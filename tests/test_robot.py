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
