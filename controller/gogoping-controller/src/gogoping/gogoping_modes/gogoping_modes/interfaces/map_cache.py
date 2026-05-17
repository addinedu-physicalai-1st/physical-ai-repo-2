"""``/map`` OccupancyGrid 구독 + ``is_outside(x, y)`` 순수 메서드 노출.

토픽 / QoS (sim_with_nav2.launch.xml 의 nav2_map_server 와 일치):
- 토픽 절대경로 ``"/map"`` — nav2_map_server 가 root namespace 에 띄워져서 publish.
  gogoping_modes 의 namespace=``gogoping`` 과 무관 → **반드시 절대 경로 사용**.
- durability ``TRANSIENT_LOCAL`` (latched) — 늦게 붙은 subscriber 도 마지막 메시지 받음.
  default ``VOLATILE`` 쓰면 publisher 와 mismatch → 메시지 영영 안 받음.
- reliability ``RELIABLE`` + depth=1.

운영(실물 Pi) 환경 통합:
- 노트북에 ``map_only.launch.xml`` (이미 존재) 띄워야 ``/map`` 발행됨.
  ``device-gogoping-laptop.sh`` 에 window 추가 예정.
- 같은 ROS_DOMAIN_ID 면 Pi/노트북/admin 모두 자동 수신.

is_outside 알고리즘 (``docs/bt/behaviors/common.md#map_boundary_monitor``):
- 격자 박스 (width × height) 밖 → True
- 박스 안이지만 ``data[idx] == -1`` (unknown) → True
  ※ SLAM 으로 만든 맵에서 unknown 셀 = "맵 영역 밖" 의미.
- 그 외 (free=0 / occupied=100) → False

맵 미수신 시 (``_latest is None``) → ``None`` 반환. monitor 는 ``None`` 보면 발화 안 함
(보수적 default — ``ERROR`` terminal 이라 false positive 회피).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from nav_msgs.msg import OccupancyGrid
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

if TYPE_CHECKING:
    import rclpy.node


class MapCache:
    """``/map`` OccupancyGrid 캐시 + 좌표 안/밖 판별."""

    TOPIC = "/map"   # 절대경로 — root namespace 의 nav2_map_server 와 일치
    QOS_DEPTH = 1

    def __init__(self, node: "rclpy.node.Node"):
        self.node = node
        self._latest: OccupancyGrid | None = None
        qos = QoSProfile(
            depth=self.QOS_DEPTH,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE,
        )
        self._sub = node.create_subscription(
            OccupancyGrid, self.TOPIC, self._on_map, qos
        )

    def _on_map(self, msg: OccupancyGrid) -> None:
        self._latest = msg

    def is_outside(self, x: float, y: float) -> bool | None:
        """좌표가 맵 영역 밖이면 True, 안이면 False. 맵 미수신 시 None.

        ``None`` 은 호출자가 "발화 안 함" 으로 해석 (보수적 default).
        """
        msg = self._latest
        if msg is None:
            return None

        info = msg.info
        if info.resolution <= 0.0:
            # corrupt map — 안전 default
            return None

        # world (m) → 격자 셀 인덱스
        col = int((x - info.origin.position.x) / info.resolution)
        row = int((y - info.origin.position.y) / info.resolution)

        # 1) 격자 박스 밖
        if col < 0 or col >= info.width or row < 0 or row >= info.height:
            return True

        # 2) 박스 안이지만 unknown (-1) 셀
        idx = row * info.width + col
        return int(msg.data[idx]) == -1

    def has_map(self) -> bool:
        """현재 맵 캐시 보유 여부."""
        return self._latest is not None
