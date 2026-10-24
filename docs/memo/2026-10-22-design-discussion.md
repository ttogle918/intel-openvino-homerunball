# 설계 의논 기록 (2026-10-22)

과자 옮기기 로봇의 구조·UI·provider·로봇 연동을 정한 의논 기록. 결정의 최종 기준은
`docs/superpowers/specs/2026-10-22-chat-ui-design.md`.

| # | 주제 | 결정 |
|---|---|---|
| 1 | 디렉토리 구조 | 상태 머신을 `controller.py`로 분리 (→ 19번에서 `snackbot/` 패키지로 묶음) |
| 2 | 챗봇 역할 | 채팅으로 작업 시작, 잡담엔 캐릭터 대답, 달래기는 2단계 |
| 3 | 상태 머신 | IDLE 추가, DONE→IDLE 자동, ESTOP→IDLE |
| 4 | UI 기술 | FastAPI + 빌드 없는 정적 웹, 디자인은 Claude Design |
| 5 | 진행자 조작 | 콘솔 키 유지 + `s` 추가, UI에 같은 버튼 |
| 6 | 서버 연동 계약 | WebSocket 메시지 4종 + 명령 2종, 서버 메시지로만 그림 |
| 7 | 카메라 영상 | 넣는다 (MJPEG, 캐시 프레임 재사용) |
| 8 | 오류 처리·dry-run·테스트 | 3단계 dry-run, 로직만 자동 테스트 |
| 9 | 비상정지 | 토크 유지, 목표값 고정 |
| 10 | STT | UI 🎤 누르고 말하기 → 채팅 경로 |
| 11 | 완성 순서 | M0~M7, 자를 때는 뒤에서부터 |
| 12 | provider 교체 | 역할별 체인 + 타임아웃, LLM은 API, ACT는 로컬 |
| 13 | 대상 과자 | 오란다, 스킬 `oranda_pickup`, 이름은 config |
| 14 | 로봇 연동 | physicalai 런타임 직접 사용 (Studio 런타임 안 씀) |
| 15 | 개수 세기 방식 | YOLO-World 제로샷 → VLM → OpenCV 체인 |
| 16 | ACT가 집는데 왜 개수를 세나 | 끝·성공 판정용. B → A 순서 |
| 17 | 그리퍼 정지 조건 | "열림"이 아니라 "닫힘 → 열림" 전이 |
| 18 | 남은 일·미확인 | git 인덱스 정리, physicalai 시그니처 등 |
| 19 | 파이썬 패키지 | 루트 `.py`들을 `snackbot/`으로, 화면은 `frontend/` |
| 20 | 구현 계획과 dori-dori 결과물 | 계획 2개로 분리 (소프트웨어 → 로봇), M4는 06의 RobotRuntime 방식 |
| 21 | 음성(STT/TTS) provider | STT는 OpenVINO Whisper 로컬, TTS는 Gemini, 대화는 Claude 우선 · 이름 보리 |
| 22 | 스킬 1회 실행 · 코드 도리도리 | UI 버튼(TESTING, 루프 스레드)으로 스킬 1회, 모델이 없으면 코드 도리도리, LLM도 `dori_dori` 의도로 호출 |

---

## 1. 디렉토리 구조

**결정:** 상태 머신을 진입점에서 `controller.py`로 분리한다. (처음엔 루트에 플랫하게 두었다가 19번에서 `snackbot/` 패키지로 묶었다.)

**상세**
- UI가 생기면 같은 루프를 콘솔 키와 웹 화면 두 곳에서 조작해야 한다. 상태 머신을 진입점과 분리해 둘 다 `controller.command()`만 호출하게 했다.
- UI가 죽어도 콘솔 `space` 비상정지는 계속 동작한다.
- 파일 10개 남짓이라 2일 프로젝트 규모에서는 플랫 구조가 한눈에 들어온다.

## 2. 챗봇 역할

**결정:** 채팅으로 작업을 시작한다("과자 옮겨줘"). 잡담에는 투덜이 말투로 짧게 대답한다. 거부 상태에서 달래면 재개하는 기능은 2단계(M5).

