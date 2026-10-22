# 스킬 1회 실행(추론 테스트) · 코드 도리도리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 화면의 `오란다 1회` · `도리도리 1회` · `홈으로` 버튼(그리고 채팅의 "도리도리 해 봐")으로 스킬을 한 번만 실행하는 `TESTING` 상태를 만들고, dori_dori 모델이 없거나 쓰기 싫을 때 코드가 홈 자세에서 몸통을 좌우로 흔드는 코드 도리도리를 넣는다.

**Architecture:** `RobotSkills`는 `skills.dori_dori.source`(auto | policy | script)로 도리도리 방식을 정하고, 코드 도리도리는 기존 `_phase()`(비상정지 세대·`_io` 락·동작 출처 교체) 위에서 `MoveSource` 키프레임으로 돈다. `Controller`는 `command("test", skill=, expect_gen=)`를 락 안에서 확인해 `TESTING`으로 바꾸고 대기 슬롯(`_pending_test`)에 넣은 뒤 루프 스레드를 깨우며, 루프 스레드만 `step_test()`로 스킬을 실행한다. 서버는 `test` 명령을 연결별 FIFO에 접수 순간의 세션 번호와 함께 넣고, 화면은 `info.tests`로 버튼을 그린다. LLM은 기존 JSON intent에 `dori_dori`를 더해(IDLE만) 같은 내부 경로(`_request_test`)를 탄다.

**Tech Stack:** Python 3.13, FastAPI/Starlette(TestClient), NumPy, PyYAML, pytest, 빌드 없는 정적 웹(index.html · app.js · style.css).

**전제:** 브랜치 `feat/robot-m4`, 테스트 340개 통과. 요구사항 기준: `docs/superpowers/specs/2026-10-22-skill-test-and-scripted-dori-design.md` (8절 LLM 추가 포함). 상태·명령은 `2026-10-22-chat-ui-design.md`, 4분할·재생·실행 기록은 `2026-10-22-digital-twin-design.md`.

## Global Constraints

- 모든 명령은 `project/`에서 실행한다. 개발 PC(Windows, Git Bash): `.venv/Scripts/python`. 로봇 노트북(Ubuntu): `.venv/bin/python`. 테스트: `.venv/Scripts/python -m pytest -q`.
- 커밋은 `project/` 안의 파일만 `git add <경로>`로 지정한다 (`git add -A` 금지). 커밋 메시지 끝에 작업한 세션의 `Co-Authored-By` 줄.
- git 안전: `stash` · `checkout` · `reset` · `restore` · `clean` · `commit --amend` 금지. `.env`는 읽지 않는다.
- **physicalai는 개발 PC에 없고 설치하지 않는다.** 모듈 최상위에서 import하지 않는다 (`robot.py`는 지금처럼 함수 안에서만). 모든 테스트는 가짜(fake)로 돈다. 테스트에서 네트워크를 쓰지 않는다.
- 새 파이썬 의존성 없음 (`requirements.txt` 그대로). physicalai / LeRobot 코어 수정 금지.
- 의존 방향 유지: `server → controller → (brain, vision, skills, voice)`. controller는 FastAPI를 모르고, server는 `robot.py`를 모른다.
- **로봇을 움직이는 스레드는 controller 루프 스레드 하나.** `command("test")`는 요청만 하고, `skills.run`/`go_home`은 `step_test()`(루프 스레드)에서만 부른다. 두 스레드가 동시에 스킬을 부르지 않는다.
- **비상정지는 테스트를 기다리지 않는다.** 기존 `_estop` 경로(skills.estop → 상태 ESTOP) 그대로, 테스트 중에도 즉시. 재시작은 기존처럼 동작이 멈춘 뒤에만(`_run_idle`).
- 스킬 시작 전 항상 `home_pose` (절대 규칙 7). 코드 도리도리 진폭 상한 30 (넘으면 경고 후 30), 관절값은 −100..100으로 자른다.
- 테스트는 횟수·피로도·거부 판단·사이클 통계(`cycle` 이벤트·`cycle_n`)에 반영하지 않는다. JSONL에는 `"type": "test"`로 따로 남긴다 (절대 규칙 1: 횟수는 코드가 센다).
- LLM 출력은 허용된 값만 (절대 규칙 3): `allowed_intents("IDLE") = ["start_task", "chat", "dori_dori"]`, 그 밖의 상태에는 `dori_dori`를 넣지 않는다.
- 화면·안내·시스템 메시지는 한국어. 결과 문구의 stop_reason: `gripper_open` 놓기 감지 / `timeout` 시간 초과 / `estop` 비상정지 / `script` 코드 동작 완료 / `done` 완료.
- 콘솔 키는 추가하지 않는다 (스킬 테스트는 UI 버튼과 채팅만).

## File Structure

| 파일 | 책임 |
|---|---|
| `snackbot/robot.py` (수정) | `DORI_SOURCES`, `dori_settings`, `dori_keyframes`, `RobotSkills.dori_source`/`dori`, `_script_dori`, `_move(segment_s=)`, `RunResult.record` 채우기, `build_policies`가 script면 dori 모델을 건너뜀 |
| `snackbot/skills.py` (수정) | `RunResult.record` 필드, `DrySkills.go_home()`이 짧게 기다리고 `done | estop` |
| `config.yaml` (수정) | `skills.dori_dori.source`, `skills.dori_dori.script` |
| `snackbot/controller.py` (수정) | `TESTING`, `TEST_SKILLS`, `_request_test`, `step_test`, 루프의 테스트 실행, 결과 메시지·JSONL, 테스트 중 시작·재개 거부, `chat`의 `dori_dori` |
| `snackbot/brain.py` (수정) | `allowed_intents` IDLE에 `dori_dori`, `DORI_WORDS` 키워드, `CHAT_SYSTEM` 도구 한 줄, `dori_chat`·`testing` 대사 |
| `snackbot/server.py` (수정) | WS `{"type":"command","name":"test","skill":...}` → 연결별 FIFO + 접수 세대 |
| `snackbot/__main__.py` (수정) | `act_label`(코드 도리도리 표시), `skill_tests_info` → `info.tests`, 경고 문구 |
| `frontend/index.html`, `app.js`, `style.css` (수정) | 스킬 테스트 줄, `TESTING` 배지·단계 표시줄, 목업 흐름 |
| `tests/test_robot.py`, `test_config.py`, `test_skills.py`, `test_controller.py`, `test_brain.py`, `test_server.py`, `test_main.py` (수정) | 테스트 |
| `CLAUDE.md`, `docs/DEMO_RUNBOOK.md`, `docs/UI_DESIGN_PROMPT.md`, `docs/DECISION_LOGIC.md`, 설계 문서 2개, `docs/memo/2026-10-22-design-discussion.md` (수정) | 현장 절차·계약·교차 링크·구현 결정 |

---

### Task 1: RobotSkills 코드 도리도리 + 설정

**Files:**
- Modify: `snackbot/robot.py`, `snackbot/skills.py:23-27` (RunResult), `config.yaml:73` (dori_dori 줄)
- Test: `tests/test_robot.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: `snackbot.twin.JOINTS`, `snackbot.motion.GRIPPER`(=5), `MoveSource(targets, steps)`, 기존 `RobotSkills._phase(source, duration_s, gen, done=None, camera_map=None)`, `RunRecorder.start(skill) / stop(result) -> Path | None`
- Produces (`snackbot/robot.py`):
  - `DORI_SOURCES = ("auto", "policy", "script")`, `DORI_MAX_AMPLITUDE = 30.0`, `DORI_DEFAULTS`, `BODY_JOINTS = JOINTS[:5]`
  - `dori_settings(conf: dict | None) -> {"joint": int, "amplitude": float, "shakes": int, "shake_s": float}` — 잘못된 값은 `SystemExit`, 진폭 > 30이면 경고 후 30
  - `dori_keyframes(home, joint: int, amplitude: float, shakes: int) -> list[np.ndarray]` — `+A, −A`를 shakes번, 마지막 홈, −100..100 클램프
  - `RobotSkills.dori_source: "policy" | "script"`, `RobotSkills.dori: dict | None` (script일 때 `dori_settings` 결과). script면 `"dori_dori"`는 `policies`/`models`에 없다
  - `RobotSkills.run("dori_dori")` (script) → `RunResult("script", False, ms)` / 비상정지면 `"estop"`
  - `RunResult.record`: 실행 기록 폴더 posix 문자열 또는 None
- Produces (`snackbot/skills.py`): `RunResult(stop_reason, grasped, ms, record=None)`
- Produces (config 키): `skills.dori_dori.source` (기본 `auto`), `skills.dori_dori.script.{joint, amplitude, shakes, shake_s}`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_robot.py` 맨 위 import를 다음으로 바꾼다:
```python
from types import SimpleNamespace

import sys
import threading

import numpy as np
import pytest

from snackbot.robot import RobotSkills, build_policies, dori_keyframes, dori_settings
from snackbot.twin import load_episode
```

파일 끝에 추가:
```python
# --- 코드 도리도리 ---
def make_script(cfg, joints=POSES["home_pose"], policies=None):
    """dori_dori 정책 없이 만든다 (source auto → 코드 도리도리)."""
    robot, holder = FakeRobot(joints), {}

    def make_runtime(switch, tap):
        holder["rt"] = FakeRuntime(switch, tap, robot)
        return holder["rt"]

    s = RobotSkills(cfg, POSES, make_runtime=make_runtime,
                    policies={"oranda_pickup": FakePolicy()} if policies is None else policies)
    s.connect()
    return s, holder["rt"], robot


def test_dori_keyframes_shake_selected_joint_around_home():
    home = [5, 1, 2, 3, 4, 80]
    frames = dori_keyframes(home, 0, 15, 2)
    assert [float(f[0]) for f in frames] == [20, -10, 20, -10, 5]
    assert all(np.allclose(f[1:], home[1:]) for f in frames)   # 다른 관절은 홈 그대로


def test_dori_keyframes_clamped_to_joint_range():
    frames = dori_keyframes([90, 0, 0, 0, 0, 80], 0, 20, 1)
    assert [float(f[0]) for f in frames] == [100, 70, 90]


def test_dori_settings_defaults_cap_and_errors(caplog):
    assert dori_settings(None) == {"joint": 0, "amplitude": 15.0, "shakes": 2, "shake_s": 0.35}
    with caplog.at_level("WARNING"):
        s = dori_settings({"joint": "wrist_roll", "amplitude": 50})
    assert s["joint"] == 4 and s["amplitude"] == 30.0 and "30" in caplog.text
    for bad in ({"joint": "gripper"}, {"joint": "elbow"}, {"amplitude": 0}, {"shakes": 0},
                {"shake_s": -1}, {"amplitude": "big"}, {"amplitude": None}):
        with pytest.raises(SystemExit):
            dori_settings(bad)


def test_dori_source_auto_uses_policy_when_loaded(rcfg):
    s, rt, _ = make(rcfg)
    assert s.dori_source == "policy" and s.dori is None
    assert s.run("dori_dori").stop_reason == "timeout" and rt.runs == ["FakePolicy", "MoveSource"]


def test_dori_source_auto_without_model_runs_script_from_home(rcfg):
    s, rt, robot = make_script(rcfg)
    assert s.dori_source == "script" and "dori_dori" not in s.policies
    r = s.run("dori_dori")
    assert (r.stop_reason, r.grasped) == ("script", False)
    assert rt.runs == ["MoveSource"]                      # 이미 홈: 이동 없이 바로 스크립트 (끝 키프레임이 홈)
    pan = [float(a[0]) for a in robot.history]
    assert max(pan) == pytest.approx(15) and min(pan) == pytest.approx(-15)
    steps = int(rcfg["skills"]["dori_dori"]["script"]["shake_s"] * s.fps)
    assert len(robot.history) == 5 * steps               # 키프레임 5개 (+A −A +A −A 홈) × 구간 스텝
    assert at(robot, POSES["home_pose"])


def test_dori_source_script_ignores_loaded_policy(rcfg):
    rcfg["skills"]["dori_dori"]["source"] = "script"
    s, rt, _ = make(rcfg)
    assert s.dori_source == "script" and "dori_dori" not in s.policies
    assert s.run("dori_dori").stop_reason == "script" and rt.runs == ["MoveSource"]


def test_dori_source_policy_without_model_or_unknown_source_exits(rcfg):
    rcfg["skills"]["dori_dori"]["source"] = "policy"
    with pytest.raises(SystemExit, match="source"):
        make_script(rcfg)
    rcfg["skills"]["dori_dori"]["source"] = "magic"
    with pytest.raises(SystemExit, match="auto"):
        make(rcfg)


def test_build_policies_skips_dori_model_when_source_is_script(rcfg, tmp_path):
    export = tmp_path / "dori"
    export.mkdir()
    rcfg["skills"]["dori_dori"].update(export_dir=str(export), source="script")
    rcfg["skills"]["oranda_pickup"]["export_dir"] = str(tmp_path / "none")
    assert build_policies(rcfg) == ({}, {})              # 폴더가 있어도 로드하지 않는다
    assert "physicalai" not in sys.modules


def test_script_dori_needs_no_gripper_values(cfg):
    cfg["skills"]["gripper"]["grasp_min"] = None
    s = RobotSkills(cfg, POSES, make_runtime=lambda sw, t: None, policies={})
    assert s.dori_source == "script" and s.watch is None


def test_script_dori_moves_home_first_when_away(rcfg):
    s, rt, robot = make_script(rcfg, joints=[30, 0, 0, 0, 0, 80])
    assert s.run("dori_dori").stop_reason == "script"
    assert rt.runs == ["MoveSource", "MoveSource"] and at(robot, POSES["home_pose"])


def test_estop_during_script_dori_stops_without_home(rcfg):
    s, rt, robot = make_script(rcfg)
    tick = s.tap.on_tick

    def on_tick(event):
        tick(event)
        if len(robot.history) == 7:
            s.estop()

    s.tap.on_tick = on_tick
    assert s.run("dori_dori").stop_reason == "estop"
    assert rt.runs == ["MoveSource"] and len(robot.history) == 7   # 다음 틱에 멈추고 홈으로 가지 않는다
    assert rt.connected


def test_script_dori_phase_is_recorded(rcfg):
    s, _, robot = make_script(rcfg)
    r = s.run("dori_dori")
    s.recorder.wait(5)
    ep = load_episode(s.recorder.last_folder)
    assert ep["skill"] == "dori_dori" and len(ep["joints"]) == len(robot.history)
    assert ep["stop_reason"] == "script" and r.record == s.recorder.last_folder.as_posix()
    assert s.tap.recorder is None


def test_run_result_record_only_when_recorded(rcfg):
    s, _, _ = make(rcfg)
    r = s.run("dori_dori")
    assert r.record == s.recorder.last_folder.as_posix()
    rcfg["recording"]["enabled"] = False
    s2, _, _ = make(rcfg)
    assert s2.run("dori_dori").record is None
```

