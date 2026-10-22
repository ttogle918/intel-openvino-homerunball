import threading
import time

from snackbot.voice import Voice


def test_speak_is_non_blocking_and_survives_errors(monkeypatch):
    v = Voice("log")
    done, gate = [], threading.Event()

    def slow(text, started=None):
        if text == "boom":
            raise RuntimeError("tts down")
        gate.wait(1)
        done.append(text)

    monkeypatch.setattr(v, "_say", slow)
    t0 = time.monotonic()
    v.speak("boom")
    v.speak("안녕")
    assert time.monotonic() - t0 < 0.1
    gate.set()
    v.close()
    assert done == ["안녕"]


def test_log_engine_prints(capsys):
    v = Voice("log")
    v.speak("반가워요")
    v.close()
    assert "[TTS] 반가워요" in capsys.readouterr().out


def test_none_engine_is_silent(capsys):
    v = Voice("none")
    v.speak("x")
    v.close()
    assert capsys.readouterr().out == ""


def test_pyttsx3_error_resets_engine(monkeypatch):
    import sys
    import types

    class Eng:
        def __init__(self, fail):
            self.fail = fail
            self.said = []

        def say(self, t):
            self.said.append(t)

        def runAndWait(self):
            if self.fail:
                raise RuntimeError("driver dead")

    engines = [Eng(True), Eng(False)]
    mod = types.SimpleNamespace(init=lambda: engines.pop(0))
    monkeypatch.setitem(sys.modules, "pyttsx3", mod)
    v = Voice("pyttsx3")
    try:
        v._tts = None
        try:
            v._say("a")
        except RuntimeError:
            pass
        assert v._tts is None
        v._say("b")
        assert v._tts is not None and v._tts.said == ["b"]
    finally:
        v.close()


# --- openai engine ---
import json

import httpx

from snackbot import voice as voice_mod
from snackbot.voice import make_voice

PROVIDERS = {"openai": {"type": "openai_compat", "base_url": "https://api.test/v1", "api_key_env": "K"}}
OPTS = {"engine": "openai", "provider": "openai", "model": "tts-m", "voice": "coral",
        "instructions": "짧게", "timeout_s": 3}


def _voice(handler, opts=OPTS, env=None):
    return Voice("openai", opts, PROVIDERS, {"K": "secret"} if env is None else env,
                 transport=httpx.MockTransport(handler))


def test_openai_request_and_playback(monkeypatch):
    seen, played = [], []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, content=b"RIFFwav")

    monkeypatch.setattr(voice_mod, "play_wav", played.append)
    v = _voice(handler)
    v.speak("안녕")
    v.close()
    req = seen[0]
    assert req.url.path == "/v1/audio/speech"
    assert req.headers["authorization"] == "Bearer secret"
    assert json.loads(req.content) == {"model": "tts-m", "voice": "coral", "input": "안녕",
                                       "response_format": "wav", "instructions": "짧게"}
    assert played == [b"RIFFwav"]


def test_openai_failure_keeps_worker_alive(monkeypatch):
    calls, played = [], []

    def handler(req):
        calls.append(1)
        return httpx.Response(500) if len(calls) == 1 else httpx.Response(200, content=b"ok")

    monkeypatch.setattr(voice_mod, "play_wav", played.append)
    v = _voice(handler)
    v.speak("a")
    v.speak("b")
    v.close()
    assert played == [b"ok"]


def test_openai_without_options_behaves_like_none(capsys):
    v = Voice("openai")
    assert v.engine == "none"
    v.speak("x")
    v.close()
    assert capsys.readouterr().out == ""


def test_openai_without_key_behaves_like_none():
    v = Voice("openai", OPTS, PROVIDERS, {})
    assert v.engine == "none"
    v.close()


def test_make_voice_wiring():
    v = make_voice({"voice": OPTS, "providers": PROVIDERS}, {"K": "secret"})
    assert v.engine == "openai" and v.options["voice"] == "coral"
    v.close()
    assert make_voice({}, {}).engine == "none"


# --- gemini engine ---
import base64
import io
import logging
import wave

GPROVIDERS = {"gemini": {"type": "openai_compat", "base_url": "https://g.test/v1beta/openai",
                         "api_key_env": "GK"}}
GOPTS = {"engine": "gemini", "provider": "gemini", "model": "tts-m", "voice": "Leda",
         "instructions": "보리처럼:", "timeout_s": 3}
PCM = b"\x01\x00\x02\x00" * 50


