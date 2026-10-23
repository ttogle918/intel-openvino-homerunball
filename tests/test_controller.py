import json
import threading
import time

import pytest

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

    def __init__(self, *counts, names=("opencv",)):
        self.counts, self.names, self.only = list(counts), list(names), []

    def count(self, frame, only=None):
        self.only.append(only)
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
                            "vision_choice": "off", "vision_options": [], "last_count": None,
                            "total": 0, "refuse_at": None,
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
    cfg["decision"]["refuse"] = "fixed"
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
    cfg["decision"]["refuse"] = "fixed"
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
    cfg["decision"]["refuse"] = "fixed"
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


class RecordingBrain(Brain):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.chat_hist, self.decide_hist = [], []

    def chat(self, text, state, count, history=None):
        self.chat_hist.append(history)
        return super().chat(text, state, count, history=history)

    def decide(self, remaining, count, state, speech_text=None, history=None, **kw):
        self.decide_hist.append(history)
        return super().decide(remaining, count, state, speech_text, history=history, **kw)


def test_controller_passes_history_and_restart_clears_it(cfg):
    c = Controller(cfg, RecordingBrain(cfg, rng=FirstRng()), FakeSkills())
    c.chat("안녕")
    c.chat("2개 옮겨줘")
    first, second = c.brain.chat_hist
    assert first == []  # 현재 발화는 포함하지 않는다
    assert [m["text"] for m in second if m["role"] == "user"] == ["안녕"]
    c.step()
    assert any(m["role"] == "user" and m["text"] == "2개 옮겨줘" for m in c.brain.decide_hist[-1])
    c.command("estop")
    assert len(c.history) > 0
    c.command("restart")
    assert [m["role"] for m in c.history] == ["system"]  # 재시작 안내만 남는다
    assert c.state == "IDLE"


class EventVoice:
    """speak가 호출마다 Event를 돌려주는 가짜 voice. 테스트가 직접 set 한다."""

    def __init__(self):
        self.events, self.spoken = [], []

    def speak(self, text):
        ev = threading.Event()
        self.events.append(ev)
        self.spoken.append(text)
        return ev

    def clear_pending(self):
        self.cleared = getattr(self, "cleared", 0) + 1


def _make_voiced(cfg, voice, timeout=8):
    cfg["voice"]["sync_timeout_s"] = timeout
    c = Controller(cfg, Brain(cfg, rng=FirstRng()), FakeSkills(), voice=voice)
    c.state, c.phase, c.remaining = "WORKING", "idle", 3
    return c


def _step_in_thread(c):
    out = []
    t = threading.Thread(target=lambda: out.append(c.step()), daemon=True)
    t.start()
    return t, out


def _wait_for(cond, timeout=2):
    end = time.monotonic() + timeout
    while time.monotonic() < end and not cond():
        time.sleep(0.01)
    return cond()


def test_skill_waits_until_speech_starts(cfg):
    v = EventVoice()
    c = _make_voiced(cfg, v)
    t, out = _step_in_thread(c)
    assert _wait_for(lambda: c.phase == "speaking")
    time.sleep(0.3)
    assert c.skills.runs == []
    v.events[0].set()
    t.join(3)
    assert c.skills.runs == ["oranda_pickup"] and out == ["success"]


def test_already_set_event_does_not_wait(cfg):
    class Instant(EventVoice):
        def speak(self, text):
            ev = super().speak(text)
            ev.set()
            return ev

    c = _make_voiced(cfg, Instant())
    t0 = time.monotonic()
    assert c.step() == "success"
    assert time.monotonic() - t0 < 1


def test_speech_wait_timeout_proceeds_and_logs_ms(cfg, tmp_path):
    c = _make_voiced(cfg, EventVoice(), timeout=0.3)
    c.log_path = tmp_path / "c.jsonl"
    assert c.step() == "success"
    assert c.skills.runs == ["oranda_pickup"]
    ms = json.loads(c.log_path.read_text(encoding="utf-8").splitlines()[0])["ms"]
    assert 250 <= ms["speech_wait"] < 2000


def test_estop_while_waiting_for_speech_skips_skill(cfg):
    v = EventVoice()
    c = _make_voiced(cfg, v)
    t, out = _step_in_thread(c)
    assert _wait_for(lambda: c.phase == "speaking")
    c.command("estop")
    t.join(3)
    assert not t.is_alive()
    assert out == [None] and c.skills.runs == [] and c.state == "ESTOP"


def test_stop_while_waiting_for_speech_skips_skill(cfg):
    v = EventVoice()
    c = _make_voiced(cfg, v)
    t, out = _step_in_thread(c)
    assert _wait_for(lambda: c.phase == "speaking")
    c._stop.set()
    t.join(3)
    assert not t.is_alive() and c.skills.runs == []


