# replays

dry-run(`python -m snackbot --dry-run`)에서 옮기기 · 도리도리 차례에 녹화 동작을 다시 재생할 데이터입니다. git에 올리지 않습니다 (이 README만 올라갑니다).
없어도 dry-run은 돕니다. 그때는 동작 시간을 `dry_run.act_s`(1초)로 대신하고, 3D 팔과 카메라 칸은 움직이지 않습니다.

```
replays/
├── oranda_pickup/
│   ├── episode.json     # 관절값 시계열 (3D 팔 재생, 동작 길이)
│   ├── tower_cam.mp4    # 카메라 칸에 보여 줄 영상 (config 카메라 이름)
│   ├── side_cam.mp4
│   └── follow_cam.mp4
└── dori_dori/
    ├── episode.json
    ├── tower_cam.mp4
    └── follow_cam.mp4
```

채우는 방법은 두 가지입니다.

1. Studio 녹화에서 받기 (Studio와 같은 네트워크에서만, 조회만 함):
   ```bash
   .venv/Scripts/python -m tools.fetch_replays --studio http://192.168.0.6:7860 --skill oranda_pickup
   ```
   받을 에피소드는 `config.yaml`의 `skills.<스킬>.replay`에 있습니다.
2. 실제 로봇 실행 기록 복사: 잘 된 실행 하나를 그대로 옮깁니다.
   ```bash
   cp -r logs/runs/<시각>_oranda_pickup replays/oranda_pickup
   ```
