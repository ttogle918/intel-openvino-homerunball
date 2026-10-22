import threading
import time

from snackbot.voice import Voice


def test_speak_is_non_blocking_and_survives_errors(monkeypatch):
    v = Voice("log")
    done, gate = [], threading.Event()

    def slow(text):
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
