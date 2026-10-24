import io
import json
import sys
import wave
from types import SimpleNamespace

import httpx
import pytest

from snackbot.providers import (
    AnthropicProvider, Chain, Member, OpenAICompat, OpenVINOProvider, ProviderError, build_chain,
    wav_to_float32,
)


class Fake:
    def __init__(self, reply=None, exc=None):
        self.reply, self.exc, self.calls = reply, exc, 0

    def complete(self, messages, max_tokens=300):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.reply

    def transcribe(self, wav):
        return self.complete([])


def test_chain_falls_through_errors_and_empty_replies():
    a, b, c = Fake(exc=TimeoutError("slow")), Fake(reply="  "), Fake(reply=" ok ")
    chain = Chain([Member("a", a), Member("b", b), Member("c", c)])
    assert chain.complete([{"role": "user", "content": "hi"}]) == ("ok", "c")
    assert (a.calls, b.calls, c.calls) == (1, 1, 1)


def test_chain_raises_when_all_fail():
    with pytest.raises(ProviderError):
        Chain([Member("a", Fake(exc=RuntimeError("x")))]).complete([])
    with pytest.raises(ProviderError):
        Chain([]).complete([])


def test_chain_truthiness_and_describe():
    assert not Chain([])
    assert Chain([]).describe() == "규칙"
    chain = Chain([Member("a:m", Fake("x")), Member("b:n", Fake("y"))])
    assert chain and chain.describe() == "a:m → b:n"


def test_chain_transcribe():
    assert Chain([Member("w", Fake(reply="안녕"))]).transcribe(b"wav") == ("안녕", "w")


def test_openai_compat_sends_model_and_auth():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "3"}}]})

    p = OpenAICompat("https://example.test/api/v1", "k", "m1", 5, transport=httpx.MockTransport(handler))
    out = p.complete([{"role": "user", "content": "몇 개?"}], max_tokens=8)
    assert out == "3"
    assert seen["url"] == "https://example.test/api/v1/chat/completions"
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["model"] == "m1" and seen["body"]["max_tokens"] == 8


def test_openai_compat_http_error_raises():
    p = OpenAICompat("https://e.test/v1", "k", "m", 5,
                     transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(httpx.HTTPStatusError):
        p.complete([{"role": "user", "content": "x"}])


def test_anthropic_provider_builds_request_and_reads_text():
    calls = {}

    def create(**kw):
        calls.update(kw)
        return SimpleNamespace(stop_reason="end_turn", content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text='{"skill": "done"}'),
        ])

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    p = AnthropicProvider("k", "claude-opus-5-5", 5, effort="low", client=client)
    out = p.complete([{"role": "system", "content": "sys"}, {"role": "user", "content": "u"}],
                     max_tokens=512)
    assert out == '{"skill": "done"}'
    assert calls["system"] == "sys"
    assert calls["model"] == "claude-opus-5-5" and calls["max_tokens"] == 512
    assert calls["output_config"] == {"effort": "low"}
    content = calls["messages"][0]["content"]
    assert content == [{"type": "text", "text": "u"}]


def test_anthropic_without_effort_omits_output_config():
    calls = {}

    def create(**kw):
        calls.update(kw)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="hi")])

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    AnthropicProvider("k", "m", client=client).complete([{"role": "user", "content": "u"}])
    assert "output_config" not in calls and "system" not in calls


def test_anthropic_refusal_raises():
    client = SimpleNamespace(messages=SimpleNamespace(
        create=lambda **kw: SimpleNamespace(stop_reason="refusal", content=[])))
    with pytest.raises(ProviderError):
        AnthropicProvider("k", "m", client=client).complete([{"role": "user", "content": "u"}])


