"""nav2 액션 클라이언트 + /plan, /odom 구독.
teleop/ros_bridge.py 의 패턴: 별도 rclpy 노드, daemon thread spin, lock 보호.
rclpy 는 start() 안에서만 import — rclpy 없는 환경에서도 모듈은 import 가능."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any

TOPIC_PLAN = "/plan"
ACTION_NAV_TO_POSE = "/navigate_to_pose"
ACTION_FOLLOW_WAYPOINTS = "/follow_waypoints"
ODOM_FRESH_S = 1.0
# tf 프레임 이름 — sim 기본은 namespace=gogoping 가 붙음.
# 실물 / 다른 namespace 는 환경변수로 override (예: 그냥 "base_link").
TF_TARGET_FRAME = os.environ.get("PINGDER_WP_TF_TARGET", "gogoping/base_link")
TF_SOURCE_FRAME = os.environ.get("PINGDER_WP_TF_SOURCE", "map")
POSE_POLL_HZ = 5.0


@dataclass
class _OdomState:
    x: float; y: float; yaw: float
    received_at_s: float


@dataclass
class _PlanState:
    points: list[tuple[float, float]]
    received_at_s: float


class WaypointsRosBridge:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._odom: _OdomState | None = None
        self._plan: _PlanState | None = None
        self._goal: dict | None = None
        self._ros_ok = False
        self._nav_available = False
        self._spin_thread: threading.Thread | None = None
        self._node: Any = None
        self._executor: Any = None
        self._nav_client: Any = None
        self._patrol_client: Any = None
        self._sse_listeners: list[Any] = []
        self._tf_buffer: Any = None
        self._tf_listener: Any = None

    # ---------- lifecycle ----------
    def start(self) -> None:
        if "ROS_DOMAIN_ID" not in os.environ:
            raise RuntimeError(
                "ROS_DOMAIN_ID 환경변수가 설정되지 않았습니다. "
                "201~219 중 할당된 ID 를 사용하세요."
            )

        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.node import Node
        from rclpy.action import ActionClient
        from nav_msgs.msg import Path
        from nav2_msgs.action import NavigateToPose, FollowWaypoints
        from tf2_ros.buffer import Buffer
        from tf2_ros.transform_listener import TransformListener

        if not rclpy.ok():
            rclpy.init()

        node = Node("waypoints_bridge")

        def _on_plan(msg: Path) -> None:
            pts = [(float(ps.pose.position.x), float(ps.pose.position.y))
                   for ps in msg.poses]
            st = _PlanState(points=pts, received_at_s=time.monotonic())
            with self._lock:
                self._plan = st
            self._emit({"type": "plan", "points": pts})

        node.create_subscription(Path, TOPIC_PLAN, _on_plan, 10)

        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, node)
        node.create_timer(1.0 / POSE_POLL_HZ, self._tick_pose)

        self._nav_client = ActionClient(node, NavigateToPose, ACTION_NAV_TO_POSE)
        self._patrol_client = ActionClient(node, FollowWaypoints, ACTION_FOLLOW_WAYPOINTS)

        executor = SingleThreadedExecutor()
        executor.add_node(node)
        self._node = node
        self._executor = executor

        with self._lock:
            self._ros_ok = True

        def _probe() -> None:
            ok = self._nav_client.wait_for_server(timeout_sec=1.0)
            with self._lock:
                self._nav_available = ok

        t = threading.Thread(target=self._spin, name="waypoints-spin", daemon=True)
        self._spin_thread = t
        t.start()
        threading.Thread(target=_probe, name="waypoints-probe", daemon=True).start()

    def _spin(self) -> None:
        try:
            self._executor.spin()
        except Exception:
            pass

    def shutdown(self) -> None:
        try:
            if self._executor is not None:
                self._executor.shutdown()
            if self._node is not None:
                self._node.destroy_node()
        except Exception:
            pass

    def _tick_pose(self) -> None:
        """5Hz: lookup map→base_link from tf2, update internal odom state, emit SSE.

        transform 미가용 시 (nav2/AMCL 미실행, 또는 tf 초기화 전) 무시. odom_snapshot 은 None 반환."""
        import math
        import rclpy.time
        try:
            tx = self._tf_buffer.lookup_transform(
                TF_SOURCE_FRAME, TF_TARGET_FRAME, rclpy.time.Time()
            )
        except Exception:
            # TransformException 등 — 첫 몇 초간은 정상
            return
        x = float(tx.transform.translation.x)
        y = float(tx.transform.translation.y)
        q = tx.transform.rotation
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        yaw = float(math.atan2(siny, cosy))
        st = _OdomState(x=x, y=y, yaw=yaw, received_at_s=time.monotonic())
        with self._lock:
            self._odom = st
        self._emit({"type": "odom", "x": x, "y": y, "yaw": yaw})

    # ---------- public API ----------
    def odom_snapshot(self) -> tuple[float, float, float] | None:
        with self._lock:
            if self._odom is None:
                return None
            if time.monotonic() - self._odom.received_at_s > ODOM_FRESH_S:
                return None
            return (self._odom.x, self._odom.y, self._odom.yaw)

    def latest_plan(self) -> list[tuple[float, float]] | None:
        with self._lock:
            return None if self._plan is None else list(self._plan.points)

    def _build_pose_stamped(self, x: float, y: float, yaw: float):
        import math
        from geometry_msgs.msg import PoseStamped
        ps = PoseStamped()
        ps.header.frame_id = "map"
        ps.header.stamp = self._node.get_clock().now().to_msg()
        ps.pose.position.x = float(x)
        ps.pose.position.y = float(y)
        half = yaw / 2.0
        ps.pose.orientation.z = math.sin(half)
        ps.pose.orientation.w = math.cos(half)
        return ps

    def navigate_to_pose(self, x: float, y: float, yaw: float, goal_id: str) -> None:
        from nav2_msgs.action import NavigateToPose
        goal = NavigateToPose.Goal()
        goal.pose = self._build_pose_stamped(x, y, yaw)
        self._send_action(self._nav_client, goal, goal_id)

    def follow_waypoints(
        self, wps: list[tuple[float, float, float]], goal_id: str
    ) -> None:
        from nav2_msgs.action import FollowWaypoints
        goal = FollowWaypoints.Goal()
        goal.poses = [self._build_pose_stamped(x, y, yaw) for (x, y, yaw) in wps]
        self._send_action(self._patrol_client, goal, goal_id)

    def cancel_current(self) -> None:
        with self._lock:
            gh = (self._goal or {}).get("_handle")
        if gh is not None:
            gh.cancel_goal_async()

    def current_goal_status(self) -> dict:
        with self._lock:
            if not self._goal:
                return {"goal_id": None, "name": None, "status": "idle"}
            # _handle 은 외부에 노출 금지
            return {k: v for k, v in self._goal.items() if not k.startswith("_")}

    def health(self) -> dict:
        with self._lock:
            odom_age = (
                None if self._odom is None
                else int((time.monotonic() - self._odom.received_at_s) * 1000)
            )
            plan_age = (
                None if self._plan is None
                else int((time.monotonic() - self._plan.received_at_s) * 1000)
            )
            return {
                "ros_domain_id": int(os.environ.get("ROS_DOMAIN_ID", "0")),
                "ros_ok": self._ros_ok,
                "nav_action_available": self._nav_available,
                "odom_age_ms": odom_age,
                "plan_age_ms": plan_age,
            }

    # ---------- SSE listener 관리 ----------
    def register_listener(self, q: Any) -> None:
        with self._lock:
            self._sse_listeners.append(q)

    def unregister_listener(self, q: Any) -> None:
        with self._lock:
            try: self._sse_listeners.remove(q)
            except ValueError: pass

    def _emit(self, event: dict) -> None:
        with self._lock:
            listeners = list(self._sse_listeners)
        for q in listeners:
            try: q.put_nowait(event)
            except Exception: pass

    def _send_action(self, client, goal, goal_id: str) -> None:
        """공통 발송 + status 추적 + SSE emit."""
        with self._lock:
            self._goal = {"goal_id": goal_id, "name": None, "status": "pending",
                          "_handle": None}
        self._emit({"type": "goal_status", "goal_id": goal_id, "status": "pending"})

        future = client.send_goal_async(goal)

        def _on_response(fut) -> None:
            gh = fut.result()
            if not gh.accepted:
                with self._lock:
                    self._goal = {"goal_id": goal_id, "status": "rejected"}
                self._emit({"type": "goal_status", "goal_id": goal_id, "status": "rejected"})
                return
            with self._lock:
                self._goal["_handle"] = gh
                self._goal["status"] = "active"
            self._emit({"type": "goal_status", "goal_id": goal_id, "status": "active"})

            result_fut = gh.get_result_async()

            def _on_result(rf) -> None:
                from action_msgs.msg import GoalStatus
                status_map = {
                    GoalStatus.STATUS_SUCCEEDED: "succeeded",
                    GoalStatus.STATUS_CANCELED: "canceled",
                    GoalStatus.STATUS_ABORTED: "aborted",
                }
                status = status_map.get(rf.result().status, "unknown")
                with self._lock:
                    self._goal = {"goal_id": goal_id, "status": status}
                self._emit({"type": "goal_status", "goal_id": goal_id, "status": status})

            result_fut.add_done_callback(_on_result)

        future.add_done_callback(_on_response)
