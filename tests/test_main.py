import pytest

from snackbot.__main__ import build, handle_key, read_windows_key


def test_build_dry_run_parts(cfg):
    parts = build(cfg, env={}, dry_run=True)
    try:
        assert parts["controller"].state == "IDLE"
        assert parts["info"]["type"] == "info"
        assert parts["info"]["target"] == {"name": "오란다"}
        assert parts["info"]["models"]["llm"] == "규칙"
        assert parts["info"]["models"]["stt"] == "Whisper small · OpenVINO · CPU"  # 키 없으면 gemini는 빠진다
        assert parts["stt"] is not None  # 모델은 warmup/첫 요청 때 로드되므로 build는 가볍다
        assert parts["frame_fn"]().shape == (480, 640, 3)
    finally:
        parts["voice"].close()


def test_build_with_fake_counter_reports_vision(cfg):
    cfg["vision"]["chain"] = [{"type": "fake"}]
    parts = build(cfg, env={}, dry_run=True)
    try:
        assert parts["info"]["models"]["vision"] == "fake"
        assert parts["controller"].vision is not None
    finally:
        parts["voice"].close()


def test_build_real_robot_requires_poses(cfg, tmp_path):
    cfg["poses_file"] = str(tmp_path / "none.yaml")
    import sys
    with pytest.raises(SystemExit, match="home_pose"):
        build(cfg, {}, dry_run=False)
    assert "physicalai" not in sys.modules


@pytest.fixture
def real_cfg(cfg, tmp_path, monkeypatch):
    """physicalai 없이 build(dry_run=False)가 돌도록 런타임·정책 로드를 가짜로 바꾼 cfg."""
    import snackbot.robot as robot
    from snackbot.config import save_pose

    poses = tmp_path / "poses.yaml"
    save_pose(poses, "home_pose", [0] * 6)
    save_pose(poses, "lift_pose", [0] * 6)
    cfg["poses_file"] = str(poses)
    cfg["skills"]["gripper"].update(closed_below=30, open_above=60, grasp_min=15)
    monkeypatch.setattr(robot, "build_runtime", lambda c, s, t: object())
    monkeypatch.setattr(robot, "build_policies", lambda c: ({}, {}))
    return cfg


def test_build_real_robot_drops_fake_counter(real_cfg):
    real_cfg["vision"]["chain"] = [{"type": "fake"}]
    parts = build(real_cfg, {}, dry_run=False)
    try:
        assert parts["controller"].vision is None
        assert parts["info"]["models"]["act"].startswith("ACT · OpenVINO")
    finally:
        parts["voice"].close()


def test_build_real_robot_act_info_lists_loaded_policies(real_cfg, monkeypatch, capsys):
    import snackbot.robot as robot
    monkeypatch.setattr(robot, "build_policies", lambda c: ({"dori_dori": object()}, {}))
    real_cfg["skills"]["device"] = "GPU"
    parts = build(real_cfg, {}, dry_run=False)
    try:
        assert parts["info"]["models"]["act"] == "ACT · OpenVINO · GPU (dori_dori만, oranda_pickup 모델 없음)"
        assert "작업 시작은 안 돼요" in capsys.readouterr().err
    finally:
        parts["voice"].close()


def test_build_real_robot_all_policies_plain_act_info(real_cfg, monkeypatch, capsys):
    import snackbot.robot as robot
    monkeypatch.setattr(robot, "build_policies",
                        lambda c: ({"oranda_pickup": object(), "dori_dori": object()}, {}))
    real_cfg["skills"]["device"] = "GPU"
    parts = build(real_cfg, {}, dry_run=False)
    try:
        assert parts["info"]["models"]["act"] == "ACT · OpenVINO · GPU"
        assert "작업 시작은 안 돼요" not in capsys.readouterr().err
    finally:
        parts["voice"].close()


class _FakeController:
    stopped = False

    def __init__(self, events):
        self.events = events

    def subscribe(self, fn):
        pass

    def start(self):
        self.events.append("start")

    def stop(self):
        self.events.append("controller.stop")

    def wait_stopped(self):
        pass


