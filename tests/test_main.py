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


def test_build_real_robot_not_yet(cfg):
    with pytest.raises(SystemExit):
        build(cfg, {}, dry_run=False)


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
        def command(self, name):
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
    (b"\x1b[A", None),
    (b"\x1b[H", None),
    (b"\x1bOS", None),
    (b"\x1bq", None),
    (b"\x1b", None),
    (b"\x1b\x1b[H", None),
    (b"\x1b\x1bOS", None),
    (b"\x1b[\x1b[A", None),
    (b"\x1b[A ", " "),
    (b"s\x1b[Aq", None),
    (b" \x1b[H", " "),
    (b"sr", "sr"),
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
        assert read_posix_chunk(r) == ""
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
    keys = iter(["sr", None])

    def read():
        try:
            return next(keys)
        except StopIteration:
            wait_for(lambda: len(calls) == 2)  # 종료하면 대기 명령이 버려지므로 먼저 기다린다
            c.stopped = True
            return None

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

    keys = iter(["qs"])
    monkeypatch.setattr(m, "enter_cbreak", lambda: None)
    monkeypatch.setattr(m, "read_key", lambda: next(keys))
    m.key_loop(c, quit_fn)
    assert quits == [1]
    assert not wait_for(lambda: calls, timeout=0.1)


def test_key_loop_empty_string_is_eof(monkeypatch, capsys):
    import snackbot.__main__ as m
    monkeypatch.setattr(m, "enter_cbreak", lambda: None)
    monkeypatch.setattr(m, "read_key", lambda: "")
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
    keys = iter(["s", "r"])

    def fake_read():
        try:
            return next(keys)
        except StopIteration:
            c.stopped = True
            return " "

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
    import time
    import snackbot.__main__ as m
    calls = []

    class C:
        def command(self, name):
            calls.append(name)
            if name == "restart":
                time.sleep(0.3)

    c = C()
    w = m.start_command_worker(c)
    assert handle_key("h", c, lambda: None, w.submit, w.clear) == "restart"
    assert wait_for(lambda: calls == ["restart"])  # 첫 restart 실행 중
    assert handle_key("h", c, lambda: None, w.submit, w.clear) == "restart"  # 대기열
    assert handle_key(" ", c, lambda: None, w.submit, w.clear) == "estop"
    time.sleep(0.5)
    w.stop()
    assert calls == ["restart", "estop"]  # 두 번째 restart는 버려졌다


def test_quit_drops_queued_commands():
    import time
    import snackbot.__main__ as m
    calls, quits = [], []

    class C:
        def command(self, name):
            calls.append(name)
            if name == "restart":
                time.sleep(0.3)

    c = C()
    w = m.start_command_worker(c)
    handle_key("h", c, lambda: None, w.submit, w.clear)
    assert wait_for(lambda: calls == ["restart"])
    handle_key("s", c, lambda: None, w.submit, w.clear)
    assert handle_key("q", c, lambda: quits.append(1), w.submit, w.clear) == "quit"
    time.sleep(0.5)
    w.stop()
    assert calls == ["restart"] and quits == [1]  # start는 실행되지 않았다


def _loop_with(monkeypatch, chunks, times, calls, expect):
    """chunks를 차례로 key_loop에 먹이고, 명령이 expect개 기록되면 종료 (종료 시 대기 명령은 버려지므로).
    times는 각 읽기 시각."""
    import snackbot.__main__ as m

    class C:
        stopped = False

        def command(self, name):
            calls.append(name)

    c = C()
    it, tm = iter(chunks), iter(times)

    def read():
        try:
            return next(it)
        except StopIteration:
            wait_for(lambda: len(calls) >= expect)
            c.stopped = True
            return None

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
