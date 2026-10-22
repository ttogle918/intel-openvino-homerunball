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
