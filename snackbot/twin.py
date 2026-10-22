"""3D 디지털 트윈: 관절 변환과 재생 에피소드 읽기. physicalai를 import하지 않는다 (개발 PC에서 테스트한다).

episode.json — 녹화 받기(tools.fetch_replays)와 실행 기록(snackbot.recorder)이 같은 형식으로 쓴다:
  {"skill": "dori_dori", "source": "studio" | "run", "fps": 30,
   "joints": [[normalized 6개], ...],
   "cameras": {"tower cam": {"video": "tower_cam.mp4", "start": 12.3, "end": 18.9},
               "follow cam": {"frames": "frames/follow_cam", "fps": 10, "count": 66}}}
카메라 키는 config 카메라 이름. 폴더 replays/<스킬>/ 하나가 재생 데이터 하나다.
"""
import functools
import json
import logging
import math
import re
from pathlib import Path
from urllib.parse import quote

from .config import load_calibration

log = logging.getLogger(__name__)

JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")   # URDF 관절 이름과 같다
DEFAULT_URDF = "twin/so101/so101_new_calib.urdf"
EPISODE_FILE = "episode.json"
TICKS_PER_TURN = 4096
TICK_ZERO = 2048
_DEFAULT_CAL = {"range_min": 0, "range_max": TICKS_PER_TURN - 1, "homing_offset": TICK_ZERO}
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")
_SKILL = re.compile(r"[A-Za-z0-9_-]+")
_NUM = (int, float)


def safe_name(name):
    """카메라 이름 → 파일·폴더 이름 (tower cam → tower_cam)."""
    return _UNSAFE.sub("_", str(name)).strip("_") or "cam"


def normalized_to_ticks(values, calibration=None):
    """physicalai SO101._normalized_to_ticks와 같은 식. 캘리브레이션이 없는 관절은 range 0..4095."""
    if len(values) != len(JOINTS):
        raise ValueError(f"관절값은 {len(JOINTS)}개여야 해요 ({len(values)}개)")
    ticks = []
    for name, value in zip(JOINTS, values):
        cal = (calibration or {}).get(name) or _DEFAULT_CAL
        lo, hi = int(cal["range_min"]), int(cal["range_max"])
        rng = hi - lo
        if rng <= 0:
            ticks.append(min(max(int(cal.get("homing_offset", TICK_ZERO)), lo), hi))
            continue
        if name == "gripper":
            tick = round(lo + min(max(float(value), 0.0), 100.0) / 100.0 * rng)
        else:
            tick = round(lo + (min(max(float(value), -100.0), 100.0) + 100.0) / 200.0 * rng)
        ticks.append(min(max(tick, lo), hi))
    return ticks


def to_radians(values, calibration=None, sign=None, offset_deg=None):
    """normalized 6개 → URDF 라디안 6개: (tick − 2048) × 2π / 4096, 그다음 × sign + radians(offset_deg)."""
    sign = list(sign) if sign is not None else [1] * len(JOINTS)
    offset = list(offset_deg) if offset_deg is not None else [0] * len(JOINTS)
    if len(sign) != len(JOINTS) or len(offset) != len(JOINTS):
        raise ValueError(f"twin.sign과 twin.offset_deg는 {len(JOINTS)}개여야 해요")
    ticks = normalized_to_ticks(values, calibration)
    return [(t - TICK_ZERO) * 2 * math.pi / TICKS_PER_TURN * float(s) + math.radians(float(o))
            for t, s, o in zip(ticks, sign, offset)]


