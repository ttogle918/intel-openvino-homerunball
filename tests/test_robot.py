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
        self.on_update = None

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


class FakeModel:
    """InferenceModel 흉내: predict_action_chunk가 받은 입력을 기록하고, 필요한 키가 없으면 KeyError."""

    def __init__(self, needs=()):
        self.needs, self.calls, self.resets = needs, [], 0

    def predict_action_chunk(self, inputs):
        self.calls.append(inputs)
        for k in self.needs:
            if k not in inputs["frames"]:
                raise KeyError(f"Expected input 'images.{k}' not found in inputs.\nAvailable keys: x")
        return np.zeros((2, 6), np.float32)

    def reset(self):
        self.resets += 1


class FakeRuntime:
    """RobotRuntime 흉내: 로봇이 매 틱 목표로 바로 간다. 정책이 도는 동안 gripper 값을 차례로 덮어쓴다."""

    def __init__(self, source, tap, robot, gripper=(), interrupt_at=None, fps=30):
        self.source, self.tap, self.robot, self.fps = source, tap, robot, fps
        self.gripper, self.interrupt_at = list(gripper), interrupt_at
        self.cameras = {"tower cam": FakeCam(), "follow cam": FakeCam()}
        self.runs, self.connected, self.last_run_reason = [], False, None
        self.return_to_initial = []

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def run(self, *, duration_s=None, stop_event=None, return_to_initial_state=False):
        if not self.connected:
            raise RuntimeError("Runtime is not connected")   # 실제 RobotRuntime.run과 같다
        self.return_to_initial.append(return_to_initial_state)
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


def make(cfg, joints=POSES["home_pose"], gripper=(), interrupt_at=None, models=None):
    robot, holder = FakeRobot(joints), {}

    def make_runtime(switch, tap):
        holder["rt"] = FakeRuntime(switch, tap, robot, gripper, interrupt_at)
        return holder["rt"]

    policies = {"oranda_pickup": FakePolicy(), "dori_dori": FakePolicy()}
    skills = RobotSkills(cfg, POSES, make_runtime=make_runtime, policies=policies, models=models)
    skills.connect()
    return skills, holder["rt"], robot


def after_run(rt, fn):
    """rt.run이 끝난 직후 fn(그때까지의 run 횟수)을 부른다 (스레드·sleep 없이 경쟁 순서를 고정)."""
    orig = rt.run

    def run(**kw):
        result = orig(**kw)
        fn(len(rt.runs))
        return result

    rt.run = run


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


def test_connect_runs_models_with_trained_camera_names_and_resets(rcfg):
    rcfg["skills"]["oranda_pickup"]["camera_map"] = {"A": "tower cam"}
    models = {"oranda_pickup": FakeModel(needs=["A"]), "dori_dori": FakeModel(needs=["tower cam"])}
    s, rt, _ = make(rcfg, models=models)
    assert rt.connected
    assert models["dori_dori"].calls[0]["frames"] == ["follow cam", "tower cam"]
    assert models["oranda_pickup"].calls[0]["frames"] == ["A", "follow cam", "tower cam"]
    assert [m.resets for m in models.values()] == [1, 1]


def test_connect_exits_with_hint_when_model_input_does_not_match(rcfg):
    models = {"oranda_pickup": FakeModel(needs=["A"]), "dori_dori": FakeModel()}
    with pytest.raises(SystemExit, match="oranda_pickup 입력이 안 맞아요.*camera_map"):
        make(rcfg, models=models)


def test_missing_poses_or_gripper_values_exit(rcfg, cfg):
    with pytest.raises(SystemExit):
        RobotSkills(rcfg, {"home_pose": [0] * 6}, make_runtime=lambda s, t: None, policies={})
    cfg["skills"]["gripper"]["grasp_min"] = None
    with pytest.raises(SystemExit):
        RobotSkills(cfg, POSES, make_runtime=lambda s, t: None, policies={"oranda_pickup": FakePolicy()})
    RobotSkills(cfg, POSES, make_runtime=lambda s, t: None, policies={"dori_dori": FakePolicy()})   # oranda 없으면 불필요


def test_estop_during_ensure_home_then_release_does_not_start_policy(rcfg):
    s, rt, _ = make(rcfg, joints=[30, 0, 0, 0, 0, 80])
    after_run(rt, lambda n: (s.estop(), s.release_estop()) if n == 1 else None)   # estop 직후 release가 끼어든다
    assert s.run("dori_dori").stop_reason == "estop"
    assert rt.runs == ["MoveSource"]


