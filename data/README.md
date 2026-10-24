# data

physical-ai-studio에서 받은 학습 데이터셋 복사본을 두는 곳입니다. 용량이 커서 git에 올리지 않습니다 (이 README만 올라갑니다).
데이터셋 원본은 Studio의 `oranda` 프로젝트에 있습니다. 실행에는 필요 없고, 학습 데이터를 살펴볼 때만 씁니다.

```
data/
└── last/                              # 오란다 옮기기 데이터셋 (31 에피소드, 5~18초, 약 311MB)
    ├── meta/
    │   ├── info.json                  # fps, 관절 · 카메라 이름, 에피소드 수
    │   ├── stats.json                 # 관절값 · 영상 통계
    │   ├── tasks.parquet
    │   └── episodes/chunk-000/        # 에피소드별 길이 · 위치
    ├── data/chunk-000/file-*.parquet  # 프레임마다 관절값(state)과 리더 팔 동작(action)
    └── videos/
        ├── observation.images.a/      # tower cam (위)
        ├── observation.images.b/      # side cam (옆)
        └── observation.images.follow/ # follow cam (손목)
            └── chunk-000/file-*.mp4   # AV1 영상
```

LeRobot 데이터셋 형식입니다. 카메라 이름 `a`, `b`, `follow`는 학습 때 이름이고, 실행할 때는 `config.yaml`의 `camera_map`으로 연결합니다.