def test_done_skill_does_not_wait_for_speech(cfg):
    v = EventVoice()
    c = _make_voiced(cfg, v)
    c.remaining = 0
    t0 = time.monotonic()
    assert c.step() == "done"
    assert time.monotonic() - t0 < 1


def test_no_voice_or_none_event_does_not_wait(cfg):
    c = _make_voiced(cfg, None)
    assert c.step() == "success"

    class NoneVoice:
        def speak(self, text):
            return None

    c = _make_voiced(cfg, NoneVoice())
    assert c.step() == "success"


def test_other_robot_messages_do_not_wait(cfg):
    v = EventVoice()
    cfg["voice"]["sync_timeout_s"] = 8
    c = Controller(cfg, Brain(cfg, rng=FirstRng()), FakeSkills(), voice=v)
    t0 = time.monotonic()
    c.command("start")  # IDLE: 안내 대사를 내지만 기다리지 않는다
    assert len(v.spoken) == 1
    c.state, c.phase = "REFUSING", "idle"
    c.command("resume")
    assert len(v.spoken) == 2
    assert time.monotonic() - t0 < 1
    assert c.state == "WORKING" and c.skills.runs == []


def test_estop_restart_start_during_wait_drops_old_decision(cfg):
    v = EventVoice()
    c = _make_voiced(cfg, v)
    t, out = _step_in_thread(c)
    assert _wait_for(lambda: c.phase == "speaking")
    # 폴링 사이에 한꺼번에 일어난 것처럼: 대기 스레드가 중간 상태를 못 보게 락을 잡고 처리한다
    with c._lock:
        c._estop()
        c._restart()
        c._start_task(None)
    t.join(3)
    assert not t.is_alive()
    assert out == [None] and c.skills.runs == []


def test_sync_timeout_null_uses_default(cfg):
    cfg["voice"]["sync_timeout_s"] = None
    c = Controller(cfg, Brain(cfg, rng=FirstRng()), FakeSkills())
    assert c.sync_timeout_s == 10  # config.yaml 기본값과 같다


def test_restart_with_stale_generation_is_rejected_and_estop_stays(cfg):
    c, _ = make(cfg)
    c.command("estop")
    g = c.generation()
    c.command("estop")  # 접수 뒤에 비상정지가 다시 들어왔다: 세션 번호가 올라간다
    c.command("restart", expect_gen=g)
    assert c.state == "ESTOP" and c.phase == "idle"
    assert c.skills.estopped  # 하드웨어 토크 유지/래치도 풀리지 않았다


def test_restart_with_current_generation_and_without_expect_gen_behave_as_before(cfg):
    c, _ = make(cfg)
    c.command("estop")
    c.command("restart", expect_gen=c.generation())
    assert c.state == "IDLE"
    c.command("estop")
    c.command("restart")
    assert c.state == "IDLE"


# --- 세션 번호 확인 보강 ---
def test_stale_done_decision_does_not_finish_new_session(cfg):
    c, _ = make(cfg)
    c.chat("2개 옮겨줘")
    c.remaining = 0  # B모드: 남은 0 -> decide가 done
    orig, fired = c._message, []

    def message(role, text, source=None):
        if role == "robot" and not fired:  # decide 뒤 done 처리 사이에 새 세션이 시작된다
            fired.append(1)
            c._estop()
            c._restart()
            c._start_task(5)
        return orig(role, text, source)

    c._message = message
    assert c.step() is None
    assert c.state == "WORKING" and c.remaining == 5


def test_stale_count_does_not_overwrite_new_session_remaining(cfg):
    class Vis(FakeVision):
        ctrl = None

        def count(self, frame, only=None):
            self.ctrl._estop()
            self.ctrl._restart()
            self.ctrl._start_task(5)
            return Count(0, "yolo")

    vis = Vis()
    c, _ = make(cfg, vision=vis)
    vis.ctrl = c
    c.chat("2개 옮겨줘")
    c.step()
    assert c.remaining == 5 and c.vision_method == "estimate" and c.skills.runs == []


# --- 재시작은 진행 중인 동작이 멈춘 뒤 ---
class BlockingRun(FakeSkills):
    """run()이 entered를 알리고 release 될 때까지 붙잡힌다. release_estop 시점에 run이 끝났는지 기록."""

    def __init__(self):
        super().__init__()
        self.entered, self.release = threading.Event(), threading.Event()
        self.run_done, self.done_at_release = False, None

    def run(self, name, on_phase=None):
        self.runs.append(name)
        self.entered.set()
        self.release.wait(5)
        self.run_done = True
        return RunResult("estop", False, 1)

    def release_estop(self):
        self.done_at_release = self.run_done
        super().release_estop()


def _estop_while_in_run(cfg, sk):
    c, _ = make(cfg, sk)
    c.chat("2개 옮겨줘")
    t = threading.Thread(target=c.step, daemon=True)
    t.start()
    assert sk.entered.wait(2)
    c.command("estop")
    return c, t