**상세**
- 검토한 안: 달래기 입력 전용 / 보기 전용 / 자유 대화. 사용자가 "작업 시작 + 달래기"로 정했다.
- 상태별 허용 intent 안에서만 LLM이 고른다: IDLE·DONE `start_task, chat`, WORKING·ESTOP `chat`, REFUSING `resume, chat`.
- LLM이 실패하면 키워드 규칙 (옮겨·집어·시작·일해 / 조금만·부탁·힘내·한 번만).
- "3개 옮겨줘"의 개수 `n`도 함께 뽑는다 (16번 B단계의 시작 개수).

## 3. 상태 머신

**결정:** 기존 문서에서 세 가지를 바꾼다.

**상세**
- **IDLE 추가:** 채팅으로 작업을 시작하려면 대기 상태가 필요하다.
- **DONE → IDLE 자동:** 트레이를 다시 세팅하고 채팅만 하면 다시 시작할 수 있어 리허설에 편하다.
- **ESTOP → IDLE:** 기존은 ESTOP → WORKING이었다. 비상정지 후 바로 작업을 재개하는 것보다 사람이 명시적으로 다시 시작하는 쪽이 안전하다. restart 시 home_pose로 천천히 복귀한 뒤 IDLE.
- 재시도를 넘긴 실패는 새 상태를 만들지 않고 WORKING 안의 `phase = waiting_operator`로 표시한다.

## 4. UI 기술

**결정:** FastAPI 서버 + `frontend/` 정적 파일(index.html, app.js, style.css, 빌드 없음). 화면 디자인은 Claude Design에 맡긴다.

**상세**
- 처음에는 Gradio를 추천했다 (채팅 컴포넌트 내장, 스크립트가 한 번만 실행됨). Streamlit은 매번 스크립트를 다시 실행하는 구조라 로봇 스레드·하드웨어 핸들과 맞지 않아 제외.
- 사용자: "프론트엔드는 Claude Design에 시키면 되니 리스크가 아니다" → 디자인 자유도가 높은 FastAPI + 웹으로 변경.
- 빌드 없는 정적 파일을 택해 시연 PC에 Node가 필요 없다.
- 프롬프트: `docs/UI_DESIGN_PROMPT.md`. 서버 없이도 열리도록 목업 모드(`?mock`)를 요구했다.

## 5. 진행자 조작

**결정:** 콘솔 키 `s`(시작) · `r`(재개) · `space`(비상정지) · `q`(종료). UI에도 재개·비상정지·재시작 버튼.

**상세**
- 브라우저가 멈춰도 터미널에서 멈출 수 있어야 한다.
- `s`는 `--no-ui`로 띄웠을 때 채팅 없이 작업을 시작하려고 추가했다.
- `quit`는 UI에서 보내지 않는다.

## 6. 서버 연동 계약

**결정:** WebSocket `/ws` 하나로 상태와 대화를 주고받는다.

**상세**
- 서버 → 화면: `info`(과자 이름, 모델 정보), `state`(state, phase, count, remaining, skill, vision_method, thresholds), `message`(role, text, source), `cycle`(단계별 ms).
- 화면 → 서버: `chat`, `command`(resume | estop | restart).
- 화면은 서버 메시지로만 그린다. 보낸 채팅도 서버가 되돌려 준 것을 그린다 → 기록이 한 곳(controller)에만 있다.
- 접속 직후 info·state 각 1개와 최근 message 50개를 보내 새로고침해도 대화가 남는다.
- `thresholds`는 피로도 게이지용, `info`는 "ACT가 노트북 안에서 OpenVINO로 돈다"를 보여 주려고 추가했다.

## 7. 카메라 영상

**결정:** 넣는다. `GET /stream/front` MJPEG.

**상세**
- 사용자: "화면 보는 거 좋아!"
- 카메라는 캡처 스레드 하나가 소유하고 최신 프레임을 캐시한다. ACT 루프·개수 세기·스트림이 모두 캐시를 읽어 충돌하지 않는다.
- YOLO 박스가 있으면 서버가 영상 위에 그려서 보낸다.

