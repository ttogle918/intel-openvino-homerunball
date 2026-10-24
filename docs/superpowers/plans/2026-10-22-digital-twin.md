# 4분할 화면 · 3D 디지털 트윈 · 녹화 재생 · 실행 기록 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 카메라 칸을 2×2(카메라 3 + 3D 팔)로 바꾸고, 실제 로봇에서는 3D 팔이 실제 관절값을 따라 움직이며, dry-run에서는 스킬 차례에 녹화 에피소드(영상 + 관절 궤적)를 시간을 맞춰 재생한다. 실제 로봇 실행은 같은 형식으로 기록해 재생 데이터로 다시 쓸 수 있게 한다.

**Architecture:** 하드웨어 없는 `snackbot/twin.py`가 관절 변환(normalized → tick → 라디안)과 `episode.json` 읽기를 맡고, 녹화 받기(`tools/fetch_replays.py`)·실행 기록(`snackbot/recorder.py`)·서버(`/api/replay`, `joints` 메시지)·DrySkills가 모두 이것을 쓴다. 서버는 `joints_fn()`을 주기적으로 읽어 값이 바뀔 때만 WebSocket으로 보내고, 화면은 `state.phase == "acting"`이 되는 순간 그 스킬의 재생을 시작한다(새 WS 메시지 없음). 3D는 `frontend/twin.js`가 three.js + urdf-loader(빌드 없이 import map, `frontend/vendor/`에 고정 버전)로 SO-101 URDF를 그린다.

**Tech Stack:** FastAPI/Starlette(StaticFiles, StreamingResponse), httpx(MockTransport 테스트), OpenCV(JPEG), NumPy, PyYAML, pytest, three@0.186.1, urdf-loader@0.13.1, SO-101 URDF(TheRobotStudio/SO-ARM100, Apache-2.0).

**전제:** `docs/superpowers/plans/2026-10-22-snackbot-robot.md`(M4) 완료 상태(브랜치 `feat/robot-m4`, 테스트 275개 통과). 요구사항 기준: `docs/superpowers/specs/2026-10-22-digital-twin-design.md` (UI·트윈 부분에서 `2026-10-22-chat-ui-design.md`보다 우선).

## Global Constraints

- 모든 명령은 `project/`에서 실행한다. 개발 PC(Windows, Git Bash): `.venv/Scripts/python`. 로봇 노트북(Ubuntu): `.venv/bin/python`. 테스트: `.venv/Scripts/python -m pytest -q`.
- 커밋은 `project/` 안의 파일만 `git add <경로>`로 지정한다 (`git add -A` 금지). 커밋 메시지 끝에 작업한 세션의 `Co-Authored-By` 줄.
- **physicalai는 개발 PC에 없고 설치하지 않는다.** `snackbot/twin.py`, `snackbot/recorder.py`는 physicalai를 import하지 않는다. `tools/cameras.py`는 `discover_uvc`, `UVCCamera`를 **함수 안에서만** import한다. 모든 테스트는 가짜(fake)로 돈다.
- 테스트에서 네트워크를 쓰지 않는다 (httpx는 `MockTransport`).
- 새 파이썬 의존성 없음 (`requirements.txt` 그대로).
- 관절 순서 `JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")` — URDF 관절 이름과 같다. 저장 단위는 SO101 normalized (몸통 −100..100, 그리퍼 0..100). 3D로 보낼 때만 라디안.
- normalized → tick은 physicalai `SO101._normalized_to_ticks`와 같은 식: 몸통 `tick = range_min + (v + 100) / 200 × (range_max − range_min)`, 그리퍼 `tick = range_min + v / 100 × (range_max − range_min)`, 값은 각각 −100..100, 0..100으로 자르고 `round` 뒤 범위로 자른다 (`range_max − range_min <= 0`이면 `homing_offset`을 범위로 자른 값). tick → 라디안 `(tick − 2048) × 2π / 4096`, 그다음 `× sign + radians(offset_deg)`. 캘리브레이션이 없으면 관절마다 `range_min=0, range_max=4095`.
- `episode.json` 형식 (녹화 받기와 실행 기록이 같다):
  `{"skill": "dori_dori", "source": "studio|run", "fps": 30, "joints": [[6개 normalized], ...], "cameras": {"tower cam": {"video": "tower_cam.mp4", "start": 12.3, "end": 18.9}, "follow cam": {"frames": "frames/follow_cam", "fps": 10, "count": 66}}}` — 카메라 키는 **config 카메라 이름**, 카메라마다 `video` 또는 `frames`(JPEG 순번 `000000.jpg`…) 중 하나.
- 프론트엔드 라이브러리: `three@0.186.1`, `urdf-loader@0.13.1`을 `frontend/vendor/`에 고정 버전 파일로 넣고 import map으로 연결한다 (빌드 없음, 오프라인 동작). 3D 모델은 `TheRobotStudio/SO-ARM100` 커밋 `a758567c3978dfeefe282ede0500085a48fe8f78`의 `Simulation/SO101/so101_new_calib.urdf`와 그 URDF가 참조하는 `assets/*.stl`을 `frontend/twin/so101/`에 넣는다 (Apache-2.0, `LICENSE`와 출처 `README.md` 포함, git으로 관리).
- 의존 방향 유지: `server → controller`. server는 `robot.py`를 모르고 `joints_fn`·`frame_fn`만 받는다.
- 오류는 그 칸만: URDF·라이브러리 로드 실패 → 3D 칸 "3D 없음", 영상 재생 실패 → 그 카메라 칸만 샘플(스트림)로. 실행 기록 실패 → 경고만. 로봇 루프는 영향 없음.
- 화면·안내 문구는 한국어.

## File Structure

| 파일 | 책임 |
|---|---|
| `snackbot/twin.py` (새) | `JOINTS`, `normalized_to_ticks`, `to_radians`, `load_episode`, `episode_duration`, `list_replays`, `replay_payload`, `make_converter`, `safe_name` |
| `snackbot/config.py` (수정) | `ui_tiles(cfg)` — `ui.tiles` → 화면 칸 목록 |
| `config.yaml` (수정) | `ui`, `twin`, `replays_dir`, `recording`, `skills.*.replay`, 카메라 `device` 주석 |
| `.gitignore` (수정) | `/replays/`, `/cameras/` |
| `tools/fetch_replays.py` (새) | Studio 에피소드 1개 → `replays/<스킬>/` (GET만) |
| `tools/cameras.py` (새) | 카메라 목록·시리얼·사진 1장, config 예시 출력 |
| `snackbot/recorder.py` (새) | `RunRecorder`: 정책 phase 관절값·프레임 → `logs/runs/<시각>_<스킬>/` |
| `snackbot/motion.py` (수정) | `Tap.recorder`: 매 틱 기록기에 넘김 |
| `snackbot/robot.py` (수정) | 정책 phase만 기록, `latest_joints()`, connect 때 관절 캐시 채우기 |
| `snackbot/skills.py` (수정) | DrySkills: 재생 데이터가 있으면 동작 시간 = 에피소드 길이, 카메라별 `latest_frame(cam)` |
| `snackbot/server.py` (수정) | `/stream/{cam}`, `/api/replay/{skill}`, `/replays` 정적, `joints` 브로드캐스트 |
| `snackbot/__main__.py` (수정) | info 확장(`ui`, `twin`, `replays`), create_app에 트윈 인자 전달 |
| `frontend/index.html`, `app.js`, `style.css` (수정) | 2×2 칸, 칸별 img/video/frames/iframe, 재생 동기, 실시간 관절 |
| `frontend/twin.js` (새) | three.js + urdf-loader 3D 팔 |
| `frontend/vendor/` (새) | three·urdf-loader 고정 파일 + LICENSE + README |
| `frontend/twin/so101/` (새) | URDF + STL 13개 + LICENSE + README |
| `tests/test_twin.py`, `test_fetch_replays.py`, `test_cameras_tool.py`, `test_recorder.py` (새), `test_config.py`, `test_motion.py`, `test_robot.py`, `test_skills.py`, `test_server.py`, `test_main.py`, `conftest.py` (수정) | 테스트 |
| `docs/DEMO_RUNBOOK.md`, `CLAUDE.md`, `docs/UI_DESIGN_PROMPT.md`, 설계 문서 2개 (수정) | 현장 절차·계약·교차 링크 |

---

### Task 1: twin — 관절 변환과 재생 에피소드, 설정

**Files:**
- Create: `snackbot/twin.py`, `tests/test_twin.py`
- Modify: `snackbot/config.py`, `config.yaml`, `.gitignore`, `tests/conftest.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: `snackbot.config.load_calibration(path) -> dict`
- Produces (`snackbot/twin.py`):
  - `JOINTS: tuple[str, ...]` (6개), `DEFAULT_URDF = "twin/so101/so101_new_calib.urdf"`, `EPISODE_FILE = "episode.json"`
  - `safe_name(name) -> str` — `"tower cam"` → `"tower_cam"` (`[^A-Za-z0-9_-]+` → `_`)
  - `normalized_to_ticks(values, calibration=None) -> list[int]` (6개, 길이가 다르면 `ValueError`)
  - `to_radians(values, calibration=None, sign=None, offset_deg=None) -> list[float]` (6개)
  - `load_episode(folder) -> dict | None` — 파일이 없으면 조용히 None, 깨졌으면 경고 로그 + None
  - `episode_duration(ep) -> float` = `len(ep["joints"]) / ep["fps"]`
  - `list_replays(replays_dir) -> list[str]` — 유효한 `episode.json`이 있는 하위 폴더 이름 (정렬)
  - `replay_payload(replays_dir, skill, convert=to_radians, url_prefix="/replays") -> dict | None` — `{"skill", "source", "fps", "q": [[라디안 6개(소수 4자리)], ...], "duration", "cameras": {이름: {"url", "start", "end"} | {"frames": [url, ...], "fps"}}}`; 스킬 이름이 `[A-Za-z0-9_-]+`가 아니거나 데이터가 없으면 None
  - `make_converter(cfg) -> Callable[[seq], list[float]]` — `robot.calibration` 파일(있으면)과 `twin.sign`·`twin.offset_deg`를 고정한 `to_radians`
- Produces (`snackbot/config.py`): `ui_tiles(cfg) -> list[dict]` — 각 칸 `{"kind": "camera", "name", "available": bool}` | `{"kind": "twin", "name": "3D"}` | `{"kind": "iframe", "name", "url"}`; `ui.tiles`가 없으면 `[tower cam, side cam, follow cam, twin]`
- Produces (config 키): `ui.tiles`, `twin.{urdf, rate_hz, sign, offset_deg}`, `replays_dir`, `recording.{enabled, dir, frame_fps, frame_width}`, `skills.<스킬>.replay.{dataset, episode}`
- Produces (테스트 fixture): `cfg["replays_dir"]`, `cfg["recording"]["dir"]`는 `tmp_path` 아래

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_twin.py`:
```python
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
```

`tests/test_config.py` 맨 위 import를 다음으로 바꾼다:
```python
import json
from pathlib import Path

from snackbot.config import load_config, load_env, load_poses, save_pose, ui_tiles
```
파일 끝에 추가:
```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_twin.py tests/test_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'snackbot.twin'`, `ImportError: cannot import name 'ui_tiles'`

- [ ] **Step 3: 구현**

`snackbot/twin.py`:
```python
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
```

`snackbot/config.py` 끝에 추가:
```python
DEFAULT_TILES = ["tower cam", "side cam", "follow cam", "twin"]


def ui_tiles(cfg):
    """config ui.tiles → 화면 칸 목록 (2×2 순서). 각 칸:
    {"kind": "camera", "name", "available"} | {"kind": "twin", "name": "3D"} | {"kind": "iframe", "name", "url"}.
    config cameras에 없는 이름의 카메라 칸은 available=False ("카메라 없음"으로 그린다)."""
    raw = (cfg.get("ui") or {}).get("tiles") or DEFAULT_TILES
    cameras = cfg.get("cameras") or {}
    tiles = []
    for tile in raw:
        if tile == "twin":
            tiles.append({"kind": "twin", "name": "3D"})
        elif isinstance(tile, dict) and tile.get("iframe"):
            tiles.append({"kind": "iframe", "name": str(tile.get("name", "화면")), "url": str(tile["iframe"])})
        else:
            tiles.append({"kind": "camera", "name": str(tile), "available": str(tile) in cameras})
    return tiles
```

`config.yaml`의 `skills:` 절에서 다음 두 줄을
```yaml
  oranda_pickup: {export_dir: trained_model/oranda-pickup-model/exports/openvino, max_time_s: 20, camera_map: {}}   # [ ] 학습 끝나면 폴더 이름·camera_map 확인
  dori_dori:     {export_dir: trained_model/dori_dori/exports/openvino, max_time_s: 6, camera_map: {}}
```
다음으로 바꾼다:
```yaml
  # replay: dry-run 재생에 쓸 Studio 녹화 {dataset: <데이터셋 id>, episode: <번호>} (python -m tools.fetch_replays 가 읽는다)
  oranda_pickup: {export_dir: trained_model/oranda-pickup-model/exports/openvino, max_time_s: 20, camera_map: {}, replay: {dataset: null, episode: null}}   # [ ] 학습 끝나면 폴더 이름·camera_map 확인
  dori_dori:     {export_dir: trained_model/dori_dori/exports/openvino, max_time_s: 6, camera_map: {}, replay: {dataset: null, episode: null}}
```
`poses_file: poses.yaml ...` 줄 바로 다음(빈 줄 뒤 `voice:` 앞)에 넣는다:
```yaml

ui:
  tiles: [tower cam, side cam, follow cam, twin]   # 2×2 칸 순서. 각 칸: config 카메라 이름 | twin | {iframe: URL, name: 이름표}

twin:                                     # 3D 디지털 트윈 (frontend/twin.js)
  urdf: twin/so101/so101_new_calib.urdf   # frontend/ 기준 경로 (정적 서빙)
  rate_hz: 15                             # 실제 로봇 관절값 전송 주기 (값이 바뀔 때만 보낸다)
  sign: [1, 1, 1, 1, 1, 1]                # [ ] 관절별 부호 보정: 3D가 실제와 반대로 돌면 -1
  offset_deg: [0, 0, 0, 0, 0, 0]          # [ ] 관절별 영점 보정 (도)

replays_dir: replays                      # git 제외. replays/<스킬>/episode.json (tools.fetch_replays 또는 실행 기록 복사)

recording:                                # 실행 기록: 실제 로봇에서 정책 phase마다 관절값·프레임 저장 (episode.json 형식)
  enabled: true
  dir: logs/runs                          # git 제외 (logs/*)
  frame_fps: 10
  frame_width: 640
```

`.gitignore` 끝에 추가:
```gitignore

# 녹화 재생 데이터 (tools.fetch_replays · 실행 기록 복사), 카메라 찾기 사진 (tools.cameras)
/replays/
/cameras/
```

`tests/conftest.py`의 `cfg` fixture에서 `c["logging"]["dir"] = ...` 줄 다음에 추가 (테스트가 저장소의 `replays/`·`logs/runs/`를 건드리지 않게):
```python
    c["replays_dir"] = str(tmp_path / "replays")
    c["recording"]["dir"] = str(tmp_path / "runs")
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_twin.py tests/test_config.py -q`
Expected: test_twin 19개 + test_config 전부 통과

- [ ] **Step 5: 전체 테스트**

Run: `.venv/Scripts/python -m pytest -q`
Expected: 모두 통과 (기존 275 + 새 테스트)

- [ ] **Step 6: 커밋**

```bash
git add snackbot/twin.py snackbot/config.py config.yaml .gitignore tests/test_twin.py tests/test_config.py tests/conftest.py
git commit -m "feat(snackbot): 트윈 관절 변환·재생 에피소드 읽기와 화면·기록 설정

Co-Authored-By: <세션의 attribution 줄>"
```

---

### Task 2: 녹화 받기 — `tools/fetch_replays.py`

**Files:**
- Create: `tools/fetch_replays.py`, `tests/test_fetch_replays.py`

