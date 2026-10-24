# CLAUDE.md — 과자 옮기기 로봇

이 파일은 Claude Code가 이 저장소에서 작업할 때 항상 참고하는 프로젝트 요약입니다.

## 프로젝트
- 하드웨어: SO-ARM101 (팔로워 1대, 학습용 리더 1대), 카메라 3대(tower · side 외부 2대 + follow 손목). 시연 노트북 = Windows 11 PC (팔로워 COM5, 리더 COM6)
- 소프트웨어: physical-ai-studio로 학습한 ACT(OpenVINO 결과물, `physicalai` 런타임), LLM(API 또는 로컬), TTS, STT(OpenVINO Whisper 로컬), FastAPI + 웹 UI
- 기간: 2일 해커톤 (**시연·발표 끝, 2026-10-25 정리 완료**). 시연 결과: 오란다 집기 12번 중 1번 성공 (집는 동작은 하지만 그리퍼가 과자를 잘 못 잡음)
- 시연: 섞인 트레이에서 목표 과자(지금은 **오란다**)만 빈 트레이로 옮긴다. 채팅·음성으로 작업을 시키고,
  전체의 절반(올림)을 옮기면 작업당 한 번 지쳐서 도리도리로 거부하며(`decision.refuse: half`, 옛 고정 임계값은 `fixed`), 달래면(채팅·음성·r 키) 다시 일한다.
  같은 과자를 두 번 연속 놓치면 투덜대고 도리도리 1회 뒤 진행자를 기다린다(`decision.max_retry: 1`, "이어서 해줘"·재개 버튼으로 다시).

## 3계층 구조
| 계층 | 담당 | 구현 |
|---|---|---|
| 인식 | 끝·성공 판정 | B: 시작 개수 + 그리퍼 쥠 판정 → A: counter 체인 (OpenCV. YOLO·VLM은 쓰지 않아 정리하며 지웠다, 같은 자리에 counter를 추가할 수 있다) |
| 판단 | 다음 행동과 대사, 채팅 의도 | 코드 가드 + LLM (provider 체인), TTS 출력 |
| 행동 | 동작 실행 | ACT 정책 2개 (OpenVINO, 시연 노트북은 CPU): `oranda_pickup`, `dori_dori` (모델이 없거나 `source: script`면 코드 도리도리) |

## 절대 규칙
1. **횟수는 코드가 센다.** LLM은 프롬프트로 받은 숫자를 해석만 한다.
2. **ACT 정책 하나 = 동작 하나.** ACT는 기억이 없으므로 순서·횟수는 controller가 관리한다.
3. **LLM 출력은 허용된 값만.** skill은 `oranda_pickup | dori_dori | done`, 채팅 intent는 상태별 허용 목록
   (`start_task | chat | resume | dori_dori`) 안에서만. 벗어나면 규칙으로 결정한다. `dori_dori`(도리도리 1회)는 대기 상태에서만, `resume`은 거부 중·두 번 놓친 뒤 대기(`waiting_operator`)에서만.
4. **STT는 UI 🎤 누르고 말하기.** 인식된 문장은 채팅과 같은 경로(`controller.chat`)로 들어간다.
5. **개수 세기는 OpenCV 규칙.** 검출 모델을 학습하지 않았다 (VLM은 계획했지만 학습 못 함). 다른 counter는 `vision.py` 체인에 같은 인터페이스(`count(frame) -> Count | None`)로 추가한다.
6. **physicalai / LeRobot 코어 수정 금지.** 설치된 버전의 API를 확인하고 그대로 사용한다.
7. **oranda_pickup ACT는 놓기까지만.** 그리퍼 "닫힘 → 열림"을 감지하면 ACT를 멈추고,
   코드가 `lift_pose → home_pose`로 복귀시킨다. 스킬 시작 전에는 항상 `home_pose`에 있어야 한다.
8. **외부 API는 타임아웃 필수.** provider 체인이 전부 실패해도 로봇 루프는 규칙 fallback으로 계속 돈다.
9. **비상정지는 토크 유지.** 정지 순간의 목표값을 고정해 유지한다.

