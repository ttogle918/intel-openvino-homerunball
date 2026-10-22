import httpx
import pytest
import yaml

from snackbot.twin import load_episode
from tools import fetch_replays

ACTION_KEYS = ["gripper.pos", "shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos",
               "wrist_roll.pos"]
EPISODE = {
    "episode_index": 3, "length": 2, "fps": 30, "tasks": ["dori"],
    "actions": [[50, 1, 2, 3, 4, 5], [60, 11, 12, 13, 14, 15]],
    "action_keys": ACTION_KEYS,
    "videos": {
        "observation.images.A": {"start": 10.0, "end": 10.5,
                                 "path": "videos/observation.images.A/chunk-000/file-000.mp4"},
        "observation.images.follow cam": {"start": 2.0, "end": 2.5,
                                          "path": "videos/observation.images.follow cam/chunk-000/file-000.mp4"},
    },
}
VIDEO = b"\x00\x00\x00\x18ftypmp42" + b"x" * 200_000


def write_cfg(tmp_path, replay=None):
    cfg = {"replays_dir": str(tmp_path / "replays"),
           "cameras": {"tower cam": {}, "follow cam": {}},
           "skills": {"dori_dori": {"camera_map": {"A": "tower cam"},
                                    "replay": replay or {"dataset": None, "episode": None}}}}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path


def studio(seen, episode=EPISODE, status=200):
    def handler(request):
        seen.append((request.method, request.url.path))
        if "/episodes/" in request.url.path:
            return httpx.Response(status, json=episode)
        return httpx.Response(200, content=VIDEO)

    return httpx.Client(transport=httpx.MockTransport(handler))


def run(tmp_path, args, client, replay=None):
    cfg = write_cfg(tmp_path, replay)
    fetch_replays.main(["--studio", "http://studio:7860/", "--skill", "dori_dori", "--config", str(cfg), *args],
                       client=client)
    return tmp_path / "replays" / "dori_dori"


def test_fetch_saves_episode_and_videos_with_get_only(tmp_path):
    seen = []
    out = run(tmp_path, ["--dataset", "d1", "--episode", "3"], studio(seen))
    assert {m for m, _ in seen} == {"GET"}
    assert seen[0][1] == "/api/dataset/d1/episodes/3"
    assert ("GET", "/api/dataset/d1/video/videos/observation.images.follow cam/chunk-000/file-000.mp4") in seen
    ep = load_episode(out)
    assert ep["source"] == "studio" and ep["fps"] == 30 and ep["episode"] == 3
    assert ep["joints"] == [[1, 2, 3, 4, 5, 50], [11, 12, 13, 14, 15, 60]]     # JOINTS 순서로 재배열
    assert ep["cameras"] == {"tower cam": {"video": "tower_cam.mp4", "start": 10.0, "end": 10.5},   # 학습 이름 A → tower cam
                             "follow cam": {"video": "follow_cam.mp4", "start": 2.0, "end": 2.5}}
    assert (out / "tower_cam.mp4").read_bytes() == VIDEO
    assert not list(out.glob("*.part"))


def test_fetch_uses_config_replay_when_no_args(tmp_path):
    seen = []
    run(tmp_path, [], studio(seen), replay={"dataset": "d9", "episode": 2})
    assert seen[0] == ("GET", "/api/dataset/d9/episodes/2")


def test_fetch_without_dataset_exits(tmp_path):
    with pytest.raises(SystemExit, match="--dataset"):
        run(tmp_path, [], studio([]))


def test_fetch_unknown_action_keys_exit_with_list(tmp_path):
    bad = {**EPISODE, "action_keys": ["a", "b", "c", "d", "e", "f"]}
    with pytest.raises(SystemExit, match="관절 키를 알 수 없어요.*'a'"):
        run(tmp_path, ["--dataset", "d1", "--episode", "3"], studio([], episode=bad))


def test_fetch_missing_episode_and_http_errors(tmp_path):
    with pytest.raises(SystemExit, match="에피소드 3"):
        run(tmp_path, ["--dataset", "d1", "--episode", "3"], studio([], episode=None))
    with pytest.raises(SystemExit, match="404"):
        run(tmp_path, ["--dataset", "d1", "--episode", "3"], studio([], status=404))

    def refuse(request):
        raise httpx.ConnectError("no route")

    with pytest.raises(SystemExit, match="연결하지 못했어요"):
        run(tmp_path, ["--dataset", "d1", "--episode", "3"], httpx.Client(transport=httpx.MockTransport(refuse)))


def test_reorder_without_pos_suffix_and_camera_name():
    keys = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
    assert fetch_replays.reorder([[1, 2, 3, 4, 5, 6]], keys) == [[1, 2, 3, 4, 5, 6]]
    assert fetch_replays.camera_name("observation.images.side cam", {"A": "tower cam"}) == "side cam"
    assert fetch_replays.camera_name("observation.images.A", {"A": "tower cam"}) == "tower cam"


def test_fetch_removes_stale_episode_json_before_downloading(tmp_path):
    out = tmp_path / "replays" / "dori_dori"
    out.mkdir(parents=True)
    (out / "episode.json").write_text("{}", encoding="utf-8")

    def handler(request):
        if "/episodes/" in request.url.path:
            return httpx.Response(200, json=EPISODE)
        return httpx.Response(500)                                  # 영상 받기 실패

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(SystemExit):
        run(tmp_path, ["--dataset", "d1", "--episode", "3"], client)
    assert not (out / "episode.json").exists()                      # 낡은 기록이 남지 않는다
