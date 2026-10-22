# 설계: UI 스킬 1회 실행(추론 테스트) · 코드 도리도리

작성 2026-10-22. 상태: **설계 확정, 구현 전**. 기존 기준: `2026-10-22-chat-ui-design.md`(상태·명령), `2026-10-22-digital-twin-design.md`(4분할·재생·실행 기록), M4 구현 결정(chat-ui-design 11.6절).

## 1. 목표

1. **스킬 1회 실행 버튼:** 화면에서 `오란다 1회` · `도리도리 1회` · `홈으로`를 누르면 그 스킬을 한 번만 실행한다.
   - **실제 로봇 모드에서는 진짜 로봇팔이 움직인다** (정책을 실제로 추론해 실행). 카메라 3칸과 3D 팔은 그 모습을 보여 줄 뿐이다.
   - dry-run에서는 같은 버튼이 녹화 재생으로 대신한다.
   - 목적: 학습한 모델이 실제로 어떻게 움직이는지 확인 (작업 흐름과 무관한 테스트).
2. **코드 도리도리:** dori_dori 모델이 없거나 쓰고 싶지 않을 때, 코드가 홈 자세에서 몸통을 좌우로 흔들어 도리도리를 한다.

범위 밖: 콘솔 키로 스킬 실행(필요하면 나중에 `1`/`2`/`0`), 녹화 궤적으로 실제 팔 움직이기, 테스트 중 파라미터 조정 UI.

## 2. 코드 도리도리 (`snackbot/robot.py`)

### 설정
```yaml
skills:
  dori_dori:
    export_dir: ...
    source: auto            # auto | policy | script  (auto: 모델이 로드되면 policy, 없으면 script)
    script: {joint: shoulder_pan, amplitude: 15, shakes: 2, shake_s: 0.35}
```
- `amplitude`: 홈 자세 기준 좌우 폭 (normalized, 몸통 단위 −100..100). **최대 30으로 자른다** (안전 상한, 넘으면 경고 후 30).
- `shakes`: 왕복 횟수. `shake_s`: 한쪽으로 가는 시간(초). 처음엔 작게 시작한다.
- `source: policy`인데 모델이 없으면 시작 때 SystemExit(안내), `source: script`면 모델이 있어도 코드 동작.

### 동작
- `run("dori_dori")`가 script로 결정되면: `ensure_home` → **스크립트 phase** → `home` 복귀.
- 스크립트 phase는 기존 `_phase()`(비상정지 세대 `_Aborted`, `_io` 락, 동작 출처 교체)를 그대로 쓰고 동작 출처만 `MoveSource`다:
  - 키프레임: 홈에서 `joint`만 `+A, −A`를 `shakes`번 반복한 뒤 홈. 각 키프레임 사이 `shake_s × fps` 스텝 선형 보간. 값은 관절 범위(−100..100)로 자른다.
  - 다른 관절은 홈 값 고정.
- 결과 `RunResult(stop_reason="script", grasped=False, ms=...)`. 비상정지면 기존과 같이 `estop`.
- 실행 기록(RunRecorder)은 정책 phase와 똑같이 스크립트 phase도 기록한다 (트윈 재생에 쓸 수 있게).
- 화면 모델 정보: `ACT · OpenVINO · GPU (oranda_pickup) · 도리도리: 코드 동작`처럼 표시.

### 안전
- 스킬 시작 전 항상 `home_pose` (기존 규칙 7).
- 비상정지 시 다음 틱에 멈추고 토크 유지 (기존 경로 그대로).
- 진폭 상한 30, 관절 범위 클램프.

## 3. 스킬 1회 실행

### 상태: `TESTING` 추가
- 새 상태 `TESTING` (UI 표시 "테스트"). 단계(phase)는 정상 사이클처럼 `acting` → `returning`을 쓴다 (화면의 녹화 재생·단계 표시줄이 그대로 동작).
- 진입 조건: **`IDLE`이고 진행 중인 동작이 없을 때만**. 그 밖의 상태(WORKING, REFUSING, DONE, ESTOP, 이미 TESTING)에서는 거부하고 시스템 메시지로 이유를 알린다.
- 테스트 중:
  - 채팅의 작업 시작(`start_task`)·`s` 키·`r` 키는 거부한다 ("테스트 중이에요").
  - 비상정지는 언제나 즉시 (기존 `_estop`: skills.estop → 상태 ESTOP). 테스트 중 비상정지 뒤에는 기존처럼 `재시작`으로 IDLE 복귀.
  - 횟수·피로도·거부 판단·사이클 통계에 반영하지 않는다.
- 끝나면 (세션 번호가 그대로이고 상태가 아직 TESTING이면) `IDLE`로 돌아간다.

### 실행 스레드
- 로봇을 움직이는 스레드는 **controller 루프 스레드 하나**로 유지한다 (두 스레드가 동시에 스킬을 부르지 않게).
- `command("test", skill=..., expect_gen=g)`는 락 안에서 조건을 확인하고 `self._pending_test = skill`, 상태 TESTING으로 바꾼 뒤 루프를 깨운다(`_wake`). 루프는 WORKING이 아닐 때 `_pending_test`를 꺼내 실행한다.
- 실행 중 `_run_idle`을 clear/set 해서 기존 재시작 대기(동작이 멈춘 뒤에만 재시작)가 테스트에도 적용된다.
- 세션 번호(`_gen`): 명령 접수 순간의 세대를 붙이고(콘솔·웹 재시작과 같은 방식), 테스트 시작 시 증가. 실행 뒤 세대가 바뀌었으면(그 사이 비상정지·재시작) 결과로 상태를 바꾸지 않는다.

