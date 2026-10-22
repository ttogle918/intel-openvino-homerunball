import sys
import threading
import time
import types

import pytest

from snackbot.providers import Chain, Member, OpenVINOProvider, build_chain, wav_to_float32
from snackbot.stt import STT


class FakeWhisper:
    created = []
    generated = []

    def __init__(self, model_dir, device, **kwargs):
        time.sleep(0.05)  # 동시 호출이 겹치게 한다
        self.args = (model_dir, device, kwargs)
        FakeWhisper.created.append(self.args)

    def generate(self, samples, **kwargs):
        FakeWhisper.generated.append((samples, kwargs))
        return " 안녕"


@pytest.fixture
def fake_genai(monkeypatch):
    FakeWhisper.created, FakeWhisper.generated = [], []
    mod = types.SimpleNamespace(WhisperPipeline=FakeWhisper, LLMPipeline=FakeWhisper, VLMPipeline=FakeWhisper)
    monkeypatch.setitem(sys.modules, "openvino_genai", mod)
    return mod


def make_wav():
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 160)
    return buf.getvalue()


def test_transcribe_uses_default_and_configured_language(fake_genai):
    OpenVINOProvider("m", kind="whisper").transcribe(make_wav())
    OpenVINOProvider("m", kind="whisper", language="en").transcribe(make_wav())
    assert [g[1]["language"] for g in FakeWhisper.generated] == ["<|ko|>", "<|en|>"]
    assert FakeWhisper.generated[0][1]["task"] == "transcribe"


def test_transcribe_explicit_language_overrides(fake_genai):
    OpenVINOProvider("m", kind="whisper").transcribe(make_wav(), language="ja")
    assert FakeWhisper.generated[0][1]["language"] == "<|ja|>"


def test_cache_dir_passed_as_keyword(fake_genai, tmp_path):
    cache = tmp_path / "cache"
    OpenVINOProvider("m", "GPU", "whisper", cache_dir=cache)._pipeline()
    assert FakeWhisper.created == [("m", "GPU", {"CACHE_DIR": str(cache)})]
    assert cache.is_dir()


def test_no_cache_dir_no_keyword(fake_genai):
    OpenVINOProvider("m", "CPU", "whisper")._pipeline()
    assert FakeWhisper.created == [("m", "CPU", {})]


def test_pipeline_created_once_across_threads(fake_genai):
    p = OpenVINOProvider("m", kind="whisper")
    threads = [threading.Thread(target=p._pipeline) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(FakeWhisper.created) == 1


def test_warmup_generates_silence(fake_genai):
    secs = OpenVINOProvider("m", kind="whisper").warmup()
    assert secs >= 0
    samples, kwargs = FakeWhisper.generated[0]
    assert len(samples) == 8000 and set(samples) == {0.0}
    assert kwargs["language"] == "<|ko|>"


def test_warmup_non_whisper_only_loads(fake_genai):
    OpenVINOProvider("m", kind="llm").warmup()
    assert len(FakeWhisper.created) == 1 and FakeWhisper.generated == []


def test_build_chain_label_language_cache_dir(fake_genai, tmp_path):
    providers = {"local_ov": {"type": "openvino"}}
    entries = [{"provider": "local_ov", "kind": "whisper", "model_dir": "m", "language": "en",
                "cache_dir": str(tmp_path), "label": "Whisper small · OpenVINO · CPU"},
               {"provider": "local_ov", "kind": "whisper", "model_dir": "m2"}]
    chain = build_chain(entries, providers, env={})
    assert [m.name for m in chain.members] == ["Whisper small · OpenVINO · CPU", "local_ov:m2"]
    p = chain.members[0].provider
    assert p.language == "en" and str(p.cache_dir) == str(tmp_path)
    assert chain.members[1].provider.language == "ko" and chain.members[1].provider.cache_dir is None


class Warm:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, 0

    def warmup(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        return 0.1


def test_stt_warmup_skips_missing_and_survives_failure(caplog):
    ok, bad, plain = Warm(), Warm(fail=True), object()
    stt = STT(Chain([Member("bad", bad), Member("plain", plain), Member("ok", ok)]))
    with caplog.at_level("INFO"):
        stt.warmup()
    assert (bad.calls, ok.calls) == (1, 1)
    assert "STT 워밍업 실패: bad" in caplog.text and "STT 워밍업 완료: ok" in caplog.text


def test_wav_helper_still_works():
    assert len(wav_to_float32(make_wav())) == 160
