# 설계: 4분할 화면 · 3D 디지털 트윈 · 녹화 재생 · 실행 기록

작성 2026-10-22. 의논 기록: `docs/memo/2026-10-22-robot-runtime-and-twin.html`. 기존 기준 설계(`2026-10-22-chat-ui-design.md`)를 확장하며, 충돌하면 이 문서가 UI·트윈 부분에서 우선한다.

## 1. 목표와 범위

- 카메라 칸을 **2×2 격자**로: 카메라 3칸(`tower cam`, `side cam`, `follow cam`) + **3D 팔(디지털 트윈)** 1칸.
- **실제 로봇 모드:** 카메라 3대 실시간 + 3D 팔이 실제 관절값을 따라 움직인다.
- **dry-run(로봇·카메라가 안 될 때 대비책):** 옮기기·도리도리를 할 차례에 그 스킬의 **녹화 에피소드 1개**(Studio 녹화 또는 우리가 저장한 실행 기록)를 재생한다. 카메라 칸에는 녹화 영상, 3D 칸에는 같은 에피소드의 관절 궤적이 시간을 맞춰 움직인다.
- **실행 기록:** 실제 로봇에서 스킬 1회 실행마다 관절값과 카메라 프레임을 저장한다 (녹화 재생과 같은 형식).
- **카메라 찾기 도구**와 **시리얼 지정**으로 카메라 이름 ↔ 실제 장치를 안정적으로 맞춘다.
- 칸마다 config로 iframe URL(예: Studio 화면)을 넣을 수 있다.

범위 밖: 녹화 궤적으로 실제 팔을 움직이기, ACT를 시뮬레이션 안에서 돌리기, Studio 화면 조종.

## 2. 설정 (config.yaml 추가)

```yaml
ui:
  tiles: [tower cam, side cam, follow cam, twin]   # 각 칸: config 카메라 이름 | twin | {iframe: URL}

twin:
  urdf: twin/so101/so101_new_calib.urdf   # frontend/ 기준 경로 (정적 서빙)
  rate_hz: 15                             # 실시간 관절값 전송 주기
  sign: [1, 1, 1, 1, 1, 1]                # 관절별 부호 보정 (3D와 실제 방향이 반대면 -1)
  offset_deg: [0, 0, 0, 0, 0, 0]          # 관절별 영점 보정 (도)

replays_dir: replays                      # git 제외. replays/<스킬>/episode.json

recording:
  enabled: true
  dir: logs/runs                          # git 제외 (logs/*)
  frame_fps: 10
  frame_width: 640

skills:
  oranda_pickup: {..., replay: {dataset: <Studio 데이터셋 id>, episode: <번호>}}   # fetch_replays가 읽는다
  dori_dori:     {..., replay: {dataset: ..., episode: ...}}
```

- `ui.tiles`가 없으면 기본값 `[tower cam, side cam, follow cam, twin]`. config `cameras`에 없는 이름의 칸은 "카메라 없음"으로 그린다.
- 카메라 `device`는 번호(`0` → `/dev/video0`) 또는 `{serial: "..."}` (physicalai `UVCCamera`가 그대로 받는다).

## 3. 관절 변환 (`snackbot/twin.py`, 하드웨어 없음)

- `JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")` — URDF 관절 이름과 같다.
- `to_radians(values, calibration=None, sign=None, offset_deg=None) -> list[float]` (6개)
  - physicalai SO101과 같은 식으로 normalized → tick: 몸통 `tick = range_min + (v + 100) / 200 × (range_max − range_min)`, 그리퍼 `tick = range_min + v / 100 × (range_max − range_min)` (값은 각각 −100..100, 0..100으로 자른다).
  - tick → 라디안: `(tick − 2048) × 2π / 4096`, 그다음 `× sign + radians(offset_deg)`.
  - `calibration`이 없으면 관절마다 `range_min=0, range_max=4095`.
- `load_episode(folder) -> dict | None`: `episode.json`을 읽어 형식을 검사한다 (없거나 깨지면 None, 경고 로그).
- `episode_duration(ep) -> float` = 프레임 수 / fps.

