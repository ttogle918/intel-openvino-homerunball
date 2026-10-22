# 아키텍처

> 세부 기준은 `docs/superpowers/specs/2026-10-22-chat-ui-design.md`. 충돌하면 설계 문서가 우선한다.

## 1. 전체 흐름 (3계층)

```mermaid
flowchart TD
    subgraph IN["입력"]
        UI["웹 UI 채팅"]
        MIC["🎤 누르고 말하기<br/>STT"]
        KEY["콘솔 키<br/>s · r · space · q"]
    end

    subgraph P["인식 계층"]
        CAM["카메라<br/>외부 + 손목"]
        CNT_A["A: counter 체인<br/>YOLO-World → VLM → OpenCV"]
        GRIP["B: 시작 개수 +<br/>그리퍼 쥠 판정"]
    end

    subgraph J["판단 계층"]
        CTRL[("controller<br/>상태 · count")]
        GUARD{"코드 가드<br/>횟수 규칙"}
        LLM["LLM provider 체인<br/>API → (로컬) → 규칙"]
        TTS["TTS"]
    end

    subgraph A["행동 계층 (ACT · OpenVINO)"]
        S1["oranda_pickup<br/>집기 → 놓기"]
        S2["dori_dori<br/>도리도리 거부"]
    end

    HOME["코드 복귀<br/>lift_pose → home_pose"]

    UI --> CTRL
    MIC --> CTRL
    KEY --> CTRL
    CAM -.-> CNT_A
    CNT_A -.-> CTRL
    GRIP --> CTRL
    CTRL --> GUARD --> LLM
    LLM --> TTS
    LLM -->|"oranda_pickup"| S1
    LLM -->|"dori_dori"| S2
    LLM -->|"done"| DONE(["작업 완료 → IDLE"])
    S1 -->|"그리퍼 닫힘 → 열림 감지 → ACT 정지"| HOME
    HOME -->|"성공 판정 → count += 1"| CTRL
    S2 --> WAIT["재개 대기<br/>r · UI 버튼 · 달래기"]
    WAIT -->|"count = 0"| CTRL
```

- 점선: A단계(M3)에서 추가. B단계만으로도 전체 흐름이 돈다.
- 과자를 찾아 집는 일은 ACT가 영상만 보고 한다. 인식 계층은 **언제 끝낼지**와 **성공했는지**만 판정한다.
- LLM은 로봇을 직접 움직이지 않고, **허용된 값 하나와 대사**만 출력한다.
- `oranda_pickup` ACT는 **놓기까지만** 한다. 홈 복귀는 학습하지 않고 코드가 저장된 자세로 강제한다.

## 1-1. oranda_pickup 실행 단계

```mermaid
flowchart LR
    A["홈 자세 확인<br/>home_pose와 비교"] --> B["ACT 추론 루프 30fps<br/>집기 → 놓기"]
    B --> C{"정지 조건"}
    C -->|"그리퍼 닫힘 → 열림 + 0.5초"| D["ACT 정지"]
    C -->|"최대 시간 초과"| D
    C -->|"비상정지"| X["목표 고정 · 중단"]
    D --> E["lift_pose로 천천히 이동<br/>위로 들기"]
    E --> F["home_pose로 천천히 이동"]
```

| 단계 | 담당 | 비고 |
|---|---|---|
| 홈 자세 확인 | 코드 | 관절별 오차가 기준(5)보다 크면 먼저 home_pose로 이동 |
| 집기 → 놓기 | ACT | 학습한 구간. `physicalai.InferenceModel.select_action` |
| 정지 판단 | 코드 | 닫힘 기준을 한 번 지난 뒤 열림 기준을 0.5초 넘으면, 또는 최대 시간(예: 20초) |
| 쥠 판정 | 코드 | 닫힘 구간의 그리퍼 최솟값 ≥ `grasp_min` → 과자를 쥐었음 |
| 위로 들기 → 홈 | 코드 | 관절 공간 보간, 느린 속도. 트레이·과자 충돌 방지 |

## 2. 한 사이클 시퀀스

