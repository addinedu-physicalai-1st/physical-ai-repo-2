"""BT behavior — graph_router 의 NavigateToVertex action 호출.

다익스트라로 lane 따라 이동 (NavigateThroughPoses 위임).

Blackboard:
  read:  target_vertex_name (str)  — 목적지 vertex name (waypoints.yaml 의 name)
  write: 없음

Action: /graph_router/navigate_to_vertex (gogoping_msgs/action/NavigateToVertex)

Status:
  RUNNING — 이동 중
  SUCCESS — 도착
  FAILURE — vertex 없음 / 경로 없음 / nav2 거부 / 취소

사용 예 (BT_carry_sub goto 모드):
    py_trees.composites.Sequence(children=[
        SetTargetVertex("운동장입구", target_key="target_vertex_name"),
        NavigateToVertex(),
        SayArrived(),
    ])
"""
from __future__ import annotations

from typing import Any

import py_trees
from rclpy.action import ActionClient

from gogoping_msgs.action import NavigateToVertex as NavigateToVertexAction


class NavigateToVertex(py_trees.behaviour.Behaviour):
    DEFAULT_ACTION = "/graph_router/navigate_to_vertex"
    DEFAULT_TARGET_KEY = "target_vertex_name"

    def __init__(
        self,
        name: str = "navigate_to_vertex",
        target_key: str = DEFAULT_TARGET_KEY,
        action_name: str = DEFAULT_ACTION,
    ) -> None:
        super().__init__(name)
        self._target_key = target_key
        self._action_name = action_name
        self._client: ActionClient | None = None
        self._node: Any = None
        self._goal_handle = None
        # terminate(INVALID) 가 send_goal_async 응답 전에 도착하면 True 로 set —
        # _on_goal_response 가 gh 받자마자 즉시 cancel 후 result 콜백 등록 skip.
        # 없으면 nav2 goal 좀비화 (state 는 swap 됐는데 robot 이 이전 경로 따라감).
        self._cancel_pending: bool = False
        self._result_status: str | None = None  # "succeeded" / "failed" / None
        self._failure_reason: str = ""
        # admin UI NavDebugLogCard 용 — main.py 가 setup(kwargs) 로 주입. None 이면 no-op.
        self._debug_events: Any = None
        self._last_target: str = ""
        self.blackboard = self.attach_blackboard_client(name=self.qualified_name)
        self.blackboard.register_key(
            key=self._target_key, access=py_trees.common.Access.READ
        )

    def setup(self, **kwargs: Any) -> None:
        try:
            self._node = kwargs["node"]
        except KeyError as e:
            raise KeyError("setup() requires 'node' kwarg (rclpy node)") from e
        self._client = ActionClient(
            self._node, NavigateToVertexAction, self._action_name
        )
        self._debug_events = kwargs.get("debug_events")

    def _dbg(self, msg: str, level: str = "info") -> None:
        if self._debug_events is not None:
            try:
                self._debug_events.event("NavTo", msg, level=level)
            except Exception:
                pass

    def initialise(self) -> None:
        self._goal_handle = None
        self._cancel_pending = False
        self._result_status = None
        self._failure_reason = ""
        try:
            target = self.blackboard.get(self._target_key)
        except KeyError:
            self._result_status = "failed"
            self._failure_reason = f"blackboard.{self._target_key} not set"
            return
        if not isinstance(target, str) or not target:
            self._result_status = "failed"
            self._failure_reason = f"invalid target: {target!r}"
            return
        if self._client is None or not self._client.server_is_ready():
            # action server 없으면 1회 짧은 wait
            if self._client is None or not self._client.wait_for_server(timeout_sec=0.5):
                self._result_status = "failed"
                self._failure_reason = "action server unavailable"
                return
        goal = NavigateToVertexAction.Goal()
        goal.target_name = target
        self._last_target = target
        send_future = self._client.send_goal_async(goal)
        send_future.add_done_callback(self._on_goal_response)
        self._dbg(f"send → {target!r}")

    def _on_goal_response(self, fut: Any) -> None:
        gh = fut.result()
        if not gh.accepted:
            self._result_status = "failed"
            self._failure_reason = "rejected"
            self._dbg(f"gh rejected ({self._last_target!r})", level="warn")
            return
        self._goal_handle = gh
        # behavior 가 이미 terminate(INVALID) 됐다면 (race) — 즉시 cancel forward.
        # result 콜백 등록은 skip — behavior 는 이미 죽었음.
        if self._cancel_pending:
            try:
                gh.cancel_goal_async()
            except Exception:
                pass
            self._cancel_pending = False
            self._dbg(
                f"race cancel via pending flag ({self._last_target!r})", level="warn"
            )
            return
        self._dbg(f"gh accepted ({self._last_target!r})")
        result_fut = gh.get_result_async()
        result_fut.add_done_callback(self._on_result)

    def _on_result(self, fut: Any) -> None:
        wrapper = fut.result()
        res = wrapper.result
        if getattr(res, "success", False):
            self._result_status = "succeeded"
            self._dbg(f"SUCCESS @ {self._last_target!r}")
        else:
            self._result_status = "failed"
            self._failure_reason = getattr(res, "message", "") or "nav2 failed"
            self._dbg(
                f"FAILURE @ {self._last_target!r} reason={self._failure_reason!r}",
                level="warn",
            )

    def update(self) -> py_trees.common.Status:
        if self._result_status == "succeeded":
            return py_trees.common.Status.SUCCESS
        if self._result_status == "failed":
            self.feedback_message = self._failure_reason
            return py_trees.common.Status.FAILURE
        return py_trees.common.Status.RUNNING

    def terminate(self, new_status: py_trees.common.Status) -> None:
        # tree 가 INVALID (parent 가 끊음) 로 가면 진행 중 goal 취소
        if new_status != py_trees.common.Status.INVALID:
            return
        if self._goal_handle is not None:
            try:
                self._goal_handle.cancel_goal_async()
            except Exception:
                pass
            self._goal_handle = None
            self._dbg(f"terminate(INVALID) gh=present → cancel ({self._last_target!r})")
        else:
            # send_goal_async 응답 전 — _on_goal_response 가 도착 시 cancel.
            self._cancel_pending = True
            self._dbg(
                f"terminate(INVALID) gh=None → pending ({self._last_target!r})",
                level="warn",
            )
