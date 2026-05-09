"""OMX OX 퀴즈 trajectory 시뮬레이션 재생.

실물 로봇(`/dev/omx_follower`) 없이 ROS2 토픽 publish 만으로 OMX 동작을 검증한다.
- 기본: `/joint_states` 로 publish — RViz + URDF 만 띄워도 시각화 가능.
- `--use-controller`: `joint_trajectory_controller` (ros2_control / Gazebo) 로 한 번에 보냄.

사용:
    # O 정답 trajectory
    python play_sim.py --answer O
    # X 정답 trajectory
    python play_sim.py --answer X
    # 임의 파일
    python play_sim.py --file /path/to/episode_X.json

Gazebo / RViz 띄우는 법은 `device/noriarm_ws/src/open_manipulator/` 의 launch 파일
(예: open_manipulator_bringup) 참고. 별도 ROS2 환경 source 필요:
    source /opt/ros/jazzy/setup.bash
    source device/noriarm_ws/install/setup.bash   # build 후

trajectory JSON 포맷 (lerobot 녹화 결과):
    {
      "hz": 30,
      "num_frames": 547,
      "trajectory": [[shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper], ...]
    }
joint 값은 도(degree) 단위. ROS2 는 라디안이므로 변환한다.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

# trajectory JSON 의 6개 컬럼은 위치 기반(positional) 으로 들어 있으므로, 이름만
# target 에 맞게 바꿔서 publish 하면 같은 데이터를 다른 URDF 에 그대로 적용할 수 있다.
#   lerobot — 녹화 원본 이름. lerobot 도구로 다시 먹일 때 사용.
#   omx     — open_manipulator_description 의 OMX-F URDF joint 이름. RViz/Gazebo 시각화용.
JOINT_NAME_PRESETS: dict[str, list[str]] = {
    "lerobot": [
        "shoulder_pan",
        "shoulder_lift",
        "elbow_flex",
        "wrist_flex",
        "wrist_roll",
        "gripper",
    ],
    "omx": [
        "joint1",
        "joint2",
        "joint3",
        "joint4",
        "joint5",
        "gripper_joint_1",
    ],
    # Gazebo / ros2_control 의 arm_controller 는 5개 arm joint 만 소유한다 (gripper 는
    # gripper_controller 로 분리). --use-controller 와 함께 쓰는 preset.
    "omx_arm": [
        "joint1",
        "joint2",
        "joint3",
        "joint4",
        "joint5",
    ],
}

# answer → 기본 trajectory 파일 매핑.
DEFAULT_FILES = {
    "O": "episode_0_trajectory.json",
    "X": "episode_1_trajectory.json",
}


def deg_to_rad(values: list[float]) -> list[float]:
    return [v * math.pi / 180.0 for v in values]


class TrajectoryPlayer(Node):
    def __init__(self, joint_names: list[str], use_controller: bool, controller_topic: str):
        super().__init__("ox_quiz_trajectory_player")
        self.joint_names = joint_names
        self.use_controller = use_controller
        if use_controller:
            self.pub_traj = self.create_publisher(JointTrajectory, controller_topic, 10)
            self.get_logger().info(f"publish target: {controller_topic} (JointTrajectory)")
        else:
            self.pub_state = self.create_publisher(JointState, "/joint_states", 10)
            self.get_logger().info("publish target: /joint_states (RViz visualization)")

    def play(self, frames_deg: list[list[float]], hz: float) -> None:
        if self.use_controller:
            self._play_controller(frames_deg, hz)
        else:
            self._play_joint_states(frames_deg, hz)

    def _play_joint_states(self, frames_deg: list[list[float]], hz: float) -> None:
        period = 1.0 / hz
        total = len(frames_deg)
        for i, frame in enumerate(frames_deg):
            msg = JointState()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.name = self.joint_names
            msg.position = deg_to_rad(frame)
            self.pub_state.publish(msg)
            if i % 30 == 0:
                self.get_logger().info(f"frame {i}/{total} ({i / total * 100:.0f}%)")
            time.sleep(period)
        self.get_logger().info("done")

    def _play_controller(self, frames_deg: list[list[float]], hz: float) -> None:
        traj = JointTrajectory()
        traj.joint_names = self.joint_names
        period = 1.0 / hz
        for i, frame in enumerate(frames_deg):
            point = JointTrajectoryPoint()
            point.positions = deg_to_rad(frame)
            t = (i + 1) * period
            sec = int(t)
            point.time_from_start.sec = sec
            point.time_from_start.nanosec = int((t - sec) * 1e9)
            traj.points.append(point)

        # 컨트롤러 subscriber 와 매칭될 때까지 대기 — 매칭 전에 publish 하면 메시지가 버려짐.
        deadline = time.monotonic() + 5.0
        while self.pub_traj.get_subscription_count() == 0 and time.monotonic() < deadline:
            time.sleep(0.1)
        if self.pub_traj.get_subscription_count() == 0:
            self.get_logger().warn(
                "controller subscriber 가 보이지 않음 — 토픽 이름과 컨트롤러 활성 상태 확인"
            )

        self.pub_traj.publish(traj)
        self.get_logger().info(f"published JointTrajectory: {len(traj.points)} points")
        # publish 직후 destroy 되지 않도록 trajectory 길이만큼 살아 있다가 종료.
        time.sleep(len(traj.points) * period + 0.5)


def resolve_trajectory_path(args: argparse.Namespace) -> Path:
    if args.file:
        return Path(args.file).expanduser().resolve()
    here = Path(__file__).resolve().parent
    name = DEFAULT_FILES[args.answer]
    return here / name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--answer", choices=["O", "X"], help="OX 퀴즈 정답 — 기본 파일 매핑")
    grp.add_argument("--file", help="trajectory JSON 파일 경로 (수동)")
    parser.add_argument(
        "--use-controller",
        action="store_true",
        help="ros2_control joint_trajectory_controller 로 한 번에 publish",
    )
    parser.add_argument(
        "--controller-topic",
        default="/arm_controller/joint_trajectory",
        help="--use-controller 일 때 publish 토픽",
    )
    parser.add_argument(
        "--target",
        choices=list(JOINT_NAME_PRESETS),
        default="omx",
        help="publish 할 joint 이름 preset (기본: omx — RViz/Gazebo 의 OMX-F URDF)",
    )
    parser.add_argument(
        "--joint-names",
        nargs="+",
        default=None,
        help="joint 이름을 직접 지정 (지정 시 --target 무시)",
    )
    args = parser.parse_args()
    joint_names = args.joint_names or JOINT_NAME_PRESETS[args.target]
    if args.use_controller and not args.joint_names and args.target == "omx":
        # Gazebo 기본 컨트롤러는 arm 5축만 받으므로 자동 전환.
        joint_names = JOINT_NAME_PRESETS["omx_arm"]
        print("note: --use-controller 감지 → omx_arm preset 으로 전환 (arm 5축만 publish)")

    path = resolve_trajectory_path(args)
    if not path.exists():
        raise SystemExit(f"trajectory file not found: {path}")
    print(f"loading: {path}")
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    trajectory = data["trajectory"]
    hz = float(data.get("hz", 30))
    print(f"frames={len(trajectory)} hz={hz}")

    width = len(joint_names)
    if trajectory and len(trajectory[0]) > width:
        # joint 수가 frame 컬럼보다 적으면 앞쪽 컬럼만 사용 (omx_arm 같은 부분 publish).
        trajectory = [frame[:width] for frame in trajectory]
        print(f"sliced trajectory to {width} columns ({joint_names})")
    elif trajectory and len(trajectory[0]) < width:
        raise SystemExit(
            f"frame width {len(trajectory[0])} < joint count {width}: "
            f"--joint-names 또는 --target 을 확인하세요"
        )

    rclpy.init()
    try:
        node = TrajectoryPlayer(
            joint_names=joint_names,
            use_controller=args.use_controller,
            controller_topic=args.controller_topic,
        )
        try:
            node.play(trajectory, hz)
        finally:
            node.destroy_node()
    finally:
        rclpy.shutdown()


if __name__ == "__main__":
    main()
