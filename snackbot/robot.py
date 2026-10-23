"""실제 로봇 (physicalai 0.3.x). DrySkills와 같은 인터페이스.

RobotRuntime 하나를 시작할 때 연결해 두고, run()마다 동작 출처(Switch.active)를 바꿔 낀다:
정책 A(oranda_pickup) · 정책 B(dori_dori) · MoveSource(자세 이동, 코드 도리도리).
- dori_dori: skills.dori_dori.source = auto(모델이 있으면 정책, 없으면 코드) | policy | script.
  코드 도리도리는 홈에서 한 관절만 ±amplitude를 오가는 MoveSource 키프레임이다 (정책 phase처럼 실행 기록).
- 정지: run(stop_event=StopAny(...))로 다음 틱에 멈춘다.
- 비상정지: 런타임을 끊지 않는다 → 서보가 마지막 목표를 토크 켠 채 유지한다.
  estop()마다 세대 번호가 올라가, release_estop()이 바로 끼어도 진행 중이던 run은 estop으로 끝난다.
- 카메라·시리얼은 스레드 안전하지 않다 → _io 락으로 한 번에 한 스레드만 쓴다.
- close()는 SO101.disconnect()가 측정값을 목표로 다시 쓴다 (프로세스를 끝내는 시점이라 토크는 유지된다).

python -m snackbot.robot oranda_pickup | dori_dori | dori_policy | dori_script | home   # 스킬 하나만 실행 (현장 점검용)
"""
import logging
import math
import threading
import time
from pathlib import Path

import numpy as np

from .config import load_calibration
from .motion import GRIPPER, GripperWatch, MoveSource, StopAny, Switch, Tap, remap_frames
from .recorder import RunRecorder
from .skills import RunResult
from .twin import JOINTS

log = logging.getLogger(__name__)
POLICIES = ("oranda_pickup", "dori_dori")
POLICY_DORI = "dori_policy"   # 모델 도리도리 (테스트 버튼): source와 무관하게 항상 정책으로 실행
SCRIPT_DORI = "dori_script"   # 코드 도리도리 (테스트 버튼·점검용): 정책이 아니라 source·모델과 무관하게 항상 코드로 실행
DORI_SOURCES = ("auto", "policy", "script")
DORI_MAX_AMPLITUDE = 30.0                 # 코드 도리도리 진폭 안전 상한 (normalized)
DORI_SHAKE_S = (0.15, 3.0)                # 한쪽 시간 안전 범위(초): 아래는 속도 상한, 위는 경로 길이 상한
DORI_MAX_SHAKES = 10
DORI_DEFAULTS = {"joint": "shoulder_pan", "amplitude": 15, "shakes": 2, "shake_s": 0.35}
BODY_JOINTS = JOINTS[:GRIPPER]            # 그리퍼를 뺀 몸통 관절 5개


def _ms(t0):
    return int((time.monotonic() - t0) * 1000)


