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
    c["dry_run"]["samples_dir"] = str(tmp_path / "samples")
    c["logging"]["dir"] = str(tmp_path / "logs")
    return c
