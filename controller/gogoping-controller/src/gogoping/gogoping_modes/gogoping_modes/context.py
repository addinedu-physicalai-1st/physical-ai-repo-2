"""공유 객체 저장소 — 모든 behavior 가 ``self.ctx.<name>`` 한 줄로 의존성 접근.

부팅 시 ``main.py`` 의 ``GogopingModes.__init__`` 에서 1회 생성 후 **불변** —
필드 추가 / 교체 / 재할당 금지. ROS Node / FSM 인스턴스 / 6개 interfaces 를 묶는다.

자세한 컨벤션: ``docs/conventions.md`` §1.

Blackboard 는 본 Context 에 두지 않는다 — py_trees 의 전역 blackboard 를 각 behavior 가
``attach_blackboard_client()`` 로 따로 접근 (``docs/conventions.md`` §1 규칙).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import rclpy.node

from .fsm.robot_fsm import RobotFSM
from .interfaces import (
    BatterySubscriber,
    CameraPanClient,
    CollisionSubscriber,
    DBLogger,
    MapCache,
    Nav2Client,
    OdomSubscriber,
    UIPublisher,
)


@dataclass(frozen=True)
class Context:
    """모든 behavior 에 주입되는 공유 의존성 묶음.

    `frozen=True` — 부팅 후 필드 재할당 시 ``FrozenInstanceError``. 새 의존성은
    Context 생성 시점에 모두 채워야 함.
    """

    node: "rclpy.node.Node"          # ROS 노드 — 로깅 / 파라미터 / 새 client 생성용
    fsm: RobotFSM                    # state 전이 (trigger 호출)
    nav2: Nav2Client
    camera_pan: CameraPanClient
    ui: UIPublisher
    battery: BatterySubscriber
    collision: CollisionSubscriber
    db_logger: DBLogger
    odom: OdomSubscriber             # /gogoping/odom 구독 → blackboard.ROBOT_POSE
    map_cache: MapCache              # /map 구독 + is_outside(x,y) (map_boundary_monitor 가 사용)
