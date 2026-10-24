# snackbot 로봇 연결 (M4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `python -m snackbot`(실제 로봇)으로 physical-ai-studio에서 학습한 ACT OpenVINO 정책 2개(`oranda_pickup`, `dori_dori`)를 SO-101에서 실행한다. 그리퍼 "닫힘→열림"으로 ACT를 멈추고, 코드가 `lift_pose → home_pose`로 복귀시키며, 비상정지는 토크를 켠 채 자세를 유지한다.

**Architecture:** `RobotRuntime`(physicalai 0.3.0) 하나를 시작할 때 연결해 두고, `run()`마다 동작 출처를 바꿔 끼운다(`Switch.active` = 정책 A / 정책 B / `MoveSource`). 매 틱 콜백(`Tap`)이 관절값·프레임을 저장하고 그리퍼 감시(`GripperWatch`)에 넘긴다. 정지는 `run(stop_event=StopAny(...))`. 카메라·시리얼은 스레드 안전하지 않으므로 `_io` 락으로 한 번에 한 스레드만 쓴다. 이 계획의 코드는 physicalai 없이도 테스트할 수 있도록 하드웨어 생성 부분만 lazy import 한다.

**Tech Stack:** physicalai 0.3.0 (`RobotRuntime`, `PolicySource`, `InferenceModel`, `UVCCamera`), physicalai-so101-plugin 0.2.0 (`SO101`), NumPy, PyYAML, httpx, pytest.

**전제:** `docs/superpowers/plans/2026-10-22-snackbot-software.md`(Task 1~10)가 끝난 상태. 설계 근거: `docs/superpowers/specs/2026-10-22-chat-ui-design.md` 7장·11.5절.

## Global Constraints

- 모든 명령은 `project/`에서 실행한다. 개발 PC(Windows): `.venv/Scripts/python`. 로봇 노트북(Ubuntu): `.venv/bin/python`.
- 커밋은 `project/` 안의 파일만 `git add <경로>`로 지정한다. 커밋 메시지 끝에 작업한 세션의 `Co-Authored-By` 줄.
- **physicalai / physicalai_so101_plugin은 `snackbot/robot.py`의 `build_runtime`·`build_policies`와 `tools/robot_probe.py`의 `open_robot` 안에서만 import한다.** 개발 PC에는 설치돼 있지 않고 설치하지 않는다. 모든 테스트는 가짜 런타임으로 개발 PC에서 돈다.
- physicalai 코어를 수정하거나 private 속성(`_action_source` 등)을 쓰지 않는다. 공개 API만: `RobotRuntime(robot, action_source, fps, cameras, callbacks)`, `.connect()`, `.disconnect()`, `.run(duration_s=, stop_event=)`, `.last_run_reason`, `.robot`, `.cameras`; `PolicySource(InferenceModel(export_dir, device=))`, `.warmup(obs)`, `.to_model_input(robot_obs, camera_frames)`; 카메라 `.read()`, `.read_latest()` → `Frame.data`; `SO101(port, calibration, role)`, `.get_observation().joint_positions`, `.set_torque(enabled=)`, `.disconnect()`.
- 관절 순서 `shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper` (그리퍼 인덱스 5). 단위는 SO101 normalized (몸통 -100..100, 그리퍼 0..100). 포즈·그리퍼 기준값 모두 이 단위.
- 그리퍼 값은 **작을수록 닫힘**으로 가정한다 (`tools.robot_probe watch`로 현장 확인).
- 물리 카메라는 config `cameras`에 한 번씩만 둔다: `tower cam`, `side cam`, `follow cam`. 런타임 하나에 3대를 모두 연결한다. dori_dori는 2대(`tower cam`, `follow cam`)로, oranda_pickup은 3대로 학습했다. `InferenceModel._prepare_inputs`가 모델이 기대하는 입력만 골라 쓰고 남는 키는 버리므로(없는 키만 오류) 카메라가 많은 쪽에 맞춘다.
- **정책 입력 이름(`images.<학습 때 이름>`)은 내보낸 모델에 고정된다.** 학습 때 Studio 카메라 이름이 config 이름과 다르면(예: oranda를 `A`·`B`로 학습) 정책별 `camera_map: {학습 이름: config 카메라 이름}`으로 맞춘다. `Switch`가 그 정책이 도는 동안 프레임을 학습 이름으로도 넘겨준다 (`camera_map`에 없는 카메라는 config 이름 그대로).
- 비상정지 중에는 어떤 `run()`도 시작하지 않는다. 비상정지에서 런타임을 끊지 않는다 (끊으면 드라이버가 측정값을 다시 목표로 쓴다).
- 스킬 인터페이스는 `DrySkills`와 같다: `tray`, `new_task(n)`, `run(name, on_phase=None) -> RunResult`, `go_home()`, `estop()`, `release_estop()`, `latest_frame(cam=None)`, `close()`.

## File Structure

| 파일 | 책임 |
|---|---|
| `config.yaml` (수정) | `robot`, `cameras`, `skills`, `poses_file` 절 추가, `vision.camera`를 `tower cam`으로 |
| `requirements-robot.txt` | 로봇 노트북 전용 의존성 |
| `snackbot/config.py` (수정) | `load_poses`, `save_pose`, `load_calibration` |
| `snackbot/motion.py` | 하드웨어 없는 동작 보조: `GripperWatch`, `MoveSource`, `plan_path`, `StopAny`, `Switch`, `Tap` |
| `snackbot/robot.py` | `RobotSkills`, `build_runtime`, `build_policies`, 스킬 단독 실행 CLI |
| `snackbot/__main__.py` (수정) | `build(dry_run=False)` 경로 |
| `tools/fetch_calibration.py` | Studio runtime-config에서 팔로워 캘리브레이션 받기 (GET만) |
| `tools/robot_probe.py` | 관절값 보기(`watch`), 포즈 저장(`save home|lift`) |
| `tests/test_motion.py`, `tests/test_robot.py`, `tests/test_tools.py` | 테스트 |
| `CLAUDE.md`, `docs/DEMO_RUNBOOK.md`, 설계 문서 (수정) | 현장 절차 |

---

### Task 1: 로봇 설정과 포즈 파일

**Files:**
- Modify: `config.yaml`, `snackbot/config.py`, `tests/test_config.py`
- Create: `requirements-robot.txt`

**Interfaces:**
- Produces: `load_poses(path) -> dict` (없으면 `{}`), `save_pose(path, name, values) -> dict` (소수 둘째 자리로 반올림해 기존 포즈와 합쳐 저장), `load_calibration(path) -> dict` (YAML/JSON); config 키 `robot.port`, `robot.calibration`, `cameras.<이름>.{device,width,height,fps}`, `skills.{fps, device, oranda_pickup, dori_dori, gripper, home_tolerance, move_s}`, `poses_file`

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_config.py` 맨 위 import를 다음으로 바꾼다:
```python
import json
from pathlib import Path

from snackbot.config import load_config, load_env, load_poses, save_pose
```
파일 끝에 추가:
```python
def test_robot_sections_cover_policy_cameras():
    cfg = load_config(ROOT / "config.yaml")
    assert {"tower cam", "side cam", "follow cam"} <= set(cfg["cameras"])
    assert cfg["vision"]["camera"] in cfg["cameras"]
    for name in ("oranda_pickup", "dori_dori"):
        manifest = ROOT / cfg["skills"][name]["export_dir"] / "manifest.json"
        if not manifest.exists():
            continue  # 학습 결과물은 git에 없다 (있는 PC에서만 확인)
        features = json.loads(manifest.read_text(encoding="utf-8"))["model"]["input_features"]
        trained = {f["init_args"]["name"].removeprefix("images.") for f in features
                   if f["init_args"]["ftype"] == "VISUAL"}
        camera_map = cfg["skills"][name].get("camera_map") or {}
        # 정책이 쓰는 카메라(학습 이름 → camera_map → config 이름)는 모두 config에 있어야 한다
        assert {camera_map.get(cam, cam) for cam in trained} <= set(cfg["cameras"]), name


