import json
from pathlib import Path

from snackbot.config import load_config, load_env, load_poses, save_pose

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


def test_robot_sections_cover_policy_cameras():
    cfg = load_config(ROOT / "config.yaml")
    assert {"tower cam", "side cam", "follow cam"} <= set(cfg["cameras"])
    assert cfg["vision"]["camera"] in cfg["cameras"]
    for name in ("oranda_pickup", "dori_dori"):
        manifest = ROOT / cfg["skills"][name]["export_dir"] / "manifest.json"
        if not manifest.exists():
            continue  # 학습 결과물은 git에 없다 (있는 PC에서만 확인)
        features = json.loads(manifest.read_text(encoding="utf-8"))["model"]["input_features"]
        trained = {f["init_args"]["name"].removeprefix("images.") for f in features
                   if f["init_args"]["ftype"] == "VISUAL"}
        camera_map = cfg["skills"][name].get("camera_map") or {}
        # 정책이 쓰는 카메라(학습 이름 → camera_map → config 이름)는 모두 config에 있어야 한다
        assert {camera_map.get(cam, cam) for cam in trained} <= set(cfg["cameras"]), name


def test_poses_roundtrip(tmp_path):
    p = tmp_path / "poses.yaml"
    assert load_poses(p) == {}
    save_pose(p, "home_pose", [1.234, 2, 3, 4, 5, 6.789])
    save_pose(p, "lift_pose", [0] * 6)
    assert load_poses(p) == {"home_pose": [1.23, 2.0, 3.0, 4.0, 5.0, 6.79], "lift_pose": [0.0] * 6}
