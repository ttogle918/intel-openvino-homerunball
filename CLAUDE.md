# CLAUDE.md — 과자 옮기기 로봇

이 파일은 Claude Code가 이 저장소에서 작업할 때 항상 참고하는 프로젝트 요약입니다.

## 프로젝트
- 하드웨어: SO-ARM101 (팔로워 1대, 학습용 리더 1대), 카메라 2대(외부 + 손목)
- 소프트웨어: physical-ai-studio로 학습한 ACT(OpenVINO 결과물, `physicalai` 런타임), LLM(API 또는 로컬), TTS, STT, FastAPI + 웹 UI
- 기간: 2일 해커톤
- 시연: 섞인 트레이에서 목표 과자(지금은 **오란다**)만 빈 트레이로 옮긴다. 채팅·음성으로 작업을 시키고,
  몇 번 하면 지쳐서 도리도리로 거부하며, 달래면(채팅·음성·r 키) 다시 일한다.

## 3계층 구조
| 계층 | 담당 | 구현 |
|---|---|---|
| 인식 | 끝·성공 판정 | B: 시작 개수 + 그리퍼 쥠 판정 → A: counter 체인 (YOLO-World/VLM/OpenCV) |
| 판단 | 다음 행동과 대사, 채팅 의도 | 코드 가드 + LLM (provider 체인), TTS 출력 |
| 행동 | 동작 실행 | ACT 정책 2개 (OpenVINO): `oranda_pickup`, `dori_dori` |

## 절대 규칙
1. **횟수는 코드가 센다.** LLM은 프롬프트로 받은 숫자를 해석만 한다.
2. **ACT 정책 하나 = 동작 하나.** ACT는 기억이 없으므로 순서·횟수는 controller가 관리한다.
3. **LLM 출력은 허용된 값만.** skill은 `oranda_pickup | dori_dori | done`, 채팅 intent는 상태별 허용 목록
   (`start_task | chat | resume`) 안에서만. 벗어나면 규칙으로 결정한다.
4. **STT는 UI 🎤 누르고 말하기.** 인식된 문장은 채팅과 같은 경로(`controller.chat`)로 들어간다.
5. **파인튜닝 없음.** 개수 세기는 제로샷(YOLO-World 텍스트 클래스, VLM)과 OpenCV. 외부에서 받은 OpenVINO 검출 모델은 같은 자리에 꽂을 수 있다.
6. **physicalai / LeRobot 코어 수정 금지.** 설치된 버전의 API를 확인하고 그대로 사용한다.
7. **oranda_pickup ACT는 놓기까지만.** 그리퍼 "닫힘 → 열림"을 감지하면 ACT를 멈추고,
   코드가 `lift_pose → home_pose`로 복귀시킨다. 스킬 시작 전에는 항상 `home_pose`에 있어야 한다.
8. **외부 API는 타임아웃 필수.** provider 체인이 전부 실패해도 로봇 루프는 규칙 fallback으로 계속 돈다.
9. **비상정지는 토크 유지.** 정지 순간의 목표값을 고정해 유지한다.

## 문서
- `docs/superpowers/specs/2026-10-22-chat-ui-design.md` — **현재 설계 기준** (아래 문서와 충돌하면 이 문서 우선)
- `docs/UI_DESIGN_PROMPT.md` — Claude Design 프롬프트 + 서버 연동 계약
- `docs/ARCHITECTURE.md` — 전체 구조, 시퀀스, 상태, 모듈 다이어그램 (Mermaid)
- `docs/DECISION_LOGIC.md` — 횟수 가드 규칙, LLM 프롬프트, JSON 스키마, fallback
- `docs/DATASET_GUIDE.md` — ACT 데이터셋 녹화 규칙과 체크리스트
- `docs/DEMO_RUNBOOK.md` — 시연 당일 준비와 장애 대응
- `docs/memo/` — 의논 기록

## 파일 구조 (목표)
```
.
├── CLAUDE.md
├── config.yaml
├── .env.example        # API 키 이름 (.env는 git 제외)
├── snackbot/           # 파이썬 패키지 (하위 폴더 없음)
│   ├── __main__.py     # 진입점: --dry-run, --no-ui
│   ├── config.py       # config.yaml + .env 로드
│   ├── controller.py   # 상태 머신 IDLE/WORKING/REFUSING/DONE/ESTOP, 루프 스레드, 명령
│   ├── server.py       # FastAPI: /ws, /stt, /stream/front, frontend/ 서빙
│   ├── providers.py    # openai_compat / anthropic / openvino 어댑터 + fallback 체인
│   ├── brain.py        # decide() 작업 판단, chat() 의도·대사
│   ├── vision.py       # counter 체인 (A단계)
│   ├── stt.py
│   ├── voice.py
│   └── skills.py       # physicalai: SO101, 카메라, InferenceModel, 자세 이동, 비상정지
├── frontend/           # Claude Design 결과물 (index.html, app.js, style.css)
├── tools/
│   ├── save_pose.py    # home_pose / lift_pose 관절값 저장
│   └── gripper_stats.py
├── tests/
│   └── samples/        # 트레이 사진 (dry-run용)
├── models/             # 로컬 모델 (git 제외)
├── logs/               # 사이클별 JSONL 로그 (git 제외)
└── docs/
```

## 실행
모든 명령은 project 루트에서 실행한다.
```bash
python -m snackbot --dry-run            # 로봇 없이 전체 흐름 + UI (http://localhost:8000)
python -m snackbot --dry-run --no-ui    # 콘솔만
python -m snackbot                      # 실제 로봇
python -m snackbot.vision tests/samples/tray_3.jpg   # 모듈 단독 테스트
python -m tools.save_pose home          # 현재 팔 자세를 home_pose로 저장
python -m tools.save_pose lift          # 현재 팔 자세를 lift_pose로 저장
pytest
```
- 의존 방향: `server → controller → (brain, vision, skills, voice)`. controller는 FastAPI를 모른다.
- 로봇 포트는 한 프로그램만 잡을 수 있다. 실행 전 physical-ai-studio 세션을 닫는다.

## 진행자 키 (UI 버튼과 같은 동작)
| 키 | 동작 |
|---|---|
| `s` | 작업 시작 (`--no-ui`용) |
| `r` | 재개 (count = 0, 거부 → 작업) |
| `space` | 비상정지 |
| `q` | 종료 |
