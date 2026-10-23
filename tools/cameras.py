"""카메라 찾기: 연결된 UVC 카메라 목록(번호·이름·시리얼)과 카메라마다 사진 1장 (로봇 노트북에서).

python -m tools.cameras [--out cameras] [--width 640 --height 480]

사진(cameras/<번호>.jpg)을 보고 어느 장치가 tower cam / side cam / follow cam 인지 정한 뒤,
출력 끝의 예시를 config.yaml cameras에 붙여 넣는다. 시리얼이 있으면 {serial: "..."}로 지정하는 편이
USB를 다시 꽂아도 번호가 바뀌지 않아 안전하다. physical-ai-studio가 카메라를 잡고 있으면 열리지 않는다.
"""
import argparse
from pathlib import Path

import cv2


def discover():
    from snackbot.wincam import patch_camera_query

    patch_camera_query()   # Windows 카메라 목록 JSON 버그 보정
    from physicalai.capture.cameras.uvc import discover_uvc

    return discover_uvc(only_usable=False)   # 다른 프로그램이 쓰는 장치도 목록에는 보인다


def open_camera(device, width, height):
    from snackbot.wincam import patch_camera_query

    patch_camera_query()
    from physicalai.capture import UVCCamera

    return UVCCamera(device=device, width=width, height=height, fps=30)


def serial_of(info):
    payload = getattr(info, "hardware_payload", None)
    serial = payload.get("serial") if isinstance(payload, dict) else None
    return str(serial) if serial else None


def snapshot(info, out, width, height):
    """장치를 번호로 열어 1장 저장한다. 실패하면 예외."""
    cam = open_camera(info.index, width, height)
    try:
        cam.connect()
        frame = cam.read().data
    finally:
        try:
            cam.disconnect()
        except Exception:
            pass
    path = Path(out) / f"{info.index}.jpg"
    if not cv2.imwrite(str(path), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)):
        raise OSError(f"사진 저장 실패: {path}")
    return path


def duplicate_serials(infos):
    """둘 이상 장치가 같이 쓰는 시리얼(빈 값 포함)의 집합. 이런 장치는 시리얼로 지정할 수 없다."""
    seen, dup = set(), set()
    for info in infos:
        serial = serial_of(info)
        if serial is None:
            continue
        (dup if serial in seen else seen).add(serial)
    return dup


def config_line(info, dup=frozenset()):
    serial = serial_of(info)
    if serial in dup:
        serial = None
    device = f'{{serial: "{serial}"}}' if serial else str(info.index)
    return f"  cam{info.index}: {{device: {device}, width: 1280, height: 720, fps: 30}}"


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m tools.cameras", description="카메라 목록과 사진 1장씩")
    p.add_argument("--out", default="cameras")
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    a = p.parse_args(argv)
    try:
        infos = discover()
    except ImportError as e:
        raise SystemExit(f"physicalai가 없어요 ({e}): 로봇 노트북에서 "
                         "pip install -r requirements.txt -r requirements-robot.txt 뒤에 실행하세요")
    if not infos:
        print("카메라를 찾지 못했어요. USB 연결과 권한(video 그룹)을 확인하세요")
        return
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for info in infos:
        serial = serial_of(info)
        try:
            shot = f"사진 {snapshot(info, out, a.width, a.height)}"
        except Exception as e:
            shot = f"열지 못함 ({type(e).__name__}: {e}) — Studio 등 다른 프로그램이 쓰는 중인지 확인"
        print(f"[{info.index}] {info.name or '(이름 없음)'} · 시리얼 {serial or '없음'} · {shot}")
    dup = duplicate_serials(infos)
    no_serial = [i for i in infos if serial_of(i) is None]
    print()
    if dup or len(no_serial) > 1:
        print("주의: 같은 시리얼(또는 시리얼 없음)인 장치가 있어요 → 그 장치들은 시리얼 대신 번호로 지정하세요 "
              "(USB를 다시 꽂으면 번호가 바뀔 수 있으니 사진으로 다시 확인)")
    print("config.yaml cameras 예시 (camN을 사진을 보고 tower cam / side cam / follow cam 으로 바꾸고, "
          "해상도는 Studio 녹화 때와 같게):")
    for info in infos:
        print(config_line(info, dup))


if __name__ == "__main__":
    main()
