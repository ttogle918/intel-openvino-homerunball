"""상태 머신과 사이클 루프. FastAPI를 모른다 (server.py가 이 모듈을 부른다).

한 사이클(step): (A단계면 개수 세기) → brain.decide → 대사 → 스킬 실행 → 성공 판정.
성공 판정: A단계면 개수 감소, 아니면(또는 counter 실패 시) 그리퍼 쥠(grasped).
"""
import json
import logging
import threading
import time
from collections import deque
from pathlib import Path

log = logging.getLogger(__name__)

IDLE, WORKING, REFUSING, DONE, ESTOP = "IDLE", "WORKING", "REFUSING", "DONE", "ESTOP"


def _ms(t0):
    return int((time.monotonic() - t0) * 1000)


class Controller:
    def __init__(self, cfg, brain, skills, vision=None, voice=None, log_dir=None, clock=time.time):
        self.decision = cfg["decision"]
        self.initial_count = cfg["target"]["initial_count"]
        self.camera = cfg["vision"].get("camera", "front")
        self.brain, self.skills, self.voice, self.clock = brain, skills, voice, clock
        self.vision = vision if vision is not None and vision.enabled else None
        self.state, self.phase = IDLE, "idle"
        self.count = self.remaining = self.retries = self.cycle_n = 0
        self.skill = None
        self.vision_method = "estimate"
        self.last_boxes = None
        self.history = deque(maxlen=50)
        self._subs = []
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self.log_path = None
        if log_dir is not None:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            self.log_path = Path(log_dir) / time.strftime("cycles-%Y%m%d.jsonl")

    # ---- 이벤트 ----
    def subscribe(self, fn):
        self._subs.append(fn)

    def snapshot(self):
        with self._lock:
            return {"type": "state", "state": self.state, "phase": self.phase, "count": self.count,
                    "remaining": self.remaining, "skill": self.skill, "vision_method": self.vision_method,
                    "thresholds": {"safe_max": self.decision["safe_max"],
                                   "force_refuse": self.decision["force_refuse"]}}

    def _emit(self, event):
        for fn in list(self._subs):
            try:
                fn(event)
            except Exception:
                log.exception("subscriber 실패")

    def _publish(self):
        self._emit(self.snapshot())

    def _message(self, role, text, source=None):
        msg = {"type": "message", "role": role, "text": text, "ts": self.clock()}
        if source:
            msg["source"] = source
        with self._lock:
            self.history.append(msg)
        self._emit(msg)
        if role == "robot" and self.voice is not None:
            self.voice.speak(text)

    def notify(self, text):
        self._message("system", text)

    # ---- 입력 ----
    def chat(self, text, source="text"):
        text = (text or "").strip()
        if not text:
            return
        self._message("user", text, source)
        with self._lock:
            state, count = self.state, self.count
        r = self.brain.chat(text, state, count)
        self._message("robot", r["say"])
        if r["intent"] == "start_task":
            self._start_task(r.get("n"))
        elif r["intent"] == "resume":
            self._resume()

    def command(self, name):
        if name == "start":
            self._start_task(None, announce=True)
        elif name == "resume":
            self._resume(announce=True)
        elif name == "estop":
            self._estop()
        elif name == "restart":
            self._restart()
        elif name == "quit":
            self.stop()
        else:
            raise ValueError(f"알 수 없는 명령: {name}")

    def _start_task(self, n, announce=False):
        with self._lock:
            if self.state not in (IDLE, DONE):
                return False
            self.remaining = n or self.initial_count
            self.count = self.retries = 0
            self.skill, self.vision_method, self.last_boxes = None, "estimate", None
            self.state, self.phase = WORKING, "idle"
            self.skills.new_task(self.remaining)
        if announce:
            self._message("robot", self.brain.line("start"))
        self._publish()
        self._wake.set()
        return True

    def _resume(self, announce=False):
        with self._lock:
            if self.state == REFUSING:
                self.count = 0
                self.state = WORKING
            elif not (self.state == WORKING and self.phase == "waiting_operator"):
                return False
            self.retries = 0
            self.phase = "idle"
        if announce:
            self._message("robot", self.brain.line("resume"))
        self._publish()
        self._wake.set()
        return True

    def _estop(self):
        self.skills.estop()  # 멱등: 항상 먼저 하드웨어를 세운다
        with self._lock:
            already = self.state == ESTOP
            self.state, self.phase = ESTOP, "idle"  # 이미 ESTOP이면 진행 중인 재시작도 중단
        self.skills.estop()  # 상태 기록 뒤 한 번 더: 재시작의 release_estop과 겹쳐도 래치가 남는다
        if not already:
            self.notify("비상정지됨")
        self._publish()

    def _restart(self):
        with self._lock:
            if self.state != ESTOP or self.phase == "returning":
                return False
            self.phase = "returning"
        self.skills.release_estop()
        with self._lock:
            still = self.state == ESTOP and self.phase == "returning"
        if not still:  # release 도중 비상정지가 들어왔다: 다시 세우고 홈 복귀하지 않는다
            self.skills.estop()
            return False
        self.skills.go_home()
        with self._lock:
            ok = self.state == ESTOP and self.phase == "returning"
            if ok:
                self.state, self.phase, self.retries, self.skill = IDLE, "idle", 0, None
        if not ok:
            self.skills.estop()
        if ok:
            self.notify("재시작: 대기 상태로 돌아왔어요")
        self._publish()
        return ok

    # ---- 사이클 ----
    def _working(self):
        with self._lock:
            return self.state == WORKING and self.phase != "waiting_operator"

    def _set_phase(self, phase):
        with self._lock:
            if self.state != WORKING:
                return
            self.phase = phase
        self._publish()

    def step(self):
        """사이클 1회. 일할 상태가 아니면 None. 결과: success | fail | refuse | done | estop."""
        if not self._working():
            return None
        ms = {}
        with self._lock:
            n_before = self.remaining
        if self.vision:
            self._set_phase("counting")
            seen = self._count(ms)
            if seen is not None:
                n_before = seen
        self._set_phase("thinking")
        t0 = time.monotonic()
        d = self.brain.decide(n_before, self.count, WORKING, None)
        ms["llm"] = _ms(t0)
        if not self._working():
            return None
        with self._lock:
            self.skill = d["skill"]
        self._message("robot", d["say"])
        if d["skill"] == "done":
            return self._finish(ms, d)
        self._set_phase("acting")
        t0 = time.monotonic()
        returning_at = []

        def on_phase(phase):
            if phase == "returning" and not returning_at:
                returning_at.append(time.monotonic())
            self._set_phase(phase)

        r = self.skills.run(d["skill"], on_phase=on_phase)
        total = _ms(t0)
        if returning_at:
            ms["act"] = int((returning_at[0] - t0) * 1000)
            ms["return"] = max(0, total - ms["act"])
        else:
            ms["act"] = total
        if r.stop_reason == "estop":
            with self._lock:
                if self.state != ESTOP:
                    self.state, self.phase = ESTOP, "idle"
            self._publish()
            self._log_cycle("estop", ms, d, r)
            return "estop"
        if d["skill"] == "dori_dori":
            with self._lock:
                if self.state != WORKING:
                    aborted = True
                else:
                    aborted = False
                    self.state, self.phase = REFUSING, "idle"
            if aborted:
                self._log_cycle("estop", ms, d, r)
                return "estop"
            self._publish()
            self._log_cycle("refuse", ms, d, r)
            return "refuse"
        return self._judge(n_before, ms, d, r)

    def _count(self, ms):
        """A단계 개수 세기. 실패하면 None (그 사이클은 B로 판정)."""
        t0 = time.monotonic()
        c = self.vision.count(self.skills.latest_frame(self.camera))
        ms["vision"] = ms.get("vision", 0) + _ms(t0)
        with self._lock:
            if c is None:
                self.vision_method = "estimate"
                return None
            self.remaining, self.vision_method, self.last_boxes = c.n, c.method, c.boxes
        self._publish()
        return c.n

    def _judge(self, n_before, ms, d, r):
        with self._lock:
            aborted = self.state != WORKING
        if aborted:
            self._log_cycle("estop", ms, d, r)
            return "estop"
        seen = None
        if self.vision:
            self._set_phase("counting")
            seen = self._count(ms)
        success = seen < n_before if seen is not None else r.grasped
        with self._lock:
            aborted = self.state != WORKING
            if not aborted:
                if success:
                    self.count += 1
                    self.retries = 0
                    if seen is None:
                        self.remaining = max(0, n_before - 1)
                else:
                    self.retries += 1
                waiting = not success and self.retries > self.decision["max_retry"]
                self.phase = "waiting_operator" if waiting else "idle"
        if aborted:
            self._log_cycle("estop", ms, d, r)
            return "estop"
        if waiting:
            self.notify("도와주세요! 확인한 뒤 재개를 눌러 주세요.")
        elif not success:
            self._message("robot", self.brain.line("fail"))
        self._publish()
        result = "success" if success else "fail"
        self._log_cycle(result, ms, d, r)
        return result

    def _finish(self, ms, d):
        with self._lock:
            aborted = self.state != WORKING
            if not aborted:
                self.state, self.phase = DONE, "idle"
        if aborted:
            self._log_cycle("estop", ms, d)
            return "estop"
        self._publish()
        self._log_cycle("done", ms, d)
        with self._lock:
            if self.state == DONE:
                self.state, self.skill = IDLE, None
        self._publish()
        return "done"

    def _log_cycle(self, result, ms, d, r=None):
        with self._lock:
            self.cycle_n += 1
            n = self.cycle_n
            record = {"ts": self.clock(), "n": n, "result": result, "state": self.state,
                      "count": self.count, "remaining": self.remaining, "skill": d["skill"],
                      "say": d["say"], "source": d.get("source"), "vision_method": self.vision_method,
                      "stop_reason": r.stop_reason if r else None, "grasped": r.grasped if r else None,
                      "ms": ms}
        self._emit({"type": "cycle", "n": n, "result": result, "ms": dict(ms)})
        if self.log_path is not None:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ---- 스레드 ----
    def start(self):
        self._thread = threading.Thread(target=self._run, name="controller", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        with self._lock:
            active = self.state != IDLE
        if active:
            self.skills.estop()  # 진행 중인 스킬·재시작 홈 복귀 중단
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)

    @property
    def stopped(self):
        return self._stop.is_set()

    def wait_stopped(self):
        while not self._stop.wait(0.5):  # 타임아웃 루프: Windows에서도 Ctrl+C가 먹도록
            pass

    def _run(self):
        while not self._stop.is_set():
            if self._working():
                try:
                    self.step()
                except Exception:
                    log.exception("사이클 실패")
                    with self._lock:
                        if self.state == WORKING:
                            self.phase = "waiting_operator"
                    self.notify("오류가 났어요. 로그를 확인한 뒤 재개를 눌러 주세요.")
                    self._publish()
            else:
                self._wake.wait(0.2)
                self._wake.clear()