`tests/test_config.py` 파일 끝에 추가:
```python
def test_config_dori_script_defaults():
    dori = load_config(ROOT / "config.yaml")["skills"]["dori_dori"]
    assert dori["source"] == "auto"
    assert dori["script"] == {"joint": "shoulder_pan", "amplitude": 15, "shakes": 2, "shake_s": 0.35}
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_robot.py tests/test_config.py -q`
Expected: FAIL — `ImportError: cannot import name 'dori_keyframes' from 'snackbot.robot'`, `KeyError: 'source'`

- [ ] **Step 3: 구현 — `RunResult.record`**

`snackbot/skills.py`의 `RunResult`를 다음으로 바꾼다:
```python
@dataclass
class RunResult:
    stop_reason: str   # gripper_open | timeout | estop | script(코드 도리도리)
    grasped: bool
    ms: int
    record: str | None = None   # 실행 기록 폴더 (실제 로봇에서 기록했을 때만, posix 경로)
```

- [ ] **Step 4: 구현 — 설정**

`config.yaml`의 `dori_dori:` 한 줄을 다음 블록으로 바꾼다 (들여쓰기 2칸, `skills:` 아래):
```yaml
  dori_dori:
    export_dir: traind-model/dori-dori-model/exports/openvino
    max_time_s: 6
    camera_map: {}
    replay: {dataset: null, episode: null}
    source: auto                           # auto | policy | script  (auto: 모델 폴더가 있으면 정책, 없으면 코드 도리도리)
    script: {joint: shoulder_pan, amplitude: 15, shakes: 2, shake_s: 0.35}   # 코드 도리도리: 홈 기준 joint만 ±amplitude(최대 30)를 shakes번, 한쪽 shake_s초
```

- [ ] **Step 5: 구현 — `snackbot/robot.py`**

모듈 docstring의 `정책 A(oranda_pickup) · 정책 B(dori_dori) · MoveSource(자세 이동).` 줄을 다음으로 바꾼다:
```python
정책 A(oranda_pickup) · 정책 B(dori_dori) · MoveSource(자세 이동, 코드 도리도리).
- dori_dori: skills.dori_dori.source = auto(모델이 있으면 정책, 없으면 코드) | policy | script.
  코드 도리도리는 홈에서 한 관절만 ±amplitude를 오가는 MoveSource 키프레임이다 (정책 phase처럼 실행 기록).
```

import 줄 `from .skills import RunResult` 다음에 추가:
```python
from .twin import JOINTS
```

`POLICIES = ("oranda_pickup", "dori_dori")` 다음에 추가:
```python
DORI_SOURCES = ("auto", "policy", "script")
DORI_MAX_AMPLITUDE = 30.0                 # 코드 도리도리 진폭 안전 상한 (normalized)
DORI_DEFAULTS = {"joint": "shoulder_pan", "amplitude": 15, "shakes": 2, "shake_s": 0.35}
BODY_JOINTS = JOINTS[:GRIPPER]            # 그리퍼를 뺀 몸통 관절 5개
```

`def _ms(t0):` 함수 다음에 추가:
```python
def dori_settings(conf):
    """skills.dori_dori.script → {joint(관절 번호), amplitude, shakes, shake_s}.
    잘못된 값은 시작할 때 SystemExit. 진폭은 안전 상한 30으로 자른다 (경고)."""
    s = {**DORI_DEFAULTS, **(conf or {})}
    if s["joint"] not in BODY_JOINTS:
        raise SystemExit(f"config.yaml skills.dori_dori.script.joint는 {', '.join(BODY_JOINTS)} 중 하나예요: {s['joint']}")
    try:
        amplitude, shakes, shake_s = float(s["amplitude"]), int(s["shakes"]), float(s["shake_s"])
    except (TypeError, ValueError) as e:
        raise SystemExit(f"config.yaml skills.dori_dori.script 값이 숫자가 아니에요: {e}") from e
    if amplitude <= 0 or shakes < 1 or shake_s <= 0:
        raise SystemExit("config.yaml skills.dori_dori.script: amplitude > 0, shakes >= 1, shake_s > 0 이어야 해요")
    if amplitude > DORI_MAX_AMPLITUDE:
        log.warning("코드 도리도리 진폭 %.1f → %.0f로 자름 (안전 상한)", amplitude, DORI_MAX_AMPLITUDE)
        amplitude = DORI_MAX_AMPLITUDE
    return {"joint": BODY_JOINTS.index(s["joint"]), "amplitude": amplitude, "shakes": shakes, "shake_s": shake_s}


def dori_keyframes(home, joint, amplitude, shakes):
    """홈에서 joint만 +A, −A를 shakes번 오간 뒤 홈. 다른 관절은 홈 값, 값은 −100..100으로 자른다."""
    home = np.asarray(home, np.float32)
    frames = []
    for _ in range(shakes):
        for sign in (1, -1):
            k = home.copy()
            k[joint] = np.clip(home[joint] + sign * amplitude, -100, 100)
            frames.append(k)
    frames.append(home.copy())
    return frames
```

`build_policies`의 반복문을 다음으로 바꾼다:
```python
    for name in POLICIES:
        if name == "dori_dori" and (sk[name].get("source") or "auto") == "script":
            log.info("dori_dori: source가 script라 정책을 로드하지 않아요 (코드 도리도리)")
            continue
        export_dir = Path(sk[name]["export_dir"])
        if export_dir.is_dir():
            found[name] = export_dir
        else:
            log.warning("%s 정책을 로드하지 않아요: 폴더가 없어요 (%s)", name, export_dir)
```

`RobotSkills.__init__`의 다음 두 줄
```python
        if policies is None:
            policies, models = build_policies(cfg)
        self.policies, self.models = policies, models or {}
```
을 다음으로 바꾼다:
```python
        if policies is None:
            policies, models = build_policies(cfg)
        policies, models = dict(policies), dict(models or {})
        dori_cfg = sk.get("dori_dori") or {}
        source = dori_cfg.get("source") or "auto"
        if source not in DORI_SOURCES:
            raise SystemExit(f"config.yaml skills.dori_dori.source는 auto | policy | script 중 하나예요: {source}")
        if source == "policy" and "dori_dori" not in policies:
            raise SystemExit("skills.dori_dori.source가 policy인데 dori_dori 모델이 없어요: export_dir 폴더를 확인하거나 "
                             "source를 auto(모델이 없으면 코드 도리도리) 또는 script로 바꾸세요.")
        self.dori_source = "policy" if source != "script" and "dori_dori" in policies else "script"
        self.dori = None
        if self.dori_source == "script":   # 모델이 있어도 쓰지 않는다 (warmup도 하지 않는다)
            self.dori = dori_settings(dori_cfg.get("script"))
            policies.pop("dori_dori", None)
            models.pop("dori_dori", None)
            log.info("dori_dori: 코드 도리도리 (%s ±%.0f, %d번, 한쪽 %.2f초)", BODY_JOINTS[self.dori["joint"]],
                     self.dori["amplitude"], self.dori["shakes"], self.dori["shake_s"])
        self.policies, self.models = policies, models
```

`run()`을 다음으로 바꾼다:
```python
    def run(self, name, on_phase=None):
        if name not in POLICIES:
            raise ValueError(f"알 수 없는 스킬: {name}")
        if name not in self.policies and not (name == "dori_dori" and self.dori_source == "script"):
            raise RuntimeError(f"{name} 정책이 로드되지 않았어요 (config.yaml skills.{name}.export_dir 폴더 확인)")
        result = None
        try:
            result = self._run(name, on_phase)
            return result
        finally:
            try:
                # 정책(또는 코드 도리도리) phase를 기록했으면 결과와 함께 episode.json (백그라운드)
                folder = self.recorder.stop(result)
                if result is not None and folder is not None:
                    result.record = Path(folder).as_posix()
            except Exception as e:
                log.warning("실행 기록 마무리 실패: %s", e)
```

`_run()`에서
```python
        if self.ensure_home(gen) == "estop":
            return RunResult("estop", False, _ms(t0))
```
다음 줄에 추가:
```python
        if name == "dori_dori" and self.dori_source == "script":
            if self._script_dori(gen) == "estop":
                return RunResult("estop", False, _ms(t0))
            return RunResult("script", False, _ms(t0))
```

`_policy()` 다음에 추가:
```python
    def _script_dori(self, gen):
        """코드 도리도리: 홈에서 한 관절만 ±amplitude를 shakes번 오간 뒤 홈 (끝 키프레임이 홈이라 도착만 확인한다).
        정책 phase처럼 실행 기록에 남긴다. 결과: done | estop."""
        d = self.dori
        keyframes = dori_keyframes(self.home, d["joint"], d["amplitude"], d["shakes"])
        self.recorder.start("dori_dori")
        self.tap.recorder = self.recorder
        try:
            reason = self._move(keyframes, gen, segment_s=d["shake_s"])
        finally:
            self.tap.recorder = None
        if reason == "timeout":   # 끝(홈)에 닿기 전에 시간이 다 됐다: 홈으로 마저 간다
            reason = self._move([self.home], gen)
        return reason
```

`_move()`를 다음으로 바꾼다:
```python
    def _move(self, targets, gen, segment_s=None):
        """targets를 차례로 선형 보간 이동. 구간마다 segment_s초 (기본 skills.move_s)."""
        seg = self.move_s if segment_s is None else float(segment_s)
        src = MoveSource(targets, seg * self.fps)
        result = self._phase(src, len(targets) * seg + 2.0, gen, done=src.done)
        if result == "done" and self._settle(targets[-1], gen) == "estop":
            return "estop"
        return result
```

- [ ] **Step 6: 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_robot.py tests/test_config.py tests/test_skills.py tests/test_main.py -q`
Expected: 모두 PASS (기존 `make()`는 정책 2개를 넣으므로 `auto` → 정책 그대로)

Run: `.venv/Scripts/python -m pytest -q`
Expected: 모두 통과

- [ ] **Step 7: 커밋**

```bash
git add snackbot/robot.py snackbot/skills.py config.yaml tests/test_robot.py tests/test_config.py
git commit -m "feat(robot): 코드 도리도리 (skills.dori_dori.source auto|policy|script)

