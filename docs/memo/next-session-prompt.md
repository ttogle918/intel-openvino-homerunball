# 다음 세션 시작 프롬프트

> 새 Claude Code 세션(작업 폴더 `C:\Users\ttogl\workspace\openvino_course_2610\project`)에 아래 코드 블록을 그대로 붙여넣는다.

```text
과자 옮기기 로봇(snackbot) 해커톤 프로젝트를 이어서 한다. 소프트웨어 전체, 로봇 연결(M4) 코드, 4분할 화면·3D 디지털 트윈·녹화 재생·실행 기록, 스킬 1회 실행 버튼·코드 도리도리·LLM 도리도리가 끝났다(모두 리뷰·병합·push 완료). 다음은 노트북 실기(실제 로봇 연결)다.

## 먼저 읽을 것 (이 순서로)
1. CLAUDE.md
2. ../.superpowers/sdd/progress.md  (저장소 루트 = 상위 폴더 openvino_course_2610/ 기준. 진행 기록·남은 Minor 목록)
3. docs/PROGRESS_REPORT.html  (요약 부분: 전체 진척, 비교표, 다음 할 일)
4. docs/DEMO_RUNBOOK.md  (2-2절: 노트북 로봇 첫 연결 절차)
5. docs/superpowers/specs/2026-10-22-chat-ui-design.md  (11.5~11.6절: Studio·physicalai에서 확인한 사실, M4 구현 결정)
6. docs/VOICE_PROVIDERS.md  (STT·TTS 후보 비교와 선택 이유)
7. docs/memo/2026-10-22-design-discussion.md  (의논 기록)
그다음 `git log --oneline -15`와 `git status`로 상태를 확인하고, 아래 "현재 상태"와 다르면 알려줘.

## 현재 상태 (2026-10-23 기준)
- 2026-10-23: oranda 모델·데이터셋 기반으로 config 반영(포트·카메라·camera_map·replay·그리퍼 값), replays/를 실제 Studio 녹화로 교체, 문서 갱신(런북 2-2~2-4, spec 11.7, 진행 보고서). **노트북 실기는 아직 안 했다** (로봇·카메라는 개발 PC에 연결 안 됨). 이 세션의 커밋은 사용자가 push한다. 리뷰 보고서: ../.superpowers/sdd/field-config-review.md (Approved with notes, I-1 포트·I-2 쥠 판정).
- git 저장소 루트는 project/의 상위 폴더(openvino_course_2610). 브랜치 feat/robot-m4. 로컬 main = feat/robot-m4 (병합은 fast-forward).
- M4 Task 1~6 코드 완료, 리뷰 완료. `python -m snackbot`(실제 로봇)은 코드가 있으나 실기는 아직 안 했다.
- 디지털 트윈 (설계 docs/superpowers/specs/2026-10-22-digital-twin-design.md, 계획 docs/superpowers/plans/2026-10-22-digital-twin.md): 완료(3aa5cef..57b98fd + 최종 리뷰 반영 7f4292c). 브라우저(dry-run)에서 확인.
- 스킬 1회 실행·코드 도리도리·LLM 도리도리 (설계 docs/superpowers/specs/2026-10-22-skill-test-and-scripted-dori-design.md, 계획 docs/superpowers/plans/2026-10-22-skill-test.md): 완료(0c15ece..fe9f77e), opus 최종 리뷰 "병합 가능", 브라우저 확인. 화면 아래 스킬 테스트 줄(오란다 1회/도리도리 1회/홈으로 — 실제 로봇이면 진짜 팔 추론 1회), TESTING 상태, `skills.dori_dori.source: auto|policy|script`(모델 없으면 코드 동작, 진폭 ≤30·한쪽 0.15~3초·횟수 1~10), 대기 중 "도리도리 해 봐" → LLM intent dori_dori → 대사 소리 시작 뒤 1회 실행. 키워드 규칙은 작업 시작 우선(사용자 결정).
- project/replays/ (git 제외)는 이제 실제 Studio 녹화다 (oranda 에피소드 0 6.1초 카메라 3대, dori_dori_4 에피소드 0 10.5초 카메라 2대). 가짜는 삭제하지 않고 치워 뒀다. 노트북에서는 `python -m tools.fetch_replays`로 다시 받는다.
- 테스트 408개: `.venv/Scripts/python -m pytest -q` (WinError 10014는 tests/conftest.py에서 재시도로 우회)
- 이 PC의 8000번 포트는 WSL 가상 머신이 잡고 있을 수 있다 → dry-run 확인은 `--port 8010`.
- STT = OpenVINO Whisper small 로컬. 이 PC에 openvino-genai 2026.4.1이 설치돼 있고 models/whisper-small, models/whisper-base가 있다. 예비 STT는 Gemini(실제 호출 확인).
- TTS = Gemini 2.5 flash preview tts, 결제 없는 프로젝트의 무료 등급 키. 문장당 약 4초. 대사 소리가 나기 시작하면 동작을 시작한다(sync_timeout 10초).
- 대화 LLM = Claude → NVIDIA → 규칙.
- 비상정지: 콘솔·웹 재시작에 세션 번호 확인, 재시작은 동작이 멈춘 뒤에만, RobotSkills 비상정지 세대 번호, 토크 유지(physicalai 소스로 확인).
- 원격:
  - origin = 강의 저장소. 더 push하지 않는다.
  - homerunball = github.com/ttogle918/intel-openvino-homerunball. 마지막 push e066990 (스킬 테스트까지 전부 + 이후). push 절차:
      git fetch . feat/robot-m4:main
      S=$(git subtree split --prefix=project main)
      homerunball-export 브랜치를 체크아웃한 임시 worktree(scratchpad)에서 `git merge $S`  (README 때문에 split이 바로 이어지지 않아 매번 merge 필요)
      push는 자동 모드에서 막히므로 사용자가 직접: git push homerunball homerunball-export:main homerunball-export:refs/heads/feat/robot-m4
      그 뒤 worktree 제거.
  - 사진 docs/ACT 학습 모습.jpg 는 올리지 않는다(untracked 유지).

## 바로 할 일
1. 노트북 실기 확인 (런북 2-2·2-3·2-4절):
   - 포트: `ls -l /dev/serial/by-id/`로 팔로워 경로를 찾아 `robot.port`에 쓴다 (config의 ACM1은 Studio PC 기준 추정. 리더는 빼 두거나 by-id로 구분 — 리더 팔을 팔로워로 열면 토크가 켜진다).
   - 카메라: `tools.cameras`로 번호·사진 확인. tower(a)=0, side(b)=4, follow=시리얼 20240307110322가 Studio PC 기준. tower·side는 시리얼 동일이라 번호로만 지정.
   - 캘리브레이션 받기(dori-dori·oranda 환경이 동일), `robot_probe watch`로 **실제 오란다를 쥐고** 그리퍼 값 확인(쥔 값 < 56.0, 놓을 때 > 56.5, 빈손 닫힘 50). 여유가 0~0.1뿐이라 조정이 필요할 수 있다.
   - 포즈: `robot_probe save home`, `save lift`(**lift는 그리퍼를 닫은 채**), `snackbot.robot home`.
   - `오란다 1회`: 결과 문구(놓기 감지 / 시간 초과, 쥠 성공 / 없음) 기록. timeout(max_time_s 20) 뒤 동작을 눈으로 확인. 도리도리 1회(폭 10부터), "보리야 도리도리 해 봐", 3D 영점(twin.sign/offset_deg), 3D 화면이 ACT 속도를 늦추는지, 녹화 받기(tools.fetch_replays).
   - 결과를 config·코드에 반영.
2. **결정:** 리뷰 I-2 — 정지하지 않은 녹화 8/31 중 7개가 grasped=False라 B단계(success = r.grasped)에서 성공 시도의 약 23%가 실패로 세어질 수 있다. 후속 코드 수정(GripperWatch: closed_seen 뒤 open_above 초과를 한 번이라도 보면 min_closed 고정)을 할지, 실기 오판 빈도를 본 뒤 정할지 사용자에게 묻는다.
3. 전체 흐름 실기(`python -m snackbot`), UI 🎤·음성 확인. 시연 전 replays/ 가 실제 녹화인지 확인.
4. 남은 Minor는 ../.superpowers/sdd/progress.md ("Twin", "ST" 줄)와 st-final-review.md Round 2 참고 (시연에 필수 아님).

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
- 카메라 (Studio oranda 환경 runtime-config, 1280×720@30): oranda 학습 이름 a = 번호 0 (USB 14.0-3, dori의 tower cam과 같은 장치) → config `tower cam`, b = 번호 4 (14.0-4) → `side cam`, follow = 번호 2 (시리얼 20240307110322) → `follow cam`. **a와 b는 시리얼이 같아(zvcai231100001) 번호로만 지정**. config의 skills.oranda_pickup.camera_map `{a: tower cam, b: side cam, follow: follow cam}`. a/b를 바꿔도 정책 출력은 bit 단위로 같다(UI 라벨·A단계 개수 세기만 영향). 런타임은 config의 카메라를 모두 연다.
- 포트: Studio PC 기준 팔로워 /dev/ttyACM1, 리더 /dev/ttyACM0. 노트북에서는 by-id 권장. 캘리브레이션은 dori-dori 환경과 oranda 환경이 동일. 단위: 몸통 -100..100, 그리퍼 0..100 (작을수록 닫힘, 데이터셋으로 확인).
- 그리퍼 값(oranda 데이터셋 31개): 홈·빈손 닫힘 50, 과자 쥠 54~56, 놓음 56~64. config 56.0 / 56.5 / 52 / hold 0.15. GripperWatch 시뮬레이션: 23/31 놓는 순간 정지, 조기 정지 0, 8개는 정지 없이 max_time_s 20.
- dori_dori 결과물: traind-model/dori-dori-model/exports/openvino (act.xml/bin/manifest.json, 입력 images.tower cam·images.follow cam, chunk 100).
- oranda_pickup 결과물: **traind-model/pickup/exports/openvino** (git 제외, 있음). 입력 state(6), images.follow/a/b (3×720×1280, letterbox 384), action (100,6), resnet18 ACT. 개발 PC CPU 140~230 ms/청크. Studio 프로젝트 oranda 20ca705b-b5a7-435b-9e49-6ae515a68e11, 환경 77201d65-2793-4ae4-b57c-9100c3c40fd0, 데이터셋 last 2fad5952-320a-42e2-b2a1-73e367f64e82 (31 에피소드, 5~18초, AV1; 복사본 project/data/last 311MB, git 제외). dori_dori replay 데이터셋은 dori_dori_4 83f518ed-2d84-4807-ae01-5d7cf1904ea6.
- 테스트 408개 통과.
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
