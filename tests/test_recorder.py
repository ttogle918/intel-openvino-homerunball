import json
import threading
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from snackbot.recorder import RunRecorder, write_jpeg
from snackbot.twin import load_episode

FRAME = np.zeros((480, 1280, 3), np.uint8)


def rec_cfg(tmp_path, **rec):
    return {"skills": {"fps": 30}, "recording": {"enabled": True, "dir": str(tmp_path / "runs"), "frame_fps": 10,
                                                 "frame_width": 320, **rec}}


def result(reason="gripper_open", grasped=True):
    return SimpleNamespace(stop_reason=reason, grasped=grasped, ms=1234)


def feed(rec, n, cams=("tower cam", "follow cam"), fps=30):
    for i in range(n):
        rec.tick(np.full(6, i, np.float32), {c: FRAME for c in cams}, i / fps)


def test_records_joints_every_tick_and_thins_frames(tmp_path):
    rec = RunRecorder(rec_cfg(tmp_path))
    folder = rec.start("dori_dori")
    feed(rec, 31)                                    # 1초, 30Hz
    rec.stop(result("timeout", False))
    rec.wait(5)
    ep = load_episode(folder)
    assert folder.parent == tmp_path / "runs" and folder.name.endswith("_dori_dori")
    assert ep["source"] == "run" and ep["skill"] == "dori_dori"
    assert (ep["stop_reason"], ep["grasped"], ep["ms"]) == ("timeout", False, 1234)
    assert len(ep["joints"]) == 31 and ep["joints"][5] == [5.0] * 6
    assert ep["fps"] == pytest.approx(30)
    assert ep["cameras"]["tower cam"] == {"frames": "frames/tower_cam", "fps": pytest.approx(10), "count": 11}
    jpg = folder / "frames" / "follow_cam" / "000010.jpg"
    assert cv2.imread(str(jpg)).shape == (120, 320, 3)   # frame_width로 줄임 (비율 유지)


def test_tick_does_not_wait_for_slow_writer(tmp_path):
    gate = threading.Event()

    def slow(path, rgb, width):
        gate.wait(5)
        write_jpeg(path, rgb, width)

    rec = RunRecorder(rec_cfg(tmp_path), writer=slow)
    folder = rec.start("oranda_pickup")
    t0 = time.monotonic()
    feed(rec, 30)
    assert time.monotonic() - t0 < 0.5                 # 저장은 백그라운드 스레드
    gate.set()
    rec.stop(result())
    rec.wait(5)
    assert load_episode(folder)["cameras"]["tower cam"]["count"] == 10


def test_full_queue_drops_frames_without_blocking(tmp_path):
    gate = threading.Event()
    rec = RunRecorder(rec_cfg(tmp_path, queue_size=2), writer=lambda p, rgb, w: gate.wait(5))
    folder = rec.start("dori_dori")
    t0 = time.monotonic()
    feed(rec, 90)                                      # 프레임 30번 시도, 큐 2칸
    assert time.monotonic() - t0 < 0.5
    gate.set()
    rec.stop(result())
    rec.wait(5)
    ep = json.loads((folder / "episode.json").read_text(encoding="utf-8"))
    assert ep["dropped_frames"] > 0
    assert len(ep["joints"]) == 90                     # 관절은 버리지 않는다


def test_writer_failure_only_warns(tmp_path, caplog):
    def boom(path, rgb, width):
        raise OSError("disk full")

    rec = RunRecorder(rec_cfg(tmp_path), writer=boom)
    folder = rec.start("dori_dori")
    with caplog.at_level("WARNING"):
        feed(rec, 10)
        rec.stop(result())
        rec.wait(5)
    ep = json.loads((folder / "episode.json").read_text(encoding="utf-8"))
    assert ep["cameras"] == {} and len(ep["joints"]) == 10
    assert caplog.text.count("disk full") == 2          # 카메라마다 한 번만