Co-Authored-By: <세션의 attribution 줄>"
```

---

### Task 2: Controller `TESTING` — 스킬 1회 실행

**Files:**
- Modify: `snackbot/controller.py`, `snackbot/skills.py` (`DrySkills.go_home`)
- Test: `tests/test_controller.py`, `tests/test_skills.py`

**Interfaces:**
- Consumes: `skills.run(name, on_phase=None) -> RunResult`(`record`는 `getattr`로, 없으면 None), `skills.go_home() -> "done" | "estop" | "timeout" | None`(None은 `"done"`으로 본다), Task 1의 `RunResult.record`
- Produces (`snackbot/controller.py`):
  - `TESTING = "TESTING"`, `TEST_SKILLS = ("oranda_pickup", "dori_dori", "home")`, `STOP_REASON_KO: dict[str, str]`, `TEST_LABELS`
  - `Controller.command(name, expect_gen=None, skill=None)` — `name == "test"`이면 `_request_test(skill, expect_gen=expect_gen)`의 bool을 돌려준다
  - `Controller._request_test(skill, expect_gen=None, origin="button") -> bool` — 허용 외 skill은 `ValueError`, 거부면 시스템 메시지 + False
  - `Controller.step_test() -> str | None` — 루프 스레드 전용. 대기 중인 테스트가 없거나 취소됐으면 None, 아니면 stop_reason (`"error"`: 예외)
  - `Controller._pending_test: tuple[str, int, str] | None` = (skill, gen, origin)
  - JSONL 테스트 줄 `{"ts","type":"test","skill","origin","stop_reason","grasped","ms","record","error"}`
- Produces (`snackbot/skills.py`): `DrySkills.go_home() -> "done" | "estop"` (`act_s/2` 대기)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_controller.py` 맨 위 import를 다음으로 바꾼다:
```python
import json
import threading
import time

import pytest

from conftest import FirstRng
from snackbot.brain import Brain
from snackbot.controller import Controller
from snackbot.skills import RunResult
from snackbot.vision import Count
```

파일 끝에 추가:
```python
# --- 스킬 1회 실행 (TESTING) ---
def _states(ev):
    return [(e["state"], e["phase"]) for e in ev if e["type"] == "state"]


def test_test_command_only_requests_and_step_test_runs_once(cfg):
    c, ev = make(cfg)
    assert c.command("test", skill="dori_dori") is True
    assert (c.state, c.skill) == ("TESTING", "dori_dori") and c.skills.runs == []   # 명령은 요청만
    assert c.step_test() == "timeout"
    assert (c.state, c.phase, c.skill) == ("IDLE", "idle", None)
    assert c.skills.runs == ["dori_dori"]
    assert c.history[-1]["role"] == "system"
    assert c.history[-1]["text"].startswith("테스트 · 도리도리: 시간 초과로 끝남 · ")
    assert c.step_test() is None                                  # 대기 중인 테스트 없음
    assert ("TESTING", "acting") in _states(ev) and _states(ev)[-1] == ("IDLE", "idle")


def test_test_oranda_message_has_grasp_and_returning_phase(cfg):
    c, ev = make(cfg)
    c.command("test", skill="oranda_pickup")
    assert c.step_test() == "gripper_open"
    text = c.history[-1]["text"]
    assert text.startswith("테스트 · 오란다: 놓기 감지로 끝남 · 쥠 성공 · ") and text.endswith("초")
    assert ("TESTING", "returning") in _states(ev)


def test_test_home_uses_go_home_without_acting(cfg):
    c, ev = make(cfg)
    c.command("test", skill="home")
    assert c.step_test() == "done"
    assert c.skills.homed == 1 and c.skills.runs == []
    assert c.history[-1]["text"].startswith("테스트 · 홈으로: 완료 · ")
    assert ("TESTING", "returning") in _states(ev) and ("TESTING", "acting") not in _states(ev)


def test_test_message_includes_record_folder(cfg):
    class Recorded(FakeSkills):
        def run(self, name, on_phase=None):
            return RunResult("script", False, 1, record="logs/runs/20261022-120000_dori_dori")

    c, _ = make(cfg, Recorded())
    c.command("test", skill="dori_dori")
    c.step_test()
    text = c.history[-1]["text"]
    assert text.startswith("테스트 · 도리도리: 코드 동작 완료 · ")
    assert text.endswith(" · 기록 logs/runs/20261022-120000_dori_dori")


def test_test_refused_outside_idle_with_reason(cfg):
    c, _ = make(cfg)
    c.chat("2개 옮겨줘")                                           # WORKING
    assert c.command("test", skill="dori_dori") is False
    assert c.state == "WORKING" and "작업 중" in c.history[-1]["text"]
    c.command("estop")
    assert c.command("test", skill="home") is False and "비상정지 중" in c.history[-1]["text"]
    c.command("restart")
    assert c.command("test", skill="dori_dori") is True
    assert c.command("test", skill="home") is False and "이미 테스트 중" in c.history[-1]["text"]
    c2, _ = make(cfg)
    c2.state = "REFUSING"
    assert c2.command("test", skill="dori_dori") is False and "거부 중" in c2.history[-1]["text"]


def test_test_unknown_skill_raises(cfg):
    c, _ = make(cfg)
    with pytest.raises(ValueError):
        c.command("test", skill="dance")
    assert c.state == "IDLE"


def test_start_and_resume_refused_while_testing(cfg):
    c, _ = make(cfg)
    c.command("test", skill="dori_dori")
    c.command("start")
    assert c.state == "TESTING" and c.history[-1]["text"] == "테스트 중이에요. 끝난 뒤 다시 시켜 주세요"
    c.command("resume")
    assert c.state == "TESTING" and c.history[-1]["text"] == "테스트 중이에요. 끝난 뒤 다시 시켜 주세요"
    c.chat("2개 옮겨줘")
    assert c.state == "TESTING" and c.history[-1]["role"] == "robot"   # 채팅은 대답만, 작업 시작 없음
    c.step_test()
    assert c.state == "IDLE" and c.count == 0 and c.remaining == 0


def test_test_does_not_touch_counts_or_cycles_and_logs_type_test(cfg, tmp_path):
    c, ev = make(cfg, log_dir=tmp_path)
    c.command("test", skill="oranda_pickup")
    c.step_test()
    assert (c.count, c.remaining, c.retries, c.cycle_n) == (0, 0, 0, 0)
    assert not [e for e in ev if e["type"] == "cycle"]
    rec = json.loads(next(tmp_path.glob("cycles-*.jsonl")).read_text(encoding="utf-8").splitlines()[0])
    assert rec["type"] == "test" and rec["skill"] == "oranda_pickup" and rec["origin"] == "button"
    assert rec["stop_reason"] == "gripper_open" and rec["grasped"] is True and rec["error"] is None
    assert isinstance(rec["ms"], int) and rec["record"] is None


def test_test_skill_exception_reports_and_returns_idle(cfg, caplog, tmp_path):
    class Boom(FakeSkills):
        def run(self, name, on_phase=None):
            raise RuntimeError("motor")

    c, _ = make(cfg, Boom(), log_dir=tmp_path)
    c.command("test", skill="oranda_pickup")
    with caplog.at_level("WARNING"):
        assert c.step_test() == "error"
    assert c.state == "IDLE" and c._run_idle.is_set()
    assert c.history[-1]["text"] == "테스트 실패: motor"
    assert "motor" in caplog.text
    rec = json.loads(next(tmp_path.glob("cycles-*.jsonl")).read_text(encoding="utf-8").splitlines()[0])
    assert rec["stop_reason"] == "error" and rec["error"] == "motor"


def test_estop_during_test_is_immediate_and_restart_waits(cfg):
    sk = BlockingRun()
    c, _ = make(cfg, sk)
    c.command("test", skill="oranda_pickup")
    t = threading.Thread(target=c.step_test, daemon=True)
    t.start()
    assert sk.entered.wait(2)
    c.command("estop")
    assert c.state == "ESTOP" and sk.estopped                # 테스트를 기다리지 않는다
    c.restart_wait_s = 0
    c.command("restart")
    assert c.state == "ESTOP" and "멈추는 중" in c.history[-1]["text"]
    sk.release.set()
    t.join(5)
    assert not t.is_alive() and c.state == "ESTOP"           # 끝난 테스트가 상태를 덮지 않는다
    assert "비상정지로 멈춤" in c.history[-1]["text"]
    c.restart_wait_s = 5
    c.command("restart")
    assert c.state == "IDLE"


def test_test_canceled_when_generation_changed_after_receipt(cfg):
    c, _ = make(cfg)
    g = c.generation()
    c.command("estop")
    c.command("restart")                                     # 접수 뒤 비상정지·재시작이 끼어들었다 (다시 IDLE)
    assert c.command("test", skill="dori_dori", expect_gen=g) is False
    assert c.state == "IDLE" and "테스트가 취소됐어요" in c.history[-1]["text"]
    assert c.command("test", skill="dori_dori", expect_gen=c.generation()) is True


def test_estop_before_loop_picks_test_drops_it(cfg):
    c, _ = make(cfg)
    c.command("test", skill="dori_dori")
    c.command("estop")
    c.command("restart")
    assert c.step_test() is None and c.skills.runs == [] and c.state == "IDLE"


def test_skill_estop_result_during_test_latches_estop(cfg):
    c, _ = make(cfg, EstopReason())
    c.command("test", skill="dori_dori")
    assert c.step_test() == "estop"
    assert c.state == "ESTOP"


def test_loop_thread_runs_tests_and_skills_only_on_loop_thread(cfg):
    class Where(FakeSkills):
        def __init__(self):
            super().__init__()
            self.threads = []

        def run(self, name, on_phase=None):
            self.threads.append(threading.current_thread().name)
            return super().run(name, on_phase)

        def go_home(self):
            self.threads.append(threading.current_thread().name)
            return super().go_home()

    sk = Where()
    c, _ = make(cfg, sk)
    c.start()
    try:
        c.command("test", skill="dori_dori")
        assert _wait_for(lambda: c.state == "IDLE" and sk.runs == ["dori_dori"])
        c.command("test", skill="home")
        assert _wait_for(lambda: c.state == "IDLE" and sk.homed == 1)
    finally:
        c.stop()
    assert sk.threads == ["controller", "controller"]
```

`tests/test_skills.py` 파일 끝에 추가:
```python
def test_go_home_short_wait_and_estop(cfg):
    cfg["dry_run"]["act_s"] = 0.2
    s = DrySkills(cfg)
    t0 = time.monotonic()
    assert s.go_home() == "done" and time.monotonic() - t0 >= 0.09
    s.estop()
    assert s.go_home() == "estop"
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_controller.py tests/test_skills.py -q`
Expected: FAIL — `TypeError: Controller.command() got an unexpected keyword argument 'skill'`, `AttributeError: 'Controller' object has no attribute 'step_test'`, `assert None == 'done'`

- [ ] **Step 3: 구현 — `DrySkills.go_home`**

`snackbot/skills.py`의
```python
    def go_home(self):
        pass
```
를 다음으로 바꾼다:
```python
    def go_home(self):
        """홈 복귀 흉내: act_s의 절반을 기다린다 (스킬 테스트 '홈으로'·재시작). 비상정지면 "estop"."""
        return "done" if self._wait(self.act_s / 2) else "estop"
```

- [ ] **Step 4: 구현 — `snackbot/controller.py` 상수**

모듈 docstring 끝(`성공 판정: ...` 줄 다음)에 추가:
```python
스킬 테스트(TESTING): command("test", skill=)는 대기(IDLE)에서만 받아 요청 슬롯에 넣고, 루프 스레드가 step_test()로
한 번 실행한다. 횟수·피로도·사이클 통계에는 넣지 않는다 (설계: docs/superpowers/specs/2026-10-22-skill-test-and-scripted-dori-design.md).
```

`IDLE, WORKING, REFUSING, DONE, ESTOP = ...` 줄을 다음으로 바꾼다:
```python
IDLE, WORKING, REFUSING, DONE, ESTOP, TESTING = "IDLE", "WORKING", "REFUSING", "DONE", "ESTOP", "TESTING"
TEST_SKILLS = ("oranda_pickup", "dori_dori", "home")
TEST_LABELS = {"dori_dori": "도리도리", "home": "홈으로"}   # oranda_pickup은 target 이름
STOP_REASON_KO = {"gripper_open": "놓기 감지로 끝남", "timeout": "시간 초과로 끝남", "estop": "비상정지로 멈춤",
                  "script": "코드 동작 완료", "done": "완료"}
```