def test_restart_waits_for_running_skill_to_finish(cfg):
    sk = BlockingRun()
    c, t = _estop_while_in_run(cfg, sk)
    waiting = threading.Event()
    c._restart_wait_hook = waiting.set
    r = threading.Thread(target=lambda: c.command("restart"), daemon=True)
    r.start()
    assert waiting.wait(5)  # 재시작이 동작 종료를 기다리는 중임을 확인한 뒤에 풀어 준다
    assert sk.done_at_release is None
    sk.release.set()
    r.join(5)
    t.join(5)
    assert not r.is_alive() and not t.is_alive()
    assert sk.done_at_release is True  # 동작이 끝난 뒤에야 토크 해제
    assert c.state == "IDLE"


def test_restart_refused_when_skill_does_not_stop_in_time(cfg):
    sk = BlockingRun()
    c, t = _estop_while_in_run(cfg, sk)
    assert c.state == "ESTOP"  # 비상정지는 run을 기다리지 않고 즉시 처리됐다
    c.restart_wait_s = 0
    c.command("restart")
    assert c.state == "ESTOP" and sk.estopped and sk.done_at_release is None and sk.homed == 0
    assert c.history[-1]["role"] == "system" and "멈추는 중" in c.history[-1]["text"]
    sk.release.set()
    t.join(5)
    assert not t.is_alive()
    c.command("restart")  # 멈춘 뒤에는 된다
    assert c.state == "IDLE"


def test_estop_clears_pending_speech(cfg):
    v = EventVoice()
    c = _make_voiced(cfg, v)
    c.command("estop")
    assert v.cleared == 1


def test_two_overlapping_restarts_release_only_once(cfg):
    sk = BlockingRun()
    c, t = _estop_while_in_run(cfg, sk)
    waiting = threading.Semaphore(0)
    c._restart_wait_hook = waiting.release
    results = []
    rs = [threading.Thread(target=lambda: results.append(c._restart()), daemon=True) for _ in range(2)]
    for r in rs:
        r.start()
    assert waiting.acquire(timeout=5) and waiting.acquire(timeout=5)
    sk.release.set()
    for r in rs + [t]:
        r.join(5)
    assert sorted(results) == [False, True] and sk.homed == 1 and c.state == "IDLE"


def test_restart_after_skill_exception_works(cfg):
    class Boom(FakeSkills):
        def run(self, name, on_phase=None):
            raise RuntimeError("motor")

    c, _ = make(cfg, Boom())
    c.chat("2개 옮겨줘")
    try:
        c.step()
    except RuntimeError:
        pass
    assert c._run_idle.is_set()
    c.command("estop")
    c.command("restart")
    assert c.state == "IDLE"


def test_no_arg_restart_follows_estop_during_wait(cfg):
    sk = BlockingRun()
    c, t = _estop_while_in_run(cfg, sk)
    waiting = threading.Event()
    c._restart_wait_hook = waiting.set
    out = []
    r = threading.Thread(target=lambda: out.append(c._restart()), daemon=True)
    r.start()
    assert waiting.wait(5)
    c.command("estop")  # 대기 중에 비상정지가 다시 들어왔다
    sk.release.set()
    r.join(5)
    t.join(5)
    assert out == [False] and c.state == "ESTOP" and sk.estopped and sk.homed == 0
    assert "재시작이 취소됐어요" in c.history[-1]["text"]


# --- 스킬 1회 실행 (TESTING) ---
def _states(ev):
    return [(e["state"], e["phase"]) for e in ev if e["type"] == "state"]


def test_test_command_only_requests_and_step_test_runs_once(cfg):
    c, ev = make(cfg)
    assert c.command("test", skill="dori_dori") is True
    assert (c.state, c.skill) == ("TESTING", "dori_dori") and c.skills.runs == []   # 명령은 요청만
    assert c.step_test() == "timeout"
    assert (c.state, c.phase, c.skill) == ("IDLE", "idle", None)
    assert c.skills.runs == ["dori_dori"]
    assert c.history[-1]["role"] == "system"
    assert c.history[-1]["text"].startswith("테스트 · 도리도리: 정책 동작 완료 · ")
    assert c.step_test() is None                                  # 대기 중인 테스트 없음
    assert ("TESTING", "acting") in _states(ev) and _states(ev)[-1] == ("IDLE", "idle")


def test_test_oranda_message_has_grasp_and_returning_phase(cfg):
    c, ev = make(cfg)
    c.command("test", skill="oranda_pickup")
    assert c.step_test() == "gripper_open"
    text = c.history[-1]["text"]
    assert text.startswith("테스트 · 오란다: 놓기 감지로 끝남 · 쥠 성공 · ") and text.endswith("초")
    assert ("TESTING", "returning") in _states(ev)


