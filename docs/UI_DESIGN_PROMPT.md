# Claude Design 프롬프트: 과자 옮기기 로봇 관제 화면

````text
# 과자 옮기기 로봇 관제 화면 만들기

## 무엇을 만드나
해커톤 시연용 웹 화면이야. 로봇팔(SO-ARM101)이 여러 과자가 섞인 트레이에서 정해진 과자 한 종류
(지금은 오란다 같은 강정류)만 골라 빈 트레이로 옮긴다.
로봇은 성실하지만 금방 지치는 투덜이 캐릭터라서, 몇 번 일하면 "힘들어요!" 하며 고개를 도리도리 젓고 일을 거부한다.
사람이 채팅이나 목소리로 달래면 다시 일한다.
이 화면은 발표장 프로젝터(1920×1080 가로)에 띄워서 관객이 보는 화면이자, 진행자가 조작하는 화면이야.
노트북 화면(1366×768)에서도 깨지지 않아야 해. 모든 UI 문구는 한국어.

옮길 과자 이름은 화면에 고정으로 쓰지 말고 서버가 보내 주는 info.target.name을 써.
("오란다 3개 남음"처럼). 받기 전에는 "과자"로 표시.

## 대표 기능 (중요도 순)
1. 채팅으로 작업 지시: "과자 옮겨줘"라고 치면 로봇이 일을 시작한다. 잡담에도 투덜이 말투로 대답한다.
2. 🎤 누르고 말하기: 버튼을 누르는 동안 녹음하고, 떼면 서버로 보낸다.
3. 피로도 게이지: 옮긴 횟수(count)가 쌓일수록 로봇이 지쳐 가는 모습이 한눈에 보여야 한다.
   - count ≤ safe_max: 쌩쌩
   - safe_max < count < force_refuse: 지침 (거부할 수도 있음)
   - count ≥ force_refuse: 한계
   - 거부 상태(REFUSING)일 때는 화면 전체에서 "거부 중"이 확실히 느껴지는 연출 (예: 로봇 아이콘이 도리도리)
4. 실시간 카메라 영상 + 남은 과자 개수: 크게. 개수를 무엇으로 셌는지(yolo / vlm / opencv)도 작게 표시.
   vision_method가 estimate면 카메라로 센 값이 아니라 "시작 개수 − 성공 수" 추정치라는 뜻이니 "추정"으로 표시.
5. 진행자 버튼: 비상정지(항상 보이고, 빨갛고, 큼), 재개, 재시작.
6. 성능 패널: 사이클마다 개수 세기 / LLM / ACT / 복귀 소요 시간(ms)과 성공률.
   사용 중인 모델과 실행 위치(예: "ACT · OpenVINO · GPU", "LLM · API")를 보여 줘서
   로봇 제어가 노트북 안에서 OpenVINO로 돈다는 게 드러나게.

## 화면 구성 제안 (더 나은 안이 있으면 바꿔도 됨)
- 왼쪽 큰 영역: 카메라 영상, 그 위에 남은 과자 개수 오버레이
- 오른쪽: 로봇 캐릭터 + 상태 배지 + 현재 단계 + 피로도 게이지, 그 아래 채팅(말풍선) + 입력창 + 🎤
- 하단 띠: 성능 패널, 진행자 버튼
- 비상정지 버튼은 어떤 상태에서도 같은 자리에 보여야 함

## 상태와 단계
state: IDLE(대기) | WORKING(작업 중) | REFUSING(거부 중) | DONE(완료) | ESTOP(비상정지)
phase: idle | counting(개수 세는 중) | thinking(생각 중) | speaking(대사 소리 시작 대기) | acting(옮기는 중) | returning(제자리로) | waiting_operator(도움 필요)
- 버튼 활성화
  - 재개: REFUSING이거나 phase가 waiting_operator일 때만
  - 재시작: ESTOP일 때만
  - 비상정지: IDLE / DONE이 아닐 때, ESTOP이라도 phase가 returning(재시작으로 홈 복귀 중)이면 켠다
- ESTOP일 때는 화면 전체를 빨간 테두리 등으로 확실히 표시

## 기술 조건 (반드시 지킬 것)
- 빌드 없는 정적 파일 3개: index.html, app.js, style.css
  (npm, 번들러, 프레임워크 없이. 외부 CDN 라이브러리는 꼭 필요할 때만.)
- 로봇 PC의 Python 서버(FastAPI)가 이 파일들을 그대로 서빙한다. 모든 주소는 같은 origin 기준 상대 경로.
- 화면에 보이는 대화와 상태는 오직 서버 메시지로만 그린다.
  내가 보낸 채팅도 화면에 바로 그리지 말고, 서버가 되돌려 주는 message를 받았을 때 그린다 (기록이 한 곳에서만 관리되도록).