`_RESTART_CANCELED = ...` 줄 다음에 추가:
```python
_TEST_BUSY = "테스트 중이에요. 끝난 뒤 다시 시켜 주세요"
_TEST_CANCELED = "테스트가 취소됐어요: 그 사이 비상정지나 상태 변경이 있었어요"
_TEST_REFUSED = {WORKING: "작업 중에는 스킬 테스트를 할 수 없어요",
                 REFUSING: "거부 중에는 스킬 테스트를 할 수 없어요. 재개하거나 재시작한 뒤에 하세요",
                 DONE: "작업을 마무리하는 중이에요. 잠시 뒤 다시 눌러 주세요",
                 ESTOP: "비상정지 중이에요. 재시작한 뒤 테스트하세요",
                 TESTING: "이미 테스트 중이에요"}
```

- [ ] **Step 5: 구현 — `__init__`, `command`, 시작·재개 거부, 비상정지**

`__init__`의 `self.decision = cfg["decision"]` 다음 줄에 추가:
```python
        self.target_name = cfg["target"]["name"]
```
`self._gen = 0 ...` 줄 다음에 추가:
```python
        self._pending_test = None  # (skill, gen, origin): 루프 스레드가 step_test()로 꺼내 실행한다
```

`command()`를 다음으로 바꾼다:
```python
    def command(self, name, expect_gen=None, skill=None):
        if name == "start":
            self._start_task(None, announce=True)
        elif name == "resume":
            self._resume(announce=True)
        elif name == "estop":
            self._estop()
        elif name == "restart":
            if expect_gen is None:
                self._restart()
            else:
                self._restart(expect_gen)
        elif name == "test":
            return self._request_test(skill, expect_gen=expect_gen)
        elif name == "quit":
            self.stop()
        else:
            raise ValueError(f"알 수 없는 명령: {name}")
```

`_start_task()` 전체를 다음으로 바꾼다 (테스트 중이면 시스템 메시지로 거부):
```python
    def _start_task(self, n, announce=False):
        with self._lock:
            busy = self.state == TESTING
            if not busy and self.state not in (IDLE, DONE):
                return False
            if not busy:
                self._gen += 1
                self.remaining = n or self.initial_count
                self.count = self.retries = 0
                self.skill, self.vision_method, self.last_boxes = None, "estimate", None
                self.state, self.phase = WORKING, "idle"
                self.skills.new_task(self.remaining)
        if busy:
            self.notify(_TEST_BUSY)
            return False
        if announce:
            self._message("robot", self.brain.line("start"))
        self._publish()
        self._wake.set()
        return True
```

`_resume()`를 다음으로 바꾼다:
```python
    def _resume(self, announce=False):
        with self._lock:
            busy = self.state == TESTING
            if not busy:
                if self.state == REFUSING:
                    self.count = 0
                    self.state = WORKING
                elif not (self.state == WORKING and self.phase == "waiting_operator"):
                    return False
                self._gen += 1
                self.retries = 0
                self.phase = "idle"
        if busy:
            self.notify(_TEST_BUSY)
            return False
        if announce:
            self._message("robot", self.brain.line("resume"))
        self._publish()
        self._wake.set()
        return True
```

`_estop()`의 락 블록
```python
        with self._lock:
            already = self.state == ESTOP
            self._gen += 1
            self.state, self.phase = ESTOP, "idle"  # 이미 ESTOP이면 진행 중인 재시작도 중단
```
을 다음으로 바꾼다:
```python
        with self._lock:
            already = self.state == ESTOP
            self._gen += 1
            self.state, self.phase = ESTOP, "idle"  # 이미 ESTOP이면 진행 중인 재시작도 중단
            self._pending_test = None  # 아직 시작 안 한 스킬 테스트는 버린다
```

- [ ] **Step 6: 구현 — 테스트 요청과 실행**

`_restart()` 다음(`# ---- 사이클 ----` 앞)에 추가:
```python
    # ---- 스킬 테스트 (TESTING) ----
    def _request_test(self, skill, expect_gen=None, origin="button"):
        """스킬 1회 실행 요청. 대기(IDLE)이고 진행 중인 동작이 없을 때만 받는다.
        expect_gen: 접수 순간의 세션 번호 (그 뒤 비상정지·재시작이 끼면 거부). 실행은 루프 스레드(step_test)가 한다."""
        if skill not in TEST_SKILLS:
            raise ValueError(f"알 수 없는 테스트 스킬: {skill}")
        with self._lock:
            if expect_gen is not None and self._gen != expect_gen:
                refused = _TEST_CANCELED
            elif self.state != IDLE:
                refused = _TEST_REFUSED.get(self.state, "대기 상태에서만 테스트할 수 있어요")
            elif not self._run_idle.is_set():
                refused = "아직 동작이 끝나지 않았어요. 잠시 뒤 다시 눌러 주세요"
            else:
                refused = None
                self._gen += 1
                self._pending_test = (skill, self._gen, origin)
                self.state, self.phase, self.skill = TESTING, "idle", skill
        if refused:
            log.info("스킬 테스트 거부 (%s): %s", skill, refused)
            self.notify(refused)
            return False
        self._publish()
        self._wake.set()
        return True

    def _set_test_phase(self, phase, gen):
        with self._lock:
            if self.state != TESTING or self._gen != gen:
                return
            self.phase = phase
        self._publish()

    def step_test(self):
        """대기 중인 스킬 테스트 1회 (루프 스레드에서만 부른다).
        없거나 접수 뒤 세션이 바뀌었으면 None, 아니면 stop_reason (예외면 "error")."""
        with self._lock:
            job, self._pending_test = self._pending_test, None
            if job is None:
                return None
            skill, gen, origin = job
            if self.state != TESTING or self._gen != gen:
                return None
            self._run_idle.clear()  # 확인과 같은 락 안: 재시작이 그 사이로 끼어들지 못한다
        t0 = time.monotonic()
        stop_reason, grasped, record, error = None, False, None, None
        try:
            if skill == "home":
                self._set_test_phase("returning", gen)
                stop_reason = self.skills.go_home() or "done"
            else:
                self._set_test_phase("acting", gen)
                r = self.skills.run(skill, on_phase=lambda phase: self._set_test_phase(phase, gen))
                stop_reason, grasped, record = r.stop_reason, bool(r.grasped), getattr(r, "record", None)
        except Exception as e:
            log.warning("스킬 테스트 실패 (%s): %r", skill, e, exc_info=True)
            error = e
        finally:
            self._run_idle.set()
        ms = _ms(t0)
        with self._lock:
            current = self.state == TESTING and self._gen == gen
            if current:
                if stop_reason == "estop":  # 스킬 쪽에서 멈췄다 (예: Ctrl+C): 사이클과 같이 비상정지로 맞춘다
                    self.state, self.phase = ESTOP, "idle"
                else:
                    self.state, self.phase, self.skill = IDLE, "idle", None
        if error is not None:
            self.notify(f"테스트 실패: {error}")
        else:
            self.notify(self._test_text(skill, origin, stop_reason, grasped, ms, record))
        if current:
            self._publish()
        result = "error" if error is not None else stop_reason
        self._log_test(skill, origin, result, grasped, ms, record, error)
        return result

    def _test_text(self, skill, origin, stop_reason, grasped, ms, record):
        """결과 한 줄: 버튼 '테스트 · 오란다: 놓기 감지로 끝남 · 쥠 성공 · 12.3초 · 기록 …', LLM '도리도리 · …'."""
        how = STOP_REASON_KO.get(stop_reason, str(stop_reason))
        label = self.target_name if skill == "oranda_pickup" else TEST_LABELS[skill]
        parts = [f"도리도리 · {how}" if origin == "llm" else f"테스트 · {label}: {how}"]
        if skill == "oranda_pickup":
            parts.append("쥠 성공" if grasped else "쥠 없음")
        parts.append(f"{ms / 1000:.1f}초")
        if record:
            parts.append(f"기록 {record}")
        return " · ".join(parts)

    def _log_test(self, skill, origin, stop_reason, grasped, ms, record, error):
        """사이클 통계와 섞이지 않게 type "test"로 남긴다 (cycle 번호·이벤트 없음). 기록 실패는 경고만."""
        try:
            self._append_log({"ts": self.clock(), "type": "test", "skill": skill, "origin": origin,
                              "stop_reason": stop_reason, "grasped": grasped, "ms": ms, "record": record,
                              "error": None if error is None else str(error)})
        except Exception as e:
            log.warning("테스트 로그 기록 실패: %s", e)
```

`_log_cycle()`의 끝
```python
        self._emit({"type": "cycle", "n": n, "result": result, "ms": dict(ms)})
        if self.log_path is not None:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
```
을 다음으로 바꾼다:
```python
        self._emit({"type": "cycle", "n": n, "result": result, "ms": dict(ms)})
        self._append_log(record)

    def _append_log(self, record):
        if self.log_path is not None:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
```

- [ ] **Step 7: 구현 — 루프에서 테스트 실행**

`_run()`의 마지막 `else:` 블록
```python
            else:
                self._wake.wait(0.2)
                self._wake.clear()
```
을 다음으로 바꾼다:
```python
            else:
                try:
                    ran = self.step_test()  # 스킬 테스트도 이 스레드에서만 (두 스레드가 스킬을 부르지 않게)
                except Exception:
                    log.exception("스킬 테스트 처리 실패")
                    ran = None
                if ran is None:
                    self._wake.wait(0.2)
                    self._wake.clear()
```

- [ ] **Step 8: 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_controller.py tests/test_skills.py -q`
Expected: 모두 PASS

Run: `.venv/Scripts/python -m pytest -q`
Expected: 모두 통과

- [ ] **Step 9: 커밋**

```bash
git add snackbot/controller.py snackbot/skills.py tests/test_controller.py tests/test_skills.py
git commit -m "feat(controller): TESTING 상태로 스킬 1회 실행 (루프 스레드, 세대 확인, 결과 메시지·JSONL)

Co-Authored-By: <세션의 attribution 줄>"
```

---

### Task 3: LLM이 도리도리를 채팅 의도로 호출

**Files:**
- Modify: `snackbot/brain.py`, `snackbot/controller.py` (`chat`)
- Test: `tests/test_brain.py`, `tests/test_controller.py`

**Interfaces:**
- Consumes: Task 2의 `Controller._request_test(skill, expect_gen=None, origin="button") -> bool`
- Produces (`snackbot/brain.py`):
  - `allowed_intents("IDLE") == ["start_task", "chat", "dori_dori"]` (DONE은 `["start_task", "chat"]` 그대로, TESTING은 `["chat"]`)
  - `DORI_WORDS = ("도리도리", "고개 저어", "고개를 저어")`, `keyword_intent`가 허용될 때만 `"dori_dori"`
  - `CHAT_SYSTEM`에 `- dori_dori: 고개를 좌우로 젓는 동작 한 번 (싫다고 하거나, 도리도리를 해 보라고 할 때)`
  - `LINES["dori_chat"]`, `LINES["testing"]`
- Produces (`Controller.chat`): intent `dori_dori` → 대사 뒤 `_request_test("dori_dori", expect_gen=<채팅 접수 때 세대>, origin="llm")`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_brain.py`의 `test_allowed_intents`를 다음으로 바꾼다:
```python
def test_allowed_intents():
    assert allowed_intents("IDLE") == ["start_task", "chat", "dori_dori"]
    assert allowed_intents("DONE") == ["start_task", "chat"]
    assert allowed_intents("REFUSING") == ["resume", "chat"]
    assert allowed_intents("WORKING") == ["chat"]
    assert allowed_intents("ESTOP") == ["chat"]
    assert allowed_intents("TESTING") == ["chat"]
```