def test_test_home_uses_go_home_without_acting(cfg):
    c, ev = make(cfg)
    c.command("test", skill="home")
    assert c.step_test() == "done"
    assert c.skills.homed == 1 and c.skills.runs == []
    assert c.history[-1]["text"].startswith("테스트 · 홈으로: 완료 · ")
    assert ("TESTING", "returning") in _states(ev) and ("TESTING", "acting") not in _states(ev)


def test_test_message_includes_record_folder(cfg):
    class Recorded(FakeSkills):
        def run(self, name, on_phase=None):
            return RunResult("script", False, 1, record="logs/runs/20261022-120000_dori_dori")

    c, _ = make(cfg, Recorded())
    c.command("test", skill="dori_dori")
    c.step_test()
    text = c.history[-1]["text"]
    assert text.startswith("테스트 · 도리도리: 코드 동작 완료 · ")
    assert text.endswith(" · 기록 logs/runs/20261022-120000_dori_dori")


def test_test_dori_script_runs_once_with_label_and_log(cfg, tmp_path):
    class Script(FakeSkills):
        def run(self, name, on_phase=None):
            self.runs.append(name)
            return RunResult("script", False, 1)

    c, _ = make(cfg, Script(), log_dir=tmp_path)
    assert c.command("test", skill="dori_script") is True
    assert c.step_test() == "script" and c.skills.runs == ["dori_script"]
    assert c.history[-1]["text"].startswith("테스트 · 코드 도리도리: 코드 동작 완료 · ")
    assert c.count == 0 and c.state == "IDLE"
    lines = [json.loads(x) for x in next(tmp_path.glob("cycles-*.jsonl")).read_text(encoding="utf-8").splitlines()]
    assert [(x["type"], x["skill"], x["stop_reason"]) for x in lines] == [("test", "dori_script", "script")]


def test_test_refused_outside_idle_with_reason(cfg):
    c, _ = make(cfg)
    c.chat("2개 옮겨줘")                                           # WORKING
    assert c.command("test", skill="dori_dori") is False
    assert c.state == "WORKING" and "작업 중" in c.history[-1]["text"]
    c.command("estop")
    assert c.command("test", skill="home") is False and "비상정지 중" in c.history[-1]["text"]
    c.command("restart")
    assert c.command("test", skill="dori_dori") is True
    assert c.command("test", skill="home") is False and "이미 테스트 중" in c.history[-1]["text"]
    c2, _ = make(cfg)
    c2.state = "REFUSING"
    assert c2.command("test", skill="dori_dori") is False and "거부 중" in c2.history[-1]["text"]


def test_test_unknown_skill_raises(cfg):
    c, _ = make(cfg)
    with pytest.raises(ValueError):
        c.command("test", skill="dance")
    assert c.state == "IDLE"


def test_start_and_resume_refused_while_testing(cfg):
    c, _ = make(cfg)
    c.command("test", skill="dori_dori")
    c.command("start")
    assert c.state == "TESTING" and c.history[-1]["text"] == "테스트 중이에요. 끝난 뒤 다시 시켜 주세요"
    c.command("resume")
    assert c.state == "TESTING" and c.history[-1]["text"] == "테스트 중이에요. 끝난 뒤 다시 시켜 주세요"
    c.chat("2개 옮겨줘")
    assert c.state == "TESTING" and c.history[-1]["role"] == "robot"   # 채팅은 대답만, 작업 시작 없음
    assert c.history[-1]["text"] == "지금 테스트 중이에요. 끝나면 시켜 주세요!"
    c.step_test()
    assert c.state == "IDLE" and c.count == 0 and c.remaining == 0


def test_test_does_not_touch_counts_or_cycles_and_logs_type_test(cfg, tmp_path):
    c, ev = make(cfg, log_dir=tmp_path)
    c.command("test", skill="oranda_pickup")
    c.step_test()
    assert (c.count, c.remaining, c.retries, c.cycle_n) == (0, 0, 0, 0)
    assert not [e for e in ev if e["type"] == "cycle"]
    rec = json.loads(next(tmp_path.glob("cycles-*.jsonl")).read_text(encoding="utf-8").splitlines()[0])
    assert rec["type"] == "test" and rec["skill"] == "oranda_pickup" and rec["origin"] == "button"
    assert rec["stop_reason"] == "gripper_open" and rec["grasped"] is True and rec["error"] is None
    assert isinstance(rec["ms"], int) and rec["record"] is None


def test_test_skill_exception_reports_and_returns_idle(cfg, caplog, tmp_path):
    class Boom(FakeSkills):
        def run(self, name, on_phase=None):
            raise RuntimeError("motor")

    c, _ = make(cfg, Boom(), log_dir=tmp_path)
    c.command("test", skill="oranda_pickup")
    with caplog.at_level("WARNING"):
        assert c.step_test() == "error"
    assert c.state == "IDLE" and c._run_idle.is_set()
    assert c.history[-1]["text"] == "테스트 실패: motor"
    assert "motor" in caplog.text
    rec = json.loads(next(tmp_path.glob("cycles-*.jsonl")).read_text(encoding="utf-8").splitlines()[0])
    assert rec["stop_reason"] == "error" and rec["error"] == "motor"


