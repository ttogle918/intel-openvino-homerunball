# Claude Code에 붙여넣을 프롬프트

> **초기 프롬프트 (기록용).** 현재 설계 기준은 `docs/superpowers/specs/2026-10-22-chat-ui-design.md`. 스킬 이름·상태·provider 등이 이후 바뀌었다.

> 사용법: 이 저장소 루트에 `CLAUDE.md`와 `docs/` 폴더를 먼저 넣어 둔 뒤, 아래 코드 블록 안의 내용을 Claude Code에 그대로 붙여넣으세요.
> `[ ]` 표시는 실제 환경 값으로 바꿔 주세요.

```text
# 프로젝트: 홈런볼 옮기기 로봇 (SO-ARM101 + LeRobot ACT + OpenVINO)

2일짜리 해커톤 프로젝트야. 저장소 루트의 CLAUDE.md와 docs/ 폴더를 먼저 전부 읽고 시작해.
특히 docs/ARCHITECTURE.md(전체 구조와 다이어그램), docs/DECISION_LOGIC.md(판단 규칙)를 기준으로 구현해.

## 한 줄 요약
섞인 과자 트레이에서 홈런볼만 빈 트레이로 옮기는 로봇. 작업 횟수가 쌓이면 "힘들어요" 하면서
도리도리로 거부하고, 진행자가 r 키를 누르면 다시 일한다.

## 핵심 원칙 (반드시 지킬 것)
1. 작업 횟수는 코드가 센다. LLM에게 기억시키지 않는다.
2. 거부 판단은 코드 가드 + LLM이다.
   - count <= 3 → 무조건 move_homerunball (LLM은 대사만 결정)
   - count >= 6 → 무조건 dori_dori
   - count 4~5 → LLM이 move_homerunball / dori_dori 중 선택
   - 남은 홈런볼 0개 → done
   (임계값은 config.yaml에서 조정 가능하게)
3. ACT 정책은 "한 번에 동작 하나"만 한다. 순서·횟수·기억은 전부 메인 루프의 몫이다.
   ACT 정책 2개:
   - move_homerunball: 홈 자세에서 홈런볼 1개 집어 빈 트레이에 놓기까지만 학습됨 (복귀는 학습 안 함)
   - dori_dori: 도리도리 후 홈 복귀까지 학습됨
   move_homerunball 이후의 홈 복귀는 코드가 저장된 관절값(lift_pose → home_pose)으로 강제한다.
4. 옮기기 성공 판정 = 실행 전후 VLM 개수 비교 (줄었으면 성공 → count += 1).
   실패하면 실패 멘트 후 최대 2회 재시도, 그래도 실패하면 진행자 확인 대기.
5. STT는 보류. 단, brain의 입력에 speech_text 자리는 남겨 두고 지금은 None을 넘긴다.
6. 단순하고 확실하게. 과한 추상화, 불필요한 클래스 계층 금지.

## 환경
- 로봇: SO-ARM101 팔로워, 포트 [/dev/ttyACM0], robot id [my_follower]
- 카메라: 외부 [index], 손목 [index]
  (ACT 학습 때 쓴 카메라 이름/키와 반드시 일치시킬 것: [예: front, wrist])
- ACT 정책 경로: move_homerunball [path], dori_dori [path]
- 데이터셋: [홈런볼 데이터셋 repo_id], [dori_dori 데이터셋 repo_id]
- 실행 PC: [예: Intel Core Ultra 노트북], OpenVINO 디바이스 후보 CPU/GPU/NPU
- LeRobot 버전: [ ]   OpenVINO 버전: [ ]

## 만들 파일
- config.yaml : 포트, 카메라, 모델 경로, 디바이스, 임계값, VLM/OpenCV 전환, 스킬 실행 시간,
                home_pose / lift_pose 관절값, 그리퍼 열림 기준값, 복귀 속도
- tools/save_pose.py : 팔로워의 현재 관절값을 읽어 config.yaml의 home_pose 또는 lift_pose로 저장
- vision.py   : VLM(openvino_genai)으로 홈런볼 개수 세기 + OpenCV fallback
- brain.py    : 코드 가드 + LLM(openvino_genai) 판단, JSON 출력 검증, 규칙 기반 fallback
- voice.py    : TTS (비동기 재생)
- skills.py   : ACT 정책 로드/실행, 홈 자세 복귀, 비상정지
- main.py     : 상태 머신 메인 루프, 키보드 입력, 콘솔 상태 출력
- tests/      : 모듈별 단독 테스트, 샘플 이미지

## 모듈별 요구사항

### vision.py
- 파인튜닝 금지. 상품명 대신 생김새로 질문:
  "How many small, round, brown cream-puff-shaped snacks are in the tray? Answer with a number only."
- 숫자만 파싱, 실패 시 1회 재시도 → 그래도 실패하면 OpenCV fallback
- OpenCV fallback: 윤곽선 면적 + 원형도로 홈런볼 크기 물체만 카운트 (임계값은 config)
- `python vision.py sample.jpg` 로 단독 테스트 가능하게

### brain.py
- 입력: remaining(int), count(int), state(str), speech_text(None|str)
- 출력: {"skill": "move_homerunball" | "dori_dori" | "done", "say": "한국어 대사 1~2문장"}
- 코드 가드를 LLM 호출 전후로 적용 (DECISION_LOGIC.md의 표 그대로)
- JSON 파싱 실패/허용 외 값 → 규칙 기반 결정 + 미리 준비한 대사 목록에서 랜덤
- 캐릭터: 성실하지만 금방 지치는 투덜이 로봇. 3회쯤부터 예고 멘트.
- 시스템 프롬프트는 DECISION_LOGIC.md에 있는 초안을 기반으로 다듬어.

### voice.py
- OpenVINO로 돌릴 수 있는 한국어 TTS를 우선 검토하고, 설치가 오래 걸리면
  OS 기본 TTS 등 가벼운 대체안 사용. 어떤 걸 쓸지 먼저 제안하고 내 확인을 받아.
- 대사 재생이 로봇 동작을 막지 않도록 비동기로.

### skills.py
- 설치된 LeRobot 버전의 실제 API(정책 로드, 전처리/후처리, 로봇 연결)를 먼저 확인하고 작성해.
  추측해서 쓰지 마.
- 정책 2개를 시작 시 미리 로드.
- 스킬 시작 전: 현재 관절값을 home_pose와 비교해서 차이가 기준(예: 관절별 5도)보다 크면
  먼저 home_pose로 천천히 이동. ACT는 학습 때와 같은 시작 자세에서 출발해야 한다.
- move_homerunball 실행:
  1. ACT 추론 루프 실행
  2. 정지 조건: 그리퍼 관절값이 "열림" 기준을 넘고 0.5초 지나면 정지.
     안전장치로 최대 시간(config, 예: 20초)도 둔다. 어느 조건으로 멈췄는지 로그에 남긴다.
  3. 정지 후 lift_pose로 천천히 이동(위로 들기) → home_pose로 천천히 이동
     (관절 공간 선형 보간, 속도와 단계 수는 config)
- dori_dori 실행: 최대 시간(예: 6초)만큼 ACT 실행 후, 혹시 남은 오차를 home_pose로 보정.
- 그리퍼 열림 기준값은 녹화 데이터셋의 그리퍼 값 분포를 보고 정할 수 있게
  데이터셋에서 마지막 프레임 그리퍼 값의 통계를 출력하는 스크립트도 만들어 줘.
- 자세 이동 함수는 비상정지(space) 시 즉시 멈출 수 있게.
- 추론 백엔드는 인터페이스로 분리 (1단계 PyTorch → 2단계 OpenVINO로 교체 가능하게).

### main.py
- 상태: WORKING / REFUSING / DONE / ESTOP (ARCHITECTURE.md의 상태 다이어그램 그대로)
- 키보드: r = 재개(count=0, REFUSING→WORKING), space = 비상정지, q = 종료
- 콘솔에 매 사이클: 상태, 남은 개수, count, 결정된 skill, 대사, 각 단계 소요 시간(ms)
- 모든 사이클을 logs/에 JSONL로 기록 (발표용 통계에 씀)

### 테스트 모드
- --dry-run: 로봇 없이 실행. 카메라는 tests/의 사진, 스킬은 로그 출력 + sleep으로 대체.
  dry-run에서도 count가 쌓여서 거부와 재개가 동작하는지 확인할 수 있어야 함.

## 작업 순서
1. 환경 확인 (LeRobot/OpenVINO 버전, 디바이스 목록, 카메라 인덱스) 후 보고.
2. 사용할 VLM / LLM / TTS 모델 후보와 다운로드 용량을 제안하고 내 확인 받기.
3. dry-run으로 전체 흐름 완성 (ACT 학습이 끝나기 전에 여기까지).
4. 실제 로봇 연결: save_pose로 home/lift 자세 저장 → 자세 이동만 단독 테스트 →
   dori_dori 스킬 단독 → move_homerunball 단독(정지 조건 확인) → 전체 루프.
5. (선택) ACT 추론을 OpenVINO로 교체하고 지연 시간 비교표 작성.

## 하지 말 것
- LeRobot 코어 코드 수정
- VLM/YOLO 파인튜닝
- 내 확인 없이 큰 패키지 설치나 모델 다운로드 (용량 먼저 알려줘)
- ACT에게 횟수나 순서를 학습시키려는 시도 (한 정책 = 한 동작)
- move_homerunball 정책에 홈 복귀까지 맡기기 (학습 안 된 구간이라 엉뚱하게 움직임)
```