`tests/test_brain.py` 파일 끝에 추가:
```python
def test_keyword_dori_only_when_allowed():
    idle = allowed_intents("IDLE")
    for text in ("도리도리 해 봐", "고개 저어 봐", "고개를 저어 줘"):
        assert keyword_intent(text, idle) == "dori_dori"
    assert keyword_intent("도리도리 해 봐", allowed_intents("WORKING")) == "chat"
    assert keyword_intent("도리도리 해 봐", allowed_intents("DONE")) == "chat"


def test_chat_rules_dori_in_idle_only_and_testing_line(cfg):
    b = make(cfg)
    assert b.chat("도리도리 해 봐", "IDLE", 0) == {"intent": "dori_dori", "say": "도리도리~ 이렇게요?",
                                                "n": None, "source": "rules"}
    assert b.chat("도리도리 해 봐", "WORKING", 1)["intent"] == "chat"
    r = b.chat("옮겨줘", "TESTING", 0)
    assert r["intent"] == "chat" and r["say"] == "지금 테스트 중이에요. 끝나면 시켜 주세요!"


def test_chat_llm_dori_tool_only_in_idle(cfg):
    r = make(cfg, '{"intent": "dori_dori", "say": "싫어요~", "n": null}').chat("너 싫지?", "IDLE", 0)
    assert r == {"intent": "dori_dori", "say": "싫어요~", "n": None, "source": "fake"}
    r = make(cfg, '{"intent": "dori_dori", "say": "싫어요~", "n": null}').chat("너 싫지?", "WORKING", 2)
    assert r["intent"] == "chat" and r["say"] == "싫어요~"


def test_chat_prompt_describes_dori_tool(cfg):
    fake = Scripted('{"intent": "chat", "say": "네", "n": null}')
    Brain(cfg, chain=Chain([Member("f", fake)]), rng=FirstRng()).chat("안녕", "IDLE", 0)
    system = fake.messages[0]["content"]
    assert "- dori_dori: 고개를 좌우로 젓는 동작 한 번 (싫다고 하거나, 도리도리를 해 보라고 할 때)" in system
    assert json.loads(fake.messages[-1]["content"])["allowed"] == ["start_task", "chat", "dori_dori"]
```

`tests/test_controller.py` 파일 끝에 추가:
```python
# --- LLM 도리도리 (채팅 의도) ---
def test_chat_dori_runs_one_test_with_llm_prefix(cfg):
    c, _ = make(cfg)
    c.chat("도리도리 해 봐")
    assert c.state == "TESTING" and c.skill == "dori_dori"
    assert [m["role"] for m in c.history] == ["user", "robot"]   # 대사 먼저, 실행은 루프 스레드
    assert c.step_test() == "timeout"
    assert c.state == "IDLE" and c.skills.runs == ["dori_dori"] and c.count == 0
    assert c.history[-1]["text"].startswith("도리도리 · 시간 초과로 끝남 · ")


def test_chat_dori_ignored_outside_idle(cfg):
    c, _ = make(cfg)
    c.chat("2개 옮겨줘")
    c.chat("도리도리 해 봐")
    assert c.state == "WORKING" and c._pending_test is None


def test_chat_dori_canceled_if_session_changed_during_llm(cfg):
    class SlowBrain(Brain):
        ctrl = None

        def chat(self, text, state, count, history=None):
            r = super().chat(text, state, count, history=history)
            self.ctrl._estop()                                     # LLM을 기다리는 사이 비상정지·재시작
            self.ctrl._restart()
            return r

    b = SlowBrain(cfg, rng=FirstRng())
    c = Controller(cfg, b, FakeSkills())
    b.ctrl = c
    c.chat("도리도리 해 봐")
    assert c.state == "IDLE" and c._pending_test is None
    assert "테스트가 취소됐어요" in c.history[-1]["text"]
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_brain.py tests/test_controller.py -q`
Expected: FAIL — `test_allowed_intents` (`['start_task', 'chat'] != [...]`), dori 키워드·프롬프트·controller chat 테스트 실패

- [ ] **Step 3: 구현 — `snackbot/brain.py`**

`RESUME_WORDS = ...` 줄 다음에 추가:
```python
DORI_WORDS = ("도리도리", "고개 저어", "고개를 저어")
```

`LINES`의 `"refusing": [...]` 줄 다음에 추가:
```python
    "dori_chat": ["도리도리~ 이렇게요?", "싫어요~ 도리도리!"],
    "testing": ["지금 테스트 중이에요. 끝나면 시켜 주세요!"],
```

`CHAT_SYSTEM`의
```
- resume: 거부 중일 때 달래거나 다시 해 달라는 부탁
```
줄 다음에 추가:
```
- dori_dori: 고개를 좌우로 젓는 동작 한 번 (싫다고 하거나, 도리도리를 해 보라고 할 때)
```

`allowed_intents`를 다음으로 바꾼다:
```python
def allowed_intents(state):
    if state == "IDLE":
        return ["start_task", "chat", "dori_dori"]   # dori_dori: 도리도리 1회 (스킬 테스트와 같은 경로)
    if state == "DONE":
        return ["start_task", "chat"]
    if state == "REFUSING":
        return ["resume", "chat"]
    return ["chat"]
```

`keyword_intent`를 다음으로 바꾼다:
```python
def keyword_intent(text, allowed):
    if "dori_dori" in allowed and any(w in text for w in DORI_WORDS):
        return "dori_dori"
    if "resume" in allowed and any(w in text for w in RESUME_WORDS):
        return "resume"
    if "start_task" in allowed and any(w in text for w in START_WORDS):
        return "start_task"
    return "chat"
```

`_chat_line`을 다음으로 바꾼다:
```python
    @staticmethod
    def _chat_line(intent, state):
        if intent == "start_task":
            return "start"
        if intent == "resume":
            return "resume"
        if intent == "dori_dori":
            return "dori_chat"
        return {"WORKING": "busy", "REFUSING": "refusing", "ESTOP": "estop", "TESTING": "testing"}.get(state, "chat")
```

- [ ] **Step 4: 구현 — `Controller.chat`**

`chat()`의
```python
        with self._lock:
            state, count = self.state, self.count
        r = self.brain.chat(text, state, count, history=hist)
        self._message("robot", r["say"])
        if r["intent"] == "start_task":
            self._start_task(r.get("n"))
        elif r["intent"] == "resume":
            self._resume()
```
를 다음으로 바꾼다:
```python
        with self._lock:
            state, count, gen = self.state, self.count, self._gen
        r = self.brain.chat(text, state, count, history=hist)
        self._message("robot", r["say"])
        if r["intent"] == "start_task":
            self._start_task(r.get("n"))
        elif r["intent"] == "resume":
            self._resume()
        elif r["intent"] == "dori_dori":
            # 버튼과 같은 경로 (대기 상태에서만, 횟수·피로도 미반영). LLM을 기다리는 사이 세션이 바뀌었으면 취소
            self._request_test("dori_dori", expect_gen=gen, origin="llm")
```

- [ ] **Step 5: 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_brain.py tests/test_controller.py -q`
Expected: 모두 PASS

Run: `.venv/Scripts/python -m pytest -q`
Expected: 모두 통과

- [ ] **Step 6: 커밋**

```bash
git add snackbot/brain.py snackbot/controller.py tests/test_brain.py tests/test_controller.py
git commit -m "feat(brain): 대기 중 채팅 의도 dori_dori로 도리도리 1회 실행

Co-Authored-By: <세션의 attribution 줄>"
```

---

### Task 4: 서버 `test` 명령 · `info.tests` · 모델 표시

**Files:**
- Modify: `snackbot/server.py`, `snackbot/__main__.py`
- Test: `tests/test_server.py`, `tests/test_main.py`

**Interfaces:**
- Consumes: `snackbot.controller.TEST_SKILLS`, `Controller.generation()`, `Controller.command("test", skill=, expect_gen=)`, Task 1의 `RobotSkills.dori_source`·`policies`
- Produces (WS 계약): 화면 → 서버 `{"type":"command","name":"test","skill":"oranda_pickup"|"dori_dori"|"home"}` (허용 외 skill·없음은 무시)
- Produces (`snackbot/__main__.py`):
  - `act_label(cfg, skills) -> str` — 예: `"ACT · OpenVINO · GPU (oranda_pickup) · 도리도리: 코드 동작"`
  - `skill_tests_info(cfg, skills) -> list[{"skill","label","enabled","reason"}]` (이름이 `test`로 시작하지 않게 한다: pytest가 함수로 모으지 않도록)
  - `info["tests"]`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_server.py` 파일 끝에 추가:
```python
def test_ws_test_command_enters_testing_and_ignores_unknown_skill(cfg, tmp_path):
    c, app = make_app(cfg, tmp_path)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json(), ws.receive_json()
        ws.send_json({"type": "command", "name": "test", "skill": "dance"})   # 허용 외: 무시
        ws.send_json({"type": "command", "name": "test"})                     # skill 없음: 무시
        ws.send_json({"type": "command", "name": "test", "skill": "home"})
        ws.send_json({"type": "chat", "text": "안녕"})                         # 같은 FIFO: 테스트 요청 뒤에 처리
        events = []
        while not (events and events[-1].get("role") == "robot"):
            events.append(ws.receive_json())
    assert [(e["state"], e["skill"]) for e in events if e["type"] == "state"] == [("TESTING", "home")]
    assert c._pending_test is not None and c._pending_test[0] == "home"
    assert not any(m["role"] == "system" for m in c.history)               # 거부 메시지 없음


def test_ws_test_carries_generation_seen_on_receipt(cfg, tmp_path, monkeypatch):
    import threading
    c, app = make_app(cfg, tmp_path)
    gate, got, done = threading.Event(), threading.Event(), threading.Event()
    results = []
    orig_gen, orig_request = c.generation, c._request_test

    def generation():
        g = orig_gen()
        got.set()
        return g

    def request(skill, expect_gen=None, origin="button"):
        results.append(orig_request(skill, expect_gen=expect_gen, origin=origin))
        done.set()
        return results[-1]

    monkeypatch.setattr(c, "generation", generation)
    monkeypatch.setattr(c, "_request_test", request)
    monkeypatch.setattr(c, "chat", lambda text, source="text": gate.wait(5))  # 워커를 붙잡아 test를 큐에 쌓는다
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json(), ws.receive_json()
        ws.send_json({"type": "chat", "text": "붙잡기"})
        ws.send_json({"type": "command", "name": "test", "skill": "dori_dori"})
        assert got.wait(5)            # 서버가 test를 접수하고 세션 번호를 읽었다
        c.command("estop")            # 접수 뒤에 비상정지·재시작이 끼어든다 (다시 IDLE)
        c.command("restart")
        gate.set()
        assert done.wait(5)
    assert results == [False]
    assert c.state == "IDLE" and c._pending_test is None and c.skills.runs == []
```

`tests/test_main.py` 파일 끝에 추가:
```python
def test_build_dry_run_info_tests_all_enabled(cfg):
    parts = build(cfg, env={}, dry_run=True)
    try:
        assert parts["info"]["tests"] == [
            {"skill": "oranda_pickup", "label": "오란다 1회", "enabled": True, "reason": ""},
            {"skill": "dori_dori", "label": "도리도리 1회", "enabled": True, "reason": ""},
            {"skill": "home", "label": "홈으로", "enabled": True, "reason": ""}]
    finally:
        parts["voice"].close()


def test_build_real_robot_without_models_uses_scripted_dori(real_cfg, capsys):
    real_cfg["skills"]["device"] = "GPU"
    parts = build(real_cfg, {}, dry_run=False)
    try:
        info = parts["info"]
        assert info["models"]["act"] == "ACT · OpenVINO · GPU (정책 없음, oranda_pickup 모델 없음) · 도리도리: 코드 동작"
        assert [(t["skill"], t["enabled"], t["reason"]) for t in info["tests"]] == [
            ("oranda_pickup", False, "모델 없음"), ("dori_dori", True, ""), ("home", True, "")]
        assert "코드 도리도리·home만" in capsys.readouterr().err
    finally:
        parts["voice"].close()


def test_build_real_robot_oranda_with_scripted_dori_act_info(real_cfg, monkeypatch):
    import snackbot.robot as robot
    monkeypatch.setattr(robot, "build_policies", lambda c: ({"oranda_pickup": object()}, {}))
    real_cfg["skills"]["device"] = "GPU"
    parts = build(real_cfg, {}, dry_run=False)
    try:
        assert parts["info"]["models"]["act"] == "ACT · OpenVINO · GPU (oranda_pickup) · 도리도리: 코드 동작"
        assert all(t["enabled"] for t in parts["info"]["tests"])
    finally:
        parts["voice"].close()
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_server.py tests/test_main.py -q`
Expected: FAIL — 서버는 아직 `test` 명령을 무시하므로 `[] != [('TESTING', 'home')]`, 세대 테스트는 약 5초 뒤 `assert done.wait(5)` 실패. main 테스트는 `KeyError: 'tests'`와 act 문자열 불일치

- [ ] **Step 3: 구현 — `snackbot/server.py`**

import 블록의 `from .twin import replay_payload, to_radians` 앞에 추가:
```python
from .controller import TEST_SKILLS
```

