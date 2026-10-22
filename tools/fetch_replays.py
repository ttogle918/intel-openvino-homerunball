"""Studio 녹화 에피소드 1개를 dry-run 재생용으로 받는다 (조회만 한다: GET).

python -m tools.fetch_replays --studio http://192.168.0.6:7860 --skill oranda_pickup [--dataset ID --episode N] [--config config.yaml]

- --dataset/--episode가 없으면 config.yaml skills.<스킬>.replay 를 쓴다.
  (Studio에서 에피소드를 열면 주소가 /projects/<프로젝트>/datasets/<데이터셋 id>/episodes/<번호>)
- 저장: <replays_dir>/<스킬>/episode.json + <카메라>.mp4 (형식: snackbot/twin.py)
- 영상 키 observation.images.<학습 이름>은 skills.<스킬>.camera_map({학습 이름: config 이름})을 거꾸로 따라
  config 카메라 이름으로 저장한다.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import quote

import httpx

from snackbot.config import load_config
from snackbot.twin import EPISODE_FILE, JOINTS, safe_name

VIDEO_PREFIX = "observation.images."
TIMEOUT = httpx.Timeout(10.0, read=120.0)


def joint_order(action_keys):
    """Studio action_keys(예: shoulder_pan.pos) → JOINTS 순서의 열 번호. 모르는 배치면 SystemExit(받은 키 목록)."""
    names = [str(k).removesuffix(".pos") for k in action_keys]
    if len(names) != len(JOINTS) or set(names) != set(JOINTS):
        raise SystemExit(f"관절 키를 알 수 없어요: {list(action_keys)} (필요: {', '.join(j + '.pos' for j in JOINTS)})")
    return [names.index(j) for j in JOINTS]


def reorder(actions, action_keys):
    """Studio actions(action_keys 순서) → JOINTS 순서의 normalized 6개씩."""
    idx = joint_order(action_keys)
    return [[round(float(row[i]), 3) for i in idx] for row in actions]


def camera_name(video_key, camera_map):
    """observation.images.<학습 이름> → config 카메라 이름 (camera_map: {학습 이름: config 이름})."""
    trained = str(video_key).removeprefix(VIDEO_PREFIX)
    return (camera_map or {}).get(trained, trained)


class _Studio:
    """GET만 하는 Studio 클라이언트. 연결·HTTP 오류는 한국어 안내와 함께 SystemExit."""

    def __init__(self, base, client):
        self.base, self.client = base.rstrip("/"), client

    def _fail(self, e, url):
        if isinstance(e, httpx.HTTPStatusError):
            return SystemExit(f"Studio가 {e.response.status_code}로 답했어요: {url} (데이터셋 id·에피소드 번호 확인)")
        return SystemExit(f"Studio에 연결하지 못했어요: {self.base} ({type(e).__name__}). "
                          "주소·포트·같은 네트워크인지 확인하세요")

    def json(self, path):
        url = self.base + path
        try:
            r = self.client.get(url)
            r.raise_for_status()
            return r.json() if r.content.strip() else None   # 빈 본문 = 없음(null)
        except httpx.HTTPError as e:
            raise self._fail(e, url) from e
        except ValueError as e:
            raise SystemExit(f"Studio 응답이 JSON이 아니에요: {url}") from e

    def download(self, path, dest):
        """스트리밍으로 받아 .part에 쓰고, 다 받으면 이름을 바꾼다. 바이트 수를 돌려준다."""
        url = self.base + path
        part = dest.with_name(dest.name + ".part")
        try:
            with self.client.stream("GET", url) as r:
                r.raise_for_status()
                with open(part, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
            part.replace(dest)
        except httpx.HTTPError as e:
            part.unlink(missing_ok=True)
            raise self._fail(e, url) from e
        return dest.stat().st_size


def main(argv=None, client=None):
    p = argparse.ArgumentParser(prog="python -m tools.fetch_replays",
                                description="Studio 녹화 에피소드를 dry-run 재생용으로 받기 (GET만)")
    p.add_argument("--studio", required=True, help="예: http://192.168.0.6:7860")
    p.add_argument("--skill", required=True, help="oranda_pickup | dori_dori")
    p.add_argument("--dataset", help="Studio 데이터셋 id (없으면 config skills.<스킬>.replay.dataset)")
    p.add_argument("--episode", type=int, help="에피소드 번호 (없으면 config skills.<스킬>.replay.episode)")
    p.add_argument("--config", default="config.yaml")
    a = p.parse_args(argv)

    cfg = load_config(a.config)
    skill = (cfg.get("skills") or {}).get(a.skill)
    if not isinstance(skill, dict):
        raise SystemExit(f"config.yaml skills에 {a.skill}이(가) 없어요")
    replay = skill.get("replay") or {}
    dataset = a.dataset or replay.get("dataset")
    episode = a.episode if a.episode is not None else replay.get("episode")
    if not dataset or episode is None:
        raise SystemExit("데이터셋·에피소드를 몰라요: --dataset ID --episode N 을 주거나 "
                         f"config.yaml skills.{a.skill}.replay 에 {{dataset: ID, episode: N}}을 쓰세요")
    out = Path(cfg.get("replays_dir", "replays")) / a.skill
    own = client is None
    studio = _Studio(a.studio, client or httpx.Client(timeout=TIMEOUT))
    try:
        ep = studio.json(f"/api/dataset/{quote(str(dataset))}/episodes/{int(episode)}")
        if not ep:
            raise SystemExit(f"에피소드 {episode}이(가) 없어요 (데이터셋 {dataset})")
        try:
            fps, actions, keys = ep["fps"], ep["actions"], ep["action_keys"]
        except (KeyError, TypeError) as e:
            raise SystemExit(f"Studio 에피소드 응답 형식이 달라요 (없는 키: {e})") from e
        joints = reorder(actions, keys)
        out.mkdir(parents=True, exist_ok=True)
        (out / EPISODE_FILE).unlink(missing_ok=True)   # 받는 중 실패하면 낡은 episode.json 대신 '재생 없음'
        known = set(cfg.get("cameras") or {})
        cameras = {}
        for key, video in (ep.get("videos") or {}).items():
            name = camera_name(key, skill.get("camera_map"))
            if not video.get("path"):
                print(f"건너뜀: {key} (영상 경로 없음)")
                continue
            if known and name not in known:
                print(f"주의: {name!r}은(는) config cameras에 없어요 (skills.{a.skill}.camera_map 확인). 그대로 저장해요")
            file = f"{safe_name(name)}.mp4"
            path = quote(str(video["path"]).replace("\\", "/"), safe="/")
            size = studio.download(f"/api/dataset/{quote(str(dataset))}/video/{path}", out / file)
            cameras[name] = {"video": file, "start": float(video["start"]), "end": float(video["end"])}
            print(f"영상 {name}: {out / file} ({size / 1e6:.1f}MB, {float(video['start']):.2f}~{float(video['end']):.2f}초)")
    finally:
        if own:
            studio.client.close()
    doc = {"skill": a.skill, "source": "studio", "fps": fps, "joints": joints, "cameras": cameras,
           "dataset": str(dataset), "episode": int(episode)}
    (out / EPISODE_FILE).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    print(f"저장: {out / EPISODE_FILE} ({len(joints)}프레임 · {len(joints) / fps:.1f}초 · 카메라 {len(cameras)}대)")


if __name__ == "__main__":
    main()