```mermaid
sequenceDiagram
    autonumber
    actor U as 사용자 (UI)
    participant C as controller.py
    participant B as brain.py
    participant T as voice.py
    participant S as skills.py
    participant R as SO-ARM101

    U->>C: chat("오란다 3개 옮겨줘")
    C->>B: chat(text, state=IDLE)
    B-->>C: {"intent": "start_task", "n": 3, "say": "..."}
    C->>C: IDLE → WORKING, remaining = 3
    C->>B: decide(remaining=3, count=2, state=WORKING)
    B->>B: 코드 가드 (count <= 3 → oranda_pickup 강제)
    B->>B: LLM 호출 → 대사 생성
    B-->>C: {"skill": "oranda_pickup", "say": "..."}
    par 대사와 동작 동시 진행
        C->>T: speak(say)
    and
        C->>S: run("oranda_pickup")
        S->>R: ACT 추론 루프 (집기 → 놓기)
        S->>S: 그리퍼 닫힘 → 열림 감지 → ACT 정지
        S->>R: lift_pose → home_pose 이동 (코드)
        S-->>C: {stop_reason: "gripper_open", grasped: true}
    end
    C->>C: B: grasped → 성공, count += 1, remaining = 2
    Note over C: A단계: 실행 전후 counter 개수 비교로 성공 판정
    C-->>U: state · message · cycle 이벤트 (WebSocket)
```

## 3. 상태 다이어그램

```mermaid
stateDiagram-v2
    [*] --> IDLE
    IDLE --> IDLE: 잡담 → 캐릭터 대답
    IDLE --> WORKING: start_task (채팅 · 음성 · s 키)
    WORKING --> WORKING: 옮기기 성공 (count + 1) / 실패 재시도 (최대 2회)
    WORKING --> REFUSING: 거부 결정 (dori_dori 실행)
    REFUSING --> WORKING: r 키 · UI 재개 · 달래기 (count = 0)
    WORKING --> DONE: 남은 0개
    DONE --> IDLE: 완료 멘트 후 자동
    WORKING --> ESTOP: space · UI 비상정지
    REFUSING --> ESTOP: space · UI 비상정지
    ESTOP --> IDLE: restart (home_pose 복귀 후)
```

- 재시도를 넘겨도 실패하면 WORKING 상태에서 `phase = waiting_operator`로 재개 명령을 기다린다.

## 4. 모듈 구조

```mermaid
flowchart LR
    CFG[("config.yaml · .env")]
    MAIN["snackbot/__main__.py<br/>진입점"]
    CTRL["controller.py<br/>상태 머신 · 루프 스레드"]
    SRV["server.py<br/>FastAPI · WebSocket"]
    WEB["frontend/<br/>정적 UI"]
    PRV["providers.py<br/>API · OpenVINO 어댑터"]
    BRN["brain.py<br/>가드 + LLM"]
    VIS["vision.py<br/>counter 체인"]
    STT["stt.py"]
    VOC["voice.py<br/>TTS"]
    SKL["skills.py<br/>physicalai"]
    LOG[("logs/*.jsonl")]

    CFG --> MAIN
    MAIN --> CTRL
    MAIN --> SRV
    SRV --> WEB
    SRV --> CTRL
    SRV --> STT
    CTRL --> BRN
    CTRL --> VIS
    CTRL --> VOC
    CTRL --> SKL
    CTRL --> LOG
    BRN --> PRV
    VIS --> PRV
    STT --> PRV
    SKL --> POSE["자세 이동<br/>home_pose · lift_pose"]
    SKL --> OVACT["InferenceModel<br/>ACT · OpenVINO"]
    SKL --> HW["SO101 · UVCCamera"]
```

## 5. 모델 실행 위치

| 구성요소 | 모델 | 실행 위치 | 단계 |
|---|---|---|---|
| ACT 2개 | physical-ai-studio 학습 → OpenVINO 결과물 | **로컬** CPU / GPU / NPU | 필수 |
| 판단·대사·채팅 의도 | instruct LLM | **API** (OpenRouter / NVIDIA / 유료) → 선택적으로 로컬 OpenVINO → 규칙 | 필수 |
| 개수 세기 (A) | YOLO-World(OpenVINO) / VLM / OpenCV | 로컬 또는 API | M3 |
| STT | Whisper | 로컬 OpenVINO 또는 API | M6 |
| TTS | 한국어 TTS | 로컬 | 선택 |