def _patch_main(monkeypatch, events, connect):
    import snackbot.__main__ as m

    class Skills:
        def close(self):
            events.append("close")

    skills = Skills()
    skills.connect = connect
    voice = type("V", (), {"close": lambda self: events.append("voice.close")})()
    parts = {"controller": _FakeController(events), "skills": skills, "voice": voice, "stt": None,
             "info": {}, "frame_fn": lambda: None}
    monkeypatch.setattr(m, "build", lambda cfg, env, dry_run=True: parts)
    monkeypatch.setattr(m, "load_config", lambda path: {})
    monkeypatch.setattr(m, "load_env", lambda path: {})


def test_main_connects_before_controller_start(monkeypatch):
    import snackbot.__main__ as m
    events = []
    _patch_main(monkeypatch, events, lambda: events.append("connect"))
    m.main(["--no-ui"])
    assert events.index("connect") < events.index("start")
    assert "close" in events and "voice.close" in events


def test_main_connect_failure_still_closes_and_exits(monkeypatch):
    import snackbot.__main__ as m
    events = []

    def bad():
        events.append("connect")
        raise SystemExit("정책 dori_dori 입력이 안 맞아요")

    _patch_main(monkeypatch, events, bad)
    with pytest.raises(SystemExit, match="입력이 안 맞아요"):
        m.main(["--no-ui"])
    assert "start" not in events
    assert events.count("close") == 1 and "controller.stop" in events and "voice.close" in events


def test_main_connect_ctrl_c_still_closes(monkeypatch):
    import snackbot.__main__ as m
    events = []

    def interrupted():
        raise KeyboardInterrupt

    _patch_main(monkeypatch, events, interrupted)
    m.main(["--no-ui"])
    assert events.count("close") == 1 and "controller.stop" in events and "voice.close" in events


def test_main_cleanup_continues_when_one_step_fails(monkeypatch):
    import snackbot.__main__ as m
    events = []
    _patch_main(monkeypatch, events, lambda: None)

    def bad_close():
        raise RuntimeError("boom")

    parts = m.build(None, None)
    parts["skills"].close = bad_close
    m.main(["--no-ui"])
    assert "voice.close" in events


def test_build_real_robot_no_policies_warning(real_cfg, capsys):
    parts = build(real_cfg, {}, dry_run=False)
    try:
        assert "정책 모델이 없어요" in capsys.readouterr().err
    finally:
        parts["voice"].close()


def test_flush_input_never_raises(monkeypatch):
    import snackbot.__main__ as m
    monkeypatch.setattr(m.sys, "platform", "linux")
    monkeypatch.setattr(m.sys, "stdin", None)
    m.flush_input()


def wait_for(cond, timeout=2.0):
    import time
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.005)
    return cond()


def test_handle_key():
    calls, quits = [], []

    class C:
        def command(self, name):
            calls.append(name)

    quit_fn = lambda: quits.append(1)  # noqa: E731
    assert handle_key("s", C(), quit_fn) == "start"
    assert wait_for(lambda: calls == ["start"])
    assert handle_key(" ", C(), quit_fn) == "estop"
    assert calls == ["start", "estop"]  # estop은 인라인
    assert handle_key("R", C(), quit_fn) == "resume"
    assert wait_for(lambda: len(calls) == 3)
    assert handle_key("x", C(), quit_fn) is None
    assert handle_key("q", C(), quit_fn) == "quit"
    assert calls == ["start", "estop", "resume"] and quits == [1]


def _getch(*chars):
    it = iter(chars)
    return lambda: next(it)


@pytest.mark.parametrize("prefix", [chr(0), chr(0xE0)])
@pytest.mark.parametrize("code", ["R", "S"])
def test_read_windows_key_ignores_special_keys(prefix, code):
    assert read_windows_key(_getch(prefix, code)) is None


def test_read_windows_key_plain():
    assert read_windows_key(_getch("s")) == "s"


@pytest.mark.parametrize("ch", [chr(3), chr(4)])
def test_handle_key_ctrl_c_d_quit(ch):
    quits = []

    class C:
        def command(self, name):
            raise AssertionError(name)

    assert handle_key(ch, C(), lambda: quits.append(1)) == "quit"
    assert quits == [1]


def test_handle_key_empty_is_noop():
    assert handle_key("", object(), lambda: None) is None


