# 음성 인식(STT) · 음성 합성(TTS) 선택 기록

2026-10-22 기준. 무엇을 골랐고, 어떤 후보를 검토했으며, 왜 그렇게 정했는지 적는다.
설정은 `config.yaml`의 `stt.chain`, `voice` 절에 있고, 바꿀 때 코드 수정은 필요 없다.

## 결론

| 역할 | 선택 | 실행 위치 | 예비 |
|---|---|---|---|
| STT | **OpenVINO Whisper small (int8)**, `openvino-genai` 2026.4.1, CPU | 노트북 안 (온디바이스) | Gemini `gemini-3.5-flash-lite` (오디오 입력 채팅) |
| TTS | **Gemini `gemini-2.5-flash-preview-tts`**, 목소리 `Leda`, 무료 등급 키 | Google API | 없음 (실패하면 소리 없이 진행, 채팅 글은 그대로) |
| 대화 LLM (참고) | Claude `claude-opus-5-5` (effort low) → NVIDIA → 규칙 | API | 규칙 대사 |

음성은 UI의 🎤를 누르고 말하는 방식이다 (항상 듣지 않는다 — 발표장 소음, 모터 소리, 로봇 자신의 TTS를 다시 알아듣는 문제 때문. 의논 기록 10번).

---

## 1. STT: 검토한 후보

| 후보 | 결과 | 탈락·채택 이유 |
|---|---|---|
| OpenAI `gpt-4o-mini-transcribe` | 키 401 (무효) | 유료 API, 키 없음. 체인 예비로 주석만 남김 |
| Gemini 오디오 입력 (`gemini-3.5-flash-lite`) | 처음 키는 402 (크레딧 없음). 무료 키로는 STT를 아직 시험하지 않음 | 네트워크·한도에 좌우됨. **예비**로 체인 2번째에 둠 |
| NVIDIA API (`integrate.api.nvidia.com`) | OpenAI 호환 모델 83개 중 STT 없음 | 지금 코드가 쓰는 곳에 음성 모델이 없다 |
| NVIDIA 음성 NIM (build.nvidia.com: Parakeet, Canary, Whisper Large v3) | Riva gRPC 방식 (`grpc.nvcf.nvidia.com` + function-id) | 새 어댑터·`nvidia-riva-client` 필요. 한국어는 Whisper Large v3만 (Parakeet는 en/vi/es/zh) |
| Claude | 음성 모델 없음 | — |
| **OpenVINO Whisper 로컬** | 동작 확인 | **채택** (아래 이유) |

### OpenVINO Whisper를 고른 이유
1. **네트워크·크레딧과 무관하다.** 시연장 와이파이가 끊기거나 API 한도가 차도 음성 명령은 된다.
2. **온디바이스 평가 항목에 맞는다.** 상호평가 기준(`openvino-physical-ai-lab/docs/07` §5)의 "on-device, no external API" 항목. ACT와 STT가 노트북 안에서 OpenVINO로 돈다고 보여 줄 수 있고, UI 모델 정보에 `Whisper small · OpenVINO · CPU`로 표시된다.
3. **코드가 이미 있었다.** `OpenVINOProvider(kind="whisper")`가 설계 때부터 있었고, 설치한 2026.4.1에서 수정 없이 돌았다.
4. **설치가 가볍다.** `openvino-genai`(Windows 다운로드 약 91MB)와 Hugging Face `OpenVINO` 조직의 변환된 모델만 받으면 된다. torch·변환 과정 없음. physicalai 0.3.0의 `openvino>=2026.4.0`과 버전이 맞는다.

### 모델 크기: small을 고른 이유

후보 (HF `OpenVINO/whisper-*-int8-ov`): base 85MB · **small 257MB** · medium 784MB · large-v3-turbo int4 478MB / int8 828MB.

측정: 개발 PC(Windows), Windows TTS 한국어 음성으로 만든 문장 5개.

| 모델 | CPU 1문장 | GPU 1문장 | 인식 결과 |
|---|---|---|---|
| base | 0.41~0.49초 | 0.16~0.23초 | "오**랜**다", "보리**아**", "한 번**만** 더" → "한 번 더" |
| **small** | 1.4~1.6초 | 0.43~0.49초 | 5개 중 4개 정확. "힘내 줘" → "힘내죠" 1개 |

- base는 빠르지만 **"한 번만" 같은 달래기 키워드를 놓친다.** 규칙 fallback이 키워드로 의도를 고르므로 치명적이다. small은 틀려도 키워드("힘내", "부탁")가 남는다.
- medium·large는 노트북 CPU에서 몇 초 이상 걸릴 것으로 보여 받지 않았다. 필요하면 같은 방법으로 받아 `model_dir`만 바꾸면 된다.
- 기본은 **CPU**. GPU는 더 빠르지만 처음 로드(컴파일)가 25초 → `cache_dir: models/ov_cache`로 2~4초. 노트북에서 비교 후 정한다 (`device`와 `label`을 같이 바꾼다).
- 서버 시작 때 백그라운드에서 워밍업한다 (CPU 약 5.6초). 첫 🎤가 느리지 않게.

---

