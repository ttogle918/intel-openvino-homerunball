"""행동 계층의 로봇 없는 구현 DrySkills (sleep). 실제 로봇은 snackbot/robot.py RobotSkills, 같은 인터페이스:
  tray · new_task(n) · run(name, on_phase=None) -> RunResult · go_home()
  estop() · release_estop() · latest_frame(cam) -> RGB uint8 HxWx3 · close()
녹화 재생 데이터(replays/<스킬>/episode.json)가 있으면 그 스킬의 동작 시간은 에피소드 길이다
(화면이 phase acting 순간 같은 에피소드를 재생하므로 영상과 단계 표시가 함께 끝난다).
"""
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .twin import episode_duration, load_episode

SNACK_RGB = (200, 120, 40)     # 황갈색 (OpenCV counter 기본 HSV 범위 안)
OTHER_RGB = (180, 180, 180)    # 다른 과자 (채도가 낮아 세지 않음)
REPLAY_SKILLS = ("oranda_pickup", "dori_dori")


@dataclass
class RunResult:
    stop_reason: str   # gripper_open | timeout | estop | script(코드 도리도리)
    grasped: bool
    ms: int
    record: str | None = None   # 실행 기록 폴더 (실제 로봇에서 기록했을 때만, posix 경로)


def _ms(t0):
    return int((time.monotonic() - t0) * 1000)


def synth_tray(n):
    img = np.full((480, 640, 3), 235, np.uint8)
    cv2.rectangle(img, (60, 120), (580, 420), (120, 120, 120), 3)
    for i in range(n):
        cv2.circle(img, (130 + (i % 5) * 95, 200 + (i // 5) * 100), 28, SNACK_RGB, -1)
    cv2.circle(img, (610, 450), 20, OTHER_RGB, -1)
    cv2.putText(img, f"DRY-RUN  tray={n}", (60, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (60, 60, 60), 2)
    return img


def synth_view(name):
    """vision 카메라가 아닌 config 카메라의 dry-run 화면 (이름표)."""
    img = np.full((480, 640, 3), 52, np.uint8)
    cv2.putText(img, "DRY-RUN", (40, 200), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (200, 200, 200), 3)
    label = str(name).encode("ascii", "replace").decode()
    cv2.putText(img, label, (40, 290), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (240, 170, 60), 3)
    return img


class DrySkills:
    """로봇 없이 시간만 보낸다. 가짜 트레이(tray)의 개수를 관리한다."""

    def __init__(self, cfg, rng=None):
        dry = cfg["dry_run"]
        self.act_s = float(dry.get("act_s", 1.0))
        self.fail_rate = float(dry.get("fail_rate", 0.0))
        self.samples = Path(dry.get("samples_dir", "tests/samples"))
        self.rng = rng or random.Random(dry.get("seed"))
        self.tray = cfg["target"]["initial_count"]
        self.camera = (cfg.get("vision") or {}).get("camera", "front")
        self.cameras = set(cfg.get("cameras") or {})
        self._estop = threading.Event()
        self._cache = {}
        replays = Path(cfg.get("replays_dir", "replays"))
        self.replay_s = {}
        for name in REPLAY_SKILLS:
            ep = load_episode(replays / name)
            if ep is not None:
                self.replay_s[name] = episode_duration(ep)

    def new_task(self, n):
        self.tray = n

    def run(self, name, on_phase=None):
        t0 = time.monotonic()
        script = name == "dori_script"   # 코드 도리도리: 녹화 재생은 dori_dori의 것을 쓴다
        if not self._wait(self.replay_s.get("dori_dori" if script else name, self.act_s)):
            return RunResult("estop", False, _ms(t0))
        if script:
            return RunResult("script", False, _ms(t0))
        if name != "oranda_pickup":
            return RunResult("timeout", False, _ms(t0))
        grasped = self.tray > 0 and self.rng.random() >= self.fail_rate
        if on_phase:
            on_phase("returning")
        if not self._wait(self.act_s / 2):
            return RunResult("estop", False, _ms(t0))
        if grasped:
            self.tray -= 1
        return RunResult("gripper_open" if grasped else "timeout", grasped, _ms(t0))

    def _wait(self, seconds):
        """비상정지면 False. 0.05초 단위로 확인한다."""
        end = time.monotonic() + seconds
        while True:
            if self._estop.is_set():
                return False
            left = end - time.monotonic()
            if left <= 0:
                return True
            time.sleep(min(0.05, left))

    def go_home(self):
        """홈 복귀 흉내: act_s의 절반을 기다린다 (스킬 테스트 '홈으로'·재시작). 비상정지면 "estop"."""
        return "done" if self._wait(self.act_s / 2) else "estop"

    def estop(self):
        self._estop.set()

    def release_estop(self):
        self._estop.clear()

    def latest_frame(self, cam=None):
        """vision 카메라(또는 cam 없음·모르는 이름)는 트레이 사진, config의 다른 카메라는 이름표 화면."""
        if cam is not None and cam != self.camera and cam in self.cameras:
            if cam not in self._cache:
                self._cache[cam] = synth_view(cam)
            return self._cache[cam]
        path = self.samples / f"tray_{self.tray}.jpg"
        if path.exists():
            if path not in self._cache:
                self._cache[path] = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
            return self._cache[path]
        return synth_tray(self.tray)

    def close(self):
        pass
