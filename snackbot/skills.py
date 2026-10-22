"""행동 계층. 이번 계획에는 DrySkills(로봇 없이 sleep)만 있다.
실제 로봇(physicalai)은 다음 계획(M4)에서 같은 인터페이스로 추가한다:
  tray · new_task(n) · run(name, on_phase=None) -> RunResult · go_home()
  estop() · release_estop() · latest_frame(cam) -> RGB uint8 HxWx3 · close()
"""
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

SNACK_RGB = (200, 120, 40)     # 황갈색 (OpenCV counter 기본 HSV 범위 안)
OTHER_RGB = (180, 180, 180)    # 다른 과자 (채도가 낮아 세지 않음)


@dataclass
class RunResult:
    stop_reason: str   # gripper_open | timeout | estop
    grasped: bool
    ms: int


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


class DrySkills:
    """로봇 없이 시간만 보낸다. 가짜 트레이(tray)의 개수를 관리한다."""

    def __init__(self, cfg, rng=None):
        dry = cfg["dry_run"]
        self.act_s = float(dry.get("act_s", 1.0))
        self.fail_rate = float(dry.get("fail_rate", 0.0))
        self.samples = Path(dry.get("samples_dir", "tests/samples"))
        self.rng = rng or random.Random(dry.get("seed"))
        self.tray = cfg["target"]["initial_count"]
        self._estop = threading.Event()
        self._cache = {}

    def new_task(self, n):
        self.tray = n

    def run(self, name, on_phase=None):
        t0 = time.monotonic()
        if not self._wait(self.act_s):
            return RunResult("estop", False, _ms(t0))
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
        pass

    def estop(self):
        self._estop.set()

    def release_estop(self):
        self._estop.clear()

    def latest_frame(self, cam=None):
        path = self.samples / f"tray_{self.tray}.jpg"
        if path.exists():
            if path not in self._cache:
                self._cache[path] = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
            return self._cache[path]
        return synth_tray(self.tray)

    def close(self):
        pass