def test_poses_roundtrip(tmp_path):
    p = tmp_path / "poses.yaml"
    assert load_poses(p) == {}
    save_pose(p, "home_pose", [1.234, 2, 3, 4, 5, 6.789])
    save_pose(p, "lift_pose", [0] * 6)
    assert load_poses(p) == {"home_pose": [1.23, 2.0, 3.0, 4.0, 5.0, 6.79], "lift_pose": [0.0] * 6}
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_poses'`

- [ ] **Step 3: 구현**

`snackbot/config.py` 끝에 추가:
```python
def load_poses(path="poses.yaml"):
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_pose(path, name, values):
    poses = load_poses(path)
    poses[name] = [round(float(v), 2) for v in values]
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(poses, f, default_flow_style=None, sort_keys=True)
    return poses


def load_calibration(path):
    """SO101 캘리브레이션: 관절 이름 → {id, drive_mode, homing_offset, range_min, range_max}. YAML 또는 JSON."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
```

`config.yaml`에서 `vision:` 절의 `camera: front`를 `camera: tower cam`으로 바꾸고, `voice:` 절 바로 위에 다음을 넣는다:
```yaml
robot:
  port: /dev/ttyACM0                       # [ ] 노트북의 팔로워 포트 (ls /dev/ttyACM*). Studio 학습 PC는 /dev/ttyACM1이었다
  calibration: calibration/follower.yaml   # python -m tools.fetch_calibration 으로 Studio에서 받는다

cameras:                                   # 키 = 학습 때 카메라 이름 (정책 입력 images.<이름>). 정책이 쓰는 카메라를 모두 둔다
  tower cam:  {device: 0, width: 1280, height: 720, fps: 30}   # [ ] 노트북의 카메라 번호
  side cam:   {device: 4, width: 1280, height: 720, fps: 30}   # [ ] oranda_pickup용 사이드 캠: Studio에 등록한 이름·해상도 확인
  follow cam: {device: 2, width: 1280, height: 720, fps: 30}

skills:
  fps: 30
  device: GPU                              # CPU | GPU | NPU (정책별로 device를 따로 써도 된다)
  # camera_map: 학습 때 Studio 카메라 이름이 위 cameras 키와 다르면 {학습 이름: config 이름}.
  #   학습 이름은 결과물 manifest.json의 "images.<이름>"에서 확인한다. 예: {A: tower cam, B: side cam}
  oranda_pickup: {export_dir: trained_model/oranda-pickup-model/exports/openvino, max_time_s: 20, camera_map: {}}   # [ ] 학습 끝나면 폴더 이름·camera_map 확인
  dori_dori:     {export_dir: trained_model/dori_dori/exports/openvino, max_time_s: 6, camera_map: {}}
  gripper:                                 # python -m tools.robot_probe watch 로 값을 읽고 정한다 (0..100, 작을수록 닫힘)
    closed_below: null                     # 이보다 작으면 "닫힘"
    open_above: null                       # 닫힘 뒤 이보다 큰 값이 open_hold_s 동안 이어지면 "놓음" → ACT 정지
    grasp_min: null                        # 닫힘 구간 최솟값이 이 이상이면 과자를 쥔 것 (빈 그리퍼는 끝까지 닫힌다)
    open_hold_s: 0.5
  home_tolerance: 5                        # 관절별 오차가 이보다 크면 스킬 전에 home_pose로 이동
  move_s: 2.0                              # 자세 하나로 이동하는 시간 (초)

poses_file: poses.yaml                     # python -m tools.robot_probe save home | save lift 가 기록
```

`requirements-robot.txt`:
```text
# 로봇 노트북 전용 (Ubuntu 24.04, Python 3.12+). requirements.txt와 함께 설치한다:
#   .venv/bin/python -m pip install -r requirements.txt -r requirements-robot.txt
physicalai==0.3.0
physicalai-so101-plugin==0.2.0
feetech-servo-sdk
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_config.py -v`
Expected: 5 passed (이 PC에는 `trained_model/dori_dori`이 있어서 dori_dori의 카메라 2대가 config에 있는지까지 확인된다)

- [ ] **Step 5: 전체 테스트**

Run: `.venv/Scripts/python -m pytest -q`
Expected: 모두 통과

- [ ] **Step 6: 커밋**

```bash
git add config.yaml requirements-robot.txt snackbot/config.py tests/test_config.py
git commit -m "feat(snackbot): 로봇·카메라·스킬 설정과 포즈 파일

Co-Authored-By: <세션의 attribution 줄>"
```

---

### Task 2: motion — 그리퍼 감시, 보간 이동, 정지 신호

**Files:**
- Create: `snackbot/motion.py`, `tests/test_motion.py`

**Interfaces:**
- Produces:
  - `GRIPPER = 5`
  - `plan_path(start, targets, steps) -> list[np.ndarray]` — 목표마다 `steps`개 선형 보간 점
  - `MoveSource(targets, steps)`: ActionSource 규약 `connect(*, bus=None, session_id=None)`, `update(robot_state, camera_frames, step) -> np.ndarray(6,)`, `disconnect()`; 첫 update에서 현재 관절값으로 경로를 만들고, 마지막 점을 보낼 때 `.done`(threading.Event)을 set, 그 뒤로 마지막 점 유지. `connect`마다 초기화.
  - `GripperWatch(closed_below, open_above, grasp_min, hold_s=0.5)`: `.update(gripper, t)`, `.reset()`, `.done` (Event), `.grasped` (bool), `.closed_seen`, `.min_closed`
  - `StopAny(*events)`: `.is_set()` (None은 무시)
  - `Switch()`: `.active`에 위임하는 ActionSource. `.camera_map` (`{학습 이름: config 이름}` 또는 None)이 있으면 update에 넘기는 프레임에 학습 이름 키를 더한다
  - `remap_frames(camera_frames, camera_map) -> dict` — 원래 키는 유지하고 `camera_map`의 학습 이름 키를 추가
  - `Tap()`: RobotRuntime 콜백 `on_tick(event)` — `.lock`, `.joints`, `.frames[name] = Frame.data`, `.watch`가 있으면 그리퍼 값을 넘긴다

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_motion.py`:
```python
import threading
from types import SimpleNamespace

import numpy as np

from snackbot.motion import GRIPPER, GripperWatch, MoveSource, StopAny, Switch, Tap, plan_path, remap_frames


def state(values):
    return SimpleNamespace(joint_positions=np.asarray(values, np.float32))


def feed(watch, values, dt=0.1):
    for i, v in enumerate(values):
        watch.update(v, i * dt)


def test_plan_path_linear_segments():
    path = plan_path([0] * 6, [[10] * 6, [10, 0, 0, 0, 0, 0]], 2)
    assert len(path) == 4
    np.testing.assert_allclose(path[0], [5] * 6)
    np.testing.assert_allclose(path[1], [10] * 6)
    np.testing.assert_allclose(path[3], [10, 0, 0, 0, 0, 0])


def test_move_source_walks_path_holds_last_and_sets_done():
    src = MoveSource([[6] * 6], steps=3)
    src.connect(bus=None, session_id="s")
    first = src.update(state([0] * 6), {}, 0)
    assert not src.done.is_set()
    out = [first] + [src.update(state([0] * 6), {}, i) for i in range(1, 5)]
    np.testing.assert_allclose(out[0], [2] * 6)
    np.testing.assert_allclose(out[2], [6] * 6)
    np.testing.assert_allclose(out[4], [6] * 6)
    assert src.done.is_set()
    src.connect(bus=None, session_id="again")
    assert not src.done.is_set()
    np.testing.assert_allclose(src.update(state([3] * 6), {}, 0), [4] * 6)


