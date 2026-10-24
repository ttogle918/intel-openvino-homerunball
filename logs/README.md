# logs

실행하면 자동으로 쌓이는 기록입니다. git에 올리지 않습니다 (이 README만 올라갑니다).

```
logs/
├── cycles-YYYYMMDD.jsonl           # 사이클마다 한 줄: 결과(success/fail/refuse/done), 판정 방법, 개수, 단계별 시간(ms)
│                                   #   스킬 테스트는 "type": "test", 지금 세기는 "type": "count"
└── runs/
    └── YYYYMMDD-HHMMSS_<스킬>/     # 실제 로봇 실행 기록 (config.yaml recording)
        ├── episode.json            # 정책이 움직인 동안의 관절값
        └── frames/<카메라>/        # 카메라 프레임 (10fps)
```

- 발표에 쓴 숫자(성공률, 단계별 시간)는 `cycles-*.jsonl`에서 뽑습니다.
- 잘 된 실행은 `replays/`로 복사해 dry-run 재생에 쓸 수 있습니다.
- 실행 기록을 끄려면 `config.yaml`에서 `recording.enabled: false`.