## 문서
- `docs/superpowers/specs/2026-10-22-chat-ui-design.md` — **현재 설계 기준** (아래 문서와 충돌하면 이 문서 우선)
- `docs/superpowers/specs/2026-10-22-digital-twin-design.md` — 4분할 화면·3D 트윈·녹화 재생·실행 기록 (UI·트윈 부분은 위 문서보다 우선)
- `docs/superpowers/specs/2026-10-22-skill-test-and-scripted-dori-design.md` — 스킬 1회 실행(TESTING)·코드 도리도리·LLM 도리도리
- `docs/UI_DESIGN_PROMPT.md` — Claude Design 프롬프트 + 서버 연동 계약
- `docs/ARCHITECTURE.md` — 전체 구조, 시퀀스, 상태, 모듈 다이어그램 (Mermaid)
- `docs/DECISION_LOGIC.md` — 횟수 가드 규칙, LLM 프롬프트, JSON 스키마, fallback
- `docs/DATASET_GUIDE.md` — ACT 데이터셋 녹화 규칙과 체크리스트
- `docs/DEMO_RUNBOOK.md` — 시연 당일 준비와 장애 대응
- `docs/VOICE_PROVIDERS.md` — STT·TTS 선택 이유와 검토한 후보
- `docs/memo/` — 의논 기록

## 파일 구조
```
.
├── CLAUDE.md
├── config.yaml
├── .env.example        # API 키 이름 (.env는 git 제외)
├── snackbot/           # 파이썬 패키지 (하위 폴더 없음)
│   ├── __main__.py     # 진입점: --dry-run, --no-ui
│   ├── config.py       # config.yaml + .env 로드
│   ├── controller.py   # 상태 머신 IDLE/WORKING/REFUSING/DONE/ESTOP/TESTING, 루프 스레드, 명령
│   ├── server.py       # FastAPI: /ws, /stt, /stream/{cam}, /api/replay/{skill}, /replays, frontend/ 서빙
│   ├── providers.py    # openai_compat / anthropic / openvino 어댑터 + fallback 체인
│   ├── brain.py        # decide() 작업 판단, chat() 의도·대사
│   ├── vision.py       # counter 체인 (OpenCV v2, dry-run용 가짜 counter)
│   ├── stt.py          # STT 체인 (OpenVINO Whisper 로컬 → Gemini), 워밍업, 단독 확인 CLI
│   ├── voice.py        # TTS (Gemini → Windows Heami 예비), 합성·재생 두 스레드, 대사 소리 시작 알림
│   ├── skills.py       # DrySkills (dry-run), RunResult
│   ├── motion.py       # 그리퍼 감시, 보간 이동, 정지 신호 (physicalai 없이 테스트)
│   ├── twin.py         # 3D 트윈: 관절 normalized→라디안, 재생 에피소드(episode.json) 읽기
│   ├── recorder.py     # 실행 기록: 정책 phase 관절값·프레임 → logs/runs/ (백그라운드 저장)
│   ├── wincam.py       # Windows 카메라 목록 보정 (pynokhwa JSON 역슬래시 버그), 카메라 열기 전 호출
│   └── robot.py        # 실제 로봇: RobotRuntime 하나 + 동작 출처 교체, 비상정지 세대, warmup
├── frontend/           # Claude Design 결과물 (index.html, app.js, style.css) + twin.js(3D)
│   ├── vendor/         # three@0.186.1, urdf-loader@0.13.1 고정 파일 (import map)
│   └── twin/so101/     # SO-101 URDF + STL (Apache-2.0)
├── tools/
│   ├── fetch_calibration.py   # Studio runtime-config → calibration/follower.yaml (GET만)
│   ├── robot_probe.py         # 관절값 보기(watch), home/lift 포즈 저장(save)
│   ├── fetch_replays.py       # Studio 녹화 에피소드 → replays/<스킬>/ (GET만, dry-run 재생용)
│   └── cameras.py             # 카메라 목록·시리얼·사진 1장 → config cameras 예시
├── tests/
│   └── samples/        # 트레이 사진 (dry-run용)
├── models/             # 로컬 모델 (git 제외)
├── logs/               # 사이클별 JSONL 로그 (git 제외)
├── replays/            # dry-run 재생 데이터 replays/<스킬>/episode.json (git 제외)
└── docs/
```

