import numpy as np

from snackbot.skills import DrySkills, RunResult, synth_tray
from snackbot.vision import OpenCVCounter

OPENCV = dict(min_area=800, max_area=8000, hsv_low=[10, 60, 80], hsv_high=[30, 255, 255])


class SeqRng:
    def __init__(self, *values):
        self.values = list(values)

    def random(self):
        return self.values.pop(0)


def test_pickup_success_reduces_tray(cfg):
    cfg["dry_run"]["fail_rate"] = 0.5
    s = DrySkills(cfg, rng=SeqRng(0.9))
    s.new_task(2)
    phases = []
    r = s.run("oranda_pickup", on_phase=phases.append)
    assert r.grasped and r.stop_reason == "gripper_open"
    assert s.tray == 1 and phases == ["returning"]


def test_pickup_failure_keeps_tray(cfg):
    cfg["dry_run"]["fail_rate"] = 0.5
    s = DrySkills(cfg, rng=SeqRng(0.1))
    s.new_task(2)
    r = s.run("oranda_pickup")
    assert not r.grasped and r.stop_reason == "timeout" and s.tray == 2


def test_empty_tray_never_grasps(cfg):
    s = DrySkills(cfg, rng=SeqRng(0.9))
    s.new_task(0)
    assert not s.run("oranda_pickup").grasped


def test_dori_dori(cfg):
    assert DrySkills(cfg).run("dori_dori") == RunResult("timeout", False, 0)


def test_estop_interrupts_and_release(cfg):
    cfg["dry_run"]["act_s"] = 0.5
    s = DrySkills(cfg)
    s.estop()
    assert s.run("oranda_pickup").stop_reason == "estop"
    s.release_estop()
    s.act_s = 0
    assert s.run("dori_dori").stop_reason == "timeout"


def test_frame_is_synthetic_and_countable(cfg):
    s = DrySkills(cfg)
    s.new_task(3)
    f = s.latest_frame("front")
    assert f.shape == (480, 640, 3) and f.dtype == np.uint8
    assert OpenCVCounter(**OPENCV).count(f).n == 3
    assert OpenCVCounter(**OPENCV).count(synth_tray(0)).n == 0
