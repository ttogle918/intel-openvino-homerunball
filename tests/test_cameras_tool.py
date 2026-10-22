from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from tools import cameras


class FakeCam:
    def __init__(self, device, fail):
        self.device, self.fail, self.disconnected = device, fail, False

    def connect(self, timeout=5.0):
        if self.fail:
            raise RuntimeError("busy")

    def read(self, timeout=2.0):
        img = np.zeros((48, 64, 3), np.uint8)
        img[:, :, 0] = 255                       # RGB 빨강
        return SimpleNamespace(data=img)

    def disconnect(self):
        self.disconnected = True


def test_cameras_lists_saves_and_prints_config(tmp_path, monkeypatch, capsys):
    infos = [SimpleNamespace(index=0, name="HD Cam", hardware_payload={"serial": "ABC123"}),
             SimpleNamespace(index=2, name="", hardware_payload=None)]
    opened = []

    def open_camera(device, width, height):
        cam = FakeCam(device, fail=device == 2)
        opened.append(cam)
        return cam

    monkeypatch.setattr(cameras, "discover", lambda: infos)
    monkeypatch.setattr(cameras, "open_camera", open_camera)
    cameras.main(["--out", str(tmp_path / "cams")])
    out = capsys.readouterr().out
    img = cv2.imread(str(tmp_path / "cams" / "0.jpg"))
    assert img is not None and img[0, 0, 2] > 200          # RGB → BGR로 저장: 빨강은 마지막 채널
    assert not (tmp_path / "cams" / "2.jpg").exists()
    assert "[0] HD Cam" in out and "ABC123" in out and "(이름 없음)" in out
    assert "열지 못함" in out and "busy" in out
    assert 'cam0: {device: {serial: "ABC123"}, width: 1280, height: 720, fps: 30}' in out
    assert "cam2: {device: 2, width: 1280, height: 720, fps: 30}" in out
    assert len(opened) == 2 and all(c.disconnected for c in opened)


def test_cameras_without_physicalai_exits(monkeypatch):
    def missing():
        raise ImportError("No module named 'physicalai'")

    monkeypatch.setattr(cameras, "discover", missing)
    with pytest.raises(SystemExit, match="physicalai"):
        cameras.main([])


def test_cameras_none_found(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cameras, "discover", lambda: [])
    cameras.main(["--out", str(tmp_path / "c")])
    assert "찾지 못했어요" in capsys.readouterr().out
