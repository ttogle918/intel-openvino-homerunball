import threading
import time

from snackbot.voice import Voice


def test_speak_is_non_blocking_and_survives_errors(monkeypatch):
    v = Voice("log")
    done, gate = [], threading.Event()

    def slow(text, started=None, wav=None):
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
    v._join_timeout_s = 0.2
    gate, entered = threading.Event(), threading.Event()

    def stuck(text, started=None, wav=None):
        entered.set()
        gate.wait(3)

    monkeypatch.setattr(v, "_say", stuck)
    v.speak("first")
    assert entered.wait(2)  # 재생 스레드가 여기서 막혔다
    pending = [v.speak("a"), v.speak("b")]
    v.close()  # 마감 시간(0.2초) 안에 못 끝난 남은 항목은 set
    assert all(e.is_set() for e in pending)
    gate.set()


def test_close_sets_event_of_sentence_synth_thread_holds(monkeypatch):
    v = Voice("none")
    v._join_timeout_s = 0.2
    gate, entered, played = threading.Event(), threading.Event(), []

    def stuck(text, started=None, wav=None):
        played.append(text)
        entered.set()
        gate.wait(3)

    monkeypatch.setattr(v, "_say", stuck)
    v.speak("playing")
    assert entered.wait(2)
    evs = [v.speak(str(i)) for i in range(5)]  # 재생 큐(2칸)가 차고 합성 스레드는 손에 든 채 put 재시도
    v.close()
    assert all(e.wait(2) for e in evs)  # 손에 든 문장은 put 재시도 루프(0.05초 간격)가 포기를 알아챈 직후 set
    gate.set()
    v._play_thread.join(0.5)
    assert not v._play_thread.is_alive()  # 종료 신호가 재생 큐에 들어갔다
    assert played == ["playing"]  # 포기된 문장은 재생되지 않는다
    v._synth_thread.join(2)
    assert not v._synth_thread.is_alive()


def test_close_shares_one_deadline_between_joins():
    v = Voice("none")
    v._join_timeout_s = 0.4
    timeouts = []

    class SlowJoin:
        def join(self, timeout=None):
            timeouts.append(timeout)
            time.sleep(timeout)  # 주어진 시간을 다 쓴 척한다

    v._synth_thread, v._play_thread = SlowJoin(), SlowJoin()
    v.close()
    assert timeouts[0] <= 0.4 and timeouts[1] <= 0.05  # 두 join이 하나의 마감 시간을 나눠 쓴다


def test_clear_pending_drops_queued_sentences_but_not_the_playing_one(monkeypatch):
    v = Voice("none")
    gate, entered, played = threading.Event(), threading.Event(), []

    def say(text, started=None, wav=None):
        played.append(text)
        started.set()
        entered.set()
        gate.wait(3)

    monkeypatch.setattr(v, "_say", say)
    first = v.speak("playing")
    assert entered.wait(2)
    pending = [v.speak(str(i)) for i in range(5)]
    v.clear_pending()
    assert first.is_set() and all(e.wait(1) for e in pending)  # 합성 스레드가 손에 든 문장은 곧바로(<=0.05초)
    gate.set()
    after = v.speak("after")  # 비운 뒤의 새 문장은 정상 재생
    assert after.wait(2)
    v.close()
    assert played == ["playing", "after"]


def test_clear_pending_drops_sentence_being_synthesized(monkeypatch):
    import snackbot.voice as vm
    v = Voice("none")
    v.engine = "openai"
    in_synth, gate, played = threading.Event(), threading.Event(), []

    def synth(text):
        in_synth.set()
        gate.wait(3)
        return text.encode()

    monkeypatch.setattr(v, "synthesize", synth)
    monkeypatch.setattr(vm, "play_wav", played.append)
    ev = v.speak("합성 중")
    assert in_synth.wait(2)
    v.clear_pending()
    gate.set()
    assert ev.wait(2)
    v.close()
    assert played == []


def test_next_sentence_synthesizes_while_previous_plays(monkeypatch):
    import snackbot.voice as vm
    v = Voice("none")
    v.engine = "openai"
    hold, played, synth = threading.Event(), [], []
    second_synth = threading.Event()

    def synthesize(text):
        synth.append(text)
        if text == "둘":
            second_synth.set()
        return text.encode()

    def play(data):
        played.append(data)
        hold.wait(3)

    monkeypatch.setattr(v, "synthesize", synthesize)
    monkeypatch.setattr(vm, "play_wav", play)
    e1, e2 = v.speak("하나"), v.speak("둘")
    assert e1.wait(2)
    assert second_synth.wait(2)  # 첫 문장이 재생 중(hold)인 채로 둘째를 합성
    assert played == ["하나".encode()] and not e2.is_set()
    hold.set()
    assert e2.wait(2)
    v.close()
    assert played == ["하나".encode(), "둘".encode()]


def test_playback_order_matches_speak_order(monkeypatch):
    import snackbot.voice as vm
    v = Voice("none")
    v.engine = "gemini"
    played = []
    monkeypatch.setattr(v, "synthesize", lambda t: t.encode())
    monkeypatch.setattr(vm, "play_wav", lambda d: played.append(d.decode()))
    evs = [v.speak(str(i)) for i in range(6)]
    assert all(e.wait(3) for e in evs)
    v.close()
    assert played == [str(i) for i in range(6)]