def test_gripper_watch_needs_close_before_open():
    w = GripperWatch(closed_below=30, open_above=60, grasp_min=15, hold_s=0.5)
    feed(w, [80] * 10)
    assert not w.done.is_set() and not w.closed_seen


def test_gripper_watch_snack_grasp_then_release():
    w = GripperWatch(30, 60, 15, 0.5)
    feed(w, [80, 50, 25, 24, 25, 70, 80, 80, 80, 80, 80, 80])
    assert w.done.is_set() and w.grasped and w.min_closed == 24


def test_gripper_watch_empty_grasp():
    w = GripperWatch(30, 60, 15, 0.5)
    feed(w, [80, 5, 3, 80, 80, 80, 80, 80, 80, 80])
    assert w.done.is_set() and not w.grasped


def test_gripper_watch_open_must_be_held_and_reset():
    w = GripperWatch(30, 60, 15, 0.5)
    feed(w, [20, 80, 80, 50, 80, 80, 80])
    assert not w.done.is_set()
    w.reset()
    assert w.min_closed is None and not w.closed_seen and not w.grasped


def test_stop_any():
    a, b = threading.Event(), threading.Event()
    s = StopAny(a, None, b)
    assert not s.is_set()
    b.set()
    assert s.is_set()


def test_switch_delegates_to_active():
    calls = []

    class Src:
        def connect(self, *, bus, session_id):
            calls.append(("connect", session_id))

        def update(self, robot_state, camera_frames, step):
            return step

        def disconnect(self):
            calls.append(("disconnect",))

    sw = Switch()
    sw.active = Src()
    sw.connect(bus=None, session_id="x")
    assert sw.update(None, {}, 7) == 7
    sw.disconnect()
    assert calls == [("connect", "x"), ("disconnect",)]


def test_switch_passes_frames_under_trained_names():
    seen = {}

    class Src:
        def update(self, robot_state, camera_frames, step):
            seen.update(camera_frames)
            return step

    sw = Switch()
    sw.active, sw.camera_map = Src(), {"A": "tower cam"}
    sw.update(None, {"tower cam": "t", "follow cam": "f"}, 0)
    assert seen == {"tower cam": "t", "follow cam": "f", "A": "t"}


def test_remap_frames():
    assert remap_frames({"x": 1}, None) == {"x": 1}
    assert remap_frames({"x": 1, "y": 2}, {"B": "y", "Z": "missing"}) == {"x": 1, "y": 2, "B": 2}


def test_tap_caches_state_frames_and_feeds_watch():
    tap, w = Tap(), GripperWatch(30, 60, 15, 0.5)
    tap.watch = w
    frame = np.zeros((2, 2, 3), np.uint8)
    tap.on_tick(SimpleNamespace(robot_state=state([1, 2, 3, 4, 5, 20]),
                                camera_frames={"tower cam": SimpleNamespace(data=frame)}, timestamp=0.0))
    assert tap.joints[GRIPPER] == 20 and tap.frames["tower cam"] is frame and w.closed_seen
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_motion.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'snackbot.motion'`

- [ ] **Step 3: 구현**

`snackbot/motion.py`:
```python
"""로봇 동작 보조. physicalai를 import하지 않는다 (개발 PC에서 테스트한다).

- MoveSource / Switch: RobotRuntime의 action_source 규약 (connect(bus, session_id) · update · disconnect)
- Tap: RobotRuntime 콜백 (on_tick)
- StopAny: RobotRuntime.run(stop_event=...)에 넘기는 정지 신호 (is_set)
"""
import threading

import numpy as np

GRIPPER = 5   # 관절 순서의 마지막. 0..100, 작을수록 닫힘


def plan_path(start, targets, steps):
    path, prev = [], np.asarray(start, np.float32)
    for target in targets:
        target = np.asarray(target, np.float32)
        for k in range(1, steps + 1):
            path.append(prev + (target - prev) * (k / steps))
        prev = target
    return path


class MoveSource:
    """현재 자세에서 targets를 차례로 선형 보간해 보낸다. 마지막 점을 보낼 때 done을 set하고 그 점을 유지한다."""

    def __init__(self, targets, steps):
        self.targets = [np.asarray(t, np.float32) for t in targets]
        self.steps = max(1, int(steps))
        self.done = threading.Event()
        self._path, self._i = None, 0

    def connect(self, *, bus=None, session_id=None):
        self._path, self._i = None, 0
        self.done.clear()

    def update(self, robot_state, camera_frames, step):
        if self._path is None:
            self._path = plan_path(robot_state.joint_positions, self.targets, self.steps)
        last = len(self._path) - 1
        action = self._path[min(self._i, last)]
        if self._i >= last:
            self.done.set()
        self._i += 1
        return action

    def disconnect(self):
        pass


class GripperWatch:
    """닫힘(< closed_below)을 한 번 본 뒤 열림(> open_above)이 hold_s 이상 이어지면 done.
    닫힘 구간의 최솟값이 grasp_min 이상이면 과자를 쥔 것 (빈 그리퍼는 끝까지 닫힌다)."""

    def __init__(self, closed_below, open_above, grasp_min, hold_s=0.5):
        self.closed_below, self.open_above = closed_below, open_above
        self.grasp_min, self.hold_s = grasp_min, hold_s
        self.done = threading.Event()
        self.reset()

    def reset(self):
        self.closed_seen = False
        self.min_closed = None
        self._open_since = None
        self.done.clear()

    @property
    def grasped(self):
        return self.min_closed is not None and self.min_closed >= self.grasp_min

    def update(self, gripper, t):
        if gripper < self.closed_below:
            self.closed_seen = True
            self.min_closed = gripper if self.min_closed is None else min(self.min_closed, gripper)
            self._open_since = None
        elif self.closed_seen and gripper > self.open_above:
            if self._open_since is None:
                self._open_since = t
            elif t - self._open_since >= self.hold_s:
                self.done.set()
        else:
            self._open_since = None


class StopAny:
    def __init__(self, *events):
        self.events = [e for e in events if e is not None]

    def is_set(self):
        return any(e.is_set() for e in self.events)


def remap_frames(camera_frames, camera_map):
    """원래 키는 그대로 두고, {학습 이름: config 이름}의 학습 이름 키를 더한다 (모델은 필요한 키만 쓴다)."""
    frames = dict(camera_frames)
    for trained, cam in (camera_map or {}).items():
        if cam in camera_frames:
            frames[trained] = camera_frames[cam]
    return frames


class Switch:
    """RobotRuntime에는 이것 하나만 꽂고, run()마다 active(와 camera_map)를 바꿔 낀다."""

    def __init__(self):
        self.active = None
        self.camera_map = None

    def connect(self, *, bus, session_id):
        self.active.connect(bus=bus, session_id=session_id)

    def update(self, robot_state, camera_frames, step):
        return self.active.update(robot_state, remap_frames(camera_frames, self.camera_map), step)

    def disconnect(self):
        self.active.disconnect()


class Tap:
    """매 틱 관절값과 카메라 프레임을 저장하고, watch가 있으면 그리퍼 값을 넘긴다."""

    def __init__(self):
        self.lock = threading.Lock()
        self.joints = None
        self.frames = {}
        self.watch = None

    def on_tick(self, event):
        joints = np.asarray(event.robot_state.joint_positions, np.float32).copy()
        with self.lock:
            self.joints = joints
            for name, frame in event.camera_frames.items():
                self.frames[name] = frame.data
        watch = self.watch
        if watch is not None:
            watch.update(float(joints[GRIPPER]), event.timestamp)
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_motion.py -v`
Expected: 11 passed

- [ ] **Step 5: 커밋**

```bash
git add snackbot/motion.py tests/test_motion.py
git commit -m "feat(snackbot): 그리퍼 감시, 보간 이동, 정지 신호

