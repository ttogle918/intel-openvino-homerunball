import json
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from conftest import FirstRng
from snackbot.brain import Brain
from snackbot.controller import Controller
from snackbot.providers import Chain, Member
from snackbot.server import create_app, mjpeg_chunk
from snackbot.stt import STT, build_stt
from snackbot.twin import to_radians
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


def make_app(cfg, tmp_path, stt=None, frame_fn=None, **kw):
    c = Controller(cfg, Brain(cfg, rng=FirstRng()), FakeSkills())
    static = tmp_path / "static"
    static.mkdir(parents=True)
    (static / "index.html").write_text("<h1>snackbot</h1>", encoding="utf-8")
    return c, create_app(c, INFO, frame_fn=frame_fn, stt=stt, static_dir=static, **kw)


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


def test_ws_receives_event_from_other_thread(cfg, tmp_path):
    import threading
    c, app = make_app(cfg, tmp_path)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        assert ws.receive_json() == INFO
        assert ws.receive_json()["type"] == "state"
        threading.Thread(target=c.notify, args=("hi",)).start()
        e = ws.receive_json()
        assert e["type"] == "message" and e["text"] == "hi"


def test_ws_history_message_delivered_once(cfg, tmp_path):
    c, app = make_app(cfg, tmp_path)
    c.notify("old")
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        c._emit(c.history[-1])          # 이미 history에 담긴 메시지를 큐로 다시 흘려보낸다
        assert ws.receive_json() == INFO
        assert ws.receive_json()["type"] == "state"
        assert ws.receive_json()["text"] == "old"
        ws.send_json({"type": "chat", "text": "2개 옮겨줘"})
        got = [ws.receive_json() for _ in range(3)]
        assert got[0]["role"] == "user" and got[1]["role"] == "robot"
        assert got[2]["type"] == "state"
        assert all(g.get("text") != "old" for g in got)


def test_ws_closes_when_send_fails(cfg, tmp_path, monkeypatch):
    from starlette.websockets import WebSocket, WebSocketDisconnect
    real, calls = WebSocket.send_json, {"n": 0}

    async def flaky(self, data, *a, **kw):
        calls["n"] += 1
        if calls["n"] > 2:              # info, state까지만 성공
            raise RuntimeError("send blocked")
        return await real(self, data, *a, **kw)

    monkeypatch.setattr(WebSocket, "send_json", flaky)
    c, app = make_app(cfg, tmp_path)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        assert ws.receive_json() == INFO
        assert ws.receive_json()["type"] == "state"
        c.notify("x")
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_ws_survives_malformed_frames(cfg, tmp_path):
    c, app = make_app(cfg, tmp_path)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json(), ws.receive_json()
        ws.send_text("not json")
        ws.send_json([1, 2])
        ws.send_json({"type": "chat", "text": "2개 옮겨줘"})
        got = [ws.receive_json() for _ in range(3)]
        assert got[0]["role"] == "user" and got[1]["role"] == "robot"
        assert got[2]["type"] == "state"


def test_estop_not_delayed_by_slow_chat(cfg, tmp_path, monkeypatch):
    import time
    c, app = make_app(cfg, tmp_path)
    monkeypatch.setattr(c, "chat", lambda text, source="text": time.sleep(1.5))
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json(), ws.receive_json()
        t0 = time.monotonic()
        ws.send_json({"type": "chat", "text": "느린 질문"})
        ws.send_json({"type": "command", "name": "estop"})
        while c.state != "ESTOP" and time.monotonic() - t0 < 1.2:
            time.sleep(0.01)
        assert c.state == "ESTOP"
        assert time.monotonic() - t0 < 0.5


def test_commands_processed_in_order_per_connection(cfg, tmp_path, monkeypatch):
    import time
    c, app = make_app(cfg, tmp_path)
    order = []

    def slow_restart(expect_gen=None):
        time.sleep(0.3)
        order.append("restart")

    monkeypatch.setattr(c, "_restart", slow_restart)
    monkeypatch.setattr(c, "chat", lambda text, source="text": order.append("chat"))
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json(), ws.receive_json()
        ws.send_json({"type": "command", "name": "restart"})
        ws.send_json({"type": "chat", "text": "안녕"})
        deadline = time.monotonic() + 3
        while len(order) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
    assert order == ["restart", "chat"]


class _Abort(BaseException):
    pass