def test_start_failure_and_disabled_do_nothing(tmp_path, caplog):
    (tmp_path / "runs").write_text("폴더가 아니라 파일", encoding="utf-8")
    rec = RunRecorder(rec_cfg(tmp_path))
    with caplog.at_level("WARNING"):
        assert rec.start("dori_dori") is None
    assert "실행 기록을 시작하지 못했어요" in caplog.text
    feed(rec, 5)
    assert rec.stop(result()) is None

    off = RunRecorder(rec_cfg(tmp_path / "b", enabled=False))
    assert off.start("dori_dori") is None
    feed(off, 5)
    off.stop(result())
    assert not (tmp_path / "b").exists() and off.last_folder is None


def test_same_second_runs_get_distinct_folders(tmp_path):
    rec = RunRecorder(rec_cfg(tmp_path), clock=lambda: time.struct_time((2026, 10, 22, 13, 0, 0, 3, 295, 0)))
    a = rec.start("dori_dori")
    rec.stop(result())
    b = rec.start("dori_dori")
    rec.stop(result())
    rec.wait(5)
    assert a.name == "20261022-130000_dori_dori" and b.name == "20261022-130000_dori_dori_2"


def test_stop_returns_immediately_when_writer_stuck_and_queue_full(tmp_path):
    gate = threading.Event()
    rec = RunRecorder(rec_cfg(tmp_path, queue_size=2), writer=lambda p, rgb, w: gate.wait(5))
    folder = rec.start("dori_dori")
    feed(rec, 90)
    t0 = time.monotonic()
    rec.stop(result())
    assert time.monotonic() - t0 < 0.5
    gate.set()
    rec.wait(5)
    assert (folder / "episode.json").exists()          # 마감 신호는 반드시 전달된다


def test_frame_thinning_survives_tick_jitter(tmp_path):
    rec = RunRecorder(rec_cfg(tmp_path, queue_size=500))   # 합성 틱은 한꺼번에 들어오므로 큐를 넉넉히
    folder = rec.start("dori_dori")
    rng = np.random.default_rng(0)
    for i in range(301):                                # 10초, 30Hz에 +-2ms 지터
        rec.tick(np.zeros(6, np.float32), {"tower cam": FRAME}, i / 30 + rng.uniform(-0.002, 0.002))
    rec.stop(result())
    rec.wait(5)
    assert load_episode(folder)["cameras"]["tower cam"]["count"] >= 98   # 10fps -> 약 100장


def test_queued_frames_are_copies(tmp_path):
    seen = []
    rec = RunRecorder(rec_cfg(tmp_path), writer=lambda p, rgb, w: seen.append(rgb))
    rec.start("dori_dori")
    buf = np.zeros((4, 4, 3), np.uint8)
    rec.tick(np.zeros(6), {"c": buf}, 0.0)
    buf[:] = 9                                          # 드라이버가 버퍼를 재사용
    rec.stop(result())
    rec.wait(5)
    assert seen and seen[0].max() == 0


def test_warned_resets_per_run_and_empty_session_leaves_nothing(tmp_path, caplog):
    def boom(path, rgb, width):
        raise OSError("disk full")

    rec = RunRecorder(rec_cfg(tmp_path), writer=boom)
    with caplog.at_level("WARNING"):
        for _ in range(2):
            rec.start("dori_dori")
            feed(rec, 3, cams=("a",))
            rec.stop(result())
            rec.wait(5)
    assert caplog.text.count("disk full") == 2          # run마다 한 번씩
    empty = rec.start("dori_dori")
    rec.stop(result())
    rec.wait(5)
    assert not empty.exists() and rec.last_folder is None


def test_wait_shares_one_deadline_and_prunes_threads(tmp_path):
    gate = threading.Event()
    rec = RunRecorder(rec_cfg(tmp_path), writer=lambda p, rgb, w: gate.wait(5))
    for _ in range(3):
        rec.start("dori_dori")
        feed(rec, 3, cams=("a",))
        rec.stop(result())
    t0 = time.monotonic()
    rec.wait(0.3)
    assert time.monotonic() - t0 < 0.8                  # 스레드 3개여도 0.3초 안팎
    gate.set()
    rec.wait(5)
    rec.start("dori_dori")
    rec.stop(result())
    rec.wait(5)
    assert rec._threads == []
