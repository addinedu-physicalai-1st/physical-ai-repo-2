"""5초마다 /clear_octomap 서비스를 호출해 stale voxel 제거.

PointCloudOctomapUpdater 는 decay 없어서, 사람이 자리를 떠도 voxel 이 영구 잔존.
주기 비우기로 fresh 한 octomap 유지. 비우는 순간 충돌 회피 신뢰성 약간 ↓ 이지만
다음 frame (~100ms 내) 에 다시 채워짐.

1Hz 에선 move_group PlanningSceneMonitor 가 매번 lock 잡혀 hybrid IK 의 FK/IK
service 호출이 줄줄이 timeout — 5s 로 충분 (장면 변화 빈도 그 정도).
"""
import rclpy
from rclpy.node import Node
from std_srvs.srv import Empty


class ClearOctomapTimer(Node):
    def __init__(self) -> None:
        super().__init__("clear_octomap_timer")
        self.cli = self.create_client(Empty, "/clear_octomap")
        self.timer = self.create_timer(5.0, self._tick)
        self._warned = False

    def _tick(self) -> None:
        if not self.cli.service_is_ready():
            if not self._warned:
                self.get_logger().info("waiting for /clear_octomap service...")
                self._warned = True
            return
        self._warned = False
        self.cli.call_async(Empty.Request())


def main() -> None:
    rclpy.init()
    node = ClearOctomapTimer()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
