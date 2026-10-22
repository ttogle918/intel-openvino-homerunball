import json
import threading
import time

from conftest import FirstRng
from snackbot.brain import Brain
from snackbot.controller import Controller
from snackbot.skills import RunResult
from snackbot.vision import Count


class FakeSkills:
    def __init__(self, grasps=()):
        self.grasps, self.runs = list(grasps), []
        self.estopped, self.homed, self.tray = False, 0, None

    def new_task(self, n):
        self.tray = n

    def run(self, name, on_phase=None):
        self.runs.append(name)
        if self.estopped:
            return RunResult("estop", False, 1)
        if name == "dori_dori":
            return RunResult("timeout", False, 1)
        grasped = self.grasps.pop(0) if self.grasps else True
        if on_phase:
            on_phase("returning")
        return RunResult("gripper_open" if grasped else "timeout", grasped, 1)

    def latest_frame(self, cam=None):
        return None

    def estop(self):
        self.estopped = True

    def release_estop(self):
        self.estopped = False

    def go_home(self):
        self.homed += 1

    def close(self):
        pass


class FakeVision:
    enabled = True

    def __init__(self, *counts):
        self.counts = list(counts)

    def count(self, frame):
        return self.counts.pop(0) if self.counts else None


def make(cfg, skills=None, vision=None, log_dir=None):
    c = Controller(cfg, Brain(cfg, rng=FirstRng()), skills or FakeSkills(), vision=vision, log_dir=log_dir)
    events = []
    c.subscribe(events.append)
    return c, events


def test_snapshot_shape(cfg):
    c, _ = make(cfg)
    assert c.snapshot() == {"type": "state", "state": "IDLE", "phase": "idle", "count": 0, "remaining": 0,
                            "skill": None, "vision_method": "estimate",
                            "thresholds": {"safe_max": 3, "force_refuse": 6}}


def test_chat_starts_task_with_count(cfg):
    c, ev = make(cfg)
    c.chat("오란다 3개 옮겨줘")
    assert (c.state, c.remaining, c.count) == ("WORKING", 3, 0)
    assert [e["role"] for e in ev if e["type"] == "message"] == ["user", "robot"]
    assert c.skills.tray == 3


def test_command_start_uses_initial_count(cfg):
    c, ev = make(cfg)
    c.command("start")
    assert c.state == "WORKING" and c.remaining == cfg["target"]["initial_count"]
    assert [e["role"] for e in ev if e["type"] == "message"] == ["robot"]


def test_b_mode_full_run_to_done_then_idle(cfg):
    c, ev = make(cfg)
    c.chat("2개 옮겨줘")
    assert [c.step(), c.step(), c.step()] == ["success", "success", "done"]
    assert (c.state, c.count, c.remaining) == ("IDLE", 2, 0)
    states = [e["state"] for e in ev if e["type"] == "state"]
    assert "DONE" in states and states[-1] == "IDLE"
    assert c.step() is None


def test_refuses_at_force_refuse_and_chat_resume_resets(cfg):
    c, _ = make(cfg)
    c.chat("10개 옮겨줘")
    assert [c.step() for _ in range(7)] == ["success"] * 6 + ["refuse"]
    assert c.state == "REFUSING" and c.skills.runs[-1] == "dori_dori"
    assert c.step() is None
    c.chat("조금만 더 해줘")
    assert c.state == "WORKING" and c.count == 0


def test_command_resume_from_refusing(cfg):
    c, ev = make(cfg)
    c.chat("10개 옮겨줘")
    for _ in range(7):
        c.step()
    c.command("resume")
    assert c.state == "WORKING" and c.count == 0
    assert [e for e in ev if e["type"] == "message"][-1]["text"] == "알겠어요… 조금만 더 할게요."


def test_failures_then_waiting_operator(cfg):
    c, ev = make(cfg, FakeSkills(grasps=[False] * 3))
    c.chat("2개 옮겨줘")
    assert [c.step(), c.step(), c.step()] == ["fail", "fail", "fail"]
    assert (c.phase, c.count, c.remaining) == ("waiting_operator", 0, 2)
    assert [e for e in ev if e["type"] == "message"][-1]["role"] == "system"
    assert c.step() is None
    c.command("resume")
    assert c.phase == "idle" and c.retries == 0
    assert c.step() == "success"


def test_estop_and_restart(cfg):
    c, _ = make(cfg)
    c.chat("2개 옮겨줘")
    c.command("estop")
    assert c.state == "ESTOP" and c.skills.estopped and c.step() is None
    c.chat("과자 옮겨줘")
    assert c.state == "ESTOP"
    c.command("restart")
    assert c.state == "IDLE" and not c.skills.estopped and c.skills.homed == 1


