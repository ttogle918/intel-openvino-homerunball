# CLAUDE.md — 홈런볼 옮기기 로봇

이 파일은 Claude Code가 이 저장소에서 작업할 때 항상 참고하는 프로젝트 요약입니다.

## 프로젝트
- 하드웨어: SO-ARM101 (팔로워 1대, 학습용 리더 1대), 카메라 2대(외부 + 손목)
- 소프트웨어: LeRobot ACT, OpenVINO (VLM, LLM, 선택적으로 ACT 추론), TTS
- 기간: 2일 해커톤
- 시연: 섞인 트레이에서 홈런볼만 빈 트레이로 옮긴다. 일을 몇 번 하면 지쳐서 도리도리로 거부하고,
  진행자가 달래면(r 키) 다시 일한다.

## 3계층 구조
| 계층 | 담당 | 구현 |
|---|---|---|
| 인식 | 남은 홈런볼 개수 세기 | VLM (OpenVINO) + OpenCV fallback |
| 판단 | 다음 행동과 대사 결정 | 코드 가드 + LLM (OpenVINO), TTS 출력 |
| 행동 | 동작 실행 | ACT 정책 2개: move_homerunball, dori_dori |

## 절대 규칙
1. **횟수는 코드가 센다.** LLM은 프롬프트로 받은 숫자를 해석만 한다.
2. **ACT 정책 하나 = 동작 하나.** ACT는 기억이 없으므로 순서·횟수는 메인 루프가 관리한다.
3. **LLM 출력은 허용된 값만.** `move_homerunball | dori_dori | done` 외의 값은 무시하고 규칙으로 결정한다.
4. **STT는 보류.** 인터페이스(speech_text)만 남겨 둔다.
5. **파인튜닝 없음.** 홈런볼 인식은 VLM 제로샷 + OpenCV 크기 판별.
6. **LeRobot 코어 수정 금지.** 설치된 버전의 API를 확인하고 그대로 사용한다.

## 문서
- `docs/ARCHITECTURE.md` — 전체 구조, 시퀀스, 상태, 모듈 다이어그램 (Mermaid)
- `docs/DECISION_LOGIC.md` — 횟수 가드 규칙, LLM 프롬프트, JSON 스키마, fallback
- `docs/DATASET_GUIDE.md` — ACT 데이터셋 녹화 규칙과 체크리스트
- `docs/DEMO_RUNBOOK.md` — 시연 당일 준비와 장애 대응

## 파일 구조 (목표)
```
.
├── CLAUDE.md
├── config.yaml
├── main.py
├── vision.py
├── brain.py
├── voice.py
├── skills.py
├── tests/
│   └── samples/        # 트레이 사진 (dry-run용)
├── logs/               # 사이클별 JSONL 로그
└── docs/
```

## 실행
```bash
python main.py --dry-run     # 로봇 없이 전체 흐름 테스트
python main.py               # 실제 로봇
python vision.py tests/samples/tray_3.jpg   # 모듈 단독 테스트
```

## 진행자 키
| 키 | 동작 |
|---|---|
| `r` | 재개 (count = 0, 거부 → 작업) |
| `space` | 비상정지 |
| `q` | 종료 |