def test_handle_key_h_restarts():
    calls = []

    class C:
        def command(self, name):
            calls.append(name)

    assert handle_key("h", C(), lambda: None) == "restart"
    assert wait_for(lambda: calls == ["restart"])


def test_command_worker_runs_commands_in_order():
    import queue
    import snackbot.__main__ as m
    calls, done = [], queue.Queue()

    class C:
        def command(self, name):
            calls.append(name)
            done.put(name)

    worker = m.start_command_worker(C())
    quit_fn = lambda: None  # noqa: E731
    assert handle_key("s", C(), quit_fn, worker.submit) == "start"
    assert handle_key("r", C(), quit_fn, worker.submit) == "resume"
    assert done.get(timeout=2) == "start" and done.get(timeout=2) == "resume"
    worker.stop()
    assert calls == ["start", "resume"]


def test_slow_restart_does_not_delay_estop():
    import time
    import snackbot.__main__ as m
    calls, done = [], []

    class C:
        def generation(self):
            return 0

        def command(self, name, expect_gen=None):
            calls.append(name)
            if name == "restart":
                time.sleep(0.5)
                done.append(1)

    c = C()
    worker = m.start_command_worker(c)
    submit = worker.submit
    t0 = time.monotonic()
    assert handle_key("h", c, lambda: None, submit) == "restart"
    assert time.monotonic() - t0 < 0.1
    assert handle_key(" ", c, lambda: None, submit) == "estop"
    assert "estop" in calls and not done  # 재시작이 끝나기 전에 estop 기록
    assert wait_for(lambda: done)
    worker.stop()


def test_command_worker_logs_error_and_continues(caplog):
    import snackbot.__main__ as m
    calls = []

    class C:
        def command(self, name):
            calls.append(name)
            if name == "start":
                raise RuntimeError("boom")

    worker = m.start_command_worker(C())
    with caplog.at_level("ERROR"):
        worker.submit("start")
        worker.submit("resume")
        assert wait_for(lambda: calls == ["start", "resume"])
        assert "boom" in caplog.text
    worker.stop()


def _pipe_with(data):
    import os
    r, w = os.pipe()
    os.write(w, data)
    return r, w


def _close(*fds):
    import os
    for fd in fds:
        try:
            os.close(fd)
        except OSError:
            pass


@pytest.mark.parametrize("data,expected", [
    (b"\x1b[A", ("", True)),
    (b"\x1b[H", ("", True)),
    (b"\x1bOS", ("", True)),
    (b"\x1bq", ("", True)),
    (b"\x1b", ("", True)),
    (b"\x1b\x1b[H", ("", True)),
    (b"\x1b\x1bOS", ("", True)),
    (b"\x1b[\x1b[A", ("", True)),
    (b"\x1b[A ", (" ", True)),
    (b"s\x1b[Aq", ("", True)),
    (b" \x1b[H", (" ", True)),
    (b"sr", ("sr", False)),
    (b" \x1b", (" ", True)),
])
def test_read_posix_chunk(data, expected):
    from snackbot.__main__ import read_posix_chunk
    r, w = _pipe_with(data)
    try:
        assert read_posix_chunk(r) == expected
    finally:
        _close(r, w)


def test_read_posix_chunk_eof():
    import os
    from snackbot.__main__ import read_posix_chunk
    r, w = os.pipe()
    os.close(w)
    try:
        assert read_posix_chunk(r) == ("", False)
    finally:
        _close(r, w)


def test_key_loop_escape_tails_never_become_commands(monkeypatch):
    import itertools
    import os
    import snackbot.__main__ as m
    calls, quits = [], []

    class C:
        stopped = False

        def command(self, name):
            calls.append(name)

    c = C()

    def quit_fn():
        quits.append(1)
        c.stopped = True

    r, w = os.pipe()
    chunks = iter([b"\x1b[H", b"\x1bOS", b" ", b"q"])

    def read_key():
        os.write(w, next(chunks))
        return m.read_posix_chunk(r)

    monkeypatch.setattr(m.sys, "platform", "linux")
    monkeypatch.setattr(m, "enter_cbreak", lambda: None)
    monkeypatch.setattr(m, "read_key", read_key)
    try:
        m.key_loop(c, quit_fn, clock=itertools.count(0, 10).__next__)  # 읽기마다 10초: 창 밖
    finally:
        _close(r, w)
    assert calls == ["estop"] and quits == [1]