### episode.json 형식 (녹화 받기와 실행 기록이 같은 형식)
```json
{"skill": "dori_dori", "source": "studio|run", "fps": 30,
 "joints": [[6개 normalized], ...],
 "cameras": {"tower cam": {"video": "tower_cam.mp4", "start": 12.3, "end": 18.9},
             "follow cam": {"frames": "frames/follow_cam", "fps": 10, "count": 66}}}
```
- 카메라마다 `video`(파일 + 영상 안의 시작·끝 초) 또는 `frames`(JPEG 순번 폴더 `000000.jpg`…) 중 하나.
- 카메라 키는 **config 카메라 이름**이다 (학습 이름이면 `camera_map`으로 바꿔서 저장).

## 4. 녹화 받기 (`tools/fetch_replays.py`, 노트북에서, GET만)

```
python -m tools.fetch_replays --studio http://192.168.0.6:7860 --skill oranda_pickup [--dataset ID --episode N] [--config config.yaml]
```
- `--dataset/--episode`가 없으면 config `skills.<스킬>.replay`를 쓴다.
- `GET /api/dataset/{id}/episodes/{n}` → `{fps, actions, action_keys, videos: {키: {start, end, path}}}`.
  - `action_keys`(예: `shoulder_pan.pos`)를 `JOINTS` 순서로 재배열해 `joints`로 저장. 모르는 키 배치면 SystemExit(받은 키 목록).
  - 영상 키(`observation.images.<학습 이름>` 꼴)에서 학습 이름을 뽑아 `camera_map`의 역방향으로 config 이름으로 바꾼다.
  - 영상마다 `GET /api/dataset/{id}/video/{path}`를 스트리밍으로 받아 `replays/<스킬>/<카메라 이름 안전화>.mp4`로 저장, `start/end`를 기록.
- 모든 요청 timeout, 연결·HTTP 오류는 한국어 안내 후 SystemExit. 쓰기 요청 없음.

## 5. 카메라 찾기 (`tools/cameras.py`, 노트북에서)

```
python -m tools.cameras            # 목록 + 카메라마다 사진 1장
```
- physicalai `discover_uvc()`(lazy import)로 장치 목록을 받아 번호·이름·시리얼(있으면)을 출력하고, 각 장치를 열어 프레임 1장을 `cameras/<번호>.jpg`로 저장한다 (실패한 장치는 건너뛰고 표시).
- 출력 끝에 config에 붙여 넣을 예시(`tower cam: {device: {serial: "..."}}`)를 보여 준다.
- `cameras/`는 git 제외.

## 6. 실행 기록 (`snackbot/recorder.py` + `robot.py`)

- `RunRecorder(cfg)`: `start(skill)` → 폴더 `logs/runs/<YYYYmmdd-HHMMSS>_<스킬>/` 생성, `tick(joints, frames, t)`는 관절을 매 틱 메모리에, 프레임은 `frame_fps`로 솎아 **백그라운드 스레드**가 JPEG(`frame_width`로 줄임)로 저장, `stop(result)` → `episode.json`(`source: "run"`, `stop_reason`, `grasped` 포함) 쓰기.
- `RobotSkills.run()`의 정책 phase 동안만 기록한다 (보간 이동은 제외). 기록 실패는 경고만, 로봇 동작에 영향 없음. 제어 스레드(Tap)에서는 큐에 넣기만 한다 (가득 차면 프레임을 버림).
- `recording.enabled: false`면 아무것도 하지 않는다.
- 저장된 폴더를 `replays/<스킬>/`로 복사하면 그대로 dry-run 재생에 쓰인다.

## 7. 서버 (`snackbot/server.py`)

- `GET /stream/{cam}`: 해당 카메라 MJPEG (`frame_fn(cam)`). 기존 `/stream/front`는 `vision.camera`로 유지.
- `GET /api/replay/{skill}`: `replays/<스킬>/episode.json`을 읽어 `{fps, q: [[라디안 6개], ...], duration, cameras: {이름: {url, start, end} | {frames: [url, ...], fps}}}`를 돌려준다 (변환은 `twin.to_radians`, 캘리브레이션 파일이 있으면 사용). 없으면 404.
- 정적: `/replays/...`(replays_dir), 프론트엔드는 기존대로.
- WebSocket `joints` 메시지: `{"type": "joints", "q": [라디안 6개]}`. 서버가 `joints_fn()`(실제 로봇: `RobotSkills.latest_joints()`, dry-run: None)을 `rate_hz`로 읽어 값이 바뀌었을 때만 모든 연결에 보낸다.
- `info`에 추가: `ui.tiles`, `twin: {mode: "live" | "replay", urdf}`, `replays: [재생 가능한 스킬 이름]`.

