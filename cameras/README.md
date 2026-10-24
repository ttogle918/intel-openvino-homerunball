# cameras

`python -m tools.cameras`가 찍는 카메라 확인 사진이 저장되는 곳입니다. git에 올리지 않습니다 (이 README만 올라갑니다).

```
cameras/
└── <번호>.jpg    # 장치 번호마다 사진 한 장 (0 = 노트북 내장 카메라일 때가 많다)
```

사진을 보고 어느 번호가 tower · side · follow인지 정해 `config.yaml`의 `cameras.<이름>.device`에 적습니다. USB를 바꿔 꽂으면 번호가 바뀔 수 있으니 다시 확인합니다.
