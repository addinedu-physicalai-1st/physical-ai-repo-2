"""Coordinate-triggered camera nod sequence with smooth interpolation.

로봇 위치 (`/gogoping/odom`, nav_msgs/Odometry) 가 사전 정의된 트리거 좌표
(TRIGGER_COORDS) 에 일정 거리 이내로 진입하면, 카메라를 다음 시퀀스로
**부드럽게 보간** 회전시킨다:

    90° → 0°   (2초 동안 선형 보간)
    0°  → 180° (4초 동안 선형 보간)
    180° → 90° (2초 동안 선형 보간, 제자리 복귀)

총 8초. 같은 좌표 재방문 시 한 세션 동안 한 번만 실행.

이 노드는 시리얼을 직접 다루지 않고 servo_bridge 노드의
`/servo_bridge/cmd_angle` (std_msgs/Float32) 토픽으로 중간 각도를
tick_hz 주기로 발행한다. 실제 USB 시리얼은 servo_bridge 가 담당.

참고: /home/leekangteak/pyserial-test/src/servo_trigger/servo_trigger/servo_trigger_node.py
"""
from __future__ import annotations

import math
import time

import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.timer import Timer
from std_msgs.msg import Float32


# (x, y) 트리거 좌표 — Travex waypoint
TRIGGER_COORDS: list[tuple[float, float]] = [
    (1.0, 1.0),
    (2.0, 2.0),
    (3.0, 3.0),
]


class CoordTrigger(Node):
    def __init__(self) -> None:
        super().__init__('coord_trigger')

        self.declare_parameter('threshold_m', 0.5)
        self.declare_parameter('odom_topic', '/gogoping/odom')
        self.declare_parameter('cmd_topic', '/servo_bridge/cmd_angle')
        self.declare_parameter('left_deg', 0.0)
        self.declare_parameter('right_deg', 180.0)
        self.declare_parameter('center_deg', 90.0)
        self.declare_parameter('left_duration_s', 2.0)    # center → left
        self.declare_parameter('right_duration_s', 4.0)   # left → right
        self.declare_parameter('center_duration_s', 2.0)  # right → center
        self.declare_parameter('tick_hz', 20.0)           # 보간 발행 주기

        self._threshold = float(self.get_parameter('threshold_m').value)
        odom_topic = str(self.get_parameter('odom_topic').value)
        cmd_topic = str(self.get_parameter('cmd_topic').value)

        self._left_deg = float(self.get_parameter('left_deg').value)
        self._right_deg = float(self.get_parameter('right_deg').value)
        self._center_deg = float(self.get_parameter('center_deg').value)
        self._left_dur = float(self.get_parameter('left_duration_s').value)
        self._right_dur = float(self.get_parameter('right_duration_s').value)
        self._center_dur = float(self.get_parameter('center_duration_s').value)
        self._tick_hz = max(float(self.get_parameter('tick_hz').value), 1.0)

        self._triggered_coords: set[tuple[float, float]] = set()
        self._animation_running = False

        # 시퀀스 상태 — 보간 중에 사용
        self._segments: list[tuple[float, float, float]] = []   # (start, end, duration)
        self._segment_idx = 0
        self._segment_t0 = 0.0
        self._tick_timer: Timer | None = None

        self.cmd_pub = self.create_publisher(Float32, cmd_topic, 10)
        self.odom_sub = self.create_subscription(
            Odometry, odom_topic, self._on_odom, 10
        )

        self.get_logger().info(
            f'CoordTrigger: odom={odom_topic}, cmd={cmd_topic}, '
            f'threshold={self._threshold}m, {len(TRIGGER_COORDS)} coords, '
            f'durations={self._left_dur}/{self._right_dur}/{self._center_dur}s '
            f'@ {self._left_deg}/{self._right_deg}/{self._center_deg}°, '
            f'tick={self._tick_hz}Hz'
        )

    def _on_odom(self, msg: Odometry) -> None:
        if self._animation_running:
            return

        x = msg.pose.pose.position.x
        y = msg.pose.pose.position.y

        for coord in TRIGGER_COORDS:
            if coord in self._triggered_coords:
                continue
            dx, dy = x - coord[0], y - coord[1]
            dist = math.hypot(dx, dy)
            if dist < self._threshold:
                self._triggered_coords.add(coord)
                self.get_logger().info(
                    f'Triggered ({coord[0]}, {coord[1]}) dist={dist:.3f}m '
                    f'→ start nod sequence'
                )
                self._start_nod_sequence()
                break

    def _start_nod_sequence(self) -> None:
        # 3 segment: center → left, left → right, right → center
        self._segments = [
            (self._center_deg, self._left_deg, self._left_dur),
            (self._left_deg, self._right_deg, self._right_dur),
            (self._right_deg, self._center_deg, self._center_dur),
        ]
        self._segment_idx = 0
        self._segment_t0 = time.monotonic()
        self._animation_running = True
        # 시작 각도 즉시 발행
        self._publish_angle(self._segments[0][0])
        # tick timer 시작
        self._tick_timer = self.create_timer(1.0 / self._tick_hz, self._on_tick)

    def _on_tick(self) -> None:
        if self._segment_idx >= len(self._segments):
            self._finish_animation()
            return

        start, end, duration = self._segments[self._segment_idx]
        elapsed = time.monotonic() - self._segment_t0

        if elapsed >= duration:
            # segment 종료 — 정확한 끝 각도 발행 후 다음 segment 로
            self._publish_angle(end)
            self._segment_idx += 1
            self._segment_t0 = time.monotonic()
            if self._segment_idx >= len(self._segments):
                self._finish_animation()
            return

        # 선형 보간
        t = elapsed / duration
        deg = start + (end - start) * t
        self._publish_angle(deg)

    def _publish_angle(self, deg: float) -> None:
        msg = Float32()
        msg.data = float(deg)
        self.cmd_pub.publish(msg)

    def _finish_animation(self) -> None:
        if self._tick_timer is not None:
            self._tick_timer.cancel()
            self._tick_timer = None
        self._animation_running = False
        self._segments = []
        self._segment_idx = 0
        self.get_logger().info('Nod sequence complete')

    def destroy_node(self) -> bool:
        if self._tick_timer is not None:
            try:
                self._tick_timer.cancel()
            except Exception:
                pass
        try:
            self._publish_angle(self._center_deg)
        except Exception:
            pass
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = CoordTrigger()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