def _gemini_reply(rate_mime="audio/L16;codec=pcm;rate=16000"):
    data = base64.b64encode(PCM).decode()
    return {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": rate_mime, "data": data}}]}}]}


def _gvoice(handler, env=None):
    return Voice("gemini", GOPTS, GPROVIDERS, {"GK": "gsecret"} if env is None else env,
                 transport=httpx.MockTransport(handler))


def test_gemini_request_and_wav(monkeypatch):
    seen, played = [], []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json=_gemini_reply())

    monkeypatch.setattr(voice_mod, "play_wav", played.append)
    v = _gvoice(handler)
    v.speak("안녕")
    v.close()
    req = seen[0]
    assert req.url.path == "/v1beta/models/tts-m:generateContent" and not req.url.query
    assert req.headers["x-goog-api-key"] == "gsecret" and "authorization" not in req.headers
    body = json.loads(req.content)
    assert body["contents"][0]["parts"][0]["text"] == "보리처럼: 안녕"
    cfg = body["generationConfig"]
    assert cfg["responseModalities"] == ["AUDIO"]
    assert cfg["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Leda"
    with wave.open(io.BytesIO(played[0])) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000)
        assert w.readframes(w.getnframes()) == PCM


def test_gemini_default_rate_and_native_base_url():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json=_gemini_reply("audio/L16"))

    prov = {"gemini": {**GPROVIDERS["gemini"], "native_base_url": "https://n.test/v1beta"}}
    v = Voice("gemini", GOPTS, prov, {"GK": "k"}, transport=httpx.MockTransport(handler))
    wav = v.synthesize("x")
    v.close()
    assert seen[0].url.host == "n.test"
    with wave.open(io.BytesIO(wav)) as w:
        assert w.getframerate() == 24000


def test_gemini_without_key_behaves_like_none(caplog):
    with caplog.at_level(logging.WARNING):
        v = Voice("gemini", GOPTS, GPROVIDERS, {})
    assert v.engine == "none"
    assert any("gemini" in r.getMessage() for r in caplog.records)
    v.close()


def test_make_voice_builds_gemini():
    v = make_voice({"voice": GOPTS, "providers": GPROVIDERS}, {"GK": "k"})
    try:
        assert v.engine == "gemini" and v._http is not None
    finally:
        v.close()


def test_speak_returns_event_set_just_before_playback(monkeypatch):
    import snackbot.voice as vm
    v = Voice("gemini")  # 키 없음 -> none으로 떨어지므로 엔진을 직접 지정
    v.engine = "openai"
    seen = {}
    holder = {}

    def fake_play(data):
        seen["set_at_play"] = holder["ev"].is_set()

    monkeypatch.setattr(v, "synthesize", lambda text: b"wav")
    monkeypatch.setattr(vm, "play_wav", fake_play)
    holder["ev"] = ev = v.speak("안녕")
    assert isinstance(ev, threading.Event)
    assert ev.wait(2)
    v.close()
    assert seen == {"set_at_play": True}


def test_event_not_set_while_synthesizing(monkeypatch):
    import snackbot.voice as vm
    v = Voice("none")
    v.engine = "gemini"
    gate = threading.Event()
    monkeypatch.setattr(v, "synthesize", lambda text: (gate.wait(2), b"wav")[1])
    monkeypatch.setattr(vm, "play_wav", lambda data: None)
    ev = v.speak("x")
    assert not ev.wait(0.2)
    gate.set()
    assert ev.wait(2)
    v.close()


def test_event_set_when_synthesis_fails(monkeypatch):
    v = Voice("none")
    v.engine = "openai"

    def boom(text):
        raise RuntimeError("tts down")

    monkeypatch.setattr(v, "synthesize", boom)
    ev = v.speak("x")
    assert ev.wait(2)
    v.close()


def test_event_set_for_log_none_and_unknown_engines(capsys):
    for engine in ("log", "none"):
        v = Voice(engine)
        assert v.speak("x").wait(2)
        v.close()
    v = Voice("none")
    v.engine = "bogus"
    assert v.speak("x").wait(2)
    v.close()


def test_event_set_after_close():
    v = Voice("none")
    v.close()
    assert v.speak("x").is_set()


def test_close_sets_events_of_unprocessed_items(monkeypatch):
    v = Voice("none")
    gate = threading.Event()
    monkeypatch.setattr(v, "_say", lambda text, started=None: gate.wait(3))
    v.speak("first")  # 워커가 여기서 막힌다
    time.sleep(0.1)
    pending = [v.speak("a"), v.speak("b")]
    v.close()  # join 2초 타임아웃, 남은 항목은 set
    assert all(e.is_set() for e in pending)
    gate.set()
