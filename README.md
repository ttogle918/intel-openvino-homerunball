# 과자 옮기는 로봇팔, 보리

Intel OpenVINO 과정 2일 해커톤 팀 프로젝트입니다.

SO-ARM101 로봇팔이 여러 과자가 섞인 트레이에서 오란다만 골라 빈 트레이로 옮깁니다. 작업은 채팅이나 음성으로 시킵니다.
보리는 성실하지만 금방 지치는 캐릭터입니다. 절반쯤 옮기면 고개를 저으며(도리도리) 그만하겠다고 하고, "조금만 더 해 줘"라고 달래면 다시 일합니다.

![화면](docs/img/ui_screen.jpg)

## 어떻게 돌아가나

```
채팅 / 🎤 음성(Whisper)
        │
        ▼
 카메라로 오란다 개수 세기 (OpenCV)
        │
        ▼
 다음 행동 정하기: 횟수 규칙은 코드, 대사는 LLM
        │
        ├─ 옮기기   → ACT 정책 oranda_pickup (OpenVINO)
        ├─ 거부     → 도리도리
        └─ 다 옮김  → 완료
        │
        ▼
 다시 세어서 성공했는지 확인 → 반복
```

- 집고 놓는 동작은 ACT 정책이 카메라 영상만 보고 합니다. 놓은 뒤 홈 자세로 돌아오는 건 코드가 맡습니다.
- 몇 개를 옮겼고 언제 거부할지는 코드가 셉니다. LLM은 말투와 대사만 정하고, 정해진 값 밖의 행동은 고를 수 없습니다.
- 같은 과자를 두 번 연속 놓치면 투덜대고 기다립니다. "이어서 해줘"라고 하면 다시 시도합니다.
- 비상정지(space 또는 화면 버튼)를 누르면 토크를 유지한 채 그 자리에 멈춥니다.

## 사용한 것

| 부분 | 사용한 것 |
|---|---|
| 로봇 | SO-ARM101 (팔로워 1대, 데이터 녹화용 리더 1대), 카메라 3대 (위 · 옆 · 손목) |
| 동작 모델 | ACT 2개 (`oranda_pickup`, `dori_dori`), physical-ai-studio로 학습해 OpenVINO로 내보냄, `physicalai` 런타임으로 CPU 실행 |
| 개수 세기 | OpenCV (색 · 면적 규칙, 프레임 5장 중앙값) |
| 대화 | Claude → NVIDIA API → 규칙 대사 순으로 시도 |
| 음성 | STT: OpenVINO Whisper small (노트북 안), TTS: Gemini (안 되면 Windows 음성) |
| 화면 | FastAPI + 웹 UI (카메라 3개, 3D 팔, 채팅, 스킬 테스트 버튼) |

## 역할

| 담당 | 한 일 |
|---|---|
| 팀원 A · B · C (공동) | 데이터셋 녹화와 정리 (오란다 옮기기, 도리도리) |
| physical-ai-studio | ACT 모델 학습과 OpenVINO 내보내기 |
| ttogle918 | 전체 워크플로우 설계, 로봇 제어 · 판단 · 음성 · 웹 UI 소프트웨어, 현장 연결과 튜닝, 저장소 관리 |

## 실행

Windows 기준입니다. Ubuntu는 `.venv/Scripts/python` 대신 `.venv/bin/python`을 씁니다.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
cp .env.example .env          # 쓰는 API 키만 채운다 (없으면 규칙 대사로 돈다)

.venv/Scripts/python -m snackbot --dry-run    # 로봇 없이 전체 흐름 확인 (http://localhost:8000)
```

실제 로봇:

```bash
.venv/Scripts/python -m pip install -r requirements.txt -r requirements-robot.txt
.venv/Scripts/python -m snackbot
```

- 학습한 모델은 용량 때문에 저장소에 없습니다. `config.yaml`의 `skills.<이름>.export_dir` 위치에 OpenVINO 결과물을 넣습니다. 모델이 없는 동작은 건너뜁니다.
- 음성 인식 모델: `hf download OpenVINO/whisper-small-int8-ov --local-dir models/whisper-small`
- 포트, 카메라 번호, 캘리브레이션, 그리퍼 값 맞추는 순서는 [시연 런북](docs/DEMO_RUNBOOK.md)에 있습니다.
- 테스트: `.venv/Scripts/python -m pytest`

## 문서

- [발표 자료](docs/slides.html) (PowerPoint: [slides.pptx](docs/slides.pptx))
- [진행 보고서](docs/PROGRESS_REPORT.html): 한 일, 실기 결과, 남은 문제
- [구조](docs/ARCHITECTURE.md), [판단 규칙](docs/DECISION_LOGIC.md), [데이터셋 녹화 규칙](docs/DATASET_GUIDE.md)

## 남은 문제

- 제어 루프가 11~13 Hz로 돕니다 (학습은 30 Hz). 그래서 동작이 녹화 때보다 느리고 덜 정확합니다.
- 오란다 모델은 5 epoch만 학습해서 더 학습이 필요합니다.
- 도리도리 모델은 데이터가 적어 고개를 잘 젓지 못합니다. 시연에서는 코드로 만든 도리도리를 씁니다.