def test_a_mode_success_by_count_decrease(cfg):
    c, _ = make(cfg, FakeSkills(grasps=[False]), vision=FakeVision(Count(3, "opencv"), Count(2, "opencv")))
    c.chat("과자 옮겨줘")
    assert c.step() == "success"
    assert (c.remaining, c.count, c.vision_method) == (2, 1, "opencv")


def test_a_mode_no_decrease_is_fail(cfg):
    c, _ = make(cfg, FakeSkills(grasps=[True]), vision=FakeVision(Count(3, "opencv"), Count(3, "opencv")))
    c.chat("과자 옮겨줘")
    assert c.step() == "fail" and c.count == 0


def test_a_mode_counter_failure_falls_back_to_b(cfg):
    c, _ = make(cfg, FakeSkills(grasps=[True]), vision=FakeVision())
    c.chat("2개 옮겨줘")
    assert c.step() == "success"
    assert (c.remaining, c.vision_method) == (1, "estimate")


def test_a_mode_zero_count_means_done(cfg):
    c, _ = make(cfg, vision=FakeVision(Count(0, "opencv")))
    c.chat("과자 옮겨줘")
    assert c.step() == "done" and c.state == "IDLE"


def test_cycle_events_and_jsonl_log(cfg, tmp_path):
    c, ev = make(cfg, log_dir=tmp_path)
    c.chat("1개 옮겨줘")
    c.step()
    cycle = [e for e in ev if e["type"] == "cycle"][0]
    assert cycle["n"] == 1 and cycle["result"] == "success" and {"llm", "act"} <= set(cycle["ms"])
    lines = next(tmp_path.glob("cycles-*.jsonl")).read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    assert record["result"] == "success" and record["skill"] == "oranda_pickup" and record["grasped"] is True


def test_history_keeps_last_50(cfg):
    c, _ = make(cfg)
    for i in range(30):
        c.chat(f"안녕 {i}")
    assert len(c.history) == 50 and c.history[-1]["role"] == "robot"


def test_background_thread_runs_to_done(cfg):
    c, ev = make(cfg)
    c.start()
    try:
        c.chat("2개 옮겨줘")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not any(
                e["type"] == "state" and e["state"] == "IDLE" and e["count"] == 2 for e in list(ev)):
            time.sleep(0.01)
        assert c.state == "IDLE" and c.count == 2
    finally:
        c.stop()
    assert c.stopped


class EstopDuringRun(FakeSkills):
    ctrl = None

    def run(self, name, on_phase=None):
        self.runs.append(name)
        self.ctrl.command("estop")
        return RunResult("timeout", False, 1)


class EstopReason(FakeSkills):
    def run(self, name, on_phase=None):
        self.runs.append(name)
        return RunResult("estop", False, 1)


def test_estop_during_dori_dori_is_not_overwritten(cfg):
    sk = EstopDuringRun()
    c, _ = make(cfg, sk)
    sk.ctrl = c
    c.chat("10개 옮겨줘")
    c.count = cfg["decision"]["force_refuse"]
    assert c.step() == "estop"
    assert sk.runs[-1] == "dori_dori"
    assert c.state == "ESTOP" and sk.estopped
    assert c.step() is None
    c.command("restart")
    assert c.state == "IDLE"


def test_estop_during_pickup_is_not_overwritten(cfg):
    sk = EstopDuringRun()
    c, _ = make(cfg, sk)
    sk.ctrl = c
    c.chat("3개 옮겨줘")
    assert c.step() == "estop"
    assert c.state == "ESTOP" and c.count == 0 and sk.estopped


def test_skill_estop_result_latches_estop(cfg):
    c, _ = make(cfg, EstopReason())
    c.chat("3개 옮겨줘")
    assert c.step() == "estop"
    assert c.state == "ESTOP"
    assert c.step() is None


def test_estop_during_restart_homing_is_kept(cfg):
    class HomeEstop(FakeSkills):
        ctrl = None

        def go_home(self):
            self.ctrl.command("estop")

    sk = HomeEstop()
    c, _ = make(cfg, sk)
    sk.ctrl = c
    c.chat("2개 옮겨줘")
    c.command("estop")
    c.command("restart")
    assert c.state == "ESTOP" and sk.estopped
    sk.go_home = lambda: None
    c.command("restart")
    assert c.state == "IDLE"


