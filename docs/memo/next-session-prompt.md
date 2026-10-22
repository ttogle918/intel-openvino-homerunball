# 다음 세션 시작 프롬프트

> 새 Claude Code 세션(작업 폴더 `C:\Users\ttogl\workspace\openvino_course_2610\project`)에 아래 코드 블록을 그대로 붙여넣는다.

```text
과자 옮기기 로봇(snackbot) 해커톤 프로젝트를 이어서 한다. 이전 세션에서 소프트웨어 전체(dry-run, FastAPI+UI, LLM/STT/TTS provider)를 끝냈고, 지금은 로봇 연결(M4) 중이다.

## 먼저 읽을 것 (이 순서로)
1. CLAUDE.md
2. .superpowers/sdd/progress.md  (저장소 루트 = 상위 폴더 openvino_course_2610/ 기준. 진행 기록·남은 Minor 목록)
3. docs/superpowers/plans/2026-10-22-snackbot-robot.md  (M4 계획, Task 1은 완료)
4. docs/superpowers/specs/2026-10-22-chat-ui-design.md  (11.5~11.6절: Studio·physicalai에서 확인한 사실)
5. docs/memo/2026-10-22-design-discussion.md  (의논 기록 20개)
그다음 `git log --oneline -15`와 `git status`로 상태를 확인하고, 아래 "현재 상태"와 다르면 알려줘.

## 현재 상태 (2026-10-22 기준)
- git 저장소 루트는 project/의 상위 폴더(openvino_course_2610). 지금 브랜치: feat/robot-m4 (main에서 갈라짐).
- main = 34c886e (소프트웨어 계획 + 최종 리뷰 수정 + Claude Design UI). homerunball 원격 main에도 이 상태가 올라가 있다.
- feat/robot-m4 (main 이후, 아직 main 병합·push 안 함):
  2a95f3c M4 Task 1 로봇·카메라·스킬 설정, 포즈 파일 (리뷰 통과)
  620cdfa 콘솔 키 단순화: ESC가 섞인 입력은 space(비상정지)만 인정, 명령은 워커 하나로 순서대로
  4d6b040 대화 LLM NVIDIA 연결 (추론 모드 끄는 extra_body), Gemini provider
  bd1c9ee 대화는 Claude 우선(claude-opus-5-5, effort low → NVIDIA nemotron → 규칙), OpenAI STT/TTS 엔진
  b2f4c6e 비상정지·종료 때 대기 중인 콘솔 명령 버리기, 나뉘어 들어온 ESC 처리(100ms 창)
  982692d __main__.build()에서 make_voice(cfg, env)로 음성 연결
  b2fc422 대화 기억(최근 12개, 역할 유지), 캐릭터 이름 고정, 재시작 때 기억 초기화
  6db1ac4 STT·TTS를 Gemini로(STT: gemini-3.5-flash-lite 채팅+오디오, TTS: gemini-2.5-flash-preview-tts, voice Leda), 캐릭터 이름 "보리"
  → 리뷰 아직 안 한 커밋: 620cdfa 이후 전부(b2f4c6e는 비상정지 경로라 opus 리뷰), bd1c9ee, b2fc422, 6db1ac4.
- 테스트: `.venv/Scripts/python -m pytest -q` (160개).
- 실제 API 확인 상태: Claude 대화는 동작 확인(1.8~3.6초, 대화 기억 "민수" 테스트 통과). Gemini 음성은 계정 크레딧 소진(402)으로 실제 호출 미확인 — 요청 형식(특히 STT의 input_audio)을 충전 후 검증해야 한다. 검증 스크립트 아이디어: TTS로 "과자 세 개 옮겨줘" 생성 → build_stt(...).transcribe → "옮겨" 포함 확인. OpenAI 키는 401(무효)이라 예비로만 남아 있다.
- 환경 주의: 이 PC의 Windows 환경 변수에 예전(무효) GEMINI_API_KEY가 있으면 load_env가 .env보다 환경 변수를 우선해서 400 API_KEY_INVALID가 난다. 사용자에게 지웠는지 확인할 것. Windows에서 tests/test_server.py가 WinError 10014(루프백 소켓)로 가끔 1~3개 실패 → 다시 돌리면 통과. 서버 시작도 같은 이유로 가끔 실패하니 재시도.
- 원격:
  - origin = github.com/ttogle918/openvino_course_2610 (강의 저장소). 사용자 결정: 여기엔 더 push하지 않는다(이미 올라간 것은 그대로 둠).
  - homerunball = github.com/ttogle918/intel-openvino-homerunball (프로젝트 저장소, main=193ae1d). project/ 폴더만 subtree로 올린다:
      git fetch . <작업브랜치>:main   (fast-forward)
      git subtree split --prefix=project main -b homerunball-export   (기존 브랜치에 이어 붙음)
      git push homerunball homerunball-export:main
    (처음 올릴 때는 README Initial commit과 merge했다. 이후엔 split 브랜치가 이어지므로 그냥 push.)
  - 사진 docs/ACT 학습 모습.jpg 는 올리지 않는다(untracked 유지).

## 바로 할 일 (순서대로)
1. 리뷰 안 된 커밋 리뷰 (보고서: .superpowers/sdd/ 의 keys-fix-report.md, llm-connect-report.md, voice-llm-report.md, memory-report.md, gemini-voice-report.md)
   - b2f4c6e(콘솔 키 대기열·ESC 창)는 opus 리뷰. 알려진 점: ESC 창은 None 청크로만 열리고, 걸러진 청크 뒤 100ms 안의 일반 키는 버려진다.
   - 리뷰에서 나온 Critical/Important는 고치고 전체 테스트.
2. 사용자가 Gemini 크레딧을 충전했으면 실제 왕복 검사(TTS → STT) 하고, 안 되면 요청 형식 수정. UI에서 🎤와 음성 재생 확인.
   dry-run 서버: `.venv/Scripts/python -m snackbot --dry-run --host 127.0.0.1 --port 8000` → http://127.0.0.1:8000 (마이크는 localhost에서만 권한이 난다).
3. M4 Task 2~6 실행 (docs/superpowers/plans/2026-10-22-snackbot-robot.md)
   - Task 2 motion.py(그리퍼 감시·보간 이동·Switch(camera_map)·Tap), Task 3 robot.py(RobotSkills), Task 4 tools(fetch_calibration, robot_probe), Task 5 __main__ 실제 로봇 경로(connect는 try 안, 로봇 모드에서 fake counter 제외), Task 6 문서.
   - 주의: 계획을 쓴 뒤 __main__.py가 많이 바뀌었다(콘솔 키 워커, h 키 등). Task 5는 현재 코드에 맞춰 적용.
4. M4 끝나면 feat/robot-m4를 main에 병합하고 homerunball에 subtree push (강의 저장소 origin에는 push하지 않는다).
5. (사용자 요청 이력) 챗봇 기능 추가 후보: 긴 대화 요약, 서버 쪽 입력 길이 제한, 스트리밍은 보류. 캐릭터 이름 "보리", 대상 과자 "오란다".

## 작업 방식 (지켜줘)
- superpowers:subagent-driven-development 방식: 구현은 sonnet 에이전트, 리뷰는 sonnet(비상정지·동시성은 opus). 스크립트: 
  C:/Users/ttogl/.claude/plugins/cache/superpowers-marketplace/superpowers/6.1.1/skills/subagent-driven-development/scripts/{task-brief,review-package}
  공통 지시 파일: .superpowers/sdd/implementer-instructions.md, reviewer-instructions.md, m4-global-constraints.md
- 코드를 고치는 에이전트는 한 번에 하나(같은 파일을 안 건드리면 두 개까지). 에이전트에게 git stash/checkout/reset/restore 금지(이전에 stash 사고가 있었다).
- 커밋은 project/ 안 파일만 경로를 지정해서. git add -A 금지(상위 폴더에 우리 것이 아닌 변경: physical-ai-studio 영상 2개 삭제 상태 → 건드리지 않는다).
- API 키(.env: ANTHROPIC/OPENAI/NVIDIA/GEMINI)는 절대 출력·기록하지 않는다. .env는 git 제외.
- 큰 패키지(openvino-genai, ultralytics, torch, physicalai) 설치 금지(이 PC는 개발용 Windows). physicalai 소스는 필요하면 `pip download --no-deps physicalai==0.3.0 physicalai-so101-plugin`으로 받아 읽기만.
- 응답은 한국어로.

## 하드웨어·모델 사실 (확인된 것)
- Studio: http://192.168.0.6:7860 (조회 API만 사용). dori-dori 프로젝트 0d36a88a-0078-47f9-972e-d5dd3e94a262, 환경 24aadb64-3457-411c-8411-48529eada534.
- 카메라: tower cam(UVC 0), follow cam(UVC 2), 1280×720@30, 그리고 oranda용으로 사이드 캠 추가(Studio 이름 미정, 현재 A/B 같은 이름일 수 있음 → config의 skills.oranda_pickup.camera_map으로 학습 이름을 config 카메라 이름에 매핑).
- 팔로워 포트는 Studio 학습 PC 기준 /dev/ttyACM1(노트북에서 다시 확인). 단위: 몸통 -100..100, 그리퍼 0..100(작을수록 닫힘 가정 → robot_probe로 확인).
- dori_dori 결과물: traind-model/dori-dori-model/exports/openvino (act.xml/bin/manifest.json, 입력 images.tower cam·images.follow cam, chunk 100). oranda_pickup은 학습 중, 같은 형태로 나온다(exports/openvino).
- physicalai 0.3.0: RobotRuntime(robot, action_source, fps, cameras, callbacks).run(duration_s, stop_event), PolicySource(InferenceModel(export_dir, device)), InferenceModel이 모델이 기대하는 입력만 골라 쓴다(남는 카메라 무시).

## 남은 결정·확인
- stash@{0}(15:15 git 사고 백업)과 scratchpad/rescue 백업을 지워도 되는지 사용자에게 물어볼 것.
- 시연 전 Ubuntu 노트북에서 실제 터미널로 방향키·Home·F키·ESC가 아무 동작도 안 하고 space만 비상정지인지 직접 확인.
- WinError 10014 원인(이 Windows PC 한정) 조사 여부.
```