def test_failed_synthesis_does_not_block_next(monkeypatch):
    import snackbot.voice as vm
    v = Voice("none")
    v.engine = "openai"
    played = []

    def synth(t):
        if t == "bad":
            raise RuntimeError("x")
        return t.encode()

    monkeypatch.setattr(v, "synthesize", synth)
    monkeypatch.setattr(vm, "play_wav", lambda d: played.append(d))
    e1, e2 = v.speak("bad"), v.speak("ok")
    assert e1.wait(2) and e2.wait(2)
    v.close()
    assert played == [b"ok"]


# --- Windows 예비 음성 (fallback: windows) ---

FB = {**GOPTS, "fallback": "windows", "fallback_cooldown_s": 600}


def _fb_voice(monkeypatch, handler, env=None, opts=FB):
    monkeypatch.setattr(voice_mod.sys, "platform", "win32")
    v = Voice("gemini", opts, GPROVIDERS, {"GK": "gsecret"} if env is None else env,
              transport=httpx.MockTransport(handler))
    made = []
    monkeypatch.setattr(v, "_synthesize_windows", lambda text: made.append(text) or b"WIN:" + text.encode())
    return v, made


def test_quota_error_uses_windows_voice_then_skips_api_for_cooldown(monkeypatch):
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(429, json={})

    v, made = _fb_voice(monkeypatch, handler)
    assert v._synthesize_any("하나") == "WIN:하나".encode()
    assert v._synthesize_any("둘") == "WIN:둘".encode()
    v.close()
    assert len(calls) == 1 and made == ["하나", "둘"]   # 한도 오류 뒤에는 API를 다시 부르지 않는다


def test_other_error_uses_short_cooldown_then_retries_api(monkeypatch):
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(500, json={})

    v, made = _fb_voice(monkeypatch, handler)
    v._synthesize_any("하나")
    v._synthesize_any("둘")
    assert len(calls) == 1 and made == ["하나", "둘"]       # 기본 60초: 그 사이 문장은 API를 기다리지 않는다
    v._primary_off_until = 0.0                              # 쿨다운이 지나면 다시 API를 부른다
    v._synthesize_any("셋")
    v.close()
    assert len(calls) == 2 and made == ["하나", "둘", "셋"]


def test_timeout_error_cooldown_is_configurable(monkeypatch):
    calls = []

    def handler(req):
        calls.append(req)
        raise httpx.ConnectTimeout("느림", request=req)

    v, made = _fb_voice(monkeypatch, handler, opts={**FB, "fallback_error_cooldown_s": 0})
    v._synthesize_any("하나")
    v._synthesize_any("둘")
    v.close()
    assert len(calls) == 2 and made == ["하나", "둘"]       # 0이면 매 문장 API를 다시 시도


def test_windows_voice_script_stops_on_error_and_logs_stderr(monkeypatch, caplog):
    import subprocess
    monkeypatch.setattr(voice_mod.sys, "platform", "win32")
    seen = {}

    def fake_run(cmd, **kw):
        seen["script"] = cmd[-1]
        raise subprocess.CalledProcessError(1, cmd, stderr="목소리 없음 Nonexistent".encode("utf-8"))

    monkeypatch.setattr(voice_mod.subprocess, "run", fake_run)
    v = Voice("windows", FB)
    try:
        v._synthesize_windows("안녕")
        raise AssertionError("예외가 나야 한다")
    except subprocess.CalledProcessError:
        pass
    v.close()
    assert seen["script"].startswith("$ErrorActionPreference='Stop';")
    assert "목소리 없음 Nonexistent" in caplog.text


def test_api_ok_does_not_use_windows_voice(monkeypatch):
    v, made = _fb_voice(monkeypatch, lambda req: httpx.Response(200, json=_gemini_reply()))
    wav = v._synthesize_any("안녕")
    v.close()
    assert wav.startswith(b"RIFF") and made == []


def test_without_fallback_error_propagates(monkeypatch):
    v, made = _fb_voice(monkeypatch, lambda req: httpx.Response(429, json={}), opts=GOPTS)
    try:
        v._synthesize_any("x")
        raise AssertionError("예외가 나야 한다")
    except httpx.HTTPStatusError:
        pass
    v.close()
    assert made == []


def test_missing_key_with_fallback_speaks_with_windows_voice(monkeypatch):
    monkeypatch.setattr(voice_mod.sys, "platform", "win32")
    played = []
    monkeypatch.setattr(voice_mod, "play_wav", played.append)
    v = Voice("gemini", FB, GPROVIDERS, {})
    assert v.engine == "windows"
    monkeypatch.setattr(v, "_synthesize_windows", lambda text: b"WIN")
    v.speak("안녕").wait(2)
    v.close()
    assert played == [b"WIN"]


def test_fallback_ignored_off_windows(monkeypatch):
    monkeypatch.setattr(voice_mod.sys, "platform", "linux")
    v = Voice("gemini", FB, GPROVIDERS, {})
    assert v.fallback is None and v.engine == "none"
    v.close()