## 8. dry-run 재생 동기

- 새 WebSocket 메시지는 만들지 않는다. 화면은 `state.phase == "acting"`이 되는 순간 `state.skill`의 재생을 시작한다 (`twin.mode == "replay"`이고 그 스킬의 재생 데이터가 있을 때).
- `DrySkills`는 그 스킬의 재생 데이터가 있으면 동작 시간을 **에피소드 길이**로 쓴다 (없으면 기존 `act_s`). 그래서 단계 표시줄의 옮기기→복귀와 영상이 함께 끝난다.
- 재생 중 비상정지면 영상·3D를 그 자리에서 멈춘다.

## 9. 화면 (`frontend/`)

- 카메라 칸을 `ui.tiles` 순서의 2×2 격자로 (좁으면 1열). 칸마다 이름표.
  - 카메라 칸: 실제 로봇 → `<img src="/stream/<이름>">`, dry-run 재생 중 → `<video>`(start~end 구간) 또는 프레임 순번 이미지, 그 밖 → 기존 샘플/"카메라 없음".
  - `twin` 칸: `frontend/twin.js`가 three.js + urdf-loader로 URDF를 그린다. 실시간 모드는 `joints` 메시지, 재생 모드는 `/api/replay/{skill}`의 `q`를 영상 시계(`currentTime − start`)에 맞춰 적용. 마우스로 회전·확대.
  - `{iframe: URL}` 칸: `<iframe>`.
- 라이브러리: `three@0.186.1`, `urdf-loader@0.13.1`을 `frontend/vendor/`에 고정 버전으로 넣고 import map으로 연결한다 (빌드 없음, 오프라인 동작).
- 3D 모델: TheRobotStudio/SO-ARM100 `Simulation/SO101/so101_new_calib.urdf` + `assets/*.stl`을 `frontend/twin/so101/`에 넣는다 (Apache-2.0, `LICENSE`와 출처 `README` 포함, git으로 관리).
- 목업 모드(`?mock`)에서도 4분할과 3D(홈 자세 + 간단한 흔들기)가 보이게 한다.
- 오류: URDF·라이브러리 로드 실패 → 그 칸에 "3D 없음", 영상 재생 실패(코덱 등) → 그 칸만 샘플로. 나머지 화면과 로봇 루프는 영향 없음.

## 10. physicalai·하드웨어 경계

- `snackbot/twin.py`, `recorder.py`는 physicalai를 import하지 않는다 (개발 PC 테스트).
- `tools/cameras.py`는 `discover_uvc`, `UVCCamera`를 함수 안에서만 import.
- `RobotSkills.latest_joints()`는 Tap 캐시를 락으로 복사해 돌려준다 (런타임 미연결이면 None).

## 11. 테스트

- `twin.to_radians`: physicalai `_normalized_to_ticks`와 같은 tick을 내는지(대표 캘리브레이션 값), 기본 범위, sign/offset, 자르기.
- `load_episode`: 정상·누락·깨진 JSON·video/frames 두 형식.
- `fetch_replays`: httpx MockTransport로 GET만, 키 재배열, camera_map 역변환, 영상 스트리밍 저장, 오류 안내.
- `tools.cameras`: 가짜 discover/카메라로 출력·저장.
- `RunRecorder`: 프레임 솎기, 백그라운드 저장, episode.json 형식, 실패 시 경고만, 큐 가득 참.
- 서버: `/stream/{cam}`, `/api/replay/{skill}`(라디안 변환·404), `joints` 브로드캐스트(바뀔 때만), `info` 확장.
- `DrySkills`: 재생 데이터가 있으면 동작 시간 = 에피소드 길이.
- 3D 렌더링 자체는 브라우저에서 확인 (자동 테스트 밖).
