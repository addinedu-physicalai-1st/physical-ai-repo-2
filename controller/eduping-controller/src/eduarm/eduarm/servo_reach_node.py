"""servo_reach_node — Cartesian P-controller → TwistStamped → moveit_servo.

Phase 4. 상위 호출자 (highfive_node 등) 가 PointStamped 로 목표 위치를 publish 하면
이 노드가 매 tick (50Hz) 현재 end-effector pose 를 TF 로 읽어 목표까지의 거리 벡터를
clamp 된 P 제어 twist 로 변환해 servo_node 로 흘려보낸다. servo_node 가 octomap +
self-collision 검사로 안전을 책임지므로 본 노드는 단순 P 제어만 한다.

동작 흐름:
  /eduping/servo_reach/target_point  ──► (TF transform to planning_frame)
                                     ──► 매 tick 50Hz:
                                             err = target − ee_pose
                                             dist = ||err||
                                             if dist < proximity_stop_m  →  zero twist + IDLE
                                             else                          →  publish
                                                  TwistStamped {linear = clamp(gain·err)}
                                          /servo_node/delta_twist_cmds

도착·중지 조건:
  · ||err|| < proximity_stop_m (default 0.02m) → zero twist, target 클리어
  · target_timeout_s (default 30.0s) 동안 새 target 없으면 abort
  · 노드 종료 시 zero twist 1회 publish (servo 가 holding 으로 전환)

ROS 파라미터:
  arm                   ('left'|'right', default 'left')
  target_topic          (default '/eduping/servo_reach/target_point')
  twist_topic           (default '/servo_node/delta_twist_cmds')
  planning_frame        (default 'world')
  publish_hz            (default 50.0)
  gain                  (1/s, default 1.5)         twist = gain · err
  max_linear_speed      (m/s, default 0.10)
  proximity_stop_m      (m, default 0.02)
  target_timeout_s      (s, default 30.0)
  start_servo_on_init   (bool, default True)       /servo_node/start_servo 호출

검증 (sim, octomap_demo_sim.launch.py 띄운 상태):
  T1) ros2 run eduarm servo_reach_node
  T2) ros2 topic pub --once /eduping/servo_reach/target_point geometry_msgs/msg/PointStamped \\
        "{header: {frame_id: world}, point: {x: 0.30, y: 0.20, z: 0.55}}"
  T3) three.js OpenarmViewer 의 왼팔 EE 가 target 으로 부드럽게 수렴
  T4) 도달 직전 D435 시야에 손을 가져다 대면 octomap 채움 → servo_node 가 halt →
      EE 가 obstacle 바로 앞에서 정지 (Phase 3 collision gate 동작)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import rclpy
from geometry_msgs.msg import PointStamped, TwistStamped
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformException, TransformListener
# tf2_geometry_msgs 는 import side-effect 로 PointStamped 의 do_transform 등록.
import tf2_geometry_msgs  # noqa: F401


@dataclass
class _ActiveTarget:
    x: float
    y: float
    z: float
    received_at: float          # ROS time (seconds from epoch float)


class ServoReachNode(Node):
    def __init__(self) -> None:
        super().__init__("servo_reach_node")

        self.declare_parameter("arm", "left")
        self.declare_parameter("target_topic", "/eduping/servo_reach/target_point")
        self.declare_parameter("twist_topic", "/servo_node/delta_twist_cmds")
        self.declare_parameter("planning_frame", "world")
        self.declare_parameter("publish_hz", 50.0)
        self.declare_parameter("gain", 1.5)
        self.declare_parameter("max_linear_speed", 0.10)
        self.declare_parameter("proximity_stop_m", 0.02)
        self.declare_parameter("target_timeout_s", 30.0)
        self.declare_parameter("start_servo_on_init", True)

        arm = self.get_parameter("arm").get_parameter_value().string_value
        if arm not in ("left", "right"):
            raise RuntimeError(f"arm 은 left|right 만 — got {arm!r}")
        self.ee_frame = f"openarm_{arm}_link7"
        self.planning_frame = self.get_parameter(
            "planning_frame").get_parameter_value().string_value
        self.publish_hz = self.get_parameter(
            "publish_hz").get_parameter_value().double_value
        self.gain = self.get_parameter("gain").get_parameter_value().double_value
        self.max_linear_speed = self.get_parameter(
            "max_linear_speed").get_parameter_value().double_value
        self.proximity_stop_m = self.get_parameter(
            "proximity_stop_m").get_parameter_value().double_value
        self.target_timeout_s = self.get_parameter(
            "target_timeout_s").get_parameter_value().double_value

        target_topic = self.get_parameter(
            "target_topic").get_parameter_value().string_value
        twist_topic = self.get_parameter(
            "twist_topic").get_parameter_value().string_value

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.target: Optional[_ActiveTarget] = None

        # twist publisher — reliable (servo 가 stream 수신).
        twist_qos = QoSProfile(reliability=QoSReliabilityPolicy.RELIABLE, depth=10)
        self.twist_pub = self.create_publisher(TwistStamped, twist_topic, twist_qos)
        self.target_sub = self.create_subscription(
            PointStamped, target_topic, self._on_target, 10)

        if self.get_parameter("start_servo_on_init").get_parameter_value().bool_value:
            self._async_start_servo()

        period = 1.0 / max(self.publish_hz, 1.0)
        self.timer = self.create_timer(period, self._tick)

        self.get_logger().info(
            f"servo_reach_node arm={arm} ee={self.ee_frame} planning_frame={self.planning_frame} "
            f"gain={self.gain} max_speed={self.max_linear_speed}m/s "
            f"proximity_stop={self.proximity_stop_m}m timeout={self.target_timeout_s}s",
        )

    # ─ Target handling ─────────────────────────────────────────────────────────

    def _on_target(self, msg: PointStamped) -> None:
        # target frame ≠ planning_frame 이면 TF 로 변환 (대표적으로 d435_depth_optical_frame
        # 에서 들어오는 경우).
        if msg.header.frame_id == self.planning_frame:
            point = msg.point
        else:
            try:
                transformed = self.tf_buffer.transform(
                    msg, self.planning_frame, timeout=Duration(seconds=0.2),
                )
            except TransformException as exc:
                self.get_logger().warning(
                    f"target frame {msg.header.frame_id!r} → {self.planning_frame!r} "
                    f"transform 실패: {exc}",
                )
                return
            point = transformed.point

        now_s = self.get_clock().now().nanoseconds * 1e-9
        self.target = _ActiveTarget(point.x, point.y, point.z, now_s)
        self.get_logger().info(
            f"new target ({self.target.x:+.3f}, {self.target.y:+.3f}, {self.target.z:+.3f}) "
            f"in {self.planning_frame}",
        )

    def _current_ee_position(self) -> Optional[tuple[float, float, float]]:
        try:
            tr = self.tf_buffer.lookup_transform(
                self.planning_frame, self.ee_frame, rclpy.time.Time(),
                timeout=Duration(seconds=0.05),
            )
        except TransformException:
            return None
        t = tr.transform.translation
        return (t.x, t.y, t.z)

    # ─ Control loop ────────────────────────────────────────────────────────────

    def _tick(self) -> None:
        if self.target is None:
            return

        now_s = self.get_clock().now().nanoseconds * 1e-9
        if now_s - self.target.received_at > self.target_timeout_s:
            self.get_logger().warning(
                f"target timeout ({self.target_timeout_s:.1f}s) — abort, publishing zero twist",
            )
            self._publish_zero()
            self.target = None
            return

        ee = self._current_ee_position()
        if ee is None:
            return   # TF not yet available — 다음 tick 재시도

        ex = self.target.x - ee[0]
        ey = self.target.y - ee[1]
        ez = self.target.z - ee[2]
        dist = math.sqrt(ex * ex + ey * ey + ez * ez)

        if dist < self.proximity_stop_m:
            self._publish_zero()
            self.get_logger().info(
                f"reached target (dist={dist:.4f}m ≤ proximity_stop={self.proximity_stop_m}m)",
            )
            self.target = None
            return

        speed = min(self.gain * dist, self.max_linear_speed)
        inv = 1.0 / dist
        twist = TwistStamped()
        twist.header.frame_id = self.planning_frame
        twist.header.stamp = self.get_clock().now().to_msg()
        twist.twist.linear.x = speed * ex * inv
        twist.twist.linear.y = speed * ey * inv
        twist.twist.linear.z = speed * ez * inv
        # angular 은 본 단계에선 미사용 (EE orientation hold). 필요 시 별도 슬롯.
        self.twist_pub.publish(twist)

    def _publish_zero(self) -> None:
        twist = TwistStamped()
        twist.header.frame_id = self.planning_frame
        twist.header.stamp = self.get_clock().now().to_msg()
        self.twist_pub.publish(twist)

    # ─ Servo start ─────────────────────────────────────────────────────────────

    def _async_start_servo(self) -> None:
        client = self.create_client(Trigger, "/servo_node/start_servo")

        def _try_call() -> None:
            if not client.service_is_ready():
                # servo 가 아직 안 떴으면 매 1초 재시도
                self.create_timer(1.0, _try_call_once)
                return
            future = client.call_async(Trigger.Request())

            def _done(_fut) -> None:
                try:
                    resp = _fut.result()
                    self.get_logger().info(
                        f"/servo_node/start_servo → success={resp.success} msg={resp.message!r}",
                    )
                except Exception as exc:
                    self.get_logger().warning(f"/servo_node/start_servo 실패: {exc}")
            future.add_done_callback(_done)

        retry_timer: list[Optional[rclpy.timer.Timer]] = [None]

        def _try_call_once() -> None:
            if client.service_is_ready():
                if retry_timer[0] is not None:
                    retry_timer[0].cancel()
                _try_call()

        retry_timer[0] = self.create_timer(1.0, _try_call_once)

    def shutdown(self) -> None:
        try:
            self._publish_zero()
        except Exception:
            pass


def main() -> None:
    rclpy.init()
    node = ServoReachNode()
    try:
        rclpy.spin(node)
    finally:
        node.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