- WebSocket이 끊기면 "연결 끊김" 표시 후 2초마다 자동 재연결.
- 목업 모드: URL에 ?mock 이 있거나 WebSocket 연결이 안 되면, app.js 안의 시뮬레이터가 아래 메시지를 흉내 낸다.
  서버 없이 열어도 전체 흐름(대기 → 작업 → 지침 → 거부 → 재개 → 완료)이 자동으로 재생되어야 함.

## 서버 연동 계약

### WebSocket: ws(s)://<같은 host>/ws (JSON 텍스트 메시지)

서버 → 화면

연결 직후 한 번 (옮길 과자, 모델 정보):
{"type":"info","target":{"name":"오란다"},"models":{"vision":"YOLO-World · OpenVINO · GPU","llm":"API · openrouter","stt":"Whisper · OpenVINO · CPU","act":"ACT · OpenVINO · GPU"},"ui":{"tiles":[{"kind":"camera","name":"tower cam","available":true},{"kind":"camera","name":"side cam","available":true},{"kind":"camera","name":"follow cam","available":true},{"kind":"twin","name":"3D"}]},"twin":{"mode":"replay","urdf":"twin/so101/so101_new_calib.urdf"},"replays":["dori_dori"]}
- ui.tiles: 2×2 칸 순서. kind: camera(available=false면 "카메라 없음") | twin | iframe({"kind":"iframe","name":"Studio","url":"http://..."})
- twin.mode: live(실제 로봇, joints 메시지) | replay(dry-run, phase acting 순간 /api/replay/<skill> 재생)
- replays: 재생 데이터가 있는 스킬

상태가 바뀔 때마다 (연결 직후에도 한 번):
{"type":"state","state":"WORKING","phase":"acting","count":2,"remaining":3,"skill":"oranda_pickup","vision_method":"yolo","thresholds":{"safe_max":3,"force_refuse":6}}
- skill: oranda_pickup | dori_dori | done | null
- vision_method: estimate | yolo | vlm | opencv | fake

대화 (연결 직후 최근 50개를 순서대로 다시 보냄):
{"type":"message","role":"user","text":"과자 옮겨줘","source":"text","ts":1729580000.1}
{"type":"message","role":"robot","text":"으… 팔이 조금 뻐근한데요.","ts":1729580001.4}
{"type":"message","role":"system","text":"비상정지됨","ts":1729580002.0}
- role: user | robot | system
- source(user일 때만): text | voice (voice면 🎤 표시)

사이클 결과 (한 사이클이 끝날 때마다):
{"type":"cycle","n":5,"result":"success","ms":{"vision":820,"llm":1100,"act":14200,"return":3100}}
- result: success | fail | refuse | done | estop
- ms의 키는 일부 빠질 수 있음

3D 팔 관절 (실제 로봇에서만, 값이 바뀔 때마다 · 연결 직후 마지막 값 한 번):
{"type":"joints","q":[0.0123,-0.4012,0.8890,0.1000,0.0000,0.3500]}
- q: 라디안 6개, 순서 shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper (URDF 관절 이름)

화면 → 서버
{"type":"chat","text":"과자 옮겨줘"}
{"type":"command","name":"resume"}   // name: resume | estop | restart

### 카메라 영상
GET /stream/<카메라 이름> → MJPEG (<img src="/stream/tower%20cam">). config cameras에 없는 이름은 404.
vision 카메라에는 검출 박스를 서버가 그려 보낸다. GET /stream/front 는 vision 카메라 (예전 화면용).
끊기면 "카메라 없음" 표시. 목업 모드에서는 회색 자리표시.

### 녹화 재생 (dry-run)
GET /api/replay/<skill> → {"skill","source","fps","q":[[라디안 6개],...],"duration","cameras":{"tower cam":{"url":"/replays/<skill>/tower_cam.mp4","start":12.3,"end":18.9},"follow cam":{"frames":["/replays/<skill>/frames/follow_cam/000000.jpg",...],"fps":10}}}
- 없으면 404. 영상은 start~end 구간만 튼다. q는 영상 시계(currentTime − start)에 맞춰 3D에 적용한다.

### 음성 입력
POST /stt
- body: 16kHz · mono · 16bit PCM WAV, Content-Type: audio/wav
- 응답: {"text":"조금만 더 해줘"}
- 브라우저에서 녹음해 WAV로 변환하는 것까지 app.js가 한다 (MediaRecorder + AudioContext로 리샘플링).
- 인식된 문장은 서버가 WebSocket message로 다시 보내 주니, 응답 text로는 화면에 그리지 않는다.
- 녹음 중, 인식 중 표시는 필요.

## 분위기
- 귀엽고 친근한 과자 공장 느낌. 그래도 관제 화면답게 정보는 또렷하게.
- 프로젝터용이라 글자와 대비가 커야 함. 남은 개수, 상태, 비상정지는 멀리서도 보여야 함.
- 로봇 대사가 나올 때 말풍선 등장 애니메이션 정도의 생동감.
````