**Interfaces:**
- Consumes: `snackbot.config.load_config`, `snackbot.twin.{EPISODE_FILE, JOINTS, safe_name}`; config `replays_dir`, `cameras`, `skills.<스킬>.{camera_map, replay}`
- Studio API (읽기만, `physical-ai-studio/application/backend/src/api/dataset.py`): `GET /api/dataset/{id}/episodes/{n}` → `Episode {episode_index, length, fps, tasks, actions, action_keys, videos: {키: {start, end, path}}}` (없으면 `null`), `GET /api/dataset/{id}/video/{path}` → 파일. Studio 내부 이름: `action_keys`는 `<관절>.pos`(`runtime/features.py feature_names`), 영상 키는 `observation.images.<카메라 이름 소문자화>`(`runtime/features.py sanitize_camera_name`: 소문자, `[^a-z0-9 _-]`→`_`, 공백은 유지) — 예: `observation.images.tower cam`. `path`는 데이터셋 기준 상대 경로(예: `videos/observation.images.tower cam/chunk-000/file-000.mp4`), 한 파일에 여러 에피소드가 들어 있어 `start/end`가 그 에피소드 구간이다.
- Produces:
  - CLI `python -m tools.fetch_replays --studio URL --skill NAME [--dataset ID --episode N] [--config config.yaml]`
  - `main(argv=None, client=None)` — `client`는 `httpx.Client` (테스트에서 MockTransport 주입, 없으면 만든 뒤 닫는다)
  - `joint_order(action_keys) -> list[int]`, `reorder(actions, action_keys) -> list[list[float]]`, `camera_name(video_key, camera_map) -> str`
  - 결과: `<replays_dir>/<스킬>/episode.json`(`source: "studio"`, `dataset`, `episode` 포함) + `<safe_name(카메라)>.mp4`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_fetch_replays.py`:
```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_fetch_replays.py -q`
Expected: FAIL — `ImportError: cannot import name 'fetch_replays' from 'tools'`

- [ ] **Step 3: 구현**

`tools/fetch_replays.py`:
```python
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
            return r.json()
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
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_fetch_replays.py -q`
Expected: 6 passed

- [ ] **Step 5: 커밋**

```bash
git add tools/fetch_replays.py tests/test_fetch_replays.py
git commit -m "feat(tools): Studio 녹화 에피소드를 재생 데이터로 받기 (GET만)

Co-Authored-By: <세션의 attribution 줄>"
```

---

### Task 3: 카메라 찾기 — `tools/cameras.py`

**Files:**
- Create: `tools/cameras.py`, `tests/test_cameras_tool.py`
- Modify: `config.yaml` (`cameras:` 줄 주석)

**Interfaces:**
- Consumes (lazy, 노트북에서만): `physicalai.capture.cameras.uvc.discover_uvc(only_usable=False) -> list[DeviceInfo]` (`DeviceInfo.index: int`, `.name: str`, `.hardware_payload: dict | None` — UVC는 `serial`이 있으면 그 안에), `physicalai.capture.UVCCamera(device=, width=, height=, fps=)` → `.connect()`, `.read().data`(RGB HxWx3), `.disconnect()`. `UVCCamera(device={"serial": "..."})`처럼 dict를 주면 physicalai가 그 값과 맞는 장치를 찾는다 (`_omnicamera._resolve_open_target`).
- Produces:
  - CLI `python -m tools.cameras [--out cameras] [--width 640 --height 480]`
  - `discover()`, `open_camera(device, width, height)` (테스트가 바꿔 끼운다), `serial_of(info) -> str | None`, `snapshot(info, out, width, height) -> Path`, `config_line(info) -> str`, `main(argv=None)`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_cameras_tool.py`:
```python
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from tools import cameras


class FakeCam:
    def __init__(self, device, fail):
        self.device, self.fail, self.disconnected = device, fail, False

    def connect(self, timeout=5.0):
        if self.fail:
            raise RuntimeError("busy")

    def read(self, timeout=2.0):
        img = np.zeros((48, 64, 3), np.uint8)
        img[:, :, 0] = 255                       # RGB 빨강
        return SimpleNamespace(data=img)

    def disconnect(self):
        self.disconnected = True


def test_cameras_lists_saves_and_prints_config(tmp_path, monkeypatch, capsys):
    infos = [SimpleNamespace(index=0, name="HD Cam", hardware_payload={"serial": "ABC123"}),
             SimpleNamespace(index=2, name="", hardware_payload=None)]
    opened = []

    def open_camera(device, width, height):
        cam = FakeCam(device, fail=device == 2)
        opened.append(cam)
        return cam

    monkeypatch.setattr(cameras, "discover", lambda: infos)
    monkeypatch.setattr(cameras, "open_camera", open_camera)
    cameras.main(["--out", str(tmp_path / "cams")])
    out = capsys.readouterr().out
    img = cv2.imread(str(tmp_path / "cams" / "0.jpg"))
    assert img is not None and img[0, 0, 2] > 200          # RGB → BGR로 저장: 빨강은 마지막 채널
    assert not (tmp_path / "cams" / "2.jpg").exists()
    assert "[0] HD Cam" in out and "ABC123" in out and "(이름 없음)" in out
    assert "열지 못함" in out and "busy" in out
    assert 'cam0: {device: {serial: "ABC123"}, width: 1280, height: 720, fps: 30}' in out
    assert "cam2: {device: 2, width: 1280, height: 720, fps: 30}" in out
    assert len(opened) == 2 and all(c.disconnected for c in opened)


def test_cameras_without_physicalai_exits(monkeypatch):
    def missing():
        raise ImportError("No module named 'physicalai'")

    monkeypatch.setattr(cameras, "discover", missing)
    with pytest.raises(SystemExit, match="physicalai"):
        cameras.main([])


def test_cameras_none_found(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cameras, "discover", lambda: [])
    cameras.main(["--out", str(tmp_path / "c")])
    assert "찾지 못했어요" in capsys.readouterr().out
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_cameras_tool.py -q`
Expected: FAIL — `ImportError: cannot import name 'cameras' from 'tools'`

- [ ] **Step 3: 구현**

`tools/cameras.py`:
```python
"""카메라 찾기: 연결된 UVC 카메라 목록(번호·이름·시리얼)과 카메라마다 사진 1장 (로봇 노트북에서).

python -m tools.cameras [--out cameras] [--width 640 --height 480]

사진(cameras/<번호>.jpg)을 보고 어느 장치가 tower cam / side cam / follow cam 인지 정한 뒤,
출력 끝의 예시를 config.yaml cameras에 붙여 넣는다. 시리얼이 있으면 {serial: "..."}로 지정하는 편이
USB를 다시 꽂아도 번호가 바뀌지 않아 안전하다. physical-ai-studio가 카메라를 잡고 있으면 열리지 않는다.
"""
import argparse
from pathlib import Path

import cv2


def discover():
    from physicalai.capture.cameras.uvc import discover_uvc

    return discover_uvc(only_usable=False)   # 다른 프로그램이 쓰는 장치도 목록에는 보인다


def open_camera(device, width, height):
    from physicalai.capture import UVCCamera

    return UVCCamera(device=device, width=width, height=height, fps=30)


def serial_of(info):
    payload = getattr(info, "hardware_payload", None)
    serial = payload.get("serial") if isinstance(payload, dict) else None
    return str(serial) if serial else None


def snapshot(info, out, width, height):
    """장치를 번호로 열어 1장 저장한다. 실패하면 예외."""
    cam = open_camera(info.index, width, height)
    try:
        cam.connect()
        frame = cam.read().data
    finally:
        try:
            cam.disconnect()
        except Exception:
            pass
    path = Path(out) / f"{info.index}.jpg"
    if not cv2.imwrite(str(path), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)):
        raise OSError(f"사진 저장 실패: {path}")
    return path


def config_line(info):
    serial = serial_of(info)
    device = f'{{serial: "{serial}"}}' if serial else str(info.index)
    return f"  cam{info.index}: {{device: {device}, width: 1280, height: 720, fps: 30}}"


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m tools.cameras", description="카메라 목록과 사진 1장씩")
    p.add_argument("--out", default="cameras")
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    a = p.parse_args(argv)
    try:
        infos = discover()
    except ImportError as e:
        raise SystemExit(f"physicalai가 없어요 ({e}): 로봇 노트북에서 "
                         "pip install -r requirements.txt -r requirements-robot.txt 뒤에 실행하세요")
    if not infos:
        print("카메라를 찾지 못했어요. USB 연결과 권한(video 그룹)을 확인하세요")
        return
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for info in infos:
        serial = serial_of(info)
        try:
            shot = f"사진 {snapshot(info, out, a.width, a.height)}"
        except Exception as e:
            shot = f"열지 못함 ({type(e).__name__}: {e}) — Studio 등 다른 프로그램이 쓰는 중인지 확인"
        print(f"[{info.index}] {info.name or '(이름 없음)'} · 시리얼 {serial or '없음'} · {shot}")
    print()
    print("config.yaml cameras 예시 (camN을 사진을 보고 tower cam / side cam / follow cam 으로 바꾸고, "
          "해상도는 Studio 녹화 때와 같게):")
    for info in infos:
        print(config_line(info))


if __name__ == "__main__":
    main()
```

`config.yaml`의 다음 줄을
```yaml
cameras:                                   # 키 = 학습 때 카메라 이름 (정책 입력 images.<이름>). 정책이 쓰는 카메라를 모두 둔다
```
다음으로 바꾼다:
```yaml
cameras:                                   # 키 = 학습 때 카메라 이름 (정책 입력 images.<이름>). 정책이 쓰는 카메라를 모두 둔다
  # device: 번호(0 → /dev/video0) 또는 {serial: "..."} (USB를 다시 꽂아도 같은 장치). python -m tools.cameras 로 확인
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_cameras_tool.py tests/test_config.py -q`
Expected: 모두 통과

- [ ] **Step 5: 커밋**

```bash
git add tools/cameras.py tests/test_cameras_tool.py config.yaml
git commit -m "feat(tools): 카메라 찾기 (목록·시리얼·사진, config 예시)

Co-Authored-By: <세션의 attribution 줄>"
```

---

### Task 4: 실행 기록 — `RunRecorder` + RobotSkills 연결 + `latest_joints()`

**Files:**
- Create: `snackbot/recorder.py`, `tests/test_recorder.py`
- Modify: `snackbot/motion.py` (`Tap`), `snackbot/robot.py` (`RobotSkills`), `tests/test_motion.py`, `tests/test_robot.py`

**Interfaces:**
- Consumes: `snackbot.twin.{EPISODE_FILE, safe_name, load_episode}`; config `recording.{enabled, dir, frame_fps, frame_width, queue_size(선택, 기본 64)}`, `skills.fps`; `RunResult(stop_reason, grasped, ms)`
- Produces:
  - `snackbot/recorder.py`: `write_jpeg(path, rgb, width)`; `RunRecorder(cfg, writer=write_jpeg, clock=time.localtime)`:
    - `.start(skill) -> Path | None` — `<dir>/<YYYYmmdd-HHMMSS>_<safe_name(스킬)>[_2…]/` 생성 + 저장 스레드 시작. 꺼져 있거나 실패하면 None(실패는 경고)
    - `.tick(joints, frames: dict[이름, RGB], t: float)` — 제어 스레드용, 막히지 않음. 관절은 매 틱, 프레임은 `frame_fps`로 솎아 큐에(가득 차면 버림)
    - `.stop(result=None) -> Path | None` — 기록을 끝내고 저장 스레드에 마무리를 맡긴다 (기다리지 않음). `episode.json`: `source: "run"`, `fps`(실제 틱 간격으로 계산, 표본이 모자라면 `skills.fps`), `joints`, `cameras: {이름: {frames: "frames/<safe>", fps, count}}`, `stop_reason`, `grasped`, `ms`, `started`, `dropped_frames`
    - `.wait(timeout=None)` — 저장 스레드 종료 대기 (테스트·종료용)
    - `.last_folder: Path | None`
  - `Tap.recorder` (기본 None): 있으면 `on_tick`마다 `recorder.tick(joints, {이름: Frame.data}, event.timestamp)`
  - `RobotSkills(cfg, poses, make_runtime=None, policies=None, models=None, recorder=None)`; `.recorder`; `.latest_joints() -> list[float] | None` (연결 전 None, connect 때 현재 관절로 채움, 이후 Tap 캐시 복사); 정책 phase 동안만 `tap.recorder` 설정, `run()`이 끝나면 `recorder.stop(결과)`; `close()`가 `recorder.wait(5)`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_recorder.py`:
```python
import json
import threading
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from snackbot.recorder import RunRecorder, write_jpeg
from snackbot.twin import load_episode

FRAME = np.zeros((480, 1280, 3), np.uint8)


def rec_cfg(tmp_path, **rec):
    return {"skills": {"fps": 30}, "recording": {"enabled": True, "dir": str(tmp_path / "runs"), "frame_fps": 10,
                                                 "frame_width": 320, **rec}}


def result(reason="gripper_open", grasped=True):
    return SimpleNamespace(stop_reason=reason, grasped=grasped, ms=1234)


def feed(rec, n, cams=("tower cam", "follow cam"), fps=30):
    for i in range(n):
        rec.tick(np.full(6, i, np.float32), {c: FRAME for c in cams}, i / fps)


def test_records_joints_every_tick_and_thins_frames(tmp_path):
    rec = RunRecorder(rec_cfg(tmp_path))
    folder = rec.start("dori_dori")
    feed(rec, 31)                                    # 1초, 30Hz
    rec.stop(result("timeout", False))
    rec.wait(5)
    ep = load_episode(folder)
    assert folder.parent == tmp_path / "runs" and folder.name.endswith("_dori_dori")
    assert ep["source"] == "run" and ep["skill"] == "dori_dori"
    assert (ep["stop_reason"], ep["grasped"], ep["ms"]) == ("timeout", False, 1234)
    assert len(ep["joints"]) == 31 and ep["joints"][5] == [5.0] * 6
    assert ep["fps"] == pytest.approx(30)
    assert ep["cameras"]["tower cam"] == {"frames": "frames/tower_cam", "fps": pytest.approx(10), "count": 11}
    jpg = folder / "frames" / "follow_cam" / "000010.jpg"
    assert cv2.imread(str(jpg)).shape == (120, 320, 3)   # frame_width로 줄임 (비율 유지)


def test_tick_does_not_wait_for_slow_writer(tmp_path):
    gate = threading.Event()

    def slow(path, rgb, width):
        gate.wait(5)
        write_jpeg(path, rgb, width)

    rec = RunRecorder(rec_cfg(tmp_path), writer=slow)
    folder = rec.start("oranda_pickup")
    t0 = time.monotonic()
    feed(rec, 30)
    assert time.monotonic() - t0 < 0.5                 # 저장은 백그라운드 스레드
    gate.set()
    rec.stop(result())
    rec.wait(5)
    assert load_episode(folder)["cameras"]["tower cam"]["count"] == 10


def test_full_queue_drops_frames_without_blocking(tmp_path):
    gate = threading.Event()
    rec = RunRecorder(rec_cfg(tmp_path, queue_size=2), writer=lambda p, rgb, w: gate.wait(5))
    folder = rec.start("dori_dori")
    t0 = time.monotonic()
    feed(rec, 90)                                      # 프레임 30번 시도, 큐 2칸
    assert time.monotonic() - t0 < 0.5
    gate.set()
    rec.stop(result())
    rec.wait(5)
    ep = json.loads((folder / "episode.json").read_text(encoding="utf-8"))
    assert ep["dropped_frames"] > 0
    assert len(ep["joints"]) == 90                     # 관절은 버리지 않는다


def test_writer_failure_only_warns(tmp_path, caplog):
    def boom(path, rgb, width):
        raise OSError("disk full")

    rec = RunRecorder(rec_cfg(tmp_path), writer=boom)
    folder = rec.start("dori_dori")
    with caplog.at_level("WARNING"):
        feed(rec, 10)
        rec.stop(result())
        rec.wait(5)
    ep = json.loads((folder / "episode.json").read_text(encoding="utf-8"))
    assert ep["cameras"] == {} and len(ep["joints"]) == 10
    assert caplog.text.count("disk full") == 2          # 카메라마다 한 번만


def test_start_failure_and_disabled_do_nothing(tmp_path, caplog):
    (tmp_path / "runs").write_text("폴더가 아니라 파일", encoding="utf-8")
    rec = RunRecorder(rec_cfg(tmp_path))
    with caplog.at_level("WARNING"):
        assert rec.start("dori_dori") is None
    assert "실행 기록을 시작하지 못했어요" in caplog.text
    feed(rec, 5)
    assert rec.stop(result()) is None

    off = RunRecorder(rec_cfg(tmp_path / "b", enabled=False))
    assert off.start("dori_dori") is None
    feed(off, 5)
    off.stop(result())
    assert not (tmp_path / "b").exists() and off.last_folder is None


def test_same_second_runs_get_distinct_folders(tmp_path):
    rec = RunRecorder(rec_cfg(tmp_path), clock=lambda: time.struct_time((2026, 10, 22, 13, 0, 0, 3, 295, 0)))
    a = rec.start("dori_dori")
    rec.stop(result())
    b = rec.start("dori_dori")
    rec.stop(result())
    rec.wait(5)
    assert a.name == "20261022-130000_dori_dori" and b.name == "20261022-130000_dori_dori_2"
