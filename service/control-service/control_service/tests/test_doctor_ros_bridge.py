"""doctor.ros_bridge unit tests.

rclpy 가 시스템에 설치돼 있는 CI/로컬에서만 동작.
"""
from __future__ import annotations
import time
import pytest

rclpy = pytest.importorskip("rclpy")

from control_service.doctor.ros_bridge import DoctorRosBridge
from control_service.streaming.teleop_protocol import (
    TargetFrame, ArmTarget, SERVO_STATUS_OK, SERVO_STATUS_SLOWED,
)


@pytest.fixture(scope="function")
def bridge():
    b = DoctorRosBridge(left_joints=[f"l{i+1}" for i in range(7)],
                        right_joints=[f"r{i+1}" for i in range(7)])
    b.start()
    yield b
    b.shutdown()


def test_publish_target_pose(bridge) -> None:
    from geometry_msgs.msg import PoseStamped
    received = []
    node = rclpy.create_node("test_listener_pose")
    node.create_subscription(
        PoseStamped, "/doctor_teleop/left/target_pose",
        lambda m: received.append(m), 10,
    )
    deadline = time.time() + 2.0
    bridge.publish_target(TargetFrame(
        ts_ms=0,
        left=ArmTarget(0.3, 0.1, 0.4, 0, 0, 0, 1, 0.5),
        right=None,
    ))
    while time.time() < deadline and not received:
        rclpy.spin_once(node, timeout_sec=0.05)
    node.destroy_node()
    assert received, "PoseStamped never received"
    assert received[0].pose.position.x == pytest.approx(0.3, abs=1e-3)


def test_publish_gripper(bridge) -> None:
    from std_msgs.msg import Float32
    received = []
    node = rclpy.create_node("test_listener_grip")
    node.create_subscription(
        Float32, "/doctor_teleop/left/gripper_cmd",
        lambda m: received.append(m), 10,
    )
    deadline = time.time() + 2.0
    bridge.publish_target(TargetFrame(
        ts_ms=0,
        left=ArmTarget(0.0, 0.0, 0.0, 0, 0, 0, 1, 0.75),
        right=None,
    ))
    while time.time() < deadline and not received:
        rclpy.spin_once(node, timeout_sec=0.05)
    node.destroy_node()
    assert received[0].data == pytest.approx(0.75, abs=1e-2)


def test_joint_state_to_frame(bridge) -> None:
    from sensor_msgs.msg import JointState
    pub_node = rclpy.create_node("test_pub_joints")
    pub = pub_node.create_publisher(JointState, "/joint_states", 10)
    msg = JointState()
    msg.name = [f"l{i+1}" for i in range(7)] + [f"r{i+1}" for i in range(7)]
    msg.position = [0.1]*7 + [0.2]*7
    deadline = time.time() + 2.0
    while time.time() < deadline:
        pub.publish(msg)
        rclpy.spin_once(pub_node, timeout_sec=0.05)
        frame = bridge.latest_state()
        if frame and abs(frame.left.joints[0] - 0.1) < 1e-3:
            break
    pub_node.destroy_node()
    frame = bridge.latest_state()
    assert frame is not None
    assert frame.left.joints[0] == pytest.approx(0.1, abs=1e-3)
    assert frame.right.joints[0] == pytest.approx(0.2, abs=1e-3)