`ws_endpoint`의 restart 분기
```python
                    elif kind == "command" and msg.get("name") == "restart":
                        # 접수한 순간의 세션 번호를 함께 넣는다: 대기하는 사이 비상정지가 끼면 이 재시작은 거부된다
                        g = controller.generation()
                        commands.put_nowait((functools.partial(controller.command, "restart", expect_gen=g), ()))
```
다음에 추가:
```python
                    elif kind == "command" and msg.get("name") == "test":
                        skill = msg.get("skill")
                        if skill in TEST_SKILLS:
                            # 재시작과 같은 패턴: 접수 순간의 세션 번호. 기다리는 사이 비상정지·재시작이 끼면 거부된다
                            g = controller.generation()
                            commands.put_nowait((functools.partial(controller.command, "test", skill=skill,
                                                                   expect_gen=g), ()))
                        else:
                            log.info("알 수 없는 테스트 스킬 무시: %r", skill)
```

모듈 docstring의 마지막 줄
```python
메시지 형식: docs/UI_DESIGN_PROMPT.md, 4분할·3D: docs/superpowers/specs/2026-10-22-digital-twin-design.md"""
```
을 다음으로 바꾼다:
```python
메시지 형식: docs/UI_DESIGN_PROMPT.md, 4분할·3D: docs/superpowers/specs/2026-10-22-digital-twin-design.md
스킬 테스트 명령(test): docs/superpowers/specs/2026-10-22-skill-test-and-scripted-dori-design.md 3장"""
```

- [ ] **Step 4: 구현 — `snackbot/__main__.py`**

`KEYS = ...` 줄 다음에 추가:
```python
TEST_BUTTONS = (("oranda_pickup", "{target} 1회"), ("dori_dori", "도리도리 1회"), ("home", "홈으로"))
```

`def build(` 앞에 추가:
```python
def act_label(cfg, skills):
    """화면 '제어' 칸: ACT · OpenVINO · <장치> (+ 로드한 정책·없는 모델, 코드 도리도리면 '· 도리도리: 코드 동작')."""
    from .robot import POLICIES

    script = getattr(skills, "dori_source", None) == "script"
    loaded = [n for n in POLICIES if n in skills.policies]
    missing = [n for n in POLICIES if n not in skills.policies and not (n == "dori_dori" and script)]
    act = f"ACT · OpenVINO · {cfg['skills'].get('device', 'CPU')}"
    if missing:
        act += f" ({'·'.join(loaded) + '만' if loaded else '정책 없음'}, {'·'.join(missing)} 모델 없음)"
    elif script and loaded:
        act += f" ({'·'.join(loaded)})"
    if script:
        act += " · 도리도리: 코드 동작"
    return act


def skill_tests_info(cfg, skills):
    """info.tests: 화면 '스킬 테스트' 버튼. 로드되지 않은 정책 버튼은 끈다 (dry-run·홈·코드 도리도리는 켠다)."""
    policies = getattr(skills, "policies", None)   # DrySkills에는 없다 → 모두 가능 (녹화 재생)
    script = getattr(skills, "dori_source", None) == "script"
    out = []
    for skill, label in TEST_BUTTONS:
        enabled = (skill == "home" or policies is None or skill in policies
                   or (skill == "dori_dori" and script))
        out.append({"skill": skill, "label": label.replace("{target}", cfg["target"]["name"]),
                    "enabled": enabled, "reason": "" if enabled else "모델 없음"})
    return out
```

`build()`의 실제 로봇 분기
```python
        from .config import load_poses
        from .robot import POLICIES, RobotSkills

        # 포즈가 없으면 여기서 SystemExit (physicalai를 import하기 전). connect()는 main이 부른다.
        skills = RobotSkills(cfg, load_poses(cfg.get("poses_file", "poses.yaml")))
        act = f"ACT · OpenVINO · {cfg['skills'].get('device', 'CPU')}"
        loaded = [n for n in POLICIES if n in skills.policies]
        if len(loaded) < len(POLICIES):
            missing = [n for n in POLICIES if n not in skills.policies]
            act += f" ({'·'.join(loaded) + '만' if loaded else '정책 없음'}, {'·'.join(missing)} 모델 없음)"
        if not skills.policies:
            print("경고: 정책 모델이 없어요: home 이동만 확인 가능", file=sys.stderr, flush=True)
```
를 다음으로 바꾼다:
```python
        from .config import load_poses
        from .robot import RobotSkills

        # 포즈가 없으면 여기서 SystemExit (physicalai를 import하기 전). connect()는 main이 부른다.
        skills = RobotSkills(cfg, load_poses(cfg.get("poses_file", "poses.yaml")))
        act = act_label(cfg, skills)
        if not skills.policies:   # 정책이 하나도 없으면 도리도리는 코드 도리도리다 (source: policy면 위에서 SystemExit)
            print("경고: 정책 모델이 없어요: 코드 도리도리·home만 확인 가능", file=sys.stderr, flush=True)
```
(그 다음 `elif "oranda_pickup" not in skills.policies:` 경고는 그대로 둔다.)

`info["replays"] = list_replays(replays_dir)` 다음 줄에 추가:
```python
    info["tests"] = skill_tests_info(cfg, skills)
```

- [ ] **Step 5: 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_server.py tests/test_main.py -q`
Expected: 모두 PASS (`test_build_real_robot_act_info_lists_loaded_policies`·`..._all_policies_plain_act_info`·`..._no_policies_warning`도 그대로 통과)

Run: `.venv/Scripts/python -m pytest -q`
Expected: 모두 통과

- [ ] **Step 6: 커밋**

```bash
git add snackbot/server.py snackbot/__main__.py tests/test_server.py tests/test_main.py
git commit -m "feat(server): WS test 명령(접수 세대)과 info.tests, 코드 도리도리 모델 표시

Co-Authored-By: <세션의 attribution 줄>"
```

---

### Task 5: 화면 — 스킬 테스트 줄 · TESTING 표시 · 목업

**Files:**
- Modify: `frontend/index.html:118-124` (`.ctrl` 영역), `frontend/app.js`, `frontend/style.css` (끝에 추가)

**Interfaces:**
- Consumes: `info.tests: [{skill, label, enabled, reason}]`, `state.state == "TESTING"`, `state.phase` `acting | returning | idle`, `state.skill` `oranda_pickup | dori_dori | home`; 보내는 명령 `{"type":"command","name":"test","skill":...}`
- Produces: `#testBtns` 안의 `.btn-test[data-skill]` 버튼, `S.tests`, `TEST_DEFAULT`, 목업 `runTest(skill, fromChat)`

- [ ] **Step 1: `frontend/index.html` 제어 영역**

다음 블록
```html
    <section class="ctrl">
      <div class="ctrl-small">
        <button class="btn btn-resume" id="btnResume" disabled>재개</button>
        <button class="btn btn-restart" id="btnRestart" disabled>재시작</button>
      </div>
      <button class="btn-estop" id="btnEstop" disabled><span class="octo"></span><b>비상정지</b></button>
    </section>
```
을 다음으로 바꾼다:
```html
    <section class="ctrl">
      <div class="ctrl-left">
        <div class="ctrl-small">
          <button class="btn btn-resume" id="btnResume" disabled>재개</button>
          <button class="btn btn-restart" id="btnRestart" disabled>재시작</button>
        </div>
        <div class="ctrl-test" role="group" aria-label="스킬 테스트">
          <span class="ctrl-test-label">스킬 테스트 · 1회 실행</span>
          <div class="ctrl-test-btns" id="testBtns"></div>
        </div>
      </div>
      <button class="btn-estop" id="btnEstop" disabled><span class="octo"></span><b>비상정지</b></button>
    </section>
```

- [ ] **Step 2: `frontend/style.css` 끝에 추가**

```css

/* 스킬 테스트 줄 (설계: docs/superpowers/specs/2026-10-22-skill-test-and-scripted-dori-design.md 3장) */
.bottom{grid-template-columns:minmax(0,1.5fr) minmax(0,1fr) 42rem}
.ctrl{grid-template-columns:minmax(0,1fr) 14rem}
.ctrl-left{display:flex;flex-direction:column;gap:.6rem;min-width:0;min-height:0}
.ctrl-left .ctrl-small{flex:1;flex-direction:row;gap:.6rem;min-height:0}
.ctrl-test{flex:none;display:flex;flex-direction:column;gap:.3rem}
.ctrl-test-label{font-size:.95rem;font-weight:800;color:var(--ink2)}
.ctrl-test-btns{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.5rem}
.btn-test{font-size:1.1rem;padding:.45rem .3rem;border-radius:.8rem;background:var(--amber-bg);color:var(--ink);box-shadow:.18rem .18rem 0 var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
body[data-state=TESTING] .state-badge{background:var(--amber-bg);color:var(--amber)}
```

- [ ] **Step 3: `frontend/app.js` — 상태·버튼**

`const MOCK_FORCED = ...` 줄 다음에 추가:
```javascript
const TEST_DEFAULT = [   // info.tests가 없을 때 (예전 서버·목업)
  { skill: 'oranda_pickup', label: '오란다 1회', enabled: true, reason: '' },
  { skill: 'dori_dori', label: '도리도리 1회', enabled: true, reason: '' },
  { skill: 'home', label: '홈으로', enabled: true, reason: '' }];
```

`const S = { ... replays: [] };`의 끝 `replays: [] };`를 `replays: [], tests: TEST_DEFAULT };`로 바꾼다.

`STATE_KO` 줄을 다음으로 바꾼다:
```javascript
const STATE_KO = { IDLE: '대기', WORKING: '작업 중', REFUSING: '거부 중', DONE: '완료', ESTOP: '비상정지', TESTING: '테스트' };
```

`renderState()`의
```javascript
  $('#phaseLabel').textContent = PHASE_KO[S.phase] || S.phase;
  const idx = STEP_ORDER.indexOf(S.phase);
  document.querySelectorAll('#steps li').forEach((li, i) => {
    li.className = idx < 0 || S.state !== 'WORKING' ? '' : i < idx ? 'done' : i === idx ? 'on' : '';
  });
```
를 다음으로 바꾼다:
```javascript
  const testing = S.state === 'TESTING';
  $('#phaseLabel').textContent = testing && S.phase === 'acting' ? '실행 중' : PHASE_KO[S.phase] || S.phase;
  const idx = STEP_ORDER.indexOf(S.phase);
  const stepping = S.state === 'WORKING' || testing;
  const first = testing ? STEP_ORDER.indexOf('acting') : 0;   // 테스트는 옮기기 → 복귀만
  document.querySelectorAll('#steps li').forEach((li, i) => {
    li.className = idx < 0 || !stepping || i < first ? '' : i < idx ? 'done' : i === idx ? 'on' : '';
  });
```

`renderState()`의 `$('#btnEstop').disabled = ...;` 줄 다음에 추가:
```javascript
  document.querySelectorAll('#testBtns .btn-test').forEach((b) => {   // 대기일 때만, 모델 없는 버튼은 꺼 둔다
    const t = S.tests.find((x) => x.skill === b.dataset.skill) || {};
    b.disabled = !S.got || st !== 'IDLE' || t.enabled === false;
    b.title = t.enabled === false ? (t.reason || '모델 없음') : '';
  });
```

`renderInfo()`의 `S.replays = Array.isArray(m.replays) ? m.replays : [];` 다음 줄에 추가:
```javascript
  S.tests = Array.isArray(m.tests) && m.tests.length ? m.tests : TEST_DEFAULT;
  buildTestButtons();
```

`$('#btnEstop').onclick = ...;` 줄 다음에 추가:
```javascript
function buildTestButtons() {   // info.tests → "스킬 테스트" 버튼. 활성/비활성은 renderState가 정한다
  const box = $('#testBtns');
  box.innerHTML = '';
  S.tests.forEach((t) => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'btn btn-test'; b.dataset.skill = t.skill; b.disabled = true;
    b.textContent = t.label || t.skill;
    b.onclick = () => sendWS({ type: 'command', name: 'test', skill: t.skill });
    box.appendChild(b);
  });
}
```

맨 끝
```javascript
/* ---------- start (모든 선언 뒤) ---------- */
if (MOCK_FORCED) startMock(); else connect();
```
을 다음으로 바꾼다:
```javascript
/* ---------- start (모든 선언 뒤) ---------- */
buildTestButtons();
if (MOCK_FORCED) startMock(); else connect();
```

- [ ] **Step 4: `frontend/app.js` — 목업 흐름**

