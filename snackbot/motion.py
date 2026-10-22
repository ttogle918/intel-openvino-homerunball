"""로봇 동작 보조. physicalai를 import하지 않는다 (개발 PC에서 테스트한다).

- MoveSource / Switch: RobotRuntime의 action_source 규약 (connect(bus, session_id) · update · disconnect)
- Tap: RobotRuntime 콜백 (on_tick)
- StopAny: RobotRuntime.run(stop_event=...)에 넘기는 정지 신호 (is_set)
"""
import threading

import numpy as np

GRIPPER = 5   # 관절 순서의 마지막. 0..100, 작을수록 닫힘


def plan_path(start, targets, steps):
    path, prev = [], np.asarray(start, np.float32)
    for target in targets:
        target = np.asarray(target, np.float32)
        for k in range(1, steps + 1):
            path.append(prev + (target - prev) * (k / steps))
        prev = target
    return path


class MoveSource:
    """현재 자세에서 targets를 차례로 선형 보간해 보낸다. 마지막 점을 보낼 때 done을 set하고 그 점을 유지한다."""

    def __init__(self, targets, steps):
        self.targets = [np.asarray(t, np.float32) for t in targets]
        self.steps = max(1, int(steps))
        self.done = threading.Event()
        self._path, self._i = None, 0

    def connect(self, *, bus=None, session_id=None):
        self._path, self._i = None, 0
        self.done.clear()

    def update(self, robot_state, camera_frames, step):
        if self._path is None:
            self._path = plan_path(robot_state.joint_positions, self.targets, self.steps)
        last = len(self._path) - 1
        action = self._path[min(self._i, last)]
        if self._i >= last:
            self.done.set()
        self._i += 1
        return action

    def disconnect(self):
        pass


class GripperWatch:
    """닫힘(< closed_below)을 한 번 본 뒤 열림(> open_above)이 hold_s 이상 이어지면 done.
    닫힘 구간의 최솟값이 grasp_min 이상이면 과자를 쥔 것 (빈 그리퍼는 끝까지 닫힌다)."""

    def __init__(self, closed_below, open_above, grasp_min, hold_s=0.5):
        self.closed_below, self.open_above = closed_below, open_above
        self.grasp_min, self.hold_s = grasp_min, hold_s
        self.done = threading.Event()
        self.reset()

    def reset(self):
        self.closed_seen = False
        self.min_closed = None
        self._open_since = None
        self.done.clear()

    @property
    def grasped(self):
        return self.min_closed is not None and self.min_closed >= self.grasp_min

    def update(self, gripper, t):
        if gripper < self.closed_below:
            self.closed_seen = True
            self.min_closed = gripper if self.min_closed is None else min(self.min_closed, gripper)
            self._open_since = None
        elif self.closed_seen and gripper > self.open_above:
            if self._open_since is None:
                self._open_since = t
            elif t - self._open_since >= self.hold_s:
                self.done.set()
        else:
            self._open_since = None


class StopAny:
    def __init__(self, *events):
        self.events = [e for e in events if e is not None]

    def is_set(self):
        return any(e.is_set() for e in self.events)


def remap_frames(camera_frames, camera_map):
    """원래 키는 그대로 두고, {학습 이름: config 이름}의 학습 이름 키를 더한다 (모델은 필요한 키만 쓴다)."""
    frames = dict(camera_frames)
    for trained, cam in (camera_map or {}).items():
        if cam in camera_frames:
            frames[trained] = camera_frames[cam]
    return frames


class Switch:
    """RobotRuntime에는 이것 하나만 꽂고, run()마다 active(와 camera_map)를 바꿔 낀다."""

    def __init__(self):
        self.active = None
        self.camera_map = None

    def connect(self, *, bus, session_id):
        self.active.connect(bus=bus, session_id=session_id)

    def update(self, robot_state, camera_frames, step):
        return self.active.update(robot_state, remap_frames(camera_frames, self.camera_map), step)

    def disconnect(self):
        self.active.disconnect()


class Tap:
    """매 틱 관절값과 카메라 프레임을 저장하고, watch가 있으면 그리퍼 값을 넘긴다."""

    def __init__(self):
        self.lock = threading.Lock()
        self.joints = None
        self.frames = {}
        self.watch = None

    def on_tick(self, event):
        joints = np.asarray(event.robot_state.joint_positions, np.float32).copy()
        with self.lock:
            self.joints = joints
            for name, frame in event.camera_frames.items():
                self.frames[name] = frame.data
        watch = self.watch
        if watch is not None:
            watch.update(float(joints[GRIPPER]), event.timestamp)
