import json
import math

import pytest

from snackbot.twin import (DEFAULT_URDF, JOINTS, episode_duration, list_replays, load_episode, make_converter,
                           normalized_to_ticks, replay_payload, safe_name, to_radians)

CAL = {   # physicalai SO101 캘리브레이션 꼴 (대표 값)
    "shoulder_pan": {"id": 1, "drive_mode": 0, "homing_offset": -1983, "range_min": 700, "range_max": 3400},
    "gripper": {"id": 6, "drive_mode": 0, "homing_offset": 1000, "range_min": 2000, "range_max": 3500},
    "wrist_roll": {"id": 5, "drive_mode": 0, "homing_offset": 2100, "range_min": 2000, "range_max": 2000},
}
TICK = 2 * math.pi / 4096


def ep_doc(**kw):
    doc = {"skill": "dori_dori", "source": "run", "fps": 10, "joints": [[0] * 6, [10] * 6, [20] * 6, [30] * 6],
           "cameras": {"tower cam": {"video": "tower_cam.mp4", "start": 12.5, "end": 12.9},
                       "follow cam": {"frames": "frames/follow_cam", "fps": 5, "count": 2}}}
    doc.update(kw)
    return doc


def write_ep(folder, doc):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "episode.json").write_text(json.dumps(doc), encoding="utf-8")
    return folder


def test_joint_names_match_urdf():
    assert JOINTS == ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
    assert DEFAULT_URDF == "twin/so101/so101_new_calib.urdf"


def test_ticks_match_physicalai_formula():
    # physicalai SO101._normalized_to_ticks: 몸통 lo + (v+100)/200*rng, 그리퍼 lo + v/100*rng, round 뒤 범위로 자름
    ticks = normalized_to_ticks([10, 0, 0, 0, 0, 30], CAL)
    assert ticks[0] == 2185          # 700 + 110/200*2700
    assert ticks[5] == 2450          # 2000 + 0.3*1500
    assert ticks[4] == 2000          # range가 0이면 homing_offset을 범위로 자른 값
    assert ticks[1] == 2048          # 캘리브레이션 없는 관절: 0..4095에서 0 → 2047.5 → round → 2048


def test_ticks_clip_out_of_range_values():
    assert normalized_to_ticks([150, -150, 0, 0, 0, 120]) == [4095, 0, 2048, 2048, 2048, 4095]
    assert normalized_to_ticks([0, 0, 0, 0, 0, -5])[5] == 0


def test_to_radians_default_range():
    q = to_radians([0, 100, -100, 0, 0, 50])
    assert q[0] == 0
    assert q[1] == pytest.approx((4095 - 2048) * TICK)
    assert q[2] == pytest.approx(-math.pi)
    assert q[5] == pytest.approx(0)      # 그리퍼 50 → 2047.5 → 2048


def test_to_radians_calibration_sign_offset():
    q = to_radians([10, 0, 0, 0, 0, 30], CAL, sign=[-1, 1, 1, 1, 1, 1], offset_deg=[90, 0, 0, 0, 0, 0])
    assert q[0] == pytest.approx(-(2185 - 2048) * TICK + math.pi / 2)
    assert q[5] == pytest.approx((2450 - 2048) * TICK)


def test_to_radians_needs_six_values():
    with pytest.raises(ValueError):
        to_radians([0] * 5)
    with pytest.raises(ValueError):
        to_radians([0] * 6, sign=[1, 1])


def test_load_episode_video_and_frames(tmp_path):
    ep = load_episode(write_ep(tmp_path / "dori_dori", ep_doc()))
    assert ep["cameras"]["tower cam"]["video"] == "tower_cam.mp4"
    assert ep["cameras"]["follow cam"]["count"] == 2
    assert episode_duration(ep) == pytest.approx(0.4)


def test_load_episode_missing_is_none_quietly(tmp_path, caplog):
    with caplog.at_level("WARNING"):
        assert load_episode(tmp_path / "nothing") is None
    assert caplog.text == ""


@pytest.mark.parametrize("doc", [
    "not json{",
    ep_doc(fps=0),
    ep_doc(joints=[]),
    ep_doc(joints=[[0] * 5]),
    ep_doc(cameras={"tower cam": {"start": 1}}),
    ep_doc(cameras={"follow cam": {"frames": "f", "fps": 5}}),
])
def test_load_episode_broken_is_none_with_warning(tmp_path, caplog, doc):
    folder = tmp_path / "x"
    folder.mkdir()
    (folder / "episode.json").write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
    with caplog.at_level("WARNING"):
        assert load_episode(folder) is None
    assert "재생 데이터" in caplog.text


def test_list_replays_only_valid(tmp_path):
    write_ep(tmp_path / "dori_dori", ep_doc())
    write_ep(tmp_path / "oranda_pickup", ep_doc(joints=[]))
    (tmp_path / "empty").mkdir()
    assert list_replays(tmp_path) == ["dori_dori"]
    assert list_replays(tmp_path / "none") == []


def test_replay_payload_converts_and_builds_urls(tmp_path):
    write_ep(tmp_path / "dori_dori", ep_doc())
    p = replay_payload(tmp_path, "dori_dori")
    assert p["fps"] == 10 and p["duration"] == pytest.approx(0.4) and p["source"] == "run"
    assert p["q"][1] == [round(v, 4) for v in to_radians([10] * 6)]
    assert p["cameras"]["tower cam"] == {"url": "/replays/dori_dori/tower_cam.mp4", "start": 12.5, "end": 12.9}
    assert p["cameras"]["follow cam"] == {"frames": ["/replays/dori_dori/frames/follow_cam/000000.jpg",
                                                     "/replays/dori_dori/frames/follow_cam/000001.jpg"], "fps": 5.0}


def test_replay_payload_custom_converter_and_missing(tmp_path):
    write_ep(tmp_path / "dori_dori", ep_doc())
    assert replay_payload(tmp_path, "dori_dori", convert=lambda v: [1.0] * 6)["q"][0] == [1.0] * 6
    assert replay_payload(tmp_path, "oranda_pickup") is None
    assert replay_payload(tmp_path, "../dori_dori") is None


def test_safe_name():
    assert safe_name("tower cam") == "tower_cam"
    assert safe_name("A/B..c") == "A_B_c"


def test_make_converter_reads_calibration_and_twin_settings(tmp_path):
    import yaml
    cal = tmp_path / "follower.yaml"
    cal.write_text(yaml.safe_dump(CAL), encoding="utf-8")
    cfg = {"robot": {"calibration": str(cal)}, "twin": {"sign": [-1, 1, 1, 1, 1, 1], "offset_deg": [0] * 6}}
    assert make_converter(cfg)([10, 0, 0, 0, 0, 30])[0] == pytest.approx(-(2185 - 2048) * TICK)
    no_cal = make_converter({"robot": {"calibration": str(tmp_path / "none.yaml")}})
    assert no_cal([0] * 6)[0] == 0
