"""FollowTrack — FOLLOW body. /gogoping/tracking_state 구독 → TARGET_* blackboard 브리지.

실제 추종 제어(STOP/REACTIVE/NAV2, cmd_vel)는 follow_node 가 담당 — 본 leaf 는
관측·표시(BT↔perception 브리지). StubFollow(영구 RUNNING placeholder) 교체.
항상 RUNNING — FOLLOW 는 self-complete 안 함(SUCCESS 내면 task_done 으로 즉시 종료됨).
"""
from __future__ import annotations

import time
from typing import Any, Callable, TYPE_CHECKING

import py_trees
from py_trees.common import Access, Status

from ...blackboard import Keys

if TYPE_CHECKING:
    from ....context import Context

_TOPIC = "/gogoping/tracking_state"


def tracking_state_to_blackboard(msg: Any, now: float) -> dict:
    """순수함수: TrackingState 유사 객체 → 쓸 blackboard key→value dict.

    - 항상: TARGET_VISIBLE=matched, TARGET_PERSON_ID=teacher_id
    - matched 일 때만: TARGET_SEEN_AT=now, TARGET_FACE_BBOX=(x1,y1,x2,y2)
      (미매칭 시 SEEN_AT/BBOX 는 마지막 값 유지 — 안 씀)
    """
    out: dict = {
        Keys.TARGET_VISIBLE: bool(msg.matched),
        Keys.TARGET_PERSON_ID: str(msg.teacher_id),
    }
    if msg.matched:
        out[Keys.TARGET_SEEN_AT] = float(now)
        out[Keys.TARGET_FACE_BBOX] = (
            int(msg.bbox_x1), int(msg.bbox_y1),
            int(msg.bbox_x2), int(msg.bbox_y2),
        )
    return out


class FollowTrack(py_trees.behaviour.Behaviour):
    """FOLLOW body — tracking_state 구독 → blackboard 기록, 항상 RUNNING."""

    def __init__(
        self,
        name: str,
        context: "Context",
        *,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(name)
        self.ctx = context
        self._now = now_fn
        self._sub: Any = None
        self._last_msg: Any = None
        self.bb = self.attach_blackboard_client(name=name)
        for key in (
            Keys.TARGET_VISIBLE, Keys.TARGET_PERSON_ID,
            Keys.TARGET_SEEN_AT, Keys.TARGET_FACE_BBOX,
        ):
            self.bb.register_key(key=key, access=Access.WRITE)

    def setup(self, **kwargs: Any) -> None:
        """tracking_state 구독 생성 (ProximitySafetyMonitor 와 동일 — ROS 리소스는 setup)."""
        if self._sub is not None:
            return
        node = getattr(self.ctx, "node", None)
        if node is None:
            return
        from gogoping_msgs.msg import TrackingState
        self._sub = node.create_subscription(
            TrackingState, _TOPIC, self._on_tracking_state, 10,
        )

    def _on_tracking_state(self, msg: Any) -> None:
        self._last_msg = msg

    def update(self) -> Status:
        if self._last_msg is not None:
            for key, val in tracking_state_to_blackboard(self._last_msg, self._now()).items():
                self.bb.set(key, val)
            self.feedback_message = str(getattr(self._last_msg, "mode", ""))
        return Status.RUNNING  # ⚠️ FOLLOW self-complete 금지 — 절대 SUCCESS 금지

    def terminate(self, new_status: Status) -> None:
        if self._sub is not None:
            node = getattr(self.ctx, "node", None)
            if node is not None:
                try:
                    node.destroy_subscription(self._sub)
                except Exception:
                    pass
            self._sub = None