def test_loop_exception_goes_to_waiting_operator(cfg):
    class Boom:
        def decide(self, *a, **k):
            raise RuntimeError("boom")

        def line(self, kind):
            return kind

    c = Controller(cfg, Boom(), FakeSkills())
    c.start()
    try:
        c.command("start")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and c.phase != "waiting_operator":
            time.sleep(0.01)
        assert c.phase == "waiting_operator"
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not (c.history and c.history[-1]["role"] == "system"):
            time.sleep(0.01)
        assert c.history[-1]["role"] == "system"
    finally:
        c.stop()


def test_estop_during_release_estop_stays_latched(cfg):
    class SlowRelease(FakeSkills):
        def __init__(self):
            super().__init__()
            self.home_latched = []

        def release_estop(self):
            time.sleep(0.2)
            self.estopped = False

        def go_home(self):
            self.home_latched.append(self.estopped)
            super().go_home()

    sk = SlowRelease()
    c, _ = make(cfg, sk)
    c.chat("2개 옮겨줘")
    c.command("estop")
    t = threading.Thread(target=lambda: c.command("restart"))
    t.start()
    time.sleep(0.05)
    c.command("estop")
    t.join(timeout=5)
    assert c.state == "ESTOP" and sk.estopped
    assert all(sk.home_latched)  # go_home이 불렸다면 정지된 채여야 한다


def test_estop_interrupted_cycles_are_logged_once(cfg, tmp_path):
    sk = EstopDuringRun()
    c, _ = make(cfg, sk, log_dir=tmp_path)
    sk.ctrl = c
    c.chat("3개 옮겨줘")
    assert c.step() == "estop"
    c.command("restart")
    c.chat("10개 옮겨줘")
    c.count = cfg["decision"]["force_refuse"]
    assert c.step() == "estop"
    lines = next(tmp_path.glob("cycles-*.jsonl")).read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["result"] for x in lines] == ["estop", "estop"]


def test_cycle_ms_splits_act_and_return(cfg):
    c, ev = make(cfg)
    c.chat("1개 옮겨줘")
    c.step()
    ms = [e for e in ev if e["type"] == "cycle"][-1]["ms"]
    assert "return" in ms and "act" in ms and ms["act"] >= 0 and ms["return"] >= 0


def test_cycle_ms_split_reflects_real_phases(cfg):
    class Timed(FakeSkills):
        def run(self, name, on_phase=None):
            time.sleep(0.05)
            on_phase("returning")
            time.sleep(0.10)
            return RunResult("gripper_open", True, 1)

    c, ev = make(cfg, Timed())
    c.chat("1개 옮겨줘")
    c.step()
    ms = [e for e in ev if e["type"] == "cycle"][-1]["ms"]
    assert 40 <= ms["act"] <= 150 and 80 <= ms["return"] <= 250


def test_cycle_ms_without_returning_has_no_return(cfg):
    c, ev = make(cfg)
    c.chat("4개 옮겨줘")
    c.count = cfg["decision"]["force_refuse"]       # dori_dori 는 returning 단계가 없다
    c.step()
    ms = [e for e in ev if e["type"] == "cycle"][-1]["ms"]
    assert "act" in ms and "return" not in ms


def test_loop_exception_after_estop_keeps_phase(cfg):
    holder = {}

    class Boom:
        def decide(self, *a, **k):
            holder["c"].command("estop")
            raise RuntimeError("boom")

        def line(self, kind):
            return kind

    c = Controller(cfg, Boom(), FakeSkills())
    holder["c"] = c
    c.command("start")
    c.start()
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not any(
                m["role"] == "system" and "오류" in m["text"] for m in c.history):
            time.sleep(0.01)
        assert c.state == "ESTOP" and c.phase == "idle"
    finally:
        c.stop()


def test_stop_estops_skills_even_when_not_working(cfg):
    c, _ = make(cfg)
    c.command("start")
    c.command("estop")
    c.skills.estopped = False
    c.stop()
    assert c.skills.estopped
    c2, _ = make(cfg)
    c2.stop()
    assert not c2.skills.estopped       # IDLE 이면 건드리지 않는다


def test_loop_exception_in_estop_hints_restart(cfg):
    holder = {}

    class Boom:
        def decide(self, *a, **k):
            holder["c"].command("estop")
            raise RuntimeError("boom")

        def line(self, kind):
            return kind

    c = Controller(cfg, Boom(), FakeSkills())
    holder["c"] = c
    c.command("start")
    c.start()
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not any(
                m["role"] == "system" and "오류" in m["text"] for m in c.history):
            time.sleep(0.01)
        texts = [m["text"] for m in c.history if "오류" in m["text"]]
        assert texts and "재시작" in texts[-1] and "재개" not in texts[-1]
    finally:
        c.stop()