### 스킬
| 버튼 | 동작 |
|---|---|
| `오란다 1회` | `skills.run("oranda_pickup")` — 홈 확인 → 정책 → 놓기 감지/시간 초과 → lift → home |
| `도리도리 1회` | `skills.run("dori_dori")` — 정책 또는 코드 도리도리(2절) |
| `홈으로` | `skills.go_home()` |
- 로드되지 않은 정책의 버튼은 비활성(툴팁 "모델 없음"). 코드 도리도리면 도리도리 버튼은 항상 활성.

### 결과 표시
- 채팅창 시스템 메시지 한 줄: `테스트 · 오란다: 놓기 감지로 끝남 · 쥠 성공 · 12.3초 · 기록 logs/runs/…`
  - stop_reason 한국어: `gripper_open` 놓기 감지 / `timeout` 시간 초과 / `estop` 비상정지 / `script` 코드 동작 완료 / `done` 완료.
  - 실행 기록이 꺼져 있으면 기록 경로는 생략.
- 사이클 로그(JSONL)에는 `type: "test"`로 따로 남긴다 (발표 통계에서 제외하기 쉽게).

### 서버·화면
- WebSocket 명령: `{"type": "command", "name": "test", "skill": "oranda_pickup" | "dori_dori" | "home"}`. 연결별 FIFO로 처리하고, 접수 순간 세대를 붙인다 (재시작과 같은 패턴). 허용 외 skill 값은 무시.
- `info`에 `tests: [{skill, label, enabled, reason}]` 추가.
- 화면: 제어 버튼 영역(재개·재시작 옆)에 "스킬 테스트" 줄 — 세 버튼. `IDLE`일 때만 활성, `TESTING` 중엔 모두 비활성(비상정지 버튼은 활성). 상태 배지에 "테스트".
- 목업 모드(`?mock`)에서도 버튼이 보이고 가짜 흐름을 보여 준다.

## 4. dry-run
- 같은 명령으로 `DrySkills.run(skill)`이 돈다 → 화면은 `acting` 단계에서 녹화 재생(있으면). `홈으로`는 짧은 대기 후 끝.
- 코드 도리도리는 dry-run에선 의미가 없으므로 DrySkills는 기존대로(재생 데이터 또는 act_s).

## 5. 오류 처리
- 테스트 중 스킬이 예외를 내면: 기존 사이클 예외 처리처럼 경고 로그 + 시스템 메시지("테스트 실패: …"), 상태는 IDLE(세대가 같을 때). 로봇 루프는 계속 돈다.
- 로드 안 된 정책을 직접 명령으로 보내면 팔을 움직이기 전에 거부(기존 RobotSkills 동작).

## 6. 테스트 (자동)
- 코드 도리도리: 키프레임(홈 기준 ±A, 횟수, 마지막 홈), 진폭 상한·클램프, `source` auto/policy/script 결정, 모델 없을 때 auto→script, policy 강제인데 없으면 SystemExit, 비상정지 중단(기존 가짜 런타임), 기록 hook 호출.
- 스킬 테스트: IDLE에서만 진입, 다른 상태 거부, 테스트 중 start/resume 거부, 결과 메시지 문구, 상태 복귀, 비상정지 → ESTOP 유지·재시작 대기, 접수 후 비상정지가 끼면 거부(세대), 루프 스레드에서만 skills.run 호출, 통계 미반영, JSONL `type: test`.
- 서버: `test` 명령 FIFO·세대·허용 값, info `tests`.
- 화면은 브라우저로 확인 (dry-run 재생, 버튼 활성/비활성, 비상정지).

## 7. 현장 확인
- 코드 도리도리 진폭·속도는 실제 팔에서 작게 시작해 조정 (`amplitude` 10 → 15 → 20).
- 오란다 1회 테스트로 `grasp_min`, `closed_below`, `open_above`, `max_time_s`가 맞는지 보고 조정.

## 8. 추가 (2026-10-22, 사용자 요청): LLM이 도리도리를 도구로 호출

- 대화 LLM이 **채팅 의도(intent)로 도리도리를 고를 수 있다.** 대화 체인(Claude → NVIDIA → 규칙)의 모든 provider에서 같게 동작하도록 Anthropic tool-use API가 아니라 기존 JSON intent 방식을 쓴다 (절대 규칙 3: LLM 출력은 허용된 값만).
  - `allowed_intents("IDLE")` = `["start_task", "chat", "dori_dori"]` (그 밖의 상태에는 넣지 않는다).
  - `CHAT_SYSTEM` 프롬프트에 도구 설명 한 줄: `dori_dori: 고개를 좌우로 젓는 동작 한 번 (싫다고 하거나, 도리도리를 해 보라고 할 때)`.
  - LLM 실패 시 키워드 fallback: `도리도리`, `고개 저어`, `고개를 저어` → `dori_dori` (IDLE에서만).
  - LLM이 `dori_dori`를 골라도 상태가 IDLE이 아니면 무시되고 chat으로 처리된다 (기존 허용 목록 규칙).
- **실행 경로는 버튼과 하나:** `controller.chat`에서 intent가 `dori_dori`면 대사를 낸 뒤 `command("test", skill="dori_dori")`와 같은 내부 경로(`_request_test`)로 1회 실행한다. 즉 TESTING 상태, 대기 상태에서만, 횟수·피로도 미반영, 결과 시스템 메시지, 비상정지 즉시 — 버튼과 완전히 같다.
- 결과 메시지의 출처 표시: 버튼은 `테스트 · …`, LLM은 `도리도리 · …`.
- 테스트: brain(IDLE 허용 목록, 다른 상태에서 무시, 키워드 fallback), controller(chat → 1회 실행 → IDLE 복귀, 다른 상태에서는 실행 안 함), 프롬프트에 도구 설명 포함.
