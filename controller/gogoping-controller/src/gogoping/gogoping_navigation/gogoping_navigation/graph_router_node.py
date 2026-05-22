"""Graph Router ROS 노드.

- waypoints.yaml + lanes.yaml 로드 (ament_index 의 share/gogoping_navigation/config)
- TF map → gogoping/base_link 로 현재 로봇 위치 추적 (map 프레임).
  odom 토픽은 odom 프레임이라 waypoints 와 좌표계가 안 맞음 → nearest_vertex 가
  엉뚱한 출발 vertex 를 골라 우회 경로가 생기는 버그가 있었음.
- service /graph_router/route (RouteToVertex) — 시각화/디버깅용
- action  /graph_router/navigate_to_vertex (NavigateToVertex)
   → 다익스트라로 vertex sequence 계산
   → nav2 의 NavigateThroughPoses 액션 클라이언트로 위임
   → feedback 중계
   → **클라이언트 cancel** 시 nav2 goal 도 같이 cancel (BT_return_sub OneShot 의
     terminate(INVALID) 가 호출하는 cancel_goal_async 가 여기까지 forward 됨)
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from threading import Lock

import rclpy
from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateThroughPoses
from rclpy.action import ActionClient, ActionServer, CancelResponse
from rclpy.action.server import ServerGoalHandle
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.time import Time
from tf2_ros import Buffer, LookupException, TransformException, TransformListener

from std_msgs.msg import String
from std_srvs.srv import Trigger

from gogoping_msgs.action import NavigateToVertex
from gogoping_msgs.srv import RouteToVertex
from gogoping_navigation.graph import Graph


_DEBUG_TOPIC = "/gogoping/debug/nav_events"   # admin UI NavDebugLogCard 가 SSE 로 받음


class GraphRouterNode(Node):
    def __init__(self) -> None:
        super().__init__("graph_router_node")
        share = Path(get_package_share_directory("gogoping_navigation"))
        wp_path = Path(self.declare_parameter(
            "waypoints_yaml", str(share / "config" / "waypoints.yaml")
        ).value)
        lanes_path = Path(self.declare_parameter(
            "lanes_yaml", str(share / "config" / "lanes.yaml")
        ).value)
        self._frame_id = self.declare_parameter("frame_id", "map").value
        self._base_frame = self.declare_parameter(
            "base_frame", "gogoping/base_link"
        ).value
        self._follow_action = self.declare_parameter(
            "follow_action", "/navigate_through_poses"
        ).value
        # lane 보간 간격 (m). 인접 vertex 사이를 이 간격으로 잘라 NavigateThroughPoses 에
        # dense pose 시퀀스로 던짐 → nav2 planner 가 짧은 구간만 plan 해서 lane 거의 그대로 추종.
        # 0 또는 음수면 보간 비활성 (legacy: vertex pose 만 던짐).
        self._interp_step = float(self.declare_parameter(
            "lane_interpolation_step", 0.15
        ).value)

        # reload_graph 서비스가 동일 경로로 다시 로드할 수 있게 인스턴스에 보관
        self._wp_path = wp_path
        self._lanes_path = lanes_path
        self._graph = Graph.from_yaml(wp_path, lanes_path=lanes_path)
        self.get_logger().info(
            f"graph: {len(self._graph.vertices)} vertex, "
            f"{len(self._graph.lanes())} lane"
        )

        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)
        self._pose_lock = Lock()
        self._cur_xy: tuple[float, float] | None = None
        self._last_tf_warn_ns: int = 0

        cb = ReentrantCallbackGroup()
        self.create_timer(0.1, self._tick_tf, callback_group=cb)
        self.create_service(
            RouteToVertex, "/graph_router/route", self._srv_route,
            callback_group=cb,
        )
        # admin UI 가 yaml 편집 후 호출 — graph 를 in-place 로 다시 로드.
        # 진행 중 NavigateThroughPoses 는 이미 발행된 path 그대로 nav2 가 따라가고,
        # 다음 routing 부터 새 그래프 적용.
        self.create_service(
            Trigger, "/graph_router/reload_graph", self._srv_reload_graph,
            callback_group=cb,
        )
        self._nav_ac: ActionClient = ActionClient(
            self, NavigateThroughPoses, self._follow_action, callback_group=cb,
        )
        self._action_server = ActionServer(
            self,
            NavigateToVertex,
            "/graph_router/navigate_to_vertex",
            execute_callback=self._act_navigate,
            # 클라이언트 (BT) 가 cancel 요청 시 즉시 수락 — _act_navigate 의 polling 루프가
            # gh.is_cancel_requested 검출해서 nav2 goal 까지 forward cancel.
            cancel_callback=lambda _gh: CancelResponse.ACCEPT,
            callback_group=cb,
        )

        # admin UI NavDebugLogCard 가 SSE 로 받는 debug 이벤트 publisher
        self._debug_pub = self.create_publisher(String, _DEBUG_TOPIC, 20)

    def _dbg(self, msg: str, level: str = "info") -> None:
        try:
            payload = {
                "ts": time.time(),
                "source": "graph_rt",
                "level": level,
                "msg": msg,
            }
            out = String()
            out.data = json.dumps(payload, ensure_ascii=False)
            self._debug_pub.publish(out)
        except Exception:
            pass

    # ──────── TF map → base_link ────────
    def _tick_tf(self) -> None:
        try:
            tf = self._tf_buffer.lookup_transform(
                self._frame_id, self._base_frame,
                Time(), timeout=Duration(seconds=0.0),
            )
        except (LookupException, TransformException):
            now_ns = self.get_clock().now().nanoseconds
            # 5 초마다 1회 경고 (TF 가 아직 안 떠있는 케이스 — 정상)
            if now_ns - self._last_tf_warn_ns > 5_000_000_000:
                self._last_tf_warn_ns = now_ns
                self.get_logger().warn(
                    f"TF {self._frame_id} → {self._base_frame} 아직 없음"
                )
            return
        with self._pose_lock:
            self._cur_xy = (
                tf.transform.translation.x,
                tf.transform.translation.y,
            )

    def _current_xy(self) -> tuple[float, float] | None:
        with self._pose_lock:
            return self._cur_xy

    # ──────── service: route ────────
    def _srv_route(
        self, req: RouteToVertex.Request, res: RouteToVertex.Response
    ) -> RouteToVertex.Response:
        target = req.target_name
        # request.start 가 (0,0,0) 이면 TF map → base_link 현재 위치 사용
        if req.start.x == 0.0 and req.start.y == 0.0:
            cur = self._current_xy()
            if cur is None:
                res.success = False
                res.message = "no tf map→base_link yet, pass non-zero start"
                return res
            sx, sy = cur
        else:
            sx, sy = req.start.x, req.start.y

        try:
            src = self._graph.nearest_vertex(sx, sy)
            seq = self._graph.route(src, target)
        except Exception as e:
            res.success = False
            res.message = str(e)
            return res

        res.success = True
        res.message = ""
        res.vertex_sequence = list(seq)
        # 총 거리
        total = 0.0
        for a, b in zip(seq[:-1], seq[1:]):
            va, vb = self._graph.vertices[a], self._graph.vertices[b]
            total += math.hypot(va.x - vb.x, va.y - vb.y)
        res.total_distance_m = float(total)
        return res

    # ──────── action: navigate_to_vertex ────────
    def _act_navigate(
        self, gh: ServerGoalHandle
    ) -> NavigateToVertex.Result:
        """graph_router 의 NavigateToVertex action 처리 — **sync**.

        과거 async 패턴을 썼지만 rclpy ActionServer + MultiThreadedExecutor 환경에선
        running asyncio event loop 가 없어서 ``await asyncio.sleep`` 이 즉시
        ``RuntimeError: no running event loop`` 으로 깨졌음. nav2 goal accepted 직후
        polling 진입과 동시에 종료 → nav_gh 가 orphan → nav2 controller 가 cmd_vel
        계속 publish (좀비). 따라서 **동기 polling + time.sleep** 으로 변환.

        ⚠️ nav_gh 가 nav2 에 보내진 후 어떤 종료 경로에서도 cancel 을 forward 해야
        nav2 controller_server 가 cmd_vel publish 를 멈춤. try/finally 의 safety net
        이 핵심.

        호출 thread: MultiThreadedExecutor + ReentrantCallbackGroup — 본 함수가 polling
        으로 thread 를 block 해도 다른 callback (cancel_callback / TF / 다른 service)
        은 별도 thread 에서 정상 동작.

        모든 abort 경로에 admin UI NavDebugLogCard 용 event publish.
        """
        target = gh.request.target_name
        result = NavigateToVertex.Result()
        nav_gh = None
        self._dbg(f"act_navigate start (target={target!r})")

        cur = self._current_xy()
        if cur is None:
            gh.abort()
            result.success = False
            result.message = "no tf map→base_link yet"
            self._dbg("abort: no tf map→base_link yet", level="warn")
            return result

        try:
            src = self._graph.nearest_vertex(*cur)
            seq = self._graph.route(src, target)
        except Exception as e:
            gh.abort()
            result.success = False
            result.message = str(e)
            self._dbg(f"abort: graph error {e}", level="err")
            return result

        # vertex sequence → PoseStamped 리스트 (lane 보간 적용)
        poses = self._build_dense_poses(seq)

        # nav2 FollowWaypoints 호출
        if not self._nav_ac.wait_for_server(timeout_sec=2.0):
            gh.abort()
            result.success = False
            result.message = f"nav2 action server '{self._follow_action}' not available"
            self._dbg(
                f"abort: nav2 server '{self._follow_action}' unavailable",
                level="err",
            )
            return result

        nav_goal = NavigateThroughPoses.Goal()
        nav_goal.poses = poses

        last_idx = 0

        def _on_nav_feedback(_fb_msg) -> None:
            """NavigateThroughPoses 의 feedback 에는 current_waypoint 없음.
            odom 으로 sequence 안 nearest vertex 인덱스 추정."""
            nonlocal last_idx
            cur = self._current_xy()
            if cur is None:
                return
            cx, cy = cur
            best_i, best_d = last_idx, float("inf")
            for i, name in enumerate(seq):
                v = self._graph.vertices[name]
                d = (v.x - cx) ** 2 + (v.y - cy) ** 2
                if d < best_d:
                    best_d, best_i = d, i
            # 단조 증가 — 뒤로 안 감
            if best_i >= last_idx:
                last_idx = best_i
            self._publish_feedback(gh, seq, last_idx)

        # ★ safety net — nav_gh 가 만들어지면 어떤 종료 경로에서도 cancel forward 보장
        try:
            send_future = self._nav_ac.send_goal_async(
                nav_goal, feedback_callback=_on_nav_feedback
            )
            # send_future 동기 대기 — 5s timeout 안 오면 abort
            send_deadline = time.monotonic() + 5.0
            while not send_future.done():
                if gh.is_cancel_requested:
                    gh.canceled()
                    result.success = False
                    result.message = "canceled before send completed"
                    self._dbg("canceled before send completed", level="warn")
                    return result
                if time.monotonic() > send_deadline:
                    gh.abort()
                    result.success = False
                    result.message = "send_goal_async timeout"
                    self._dbg("abort: send_goal_async timeout", level="err")
                    return result
                time.sleep(0.01)

            nav_gh = send_future.result()
            if not nav_gh.accepted:
                nav_gh = None   # 어차피 active 아님 → finally cancel skip
                gh.abort()
                result.success = False
                result.message = "nav2 rejected goal"
                self._dbg("abort: nav2 rejected goal", level="warn")
                return result

            self._dbg(f"nav2 goal accepted ({len(poses)} poses)")

            # 최종 결과 대기 — polling 으로 클라이언트 cancel request 검출.
            get_result_future = nav_gh.get_result_async()
            while not get_result_future.done():
                if gh.is_cancel_requested:
                    self.get_logger().info(
                        "navigate_to_vertex: client cancel → nav2 NavigateThroughPoses cancel"
                    )
                    self._dbg(
                        f"client cancel → nav2 cancel (target={target!r}, "
                        f"reached_idx={last_idx}/{len(seq)-1})",
                        level="warn",
                    )
                    try:
                        cancel_future = nav_gh.cancel_goal_async()
                        # cancel_future 도 짧게 동기 대기 (2s) — nav2 ack 보장
                        cancel_deadline = time.monotonic() + 2.0
                        while not cancel_future.done():
                            if time.monotonic() > cancel_deadline:
                                self._dbg(
                                    "nav2 cancel ack timeout — proceed anyway",
                                    level="warn",
                                )
                                break
                            time.sleep(0.02)
                        if cancel_future.done():
                            self._dbg(f"nav2 cancel ack (target={target!r})")
                    except Exception as e:
                        self.get_logger().warning(f"nav2 cancel failed: {e}")
                        self._dbg(f"nav2 cancel FAILED: {e}", level="err")
                    nav_gh = None   # 명시 cancel — finally 가 중복 cancel 안 하게
                    gh.canceled()
                    result.success = False
                    result.message = "canceled by client"
                    result.final_vertex = seq[last_idx] if last_idx < len(seq) else ""
                    return result
                time.sleep(0.05)

            wrapper = get_result_future.result()
            # action_msgs/GoalStatus: 4=SUCCEEDED — nav2 자체가 종료한 상태라 nav_gh 도 끝남
            nav_gh = None   # 정상 종료 — finally cancel skip
            succeeded = wrapper.status == 4

            if not succeeded:
                gh.abort()
                result.success = False
                result.message = f"nav2 status={wrapper.status}"
                result.final_vertex = seq[last_idx] if last_idx < len(seq) else target
                self._dbg(f"abort: nav2 status={wrapper.status}", level="warn")
                return result

            gh.succeed()
            result.success = True
            result.message = ""
            result.final_vertex = target
            self._dbg(f"SUCCESS (target={target!r})")
            return result

        except Exception as e:
            # polling 중 일반 예외 — nav_gh 가 살아있으면 orphan 방지 위해 cancel
            # RcutilsLogger 는 .exception 메서드 없음 — .error 로 traceback 직접 format
            import traceback
            self.get_logger().error(
                f"navigate_to_vertex exception: {e}\n{traceback.format_exc()}"
            )
            self._dbg(f"abort: exception {type(e).__name__}: {e}", level="err")
            try:
                gh.abort()
            except Exception:
                pass
            result.success = False
            result.message = f"exception: {e}"
            return result
        finally:
            # ★ safety net — nav_gh 가 active 상태로 살아남으면 nav2 controller 가
            # cmd_vel 을 계속 publish 하는 좀비 bug. 어떤 종료 경로에서도 cancel forward.
            if nav_gh is not None:
                try:
                    nav_gh.cancel_goal_async()
                    self._dbg(
                        f"orphan nav_gh canceled in finally (target={target!r})",
                        level="err",
                    )
                except Exception as e:
                    self.get_logger().warning(f"orphan cancel failed: {e}")
                    self._dbg(f"orphan cancel FAILED: {e}", level="err")

    # ──────── service: reload_graph ────────
    def _srv_reload_graph(
        self, req: Trigger.Request, res: Trigger.Response
    ) -> Trigger.Response:
        try:
            new_graph = Graph.from_yaml(self._wp_path, lanes_path=self._lanes_path)
        except Exception as e:
            res.success = False
            res.message = f"reload failed: {e}"
            return res
        self._graph = new_graph
        n_v = len(self._graph.vertices)
        n_l = len(self._graph.lanes())
        self.get_logger().info(f"graph reloaded: {n_v} vertex, {n_l} lane")
        res.success = True
        res.message = f"reloaded — {n_v} vertices, {n_l} lanes"
        return res

    def _make_pose(self, x: float, y: float, yaw: float) -> PoseStamped:
        ps = PoseStamped()
        ps.header.frame_id = self._frame_id
        ps.header.stamp = self.get_clock().now().to_msg()
        ps.pose.position.x = float(x)
        ps.pose.position.y = float(y)
        ps.pose.orientation.z = float(math.sin(yaw / 2.0))
        ps.pose.orientation.w = float(math.cos(yaw / 2.0))
        return ps

    def _build_dense_poses(self, seq: list[str]) -> list[PoseStamped]:
        """vertex sequence → dense PoseStamped 리스트.

        인접 vertex (A,B) 사이를 직선으로 가정하고 ``self._interp_step`` 간격으로 잘라
        중간 pose 를 삽입. 중간 pose 의 yaw 는 A→B 진행방향 (atan2(dy,dx)),
        도착 vertex 의 yaw 는 waypoints.yaml 에 정의된 값 그대로.

        보간을 끄려면 ``lane_interpolation_step`` 을 0 이하로.

        lane 이 비직선 (코너) 인 경우 중간점이 벽 통과할 수 있으니, 그 lane 은
        waypoints.yaml 에 중간 vertex 를 명시적으로 추가해서 직선 구간으로 쪼개야 함.
        """
        poses: list[PoseStamped] = []
        if len(seq) == 0:
            return poses
        if self._interp_step <= 0.0:
            # legacy — vertex 만
            for name in seq:
                v = self._graph.vertices[name]
                poses.append(self._make_pose(v.x, v.y, v.yaw))
            return poses

        for i in range(len(seq) - 1):
            v = self._graph.vertices[seq[i]]
            v_next = self._graph.vertices[seq[i + 1]]
            dx = v_next.x - v.x
            dy = v_next.y - v.y
            dist = math.hypot(dx, dy)
            seg_yaw = math.atan2(dy, dx)
            n_steps = max(1, int(math.ceil(dist / self._interp_step)))
            for k in range(n_steps):
                t = k / n_steps
                poses.append(self._make_pose(
                    v.x + dx * t, v.y + dy * t, seg_yaw,
                ))
        # 도착 vertex 는 자체 yaw 보존
        last = self._graph.vertices[seq[-1]]
        poses.append(self._make_pose(last.x, last.y, last.yaw))
        return poses

    def _publish_feedback(
        self, gh: ServerGoalHandle, seq: list[str], idx: int
    ) -> None:
        idx = max(0, min(len(seq) - 1, idx))
        fb = NavigateToVertex.Feedback()
        fb.current_vertex = seq[idx]
        fb.sequence_index = int(idx)
        fb.sequence_total = len(seq)
        fb.progress = float(idx) / max(1, len(seq) - 1)
        gh.publish_feedback(fb)


def main() -> None:
    rclpy.init()
    node = GraphRouterNode()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
