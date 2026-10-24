# models

내려받은 모델과 OpenVINO 캐시를 두는 곳입니다. git에 올리지 않습니다 (이 README만 올라갑니다).
ACT 모델은 여기가 아니라 `trained_model/`에 넣습니다.

```
models/
├── whisper-small/   # 음성 인식 (OpenVINO Whisper small int8, 약 257MB) — config.yaml stt.chain
└── ov_cache/        # OpenVINO 컴파일 캐시. 처음 실행할 때 자동으로 생기고 지워도 된다
```

받는 방법:

```bash
.venv/Scripts/python -m pip install huggingface_hub
.venv/Scripts/hf download OpenVINO/whisper-small-int8-ov --local-dir models/whisper-small
.venv/Scripts/python -m snackbot.stt a.wav     # 확인 (한국어 녹음 파일)
```

Whisper가 없으면 음성 인식은 Gemini 예비로 넘어가고, 그것도 안 되면 🎤만 안 됩니다 (채팅은 그대로).
