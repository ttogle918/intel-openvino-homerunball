"""상태 머신과 사이클 루프. FastAPI를 모른다 (server.py가 이 모듈을 부른다).

한 사이클(step): (A단계면 개수 세기) → brain.decide → 대사 → 스킬 실행 → 성공 판정.
성공 판정: A단계면 개수 감소, 아니면(또는 counter 실패 시) 그리퍼 쥠(grasped).
스킬 테스트(TESTING): command("test", skill=)는 대기(IDLE)에서만 받아 요청 슬롯에 넣고, 루프 스레드가 step_test()로
한 번 실행한다. 횟수·피로도·사이클 통계에는 넣지 않는다 (설계: docs/superpowers/specs/2026-10-22-skill-test-and-scripted-dori-design.md).
"""
import json
import logging
import threading
import time
from collections import deque
from pathlib import Path

log = logging.getLogger(__name__)

IDLE, WORKING, REFUSING, DONE, ESTOP, TESTING = "IDLE", "WORKING", "REFUSING", "DONE", "ESTOP", "TESTING"
TEST_SKILLS = ("oranda_pickup", "dori_dori", "dori_script", "home")
TEST_LABELS = {"dori_dori": "도리도리", "dori_script": "코드 도리도리", "home": "홈으로"}   # oranda_pickup은 target 이름
STOP_REASON_KO = {"gripper_open": "놓기 감지로 끝남", "timeout": "시간 초과로 끝남", "estop": "비상정지로 멈춤",
                  "script": "코드 동작 완료", "done": "완료"}


_RESTART_CANCELED = "재시작이 취소됐어요: 그 사이 비상정지가 들어왔어요"
_TEST_BUSY = "테스트 중이에요. 끝난 뒤 다시 시켜 주세요"
_TEST_CANCELED = "테스트가 취소됐어요: 그 사이 비상정지나 상태 변경이 있었어요"
_TEST_REFUSED = {WORKING: "작업 중에는 스킬 테스트를 할 수 없어요",
                 REFUSING: "거부 중에는 스킬 테스트를 할 수 없어요. 재개하거나 재시작한 뒤에 하세요",
                 DONE: "작업을 마무리하는 중이에요. 잠시 뒤 다시 눌러 주세요",
                 ESTOP: "비상정지 중이에요. 재시작한 뒤 테스트하세요",
                 TESTING: "이미 테스트 중이에요"}


def _ms(t0):
    return int((time.monotonic() - t0) * 1000)


