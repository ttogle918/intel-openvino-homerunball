import json
from pathlib import Path

from snackbot.config import load_config, load_env, load_poses, save_pose, ui_tiles

ROOT = Path(__file__).resolve().parents[1]


def test_repo_config_has_core_sections():
    cfg = load_config(ROOT / "config.yaml")
    assert cfg["target"] == {"name": "오란다", "robot_name": "보리", "initial_count": 3}
    assert cfg["decision"] == {"refuse": "half", "safe_max": 3, "force_refuse": 6, "max_retry": 1}
    for entry in cfg["brain"]["chain"]:
        assert entry["provider"] in cfg["providers"]
        assert entry.get("model")
    assert [e["type"] for e in cfg["vision"]["chain"]] == ["opencv"]   # 노트북 tower cam 현장 튜닝 (roi)
    assert [e["provider"] for e in cfg["stt"]["chain"]] == ["local_ov", "gemini"]


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


def test_save_pose_keeps_header_comments(tmp_path):
    p = tmp_path / "poses.yaml"
    p.write_text("# 환경: Windows 노트북\n\n# 다시 저장: robot_probe save home\nhome_pose: [0, 0, 0, 0, 0, 0]\n", encoding="utf-8")
    save_pose(p, "lift_pose", [1] * 6)
    text = p.read_text(encoding="utf-8")
    assert text.startswith("# 환경: Windows 노트북\n\n# 다시 저장: robot_probe save home\n")
    assert load_poses(p) == {"home_pose": [0] * 6, "lift_pose": [1.0] * 6}


def test_ui_tiles_default_and_custom():
    cfg = {"cameras": {"tower cam": {}, "follow cam": {}}}
    assert ui_tiles(cfg) == [
        {"kind": "camera", "name": "tower cam", "available": True},
        {"kind": "camera", "name": "side cam", "available": False},
        {"kind": "camera", "name": "follow cam", "available": True},
        {"kind": "twin", "name": "3D"},
    ]
    cfg["ui"] = {"tiles": ["twin", {"iframe": "http://studio:7860", "name": "Studio"}, "follow cam"]}
    assert ui_tiles(cfg) == [{"kind": "twin", "name": "3D"},
                             {"kind": "iframe", "name": "Studio", "url": "http://studio:7860"},
                             {"kind": "camera", "name": "follow cam", "available": True}]


def test_config_has_twin_sections():
    cfg = load_config(ROOT / "config.yaml")
    assert ui_tiles(cfg)[3] == {"kind": "twin", "name": "3D"}
    assert cfg["twin"]["urdf"] == "twin/so101/so101_new_calib.urdf"
    assert len(cfg["twin"]["sign"]) == 6 and len(cfg["twin"]["offset_deg"]) == 6
    assert cfg["replays_dir"] == "replays" and cfg["recording"]["dir"] == "logs/runs"
    for name in ("oranda_pickup", "dori_dori"):
        assert set(cfg["skills"][name]["replay"]) == {"dataset", "episode"}


def test_config_dori_script_defaults():
    dori = load_config(ROOT / "config.yaml")["skills"]["dori_dori"]
    assert dori["source"] in ("auto", "policy", "script")   # 현장 값 (2026-10-23 실기: script), 형식만 확인
    assert dori["script"] == {"joint": "shoulder_pan", "amplitude": 15, "shakes": 2, "shake_s": 0.35}
