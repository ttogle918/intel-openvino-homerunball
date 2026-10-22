"""팔로워 관절값 읽기 (현장 점검용). 토크를 끄므로 손으로 팔을 움직일 수 있다 — 팔이 처지니 손으로 받친다.
끝나면 disconnect()가 지금 자세를 목표로 잡고 토크를 켠다.

python -m tools.robot_probe watch          # 5Hz로 관절값 출력. 그리퍼: 열림 / 빈손 닫힘 / 오란다 쥠 값을 적는다
python -m tools.robot_probe save home      # 지금 자세를 poses.yaml의 home_pose로
python -m tools.robot_probe save lift      # 놓은 뒤 위로 든 자세를 lift_pose로
"""
import argparse
import time

import numpy as np

from snackbot.config import load_calibration, load_config, save_pose

JOINTS = "shoulder_pan shoulder_lift elbow_flex wrist_flex wrist_roll gripper"


def open_robot(cfg):
    from snackbot.robot import load_so101

    SO101 = load_so101()
    r = cfg["robot"]
    try:
        calibration = load_calibration(r["calibration"])
    except FileNotFoundError:
        raise SystemExit(f"캘리브레이션 파일이 없어요: {r['calibration']}\n"
                         "먼저 python -m tools.fetch_calibration --studio URL --project ID --env ID 로 받아 오세요")
    robot = SO101(port=r["port"], calibration=calibration, role="follower")
    try:
        robot.connect()  # 실패하면 SO101이 스스로 포트를 닫는다
    except Exception as e:
        raise SystemExit(f"포트를 열지 못했어요: {r['port']} ({type(e).__name__}: {e})\n"
                         "Linux는 ls /dev/ttyACM* 로 포트 이름을 확인하고, "
                         "physical-ai-studio 세션이 열려 있으면 닫으세요 (포트는 한 프로그램만 잡을 수 있어요)")
    return robot


def _spaced(n, gap=0.05):
    """n번 돌려주되 사이마다 gap초 쉰다 (값 평균용)."""
    for i in range(n):
        if i:
            time.sleep(gap)
        yield i


def fmt(joints):
    return " ".join(f"{v:7.1f}" for v in joints)


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m tools.robot_probe")
    p.add_argument("cmd", choices=["watch", "save"])
    p.add_argument("name", nargs="?", choices=["home", "lift"])
    p.add_argument("--config", default="config.yaml")
    a = p.parse_args(argv)
    if a.cmd == "save" and a.name is None:
        p.error("save에는 home 또는 lift가 필요해요")
    cfg = load_config(a.config)
    robot = open_robot(cfg)
    try:
        robot.set_torque(enabled=False)
        if a.cmd == "watch":
            print(JOINTS, "(Ctrl+C로 끝)")
            while True:
                print(fmt(robot.get_observation().joint_positions), flush=True)
                time.sleep(0.2)
        else:
            joints = np.mean([robot.get_observation().joint_positions for _ in _spaced(5)], axis=0)
            save_pose(cfg.get("poses_file", "poses.yaml"), f"{a.name}_pose", joints)
            print(f"{a.name}_pose 저장: {fmt(joints)}")
    except KeyboardInterrupt:
        pass
    finally:
        robot.disconnect()


if __name__ == "__main__":
    main()
