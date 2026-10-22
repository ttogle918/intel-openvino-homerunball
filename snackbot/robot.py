"""실제 로봇 (physicalai 0.3.x). DrySkills와 같은 인터페이스.

RobotRuntime 하나를 시작할 때 연결해 두고, run()마다 동작 출처(Switch.active)를 바꿔 낀다:
정책 A(oranda_pickup) · 정책 B(dori_dori) · MoveSource(자세 이동).
- 정지: run(stop_event=StopAny(...))로 다음 틱에 멈춘다.
- 비상정지: 런타임을 끊지 않는다 → 서보가 마지막 목표를 토크 켠 채 유지한다.
  estop()마다 세대 번호가 올라가, release_estop()이 바로 끼어도 진행 중이던 run은 estop으로 끝난다.
- 카메라·시리얼은 스레드 안전하지 않다 → _io 락으로 한 번에 한 스레드만 쓴다.
- close()는 SO101.disconnect()가 측정값을 목표로 다시 쓴다 (프로세스를 끝내는 시점이라 토크는 유지된다).

python -m snackbot.robot oranda_pickup | dori_dori | home   # 스킬 하나만 실행 (현장 점검용)
"""
import logging
import threading
import time
from pathlib import Path

import numpy as np

from .config import load_calibration
from .motion import GRIPPER, GripperWatch, MoveSource, StopAny, Switch, Tap, remap_frames
from .skills import RunResult

log = logging.getLogger(__name__)
POLICIES = ("oranda_pickup", "dori_dori")


def _ms(t0):
    return int((time.monotonic() - t0) * 1000)


def load_so101():
    """physicalai 0.3.0 본체의 SO101 (Studio 백엔드와 같은 경로). 없으면 플러그인 패키지."""
    try:
        from physicalai.robot.so101 import SO101
    except ImportError:
        from physicalai_so101_plugin import SO101
    return SO101


def build_runtime(cfg, action_source, tap):
    from physicalai.capture import UVCCamera
    from physicalai.runtime import RobotRuntime

    SO101 = load_so101()

    r = cfg["robot"]
    robot = SO101(port=r["port"], calibration=load_calibration(r["calibration"]), role="follower")
    cameras = {name: UVCCamera(device=c["device"], width=c["width"], height=c["height"], fps=c["fps"])
               for name, c in cfg["cameras"].items()}
    return RobotRuntime(robot=robot, action_source=action_source, fps=float(cfg["skills"].get("fps", 30)),
                        cameras=cameras, callbacks=[tap])


def build_policies(cfg):
    """(policies, models). export_dir 폴더가 없는 정책은 로드하지 않고 경고만 한다 (모델이 아직 없는 경우)."""
    sk = cfg["skills"]
    found = {}
    for name in POLICIES:
        export_dir = Path(sk[name]["export_dir"])
        if export_dir.is_dir():
            found[name] = export_dir
        else:
            log.warning("%s 정책을 로드하지 않아요: 폴더가 없어요 (%s)", name, export_dir)
    if not found:
        return {}, {}
    from physicalai.inference import InferenceModel
    from physicalai.runtime import PolicySource

    models = {name: InferenceModel(d, device=sk[name].get("device", sk.get("device", "CPU")))
              for name, d in found.items()}
    return {name: PolicySource(m) for name, m in models.items()}, models


class _Aborted:
    """run() 하나의 정지 신호: 비상정지가 켜져 있거나, 이 run을 시작한 뒤 estop()이 한 번이라도 불렸으면 set."""

    def __init__(self, skills, gen):
        self._skills, self._gen = skills, gen

    def is_set(self):
        s = self._skills
        return s._estop.is_set() or s._current_gen() != self._gen