def test_estop_during_test_is_immediate_and_restart_waits(cfg):
    sk = BlockingRun()
    c, _ = make(cfg, sk)
    c.command("test", skill="oranda_pickup")
    t = threading.Thread(target=c.step_test, daemon=True)
    t.start()
    assert sk.entered.wait(2)
    c.command("estop")
    assert c.state == "ESTOP" and sk.estopped                # 테스트를 기다리지 않는다
    c.restart_wait_s = 0
    c.command("restart")
    assert c.state == "ESTOP" and "멈추는 중" in c.history[-1]["text"]
    sk.release.set()
    t.join(5)
    assert not t.is_alive() and c.state == "ESTOP"           # 끝난 테스트가 상태를 덮지 않는다
    assert "비상정지로 멈춤" in c.history[-1]["text"]
    c.restart_wait_s = 5
    c.command("restart")
    assert c.state == "IDLE"


def test_test_canceled_when_generation_changed_after_receipt(cfg):
    c, _ = make(cfg)
    g = c.generation()
    c.command("estop")
    c.command("restart")                                     # 접수 뒤 비상정지·재시작이 끼어들었다 (다시 IDLE)
    assert c.command("test", skill="dori_dori", expect_gen=g) is False
    assert c.state == "IDLE" and "테스트가 취소됐어요" in c.history[-1]["text"]
    assert c.command("test", skill="dori_dori", expect_gen=c.generation()) is True


def test_estop_before_loop_picks_test_drops_it(cfg):
    c, _ = make(cfg)
    c.command("test", skill="dori_dori")
    c.command("estop")
    c.command("restart")
    assert c.step_test() is None and c.skills.runs == [] and c.state == "IDLE"


def test_skill_estop_result_during_test_latches_estop(cfg):
    c, _ = make(cfg, EstopReason())
    c.command("test", skill="dori_dori")
    assert c.step_test() == "estop"
    assert c.state == "ESTOP"


def test_loop_thread_runs_tests_and_skills_only_on_loop_thread(cfg):
    class Where(FakeSkills):
        def __init__(self):
            super().__init__()
            self.threads = []

        def run(self, name, on_phase=None):
            self.threads.append(threading.current_thread().name)
            return super().run(name, on_phase)

        def go_home(self):
            self.threads.append(threading.current_thread().name)
            return super().go_home()

    sk = Where()
    c, _ = make(cfg, sk)
    c.start()
    try:
        c.command("test", skill="dori_dori")
        assert _wait_for(lambda: c.state == "IDLE" and sk.runs == ["dori_dori"])
        c.command("test", skill="home")
        assert _wait_for(lambda: c.state == "IDLE" and sk.homed == 1)
    finally:
        c.stop()
    assert sk.threads == ["controller", "controller"]


# --- LLM 도리도리 (채팅 의도) ---
def test_chat_dori_runs_one_test_with_llm_prefix(cfg):
    c, _ = make(cfg)
    c.chat("도리도리 해 봐")
    assert c.state == "TESTING" and c.skill == "dori_dori"
    assert [m["role"] for m in c.history] == ["user"]            # 대사는 루프 스레드가 낸다 (소리 시작 뒤 실행)
    assert c.step_test() == "timeout"
    assert [m["role"] for m in c.history] == ["user", "robot", "system"]
    assert c.state == "IDLE" and c.skills.runs == ["dori_dori"] and c.count == 0
    assert c.history[-1]["text"].startswith("도리도리 · 정책 동작 완료 · ")


def test_chat_dori_ignored_outside_idle(cfg):
    c, _ = make(cfg)
    c.chat("2개 옮겨줘")
    c.chat("도리도리 해 봐")
    assert c.state == "WORKING" and c._pending_test is None


def test_chat_dori_canceled_if_session_changed_during_llm(cfg):
    class SlowBrain(Brain):
        ctrl = None

        def chat(self, text, state, count, history=None):
            r = super().chat(text, state, count, history=history)
            self.ctrl._estop()                                     # LLM을 기다리는 사이 비상정지·재시작
            self.ctrl._restart()
            return r

    b = SlowBrain(cfg, rng=FirstRng())
    c = Controller(cfg, b, FakeSkills())
    b.ctrl = c
    c.chat("도리도리 해 봐")
    assert c.state == "IDLE" and c._pending_test is None
    assert "테스트가 취소됐어요" in c.history[-1]["text"]


def test_chat_dori_refused_leaves_only_reason_not_speech(cfg):
    c, _ = make(cfg)
    c._run_idle.clear()                                       # 아직 이전 동작이 끝나지 않았다
    c.chat("도리도리 해 봐")
    assert c.state == "IDLE" and c._pending_test is None
    assert [m["role"] for m in c.history] == ["user", "system"]
    assert "아직 동작이 끝나지 않았어요" in c.history[-1]["text"]


