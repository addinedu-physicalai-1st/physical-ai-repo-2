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
TOPIC_INITIAL_POSE = "/initialpose"
ACTION_NAV_TO_POSE = "/navigate_to_pose"
ACTION_FOLLOW_WAYPOINTS = "/follow_waypoints"
SRV_GRAPH_ROUTE = "/graph_router/route"
ACTION_GRAPH_NAVIGATE = "/graph_router/navigate_to_vertex"
ODOM_FRESH_S = 1.0
# 자가 회복 — nav action server 연결 polling 주기
RECONNECT_INTERVAL_S = 5.0
# 호출 시점 ready 체크 timeout (server_is_ready 후 wait_for_server)
CALL_READY_TIMEOUT_S = 1.0
# send_goal_async future timeout — 이 시간 안에 accept 응답 없으면 reject
GOAL_ACCEPT_TIMEOUT_S = 5.0
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
        self._initial_pose_pub: Any = None
        self._route_client: Any = None
        self._gr_nav_client: Any = None
        self._sse_listeners: list[Any] = []
        self._tf_buffer: Any = None
        self._tf_listener: Any = None
        # 자가 회복용 백그라운드 스레드 제어
        self._reconnect_thread: threading.Thread | None = None
        self._stop_evt = threading.Event()

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
        from geometry_msgs.msg import PoseWithCovarianceStamped
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
        # AMCL 초기 위치 재설정용 — admin-ui 의 "2D Pose Estimate" (Shift+drag).
        self._initial_pose_pub = node.create_publisher(
            PoseWithCovarianceStamped, TOPIC_INITIAL_POSE, 10,
        )
        try:
            from gogoping_msgs.srv import RouteToVertex
            from gogoping_msgs.action import NavigateToVertex
            self._route_client = node.create_client(RouteToVertex, SRV_GRAPH_ROUTE)
            self._gr_nav_client = ActionClient(node, NavigateToVertex, ACTION_GRAPH_NAVIGATE)
        except Exception as e:
            # gogoping_msgs 빌드 안 됐을 수도 — graph routing 만 비활성, 다른 기능은 동작
            node.get_logger().warn(f"graph router clients unavailable: {e}")

        executor = SingleThreadedExecutor()
        executor.add_node(node)
        self._node = node
        self._executor = executor

        with self._lock:
            self._ros_ok = True

        node.get_logger().info("waypoints_bridge started — nav action self-heal active")

        t = threading.Thread(target=self._spin, name="waypoints-spin", daemon=True)
        self._spin_thread = t
        t.start()
        # 백그라운드 자가 회복 — nav action 연결 polling + 자동 재연결
        self._stop_evt.clear()
        self._reconnect_thread = threading.Thread(
            target=self._reconnect_loop, name="waypoints-reconnect", daemon=True,
        )
        self._reconnect_thread.start()

    def _reconnect_loop(self) -> None:
        """nav action server 가용성 주기 polling.
        - 연결 안 되어 있으면 wait_for_server 로 재연결 시도
        - 연결되어 있다 끊기면 다음 사이클에서 감지 → 재연결
        - 변화 시 ROS log 에 기록
        """
        while not self._stop_evt.is_set():
            try:
                with self._lock:
                    was_available = self._nav_available
                    node = self._node
                if node is None:
                    self._stop_evt.wait(RECONNECT_INTERVAL_S)
                    continue

                if not was_available:
                    # 끊긴 상태 — 재연결 시도
                    ok = self._nav_client.wait_for_server(timeout_sec=2.0)
                    with self._lock:
                        self._nav_available = ok
                    if ok:
                        node.get_logger().info("nav action server connected")
                else:
                    # 연결 상태 — 즉시 ready 체크 (graph 변동 감지)
                    still_ok = self._nav_client.server_is_ready()
                    with self._lock:
                        self._nav_available = still_ok
                    if not still_ok:
                        node.get_logger().warn(
                            "nav action server lost — will retry in next cycle"
                        )
            except Exception as e:
                if self._node is not None:
                    self._node.get_logger().error(f"reconnect loop error: {e}")
            self._stop_evt.wait(RECONNECT_INTERVAL_S)

    def _spin(self) -> None:
        try:
            self._executor.spin()
        except Exception:
            pass

    def shutdown(self) -> None:
        # 백그라운드 자가 회복 루프 정리 먼저
        self._stop_evt.set()
        if self._reconnect_thread is not None:
            self._reconnect_thread.join(timeout=1.0)
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

    def _ensure_action_ready(self, client: Any, kind: str, goal_id: str) -> bool:
        """호출 시점에 action server ready 체크 + 1초 wait. 안 되면 SSE reject 발행."""
        if client.server_is_ready():
            return True
        if self._node is not None:
            self._node.get_logger().warn(
                f"{kind} action server not ready — wait {CALL_READY_TIMEOUT_S}s"
            )
        ok = client.wait_for_server(timeout_sec=CALL_READY_TIMEOUT_S)
        with self._lock:
            self._nav_available = ok
        if not ok:
            if self._node is not None:
                self._node.get_logger().error(
                    f"{kind} action server unavailable — goal {goal_id} rejected"
                )
            self._emit({
                "type": "goal_status", "goal_id": goal_id, "status": "rejected",
                "reason": f"{kind}_action_server_unavailable",
            })
        return ok

    def navigate_to_pose(self, x: float, y: float, yaw: float, goal_id: str) -> None:
        from nav2_msgs.action import NavigateToPose
        if not self._ensure_action_ready(self._nav_client, "navigate_to_pose", goal_id):
            return
        goal = NavigateToPose.Goal()
        goal.pose = self._build_pose_stamped(x, y, yaw)
        self._send_action(self._nav_client, goal, goal_id)

    def follow_waypoints(
        self, wps: list[tuple[float, float, float]], goal_id: str
    ) -> None:
        from nav2_msgs.action import FollowWaypoints
        if not self._ensure_action_ready(self._patrol_client, "follow_waypoints", goal_id):
            return
        goal = FollowWaypoints.Goal()
        goal.poses = [self._build_pose_stamped(x, y, yaw) for (x, y, yaw) in wps]
        self._send_action(self._patrol_client, goal, goal_id)

    def route_to(
        self, target_name: str, timeout_s: float = 2.0
    ) -> dict:
        """동기 service 호출 — 다익스트라 결과 반환. 로봇 안 움직임."""
        if self._route_client is None:
            return {"success": False, "message": "graph_router clients unavailable",
                    "vertex_sequence": [], "total_distance_m": 0.0}
        from gogoping_msgs.srv import RouteToVertex
        req = RouteToVertex.Request()
        req.target_name = target_name
        # start (0,0,0) 으로 두면 graph_router_node 가 현재 odom 사용
        if not self._route_client.wait_for_service(timeout_sec=timeout_s):
            return {"success": False, "message": "service unavailable",
                    "vertex_sequence": [], "total_distance_m": 0.0}
        future = self._route_client.call_async(req)
        # spin 은 별도 thread — 결과 polling
        deadline = time.monotonic() + timeout_s
        while not future.done() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not future.done():
            return {"success": False, "message": "service timeout",
                    "vertex_sequence": [], "total_distance_m": 0.0}
        res = future.result()
        return {
            "success": bool(res.success),
            "message": str(res.message),
            "vertex_sequence": list(res.vertex_sequence),
            "total_distance_m": float(res.total_distance_m),
        }

    def navigate_to_vertex(self, target_name: str, goal_id: str) -> None:
        """graph_router action 호출 → 다익스트라 + nav2 위임. feedback SSE 로 emit.
        진행 중 goal 이 있으면 먼저 cancel — 새 명령이 이전 명령을 대체."""
        if self._gr_nav_client is None:
            self._emit({"type": "goal_status", "goal_id": goal_id,
                        "status": "rejected", "reason": "graph_router unavailable"})
            return
        # 이전 goal cancel (best effort, 비동기). 새 goal 즉시 진행.
        self.cancel_current()
        from gogoping_msgs.action import NavigateToVertex
        goal = NavigateToVertex.Goal()
        goal.target_name = target_name
        self._send_action(self._gr_nav_client, goal, goal_id, name=target_name,
                          feedback_emit=True)

    def cancel_current(self) -> None:
        with self._lock:
            gh = (self._goal or {}).get("_handle")
        if gh is not None:
            gh.cancel_goal_async()

    def set_initial_pose(self, x: float, y: float, yaw: float) -> None:
        """AMCL 초기 위치 재설정 — /initialpose 토픽에 PoseWithCovarianceStamped 발행.
        RViz 의 '2D Pose Estimate' 버튼과 동일 동작. 로봇은 안 움직이고 AMCL 의
        파티클이 (x, y, yaw) 근처로 재샘플링되어 위치 추정이 회복됨."""
        import math
        from geometry_msgs.msg import PoseWithCovarianceStamped
        if self._node is None:
            return  # rclpy 미시작 — 무시
        if self._initial_pose_pub is None:
            # Lazy init — uvicorn --reload 시 start() 가 재실행 안 되어
            # _initial_pose_pub 가 None 으로 남아있는 케이스 처리.
            self._initial_pose_pub = self._node.create_publisher(
                PoseWithCovarianceStamped, TOPIC_INITIAL_POSE, 10,
            )
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = "map"
        msg.header.stamp = self._node.get_clock().now().to_msg()
        msg.pose.pose.position.x = float(x)
        msg.pose.pose.position.y = float(y)
        half = yaw / 2.0
        msg.pose.pose.orientation.z = math.sin(half)
        msg.pose.pose.orientation.w = math.cos(half)
        # 6x6 covariance — RViz 의 기본값 (대각만, x/y/yaw)
        cov = [0.0] * 36
        cov[0]  = 0.25  # x  σ²
        cov[7]  = 0.25  # y  σ²
        cov[35] = 0.0685389  # yaw σ² (≈ π/12 = 15°)
        msg.pose.covariance = cov
        self._initial_pose_pub.publish(msg)

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

    def _send_action(
        self, client, goal, goal_id: str,
        name: str | None = None, feedback_emit: bool = False,
    ) -> None:
        """공통 발송 + status 추적 + SSE emit + 자가 회복 보호.
        feedback_emit=True 면 action 의 feedback 메시지를 SSE 로 중계 (NavigateToVertex 용)."""
        with self._lock:
            self._goal = {"goal_id": goal_id, "name": name, "status": "pending",
                          "_handle": None, "_sent_at": time.monotonic()}
        self._emit({"type": "goal_status", "goal_id": goal_id, "status": "pending",
                    "name": name})

        if self._node is not None:
            self._node.get_logger().info(f"goal {goal_id} sent")

        def _on_fb(fb_msg) -> None:
            fb = fb_msg.feedback
            payload = {"type": "route_progress", "goal_id": goal_id}
            for k in ("current_vertex", "sequence_index", "sequence_total", "progress"):
                if hasattr(fb, k):
                    v = getattr(fb, k)
                    payload[k] = (
                        float(v) if isinstance(v, float)
                        else int(v) if isinstance(v, int)
                        else str(v)
                    )
            self._emit(payload)

        future = client.send_goal_async(
            goal, feedback_callback=_on_fb if feedback_emit else None
        )

        def _on_response(fut) -> None:
            try:
                gh = fut.result()
            except Exception as e:
                if self._node is not None:
                    self._node.get_logger().error(
                        f"goal {goal_id} send_goal_async failed: {e}"
                    )
                with self._lock:
                    self._goal = {"goal_id": goal_id, "status": "rejected"}
                self._emit({
                    "type": "goal_status", "goal_id": goal_id,
                    "status": "rejected", "reason": str(e),
                })
                return
            if gh is None or not gh.accepted:
                with self._lock:
                    self._goal = {"goal_id": goal_id, "status": "rejected"}
                self._emit({
                    "type": "goal_status", "goal_id": goal_id,
                    "status": "rejected", "reason": "server_rejected",
                })
                if self._node is not None:
                    self._node.get_logger().warn(f"goal {goal_id} rejected by server")
                return
            with self._lock:
                self._goal["_handle"] = gh
                self._goal["status"] = "active"
            self._emit({"type": "goal_status", "goal_id": goal_id, "status": "active"})
            if self._node is not None:
                self._node.get_logger().info(f"goal {goal_id} accepted, executing")

            result_fut = gh.get_result_async()

            def _on_result(rf) -> None:
                from action_msgs.msg import GoalStatus
                status_map = {
                    GoalStatus.STATUS_SUCCEEDED: "succeeded",
                    GoalStatus.STATUS_CANCELED: "canceled",
                    GoalStatus.STATUS_ABORTED: "aborted",
                }
                try:
                    status = status_map.get(rf.result().status, "unknown")
                except Exception as e:
                    status = "unknown"
                    if self._node is not None:
                        self._node.get_logger().error(
                            f"goal {goal_id} get_result failed: {e}"
                        )
                with self._lock:
                    self._goal = {"goal_id": goal_id, "status": status}
                self._emit({"type": "goal_status", "goal_id": goal_id, "status": status})
                if self._node is not None:
                    self._node.get_logger().info(f"goal {goal_id} → {status}")

            result_fut.add_done_callback(_on_result)

        future.add_done_callback(_on_response)