def test_key_loop_handles_every_char_of_a_chunk(monkeypatch):
    import snackbot.__main__ as m
    calls = []

    class C:
        stopped = False

        def command(self, name):
            calls.append(name)

    c = C()
    keys = iter([("sr", False), ("", True)])

    def read():
        try:
            return next(keys)
        except StopIteration:
            wait_for(lambda: len(calls) == 2)  # 종료하면 대기 명령이 버려지므로 먼저 기다린다
            c.stopped = True
            return "", True

    monkeypatch.setattr(m, "enter_cbreak", lambda: None)
    monkeypatch.setattr(m, "read_key", read)
    m.key_loop(c, lambda: None)
    assert calls == ["start", "resume"]


def test_key_loop_ignores_chars_after_quit(monkeypatch):
    import snackbot.__main__ as m
    calls, quits = [], []

    class C:
        stopped = False

        def command(self, name):
            calls.append(name)

    c = C()

    def quit_fn():
        quits.append(1)
        c.stopped = True

    keys = iter([("qs", False)])
    monkeypatch.setattr(m, "enter_cbreak", lambda: None)
    monkeypatch.setattr(m, "read_key", lambda: next(keys))
    m.key_loop(c, quit_fn)
    assert quits == [1]
    assert not wait_for(lambda: calls, timeout=0.1)


def test_key_loop_empty_string_is_eof(monkeypatch, capsys):
    import snackbot.__main__ as m
    monkeypatch.setattr(m, "enter_cbreak", lambda: None)
    monkeypatch.setattr(m, "read_key", lambda: ("", False))
    m.key_loop(type("C", (), {"stopped": False})(), lambda: None)
    assert "콘솔 키 비활성" in capsys.readouterr().err


def test_key_loop_stops_after_repeated_errors(monkeypatch, capsys):
    import snackbot.__main__ as m
    n = []

    def bad():
        n.append(1)
        raise ValueError("x")

    monkeypatch.setattr(m, "enter_cbreak", lambda: None)
    monkeypatch.setattr(m, "read_key", bad)
    m.key_loop(type("C", (), {"stopped": False})(), lambda: None)
    err = capsys.readouterr().err
    assert len(n) == 10 and "콘솔 키 오류" in err and "콘솔 키 비활성" in err


def test_key_loop_eof_warns(monkeypatch, capsys):
    import snackbot.__main__ as m

    def eof():
        raise EOFError

    monkeypatch.setattr(m, "enter_cbreak", lambda: None)
    monkeypatch.setattr(m, "read_key", eof)
    m.key_loop(type("C", (), {"stopped": False})(), lambda: None)
    assert "콘솔 키 비활성" in capsys.readouterr().err


def test_key_loop_survives_handler_error(monkeypatch):
    import snackbot.__main__ as m

    class C:
        stopped = False

        def command(self, name):
            raise RuntimeError("boom")

    c = C()
    keys = iter([("s", False), ("r", False)])

    def fake_read():
        try:
            return next(keys)
        except StopIteration:
            c.stopped = True
            return " ", False

    monkeypatch.setattr(m, "enter_cbreak", lambda: None)
    monkeypatch.setattr(m, "read_key", fake_read)
    m.key_loop(c, lambda: None)      # 예외 없이 끝나야 한다
    assert c.stopped


def test_key_loop_warns_when_cbreak_fails(monkeypatch, capsys):
    import snackbot.__main__ as m

    def bad():
        raise OSError("no tty")

    monkeypatch.setattr(m, "enter_cbreak", bad)
    m.key_loop(type("C", (), {"stopped": False})(), lambda: None)
    assert "비상정지" in capsys.readouterr().err


def test_estop_drops_queued_commands():
    import threading
    import snackbot.__main__ as m
    calls = []
    started, release = threading.Event(), threading.Event()

    class C:
        def generation(self):
            return 0

        def command(self, name, expect_gen=None):
            calls.append(name)
            if name == "restart":
                started.set()
                release.wait(5)

    c = C()
    w = m.start_command_worker(c)
    assert handle_key("h", c, lambda: None, w.submit, w.clear) == "restart"
    assert started.wait(2)  # 첫 restart 실행 중
    assert handle_key("h", c, lambda: None, w.submit, w.clear) == "restart"  # 대기열
    assert handle_key(" ", c, lambda: None, w.submit, w.clear) == "estop"
    release.set()
    w.stop()
    assert calls == ["restart", "estop"]  # 두 번째 restart는 버려졌다