Co-Authored-By: <세션의 attribution 줄>"
```

---

### Task 3: RobotSkills — 실제 로봇 스킬

**Files:**
- Create: `snackbot/robot.py`, `tests/test_robot.py`

**Interfaces:**
- Consumes: `motion.*` (Task 2), `load_calibration`, `load_config`, `load_poses` (Task 1), `RunResult` (`snackbot/skills.py`)
- Produces:
  - `RobotSkills(cfg, poses, make_runtime=None, policies=None)` — `make_runtime(switch, tap) -> runtime` (기본 `build_runtime`), `policies` = `{"oranda_pickup": src, "dori_dori": src}` (기본 `build_policies`). 포즈(`home_pose`, `lift_pose`)나 그리퍼 기준값이 없으면 `SystemExit`(안내 문구).
  - 메서드: `connect()` (런타임 연결 + 정책 warmup), `tray`, `new_task(n)`, `run(name, on_phase=None) -> RunResult`, `ensure_home() -> "done"|"timeout"|"estop"`, `go_home() -> str`, `estop()`, `release_estop()`, `latest_frame(cam=None) -> ndarray|None`, `close()`
  - `build_runtime(cfg, action_source, tap)`, `build_policies(cfg)` — physicalai lazy import
  - CLI: `python -m snackbot.robot oranda_pickup|dori_dori|home [--config]`
- 동작 규칙:
  - `run`: 비상정지면 즉시 `estop`. `ensure_home` → 정책 phase → (oranda_pickup이면 `on_phase("returning")` 후 `lift → home`, dori_dori면 `home`)
  - oranda_pickup 정책 phase는 `GripperWatch.done`이나 `max_time_s`에서 끝난다. `stop_reason`: 그리퍼로 끝나면 `gripper_open`, 시간이면 `timeout`. `grasped` = `GripperWatch.grasped`.
  - 어떤 phase든 비상정지(또는 런타임 `last_run_reason == "interrupted"`, 즉 Ctrl+C)면 그 뒤 이동 없이 `estop`을 돌려준다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_robot.py`:
```python
from types import SimpleNamespace

import numpy as np
import pytest

from snackbot.robot import RobotSkills

POSES = {"home_pose": [0, 0, 0, 0, 0, 80], "lift_pose": [0, -20, 10, 0, 0, 80]}


class FakeCam:
    def __init__(self):
        self.frame = np.full((4, 4, 3), 7, np.uint8)

    def read_latest(self):
        return SimpleNamespace(data=self.frame)

    def read(self, timeout=2.0):
        return self.read_latest()


class FakeRobot:
    def __init__(self, joints):
        self.joints = np.array(joints, np.float32)
        self.history = []

    def get_observation(self):
        return SimpleNamespace(joint_positions=self.joints.copy())


class FakePolicy:
    def __init__(self):
        self.on_update, self.warmed = None, None

    def connect(self, *, bus, session_id):
        pass

    def update(self, robot_state, camera_frames, step):
        if self.on_update:
            self.on_update(step)
        return np.array(robot_state.joint_positions, np.float32)

    def disconnect(self):
        pass

    def to_model_input(self, obs, frames):
        return {"state": obs.joint_positions, "frames": sorted(frames)}

    def warmup(self, model_input):
        self.warmed = model_input


class FakeRuntime:
    """RobotRuntime 흉내: 로봇이 매 틱 목표로 바로 간다. 정책이 도는 동안 gripper 값을 차례로 덮어쓴다."""

    def __init__(self, source, tap, robot, gripper=(), interrupt_at=None, fps=30):
        self.source, self.tap, self.robot, self.fps = source, tap, robot, fps
        self.gripper, self.interrupt_at = list(gripper), interrupt_at
        self.cameras = {"tower cam": FakeCam(), "follow cam": FakeCam()}
        self.runs, self.connected, self.last_run_reason = [], False, None

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def run(self, *, duration_s=None, stop_event=None, return_to_initial_state=False):
        active = self.source.active
        self.runs.append(type(active).__name__)
        self.source.connect(bus=None, session_id=str(len(self.runs)))
        self.last_run_reason, steps = None, 0
        try:
            while True:
                if stop_event is not None and stop_event.is_set():
                    reason = "stop_requested"
                    break
                if duration_s is not None and steps / self.fps >= duration_s:
                    reason = "duration_elapsed"
                    break
                if self.interrupt_at is not None and steps == self.interrupt_at:
                    self.interrupt_at = None
                    reason = "interrupted"
                    break
                action = self.source.update(self.robot.get_observation(), {}, steps)
                self.robot.joints = np.array(action, np.float32)
                if isinstance(active, FakePolicy) and self.gripper:
                    self.robot.joints[5] = self.gripper.pop(0)
                self.robot.history.append(self.robot.joints.copy())
                self.tap.on_tick(SimpleNamespace(
                    robot_state=self.robot.get_observation(),
                    camera_frames={n: c.read_latest() for n, c in self.cameras.items()},
                    timestamp=steps / self.fps))
                steps += 1
        finally:
            self.source.disconnect()
        self.last_run_reason = reason
        return steps


@pytest.fixture
def rcfg(cfg):
    cfg["skills"]["gripper"].update(closed_below=30, open_above=60, grasp_min=15, open_hold_s=0.1)
    cfg["skills"]["move_s"] = 0.1
    cfg["skills"]["oranda_pickup"]["max_time_s"] = 2
    cfg["skills"]["dori_dori"]["max_time_s"] = 0.2
    return cfg


def make(cfg, joints=POSES["home_pose"], gripper=(), interrupt_at=None):
    robot, holder = FakeRobot(joints), {}

    def make_runtime(switch, tap):
        holder["rt"] = FakeRuntime(switch, tap, robot, gripper, interrupt_at)
        return holder["rt"]

    policies = {"oranda_pickup": FakePolicy(), "dori_dori": FakePolicy()}
    skills = RobotSkills(cfg, POSES, make_runtime=make_runtime, policies=policies)
    return skills, holder["rt"], robot


def at(robot, pose):
    return np.allclose(robot.joints, pose, atol=1e-3)


def test_oranda_snack_grasp_release_then_lift_and_home(rcfg):
    s, rt, robot = make(rcfg, gripper=[80, 80] + [25] * 5 + [80] * 10)
    phases = []
    r = s.run("oranda_pickup", on_phase=phases.append)
    assert (r.stop_reason, r.grasped) == ("gripper_open", True)
    assert rt.runs == ["FakePolicy", "MoveSource"]
    assert phases == ["returning"]
    assert any(np.allclose(a, POSES["lift_pose"], atol=1e-3) for a in robot.history)
    assert at(robot, POSES["home_pose"])


def test_oranda_empty_grasp(rcfg):
    s, _, _ = make(rcfg, gripper=[80, 80] + [3] * 5 + [80] * 10)
    r = s.run("oranda_pickup")
    assert (r.stop_reason, r.grasped) == ("gripper_open", False)


def test_oranda_timeout_still_returns_home(rcfg):
    s, rt, robot = make(rcfg, gripper=[80, 80] + [25] * 100)
    r = s.run("oranda_pickup")
    assert r.stop_reason == "timeout" and rt.runs == ["FakePolicy", "MoveSource"]
    assert at(robot, POSES["home_pose"])


def test_moves_home_first_when_away(rcfg):
    s, rt, _ = make(rcfg, joints=[30, 0, 0, 0, 0, 80], gripper=[80, 80] + [25] * 5 + [80] * 10)
    s.run("oranda_pickup")
    assert rt.runs[:2] == ["MoveSource", "FakePolicy"]


def test_dori_dori_runs_for_max_time_then_home(rcfg):
    s, rt, robot = make(rcfg)
    r = s.run("dori_dori")
    assert (r.stop_reason, r.grasped) == ("timeout", False)
    assert rt.runs == ["FakePolicy", "MoveSource"] and at(robot, POSES["home_pose"])


def test_estop_before_run_does_nothing(rcfg):
    s, rt, _ = make(rcfg)
    s.estop()
    assert s.run("dori_dori").stop_reason == "estop" and rt.runs == []


def test_estop_during_policy_stops_without_moving(rcfg):
    s, rt, _ = make(rcfg, gripper=[80] * 100)
    s.policies["oranda_pickup"].on_update = lambda step: s.estop() if step == 3 else None
    assert s.run("oranda_pickup").stop_reason == "estop"
    assert rt.runs == ["FakePolicy"]
    s.release_estop()
    assert s.go_home() == "done" and rt.runs[-1] == "MoveSource"


def test_ctrl_c_interrupt_counts_as_estop(rcfg):
    s, rt, _ = make(rcfg, interrupt_at=2)
    assert s.run("dori_dori").stop_reason == "estop"
    assert rt.runs == ["FakePolicy"]
    assert s.go_home() == "estop"


def test_latest_frame_reads_camera_when_idle_and_cache_when_busy(rcfg):
    s, rt, _ = make(rcfg)
    assert s.latest_frame() is rt.cameras["tower cam"].frame
    busy = np.zeros((2, 2, 3), np.uint8)
    with s._io:
        s.tap.frames["tower cam"] = busy
        assert s.latest_frame("tower cam") is busy


def test_connect_warms_up_both_policies_with_trained_camera_names(rcfg):
    rcfg["skills"]["oranda_pickup"]["camera_map"] = {"A": "tower cam"}
    s, rt, _ = make(rcfg)
    s.connect()
    assert rt.connected
    assert s.policies["dori_dori"].warmed["frames"] == ["follow cam", "tower cam"]
    assert s.policies["oranda_pickup"].warmed["frames"] == ["A", "follow cam", "tower cam"]


def test_missing_poses_or_gripper_values_exit(rcfg, cfg):
    with pytest.raises(SystemExit):
        RobotSkills(rcfg, {"home_pose": [0] * 6}, make_runtime=lambda s, t: None, policies={})
    cfg["skills"]["gripper"]["grasp_min"] = None
    with pytest.raises(SystemExit):
        RobotSkills(cfg, POSES, make_runtime=lambda s, t: None, policies={})
```