def test_test_twice_with_same_gen_says_already_testing(cfg):
    c, _ = make(cfg)
    g = c.generation()
    assert c.command("test", skill="dori_dori", expect_gen=g) is True
    assert c.command("test", skill="dori_dori", expect_gen=g) is False
    assert "이미 테스트 중" in c.history[-1]["text"] and "취소" not in c.history[-1]["text"]


def test_test_refused_in_done(cfg):
    c, _ = make(cfg)
    c.state = "DONE"
    assert c.command("test", skill="dori_dori") is False
    assert c.state == "DONE" and c._pending_test is None and c.history[-1]["role"] == "system"


def test_llm_prefix_uses_label_and_missing_stop_reason_text(cfg):
    c, _ = make(cfg)
    assert c._test_text("home", "llm", "done", None, 1000, None) == "홈으로 · 완료 · 1.0초"
    assert c._test_text("dori_dori", "button", None, None, 1000, None) == "테스트 · 도리도리: 알 수 없음 · 1.0초"


def test_test_log_grasped_none_for_non_pickup_and_error(cfg, tmp_path):
    class Boom(FakeSkills):
        def run(self, name, on_phase=None):
            raise RuntimeError("motor")

    c, _ = make(cfg, Boom(), log_dir=tmp_path)
    c.command("test", skill="home")
    c.step_test()
    c.command("test", skill="oranda_pickup")
    c.step_test()
    recs = [json.loads(x) for x in next(tmp_path.glob("cycles-*.jsonl")).read_text(encoding="utf-8").splitlines()]
    assert [r["grasped"] for r in recs] == [None, None]


def test_stop_during_test_ends_in_estop(cfg):
    sk = BlockingRun()
    c, _ = make(cfg, sk)
    c.command("test", skill="oranda_pickup")
    t = threading.Thread(target=c.step_test, daemon=True)
    t.start()
    assert sk.entered.wait(2)
    c.stop()
    assert sk.estopped
    sk.release.set()
    t.join(5)
    assert not t.is_alive() and c.state == "ESTOP"


def test_test_exception_after_estop_keeps_estop(cfg):
    class BoomAfterEstop(FakeSkills):
        ctrl = None

        def run(self, name, on_phase=None):
            self.ctrl.command("estop")
            raise RuntimeError("motor")

    sk = BoomAfterEstop()
    c, _ = make(cfg, sk)
    sk.ctrl = c
    c.command("test", skill="dori_dori")
    assert c.step_test() == "error"
    assert c.state == "ESTOP" and c._run_idle.is_set()


def test_home_test_go_home_estop_latches_estop(cfg):
    class HomeEstop(FakeSkills):
        def go_home(self):
            return "estop"

    c, _ = make(cfg, HomeEstop())
    c.command("test", skill="home")
    assert c.step_test() == "estop"
    assert c.state == "ESTOP"


def test_restart_finished_before_step_test_wraps_up_does_not_paste_old_result(cfg, monkeypatch):
    import snackbot.controller as ctl

    real_ms, fired = ctl._ms, []
    sk = EstopDuringRun()
    c, _ = make(cfg, sk)
    sk.ctrl = c

    def hooked(t0):
        if not fired:                                          # finally의 set 뒤, 마지막 락 앞
            fired.append(1)
            c.command("restart")
        return real_ms(t0)

    monkeypatch.setattr(ctl, "_ms", hooked)
    c.command("test", skill="dori_dori")
    c.step_test()
    assert fired and c.state == "IDLE"
    assert not any("시간 초과" in m["text"] or "비상정지로 멈춤" in m["text"] for m in c.history)


# --- LLM 도리도리: 대사 소리가 시작된 뒤 움직인다 ---
def _llm_dori_voiced(cfg, timeout=8):
    v = EventVoice()
    cfg["voice"]["sync_timeout_s"] = timeout
    c = Controller(cfg, Brain(cfg, rng=FirstRng()), FakeSkills(), voice=v)
    speaking = threading.Event()
    c.subscribe(lambda e: speaking.set() if (e["type"] == "state" and e["state"] == "TESTING"
                                             and e["phase"] == "speaking") else None)
    c.chat("도리도리 해 봐")
    return c, v, speaking


def _step_test_in_thread(c):
    out = []
    t = threading.Thread(target=lambda: out.append(c.step_test()), daemon=True)
    t.start()
    return t, out


def test_llm_dori_waits_for_speech_before_moving(cfg):
    c, v, speaking = _llm_dori_voiced(cfg)
    assert v.spoken == [] and c.state == "TESTING"                # chat()은 말하지 않는다 (루프 스레드가 말한다)
    t, out = _step_test_in_thread(c)
    assert speaking.wait(3)
    assert c.skills.runs == [] and c.phase == "speaking" and len(v.spoken) == 1
    assert c._run_idle.is_set()                                   # 팔은 아직 안 움직였다
    v.events[0].set()
    t.join(3)
    assert out == ["timeout"] and c.skills.runs == ["dori_dori"] and c.state == "IDLE"


