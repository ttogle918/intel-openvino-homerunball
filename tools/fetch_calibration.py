"""Studio 환경의 runtime-config에서 팔로워 캘리브레이션을 받아 저장한다 (조회만 한다).
녹화·학습 때와 같은 캘리브레이션을 써야 관절 단위가 맞는다.

python -m tools.fetch_calibration --studio http://192.168.0.6:7860 --project <프로젝트 id> --env <환경 id>
"""
import argparse
from pathlib import Path

import httpx
import yaml


def find_follower(node):
    """class_path가 SO101로 끝나고 role이 follower인 노드의 init_args (SharedRobot 안에 있어도)."""
    if isinstance(node, dict):
        args = node.get("init_args")
        if str(node.get("class_path", "")).endswith("SO101") and isinstance(args, dict) \
                and args.get("role") == "follower":
            return args
        children = node.values()
    elif isinstance(node, list):
        children = node
    else:
        return None
    for child in children:
        found = find_follower(child)
        if found is not None:
            return found
    return None


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m tools.fetch_calibration")
    p.add_argument("--studio", required=True, help="예: http://192.168.0.6:7860")
    p.add_argument("--project", required=True)
    p.add_argument("--env", required=True)
    p.add_argument("--out", default="calibration/follower.yaml")
    a = p.parse_args(argv)

    url = f"{a.studio.rstrip('/')}/api/projects/{a.project}/environments/{a.env}/runtime-config"
    try:
        r = httpx.get(url, timeout=10)
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise SystemExit(f"Studio가 {e.response.status_code}로 답했어요. --project, --env id를 확인하세요 ({url})")
    except httpx.HTTPError as e:
        raise SystemExit(f"Studio에 연결하지 못했어요: {a.studio} ({type(e).__name__}). 주소·포트·같은 네트워크인지 확인하세요")
    doc = yaml.safe_load(r.text)
    follower = find_follower(doc)
    if follower is None:
        raise SystemExit("runtime-config에서 follower SO101을 찾지 못했어요")
    cal = follower.get("calibration")
    if not isinstance(cal, dict):
        raise SystemExit(f"follower calibration이 관절 표(dict)가 아니라 {type(cal).__name__}예요 "
                         "(Studio PC의 파일 경로일 수 있어요). Studio PC의 캘리브레이션 파일을 복사해 "
                         "calibration/follower.yaml(또는 JSON)로 두세요")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(cal, sort_keys=False), encoding="utf-8")
    print(f"캘리브레이션 저장: {out}")
    print(f"Studio 기준 팔로워 포트: {follower.get('port')} (노트북 포트는 config.yaml robot.port에 직접 쓴다)")
    for name, cam in ((doc.get("init_args") or {}).get("cameras") or {}).items():
        device = cam.get("init_args", {}).get("camera", {}).get("init_args", {}).get("device", {})
        print(f"카메라 {name!r}: index {device.get('index') if isinstance(device, dict) else device}")


if __name__ == "__main__":
    main()