def test_estop_release_during_policy_tick_still_stops_run(rcfg):
    s, rt, _ = make(rcfg, gripper=[80] * 100)
    s.policies["oranda_pickup"].on_update = lambda step: (s.estop(), s.release_estop()) if step == 3 else None
    assert s.run("oranda_pickup").stop_reason == "estop"
    assert rt.runs == ["FakePolicy"]


def test_estop_between_policy_and_lift_skips_returning(rcfg):
    s, rt, _ = make(rcfg, gripper=[80, 80] + [25] * 5 + [80] * 10)
    after_run(rt, lambda n: s.estop() if n == 1 else None)
    phases = []
    assert s.run("oranda_pickup", on_phase=phases.append).stop_reason == "estop"
    assert phases == [] and rt.runs == ["FakePolicy"]


def test_estop_during_lift_stops_without_home(rcfg):
    s, rt, _ = make(rcfg, gripper=[80, 80] + [25] * 5 + [80] * 10)
    after_run(rt, lambda n: s.estop() if n == 2 else None)   # 2번째 run = lift/home 이동
    assert s.run("oranda_pickup").stop_reason == "estop"
    assert rt.runs == ["FakePolicy", "MoveSource"]


def test_estop_during_go_home(rcfg):
    s, rt, _ = make(rcfg, joints=[30, 0, 0, 0, 0, 80])
    after_run(rt, lambda n: s.estop())
    assert s.go_home() == "estop"


def test_estop_keeps_runtime_connected_and_never_returns_to_initial_state(rcfg):
    s, rt, _ = make(rcfg, gripper=[80] * 100)
    s.policies["oranda_pickup"].on_update = lambda step: s.estop() if step == 3 else None
    s.run("oranda_pickup")
    assert rt.connected
    assert rt.return_to_initial and not any(rt.return_to_initial)


def test_fake_runtime_rejects_run_before_connect(rcfg):
    robot, holder = FakeRobot(POSES["home_pose"]), {}

    def make_runtime(switch, tap):
        holder["rt"] = FakeRuntime(switch, tap, robot)
        return holder["rt"]

    s = RobotSkills(rcfg, POSES, make_runtime=make_runtime, policies={"dori_dori": FakePolicy()})
    with pytest.raises(RuntimeError, match="not connected"):
        s.run("dori_dori")


def test_timeout_lift_keeps_current_gripper(rcfg):
    rcfg["skills"]["oranda_pickup"]["max_time_s"] = 0.2
    s, _, robot = make(rcfg, gripper=[80, 80] + [25] * 100)
    r = s.run("oranda_pickup")
    assert r.stop_reason == "timeout"
    lift_steps = [a for a in robot.history if np.allclose(a[:5], POSES["lift_pose"][:5], atol=1e-3)]
    assert lift_steps and all(abs(a[5] - 25) < 1e-3 for a in lift_steps)
    assert at(robot, POSES["home_pose"])


def test_unknown_skill_fails_before_moving(rcfg):
    s, rt, _ = make(rcfg, joints=[30, 0, 0, 0, 0, 80])
    with pytest.raises(ValueError):
        s.run("dance")
    assert rt.runs == []


def test_missing_policy_raises_before_moving_and_home_still_works(rcfg, caplog):
    robot, holder = FakeRobot([30, 0, 0, 0, 0, 80]), {}

    def make_runtime(switch, tap):
        holder["rt"] = FakeRuntime(switch, tap, robot)
        return holder["rt"]

    rcfg["skills"]["oranda_pickup"]["export_dir"] = "no/such/dir"
    rcfg["skills"]["dori_dori"]["export_dir"] = "no/such/dir2"
    rcfg["skills"]["gripper"]["grasp_min"] = None   # oranda가 없으면 기준값이 비어 있어도 된다
    s = RobotSkills(rcfg, POSES, make_runtime=make_runtime)   # 폴더 없음 -> 정책 0개, physicalai import 없음
    assert s.policies == {} and "such" in caplog.text and "dir2" in caplog.text
    s.connect()
    with pytest.raises(RuntimeError, match="oranda_pickup 정책이 로드되지 않았어요"):
        s.run("oranda_pickup")
    assert holder["rt"].runs == []
    assert s.go_home() == "done" and at(robot, POSES["home_pose"])


def test_idle_camera_read_failure_warns(rcfg, caplog):
    s, rt, _ = make(rcfg)

    def boom():
        raise OSError("boom")

    rt.cameras["tower cam"].read_latest = boom
    with caplog.at_level("WARNING"):
        s.latest_frame()
    assert "boom" in caplog.text
