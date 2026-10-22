from pathlib import Path

from snackbot.config import load_config, load_env

ROOT = Path(__file__).resolve().parents[1]


def test_repo_config_has_core_sections():
    cfg = load_config(ROOT / "config.yaml")
    assert cfg["target"] == {"name": "오란다", "initial_count": 3}
    assert cfg["decision"] == {"safe_max": 3, "force_refuse": 6, "max_retry": 2}
    assert cfg["brain"]["chain"] == []
    assert cfg["vision"]["chain"] == []
    assert cfg["stt"]["chain"] == []


def test_load_env_reads_file_and_environment_wins(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text('# 주석\nA=1\nB="x y"\nC=file\n\nBROKEN\n', encoding="utf-8")
    monkeypatch.setenv("C", "env")
    env = load_env(p)
    assert env["A"] == "1"
    assert env["B"] == "x y"
    assert env["C"] == "env"
    assert "BROKEN" not in env


def test_load_env_missing_file_is_ok(tmp_path):
    assert isinstance(load_env(tmp_path / "none.env"), dict)