def test_build_chain_skips_missing_keys_and_unknown():
    providers = {
        "nvidia": {"type": "openai_compat", "base_url": "https://o.test/v1", "api_key_env": "NV_KEY"},
        "gemini": {"type": "openai_compat", "base_url": "http://localhost:1/v1"},
        "local_ov": {"type": "openvino"},
    }
    entries = [
        {"provider": "nvidia", "model": "a"},
        {"provider": "nope", "model": "b"},
        {"provider": "gemini", "model": "c"},
        {"provider": "local_ov", "model_dir": "models/llm", "device": "GPU"},
    ]
    assert [m.name for m in build_chain(entries, providers, env={}).members] == [
        "gemini:c", "local_ov:models/llm"]
    assert [m.name for m in build_chain(entries, providers, env={"NV_KEY": "x"}).members] == [
        "nvidia:a", "gemini:c", "local_ov:models/llm"]
    assert not build_chain(None, providers, env={})


def test_wav_to_float32():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((16384).to_bytes(2, "little", signed=True) * 4)
    assert wav_to_float32(buf.getvalue()) == [0.5] * 4


def test_build_chain_skips_entry_missing_model():
    providers = {"gemini": {"type": "openai_compat", "base_url": "http://x"}}
    entries = [{"provider": "gemini"}, {"provider": "gemini", "model": "m"}]
    assert [m.name for m in build_chain(entries, providers, env={}).members] == ["gemini:m"]


def test_build_chain_skips_provider_missing_type():
    providers = {"bad": {"base_url": "http://x"}, "ok": {"type": "openai_compat", "base_url": "http://x"}}
    entries = [{"provider": "bad", "model": "m"}, {"provider": "ok", "model": "m"}]
    assert [m.name for m in build_chain(entries, providers, env={}).members] == ["ok:m"]


def test_build_chain_skips_anthropic_when_sdk_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    providers = {"claude": {"type": "anthropic", "api_key_env": "K"}}
    entries = [{"provider": "claude", "model": "m"}]
    assert not build_chain(entries, providers, env={"K": "x"}).members


def test_openai_compat_extra_body_is_merged_into_request():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    p = OpenAICompat("https://e.test/v1", "k", "m", 5, transport=httpx.MockTransport(handler),
                     extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    p.complete([{"role": "user", "content": "x"}])
    assert seen["body"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert seen["body"]["model"] == "m"


def test_anthropic_sends_alternating_roles_merged_and_user_first():
    calls = {}

    def create(**kw):
        calls.update(kw)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="ok")])

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    p = AnthropicProvider("k", "m", client=client)
    p.complete([{"role": "system", "content": "s1"}, {"role": "system", "content": "s2"},
                {"role": "assistant", "content": "먼저"},
                {"role": "user", "content": "a"}, {"role": "user", "content": "b"},
                {"role": "assistant", "content": "c"}, {"role": "user", "content": "d"}])
    assert calls["system"] == "s1\ns2"
    assert [m["role"] for m in calls["messages"]] == ["user", "assistant", "user"]
    assert calls["messages"][0]["content"] == [{"type": "text", "text": "a\nb"}]
    assert calls["messages"][1]["content"] == [{"type": "text", "text": "c"}]
    last = calls["messages"][2]["content"]
    assert last == [{"type": "text", "text": "d"}]


def test_openai_compat_transcribe():
    import base64
    import json
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": " 과자 옮겨줘 \n"}}]})

    p = OpenAICompat("https://e.test/v1", "k", "gm", 5, transport=httpx.MockTransport(handler))
    assert p.transcribe(b"RIFFwav") == "과자 옮겨줘"
    assert seen[0].url.path == "/v1/chat/completions"
    body = json.loads(seen[0].content)
    parts = body["messages"][0]["content"]
    assert body["model"] == "gm" and body["messages"][0]["role"] == "user"
    assert parts[0]["type"] == "text" and "받아써" in parts[0]["text"]
    assert parts[1] == {"type": "input_audio", "input_audio": {
        "data": base64.b64encode(b"RIFFwav").decode(), "format": "wav"}}
