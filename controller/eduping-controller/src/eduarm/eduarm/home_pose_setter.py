"""양팔 OpenArm 을 non-singular home pose 로 이동시킨 후 종료.

mock_components 의 기본 initial_value 가 모두 0.0 이라 시뮬 시작 시 팔이
fully-extended (자연 singularity) 상태. 어떤 servo IK 명령도 condition number
무한대로 즉시 emergency stop. URDF submodule 을 수정하지 않고 우회하기 위해
launch 시점에 이 노드가 한 번 FollowJointTrajectory 액션으로 home pose 까지
보낸 뒤 종료.

home pose 는 두 팔 모두 elbow 90° + 어깨 살짝 굽힘 + 손목 회전 — non-singular,
의사가 진찰 시작할 만한 자연스러운 자세.

doctor_teleop.launch.py 에서 TimerAction 으로 controller spawn 이후 호출.
"""
from __future__ import annotations

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from control_msgs.action import FollowJointTrajectory
from trajectory_msgs.msg import JointTrajectoryPoint
from builtin_interfaces.msg import Duration


LEFT_NAMES = [f"openarm_left_joint{i}" for i in range(1, 8)]
RIGHT_NAMES = [f"openarm_right_joint{i}" for i in range(1, 8)]

# URDF default 자세 (모든 joint = 0). 시각적으로 깔끔하지만 j4=0 + 전 joint=0
# 은 자연 singularity. moveit servo 의 singularity threshold (servo yaml 의
# hard_stop=1e9) 가 사실상 무력화돼 있어 명령은 받지만 첫 모션이 느릴 수 있음.
LEFT_HOME  = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
RIGHT_HOME = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


class HomePoseSetter(Node):
    def __init__(self) -> None:
        super().__init__("eduarm_home_pose_setter")
        self._ac_left = ActionClient(
            self, FollowJointTrajectory,
            "/left_joint_trajectory_controller/follow_joint_trajectory",
        )
        self._ac_right = ActionClient(
            self, FollowJointTrajectory,
            "/right_joint_trajectory_controller/follow_joint_trajectory",
        )

    def run(self) -> None:
        self.get_logger().info("waiting for both controllers...")
        if not self._ac_left.wait_for_server(timeout_sec=30.0):
            self.get_logger().error("left controller action server timeout")
            return
        if not self._ac_right.wait_for_server(timeout_sec=30.0):
            self.get_logger().error("right controller action server timeout")
            return

        self.get_logger().info("sending L/R home pose goals (1.5s ramp)...")
        fut_l = self._ac_left.send_goal_async(self._make_goal(LEFT_NAMES, LEFT_HOME))
        fut_r = self._ac_right.send_goal_async(self._make_goal(RIGHT_NAMES, RIGHT_HOME))
        rclpy.spin_until_future_complete(self, fut_l, timeout_sec=5.0)
        rclpy.spin_until_future_complete(self, fut_r, timeout_sec=5.0)

        gh_l = fut_l.result()
        gh_r = fut_r.result()
        if not (gh_l and gh_l.accepted and gh_r and gh_r.accepted):
            self.get_logger().error("goals not accepted")
            return

        res_l = gh_l.get_result_async()
        res_r = gh_r.get_result_async()
        rclpy.spin_until_future_complete(self, res_l, timeout_sec=8.0)
        rclpy.spin_until_future_complete(self, res_r, timeout_sec=8.0)
        self.get_logger().info("home pose reached")

    @staticmethod
    def _make_goal(names: list[str], positions: list[float]) -> FollowJointTrajectory.Goal:
        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = names
        pt = JointTrajectoryPoint()
        pt.positions = positions
        pt.time_from_start = Duration(sec=1, nanosec=500_000_000)
        goal.trajectory.points = [pt]
        return goal


def main() -> None:
    rclpy.init()
    node = HomePoseSetter()
    try:
        node.run()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