def test_llm_dori_estop_during_speech_wait_never_runs(cfg):
    c, v, speaking = _llm_dori_voiced(cfg)
    t, out = _step_test_in_thread(c)
    assert speaking.wait(3)
    c._estop()                                                    # 대기를 기다리지 않는다 (락 없이 즉시)
    t.join(3)
    assert not t.is_alive() and out == [None]
    assert c.state == "ESTOP" and c.skills.runs == [] and c._run_idle.is_set()


def test_llm_dori_runs_after_sync_timeout(cfg):
    c, v, _ = _llm_dori_voiced(cfg, timeout=0)                    # 소리가 끝내 시작되지 않아도 실행한다
    assert c.step_test() == "timeout"
    assert c.skills.runs == ["dori_dori"] and c.state == "IDLE"
    assert v.events and not v.events[0].is_set()


def test_llm_dori_session_change_during_speech_wait_never_runs(cfg):
    c, v, speaking = _llm_dori_voiced(cfg)
    t, out = _step_test_in_thread(c)
    assert speaking.wait(3)
    with c._lock:
        c._gen += 1                                               # 대기 중 세션이 바뀌었다
    t.join(3)
    assert out == [None] and c.skills.runs == [] and c._run_idle.is_set()


def test_button_test_does_not_wait_for_speech(cfg):
    v = EventVoice()
    c = Controller(cfg, Brain(cfg, rng=FirstRng()), FakeSkills(), voice=v)
    c.command("test", skill="dori_dori")
    assert c.step_test() == "timeout"                             # 소리 이벤트를 set하지 않아도 바로 실행
    assert c.skills.runs == ["dori_dori"] and v.spoken == []


def test_dori_timeout_text_is_policy_done_but_other_skills_unchanged(cfg):
    c, _ = make(cfg)
    assert c._test_text("dori_dori", "button", "timeout", None, 1000, None) == "테스트 · 도리도리: 정책 동작 완료 · 1.0초"
    assert c._test_text("dori_dori", "button", "script", None, 1000, None) == "테스트 · 도리도리: 코드 동작 완료 · 1.0초"
    assert "시간 초과" in c._test_text("oranda_pickup", "button", "timeout", False, 1000, None)


def test_vision_options_and_set_method(cfg):
    c, ev = make(cfg, vision=FakeVision(names=["opencv"]))
    assert c.vision_options() == ["opencv", "off"] and c.snapshot()["vision_choice"] == "opencv"
    c.set_vision_method("off")
    assert c.snapshot()["vision_choice"] == "off" and ev[-1]["vision_choice"] == "off"
    with pytest.raises(ValueError):
        c.set_vision_method("vlm")
    c2, _ = make(cfg, vision=FakeVision(names=["yolo", "opencv"]))
    assert c2.vision_options() == ["auto", "yolo", "opencv", "off"] and c2.snapshot()["vision_choice"] == "auto"
    c3, _ = make(cfg)
    with pytest.raises(ValueError):
        c3.set_vision_method("off")


def test_vision_off_uses_b_stage_and_named_choice_passes_only(cfg):
    v = FakeVision(Count(3, "opencv"), names=["yolo", "opencv"])
    c, _ = make(cfg, FakeSkills(grasps=[True]), vision=v)
    c.set_vision_method("off")
    c.chat("2개 옮겨줘")
    assert c.step() == "success" and v.only == [] and (c.remaining, c.vision_method) == (1, "estimate")
    c.set_vision_method("opencv")
    c.step()
    assert v.only and set(v.only) == {"opencv"}


def test_count_now_idle_only_publishes_and_keeps_counters(cfg, tmp_path):
    v = FakeVision(Count(4, "opencv", [[1, 2, 3, 4]]), names=["opencv"])
    c, ev = make(cfg, vision=v, log_dir=tmp_path)
    assert c.command("count") is True
    snap = c.snapshot()
    assert (snap["remaining"], snap["vision_method"], snap["count"]) == (4, "opencv", 0)
    assert snap["last_count"]["n"] == 4 and snap["last_count"]["method"] == "opencv" and "ms" in snap["last_count"]
    assert c.last_boxes == [[1, 2, 3, 4]] and ev[-1]["type"] == "state" and not c.history
    lines = [json.loads(x) for x in c.log_path.read_text(encoding="utf-8").splitlines()]
    assert lines[-1]["type"] == "count" and lines[-1]["n"] == 4 and c.cycle_n == 0
    c.chat("2개 옮겨줘")
    assert c.command("count") is False and c.remaining == 2        # 작업 중에는 거부, 값을 건드리지 않는다
    assert v.only == [None]


