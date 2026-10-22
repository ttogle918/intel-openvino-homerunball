"""config.yaml과 .env 로드."""
import os
from pathlib import Path

import yaml


def load_config(path="config.yaml"):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_env(path=".env"):
    """.env를 읽어 os.environ과 합친다. 이미 설정된 환경 변수가 우선한다."""
    env = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    env.update(os.environ)
    return env
