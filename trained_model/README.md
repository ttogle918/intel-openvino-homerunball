# trained_model

physical-ai-studio에서 학습한 ACT 모델을 넣는 곳입니다. 용량이 커서 모델 파일은 git에 올리지 않습니다 (이 README만 올라갑니다).

```
trained_model/
├── oranda_pickup/            # 오란다 집어서 옮기기
│   └── exports/openvino/     # act.xml, act.bin, manifest.json
└── dori_dori/                # 고개 젓기 (도리도리)
    └── exports/openvino/
```

## 넣는 방법

1. physical-ai-studio에서 학습이 끝난 모델을 OpenVINO 형식으로 내보냅니다.
2. 내보낸 폴더를 통째로 받아 위 구조대로 `trained_model/<스킬 이름>/`에 넣습니다. `exports/openvino/` 안에 `act.xml`, `act.bin`, `manifest.json` 세 파일이 있으면 됩니다. `model.ckpt`, `exports/onnx`, `exports/torch`는 실행에 쓰지 않으니 있어도 되고 없어도 됩니다.
3. 경로는 `config.yaml`의 `skills.<스킬 이름>.export_dir`에 적혀 있습니다. 다른 곳에 두려면 이 값을 바꿉니다.
4. 모델의 카메라 이름이 `config.yaml`의 `cameras`와 다르면 `skills.<스킬 이름>.camera_map`으로 맞춥니다. 모델이 기대하는 이름은 `manifest.json`의 `images.<이름>`에서 볼 수 있습니다.
   - `oranda_pickup`: `images.a`, `images.b`, `images.follow` → `camera_map: {a: tower cam, b: side cam, follow: follow cam}`
   - `dori_dori`: `images.tower cam`, `images.follow cam` (config 이름과 같아서 그대로)
5. 확인: `.venv/Scripts/python -m snackbot.robot oranda_pickup` (도리도리 모델은 `dori_policy`. `dori_dori`는 `source` 설정을 따르므로 지금은 코드 동작). 시작할 때 정책을 한 번 미리 돌려 보므로 카메라 이름이 틀리면 바로 알려 줍니다.

모델 폴더가 없는 동작은 건너뛰고 경고만 냅니다. 도리도리는 모델이 없어도 코드 동작(`skills.dori_dori.source: script`)으로 할 수 있습니다.
