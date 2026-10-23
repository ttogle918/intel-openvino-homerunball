from types import SimpleNamespace

import sys
import threading

import numpy as np
import pytest

from snackbot.robot import RobotSkills, build_policies, dori_keyframes, dori_settings
from snackbot.twin import load_episode

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
        self.on_update, self.disconnects = None, 0

    def connect(self, *, bus, session_id):
        pass

    def update(self, robot_state, camera_frames, step):
        if self.on_update:
            self.on_update(step)
        return np.array(robot_state.joint_positions, np.float32)

    def disconnect(self):
        self.disconnects += 1

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


def make(cfg, joints=POSES["home_pose"], gripper=(), interrupt_at=None, models=None, recorder=None):
    robot, holder = FakeRobot(joints), {}

    def make_runtime(switch, tap):
        holder["rt"] = FakeRuntime(switch, tap, robot, gripper, interrupt_at)
        return holder["rt"]

    policies = {"oranda_pickup": FakePolicy(), "dori_dori": FakePolicy()}
    skills = RobotSkills(cfg, POSES, make_runtime=make_runtime, policies=policies, models=models, recorder=recorder)
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


def test_connect_exits_with_policy_name_on_other_input_errors(rcfg):
    class BadShape(FakeModel):
        def predict_action_chunk(self, inputs):
            raise ValueError("state shape (1, 6) != (1, 7)")

    with pytest.raises(SystemExit, match="dori_dori.*ValueError.*shape"):
        make(rcfg, models={"oranda_pickup": FakeModel(), "dori_dori": BadShape()})


def test_go_home_waits_for_old_run_and_old_policy_is_disconnected(rcfg):
    """space -> h: 이전 run이 _io를 잡은 동안 go_home이 동작 출처를 바꿔 끼우면 안 된다."""
    s, rt, _ = make(rcfg, gripper=[80] * 100)
    policy = s.policies["oranda_pickup"]
    seen, out = {}, {}

    def go_home_thread():
        out["home"] = s.go_home()

    t = threading.Thread(target=go_home_thread)

    def on_update(step):
        if step != 1:
            return
        s.estop()
        s.release_estop()
        t.start()
        t.join(timeout=0.3)   # 고쳐졌으면 go_home은 _io에서 막혀 있어 끝나지 않는다
        seen["blocked"] = t.is_alive()
        seen["active_is_policy"] = s.switch.active is policy

    policy.on_update = on_update
    assert s.run("oranda_pickup").stop_reason == "estop"
    t.join(timeout=5)
    assert seen == {"blocked": True, "active_is_policy": True}
    assert policy.disconnects == 1
    assert out["home"] == "done" and rt.runs == ["FakePolicy", "MoveSource"]


def _fast_clock(monkeypatch, on_sleep=lambda: None):
    ticks = iter(range(10**6))
    monkeypatch.setattr("snackbot.robot.time", SimpleNamespace(
        monotonic=lambda: next(ticks) * 0.3, sleep=lambda _s: on_sleep()))


def test_settle_warns_when_arm_does_not_reach_target(rcfg, caplog, monkeypatch):
    _fast_clock(monkeypatch)
    s, _, _ = make(rcfg, joints=[30, 0, 0, 0, 0, 80])
    s.home_tolerance = -1   # 항상 도착하지 못한 것으로 본다
    with caplog.at_level("WARNING"):
        assert s.go_home() == "done"
    assert "벗어나 있어요" in caplog.text


def test_estop_during_settle_returns_estop_without_warning(rcfg, caplog, monkeypatch):
    holder = {}
    _fast_clock(monkeypatch, on_sleep=lambda: holder["s"].estop())
    s, _, _ = make(rcfg, joints=[30, 0, 0, 0, 0, 80])
    holder["s"] = s
    s.home_tolerance = -1
    with caplog.at_level("WARNING"):
        assert s.go_home() == "estop"
    assert "벗어나 있어요" not in caplog.text


def test_camera_failure_warns_once_until_recovered(rcfg, caplog):
    s, rt, _ = make(rcfg)
    cam, good = rt.cameras["tower cam"], rt.cameras["tower cam"].read_latest
    state = {"fail": True}

    def flaky():
        if state["fail"]:
            raise OSError("boom")
        return good()

    cam.read_latest = flaky
    with caplog.at_level("WARNING"):
        s.latest_frame(); s.latest_frame()
        assert caplog.text.count("boom") == 1
        state["fail"] = False
        s.latest_frame()
        state["fail"] = True
        s.latest_frame()
        assert caplog.text.count("boom") == 2


def test_policy_phase_is_recorded_but_moves_are_not(rcfg):
    s, rt, _ = make(rcfg, joints=[30, 0, 0, 0, 0, 80], gripper=[80, 80] + [25] * 5 + [80] * 10)
    steps = []
    s.policies["oranda_pickup"].on_update = steps.append
    r = s.run("oranda_pickup")
    s.recorder.wait(5)
    ep = load_episode(s.recorder.last_folder)
    assert rt.runs == ["MoveSource", "FakePolicy", "MoveSource"]
    assert len(ep["joints"]) == len(steps)                # 정책이 돈 틱만 (홈·lift 이동은 제외)
    assert (ep["stop_reason"], ep["grasped"]) == (r.stop_reason, r.grasped) == ("gripper_open", True)
    assert set(ep["cameras"]) == {"tower cam", "follow cam"}
    assert s.tap.recorder is None