## 8. 오류 처리 · dry-run · 테스트

**결정:** 무엇이 실패해도 루프는 규칙 fallback으로 계속 돈다. dry-run은 3단계. 시연을 깨뜨릴 수 있는 로직만 자동 테스트.

**상세**
- dry-run ① 모델·로봇 없음 (규칙만, B 판정) → ② 샘플 사진에 실제 모델 → ③ 실제 로봇.
- `dry_run.fail_rate`로 실패를 주입해 재시도·운영자 대기 흐름도 확인한다.
- 자동 테스트: 가드 표, LLM 출력 검증, chat 키워드 fallback, provider 체인, 상태 전이, B/A 판정.
- UI·하드웨어는 런북 체크리스트로 수동 확인.

## 9. 비상정지

**결정:** 토크 유지. 정지 순간의 목표값을 고정해 그 값만 유지한다.

**상세**
- 토크를 끄면 팔이 떨어져 과자·트레이와 부딪힌다.
- physical-ai-studio 문서에도 같은 패턴: 측정값을 매번 다시 보내면 중력 때문에 처진다. 목표값을 한 번 고정해 그 사본을 유지한다.
- ACT 루프와 자세 보간 이동이 매 스텝 estop 이벤트를 확인한다.

## 10. STT

**결정:** UI 🎤 누르고 말하기 → `POST /stt`(16kHz WAV) → Whisper → `controller.chat(text, source="voice")`.

**상세**
- 기존 규칙 "STT 보류"를 바꿨다.
- 계속 듣지 않는 이유: 발표장 소음, 모터 소리, 로봇 자신의 TTS가 인식되는 문제.
- 채팅과 같은 경로라 작업 시작·달래기 로직을 그대로 재사용한다.
- WAV 변환은 브라우저 JS에서 해서 서버에 ffmpeg가 필요 없다.

## 11. 완성 순서

**결정:** M0 환경 확인 → M1 핵심 흐름(B 판정) → M2 서버 + UI → M3 provider·LLM·TTS·counter(A) → M4 로봇 → M5 달래기 → M6 STT → M7 디바이스 지연 비교(선택).

**상세**
- M1~M3은 ACT 학습이 끝나기 전에(1일차) 끝낸다.
- M4가 시연의 핵심이라 2일차 맨 앞.
- 시간이 부족하면 M7 → M6 → M5 → counter 체인 순으로 자른다. M4까지 B 판정 + 채팅 시작 + r 키만으로 시연이 성립한다.
- 사용자: "STT도 넣되 완성본의 순서를 먼저 정하자."

## 12. provider 교체

**결정:** 역할(brain·vision·stt)마다 provider 체인을 두고 순서대로 시도한다. 시연 기본값은 **판단·대사 LLM = API**, **ACT = 로컬 OpenVINO**, 나머지는 상황에 맞게.

**상세**
- 어댑터 3종: `openai_compat`(OpenRouter, NVIDIA build.nvidia.com, OpenAI, Gemini, Groq, Ollama — base_url과 키만 다름), `anthropic`, `openvino`(로컬 openvino_genai).
- 키는 `.env` (git 제외).
- API 호출은 타임아웃 필수(brain 기본 5초). 체인이 전부 실패하면 규칙으로 결정 → 네트워크가 끊겨도 시연이 멈추지 않는다.
- 참고: 실습 자료의 M6 상호평가 기준(`openvino-physical-ai-lab/docs/07` §5)에 "on-device, no external API" 20점 항목이 있다. 사용자는 이를 알고 LLM은 API로 정했다 (ACT는 로컬).

## 13. 대상 과자

**결정:** 홈런볼 → **오란다**(강정류). 화면·대사는 "과자" 일반화 + `config.target.name`. 스킬 이름 `oranda_pickup`.

**상세**
- Studio 데이터셋·정책 이름: `oranda_pickup`, task 문장: `"PIck up the Snack and place it in the empty tray"` (녹화에 쓴 문장 그대로. ACT는 task 문장을 입력으로 쓰지 않는다).
- 오란다는 모양이 불규칙해서 OpenCV 판별은 원형도 대신 면적 + 색상(황갈색 HSV) 위주로.
- 과자가 바뀌어도 UI 코드는 고칠 필요가 없다 (`info.target.name`).

