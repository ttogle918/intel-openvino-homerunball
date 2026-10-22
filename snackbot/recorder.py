"""실행 기록: 실제 로봇에서 스킬의 정책 phase 1회마다 관절값과 카메라 프레임을 저장한다.
형식은 녹화 재생과 같다 (snackbot/twin.py의 episode.json, source "run"). physicalai를 import하지 않는다.

logs/runs/<YYYYmmdd-HHMMSS>_<스킬>/episode.json + frames/<카메라>/000000.jpg …
저장된 폴더를 replays/<스킬>/로 복사하면 dry-run 재생에 그대로 쓰인다.

- tick()은 제어 스레드(Tap.on_tick)에서 불린다: 관절은 리스트에 붙이고, 프레임은 frame_fps로 솎아 큐에 넣기만 한다.
  큐가 가득 차면 그 프레임은 버린다 (다음 틱에 다시 시도). JPEG 저장은 백그라운드 스레드가 한다.
- 기록 실패는 경고만 한다. 로봇 동작에는 영향이 없다.
"""
import json
import logging
import queue
import threading
import time
from pathlib import Path

import cv2

from .twin import EPISODE_FILE, safe_name

log = logging.getLogger(__name__)
_STOP = object()
_EPS = 1e-6


def write_jpeg(path, rgb, width):
    """RGB 프레임을 폭 width 이하로 줄여(비율 유지) JPEG로 쓴다."""
    h, w = rgb.shape[:2]
    if w > width:
        rgb = cv2.resize(rgb, (width, max(1, round(h * width / w))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise OSError(f"JPEG 인코딩 실패: {path}")
    Path(path).write_bytes(buf.tobytes())


def _rate(first, last, n, default):
    """n개 표본이 first~last 초에 걸쳐 있으면 초당 개수. 표본이 모자라면 default."""
    if n > 1 and first is not None and last is not None and last > first:
        return round((n - 1) / (last - first), 3)
    return default


class _Session:
    def __init__(self, skill, folder, queue_size):
        self.skill, self.folder = skill, folder
        self.started = time.time()
        self.joints = []
        self.first_t = self.last_t = None
        self.queue = queue.Queue(maxsize=max(1, queue_size))
        self.next_index = 0
        self.first_frame_t = self.last_frame_t = None
        self.counts = {}
        self.dropped = 0
        self.thread = None


class RunRecorder:
    """start(skill) → tick(joints, frames, t)… → stop(result). recording.enabled가 false면 아무것도 하지 않는다."""

    def __init__(self, cfg, writer=write_jpeg, clock=time.localtime):
        rec = cfg.get("recording") or {}
        self.enabled = bool(rec.get("enabled", False))
        self.dir = Path(rec.get("dir", "logs/runs"))
        self.frame_fps = float(rec.get("frame_fps", 10))
        self.frame_width = int(rec.get("frame_width", 640))
        self.queue_size = int(rec.get("queue_size", 64))
        self.fps = float((cfg.get("skills") or {}).get("fps", 30))
        self.writer, self.clock = writer, clock
        self.last_folder = None
        self._session = None
        self._lock = threading.Lock()
        self._threads = []
        self._warned = set()

    def _warn_once(self, key, msg, *args):
        if key not in self._warned:
            self._warned.add(key)
            log.warning(msg, *args)

    def start(self, skill):
        """새 기록 폴더를 만들고 저장 스레드를 띄운다. 꺼져 있거나 실패하면 None."""
        if not self.enabled:
            return None
        try:
            stamp = time.strftime("%Y%m%d-%H%M%S", self.clock())
            base = f"{stamp}_{safe_name(skill)}"
            folder, n = self.dir / base, 2
            while folder.exists():
                folder, n = self.dir / f"{base}_{n}", n + 1
            folder.mkdir(parents=True)
            s = _Session(skill, folder, self.queue_size)
            s.thread = threading.Thread(target=self._worker, args=(s,), name="run-recorder", daemon=True)
            s.thread.start()
        except Exception as e:
            log.warning("실행 기록을 시작하지 못했어요 (%s, 로봇 동작에는 영향 없음): %s", skill, e)
            return None
        with self._lock:
            self._session = s
            self._threads.append(s.thread)
        self.last_folder = folder
        return folder

    def tick(self, joints, frames, t):
        """제어 스레드에서 매 틱 불린다. 막히지 않는다."""
        s = self._session
        if s is None:
            return
        try:
            s.joints.append([round(float(v), 3) for v in joints])
            if s.first_t is None:
                s.first_t = t
            s.last_t = t
            if not frames or (s.last_frame_t is not None and t - s.last_frame_t < 1.0 / self.frame_fps - _EPS):
                return
            try:
                s.queue.put_nowait((s.next_index, dict(frames)))
            except queue.Full:
                s.dropped += 1
                return
            s.next_index += 1
            if s.first_frame_t is None:
                s.first_frame_t = t
            s.last_frame_t = t
        except Exception as e:
            self._warn_once("tick", "실행 기록 중 오류 (로봇 동작에는 영향 없음): %s", e)

    def stop(self, result=None):
        """기록을 끝낸다. episode.json은 저장 스레드가 남은 프레임을 다 쓴 뒤에 쓴다 (기다리지 않는다)."""
        with self._lock:
            s, self._session = self._session, None
        if s is None:
            return None
        meta = {"stop_reason": getattr(result, "stop_reason", None),
                "grasped": bool(getattr(result, "grasped", False)), "ms": getattr(result, "ms", None)}
        try:
            s.queue.put((_STOP, meta), timeout=5)
        except Exception as e:
            log.warning("실행 기록을 마무리하지 못했어요: %s (%s)", s.folder, e)
        return s.folder

    def wait(self, timeout=None):
        """저장 스레드가 끝날 때까지 기다린다 (테스트·종료용)."""
        with self._lock:
            threads, self._threads = self._threads, []
        for t in threads:
            t.join(timeout)

    def _worker(self, s):
        while True:
            index, item = s.queue.get()
            if index is _STOP:
                self._finish(s, item)
                return
            for cam, rgb in item.items():
                try:
                    folder = s.folder / "frames" / safe_name(cam)
                    folder.mkdir(parents=True, exist_ok=True)
                    self.writer(folder / f"{index:06d}.jpg", rgb, self.frame_width)
                    s.counts[cam] = index + 1
                except Exception as e:
                    self._warn_once(("frame", cam), "실행 기록 프레임 저장 실패 (%s): %s", cam, e)

    def _finish(self, s, meta):
        frame_fps = _rate(s.first_frame_t, s.last_frame_t, s.next_index, self.frame_fps)
        doc = {"skill": s.skill, "source": "run", "fps": _rate(s.first_t, s.last_t, len(s.joints), self.fps),
               "joints": s.joints,
               "cameras": {cam: {"frames": f"frames/{safe_name(cam)}", "fps": frame_fps, "count": n}
                           for cam, n in s.counts.items()},
               "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(s.started)),
               "dropped_frames": s.dropped, **meta}
        try:
            tmp = s.folder / (EPISODE_FILE + ".part")
            tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            tmp.replace(s.folder / EPISODE_FILE)
        except Exception as e:
            log.warning("실행 기록 episode.json 저장 실패: %s (%s)", s.folder, e)