```

`tests/test_motion.py` 끝에 추가:
```python
def test_tap_sends_ticks_to_recorder_only_when_set():
    tap, got = Tap(), []
    rec = SimpleNamespace(tick=lambda joints, frames, t: got.append((joints.tolist(), frames, t)))
    event = SimpleNamespace(robot_state=state([1, 2, 3, 4, 5, 6]),
                            camera_frames={"tower cam": SimpleNamespace(data="img")}, timestamp=0.5)
    tap.on_tick(event)
    tap.recorder = rec
    tap.on_tick(event)
    assert got == [([1, 2, 3, 4, 5, 6], {"tower cam": "img"}, 0.5)]
    assert tap.frames == {"tower cam": "img"}
```

`tests/test_robot.py`:
- import 절 끝(`from snackbot.robot import RobotSkills` 다음)에 추가:
```python
from snackbot.twin import load_episode
```
- `make()`를 다음으로 바꾼다:
```python
def make(cfg, joints=POSES["home_pose"], gripper=(), interrupt_at=None, models=None, recorder=None):
    robot, holder = FakeRobot(joints), {}

    def make_runtime(switch, tap):
        holder["rt"] = FakeRuntime(switch, tap, robot, gripper, interrupt_at)
        return holder["rt"]

    policies = {"oranda_pickup": FakePolicy(), "dori_dori": FakePolicy()}
    skills = RobotSkills(cfg, POSES, make_runtime=make_runtime, policies=policies, models=models, recorder=recorder)
    skills.connect()
    return skills, holder["rt"], robot
```
- 파일 끝에 추가:
```python
def test_policy_phase_is_recorded_but_moves_are_not(rcfg):
    s, rt, _ = make(rcfg, joints=[30, 0, 0, 0, 0, 80], gripper=[80, 80] + [25] * 5 + [80] * 10)
    steps = []
    s.policies["oranda_pickup"].on_update = steps.append
    r = s.run("oranda_pickup")
    s.recorder.wait(5)
    ep = load_episode(s.recorder.last_folder)
    assert rt.runs == ["MoveSource", "FakePolicy", "MoveSource"]
    assert len(ep["joints"]) == len(steps)                # 정책이 돈 틱만 (홈·lift 이동은 제외)
    assert (ep["stop_reason"], ep["grasped"]) == (r.stop_reason, r.grasped) == ("gripper_open", True)
    assert set(ep["cameras"]) == {"tower cam", "follow cam"}
    assert s.tap.recorder is None


def test_recording_disabled_or_broken_does_not_change_run(rcfg, tmp_path, caplog):
    rcfg["recording"]["enabled"] = False
    s, _, _ = make(rcfg)
    assert s.run("dori_dori").stop_reason == "timeout" and s.recorder.last_folder is None

    (tmp_path / "file").write_text("x", encoding="utf-8")
    rcfg["recording"].update(enabled=True, dir=str(tmp_path / "file"))
    s2, _, _ = make(rcfg)
    with caplog.at_level("WARNING"):
        assert s2.run("dori_dori").stop_reason == "timeout"
    assert "실행 기록을 시작하지 못했어요" in caplog.text


def test_latest_joints_none_before_connect_then_cached_copy(rcfg):
    robot = FakeRobot(POSES["home_pose"])
    s = RobotSkills(rcfg, POSES, make_runtime=lambda sw, t: FakeRuntime(sw, t, robot),
                    policies={"dori_dori": FakePolicy()})
    assert s.latest_joints() is None
    s.connect()
    assert s.latest_joints() == POSES["home_pose"]
    robot.joints[:] = 99                                  # 캐시는 connect·틱에서만 바뀐다
    assert s.latest_joints() == POSES["home_pose"]
    s.run("dori_dori")
    assert s.latest_joints() == pytest.approx(POSES["home_pose"])
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_recorder.py tests/test_motion.py tests/test_robot.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'snackbot.recorder'`, `TypeError: ... unexpected keyword argument 'recorder'`, `AttributeError: ... 'latest_joints'`

- [ ] **Step 3: 구현**

`snackbot/recorder.py`:
```python
"""실행 기록: 실제 로봇에서 스킬의 정책 phase 1회마다 관절값과 카메라 프레임을 저장한다.
형식은 녹화 재생과 같다 (snackbot/twin.py의 episode.json, source "run"). physicalai를 import하지 않는다.

logs/runs/<YYYYmmdd-HHMMSS>_<스킬>/episode.json + frames/<카메라>/000000.jpg …
저장된 폴더를 replays/<스킬>/로 복사하면 dry-run 재생에 그대로 쓰인다.

- tick()은 제어 스레드(Tap.on_tick)에서 불린다: 관절은 리스트에 붙이고, 프레임은 frame_fps로 솎아 큐에 넣기만 한다.
  큐가 가득 차면 그 프레임은 버린다 (다음 틱에 다시 시도). JPEG 저장은 백그라운드 스레드가 한다.
- 기록 실패는 경고만 한다. 로봇 동작에는 영향이 없다.
"""
import json
import logging
import queue
import threading
import time
from pathlib import Path

import cv2

from .twin import EPISODE_FILE, safe_name

log = logging.getLogger(__name__)
_STOP = object()
_EPS = 1e-6