def _finite(value, what):
    """숫자(bool 제외)이고 유한하면 float, 아니면 SystemExit."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SystemExit(f"config.yaml skills.dori_dori.script.{what}는 유한한 숫자여야 해요: {value!r}")
    return float(value)


def dori_settings(conf):
    """skills.dori_dori.script → {joint(관절 번호), amplitude, shakes, shake_s}.
    잘못된 값은 시작할 때 SystemExit. 진폭(<=30), 한쪽 시간(0.15~3초), 횟수(1~10)는 안전 범위로 자른다 (경고)."""
    if conf is not None and not isinstance(conf, dict):
        raise SystemExit(f"config.yaml skills.dori_dori.script는 {{joint, amplitude, shakes, shake_s}} 형태여야 해요: {conf!r}")
    s = {**DORI_DEFAULTS, **(conf or {})}
    if s["joint"] not in BODY_JOINTS:
        raise SystemExit(f"config.yaml skills.dori_dori.script.joint는 {', '.join(BODY_JOINTS)} 중 하나예요: {s['joint']!r}")
    amplitude, shake_s = _finite(s["amplitude"], "amplitude"), _finite(s["shake_s"], "shake_s")
    shakes = s["shakes"]
    if isinstance(shakes, bool) or not isinstance(shakes, int):
        raise SystemExit(f"config.yaml skills.dori_dori.script.shakes는 정수여야 해요: {shakes!r}")
    if amplitude <= 0 or shakes < 1 or shake_s <= 0:
        raise SystemExit("config.yaml skills.dori_dori.script: amplitude > 0, shakes >= 1, shake_s > 0 이어야 해요")
    if amplitude > DORI_MAX_AMPLITUDE:
        log.warning("코드 도리도리 진폭 %.1f → %.0f로 자름 (안전 상한)", amplitude, DORI_MAX_AMPLITUDE)
        amplitude = DORI_MAX_AMPLITUDE
    if not DORI_SHAKE_S[0] <= shake_s <= DORI_SHAKE_S[1]:
        clamped = min(max(shake_s, DORI_SHAKE_S[0]), DORI_SHAKE_S[1])
        log.warning("코드 도리도리 shake_s %.2f → %.2f초로 자름 (안전 범위 %.2f~%.0f)", shake_s, clamped, *DORI_SHAKE_S)
        shake_s = clamped
    if shakes > DORI_MAX_SHAKES:
        log.warning("코드 도리도리 shakes %d → %d로 자름 (안전 상한)", shakes, DORI_MAX_SHAKES)
        shakes = DORI_MAX_SHAKES
    return {"joint": BODY_JOINTS.index(s["joint"]), "amplitude": amplitude, "shakes": shakes, "shake_s": shake_s}


def dori_source_setting(sk):
    """skills.dori_dori.source (auto | policy | script). 모델을 로드하기 전에 값과 script 설정을 검사한다."""
    dori = sk.get("dori_dori") or {}
    source = dori.get("source") or "auto"
    if source not in DORI_SOURCES:
        raise SystemExit(f"config.yaml skills.dori_dori.source는 auto | policy | script 중 하나예요: {source}")
    if source != "policy":
        dori_settings(dori.get("script"))
    return source


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


def load_so101():
    """physicalai 0.3.0 본체의 SO101 (Studio 백엔드와 같은 경로). 없으면 플러그인 패키지."""
    try:
        from physicalai.robot.so101 import SO101
    except ImportError:
        from physicalai_so101_plugin import SO101
    return SO101


def build_runtime(cfg, action_source, tap):
    from snackbot.wincam import patch_camera_query
    patch_camera_query()   # Windows 카메라 목록 JSON 버그 보정 (UVCCamera 열기 전)
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
    dori_source = dori_source_setting(sk)   # 잘못된 설정이면 모델을 로드하기 전에 끝낸다
    if dori_source == "policy" and not Path(sk["dori_dori"]["export_dir"]).is_dir():
        # 어떤 모델도 로드하기 전에 끝낸다 (oranda GPU 컴파일을 기다리지 않게)
        raise SystemExit("skills.dori_dori.source가 policy인데 dori_dori 모델이 없어요: export_dir 폴더를 확인하거나 "
                         "source를 auto(모델이 없으면 코드 도리도리) 또는 script로 바꾸세요.")
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
    def __init__(self, cfg, poses, make_runtime=None, policies=None, models=None, recorder=None):
        sk = cfg["skills"]
        missing = [k for k in ("home_pose", "lift_pose") if k not in poses]
        if missing:
            raise SystemExit(f"{', '.join(missing)} 없음: python -m tools.robot_probe save home / save lift 로 먼저 저장하세요.")
        if policies is None:
            policies, models = build_policies(cfg)
        policies, models = dict(policies), dict(models or {})
        dori_cfg = sk.get("dori_dori") or {}
        source = dori_source_setting(sk)
        if source == "policy" and "dori_dori" not in policies:
            raise SystemExit("skills.dori_dori.source가 policy인데 dori_dori 모델이 없어요: export_dir 폴더를 확인하거나 "
                             "source를 auto(모델이 없으면 코드 도리도리) 또는 script로 바꾸세요.")
        self.dori_source = "policy" if source != "script" and "dori_dori" in policies else "script"
        self.dori_script = dori_settings(dori_cfg.get("script"))   # dori_script 테스트 때문에 source와 무관하게 항상 검사
        self.dori = None
        if self.dori_source == "script":   # run("dori_dori")만 코드 동작이다: 모델이 있으면 로드·warmup해서 "모델 도리도리" 버튼에 쓴다
            self.dori = self.dori_script
            log.info("dori_dori: 코드 도리도리 (%s ±%.0f, %d번, 한쪽 %.2f초)", BODY_JOINTS[self.dori["joint"]],
                     self.dori["amplitude"], self.dori["shakes"], self.dori["shake_s"])
        self.policies, self.models = policies, models
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
        self.recorder = recorder if recorder is not None else RunRecorder(cfg)
        self.runtime = (make_runtime or (lambda s, t: build_runtime(cfg, s, t)))(self.switch, self.tap)
        self.tray = 0
        self._estop = threading.Event()
        self._estop_gen = 0
        self._gen_lock = threading.Lock()
        self._io = threading.Lock()
        self._cam_failed = set()

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
        with self.tap.lock:   # 3D 화면이 첫 틱 전에도 지금 자세를 그리도록
            self.tap.joints = np.asarray(obs.joint_positions, np.float32).copy()
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
            except Exception as e:   # 차원·해상도 불일치 등
                raise SystemExit(f"정책 {name} 첫 추론이 실패했어요: {type(e).__name__}: {str(e)[:200]} — "
                                 "state 차원, 카메라 해상도, export_dir 확인") from e
            model.reset()
            log.info("%s warmup 완료: chunk %s", name, getattr(chunk, "shape", "?"))

    def new_task(self, n):
        pass

    def run(self, name, on_phase=None):
        if name not in POLICIES and name not in (SCRIPT_DORI, POLICY_DORI):
            raise ValueError(f"알 수 없는 스킬: {name}")
        if name == POLICY_DORI and "dori_dori" not in self.policies:
            raise RuntimeError("도리도리 모델이 로드되지 않았어요 (config.yaml skills.dori_dori.export_dir 폴더 확인)")
        if (name in POLICIES and name not in self.policies
                and not (name == "dori_dori" and self.dori_source == "script")):
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

    def _run(self, name, on_phase):
        t0 = time.monotonic()
        gen = self._current_gen()
        if self.ensure_home(gen) == "estop":
            return RunResult("estop", False, _ms(t0))
        if name == SCRIPT_DORI or (name == "dori_dori" and self.dori_source == "script"):
            if self._script_dori(gen) == "estop":
                return RunResult("estop", False, _ms(t0))
            return RunResult("script", False, _ms(t0))
        if name == "oranda_pickup":
            self.watch.reset()
            self.tap.watch = self.watch
            try:
                reason = self._policy(name, gen, done=self.watch.done)
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
        if self._policy("dori_dori", gen) == "estop":   # dori_dori 또는 dori_policy (source와 무관하게 모델)
            return RunResult("estop", False, _ms(t0))
        if self._move([self.home], gen) == "estop":
            return RunResult("estop", False, _ms(t0))
        return RunResult("timeout", False, _ms(t0))

    def _policy(self, name, gen, done=None):
        """정책 phase 하나. 이 구간만 실행 기록에 남긴다 (보간 이동은 제외)."""
        self.recorder.start(name)
        self.tap.recorder = self.recorder
        try:
            return self._phase(self.policies[name], self.max_time[name], gen, done=done,
                               camera_map=self.camera_maps[name])
        finally:
            self.tap.recorder = None

    def _script_dori(self, gen):
        """코드 도리도리: 홈에서 한 관절만 ±amplitude를 shakes번 오간 뒤 홈 (끝 키프레임이 홈이라 도착만 확인한다).
        정책 phase처럼 실행 기록에 남긴다. 결과: done | estop."""
        d = self.dori_script
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

    def latest_joints(self):
        """3D 화면용 최근 관절값 (normalized 6개 list). 연결 전이면 None. 제어 스레드를 막지 않게 Tap 캐시만 복사한다."""
        with self.tap.lock:
            joints = self.tap.joints
            return None if joints is None else joints.tolist()

    def ensure_home(self, gen=None):
        gen = self._current_gen() if gen is None else gen
        with self._io:
            current = np.asarray(self.runtime.robot.get_observation().joint_positions, np.float32)
        if np.max(np.abs(current - self.home)) <= self.home_tolerance:
            return "done"
        return self._move([self.home], gen)

    def go_home(self):
        return self._move([self.home], self._current_gen())

    def _move(self, targets, gen, segment_s=None):
        """targets를 차례로 선형 보간 이동. 구간마다 segment_s초 (기본 skills.move_s)."""
        seg = self.move_s if segment_s is None else float(segment_s)
        src = MoveSource(targets, seg * self.fps)
        result = self._phase(src, len(targets) * seg + 2.0, gen, done=src.done)
        if result == "done" and self._settle(targets[-1], gen) == "estop":
            return "estop"
        return result

    def _settle(self, target, gen):
        """명령을 다 보낸 뒤 실제로 도착했는지 본다 (서보가 따라가는 중이면 최대 1초 기다리고, 그래도 멀면 경고)."""
        aborted, deadline = _Aborted(self, gen), time.monotonic() + 1.0
        while True:
            with self._io:
                current = np.asarray(self.runtime.robot.get_observation().joint_positions, np.float32)
            err = float(np.max(np.abs(current - np.asarray(target, np.float32))))
            if err <= self.home_tolerance:
                return "done"
            if aborted.is_set():
                return "estop"
            if time.monotonic() >= deadline:
                log.warning("이동 뒤에도 목표에서 %.1f 벗어나 있어요 (허용 %.1f): 걸렸는지 확인하세요",
                            err, self.home_tolerance)
                return "done"
            time.sleep(0.1)

    def _phase(self, source, duration_s, gen, done=None, camera_map=None):
        """동작 출처 하나로 run() 한 번. 결과: done | timeout | estop."""
        aborted = _Aborted(self, gen)
        if aborted.is_set():
            return "estop"
        with self._io:   # 동작 출처 교체도 락 안: 이전 run이 끝나(shutdown의 disconnect) 기 전에는 바꾸지 않는다
            if aborted.is_set():
                return "estop"
            self.switch.active, self.switch.camera_map = source, camera_map
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
                self._cam_failed.discard(cam)
            except Exception as e:
                if cam not in self._cam_failed:   # 상태가 바뀔 때 한 번만 (스트림 주기마다 찍지 않는다)
                    self._cam_failed.add(cam)
                    log.warning("카메라 %s 읽기 실패: %s", cam, e)
                else:
                    log.debug("카메라 %s 읽기 실패: %s", cam, e)
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
        self.recorder.wait(5)   # 마지막 실행 기록을 마저 쓴다


def main(argv=None):
    import argparse

    from .config import load_config, load_poses

    p = argparse.ArgumentParser(prog="python -m snackbot.robot", description="스킬 하나만 실행 (현장 점검용)")
    p.add_argument("skill", choices=[*POLICIES, POLICY_DORI, SCRIPT_DORI, "home"])
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