def _check_episode(ep):
    if not isinstance(ep, dict):
        raise ValueError("JSON 객체가 아니에요")
    fps = ep.get("fps")
    if not isinstance(fps, _NUM) or fps <= 0:
        raise ValueError(f"fps가 잘못됐어요: {fps!r}")
    joints = ep.get("joints")
    if not isinstance(joints, list) or not joints:
        raise ValueError("joints가 비어 있어요")
    for row in joints:
        if not isinstance(row, list) or len(row) != len(JOINTS) or not all(isinstance(v, _NUM) for v in row):
            raise ValueError(f"joints 한 줄은 숫자 {len(JOINTS)}개여야 해요: {str(row)[:80]}")
    cameras = ep.get("cameras", {})
    if not isinstance(cameras, dict):
        raise ValueError("cameras는 객체여야 해요")
    for name, cam in cameras.items():
        if not isinstance(cam, dict):
            raise ValueError(f"카메라 {name}: 객체가 아니에요")
        if "video" in cam:
            if not isinstance(cam["video"], str) or not all(isinstance(cam.get(k, 0), _NUM) for k in ("start", "end")):
                raise ValueError(f"카메라 {name}: video(파일 이름)·start·end(초) 형식이 아니에요")
        elif "frames" in cam:
            if not isinstance(cam["frames"], str) or not isinstance(cam.get("count"), int) or cam["count"] < 0 \
                    or not isinstance(cam.get("fps"), _NUM) or cam["fps"] <= 0:
                raise ValueError(f"카메라 {name}: frames(폴더)·fps·count 형식이 아니에요")
        else:
            raise ValueError(f"카메라 {name}: video 또는 frames가 필요해요")


def load_episode(folder):
    """folder/episode.json을 읽어 형식을 검사한다. 파일이 없으면 None(로그 없음), 깨졌으면 경고 로그 + None."""
    path = Path(folder) / EPISODE_FILE
    if not path.is_file():
        return None
    try:
        ep = json.loads(path.read_text(encoding="utf-8"))
        _check_episode(ep)
    except (OSError, ValueError) as e:
        log.warning("재생 데이터를 쓸 수 없어요: %s (%s)", path, e)
        return None
    return ep


def episode_duration(ep):
    return len(ep["joints"]) / float(ep["fps"])


def list_replays(replays_dir):
    """재생할 수 있는 스킬 이름 (replays_dir 아래 유효한 episode.json이 있는 폴더)."""
    root = Path(replays_dir)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and load_episode(p) is not None)


def replay_payload(replays_dir, skill, convert=to_radians, url_prefix="/replays"):
    """GET /api/replay/{skill} 응답. 재생 데이터가 없거나 스킬 이름이 이상하면 None."""
    if not _SKILL.fullmatch(str(skill)):
        return None
    ep = load_episode(Path(replays_dir) / skill)
    if ep is None:
        return None
    duration = episode_duration(ep)
    base = f"{url_prefix}/{quote(skill)}"
    cameras = {}
    for name, cam in ep.get("cameras", {}).items():
        if "video" in cam:
            start = float(cam.get("start", 0))
            cameras[name] = {"url": f"{base}/{quote(cam['video'])}", "start": start,
                             "end": float(cam.get("end") or start + duration)}
        else:
            folder = quote(cam["frames"].strip("/"))
            cameras[name] = {"frames": [f"{base}/{folder}/{i:06d}.jpg" for i in range(cam["count"])],
                             "fps": float(cam["fps"])}
    return {"skill": skill, "source": ep.get("source"), "fps": float(ep["fps"]),
            "q": [[round(float(v), 4) for v in convert(row)] for row in ep["joints"]],
            "duration": duration, "cameras": cameras}


def make_converter(cfg):
    """config의 robot.calibration(파일이 있으면)·twin.sign·twin.offset_deg로 to_radians를 고정한 함수."""
    twin = cfg.get("twin") or {}
    path = (cfg.get("robot") or {}).get("calibration")
    calibration = None
    if path and Path(path).is_file():
        try:
            calibration = load_calibration(path)
        except Exception as e:
            log.warning("캘리브레이션을 읽지 못해 기본 범위로 3D를 그려요: %s (%s)", path, e)
        if not isinstance(calibration, dict):
            calibration = None
    return functools.partial(to_radians, calibration=calibration,
                             sign=twin.get("sign"), offset_deg=twin.get("offset_deg"))
