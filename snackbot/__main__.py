"""python -m snackbot [--dry-run] [--no-ui]

키: s 시작 · r 재개 · h 재시작(홈 복귀) · space 비상정지 · q 종료 (UI 버튼과 같은 동작)
"""
import argparse
import atexit
import collections
import logging
import os
import sys
import threading
import time
from pathlib import Path

from .brain import Brain
from .config import load_config, load_env
from .controller import Controller
from .providers import build_chain
from .stt import build_stt
from .vision import build_vision
from .voice import make_voice

KEYS = {"s": "start", "r": "resume", "h": "restart", " ": "estop", "q": "quit"}
QUIT_CHARS = (chr(3), chr(4))  # Ctrl+C, Ctrl+D
_restore_terminal = None
log = logging.getLogger(__name__)


def build(cfg, env, dry_run=True):
    if dry_run:
        from .skills import DrySkills

        skills, act = DrySkills(cfg), "dry-run"
    else:
        from .config import load_poses
        from .robot import POLICIES, RobotSkills

        # 포즈가 없으면 여기서 SystemExit (physicalai를 import하기 전). connect()는 main이 부른다.
        skills = RobotSkills(cfg, load_poses(cfg.get("poses_file", "poses.yaml")))
        act = f"ACT · OpenVINO · {cfg['skills'].get('device', 'CPU')}"
        loaded = [n for n in POLICIES if n in skills.policies]
        if len(loaded) < len(POLICIES):
            missing = [n for n in POLICIES if n not in skills.policies]
            act += f" ({'·'.join(loaded) + '만' if loaded else '정책 없음'}, {'·'.join(missing)} 모델 없음)"
        if "oranda_pickup" not in skills.policies:
            print("경고: 과자 옮기기 모델이 없어 작업 시작은 안 돼요: dori_dori·home만 확인 가능", file=sys.stderr, flush=True)
        chain = cfg["vision"].get("chain") or []
        if any(e.get("type") == "fake" for e in chain):
            log.warning("실제 로봇에서는 fake counter를 쓰지 않는다 (vision.chain에서 뺐다)")
            cfg = {**cfg, "vision": {**cfg["vision"], "chain": [e for e in chain if e.get("type") != "fake"]}}
    providers = cfg.get("providers", {})
    llm = build_chain(cfg["brain"].get("chain"), providers, env)
    vision = build_vision(cfg["vision"], providers, env, remaining_fn=lambda: skills.tray)
    stt = build_stt(cfg.get("stt"), providers, env)
    voice = make_voice(cfg, env)
    controller = Controller(cfg, Brain(cfg, chain=llm), skills, vision=vision, voice=voice,
                            log_dir=cfg.get("logging", {}).get("dir", "logs"))
    info = {"type": "info", "target": {"name": cfg["target"]["name"]}, "models": {
        "llm": llm.describe(),
        "vision": " → ".join(c.name for c in vision.counters) or "추정 (시작 개수 − 성공 수)",
        "stt": stt.chain.describe() if stt else "없음",
        "act": act,
    }}
    camera = cfg["vision"].get("camera", "front")
    return {"controller": controller, "skills": skills, "voice": voice, "stt": stt, "info": info,
            "frame_fn": lambda: skills.latest_frame(camera)}


def handle_key(ch, controller, quit_fn, submit=None, clear=None):
    """submit(name): estop 외 명령을 넘길 곳. 없으면 인라인 실행 (key_loop는 명령 워커의 submit을 넘긴다).
    clear(): 아직 시작 안 한 대기 명령을 버린다 (비상정지·종료 직전에 부른다)."""
    if ch in QUIT_CHARS:
        if clear is not None:
            clear()
        quit_fn()
        return "quit"
    name = KEYS.get(ch.lower())
    if name == "quit":
        if clear is not None:
            clear()
        quit_fn()
    elif name == "estop":
        if clear is not None:
            clear()  # 대기 중인 restart 등이 estop 뒤에 실행되어 estop을 풀면 안 된다
        controller.command(name)  # 논블로킹이라 항상 인라인, 다른 무엇보다 먼저
    elif name == "restart" and submit is not None:
        # 접수 시점의 세션 번호를 함께 넘긴다: 그 뒤에 비상정지가 끼어들면 controller가 락 안에서 거부한다
        submit(name, controller.generation())
    elif name is not None:
        if submit is None:
            controller.command(name)
        else:
            submit(name)
    return name