## 14. 로봇 연동 (physicalai)

**결정:** physical-ai-studio에서 학습·내보낸 OpenVINO ACT를 `physicalai` 런타임 패키지로 직접 실행한다. Studio의 `RobotRuntime`·`Shared*`는 쓰지 않는다.

**상세**
- 사용 API: `SO101(port, calibration, role="follower")`, `UVCCamera`, `InferenceModel(export_dir, backend="openvino", device)` + `reset()`, `select_action(obs)`.
- 정책 결과물: `exports/openvino/` = `act.xml`, `act.bin`, `manifest.json`. 정규화가 그래프에 포함돼 출력이 곧 관절 목표값.
- 관절 단위: 몸통 -100..100, 그리퍼 0..100. home/lift pose와 그리퍼 기준값 모두 이 단위.
- 루프를 직접 도는 이유: 매 스텝 그리퍼 정지 조건과 비상정지를 확인해야 한다. Windows 프로세스 간 통신 문제도 피한다.
- 카메라 이름은 학습 때와 정확히 같아야 한다 (`images.<cam>`). 캘리브레이션도 녹화 때와 같아야 한다.
- 로봇 포트는 한 프로그램만 잡을 수 있다 → 실행 전 Studio 세션을 닫는다.
- 기존 계획의 "PyTorch → OpenVINO 교체"와 추론 백엔드 분리는 필요 없어졌다. M7은 디바이스별 지연 비교로 바꿨다 (`bench_policy.py` 재사용).

## 15. 개수 세기 방식

**결정:** counter 체인: YOLO(OpenVINO) → VLM → OpenCV. 순서는 config로.

**상세**
- 사용자: "개수 세기는 모델을 로컬로 줄 수도, 아닐 수도 있다. `03`~`04` 코드 참고."
- `03_openvino_workspace/10_project_logistics_counter`: YOLO-World에 텍스트 클래스를 지정(`set_classes`) → 저장 → OpenVINO로 내보내 검출 개수를 센다. 학습이 없어 "파인튜닝 없음" 규칙과 맞고, 박스 좌표로 화면 오버레이도 된다.
- 외부에서 받은 OpenVINO 검출 모델도 같은 `yolo` 자리에 꽂을 수 있다.
- 클래스 텍스트·VLM 질문·HSV 값은 M3에서 실제 트레이 사진으로 정한다.

## 16. ACT가 집는데 왜 개수를 세나

**결정:** **B → A 순서.** B(M1): 시작 개수 + 그리퍼 쥠 판정. A(M3): counter 체인으로 개수 비교. A가 실패한 사이클은 B로 대체.

**상세**
- 사용자 질문: "physical ai studio로 학습한 ACT가 과자를 찾아 옮기는 건 하는데, 개수 세기는 정확도 때문인가?"
- 답: 찾아 집는 건 ACT가 영상만 보고 한다. 개수 세기는 정확도 때문이 아니라 ACT가 못 하는 판단 두 가지 때문이다.
  - **언제 끝낼지:** ACT는 "이제 없다"를 모른다. 0개여도 부르면 허공을 집거나 다른 과자를 집는다.
  - **성공했는지:** count는 성공 때만 올라가고 이게 거부 타이밍을 정한다.
- B: 시작 개수는 채팅의 `n` 또는 `target.initial_count`. 성공 = 닫힘 구간의 그리퍼 최솟값 ≥ `grasp_min` (빈 그리퍼는 끝까지 닫힘). 한계: 다른 과자를 집어도 성공으로 셈.
- A: 실행 전후 개수 감소로 판정. 더 확실하지만 모델·튜닝이 필요하다.
- UI는 B일 때 `vision_method = estimate`로 "추정"이라고 표시한다.

## 17. 그리퍼 정지 조건

**결정:** "그리퍼 열림"이 아니라 **"닫힘 → 열림" 전이**로 ACT를 멈춘다.