참고: `rcfg`와 `cfg` fixture는 같은 객체다 (rcfg가 cfg를 고쳐서 돌려준다). 마지막 테스트는 첫 번째 확인 뒤 같은 객체의 `grasp_min`을 비운다.

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_robot.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'snackbot.robot'`

- [ ] **Step 3: 구현**

`snackbot/robot.py`:
```python
"""실제 로봇 (physicalai 0.3.x). DrySkills와 같은 인터페이스.

RobotRuntime 하나를 시작할 때 연결해 두고, run()마다 동작 출처(Switch.active)를 바꿔 낀다:
정책 A(oranda_pickup) · 정책 B(dori_dori) · MoveSource(자세 이동).
- 정지: run(stop_event=StopAny(...))로 다음 틱에 멈춘다.
- 비상정지: 런타임을 끊지 않는다 → 서보가 마지막 목표를 토크 켠 채 유지한다.
- 카메라·시리얼은 스레드 안전하지 않다 → _io 락으로 한 번에 한 스레드만 쓴다.

python -m snackbot.robot oranda_pickup | dori_dori | home   # 스킬 하나만 실행 (현장 점검용)
"""
import logging
import threading
import time

import numpy as np

from .config import load_calibration
from .motion import GripperWatch, MoveSource, StopAny, Switch, Tap, remap_frames
from .skills import RunResult

log = logging.getLogger(__name__)
POLICIES = ("oranda_pickup", "dori_dori")


def _ms(t0):
    return int((time.monotonic() - t0) * 1000)


def build_runtime(cfg, action_source, tap):
    from physicalai.capture import UVCCamera
    from physicalai.runtime import RobotRuntime
    from physicalai_so101_plugin import SO101

    r = cfg["robot"]
    robot = SO101(port=r["port"], calibration=load_calibration(r["calibration"]), role="follower")
    cameras = {name: UVCCamera(device=c["device"], width=c["width"], height=c["height"], fps=c["fps"])
               for name, c in cfg["cameras"].items()}
    return RobotRuntime(robot=robot, action_source=action_source, fps=float(cfg["skills"].get("fps", 30)),
                        cameras=cameras, callbacks=[tap])


def build_policies(cfg):
    from physicalai.inference import InferenceModel
    from physicalai.runtime import PolicySource

    sk = cfg["skills"]
    return {name: PolicySource(InferenceModel(sk[name]["export_dir"],
                                              device=sk[name].get("device", sk.get("device", "CPU"))))
            for name in POLICIES}


