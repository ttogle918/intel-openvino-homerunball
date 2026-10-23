import socket
import sys

if sys.platform == "win32":     # 루프백을 가로채는 소프트웨어 때문에 socketpair가 가끔 WinError 10014로 실패한다
    _socketpair = socket.socketpair

    def _retry_socketpair(*a, **k):
        for i in range(5):
            try:
                return _socketpair(*a, **k)
            except OSError as e:
                if getattr(e, "winerror", None) != 10014 or i == 4:
                    raise

    socket.socketpair = _retry_socketpair

import copy
from pathlib import Path

import pytest

from snackbot.config import load_config

ROOT = Path(__file__).resolve().parents[1]


class FirstRng:
    """테스트용: 항상 첫 번째 후보를 고른다."""

    def choice(self, seq):
        return seq[0]


@pytest.fixture
def cfg(tmp_path):
    c = copy.deepcopy(load_config(ROOT / "config.yaml"))
    c["dry_run"]["act_s"] = 0
    c["vision"]["frames"] = 1          # 테스트의 가짜 counter는 호출마다 값을 하나씩 쓴다 (다중 프레임은 전용 테스트)
    c["skills"]["dori_dori"]["source"] = "auto"   # 현장 config(script)와 무관하게 기본 동작으로 시험한다
    c["dry_run"]["samples_dir"] = str(tmp_path / "samples")
    c["logging"]["dir"] = str(tmp_path / "logs")
    c["replays_dir"] = str(tmp_path / "replays")
    c["recording"]["dir"] = str(tmp_path / "runs")
    return c
