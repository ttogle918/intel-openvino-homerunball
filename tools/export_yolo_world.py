"""YOLO-World에 텍스트 클래스를 지정해 OpenVINO로 내보낸다 (학습 없음).
03_openvino_workspace/10_project_logistics_counter 패턴. ultralytics가 있는 환경(로봇 노트북)에서 실행.

python -m tools.export_yolo_world --weights weights/yolov8s-worldv2.pt --classes "golden brown puffed rice snack" --out models/oranda_world.pt
"""
import argparse


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m tools.export_yolo_world")
    p.add_argument("--weights", required=True, help="YOLO-World .pt (예: yolov8s-worldv2.pt)")
    p.add_argument("--classes", nargs="+", required=True, help="찾을 물체를 묘사하는 영어 텍스트")
    p.add_argument("--out", default="models/oranda_world.pt")
    a = p.parse_args(argv)

    from ultralytics import YOLO

    model = YOLO(a.weights)
    model.set_classes(a.classes)
    model.save(a.out)
    folder = YOLO(a.out).export(format="openvino", half=True)
    print(f"OpenVINO 모델: {folder}")
    print(f"config.yaml vision.chain에 추가: {{type: yolo, model_dir: \"{folder}\"}}")


if __name__ == "__main__":
    main()
