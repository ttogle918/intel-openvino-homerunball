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