def test_recording_disabled_or_broken_does_not_change_run(rcfg, tmp_path, caplog):
    rcfg["recording"]["enabled"] = False
    s, _, _ = make(rcfg)
    assert s.run("dori_dori").stop_reason == "timeout" and s.recorder.last_folder is None

    (tmp_path / "file").write_text("x", encoding="utf-8")
    rcfg["recording"].update(enabled=True, dir=str(tmp_path / "file"))
    s2, _, _ = make(rcfg)
    with caplog.at_level("WARNING"):
        assert s2.run("dori_dori").stop_reason == "timeout"
    assert "실행 기록을 시작하지 못했어요" in caplog.text


def test_latest_joints_none_before_connect_then_cached_copy(rcfg):
    robot = FakeRobot(POSES["home_pose"])
    s = RobotSkills(rcfg, POSES, make_runtime=lambda sw, t: FakeRuntime(sw, t, robot),
                    policies={"dori_dori": FakePolicy()})
    assert s.latest_joints() is None
    s.connect()
    assert s.latest_joints() == POSES["home_pose"]
    robot.joints[:] = 99                                  # 캐시는 connect·틱에서만 바뀐다
    assert s.latest_joints() == POSES["home_pose"]
    s.run("dori_dori")
    assert s.latest_joints() == pytest.approx(POSES["home_pose"])


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


def test_dori_script_runs_script_even_when_source_policy_and_model_loaded(rcfg):
    s, rt, robot = make(rcfg)
    assert s.dori_source == "policy" and "dori_dori" in s.policies
    r = s.run("dori_script")
    assert (r.stop_reason, r.grasped) == ("script", False)
    assert rt.runs == ["MoveSource"]                      # 정책(FakePolicy)은 돌지 않는다
    pan = [float(a[0]) for a in robot.history]
    assert max(pan) == pytest.approx(15) and min(pan) == pytest.approx(-15)
    assert at(robot, POSES["home_pose"])
    assert s.run("dori_dori").stop_reason == "timeout"    # 기존 도리도리는 그대로 정책


def test_estop_during_dori_script_returns_estop_even_with_policy_loaded(rcfg):
    s, rt, robot = make(rcfg)
    tick = s.tap.on_tick

    def on_tick(event):
        tick(event)
        if len(robot.history) == 7:
            s.estop()

    s.tap.on_tick = on_tick
    assert s.run("dori_script").stop_reason == "estop"
    assert rt.runs == ["MoveSource"] and len(robot.history) == 7


def test_dori_source_policy_without_model_or_unknown_source_exits(rcfg):
    rcfg["skills"]["dori_dori"]["source"] = "policy"
    with pytest.raises(SystemExit, match="source"):
        make_script(rcfg)
    rcfg["skills"]["dori_dori"]["source"] = "magic"
    with pytest.raises(SystemExit, match="auto"):
        make(rcfg)


def test_build_policies_policy_without_dori_model_exits_before_any_load(rcfg, tmp_path):
    oranda = tmp_path / "oranda"
    oranda.mkdir()
    rcfg["skills"]["oranda_pickup"]["export_dir"] = str(oranda)       # oranda 모델은 있다 (로드 대상)
    rcfg["skills"]["dori_dori"].update(export_dir=str(tmp_path / "none"), source="policy")
    sys.modules.pop("physicalai", None)
    with pytest.raises(SystemExit, match="dori_dori"):
        build_policies(rcfg)
    assert "physicalai" not in sys.modules                           # 어떤 모델도 로드하기 전에 끝났다


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


def test_dori_settings_rejects_unsafe_values(caplog):
    bad = ({"shake_s": 0}, {"shake_s": float("inf")}, {"shake_s": float("nan")}, {"amplitude": float("nan")},
           {"amplitude": float("inf")}, {"amplitude": True}, {"shakes": 2.9}, {"shakes": True}, {"shakes": "2"},
           {"joint": 0}, {"joint": None})
    for conf in bad:
        with pytest.raises(SystemExit):
            dori_settings(conf)
    for script in ("shoulder_pan", ["joint"], 3):
        with pytest.raises(SystemExit):
            dori_settings(script)


def test_dori_settings_clamps_speed_and_length(caplog):
    with caplog.at_level("WARNING"):
        s = dori_settings({"shake_s": 0.01, "shakes": 100})
    assert s["shake_s"] == 0.15 and s["shakes"] == 10 and "0.15" in caplog.text
    assert dori_settings({"shake_s": 1e5})["shake_s"] == 3.0
    assert dori_settings({"shake_s": 0.15, "shakes": 10})["shakes"] == 10


def test_bad_dori_script_config_exits_before_loading_models(rcfg, tmp_path):
    export = tmp_path / "dori"
    export.mkdir()
    rcfg["skills"]["dori_dori"].update(export_dir=str(export), source="script", script={"shake_s": float("nan")})
    rcfg["skills"]["oranda_pickup"]["export_dir"] = str(tmp_path / "none")
    with pytest.raises(SystemExit, match="shake_s"):
        build_policies(rcfg)
    assert "physicalai" not in sys.modules
    rcfg["skills"]["dori_dori"].update(source="magic", script={})
    with pytest.raises(SystemExit, match="auto"):
        build_policies(rcfg)


def test_script_dori_goes_home_after_timeout(rcfg, monkeypatch):
    s, rt, robot = make_script(rcfg)
    calls = []
    real = s._move

    def fake_move(targets, gen, segment_s=None):
        calls.append(len(targets))
        return "timeout" if len(calls) == 1 and segment_s else real(targets, gen, segment_s)

    monkeypatch.setattr(s, "_move", fake_move)
    assert s._script_dori(s._current_gen()) == "done"
    assert calls == [5, 1] and at(robot, POSES["home_pose"])