def test_count_now_refused_when_off_failed_or_no_vision(cfg):
    c, _ = make(cfg, vision=FakeVision(names=["opencv"]))      # counts 없음 -> 실패
    assert c.command("count") is False and c.history[-1]["text"].startswith("개수를 세지 못했어요")
    c.set_vision_method("off")
    assert c.command("count") is False and "꺼져" in c.history[-1]["text"]
    c2, _ = make(cfg)
    assert c2.command("count") is False and c2.remaining == 0


def _run_task(c, n_steps):
    return [c.step() for _ in range(n_steps)]


@pytest.mark.parametrize("total,at", [(3, 2), (4, 2), (5, 3), (6, 3)])
def test_half_refuses_once_at_ceil_half_and_resume_finishes(cfg, total, at):
    c, _ = make(cfg)
    c.chat(f"{total}개 옮겨줘")
    assert _run_task(c, at + 1) == ["success"] * at + ["refuse"]
    assert (c.state, c.refused, c.skills.runs[-1]) == ("REFUSING", True, "dori_dori")
    assert c.snapshot()["refuse_at"] == at and c.snapshot()["total"] == total
    c.command("resume")
    assert c.refused and c.state == "WORKING" and c.count == 0     # 재개로 거부 표시는 초기화되지 않는다
    assert _run_task(c, total - at + 1) == ["success"] * (total - at) + ["done"]
    assert c.skills.runs.count("dori_dori") == 1


def test_half_total_two_never_refuses(cfg):
    c, _ = make(cfg)
    c.chat("2개 옮겨줘")
    assert _run_task(c, 3) == ["success", "success", "done"]
    assert "dori_dori" not in c.skills.runs


def test_half_new_task_resets_refused(cfg):
    c, _ = make(cfg)
    c.chat("3개 옮겨줘")
    _run_task(c, 3)
    c.command("resume")
    _run_task(c, 2)                                  # 나머지 1개 + done
    assert c.state == "IDLE"
    c.chat("3개 옮겨줘")
    assert not c.refused and c.total == 3
    assert _run_task(c, 3) == ["success", "success", "refuse"]


def test_half_tired_line_before_refusal(cfg, tmp_path):
    c, ev = make(cfg, log_dir=tmp_path)
    c.chat("6개 옮겨줘")
    _run_task(c, 3)
    says = [e["text"] for e in ev if e["type"] == "message" and e["role"] == "robot"]
    assert says[1] == "오란다 하나 옮길게요!" and says[2] == "오란다 하나 옮길게요!"
    assert says[3] == "으… 팔이 조금 뻐근한데요."   # 3번째 옮기기 (moved 2 == 3 - 1)
    records = [json.loads(x) for x in next(tmp_path.glob("cycles-*.jsonl")).read_text(encoding="utf-8").splitlines()]
    assert (records[0]["total"], records[0]["refuse_at"], records[0]["refused"]) == (6, 3, False)


def test_half_first_vision_count_sets_total_once(cfg):
    counts = [Count(6, "opencv"), Count(5, "opencv"), Count(5, "opencv"), Count(4, "opencv"),
              Count(4, "opencv"), Count(3, "opencv"), Count(9, "opencv")]
    c, _ = make(cfg, vision=FakeVision(*counts))
    c.chat("과자 옮겨줘")                              # chat 개수 없음: initial_count(3) → 카메라 6으로 교체
    assert c.step() == "success" and c.total == 6
    assert c.step() == "success"
    assert c.step() == "success"                      # 3개 옮김 (6 → 3)
    assert c.total == 6
    c.step()                                          # 다음 사이클 앞 세기가 9: total 은 그대로 (moved < 0 은 0)
    assert c.total == 6 and c.skills.runs.count("dori_dori") == 0


def test_half_vision_more_than_total_keeps_refuse_point(cfg):
    counts = [Count(6, "opencv"), Count(5, "opencv"), Count(7, "opencv")]
    c, _ = make(cfg, vision=FakeVision(*counts))
    c.chat("과자 옮겨줘")
    assert c.step() == "success"
    c.step()
    assert c.total == 6 and c.snapshot()["refuse_at"] == 3


def test_half_vision_off_uses_chat_number(cfg):
    c, _ = make(cfg, vision=FakeVision(Count(9, "opencv")))
    c.set_vision_method("off")
    c.chat("5개 옮겨줘")
    assert _run_task(c, 4) == ["success"] * 3 + ["refuse"]
    assert c.total == 5 and c.snapshot()["refuse_at"] == 3


def test_half_vision_failure_uses_initial_count(cfg):
    c, _ = make(cfg, vision=FakeVision())
    c.command("start")                                 # initial_count 3 → 2개 뒤 거부
    assert _run_task(c, 3) == ["success", "success", "refuse"]


def test_fixed_snapshot_has_no_refuse_at(cfg):
    cfg["decision"]["refuse"] = "fixed"
    c, _ = make(cfg)
    c.chat("6개 옮겨줘")
    assert c.snapshot()["refuse_at"] is None