class RobotSkills:
    def __init__(self, cfg, poses, make_runtime=None, policies=None):
        sk = cfg["skills"]
        gripper = sk["gripper"]
        missing = [k for k in ("home_pose", "lift_pose") if k not in poses]
        if missing:
            raise SystemExit(f"{', '.join(missing)} 없음: python -m tools.robot_probe save home / save lift 로 먼저 저장하세요.")
        if any(gripper.get(k) is None for k in ("closed_below", "open_above", "grasp_min")):
            raise SystemExit("config.yaml skills.gripper 값이 비어 있어요: python -m tools.robot_probe watch 로 읽고 채우세요.")
        self.fps = float(sk.get("fps", 30))
        self.move_s = float(sk.get("move_s", 2.0))
        self.home_tolerance = float(sk.get("home_tolerance", 5))
        self.max_time = {name: float(sk[name]["max_time_s"]) for name in POLICIES}
        self.camera_maps = {name: sk[name].get("camera_map") or {} for name in POLICIES}
        self.home = np.asarray(poses["home_pose"], np.float32)
        self.lift = np.asarray(poses["lift_pose"], np.float32)
        self.camera = cfg["vision"].get("camera", "tower cam")
        self.watch = GripperWatch(gripper["closed_below"], gripper["open_above"], gripper["grasp_min"],
                                  gripper.get("open_hold_s", 0.5))
        self.tap, self.switch = Tap(), Switch()
        self.runtime = (make_runtime or (lambda s, t: build_runtime(cfg, s, t)))(self.switch, self.tap)
        self.policies = policies if policies is not None else build_policies(cfg)
        self.tray = 0
        self._estop = threading.Event()
        self._io = threading.Lock()

    def connect(self):
        """로봇·카메라를 연결하고 정책 2개를 warmup한다 (첫 추론이 느린 것을 시작할 때 미리 치른다)."""
        with self._io:
            self.runtime.connect()
            obs = self.runtime.robot.get_observation()
            frames = {name: cam.read() for name, cam in self.runtime.cameras.items()}
        for name, policy in self.policies.items():
            try:
                policy.warmup(policy.to_model_input(obs, remap_frames(frames, self.camera_maps.get(name))))
            except Exception as e:
                log.warning("%s warmup 실패 (첫 실행이 느릴 수 있음): %s", name, e)

    def new_task(self, n):
        pass

    def run(self, name, on_phase=None):
        t0 = time.monotonic()
        if self.ensure_home() == "estop":
            return RunResult("estop", False, _ms(t0))
        if name == "oranda_pickup":
            self.watch.reset()
            self.tap.watch = self.watch
            try:
                reason = self._phase(self.policies[name], self.max_time[name], done=self.watch.done,
                                     camera_map=self.camera_maps[name])
            finally:
                self.tap.watch = None
            if reason == "estop":
                return RunResult("estop", self.watch.grasped, _ms(t0))
            stop_reason = "gripper_open" if reason == "done" else "timeout"
            if on_phase:
                on_phase("returning")
            if self._move([self.lift, self.home]) == "estop":
                return RunResult("estop", self.watch.grasped, _ms(t0))
            return RunResult(stop_reason, self.watch.grasped, _ms(t0))
        if self._phase(self.policies[name], self.max_time[name], camera_map=self.camera_maps[name]) == "estop":
            return RunResult("estop", False, _ms(t0))
        if self._move([self.home]) == "estop":
            return RunResult("estop", False, _ms(t0))
        return RunResult("timeout", False, _ms(t0))

    def ensure_home(self):
        with self._io:
            current = np.asarray(self.runtime.robot.get_observation().joint_positions, np.float32)
        if np.max(np.abs(current - self.home)) <= self.home_tolerance:
            return "done"
        return self._move([self.home])

    def go_home(self):
        return self._move([self.home])

    def _move(self, targets):
        src = MoveSource(targets, self.move_s * self.fps)
        return self._phase(src, len(targets) * self.move_s + 2.0, done=src.done)

    def _phase(self, source, duration_s, done=None, camera_map=None):
        """동작 출처 하나로 run() 한 번. 결과: done | timeout | estop."""
        if self._estop.is_set():
            return "estop"
        self.switch.active, self.switch.camera_map = source, camera_map
        with self._io:
            self.runtime.run(duration_s=duration_s, stop_event=StopAny(self._estop, done))
        if self.runtime.last_run_reason == "interrupted":   # Ctrl+C → 비상정지로 취급
            self._estop.set()
        if self._estop.is_set():
            return "estop"
        if done is not None and done.is_set():
            return "done"
        return "timeout"

    def estop(self):
        self._estop.set()

    def release_estop(self):
        self._estop.clear()

    def latest_frame(self, cam=None):
        """쉬는 중이면 카메라에서 바로 읽고, 동작 중이면 매 틱 저장된 프레임을 준다 (막히지 않는다)."""
        cam = cam or self.camera
        if self._io.acquire(blocking=False):
            try:
                data = self.runtime.cameras[cam].read_latest().data
                with self.tap.lock:
                    self.tap.frames[cam] = data
            except Exception as e:
                log.debug("카메라 %s 읽기 실패: %s", cam, e)
            finally:
                self._io.release()
        with self.tap.lock:
            return self.tap.frames.get(cam)

    def close(self):
        self._estop.set()   # 돌고 있는 동작을 먼저 멈춘다
        with self._io:
            try:
                self.runtime.disconnect()
            except Exception as e:
                log.warning("런타임 해제 실패: %s", e)


def main(argv=None):
    import argparse

    from .config import load_config, load_poses

    p = argparse.ArgumentParser(prog="python -m snackbot.robot", description="스킬 하나만 실행 (현장 점검용)")
    p.add_argument("skill", choices=[*POLICIES, "home"])
    p.add_argument("--config", default="config.yaml")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config(a.config)
    skills = RobotSkills(cfg, load_poses(cfg.get("poses_file", "poses.yaml")))
    skills.connect()
    try:
        if a.skill == "home":
            print("home:", skills.go_home())
        else:
            print(skills.run(a.skill, on_phase=lambda phase: print("phase:", phase)))
    except KeyboardInterrupt:
        skills.estop()
        print("비상정지 (자세 유지)")
    finally:
        skills.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_robot.py -v`
Expected: 11 passed

- [ ] **Step 5: 전체 테스트**

Run: `.venv/Scripts/python -m pytest -q`
Expected: 모두 통과

- [ ] **Step 6: 커밋**

```bash
git add snackbot/robot.py tests/test_robot.py
git commit -m "feat(snackbot): 실제 로봇 스킬 (RobotRuntime 하나 + 동작 출처 교체)

Co-Authored-By: <세션의 attribution 줄>"
```

---

### Task 4: 현장 도구 — 캘리브레이션 받기, 관절값 보기·포즈 저장

**Files:**
- Create: `tools/fetch_calibration.py`, `tools/robot_probe.py`, `tests/test_tools.py`

**Interfaces:**
- Consumes: `load_config`, `load_calibration`, `save_pose` (Task 1)
- Produces:
  - `tools.fetch_calibration.find_follower(doc) -> dict | None` — runtime-config 안에서 `class_path`가 `SO101`로 끝나고 `init_args.role == "follower"`인 노드의 `init_args` (SharedRobot 안에 있어도 찾는다)
  - CLI `python -m tools.fetch_calibration --studio URL --project ID --env ID [--out calibration/follower.yaml]` — GET만 한다
  - CLI `python -m tools.robot_probe watch` / `save home|lift` (토크를 끄고 읽는다, 끝나면 `disconnect()`로 자세 유지)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_tools.py`:
```python
from tools.fetch_calibration import find_follower

CAL = {"shoulder_pan": {"id": 1, "drive_mode": 0, "homing_offset": -1983, "range_min": 0, "range_max": 4095}}
DOC = {
    "class_path": "physicalai.runtime.RobotRuntime",
    "init_args": {
        "robot": {"class_path": "physicalai.robot.SharedRobot", "init_args": {"name": "x", "robot": {
            "class_path": "physicalai_so101_plugin.SO101",
            "init_args": {"port": "/dev/ttyACM1", "calibration": CAL, "role": "follower", "unit": "normalized"}}}},
        "action_source": {"class_path": "physicalai.runtime.TeleopSource", "init_args": {"leader": {
            "class_path": "physicalai.robot.SharedRobot", "init_args": {"robot": {
                "class_path": "physicalai_so101_plugin.SO101",
                "init_args": {"port": "/dev/ttyACM0", "calibration": {"other": 1}, "role": "leader"}}}}}},
    },
}


def test_find_follower_inside_shared_robot():
    found = find_follower(DOC)
    assert found["calibration"] == CAL and found["port"] == "/dev/ttyACM1"


def test_find_follower_none():
    assert find_follower({"init_args": {"robot": {"class_path": "x.Other"}}}) is None
    assert find_follower([{"a": 1}]) is None
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.fetch_calibration'`

- [ ] **Step 3: 구현**