## 실행
모든 명령은 project 루트에서 실행한다.
환경 준비 (처음 한 번):
```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Linux: .venv/bin/python
cp .env.example .env                                      # 쓸 API 키만 채운다
.venv/Scripts/python -m pip install huggingface_hub       # STT 모델 받기용
.venv/Scripts/hf download OpenVINO/whisper-small-int8-ov --local-dir models/whisper-small   # 257MB (Linux: .venv/bin/hf)
```
```bash
.venv/Scripts/python -m snackbot --dry-run            # 로봇 없이 전체 흐름 + UI (http://localhost:8000)
.venv/Scripts/python -m snackbot --dry-run --no-ui    # 콘솔만
.venv/Scripts/python -m snackbot                      # 실제 로봇
.venv/Scripts/python -m snackbot.vision tests/samples/tray_3.jpg   # 모듈 단독 테스트
.venv/Scripts/python -m snackbot.stt a.wav b.wav      # Whisper 확인 (워밍업 후 파일마다 텍스트·source·ms)
.venv/Scripts/python -m pytest
```
로봇 노트북 = 이 Windows PC, 파이썬은 `.venv/Scripts/python` (처음 연결 순서 전체는 `docs/DEMO_RUNBOOK.md` 2-2절):
```bash
.venv/Scripts/python -m pip install -r requirements.txt -r requirements-robot.txt   # physicalai 0.3.0 (Linux: .venv/bin/python)
.venv/Scripts/python -m tools.fetch_calibration --studio http://192.168.0.6:7860 --project <id> --env <id>
.venv/Scripts/python -m tools.robot_probe watch           # 관절값 보기 (토크 끔, 그리퍼 기준값 정하기)
.venv/Scripts/python -m tools.robot_probe save home       # 현재 팔 자세를 home_pose로 (lift도 같은 방법)
.venv/Scripts/python -m snackbot.robot home               # 홈으로 이동 (스킬 하나만: dori_dori | dori_script | oranda_pickup)
.venv/Scripts/python -m tools.cameras                     # 카메라 번호·시리얼·사진 (cameras/)
.venv/Scripts/python -m tools.fetch_replays --studio http://192.168.0.6:7860 --skill oranda_pickup   # 녹화 받기
```
- 모델 폴더(`skills.<이름>.export_dir`)가 없는 정책은 건너뛴다 (과자 모델 없이 `home`·`dori_dori` 확인 가능).
- 의존 방향: `server → controller → (brain, vision, skills, voice)`. controller는 FastAPI를 모른다.
- 로봇 포트는 한 프로그램만 잡을 수 있다. 실행 전 physical-ai-studio 세션을 닫는다.
- 시연 노트북(Windows) 장치: 팔로워 `COM5`, 리더 `COM6`, 카메라 1 = follow(손목) · 2 = tower · 3 = side (0 = 내장, 쓰지 않음). 카메라는 USB 포트를 나눠 꽂는다 (NV12 비압축이라 한 경로에 두 대면 시간 초과). 정책은 CPU (`skills.device`).
- 개수 세기 ROI는 `python -m snackbot.vision <사진> --blobs`로 맞춘다. 남은 한계: 제어 루프 11~13 Hz(목표 30, 화면을 여러 창에서 열면 4 Hz), pickup 덜 학습(5 epoch), 모델 도리도리 과적합(데이터 부족, 시연은 코드 도리도리) → 상세는 `README.md`, `docs/PROGRESS_REPORT.html`.

## 진행자 키 (UI 버튼과 같은 동작)
| 키 | 동작 |
|---|---|
| `s` | 작업 시작 (`--no-ui`용) |
| `r` | 재개 (count = 0, 거부 → 작업) |
| `space` | 비상정지 |
| `h` | 재시작 (비상정지 해제 → 홈 복귀 → 대기) |
| `q` | 종료 |

UI에는 **스킬 테스트** 버튼(`오란다 1회` · `모델 도리도리 1회` · `코드 도리도리 1회` · `홈으로`)도 있다. 대기 상태에서만 눌리고, 실제 로봇이면 진짜 팔이 움직인다 (콘솔 키는 없다). 채팅·🎤 "도리도리 해 봐"도 같은 1회 실행이다.