def test_stream_stops_when_controller_stopped(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr("snackbot.server.STREAM_INTERVAL_S", 0.001)
    calls = {"n": 0}
    holder = {}

    def frame_fn():
        calls["n"] += 1
        if calls["n"] == 3:
            holder["c"].stop()
        if calls["n"] > 50:
            raise _Abort()          # 수정 전에는 무한 루프 → 테스트가 멈추지 않게 중단
        return np.zeros((10, 10, 3), np.uint8)

    c, app = make_app(cfg, tmp_path, frame_fn=frame_fn)
    holder["c"] = c
    with TestClient(app) as client:
        r = client.get("/stream/front")
    assert r.status_code == 200 and calls["n"] <= 5


def test_ws_restart_carries_generation_seen_on_receipt(cfg, tmp_path, monkeypatch):
    import threading
    c, app = make_app(cfg, tmp_path)
    c.command("estop")
    gate, got, done = threading.Event(), threading.Event(), threading.Event()
    results = []
    orig_gen, orig_restart = c.generation, c._restart

    def generation():
        g = orig_gen()
        got.set()
        return g

    def restart(expect_gen=None):
        results.append(orig_restart(expect_gen))
        done.set()
        return results[-1]

    monkeypatch.setattr(c, "generation", generation)
    monkeypatch.setattr(c, "_restart", restart)
    monkeypatch.setattr(c, "chat", lambda text, source="text": gate.wait(5))  # 워커를 붙잡아 restart를 큐에 쌓는다
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json(), ws.receive_json()
        ws.send_json({"type": "chat", "text": "붙잡기"})
        ws.send_json({"type": "command", "name": "restart"})
        assert got.wait(5)          # 서버가 restart를 접수하고 세션 번호를 읽었다
        c.command("estop")          # 접수 뒤에 다시 비상정지가 끼어든다
        gate.set()
        assert done.wait(5)
    assert results == [False]
    assert c.state == "ESTOP" and c.skills.estopped and c.skills.homed == 0


def test_stream_camera_by_name_and_404_for_unknown(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr("snackbot.server.STREAM_INTERVAL_S", 0.001)
    seen, holder = [], {}

    def frame_fn(cam=None):
        seen.append(cam)
        if len(seen) == 3:
            holder["c"].stop()
        if len(seen) > 50:
            raise _Abort()
        return np.zeros((10, 10, 3), np.uint8)

    c, app = make_app(cfg, tmp_path, frame_fn=frame_fn, cameras=["side cam"])
    holder["c"] = c
    with TestClient(app) as client:
        assert client.get("/stream/nope").status_code == 404
        r = client.get("/stream/side%20cam")
    assert r.status_code == 200 and r.content.startswith(b"--frame")
    assert set(seen) == {"side cam"}


def write_replay(root, skill="dori_dori"):
    folder = root / skill
    (folder / "frames" / "follow_cam").mkdir(parents=True)
    (folder / "tower_cam.mp4").write_bytes(b"video")
    (folder / "frames" / "follow_cam" / "000000.jpg").write_bytes(b"jpg")
    (folder / "episode.json").write_text(json.dumps({
        "skill": skill, "source": "studio", "fps": 2, "joints": [[0] * 6, [100, 0, 0, 0, 0, 50]],
        "cameras": {"tower cam": {"video": "tower_cam.mp4", "start": 1.0, "end": 2.0},
                    "follow cam": {"frames": "frames/follow_cam", "fps": 1, "count": 1}}}), encoding="utf-8")


def test_replay_api_and_static_files(cfg, tmp_path):
    replays = tmp_path / "replays"
    write_replay(replays)
    _, app = make_app(cfg, tmp_path, replays_dir=replays)
    with TestClient(app) as client:
        r = client.get("/api/replay/dori_dori")
        assert r.status_code == 200
        data = r.json()
        assert data["fps"] == 2 and data["duration"] == 1.0
        assert data["q"] == [[round(v, 4) for v in to_radians(row)] for row in ([0] * 6, [100, 0, 0, 0, 0, 50])]
        assert data["cameras"]["tower cam"] == {"url": "/replays/dori_dori/tower_cam.mp4", "start": 1.0, "end": 2.0}
        assert client.get(data["cameras"]["tower cam"]["url"]).content == b"video"
        assert client.get(data["cameras"]["follow cam"]["frames"][0]).content == b"jpg"
        assert client.get("/api/replay/oranda_pickup").status_code == 404
        assert "snackbot" in client.get("/").text          # 프론트엔드 서빙은 그대로


def test_replay_api_uses_converter_and_404_without_dir(cfg, tmp_path):
    replays = tmp_path / "replays"
    write_replay(replays)
    _, app = make_app(cfg, tmp_path, replays_dir=replays, convert=lambda v: [1.0] * 6)
    with TestClient(app) as client:
        assert client.get("/api/replay/dori_dori").json()["q"][0] == [1.0] * 6
    _, app2 = make_app(cfg, tmp_path / "b")
    with TestClient(app2) as client:
        assert client.get("/api/replay/dori_dori").status_code == 404


def test_joints_sent_only_when_changed(cfg, tmp_path):
    cur = {"v": None}
    _, app = make_app(cfg, tmp_path, joints_fn=lambda: cur["v"], joints_hz=200)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        assert ws.receive_json() == INFO
        assert ws.receive_json()["type"] == "state"
        cur["v"] = [0] * 6
        assert ws.receive_json() == {"type": "joints", "q": [round(v, 4) for v in to_radians([0] * 6)]}
        time.sleep(0.1)                                     # 같은 값을 여러 번 읽는 동안에는 보내지 않는다
        cur["v"] = [100, 0, 0, 0, 0, 0]
        second = ws.receive_json()
        assert second["type"] == "joints"
        assert second["q"][0] == round(to_radians([100, 0, 0, 0, 0, 0])[0], 4)


def test_new_connection_gets_last_joints(cfg, tmp_path):
    _, app = make_app(cfg, tmp_path, joints_fn=lambda: [0] * 6, joints_hz=200)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json(), ws.receive_json()
            first = ws.receive_json()
            assert first["type"] == "joints"
        with client.websocket_connect("/ws") as ws2:
            assert ws2.receive_json() == INFO
            assert ws2.receive_json()["type"] == "state"
            assert ws2.receive_json() == first


def test_joints_fn_errors_and_none_are_skipped(cfg, tmp_path):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("serial busy")
        return None if calls["n"] < 5 else [0] * 6

    _, app = make_app(cfg, tmp_path, joints_fn=flaky, joints_hz=200)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json(), ws.receive_json()
        assert ws.receive_json()["type"] == "joints" and calls["n"] >= 5


def test_stream_encodes_off_the_event_loop_thread(cfg, tmp_path, monkeypatch):
    import threading
    monkeypatch.setattr("snackbot.server.STREAM_INTERVAL_S", 0.001)
    loop_thread = {}
    encode_threads = []
    real_chunk = mjpeg_chunk

    def spy_chunk(frame, boxes=None):
        encode_threads.append(threading.get_ident())
        return real_chunk(frame, boxes)

    monkeypatch.setattr("snackbot.server.mjpeg_chunk", spy_chunk)
    holder = {}

    def frame_fn():
        if len(encode_threads) >= 2:
            holder["c"].stop()
        return np.zeros((10, 10, 3), np.uint8)

    c, app = make_app(cfg, tmp_path, frame_fn=frame_fn)
    holder["c"] = c

    @app.middleware("http")
    async def note_loop_thread(request, call_next):
        loop_thread["id"] = threading.get_ident()
        return await call_next(request)

    with TestClient(app) as client:
        r = client.get("/stream/front")
    assert r.status_code == 200 and encode_threads
    assert loop_thread["id"] not in encode_threads


def test_app_starts_when_replays_dir_cannot_be_created(cfg, tmp_path, caplog):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    _, app = make_app(cfg, tmp_path, replays_dir=blocker / "replays")      # 파일 아래에는 폴더를 못 만든다
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/replays/x").status_code == 404
    assert "replays" in caplog.text


def test_ws_test_command_enters_testing_and_ignores_unknown_skill(cfg, tmp_path):
    c, app = make_app(cfg, tmp_path)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json(), ws.receive_json()
        ws.send_json({"type": "command", "name": "test", "skill": "dance"})   # 허용 외: 무시
        ws.send_json({"type": "command", "name": "test"})                     # skill 없음: 무시
        ws.send_json({"type": "command", "name": "test", "skill": "home"})
        ws.send_json({"type": "chat", "text": "안녕"})                         # 같은 FIFO: 테스트 요청 뒤에 처리
        events = []
        while not (events and events[-1].get("role") == "robot"):
            events.append(ws.receive_json())
    assert [(e["state"], e["skill"]) for e in events if e["type"] == "state"] == [("TESTING", "home")]
    assert c._pending_test is not None and c._pending_test[0] == "home"
    assert not any(m["role"] == "system" for m in c.history)               # 거부 메시지 없음


def test_ws_test_carries_generation_seen_on_receipt(cfg, tmp_path, monkeypatch):
    import threading
    c, app = make_app(cfg, tmp_path)
    gate, got, done = threading.Event(), threading.Event(), threading.Event()
    results = []
    orig_gen, orig_request = c.generation, c._request_test

    def generation():
        g = orig_gen()
        got.set()
        return g

    def request(skill, expect_gen=None, origin="button"):
        results.append(orig_request(skill, expect_gen=expect_gen, origin=origin))
        done.set()
        return results[-1]

    monkeypatch.setattr(c, "generation", generation)
    monkeypatch.setattr(c, "_request_test", request)
    monkeypatch.setattr(c, "chat", lambda text, source="text": gate.wait(5))  # 워커를 붙잡아 test를 큐에 쌓는다
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json(), ws.receive_json()
        ws.send_json({"type": "chat", "text": "붙잡기"})
        ws.send_json({"type": "command", "name": "test", "skill": "dori_dori"})
        assert got.wait(5)            # 서버가 test를 접수하고 세션 번호를 읽었다
        c.command("estop")            # 접수 뒤에 비상정지·재시작이 끼어든다 (다시 IDLE)
        c.command("restart")
        gate.set()
        assert done.wait(5)
    assert results == [False]
    assert c.state == "IDLE" and c._pending_test is None and c.skills.runs == []
