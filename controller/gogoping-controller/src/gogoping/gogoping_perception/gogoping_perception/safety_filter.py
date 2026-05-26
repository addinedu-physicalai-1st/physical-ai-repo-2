"""Safety filter — /gogoping/cmd_vel_raw → /gogoping/cmd_vel passthrough.

safety_stop True 시 zero Twist override. False 면 그대로 forward.
raw 미수신 SAFETY_STALE_TIMEOUT_S 초 후엔 zero publish (stale 방지).

Pure logic (filter_twist) 는 ROS 의존 없이 unit-testable.
"""
from __future__ import annotations

import time
from typing import Any


def filter_twist(raw: Any, safety_stop: bool) -> Any:
    """pure: safety_stop True 면 zero, False 면 raw 그대로 (필드 복사).

    raw 는 geometry_msgs/Twist 또는 같은 필드 구조 (.linear.x/y/z, .angular.x/y/z) 객체.
    반환은 Twist 객체 (ROS 환경에서) 또는 같은 구조 (test stub).
    """
    # ROS env 가 있으면 geometry_msgs.Twist, 없으면 stub 와 같은 구조 (test 호환)
    try:
        from geometry_msgs.msg import Twist
        out = Twist()
    except ImportError:
        # test 환경 — raw 와 같은 구조의 stub 만들 수 없으니 raw type 활용
        class _V:
            pass
        out = type('_TwistStub', (), {})()
        out.linear = _V()
        out.angular = _V()
        for v in (out.linear, out.angular):
            v.x = 0.0
            v.y = 0.0
            v.z = 0.0

    if safety_stop:
        return out

    out.linear.x = float(raw.linear.x)
    out.linear.y = float(raw.linear.y)
    out.linear.z = float(raw.linear.z)
    out.angular.x = float(raw.angular.x)
    out.angular.y = float(raw.angular.y)
    out.angular.z = float(raw.angular.z)
    return out


def main() -> None:
    """ROS 환경에서만 동작. test 시엔 호출 X."""
    import rclpy
    from geometry_msgs.msg import Twist
    from rclpy.node import Node
    from std_msgs.msg import Bool
    from gogoping_perception import config

    class SafetyFilterNode(Node):
        def __init__(self) -> None:
            super().__init__("gogoping_safety_filter")
            self._safety_stop: bool = False
            self._last_raw_ts: float = 0.0
            self._pub = self.create_publisher(Twist, "/gogoping/cmd_vel", 10)
            self.create_subscription(Twist, "/gogoping/cmd_vel_raw", self._on_raw, 10)
            self.create_subscription(Bool, "/gogoping/safety_stop", self._on_safety, 10)
            self._timer = self.create_timer(0.1, self._tick_stale_check)

        def _on_raw(self, msg) -> None:
            self._last_raw_ts = time.time()
            out = filter_twist(msg, self._safety_stop)
            self._pub.publish(out)

        def _on_safety(self, msg) -> None:
            self._safety_stop = bool(msg.data)

        def _tick_stale_check(self) -> None:
            if self._last_raw_ts == 0.0:
                return  # 아직 raw 한 번도 안 받음 — idle 가정, publish X
            if (time.time() - self._last_raw_ts) > config.SAFETY_STALE_TIMEOUT_S:
                self._pub.publish(Twist())

    rclpy.init()
    node = SafetyFilterNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