**상세**
- 홈 자세에서 그리퍼가 이미 열려 있으면 "열림 + 0.5초" 조건은 시작하자마자 걸린다.
- 닫힘 기준(`gripper_closed_below`)을 한 번 지난 뒤 열림 기준(`gripper_open_above`)을 0.5초 넘으면 정지. 안전장치로 최대 시간.
- 기준값은 `tools/gripper_stats.py`로 데이터셋에서 정한다.

## 18. 남은 일 · 미확인 사항

**상세**
- **git 인덱스:** 저장소 인덱스에 상위 폴더 전체가 삭제로 스테이징돼 있어 커밋하지 않았다. 정리가 먼저다.
- **physicalai 설치 경로:** PyPI `physicalai[so101-plugin]`(실습 자료) vs Studio가 고정한 git 커밋. 실제 시그니처, `select_action`이 uint8 HWC 이미지를 받는지.
- **카메라 이름:** 손목 카메라가 `wrist`인지 `gripper`인지, dori_dori도 같은 이름인지.
- **로봇 노트북(Ubuntu 24.04)의 OpenVINO GPU/NPU 디바이스 문자열.**
- **API 모델 ID와 키.**
- 첫 대화에서 만든 루트의 코드 뼈대(빈 함수뿐)는 19번 결정과 함께 지웠다. 구현 계획에서 `snackbot/`에 새로 만든다.

## 19. 파이썬 패키지

**결정:** 파이썬 코드를 `snackbot/` 패키지 하나로 묶고(하위 폴더 없음), 화면은 `frontend/`. 실행은 `python -m snackbot`.

**상세**
- 사용자: "py 파일들은 FastAPI에 붙는 거니까 backend처럼 묶어도 되지 않나?" → 동의. 파이썬 쪽이 10개 가까이 되니 묶는 게 경계가 잘 보인다.
- 이름 후보: `server`는 안에 `server.py`가 있어 `server/server.py`가 되고, FastAPI가 본체처럼 읽혀서 제외. `workflow`는 범위가 모호해서 제외. 프로그램이 무엇인지 드러나는 `snackbot`으로 정했다 (과자가 바뀌어도 유효).
- 하위 폴더(`api/`, `core/` 등)는 나누지 않는다. 파일 10개 규모에는 import 경로만 길어진다.
- `config.yaml`, `.env`는 현장에서 고치는 값이라 루트에 둔다.
- **의존 방향은 그대로:** `server → controller → (brain, vision, skills, voice)`. controller는 FastAPI를 모르고 `--no-ui`면 서버 없이 돈다. 패키지는 위치만 묶는다.
- `tools/`는 `python -m tools.save_pose home`처럼 실행해 `snackbot` 모듈을 재사용한다.

## 20. 구현 계획과 dori-dori 결과물

**결정:** 구현 계획을 둘로 나눈다. 이번 계획(`docs/superpowers/plans/2026-10-22-snackbot-software.md`)은 로봇 없이 끝까지 도는 소프트웨어, 다음 계획(M4)은 로봇 노트북에서 physicalai 연결. 계획은 Opus, 구현은 Sonnet 에이전트.

**상세**
- 이 PC에 physicalai가 없어 실제 시그니처를 확인할 수 없다. 추측으로 로봇 코드를 쓰지 않는다는 규칙 때문에 나눴다.
- 개발 PC는 `project/.venv` (작은 패키지만). openvino-genai·ultralytics·torch는 설치하지 않고 lazy import.
- dori-dori 결과물(`trained_model/dori_dori/exports/openvino`)의 카메라 이름은 `tower cam` / `follow cam`, 해상도 1280×720, chunk 100. `front` / wrist 가정을 바꿔야 한다.
- 06 실습은 스킬마다 runtime.yaml + `RobotRuntime.from_config` → `run(duration_s)`로 정책을 돌린다 (0.3.0 시그니처 확인됨). M4는 이 방식을 기반으로 하고, 그리퍼 정지 조건·비상정지는 `stop_event`/`callbacks`로 거는 방법을 먼저 확인한다.
- 런타임이 카메라를 잡고 있는 동안 화면 영상·개수 세기를 어떻게 할지는 M4 숙제.
- `trained_model/`은 약 1GB라 git에서 제외했다.

