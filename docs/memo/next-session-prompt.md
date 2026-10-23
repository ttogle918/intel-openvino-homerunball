# 다음 세션 시작 프롬프트

> 새 Claude Code 세션(작업 폴더 `C:\Users\ttogl\workspace\openvino_course_2610\project`)에 아래 코드 블록을 그대로 붙여넣는다.

```text
과자 옮기기 로봇(snackbot) 해커톤 프로젝트를 이어서 한다. 소프트웨어 전체, 로봇 연결(M4), 4분할 화면·3D 트윈·녹화 재생·실행 기록, 스킬 1회 실행·코드 도리도리·LLM 도리도리, OpenCV 개수 세기, half 거부 규칙이 구현됐고, 2026-10-23에 시연 노트북(이 Windows PC)에서 첫 실기를 해서 오란다 1회가 성공했다. 다음은 제어 루프 주기 조사와 전체 흐름 실기다.

## 먼저 읽을 것 (이 순서로)
1. CLAUDE.md
2. ../.superpowers/sdd/progress.md  (저장소 루트 = 상위 폴더 openvino_course_2610/ 기준. 진행 기록 끝부분)
3. docs/PROGRESS_REPORT.html  (맨 위 "이번 갱신(2026-10-23 실기)" 박스, 비교표, 다음 할 일)
4. docs/DEMO_RUNBOOK.md  (2-2 로봇 첫 연결, 2-3 4분할·3D·기록, 2-4 스킬 1회·코드 도리도리, 2-5 개수 세기)
5. docs/DECISION_LOGIC.md  (half 거부 규칙)
6. docs/superpowers/specs/2026-10-22-chat-ui-design.md  (11.5~11.7절)
7. ../.superpowers/sdd/field-config-review.md, dori-script-review.md  (리뷰 기록)
그다음 `git log --oneline -15`와 `git status`로 상태를 확인하고, 아래 "현재 상태"와 다르면 알려줘.

## 현재 상태 (2026-10-23 기준)
- 최신 커밋 0ea623b (리뷰 반영: 허용 밖 skill이면 LLM 대사도 버림, 사이클당 세기 방법 한 번, half 게이지). 그 앞 27bdae2 (전체의 절반을 옮기면 작업당 한 번 거부). 브랜치 feat/robot-m4 (git 저장소 루트는 project/의 상위 폴더 openvino_course_2610). 이 세션의 커밋은 사용자가 push한다. 자동 테스트 445개: `.venv/Scripts/python -m pytest -q`.
- **시연 노트북 = 이 Windows 11 PC (192.168.0.17).** 노트북 계획은 접었다. physicalai 0.3.0을 project/.venv에 설치했다(사용자 승인). 실제 로봇 명령은 `.venv\Scripts\python`(PowerShell) 또는 `.venv/Scripts/python`(Git Bash)로 실행한다.
- 포트: 팔로워 COM5(서보 homing offset·토크 켜짐으로 판별), 리더 COM6. physicalai는 캘리브레이션의 range_min/max(0..4095)만 쓰고 homing_offset은 서보 EEPROM에 남는다.
- 카메라: 0 = 노트북 내장(쓰지 않음), 1 = follow(손목, icspring, 시리얼 20240307110322), 2 = tower(학습 이름 a), 3 = side(b). tower·side는 시리얼(ZVCAI231100001)이 같아 Windows가 둘째에 포트 기반 ID를 줬다. physicalai가 NV12(비압축) 720p30을 골라 카메라 두 대가 같은 USB 경로에 있으면 시간 초과가 난다 → USB 포트를 나눠 꽂는다(허브 없이). pynokhwa의 Windows JSON 역슬래시 버그는 snackbot/wincam.py가 보정한다(663fc7b). 서버를 다시 띄울 때 가끔 "Timed out waiting for first frame"(USB 대역폭) → 다시 꽂거나 포트 분산.
- 정책은 CPU (skills.device: CPU). GPU는 컴파일이 정책마다 55~65초. CPU는 로드 약 6초, 100스텝 청크당 0.14~0.23초. 모션 없는 확인(연결 + warmup 2회)은 9초.
- poses.yaml: home [4.9, -59.7, 51.9, 35.1, 3.4, 49.4](사용자), lift [10.5, 13.0, -10.0, 22.0, 3.4, 50.0](데이터셋 에피소드 1·5의 놓은 직후 값에서 유도, 그리퍼 닫힘). 그리퍼 watch 실측: 빈손 49.4~50.1, 오란다 쥠 54.2~55.4, 열림 79.0 → config 56.0 / 56.5 / 52 / hold 0.15 유지.
- **실기 결과:** 오란다 1회 성공(gripper_open, 쥠 성공, 22.7초, logs/runs/20261023-103209_oranda_pickup). 홈으로 2.2초. 모델 도리도리 1회는 shoulder_pan이 ±1에 머물고 lift·elbow만 까딱거리다 시간 초과 → 사용자 판단: 모델은 도리도리를 못 한다 → 코드 도리도리 1회 버튼 추가(dori_script, 78a23ae, 줄바꿈 CSS db24091, opus 승인·참고 사항 있음).
- **열린 문제:** 제어 루프가 11~13 Hz로 돌았다(녹화 에피소드 fps 11.0 / 13.1, 학습은 30 Hz, 런타임 스텝당 약 77 ms). 의심: 카메라 3대 NV12→RGB, MJPEG 스트림 인코딩, 실행 기록(recorder), 3D 트윈, CPU 경쟁. 아직 조사하지 않았다.
- **개수 세기:** OpenCV counter v2(fb6a85d) = tower cam 검은 매트 ROI + 어두운 링 검사(도착 트레이 제외) + hue ≤ 22 · 면적 ≥ 800(노란 공·버섯 과자 제외) + 붙은 덩어리는 unit_area 1700으로 분리. 실제 프레임에서 오란다 3개, 17 ms. UI에 개수 세기 토글(끔 · OpenCV)과 지금 세기 버튼. VLM은 일단 뺐다(사용자에게 1 epoch VLM이 있어 나중에 추가). dry-run은 가짜 counter. ROI 재조정: `python -m snackbot.vision <사진> --blobs`.
- **거부 규칙(27bdae2):** decision.refuse half(기본) | fixed. total = 첫 개수 세기 성공 값(없으면 채팅 n → initial_count). ceil(total/2)개 옮기면 작업당 한 번 거부(3→2, 4→2, 5→3, 6→3), 달랜 뒤엔 다시 거부하지 않음. UI 게이지 "전체 N · M개째 뒤 거부".
- **리뷰:** fb6a85d + 27bdae2 opus 리뷰 Approved with notes(../.superpowers/sdd/vision-refuse-review.md), 지적 반영 0ea623b. 남은 Minor: 첫 세기가 추정일 때 쥠 판정 경로, YOLO/VLM을 꽂으면 vision 동시 호출 락.
- course_guide.html(저장소 루트)에 06 Physical AI 장, 07 해커톤 프로젝트 장이 추가됐다(a3d8024).
- 이 PC의 8000번 포트는 WSL 가상 머신이 잡고 있을 수 있다 → dry-run 확인은 `--port 8010`. (지금 실제 로봇 서버가 돌고 있을 수 있으니 서버를 멋대로 끄거나 로봇·카메라에 연결하지 않는다.)
- STT = OpenVINO Whisper small 로컬(models/whisper-small, CPU), 예비 Gemini. TTS = Gemini 2.5 flash preview tts(무료 키, 문장당 약 4초, 대사 소리가 나면 동작 시작). 대화 LLM = Claude → NVIDIA → 규칙.
- 비상정지: 콘솔·웹 재시작에 세션 번호 확인, 재시작은 동작이 멈춘 뒤에만, RobotSkills 비상정지 세대 번호, 토크 유지.
- 원격:
  - origin = 강의 저장소. 더 push하지 않는다.
  - homerunball = github.com/ttogle918/intel-openvino-homerunball. 마지막 push e066990. 그 뒤 로컬 커밋(6681a3d 이후)은 아직 push 전이다. push 절차:
      git fetch . feat/robot-m4:main
      S=$(git subtree split --prefix=project main)
      homerunball-export 브랜치를 체크아웃한 임시 worktree(scratchpad)에서 `git merge $S`  (README 때문에 split이 바로 이어지지 않아 매번 merge 필요)
      push는 자동 모드에서 막히므로 사용자가 직접: git push homerunball homerunball-export:main homerunball-export:refs/heads/feat/robot-m4
      그 뒤 worktree 제거.
  - 사진 docs/ACT 학습 모습.jpg 는 올리지 않는다(untracked 유지). calibration/, poses.yaml, bash.exe.stackdump도 untracked다.

## 바로 할 일
1. **제어 루프 주기 조사(1순위):** 11~13 Hz의 원인을 하나씩 껐다 켜며 찾는다. 후보: 카메라 3대 NV12→RGB(ui.tiles로 카메라 칸 줄이기), MJPEG 인코딩, recording.enabled: false, 3D 트윈, CPU 경쟁. 스텝 시간을 재서 비교한다(코드 수정이 필요하면 먼저 제안). 30 Hz에 가까워지면 모델 도리도리를 한 번 더 시험한다.
2. **전체 흐름 실기** (`.venv\Scripts\python -m snackbot`): OpenCV 개수 세기 + half 거부 + 달래기(채팅·🎤·r) + 완료. 3D 영점(twin.sign / offset_deg), 3D 화면이 속도를 늦추는지, 녹화 받기(tools.fetch_replays) 확인.
3. **도리도리 결정:** 모델 대신 코드 도리도리로 갈지 사용자에게 묻는다(skills.dori_dori.source: script 고려. 지금 auto는 모델 폴더가 있으면 모델을 쓴다). 코드 도리도리 폭·속도 조정(amplitude 10 → 15 → 20).
4. 리뷰 I-2(쥠 판정 거짓 실패 약 23%)는 전체 흐름에서 오판 빈도를 본 뒤 후속 코드 수정 여부를 사용자와 정한다.
5. VLM 개수 세기는 나중에(사용자의 1 epoch VLM을 chain에 추가).
6. 사용자가 push한다(위 절차). 시연 전 replays/가 실제 녹화인지 확인.
7. 남은 Minor는 ../.superpowers/sdd/progress.md ("Twin", "ST" 줄)와 st-final-review.md Round 2 참고 (시연에 필수 아님).

## 작업 방식 (지켜줘)
- superpowers:subagent-driven-development 방식: 구현은 sonnet 에이전트, 리뷰는 sonnet(비상정지·동시성은 opus). 스크립트:
  C:/Users/ttogl/.claude/plugins/cache/superpowers-marketplace/superpowers/6.1.1/skills/subagent-driven-development/scripts/{task-brief,review-package}
  공통 지시 파일: ../.superpowers/sdd/implementer-instructions.md, reviewer-instructions.md, m4-global-constraints.md
- 코드를 고치는 에이전트는 한 번에 하나(같은 파일을 안 건드리면 두 개까지). 에이전트에게 git stash/checkout/reset/restore 금지(이전에 stash 사고가 있었다).
- 커밋은 project/ 안 파일만 경로를 지정해서. git add -A 금지(상위 폴더에 우리 것이 아닌 변경: physical-ai-studio 영상 2개 삭제 상태 → 건드리지 않는다).
- API 키(.env: ANTHROPIC/OPENAI/NVIDIA/GEMINI)는 절대 출력·기록하지 않는다. .env는 git 제외.
- openvino-genai는 이 PC에 설치돼 있다(사용자 승인). physicalai 0.3.0은 .venv에 설치돼 있다(사용자 승인). 그 밖의 큰 패키지(ultralytics, torch)는 설치 금지.
- 응답은 한국어로.

## 하드웨어·모델 사실 (확인된 것)
- Studio: http://192.168.0.6:7860 (조회 API만 사용). dori-dori 프로젝트 0d36a88a-0078-47f9-972e-d5dd3e94a262, 환경 24aadb64-3457-411c-8411-48529eada534. oranda 프로젝트 20ca705b-b5a7-435b-9e49-6ae515a68e11, 환경 77201d65-2793-4ae4-b57c-9100c3c40fd0, 데이터셋 last 2fad5952-320a-42e2-b2a1-73e367f64e82 (31 에피소드, 5~18초, 복사본 project/data/last, git 제외).
- oranda_pickup 결과물: traind-model/pickup/exports/openvino (입력 state(6), images.follow/a/b 3×720×1280, action (100,6), resnet18 ACT). config camera_map {a: tower cam, b: side cam, follow: follow cam}. a/b를 바꿔도 정책 출력은 같다.
- dori_dori 결과물: traind-model/dori-dori-model/exports/openvino (입력 images.tower cam·images.follow cam, chunk 100). 실기에서 동작 안 함(위 열린 문제).
- 단위: 몸통 -100..100, 그리퍼 0..100 (작을수록 닫힘, 데이터와 실측으로 확인).
- physicalai 0.3.0: SO101은 본체 physicalai.robot.so101에 있다. RobotRuntime(robot, action_source, fps, cameras, callbacks).run(duration_s, stop_event)은 매 run마다 action_source.connect/disconnect를 부른다. PolicySource(InferenceModel(export_dir, device)), InferenceModel이 모델이 기대하는 입력만 골라 쓴다.

## 남은 결정·확인
- 시연 전 노트북(Windows) 실제 터미널에서 방향키·Home·F키·ESC가 아무 동작도 안 하고 space만 비상정지인지 직접 확인.
- WinError 10014(이 Windows PC 한정, 테스트 동시 실행 때 주로) 원인 조사 여부.
- 무료 Gemini TTS 하루 호출 한도 확인(AI Studio Rate limits 화면). 리허설을 많이 하면 주의.
```

## 지난 기록
- NVIDIA 음성 모델 확인(2026-10-22): OpenAI 호환 API 83개 모델에 STT/TTS가 없고, 음성 NIM은 Riva gRPC가 필요해 채택하지 않았다.
- STT 결정(2026-10-22): OpenVINO Whisper 로컬(small, CPU 1.2~1.8초/문장, GPU 0.43~0.49초)로 구현 완료(`1284e6a`, `e006840`). base는 달래기 키워드를 잃어 탈락.
- 자세한 후보 비교, 측정, 선택 이유는 `docs/VOICE_PROVIDERS.md`로 대체한다.
