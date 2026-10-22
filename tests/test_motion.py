import threading
from types import SimpleNamespace

import numpy as np

from snackbot.motion import GRIPPER, GripperWatch, MoveSource, StopAny, Switch, Tap, plan_path, remap_frames


def state(values):
    return SimpleNamespace(joint_positions=np.asarray(values, np.float32))


def feed(watch, values, dt=0.1):
    for i, v in enumerate(values):
        watch.update(v, i * dt)


def test_plan_path_linear_segments():
    path = plan_path([0] * 6, [[10] * 6, [10, 0, 0, 0, 0, 0]], 2)
    assert len(path) == 4
    np.testing.assert_allclose(path[0], [5] * 6)
    np.testing.assert_allclose(path[1], [10] * 6)
    np.testing.assert_allclose(path[3], [10, 0, 0, 0, 0, 0])


def test_move_source_walks_path_holds_last_and_sets_done():
    src = MoveSource([[6] * 6], steps=3)
    src.connect(bus=None, session_id="s")
    first = src.update(state([0] * 6), {}, 0)
    assert not src.done.is_set()
    out = [first] + [src.update(state([0] * 6), {}, i) for i in range(1, 5)]
    np.testing.assert_allclose(out[0], [2] * 6)
    np.testing.assert_allclose(out[2], [6] * 6)
    np.testing.assert_allclose(out[4], [6] * 6)
    assert src.done.is_set()
    src.connect(bus=None, session_id="again")
    assert not src.done.is_set()
    np.testing.assert_allclose(src.update(state([3] * 6), {}, 0), [4] * 6)


def test_gripper_watch_needs_close_before_open():
    w = GripperWatch(closed_below=30, open_above=60, grasp_min=15, hold_s=0.5)
    feed(w, [80] * 10)
    assert not w.done.is_set() and not w.closed_seen


def test_gripper_watch_snack_grasp_then_release():
    w = GripperWatch(30, 60, 15, 0.5)
    feed(w, [80, 50, 25, 24, 25, 70, 80, 80, 80, 80, 80, 80])
    assert w.done.is_set() and w.grasped and w.min_closed == 24


def test_gripper_watch_empty_grasp():
    w = GripperWatch(30, 60, 15, 0.5)
    feed(w, [80, 5, 3, 80, 80, 80, 80, 80, 80, 80])
    assert w.done.is_set() and not w.grasped


def test_gripper_watch_open_must_be_held_and_reset():
    w = GripperWatch(30, 60, 15, 0.5)
    feed(w, [20, 80, 80, 50, 80, 80, 80])
    assert not w.done.is_set()
    w.reset()
    assert w.min_closed is None and not w.closed_seen and not w.grasped


def test_stop_any():
    a, b = threading.Event(), threading.Event()
    s = StopAny(a, None, b)
    assert not s.is_set()
    b.set()
    assert s.is_set()


def test_switch_delegates_to_active():
    calls = []

    class Src:
        def connect(self, *, bus, session_id):
            calls.append(("connect", session_id))

        def update(self, robot_state, camera_frames, step):
            return step

        def disconnect(self):
            calls.append(("disconnect",))

    sw = Switch()
    sw.active = Src()
    sw.connect(bus=None, session_id="x")
    assert sw.update(None, {}, 7) == 7
    sw.disconnect()
    assert calls == [("connect", "x"), ("disconnect",)]


def test_switch_passes_frames_under_trained_names():
    seen = {}

    class Src:
        def update(self, robot_state, camera_frames, step):
            seen.update(camera_frames)
            return step

    sw = Switch()
    sw.active, sw.camera_map = Src(), {"A": "tower cam"}
    sw.update(None, {"tower cam": "t", "follow cam": "f"}, 0)
    assert seen == {"tower cam": "t", "follow cam": "f", "A": "t"}


def test_remap_frames():
    assert remap_frames({"x": 1}, None) == {"x": 1}
    assert remap_frames({"x": 1, "y": 2}, {"B": "y", "Z": "missing"}) == {"x": 1, "y": 2, "B": 2}


def test_tap_caches_state_frames_and_feeds_watch():
    tap, w = Tap(), GripperWatch(30, 60, 15, 0.5)
    tap.watch = w
    frame = np.zeros((2, 2, 3), np.uint8)
    tap.on_tick(SimpleNamespace(robot_state=state([1, 2, 3, 4, 5, 20]),
                                camera_frames={"tower cam": SimpleNamespace(data=frame)}, timestamp=0.0))
    assert tap.joints[GRIPPER] == 20 and tap.frames["tower cam"] is frame and w.closed_seen