## 2. TTS: 검토한 후보

| 후보 | 결과 | 탈락·채택 이유 |
|---|---|---|
| OpenAI `gpt-4o-mini-tts` | 키 401 | 유료, 키 없음 |
| Gemini TTS, 처음 키 | 402 (선불 크레딧 소진) | 결제가 연결된 프로젝트의 키였다 |
| **Gemini `gemini-2.5-flash-preview-tts`, 무료 키** | 동작, 왕복 검사 통과 | **채택** (아래 이유) |
| Gemini `gemini-3.8-flash-tts` / `-flash-lite-tts` | 동작하지만 **말투 지시문("귀엽고 금방 지치는 … 말해")까지 소리 내어 읽음**. 4.6~5.0초 / 3.0~3.8초 | 지시문을 다른 방식으로 넘겨야 하고 빠르지도 않다 |
| NVIDIA 음성 NIM (Magpie 등) | Riva gRPC | 새 어댑터 필요, 한국어 TTS 확인 못 함 |
| pyttsx3 (OS TTS) | 미설치 | Windows는 한국어 Heami 음성이 괜찮지만 시연 노트북(Ubuntu)은 espeak-ng라 기계음 |
| edge-tts (Edge 브라우저 읽어주기) | 동작 (한국어 SunHi/InJoon/Hyunsu, 1문장 1.1초) | 키 없이 무료지만 **비공식 엔드포인트**라 언제든 막힐 수 있음. mp3라 재생 코드 추가 필요 |
| Supertonic 3 (Supertone, 99M, 31개 언어, ONNX) | 조사만 | 한국어 지원, OpenVINO로 온디바이스 가능 → **온디바이스 점수를 노릴 때의 다음 후보**. 예제가 ONNX Runtime용이라 이식 작업, OpenRAIL-M 라이선스 |
| MeloTTS-Korean | 조사만 | OpenVINO 변환 글은 영어·중국어만. 한국어 변환은 확인 안 됨, torch 필요 |

### Gemini 2.5 Flash TTS를 고른 이유
1. **무료로 바로 된다.** 공식 가격표상 Flash 계열 TTS는 무료 등급이 있다. 결제를 연결하지 않은 새 Google 프로젝트에서 AI Studio 키를 만들면 무료 등급으로 돈다.
2. **코드 변경이 없다.** 이미 붙어 있던 엔진이다 (`voice.engine: gemini`).
3. **목소리·말투 지시가 된다.** "귀엽고 금방 지치는 투덜이 로봇 보리" 캐릭터를 프롬프트로 지정한다.
4. **왕복 검사를 통과했다.** Gemini가 만든 음성을 로컬 Whisper가 다시 맞게 알아들었다:

| 원문 | TTS | STT | Whisper가 들은 문장 |
|---|---|---|---|
| 과자 세 개 옮겨줘 | 4.9초 | 0.9초 | 과자 3개 옮겨줘 |
| 조금만 더 힘내 줘, 부탁이야 | 4.7초 | 1.1초 | 조금만 더 힘내줘, 부탁이야. |
| 오란다 다 옮겼어? 고마워 보리야 | 3.7초 | 1.6초 | 오란다 다 옮겼어. 고마워 보리야. |

### 알고 쓰는 약점
- **느리다:** 문장당 약 4초. 그래서 **대사 소리가 나기 시작하면 동작을 시작**하도록 맞춘다 (사이클마다 약 4초 늘어남. TTS 실패·`voice.sync_timeout_s` 초과면 기다리지 않고 동작). 소리보다 동작이 먼저 끝나 "싫어!"가 도리도리 뒤에 들리는 문제를 막는다.
- **무료 등급 하루 한도를 모른다:** 공식 문서에서 숫자를 찾지 못했다. 리허설을 많이 하는 날은 AI Studio의 Rate limits 화면을 확인한다. 한도에 걸리면 소리만 안 나고 시연은 계속된다 (채팅 글은 나온다).
- **인터넷이 필요하다.** 끊기면 소리만 빠진다.
- 예비 TTS는 두지 않기로 했다 (사용자 결정). 필요해지면 후보는 edge-tts(빠르게) 또는 Supertonic 3(온디바이스).

---

## 3. 현장 주의

- 이 PC에서 예전(무효) `GEMINI_API_KEY`를 Windows 환경 변수에서 지웠다. 지우기 전에 열린 터미널·프로그램은 예전 값을 물려받아 `.env`보다 우선하므로 **새 터미널에서 실행**한다.
- 노트북 준비: `openvino-genai` 설치, `hf download OpenVINO/whisper-small-int8-ov --local-dir models/whisper-small`, `python -m snackbot.stt <wav>`로 확인 (`docs/DEMO_RUNBOOK.md` 2-1절).

## 근거 커밋
- `1284e6a` STT를 OpenVINO Whisper 로컬로, 서버 시작 때 워밍업
- `e006840` Whisper generate 동시 실행 방지 락
- `a7f14ac`, `ee5a12b` 문서·진행 보고서
- 의논 기록: `docs/memo/2026-10-22-design-discussion.md` 10번(🎤 방식), 21번(음성 provider)