## 21. 음성(STT/TTS) provider

**결정:** STT는 OpenVINO Whisper 로컬(C안). TTS는 Gemini(크레딧 충전 필요), 예비로 OS TTS. 대화 LLM은 Claude → NVIDIA → 규칙, 캐릭터 이름 "보리", 대화 기억 최근 12개.

**상세**
- Claude(Anthropic)는 음성 모델이 없다. OpenAI 키는 무효(401), Gemini는 크레딧 소진(402)으로 실제 확인 못 함.
- NVIDIA: OpenAI 호환 API에는 음성 모델 없음. build.nvidia.com 음성 NIM은 Riva gRPC라 어댑터가 따로 필요하고, 한국어 TTS는 확인되지 않았다.
- OpenVINO Whisper를 고른 이유: 코드(`OpenVINOProvider(kind="whisper")`)가 이미 있고, 노트북 안에서 돌아 네트워크·크레딧에 영향받지 않으며, "on-device" 평가 항목에도 맞는다.
- 실행 순서는 `docs/memo/next-session-prompt.md` 끝의 "결정" 절. 결과는 같은 파일의 "결과" 절.
- 구현 결과 (커밋 `1284e6a`, `e006840`): `openvino-genai==2026.4.1.0`, 모델 `OpenVINO/whisper-small-int8-ov`(257MB, torch·변환 불필요), 서버 시작 때 백그라운드 워밍업.
- 측정 (이 개발 PC, Windows TTS 한국어 문장 5개): small CPU 1.2~1.8초/문장, GPU 0.43~0.49초(첫 로드 25초, CACHE_DIR `models/ov_cache`로 2~4초), 서버 워밍업 CPU 약 5.6초.
- small 채택 이유: 5개 중 4개 정확하고 "힘내 줘"→"힘내죠"여도 달래기 키워드('힘내', '부탁')가 남는다. base(85MB)는 0.4초로 빠르지만 "오랜다", "보리아", "한 번만 더"→"한 번 더"(달래기 키워드 손실)라 탈락.
- 기본은 CPU. GPU로 바꾸면 config의 device와 label을 같이 바꾼다.
- TTS: 결제를 연결하지 않은 새 프로젝트의 무료 등급 Gemini 키로 `gemini-2.5-flash-preview-tts` 동작, TTS → STT 왕복 검사 통과 (문장당 TTS 약 4초). 3.8 TTS 모델은 말투 지시문까지 읽어서 제외. 대사 소리가 나기 시작하면 동작을 시작하도록 맞춘다 (사용자 결정 A안).
- 후보 비교와 선택 이유 전체: `docs/VOICE_PROVIDERS.md`.

## 22. 스킬 1회 실행 · 코드 도리도리

**결정:** 화면 버튼 `오란다 1회` · `도리도리 1회` · `홈으로`로 학습한 정책을 한 번만 실제로 돌려 본다 (새 상태 TESTING, 대기에서만, 횟수·피로도 미반영). dori_dori 모델이 없거나 쓰기 싫으면 코드가 홈에서 몸통을 좌우로 흔든다 (`skills.dori_dori.source: auto | policy | script`). 대화 LLM도 `dori_dori` 의도로 같은 1회 실행을 부른다 (tool-use API가 아니라 기존 JSON intent, 모든 provider에서 같게).

**상세**
- 설계: `docs/superpowers/specs/2026-10-22-skill-test-and-scripted-dori-design.md`, 구현 계획: `docs/superpowers/plans/2026-10-22-skill-test.md`.
- 로봇을 움직이는 스레드는 controller 루프 하나로 유지한다 (요청 슬롯 + 깨우기). 비상정지는 테스트를 기다리지 않는다.
- 코드 도리도리는 진폭 상한 30, 관절 범위 클램프, 실행 기록에 정책 phase처럼 남는다.
- 키워드 fallback에서는 작업 시작(`start_task`)이 도리도리보다 우선한다 ("도리도리 하지 말고 옮겨줘" → 작업 시작). 사용자 결정.
