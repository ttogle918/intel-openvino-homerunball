import sys
import types

import pytest

from snackbot import wincam

BS = chr(92)
# 역슬래시가 이스케이프되지 않은 Windows 형식 meta
WIN_META = '{"symlink": "' + BS * 2 + "?" + BS + "usb#vid_01da&pid_5875&mi_00#6&312a74&0&0000#{e5}" + BS + 'global"}'
OK_META = '{"symlink": "/dev/video0"}'


class FakeInfo:
    def __init__(self, index, name, meta):
        self.index, self.name, self.meta = index, name, meta

    def can_open(self):
        return self.index != 1


def _fake(monkeypatch, raw):
    mod = types.ModuleType("pynokhwa")
    inner = types.ModuleType("pynokhwa.pynokhwa")
    inner.query = lambda: raw
    mod.pynokhwa = inner
    mod.CameraInfo = FakeInfo
    mod.query = lambda only_usable=True: (_ for _ in ()).throw(AssertionError("원본 호출"))
    monkeypatch.setitem(sys.modules, "pynokhwa", mod)
    return mod


def test_windows_meta_parsed(monkeypatch):
    mod = _fake(monkeypatch, [(0, "cam", WIN_META)])
    assert wincam.patch_camera_query() is True
    info = mod.query()[0]
    assert info.meta["symlink"].startswith(BS * 2 + "?" + BS + "usb#vid_01da")
    assert info.meta["symlink"].endswith(BS + "global")


def test_valid_json_unchanged(monkeypatch):
    mod = _fake(monkeypatch, [(0, "cam", OK_META)])
    wincam.patch_camera_query()
    assert mod.query()[0].meta == {"symlink": "/dev/video0"}


def test_only_usable_filter(monkeypatch):
    mod = _fake(monkeypatch, [(0, "a", OK_META), (1, "b", OK_META)])
    wincam.patch_camera_query()
    assert [i.index for i in mod.query()] == [0]
    assert [i.index for i in mod.query(only_usable=False)] == [0, 1]


def test_idempotent(monkeypatch):
    mod = _fake(monkeypatch, [(0, "a", OK_META)])
    wincam.patch_camera_query()
    first = mod.query
    assert wincam.patch_camera_query() is True
    assert mod.query is first


def test_missing_pynokhwa(monkeypatch):
    monkeypatch.setitem(sys.modules, "pynokhwa", None)
    assert wincam.patch_camera_query() is False
