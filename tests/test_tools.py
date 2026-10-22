from tools.fetch_calibration import find_follower

CAL = {"shoulder_pan": {"id": 1, "drive_mode": 0, "homing_offset": -1983, "range_min": 0, "range_max": 4095}}
DOC = {
    "class_path": "physicalai.runtime.RobotRuntime",
    "init_args": {
        "robot": {"class_path": "physicalai.robot.SharedRobot", "init_args": {"name": "x", "robot": {
            "class_path": "physicalai_so101_plugin.SO101",
            "init_args": {"port": "/dev/ttyACM1", "calibration": CAL, "role": "follower", "unit": "normalized"}}}},
        "action_source": {"class_path": "physicalai.runtime.TeleopSource", "init_args": {"leader": {
            "class_path": "physicalai.robot.SharedRobot", "init_args": {"robot": {
                "class_path": "physicalai_so101_plugin.SO101",
                "init_args": {"port": "/dev/ttyACM0", "calibration": {"other": 1}, "role": "leader"}}}}}},
    },
}


def test_find_follower_inside_shared_robot():
    found = find_follower(DOC)
    assert found["calibration"] == CAL and found["port"] == "/dev/ttyACM1"


def test_find_follower_none():
    assert find_follower({"init_args": {"robot": {"class_path": "x.Other"}}}) is None
    assert find_follower([{"a": 1}]) is None


def test_fetch_calibration_main_get_only(tmp_path, monkeypatch, capsys):
    import httpx
    import yaml

    from tools import fetch_calibration

    seen = []

    def handler(request):
        seen.append((request.method, str(request.url)))
        return httpx.Response(200, text=yaml.safe_dump(DOC))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(fetch_calibration.httpx, "get", lambda url, **kw: client.get(url, **kw))
    out = tmp_path / "cal.yaml"
    fetch_calibration.main(["--studio", "http://studio:7860/", "--project", "p1", "--env", "e1", "--out", str(out)])
    assert seen == [("GET", "http://studio:7860/api/projects/p1/environments/e1/runtime-config")]
    assert yaml.safe_load(out.read_text(encoding="utf-8")) == CAL


def test_robot_probe_save_averages_and_disconnects(tmp_path, monkeypatch):
    import numpy as np
    import yaml

    from tools import robot_probe

    class Obs:
        joint_positions = np.array([1, 2, 3, 4, 5, 6.0])

    class FakeRobot:
        disconnected = False

        def get_observation(self):
            return Obs()

        def disconnect(self):
            self.disconnected = True

    robot = FakeRobot()
    poses = tmp_path / "poses.yaml"
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"poses_file": str(poses), "robot": {}}), encoding="utf-8")
    monkeypatch.setattr(robot_probe, "open_robot", lambda c: robot)
    robot_probe.main(["save", "home", "--config", str(cfg)])
    assert yaml.safe_load(poses.read_text(encoding="utf-8"))["home_pose"] == [1, 2, 3, 4, 5, 6]
    assert robot.disconnected