def test_quit_drops_queued_commands():
    import threading
    import snackbot.__main__ as m
    calls, quits = [], []
    started, release = threading.Event(), threading.Event()

    class C:
        def generation(self):
            return 0

        def command(self, name, expect_gen=None):
            calls.append(name)
            if name == "restart":
                started.set()
                release.wait(5)

    c = C()
    w = m.start_command_worker(c)
    handle_key("h", c, lambda: None, w.submit, w.clear)
    assert started.wait(2)
    handle_key("s", c, lambda: None, w.submit, w.clear)
    assert handle_key("q", c, lambda: quits.append(1), w.submit, w.clear) == "quit"
    release.set()
    w.stop()
    assert calls == ["restart"] and quits == [1]  # start는 실행되지 않았다


def test_restart_passes_generation_taken_at_submit():
    import snackbot.__main__ as m
    seen = []

    class C:
        def generation(self):
            return 7

        def command(self, name, expect_gen=None):
            seen.append((name, expect_gen))

    c = C()
    w = m.start_command_worker(c)
    handle_key("h", c, lambda: None, w.submit, w.clear)
    handle_key("s", c, lambda: None, w.submit, w.clear)
    assert wait_for(lambda: len(seen) == 2)
    w.stop()
    assert seen == [("restart", 7), ("start", None)]


def test_estop_between_worker_pop_and_controller_does_not_release_estop(cfg):
    """워커가 restart를 꺼낸 뒤 controller 진입 전에 estop이 끼어들어도 estop은 풀리지 않는다."""
    import threading
    import snackbot.__main__ as m
    from snackbot.controller import ESTOP

    parts = build(cfg, env={}, dry_run=True)
    controller = parts["controller"]
    try:
        controller.command("estop")
        popped, go, finished = threading.Event(), threading.Event(), threading.Event()

        class Gate:
            """restart만 워커와 controller 사이에서 멈춰 estop이 끼어들 틈을 결정적으로 만든다."""
            generation = staticmethod(controller.generation)

            def command(self, name, expect_gen=None):
                if name != "restart":
                    return controller.command(name)
                popped.set()
                assert go.wait(5)
                try:
                    controller.command(name, expect_gen=expect_gen)
                finally:
                    finished.set()

        gate = Gate()
        w = m.start_command_worker(gate)
        assert handle_key("h", gate, lambda: None, w.submit, w.clear) == "restart"
        assert popped.wait(2)  # 워커가 restart를 이미 꺼냈다: clear()는 비울 게 없다
        assert handle_key(" ", gate, lambda: None, w.submit, w.clear) == "estop"
        go.set()
        assert finished.wait(5)
        w.stop()
        assert controller.state == ESTOP and controller.phase == "idle"
    finally:
        parts["voice"].close()


def _loop_with(monkeypatch, chunks, times, calls, expect):
    """chunks를 차례로 key_loop에 먹이고, 명령이 expect개 기록되면 종료 (종료 시 대기 명령은 버려지므로).
    times는 각 읽기 시각."""
    import snackbot.__main__ as m

    class C:
        stopped = False

        def generation(self):
            return 0

        def command(self, name, expect_gen=None):
            calls.append(name)

    c = C()
    # 테스트 표기: None = ESC만 든 입력, 문자열 = 일반 입력, (keys, True) = ESC가 든 입력
    it = iter([(c_, False) if isinstance(c_, str) else ("", True) if c_ is None else c_ for c_ in chunks])
    tm = iter(times)

    def read():
        try:
            return next(it)
        except StopIteration:
            wait_for(lambda: len(calls) >= expect)
            c.stopped = True
            return "", True

    monkeypatch.setattr(m, "enter_cbreak", lambda: None)
    monkeypatch.setattr(m, "read_key", read)
    m.key_loop(c, lambda: None, clock=lambda: next(tm, 99.0))


