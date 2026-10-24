"""LLM / STT provider 어댑터와 fallback 체인.

메시지 형식: [{"role": "system" | "user", "content": str}, ...]
"""
import base64
import io
import logging
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

NEEDS_KEY = {"openai_compat", "anthropic"}


STT_CHAT_PROMPT = "다음 한국어 음성을 들리는 그대로 받아써. 받아쓴 문장만 출력해."


class ProviderError(Exception):
    pass


class OpenAICompat:
    """NVIDIA, Gemini(OpenAI 호환) — base_url과 키만 다르다."""

    def __init__(self, base_url, api_key, model, timeout_s=5.0, transport=None, extra_body=None):
        self.model = model
        self.extra_body = dict(extra_body or {})  # 예: 추론 모델의 생각 끄기
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.http = httpx.Client(base_url=base_url.rstrip("/"), headers=headers,
                                 timeout=timeout_s, transport=transport)

    def complete(self, messages, max_tokens=300):
        msgs = [dict(m) for m in messages]
        r = self.http.post("/chat/completions",
                           json={**self.extra_body, "model": self.model, "messages": msgs,
                                 "max_tokens": max_tokens})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""

    def transcribe(self, wav, language="ko"):
        """오디오 입력 chat으로 받아쓴다 (Gemini)."""
        audio = base64.standard_b64encode(wav).decode()
        content = [{"type": "text", "text": STT_CHAT_PROMPT},
                   {"type": "input_audio", "input_audio": {"data": audio, "format": "wav"}}]
        r = self.http.post("/chat/completions",
                           json={**self.extra_body, "model": self.model,
                                 "messages": [{"role": "user", "content": content}]})
        r.raise_for_status()
        return (r.json()["choices"][0]["message"]["content"] or "").strip()


class AnthropicProvider:
    """Claude (공식 anthropic SDK). 재시도는 체인이 맡으므로 SDK 재시도는 끈다."""

    def __init__(self, api_key, model, timeout_s=5.0, effort=None, client=None):
        if client is None:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=0)
        self.client, self.model, self.effort = client, model, effort

    def complete(self, messages, max_tokens=300):
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        turns = []  # 같은 role이 이어지면 합쳐서 user/assistant가 번갈아 오게 한다
        for m in messages:
            if m["role"] == "system":
                continue
            if turns and turns[-1]["role"] == m["role"]:
                turns[-1]["content"] += "\n" + m["content"]
            else:
                turns.append({"role": m["role"], "content": m["content"]})
        while turns and turns[0]["role"] != "user":  # Anthropic은 user로 시작해야 한다
            turns.pop(0)
        out = [{"role": t["role"], "content": [{"type": "text", "text": t["content"]}]} for t in turns]
        kwargs = {"model": self.model, "max_tokens": max_tokens, "messages": out}
        if system:
            kwargs["system"] = system
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        resp = self.client.messages.create(**kwargs)
        if resp.stop_reason == "refusal":
            raise ProviderError("refusal")
        return "".join(b.text for b in resp.content if b.type == "text")

    def transcribe(self, wav):
        raise ProviderError("anthropic은 음성 전사를 지원하지 않음")


