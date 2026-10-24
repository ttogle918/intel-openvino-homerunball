# 다음 세션 시작 프롬프트

> **2026-10-23(금) 시연·발표가 끝났고, 2026-10-25에 저장소를 정리했다.** 이어서 할 작업은 없다. 아래는 마지막 작업 세션 기준 기록이다. 그 뒤 정리에서 YOLO·VLM counter, OpenAI·pyttsx3 음성, openrouter·ollama 설정을 지웠고 README.md를 만들었다. 시연 결과(집기 12번 중 1번 성공)와 남은 한계는 README.md에 있다.

> 새 Claude Code 세션(작업 폴더 `C:\Users\ttogl\workspace\openvino_course_2610\project`)에 아래 코드 블록을 그대로 붙여넣는다.

```text
과자 옮기기 로봇(snackbot) 해커톤 프로젝트를 이어서 한다. 소프트웨어 전체, 로봇 연결(M4), 4분할 화면·3D 트윈·녹화 재생·실행 기록, 스킬 1회 실행(오란다·모델 도리도리·코드 도리도리·홈), OpenCV 개수 세기(중앙값·확인 재세기·정정), half 거부, 두 번 놓치면 투덜+도리도리, Windows Heami 예비 TTS, 발표 자료 11장이 끝났다. 2026-10-23~24에 시연 노트북(이 Windows PC)에서 실기와 전체 워크플로우 브라우저 확인을 마쳤다. 다음은 제어 루프 주기 조사와 집기 정확도(추가 학습)다.

## 먼저 읽을 것 (이 순서로)
1. CLAUDE.md
2. ../.superpowers/sdd/progress.md  (저장소 루트 = 상위 폴더 openvino_course_2610/ 기준. 진행 기록 끝부분)
3. docs/PROGRESS_REPORT.html  (맨 위 "이번 갱신(2026-10-25)" 박스, 비교표, 다음 할 일)
4. docs/DEMO_RUNBOOK.md  (2-2 로봇 첫 연결, 2-3 4분할·3D·기록, 2-4 스킬 1회·코드 도리도리, 2-5 개수 세기)
5. docs/DECISION_LOGIC.md  (half 거부 규칙)
6. docs/superpowers/specs/2026-10-22-chat-ui-design.md  (11.5~11.7절)
7. ../.superpowers/sdd/field-config-review.md, dori-script-review.md  (리뷰 기록)
그다음 `git log --oneline -15`와 `git status`로 상태를 확인하고, 아래 "현재 상태"와 다르면 알려줘.

## 현재 상태 (2026-10-25 기준)
- 최신 커밋은 문서 갱신(이 메모 포함). 그 앞 1995537 (두 번 연속 놓치면 투덜대고 도리도리 → 진행자 확인 대기, 대기 중 채팅 "이어서 해줘"로 재개). 브랜치 feat/robot-m4 (git 저장소 루트는 project/의 상위 폴더 openvino_course_2610). 자동 테스트 499개: `.venv/Scripts/python -m pytest -q`.
- **시연 노트북 = 이 Windows 11 PC (192.168.0.17).** physicalai 0.3.0을 project/.venv에 설치했다(사용자 승인). 실제 로봇 명령은 `.venv\Scripts\python`(PowerShell) 또는 `.venv/Scripts/python`(Git Bash). 서버: `.venv\Scripts\python -m snackbot --port 8010` (8000은 WSL이 잡고 있을 수 있다). 사용자가 서버를 직접 켜고 끈다 → 멋대로 끄거나 로봇·카메라에 연결하지 않는다.
- 포트: 팔로워 COM5, 리더 COM6. physicalai는 캘리브레이션의 range_min/max(0..4095)만 쓰고 homing_offset은 서보 EEPROM에 남는다.
- 카메라: 0 = 노트북 내장(쓰지 않음), 1 = follow(손목), 2 = tower(학습 이름 a), 3 = side(b). tower·side 시리얼이 같다(ZVCAI231100001). NV12 720p30이라 USB 포트를 나눠 꽂는다. pynokhwa JSON 버그는 snackbot/wincam.py가 보정. 서버 재시작 때 가끔 "Timed out waiting for first frame" → 다시 켜면 된다.
- 정책은 CPU (skills.device: CPU, 로드 약 6초). GPU는 컴파일이 정책마다 55~65초.
- poses.yaml·calibration/follower.yaml은 커밋돼 있다(174f381, 머리말에 Windows 명령은 살아 있고 Ubuntu 명령은 주석). home [4.9, -59.7, 51.9, 35.1, 3.4, 49.4], lift [10.5, 13.0, -10.0, 22.0, 3.4, 50.0]. 그리퍼 56.0 / 56.5 / 52 / hold 0.15.
- **개수 세기 (OpenCV, tower cam):** ROI [0.289, 0.208, 0.617, 0.847] + 어두운 링 검사 + 오란다 색 화소(H 5~21, S≥80) + min_area 600 + unit_area 1700. 한 번 셀 때 5프레임 중앙값(frame_gap 0.1초). 성공 = 개수 감소, 그리퍼가 놓았는데 그대로면 0.7초 뒤 다시 세어 확인(vision_confirm). 앞 세기가 연속 두 번 더 많이 보면 정정(c4d3c04), 남은 0인데 카메라가 보면 작업당 한 번 되살림. LLM에는 moved/this_item을 준다. VLM은 나중(사용자의 1 epoch VLM).
- **거부(half):** refuse_at = ceil(refuse_total/2), refuse_total = 맨 처음 센 개수(되살림해도 안 바뀜, 첫 정정만 바꿈). 작업당 한 번, 달래면 끝까지.
- **연속 실패(1995537):** decision.max_retry: 1. 두 번 연속 놓치면 give_up 대사(채팅+TTS) → 소리 시작 뒤 도리도리 1회(source: script라 코드) → phase waiting_operator + 안내. 대기 중 채팅 intent는 resume·chat, 키워드 "이어서·계속·재개" 추가. 횟수·피로도·refused에 안 넣는다. 재개·재시작 버튼이 납작하던 CSS도 고쳤다. **실제 팔로는 아직 확인 안 함.**
- **도리도리:** skills.dori_dori.source: script (코드 도리도리가 기본). 모델 도리도리 1회 버튼은 source와 무관하게 모델로 1회. 모델은 데이터가 적어 과적합(100 epoch, train 0.07 / val 0.49).
- **음성:** STT = OpenVINO Whisper small 로컬(CPU), 예비 Gemini. TTS = Gemini 2.5 flash preview tts → 실패하면 Windows Microsoft Heami(voice.fallback: windows, 한도 오류 뒤 600초·기타 오류 뒤 60초 Gemini 건너뜀). 대화 LLM = Claude → NVIDIA → 규칙. 주의: Claude Code 셸 환경에 예전 GEMINI_API_KEY가 남아 있으면 .env보다 우선한다 → 서버를 띄울 때 `env -u GEMINI_API_KEY`. .env 키는 유효하지만 하루 한도를 넘기면 429(그때는 Heami).
- **전체 워크플로우 확인(2026-10-23, 실제 로봇):** 테스트 버튼 4개, 채팅, STT(/stt), TTS(Heami로 넘어감), 웹캠 3대 확인. 기록: logs/workflow_check/ (webcams.mp4, webcams_oranda.gif, snackbot_workflow_check.gif, screens/ 14장, git 제외).
- **발표 자료:** docs/slides.html, docs/slides.pptx (11장, 7장 데이터셋과 학습: docs/img/act_training.jpg, loss_pickup.png, loss_dori.png). pptx는 scratchpad의 pptxgenjs 스크립트로 만들었다(세션이 바뀌면 사라짐 → 고칠 때는 pptx를 직접 편집하거나 다시 생성).
- **학습 사실:** pickup 5 epoch, batch 8, 31 에피소드 9,111 프레임, train 0.35 / val 0.66(아직 내려가는 중 = 덜 학습). dori 100 epoch, batch 4, 약 1천 프레임.
- **열린 문제:** 제어 루프 11~13 Hz(학습 30 Hz). MJPEG 화면을 추가로 열면 4.2 Hz까지 떨어진다 → 서버 JPEG 인코딩 부하가 유력. 집기 정확도(pickup 덜 학습).
- 비상정지: 콘솔·웹 재시작에 세션 번호 확인, 재시작은 동작이 멈춘 뒤에만, RobotSkills 비상정지 세대 번호, 토크 유지.
- 원격:
  - origin = 강의 저장소. 더 push하지 않는다.
  - homerunball = github.com/ttogle918/intel-openvino-homerunball. 마지막 push e6f3b0d(c4d3c04까지). 그 뒤 4b6c063, c5fb788, 1995537, 문서 갱신은 아직 push 전이다. push 절차:
      git fetch . feat/robot-m4:main
      S=$(git subtree split --prefix=project main)
      homerunball-export 브랜치를 체크아웃한 임시 worktree(scratchpad)에서 `git merge $S`  (README 때문에 split이 바로 이어지지 않아 매번 merge 필요)
      push는 자동 모드에서 막히므로 사용자가 직접: git push homerunball homerunball-export:main homerunball-export:refs/heads/feat/robot-m4
      그 뒤 worktree 제거.
  - 사진 docs/ACT 학습 모습.jpg, docs/img/ 의 스크린샷·doridori-*.png 원본은 올리지 않는다(untracked 유지, 발표에는 줄인 docs/img/act_training.jpg만). bash.exe.stackdump도 untracked.

## 바로 할 일
1. **두 번 놓침 흐름 실기:** 서버를 다시 켜고 일부러 두 번 놓치게 해서 투덜 대사 → 코드 도리도리 → "이어서 해줘"로 재개되는지 본다.
2. **제어 루프 주기 조사:** MJPEG 인코딩(화면 수·해상도·품질·인코딩 주기), 카메라 NV12→RGB, recording.enabled: false, 3D 트윈을 하나씩 껐다 켜며 스텝 시간을 잰다(코드 수정이 필요하면 먼저 제안).
3. **집기 정확도:** pickup을 더 학습(epoch 늘리기)하도록 사용자에게 권한다. 도리도리 모델은 데이터를 더 녹화해야 쓸 수 있다(지금은 코드 도리도리).
4. VLM 개수 세기는 학습하지 못해 하지 않기로 했다 (OpenCV로 마무리).
5. 사용자가 push한다(위 절차). 시연 전 replays/가 실제 녹화인지 확인.
6. 남은 Minor는 ../.superpowers/sdd/progress.md와 리뷰 기록 참고 (시연에 필수 아님).

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
- dori_dori 결과물: traind-model/dori-dori-model/exports/openvino (입력 images.tower cam·images.follow cam, chunk 100). 실기에서 shoulder_pan이 거의 안 움직임(데이터 부족) → 시연은 코드 도리도리.
- 단위: 몸통 -100..100, 그리퍼 0..100 (작을수록 닫힘, 데이터와 실측으로 확인).
- physicalai 0.3.0: SO101은 본체 physicalai.robot.so101에 있다. RobotRuntime(robot, action_source, fps, cameras, callbacks).run(duration_s, stop_event)은 매 run마다 action_source.connect/disconnect를 부른다. PolicySource(InferenceModel(export_dir, device)), InferenceModel이 모델이 기대하는 입력만 골라 쓴다.

## 남은 결정·확인
- 시연 전 노트북(Windows) 실제 터미널에서 방향키·Home·F키·ESC가 아무 동작도 안 하고 space만 비상정지인지 직접 확인.
- WinError 10014(이 Windows PC 한정, 테스트 동시 실행 때 주로) 원인 조사 여부.
- 무료 Gemini TTS 하루 호출 한도 확인(AI Studio Rate limits 화면). 넘기면 Heami가 대신 말한다.
```

## 지난 기록
- NVIDIA 음성 모델 확인(2026-10-22): OpenAI 호환 API 83개 모델에 STT/TTS가 없고, 음성 NIM은 Riva gRPC가 필요해 채택하지 않았다.
- STT 결정(2026-10-22): OpenVINO Whisper 로컬(small, CPU 1.2~1.8초/문장, GPU 0.43~0.49초)로 구현 완료(`1284e6a`, `e006840`). base는 달래기 키워드를 잃어 탈락.
- 자세한 후보 비교, 측정, 선택 이유는 `docs/VOICE_PROVIDERS.md`로 대체한다.