class RobotSkills:
    def __init__(self, cfg, poses, make_runtime=None, policies=None, models=None):
        sk = cfg["skills"]
        missing = [k for k in ("home_pose", "lift_pose") if k not in poses]
        if missing:
            raise SystemExit(f"{', '.join(missing)} 없음: python -m tools.robot_probe save home / save lift 로 먼저 저장하세요.")
        if policies is None:
            policies, models = build_policies(cfg)
        self.policies, self.models = policies, models or {}
        self.watch = None
        if "oranda_pickup" in self.policies:   # 그리퍼 기준값은 oranda_pickup이 있을 때만 필요
            gripper = sk["gripper"]
            if any(gripper.get(k) is None for k in ("closed_below", "open_above", "grasp_min")):
                raise SystemExit("config.yaml skills.gripper 값이 비어 있어요: python -m tools.robot_probe watch 로 읽고 채우세요.")
            self.watch = GripperWatch(gripper["closed_below"], gripper["open_above"], gripper["grasp_min"],
                                      gripper.get("open_hold_s", 0.5))
        self.fps = float(sk.get("fps", 30))
        self.move_s = float(sk.get("move_s", 2.0))
        self.home_tolerance = float(sk.get("home_tolerance", 5))
        self.max_time = {name: float(sk[name]["max_time_s"]) for name in self.policies}
        self.camera_maps = {name: sk[name].get("camera_map") or {} for name in POLICIES}
        self.home = np.asarray(poses["home_pose"], np.float32)
        self.lift = np.asarray(poses["lift_pose"], np.float32)
        self.camera = cfg["vision"].get("camera", "tower cam")
        self.tap, self.switch = Tap(), Switch()
        self.runtime = (make_runtime or (lambda s, t: build_runtime(cfg, s, t)))(self.switch, self.tap)
        self.tray = 0
        self._estop = threading.Event()
        self._estop_gen = 0
        self._gen_lock = threading.Lock()
        self._io = threading.Lock()

    def _current_gen(self):
        with self._gen_lock:
            return self._estop_gen

    def connect(self):
        """로봇·카메라를 연결하고, 정책을 실제 관절값·카메라 프레임으로 한 번 돌려 본다
        (첫 추론 지연과 입력 이름 오류를 시작할 때 치른다)."""
        with self._io:
            self.runtime.connect()
            obs = self.runtime.robot.get_observation()
            frames = {name: cam.read() for name, cam in self.runtime.cameras.items()}
        for name, policy in self.policies.items():
            model = self.models.get(name)
            if model is None:
                continue
            inputs = policy.to_model_input(obs, remap_frames(frames, self.camera_maps.get(name)))
            try:
                chunk = model.predict_action_chunk(inputs)
            except KeyError as e:
                key = str(e.args[0]).splitlines()[0] if e.args else e
                raise SystemExit(f"정책 {name} 입력이 안 맞아요: {key} — manifest.json의 images.<이름>과 "
                                 "config cameras / camera_map 확인") from e
            model.reset()
            log.info("%s warmup 완료: chunk %s", name, getattr(chunk, "shape", "?"))

    def new_task(self, n):
        pass

    def run(self, name, on_phase=None):
        if name not in POLICIES:
            raise ValueError(f"알 수 없는 스킬: {name}")
        if name not in self.policies:
            raise RuntimeError(f"{name} 정책이 로드되지 않았어요 (config.yaml skills.{name}.export_dir 폴더 확인)")
        t0 = time.monotonic()
        gen = self._current_gen()
        if self.ensure_home(gen) == "estop":
            return RunResult("estop", False, _ms(t0))
        if name == "oranda_pickup":
            self.watch.reset()
            self.tap.watch = self.watch
            try:
                reason = self._phase(self.policies[name], self.max_time[name], gen, done=self.watch.done,
                                     camera_map=self.camera_maps[name])
            finally:
                self.tap.watch = None
            if reason == "estop" or _Aborted(self, gen).is_set():
                return RunResult("estop", self.watch.grasped, _ms(t0))
            stop_reason = "gripper_open" if reason == "done" else "timeout"
            if on_phase:
                on_phase("returning")
            lift = self.lift.copy()
            if stop_reason == "timeout":   # 놓지 못한 채 끝났다: 들어 올리는 동안 그리퍼는 지금 값 유지
                with self._io:
                    lift[GRIPPER] = self.runtime.robot.get_observation().joint_positions[GRIPPER]
            if self._move([lift, self.home], gen) == "estop":
                return RunResult("estop", self.watch.grasped, _ms(t0))
            return RunResult(stop_reason, self.watch.grasped, _ms(t0))
        if self._phase(self.policies[name], self.max_time[name], gen, camera_map=self.camera_maps[name]) == "estop":
            return RunResult("estop", False, _ms(t0))
        if self._move([self.home], gen) == "estop":
            return RunResult("estop", False, _ms(t0))
        return RunResult("timeout", False, _ms(t0))

    def ensure_home(self, gen=None):
        gen = self._current_gen() if gen is None else gen
        with self._io:
            current = np.asarray(self.runtime.robot.get_observation().joint_positions, np.float32)
        if np.max(np.abs(current - self.home)) <= self.home_tolerance:
            return "done"
        return self._move([self.home], gen)

    def go_home(self):
        return self._move([self.home], self._current_gen())

    def _move(self, targets, gen):
        src = MoveSource(targets, self.move_s * self.fps)
        result = self._phase(src, len(targets) * self.move_s + 2.0, gen, done=src.done)
        if result == "done":
            self._settle(targets[-1], gen)
        return result

    def _settle(self, target, gen):
        """명령을 다 보낸 뒤 실제로 도착했는지 본다 (서보가 따라가는 중이면 최대 1초 기다리고, 그래도 멀면 경고)."""
        aborted, deadline = _Aborted(self, gen), time.monotonic() + 1.0
        while True:
            with self._io:
                current = np.asarray(self.runtime.robot.get_observation().joint_positions, np.float32)
            err = float(np.max(np.abs(current - np.asarray(target, np.float32))))
            if err <= self.home_tolerance:
                return
            if time.monotonic() >= deadline or aborted.is_set():
                log.warning("이동 뒤에도 목표에서 %.1f 벗어나 있어요 (허용 %.1f): 걸렸는지 확인하세요",
                            err, self.home_tolerance)
                return
            time.sleep(0.1)

    def _phase(self, source, duration_s, gen, done=None, camera_map=None):
        """동작 출처 하나로 run() 한 번. 결과: done | timeout | estop."""
        aborted = _Aborted(self, gen)
        if aborted.is_set():
            return "estop"
        self.switch.active, self.switch.camera_map = source, camera_map
        with self._io:
            self.runtime.run(duration_s=duration_s, stop_event=StopAny(aborted, done))
        if self.runtime.last_run_reason == "interrupted":   # Ctrl+C → 비상정지로 취급
            self.estop()
        if aborted.is_set():
            return "estop"
        if done is not None and done.is_set():
            return "done"
        return "timeout"

    def estop(self):
        with self._gen_lock:
            self._estop_gen += 1
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
                log.warning("카메라 %s 읽기 실패: %s", cam, e)
            finally:
                self._io.release()
        with self.tap.lock:
            return self.tap.frames.get(cam)

    def close(self):
        self.estop()   # 돌고 있는 동작을 먼저 멈춘다
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
    try:
        skills.connect()
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