class OpenVINOProvider:
    """로컬 openvino_genai. kind: llm | whisper. 처음 호출할 때 파이프라인을 만든다.
    API는 M3에서 설치된 openvino_genai 버전으로 확인한다."""

    def __init__(self, model_dir, device="CPU", kind="llm", language="ko", cache_dir=None):
        self.model_dir, self.device, self.kind = str(model_dir), device, kind
        self.language = language
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._pipe = None
        self._lock = threading.Lock()
        self._run_lock = threading.Lock()  # 같은 파이프라인에서 generate가 동시에 돌지 않게 한다

    def _pipeline(self):
        with self._lock:  # 워밍업 스레드와 첫 요청이 겹쳐도 파이프라인은 하나만 만든다
            if self._pipe is None:
                import openvino_genai as ov_genai
                cls = {"llm": ov_genai.LLMPipeline,
                       "whisper": ov_genai.WhisperPipeline}[self.kind]
                if self.cache_dir is not None:
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    self._pipe = cls(self.model_dir, self.device, CACHE_DIR=str(self.cache_dir))
                else:
                    self._pipe = cls(self.model_dir, self.device)
            return self._pipe

    def warmup(self):
        """파이프라인을 만들고(whisper는 무음 한 번 generate까지) 걸린 초를 돌려준다."""
        t0 = time.monotonic()
        pipe = self._pipeline()
        if self.kind == "whisper":
            with self._run_lock:
                pipe.generate([0.0] * 8000, language=f"<|{self.language}|>", task="transcribe")
        return time.monotonic() - t0

    def complete(self, messages, max_tokens=300):
        pipe = self._pipeline()
        prompt = pipe.get_tokenizer().apply_chat_template(messages, add_generation_prompt=True)
        with self._run_lock:
            return _text(pipe.generate(prompt, max_new_tokens=max_tokens))

    def transcribe(self, wav, language=None):
        language = language or self.language
        pipe, samples = self._pipeline(), wav_to_float32(wav)
        with self._run_lock:
            return _text(pipe.generate(samples, language=f"<|{language}|>", task="transcribe"))


def _text(result):
    if isinstance(result, str):
        return result
    texts = getattr(result, "texts", None)
    return texts[0] if texts else str(result)


def wav_to_float32(wav):
    import numpy as np
    with wave.open(io.BytesIO(wav)) as w:
        frames, channels, width = w.readframes(w.getnframes()), w.getnchannels(), w.getsampwidth()
    if width != 2:
        raise ProviderError("16bit PCM WAV만 지원")
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples.tolist()


@dataclass
class Member:
    name: str
    provider: object


class Chain:
    """위에서부터 시도. 예외·빈 응답이면 다음 provider. 전부 실패하면 ProviderError."""

    def __init__(self, members=()):
        self.members = list(members)
        self._lock = threading.Lock()

    def __bool__(self):
        return bool(self.members)

    def describe(self):
        return " → ".join(m.name for m in self.members) or "규칙"

    def complete(self, messages, max_tokens=300):
        return self._try(lambda p: p.complete(messages, max_tokens=max_tokens))

    def transcribe(self, wav):
        return self._try(lambda p: p.transcribe(wav))

    def _try(self, call):
        errors = []
        with self._lock:
            for m in self.members:
                try:
                    text = call(m.provider)
                except Exception as e:  # 타임아웃·HTTP 오류·미설치 모두 다음으로
                    log.warning("provider %s 실패: %s", m.name, e)
                    errors.append(f"{m.name}: {e}")
                    continue
                if text and text.strip():
                    return text.strip(), m.name
                errors.append(f"{m.name}: 빈 응답")
        raise ProviderError("; ".join(errors) or "provider 없음")


def build_chain(entries, providers_cfg, env):
    members = []
    for e in entries or []:
        pname = e.get("provider")
        pc = (providers_cfg or {}).get(pname)
        if pc is None:
            log.warning("알 수 없는 provider: %s (건너뜀)", pname)
            continue
        try:
            kind = pc["type"]
            key_env = pc.get("api_key_env")
            key = env.get(key_env, "") if key_env else ""
            if kind in NEEDS_KEY and key_env and not key:
                log.warning("%s: %s 없음 (건너뜀)", pname, key_env)
                continue
            timeout = float(e.get("timeout_s", 5))
            if kind == "openai_compat":
                provider = OpenAICompat(pc["base_url"], key, e["model"], timeout, extra_body=e.get("extra_body"))
            elif kind == "anthropic":
                provider = AnthropicProvider(key, e["model"], timeout, e.get("effort"))
            elif kind == "openvino":
                provider = OpenVINOProvider(e["model_dir"], e.get("device", "CPU"), e.get("kind", "llm"),
                                            e.get("language", "ko"), e.get("cache_dir"))
            else:
                log.warning("알 수 없는 provider type: %s (건너뜀)", kind)
                continue
        except Exception as ex:
            log.warning("%s 준비 실패 (건너뜀): %s", pname, ex)
            continue
        members.append(Member(e.get("label") or f"{pname}:{e.get('model') or e.get('model_dir')}", provider))
    return Chain(members)