`tools/fetch_calibration.py`:
```python
"""Studio 환경의 runtime-config에서 팔로워 캘리브레이션을 받아 저장한다 (조회만 한다).
녹화·학습 때와 같은 캘리브레이션을 써야 관절 단위가 맞는다.

python -m tools.fetch_calibration --studio http://192.168.0.6:7860 --project <프로젝트 id> --env <환경 id>
"""
import argparse
from pathlib import Path

import httpx
import yaml


def find_follower(node):
    """class_path가 SO101로 끝나고 role이 follower인 노드의 init_args (SharedRobot 안에 있어도)."""
    if isinstance(node, dict):
        args = node.get("init_args")
        if str(node.get("class_path", "")).endswith("SO101") and isinstance(args, dict) \
                and args.get("role") == "follower":
            return args
        children = node.values()
    elif isinstance(node, list):
        children = node
    else:
        return None
    for child in children:
        found = find_follower(child)
        if found is not None:
            return found
    return None


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m tools.fetch_calibration")
    p.add_argument("--studio", required=True, help="예: http://192.168.0.6:7860")
    p.add_argument("--project", required=True)
    p.add_argument("--env", required=True)
    p.add_argument("--out", default="calibration/follower.yaml")
    a = p.parse_args(argv)

    url = f"{a.studio.rstrip('/')}/api/projects/{a.project}/environments/{a.env}/runtime-config"
    r = httpx.get(url, timeout=10)
    r.raise_for_status()
    doc = yaml.safe_load(r.text)
    follower = find_follower(doc)
    if follower is None:
        raise SystemExit("runtime-config에서 follower SO101을 찾지 못했어요")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(follower["calibration"], sort_keys=False), encoding="utf-8")
    print(f"캘리브레이션 저장: {out}")
    print(f"Studio 기준 팔로워 포트: {follower.get('port')} (노트북 포트는 config.yaml robot.port에 직접 쓴다)")
    for name, cam in ((doc.get("init_args") or {}).get("cameras") or {}).items():
        device = cam.get("init_args", {}).get("camera", {}).get("init_args", {}).get("device", {})
        print(f"카메라 {name!r}: index {device.get('index') if isinstance(device, dict) else device}")


if __name__ == "__main__":
    main()
```

`tools/robot_probe.py`:
```python
"""팔로워 관절값 읽기 (현장 점검용). 토크를 끄므로 손으로 팔을 움직일 수 있다 — 팔이 처지니 손으로 받친다.
끝나면 disconnect()가 지금 자세를 목표로 잡고 토크를 켠다.

python -m tools.robot_probe watch          # 5Hz로 관절값 출력. 그리퍼: 열림 / 빈손 닫힘 / 오란다 쥠 값을 적는다
python -m tools.robot_probe save home      # 지금 자세를 poses.yaml의 home_pose로
python -m tools.robot_probe save lift      # 놓은 뒤 위로 든 자세를 lift_pose로
"""
import argparse
import time

import numpy as np

from snackbot.config import load_calibration, load_config, save_pose

JOINTS = "shoulder_pan shoulder_lift elbow_flex wrist_flex wrist_roll gripper"


def open_robot(cfg):
    from physicalai_so101_plugin import SO101

    r = cfg["robot"]
    robot = SO101(port=r["port"], calibration=load_calibration(r["calibration"]), role="follower")
    robot.connect()
    robot.set_torque(enabled=False)
    return robot


def fmt(joints):
    return " ".join(f"{v:7.1f}" for v in joints)


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m tools.robot_probe")
    p.add_argument("cmd", choices=["watch", "save"])
    p.add_argument("name", nargs="?", choices=["home", "lift"])
    p.add_argument("--config", default="config.yaml")
    a = p.parse_args(argv)
    if a.cmd == "save" and a.name is None:
        p.error("save에는 home 또는 lift가 필요해요")
    cfg = load_config(a.config)
    robot = open_robot(cfg)
    try:
        if a.cmd == "watch":
            print(JOINTS, "(Ctrl+C로 끝)")
            while True:
                print(fmt(robot.get_observation().joint_positions), flush=True)
                time.sleep(0.2)
        else:
            joints = np.mean([robot.get_observation().joint_positions for _ in range(5)], axis=0)
            save_pose(cfg.get("poses_file", "poses.yaml"), f"{a.name}_pose", joints)
            print(f"{a.name}_pose 저장: {fmt(joints)}")
    except KeyboardInterrupt:
        pass
    finally:
        robot.disconnect()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_tools.py -v`
Expected: 2 passed

- [ ] **Step 5: 커밋**

```bash
git add tools/fetch_calibration.py tools/robot_probe.py tests/test_tools.py
git commit -m "feat(tools): Studio 캘리브레이션 받기, 관절값 보기·포즈 저장

Co-Authored-By: <세션의 attribution 줄>"
```

---

### Task 5: 진입점에 실제 로봇 연결

**Files:**
- Modify: `snackbot/__main__.py`, `tests/test_main.py`

**Interfaces:**
- Consumes: `RobotSkills` (Task 3), `load_poses` (Task 1)
- Produces: `build(cfg, env, dry_run=False)` → `RobotSkills(cfg, load_poses(cfg.get("poses_file", "poses.yaml")))` (아직 연결하지 않는다); `info["models"]["act"]` = `"ACT · OpenVINO · <skills.device>"`. 포즈가 없으면 physicalai를 import하기 전에 `SystemExit`. 실제 로봇에서는 `vision.chain`의 `fake` counter를 경고와 함께 뺀다 (`RobotSkills.tray`는 항상 0이라 바로 완료가 된다).
- `main`: `skills.connect()`(있으면)를 `try:` 블록 안에서 `controller.start()`보다 먼저 부른다 → 연결·warmup이 실패해도 `finally`의 `skills.close()`가 돈다.

- [ ] **Step 1: 테스트 수정 (실패 확인용)**

`tests/test_main.py`의 `test_build_real_robot_not_yet`을 다음으로 바꾼다:
```python
def test_build_real_robot_requires_poses(cfg, tmp_path):
    cfg["poses_file"] = str(tmp_path / "none.yaml")
    with pytest.raises(SystemExit, match="home_pose"):
        build(cfg, {}, dry_run=False)
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_main.py -v`
Expected: FAIL — `test_build_real_robot_requires_poses`의 `match="home_pose"`가 맞지 않는다 (지금은 "M4 계획에서 구현합니다" 문구로 끝난다)

- [ ] **Step 3: 구현**

`snackbot/__main__.py`의 `build` 앞부분
```python
    if not dry_run:
        raise SystemExit("실제 로봇 연결(physicalai)은 M4 계획에서 구현합니다. 지금은 --dry-run으로 실행하세요.")
    from .skills import DrySkills

    skills = DrySkills(cfg)
```
를 다음으로 바꾼다:
```python
    if dry_run:
        from .skills import DrySkills

        skills, act = DrySkills(cfg), "dry-run"
    else:
        from .config import load_poses
        from .robot import RobotSkills

        skills = RobotSkills(cfg, load_poses(cfg.get("poses_file", "poses.yaml")))
        act = f"ACT · OpenVINO · {cfg['skills'].get('device', 'CPU')}"
        chain = cfg["vision"].get("chain") or []
        if any(e.get("type") == "fake" for e in chain):
            logging.getLogger(__name__).warning("실제 로봇에서는 fake counter를 쓰지 않는다 (vision.chain에서 뺐다)")
            cfg = {**cfg, "vision": {**cfg["vision"], "chain": [e for e in chain if e.get("type") != "fake"]}}
```
같은 함수의 `info` 안 `"act": "dry-run",`을 `"act": act,`로 바꾼다 (`cfg`를 바꿔 쓰는 줄 다음에 `vision = build_vision(cfg["vision"], ...)`이 오도록, 즉 위 분기가 `build_vision` 호출보다 앞에 있어야 한다).

`main`에서 `controller.start()`를 부르는 곳을 찾아, 그 호출과 키 스레드 시작을 기존 `try:` 블록 안으로 옮기고 맨 앞에 연결을 넣는다:
```python
    try:
        connect = getattr(parts["skills"], "connect", None)
        if connect is not None:
            connect()   # 실제 로봇: 연결 + 정책 warmup. 실패해도 finally에서 close()
        controller.start()
        # (기존 키 스레드 시작, --no-ui 대기 / uvicorn 실행 코드가 이어진다)
```
테스트를 하나 더 추가한다:
```python
def test_build_real_robot_drops_fake_counter(cfg, tmp_path, monkeypatch):
    import snackbot.robot as robot
    from snackbot.config import save_pose

    poses = tmp_path / "poses.yaml"
    save_pose(poses, "home_pose", [0] * 6)
    save_pose(poses, "lift_pose", [0] * 6)
    cfg["poses_file"] = str(poses)
    cfg["vision"]["chain"] = [{"type": "fake"}]
    cfg["skills"]["gripper"].update(closed_below=30, open_above=60, grasp_min=15)
    monkeypatch.setattr(robot, "build_runtime", lambda c, s, t: object())
    monkeypatch.setattr(robot, "build_policies", lambda c: {})
    parts = build(cfg, {}, dry_run=False)
    try:
        assert parts["controller"].vision is None
        assert parts["info"]["models"]["act"].startswith("ACT · OpenVINO")
    finally:
        parts["voice"].close()
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/Scripts/python -m pytest -q`
Expected: 모두 통과

