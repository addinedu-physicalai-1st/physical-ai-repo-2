"""GogoPing modes — 프로그램 진입점.

흐름:
1. ``rclpy.init`` + Node(namespace="gogoping") 생성
2. ``init_blackboard()`` → 21 Keys 기본값 세팅
3. ``RobotFSM`` 인스턴스 + ``Context`` 생성 (interfaces 6개 + FSM + node)
4. FSM 의 ``on_state_change`` 콜백에 ``_on_state_change`` 등록 → BT 트리 swap
5. ``TICK_HZ`` 주기로 ``_tick``:
     - 트리 tick
     - root SUCCESS / FAILURE → 적절한 trigger (task_done / return_request)
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
from .interfaces.blackboard_service import BlackboardServiceServer

# 평탄화 (2026-05-25): 4 task state — root SUCCESS 시 task_done 발화 대상.
_TASK_STATES = frozenset({"GOTO", "FOLLOW", "LULLABY", "HIDEANDSEEK"})
from .interfaces import (
    BaseDriverClient,
    BatterySubscriber,
    CameraPanClient,
    CollisionSubscriber,
    DBLogger,
    DebugEventPublisher,
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
            base_driver=BaseDriverClient(node),
            cmd_vel_pub=node.create_publisher(Twist, "/gogoping/cmd_vel", 10),
            debug_events=DebugEventPublisher(node),
        )

        # 4) BT 트리 상태 + state 변화 콜백
        self.tree: py_trees.trees.BehaviourTree | None = None
        self._current_state: str | None = None
        # _on_state_change 가 기록만 하고, 실제 BT swap 은 _tick 첫머리에서 처리.
        # 이유:
        #   - service callback thread (rclpy executor) 에서 fsm.trigger() 가 호출되면
        #     transitions 라이브러리가 on_state_change 콜백을 *동기* 발화 — 그 안에서
        #     stop(INVALID) + setup() 까지 다 하면 main thread 의 _tick 과 race
        #     (트리 자료구조가 partial 상태에서 tick).
        #   - VerifyDockingContact 같이 본인 트리의 update() 안에서 fsm.trigger("docked")
        #     를 호출하는 노드가 있어 — 즉시 swap 하면 자기 트리를 자기 update 도중
        #     stop 하는 reentrancy.
        # 한 tick (100 ms @ 10 Hz) latency 발생하지만, BT leaf 들의 terminate() 가
        # cmd_vel=0 / goal cancel 책임지므로 안전.
        self._pending_state: str | None = None
        fsm.add_callback("on_state_change", self._on_state_change)

        # SubBT transition tracker — SubTree (BT_*_sub) 안 Sequence 의 active child
        # 변화를 admin UI 에 emit. py_trees 가 transition callback 을 제공하지 않으므로
        # 매 tick polling 으로 변화 감지. BT swap 으로 SubTree 재빌드되면 reset.
        self._subbt_display_name: str | None = None
        self._subbt_sequence_id: int = 0
        self._subbt_running_idx: int = -1

        # 부팅 시 INITIAL_STATE 의 트리 build (FSM 콜백은 state 변경 시에만 fire 라 초기 1회는 수동)
        self._build_tree_for_state(self.INITIAL_STATE)

        # 5) 외부 blackboard write 서비스 — control-service 의 hideseek 핸들러가 호출.
        # CommandListener (BT behavior) 와 달리 *항상* live (트리 swap 무관) — 별도 노드 등록.
        self._blackboard_service = BlackboardServiceServer(node)

        # 6) tick + publish 타이머
        self._timer = node.create_timer(1.0 / self.TICK_HZ, self._tick)
        self._last_publish = 0.0

        # 7) 근접 상황 — robot-web/admin 안내 표시 전용 (FSM 로직엔 무관).
        # graph_router 와 동일한 /gogoping/proximity_event 를 구독해 snapshot 에 실어
        # 기존 /ws/robot-state 파이프로 UI 에 전달 (새 WS 불필요).
        from std_msgs.msg import String as _String
        self._latest_proximity: dict | None = None
        node.create_subscription(
            _String, "/gogoping/proximity_event", self._on_proximity_event, 10,
        )

        self._logger.info(
            f"GogopingModes ready — initial state={fsm.current_state}, "
            f"tick={self.TICK_HZ}Hz, publish={self.PUBLISH_HZ}Hz"
        )

    # ------------------------------------------------------------ BT swap

    def _on_state_change(self) -> None:
        """FSM state 변경 콜백 — pending state 만 기록. 실제 BT swap 은 _tick 에서.

        service callback thread 또는 본인 BT update() 안에서 호출돼도 안전 —
        실제 트리 stop/build/setup 은 main thread (timer) 의 다음 _tick 첫머리.
        """
        new_state = self.ctx.fsm.current_state
        if new_state == self._current_state:
            return
        self._pending_state = new_state
        if self.ctx.debug_events is not None:
            self.ctx.debug_events.event(
                "FSM", f"{self._current_state} → {new_state}"
            )

    def _build_tree_for_state(self, state: str) -> None:
        """이전 트리 shutdown + 새 트리 build + setup.

        ``tree.shutdown()`` 단독으로는 RUNNING 자식의 ``terminate(INVALID)`` 가 호출 안 됨
        (py_trees 의 shutdown 은 cleanup 만). ``root.stop(INVALID)`` 를 먼저 호출해서
        명시적으로 자식 terminate 전파 — ManualTorqueHold 의 enable 복원 보장 등 필수.
        """
        if self.tree is not None:
            try:
                self.tree.root.stop(py_trees.common.Status.INVALID)
            except Exception as e:
                self._logger.warning(f"root.stop(INVALID) failed: {e}")
            self.tree.shutdown()
        root = build_main_tree(state, self.ctx)
        self.tree = py_trees.trees.BehaviourTree(root)
        try:
            # node 를 명시 전달 — NavigateToVertex 등 일부 behavior 가 setup(node=...) 를 요구.
            # debug_events 도 같이 전달 — NavigateToVertex 가 cancel chain event publish 용.
            # py_trees 의 composite/decorator 가 자식들에게 kwargs 를 전파한다.
            self.tree.setup(
                timeout=5.0, node=self.node, debug_events=self.ctx.debug_events,
            )
        except Exception as e:
            self._logger.error(f"BT setup failed for state={state}: {e}")
            raise
        self._current_state = state

    # ------------------------------------------------------------ Tick

    def _tick(self) -> None:
        """매 1/TICK_HZ 초 호출 — (deferred BT swap) + BT tick + root status 처리 + publish."""
        # 0) deferred BT swap — _on_state_change 가 기록한 pending state 가 있으면 먼저 처리.
        #    GIL 덕에 단일 ref 의 read/write 는 atomic — lock 불필요.
        pending = self._pending_state
        if pending is not None and pending != self._current_state:
            self._logger.info(f"[BT swap] {self._current_state} → {pending}")
            if self.ctx.debug_events is not None:
                self.ctx.debug_events.event(
                    "BT swap", f"{self._current_state} → {pending}"
                )
            self._build_tree_for_state(pending)
        # 일치하든 안 하든 pending 은 소비.
        self._pending_state = None

        if self.tree is None:
            return

        # 1) BT tick
        self.tree.tick()

        # 1.5) SubBT transition emit — Sequence 안 active leaf 변화 감지
        self._emit_subbt_transitions()

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
                proximity=self._latest_proximity,
            )
            self.ctx.ui.publish_state(snap)
            self._last_publish = now

    # ------------------------------------------------------------ SubBT 트랜지션

    _SUBBT_SEARCH_MAX_DEPTH = 6
    _SUBBT_DECORATOR_MAX_DEPTH = 4

    def _emit_subbt_transitions(self) -> None:
        """SubTree (``BT_*_sub``) 안 Sequence 의 active child 변경 시 ``[SubBT]`` event.

        py_trees 는 transition callback 없음 → 매 tick polling. BT swap 이 SubTree 를
        rebuild 하면 ``id(sequence)`` 가 바뀌므로 tracker state 자동 reset.

        emit 케이스 (선택적 — 노이즈 줄이려고):
          - 첫 RUNNING child 등장: ``"BT_X_sub: → step1"``
          - active child 교체: ``"BT_X_sub: step1 ✓ → step2"`` / ``"step1 ✗ → step2"`` (warn)
          - 마지막 child 종료 후 SubTree SUCCESS/FAILURE: ``"step3 ✓ (exit SUCCESS)"``
        """
        if self.ctx.debug_events is None or self.tree is None:
            return

        sub = self._find_subtree_by_name(self.tree.root)
        if sub is None:
            # 이전 SubTree 정보 정리 (BT swap 이 다른 state 로 갔거나 root 트리에 SubTree 자체가 없을 때)
            self._subbt_display_name = None
            self._subbt_sequence_id = 0
            self._subbt_running_idx = -1
            return

        # SubTree 가 decorator (OneShot 등) 면 multi-child composite 까지 descend.
        # BT_goto_sub 처럼 SubTree 자체가 Sequence 인 경우는 descend 즉시 자기 반환.
        seq = self._descend_to_sequence(sub)
        if seq is None:
            return

        # BT swap 으로 tree 가 재빌드되면 seq python id 가 바뀜 → tracker reset.
        seq_id = id(seq)
        if seq_id != self._subbt_sequence_id:
            self._subbt_display_name = sub.name
            self._subbt_sequence_id = seq_id
            self._subbt_running_idx = -1

        children = list(getattr(seq, "children", None) or [])
        running_idx = -1
        for i, child in enumerate(children):
            st = getattr(child, "status", None)
            if st is not None and getattr(st, "name", None) == "RUNNING":
                running_idx = i
                break

        if running_idx == self._subbt_running_idx:
            return  # 변화 없음

        prev_idx = self._subbt_running_idx
        self._subbt_running_idx = running_idx
        display_name = self._subbt_display_name or sub.name

        # 첫 RUNNING child 등장 — SubTree 시작 직후
        if prev_idx < 0:
            if running_idx >= 0:
                curr = children[running_idx]
                self.ctx.debug_events.event(
                    "SubBT", f"{display_name}: → {curr.name}"
                )
            return

        if not (0 <= prev_idx < len(children)):
            return
        prev_child = children[prev_idx]
        prev_status_name = getattr(getattr(prev_child, "status", None), "name", "INVALID")
        mark = {"SUCCESS": "✓", "FAILURE": "✗"}.get(prev_status_name, "○")
        level = "warn" if prev_status_name == "FAILURE" else "info"

        if running_idx >= 0:
            curr = children[running_idx]
            self.ctx.debug_events.event(
                "SubBT",
                f"{display_name}: {prev_child.name} {mark} → {curr.name}",
                level=level,
            )
            return

        # running 자식 없음 — Sequence 종료. SubTree 자체 status 도 함께 표시.
        sub_status_name = getattr(getattr(sub, "status", None), "name", "INVALID")
        if sub_status_name in ("SUCCESS", "FAILURE"):
            sub_level = "warn" if sub_status_name == "FAILURE" else "info"
            self.ctx.debug_events.event(
                "SubBT",
                f"{display_name}: {prev_child.name} {mark} (exit {sub_status_name})",
                level=sub_level,
            )
        else:
            self.ctx.debug_events.event(
                "SubBT", f"{display_name}: {prev_child.name} {mark}", level=level,
            )

    def _find_subtree_by_name(self, node, depth: int = 0):
        """``BT_*_sub`` 첫 매칭 노드. ``tree_inspector._find_subtree`` 와 달리 status 무관."""
        if depth >= self._SUBBT_SEARCH_MAX_DEPTH:
            return None
        name = getattr(node, "name", "")
        if name.startswith("BT_") and name.endswith("_sub"):
            return node
        children = getattr(node, "children", None)
        if not children:
            return None
        for child in children:
            found = self._find_subtree_by_name(child, depth + 1)
            if found is not None:
                return found
        return None

    def _descend_to_sequence(self, sub_node):
        """OneShot 등 single-child wrapper 를 가로질러 첫 multi-child composite 반환.

        BT_goto_sub 처럼 sub_node 자체가 Sequence (children ≥ 2) 면 그대로 반환.
        BT_return_sub 처럼 OneShot decorator 는 child 1개라 descend.
        max depth 안에서 multi-child 못 찾으면 None.
        """
        cur = sub_node
        for _ in range(self._SUBBT_DECORATOR_MAX_DEPTH):
            children = getattr(cur, "children", None)
            if not children:
                return None
            if len(children) > 1:
                return cur
            cur = children[0]
        return None

    def _on_tree_success(self) -> None:
        """MainTree root SUCCESS = task state 완료 → IDLE 복귀.

        평탄화 (2026-05-25): GOTO/FOLLOW/LULLABY/HIDEANDSEEK 4 task state 모두
        task_done 한 trigger 로 통합. body SUCCESS 시 shell 의 SuccessOnSelected 정책에
        의해 root SUCCESS → 본 콜백 → task_done → IDLE.

        IDLE / CHARGING / MANUAL / RETURNING / LOW_BATTERY_RETURNING / ERROR 의 root SUCCESS 는
        task 완료 의미가 아니므로 무시 (state 전이는 그쪽 monitor 의 trigger 가 담당).
        """
        if self._current_state not in _TASK_STATES:
            return
        self._logger.info(f"[tree SUCCESS] {self._current_state} → task_done")
        self.ctx.fsm.trigger("task_done")

    def _on_proximity_event(self, msg) -> None:
        """/gogoping/proximity_event(JSON) → snapshot 의 proximity 필드용 캐시.

        표시 전용 — FSM/BT 로직엔 영향 없음. 파싱 실패 시 None.
        """
        import json
        try:
            self._latest_proximity = json.loads(msg.data)
        except (ValueError, TypeError, AttributeError):
            self._latest_proximity = None

    def _on_tree_failure(self) -> None:
        """MainTree root FAILURE 처리.

        - GOTO 실패 = 목적지 도달 불가(주로 경로 막힘 + 우회로 없음). 이때 충전소 복귀
          (RETURNING)는 부적절 — 복귀 경로도 같은 막힌 곳을 지나면 또 멈춘다. 그 자리
          정지 후 IDLE 로 보내 사람이 비키거나 재명령을 기다린다. (배터리 부족 등 진짜
          복귀 사유는 BatteryLowMonitor 가 별도 trigger 로 처리.)
        - 그 외 task state(FOLLOW/LULLABY/HIDEANDSEEK) 실패 = 기존대로 RETURNING 도피.
          예: FollowSubTree 의 Loss Recovery 끝까지 대상 못 찾음 → 복귀.
        """
        if self._current_state == "GOTO":
            self._logger.warning("[tree FAILURE] GOTO 도달 불가 → cancel (IDLE 정지)")
            self.ctx.fsm.trigger("cancel")
            return
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