def test_key_loop_split_escape_tail_within_window_is_ignored(monkeypatch):
    calls = []
    # ESC만 담긴 입력(None) 직후 30ms 뒤에 "[H"가 오면 꼬리다. "H"는 창 밖이라 일반 키.
    _loop_with(monkeypatch, [None, "[H", None, "H"], [1.0, 1.03, 5.0, 5.5, 9.0], calls, 1)
    assert calls == ["restart"]


def test_key_loop_split_escape_tail_keeps_space(monkeypatch):
    calls = []
    _loop_with(monkeypatch, [None, "[ H"], [1.0, 1.03, 9.0], calls, 1)
    assert calls == ["estop"]


def test_key_loop_chunks_run_in_order_through_worker(monkeypatch):
    calls = []
    _loop_with(monkeypatch, ["s", "r", "h"], [1.0, 2.0, 3.0, 9.0], calls, 3)
    assert calls == ["start", "resume", "restart"]


def _read_keys_recorded(monkeypatch, chunks, times):
    """_read_keys를 직접 돌려 estop(인라인)과 워커로 가는 submit을 순서대로 기록한다.
    워커를 거치지 않으므로 종료 때 대기 명령이 버려져 결과가 가려지는 일이 없다."""
    import snackbot.__main__ as m
    calls = []

    class C:
        stopped = False

        def generation(self):
            return 0

        def command(self, name, expect_gen=None):
            calls.append(name)

    it, tm = iter(chunks), iter(times)
    monkeypatch.setattr(m, "read_key", lambda: next(it, ("", False)))  # 다 읽으면 EOF로 끝
    m._read_keys(C(), lambda: None, lambda n, *a: calls.append(n), lambda: None,
                 clock=lambda: next(tm, 99.0))
    return calls


def test_key_loop_space_with_esc_in_same_read_opens_window(monkeypatch, capsys):
    # space + ESC 읽기 직후 10ms 뒤에 "[H"가 오면 꼬리다: restart가 submit되면 안 된다.
    calls = _read_keys_recorded(monkeypatch, [(" ", True), ("[H", False)], [1.0, 1.01])
    assert calls == ["estop"]


def test_key_loop_window_after_space_with_esc_still_allows_space(monkeypatch, capsys):
    calls = _read_keys_recorded(monkeypatch, [(" ", True), ("[ H", False)], [1.0, 1.01])
    assert calls == ["estop", "estop"]


def test_key_loop_real_posix_chunks_space_esc_then_tail(monkeypatch, capsys):
    import os
    import snackbot.__main__ as m
    r, w = os.pipe()
    chunks = iter([b" \x1b", b"[H"])

    def read_key():
        try:
            os.write(w, next(chunks))
        except StopIteration:
            return "", False
        return m.read_posix_chunk(r)

    try:
        monkeypatch.setattr(m, "read_key", read_key)
        calls = []

        class C:
            stopped = False

            def generation(self):
                return 0

            def command(self, name, expect_gen=None):
                calls.append(name)

        times = iter([1.0, 1.01])
        m._read_keys(C(), lambda: None, lambda n, *a: calls.append(n), lambda: None,
                     clock=lambda: next(times, 99.0))
    finally:
        _close(r, w)
    assert calls == ["estop"]


def test_read_windows_key_escape_returns_none():
    assert read_windows_key(_getch("\x1b")) is None


def test_key_loop_logs_keys_dropped_in_esc_window(monkeypatch, caplog, capsys):
    with caplog.at_level("DEBUG", logger="snackbot.__main__"):
        calls = _read_keys_recorded(monkeypatch, [("", True), ("q", False), (" ", True)], [1.0, 1.02, 1.04])
    assert calls == ["estop"]
    assert "ESC 창" in caplog.text


