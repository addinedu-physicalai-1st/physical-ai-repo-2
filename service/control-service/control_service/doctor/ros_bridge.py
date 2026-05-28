"""ROS 2 bridge for doctor teleop.

Publish:
  /doctor_teleop/left/target_pose   (geometry_msgs/PoseStamped)
  /doctor_teleop/right/target_pose
  /doctor_teleop/left/gripper_cmd   (std_msgs/Float32)
  /doctor_teleop/right/gripper_cmd

Subscribe:
  /joint_states                     (sensor_msgs/JointState) — 좌+우 관절 합쳐서
  /servo_node/left/status           (std_msgs/Int8, MoveIt Servo status code)
  /servo_node/right/status

스레딩: rclpy spin 은 daemon thread. publish 메서드는 thread-safe (lock).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from control_service.streaming.teleop_protocol import (
    ArmState, ArmTarget, StateFrame, TargetFrame,
    SERVO_STATUS_OK, SERVO_STATUS_SLOWED, SERVO_STATUS_STOPPED, SERVO_STATUS_ERROR,
)

log = logging.getLogger(__name__)


def _servo_code_to_status(code: int) -> int:
    """MoveIt Servo StatusCode → 우리 servo_status 매핑.

    moveit_servo StatusCode 정의 (humble+):
      INVALID=-1, NO_WARNING=0, DECELERATE_FOR_LEAVING_SINGULARITY=1,
      DECELERATE_FOR_SINGULARITY=2, HALT_FOR_SINGULARITY=3,
      DECELERATE_FOR_COLLISION=4, HALT_FOR_COLLISION=5,
      JOINT_BOUND=6.
    """
    if code in (0,):
        return SERVO_STATUS_OK
    if code in (1, 2, 4):
        return SERVO_STATUS_SLOWED
    if code in (3, 5, 6):
        return SERVO_STATUS_STOPPED
    return SERVO_STATUS_ERROR


class DoctorRosBridge:
    def __init__(self, left_joints: list[str], right_joints: list[str]) -> None:
        self._left_joints = list(left_joints)
        self._right_joints = list(right_joints)
        self._lock = threading.Lock()
        self._latest_left = ArmState(joints=[0.0]*7, gripper=0.0, servo_status=SERVO_STATUS_OK)
        self._latest_right = ArmState(joints=[0.0]*7, gripper=0.0, servo_status=SERVO_STATUS_OK)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._node = None
        self._pubs: dict[str, object] = {}
        self._latest_fsr_raw: int | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._spin, name="DoctorRosBridge", daemon=True)
        self._thread.start()
        # 노드 준비될 때까지 잠깐 대기
        for _ in range(50):
            if self._node is not None:
                break
            time.sleep(0.02)
        if self._node is None:
            log.warning("DoctorRosBridge node not ready after 1s — publish calls will silently no-op until node initializes")

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _spin(self) -> None:
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.node import Node
        from geometry_msgs.msg import PoseStamped
        from sensor_msgs.msg import JointState
        from std_msgs.msg import Float32, Int8, Int32

        if not rclpy.ok():
            rclpy.init()
        node = Node("doctor_ros_bridge")
        self._node = node

        self._pubs["left_pose"] = node.create_publisher(PoseStamped, "/doctor_teleop/left/target_pose", 10)
        self._pubs["right_pose"] = node.create_publisher(PoseStamped, "/doctor_teleop/right/target_pose", 10)
        self._pubs["left_grip"] = node.create_publisher(Float32, "/doctor_teleop/left/gripper_cmd", 10)
        self._pubs["right_grip"] = node.create_publisher(Float32, "/doctor_teleop/right/gripper_cmd", 10)

        def on_joint_states(msg: JointState) -> None:
            name_idx = {n: i for i, n in enumerate(msg.name)}
            l_grip_key = "openarm_left_finger_joint1"
            r_grip_key = "openarm_right_finger_joint1"
            l_grip = (
                msg.position[name_idx[l_grip_key]]
                if l_grip_key in name_idx
                else self._latest_left.gripper
            )
            r_grip = (
                msg.position[name_idx[r_grip_key]]
                if r_grip_key in name_idx
                else self._latest_right.gripper
            )
            with self._lock:
                self._latest_left = ArmState(
                    joints=[msg.position[name_idx[j]] if j in name_idx else 0.0 for j in self._left_joints],
                    gripper=l_grip,
                    servo_status=self._latest_left.servo_status,
                )
                self._latest_right = ArmState(
                    joints=[msg.position[name_idx[j]] if j in name_idx else 0.0 for j in self._right_joints],
                    gripper=r_grip,
                    servo_status=self._latest_right.servo_status,
                )

        node.create_subscription(JointState, "/joint_states", on_joint_states, 10)

        def make_status_cb(side: str):
            def cb(msg: Int8) -> None:
                with self._lock:
                    if side == "left":
                        self._latest_left = ArmState(
                            joints=self._latest_left.joints,
                            gripper=self._latest_left.gripper,
                            servo_status=_servo_code_to_status(msg.data),
                        )
                    else:
                        self._latest_right = ArmState(
                            joints=self._latest_right.joints,
                            gripper=self._latest_right.gripper,
                            servo_status=_servo_code_to_status(msg.data),
                        )
            return cb

        node.create_subscription(Int8, "/servo_node/left/status", make_status_cb("left"), 10)
        node.create_subscription(Int8, "/servo_node/right/status", make_status_cb("right"), 10)

        def on_fsr_raw(msg: "Int32") -> None:
            with self._lock:
                self._latest_fsr_raw = int(msg.data)

        node.create_subscription(Int32, "/eduping/stethoscope/fsr_raw", on_fsr_raw, 10)

        # D435 영상/포인트클라우드는 eduarm 의 uploader 노드가 WebSocket 으로 직접
        # 푸시. control-service 는 이제 ROS image/pointcloud sub 하지 않음.

        # leader_passthrough 의 active gate 제어 — UI 의 "Start Telehealth" 버튼 핸들러.
        from std_srvs.srv import SetBool
        self._leader_active_client = node.create_client(
            SetBool, "/leader_passthrough/set_active",
        )

        ex = SingleThreadedExecutor()
        ex.add_node(node)

        # Switch both servo nodes to POSE command mode (command_type=2).
        # Import here (like other ROS imports) so the module loads without ROS installed.
        from moveit_msgs.srv import ServoCommandType  # noqa: PLC0415

        left_switch = node.create_client(
            ServoCommandType, "/servo_node_left/switch_command_type"
        )
        right_switch = node.create_client(
            ServoCommandType, "/servo_node_right/switch_command_type"
        )

        def _switch_to_pose(client, side: str) -> None:
            """Run in a daemon thread — must not touch ex (not thread-safe).

            ROS launch 가 control-service 보다 늦게 떠도 따라잡도록 끈질기게 재시도.
            성공 후엔 30초 간격으로 재호출 — servo 가 어떤 이유로든 mode 를 잃으면
            (e.g., re-init, pause 후 unpause) 자동 복구.
            """
            req = ServoCommandType.Request()
            req.command_type = ServoCommandType.Request.POSE  # 2
            switched_once = False
            while not self._stop.is_set():
                if not client.wait_for_service(timeout_sec=2.0):
                    if not switched_once:
                        log.debug("servo switch %s — waiting for service...", side)
                    continue
                fut = client.call_async(req)
                deadline = time.time() + 2.0
                while not fut.done() and time.time() < deadline:
                    time.sleep(0.05)
                ok = fut.done() and fut.result() and fut.result().success
                if ok:
                    if not switched_once:
                        log.info("servo %s switched to POSE mode", side)
                        switched_once = True
                else:
                    log.warning(
                        "servo %s switch_command_type call failed/timed out", side
                    )
                # 처음 성공 후엔 30s 간격으로 재확인. 실패 시엔 2s 후 재시도.
                self._stop.wait(timeout=30.0 if switched_once else 2.0)

        for _side, _client in (("left", left_switch), ("right", right_switch)):
            threading.Thread(
                target=_switch_to_pose,
                args=(_client, _side),
                name=f"servo_switch_{_side}",
                daemon=True,
            ).start()

        try:
            while not self._stop.is_set():
                ex.spin_once(timeout_sec=0.05)
        finally:
            node.destroy_node()

    def publish_target(self, frame: TargetFrame) -> None:
        from geometry_msgs.msg import PoseStamped
        from std_msgs.msg import Float32

        def _look_at_quat(target_x: float, target_y: float, target_z: float
                          ) -> tuple[float, float, float, float]:
            """target → base 의 look-at orientation (xyzw quaternion).

            wrist 가 항상 robot body 에서 바깥쪽 (target 위치) 을 향하도록 자동 계산.
            의사/leader 가 보낸 quat 는 무시 — 7DoF arm 의 redundancy 가 자연스러운
            손목 자세를 만들도록 함. base 는 world 원점 (openarm_body_link0 가 거의
            동일 위치) 기준.
            """
            import math
            fx, fy, fz = target_x, target_y, target_z  # forward = base → target
            n = math.sqrt(fx * fx + fy * fy + fz * fz)
            if n < 1e-6:
                return 0.0, 0.0, 0.0, 1.0
            fx, fy, fz = fx / n, fy / n, fz / n
            # right = forward × world_up. world_up = (0,0,1).
            rx, ry, rz = fy, -fx, 0.0
            rn = math.sqrt(rx * rx + ry * ry + rz * rz)
            if rn < 1e-6:
                # forward 가 world_up 과 평행 — fallback 으로 x 축 사용.
                rx, ry, rz = 1.0, 0.0, 0.0
            else:
                rx, ry, rz = rx / rn, ry / rn, rz / rn
            # up = right × forward (정규화)
            ux = ry * fz - rz * fy
            uy = rz * fx - rx * fz
            uz = rx * fy - ry * fx
            # 회전 행렬 → quaternion. 컬럼: [right, up, forward].
            m00, m01, m02 = rx, ux, fx
            m10, m11, m12 = ry, uy, fy
            m20, m21, m22 = rz, uz, fz
            tr = m00 + m11 + m22
            if tr > 0:
                s = math.sqrt(tr + 1.0) * 2
                qw = 0.25 * s
                qx = (m21 - m12) / s
                qy = (m02 - m20) / s
                qz = (m10 - m01) / s
            elif m00 > m11 and m00 > m22:
                s = math.sqrt(1.0 + m00 - m11 - m22) * 2
                qw = (m21 - m12) / s
                qx = 0.25 * s
                qy = (m01 + m10) / s
                qz = (m02 + m20) / s
            elif m11 > m22:
                s = math.sqrt(1.0 + m11 - m00 - m22) * 2
                qw = (m02 - m20) / s
                qx = (m01 + m10) / s
                qy = 0.25 * s
                qz = (m12 + m21) / s
            else:
                s = math.sqrt(1.0 + m22 - m00 - m11) * 2
                qw = (m10 - m01) / s
                qx = (m02 + m20) / s
                qy = (m12 + m21) / s
                qz = 0.25 * s
            return qx, qy, qz, qw

        def _pose_stamped(a: ArmTarget) -> "PoseStamped":
            p = PoseStamped()
            # URDF root = "world" (그 아래 openarm_body_link0).
            p.header.frame_id = "world"
            if self._node:
                p.header.stamp = self._node.get_clock().now().to_msg()
            p.pose.position.x = float(a.x)
            p.pose.position.y = float(a.y)
            p.pose.position.z = float(a.z)
            # 의사/leader 가 보낸 quat 무시 — base → target 방향 look-at 으로 덮어씀.
            # 손목이 항상 robot 바깥쪽을 향해 자연스러운 자세 유지.
            qx, qy, qz, qw = _look_at_quat(a.x, a.y, a.z)
            p.pose.orientation.x = qx
            p.pose.orientation.y = qy
            p.pose.orientation.z = qz
            p.pose.orientation.w = qw
            return p

        with self._lock:
            if frame.left and "left_pose" in self._pubs:
                self._pubs["left_pose"].publish(_pose_stamped(frame.left))
                f = Float32()
                f.data = float(frame.left.gripper)
                self._pubs["left_grip"].publish(f)
            if frame.right and "right_pose" in self._pubs:
                self._pubs["right_pose"].publish(_pose_stamped(frame.right))
                f = Float32()
                f.data = float(frame.right.gripper)
                self._pubs["right_grip"].publish(f)

    def latest_state(self) -> StateFrame:
        with self._lock:
            return StateFrame(
                ts_ms=int(time.time() * 1000) & 0xFFFFFFFF,
                left=self._latest_left,
                right=self._latest_right,
            )

    def latest_fsr_raw(self) -> int | None:
        with self._lock:
            return self._latest_fsr_raw

    def set_leader_active(self, active: bool) -> bool:
        """leader_passthrough_node 의 ~/set_active 호출.

        UI 의 "Start/Stop Telehealth" 버튼 → bridge on_event → 이 메서드.
        active=True 면 leader → JTC 흐름 시작, False 면 정지 (마지막 위치 hold).
        Returns True if service call accepted (response.success), False otherwise.
        """
        from std_srvs.srv import SetBool
        client = getattr(self, "_leader_active_client", None)
        if client is None or not client.service_is_ready():
            log.warning("leader_passthrough/set_active not ready (node 안 떠 있음)")
            return False
        req = SetBool.Request()
        req.data = bool(active)
        fut = client.call_async(req)
        # daemon thread 에서 호출 — executor 가 따로 spin 하므로 sleep poll.
        deadline = time.time() + 1.0
        while not fut.done() and time.time() < deadline:
            time.sleep(0.01)
        if fut.done() and fut.result() and fut.result().success:
            return True
        log.warning("set_leader_active(%s) timed out / failed", active)
        return False
