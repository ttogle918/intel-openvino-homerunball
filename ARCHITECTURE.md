# 아키텍처

## 1. 전체 흐름 (3계층)

```mermaid
flowchart TD
    subgraph P["인식 계층"]
        CAM["카메라<br/>외부 + 손목"] --> VLM["홈런볼 개수 세기<br/>VLM · OpenVINO"]
        VLM -. "파싱 실패 시" .-> CV["OpenCV 크기 판별<br/>fallback"]
        MIC["마이크 · STT<br/>(보류)"]
    end

    subgraph J["판단 계층"]
        CNT[("작업 카운터<br/>코드가 관리")]
        GUARD{"코드 가드<br/>횟수 규칙"}
        LLM["LLM · OpenVINO<br/>스킬 + 대사 결정"]
        TTS["TTS<br/>대사 출력"]
    end

    subgraph A["행동 계층 (ACT)"]
        S1["move_homerunball<br/>홈런볼 1개 옮기기"]
        S2["dori_dori<br/>도리도리 거부"]
    end

    VLM --> GUARD
    CV --> GUARD
    MIC -.-> LLM
    CNT --> GUARD
    GUARD --> LLM
    LLM --> TTS
    LLM -->|"move_homerunball"| S1
    LLM -->|"dori_dori"| S2
    LLM -->|"done"| DONE(["작업 완료"])
    S1 -->|"개수 감소 확인 → count += 1"| CNT
    S2 --> WAIT["진행자 r 키 대기"]
    WAIT -->|"count = 0"| CNT
```

- 실선: 현재 구현 범위, 점선: fallback 또는 보류
- LLM은 로봇을 직접 움직이지 않고, **허용된 스킬 이름 하나와 대사**만 출력한다.

## 2. 한 사이클 시퀀스

```mermaid
sequenceDiagram
    autonumber
    participant M as main.py
    participant V as vision.py
    participant B as brain.py
    participant T as voice.py
    participant S as skills.py
    participant R as SO-ARM101

    M->>V: count_homerunballs(frame)
    V-->>M: remaining = 3
    M->>B: decide(remaining=3, count=2, state=WORKING)
    B->>B: 코드 가드 (count <= 3 → move 강제)
    B->>B: LLM 호출 → 대사 생성
    B-->>M: {"skill": "move_homerunball", "say": "..."}
    par 대사와 동작 동시 진행
        M->>T: speak(say)
    and
        M->>S: run("move_homerunball")
        S->>R: ACT 추론 루프 (예: 20초)
        S->>R: 홈 자세 복귀
    end
    M->>V: count_homerunballs(frame)
    V-->>M: remaining = 2
    M->>M: 3 → 2 감소 = 성공, count += 1
```

## 3. 상태 다이어그램

```mermaid
stateDiagram-v2
    [*] --> WORKING
    WORKING --> WORKING: 옮기기 성공 (count + 1)
    WORKING --> WORKING: 옮기기 실패 (재시도, 최대 2회)
    WORKING --> REFUSING: 거부 결정 (dori_dori 실행)
    REFUSING --> WORKING: 진행자 r 키 (count = 0)
    WORKING --> DONE: 남은 홈런볼 0개
    WORKING --> ESTOP: space 키
    REFUSING --> ESTOP: space 키
    ESTOP --> WORKING: 수동 재시작
    DONE --> [*]
```

## 4. 모듈 구조

```mermaid
flowchart LR
    CFG[("config.yaml")]
    MAIN["main.py<br/>상태 머신 · 키 입력 · 로그"]
    VIS["vision.py<br/>VLM + OpenCV"]
    BRN["brain.py<br/>가드 + LLM"]
    VOC["voice.py<br/>TTS"]
    SKL["skills.py<br/>ACT 정책 2개"]
    LOG[("logs/*.jsonl")]

    CFG --> MAIN
    MAIN --> VIS
    MAIN --> BRN
    MAIN --> VOC
    MAIN --> SKL
    MAIN --> LOG
    SKL --> BACK{"추론 백엔드"}
    BACK --> PT["PyTorch (1단계)"]
    BACK --> OV["OpenVINO (2단계)"]
```

## 5. OpenVINO 사용 위치

| 구성요소 | 모델 | 디바이스 후보 | 단계 |
|---|---|---|---|
| 홈런볼 개수 세기 | 소형 VLM (INT4/INT8) | GPU / CPU | 필수 |
| 판단과 대사 | 소형 instruct LLM (INT4) | GPU / NPU / CPU | 필수 |
| TTS | 한국어 TTS (가능하면 OpenVINO) | CPU | 선택 |
| ACT 추론 | 학습한 ACT 정책 변환 | CPU / GPU / NPU | 선택 (지연 비교용) |
| STT | Whisper | CPU / GPU | 보류 |
