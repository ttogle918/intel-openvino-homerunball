import pytest

from snackbot.__main__ import build, handle_key, read_windows_key


def test_build_dry_run_parts(cfg):
    parts = build(cfg, env={}, dry_run=True)
    try:
        assert parts["controller"].state == "IDLE"
        assert parts["info"]["type"] == "info"
        assert parts["info"]["target"] == {"name": "오란다"}
        assert parts["info"]["models"]["llm"] == "규칙"
        assert parts["info"]["models"]["stt"] == "없음"
        assert parts["stt"] is None
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


def test_handle_key():
    calls, quits = [], []

    class C:
        def command(self, name):
            calls.append(name)

    quit_fn = lambda: quits.append(1)  # noqa: E731
    assert handle_key("s", C(), quit_fn) == "start"
    assert handle_key(" ", C(), quit_fn) == "estop"
    assert handle_key("R", C(), quit_fn) == "resume"
    assert handle_key("x", C(), quit_fn) is None
    assert handle_key("q", C(), quit_fn) == "quit"
    assert calls == ["start", "estop", "resume"] and quits == [1]


def _getch(*chars):
    it = iter(chars)
    return lambda: next(it)


@pytest.mark.parametrize("prefix", [chr(0), chr(0xE0)])
@pytest.mark.parametrize("code", ["R", "S"])
def test_read_windows_key_ignores_special_keys(prefix, code):
    assert read_windows_key(_getch(prefix, code)) == ""


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
    assert calls == ["restart"]


def test_read_posix_key_discards_escape_sequence():
    from snackbot.__main__ import read_posix_key
    assert read_posix_key(_getch(chr(27), "O", "R")) == ""
    assert read_posix_key(_getch("r")) == "r"


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
