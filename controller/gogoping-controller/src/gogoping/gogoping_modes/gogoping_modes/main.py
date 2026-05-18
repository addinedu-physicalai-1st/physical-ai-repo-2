"""GogoPing modes — 프로그램 진입점.

흐름:
1. ``rclpy.init`` + Node(namespace="gogoping") 생성
2. ``init_blackboard()`` → 21 Keys 기본값 세팅
3. ``RobotFSM`` 인스턴스 + ``Context`` 생성 (interfaces 6개 + FSM + node)
4. FSM 의 ``on_state_change`` 콜백에 ``_on_state_change`` 등록 → BT 트리 swap
5. ``TICK_HZ`` 주기로 ``_tick``:
     - 트리 tick
     - root SUCCESS / FAILURE → 적절한 trigger (assist_done / play_done / return_request)
     - 1Hz 로 ``tree_inspector.snapshot`` 생성 후 ``UIPublisher.publish_state``
6. ``rclpy.spin``

자세한 컨벤션: ``docs/conventions.md`` §3.
"""
from __future__ import annotations

import time

import py_trees
from py_trees.common import Status

import rclpy
import rclpy.node

from .bt.blackboard import init_blackboard
from .bt.tree_inspector import snapshot
from .bt.trees.main_trees import build_main_tree
from .context import Context
from .fsm.robot_fsm import RobotFSM
from .interfaces import (
    BatterySubscriber,
    CameraPanClient,
    CollisionSubscriber,
    DBLogger,
    MapCache,
    Nav2Client,
    PoseSubscriber,
    UIPublisher,
)


class GogopingModes:
    """rclpy Node + FSM + BT swap 루프를 묶는 메인 클래스."""

    TICK_HZ = 10.0          # BT tick frequency
    PUBLISH_HZ = 1.0        # /gogoping/state publish frequency
    # 부팅 시퀀스: CHARGING → battery_full (BatteryFullMonitor 가 첫 tick 에 발화) → IDLE.
    # docs/fsm-triggers.md 의 표준 흐름.
    INITIAL_STATE = "CHARGING"

    def __init__(self, node: rclpy.node.Node):
        self.node = node
        self._logger = node.get_logger()

        # 1) blackboard 기본값
        init_blackboard()

        # 2) FSM
        fsm = RobotFSM(initial=self.INITIAL_STATE)

        # 3) Context (불변 묶음)
        from geometry_msgs.msg import Twist
        self.ctx = Context(
            node=node,
            fsm=fsm,
            nav2=Nav2Client(node),
            camera_pan=CameraPanClient(node),
            ui=UIPublisher(node),
            battery=BatterySubscriber(node),
            collision=CollisionSubscriber(node),
            db_logger=DBLogger(node),
            pose=PoseSubscriber(node),
            map_cache=MapCache(node),
            cmd_vel_pub=node.create_publisher(Twist, "/gogoping/cmd_vel", 10),
        )

        # 4) BT 트리 상태 + state 변화 콜백
        self.tree: py_trees.trees.BehaviourTree | None = None
        self._current_state: str | None = None
        fsm.add_callback("on_state_change", self._on_state_change)

        # 부팅 시 INITIAL_STATE 의 트리 build (FSM 콜백은 state 변경 시에만 fire 라 초기 1회는 수동)
        self._build_tree_for_state(self.INITIAL_STATE)

        # 5) tick + publish 타이머
        self._timer = node.create_timer(1.0 / self.TICK_HZ, self._tick)
        self._last_publish = 0.0

        self._logger.info(
            f"GogopingModes ready — initial state={fsm.current_state}, "
            f"tick={self.TICK_HZ}Hz, publish={self.PUBLISH_HZ}Hz"
        )

    # ------------------------------------------------------------ BT swap

    def _on_state_change(self) -> None:
        """FSM state 가 바뀔 때마다 호출 — 새 state 에 맞는 MainTree 로 swap."""
        new_state = self.ctx.fsm.current_state
        if new_state == self._current_state:
            return
        self._logger.info(
            f"[BT swap] {self._current_state} → {new_state}"
        )
        self._build_tree_for_state(new_state)

    def _build_tree_for_state(self, state: str) -> None:
        """이전 트리 shutdown + 새 트리 build + setup."""
        if self.tree is not None:
            self.tree.shutdown()
        root = build_main_tree(state, self.ctx)
        self.tree = py_trees.trees.BehaviourTree(root)
        try:
            # node 를 명시 전달 — NavigateToVertex 등 일부 behavior 가 setup(node=...) 를 요구.
            # py_trees 의 composite/decorator 가 자식들에게 kwargs 를 전파한다.
            self.tree.setup(timeout=5.0, node=self.node)
        except Exception as e:
            self._logger.error(f"BT setup failed for state={state}: {e}")
            raise
        self._current_state = state

    # ------------------------------------------------------------ Tick

    def _tick(self) -> None:
        """매 1/TICK_HZ 초 호출 — BT tick + root status 처리 + publish."""
        if self.tree is None:
            return

        # 1) BT tick
        self.tree.tick()

        # 2) Root SUCCESS / FAILURE 처리
        root_status = self.tree.root.status
        if root_status == Status.SUCCESS:
            self._on_tree_success()
        elif root_status == Status.FAILURE:
            self._on_tree_failure()

        # 3) 1Hz publish
        now = time.time()
        if now - self._last_publish >= 1.0 / self.PUBLISH_HZ:
            snap = snapshot(
                self.ctx.fsm.current_state,
                self.tree.root,
                map_cache=self.ctx.map_cache,
            )
            self.ctx.ui.publish_state(snap)
            self._last_publish = now

    def _on_tree_success(self) -> None:
        """MainTree root SUCCESS = ASSIST/PLAY task 완료 → IDLE 복귀.

        CHARGING / IDLE / MANUAL / RETURNING / ERROR 의 root SUCCESS 는 task 완료
        의미가 아니므로 무시 (state 전이는 그쪽 monitor 의 trigger 가 담당).
        """
        mapping = {"ASSIST": "assist_done", "PLAY": "play_done"}
        trigger = mapping.get(self._current_state)
        if trigger is None:
            return
        self._logger.info(f"[tree SUCCESS] {self._current_state} → {trigger}")
        self.ctx.fsm.trigger(trigger)

    def _on_tree_failure(self) -> None:
        """MainTree root FAILURE = SubTree 가 끝까지 실패 → RETURNING 으로 도피.

        예: FollowSubTree 의 Loss Recovery 끝까지 대상 못 찾음 → FAILURE → RETURNING.
        """
        self._logger.warning(
            f"[tree FAILURE] {self._current_state} → return_request"
        )
        self.ctx.fsm.trigger("return_request")


def main() -> None:
    rclpy.init()
    # namespace="gogoping" — 모든 토픽/서비스에 /gogoping/ prefix.
    # (UIPublisher 의 TOPIC = "state" 등 상대 path 가 자동 prefix 됨)
    node = rclpy.create_node("gogoping_modes", namespace="gogoping")
    try:
        _app = GogopingModes(node)
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