`createMock` 안의 `function begin() { const t = ++tok; work(t); }` 다음에 추가:
```javascript
  async function runTest(skill, fromChat) {   // 스킬 1회 실행 흉내: TESTING (acting → returning) → IDLE
    const t = ++tok, t0 = Date.now();
    if (skill === 'home') {
      pushState({ state: 'TESTING', phase: 'returning', skill }); await sleep(1200); if (t !== tok) return;
    } else {
      pushState({ state: 'TESTING', phase: 'acting', skill }); await sleep(skill === 'dori_dori' ? 1800 : 2600); if (t !== tok) return;
      if (skill === 'oranda_pickup') { pushState({ phase: 'returning' }); await sleep(1100); if (t !== tok) return; }
    }
    const how = { oranda_pickup: '놓기 감지로 끝남 · 쥠 성공', dori_dori: '코드 동작 완료', home: '완료' }[skill];
    const label = { oranda_pickup: '오란다', dori_dori: '도리도리', home: '홈으로' }[skill];
    const sec = ((Date.now() - t0) / 1000).toFixed(1);
    say('system', fromChat ? `도리도리 · ${how} · ${sec}초` : `테스트 · ${label}: ${how} · ${sec}초`);
    pushState({ state: 'IDLE', phase: 'idle', skill: null });
  }
```

목업 `api.start()`의 info emit에서 `replays: [] });`를 `replays: [], tests: TEST_DEFAULT });`로 바꾼다.

목업 `recv(m)`의 채팅 분기
```javascript
          if (st.state === 'REFUSING' && /조금|더|힘내|고마|부탁|간식|해줘|달래/.test(text)) { say('robot', '으으… 알겠어요, 조금만 더요.'); resumeFn && resumeFn(); }
          else if (st.state === 'IDLE' && /옮|시작|해줘|치워/.test(text)) { say('robot', '네네~ 시작할게요!'); begin(); }
```
를 다음으로 바꾼다:
```javascript
          if (st.state === 'REFUSING' && /조금|더|힘내|고마|부탁|간식|해줘|달래/.test(text)) { say('robot', '으으… 알겠어요, 조금만 더요.'); resumeFn && resumeFn(); }
          else if (st.state === 'IDLE' && /도리도리|고개/.test(text)) { say('robot', '도리도리~ 이렇게요?'); runTest('dori_dori', true); }
          else if (st.state === 'IDLE' && /옮|시작|해줘|치워/.test(text)) { say('robot', '네네~ 시작할게요!'); begin(); }
          else if (st.state === 'TESTING') say('robot', '지금 테스트 중이에요. 끝나면 시켜 주세요!');
```

목업 `recv(m)`의 명령 분기 끝
```javascript
        } else if (m.name === 'resume' && resumeFn) { say('system', '진행자가 재개했어요'); resumeFn(); }
```
를 다음으로 바꾼다:
```javascript
        } else if (m.name === 'resume' && resumeFn) { say('system', '진행자가 재개했어요'); resumeFn(); }
        else if (m.name === 'test') {
          if (st.state === 'IDLE' && TEST_DEFAULT.some((x) => x.skill === m.skill)) runTest(m.skill, false);
          else say('system', st.state === 'TESTING' ? '이미 테스트 중이에요' : '대기 상태에서만 테스트할 수 있어요');
        }
```
(목업 비상정지 조건 `!['IDLE', 'DONE', 'ESTOP'].includes(st.state)`는 TESTING도 포함하므로 그대로 둔다.)

- [ ] **Step 5: 문법·자동 테스트 확인**

Run: `node --check frontend/app.js`
Expected: 출력 없음 (문법 오류 없음)

Run: `.venv/Scripts/python -m pytest -q`
Expected: 모두 통과 (서버 쪽 그대로)

- [ ] **Step 6: 브라우저 확인 (수동, Chrome 또는 Edge)**

서버: `.venv/Scripts/python -m snackbot --dry-run` → `http://localhost:8000` (DevTools Console 열어 둔다). 녹화 재생 확인에는 `replays/` 가짜 데이터가 있으면 좋다 (`docs/superpowers/plans/2026-10-22-digital-twin.md` Task 9 Step 8 스크립트, git 제외 폴더).

| # | 할 것 | 기대 |
|---|---|---|
| 1 | 페이지 열기 | 아래 제어 칸: 재개·재시작이 한 줄, 그 아래 "스킬 테스트 · 1회 실행"과 `오란다 1회` · `도리도리 1회` · `홈으로`. 대기 상태라 세 버튼 활성, 비상정지 비활성 |
| 2 | `도리도리 1회` | 배지 "테스트", 단계 "실행 중", 단계 표시줄은 `옮기기`만 켜짐(앞 단계는 꺼짐). 세 버튼 비활성, **비상정지 활성**. `replays/dori_dori`가 있으면 카메라 칸·3D가 재생. 끝나면 채팅에 `테스트 · 도리도리: 시간 초과로 끝남 · …초`, 배지 "대기", 버튼 다시 활성 |
| 3 | `오란다 1회` | 옮기기 → 복귀 단계, 끝에 `테스트 · 오란다: 놓기 감지로 끝남 · 쥠 성공 · …` (dry-run 가짜 트레이가 비어 있으면 `시간 초과로 끝남 · 쥠 없음`. 가짜 트레이 개수는 하나 줄 수 있고 다음 작업 시작 때 다시 정해진다). 성능 칸(성공률·점·ms)과 피로도는 그대로 |
| 4 | `홈으로` | 단계 `복귀`만, 약 0.5초 뒤 `테스트 · 홈으로: 완료 · …` |
| 5 | `오란다 1회` 중 비상정지 | 즉시 "비상정지" 화면, 재생 멈춤, 채팅에 `비상정지됨` 뒤 `테스트 · 오란다: 비상정지로 멈춤 …`. `재시작` → 대기 |
| 6 | 채팅 `도리도리 해 봐` (대기) | 로봇 대사 뒤 테스트 1회, 결과 `도리도리 · …` |
| 7 | 채팅 `2개 옮겨줘` → 작업 중에 버튼 | 세 버튼 비활성. 작업 중 채팅 `도리도리 해 봐` → 대답만 |
| 8 | 테스트 중 채팅 `2개 옮겨줘` | 로봇이 대답만 하고 작업은 시작하지 않는다 |
| 9 | `http://localhost:8000/?mock` | 처음 약 2초(자동 작업 시작 전) 버튼 활성 → `홈으로`·`도리도리 1회`가 가짜 흐름으로 돈다. 자동 흐름 중엔 비활성. 비상정지 → 재시작 뒤 다시 활성 |
| 10 | 창 폭을 760px 이하로 | 버튼 글자가 잘려도(…) 줄이 넘치지 않는다 |

- [ ] **Step 7: 커밋**

```bash
git add frontend/index.html frontend/app.js frontend/style.css
git commit -m "feat(frontend): 스킬 테스트 버튼, TESTING 배지·단계 표시, 목업 테스트 흐름

Co-Authored-By: <세션의 attribution 줄>"
```

---

### Task 6: 문서 — 현장 절차 · 연동 계약 · 교차 링크

**Files:**
- Modify: `CLAUDE.md`, `docs/DEMO_RUNBOOK.md`, `docs/UI_DESIGN_PROMPT.md`, `docs/DECISION_LOGIC.md`, `docs/superpowers/specs/2026-10-22-skill-test-and-scripted-dori-design.md`, `docs/superpowers/specs/2026-10-22-chat-ui-design.md`, `docs/memo/2026-10-22-design-discussion.md`

**Interfaces:**
- Consumes: Task 1~5의 이름·문구 (`source: auto|policy|script`, `script.{joint, amplitude, shakes, shake_s}`, `TESTING`, `{"type":"command","name":"test","skill":...}`, `info.tests`, 결과 문구, JSONL `type: test`)
- Produces: 문서만

- [ ] **Step 1: `CLAUDE.md`**

3계층 표의 행동 줄
```
| 행동 | 동작 실행 | ACT 정책 2개 (OpenVINO): `oranda_pickup`, `dori_dori` |
```
을 다음으로 바꾼다:
```
| 행동 | 동작 실행 | ACT 정책 2개 (OpenVINO): `oranda_pickup`, `dori_dori` (모델이 없으면 코드 도리도리) |
```

절대 규칙 3의 둘째 줄
```
   (`start_task | chat | resume`) 안에서만. 벗어나면 규칙으로 결정한다.
```
을 다음으로 바꾼다:
```
   (`start_task | chat | resume | dori_dori`) 안에서만. 벗어나면 규칙으로 결정한다. `dori_dori`(도리도리 1회)는 대기 상태에서만.
```

`## 문서` 목록의 `2026-10-22-digital-twin-design.md` 줄 다음에 추가:
```markdown
- `docs/superpowers/specs/2026-10-22-skill-test-and-scripted-dori-design.md` — 스킬 1회 실행(TESTING)·코드 도리도리·LLM 도리도리
```

파일 구조의 `controller.py` 줄
```
│   ├── controller.py   # 상태 머신 IDLE/WORKING/REFUSING/DONE/ESTOP, 루프 스레드, 명령
```
을 다음으로 바꾼다:
```
│   ├── controller.py   # 상태 머신 IDLE/WORKING/REFUSING/DONE/ESTOP/TESTING, 루프 스레드, 명령
```

`## 진행자 키` 표 다음(파일 끝)에 추가:
```markdown

UI에는 **스킬 테스트** 버튼(`오란다 1회` · `도리도리 1회` · `홈으로`)도 있다. 대기 상태에서만 눌리고, 실제 로봇이면 진짜 팔이 움직인다 (콘솔 키는 없다). 채팅·🎤 "도리도리 해 봐"도 같은 1회 실행이다.
```

- [ ] **Step 2: `docs/DEMO_RUNBOOK.md`**

`## 3. 진행자 대본 예시` 바로 앞에 추가:
```markdown
## 2-4. 스킬 1회 실행 · 코드 도리도리 (설계: `docs/superpowers/specs/2026-10-22-skill-test-and-scripted-dori-design.md`)

화면 아래 제어 칸의 **스킬 테스트** 줄: `오란다 1회` · `도리도리 1회` · `홈으로`. **대기 상태에서만** 눌린다.
- 실제 로봇 모드(`python -m snackbot`)에서는 **진짜 팔이 움직인다** (정책을 실제로 추론). 누르기 전에 팔 주변을 비운다. 비상정지(space·UI)는 테스트 중에도 즉시 → `재시작`(`h`)으로 대기 복귀
- 결과는 채팅창 시스템 메시지 한 줄: `테스트 · 오란다: 놓기 감지로 끝남 · 쥠 성공 · 12.3초 · 기록 logs/runs/…` (실행 기록이 꺼져 있으면 기록 경로는 없다). 횟수·피로도·성공률에는 들어가지 않고, `logs/cycles-*.jsonl`에 `"type": "test"`로 남는다 (발표 통계에서 빼기 쉽게)
- 모델이 없는 정책의 버튼은 꺼져 있다 (마우스를 올리면 "모델 없음"). dry-run에서는 같은 버튼이 녹화 재생으로 대신한다
- 채팅·🎤로 "도리도리 해 봐" (대기 중)도 같은 1회 실행이다. 결과 메시지는 `도리도리 · …`
- 테스트 중에는 채팅 작업 지시·`s`·`r`이 거부된다 ("테스트 중이에요")

**코드 도리도리** — `skills.dori_dori.source`가 `auto`이고 dori_dori 모델 폴더가 없으면, 또는 `script`면 코드가 홈 자세에서 `script.joint`(기본 몸통 `shoulder_pan`)만 좌우로 흔든다
- [ ] 처음엔 작게: `amplitude` 10 → 15 → 20 (홈 기준 normalized, **최대 30**, 넘으면 경고 후 30). `shake_s`(한쪽으로 가는 시간, 초)는 0.35에서 시작해 너무 빠르면 늘린다. `shakes`는 왕복 횟수
- [ ] 확인: `.venv/bin/python -m snackbot.robot dori_dori` → `RunResult(stop_reason='script', ...)` 뒤 홈. 또는 UI `도리도리 1회`
- [ ] 화면 '제어' 칸에 `· 도리도리: 코드 동작`이 보이면 코드 도리도리다
- [ ] 모델을 꼭 쓰려면 `source: policy` (모델 폴더가 없으면 시작할 때 안내와 함께 멈춘다). 모델이 있어도 코드 도리도리를 쓰려면 `source: script` (모델을 로드하지 않아 시작이 빨라진다)

**오란다 1회로 그리퍼 기준값 맞추기 (과자 모델이 나오면)**
- [ ] `오란다 1회` 결과가 `놓기 감지로 끝남 · 쥠 성공`인지 본다
- [ ] `시간 초과로 끝남`이면 `skills.gripper.open_above`·`closed_below`·`open_hold_s` 또는 `skills.oranda_pickup.max_time_s`를, 과자를 쥐었는데 `쥠 없음`이면 `grasp_min`을 조정한다 (`python -m tools.robot_probe watch` 값 참고)

```

