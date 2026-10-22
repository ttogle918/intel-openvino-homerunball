# snackbot 소프트웨어 (dry-run · 서버 · provider) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 로봇 없이 `python -m snackbot --dry-run`으로 채팅 → 작업 → 거부 → 재개 → 완료 흐름 전체가 웹 UI와 콘솔에서 돌아가게 만든다. LLM/VLM/STT provider 체인, 개수 세기 체인(A단계), TTS까지 포함한다.

**Architecture:** 파이썬 패키지 `snackbot/` 하나. `controller.py`가 상태 머신과 사이클 루프 스레드를 갖고, `server.py`(FastAPI)는 controller를 부르기만 한다. 행동 계층은 이번 계획에서 `DrySkills`(sleep)만 만들고, 실제 로봇(physicalai)은 다음 계획(M4)에서 같은 인터페이스로 추가한다.

**Tech Stack:** Python 3.12+ (개발 PC 3.13), FastAPI + uvicorn, httpx, PyYAML, NumPy, OpenCV, anthropic SDK, pytest. 선택: pyttsx3, openvino-genai, ultralytics (lazy import).

**설계 기준:** `docs/superpowers/specs/2026-10-22-chat-ui-design.md` (이하 "설계 문서"), `docs/DECISION_LOGIC.md`, `docs/UI_DESIGN_PROMPT.md`.

## Global Constraints

- 모든 명령은 `project/` 디렉토리에서 실행한다. 파이썬은 **`.venv/Scripts/python`** (Windows 개발 PC; 이미 생성·설치됨). Linux라면 `.venv/bin/python`.
- git 저장소 루트는 `project/`의 상위 폴더다. 커밋할 때 **`project/` 안의 파일만** `git add <경로>`로 지정한다 (`git add -A`·`git add .` 금지 — 상위 폴더에 우리 것이 아닌 변경이 있다).
- 커밋 메시지 마지막 줄: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
- 프레임 규약: snackbot 안의 이미지 배열은 **RGB uint8 HxWx3**. OpenCV로 저장·인코딩할 때만 BGR로 바꾼다.
- 스킬 이름: `oranda_pickup | dori_dori | done`. 채팅 intent: `start_task | resume | chat`. 상태: `IDLE | WORKING | REFUSING | DONE | ESTOP`. phase: `idle | counting | thinking | acting | returning | waiting_operator`.
- 가드 임계값: `safe_max: 3`, `force_refuse: 6`, `max_retry: 2` (config.yaml `decision`).
- 대사 검증: 비었거나 80자 초과 → 준비된 대사. 과자 이름은 `config.target.name`("오란다")을 `{target}` 자리에 넣는다 (`str.format` 대신 `.replace("{target}", ...)` — 프롬프트에 JSON 중괄호가 있다).
- 외부 API는 타임아웃 필수. provider 체인이 전부 실패해도 규칙으로 계속 돈다. 어떤 예외도 사이클 루프를 죽이지 않는다.
- controller는 FastAPI를 import하지 않는다. 의존 방향: `server → controller → (brain, vision, skills, voice)`.
- openvino_genai, ultralytics, pyttsx3, anthropic은 **해당 기능을 쓸 때만** import한다 (모듈 최상단 import 금지). 설치돼 있지 않아도 테스트와 dry-run이 돌아야 한다.
- 큰 패키지(openvino-genai, ultralytics, torch) 설치·모델 다운로드 금지.
- physicalai / LeRobot 코드는 이 계획에서 쓰지 않는다.

## File Structure

| 파일 | 책임 |
|---|---|
| `requirements.txt`, `pytest.ini`, `.env.example`, `.gitignore` | 의존성, 테스트 설정, 키 이름 |
| `config.yaml` | 현장에서 고치는 값 전부 |
| `snackbot/__init__.py` | 패키지 표시 |
| `snackbot/config.py` | `load_config`, `load_env` |
| `snackbot/providers.py` | `OpenAICompat`, `AnthropicProvider`, `OpenVINOProvider`, `Chain`, `build_chain`, `ProviderError` |
| `snackbot/brain.py` | 가드 규칙, `Brain.decide`, `Brain.chat`, 대사 목록 |
| `snackbot/vision.py` | `Count`, counter 4종, `Vision`, `build_vision`, `encode_jpeg`, CLI |
| `snackbot/skills.py` | `RunResult`, `DrySkills`, `synth_tray` |
| `snackbot/voice.py` | `Voice` (비동기 TTS) |
| `snackbot/controller.py` | 상태 머신, `step()`, 루프 스레드, 이벤트, JSONL 로그 |
| `snackbot/stt.py` | `STT`, `build_stt` |
| `snackbot/server.py` | `create_app`, `/ws`, `/stt`, `/stream/front`, 정적 서빙 |
| `snackbot/__main__.py` | `build`, 콘솔 키, `main` |
| `tools/__init__.py`, `tools/export_yolo_world.py` | YOLO-World → OpenVINO 내보내기 (로봇 노트북용) |
| `frontend/index.html` | 개발용 임시 화면 (Claude Design 결과물로 교체) |
| `tests/conftest.py`, `tests/test_*.py` | 테스트 |

---

### Task 1: 프로젝트 기반 (config · 테스트 설정)

**Files:**
- Create: `requirements.txt`, `pytest.ini`, `.env.example`, `config.yaml`, `snackbot/__init__.py`, `snackbot/config.py`, `tests/conftest.py`, `tests/test_config.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `load_config(path) -> dict`, `load_env(path=".env") -> dict` (os.environ이 .env보다 우선), pytest fixture `cfg` (config.yaml 복사본, `dry_run.act_s=0`, `logging.dir=tmp_path/logs`), `FirstRng` 테스트 도우미(`choice(seq)`가 첫 원소 반환) — `tests/conftest.py`에 정의

- [ ] **Step 1: 설정 파일 작성**

`requirements.txt`:
```text
# 개발 PC · dry-run (python -m snackbot --dry-run)
fastapi
uvicorn[standard]
httpx
pyyaml
numpy
opencv-python
anthropic
pytest
# 선택 (필요한 환경에서만 설치)
# pyttsx3          # voice.engine: pyttsx3
# openvino-genai   # local_ov provider (LLM / VLM / Whisper)
# ultralytics      # vision yolo counter, tools.export_yolo_world
```

`pytest.ini`:
```ini
[pytest]
testpaths = tests
pythonpath = .
```

`.env.example`:
```text
# 이 파일을 .env로 복사해서 쓰는 키만 채운다. .env는 git에 올리지 않는다.
OPENROUTER_API_KEY=
NVIDIA_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
```

`.gitignore` 끝에 추가:
```text
.env
.pytest_cache/
```

`config.yaml`:
```yaml
# 과자 옮기기 로봇 설정. 설계: docs/superpowers/specs/2026-10-22-chat-ui-design.md
# API 키는 .env에 (.env.example 참고). 이 파일에는 키를 쓰지 않는다.

target:
  name: 오란다
  initial_count: 3          # B단계: 채팅에 개수가 없을 때

decision:
  safe_max: 3               # 이하면 무조건 일함
  force_refuse: 6           # 이상이면 무조건 거부
  max_retry: 2              # 옮기기 실패 시 재시도 횟수

providers:                  # 접속 정보만. 어떤 모델을 쓸지는 각 역할의 chain에서 고른다.
  openrouter: {type: openai_compat, base_url: "https://openrouter.ai/api/v1", api_key_env: OPENROUTER_API_KEY}
  nvidia:     {type: openai_compat, base_url: "https://integrate.api.nvidia.com/v1", api_key_env: NVIDIA_API_KEY}
  openai:     {type: openai_compat, base_url: "https://api.openai.com/v1", api_key_env: OPENAI_API_KEY}
  anthropic:  {type: anthropic, api_key_env: ANTHROPIC_API_KEY}
  ollama:     {type: openai_compat, base_url: "http://localhost:11434/v1"}
  local_ov:   {type: openvino}

brain:
  max_say_len: 80
  max_tokens: 1024
  # 위에서부터 시도, 전부 실패하면 규칙. 비우면 규칙만.
  chain: []
  # chain:
  #   - {provider: openrouter, model: "[모델 ID]", timeout_s: 5}
  #   - {provider: anthropic, model: "claude-opus-5-5", effort: low, timeout_s: 8}
  #   - {provider: local_ov, model_dir: "models/llm", device: GPU, kind: llm}

vision:
  camera: front
  # 비우면 B단계 (시작 개수 + 그리퍼 판정). 위에서부터 시도.
  chain: []
  # chain:
  #   - {type: yolo, model_dir: "models/oranda_world_openvino_model", conf: 0.35, device: "intel:gpu"}
  #   - {type: vlm, provider: local_ov, model_dir: "models/vlm", device: GPU, kind: vlm, prompt: "How many [오란다 생김새] are in the tray? Answer with a number only."}
  #   - {type: opencv, min_area: 800, max_area: 8000, hsv_low: [10, 60, 80], hsv_high: [30, 255, 255]}
  #   - {type: fake}        # dry-run에서 A단계 흐름 확인용

stt:
  chain: []
  # chain:
  #   - {provider: local_ov, model_dir: "models/whisper", device: CPU, kind: whisper}
  #   - {provider: openai, model: "[전사 모델 ID]", timeout_s: 10}

voice:
  engine: none              # none | log | pyttsx3

dry_run:
  act_s: 1.0                # 스킬 하나에 걸리는 가짜 시간 (초)
  fail_rate: 0.0            # 옮기기 실패 확률 (재시도 흐름 확인용)
  samples_dir: tests/samples   # tray_N.jpg가 있으면 그 사진, 없으면 합성 이미지
  seed: null

server:
  host: 127.0.0.1
  port: 8000

logging:
  dir: logs
```

`snackbot/__init__.py`:
```python
"""과자 옮기기 로봇."""
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/conftest.py`:
```python
import copy
from pathlib import Path

import pytest

from snackbot.config import load_config

ROOT = Path(__file__).resolve().parents[1]


class FirstRng:
    """테스트용: 항상 첫 번째 후보를 고른다."""

    def choice(self, seq):
        return seq[0]


@pytest.fixture
def cfg(tmp_path):
    c = copy.deepcopy(load_config(ROOT / "config.yaml"))
    c["dry_run"]["act_s"] = 0
    c["dry_run"]["samples_dir"] = str(tmp_path / "samples")
    c["logging"]["dir"] = str(tmp_path / "logs")
    return c
```

`tests/test_config.py`:
```python
from pathlib import Path

from snackbot.config import load_config, load_env

ROOT = Path(__file__).resolve().parents[1]


def test_repo_config_has_core_sections():
    cfg = load_config(ROOT / "config.yaml")
    assert cfg["target"] == {"name": "오란다", "initial_count": 3}
    assert cfg["decision"] == {"safe_max": 3, "force_refuse": 6, "max_retry": 2}
    assert cfg["brain"]["chain"] == []
    assert cfg["vision"]["chain"] == []
    assert cfg["stt"]["chain"] == []


