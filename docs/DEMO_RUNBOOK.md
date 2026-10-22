# 시연 런북

## 1. 2일 일정

```mermaid
gantt
    title 오란다 로봇 2일 일정
    dateFormat HH:mm
    axisFormat %H:%M
    section 1일차
    세팅 · 캘리브레이션          :a1, 09:00, 2h
    도리도리 녹화 · 학습 시작      :a2, after a1, 1h
    오란다 녹화 (50~60 에피소드)  :a3, after a2, 3h
    오란다 ACT 학습 (밤사이)      :a4, after a3, 10h
    dry-run 코드 (vision·brain·voice) :a5, 12:00, 7h
    section 2일차
    스킬 단독 테스트              :b1, 09:00, 1h30m
    전체 루프 통합                :b2, after b1, 2h
    리허설 · 영상 촬영            :b3, after b2, 2h
    발표                         :b4, after b3, 1h
```

## 2. 시연 직전 체크리스트
- [ ] 카메라 위치·조명이 녹화 때와 같은지 확인
- [ ] 트레이 위치 테이프 표시에 맞추기
- [ ] 로봇 홈 자세, 토크 상태 확인
- [ ] `python -m snackbot --dry-run` 1회 통과
- [ ] 스피커 볼륨 확인 (TTS)
- [ ] 오란다 3개 + 다른 과자 2개 배치
- [ ] **성공 영상 백업**이 발표 자료에 들어가 있는지 확인
- [ ] 서버는 127.0.0.1에만 띄운다 (인증이 없으므로 0.0.0.0 금지)

## 2-1. 노트북 준비 (처음 한 번, 음성 인식 Whisper 로컬)
- [ ] 새 터미널을 연다. Windows 환경 변수에 예전 `GEMINI_API_KEY`가 남아 있으면 `.env`보다 우선해 400 오류가 나므로, 지운 뒤에 연 터미널에서 실행한다 (열려 있던 터미널은 예전 값을 갖고 있다)
- [ ] `.venv/Scripts/python -m pip install -r requirements.txt` (`openvino-genai==2026.4.1.0` 포함, Windows 다운로드 약 91MB. physicalai의 `openvino>=2026.4.0`과 호환). Ubuntu는 `.venv/bin/python`
- [ ] 모델 받기 (torch·변환 불필요): `.venv/Scripts/python -m pip install huggingface_hub` 후
  `.venv/Scripts/hf download OpenVINO/whisper-small-int8-ov --local-dir models/whisper-small` (257MB, Linux는 `.venv/bin/hf`)
- [ ] 확인: `.venv/Scripts/python -m snackbot.stt a.wav b.wav` (한국어 녹음 파일. 워밍업 후 파일마다 텍스트·source·ms가 나온다)
- [ ] CPU/GPU 선택: 기본은 `config.yaml`의 `stt.chain` 첫 항목 `device: CPU` (small 1.2~1.8초/문장). GPU로 바꾸면 `device`와 `label`("Whisper small · OpenVINO · GPU")을 같이 바꾼다. GPU는 0.4~0.5초지만 첫 로드가 길다(캐시 `models/ov_cache` 후 2~4초)
- [ ] 서버를 켜면 백그라운드에서 워밍업한다 (CPU 약 5.6초). 그 뒤 UI 🎤로 "오란다 세 개 옮겨줘" 확인
- [ ] TTS는 Gemini만 쓴다 (OS TTS 예비는 만들지 않기로 했다). 크레딧을 충전한 뒤 TTS → STT 왕복 검사를 하고, 크레딧이 없으면(402) 소리 없이 진행한다

## 3. 진행자 대본 예시
1. "이 로봇은 과자 공장 직원입니다. 오란다만 골라내요." → 시작
2. 1~3회: 로봇이 옮기면서 점점 투덜댐
3. 4~5회째부터 거부할 수 있고, 6회째에는 반드시 도리도리하며 거부 → 관객 반응
4. 진행자: 채팅이나 🎤로 "조금만 더 해 주세요~" (안 되면 `r` 키 · UI 재개 버튼) → 로봇 재개
5. 마지막 오란다까지 옮기면 완료 멘트

## 4. 장애 대응

| 증상 | 원인 후보 | 대응 |
|---|---|---|
| 엉뚱한 과자를 집음 | 배치가 학습 분포 밖, 조명 변화 | 배치를 녹화 때와 비슷하게, 조명 조정 |
| 집기 계속 실패 | 카메라 이동, 캘리브레이션 틀어짐 | 카메라 테이프 위치 확인, 재시작 |
| 개수가 틀림 (A단계) | 조명, 과자 겹침 | config `vision.chain` 순서 변경 또는 비워서 B단계(시작 개수 + 그리퍼 판정)로 전환 |
| LLM 응답이 느림 | 디바이스 부하 | 더 작은 모델 또는 fallback 대사 모드 |
| 대사가 안 나옴 | 오디오 장치 | 콘솔 대사를 화면에 띄워 대체 |
| 로봇 이상 동작 | — | **space 비상정지** (UI 비상정지 버튼도 같음) → `h` 또는 UI 재시작 (홈 복귀 후 대기) → 채팅으로 다시 시작 |
| 전부 안 됨 | — | 백업 영상 재생 |

## 5. 발표에서 보여줄 숫자 (logs/ 에서 집계)
- 사이클당 단계별 지연: 개수 세기 / LLM / ACT / 복귀 (ms)
- 옮기기 성공률 (성공 / 시도)
- (선택) ACT 추론 PyTorch vs OpenVINO 지연 비교