- [ ] **Step 5: 커밋**

```bash
git add snackbot/__main__.py tests/test_main.py
git commit -m "feat(snackbot): python -m snackbot 실제 로봇 경로

Co-Authored-By: <세션의 attribution 줄>"
```

---

### Task 6: 현장 절차 문서

**Files:**
- Modify: `CLAUDE.md`, `docs/DEMO_RUNBOOK.md`, `docs/superpowers/specs/2026-10-22-chat-ui-design.md`

- [ ] **Step 1: DEMO_RUNBOOK에 로봇 연결 순서 추가**

`docs/DEMO_RUNBOOK.md`의 `## 2. 시연 직전 체크리스트` 바로 위에 넣는다:
```markdown
## 1-1. 로봇 노트북 처음 연결 (한 번)

1. Studio 세션을 모두 끄고 `docker compose down` (로봇 포트는 한 프로그램만 잡는다)
2. 환경: `python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt -r requirements-robot.txt`
3. 모델: `trained_model/<이름>-model/exports/openvino`에 넣고 `config.yaml skills.*.export_dir` 확인 →
   `.venv/bin/python -m pytest tests/test_config.py` (정책의 카메라 이름 = config 카메라 이름인지 검사)
4. 캘리브레이션: `.venv/bin/python -m tools.fetch_calibration --studio http://192.168.0.6:7860 --project <id> --env <id>`,
   `ls /dev/ttyACM*`로 포트를 찾아 `config.yaml robot.port`, 카메라 번호는 `cameras.*.device`
5. 그리퍼 기준: `.venv/bin/python -m tools.robot_probe watch` → 열림 / 빈손으로 끝까지 닫힘 / 오란다를 쥔 닫힘 값을 적고
   `skills.gripper`의 `closed_below`(쥔 값보다 조금 크게), `open_above`(열림 값보다 조금 작게), `grasp_min`(빈손 값과 쥔 값 사이)을 채운다.
   값이 클수록 닫히는 방향이면 멈추고 보고한다 (코드는 작을수록 닫힘으로 가정)
6. 자세: 팔을 손으로 잡고 `.venv/bin/python -m tools.robot_probe save home`, 빈 트레이 위로 든 자세에서 `save lift`
7. 단독 실행 (한 손은 전원에): `.venv/bin/python -m snackbot.robot home` → `dori_dori` → `oranda_pickup`
   (oranda_pickup은 `RunResult(stop_reason='gripper_open', grasped=True, ...)`가 나와야 한다)
8. 전체: `.venv/bin/python -m snackbot` → 브라우저 `http://127.0.0.1:8000`
```

- [ ] **Step 2: CLAUDE.md 실행 절에 로봇 명령 추가**

`CLAUDE.md`의 `## 실행` 두 번째 코드 블록에서 `tools.save_pose home` / `tools.save_pose lift` 두 줄을 지우고, 블록 끝(닫는 ``` 위)에 추가:
```bash
.venv/Scripts/python -m tools.fetch_calibration --studio http://192.168.0.6:7860 --project <id> --env <id>
.venv/Scripts/python -m tools.robot_probe watch        # 관절값 보기 (그리퍼 기준값 정하기)
.venv/Scripts/python -m tools.robot_probe save home    # 현재 팔 자세를 home_pose로 (lift도 같은 방법)
.venv/Scripts/python -m snackbot.robot dori_dori       # 스킬 하나만 실제 로봇으로
```
같은 파일 `## 파일 구조 (목표)`의 `├── skills.py ...` 줄 아래에 다음 두 줄을 넣고,
```
│   ├── motion.py       # 그리퍼 감시, 보간 이동, 정지 신호 (physicalai 없이 테스트)
│   ├── robot.py        # 실제 로봇: RobotRuntime 하나 + 동작 출처 교체
```
`tools/` 아래 `save_pose.py`·`gripper_stats.py` 두 줄을 다음으로 바꾼다:
```
│   ├── fetch_calibration.py   # Studio runtime-config → calibration/follower.yaml
│   ├── robot_probe.py         # 관절값 보기, home/lift 포즈 저장
│   └── export_yolo_world.py   # YOLO-World → OpenVINO (개수 세기 A단계)
```

- [ ] **Step 3: 설계 문서에 M4 결정 기록**

`docs/superpowers/specs/2026-10-22-chat-ui-design.md`의 `## 12. 미확인 사항` 바로 위에 넣는다:
```markdown
## 11.6 M4 구현 결정 (plans/2026-10-22-snackbot-robot.md)

- 7.1~7.2의 "루프 직접 작성" 대신 **RobotRuntime 하나 + 동작 출처 교체**: `Switch.active` = PolicySource(정책 A/B) 또는 MoveSource(보간 이동). run()마다 `stop_event=StopAny(비상정지, 끝 신호)`.
- 그리퍼 감시는 런타임 콜백 `Tap.on_tick`에서. 정지 조건은 7.2절 그대로 (닫힘 → 열림 0.5초).
- 비상정지: 런타임을 끊지 않는다 (SO101.disconnect는 측정값을 목표로 다시 써서 처진다). 다음 틱에 run이 끝나고 서보는 마지막 목표를 유지.
- 카메라·시리얼은 스레드 안전하지 않아 `_io` 락으로 보호. 동작 중 프레임은 Tap 캐시, 쉬는 중엔 `read_latest()`.
- `tools/gripper_stats.py`(데이터셋 통계) 대신 `tools/robot_probe.py watch`로 실제 그리퍼 값을 보고 정한다. 포즈는 `poses.yaml`.
- `return_to_initial_state`는 쓰지 않는다 (시작 자세로 가는 2.5초 고정 보간이라 lift → home을 표현할 수 없다).
```

- [ ] **Step 4: 커밋**

```bash
git add CLAUDE.md docs/DEMO_RUNBOOK.md docs/superpowers/specs/2026-10-22-chat-ui-design.md
git commit -m "docs: 로봇 노트북 연결 절차와 M4 구현 결정

Co-Authored-By: <세션의 attribution 줄>"
```

---

## 실제 로봇에서만 확인할 수 있는 것 (계획 밖, 현장 체크)

- `UVCCamera(device=0, 1280, 720, 30)`이 노트북 카메라에서 열리는지 (지원 포맷이 아니면 `CaptureError`에 목록이 나온다)
- 그리퍼 값 방향 (작을수록 닫힘인지)
- `PolicySource` 기본 실행(SyncExecution)에서 GPU 추론 지연이 30fps 루프를 얼마나 늦추는지 → 느리면 `skills.device: CPU`와 비교
- 첫 GPU 컴파일 시간 (connect의 warmup에서 치른다)
- oranda_pickup 결과물 폴더 이름과 카메라 이름 (Task 1 테스트가 확인). 사이드 캠의 Studio 이름이 `side cam`이 아니면 config 키를 그 이름으로 바꾼다
- 카메라 3대를 1280×720@30으로 동시에 읽을 때 USB 대역폭·루프 지연 (dori_dori만 돌릴 때도 3대를 읽는다)
