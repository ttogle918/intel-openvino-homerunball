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
    robot = SO101(port=r["port"], calibration=load_calibration(r["calibration"]), role="follower")
    robot.connect()
    robot.set_torque(enabled=False)
    return robot


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
        if a.cmd == "watch":
            print(JOINTS, "(Ctrl+C로 끝)")
            while True:
                print(fmt(robot.get_observation().joint_positions), flush=True)
                time.sleep(0.2)
        else:
            joints = np.mean([robot.get_observation().joint_positions for _ in range(5)], axis=0)
            save_pose(cfg.get("poses_file", "poses.yaml"), f"{a.name}_pose", joints)
            print(f"{a.name}_pose 저장: {fmt(joints)}")
    except KeyboardInterrupt:
        pass
    finally:
        robot.disconnect()


if __name__ == "__main__":
    main()
