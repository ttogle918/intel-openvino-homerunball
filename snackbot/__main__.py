"""python -m snackbot [--dry-run] [--no-ui]

키: s 시작 · r 재개 · space 비상정지 · q 종료 (UI 버튼과 같은 동작)
"""
import argparse
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

KEYS = {"s": "start", "r": "resume", " ": "estop", "q": "quit"}


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
    name = KEYS.get(ch.lower())
    if name == "quit":
        quit_fn()
    elif name is not None:
        controller.command(name)
    return name


def read_key():
    if sys.platform == "win32":
        import msvcrt
        return msvcrt.getwch()
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def key_loop(controller, quit_fn):
    while not controller.stopped:
        try:
            ch = read_key()
        except (EOFError, OSError):
            return
        handle_key(ch, controller, quit_fn)


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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    root = Path(args.config).resolve().parent
    cfg = load_config(args.config)
    env = load_env(root / ".env")
    parts = build(cfg, env, dry_run=args.dry_run)
    controller = parts["controller"]
    controller.subscribe(console_printer)
    server = None

    def quit_fn():
        controller.stop()
        if server is not None:
            server.should_exit = True

    print("키: s 시작 · r 재개 · space 비상정지 · q 종료", flush=True)
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
            server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
            print(f"UI: http://{host}:{port}", flush=True)
            server.run()
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop()
        parts["skills"].close()
        parts["voice"].close()


if __name__ == "__main__":
    main()