def write_jpeg(path, rgb, width):
    """RGB 프레임을 폭 width 이하로 줄여(비율 유지) JPEG로 쓴다."""
    h, w = rgb.shape[:2]
    if w > width:
        rgb = cv2.resize(rgb, (width, max(1, round(h * width / w))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise OSError(f"JPEG 인코딩 실패: {path}")
    Path(path).write_bytes(buf.tobytes())


def _rate(first, last, n, default):
    """n개 표본이 first~last 초에 걸쳐 있으면 초당 개수. 표본이 모자라면 default."""
    if n > 1 and first is not None and last is not None and last > first:
        return round((n - 1) / (last - first), 3)
    return default


class _Session:
    def __init__(self, skill, folder, queue_size):
        self.skill, self.folder = skill, folder
        self.started = time.time()
        self.joints = []
        self.first_t = self.last_t = None
        self.queue = queue.Queue(maxsize=max(1, queue_size))
        self.next_index = 0
        self.first_frame_t = self.last_frame_t = None
        self.counts = {}
        self.dropped = 0
        self.thread = None


class RunRecorder:
    """start(skill) → tick(joints, frames, t)… → stop(result). recording.enabled가 false면 아무것도 하지 않는다."""

    def __init__(self, cfg, writer=write_jpeg, clock=time.localtime):
        rec = cfg.get("recording") or {}
        self.enabled = bool(rec.get("enabled", False))
        self.dir = Path(rec.get("dir", "logs/runs"))
        self.frame_fps = float(rec.get("frame_fps", 10))
        self.frame_width = int(rec.get("frame_width", 640))
        self.queue_size = int(rec.get("queue_size", 64))
        self.fps = float((cfg.get("skills") or {}).get("fps", 30))
        self.writer, self.clock = writer, clock
        self.last_folder = None
        self._session = None
        self._lock = threading.Lock()
        self._threads = []
        self._warned = set()

    def _warn_once(self, key, msg, *args):
        if key not in self._warned:
            self._warned.add(key)
            log.warning(msg, *args)

    def start(self, skill):
        """새 기록 폴더를 만들고 저장 스레드를 띄운다. 꺼져 있거나 실패하면 None."""
        if not self.enabled:
            return None
        try:
            stamp = time.strftime("%Y%m%d-%H%M%S", self.clock())
            base = f"{stamp}_{safe_name(skill)}"
            folder, n = self.dir / base, 2
            while folder.exists():
                folder, n = self.dir / f"{base}_{n}", n + 1
            folder.mkdir(parents=True)
            s = _Session(skill, folder, self.queue_size)
            s.thread = threading.Thread(target=self._worker, args=(s,), name="run-recorder", daemon=True)
            s.thread.start()
        except Exception as e:
            log.warning("실행 기록을 시작하지 못했어요 (%s, 로봇 동작에는 영향 없음): %s", skill, e)
            return None
        with self._lock:
            self._session = s
            self._threads.append(s.thread)
        self.last_folder = folder
        return folder

    def tick(self, joints, frames, t):
        """제어 스레드에서 매 틱 불린다. 막히지 않는다."""
        s = self._session
        if s is None:
            return
        try:
            s.joints.append([round(float(v), 3) for v in joints])
            if s.first_t is None:
                s.first_t = t
            s.last_t = t
            if not frames or (s.last_frame_t is not None and t - s.last_frame_t < 1.0 / self.frame_fps - _EPS):
                return
            try:
                s.queue.put_nowait((s.next_index, dict(frames)))
            except queue.Full:
                s.dropped += 1
                return
            s.next_index += 1
            if s.first_frame_t is None:
                s.first_frame_t = t
            s.last_frame_t = t
        except Exception as e:
            self._warn_once("tick", "실행 기록 중 오류 (로봇 동작에는 영향 없음): %s", e)

    def stop(self, result=None):
        """기록을 끝낸다. episode.json은 저장 스레드가 남은 프레임을 다 쓴 뒤에 쓴다 (기다리지 않는다)."""
        with self._lock:
            s, self._session = self._session, None
        if s is None:
            return None
        meta = {"stop_reason": getattr(result, "stop_reason", None),
                "grasped": bool(getattr(result, "grasped", False)), "ms": getattr(result, "ms", None)}
        try:
            s.queue.put((_STOP, meta), timeout=5)
        except Exception as e:
            log.warning("실행 기록을 마무리하지 못했어요: %s (%s)", s.folder, e)
        return s.folder

    def wait(self, timeout=None):
        """저장 스레드가 끝날 때까지 기다린다 (테스트·종료용)."""
        with self._lock:
            threads, self._threads = self._threads, []
        for t in threads:
            t.join(timeout)

    def _worker(self, s):
        while True:
            index, item = s.queue.get()
            if index is _STOP:
                self._finish(s, item)
                return
            for cam, rgb in item.items():
                try:
                    folder = s.folder / "frames" / safe_name(cam)
                    folder.mkdir(parents=True, exist_ok=True)
                    self.writer(folder / f"{index:06d}.jpg", rgb, self.frame_width)
                    s.counts[cam] = index + 1
                except Exception as e:
                    self._warn_once(("frame", cam), "실행 기록 프레임 저장 실패 (%s): %s", cam, e)

    def _finish(self, s, meta):
        frame_fps = _rate(s.first_frame_t, s.last_frame_t, s.next_index, self.frame_fps)
        doc = {"skill": s.skill, "source": "run", "fps": _rate(s.first_t, s.last_t, len(s.joints), self.fps),
               "joints": s.joints,
               "cameras": {cam: {"frames": f"frames/{safe_name(cam)}", "fps": frame_fps, "count": n}
                           for cam, n in s.counts.items()},
               "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(s.started)),
               "dropped_frames": s.dropped, **meta}
        try:
            tmp = s.folder / (EPISODE_FILE + ".part")
            tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            tmp.replace(s.folder / EPISODE_FILE)
        except Exception as e:
            log.warning("실행 기록 episode.json 저장 실패: %s (%s)", s.folder, e)
```

`snackbot/motion.py`의 `Tap` 클래스 전체를 다음으로 바꾼다:
```python
class Tap:
    """매 틱 관절값과 카메라 프레임을 저장하고, watch가 있으면 그리퍼 값을, recorder가 있으면 틱 전체를 넘긴다."""

    def __init__(self):
        self.lock = threading.Lock()
        self.joints = None
        self.frames = {}
        self.watch = None
        self.recorder = None

    def on_tick(self, event):
        joints = np.asarray(event.robot_state.joint_positions, np.float32).copy()
        frames = {name: frame.data for name, frame in event.camera_frames.items()}
        with self.lock:
            self.joints = joints
            self.frames.update(frames)
        watch = self.watch
        if watch is not None:
            watch.update(float(joints[GRIPPER]), event.timestamp)
        recorder = self.recorder
        if recorder is not None:
            recorder.tick(joints, frames, event.timestamp)   # 큐에 넣기만 한다 (RunRecorder.tick)
```

`snackbot/robot.py`:
- import 절에서 `from .motion import ...` 다음 줄에 추가:
```python
from .recorder import RunRecorder
```
- `RobotSkills.__init__` 시그니처를 다음으로 바꾼다:
```python
    def __init__(self, cfg, poses, make_runtime=None, policies=None, models=None, recorder=None):
```
- 같은 함수의 `self.tap, self.switch = Tap(), Switch()` 줄 다음에 추가:
```python
        self.recorder = recorder if recorder is not None else RunRecorder(cfg)
```
- `connect()`에서 `with self._io:` 블록(`frames = {...}` 줄까지) 바로 다음, `for name, policy in self.policies.items():` 앞에 추가:
```python
        with self.tap.lock:   # 3D 화면이 첫 틱 전에도 지금 자세를 그리도록
            self.tap.joints = np.asarray(obs.joint_positions, np.float32).copy()
```
- `run()` 메서드 전체를 다음으로 바꾼다 (본문은 `_run`으로 옮기고, 정책 phase는 `_policy`를 거친다):
```python
    def run(self, name, on_phase=None):
        if name not in POLICIES:
            raise ValueError(f"알 수 없는 스킬: {name}")
        if name not in self.policies:
            raise RuntimeError(f"{name} 정책이 로드되지 않았어요 (config.yaml skills.{name}.export_dir 폴더 확인)")
        result = None
        try:
            result = self._run(name, on_phase)
            return result
        finally:
            try:
                self.recorder.stop(result)   # 정책 phase를 기록했으면 결과와 함께 episode.json (백그라운드)
            except Exception as e:
                log.warning("실행 기록 마무리 실패: %s", e)

    def _run(self, name, on_phase):
        t0 = time.monotonic()
        gen = self._current_gen()
        if self.ensure_home(gen) == "estop":
            return RunResult("estop", False, _ms(t0))
        if name == "oranda_pickup":
            self.watch.reset()
            self.tap.watch = self.watch
            try:
                reason = self._policy(name, gen, done=self.watch.done)
            finally:
                self.tap.watch = None
            if reason == "estop" or _Aborted(self, gen).is_set():
                return RunResult("estop", self.watch.grasped, _ms(t0))
            stop_reason = "gripper_open" if reason == "done" else "timeout"
            if on_phase:
                on_phase("returning")
            lift = self.lift.copy()
            if stop_reason == "timeout":   # 놓지 못한 채 끝났다: 들어 올리는 동안 그리퍼는 지금 값 유지
                with self._io:
                    lift[GRIPPER] = self.runtime.robot.get_observation().joint_positions[GRIPPER]
            if self._move([lift, self.home], gen) == "estop":
                return RunResult("estop", self.watch.grasped, _ms(t0))
            return RunResult(stop_reason, self.watch.grasped, _ms(t0))
        if self._policy(name, gen) == "estop":
            return RunResult("estop", False, _ms(t0))
        if self._move([self.home], gen) == "estop":
            return RunResult("estop", False, _ms(t0))
        return RunResult("timeout", False, _ms(t0))

    def _policy(self, name, gen, done=None):
        """정책 phase 하나. 이 구간만 실행 기록에 남긴다 (보간 이동은 제외)."""
        self.recorder.start(name)
        self.tap.recorder = self.recorder
        try:
            return self._phase(self.policies[name], self.max_time[name], gen, done=done,
                               camera_map=self.camera_maps[name])
        finally:
            self.tap.recorder = None

    def latest_joints(self):
        """3D 화면용 최근 관절값 (normalized 6개 list). 연결 전이면 None. 제어 스레드를 막지 않게 Tap 캐시만 복사한다."""
        with self.tap.lock:
            joints = self.tap.joints
            return None if joints is None else joints.tolist()
```
- `close()`를 다음으로 바꾼다:
```python
    def close(self):
        self.estop()   # 돌고 있는 동작을 먼저 멈춘다
        with self._io:
            try:
                self.runtime.disconnect()
            except Exception as e:
                log.warning("런타임 해제 실패: %s", e)
        self.recorder.wait(5)   # 마지막 실행 기록을 마저 쓴다
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_recorder.py tests/test_motion.py tests/test_robot.py -q`
Expected: 모두 통과 (test_recorder 6개)

- [ ] **Step 5: 전체 테스트**

Run: `.venv/Scripts/python -m pytest -q`
Expected: 모두 통과. 저장소 `logs/runs/`에 새 폴더가 생기지 않았는지 `ls logs` 로 확인 (conftest가 tmp로 돌린다)

- [ ] **Step 6: 커밋**

```bash
git add snackbot/recorder.py snackbot/motion.py snackbot/robot.py tests/test_recorder.py tests/test_motion.py tests/test_robot.py
git commit -m "feat(snackbot): 실행 기록 (정책 phase 관절값·프레임, 백그라운드 저장)과 latest_joints

Co-Authored-By: <세션의 attribution 줄>"
```

---

### Task 5: 서버·진입점 — 카메라별 스트림, 재생 API, 관절 전송, info 확장, DrySkills 재생 시간

**Files:**
- Modify: `snackbot/server.py`, `snackbot/skills.py`, `snackbot/__main__.py`, `tests/test_server.py`, `tests/test_skills.py`, `tests/test_main.py`

**Interfaces:**
- Consumes: `twin.{to_radians, replay_payload, list_replays, make_converter, load_episode, episode_duration, DEFAULT_URDF}`, `config.ui_tiles`, `RobotSkills.latest_joints`
- Produces:
  - `create_app(controller, info, frame_fn=None, stt=None, static_dir="frontend", *, cameras=(), box_camera=None, joints_fn=None, joints_hz=15.0, convert=None, replays_dir=None)`
    - `GET /stream/front` 그대로 (`frame_fn()`, 상자 그림)
    - `GET /stream/{cam}` → `frame_fn(cam)` MJPEG, `cam`이 `cameras`에 없거나 `frame_fn`이 없으면 404. `cam == box_camera`일 때만 상자
    - `GET /api/replay/{skill}` → `twin.replay_payload(replays_dir, skill, convert)`, 없으면 404
    - `/replays/...` 정적 (`replays_dir`, 없으면 만든다)
    - WebSocket `{"type": "joints", "q": [라디안 6개(소수 4자리)]}` — `joints_fn()`을 `joints_hz`로 읽어 바뀔 때만 모든 연결에. 새 연결은 info·state·history 다음에 마지막 joints 한 번
  - `DrySkills`: `.replay_s: dict[스킬, 초]`, 재생 데이터가 있으면 `run()`의 동작 시간 = 에피소드 길이; `.latest_frame(cam)` — vision 카메라·모르는 이름은 트레이 사진, config의 다른 카메라는 `synth_view(이름)`
  - `build()` 반환 dict에 추가: `frame_fn(cam=None)`, `cameras: list[str]`, `box_camera`, `joints_fn`(실제 로봇: `skills.latest_joints`, dry-run: None), `joints_hz`, `convert`, `replays_dir`; `info`에 `ui: {tiles}`, `twin: {mode: "replay"|"live", urdf}`, `replays: [스킬]`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_server.py`:
- 맨 위 import를 다음으로 바꾼다:
```python
import json
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from conftest import FirstRng
from snackbot.brain import Brain
from snackbot.controller import Controller
from snackbot.providers import Chain, Member
from snackbot.server import create_app, mjpeg_chunk
from snackbot.stt import STT, build_stt
from snackbot.twin import to_radians
from test_controller import FakeSkills
```
- `make_app`을 다음으로 바꾼다:
```python
def make_app(cfg, tmp_path, stt=None, frame_fn=None, **kw):
    c = Controller(cfg, Brain(cfg, rng=FirstRng()), FakeSkills())
    static = tmp_path / "static"
    static.mkdir(parents=True)
    (static / "index.html").write_text("<h1>snackbot</h1>", encoding="utf-8")
    return c, create_app(c, INFO, frame_fn=frame_fn, stt=stt, static_dir=static, **kw)
```
- 파일 끝에 추가:
```python
def test_stream_camera_by_name_and_404_for_unknown(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr("snackbot.server.STREAM_INTERVAL_S", 0.001)
    seen, holder = [], {}

    def frame_fn(cam=None):
        seen.append(cam)
        if len(seen) == 3:
            holder["c"].stop()
        if len(seen) > 50:
            raise _Abort()
        return np.zeros((10, 10, 3), np.uint8)

    c, app = make_app(cfg, tmp_path, frame_fn=frame_fn, cameras=["side cam"])
    holder["c"] = c
    with TestClient(app) as client:
        assert client.get("/stream/nope").status_code == 404
        r = client.get("/stream/side%20cam")
    assert r.status_code == 200 and r.content.startswith(b"--frame")
    assert set(seen) == {"side cam"}


def write_replay(root, skill="dori_dori"):
    folder = root / skill
    (folder / "frames" / "follow_cam").mkdir(parents=True)
    (folder / "tower_cam.mp4").write_bytes(b"video")
    (folder / "frames" / "follow_cam" / "000000.jpg").write_bytes(b"jpg")
    (folder / "episode.json").write_text(json.dumps({
        "skill": skill, "source": "studio", "fps": 2, "joints": [[0] * 6, [100, 0, 0, 0, 0, 50]],
        "cameras": {"tower cam": {"video": "tower_cam.mp4", "start": 1.0, "end": 2.0},
                    "follow cam": {"frames": "frames/follow_cam", "fps": 1, "count": 1}}}), encoding="utf-8")


def test_replay_api_and_static_files(cfg, tmp_path):
    replays = tmp_path / "replays"
    write_replay(replays)
    _, app = make_app(cfg, tmp_path, replays_dir=replays)
    with TestClient(app) as client:
        r = client.get("/api/replay/dori_dori")
        assert r.status_code == 200
        data = r.json()
        assert data["fps"] == 2 and data["duration"] == 1.0
        assert data["q"] == [[round(v, 4) for v in to_radians(row)] for row in ([0] * 6, [100, 0, 0, 0, 0, 50])]
        assert data["cameras"]["tower cam"] == {"url": "/replays/dori_dori/tower_cam.mp4", "start": 1.0, "end": 2.0}
        assert client.get(data["cameras"]["tower cam"]["url"]).content == b"video"
        assert client.get(data["cameras"]["follow cam"]["frames"][0]).content == b"jpg"
        assert client.get("/api/replay/oranda_pickup").status_code == 404
        assert "snackbot" in client.get("/").text          # 프론트엔드 서빙은 그대로


def test_replay_api_uses_converter_and_404_without_dir(cfg, tmp_path):
    replays = tmp_path / "replays"
    write_replay(replays)
    _, app = make_app(cfg, tmp_path, replays_dir=replays, convert=lambda v: [1.0] * 6)
    with TestClient(app) as client:
        assert client.get("/api/replay/dori_dori").json()["q"][0] == [1.0] * 6
    _, app2 = make_app(cfg, tmp_path / "b")
    with TestClient(app2) as client:
        assert client.get("/api/replay/dori_dori").status_code == 404


def test_joints_sent_only_when_changed(cfg, tmp_path):
    cur = {"v": None}
    _, app = make_app(cfg, tmp_path, joints_fn=lambda: cur["v"], joints_hz=200)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        assert ws.receive_json() == INFO
        assert ws.receive_json()["type"] == "state"
        cur["v"] = [0] * 6
        assert ws.receive_json() == {"type": "joints", "q": [round(v, 4) for v in to_radians([0] * 6)]}
        time.sleep(0.1)                                     # 같은 값을 여러 번 읽는 동안에는 보내지 않는다
        cur["v"] = [100, 0, 0, 0, 0, 0]
        second = ws.receive_json()
        assert second["type"] == "joints"
        assert second["q"][0] == round(to_radians([100, 0, 0, 0, 0, 0])[0], 4)


def test_new_connection_gets_last_joints(cfg, tmp_path):
    _, app = make_app(cfg, tmp_path, joints_fn=lambda: [0] * 6, joints_hz=200)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json(), ws.receive_json()
            first = ws.receive_json()
            assert first["type"] == "joints"
        with client.websocket_connect("/ws") as ws2:
            assert ws2.receive_json() == INFO
            assert ws2.receive_json()["type"] == "state"
            assert ws2.receive_json() == first


def test_joints_fn_errors_and_none_are_skipped(cfg, tmp_path):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("serial busy")
        return None if calls["n"] < 5 else [0] * 6

    _, app = make_app(cfg, tmp_path, joints_fn=flaky, joints_hz=200)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json(), ws.receive_json()
        assert ws.receive_json()["type"] == "joints" and calls["n"] >= 5
```

`tests/test_skills.py`:
- 맨 위 import를 다음으로 바꾼다:
```python
import json
import time
from pathlib import Path

import numpy as np
import pytest

from snackbot.skills import DrySkills, RunResult, synth_tray
from snackbot.vision import OpenCVCounter
```
- 파일 끝에 추가:
```python
def test_replay_episode_sets_act_time(cfg):
    folder = Path(cfg["replays_dir"]) / "dori_dori"
    folder.mkdir(parents=True)
    (folder / "episode.json").write_text(json.dumps({"skill": "dori_dori", "source": "run", "fps": 10,
                                                     "joints": [[0] * 6] * 3, "cameras": {}}), encoding="utf-8")
    s = DrySkills(cfg)
    assert s.replay_s == {"dori_dori": pytest.approx(0.3)}
    t0 = time.monotonic()
    assert s.run("dori_dori").stop_reason == "timeout"
    assert time.monotonic() - t0 >= 0.28
    assert s.run("oranda_pickup").ms < 200               # 재생 데이터가 없는 스킬은 act_s (테스트에서 0)


def test_frames_per_camera(cfg):
    s = DrySkills(cfg)
    s.new_task(2)
    tray = s.latest_frame("tower cam")                    # vision 카메라
    assert np.array_equal(tray, s.latest_frame()) and np.array_equal(tray, s.latest_frame("front"))
    side = s.latest_frame("side cam")                     # config의 다른 카메라: 이름표 화면
    assert side.shape == (480, 640, 3) and not np.array_equal(side, tray)
    assert side is s.latest_frame("side cam")
```

`tests/test_main.py` 끝에 추가:
```python
def test_build_dry_run_twin_info_and_parts(cfg, tmp_path):
    cfg["robot"]["calibration"] = str(tmp_path / "none.yaml")
    parts = build(cfg, env={}, dry_run=True)
    try:
        info = parts["info"]
        assert [t["kind"] for t in info["ui"]["tiles"]] == ["camera", "camera", "camera", "twin"]
        assert info["twin"] == {"mode": "replay", "urdf": "twin/so101/so101_new_calib.urdf"}
        assert info["replays"] == []
        assert parts["joints_fn"] is None and parts["joints_hz"] == 15.0
        assert parts["cameras"] == ["tower cam", "side cam", "follow cam"] and parts["box_camera"] == "tower cam"
        assert parts["frame_fn"]("side cam").shape == (480, 640, 3)
        assert parts["convert"]([0] * 6)[0] == 0
        assert parts["replays_dir"] == cfg["replays_dir"]
    finally:
        parts["voice"].close()


def test_build_real_robot_twin_live(real_cfg):
    parts = build(real_cfg, {}, dry_run=False)
    try:
        assert parts["info"]["twin"]["mode"] == "live"
        assert parts["joints_fn"] == parts["skills"].latest_joints
    finally:
        parts["voice"].close()


def test_main_passes_twin_parts_to_create_app(monkeypatch):
    import uvicorn

    import snackbot.__main__ as m
    import snackbot.server as server

    events = []
    _patch_main(monkeypatch, events, lambda: None)
    parts = m.build(None, None)
    parts.update(cameras=["tower cam"], box_camera="tower cam", joints_fn=lambda: None, joints_hz=20.0,
                 convert=str, replays_dir="replays")
    seen = {}

    def fake_create_app(controller, info, **kw):
        seen.update(kw)
        return "app"

    class FakeServer:
        should_exit = False

        def __init__(self, config):
            pass

        def run(self):
            events.append("served")

    monkeypatch.setattr(server, "create_app", fake_create_app)
    monkeypatch.setattr(uvicorn, "Config", lambda app, **kw: app)
    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    m.main([])
    assert "served" in events
    assert seen["cameras"] == ["tower cam"] and seen["box_camera"] == "tower cam"
    assert seen["joints_fn"] is parts["joints_fn"] and seen["joints_hz"] == 20.0
    assert seen["convert"] is str and seen["replays_dir"] == "replays"
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python -m pytest tests/test_server.py tests/test_skills.py tests/test_main.py -q`
Expected: FAIL — `TypeError: create_app() got an unexpected keyword argument 'cameras'`, `AttributeError: 'DrySkills' object has no attribute 'replay_s'`, `KeyError: 'ui'`

- [ ] **Step 3: 구현 — `snackbot/skills.py`**

파일 전체를 다음으로 바꾼다:
```python
"""행동 계층의 로봇 없는 구현 DrySkills (sleep). 실제 로봇은 snackbot/robot.py RobotSkills, 같은 인터페이스:
  tray · new_task(n) · run(name, on_phase=None) -> RunResult · go_home()
  estop() · release_estop() · latest_frame(cam) -> RGB uint8 HxWx3 · close()
녹화 재생 데이터(replays/<스킬>/episode.json)가 있으면 그 스킬의 동작 시간은 에피소드 길이다
(화면이 phase acting 순간 같은 에피소드를 재생하므로 영상과 단계 표시가 함께 끝난다).
"""
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .twin import episode_duration, load_episode

SNACK_RGB = (200, 120, 40)     # 황갈색 (OpenCV counter 기본 HSV 범위 안)
OTHER_RGB = (180, 180, 180)    # 다른 과자 (채도가 낮아 세지 않음)
REPLAY_SKILLS = ("oranda_pickup", "dori_dori")


@dataclass
class RunResult:
    stop_reason: str   # gripper_open | timeout | estop
    grasped: bool
    ms: int


def _ms(t0):
    return int((time.monotonic() - t0) * 1000)


def synth_tray(n):
    img = np.full((480, 640, 3), 235, np.uint8)
    cv2.rectangle(img, (60, 120), (580, 420), (120, 120, 120), 3)
    for i in range(n):
        cv2.circle(img, (130 + (i % 5) * 95, 200 + (i // 5) * 100), 28, SNACK_RGB, -1)
    cv2.circle(img, (610, 450), 20, OTHER_RGB, -1)
    cv2.putText(img, f"DRY-RUN  tray={n}", (60, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (60, 60, 60), 2)
    return img


def synth_view(name):
    """vision 카메라가 아닌 config 카메라의 dry-run 화면 (이름표)."""
    img = np.full((480, 640, 3), 52, np.uint8)
    cv2.putText(img, "DRY-RUN", (40, 200), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (200, 200, 200), 3)
    label = str(name).encode("ascii", "replace").decode()
    cv2.putText(img, label, (40, 290), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (240, 170, 60), 3)
    return img


class DrySkills:
    """로봇 없이 시간만 보낸다. 가짜 트레이(tray)의 개수를 관리한다."""

    def __init__(self, cfg, rng=None):
        dry = cfg["dry_run"]
        self.act_s = float(dry.get("act_s", 1.0))
        self.fail_rate = float(dry.get("fail_rate", 0.0))
        self.samples = Path(dry.get("samples_dir", "tests/samples"))
        self.rng = rng or random.Random(dry.get("seed"))
        self.tray = cfg["target"]["initial_count"]
        self.camera = (cfg.get("vision") or {}).get("camera", "front")
        self.cameras = set(cfg.get("cameras") or {})
        self._estop = threading.Event()
        self._cache = {}
        replays = Path(cfg.get("replays_dir", "replays"))
        self.replay_s = {}
        for name in REPLAY_SKILLS:
            ep = load_episode(replays / name)
            if ep is not None:
                self.replay_s[name] = episode_duration(ep)

    def new_task(self, n):
        self.tray = n

    def run(self, name, on_phase=None):
        t0 = time.monotonic()
        if not self._wait(self.replay_s.get(name, self.act_s)):
            return RunResult("estop", False, _ms(t0))
        if name != "oranda_pickup":
            return RunResult("timeout", False, _ms(t0))
        grasped = self.tray > 0 and self.rng.random() >= self.fail_rate
        if on_phase:
            on_phase("returning")
        if not self._wait(self.act_s / 2):
            return RunResult("estop", False, _ms(t0))
        if grasped:
            self.tray -= 1
        return RunResult("gripper_open" if grasped else "timeout", grasped, _ms(t0))

    def _wait(self, seconds):
        """비상정지면 False. 0.05초 단위로 확인한다."""
        end = time.monotonic() + seconds
        while True:
            if self._estop.is_set():
                return False
            left = end - time.monotonic()
            if left <= 0:
                return True
            time.sleep(min(0.05, left))

    def go_home(self):
        pass

    def estop(self):
        self._estop.set()

    def release_estop(self):
        self._estop.clear()

    def latest_frame(self, cam=None):
        """vision 카메라(또는 cam 없음·모르는 이름)는 트레이 사진, config의 다른 카메라는 이름표 화면."""
        if cam is not None and cam != self.camera and cam in self.cameras:
            if cam not in self._cache:
                self._cache[cam] = synth_view(cam)
            return self._cache[cam]
        path = self.samples / f"tray_{self.tray}.jpg"
        if path.exists():
            if path not in self._cache:
                self._cache[path] = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
            return self._cache[path]
        return synth_tray(self.tray)

    def close(self):
        pass
```

- [ ] **Step 4: 구현 — `snackbot/server.py`**

파일 전체를 다음으로 바꾼다:
```python
"""FastAPI: WebSocket(/ws), 음성(/stt), 카메라(/stream/front, /stream/{cam}), 재생 데이터(/api/replay/{skill}, /replays),
frontend/ 정적 서빙. controller를 부르기만 한다 (controller는 이 모듈을 모른다).
메시지 형식: docs/UI_DESIGN_PROMPT.md, 4분할·3D: docs/superpowers/specs/2026-10-22-digital-twin-design.md"""
import asyncio
import contextlib
import functools
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .twin import replay_payload, to_radians
from .vision import encode_jpeg

log = logging.getLogger(__name__)
UI_COMMANDS = ("resume", "estop", "restart")
STREAM_INTERVAL_S = 0.1
MJPEG = "multipart/x-mixed-replace; boundary=frame"


def draw_boxes(frame, boxes):
    if not boxes:
        return frame
    out = frame.copy()
    for x1, y1, x2, y2 in boxes:
        cv2.rectangle(out, (int(x1), int(y1)), (int(x2), int(y2)), (255, 200, 0), 2)
    return out


def mjpeg_chunk(frame, boxes=None):
    return b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + encode_jpeg(draw_boxes(frame, boxes)) + b"\r\n"


def create_app(controller, info, frame_fn=None, stt=None, static_dir="frontend", *, cameras=(), box_camera=None,
               joints_fn=None, joints_hz=15.0, convert=None, replays_dir=None):
    """frame_fn(cam=None): RGB 프레임. 인자 없이 부르면 vision 카메라 (/stream/front).
    cameras: /stream/{cam}으로 열 수 있는 config 카메라 이름. box_camera: 개수 세기 상자를 그릴 카메라.
    joints_fn(): normalized 관절값 6개 또는 None (dry-run). joints_hz마다 읽어 바뀌면 joints 메시지.
    convert: normalized → 라디안 (기본 twin.to_radians). replays_dir: /api/replay, /replays의 폴더."""
    clients = set()
    shared = {"loop": None, "queue": None, "joints": None}
    camera_names = set(cameras)
    to_rad = convert or to_radians

    async def pump(queue):
        """이벤트를 들어온 순서대로 모든 접속의 outbox에 넣는다 (소켓을 await하지 않는다)."""
        while True:
            event = await queue.get()
            for outbox in list(clients):
                outbox.put_nowait((event, True))

    async def joints_pump():
        """joints_fn()을 joints_hz로 읽어 라디안으로 바꾸고, 값이 바뀌었을 때만 모든 연결에 보낸다."""
        last = None
        while True:
            try:
                values = joints_fn()
                q = None if values is None else [round(float(v), 4) for v in to_rad(values)]
            except Exception as e:
                log.debug("관절값 읽기 실패: %r", e)
                q = None
            if q is not None and q != last:
                last = q
                event = {"type": "joints", "q": q}
                shared["joints"] = event
                shared["queue"].put_nowait(event)
            await asyncio.sleep(1.0 / joints_hz)

    async def writer(ws, outbox, skip_keys):
        """접속별 전송 작업. 오류·타임아웃이면 outbox를 등록 해제하고 소켓을 닫아
        수신 루프를 끝낸다 (브라우저가 close를 받아 재접속한다)."""
        try:
            while True:
                e, live = await outbox.get()
                # 접속 직전 history에 이미 담긴 메시지가 큐에서도 오면 한 번만 보낸다
                key = (e.get("ts"), e.get("role"), e.get("text"))
                if live and e.get("type") == "message" and key in skip_keys:
                    skip_keys.discard(key)      # 한 번만 건너뛴다
                    continue
                await asyncio.wait_for(ws.send_json(e), 2.0)
        except Exception as ex:
            log.debug("ws writer 종료: %r", ex)
        finally:
            clients.discard(outbox)
            with contextlib.suppress(Exception):
                await ws.close()

    def on_event(event):
        # controller 스레드에서 불린다 → 이벤트 루프 스레드로 넘긴다
        loop = shared["loop"]
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(shared["queue"].put_nowait, event)

    @asynccontextmanager
    async def lifespan(app):
        shared["queue"] = asyncio.Queue()
        shared["loop"] = asyncio.get_running_loop()
        tasks = [asyncio.create_task(pump(shared["queue"]))]
        if joints_fn is not None:
            tasks.append(asyncio.create_task(joints_pump()))
        try:
            yield
        finally:
            shared["loop"] = None
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(lifespan=lifespan)
    controller.subscribe(on_event)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        # 동기 구간(await 없음): 초기 상태를 담고 등록 → 이벤트 누락·중복 없음
        outbox = asyncio.Queue()
        outbox.put_nowait((info, False))
        outbox.put_nowait((controller.snapshot(), False))
        history = list(controller.history)
        for m in history:
            outbox.put_nowait((m, False))
        if shared["joints"] is not None:   # 팔이 멈춰 있으면 다음 joints가 오지 않으므로 마지막 값을 한 번
            outbox.put_nowait((shared["joints"], False))
        skip_keys = {(m.get("ts"), m.get("role"), m.get("text")) for m in history}
        clients.add(outbox)
        task = asyncio.create_task(writer(ws, outbox, skip_keys))
        commands = asyncio.Queue()   # 연결별 FIFO: chat/resume/restart 를 들어온 순서대로 하나씩

        async def worker():
            while True:
                fn, args = await commands.get()
                try:
                    await run_in_threadpool(fn, *args)
                except Exception as e:
                    log.warning("ws 명령 처리 실패: %r", e)

        worker_task = asyncio.create_task(worker())

        try:
            while True:
                text = await ws.receive_text()
                try:
                    msg = json.loads(text)
                    kind = msg.get("type")
                    if kind == "chat":
                        commands.put_nowait((controller.chat, (str(msg.get("text", "")), "text")))
                    elif kind == "command" and msg.get("name") == "estop":
                        try:
                            controller.command("estop")     # 즉시 처리: 큐·스레드풀 뒤에 서지 않는다
                        except Exception:
                            log.exception("비상정지 처리 실패")
                    elif kind == "command" and msg.get("name") == "restart":
                        # 접수한 순간의 세션 번호를 함께 넣는다: 대기하는 사이 비상정지가 끼면 이 재시작은 거부된다
                        g = controller.generation()
                        commands.put_nowait((functools.partial(controller.command, "restart", expect_gen=g), ()))
                    elif kind == "command" and msg.get("name") in UI_COMMANDS:
                        commands.put_nowait((controller.command, (msg["name"],)))
                except Exception as e:
                    log.warning("잘못된 ws 메시지 무시: %r (%s)", text[:100], e)
        except WebSocketDisconnect:
            pass
        finally:
            clients.discard(outbox)
            task.cancel()
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.gather(task, worker_task, return_exceptions=True)

    @app.post("/stt")
    async def stt_endpoint(request: Request):
        if stt is None:
            raise HTTPException(503, "STT가 설정되지 않았어요 (config.yaml stt.chain)")
        wav = await request.body()
        try:
            text = await run_in_threadpool(stt.transcribe, wav)
        except Exception as e:
            log.warning("STT 실패: %s", e)
            controller.notify("음성 인식에 실패했어요")
            raise HTTPException(502, "STT 실패")
        text = (text or "").strip()
        if not text:
            controller.notify("못 알아들었어요")
            return {"text": ""}
        await run_in_threadpool(controller.chat, text, "voice")
        return {"text": text}

    async def mjpeg(read, boxes):
        while not controller.stopped:
            try:
                frame = await run_in_threadpool(read)
                chunk = mjpeg_chunk(frame, boxes()) if frame is not None else None
            except Exception as e:
                log.debug("프레임 오류, 건너뜀: %r", e)
                chunk = None
            if chunk is not None:
                yield chunk
            await asyncio.sleep(STREAM_INTERVAL_S)

    @app.get("/stream/front")
    async def stream_front():
        if frame_fn is None:
            raise HTTPException(404, "카메라 없음")
        return StreamingResponse(mjpeg(frame_fn, lambda: controller.last_boxes), media_type=MJPEG)

    @app.get("/stream/{cam}")
    async def stream_cam(cam: str):
        if frame_fn is None or cam not in camera_names:
            raise HTTPException(404, "카메라 없음")
        boxes = (lambda: controller.last_boxes) if cam == box_camera else (lambda: None)
        return StreamingResponse(mjpeg(functools.partial(frame_fn, cam), boxes), media_type=MJPEG)

    @app.get("/api/replay/{skill}")
    async def replay(skill: str):
        data = None
        if replays_dir is not None:
            data = await run_in_threadpool(replay_payload, replays_dir, skill, to_rad)
        if data is None:
            raise HTTPException(404, f"{skill} 재생 데이터 없음")
        return data

    if replays_dir is not None:
        Path(replays_dir).mkdir(parents=True, exist_ok=True)
        app.mount("/replays", StaticFiles(directory=replays_dir), name="replays")
    static = Path(static_dir)
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="frontend")
    return app
```

- [ ] **Step 5: 구현 — `snackbot/__main__.py`**

- import 절에서 다음 줄을
```python
from .config import load_config, load_env
```
다음으로 바꾼다:
```python
from .config import load_config, load_env, ui_tiles
```
그리고 `from .stt import build_stt` 다음 줄에 추가:
```python
from .twin import DEFAULT_URDF, list_replays, make_converter
```
- `build()` 끝의 다음 세 줄을
```python
    camera = cfg["vision"].get("camera", "front")
    return {"controller": controller, "skills": skills, "voice": voice, "stt": stt, "info": info,
            "frame_fn": lambda: skills.latest_frame(camera)}
```
다음으로 바꾼다:
```python
    camera = cfg["vision"].get("camera", "front")
    twin = cfg.get("twin") or {}
    replays_dir = cfg.get("replays_dir", "replays")
    info["ui"] = {"tiles": ui_tiles(cfg)}
    info["twin"] = {"mode": "replay" if dry_run else "live", "urdf": twin.get("urdf", DEFAULT_URDF)}
    info["replays"] = list_replays(replays_dir)
    return {"controller": controller, "skills": skills, "voice": voice, "stt": stt, "info": info,
            "frame_fn": lambda cam=None: skills.latest_frame(cam or camera),
            "cameras": list(cfg.get("cameras") or {}), "box_camera": camera,
            "joints_fn": getattr(skills, "latest_joints", None), "joints_hz": float(twin.get("rate_hz", 15)),
            "convert": make_converter(cfg), "replays_dir": replays_dir}
```
- `main()`의 `create_app(...)` 호출 두 줄을
```python
            app = create_app(controller, parts["info"], frame_fn=parts["frame_fn"], stt=parts["stt"],
                             static_dir=root / "frontend")
```
다음으로 바꾼다:
```python
            app = create_app(controller, parts["info"], frame_fn=parts["frame_fn"], stt=parts["stt"],
                             static_dir=root / "frontend", cameras=parts.get("cameras", ()),
                             box_camera=parts.get("box_camera"), joints_fn=parts.get("joints_fn"),
                             joints_hz=parts.get("joints_hz", 15.0), convert=parts.get("convert"),
                             replays_dir=parts.get("replays_dir"))
```

- [ ] **Step 6: 통과 확인**

Run: `.venv/Scripts/python -m pytest tests/test_server.py tests/test_skills.py tests/test_main.py -q`
Expected: 모두 통과

- [ ] **Step 7: 전체 테스트**

Run: `.venv/Scripts/python -m pytest -q`
Expected: 모두 통과

- [ ] **Step 8: 커밋**

```bash
git add snackbot/server.py snackbot/skills.py snackbot/__main__.py tests/test_server.py tests/test_skills.py tests/test_main.py
git commit -m "feat(snackbot): 카메라별 스트림·재생 API·관절 전송·info 확장, dry-run 재생 시간

Co-Authored-By: <세션의 attribution 줄>"
```

---

### Task 6: 화면 — 2×2 칸, 3D 트윈, 녹화 재생

**Files:**
- Create: `frontend/twin.js`, `frontend/vendor/` (three·urdf-loader 파일, LICENSE, README.md), `frontend/twin/so101/` (URDF, `assets/*.stl` 13개, LICENSE, README.md)
- Modify: `frontend/index.html`, `frontend/app.js`, `frontend/style.css`

**Interfaces:**
- Consumes (서버): `info.ui.tiles`, `info.twin.{mode, urdf}`, `info.replays`, `state.{state, phase, skill}`, `{"type": "joints", "q"}`, `GET /stream/<encodeURIComponent(이름)>`, `GET /api/replay/<스킬>` (Task 5)
- Produces:
  - `frontend/twin.js` (ES module): `export const JOINTS`, `export function createTwin(host: HTMLElement, urdfUrl: string): Promise<{setJoints(q: number[6]), dispose()}>` — WebGL·URDF 실패면 reject
  - `app.js`(classic script)는 `import('./twin.js')`(동적 import)로 불러온다. 재생 시작: `state.phase`가 `acting`이 되는 순간(`twin.mode == "replay"`이고 `info.replays`에 그 스킬이 있을 때). 비상정지: 그 자리에서 멈춤. `counting`·`IDLE`·`DONE`: 재생 정리 후 스트림으로
  - import map: `three` → `/vendor/three/build/three.module.js`, `three/examples/jsm/` · `three/addons/` → `/vendor/three/examples/jsm/`, `urdf-loader` → `/vendor/urdf-loader/src/URDFLoader.js`

- [ ] **Step 1: 라이브러리 고정 버전 받기 (Git Bash)**

urdf-loader 0.13.1의 ESM 파일은 `import * as THREE from 'three'`, `'three/examples/jsm/loaders/STLLoader.js'`, `'three/examples/jsm/loaders/ColladaLoader.js'`, `'./URDFClasses.js'`를 쓰고, ColladaLoader는 `../loaders/TGALoader.js`, `./collada/ColladaParser.js`, `./collada/ColladaComposer.js`를, three.module.js는 `./three.core.js`를 쓴다. 그 파일을 모두 받는다:
```bash
V=frontend/vendor
T=https://cdn.jsdelivr.net/npm/three@0.186.1
for f in build/three.module.js build/three.core.js \
         examples/jsm/controls/OrbitControls.js \
         examples/jsm/loaders/STLLoader.js examples/jsm/loaders/ColladaLoader.js examples/jsm/loaders/TGALoader.js \
         examples/jsm/loaders/collada/ColladaParser.js examples/jsm/loaders/collada/ColladaComposer.js LICENSE; do
  mkdir -p "$V/three/$(dirname "$f")"
  curl -sSfL -o "$V/three/$f" "$T/$f" || echo "FAIL $f"
done
U=https://cdn.jsdelivr.net/npm/urdf-loader@0.13.1
mkdir -p "$V/urdf-loader/src"
for f in src/URDFLoader.js src/URDFClasses.js; do curl -sSfL -o "$V/urdf-loader/$f" "$U/$f" || echo "FAIL $f"; done
curl -sSfL -o "$V/urdf-loader/LICENSE" https://raw.githubusercontent.com/gkjohnson/urdf-loaders/v0.13.1/LICENSE || echo "FAIL LICENSE"
```
확인 (모든 import 대상이 받은 파일 안에 있는지):
```bash
grep -rhoE "(from|import) '[^']+'" frontend/vendor | sort -u
```
Expected (정확히 이 목록. `three/addons/...`는 주석 속 예시라 import map에만 걸어 둔다):
```
from '../loaders/TGALoader.js'
from './ColladaParser.js'
from './URDFClasses.js'
from './collada/ColladaComposer.js'
from './collada/ColladaParser.js'
from './three.core.js'
from 'three'
from 'three/addons/controls/OrbitControls.js'
from 'three/addons/loaders/ColladaLoader.js'
from 'three/addons/loaders/STLLoader.js'
from 'three/addons/loaders/TGALoader.js'
from 'three/examples/jsm/loaders/ColladaLoader.js'
from 'three/examples/jsm/loaders/STLLoader.js'
```
그리고 `FAIL` 줄이 없어야 한다.

`frontend/vendor/README.md`:
```markdown
# 고정 버전 라이브러리 (빌드 없이 import map으로 연결)

| 폴더 | 버전 | 출처 | 라이선스 |
|---|---|---|---|
| `three/` | three@0.186.1 | https://cdn.jsdelivr.net/npm/three@0.186.1/ (build/three.module.js, build/three.core.js, examples/jsm의 OrbitControls·STLLoader·ColladaLoader·TGALoader·collada/*) | MIT (`three/LICENSE`) |
| `urdf-loader/` | urdf-loader@0.13.1 | https://cdn.jsdelivr.net/npm/urdf-loader@0.13.1/src/ (URDFLoader.js, URDFClasses.js) | Apache-2.0 (`urdf-loader/LICENSE`, github.com/gkjohnson/urdf-loaders v0.13.1) |

import map: `frontend/index.html`. 버전을 바꾸면 이 표와 import 목록 확인(`docs/superpowers/plans/2026-10-22-digital-twin.md` Task 6 Step 1)을 함께 고친다.
```

- [ ] **Step 2: SO-101 3D 모델 받기 (Git Bash)**

URDF가 참조하는 STL만 받는다 (`assets/` 폴더의 리더 손잡이·카메라 마운트 등 쓰지 않는 파일은 받지 않는다):
```bash
S=https://raw.githubusercontent.com/TheRobotStudio/SO-ARM100/a758567c3978dfeefe282ede0500085a48fe8f78
D=frontend/twin/so101
mkdir -p "$D/assets"
curl -sSfL -o "$D/so101_new_calib.urdf" "$S/Simulation/SO101/so101_new_calib.urdf"
for f in $(grep -o 'assets/[^"]*\.stl' "$D/so101_new_calib.urdf" | sort -u); do
  curl -sSfL -o "$D/$f" "$S/Simulation/SO101/$f" || echo "FAIL $f"
done
curl -sSfL -o "$D/LICENSE" "$S/LICENSE"
ls "$D/assets" | wc -l
du -sh "$D"
grep -o '<joint name="[a-z_]*" type="revolute"' "$D/so101_new_calib.urdf"
```
Expected: `13`, 약 `16M`, revolute 관절 6개 `gripper wrist_roll wrist_flex elbow_flex shoulder_lift shoulder_pan` (= `JOINTS`). `FAIL` 줄 없음.

`frontend/twin/so101/README.md`:
```markdown
# SO-101 3D 모델 (디지털 트윈)

- 출처: TheRobotStudio/SO-ARM100, 커밋 a758567c3978dfeefe282ede0500085a48fe8f78
  - `Simulation/SO101/so101_new_calib.urdf`
  - 그 URDF가 참조하는 `Simulation/SO101/assets/*.stl` 13개 (쓰지 않는 STL·.part 파일은 넣지 않았다)
- 라이선스: Apache-2.0 (`LICENSE`, 원본 저장소의 파일 그대로)
- 수정: 없음
- 관절 이름: shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper (snackbot/twin.py `JOINTS`와 같다)
- 다시 받기: `docs/superpowers/plans/2026-10-22-digital-twin.md` Task 6 Step 2
```

- [ ] **Step 3: `frontend/twin.js` 작성**

```javascript
// 3D 디지털 트윈: three.js + urdf-loader로 SO-101 URDF를 그린다. app.js가 import('./twin.js')로 불러온다.
// 관절값은 라디안 6개 (서버 twin.to_radians). 마우스: 왼쪽 드래그 회전, 휠 확대, 오른쪽 드래그 이동.
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import URDFLoader from 'urdf-loader';

export const JOINTS = ['shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper'];

export function createTwin(host, urdfUrl) {
  const renderer = new THREE.WebGLRenderer({ antialias: true });   // WebGL이 없으면 여기서 예외 → 호출 쪽 "3D 없음"
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  host.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x2a1a10);
  scene.add(new THREE.HemisphereLight(0xfff4e0, 0x3a2314, 2.2));
  const sun = new THREE.DirectionalLight(0xffffff, 2.0);
  sun.position.set(1, 2, 1.5);
  scene.add(sun);
  scene.add(new THREE.GridHelper(0.8, 16, 0x8a6a4a, 0x4a3424));

  const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 20);
  camera.position.set(0.45, 0.4, 0.55);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 0.12, 0);
  controls.enableDamping = true;
  controls.update();

  let robot = null;
  let raf = 0;
  let disposed = false;
  const resize = () => {
    const w = host.clientWidth || 1;
    const h = host.clientHeight || 1;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(resize);
  ro.observe(host);
  resize();
  const loop = () => {
    raf = requestAnimationFrame(loop);
    controls.update();
    renderer.render(scene, camera);
  };
  loop();

  const api = {
    setJoints(q) {
      if (!robot || !q) return;
      JOINTS.forEach((name, i) => {
        if (Number.isFinite(q[i])) robot.setJointValue(name, q[i]);
      });
    },
    dispose() {
      disposed = true;
      cancelAnimationFrame(raf);
      ro.disconnect();
      controls.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    },
  };

  return new Promise((resolve, reject) => {
    const manager = new THREE.LoadingManager();
    manager.onError = (url) => console.warn('3D 파일 로드 실패:', url);
    manager.onLoad = () => {   // URDF와 STL을 모두 받은 뒤 (STL 일부가 실패해도 나머지로 그린다)
      if (!disposed && robot) resolve(api);
    };
    const loader = new URDFLoader(manager);
    loader.load(urdfUrl, (r) => {
      robot = r;
      robot.rotation.x = -Math.PI / 2;   // URDF는 Z가 위, three.js는 Y가 위
      scene.add(robot);
    }, null, (e) => {
      api.dispose();
      reject(e);
    });
  });
}
```

- [ ] **Step 4: `frontend/index.html` 교체**

파일 전체를 다음으로 바꾼다 (바뀐 곳: `<head>`의 import map, `.cam` 칸 안이 `#tiles` 격자로):
```html
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>과자 옮기기 로봇 관제</title>
<script type="importmap">
{
  "imports": {
    "three": "/vendor/three/build/three.module.js",
    "three/examples/jsm/": "/vendor/three/examples/jsm/",
    "three/addons/": "/vendor/three/examples/jsm/",
    "urdf-loader": "/vendor/urdf-loader/src/URDFLoader.js"
  }
}
</script>
<link rel="stylesheet" href="style.css">
</head>
<body data-state="IDLE" data-phase="idle">
<div class="frame-alert" aria-hidden="true"></div>

<header class="topbar">
  <div class="brand"><span class="brand-mark"></span><h1>과자 옮기기 관제실</h1></div>
  <div class="top-right">
    <span id="mockTag" class="pill pill-mock" hidden>목업 모드</span>
    <span id="conn" class="pill pill-off"><i></i><b>연결 끊김</b></span>
  </div>
</header>

<main class="main">
  <section class="cam card" aria-label="카메라와 3D">
    <div class="tiles" id="tiles"></div>
    <div class="count-overlay">
      <div class="count-name" id="cntName">과자</div>
      <div class="count-row"><span class="count-num" id="cntNum">–</span><span class="count-unit">개 남음</span></div>
      <div class="count-method" id="cntMethod"></div>
    </div>
    <div class="cam-refuse" id="camRefuse"><b>거부 중</b><span>달래 주면 다시 일할지도 몰라요</span></div>
    <div class="cam-estop" id="camEstop"><b>비상정지</b></div>
  </section>

  <aside class="side">
    <section class="robot-card card">
      <div class="robot-stage">
        <div class="robot" id="robot" data-mood="fresh">
          <div class="r-antenna"></div>
          <div class="r-head">
            <div class="r-eye l"></div><div class="r-eye r"></div>
            <div class="r-cheek l"></div><div class="r-cheek r"></div>
            <div class="r-mouth"></div>
          </div>
          <div class="r-body"><div class="r-belly"></div></div>
          <div class="r-sweat"></div>
        </div>
      </div>
      <div class="robot-info">
        <div class="badge-row">
          <span class="state-badge" id="stateBadge">대기</span>
          <span class="phase-label" id="phaseLabel">쉬는 중</span>
        </div>
        <ol class="steps" id="steps">
          <li data-p="counting">개수<br>세기</li>
          <li data-p="thinking">생각</li>
          <li data-p="speaking">말하기</li>
          <li data-p="acting">옮기기</li>
          <li data-p="returning">복귀</li>
        </ol>
        <div class="fatigue">
          <div class="fatigue-head"><span>피로도</span><span id="fatigueTier" class="tier">쌩쌩</span></div>
          <div class="gauge" id="gauge">
            <div class="gauge-fill" id="gaugeFill"></div>
            <div class="gauge-mark" id="gaugeMark"></div>
          </div>
          <div class="gauge-scale"><span>0</span><span id="gaugeCount">0회</span><span id="gaugeMax">한계 –</span></div>
        </div>
      </div>
    </section>

    <section class="chat card">
      <div class="chat-log" id="chatLog"><div class="chat-empty" id="chatEmpty">대화가 없어요. 말을 걸어 보세요.</div></div>
      <div class="voice-status" id="voiceStatus" hidden></div>
      <form class="chat-form" id="chatForm" autocomplete="off">
        <input id="chatInput" type="text" placeholder="로봇에게 말하기  (예: 과자 옮겨줘)" maxlength="200">
        <button type="button" class="mic" id="micBtn" aria-label="누르고 말하기">
          <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>
          <span>누르고 말하기</span>
        </button>
        <button type="submit" class="send">보내기</button>
      </form>
    </section>
  </aside>

  <footer class="bottom">
    <section class="perf card">
      <div class="perf-head">
        <h2>성능</h2>
        <div class="success"><span>성공률</span><b id="succRate">–</b><small id="succDetail"></small></div>
        <div class="dots" id="cycleDots" title="최근 사이클"></div>
      </div>
      <div class="timings" id="timings">
        <div class="tm" data-k="vision"><label>개수 세기</label><b>–</b><div class="bar"><i></i></div></div>
        <div class="tm" data-k="llm"><label>LLM</label><b>–</b><div class="bar"><i></i></div></div>
        <div class="tm" data-k="act"><label>ACT</label><b>–</b><div class="bar"><i></i></div></div>
        <div class="tm" data-k="return"><label>복귀</label><b>–</b><div class="bar"><i></i></div></div>
      </div>
    </section>

    <section class="models card">
      <h2>모델 · 실행 위치</h2>
      <dl id="models">
        <div data-k="act"><dt>제어</dt><dd>–</dd></div>
        <div data-k="vision"><dt>비전</dt><dd>–</dd></div>
        <div data-k="llm"><dt>대화</dt><dd>–</dd></div>
        <div data-k="stt"><dt>음성</dt><dd>–</dd></div>
      </dl>
    </section>

    <section class="ctrl">
      <div class="ctrl-small">
        <button class="btn btn-resume" id="btnResume" disabled>재개</button>
        <button class="btn btn-restart" id="btnRestart" disabled>재시작</button>
      </div>
      <button class="btn-estop" id="btnEstop" disabled><span class="octo"></span><b>비상정지</b></button>
    </section>
  </footer>
</main>
<script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 5: `frontend/style.css`에 4분할 스타일 추가**

파일 끝에 추가 (기존 규칙은 그대로, 아래가 덮어쓴다):
```css

/* 4분할 화면 (카메라 3 + 3D). 설계: docs/superpowers/specs/2026-10-22-digital-twin-design.md 9장 */
.tiles{position:absolute;inset:0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));grid-auto-rows:minmax(0,1fr);gap:.35rem;padding:.35rem;background:var(--ink)}
.tiles[data-n="1"]{grid-template-columns:1fr}
.tile{position:relative;overflow:hidden;border-radius:.8rem;background:#2a1a10;min-width:0;min-height:0}
.tile>img,.tile>video,.tile>iframe,.tile>.twin-host{position:absolute;inset:0;width:100%;height:100%;border:0;object-fit:contain;background:#000}
.tile>iframe{background:#fff}
.tile>.twin-host{background:#2a1a10}
.twin-host canvas{display:block;width:100%;height:100%;touch-action:none}
.tile>[hidden]{display:none}
.tile .cam-empty span{font-size:1.2rem}
.tile-label{position:absolute;top:.6rem;left:.6rem;z-index:1;background:rgba(0,0,0,.6);color:#fff;font-family:var(--mono);font-weight:700;font-size:.95rem;padding:.25rem .8rem;border-radius:99px;display:flex;gap:.45rem;align-items:center;pointer-events:none}
.tile-label i{width:.65rem;height:.65rem;border-radius:50%;background:var(--red);animation:blink 1.4s infinite}
.tile[data-kind=twin] .tile-label i{background:var(--blue);animation:none}
.tile[data-kind=iframe] .tile-label i{background:var(--green);animation:none}
.cam .count-overlay{left:50%;top:50%;bottom:auto;transform:translate(-50%,-50%);z-index:2;padding:.5rem 1.3rem .6rem;min-width:0;pointer-events:none}
.cam .count-num{font-size:5.5rem}
.cam .count-unit{font-size:1.8rem}
.cam .count-name{font-size:1.15rem}
.cam-refuse,.cam-estop{z-index:3}
@media (max-width:760px),(max-aspect-ratio:3/4){.tiles{grid-template-columns:1fr}}
```

- [ ] **Step 6: `frontend/app.js` 수정**

(1) 상태 객체: 다음 두 줄을
```javascript
const S = { state: 'IDLE', phase: 'idle', count: 0, remaining: null, vision_method: null, skill: null,
  th: { safe_max: 3, force_refuse: 6 }, name: '과자', got: false, cycles: [], mock: false };
```
다음으로 바꾼다:
```javascript
const S = { state: 'IDLE', phase: 'idle', count: 0, remaining: null, vision_method: null, skill: null,
  th: { safe_max: 3, force_refuse: 6 }, name: '과자', got: false, cycles: [], mock: false,
  twin: { mode: 'replay', urdf: 'twin/so101/so101_new_calib.urdf' }, replays: [] };
```

(2) `renderInfo` 함수 전체를 다음으로 바꾼다:
```javascript
function renderInfo(m) {
  if (m.target && m.target.name) S.name = m.target.name;
  const mod = m.models || {};
  document.querySelectorAll('#models > div').forEach((d) => {
    d.querySelector('dd').textContent = mod[d.dataset.k] || '–';
    d.querySelector('dd').title = mod[d.dataset.k] || '';
  });
  S.twin = m.twin || { mode: S.mock ? 'mock' : 'replay', urdf: DEFAULT_URDF };
  S.replays = Array.isArray(m.replays) ? m.replays : [];
  buildTiles(m.ui && m.ui.tiles);
  S.replays.forEach((skill) => loadReplay(skill).then((d) => {   // 미리 받아 두면 acting 순간 바로 튼다
    if (d && !lastQ && S.twin.mode === 'replay' && d.q && d.q.length) setJoints(d.q[0]);
  }));
  renderState();
}
```

(3) `handle` 함수 전체를 다음으로 바꾼다:
```javascript
function handle(m) {
  switch (m.type) {
    case 'info': renderInfo(m); break;
    case 'state': {
      const prev = { state: S.state, phase: S.phase, skill: S.skill };
      S.got = true;
      S.state = m.state; S.phase = m.phase || 'idle';
      S.count = m.count ?? 0; S.remaining = m.remaining ?? null;
      S.vision_method = m.vision_method || null; S.skill = m.skill || null;
      if (m.thresholds) S.th = { safe_max: m.thresholds.safe_max, force_refuse: m.thresholds.force_refuse };
      renderState();
      onReplayState(prev);
      break;
    }
    case 'message': addMsg(m); break;
    case 'cycle': S.cycles.push(m); if (S.cycles.length > 50) S.cycles.shift(); renderCycles(); break;
    case 'joints': if (!replay && Array.isArray(m.q)) setJoints(m.q); break;
  }
}
```

(4) `startMock`, `stopMock`, `resetUI` 세 함수 전체를 다음으로 바꾼다:
```javascript
function startMock() {
  if (mock) return;
  S.mock = true; $('#mockTag').hidden = false;
  resetUI();
  mock = createMock(handle);
  setConn(true, '시뮬레이터');
  mock.start();
  startSway();
}
function stopMock() {
  if (!mock) return;
  mock.stop(); mock = null; S.mock = false; $('#mockTag').hidden = true; stopSway(); resetUI();
  tiles.forEach((t) => { if (t.spec.kind === 'camera') loadStream(t); });
}
function resetUI() {
  clearReplay();
  clearChat(); S.cycles = []; S.got = false; S.state = 'IDLE'; S.phase = 'idle'; S.count = 0; S.remaining = null; S.vision_method = null;
  renderCycles(); renderState();
}
```

(5) 시작 줄 옮기기: 다음 한 줄을 지운다 (맨 끝으로 옮긴다. 아래 칸·재생 코드의 `let`/`const`가 선언되기 전에 목업이 시작되면 안 된다):
```javascript
if (MOCK_FORCED) startMock(); else connect();
```

(6) 카메라 블록 교체: 다음 블록 전체를
```javascript
/* ---------- camera ---------- */
const cam = $('#camImg');
function camOn() { cam.hidden = false; $('#camEmpty').hidden = true; }
function camOff() { cam.hidden = true; $('#camEmpty').hidden = false; }
cam.onload = camOn;
cam.onerror = () => { camOff(); $('#camEmptyText').textContent = '카메라 없음'; setTimeout(loadCam, 3000); };
function loadCam() { if (S.mock) { camOff(); $('#camEmptyText').textContent = '카메라 자리표시 (목업)'; setTimeout(loadCam, 2000); return; } cam.src = '/stream/front?t=' + Date.now(); }
if (MOCK_FORCED) { camOff(); $('#camEmptyText').textContent = '카메라 자리표시 (목업)'; setTimeout(loadCam, 2000); } else loadCam();
```
다음으로 바꾼다:
```javascript
/* ---------- tiles: 2×2 (카메라 · 3D · iframe). 설계: docs/superpowers/specs/2026-10-22-digital-twin-design.md 9장 ---------- */
const DEFAULT_TILES = [
  { kind: 'camera', name: 'tower cam', available: true }, { kind: 'camera', name: 'side cam', available: true },
  { kind: 'camera', name: 'follow cam', available: true }, { kind: 'twin', name: '3D' }];
const DEFAULT_URDF = 'twin/so101/so101_new_calib.urdf';
const tilesEl = $('#tiles');
let tiles = [], tilesKey = '', twin = null, twinTile = null, lastQ = null;

function showOnly(t, shown, text) {
  [t.img, t.video, t.frame].forEach((e) => { if (e) e.hidden = e !== shown; });
  t.empty.hidden = !!shown;
  if (!shown && text) t.emptyText.textContent = text;
}

function loadStream(t) {
  clearTimeout(t.retryT);
  if (t.replay) return;
  if (S.mock) { t.img.removeAttribute('src'); showOnly(t, null, '카메라 자리표시 (목업)'); return; }
  if (t.spec.available === false) { showOnly(t, null, '카메라 없음'); return; }
  t.img.src = '/stream/' + encodeURIComponent(t.spec.name) + '?t=' + Date.now();
}

function makeTile(spec) {
  const el = document.createElement('div');
  el.className = 'tile';
  el.dataset.kind = spec.kind;
  el.innerHTML = '<div class="cam-empty"><div class="stripes"></div><span></span></div><div class="tile-label"><i></i><b></b></div>';
  el.querySelector('.tile-label b').textContent = spec.name || '';
  const t = { spec, el, empty: el.querySelector('.cam-empty'), emptyText: el.querySelector('.cam-empty span'), replay: null, retryT: 0 };
  if (spec.kind === 'camera') {
    t.img = document.createElement('img');
    t.video = document.createElement('video');
    t.frame = document.createElement('img');
    t.img.alt = ''; t.frame.alt = '';
    t.video.muted = true; t.video.playsInline = true; t.video.preload = 'auto';
    el.prepend(t.img, t.video, t.frame);
    showOnly(t, null, '연결 중…');
    t.img.onload = () => { if (!t.replay) showOnly(t, t.img); };
    t.img.onerror = () => {
      if (t.replay || !t.img.getAttribute('src')) return;
      showOnly(t, null, '카메라 없음');
      t.retryT = setTimeout(() => loadStream(t), 3000);
    };
    loadStream(t);
  } else if (spec.kind === 'twin') {
    t.host = document.createElement('div');
    t.host.className = 'twin-host';
    el.prepend(t.host);
    showOnly(t, null, '3D 불러오는 중…');
    twinTile = t;
    loadTwin(t);
  } else if (spec.kind === 'iframe') {
    const f = document.createElement('iframe');
    f.src = spec.url; f.title = spec.name || ''; f.loading = 'lazy'; f.referrerPolicy = 'no-referrer';
    el.prepend(f);
    t.empty.hidden = true;
  }
  return t;
}

function buildTiles(specs) {
  const list = Array.isArray(specs) && specs.length ? specs : DEFAULT_TILES;
  const key = JSON.stringify(list);
  if (key === tilesKey) return;   // 재접속 때 같은 info면 3D를 다시 불러오지 않는다
  tilesKey = key;
  clearReplay();
  tiles.forEach((t) => { clearTimeout(t.retryT); if (t.img) t.img.removeAttribute('src'); });
  if (twin) { twin.dispose(); twin = null; }
  twinTile = null;
  tilesEl.innerHTML = '';
  tiles = list.map(makeTile);
  tiles.forEach((t) => tilesEl.appendChild(t.el));
  tilesEl.dataset.n = String(tiles.length);
}

function loadTwin(t) {
  const urdf = (S.twin && S.twin.urdf) || DEFAULT_URDF;
  import('./twin.js')
    .then((mod) => mod.createTwin(t.host, urdf))
    .then((api) => {
      if (twinTile !== t) { api.dispose(); return; }
      twin = api;
      t.empty.hidden = true;
      if (lastQ) twin.setJoints(lastQ);
    })
    .catch((e) => { console.warn('3D 로드 실패', e); if (twinTile === t) showOnly(t, null, '3D 없음'); });
}

function setJoints(q) { lastQ = q; if (twin) twin.setJoints(q); }

let swayRaf = 0;
function startSway() {   // 목업: 홈 자세 근처에서 천천히 흔든다
  cancelAnimationFrame(swayRaf);
  const t0 = performance.now();
  const step = () => {
    const t = (performance.now() - t0) / 1000;
    setJoints([0.35 * Math.sin(t * 0.8), -0.3 + 0.15 * Math.sin(t * 1.1), 0.4 + 0.15 * Math.sin(t * 0.9),
      0.3 * Math.sin(t * 1.3), 0.5 * Math.sin(t * 0.6), 0.4 + 0.3 * Math.sin(t * 2)]);
    swayRaf = requestAnimationFrame(step);
  };
  swayRaf = requestAnimationFrame(step);
}
function stopSway() { cancelAnimationFrame(swayRaf); swayRaf = 0; }

/* ---------- dry-run 재생: phase acting 이 되는 순간 그 스킬의 녹화(영상·프레임 + 관절 궤적)를 함께 튼다 ---------- */
const replayData = {};
let replay = null;

function loadReplay(skill) {
  if (replayData[skill]) return Promise.resolve(replayData[skill]);
  return fetch('/api/replay/' + encodeURIComponent(skill))
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => { if (d) replayData[skill] = d; return d; })
    .catch(() => null);
}

function onReplayState(prev) {
  if (S.state === 'ESTOP') { pauseReplay(); return; }
  if (S.phase === 'acting' && S.skill && (prev.phase !== 'acting' || prev.skill !== S.skill)) {
    if (S.twin.mode === 'replay' && S.replays.includes(S.skill)) startReplay(S.skill);
    return;
  }
  if (S.phase === 'counting' || S.state === 'IDLE' || S.state === 'DONE') clearReplay();
}

function startReplay(skill) {
  if (replayData[skill]) { beginReplay(skill, replayData[skill]); return; }
  loadReplay(skill).then((d) => {
    if (d && S.phase === 'acting' && S.skill === skill && !replay) beginReplay(skill, d);
  });
}

function beginReplay(skill, data) {
  clearReplay();
  const r = { skill, data, t0: performance.now(), created: performance.now(), clock: null, raf: 0, paused: false, tiles: [] };
  replay = r;
  tiles.forEach((t) => {
    if (t.spec.kind !== 'camera') return;
    const cam = data.cameras && data.cameras[t.spec.name];
    if (!cam) return;
    clearTimeout(t.retryT);
    t.replay = r; t.cam = cam; t.ended = false; t.frameIdx = -1;
    t.img.removeAttribute('src');
    r.tiles.push(t);
    if (cam.url) {
      const v = t.video;
      const start = cam.start || 0;
      v.onerror = () => replayFallback(r, t);
      v.onloadedmetadata = () => { v.currentTime = start; };
      v.onseeked = () => { if (replay === r && !r.paused && v.paused && !t.ended) v.play().catch(() => replayFallback(r, t)); };
      v.onplaying = () => {
        if (r.clock && r.clock.video === v && !r.clock.started) {
          r.clock.started = true;
          r.t0 = performance.now() - (v.currentTime - start) * 1000;
        }
      };
      v.src = cam.url;
      showOnly(t, v);
      if (!r.clock) r.clock = { video: v, start, tile: t, started: false };   // 첫 영상이 시계
    } else if (cam.frames && cam.frames.length) {
      showOnly(t, t.frame);
    }
  });
  r.raf = requestAnimationFrame(() => replayTick(r));
}

function replayTick(r) {
  if (replay !== r || r.paused) return;
  const now = performance.now();
  const c = r.clock;
  if (c && !c.started) {
    if (now - r.created > 3000) replayFallback(r, c.tile);   // 영상이 3초 안에 안 나오면 그 칸만 샘플로, 시계는 벽시계
    r.t0 = now;                                              // 영상이 나올 때까지 0초에 머문다
  }
  const v = r.clock && r.clock.started && !r.clock.video.paused ? r.clock.video : null;
  const t = v ? Math.max(0, v.currentTime - r.clock.start) : (now - r.t0) / 1000;
  const q = r.data.q || [];
  if (q.length) setJoints(q[Math.min(q.length - 1, Math.floor(t * r.data.fps))]);
  r.tiles.forEach((tile) => {
    const cam = tile.cam;
    if (!cam || tile.replay !== r) return;
    if (cam.url) {
      if (!tile.ended && cam.end > 0 && tile.video.currentTime >= cam.end) { tile.video.pause(); tile.ended = true; }
    } else if (cam.frames) {
      const i = Math.min(cam.frames.length - 1, Math.floor(t * cam.fps));
      if (i !== tile.frameIdx) { tile.frameIdx = i; tile.frame.src = cam.frames[i]; }
    }
  });
  const videosDone = r.tiles.every((x) => x.replay !== r || !x.cam || !x.cam.url || x.ended);
  if (t >= (r.data.duration || 0) && videosDone) return;   // 끝: 마지막 장면에서 멈춰 둔다
  r.raf = requestAnimationFrame(() => replayTick(r));
}

function releaseVideo(t) {
  const v = t.video;
  v.onerror = v.onloadedmetadata = v.onseeked = v.onplaying = null;
  v.pause(); v.removeAttribute('src'); v.load();
}

function replayFallback(r, t) {   // 그 칸만 샘플(스트림)로 돌린다 (코덱 등 재생 실패)
  if (t.replay !== r) return;
  t.replay = null; t.cam = null;
  releaseVideo(t);
  if (r.clock && r.clock.video === t.video) r.clock = null;
  loadStream(t);
}

function pauseReplay() {   // 비상정지: 영상·3D를 그 자리에서 멈춘다
  const r = replay;
  if (!r || r.paused) return;
  r.paused = true;
  cancelAnimationFrame(r.raf);
  r.tiles.forEach((t) => { if (t.replay === r) t.video.pause(); });
}

function clearReplay() {
  const r = replay;
  if (!r) return;
  replay = null;
  cancelAnimationFrame(r.raf);
  r.tiles.forEach((t) => {
    if (t.replay !== r) return;
    t.replay = null; t.cam = null;
    releaseVideo(t);
    t.frame.removeAttribute('src');
    loadStream(t);
  });
  if (S.twin.mode !== 'live' && r.data.q && r.data.q.length) setJoints(r.data.q[0]);
}
```

(7) 목업 info: `createMock` 안 `api.start()`의 다음 줄을
```javascript
      emit({ type: 'info', target: { name: '오란다' }, models: { vision: 'YOLO-World · OpenVINO · GPU', llm: 'API · openrouter', stt: 'Whisper · OpenVINO · CPU', act: 'ACT · OpenVINO · GPU' } });
```
다음으로 바꾼다:
```javascript
      emit({ type: 'info', target: { name: '오란다' }, models: { vision: 'YOLO-World · OpenVINO · GPU', llm: 'API · openrouter', stt: 'Whisper · OpenVINO · CPU', act: 'ACT · OpenVINO · GPU' },
        ui: { tiles: DEFAULT_TILES }, twin: { mode: 'mock', urdf: DEFAULT_URDF }, replays: [] });
```

(8) 파일 맨 끝의 다음 세 줄을
```javascript
  return api;
}
})();
```
다음으로 바꾼다:
```javascript
  return api;
}