`## 4. 장애 대응` 표의 `| 로봇 이상 동작 | ...` 줄 다음에 추가:
```markdown
| 도리도리 정책이 이상하게 움직임 | 학습 부족, 카메라 위치 | `config.yaml` `skills.dori_dori.source: script` (코드 도리도리, 2-4절) |
| 스킬 테스트 버튼이 안 눌림 | 대기 상태가 아님, 모델 없음 | 작업이 끝나거나 비상정지 → 재시작 뒤 대기에서. 꺼진 버튼은 모델 폴더(`export_dir`) 확인 |
```

- [ ] **Step 3: `docs/UI_DESIGN_PROMPT.md` (서버 연동 계약)**

`state: IDLE(대기) | WORKING(작업 중) | REFUSING(거부 중) | DONE(완료) | ESTOP(비상정지)` 줄을 다음으로 바꾼다:
```
state: IDLE(대기) | WORKING(작업 중) | REFUSING(거부 중) | DONE(완료) | ESTOP(비상정지) | TESTING(테스트: 스킬 1회 실행)
```

`  - 비상정지: IDLE / DONE이 아닐 때, ESTOP이라도 phase가 returning(재시작으로 홈 복귀 중)이면 켠다` 줄 다음에 추가:
```
  - 스킬 테스트(info.tests의 버튼들): IDLE일 때만, 그리고 그 버튼의 enabled가 true일 때만 (false면 reason을 툴팁으로). TESTING 중엔 모두 끄고 비상정지는 켠다
- 단계 표시줄은 WORKING과 TESTING에서 켠다. TESTING은 acting(실행 중) → returning(복귀)만 쓴다 (`홈으로`는 returning만)
```

info 예시 줄 끝의 `,"replays":["dori_dori"]}`를 다음으로 바꾼다:
```
,"replays":["dori_dori"],"tests":[{"skill":"oranda_pickup","label":"오란다 1회","enabled":true,"reason":""},{"skill":"dori_dori","label":"도리도리 1회","enabled":true,"reason":""},{"skill":"home","label":"홈으로","enabled":true,"reason":""}]}
```
`- replays: 재생 데이터가 있는 스킬` 줄 다음에 추가:
```
- tests: 스킬 테스트 버튼 (순서대로). enabled=false면 reason("모델 없음")
```

`- skill: oranda_pickup | dori_dori | done | null` 줄을 다음으로 바꾼다:
```
- skill: oranda_pickup | dori_dori | done | home(TESTING의 홈으로) | null
```

`- source(user일 때만): text | voice (voice면 🎤 표시)` 줄 다음에 추가:
```
- 스킬 테스트 결과는 system 메시지 한 줄: "테스트 · 오란다: 놓기 감지로 끝남 · 쥠 성공 · 12.3초 · 기록 logs/runs/…" (채팅으로 시킨 도리도리는 "도리도리 · …"). 테스트는 cycle 메시지를 보내지 않는다
```

`{"type":"command","name":"resume"}   // name: resume | estop | restart` 줄을 다음으로 바꾼다:
```
{"type":"command","name":"resume"}   // name: resume | estop | restart
{"type":"command","name":"test","skill":"oranda_pickup"}   // skill: oranda_pickup | dori_dori | home (스킬 1회 실행, IDLE에서만 받는다)
```

`  서버 없이 열어도 전체 흐름(대기 → 작업 → 지침 → 거부 → 재개 → 완료)이 자동으로 재생되어야 함.` 줄 다음에 추가:
```
  스킬 테스트 버튼도 목업에서 가짜 흐름(TESTING → 결과 system 메시지 → IDLE)을 보여 준다.
```

- [ ] **Step 4: `docs/DECISION_LOGIC.md` 7장**

표의
```
| IDLE / DONE | `start_task`, `chat` |
| WORKING / ESTOP | `chat` |
```
를 다음으로 바꾼다:
```
| IDLE | `start_task`, `chat`, `dori_dori` |
| DONE | `start_task`, `chat` |
| WORKING / ESTOP / TESTING | `chat` |
```

출력 스키마 줄
```
{"intent": "start_task | resume | chat", "say": "한국어 대사 1문장", "n": 3}
```
을 다음으로 바꾼다:
```
{"intent": "start_task | resume | chat | dori_dori", "say": "한국어 대사 1문장", "n": 3}
```

`  - resume: 조금만, 부탁, 힘내, 한 번만` 줄 다음에 추가:
```
  - dori_dori (IDLE만): 도리도리, 고개 저어, 고개를 저어
```

7장 목록의 마지막 줄("say 검증은 4장과 같다 (비었거나 80자 초과 → 준비된 대사).", say는 백틱으로 감싸져 있다) 다음에 추가:
```
- `dori_dori`: 고개를 좌우로 젓는 동작 1회. 프롬프트에 도구 설명 한 줄(`dori_dori: 고개를 좌우로 젓는 동작 한 번 (싫다고 하거나, 도리도리를 해 보라고 할 때)`). 실행은 UI 스킬 테스트와 같은 경로(TESTING)라 횟수·피로도에 반영하지 않는다. 설계: `docs/superpowers/specs/2026-10-22-skill-test-and-scripted-dori-design.md` 8절
```

- [ ] **Step 5: 설계 문서 교차 링크와 구현 결정**

`docs/superpowers/specs/2026-10-22-chat-ui-design.md`의 `- 화면 4분할·3D 디지털 트윈·녹화 재생·실행 기록은 ...` 줄 다음에 추가:
```markdown
- 스킬 1회 실행(TESTING 상태, `test` 명령)·코드 도리도리·LLM `dori_dori` 의도는 `2026-10-22-skill-test-and-scripted-dori-design.md`가 이 문서의 상태·명령·채팅 의도 부분보다 우선한다.
```

`docs/superpowers/specs/2026-10-22-skill-test-and-scripted-dori-design.md`의 셋째 줄(`작성 2026-10-22. 상태: ...`) 다음에 빈 줄과 함께 넣는다:
```markdown
구현 계획: `docs/superpowers/plans/2026-10-22-skill-test.md`.
```
같은 파일 끝에 추가:
```markdown

## 9. 구현 결정 (계획에서 정한 것)

- 코드 도리도리의 끝 키프레임이 홈이므로 따로 홈 이동(move_s)을 하지 않고 도착만 확인한다(`_settle`). 시간이 다 돼 홈에 못 닿았을 때만 홈 이동.
- `source: script`면 dori_dori 모델을 아예 로드하지 않는다 (시작 시간·warmup 절약). `script.joint`는 그리퍼를 뺀 몸통 관절 5개 중 하나. 잘못된 `source`·`script` 값은 시작할 때 SystemExit.
- `RunResult.record`: 실행 기록 폴더(posix 경로). 결과 메시지의 `기록 …`에 쓴다.
- TESTING에 들어가는 순간(요청 수락) 세션 번호를 올린다. 비상정지는 아직 시작 안 한 테스트 요청을 버린다.
- 스킬이 스스로 `estop`으로 끝나면(예: Ctrl+C) 상태도 ESTOP (사이클과 같다).
- `홈으로` 테스트의 단계는 `returning`만 (재생 없음). `오란다 1회`·`도리도리 1회`는 `acting`부터.
- DrySkills.go_home은 `act_s/2` 기다리고 `done | estop`을 돌려준다 (dry-run 재시작도 그만큼 걸린다).
- TESTING 중 채팅은 대답만(허용 intent `chat`, 대사 "지금 테스트 중이에요. 끝나면 시켜 주세요!"). `s`·`r`·UI 시작/재개는 시스템 메시지 "테스트 중이에요. 끝난 뒤 다시 시켜 주세요".
- LLM 도리도리는 채팅을 접수한 순간의 세션 번호로 요청한다 (LLM을 기다리는 사이 비상정지·재시작이 끼면 취소). DONE에서는 허용하지 않는다 (IDLE만).
- 결과 문구: 버튼 `테스트 · <이름>: <결과> · [쥠 성공|쥠 없음 ·] <초>초[ · 기록 <폴더>]` (`<이름>`은 target 이름 · 도리도리 · 홈으로, 쥠은 오란다만), LLM `도리도리 · <결과> · …`, 예외는 둘 다 `테스트 실패: <오류>`. 결과 이름: 놓기 감지로 끝남 / 시간 초과로 끝남 / 비상정지로 멈춤 / 코드 동작 완료 / 완료.
- JSONL 테스트 줄: `{"ts","type":"test","skill","origin":"button|llm","stop_reason"(예외면 "error"),"grasped","ms","record","error"}`. 사이클 번호·`cycle` 이벤트 없음. 사이클 줄은 그대로 (`type` 없음).
- 버튼 이름표: `<target 이름> 1회` · `도리도리 1회` · `홈으로` (`info.tests`). dry-run은 모두 활성.
- 화면: 제어 칸을 넓혀 재개·재시작을 한 줄로, 그 아래 스킬 테스트 줄. 테스트 중 단계 표시줄은 옮기기·복귀만, acting 단계 이름은 "실행 중".
```

`docs/memo/2026-10-22-design-discussion.md` 요약 표의 `| 21 | 음성(STT/TTS) provider | ... |` 줄 다음에 추가:
```markdown
| 22 | 스킬 1회 실행 · 코드 도리도리 | UI 버튼(TESTING, 루프 스레드)으로 스킬 1회, 모델이 없으면 코드 도리도리, LLM도 `dori_dori` 의도로 호출 |
```
파일 끝에 추가:
```markdown

## 22. 스킬 1회 실행 · 코드 도리도리

**결정:** 화면 버튼 `오란다 1회` · `도리도리 1회` · `홈으로`로 학습한 정책을 한 번만 실제로 돌려 본다 (새 상태 TESTING, 대기에서만, 횟수·피로도 미반영). dori_dori 모델이 없거나 쓰기 싫으면 코드가 홈에서 몸통을 좌우로 흔든다 (`skills.dori_dori.source: auto | policy | script`). 대화 LLM도 `dori_dori` 의도로 같은 1회 실행을 부른다 (tool-use API가 아니라 기존 JSON intent, 모든 provider에서 같게).

**상세**
- 설계: `docs/superpowers/specs/2026-10-22-skill-test-and-scripted-dori-design.md`, 구현 계획: `docs/superpowers/plans/2026-10-22-skill-test.md`.
- 로봇을 움직이는 스레드는 controller 루프 하나로 유지한다 (요청 슬롯 + 깨우기). 비상정지는 테스트를 기다리지 않는다.
- 코드 도리도리는 진폭 상한 30, 관절 범위 클램프, 실행 기록에 정책 phase처럼 남는다.
```

- [ ] **Step 6: 확인과 커밋**

Run: `.venv/Scripts/python -m pytest -q`
Expected: 모두 통과 (문서만 바뀜)

```bash
git add CLAUDE.md docs/DEMO_RUNBOOK.md docs/UI_DESIGN_PROMPT.md docs/DECISION_LOGIC.md docs/superpowers/specs/2026-10-22-skill-test-and-scripted-dori-design.md docs/superpowers/specs/2026-10-22-chat-ui-design.md docs/memo/2026-10-22-design-discussion.md
git commit -m "docs: 스킬 1회 실행·코드 도리도리 현장 절차와 연동 계약

Co-Authored-By: <세션의 attribution 줄>"
```

---

## 실제 로봇에서만 확인할 수 있는 것 (계획 밖, 현장 체크)

- 코드 도리도리 진폭·속도: `amplitude` 10 → 15 → 20, `shake_s`가 서보에 너무 빠르지 않은지 (`_settle`이 "목표에서 … 벗어나 있어요" 경고를 내면 `shake_s`를 늘린다)
- `shoulder_pan` 좌우 흔들기가 테이블·트레이·카메라 마운트에 닿지 않는지 (홈 자세 기준)
- `오란다 1회`로 `grasp_min`, `closed_below`, `open_above`, `max_time_s`가 맞는지 (DEMO_RUNBOOK 2-4절)
- 테스트 중 비상정지 → 토크 유지 → 재시작 → 홈 복귀가 사이클 때와 같이 동작하는지
- 코드 도리도리 실행 기록(`logs/runs/<시각>_dori_dori/`)을 `replays/dori_dori/`로 복사해 dry-run 재생에 쓸 수 있는지