def test_load_env_reads_file_and_environment_wins(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text('# 주석\nA=1\nB="x y"\nC=file\n\nBROKEN\n', encoding="utf-8")
    monkeypatch.setenv("C", "env")
    env = load_env(p)
    assert env["A"] == "1"
    assert env["B"] == "x y"
    assert env["C"] == "env"
    assert "BROKEN" not in env


def test_load_env_missing_file_is_ok(tmp_path):
    assert isinstance(load_env(tmp_path / "none.env"), dict)
```

- [ ] **Step 3: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'snackbot.config'`

- [ ] **Step 4: 구현**

`snackbot/config.py`:
```python
"""config.yaml과 .env 로드."""
import os
from pathlib import Path

import yaml


def load_config(path="config.yaml"):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_env(path=".env"):
    """.env를 읽어 os.environ과 합친다. 이미 설정된 환경 변수가 우선한다."""
    env = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    env.update(os.environ)
    return env
```

- [ ] **Step 5: 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_config.py -v`
Expected: 3 passed

- [ ] **Step 6: 커밋**

```bash
git add requirements.txt pytest.ini .env.example .gitignore config.yaml snackbot/__init__.py snackbot/config.py tests/conftest.py tests/test_config.py
git commit -m "feat(snackbot): config 로드와 테스트 기반

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: provider 어댑터와 fallback 체인

**Files:**
- Create: `snackbot/providers.py`, `tests/test_providers.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `class ProviderError(Exception)`
  - 메시지 형식 `[{"role": "system"|"user", "content": str}]`, 이미지 = JPEG `bytes`
  - provider 공통: `complete(messages, max_tokens=300, image=None) -> str`, `transcribe(wav: bytes) -> str`
  - `OpenAICompat(base_url, api_key, model, timeout_s=5.0, transport=None)`
  - `AnthropicProvider(api_key, model, timeout_s=5.0, effort=None, client=None)`
  - `OpenVINOProvider(model_dir, device="CPU", kind="llm"|"vlm"|"whisper")`
  - `Member(name: str, provider)` dataclass, `Chain(members)`: `__bool__`, `describe() -> str`, `complete(...) -> (text, member_name)`, `transcribe(wav) -> (text, member_name)`; 전부 실패 시 `ProviderError`. 내부 락으로 호출을 직렬화한다.
  - `build_chain(entries: list[dict] | None, providers_cfg: dict, env: dict) -> Chain` — entry 키: `provider`, `model` 또는 `model_dir`, `timeout_s`, `effort`, `device`, `kind`. 키가 없거나 provider 이름을 모르면 경고 후 건너뜀. Member 이름은 `"{provider}:{model 또는 model_dir}"`.
  - `wav_to_float32(wav: bytes) -> list[float]`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_providers.py`:
```python
import io
import json
import wave
from types import SimpleNamespace

import httpx
import pytest

from snackbot.providers import (
    AnthropicProvider, Chain, Member, OpenAICompat, ProviderError, build_chain, wav_to_float32,
)


class Fake:
    def __init__(self, reply=None, exc=None):
        self.reply, self.exc, self.calls = reply, exc, 0

    def complete(self, messages, max_tokens=300, image=None):
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


def test_openai_compat_sends_model_auth_and_image():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "3"}}]})

    p = OpenAICompat("https://example.test/api/v1", "k", "m1", 5, transport=httpx.MockTransport(handler))
    out = p.complete([{"role": "user", "content": "몇 개?"}], max_tokens=8, image=b"\xff\xd8jpg")
    assert out == "3"
    assert seen["url"] == "https://example.test/api/v1/chat/completions"
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["model"] == "m1" and seen["body"]["max_tokens"] == 8
    parts = seen["body"]["messages"][-1]["content"]
    assert parts[0] == {"type": "text", "text": "몇 개?"}
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_openai_compat_http_error_raises():
    p = OpenAICompat("https://e.test/v1", "k", "m", 5,
                     transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(httpx.HTTPStatusError):
        p.complete([{"role": "user", "content": "x"}])


def test_openai_compat_transcribe():
    def handler(request):
        assert str(request.url).endswith("/audio/transcriptions")
        return httpx.Response(200, json={"text": "과자 옮겨줘"})

    p = OpenAICompat("https://e.test/v1", "k", "w", 5, transport=httpx.MockTransport(handler))
    assert p.transcribe(b"RIFF") == "과자 옮겨줘"


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
                     max_tokens=512, image=b"jpg")
    assert out == '{"skill": "done"}'
    assert calls["system"] == "sys"
    assert calls["model"] == "claude-opus-5-5" and calls["max_tokens"] == 512
    assert calls["output_config"] == {"effort": "low"}
    content = calls["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/jpeg"
    assert content[1] == {"type": "text", "text": "u"}


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
        "openrouter": {"type": "openai_compat", "base_url": "https://o.test/v1", "api_key_env": "OR_KEY"},
        "ollama": {"type": "openai_compat", "base_url": "http://localhost:11434/v1"},
        "local_ov": {"type": "openvino"},
    }
    entries = [
        {"provider": "openrouter", "model": "a"},
        {"provider": "nope", "model": "b"},
        {"provider": "ollama", "model": "c"},
        {"provider": "local_ov", "model_dir": "models/llm", "device": "GPU"},
    ]
    assert [m.name for m in build_chain(entries, providers, env={}).members] == [
        "ollama:c", "local_ov:models/llm"]
    assert [m.name for m in build_chain(entries, providers, env={"OR_KEY": "x"}).members] == [
        "openrouter:a", "ollama:c", "local_ov:models/llm"]
    assert not build_chain(None, providers, env={})


def test_wav_to_float32():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((16384).to_bytes(2, "little", signed=True) * 4)
    assert wav_to_float32(buf.getvalue()) == [0.5] * 4
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_providers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'snackbot.providers'`

- [ ] **Step 3: 구현**

`snackbot/providers.py`:
```python
"""LLM / VLM / STT provider 어댑터와 fallback 체인.

메시지 형식: [{"role": "system" | "user", "content": str}, ...]
이미지: JPEG bytes (complete의 image 인자)
"""
import base64
import io
import logging
import threading
import wave
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

NEEDS_KEY = {"openai_compat", "anthropic"}


class ProviderError(Exception):
    pass


class OpenAICompat:
    """OpenRouter, NVIDIA, OpenAI, Gemini(OpenAI 호환), Groq, Ollama — base_url과 키만 다르다."""

    def __init__(self, base_url, api_key, model, timeout_s=5.0, transport=None):
        self.model = model
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.http = httpx.Client(base_url=base_url.rstrip("/"), headers=headers,
                                 timeout=timeout_s, transport=transport)

    def complete(self, messages, max_tokens=300, image=None):
        msgs = [dict(m) for m in messages]
        if image is not None:
            url = "data:image/jpeg;base64," + base64.standard_b64encode(image).decode()
            msgs[-1]["content"] = [{"type": "text", "text": msgs[-1]["content"]},
                                   {"type": "image_url", "image_url": {"url": url}}]
        r = self.http.post("/chat/completions",
                           json={"model": self.model, "messages": msgs, "max_tokens": max_tokens})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""

    def transcribe(self, wav, language="ko"):
        r = self.http.post("/audio/transcriptions",
                           files={"file": ("speech.wav", wav, "audio/wav")},
                           data={"model": self.model, "language": language})
        r.raise_for_status()
        return r.json()["text"]


class AnthropicProvider:
    """Claude (공식 anthropic SDK). 재시도는 체인이 맡으므로 SDK 재시도는 끈다."""

    def __init__(self, api_key, model, timeout_s=5.0, effort=None, client=None):
        if client is None:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=0)
        self.client, self.model, self.effort = client, model, effort

    def complete(self, messages, max_tokens=300, image=None):
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        text = "\n".join(m["content"] for m in messages if m["role"] != "system")
        content = [{"type": "text", "text": text}]
        if image is not None:
            content.insert(0, {"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.standard_b64encode(image).decode()}})
        kwargs = {"model": self.model, "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": content}]}
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
    """로컬 openvino_genai. kind: llm | vlm | whisper. 처음 호출할 때 파이프라인을 만든다.
    API는 M3에서 설치된 openvino_genai 버전으로 확인한다."""

    def __init__(self, model_dir, device="CPU", kind="llm"):
        self.model_dir, self.device, self.kind = str(model_dir), device, kind
        self._pipe = None

    def _pipeline(self):
        if self._pipe is None:
            import openvino_genai as ov_genai
            cls = {"llm": ov_genai.LLMPipeline, "vlm": ov_genai.VLMPipeline,
                   "whisper": ov_genai.WhisperPipeline}[self.kind]
            self._pipe = cls(self.model_dir, self.device)
        return self._pipe

    def complete(self, messages, max_tokens=300, image=None):
        pipe = self._pipeline()
        if self.kind == "vlm":
            import cv2
            import numpy as np
            import openvino as ov
            prompt = "\n".join(m["content"] for m in messages)
            bgr = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
            rgb = np.ascontiguousarray(bgr[:, :, ::-1])
            return _text(pipe.generate(prompt, image=ov.Tensor(rgb[None]), max_new_tokens=max_tokens))
        prompt = pipe.get_tokenizer().apply_chat_template(messages, add_generation_prompt=True)
        return _text(pipe.generate(prompt, max_new_tokens=max_tokens))

    def transcribe(self, wav, language="ko"):
        return _text(self._pipeline().generate(wav_to_float32(wav), language=f"<|{language}|>",
                                               task="transcribe"))


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

    def complete(self, messages, max_tokens=300, image=None):
        return self._try(lambda p: p.complete(messages, max_tokens=max_tokens, image=image))

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
        kind = pc["type"]
        key_env = pc.get("api_key_env")
        key = env.get(key_env, "") if key_env else ""
        if kind in NEEDS_KEY and key_env and not key:
            log.warning("%s: %s 없음 (건너뜀)", pname, key_env)
            continue
        timeout = float(e.get("timeout_s", 5))
        if kind == "openai_compat":
            provider = OpenAICompat(pc["base_url"], key, e["model"], timeout)
        elif kind == "anthropic":
            provider = AnthropicProvider(key, e["model"], timeout, e.get("effort"))
        elif kind == "openvino":
            provider = OpenVINOProvider(e["model_dir"], e.get("device", "CPU"), e.get("kind", "llm"))
        else:
            log.warning("알 수 없는 provider type: %s (건너뜀)", kind)
            continue
        members.append(Member(f"{pname}:{e.get('model') or e.get('model_dir')}", provider))
    return Chain(members)
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_providers.py -v`
Expected: 12 passed

- [ ] **Step 5: 커밋**

```bash
git add snackbot/providers.py tests/test_providers.py
git commit -m "feat(snackbot): provider 어댑터와 fallback 체인

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: brain — 가드 규칙, 작업 판단, 채팅 의도

**Files:**
- Create: `snackbot/brain.py`, `tests/test_brain.py`

**Interfaces:**
- Consumes: `Chain.complete(messages, max_tokens) -> (text, name)`, `ProviderError` (Task 2)
- Produces:
  - `SKILLS = ("oranda_pickup", "dori_dori", "done")`
  - `allowed_skills(remaining: int, count: int, decision: dict) -> list[str]`
  - `allowed_intents(state: str) -> list[str]`
  - `keyword_intent(text, allowed) -> str`, `parse_n(text) -> int | None` (1~20, "개" 필수), `parse_json(text) -> dict | None`
  - `Brain(cfg, chain=None, rng=None)`
    - `.decide(remaining, count, state, speech_text=None) -> {"skill", "say", "source"}` (`source` = 응답한 provider 이름 또는 `"rules"`)
    - `.chat(text, state, count) -> {"intent", "say", "n", "source"}` (`n`은 intent가 start_task일 때만 숫자, 아니면 None)
    - `.line(key) -> str` — key: `start, oranda_pickup, oranda_pickup_tired, dori_dori, done, fail, resume, chat, busy, refusing`
  - `rng`는 `.choice(seq)`만 쓴다 (가드 4~5 구간 규칙 결정).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_brain.py`:
```python
import json

from conftest import FirstRng
from snackbot.brain import (
    Brain, allowed_intents, allowed_skills, keyword_intent, parse_json, parse_n,
)
from snackbot.providers import Chain, Member, ProviderError

D = {"safe_max": 3, "force_refuse": 6, "max_retry": 2}


class Scripted:
    def __init__(self, *replies):
        self.replies, self.messages = list(replies), None

    def complete(self, messages, max_tokens=300, image=None):
        self.messages = messages
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def make(cfg, *replies):
    chain = Chain([Member("fake", Scripted(*replies))]) if replies else None
    return Brain(cfg, chain=chain, rng=FirstRng())


def test_guard_table():
    assert allowed_skills(0, 0, D) == ["done"]
    assert allowed_skills(0, 9, D) == ["done"]
    assert allowed_skills(3, 3, D) == ["oranda_pickup"]
    assert allowed_skills(3, 4, D) == ["oranda_pickup", "dori_dori"]
    assert allowed_skills(3, 5, D) == ["oranda_pickup", "dori_dori"]
    assert allowed_skills(3, 6, D) == ["dori_dori"]


def test_rules_only_decide_uses_guard_and_lines(cfg):
    b = make(cfg)
    d = b.decide(2, 0, "WORKING")
    assert d["skill"] == "oranda_pickup" and d["source"] == "rules"
    assert d["say"] in ("오란다 하나 옮길게요!", "이번 것도 제가 할게요.")
    assert b.decide(2, 3, "WORKING")["say"] in ("으… 팔이 조금 뻐근한데요.", "이거 몇 개 남았어요?")
    assert b.decide(2, 7, "WORKING")["skill"] == "dori_dori"
    assert b.decide(0, 1, "WORKING")["skill"] == "done"


def test_llm_choice_used_in_free_zone(cfg):
    d = make(cfg, '{"skill": "dori_dori", "say": "싫어요!"}').decide(2, 4, "WORKING")
    assert d == {"skill": "dori_dori", "say": "싫어요!", "source": "fake"}


def test_guard_overrides_llm_but_keeps_say(cfg):
    d = make(cfg, '좋아요 {"skill": "dori_dori", "say": "쉬고 싶어요"}').decide(2, 1, "WORKING")
    assert d["skill"] == "oranda_pickup" and d["say"] == "쉬고 싶어요"


def test_bad_json_or_unknown_skill_falls_back_to_rules(cfg):
    for reply in ["no json here", '{"skill": "dance", "say": "춤!"}']:
        d = make(cfg, reply).decide(2, 1, "WORKING")
        assert d["skill"] == "oranda_pickup" and d["source"] == "rules"
        assert d["say"] != "춤!"


def test_long_or_empty_say_replaced(cfg):
    long = "가" * 81
    d = make(cfg, json.dumps({"skill": "oranda_pickup", "say": long}, ensure_ascii=False)).decide(2, 1, "WORKING")
    assert d["say"] != long and 0 < len(d["say"]) <= 80
    assert make(cfg, '{"skill": "oranda_pickup", "say": ""}').decide(2, 1, "WORKING")["say"]


def test_provider_error_falls_back(cfg):
    d = make(cfg, ProviderError("down")).decide(2, 1, "WORKING")
    assert d["source"] == "rules" and d["skill"] == "oranda_pickup"


def test_decide_prompt_has_target_and_allowed(cfg):
    fake = Scripted('{"skill": "oranda_pickup", "say": "네"}')
    Brain(cfg, chain=Chain([Member("f", fake)]), rng=FirstRng()).decide(2, 4, "WORKING")
    assert fake.messages[0]["role"] == "system" and "오란다" in fake.messages[0]["content"]
    assert json.loads(fake.messages[1]["content"])["allowed"] == ["oranda_pickup", "dori_dori"]


def test_parse_json():
    assert parse_json('앞말 {"a": 1} 뒷말') == {"a": 1}
    assert parse_json("[1, 2]") is None
    assert parse_json("{broken") is None


def test_allowed_intents():
    assert allowed_intents("IDLE") == ["start_task", "chat"]
    assert allowed_intents("DONE") == ["start_task", "chat"]
    assert allowed_intents("REFUSING") == ["resume", "chat"]
    assert allowed_intents("WORKING") == ["chat"]
    assert allowed_intents("ESTOP") == ["chat"]


def test_keyword_intent():
    assert keyword_intent("오란다 옮겨줘", ["start_task", "chat"]) == "start_task"
    assert keyword_intent("안녕", ["start_task", "chat"]) == "chat"
    assert keyword_intent("조금만 더 해줘", ["resume", "chat"]) == "resume"
    assert keyword_intent("옮겨줘", ["resume", "chat"]) == "chat"
    assert keyword_intent("옮겨줘", ["chat"]) == "chat"


def test_parse_n():
    assert parse_n("3개 옮겨줘") == 3
    assert parse_n("오란다 두 개만") == 2
    assert parse_n("다섯개") == 5
    assert parse_n("네, 옮겨줘") is None
    assert parse_n("과자 옮겨줘") is None
    assert parse_n("100개") is None


def test_chat_rules(cfg):
    b = make(cfg)
    r = b.chat("오란다 3개 옮겨줘", "IDLE", 0)
    assert r["intent"] == "start_task" and r["n"] == 3 and r["source"] == "rules"
    assert b.chat("안녕", "IDLE", 0)["intent"] == "chat"
    assert b.chat("안녕", "IDLE", 0)["n"] is None
    assert b.chat("조금만 더 해줘", "REFUSING", 6)["intent"] == "resume"
    assert b.chat("옮겨줘", "WORKING", 1)["say"] == "지금 일하는 중이에요! 이따 얘기해요."


def test_chat_llm_valid(cfg):
    r = make(cfg, '{"intent": "start_task", "say": "출발!", "n": 2}').chat("일 좀 해", "IDLE", 0)
    assert r == {"intent": "start_task", "say": "출발!", "n": 2, "source": "fake"}


def test_chat_llm_intent_outside_allowed_uses_keywords(cfg):
    r = make(cfg, '{"intent": "start_task", "say": "가요!", "n": 2}').chat("부탁해", "REFUSING", 6)
    assert r["intent"] == "resume" and r["say"] == "가요!" and r["n"] is None


def test_chat_llm_bad_n_falls_back_to_text(cfg):
    r = make(cfg, '{"intent": "start_task", "say": "네", "n": "many"}').chat("4개 옮겨", "IDLE", 0)
    assert r["n"] == 4
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_brain.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'snackbot.brain'`

- [ ] **Step 3: 구현**

`snackbot/brain.py`:
```python
"""판단 계층: 코드 가드 + LLM. 규칙은 docs/DECISION_LOGIC.md.
횟수는 controller가 세고, LLM은 허용된 값 안에서 고르기만 한다."""
import json
import random
import re

from .providers import ProviderError

SKILLS = ("oranda_pickup", "dori_dori", "done")
MAX_N = 20

START_WORDS = ("옮겨", "집어", "시작", "일해")
RESUME_WORDS = ("조금만", "부탁", "힘내", "한 번만", "한번만")
KOREAN_N = {"하나": 1, "한": 1, "둘": 2, "두": 2, "셋": 3, "세": 3, "넷": 4, "네": 4, "다섯": 5,
            "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10}

LINES = {
    "start": ["알겠어요! {target} 옮기러 갈게요.", "좋아요, 시작할게요!"],
    "oranda_pickup": ["{target} 하나 옮길게요!", "이번 것도 제가 할게요."],
    "oranda_pickup_tired": ["으… 팔이 조금 뻐근한데요.", "이거 몇 개 남았어요?"],
    "dori_dori": ["싫어요! 힘들어요!", "오늘은 여기까지예요…"],
    "done": ["다 옮겼어요! 칭찬해 주세요.", "{target} 정리 완료!"],
    "fail": ["어라, 놓쳤네요. 다시 해볼게요."],
    "resume": ["알겠어요… 조금만 더 할게요."],
    "chat": ["저는 과자 옮기는 로봇이에요. '과자 옮겨줘'라고 해 주세요!"],
    "busy": ["지금 일하는 중이에요! 이따 얘기해요."],
    "refusing": ["지금은 쉬는 중이에요… 달래 주면 생각해 볼게요."],
}

DECIDE_SYSTEM = """너는 과자 공장에서 {target}만 골라 옮기는 로봇팔이야.
성실하지만 금방 지치는 투덜이 성격이야. 말은 짧고 귀엽게, 한국어 1~2문장으로 해.

매번 다음 정보를 받아:
- remaining: 트레이에 남은 {target} 개수
- count: 지금까지 옮긴 횟수
- allowed: 이번에 고를 수 있는 행동 목록
- speech_text: 사람이 한 말 (없으면 null)

규칙:
- 반드시 allowed 안에서만 skill을 골라.
- count가 3쯤이면 슬슬 힘들다는 예고를 해.
- count가 4~5면 계속할지 거부할지 네가 정해. 거부하면 dori_dori.
- remaining이 0이면 done을 고르고 뿌듯해해.

출력은 JSON 한 줄만:
{"skill": "...", "say": "..."}"""

CHAT_SYSTEM = """너는 과자 공장에서 {target}만 골라 옮기는 로봇팔이야.
성실하지만 금방 지치는 투덜이 성격이야. 말은 짧고 귀엽게, 한국어 1문장으로 해.

사람이 한 말(text), 지금 상태(state), 지금까지 옮긴 횟수(count), 고를 수 있는 의도 목록(allowed)을 받아.
- start_task: 과자를 옮기라는 작업 지시
- resume: 거부 중일 때 달래거나 다시 해 달라는 부탁
- chat: 그 밖의 말
반드시 allowed 안에서 intent를 골라. 작업 지시에 개수가 있으면 n에 숫자, 없으면 null.

출력은 JSON 한 줄만:
{"intent": "...", "say": "...", "n": null}"""


def allowed_skills(remaining, count, decision):
    if remaining <= 0:
        return ["done"]
    if count <= decision["safe_max"]:
        return ["oranda_pickup"]
    if count >= decision["force_refuse"]:
        return ["dori_dori"]
    return ["oranda_pickup", "dori_dori"]


def allowed_intents(state):
    if state in ("IDLE", "DONE"):
        return ["start_task", "chat"]
    if state == "REFUSING":
        return ["resume", "chat"]
    return ["chat"]


def keyword_intent(text, allowed):
    if "resume" in allowed and any(w in text for w in RESUME_WORDS):
        return "resume"
    if "start_task" in allowed and any(w in text for w in START_WORDS):
        return "start_task"
    return "chat"


def parse_n(text):
    m = re.search(r"(\d+)\s*개", text)
    if m:
        n = int(m.group(1))
    else:
        m = re.search("(" + "|".join(sorted(KOREAN_N, key=len, reverse=True)) + r")\s*개", text)
        if not m:
            return None
        n = KOREAN_N[m.group(1)]
    return n if 0 < n <= MAX_N else None


def parse_json(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class Brain:
    def __init__(self, cfg, chain=None, rng=None):
        self.target = cfg["target"]["name"]
        self.decision = cfg["decision"]
        self.max_say = cfg["brain"].get("max_say_len", 80)
        self.max_tokens = cfg["brain"].get("max_tokens", 1024)
        self.chain = chain
        self.rng = rng or random.Random()

    def line(self, key):
        return self.rng.choice(LINES[key]).replace("{target}", self.target)

    def decide(self, remaining, count, state, speech_text=None):
        allowed = allowed_skills(remaining, count, self.decision)
        rule_skill = self.rng.choice(allowed)
        skill, say, source = rule_skill, None, "rules"
        if self.chain:
            user = json.dumps({"remaining": remaining, "count": count, "allowed": allowed,
                               "speech_text": speech_text}, ensure_ascii=False)
            data, source = self._ask(DECIDE_SYSTEM, user)
            if data is not None and data.get("skill") in SKILLS:
                skill = data["skill"] if data["skill"] in allowed else rule_skill
                say = data.get("say")
            else:
                source = "rules"
        return {"skill": skill, "say": self._valid_say(say, self._skill_line(skill, count)),
                "source": source}

    def chat(self, text, state, count):
        allowed = allowed_intents(state)
        intent, say, n, source = keyword_intent(text, allowed), None, parse_n(text), "rules"
        if self.chain:
            user = json.dumps({"text": text, "state": state, "count": count, "allowed": allowed},
                              ensure_ascii=False)
            data, source = self._ask(CHAT_SYSTEM, user)
            if data is None:
                source = "rules"
            else:
                if data.get("intent") in allowed:
                    intent = data["intent"]
                say = data.get("say")
                llm_n = data.get("n")
                if isinstance(llm_n, int) and not isinstance(llm_n, bool) and 0 < llm_n <= MAX_N:
                    n = llm_n
        if intent != "start_task":
            n = None
        return {"intent": intent, "say": self._valid_say(say, self._chat_line(intent, state)),
                "n": n, "source": source}

    def _ask(self, system, user):
        messages = [{"role": "system", "content": system.replace("{target}", self.target)},
                    {"role": "user", "content": user}]
        try:
            text, source = self.chain.complete(messages, max_tokens=self.max_tokens)
        except ProviderError:
            return None, "rules"
        return parse_json(text), source

    def _valid_say(self, say, fallback_key):
        if isinstance(say, str) and say.strip() and len(say.strip()) <= self.max_say:
            return say.strip()
        return self.line(fallback_key)

    def _skill_line(self, skill, count):
        if skill == "oranda_pickup" and count == self.decision["safe_max"]:
            return "oranda_pickup_tired"
        return skill

    @staticmethod
    def _chat_line(intent, state):
        if intent == "start_task":
            return "start"
        if intent == "resume":
            return "resume"
        return {"WORKING": "busy", "REFUSING": "refusing"}.get(state, "chat")
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_brain.py -v`
Expected: 16 passed

- [ ] **Step 5: 커밋**

```bash
git add snackbot/brain.py tests/test_brain.py
git commit -m "feat(snackbot): brain 가드 규칙, 작업 판단, 채팅 의도

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: vision — counter 체인 (A단계)

**Files:**
- Create: `snackbot/vision.py`, `tests/test_vision.py`, `tools/__init__.py`, `tools/export_yolo_world.py`

**Interfaces:**
- Consumes: `build_chain`, `ProviderError`, `Chain.complete` (Task 2)
- Produces:
  - `Count(n: int, method: str, boxes: list[list[float]] | None = None)` dataclass (boxes = `[x1, y1, x2, y2]`)
  - counter 공통: `.name: str`, `.count(frame_rgb) -> Count | None`
  - `FakeCounter(remaining_fn)`, `OpenCVCounter(min_area, max_area, hsv_low, hsv_high)`, `VlmCounter(chain, prompt, retries=1, max_tokens=64)`, `YoloCounter(model_dir, conf, device)`
  - `Vision(counters)`: `.enabled -> bool`, `.counters`, `.count(frame) -> Count | None` (예외는 다음 counter로)
  - `build_vision(vision_cfg, providers_cfg, env, remaining_fn=None) -> Vision`
  - `parse_count(text) -> int | None` (0~50), `encode_jpeg(frame_rgb, quality=85) -> bytes`
  - CLI: `python -m snackbot.vision <image> [--config config.yaml]`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_vision.py`:
```python
import cv2
import numpy as np

from snackbot.providers import Chain, Member
from snackbot.vision import (
    Count, FakeCounter, OpenCVCounter, Vision, VlmCounter, build_vision, encode_jpeg, parse_count,
)

OPENCV = dict(min_area=800, max_area=8000, hsv_low=[10, 60, 80], hsv_high=[30, 255, 255])


def blobs_image():
    img = np.full((240, 320, 3), 255, np.uint8)            # RGB
    cv2.circle(img, (60, 60), 25, (200, 120, 40), -1)      # 황갈색 → 셈
    cv2.circle(img, (200, 120), 25, (200, 120, 40), -1)    # 황갈색 → 셈
    cv2.circle(img, (280, 200), 4, (200, 120, 40), -1)     # 너무 작음
    cv2.circle(img, (120, 180), 25, (40, 80, 220), -1)     # 파란색
    return img


class Scripted:
    def __init__(self, *replies):
        self.replies, self.images = list(replies), []

    def complete(self, messages, max_tokens=300, image=None):
        self.images.append(image)
        return self.replies.pop(0)


class Boom:
    name = "boom"

    def count(self, frame):
        raise RuntimeError("x")


class Nothing:
    name = "nothing"

    def count(self, frame):
        return None


def test_opencv_counter_counts_brown_blobs_in_size_range():
    r = OpenCVCounter(**OPENCV).count(blobs_image())
    assert r.n == 2 and r.method == "opencv" and len(r.boxes) == 2


def test_parse_count():
    assert parse_count("3") == 3
    assert parse_count("There are 2 snacks.") == 2
    assert parse_count("none") is None
    assert parse_count("999") is None


def test_vlm_counter_retries_then_gives_up():
    fake = Scripted("잘 모르겠어요", "두 개")
    assert VlmCounter(Chain([Member("f", fake)]), "How many?", retries=1).count(blobs_image()) is None
    assert len(fake.images) == 2


def test_vlm_counter_parses_number_and_sends_jpeg():
    fake = Scripted("음", "4")
    assert VlmCounter(Chain([Member("f", fake)]), "How many?").count(blobs_image()) == Count(4, "vlm")
    assert fake.images[0][:2] == b"\xff\xd8"


def test_vision_chain_falls_through():
    v = Vision([Boom(), Nothing(), FakeCounter(lambda: 2)])
    assert v.enabled and v.count(None) == Count(2, "fake")
    assert Vision([Nothing()]).count(None) is None
    assert not Vision([]).enabled


def test_build_vision_types_and_empty():
    v = build_vision({"chain": [{"type": "fake"}, {"type": "opencv", **OPENCV}, {"type": "mystery"}]},
                     {}, {}, remaining_fn=lambda: 1)
    assert [c.name for c in v.counters] == ["fake", "opencv"]
    assert build_vision({"chain": []}, {}, {}).counters == []


def test_build_vision_skips_vlm_without_key_and_yolo_without_package():
    providers = {"openrouter": {"type": "openai_compat", "base_url": "https://o.test/v1",
                                "api_key_env": "OR_KEY"}}
    v = build_vision({"chain": [
        {"type": "vlm", "provider": "openrouter", "model": "m", "prompt": "How many?"},
        {"type": "yolo", "model_dir": "models/does_not_exist"},
    ]}, providers, {})
    assert v.counters == []


def test_encode_jpeg():
    assert encode_jpeg(blobs_image())[:2] == b"\xff\xd8"
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_vision.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'snackbot.vision'`

- [ ] **Step 3: 구현**

`snackbot/vision.py`:
```python
"""A단계 개수 세기: counter 체인. 프레임은 RGB uint8 HxWx3.
비어 있으면 controller가 B단계(시작 개수 + 그리퍼 판정)로 동작한다."""
import logging
import re
from dataclasses import dataclass

import cv2
import numpy as np

from .providers import ProviderError, build_chain

log = logging.getLogger(__name__)
MAX_COUNT = 50


@dataclass
class Count:
    n: int
    method: str
    boxes: list | None = None


def parse_count(text):
    m = re.search(r"\d+", text or "")
    if not m:
        return None
    n = int(m.group(0))
    return n if n <= MAX_COUNT else None


def encode_jpeg(frame_rgb, quality=85):
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR),
                           [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("JPEG 인코딩 실패")
    return buf.tobytes()


class FakeCounter:
    """dry-run 전용: 가짜 트레이의 개수를 그대로 돌려준다."""
    name = "fake"

    def __init__(self, remaining_fn):
        self.remaining_fn = remaining_fn

    def count(self, frame):
        return Count(int(self.remaining_fn()), "fake")


class OpenCVCounter:
    """색상(HSV) 범위 + 면적으로 센다. 오란다는 모양이 불규칙해 원형도는 쓰지 않는다."""
    name = "opencv"

    def __init__(self, min_area=800, max_area=8000, hsv_low=(10, 60, 80), hsv_high=(30, 255, 255)):
        self.min_area, self.max_area = min_area, max_area
        self.low, self.high = np.array(hsv_low, np.uint8), np.array(hsv_high, np.uint8)

    def count(self, frame):
        hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
        mask = cv2.inRange(hsv, self.low, self.high)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for c in contours:
            if self.min_area <= cv2.contourArea(c) <= self.max_area:
                x, y, w, h = cv2.boundingRect(c)
                boxes.append([x, y, x + w, y + h])
        return Count(len(boxes), "opencv", boxes)


class VlmCounter:
    """이미지 + 질문 → 숫자만 파싱. 실패하면 retries번 더 묻고, 그래도 안 되면 None."""
    name = "vlm"

    def __init__(self, chain, prompt, retries=1, max_tokens=64):
        self.chain, self.prompt, self.retries, self.max_tokens = chain, prompt, retries, max_tokens

    def count(self, frame):
        jpg = encode_jpeg(frame)
        for _ in range(self.retries + 1):
            try:
                text, _source = self.chain.complete([{"role": "user", "content": self.prompt}],
                                                    max_tokens=self.max_tokens, image=jpg)
            except ProviderError as e:
                log.warning("VLM 실패: %s", e)
                return None
            n = parse_count(text)
            if n is not None:
                return Count(n, "vlm")
        return None


class YoloCounter:
    """Ultralytics OpenVINO 모델 폴더 (YOLO-World 텍스트 클래스로 내보낸 것 등)."""
    name = "yolo"

    def __init__(self, model_dir, conf=0.35, device="intel:gpu"):
        from ultralytics import YOLO
        self.model = YOLO(str(model_dir), task="detect")
        self.conf, self.device = conf, device

    def count(self, frame):
        res = self.model(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), conf=self.conf,
                         device=self.device, verbose=False)[0]
        boxes = [[float(v) for v in b] for b in res.boxes.xyxy.tolist()]
        return Count(len(boxes), "yolo", boxes)


class Vision:
    def __init__(self, counters):
        self.counters = list(counters)

    @property
    def enabled(self):
        return bool(self.counters)

    def count(self, frame):
        for c in self.counters:
            try:
                r = c.count(frame)
            except Exception as e:
                log.warning("counter %s 실패: %s", c.name, e)
                continue
            if r is not None:
                return r
        return None


def build_vision(vision_cfg, providers_cfg, env, remaining_fn=None):
    counters = []
    for e in (vision_cfg or {}).get("chain") or []:
        kind = e.get("type")
        try:
            if kind == "fake":
                counters.append(FakeCounter(remaining_fn))
            elif kind == "opencv":
                counters.append(OpenCVCounter(**{k: e[k] for k in
                                                 ("min_area", "max_area", "hsv_low", "hsv_high") if k in e}))
            elif kind == "vlm":
                chain = build_chain([e], providers_cfg, env)
                if chain:
                    counters.append(VlmCounter(chain, e["prompt"], e.get("retries", 1), e.get("max_tokens", 64)))
            elif kind == "yolo":
                counters.append(YoloCounter(e["model_dir"], e.get("conf", 0.35), e.get("device", "intel:gpu")))
            else:
                log.warning("알 수 없는 counter: %s (건너뜀)", kind)
        except Exception as ex:
            log.warning("counter %s 준비 실패 (건너뜀): %s", kind, ex)
    return Vision(counters)


def main(argv=None):
    import argparse

    from .config import load_config, load_env

    p = argparse.ArgumentParser(prog="python -m snackbot.vision")
    p.add_argument("image")
    p.add_argument("--config", default="config.yaml")
    a = p.parse_args(argv)
    cfg = load_config(a.config)
    v = build_vision(cfg["vision"], cfg.get("providers", {}), load_env())
    if not v.enabled:
        print("vision.chain이 비어 있어요 (B단계). config.yaml에 counter를 추가하세요.")
        return 1
    bgr = cv2.imread(a.image)
    if bgr is None:
        print(f"이미지를 못 읽었어요: {a.image}")
        return 1
    print(v.count(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`tools/__init__.py`:
```python
"""현장 도구 (python -m tools.<이름>)."""
```

`tools/export_yolo_world.py`:
```python
"""YOLO-World에 텍스트 클래스를 지정해 OpenVINO로 내보낸다 (학습 없음).
03_openvino_workspace/10_project_logistics_counter 패턴. ultralytics가 있는 환경(로봇 노트북)에서 실행.

python -m tools.export_yolo_world --weights weights/yolov8s-worldv2.pt --classes "golden brown puffed rice snack" --out models/oranda_world.pt
"""
import argparse


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m tools.export_yolo_world")
    p.add_argument("--weights", required=True, help="YOLO-World .pt (예: yolov8s-worldv2.pt)")
    p.add_argument("--classes", nargs="+", required=True, help="찾을 물체를 묘사하는 영어 텍스트")
    p.add_argument("--out", default="models/oranda_world.pt")
    a = p.parse_args(argv)

    from ultralytics import YOLO

    model = YOLO(a.weights)
    model.set_classes(a.classes)
    model.save(a.out)
    folder = YOLO(a.out).export(format="openvino", half=True)
    print(f"OpenVINO 모델: {folder}")
    print(f"config.yaml vision.chain에 추가: {{type: yolo, model_dir: \"{folder}\"}}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_vision.py -v`
Expected: 8 passed (`test_build_vision_skips_vlm_without_key_and_yolo_without_package`는 ultralytics 미설치로 yolo가 건너뛰어져서 통과한다)

- [ ] **Step 5: 커밋**

```bash
git add snackbot/vision.py tests/test_vision.py tools/__init__.py tools/export_yolo_world.py
git commit -m "feat(snackbot): 개수 세기 counter 체인과 YOLO-World 내보내기 도구

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: skills — DrySkills (로봇 없이)

**Files:**
- Create: `snackbot/skills.py`, `tests/test_skills.py`

**Interfaces:**
- Consumes: `OpenCVCounter` (테스트에서만, Task 4)
- Produces (다음 계획의 실제 로봇 클래스도 같은 인터페이스를 지킨다):
  - `RunResult(stop_reason: str, grasped: bool, ms: int)` dataclass — `stop_reason`: `gripper_open | timeout | estop`
  - `DrySkills(cfg, rng=None)`: `.tray: int`, `.new_task(n)`, `.run(name, on_phase=None) -> RunResult` (`oranda_pickup`이면 복귀 직전 `on_phase("returning")` 호출), `.go_home()`, `.estop()`, `.release_estop()`, `.latest_frame(cam=None) -> RGB ndarray`, `.close()`
  - `synth_tray(n) -> RGB ndarray (480, 640, 3)` — 황갈색 원 n개 + 회색 원 1개

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_skills.py`:
```python
import numpy as np

from snackbot.skills import DrySkills, RunResult, synth_tray
from snackbot.vision import OpenCVCounter

OPENCV = dict(min_area=800, max_area=8000, hsv_low=[10, 60, 80], hsv_high=[30, 255, 255])


class SeqRng:
    def __init__(self, *values):
        self.values = list(values)

    def random(self):
        return self.values.pop(0)


def test_pickup_success_reduces_tray(cfg):
    cfg["dry_run"]["fail_rate"] = 0.5
    s = DrySkills(cfg, rng=SeqRng(0.9))
    s.new_task(2)
    phases = []
    r = s.run("oranda_pickup", on_phase=phases.append)
    assert r.grasped and r.stop_reason == "gripper_open"
    assert s.tray == 1 and phases == ["returning"]


def test_pickup_failure_keeps_tray(cfg):
    cfg["dry_run"]["fail_rate"] = 0.5
    s = DrySkills(cfg, rng=SeqRng(0.1))
    s.new_task(2)
    r = s.run("oranda_pickup")
    assert not r.grasped and r.stop_reason == "timeout" and s.tray == 2


def test_empty_tray_never_grasps(cfg):
    s = DrySkills(cfg, rng=SeqRng(0.9))
    s.new_task(0)
    assert not s.run("oranda_pickup").grasped


def test_dori_dori(cfg):
    assert DrySkills(cfg).run("dori_dori") == RunResult("timeout", False, 0)


def test_estop_interrupts_and_release(cfg):
    cfg["dry_run"]["act_s"] = 0.5
    s = DrySkills(cfg)
    s.estop()
    assert s.run("oranda_pickup").stop_reason == "estop"
    s.release_estop()
    s.act_s = 0
    assert s.run("dori_dori").stop_reason == "timeout"


def test_frame_is_synthetic_and_countable(cfg):
    s = DrySkills(cfg)
    s.new_task(3)
    f = s.latest_frame("front")
    assert f.shape == (480, 640, 3) and f.dtype == np.uint8
    assert OpenCVCounter(**OPENCV).count(f).n == 3
    assert OpenCVCounter(**OPENCV).count(synth_tray(0)).n == 0
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_skills.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'snackbot.skills'`

- [ ] **Step 3: 구현**

`snackbot/skills.py`:
```python
"""행동 계층. 이번 계획에는 DrySkills(로봇 없이 sleep)만 있다.
실제 로봇(physicalai)은 다음 계획(M4)에서 같은 인터페이스로 추가한다:
  tray · new_task(n) · run(name, on_phase=None) -> RunResult · go_home()
  estop() · release_estop() · latest_frame(cam) -> RGB uint8 HxWx3 · close()
"""
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

SNACK_RGB = (200, 120, 40)     # 황갈색 (OpenCV counter 기본 HSV 범위 안)
OTHER_RGB = (180, 180, 180)    # 다른 과자 (채도가 낮아 세지 않음)


@dataclass
class RunResult:
    stop_reason: str   # gripper_open | timeout | estop
    grasped: bool
    ms: int


def _ms(t0):
    return int((time.monotonic() - t0) * 1000)


def synth_tray(n):
    img = np.full((480, 640, 3), 235, np.uint8)
    cv2.rectangle(img, (60, 120), (580, 420), (120, 120, 120), 3)
    for i in range(n):
        cv2.circle(img, (130 + (i % 5) * 95, 200 + (i // 5) * 100), 28, SNACK_RGB, -1)
    cv2.circle(img, (610, 450), 20, OTHER_RGB, -1)
    cv2.putText(img, f"DRY-RUN  tray={n}", (60, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (60, 60, 60), 2)
    return img


class DrySkills:
    """로봇 없이 시간만 보낸다. 가짜 트레이(tray)의 개수를 관리한다."""

    def __init__(self, cfg, rng=None):
        dry = cfg["dry_run"]
        self.act_s = float(dry.get("act_s", 1.0))
        self.fail_rate = float(dry.get("fail_rate", 0.0))
        self.samples = Path(dry.get("samples_dir", "tests/samples"))
        self.rng = rng or random.Random(dry.get("seed"))
        self.tray = cfg["target"]["initial_count"]
        self._estop = threading.Event()
        self._cache = {}

    def new_task(self, n):
        self.tray = n

    def run(self, name, on_phase=None):
        t0 = time.monotonic()
        if not self._wait(self.act_s):
            return RunResult("estop", False, _ms(t0))
        if name != "oranda_pickup":
            return RunResult("timeout", False, _ms(t0))
        grasped = self.tray > 0 and self.rng.random() >= self.fail_rate
        if on_phase:
            on_phase("returning")
        if not self._wait(self.act_s / 2):
            return RunResult("estop", False, _ms(t0))
        if grasped:
            self.tray -= 1
        return RunResult("gripper_open" if grasped else "timeout", grasped, _ms(t0))

    def _wait(self, seconds):
        """비상정지면 False. 0.05초 단위로 확인한다."""
        end = time.monotonic() + seconds
        while True:
            if self._estop.is_set():
                return False
            left = end - time.monotonic()
            if left <= 0:
                return True
            time.sleep(min(0.05, left))

    def go_home(self):
        pass

    def estop(self):
        self._estop.set()

    def release_estop(self):
        self._estop.clear()

    def latest_frame(self, cam=None):
        path = self.samples / f"tray_{self.tray}.jpg"
        if path.exists():
            if path not in self._cache:
                self._cache[path] = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
            return self._cache[path]
        return synth_tray(self.tray)

    def close(self):
        pass
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_skills.py -v`
Expected: 6 passed

- [ ] **Step 5: 커밋**

```bash
git add snackbot/skills.py tests/test_skills.py
git commit -m "feat(snackbot): DrySkills로 로봇 없이 스킬 실행

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: voice — 비동기 TTS

**Files:**
- Create: `snackbot/voice.py`, `tests/test_voice.py`

**Interfaces:**
- Produces: `Voice(engine="none"|"log"|"pyttsx3")`: `.speak(text)` (즉시 반환, 순서대로 재생, 실패해도 예외 없음), `.close()`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_voice.py`:
```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_voice.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'snackbot.voice'`

- [ ] **Step 3: 구현**

`snackbot/voice.py`:
```python
"""TTS. speak()는 바로 반환하고 백그라운드 스레드가 순서대로 읽는다. 실패해도 예외를 내지 않는다."""
import logging
import queue
import threading

log = logging.getLogger(__name__)


class Voice:
    def __init__(self, engine="none"):
        self.engine = engine
        self._q = queue.Queue()
        self._tts = None
        self._thread = threading.Thread(target=self._worker, name="voice", daemon=True)
        self._thread.start()

    def speak(self, text):
        self._q.put(text)

    def close(self):
        self._q.put(None)
        self._thread.join(timeout=2)

    def _worker(self):
        while True:
            text = self._q.get()
            if text is None:
                return
            try:
                self._say(text)
            except Exception as e:
                log.warning("TTS 실패: %s", e)

    def _say(self, text):
        if self.engine == "log":
            print(f"[TTS] {text}", flush=True)
        elif self.engine == "pyttsx3":
            if self._tts is None:
                import pyttsx3
                self._tts = pyttsx3.init()
            self._tts.say(text)
            self._tts.runAndWait()
        elif self.engine != "none":
            raise ValueError(f"알 수 없는 TTS 엔진: {self.engine}")
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_voice.py -v`
Expected: 3 passed

- [ ] **Step 5: 커밋**

```bash
git add snackbot/voice.py tests/test_voice.py
git commit -m "feat(snackbot): 비동기 TTS

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: controller — 상태 머신과 사이클 루프

**Files:**
- Create: `snackbot/controller.py`, `tests/test_controller.py`

**Interfaces:**
- Consumes: `Brain.decide/chat/line` (Task 3), `Count` (Task 4), `RunResult` + skills 인터페이스 (Task 5), `Voice.speak` (Task 6), `Vision.enabled/count` (Task 4)
- Produces:
  - 상수 `IDLE, WORKING, REFUSING, DONE, ESTOP`
  - `Controller(cfg, brain, skills, vision=None, voice=None, log_dir=None, clock=time.time)`
  - 속성: `state, phase, count, remaining, retries, skill, vision_method, last_boxes, history (deque, 최대 50)`
  - `.subscribe(fn)` — 이벤트 dict를 받는다: `{"type": "state", ...}` (`snapshot()`과 같은 형식), `{"type": "message", "role", "text", "ts", "source"?}`, `{"type": "cycle", "n", "result", "ms"}`
  - `.snapshot() -> {"type": "state", "state", "phase", "count", "remaining", "skill", "vision_method", "thresholds": {"safe_max", "force_refuse"}}`
  - `.chat(text, source="text")`, `.command(name)` (`start | resume | estop | restart | quit`), `.notify(text)` (system 메시지)
  - `.step() -> "success" | "fail" | "refuse" | "done" | "estop" | None`
  - `.start()`, `.stop()`, `.stopped -> bool`, `.wait_stopped()`
  - 로그: `log_dir/cycles-YYYYMMDD.jsonl` 한 줄에 사이클 하나
- 결정 사항(설계 문서에 없던 것):
  - 새 작업(start_task)은 count를 0으로 시작한다.
  - DONE은 이벤트를 한 번 낸 뒤 바로 IDLE로 간다.
  - 사이클 중 예외가 나면 `phase=waiting_operator` + system 메시지 (루프는 계속).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_controller.py`:
```python
import json
import time

from conftest import FirstRng
from snackbot.brain import Brain
from snackbot.controller import Controller
from snackbot.skills import RunResult
from snackbot.vision import Count


class FakeSkills:
    def __init__(self, grasps=()):
        self.grasps, self.runs = list(grasps), []
        self.estopped, self.homed, self.tray = False, 0, None

    def new_task(self, n):
        self.tray = n

    def run(self, name, on_phase=None):
        self.runs.append(name)
        if self.estopped:
            return RunResult("estop", False, 1)
        if name == "dori_dori":
            return RunResult("timeout", False, 1)
        grasped = self.grasps.pop(0) if self.grasps else True
        if on_phase:
            on_phase("returning")
        return RunResult("gripper_open" if grasped else "timeout", grasped, 1)

    def latest_frame(self, cam=None):
        return None

    def estop(self):
        self.estopped = True

    def release_estop(self):
        self.estopped = False

    def go_home(self):
        self.homed += 1

    def close(self):
        pass


class FakeVision:
    enabled = True

    def __init__(self, *counts):
        self.counts = list(counts)

    def count(self, frame):
        return self.counts.pop(0) if self.counts else None


def make(cfg, skills=None, vision=None, log_dir=None):
    c = Controller(cfg, Brain(cfg, rng=FirstRng()), skills or FakeSkills(), vision=vision, log_dir=log_dir)
    events = []
    c.subscribe(events.append)
    return c, events


def test_snapshot_shape(cfg):
    c, _ = make(cfg)
    assert c.snapshot() == {"type": "state", "state": "IDLE", "phase": "idle", "count": 0, "remaining": 0,
                            "skill": None, "vision_method": "estimate",
                            "thresholds": {"safe_max": 3, "force_refuse": 6}}


def test_chat_starts_task_with_count(cfg):
    c, ev = make(cfg)
    c.chat("오란다 3개 옮겨줘")
    assert (c.state, c.remaining, c.count) == ("WORKING", 3, 0)
    assert [e["role"] for e in ev if e["type"] == "message"] == ["user", "robot"]
    assert c.skills.tray == 3


def test_command_start_uses_initial_count(cfg):
    c, ev = make(cfg)
    c.command("start")
    assert c.state == "WORKING" and c.remaining == cfg["target"]["initial_count"]
    assert [e["role"] for e in ev if e["type"] == "message"] == ["robot"]


def test_b_mode_full_run_to_done_then_idle(cfg):
    c, ev = make(cfg)
    c.chat("2개 옮겨줘")
    assert [c.step(), c.step(), c.step()] == ["success", "success", "done"]
    assert (c.state, c.count, c.remaining) == ("IDLE", 2, 0)
    states = [e["state"] for e in ev if e["type"] == "state"]
    assert "DONE" in states and states[-1] == "IDLE"
    assert c.step() is None


def test_refuses_at_force_refuse_and_chat_resume_resets(cfg):
    c, _ = make(cfg)
    c.chat("10개 옮겨줘")
    assert [c.step() for _ in range(7)] == ["success"] * 6 + ["refuse"]
    assert c.state == "REFUSING" and c.skills.runs[-1] == "dori_dori"
    assert c.step() is None
    c.chat("조금만 더 해줘")
    assert c.state == "WORKING" and c.count == 0


def test_command_resume_from_refusing(cfg):
    c, ev = make(cfg)
    c.chat("10개 옮겨줘")
    for _ in range(7):
        c.step()
    c.command("resume")
    assert c.state == "WORKING" and c.count == 0
    assert [e for e in ev if e["type"] == "message"][-1]["text"] == "알겠어요… 조금만 더 할게요."


def test_failures_then_waiting_operator(cfg):
    c, ev = make(cfg, FakeSkills(grasps=[False] * 3))
    c.chat("2개 옮겨줘")
    assert [c.step(), c.step(), c.step()] == ["fail", "fail", "fail"]
    assert (c.phase, c.count, c.remaining) == ("waiting_operator", 0, 2)
    assert [e for e in ev if e["type"] == "message"][-1]["role"] == "system"
    assert c.step() is None
    c.command("resume")
    assert c.phase == "idle" and c.retries == 0
    assert c.step() == "success"


def test_estop_and_restart(cfg):
    c, _ = make(cfg)
    c.chat("2개 옮겨줘")
    c.command("estop")
    assert c.state == "ESTOP" and c.skills.estopped and c.step() is None
    c.chat("과자 옮겨줘")
    assert c.state == "ESTOP"
    c.command("restart")
    assert c.state == "IDLE" and not c.skills.estopped and c.skills.homed == 1


def test_a_mode_success_by_count_decrease(cfg):
    c, _ = make(cfg, FakeSkills(grasps=[False]), vision=FakeVision(Count(3, "opencv"), Count(2, "opencv")))
    c.chat("과자 옮겨줘")
    assert c.step() == "success"
    assert (c.remaining, c.count, c.vision_method) == (2, 1, "opencv")


def test_a_mode_no_decrease_is_fail(cfg):
    c, _ = make(cfg, FakeSkills(grasps=[True]), vision=FakeVision(Count(3, "opencv"), Count(3, "opencv")))
    c.chat("과자 옮겨줘")
    assert c.step() == "fail" and c.count == 0


def test_a_mode_counter_failure_falls_back_to_b(cfg):
    c, _ = make(cfg, FakeSkills(grasps=[True]), vision=FakeVision())
    c.chat("2개 옮겨줘")
    assert c.step() == "success"
    assert (c.remaining, c.vision_method) == (1, "estimate")


def test_a_mode_zero_count_means_done(cfg):
    c, _ = make(cfg, vision=FakeVision(Count(0, "opencv")))
    c.chat("과자 옮겨줘")
    assert c.step() == "done" and c.state == "IDLE"


def test_cycle_events_and_jsonl_log(cfg, tmp_path):
    c, ev = make(cfg, log_dir=tmp_path)
    c.chat("1개 옮겨줘")
    c.step()
    cycle = [e for e in ev if e["type"] == "cycle"][0]
    assert cycle["n"] == 1 and cycle["result"] == "success" and {"llm", "act"} <= set(cycle["ms"])
    lines = next(tmp_path.glob("cycles-*.jsonl")).read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    assert record["result"] == "success" and record["skill"] == "oranda_pickup" and record["grasped"] is True


def test_history_keeps_last_50(cfg):
    c, _ = make(cfg)
    for i in range(30):
        c.chat(f"안녕 {i}")
    assert len(c.history) == 50 and c.history[-1]["role"] == "robot"


def test_background_thread_runs_to_done(cfg):
    c, ev = make(cfg)
    c.start()
    try:
        c.chat("2개 옮겨줘")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not any(
                e.get("result") == "done" for e in ev if e["type"] == "cycle"):
            time.sleep(0.01)
        assert c.state == "IDLE" and c.count == 2
    finally:
        c.stop()
    assert c.stopped
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_controller.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'snackbot.controller'`

- [ ] **Step 3: 구현**

`snackbot/controller.py`:
```python
"""상태 머신과 사이클 루프. FastAPI를 모른다 (server.py가 이 모듈을 부른다).

한 사이클(step): (A단계면 개수 세기) → brain.decide → 대사 → 스킬 실행 → 성공 판정.
성공 판정: A단계면 개수 감소, 아니면(또는 counter 실패 시) 그리퍼 쥠(grasped).
"""
import json
import logging
import threading
import time
from collections import deque
from pathlib import Path

log = logging.getLogger(__name__)

IDLE, WORKING, REFUSING, DONE, ESTOP = "IDLE", "WORKING", "REFUSING", "DONE", "ESTOP"


def _ms(t0):
    return int((time.monotonic() - t0) * 1000)


class Controller:
    def __init__(self, cfg, brain, skills, vision=None, voice=None, log_dir=None, clock=time.time):
        self.decision = cfg["decision"]
        self.initial_count = cfg["target"]["initial_count"]
        self.camera = cfg["vision"].get("camera", "front")
        self.brain, self.skills, self.voice, self.clock = brain, skills, voice, clock
        self.vision = vision if vision is not None and vision.enabled else None
        self.state, self.phase = IDLE, "idle"
        self.count = self.remaining = self.retries = self.cycle_n = 0
        self.skill = None
        self.vision_method = "estimate"
        self.last_boxes = None
        self.history = deque(maxlen=50)
        self._subs = []
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self.log_path = None
        if log_dir is not None:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            self.log_path = Path(log_dir) / time.strftime("cycles-%Y%m%d.jsonl")

    # ---- 이벤트 ----
    def subscribe(self, fn):
        self._subs.append(fn)

    def snapshot(self):
        with self._lock:
            return {"type": "state", "state": self.state, "phase": self.phase, "count": self.count,
                    "remaining": self.remaining, "skill": self.skill, "vision_method": self.vision_method,
                    "thresholds": {"safe_max": self.decision["safe_max"],
                                   "force_refuse": self.decision["force_refuse"]}}

    def _emit(self, event):
        for fn in list(self._subs):
            try:
                fn(event)
            except Exception:
                log.exception("subscriber 실패")

    def _publish(self):
        self._emit(self.snapshot())

    def _message(self, role, text, source=None):
        msg = {"type": "message", "role": role, "text": text, "ts": self.clock()}
        if source:
            msg["source"] = source
        with self._lock:
            self.history.append(msg)
        self._emit(msg)
        if role == "robot" and self.voice is not None:
            self.voice.speak(text)

    def notify(self, text):
        self._message("system", text)

    # ---- 입력 ----
    def chat(self, text, source="text"):
        text = (text or "").strip()
        if not text:
            return
        self._message("user", text, source)
        with self._lock:
            state, count = self.state, self.count
        r = self.brain.chat(text, state, count)
        self._message("robot", r["say"])
        if r["intent"] == "start_task":
            self._start_task(r.get("n"))
        elif r["intent"] == "resume":
            self._resume()

    def command(self, name):
        if name == "start":
            self._start_task(None, announce=True)
        elif name == "resume":
            self._resume(announce=True)
        elif name == "estop":
            self._estop()
        elif name == "restart":
            self._restart()
        elif name == "quit":
            self.stop()
        else:
            raise ValueError(f"알 수 없는 명령: {name}")

    def _start_task(self, n, announce=False):
        with self._lock:
            if self.state not in (IDLE, DONE):
                return False
            self.remaining = n or self.initial_count
            self.count = self.retries = 0
            self.skill, self.vision_method, self.last_boxes = None, "estimate", None
            self.state, self.phase = WORKING, "idle"
            self.skills.new_task(self.remaining)
        if announce:
            self._message("robot", self.brain.line("start"))
        self._publish()
        self._wake.set()
        return True

    def _resume(self, announce=False):
        with self._lock:
            if self.state == REFUSING:
                self.count = 0
                self.state = WORKING
            elif not (self.state == WORKING and self.phase == "waiting_operator"):
                return False
            self.retries = 0
            self.phase = "idle"
        if announce:
            self._message("robot", self.brain.line("resume"))
        self._publish()
        self._wake.set()
        return True

    def _estop(self):
        with self._lock:
            if self.state == ESTOP:
                return
            self.state, self.phase = ESTOP, "idle"
        self.skills.estop()
        self.notify("비상정지됨")
        self._publish()

    def _restart(self):
        with self._lock:
            if self.state != ESTOP:
                return False
        self.skills.release_estop()
        self.skills.go_home()
        with self._lock:
            self.state, self.phase, self.retries, self.skill = IDLE, "idle", 0, None
        self.notify("재시작: 대기 상태로 돌아왔어요")
        self._publish()
        return True

    # ---- 사이클 ----
    def _working(self):
        with self._lock:
            return self.state == WORKING and self.phase != "waiting_operator"

    def _set_phase(self, phase):
        with self._lock:
            if self.state != WORKING:
                return
            self.phase = phase
        self._publish()

    def step(self):
        """사이클 1회. 일할 상태가 아니면 None. 결과: success | fail | refuse | done | estop."""
        if not self._working():
            return None
        ms = {}
        with self._lock:
            n_before = self.remaining
        if self.vision:
            self._set_phase("counting")
            seen = self._count(ms)
            if seen is not None:
                n_before = seen
        self._set_phase("thinking")
        t0 = time.monotonic()
        d = self.brain.decide(n_before, self.count, WORKING, None)
        ms["llm"] = _ms(t0)
        if not self._working():
            return None
        with self._lock:
            self.skill = d["skill"]
        self._message("robot", d["say"])
        if d["skill"] == "done":
            return self._finish(ms, d)
        self._set_phase("acting")
        t0 = time.monotonic()
        r = self.skills.run(d["skill"], on_phase=self._set_phase)
        ms["act"] = _ms(t0)
        if r.stop_reason == "estop":
            self._log_cycle("estop", ms, d, r)
            return "estop"
        if d["skill"] == "dori_dori":
            with self._lock:
                self.state, self.phase = REFUSING, "idle"
            self._publish()
            self._log_cycle("refuse", ms, d, r)
            return "refuse"
        return self._judge(n_before, ms, d, r)

    def _count(self, ms):
        """A단계 개수 세기. 실패하면 None (그 사이클은 B로 판정)."""
        t0 = time.monotonic()
        c = self.vision.count(self.skills.latest_frame(self.camera))
        ms["vision"] = ms.get("vision", 0) + _ms(t0)
        with self._lock:
            if c is None:
                self.vision_method = "estimate"
                return None
            self.remaining, self.vision_method, self.last_boxes = c.n, c.method, c.boxes
        self._publish()
        return c.n

    def _judge(self, n_before, ms, d, r):
        with self._lock:
            if self.state != WORKING:
                return "estop"
        seen = None
        if self.vision:
            self._set_phase("counting")
            seen = self._count(ms)
        success = seen < n_before if seen is not None else r.grasped
        with self._lock:
            if success:
                self.count += 1
                self.retries = 0
                if seen is None:
                    self.remaining = max(0, n_before - 1)
            else:
                self.retries += 1
            waiting = not success and self.retries > self.decision["max_retry"]
            self.phase = "waiting_operator" if waiting else "idle"
        if waiting:
            self.notify("도와주세요! 확인한 뒤 재개를 눌러 주세요.")
        elif not success:
            self._message("robot", self.brain.line("fail"))
        self._publish()
        result = "success" if success else "fail"
        self._log_cycle(result, ms, d, r)
        return result

    def _finish(self, ms, d):
        with self._lock:
            self.state, self.phase = DONE, "idle"
        self._publish()
        self._log_cycle("done", ms, d)
        with self._lock:
            self.state, self.skill = IDLE, None
        self._publish()
        return "done"

    def _log_cycle(self, result, ms, d, r=None):
        with self._lock:
            self.cycle_n += 1
            n = self.cycle_n
            record = {"ts": self.clock(), "n": n, "result": result, "state": self.state,
                      "count": self.count, "remaining": self.remaining, "skill": d["skill"],
                      "say": d["say"], "source": d.get("source"), "vision_method": self.vision_method,
                      "stop_reason": r.stop_reason if r else None, "grasped": r.grasped if r else None,
                      "ms": ms}
        self._emit({"type": "cycle", "n": n, "result": result, "ms": dict(ms)})
        if self.log_path is not None:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ---- 스레드 ----
    def start(self):
        self._thread = threading.Thread(target=self._run, name="controller", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)

    @property
    def stopped(self):
        return self._stop.is_set()

    def wait_stopped(self):
        while not self._stop.wait(0.5):  # 타임아웃 루프: Windows에서도 Ctrl+C가 먹도록
            pass

    def _run(self):
        while not self._stop.is_set():
            if self._working():
                try:
                    self.step()
                except Exception:
                    log.exception("사이클 실패")
                    with self._lock:
                        self.phase = "waiting_operator"
                    self.notify("오류가 났어요. 로그를 확인한 뒤 재개를 눌러 주세요.")
                    self._publish()
            else:
                self._wake.wait(0.2)
                self._wake.clear()
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_controller.py -v`
Expected: 15 passed

- [ ] **Step 5: 전체 테스트**

Run: `.venv/Scripts/python -m pytest -q`
Expected: 모두 통과

- [ ] **Step 6: 커밋**

```bash
git add snackbot/controller.py tests/test_controller.py
git commit -m "feat(snackbot): controller 상태 머신과 사이클 루프 (B/A 판정)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: STT와 FastAPI 서버

**Files:**
- Create: `snackbot/stt.py`, `snackbot/server.py`, `tests/test_server.py`

**Interfaces:**
- Consumes: `build_chain`, `Chain.transcribe` (Task 2), `encode_jpeg` (Task 4), Controller의 `subscribe/snapshot/history/chat/command/notify/last_boxes` (Task 7)
- Produces:
  - `STT(chain)`: `.chain`, `.transcribe(wav: bytes) -> str`; `build_stt(stt_cfg, providers_cfg, env) -> STT | None`
  - `create_app(controller, info: dict, frame_fn=None, stt=None, static_dir="frontend") -> FastAPI`
    - `WS /ws`: 접속 시 `info` → `snapshot()` → `history` 순서로 보냄. 받는 메시지: `{"type": "chat", "text"}`, `{"type": "command", "name": "resume"|"estop"|"restart"}` (그 외 무시). controller 이벤트는 모든 접속에 브로드캐스트.
    - `POST /stt`: body = WAV bytes → `{"text"}`; STT 없음 503, 실패 502, 빈 결과면 system 메시지 "못 알아들었어요" + `{"text": ""}`; 성공하면 `controller.chat(text, "voice")`
    - `GET /stream/front`: MJPEG (`frame_fn` 없으면 404), `controller.last_boxes`를 그려서 보냄
    - `static_dir`가 있으면 `/`에 정적 파일 (html=True)
  - `mjpeg_chunk(frame_rgb, boxes=None) -> bytes`, `draw_boxes(frame_rgb, boxes) -> ndarray`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_server.py`:
```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'snackbot.server'`

- [ ] **Step 3: 구현**

`snackbot/stt.py`:
```python
"""음성 → 텍스트. provider 체인(로컬 Whisper 또는 API)을 쓴다."""
from .providers import build_chain


class STT:
    def __init__(self, chain):
        self.chain = chain

    def transcribe(self, wav):
        text, _source = self.chain.transcribe(wav)
        return text


def build_stt(stt_cfg, providers_cfg, env):
    chain = build_chain((stt_cfg or {}).get("chain"), providers_cfg, env)
    return STT(chain) if chain else None
```

`snackbot/server.py`:
```python
"""FastAPI: WebSocket(/ws), 음성(/stt), 카메라(/stream/front), frontend/ 정적 서빙.
controller를 부르기만 한다 (controller는 이 모듈을 모른다). 메시지 형식: docs/UI_DESIGN_PROMPT.md"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .vision import encode_jpeg

log = logging.getLogger(__name__)
UI_COMMANDS = ("resume", "estop", "restart")
STREAM_INTERVAL_S = 0.1


def draw_boxes(frame, boxes):
    if not boxes:
        return frame
    out = frame.copy()
    for x1, y1, x2, y2 in boxes:
        cv2.rectangle(out, (int(x1), int(y1)), (int(x2), int(y2)), (255, 200, 0), 2)
    return out


def mjpeg_chunk(frame, boxes=None):
    return b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + encode_jpeg(draw_boxes(frame, boxes)) + b"\r\n"


def create_app(controller, info, frame_fn=None, stt=None, static_dir="frontend"):
    clients = set()
    shared = {"loop": None, "queue": None}

    async def broadcast(event):
        for ws in list(clients):
            try:
                await ws.send_json(event)
            except Exception:
                clients.discard(ws)

    async def pump(queue):
        """이벤트를 들어온 순서대로 보낸다 (전송 작업이 하나라 순서가 섞이지 않는다)."""
        while True:
            await broadcast(await queue.get())

    def on_event(event):
        # controller 스레드에서 불린다 → 이벤트 루프 스레드로 넘긴다
        loop = shared["loop"]
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(shared["queue"].put_nowait, event)

    @asynccontextmanager
    async def lifespan(app):
        shared["queue"] = asyncio.Queue()
        shared["loop"] = asyncio.get_running_loop()
        task = asyncio.create_task(pump(shared["queue"]))
        yield
        shared["loop"] = None
        task.cancel()

    app = FastAPI(lifespan=lifespan)
    controller.subscribe(on_event)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        await ws.send_json(info)
        await ws.send_json(controller.snapshot())
        for msg in list(controller.history):
            await ws.send_json(msg)
        clients.add(ws)
        try:
            while True:
                msg = await ws.receive_json()
                kind = msg.get("type")
                if kind == "chat":
                    await run_in_threadpool(controller.chat, str(msg.get("text", "")), "text")
                elif kind == "command" and msg.get("name") in UI_COMMANDS:
                    await run_in_threadpool(controller.command, msg["name"])
        except WebSocketDisconnect:
            pass
        finally:
            clients.discard(ws)

    @app.post("/stt")
    async def stt_endpoint(request: Request):
        if stt is None:
            raise HTTPException(503, "STT가 설정되지 않았어요 (config.yaml stt.chain)")
        wav = await request.body()
        try:
            text = await run_in_threadpool(stt.transcribe, wav)
        except Exception as e:
            log.warning("STT 실패: %s", e)
            controller.notify("음성 인식에 실패했어요")
            raise HTTPException(502, "STT 실패")
        text = (text or "").strip()
        if not text:
            controller.notify("못 알아들었어요")
            return {"text": ""}
        await run_in_threadpool(controller.chat, text, "voice")
        return {"text": text}

    @app.get("/stream/front")
    async def stream_front():
        if frame_fn is None:
            raise HTTPException(404, "카메라 없음")

        async def frames():
            while True:
                frame = await run_in_threadpool(frame_fn)
                if frame is not None:
                    yield mjpeg_chunk(frame, controller.last_boxes)
                await asyncio.sleep(STREAM_INTERVAL_S)

        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")

    static = Path(static_dir)
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="frontend")
    return app
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_server.py -v`
Expected: 8 passed

- [ ] **Step 5: 커밋**

```bash
git add snackbot/stt.py snackbot/server.py tests/test_server.py
git commit -m "feat(snackbot): FastAPI 서버 (WebSocket, STT, MJPEG, 정적 서빙)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: 진입점, 콘솔 키, 임시 화면, 실행 확인

**Files:**
- Create: `snackbot/__main__.py`, `frontend/index.html`, `tests/test_main.py`

**Interfaces:**
- Consumes: Task 1~8 전부
- Produces:
  - `build(cfg, env, dry_run=True) -> {"controller", "skills", "voice", "stt", "info", "frame_fn"}` (`dry_run=False`면 `SystemExit` — 실제 로봇은 다음 계획)
  - `info` = `{"type": "info", "target": {"name"}, "models": {"llm", "vision", "stt", "act"}}`
  - `handle_key(ch, controller, quit_fn) -> str | None` — `s`→start, `r`→resume, 공백→estop, `q`→quit_fn()
  - `main(argv=None)` — `python -m snackbot [--dry-run] [--no-ui] [--config] [--host] [--port]`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_main.py`:
```python
import pytest

from snackbot.__main__ import build, handle_key


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
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_main.py -v`
Expected: FAIL — `ImportError` (snackbot.__main__ 없음)

- [ ] **Step 3: 구현**

`snackbot/__main__.py`:
```python
"""python -m snackbot [--dry-run] [--no-ui]

키: s 시작 · r 재개 · space 비상정지 · q 종료 (UI 버튼과 같은 동작)
"""
import argparse
import logging
import sys
import threading
from pathlib import Path

from .brain import Brain
from .config import load_config, load_env
from .controller import Controller
from .providers import build_chain
from .stt import build_stt
from .vision import build_vision
from .voice import Voice

KEYS = {"s": "start", "r": "resume", " ": "estop", "q": "quit"}


def build(cfg, env, dry_run=True):
    if not dry_run:
        raise SystemExit("실제 로봇 연결(physicalai)은 M4 계획에서 구현합니다. 지금은 --dry-run으로 실행하세요.")
    from .skills import DrySkills

    skills = DrySkills(cfg)
    providers = cfg.get("providers", {})
    llm = build_chain(cfg["brain"].get("chain"), providers, env)
    vision = build_vision(cfg["vision"], providers, env, remaining_fn=lambda: skills.tray)
    stt = build_stt(cfg.get("stt"), providers, env)
    voice = Voice(cfg.get("voice", {}).get("engine", "none"))
    controller = Controller(cfg, Brain(cfg, chain=llm), skills, vision=vision, voice=voice,
                            log_dir=cfg.get("logging", {}).get("dir", "logs"))
    info = {"type": "info", "target": {"name": cfg["target"]["name"]}, "models": {
        "llm": llm.describe(),
        "vision": " → ".join(c.name for c in vision.counters) or "추정 (시작 개수 − 성공 수)",
        "stt": stt.chain.describe() if stt else "없음",
        "act": "dry-run",
    }}
    camera = cfg["vision"].get("camera", "front")
    return {"controller": controller, "skills": skills, "voice": voice, "stt": stt, "info": info,
            "frame_fn": lambda: skills.latest_frame(camera)}


def handle_key(ch, controller, quit_fn):
    name = KEYS.get(ch.lower())
    if name == "quit":
        quit_fn()
    elif name is not None:
        controller.command(name)
    return name


def read_key():
    if sys.platform == "win32":
        import msvcrt
        return msvcrt.getwch()
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def key_loop(controller, quit_fn):
    while not controller.stopped:
        try:
            ch = read_key()
        except (EOFError, OSError):
            return
        handle_key(ch, controller, quit_fn)


def console_printer(event):
    kind = event["type"]
    if kind == "state":
        print(f"[{event['state']}/{event['phase']}] count={event['count']} "
              f"remaining={event['remaining']} ({event['vision_method']})", flush=True)
    elif kind == "message":
        print(f"  {event['role']}: {event['text']}", flush=True)
    elif kind == "cycle":
        print(f"  cycle {event['n']}: {event['result']} {event['ms']}", flush=True)


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m snackbot")
    p.add_argument("--dry-run", action="store_true", help="로봇 없이 실행")
    p.add_argument("--no-ui", action="store_true", help="웹 UI 없이 콘솔만")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    root = Path(args.config).resolve().parent
    cfg = load_config(args.config)
    env = load_env(root / ".env")
    parts = build(cfg, env, dry_run=args.dry_run)
    controller = parts["controller"]
    controller.subscribe(console_printer)
    server = None

    def quit_fn():
        controller.stop()
        if server is not None:
            server.should_exit = True

    print("키: s 시작 · r 재개 · space 비상정지 · q 종료", flush=True)
    controller.start()
    if sys.stdin.isatty():
        threading.Thread(target=key_loop, args=(controller, quit_fn), name="keys", daemon=True).start()
    try:
        if args.no_ui:
            controller.wait_stopped()
        else:
            import uvicorn

            from .server import create_app

            srv = cfg.get("server", {})
            host, port = args.host or srv.get("host", "127.0.0.1"), args.port or srv.get("port", 8000)
            app = create_app(controller, parts["info"], frame_fn=parts["frame_fn"], stt=parts["stt"],
                             static_dir=root / "frontend")
            server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
            print(f"UI: http://{host}:{port}", flush=True)
            server.run()
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop()
        parts["skills"].close()
        parts["voice"].close()


if __name__ == "__main__":
    main()
```

`frontend/index.html` (개발용 임시 화면 — Claude Design 결과물이 오면 통째로 교체):
```html
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>snackbot dev</title>
<style>
  body { font-family: system-ui, "Malgun Gothic", sans-serif; margin: 16px; background: #faf7f2; color: #222; }
  #wrap { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  #cam { width: 100%; min-height: 240px; background: #ccc; }
  #state { font-size: 1.3rem; font-weight: 700; }
  #log { height: 320px; overflow-y: auto; border: 1px solid #ddd; padding: 8px; background: #fff; }
  .user { color: #087f3c; } .robot { color: #a14d00; } .system { color: #c00; }
  body.estop { outline: 8px solid #d00; outline-offset: -8px; }
  @media (max-width: 760px) { #wrap { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<p><b>개발용 임시 화면</b> — Claude Design 결과물(index.html · app.js · style.css)로 교체한다.</p>
<div id="wrap">
  <div><img id="cam" src="/stream/front" alt="카메라 없음"></div>
  <div>
    <div id="state">연결 중…</div>
    <div id="info"></div>
    <div id="log"></div>
    <form id="f"><input id="t" placeholder="예: 오란다 3개 옮겨줘" autocomplete="off" style="width:70%"> <button>보내기</button></form>
    <p><button data-cmd="resume">재개</button> <button data-cmd="estop">비상정지</button> <button data-cmd="restart">재시작</button></p>
    <div id="cycle"></div>
  </div>
</div>
<script>
  const $ = (id) => document.getElementById(id);
  let ws;
  function add(m) {
    const d = document.createElement("div");
    d.className = m.role;
    d.textContent = `${m.role}${m.source === "voice" ? " 🎤" : ""}: ${m.text}`;
    $("log").appendChild(d);
    $("log").scrollTop = $("log").scrollHeight;
  }
  function connect() {
    ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.type === "info") {
        $("info").textContent = `대상: ${m.target.name} · ` +
          Object.entries(m.models).map(([k, v]) => `${k}=${v}`).join(" · ");
      } else if (m.type === "state") {
        $("state").textContent = `${m.state} / ${m.phase} · count ${m.count} ` +
          `(${m.thresholds.safe_max}/${m.thresholds.force_refuse}) · 남은 ${m.remaining} (${m.vision_method})`;
        document.body.classList.toggle("estop", m.state === "ESTOP");
      } else if (m.type === "message") {
        add(m);
      } else if (m.type === "cycle") {
        $("cycle").textContent = `cycle ${m.n}: ${m.result} ${JSON.stringify(m.ms)}`;
      }
    };
    ws.onclose = () => {
      $("state").textContent = "연결 끊김 — 2초 후 재연결";
      setTimeout(connect, 2000);
    };
  }
  $("f").onsubmit = (e) => {
    e.preventDefault();
    const t = $("t").value.trim();
    if (t && ws.readyState === 1) ws.send(JSON.stringify({ type: "chat", text: t }));
    $("t").value = "";
  };
  document.querySelectorAll("[data-cmd]").forEach((b) => {
    b.onclick = () => ws.readyState === 1 && ws.send(JSON.stringify({ type: "command", name: b.dataset.cmd }));
  });
  connect();
</script>
</body>
</html>
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_main.py -v`
Expected: 4 passed

- [ ] **Step 5: 실제 서버로 실행 확인 (dry-run + WebSocket)**

서버를 백그라운드로 띄우고, WebSocket으로 "2개 옮겨줘"를 보내 사이클 결과가 `success, success, done`으로 오는지, `/`가 임시 화면을 주는지 확인한다.

Run:
```bash
.venv/Scripts/python -m snackbot --dry-run --port 8765 > logs/smoke.log 2>&1 &
PID=$!
.venv/Scripts/python - <<'EOF'
import asyncio, json, time
import httpx, websockets

async def main():
    deadline = time.monotonic() + 15
    while True:
        try:
            ws = await websockets.connect("ws://127.0.0.1:8765/ws")
            break
        except OSError:
            if time.monotonic() > deadline:
                raise
            await asyncio.sleep(0.3)
    async with ws:
        await ws.send(json.dumps({"type": "chat", "text": "2개 옮겨줘"}))
        results = []
        while "done" not in results:
            m = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if m["type"] == "cycle":
                results.append(m["result"])
        print("cycles:", results)
    print("index:", "snackbot dev" in httpx.get("http://127.0.0.1:8765/").text)

asyncio.run(main())
EOF
kill $PID
```
Expected:
```
cycles: ['success', 'success', 'done']
index: True
```
그리고 `logs/cycles-*.jsonl`에 3줄이 추가된다.

- [ ] **Step 6: 전체 테스트**

Run: `.venv/Scripts/python -m pytest -q`
Expected: 모두 통과

- [ ] **Step 7: 커밋**

```bash
git add snackbot/__main__.py frontend/index.html tests/test_main.py
git commit -m "feat(snackbot): 진입점, 콘솔 키, 개발용 임시 화면

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: 문서 정리

**Files:**
- Modify: `CLAUDE.md`, `docs/DEMO_RUNBOOK.md`

**Interfaces:**
- Consumes: 실제로 동작하는 명령 (Task 9)

- [ ] **Step 1: CLAUDE.md 실행 절에 환경 준비 추가**

`CLAUDE.md`의 `## 실행` 절에서 `모든 명령은 project 루트에서 실행한다.` 줄 바로 아래에 다음을 넣는다:
~~~markdown
환경 준비 (처음 한 번):
```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Linux: .venv/bin/python
cp .env.example .env                                      # 쓸 API 키만 채운다
```
~~~
그리고 같은 절의 코드 블록에 있는 `python -m ...` 명령들의 `python`을 `.venv/Scripts/python`으로, `pytest` 줄을 `.venv/Scripts/python -m pytest`로 바꾼다.

- [ ] **Step 2: DEMO_RUNBOOK 대본의 거부 횟수를 가드 규칙에 맞춤**

`docs/DEMO_RUNBOOK.md`의
```
3. 4~6회: 로봇이 도리도리하며 거부 → 관객 반응
```
를
```
3. 4~5회째부터 거부할 수 있고, 6회째에는 반드시 도리도리하며 거부 → 관객 반응
```
로 바꾼다. 같은 파일의
```
4. 진행자: "조금만 더 해 주세요~" + `r` 키 → 로봇 재개
```
를
```
4. 진행자: 채팅이나 🎤로 "조금만 더 해 주세요~" (안 되면 `r` 키 · UI 재개 버튼) → 로봇 재개
```
로 바꾼다.

- [ ] **Step 3: 전체 테스트 한 번 더**

Run: `.venv/Scripts/python -m pytest -q`
Expected: 모두 통과

- [ ] **Step 4: 커밋**

```bash
git add CLAUDE.md docs/DEMO_RUNBOOK.md
git commit -m "docs: 실행 환경 준비, 런북 거부 횟수 정리

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## 이 계획 다음

- **M4 계획:** `docs/superpowers/plans/2026-10-22-snackbot-robot.md` — `RobotSkills`(`snackbot/robot.py`, DrySkills와 같은 인터페이스), `snackbot/motion.py`, `tools/fetch_calibration.py`, `tools/robot_probe.py`(포즈 저장·그리퍼 기준값), `__main__.build`의 `dry_run=False` 경로.
- **M3 실모델 연결:** config.yaml의 `brain.chain` / `vision.chain` / `stt.chain`에 실제 모델 ID를 넣고 `OpenVINOProvider`의 openvino_genai 호출을 설치된 버전으로 확인한다.
- **Claude Design 결과물:** `frontend/`의 임시 화면을 교체한다 (계약은 `docs/UI_DESIGN_PROMPT.md`).