/* ---------- start (모든 선언 뒤) ---------- */
if (MOCK_FORCED) startMock(); else connect();
})();
```

확인: `grep -n "camImg\|camEmptyText\|loadCam" frontend/app.js frontend/index.html` → 아무것도 안 나온다.

- [ ] **Step 7: 자동 테스트 (서버 쪽이 그대로인지)**

Run: `.venv/Scripts/python -m pytest -q`
Expected: 모두 통과

- [ ] **Step 8: 브라우저 확인용 가짜 재생 데이터 만들기**

`replays/`는 git 제외 폴더라 저장소에 남지 않는다. 프로젝트 루트에서 (Git Bash):
```bash
.venv/Scripts/python - <<'PY'
import json, math
from pathlib import Path
import cv2, numpy as np

for skill, secs in (("oranda_pickup", 4.0), ("dori_dori", 3.0)):
    out = Path("replays") / skill
    (out / "frames" / "follow_cam").mkdir(parents=True, exist_ok=True)
    fps, n, lead = 30, int(secs * 30), 1.0      # lead: 영상 안의 시작 위치 (Studio 영상은 여러 에피소드가 한 파일)
    joints = [[40 * math.sin(2 * math.pi * i / fps), -20, 30, 10 * math.sin(4 * math.pi * i / fps), 0,
               30 + 20 * math.sin(2 * math.pi * i / fps)] for i in range(n)]
    w = cv2.VideoWriter(str(out / "tower_cam.webm"), cv2.VideoWriter_fourcc(*"VP80"), fps, (640, 360))
    for i in range(int((secs + 2 * lead) * fps)):
        img = np.full((360, 640, 3), (160, 90, 40), np.uint8)
        cv2.putText(img, f"{skill} t={i / fps - lead:5.2f}s", (30, 190), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
        w.write(img)
    w.release()
    count = int(secs * 10)
    for i in range(count):
        img = np.full((360, 640, 3), (60, 140, 60), np.uint8)
        cv2.putText(img, f"follow #{i}", (30, 190), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
        cv2.imwrite(str(out / "frames" / "follow_cam" / f"{i:06d}.jpg"), img)
    doc = {"skill": skill, "source": "run", "fps": fps, "joints": joints,
           "cameras": {"tower cam": {"video": "tower_cam.webm", "start": lead, "end": lead + secs},
                       "follow cam": {"frames": "frames/follow_cam", "fps": 10, "count": count}}}
    (out / "episode.json").write_text(json.dumps(doc), encoding="utf-8")
    print(out, n, "joints,", count, "frames")
PY
```
Expected: `replays\oranda_pickup 120 joints, 40 frames`, `replays\dori_dori 90 joints, 30 frames`

- [ ] **Step 9: 브라우저 확인 (수동, Chrome 또는 Edge)**

서버: `.venv/Scripts/python -m snackbot --dry-run` → `http://localhost:8000` (DevTools 열어 둔다)

| # | 할 것 | 기대 |
|---|---|---|
| 1 | 페이지 열기 | 카메라 칸이 2×2: `tower cam`(트레이 사진), `side cam`·`follow cam`(DRY-RUN 이름표 화면), `3D`(노란 SO-101 팔, 바닥 격자). 칸마다 왼쪽 위 이름표 |
| 2 | 3D 칸에서 드래그·휠 | 회전·확대된다. Console에 import 오류 없음. Network: `/vendor/three/build/three.module.js`, `three.core.js`, `/vendor/urdf-loader/src/URDFLoader.js`, STL 13개 모두 200 |
| 3 | 채팅 `2개 옮겨줘` | 단계가 `옮기기`가 되는 순간 `tower cam` 칸이 `oranda_pickup t= 0.00s`부터 영상 재생, `follow cam` 칸이 `follow #0`부터 번호 증가, 3D 팔이 좌우로 흔들림(어깨) — 셋이 함께 움직인다 |
| 4 | 같은 사이클 끝 | 영상이 `t≈4.00s`에서 멈출 무렵 단계가 `복귀`로 넘어간다 (`DrySkills` 동작 시간 = 에피소드 4초). 다음 `개수 세기`에서 칸들이 원래 화면으로 돌아온다 |
| 5 | 다시 옮기기 중 `비상정지` | 영상·프레임·3D가 그 자리에서 멈춘다. `재시작` → 칸들이 원래 화면으로 |
| 6 | 횟수를 늘려 거부(도리도리)까지 진행 (`7개 옮겨줘` 등) | 도리도리 차례에 `dori_dori t=...` 영상과 3D 재생 |
| 7 | `http://localhost:8000/?mock` | 목업 모드: 카메라 칸 3개 "카메라 자리표시 (목업)", 3D 팔이 천천히 흔들림 |
| 8 | 창 폭을 760px 이하로 | 칸이 1열로 |
| 9 | 3D 오류 처리: 프로젝트 루트에 `twin-check.yaml`을 `config.yaml` 복사본으로 만들고 `twin.urdf`를 `twin/none.urdf`로 바꿔 `.venv/Scripts/python -m snackbot --dry-run --config twin-check.yaml` | 3D 칸만 "3D 없음", 나머지 칸·채팅·로봇 루프 정상 |
| 10 | 영상 오류 처리: `replays/oranda_pickup/episode.json`의 `"tower_cam.webm"`을 `"missing.webm"`으로 바꾸고 서버 재시작 후 옮기기 | `tower cam` 칸만 원래 화면(트레이 사진)으로, `follow cam`·3D 재생은 계속 |
| 11 | iframe 칸: `twin-check.yaml`의 `ui.tiles`를 `[tower cam, side cam, {iframe: "https://example.com", name: 예시}, twin]`로 바꿔 실행 | 셋째 칸에 example.com 페이지 |

확인 뒤 정리: `rm twin-check.yaml` (그리고 10번에서 바꾼 `episode.json`은 Step 8을 다시 돌려 되돌린다). `replays/`는 git 제외라 그대로 둬도 된다.

- [ ] **Step 10: 커밋**

```bash
git status --short frontend
git add frontend/index.html frontend/app.js frontend/style.css frontend/twin.js frontend/vendor frontend/twin
git commit -m "feat(frontend): 4분할 화면, 3D 디지털 트윈(three·urdf-loader 고정 버전), dry-run 녹화 재생

Co-Authored-By: <세션의 attribution 줄>"
```
(`git status`에 `replays/`, `twin-check.yaml`이 보이면 커밋하지 않는다.)

---

### Task 7: 문서 — 현장 절차, CLAUDE.md, 연동 계약, 교차 링크

**Files:**
- Modify: `docs/DEMO_RUNBOOK.md`, `CLAUDE.md`, `docs/UI_DESIGN_PROMPT.md`, `docs/superpowers/specs/2026-10-22-digital-twin-design.md`, `docs/superpowers/specs/2026-10-22-chat-ui-design.md`

**Interfaces:**
- Consumes: Task 1~6의 명령·파일 이름 (`tools.cameras`, `tools.fetch_replays`, `logs/runs/`, `replays/`, `twin.sign`/`offset_deg`, `joints` 메시지, `/stream/{cam}`, `/api/replay/{skill}`)
- Produces: 문서만 (코드 변경 없음)

- [ ] **Step 1: DEMO_RUNBOOK에 화면·재생 절 추가**

`docs/DEMO_RUNBOOK.md`의 `- 비상정지는 토크를 켠 채 그 자리를 유지한다. ...` 문단 바로 다음(`## 3. 진행자 대본 예시` 앞)에 넣는다:
```markdown

## 2-3. 화면 4분할 · 3D 트윈 · 녹화 재생 (설계: `docs/superpowers/specs/2026-10-22-digital-twin-design.md`)

화면 카메라 칸은 2×2: `tower cam` · `side cam` · `follow cam` + 3D 팔. 순서·내용은 `config.yaml`의 `ui.tiles` (칸에 `{iframe: URL, name: 이름}`도 넣을 수 있다).

**카메라 찾기 (노트북, 처음 한 번 · USB를 바꿔 꽂았을 때)** — Studio 세션을 먼저 닫는다
- [ ] `.venv/bin/python -m tools.cameras` → 장치마다 번호·이름·시리얼과 사진 `cameras/<번호>.jpg`
- [ ] 사진을 보고 어느 장치가 어느 카메라인지 정해, 출력 끝 예시를 `config.yaml` `cameras`에 붙여 넣는다. 시리얼이 있으면 `device: {serial: "..."}` (다시 꽂아도 같은 장치), 없으면 번호

**녹화 받기 (로봇이 안 될 때 대비, Studio가 켜진 PC와 같은 네트워크에서)**
- [ ] Studio에서 보여 줄 에피소드를 연다 → 주소창 `/projects/<프로젝트>/datasets/<데이터셋 id>/episodes/<번호>`에서 id와 번호를 `config.yaml` `skills.oranda_pickup.replay`, `skills.dori_dori.replay`에 쓴다 (`{dataset: <id>, episode: <번호>}`)
- [ ] `python -m tools.fetch_replays --studio http://192.168.0.6:7860 --skill oranda_pickup` (dori_dori도 같은 방법. 조회만 한다) → `replays/<스킬>/episode.json` + 카메라별 `.mp4`
- [ ] 카메라 이름이 config와 다르게 학습됐으면(`camera_map`) 자동으로 config 이름으로 바꿔 저장한다. "config cameras에 없어요" 주의가 나오면 `camera_map` 확인
- [ ] `python -m snackbot --dry-run` → 옮기기·도리도리 차례에 카메라 칸은 녹화 영상, 3D 칸은 같은 에피소드 관절 궤적이 함께 움직이는지 확인 (영상이 안 나오면 Chrome/Edge로. Studio 영상 코덱이 브라우저에서 안 되면 그 칸만 원래 화면으로 나온다)

**실행 기록 (실제 로봇)**
- [ ] `recording.enabled: true`면 스킬을 실행할 때마다 `logs/runs/<YYYYmmdd-HHMMSS>_<스킬>/`에 정책 구간의 관절값(`episode.json`)과 카메라 사진(`frames/`, `frame_fps`장/초)이 쌓인다. 기록 실패는 경고만, 로봇 동작에는 영향 없다
- [ ] 잘 된 실행 하나를 재생 데이터로: 기존 것을 치우고 복사 — `rm -rf replays/oranda_pickup && cp -r logs/runs/20261023-101500_oranda_pickup replays/oranda_pickup`

**3D 방향 맞추기 (실제 로봇, 처음 한 번)**
- [ ] `python -m snackbot` 화면에서 3D 팔이 실제 팔을 따라 움직이는지 본다 (`robot.calibration` 파일이 있으면 그 범위로 변환)
- [ ] 관절이 반대로 돌면 `twin.sign`의 그 자리를 `-1`, 영점이 어긋나면 `twin.offset_deg`(도)로 맞춘다. 순서: shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper
```

같은 파일 `## 4. 장애 대응` 표의 마지막 줄
```markdown
| 전부 안 됨 | — | 백업 영상 재생 |
```
을 다음으로 바꾼다:
```markdown
| 카메라 칸이 "카메라 없음" | 장치 번호가 바뀜, 다른 프로그램이 점유 | Studio 닫기, `python -m tools.cameras`로 확인 후 `cameras.<이름>.device` (시리얼 권장) |
| 3D 칸이 "3D 없음" | `frontend/vendor/`·`frontend/twin/so101/` 파일 누락, WebGL 꺼짐 | 브라우저 콘솔 확인. 나머지 화면·로봇은 그대로 동작 |
| 로봇·카메라가 안 됨 | 하드웨어 문제 | `python -m snackbot --dry-run`: 옮기기·도리도리 차례에 녹화 재생 (2-3절 녹화 받기) |
| 전부 안 됨 | — | 백업 영상 재생 |
```

- [ ] **Step 2: CLAUDE.md 갱신**

파일 구조에서 다음 줄을
```
│   ├── server.py       # FastAPI: /ws, /stt, /stream/front, frontend/ 서빙
```
다음으로 바꾼다:
```
│   ├── server.py       # FastAPI: /ws, /stt, /stream/{cam}, /api/replay/{skill}, /replays, frontend/ 서빙
```
`│   ├── motion.py ...` 줄 다음에 두 줄을 넣는다:
```
│   ├── twin.py         # 3D 트윈: 관절 normalized→라디안, 재생 에피소드(episode.json) 읽기
│   ├── recorder.py     # 실행 기록: 정책 phase 관절값·프레임 → logs/runs/ (백그라운드 저장)
```
다음 줄을
```
├── frontend/           # Claude Design 결과물 (index.html, app.js, style.css)
```
다음으로 바꾼다:
```
├── frontend/           # Claude Design 결과물 (index.html, app.js, style.css) + twin.js(3D)
│   ├── vendor/         # three@0.186.1, urdf-loader@0.13.1 고정 파일 (import map)
│   └── twin/so101/     # SO-101 URDF + STL (Apache-2.0)
```
`│   ├── robot_probe.py ...` 줄 다음에 두 줄을 넣는다:
```
│   ├── fetch_replays.py       # Studio 녹화 에피소드 → replays/<스킬>/ (GET만, dry-run 재생용)
│   ├── cameras.py             # 카메라 목록·시리얼·사진 1장 → config cameras 예시
```
`├── logs/ ...` 줄 다음에 넣는다:
```
├── replays/            # dry-run 재생 데이터 replays/<스킬>/episode.json (git 제외)
```
"로봇 노트북" 명령 블록의 `.venv/bin/python -m snackbot.robot home ...` 줄 다음에 넣는다:
```bash
.venv/bin/python -m tools.cameras                     # 카메라 번호·시리얼·사진 (cameras/)
.venv/bin/python -m tools.fetch_replays --studio http://192.168.0.6:7860 --skill oranda_pickup   # 녹화 받기
```
`## 문서` 목록의 첫 줄 다음에 넣는다:
```markdown
- `docs/superpowers/specs/2026-10-22-digital-twin-design.md` — 4분할 화면·3D 트윈·녹화 재생·실행 기록 (UI·트윈 부분은 위 문서보다 우선)
```

- [ ] **Step 3: 서버 연동 계약 갱신 (`docs/UI_DESIGN_PROMPT.md`)**

`연결 직후 한 번 (옮길 과자, 모델 정보):` 다음의 info 예시 줄을 다음으로 바꾼다:
```
{"type":"info","target":{"name":"오란다"},"models":{"vision":"YOLO-World · OpenVINO · GPU","llm":"API · openrouter","stt":"Whisper · OpenVINO · CPU","act":"ACT · OpenVINO · GPU"},"ui":{"tiles":[{"kind":"camera","name":"tower cam","available":true},{"kind":"camera","name":"side cam","available":true},{"kind":"camera","name":"follow cam","available":true},{"kind":"twin","name":"3D"}]},"twin":{"mode":"replay","urdf":"twin/so101/so101_new_calib.urdf"},"replays":["dori_dori"]}
- ui.tiles: 2×2 칸 순서. kind: camera(available=false면 "카메라 없음") | twin | iframe({"kind":"iframe","name":"Studio","url":"http://..."})
- twin.mode: live(실제 로봇, joints 메시지) | replay(dry-run, phase acting 순간 /api/replay/<skill> 재생)
- replays: 재생 데이터가 있는 스킬
```
`사이클 결과 (한 사이클이 끝날 때마다):` 블록(두 줄 설명 포함) 다음에 넣는다:
```
3D 팔 관절 (실제 로봇에서만, 값이 바뀔 때마다 · 연결 직후 마지막 값 한 번):
{"type":"joints","q":[0.0123,-0.4012,0.8890,0.1000,0.0000,0.3500]}
- q: 라디안 6개, 순서 shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper (URDF 관절 이름)
```
`### 카메라 영상` 절 전체(두 줄)를 다음으로 바꾼다:
```
### 카메라 영상
GET /stream/<카메라 이름> → MJPEG (<img src="/stream/tower%20cam">). config cameras에 없는 이름은 404.
vision 카메라에는 검출 박스를 서버가 그려 보낸다. GET /stream/front 는 vision 카메라 (예전 화면용).
끊기면 "카메라 없음" 표시. 목업 모드에서는 회색 자리표시.

### 녹화 재생 (dry-run)
GET /api/replay/<skill> → {"skill","source","fps","q":[[라디안 6개],...],"duration","cameras":{"tower cam":{"url":"/replays/<skill>/tower_cam.mp4","start":12.3,"end":18.9},"follow cam":{"frames":["/replays/<skill>/frames/follow_cam/000000.jpg",...],"fps":10}}}
- 없으면 404. 영상은 start~end 구간만 튼다. q는 영상 시계(currentTime − start)에 맞춰 3D에 적용한다.
```

- [ ] **Step 4: 설계 문서 교차 링크와 구현 결정**

`docs/superpowers/specs/2026-10-22-chat-ui-design.md`의 `- 기존 문서(ARCHITECTURE / ...)와 충돌하면 **이 문서가 우선**한다.` 줄 다음에 넣는다:
```markdown
- 화면 4분할·3D 디지털 트윈·녹화 재생·실행 기록은 `2026-10-22-digital-twin-design.md`가 이 문서의 UI 부분보다 우선한다.
```

`docs/superpowers/specs/2026-10-22-digital-twin-design.md`의 셋째 줄(`작성 2026-10-22. 의논 기록: ...`) 다음에 빈 줄과 함께 넣는다:
```markdown
구현 계획: `docs/superpowers/plans/2026-10-22-digital-twin.md`.
```
같은 파일 끝에 추가:
```markdown

## 12. 구현 결정 (계획에서 정한 것)

- 3D 모델 파일: `assets/*.stl` 전부가 아니라 **URDF가 참조하는 STL 13개**만 넣는다 (리더 손잡이·카메라 마운트 등은 쓰지 않음, 약 16MB). 원본 커밋 `a758567`에 고정.
- `load_episode`: 파일이 없으면 조용히 None (재생 데이터가 없는 것이 보통), 깨졌으면 경고 + None.
- dry-run 카메라 칸: `/stream/<이름>`이 vision 카메라는 트레이 사진, config의 다른 카메라는 "DRY-RUN <이름>" 화면. config에 없는 이름은 404.
- `joints` 변환은 서버에서 (`twin.make_converter`: `robot.calibration` 파일이 있으면 그 범위 + `twin.sign`/`offset_deg`). 새 WebSocket 연결은 마지막 joints를 한 번 받는다 (팔이 멈춰 있으면 다음 값이 오지 않으므로). `RobotSkills.connect()`가 관절 캐시를 채운다.
- 실행 기록 `fps`는 실제 틱 간격으로 계산한다 (표본이 모자라면 `skills.fps`). 추가 필드: `ms`, `started`, `dropped_frames`. 저장 큐 크기 `recording.queue_size`(기본 64).
- 화면 재생: 첫 영상 칸이 시계 (`playing` 뒤 `currentTime − start`), 영상이 3초 안에 안 나오면 그 칸만 원래 화면으로 돌리고 벽시계. 끝나면 마지막 장면에서 멈춰 두고 다음 `counting`·`IDLE`·`DONE`에서 정리. 개수 표시는 4칸 가운데로 줄여 옮긴다.
- Studio 키 이름(코드 확인): `action_keys`는 `<관절>.pos`, 영상 키는 `observation.images.<카메라 이름 소문자화>`(공백 유지). 영상 경로의 `\`는 `/`로.
```

- [ ] **Step 5: 확인과 커밋**

Run: `.venv/Scripts/python -m pytest -q`
Expected: 모두 통과 (문서만 바뀜)

```bash
git add docs/DEMO_RUNBOOK.md CLAUDE.md docs/UI_DESIGN_PROMPT.md docs/superpowers/specs/2026-10-22-digital-twin-design.md docs/superpowers/specs/2026-10-22-chat-ui-design.md
git commit -m "docs: 4분할·3D 트윈·녹화 재생 현장 절차와 연동 계약

Co-Authored-By: <세션의 attribution 줄>"
```

---

## 실제 로봇·Studio에서만 확인할 수 있는 것 (계획 밖, 현장 체크)

- 3D 팔의 방향·영점: URDF 0 라디안이 SO101 tick 2048(캘리브레이션 범위 가운데)과 맞는지. 다르면 `twin.sign`/`offset_deg` (DEMO_RUNBOOK 2-3절)
- 실제 Studio 응답의 `action_keys`·영상 키 이름 (계획은 Studio 소스 `runtime/features.py`를 기준으로 했다). 다르면 `tools.fetch_replays`가 받은 키 목록과 함께 멈춘다
- Studio 영상 코덱(LeRobot 기본은 AV1일 수 있다)이 시연 노트북의 브라우저에서 재생되는지. 안 되면 그 칸만 원래 화면으로 나온다 → 실행 기록(JPEG 프레임)을 재생 데이터로 쓰는 쪽이 안전
- `discover_uvc()`가 노트북 카메라 3대의 시리얼을 주는지 (없으면 번호로)
- 카메라 3대 + 실행 기록(JPEG 3장 × 10fps) 동안 제어 루프 지연·저장 큐 버림(`dropped_frames`)
- `RobotRuntime` 틱 이벤트의 `Frame.data`가 다음 틱에 재사용되지 않는지 (재사용되면 기록 사진이 섞인다 → `RunRecorder.tick`에서 `.copy()`)