class CommandWorker:
    """명령(restart는 수 초 걸린다)을 키 스레드 밖에서 순서대로 실행한다.

    submit(name) 대기열에 넣기 · clear() 아직 시작 안 한 명령 버리기 · stop() 대기분 버리고 종료."""

    def __init__(self, controller):
        self._controller = controller
        self._pending = collections.deque()
        self._cond = threading.Condition()
        self._closed = False
        threading.Thread(target=self._run, name="key-commands", daemon=True).start()

    def submit(self, name, expect_gen=None):
        with self._cond:
            if self._closed:
                return
            self._pending.append((name, expect_gen))
            self._cond.notify()

    def clear(self):
        with self._cond:
            self._pending.clear()

    def stop(self):
        with self._cond:
            self._closed = True
            self._pending.clear()
            self._cond.notify()

    def _run(self):
        while True:
            with self._cond:
                while not self._pending and not self._closed:
                    self._cond.wait()
                if self._closed:
                    return
                name, expect_gen = self._pending.popleft()  # 꺼낸 뒤에 끼어든 estop은 expect_gen이 막는다
            try:
                if expect_gen is None:
                    self._controller.command(name)
                else:
                    self._controller.command(name, expect_gen=expect_gen)
            except Exception:
                log.exception("명령 실행 실패: %s", name)


def start_command_worker(controller):
    return CommandWorker(controller)


def read_windows_key(getch):
    """방향키·Insert·Delete·F키는 접두(0x00/0xe0) + 스캔코드 두 글자로 온다. 둘 다 읽고 버린다."""
    ch = getch()
    if ch in (chr(0), chr(0xE0)):
        getch()
        return None
    if ch == "\x1b":
        return None  # VT 입력 모드의 ESC [ H 같은 시퀀스: 꼬리가 키로 새지 않게 ESC 창을 연다
    return ch


def read_posix_chunk(fd):
    """fd에서 버퍼 없이 한 번 읽는다 (sys.stdin.read는 시퀀스 꼬리를 파이썬 버퍼에 숨겨 키로 새게 한다).

    ESC가 하나라도 섞인 입력은 방향키·Alt 조합 등 시퀀스일 수 있어 꼬리가 키로 오인된다.
    그런 입력에서는 space(비상정지)만 인정한다 (비상정지가 한 번 더 걸려도 안전).
    반환: (keys, had_esc). keys는 인정한 글자들, had_esc는 입력에 ESC가 있었는지.
    ESC가 든 입력은 space가 남아 있어도 had_esc=True다 (호출자가 ESC 창을 연다). EOF는 ("", False)."""
    data = os.read(fd, 32)
    if not data:
        return "", False
    text = data.decode("utf-8", errors="replace")
    if "\x1b" not in text:
        return text, False
    return " " * text.count(" "), True


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
        ch = read_windows_key(msvcrt.getwch)
        return ("", True) if ch is None else (ch, False)
    return read_posix_chunk(sys.stdin.fileno())


KEY_OFF_MSG = "콘솔 키 비활성: UI 비상정지 버튼을 쓰세요"
MAX_KEY_ERRORS = 10


ESC_WINDOW = 0.1  # ESC가 든 입력 직후 이 시간 안에 오는 입력은 시퀀스 꼬리일 수 있다


def key_loop(controller, quit_fn, clock=time.monotonic):
    try:
        enter_cbreak()
    except Exception as e:
        print(f"경고: 터미널 키 입력을 켜지 못했어요 ({e}). space 비상정지 키가 꺼져 있으니 UI 버튼을 쓰세요.",
              file=sys.stderr, flush=True)
        return
    worker = start_command_worker(controller)
    try:
        _read_keys(controller, quit_fn, worker.submit, worker.clear, clock)
    finally:
        worker.stop()


def _read_keys(controller, quit_fn, submit, clear=None, clock=time.monotonic):
    errors = 0
    last_esc = None  # 마지막으로 ESC/시퀀스를 버린 시각
    while not controller.stopped:
        try:
            result = read_key()
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
        now = clock()
        ch, had_esc = result
        if had_esc:
            last_esc = now  # ESC가 든 입력(space가 남아 있어도): 꼬리가 뒤따라 올 수 있다
            if not ch:
                continue
        elif ch == "":
            print(KEY_OFF_MSG, file=sys.stderr, flush=True)
            return  # EOF
        elif last_esc is not None and now - last_esc <= ESC_WINDOW:
            kept = " " * ch.count(" ")  # 나뉘어 들어온 시퀀스 꼬리: space만 인정
            last_esc = now
            if len(kept) != len(ch):
                log.debug("ESC 창 안의 입력을 버림: %r", ch.replace(" ", ""))
            if not kept:
                continue
            ch = kept
        for one in ch:
            if controller.stopped:
                break  # 종료 요청 뒤의 글자는 처리하지 않는다
            try:
                handle_key(one, controller, quit_fn, submit, clear)
            except Exception:
                log.exception("키 처리 실패: %r", one)


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

    if parts["stt"] is not None:  # 모델 로드·컴파일이 느리니 서버 시작을 막지 않고 미리 데운다
        threading.Thread(target=parts["stt"].warmup, name="stt-warmup", daemon=True).start()

    print("키: s 시작 · r 재개 · h 재시작 · space 비상정지 · q 종료", flush=True)
    try:
        connect = getattr(parts["skills"], "connect", None)
        if connect is not None:
            connect()  # 실제 로봇: 연결 + 정책 warmup. 실패(SystemExit)해도 finally에서 close()
        controller.start()
        if sys.stdin.isatty():
            threading.Thread(target=key_loop, args=(controller, quit_fn), name="keys", daemon=True).start()
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