class Controller:
    def __init__(self, cfg, brain, skills, vision=None, voice=None, log_dir=None, clock=time.time):
        self.decision = cfg["decision"]
        self.target_name = cfg["target"]["name"]
        self.initial_count = cfg["target"]["initial_count"]
        self.camera = cfg["vision"].get("camera", "front")
        sync = (cfg.get("voice") or {}).get("sync_timeout_s")
        self.sync_timeout_s = 10.0 if sync is None else float(sync)
        self.restart_wait_s = 5.0  # 재시작이 진행 중인 동작(skills.run)이 멈추기를 기다리는 최대 시간
        self._run_idle = threading.Event()  # set = skills.run 실행 중이 아님
        self._run_idle.set()
        self._restart_wait_hook = None  # 테스트용: 재시작이 동작 종료를 기다리기 시작할 때 부른다
        self._gen = 0  # 세션 번호: estop/start/resume/restart 때 올라간다 (이전 세션의 결정을 버리는 용도)
        self._pending_test = None  # (skill, gen, origin, say): 루프 스레드가 step_test()로 꺼내 실행한다
        self.brain, self.skills, self.voice, self.clock = brain, skills, voice, clock
        self.vision = vision if vision is not None and vision.enabled else None
        self.state, self.phase = IDLE, "idle"
        self.count = self.remaining = self.retries = self.cycle_n = 0
        self.skill = None
        self.vision_method = "estimate"
        self.vision_choice = "auto"   # 개수 세기 방법: auto(체인 순서) | off(B단계) | counter 이름
        self.last_count = None        # 마지막 "지금 세기" 결과 {n, method, ms, ts} (화면 표시용)
        self._counting_now = False
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
                    "vision_choice": self._effective_choice(), "vision_options": self.vision_options(),
                    "last_count": self.last_count,
                    "thresholds": {"safe_max": self.decision["safe_max"],
                                   "force_refuse": self.decision["force_refuse"]}}

    # ---- 개수 세기 방법 ----
    def vision_options(self):
        """화면 토글에 보여줄 선택지. counter가 없으면 비어 있다 (항상 B단계). 둘 이상이면 "auto"(체인 전체)가 앞에 붙는다."""
        if not self.vision:
            return []
        names = self.vision.names
        return (["auto"] if len(names) > 1 else []) + names + ["off"]

    def _effective_choice(self):
        """counter가 하나뿐이면 auto는 그 counter와 같다 (토글에서 그 항목이 눌려 보이도록)."""
        if not self.vision:
            return "off"
        if self.vision_choice == "auto" and len(self.vision.names) == 1:
            return self.vision.names[0]
        return self.vision_choice

    def set_vision_method(self, name):
        """개수 세기 방법 선택: auto | off | counter 이름. 다음 개수 세기부터 적용된다 (진행 중인 사이클은 그대로)."""
        with self._lock:
            if name != "auto" and name not in self.vision_options() or not self.vision:
                raise ValueError(f"알 수 없는 개수 세기 방법: {name}")
            self.vision_choice = name
        self._publish()

    def _count_args(self):
        """(세기 가능 여부, only). off이거나 counter가 없으면 B단계."""
        choice = self.vision_choice
        if not self.vision or choice == "off":
            return False, None
        return True, None if choice == "auto" else choice

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
            return self.voice.speak(text)
        return None

    def notify(self, text):
        self._message("system", text)

    # ---- 입력 ----
    def chat(self, text, source="text"):
        text = (text or "").strip()
        if not text:
            return
        with self._lock:
            hist = list(self.history)  # 현재 발화를 넣기 전 스냅샷 (brain이 현재 발화는 따로 붙인다)
        self._message("user", text, source)
        with self._lock:
            state, count, gen = self.state, self.count, self._gen
        r = self.brain.chat(text, state, count, history=hist)
        if r["intent"] == "dori_dori":
            # 버튼과 같은 경로 (대기 상태에서만, 횟수·피로도 미반영). LLM을 기다리는 사이 세션이 바뀌었으면 취소.
            # 거부되면 대사 없이 거부 이유만 남는다
            # 대사는 job에 실어 루프 스레드(step_test)가 내고, 소리가 시작된 뒤 움직인다 (사이클과 같다)
            self._request_test("dori_dori", expect_gen=gen, origin="llm", say=r["say"])
            return
        self._message("robot", r["say"])
        if r["intent"] == "start_task":
            self._start_task(r.get("n"))
        elif r["intent"] == "resume":
            self._resume()

    def generation(self):
        """현재 세션 번호. 콘솔 키 워커가 restart를 접수한 시점의 값을 command(expect_gen=)로 되돌려준다."""
        with self._lock:
            return self._gen

    def command(self, name, expect_gen=None, skill=None, method=None):
        if name == "start":
            self._start_task(None, announce=True)
        elif name == "resume":
            self._resume(announce=True)
        elif name == "estop":
            self._estop()
        elif name == "restart":
            if expect_gen is None:
                self._restart()
            else:
                self._restart(expect_gen)
        elif name == "test":
            return self._request_test(skill, expect_gen=expect_gen)
        elif name == "vision_method":
            self.set_vision_method(method)
        elif name == "count":
            return self.count_now()
        elif name == "quit":
            self.stop()
        else:
            raise ValueError(f"알 수 없는 명령: {name}")

    def _start_task(self, n, announce=False):
        with self._lock:
            busy = self.state == TESTING
            if not busy and self.state not in (IDLE, DONE):
                return False
            if not busy:
                self._gen += 1
                self.remaining = n or self.initial_count
                self.count = self.retries = 0
                self.skill, self.vision_method, self.last_boxes = None, "estimate", None
                self.state, self.phase = WORKING, "idle"
                self.skills.new_task(self.remaining)
        if busy:
            self.notify(_TEST_BUSY)
            return False
        if announce:
            self._message("robot", self.brain.line("start"))
        self._publish()
        self._wake.set()
        return True

    def _resume(self, announce=False):
        with self._lock:
            busy = self.state == TESTING
            if not busy:
                if self.state == REFUSING:
                    self.count = 0
                    self.state = WORKING
                elif not (self.state == WORKING and self.phase == "waiting_operator"):
                    return False
                self._gen += 1
                self.retries = 0
                self.phase = "idle"
        if busy:
            self.notify(_TEST_BUSY)
            return False
        if announce:
            self._message("robot", self.brain.line("resume"))
        self._publish()
        self._wake.set()
        return True

    def _estop(self):
        self.skills.estop()  # 멱등: 항상 먼저 하드웨어를 세운다
        with self._lock:
            already = self.state == ESTOP
            self._gen += 1
            self.state, self.phase = ESTOP, "idle"  # 이미 ESTOP이면 진행 중인 재시작도 중단
            self._pending_test = None  # 아직 시작 안 한 스킬 테스트는 버린다
        self.skills.estop()  # 상태 기록 뒤 한 번 더: 재시작의 release_estop과 겹쳐도 래치가 남는다
        if self.voice is not None:  # 락 밖: 비상정지 전의 남은 대사가 이어 나오지 않게 (재생 중인 한 문장은 끝까지)
            try:
                self.voice.clear_pending()
            except Exception:
                log.exception("남은 대사 비우기 실패")
        if not already:
            self.notify("비상정지됨")
        self._publish()

    def _restart(self, expect_gen=None):
        with self._lock:
            if expect_gen is not None and self._gen != expect_gen:
                # 접수 뒤에 비상정지 등이 끼어들었다: 나중에 누른 비상정지를 풀면 안 된다
                log.info("restart 거부: 접수 뒤 세션이 바뀜 (%s != %s)", expect_gen, self._gen)
                self.notify(_RESTART_CANCELED)
                return False
            if self.state != ESTOP or self.phase == "returning":
                return False
            if expect_gen is None:
                expect_gen = self._gen  # 인자 없는 재시작도 대기 중에 끼어든 비상정지를 따른다
        # 진행 중인 동작이 멈출 때까지 기다린다 (락 밖: 비상정지는 이 대기와 무관하게 즉시 처리된다).
        # 동작이 아직 도는 채로 토크 해제·홈 복귀를 하면 두 명령이 겹친다.
        if self._restart_wait_hook is not None and not self._run_idle.is_set():
            self._restart_wait_hook()
        if not self._run_idle.wait(self.restart_wait_s):
            self.notify("아직 동작이 멈추는 중이에요. 잠시 뒤 다시 재시작하세요")
            return False
        with self._lock:
            if self._gen != expect_gen:
                log.info("restart 거부: 대기 중 세션이 바뀜 (%s != %s)", expect_gen, self._gen)
                self.notify(_RESTART_CANCELED)
                return False
            if self.state != ESTOP or self.phase == "returning":
                return False
            self.phase = "returning"
            self._gen += 1
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
                self._gen += 1
                # 비상정지 후 재시작은 새 시연의 시작: LLM 대화 기억을 비운다.
                # (UI 로그는 재접속 전까지 그대로 보인다. 작업 시작/재개 사이에는 기억을 유지한다.)
                self.history.clear()
        if not ok:
            self.skills.estop()
        if ok:
            self.notify("재시작: 대기 상태로 돌아왔어요")
        self._publish()
        return ok

    # ---- 스킬 테스트 (TESTING) ----
    def _request_test(self, skill, expect_gen=None, origin="button", say=None):
        """스킬 1회 실행 요청. 대기(IDLE)이고 진행 중인 동작이 없을 때만 받는다.
        expect_gen: 접수 순간의 세션 번호 (그 뒤 비상정지·재시작이 끼면 거부).
        say: 있으면 루프 스레드가 말하고 소리가 시작된 뒤에 움직인다 (버튼은 없음 = 즉시). 실행은 루프 스레드(step_test)가 한다."""
        if skill not in TEST_SKILLS:
            raise ValueError(f"알 수 없는 테스트 스킬: {skill}")
        with self._lock:
            if self.state != IDLE:   # 상태 확인이 먼저: 두 번 누르면 "이미 테스트 중"
                refused = _TEST_REFUSED.get(self.state, "대기 상태에서만 테스트할 수 있어요")
            elif expect_gen is not None and self._gen != expect_gen:
                refused = _TEST_CANCELED
            elif not self._run_idle.is_set():
                refused = "아직 동작이 끝나지 않았어요. 잠시 뒤 다시 눌러 주세요"
            else:
                refused = None
                self._gen += 1
                self._pending_test = (skill, self._gen, origin, say)
                self.state, self.phase, self.skill = TESTING, "idle", skill
        if refused:
            log.info("스킬 테스트 거부 (%s): %s", skill, refused)
            self.notify(refused)
            return False
        self._publish()
        self._wake.set()
        return True

    def _testing(self, gen):
        with self._lock:
            return self.state == TESTING and self._gen == gen

    def _set_test_phase(self, phase, gen):
        with self._lock:
            if self.state != TESTING or self._gen != gen:
                return
            self.phase = phase
        self._publish()

    def step_test(self):
        """대기 중인 스킬 테스트 1회 (루프 스레드에서만 부른다).
        없거나 접수 뒤 세션이 바뀌었으면 None, 아니면 stop_reason (예외면 "error")."""
        with self._lock:
            job, self._pending_test = self._pending_test, None
            if job is None:
                return None
            skill, gen, origin, say = job
            if self.state != TESTING or self._gen != gen:
                return None
            if not say:
                self._run_idle.clear()  # 확인과 같은 락 안: 재시작이 그 사이로 끼어들지 못한다
        if say:
            # 락 밖에서 말하고 소리가 시작될 때까지 기다린다. 팔은 아직 안 움직이고 _run_idle은 set이라
            # 비상정지·재시작은 이 대기를 기다리지 않는다 (세대가 바뀌면 0.1초 안에 빠져나온다)
            try:
                started = self._message("robot", say)
            except Exception as e:
                log.warning("테스트 대사 실패: %r", e)
                started = None
            self._wait_speech(started, gen, alive=lambda: self._testing(gen),
                              on_wait=lambda: self._set_test_phase("speaking", gen))
            with self._lock:
                if self.state != TESTING or self._gen != gen or self._stop.is_set():
                    return None
                self._run_idle.clear()  # 재확인과 같은 락 안
        t0 = time.monotonic()
        stop_reason, grasped, record, error = None, None, None, None
        try:
            if skill == "home":
                self._set_test_phase("returning", gen)
                stop_reason = self.skills.go_home() or "done"
            else:
                self._set_test_phase("acting", gen)
                r = self.skills.run(skill, on_phase=lambda phase: self._set_test_phase(phase, gen))
                stop_reason, grasped, record = r.stop_reason, bool(r.grasped), getattr(r, "record", None)
        except Exception as e:
            log.warning("스킬 테스트 실패 (%s): %r", skill, e, exc_info=True)
            error = e
        finally:
            self._run_idle.set()
        ms = _ms(t0)
        with self._lock:
            current = self.state == TESTING and self._gen == gen
            stale = not current and self.state != ESTOP   # 재시작이 먼저 끝났다: 지난 결과가 새 세션 화면을 덮지 않게
            if current:
                if stop_reason == "estop":  # 스킬 쪽에서 멈췄다 (예: Ctrl+C): 사이클과 같이 비상정지로 맞춘다
                    self.state, self.phase = ESTOP, "idle"
                else:
                    self.state, self.phase, self.skill = IDLE, "idle", None
        if stale:
            log.info("테스트 결과 생략 (그 사이 세션이 바뀜): %s %s", skill, stop_reason)
        elif error is not None:
            self.notify(f"테스트 실패: {error}")
        else:
            self.notify(self._test_text(skill, origin, stop_reason, grasped, ms, record))
        if current:
            self._publish()
        result = "error" if error is not None else stop_reason
        self._log_test(skill, origin, result, grasped, ms, record, error)
        return result

    def _test_text(self, skill, origin, stop_reason, grasped, ms, record):
        """결과 한 줄: 버튼 '테스트 · 오란다: 놓기 감지로 끝남 · 쥠 성공 · 12.3초 · 기록 …', LLM '도리도리 · …'."""
        how = STOP_REASON_KO.get(stop_reason, "알 수 없음" if stop_reason is None else str(stop_reason))
        if skill == "dori_dori" and stop_reason == "timeout":
            how = "정책 동작 완료"  # 정책 도리도리는 끝 신호가 없어 시간이 끝나는 것이 정상 종료다 (RunResult·로그는 원본)
        label = self.target_name if skill == "oranda_pickup" else TEST_LABELS[skill]
        parts = [f"{label} · {how}" if origin == "llm" else f"테스트 · {label}: {how}"]
        if skill == "oranda_pickup":
            parts.append("쥠 성공" if grasped else "쥠 없음")
        parts.append(f"{ms / 1000:.1f}초")
        if record:
            parts.append(f"기록 {record}")
        return " · ".join(parts)

    def _log_test(self, skill, origin, stop_reason, grasped, ms, record, error):
        """사이클 통계와 섞이지 않게 type "test"로 남긴다 (cycle 번호·이벤트 없음). 기록 실패는 경고만."""
        try:
            self._append_log({"ts": self.clock(), "type": "test", "skill": skill, "origin": origin,
                              "stop_reason": stop_reason, "grasped": grasped, "ms": ms, "record": record,
                              "error": None if error is None else str(error)})
        except Exception as e:
            log.warning("테스트 로그 기록 실패: %s", e)

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

    def _wait_speech(self, started, gen, alive=None, on_wait=None):
        """대사 소리가 나기 시작할 때까지 기다린다 (최대 sync_timeout_s). 대기한 ms를 돌려준다.
        비상정지·종료·상태 변경이 오면 즉시 멈춘다. 락은 잡지 않는다.
        alive: 계속 기다려도 되는지 판정 (기본: 사이클 일하는 중), on_wait: 기다리기 시작할 때 단계 표시."""
        alive = alive or self._working
        on_wait = on_wait or (lambda: self._set_phase("speaking"))
        if started is None:
            return 0
        t0 = time.monotonic()
        if not started.is_set():
            on_wait()
            while not started.wait(0.1):
                if (not alive() or self._stop.is_set() or self._gen != gen
                        or time.monotonic() - t0 >= self.sync_timeout_s):
                    break
        return _ms(t0)

    def step(self):
        """사이클 1회. 일할 상태가 아니면 None. 결과: success | fail | refuse | done | estop."""
        if not self._working():
            return None
        ms = {}
        with self._lock:
            n_before = self.remaining
            gen = self._gen
        if self._count_args()[0]:
            self._set_phase("counting")
            seen = self._count(ms, gen)
            if seen is not None:
                n_before = seen
        self._set_phase("thinking")
        t0 = time.monotonic()
        with self._lock:
            hist = list(self.history)
        d = self.brain.decide(n_before, self.count, WORKING, None, history=hist)
        ms["llm"] = _ms(t0)
        if not self._working() or self._gen != gen:
            return None
        with self._lock:
            self.skill = d["skill"]
        started = self._message("robot", d["say"])
        if d["skill"] == "done":
            return self._finish(ms, d, gen)
        ms["speech_wait"] = self._wait_speech(started, gen)
        with self._lock:
            go = self._working() and not self._stop.is_set() and self._gen == gen
            if go:
                self._run_idle.clear()  # 확인과 같은 락 안에서 표시: 재시작이 그 사이로 끼어들지 못한다
        if not go:
            self._log_cycle("estop", ms, d)  # 기다리는 중 중단: 대사만 나가고 동작은 안 했다
            return None
        try:
            return self._act(n_before, ms, d, gen)
        finally:
            self._run_idle.set()

    def _act(self, n_before, ms, d, gen):
        self._set_phase("acting")
        t0 = time.monotonic()
        returning_at = []

        def on_phase(phase):
            if phase == "returning" and not returning_at:
                returning_at.append(time.monotonic())
            self._set_phase(phase)

        try:
            r = self.skills.run(d["skill"], on_phase=on_phase)
        finally:
            self._run_idle.set()  # 동작 끝: 이후 판정·로그는 재시작을 막지 않는다
        total = _ms(t0)
        if returning_at:
            ms["act"] = int((returning_at[0] - t0) * 1000)
            ms["return"] = max(0, total - ms["act"])
        else:
            ms["act"] = total
        if r.stop_reason == "estop":
            with self._lock:
                if self.state != ESTOP and self._gen == gen:  # 새 세션이 시작됐다면 건드리지 않는다
                    self.state, self.phase = ESTOP, "idle"
            self._publish()
            self._log_cycle("estop", ms, d, r)
            return "estop"
        if d["skill"] == "dori_dori":
            with self._lock:
                if self.state != WORKING or self._gen != gen:
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
        return self._judge(n_before, ms, d, r, gen)

    def _count(self, ms, gen):
        """A단계 개수 세기. 실패하면 None (그 사이클은 B로 판정)."""
        t0 = time.monotonic()
        _, only = self._count_args()
        c = self.vision.count(self.skills.latest_frame(self.camera), only=only)
        ms["vision"] = ms.get("vision", 0) + _ms(t0)
        with self._lock:
            if self._gen != gen:  # 세는 동안 세션이 바뀌었다: 이전 세션의 결과로 새 세션을 덮지 않는다
                return None
            if c is None:
                self.vision_method = "estimate"
                return None
            self.remaining, self.vision_method, self.last_boxes = c.n, c.method, c.boxes
        self._publish()
        return c.n

    def count_now(self):
        """"지금 세기": 대기(IDLE)에서만, 고른 방법으로 한 번 센다. 남은 개수·방법·상자만 화면에 올리고
        횟수·피로도·사이클 기록은 건드리지 않는다 (로그에는 type "count"로 남긴다)."""
        with self._lock:
            refused = None
            if self.state != IDLE:
                refused = "대기 상태에서만 지금 세기를 할 수 있어요"
            elif not self._count_args()[0]:
                refused = "개수 세기가 꺼져 있어요" if self.vision else "개수 세기 모델이 설정되지 않았어요"
            elif self._counting_now:
                refused = "이미 세는 중이에요"
            else:
                self._counting_now = True
                gen = self._gen
                _, only = self._count_args()
        if refused:
            self.notify(refused)
            return False
        t0 = time.monotonic()
        c, error = None, None
        try:
            c = self.vision.count(self.skills.latest_frame(self.camera), only=only)
        except Exception as e:   # 프레임을 못 읽는 경우 등
            log.warning("지금 세기 실패: %r", e)
            error = e
        ms = _ms(t0)
        with self._lock:
            self._counting_now = False
            current = self.state == IDLE and self._gen == gen   # 세는 동안 작업이 시작됐다면 그 화면을 덮지 않는다
            if current and c is not None:
                self.remaining, self.vision_method, self.last_boxes = c.n, c.method, c.boxes
                self.last_count = {"n": c.n, "method": c.method, "ms": ms, "ts": self.clock()}
        if c is None:
            self.notify("개수를 세지 못했어요" + (f": {error}" if error else ""))
        elif current:
            self._publish()
        try:
            self._append_log({"ts": self.clock(), "type": "count", "choice": only or "auto",
                              "n": None if c is None else c.n, "method": None if c is None else c.method,
                              "boxes": None if c is None else c.boxes, "ms": ms,
                              "error": None if error is None else str(error)})
        except Exception as e:
            log.warning("개수 로그 기록 실패: %s", e)
        return c is not None

    def _judge(self, n_before, ms, d, r, gen):
        with self._lock:
            aborted = self.state != WORKING or self._gen != gen
        if aborted:
            self._log_cycle("estop", ms, d, r)
            return "estop"
        seen = None
        if self._count_args()[0]:
            self._set_phase("counting")
            seen = self._count(ms, gen)
        success = seen < n_before if seen is not None else r.grasped
        with self._lock:
            aborted = self.state != WORKING or self._gen != gen
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

    def _finish(self, ms, d, gen):
        with self._lock:
            if self.state == WORKING and self._gen != gen:
                return None  # 이전 세션의 done 결정: 새 세션을 끝내지 않는다
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
        self._append_log(record)

    def _append_log(self, record):
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
                        estopped = self.state == ESTOP
                    self.notify("오류가 났어요. 로그를 확인한 뒤 "
                                + ("재시작을 눌러 주세요." if estopped else "재개를 눌러 주세요."))
                    self._publish()
            else:
                try:
                    ran = self.step_test()  # 스킬 테스트도 이 스레드에서만 (두 스레드가 스킬을 부르지 않게)
                except Exception:
                    log.exception("스킬 테스트 처리 실패")
                    ran = None
                if ran is None:
                    self._wake.wait(0.2)
                    self._wake.clear()