def test_build_dry_run_twin_info_and_parts(cfg, tmp_path):
    cfg["robot"]["calibration"] = str(tmp_path / "none.yaml")
    parts = build(cfg, env={}, dry_run=True)
    try:
        info = parts["info"]
        assert [t["kind"] for t in info["ui"]["tiles"]] == ["camera", "camera", "camera", "twin"]
        assert info["twin"] == {"mode": "replay", "urdf": "twin/so101/so101_new_calib.urdf"}
        assert info["replays"] == []
        assert parts["joints_fn"] is None and parts["joints_hz"] == 15.0
        assert parts["cameras"] == ["tower cam", "side cam", "follow cam"] and parts["box_camera"] == "tower cam"
        assert parts["frame_fn"]("side cam").shape == (480, 640, 3)
        assert parts["convert"]([0] * 6)[0] == 0
        assert parts["replays_dir"] == cfg["replays_dir"]
    finally:
        parts["voice"].close()


def test_build_real_robot_twin_live(real_cfg):
    parts = build(real_cfg, {}, dry_run=False)
    try:
        assert parts["info"]["twin"]["mode"] == "live"
        assert parts["joints_fn"] == parts["skills"].latest_joints
    finally:
        parts["voice"].close()


def test_main_passes_twin_parts_to_create_app(monkeypatch):
    import uvicorn

    import snackbot.__main__ as m
    import snackbot.server as server

    events = []
    _patch_main(monkeypatch, events, lambda: None)
    parts = m.build(None, None)
    parts.update(cameras=["tower cam"], box_camera="tower cam", joints_fn=lambda: None, joints_hz=20.0,
                 convert=str, replays_dir="replays")
    seen = {}

    def fake_create_app(controller, info, **kw):
        seen.update(kw)
        return "app"

    class FakeServer:
        should_exit = False

        def __init__(self, config):
            pass

        def run(self):
            events.append("served")

    monkeypatch.setattr(server, "create_app", fake_create_app)
    monkeypatch.setattr(uvicorn, "Config", lambda app, **kw: app)
    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    m.main([])
    assert "served" in events
    assert seen["cameras"] == ["tower cam"] and seen["box_camera"] == "tower cam"
    assert seen["joints_fn"] is parts["joints_fn"] and seen["joints_hz"] == 20.0
    assert seen["convert"] is str and seen["replays_dir"] == "replays"


@pytest.mark.parametrize("raw,expected", [(0, 15.0), (None, 15.0), (-5, 1.0), (0.2, 1.0), (30, 30.0)])
def test_build_twin_rate_hz_is_clamped(cfg, raw, expected):
    cfg["twin"] = {**(cfg.get("twin") or {}), "rate_hz": raw}
    parts = build(cfg, env={}, dry_run=True)
    try:
        assert parts["joints_hz"] == expected
    finally:
        parts["voice"].close()


def test_build_dry_run_info_tests_all_enabled(cfg):
    parts = build(cfg, env={}, dry_run=True)
    try:
        assert parts["info"]["tests"] == [
            {"skill": "oranda_pickup", "label": "오란다 1회", "enabled": True, "reason": ""},
            {"skill": "dori_dori", "label": "도리도리 1회", "enabled": True, "reason": ""},
            {"skill": "home", "label": "홈으로", "enabled": True, "reason": ""}]
    finally:
        parts["voice"].close()


def test_build_real_robot_without_models_uses_scripted_dori(real_cfg, capsys):
    real_cfg["skills"]["device"] = "GPU"
    parts = build(real_cfg, {}, dry_run=False)
    try:
        info = parts["info"]
        assert info["models"]["act"] == "ACT · OpenVINO · GPU (정책 없음, oranda_pickup 모델 없음) · 도리도리: 코드 동작"
        assert [(t["skill"], t["enabled"], t["reason"]) for t in info["tests"]] == [
            ("oranda_pickup", False, "모델 없음"), ("dori_dori", True, ""), ("home", True, "")]
        assert "코드 도리도리·home만" in capsys.readouterr().err
    finally:
        parts["voice"].close()


def test_build_real_robot_oranda_with_scripted_dori_act_info(real_cfg, monkeypatch):
    import snackbot.robot as robot
    monkeypatch.setattr(robot, "build_policies", lambda c: ({"oranda_pickup": object()}, {}))
    real_cfg["skills"]["device"] = "GPU"
    parts = build(real_cfg, {}, dry_run=False)
    try:
        assert parts["info"]["models"]["act"] == "ACT · OpenVINO · GPU (oranda_pickup) · 도리도리: 코드 동작"
        assert all(t["enabled"] for t in parts["info"]["tests"])
    finally:
        parts["voice"].close()
