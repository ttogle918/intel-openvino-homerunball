# 다음 세션 시작 프롬프트

> 새 Claude Code 세션(작업 폴더 `C:\Users\ttogl\workspace\openvino_course_2610\project`)에 아래 코드 블록을 그대로 붙여넣는다.

```text
과자 옮기기 로봇(snackbot) 해커톤 프로젝트를 이어서 한다. 소프트웨어 전체(dry-run, FastAPI+UI, LLM/STT/TTS provider)와 로봇 연결(M4) 코드 6개 Task가 끝났고, 지금은 노트북 실기 확인 단계다.

## 먼저 읽을 것 (이 순서로)
1. CLAUDE.md
2. ../.superpowers/sdd/progress.md  (저장소 루트 = 상위 폴더 openvino_course_2610/ 기준. 진행 기록·남은 Minor 목록)
3. docs/PROGRESS_REPORT.html  (요약 부분: 전체 진척, 비교표, 다음 할 일)
4. docs/DEMO_RUNBOOK.md  (2-2절: 노트북 로봇 첫 연결 절차)
5. docs/superpowers/specs/2026-10-22-chat-ui-design.md  (11.5~11.6절: Studio·physicalai에서 확인한 사실, M4 구현 결정)
6. docs/VOICE_PROVIDERS.md  (STT·TTS 후보 비교와 선택 이유)
7. docs/memo/2026-10-22-design-discussion.md  (의논 기록)
그다음 `git log --oneline -15`와 `git status`로 상태를 확인하고, 아래 "현재 상태"와 다르면 알려줘.

## 현재 상태 (2026-10-22 기준)
- git 저장소 루트는 project/의 상위 폴더(openvino_course_2610). 브랜치 feat/robot-m4. 로컬 main = feat/robot-m4 (병합은 fast-forward).
- M4 Task 1~6 코드 완료, 리뷰 완료. `python -m snackbot`(실제 로봇)은 코드가 있으나 실기는 아직 안 했다.
- 테스트 275개: `.venv/Scripts/python -m pytest -q`
- STT = OpenVINO Whisper small 로컬. 이 PC에 openvino-genai 2026.4.1이 설치돼 있고 models/whisper-small, models/whisper-base가 있다. 예비 STT는 Gemini(실제 호출 확인).
- TTS = Gemini 2.5 flash preview tts, 결제 없는 프로젝트의 무료 등급 키. 문장당 약 4초. 대사 소리가 나기 시작하면 동작을 시작한다(sync_timeout 10초).
- 대화 LLM = Claude → NVIDIA → 규칙.
- 비상정지: 콘솔·웹 재시작에 세션 번호 확인, 재시작은 동작이 멈춘 뒤에만, RobotSkills 비상정지 세대 번호, 토크 유지(physicalai 소스로 확인).
- 원격:
  - origin = 강의 저장소. 더 push하지 않는다.
  - homerunball = github.com/ttogle918/intel-openvino-homerunball. 1회 push 완료(2afa38e). push 절차(바뀜):
      git fetch . feat/robot-m4:main
      S=$(git subtree split --prefix=project main)
      homerunball-export 브랜치를 체크아웃한 임시 worktree(scratchpad)에서 `git merge $S`  (README 때문에 split이 바로 이어지지 않아 매번 merge 필요)
      push는 자동 모드에서 막히므로 사용자가 직접: git push homerunball homerunball-export:main homerunball-export:refs/heads/feat/robot-m4
      그 뒤 worktree 제거.
  - 사진 docs/ACT 학습 모습.jpg 는 올리지 않는다(untracked 유지).

## 바로 할 일
1. 노트북 실기 확인 결과 반영 (런북 2-2절): 포트, 카메라 번호, 그리퍼 방향·기준값, 포즈(home/lift) 저장, home 이동, dori_dori.
2. 과자 모델(oranda_pickup)이 나오면 manifest의 images 이름 → skills.oranda_pickup.camera_map, grasp_min 확정, oranda_pickup 실기.
3. 전체 흐름 실기(`python -m snackbot`), UI 🎤·음성 재생 확인.
4. (사용자 결정 대기) 로봇이 안 될 때 대비책: 3D 디지털 트윈 패널 — three.js + urdf-loader + TheRobotStudio SO-ARM100 저장소 Simulation/SO101/so101_new_calib.urdf (Apache-2.0), 녹화 궤적 재생. 시작하기 전에 사용자에게 먼저 물어본다.
5. 다음 homerunball push 준비(위 절차, push는 사용자가 실행).

## 작업 방식 (지켜줘)
- superpowers:subagent-driven-development 방식: 구현은 sonnet 에이전트, 리뷰는 sonnet(비상정지·동시성은 opus). 스크립트:
  C:/Users/ttogl/.claude/plugins/cache/superpowers-marketplace/superpowers/6.1.1/skills/subagent-driven-development/scripts/{task-brief,review-package}
  공통 지시 파일: ../.superpowers/sdd/implementer-instructions.md, reviewer-instructions.md, m4-global-constraints.md
- 코드를 고치는 에이전트는 한 번에 하나(같은 파일을 안 건드리면 두 개까지). 에이전트에게 git stash/checkout/reset/restore 금지(이전에 stash 사고가 있었다).
- 커밋은 project/ 안 파일만 경로를 지정해서. git add -A 금지(상위 폴더에 우리 것이 아닌 변경: physical-ai-studio 영상 2개 삭제 상태 → 건드리지 않는다).
- API 키(.env: ANTHROPIC/OPENAI/NVIDIA/GEMINI)는 절대 출력·기록하지 않는다. .env는 git 제외.
- openvino-genai는 이 PC에 설치돼 있다(사용자 승인). 그 밖의 큰 패키지(ultralytics, torch, physicalai) 설치 금지. physicalai 소스는 scratchpad에 받아 읽기만(설치 금지).
- 응답은 한국어로.

## 하드웨어·모델 사실 (확인된 것)
- Studio: http://192.168.0.6:7860 (조회 API만 사용). dori-dori 프로젝트 0d36a88a-0078-47f9-972e-d5dd3e94a262, 환경 24aadb64-3457-411c-8411-48529eada534.
- 카메라: tower cam(UVC 0), follow cam(UVC 2), 1280×720@30, 그리고 oranda용으로 사이드 캠 추가(Studio 이름 미정, 현재 A/B 같은 이름일 수 있음 → config의 skills.oranda_pickup.camera_map으로 학습 이름을 config 카메라 이름에 매핑). 런타임은 config의 카메라를 모두 연다(사이드 캠이 없으면 config에서 주석 처리).
- 팔로워 포트는 Studio 학습 PC 기준 /dev/ttyACM1(노트북에서 다시 확인). 단위: 몸통 -100..100, 그리퍼 0..100(작을수록 닫힘 가정 → robot_probe로 확인).
- dori_dori 결과물: traind-model/dori-dori-model/exports/openvino (act.xml/bin/manifest.json, 입력 images.tower cam·images.follow cam, chunk 100). oranda_pickup은 학습 중, 같은 형태로 나온다(exports/openvino).
- physicalai 0.3.0: SO101은 본체 physicalai.robot.so101에 있다(플러그인 불필요). RobotRuntime(robot, action_source, fps, cameras, callbacks).run(duration_s, stop_event)은 매 run마다 action_source.connect/disconnect를 부른다. PolicySource(InferenceModel(export_dir, device)), InferenceModel이 모델이 기대하는 입력만 골라 쓴다(남는 카메라 무시).

## 남은 결정·확인
- 시연 전 Ubuntu 노트북 실제 터미널에서 방향키·Home·F키·ESC가 아무 동작도 안 하고 space만 비상정지인지 직접 확인.
- WinError 10014(이 Windows PC 한정, 테스트 동시 실행 때 주로) 원인 조사 여부.
- 무료 Gemini TTS 하루 호출 한도 확인(AI Studio Rate limits 화면). 리허설을 많이 하면 주의.
```

## 지난 기록
- NVIDIA 음성 모델 확인(2026-10-22): OpenAI 호환 API 83개 모델에 STT/TTS가 없고, 음성 NIM은 Riva gRPC가 필요해 채택하지 않았다.
- STT 결정(2026-10-22): OpenVINO Whisper 로컬(small, CPU 1.2~1.8초/문장, GPU 0.43~0.49초)로 구현 완료(`1284e6a`, `e006840`). base는 달래기 키워드를 잃어 탈락.
- 자세한 후보 비교, 측정, 선택 이유는 `docs/VOICE_PROVIDERS.md`로 대체한다.
