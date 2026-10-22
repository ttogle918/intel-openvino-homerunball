"""python -m snackbot [--dry-run] [--no-ui]

키: s 시작 · r 재개 · h 재시작(홈 복귀) · space 비상정지 · q 종료 (UI 버튼과 같은 동작)
"""
import argparse
import atexit
import logging
import sys
import threading
from pathlib import Path

from .brain import Brain
from .config import load_config, load_env
from .controller import Controller
from .providers import build_chain
from .stt import build_stt
from .vision import build_vision
from .voice import Voice

KEYS = {"s": "start", "r": "resume", "h": "restart", " ": "estop", "q": "quit"}
QUIT_CHARS = (chr(3), chr(4))  # Ctrl+C, Ctrl+D
_restore_terminal = None
log = logging.getLogger(__name__)


def build(cfg, env, dry_run=True):
    if not dry_run:
        raise SystemExit("실제 로봇 연결(physicalai)은 M4 계획에서 구현합니다. 지금은 --dry-run으로 실행하세요.")
    from .skills import DrySkills

    skills = DrySkills(cfg)
    providers = cfg.get("providers", {})
    llm = build_chain(cfg["brain"].get("chain"), providers, env)
    vision = build_vision(cfg["vision"], providers, env, remaining_fn=lambda: skills.tray)
    stt = build_stt(cfg.get("stt"), providers, env)
    voice = Voice(cfg.get("voice", {}).get("engine", "none"))
    controller = Controller(cfg, Brain(cfg, chain=llm), skills, vision=vision, voice=voice,
                            log_dir=cfg.get("logging", {}).get("dir", "logs"))
    info = {"type": "info", "target": {"name": cfg["target"]["name"]}, "models": {
        "llm": llm.describe(),
        "vision": " → ".join(c.name for c in vision.counters) or "추정 (시작 개수 − 성공 수)",
        "stt": stt.chain.describe() if stt else "없음",
        "act": "dry-run",
    }}
    camera = cfg["vision"].get("camera", "front")
    return {"controller": controller, "skills": skills, "voice": voice, "stt": stt, "info": info,
            "frame_fn": lambda: skills.latest_frame(camera)}


def handle_key(ch, controller, quit_fn):
    if ch in QUIT_CHARS:
        quit_fn()
        return "quit"
    name = KEYS.get(ch.lower())
    if name == "quit":
        quit_fn()
    elif name is not None:
        controller.command(name)
    return name


def read_windows_key(getch):
    """방향키·Insert·Delete·F키는 접두(0x00/0xe0) + 스캔코드 두 글자로 온다. 둘 다 읽고 버린다."""
    ch = getch()
    if ch in (chr(0), chr(0xE0)):
        getch()
        return ""
    return ch


def _stdin_ready():
    import select
    return bool(select.select([sys.stdin], [], [], 0.05)[0])


def read_posix_key(read1, ready=None):
    """ESC로 시작하는 방향키·F키·Alt 시퀀스는 뒤따르는 입력이 있을 때만 (최대 5글자) 읽고 버린다.

    반환: 키 문자 · None(버린 시퀀스/ESC 단독) · ""(read1이 EOF)."""
    ch = read1()
    if ch != chr(27):
        return ch
    ready = ready or _stdin_ready
    for _ in range(5):
        if not ready():
            break
        if read1() == "":
            return ""
    return None


def enter_cbreak():
    """POSIX 터미널을 cbreak로 바꾸고 원래 설정을 복원하는 함수를 모듈에 보관한다."""
    global _restore_terminal
    if sys.platform == "win32" or _restore_terminal is not None:
        return
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)

    def restore():
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

    _restore_terminal = restore
    atexit.register(restore_terminal)


def restore_terminal():
    global _restore_terminal
    fn, _restore_terminal = _restore_terminal, None
    if fn is not None:
        try:
            fn()
        except Exception:
            pass


def read_key():
    if sys.platform == "win32":
        import msvcrt
        return read_windows_key(msvcrt.getwch)
    return read_posix_key(lambda: sys.stdin.read(1))


KEY_OFF_MSG = "콘솔 키 비활성: UI 비상정지 버튼을 쓰세요"
MAX_KEY_ERRORS = 10


def key_loop(controller, quit_fn):
    try:
        enter_cbreak()
    except Exception as e:
        print(f"경고: 터미널 키 입력을 켜지 못했어요 ({e}). space 비상정지 키가 꺼져 있으니 UI 버튼을 쓰세요.",
              file=sys.stderr, flush=True)
        return
    errors = 0
    while not controller.stopped:
        try:
            ch = read_key()
        except (EOFError, OSError):
            print(KEY_OFF_MSG, file=sys.stderr, flush=True)
            return
        except Exception as e:
            errors += 1
            if errors == 1:
                print(f"콘솔 키 오류: {e!r}", file=sys.stderr, flush=True)
            if errors >= MAX_KEY_ERRORS:
                print(KEY_OFF_MSG, file=sys.stderr, flush=True)
                return
            continue
        errors = 0
        if ch is None:
            continue  # 버린 방향키/F키 시퀀스
        if ch == "" and sys.platform != "win32":
            print(KEY_OFF_MSG, file=sys.stderr, flush=True)
            return  # EOF
        try:
            handle_key(ch, controller, quit_fn)
        except Exception:
            log.exception("키 처리 실패: %r", ch)


def console_printer(event):
    kind = event["type"]
    if kind == "state":
        print(f"[{event['state']}/{event['phase']}] count={event['count']} "
              f"remaining={event['remaining']} ({event['vision_method']})", flush=True)
    elif kind == "message":
        print(f"  {event['role']}: {event['text']}", flush=True)
    elif kind == "cycle":
        print(f"  cycle {event['n']}: {event['result']} {event['ms']}", flush=True)


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m snackbot")
    p.add_argument("--dry-run", action="store_true", help="로봇 없이 실행")
    p.add_argument("--no-ui", action="store_true", help="웹 UI 없이 콘솔만")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    args = p.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")  # cp949 콘솔에서 이모지 출력 오류 방지
    except (AttributeError, ValueError):
        pass
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    root = Path(args.config).resolve().parent
    cfg = load_config(args.config)
    env = load_env(root / ".env")
    parts = build(cfg, env, dry_run=args.dry_run)
    controller = parts["controller"]
    controller.subscribe(console_printer)
    server = None
    quit_requested = threading.Event()

    def quit_fn():
        quit_requested.set()
        controller.stop()
        if server is not None:
            server.should_exit = True

    print("키: s 시작 · r 재개 · h 재시작 · space 비상정지 · q 종료", flush=True)
    controller.start()
    if sys.stdin.isatty():
        threading.Thread(target=key_loop, args=(controller, quit_fn), name="keys", daemon=True).start()
    try:
        if args.no_ui:
            controller.wait_stopped()
        else:
            import uvicorn

            from .server import create_app

            srv = cfg.get("server", {})
            host, port = args.host or srv.get("host", "127.0.0.1"), args.port or srv.get("port", 8000)
            app = create_app(controller, parts["info"], frame_fn=parts["frame_fn"], stt=parts["stt"],
                             static_dir=root / "frontend")
            server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning",
                                                  timeout_graceful_shutdown=2))
            print(f"UI: http://{host}:{port}", flush=True)
            if not quit_requested.is_set():
                server.run()
    except KeyboardInterrupt:
        pass
    finally:
        restore_terminal()
        controller.stop()
        parts["skills"].close()
        parts["voice"].close()


if __name__ == "__main__":
    main()
