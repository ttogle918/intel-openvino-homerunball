import numpy as np
from fastapi.testclient import TestClient

from conftest import FirstRng
from snackbot.brain import Brain
from snackbot.controller import Controller
from snackbot.providers import Chain, Member
from snackbot.server import create_app, mjpeg_chunk
from snackbot.stt import STT, build_stt
from test_controller import FakeSkills

INFO = {"type": "info", "target": {"name": "오란다"}, "models": {"llm": "규칙"}}


class FakeSTT:
    def __init__(self, text=None, exc=None):
        self.text, self.exc, self.got = text, exc, None

    def transcribe(self, wav):
        self.got = wav
        if self.exc:
            raise self.exc
        return self.text


def make_app(cfg, tmp_path, stt=None, frame_fn=None):
    c = Controller(cfg, Brain(cfg, rng=FirstRng()), FakeSkills())
    static = tmp_path / "static"
    static.mkdir(parents=True)
    (static / "index.html").write_text("<h1>snackbot</h1>", encoding="utf-8")
    return c, create_app(c, INFO, frame_fn=frame_fn, stt=stt, static_dir=static)


def test_ws_sends_info_state_history_then_handles_chat(cfg, tmp_path):
    c, app = make_app(cfg, tmp_path)
    c.notify("hello")
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        assert ws.receive_json() == INFO
        assert ws.receive_json()["state"] == "IDLE"
        assert ws.receive_json()["text"] == "hello"
        ws.send_json({"type": "chat", "text": "2개 옮겨줘"})
        got = [ws.receive_json() for _ in range(3)]
        assert got[0]["role"] == "user" and got[0]["text"] == "2개 옮겨줘" and got[0]["source"] == "text"
        assert got[1]["role"] == "robot"
        assert got[2]["type"] == "state" and got[2]["state"] == "WORKING"
    assert c.state == "WORKING"


def test_ws_command_estop(cfg, tmp_path):
    c, app = make_app(cfg, tmp_path)
    c.command("start")
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        for _ in range(2 + len(c.history)):
            ws.receive_json()
        ws.send_json({"type": "command", "name": "quit"})       # UI에서 quit는 무시
        ws.send_json({"type": "command", "name": "estop"})
        for _ in range(5):
            e = ws.receive_json()
            if e["type"] == "state" and e["state"] == "ESTOP":
                break
    assert c.state == "ESTOP" and not c.stopped


def test_stt_posts_voice_chat(cfg, tmp_path):
    stt = FakeSTT("과자 3개 옮겨줘")
    c, app = make_app(cfg, tmp_path, stt=stt)
    with TestClient(app) as client:
        r = client.post("/stt", content=b"RIFFdata", headers={"Content-Type": "audio/wav"})
    assert r.status_code == 200 and r.json() == {"text": "과자 3개 옮겨줘"}
    assert stt.got == b"RIFFdata"
    assert c.state == "WORKING" and c.remaining == 3
    assert c.history[0]["source"] == "voice"


def test_stt_empty_text_notifies(cfg, tmp_path):
    c, app = make_app(cfg, tmp_path, stt=FakeSTT("  "))
    with TestClient(app) as client:
        r = client.post("/stt", content=b"x")
    assert r.json() == {"text": ""}
    assert (c.history[-1]["role"], c.history[-1]["text"]) == ("system", "못 알아들었어요")
    assert c.state == "IDLE"


def test_stt_failure_and_not_configured(cfg, tmp_path):
    c, app = make_app(cfg, tmp_path, stt=FakeSTT(exc=RuntimeError("down")))
    with TestClient(app) as client:
        assert client.post("/stt", content=b"x").status_code == 502
    assert c.history[-1]["text"] == "음성 인식에 실패했어요"
    _, app2 = make_app(cfg, tmp_path / "b")
    with TestClient(app2) as client:
        assert client.post("/stt", content=b"x").status_code == 503


def test_stream_404_without_camera_and_static_index(cfg, tmp_path):
    _, app = make_app(cfg, tmp_path)
    with TestClient(app) as client:
        assert client.get("/stream/front").status_code == 404
        assert "snackbot" in client.get("/").text


def test_mjpeg_chunk_draws_boxes():
    chunk = mjpeg_chunk(np.zeros((60, 80, 3), np.uint8), [[10, 10, 30, 30]])
    assert chunk.startswith(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n\xff\xd8")
    assert chunk.endswith(b"\r\n")


class FakeWhisper:
    def transcribe(self, wav):
        return " 안녕 "


def test_stt_wrapper_and_builder():
    assert STT(Chain([Member("w", FakeWhisper())])).transcribe(b"x") == "안녕"
    assert build_stt({"chain": []}, {}, {}) is None
    assert build_stt(None, {}, {}) is None
