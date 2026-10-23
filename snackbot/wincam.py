"""Windows 카메라 목록 보정 (pynokhwa 0.1.4 JSON 이스케이프 버그).

pynokhwa.query()는 장치 meta를 json.loads 하는데, Windows(MediaFoundation)의 symlink에는
역슬래시가 이스케이프 없이 들어 있어 JSONDecodeError가 난다.
설치된 패키지는 고치지 않고(CLAUDE.md 6번), 모듈 속성 query만 교체한다.
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

_PATCHED = "_snackbot_wincam_patched"


def _load_meta(s):
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return json.loads(s.replace("\\", "\\\\"))


def patch_camera_query() -> bool:
    """pynokhwa.query를 보정판으로 교체. 한 번만 적용하고, pynokhwa가 없으면 조용히 False."""
    try:
        import pynokhwa
    except ImportError:
        return False
    if getattr(pynokhwa, _PATCHED, False):
        return True
    native = pynokhwa.pynokhwa.query

    def query(only_usable=True):
        res = [pynokhwa.CameraInfo(*x[:-1], _load_meta(x[-1])) for x in native()]
        if only_usable:
            res = [r for r in res if r.can_open()]
        return res

    pynokhwa.query = query
    setattr(pynokhwa, _PATCHED, True)
    log.info("pynokhwa.query 보정 적용 (Windows symlink 역슬래시)")
    return True
