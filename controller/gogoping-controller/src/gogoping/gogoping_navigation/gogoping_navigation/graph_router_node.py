"""Graph Router ROS 노드.

- waypoints.yaml + lanes.yaml 로드 (ament_index 의 share/gogoping_navigation/config)
- TF map → gogoping/base_link 로 현재 로봇 위치 추적 (map 프레임).
  odom 토픽은 odom 프레임이라 waypoints 와 좌표계가 안 맞음 → nearest_vertex 가
  엉뚱한 출발 vertex 를 골라 우회 경로가 생기는 버그가 있었음.
- service /graph_router/route (RouteToVertex) — 시각화/디버깅용
- action  /graph_router/navigate_to_vertex (NavigateToVertex)
   → 다익스트라로 vertex sequence 계산 (L1)
   → vertex 단위로 nav2 의 NavigateToPose 를 chain 호출 (L2 — segment 단위 위임)
   → segment 끝날 때마다 feedback publish (last_idx 갱신)
   → **클라이언트 cancel** 시 현재 segment 의 nav2 goal 을 cancel + sequence 중단
     (BT_return_sub OneShot 의 terminate(INVALID) 가 호출하는 cancel_goal_async
      가 여기까지 forward 됨)
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
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Path as NavPath  # pathlib.Path 와 충돌 방지
from rclpy.action import ActionClient, ActionServer, CancelResponse
from rclpy.action.server import ServerGoalHandle
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from tf2_ros import Buffer, LookupException, TransformException, TransformListener

from std_msgs.msg import String
from std_srvs.srv import Trigger

from gogoping_msgs.action import NavigateToVertex
from gogoping_msgs.srv import RouteToVertex
from gogoping_navigation.graph import Graph


_DEBUG_TOPIC = "/gogoping/debug/nav_events"   # admin UI NavDebugLogCard 가 SSE 로 받음
_ROUTE_PATH_TOPIC = "/graph_router/route_path"  # RViz Path display — L1 vertex sequence 시각화

# action_msgs/GoalStatus — admin UI 에 raw int 대신 사람 말로 표시.
# (STATUS_UNKNOWN=0 / ACCEPTED=1 / EXECUTING=2 / CANCELING=3 / SUCCEEDED=4 / CANCELED=5 / ABORTED=6)
_NAV2_STATUS_NAME = {
    0: "UNKNOWN",
    1: "ACCEPTED",
    2: "EXECUTING",
    3: "CANCELING",
    4: "SUCCEEDED",
    5: "CANCELED",
    6: "ABORTED",
}


def _nav2_status_str(status: int) -> str:
    name = _NAV2_STATUS_NAME.get(int(status))
    return f"{name}({status})" if name else f"UNKNOWN({status})"


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
            "follow_action", "/navigate_to_pose"
        ).value
        # preempt next-goal — 현재 segment target 까지의 거리가 이 값 이하면 다음 vertex
        # goal 을 미리 발사해 nav2 BT 가 자동 preempt 하게 함 → vertex 마다 robot 이 정지
        # 안 함 (cmd_vel 끊김 없이 다음 segment 로 전이).  0 이면 비활성 (legacy SUCCESS 대기).
        # 마지막 segment 는 preempt 안 함 (최종 도착 정밀도 보존).
        self._preempt_distance = float(self.declare_parameter(
            "preempt_distance", 0.5
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
        # 진행 중인 segment 는 이미 발행된 nav2 NavigateToPose goal 로 계속 진행되고,
        # 다음 segment (또는 다음 routing) 부터 새 그래프 적용.
        self.create_service(
            Trigger, "/graph_router/reload_graph", self._srv_reload_graph,
            callback_group=cb,
        )
        self._nav_ac: ActionClient = ActionClient(
            self, NavigateToPose, self._follow_action, callback_group=cb,
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

        # L1 vertex sequence (다익스트라 결과) 를 nav_msgs/Path 로 RViz 가 볼 수 있게 publish.
        # 액션 발사 시점에 1회만 publish — TRANSIENT_LOCAL latching 으로 RViz 가 늦게 붙어도
        # 최신 path 즉시 수신. 종료 시 빈 Path 로 clear.
        self._route_path_pub = self.create_publisher(
            NavPath,
            _ROUTE_PATH_TOPIC,
            QoSProfile(
                depth=1,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
                reliability=ReliabilityPolicy.RELIABLE,
            ),
        )

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

    def _publish_route_path(self, seq: list[str]) -> None:
        """L1 vertex sequence → nav_msgs/Path publish (RViz Path display 용).

        TRANSIENT_LOCAL latched — 후속 RViz 구독자도 최신 path 즉시 수신.
        빈 list 면 빈 Path 발행 (clear).
        """
        try:
            path = NavPath()
            path.header.frame_id = self._frame_id
            path.header.stamp = self.get_clock().now().to_msg()
            for name in seq:
                v = self._graph.vertices.get(name)
                if v is None:
                    continue
                path.poses.append(self._make_pose(v.x, v.y, v.yaw))
            self._route_path_pub.publish(path)
        except Exception as e:
            self._dbg(f"route_path publish 실패: {e}", level="warn")

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
        """thin wrapper — 도착/실패/취소 모두 RViz 의 파란 L1 path 를 비워줌."""
        try:
            return self._act_navigate_impl(gh)
        finally:
            # 빈 Path publish → TRANSIENT_LOCAL latched 상태 clear → RViz 파란선 사라짐
            self._publish_route_path([])

    def _act_navigate_impl(
        self, gh: ServerGoalHandle
    ) -> NavigateToVertex.Result:
        """graph_router 의 NavigateToVertex action 처리 — **sync polling chain**.

        L1 (다익스트라 vertex sequence) + L2 (Nav2 segment 단위 NavigateToPose).
        매 vertex 마다 NavigateToPose.Goal 하나 보내고 sync polling 으로 결과 대기.

        cancel chain 함정 3개 (nav-cancel-chain.md):
          1. NavTo race      — caller 측 책임 (외층 BT). 여기 무관.
          2. state change    — 외층 BT 책임. 여기 무관.
          3. async + orphan  — sync polling + try/finally safety net 으로 회피.
                                각 iteration 별로 nav_gh 살아있으면 cancel 보장.

        호출 thread: MultiThreadedExecutor + ReentrantCallbackGroup — 본 함수가
        polling 으로 thread 를 block 해도 cancel_callback / TF tick 등 다른 콜백은
        별도 thread 에서 정상 동작.

        모든 abort 경로에 admin UI NavDebugLogCard 용 event publish.
        """
        target = gh.request.target_name
        result = NavigateToVertex.Result()

        target_v = self._graph.vertices.get(target) if hasattr(self._graph, "vertices") else None
        if target_v is not None:
            self._dbg(
                f"act_navigate start target={target!r} xy=({target_v.x:.2f}, {target_v.y:.2f})"
            )
        else:
            self._dbg(f"act_navigate start target={target!r}")

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

        # L1 sequence 시각화 — RViz Path display 용 (액션 1회당 1번 publish).
        self._publish_route_path(seq)

        if not self._nav_ac.wait_for_server(timeout_sec=2.0):
            gh.abort()
            result.success = False
            result.message = f"nav2 action server '{self._follow_action}' not available"
            self._dbg(
                f"abort: nav2 server '{self._follow_action}' unavailable",
                level="err",
            )
            return result

        # 첫 vertex (src) 는 현재 위치이므로 skip — seq[1:] 부터 segment 별 nav.
        # seq 가 1개 (src == target) 면 즉시 SUCCESS.
        if len(seq) <= 1:
            gh.succeed()
            result.success = True
            result.message = "already at target"
            result.final_vertex = target
            self._dbg(f"SUCCESS (already at target={target!r})")
            return result

        last_idx = 0
        self._publish_feedback(gh, seq, last_idx)

        for i in range(1, len(seq)):
            segment_target = seq[i]
            nav_gh = None
            try:
                nav_goal = NavigateToPose.Goal()
                nav_goal.pose = self._vertex_pose(segment_target)

                self._dbg(
                    f"segment {i}/{len(seq)-1} → {segment_target!r}"
                )

                send_future = self._nav_ac.send_goal_async(nav_goal)
                send_deadline = time.monotonic() + 5.0
                while not send_future.done():
                    if gh.is_cancel_requested:
                        gh.canceled()
                        result.success = False
                        result.message = "canceled before send completed"
                        result.final_vertex = seq[last_idx]
                        self._dbg(
                            f"canceled before send completed (segment {i})",
                            level="warn",
                        )
                        return result
                    if time.monotonic() > send_deadline:
                        gh.abort()
                        result.success = False
                        result.message = f"send_goal_async timeout (segment {i})"
                        result.final_vertex = seq[last_idx]
                        self._dbg(f"abort: send timeout (segment {i})", level="err")
                        return result
                    time.sleep(0.01)

                nav_gh = send_future.result()
                if not nav_gh.accepted:
                    nav_gh = None
                    gh.abort()
                    result.success = False
                    result.message = f"nav2 rejected goal (segment {i} → {segment_target!r})"
                    result.final_vertex = seq[last_idx]
                    self._dbg(
                        f"abort: nav2 rejected (segment {i} → {segment_target!r})",
                        level="warn",
                    )
                    return result

                get_result_future = nav_gh.get_result_async()
                # preempt next-goal — 마지막 segment 가 아니고 preempt 활성이면
                # 현재 segment target 거리 검사 후 도착 직전에 미리 다음 iter 로 break.
                is_last_segment = (i == len(seq) - 1)
                preempt_active = (self._preempt_distance > 0.0 and not is_last_segment)
                preempted = False
                while not get_result_future.done():
                    if preempt_active:
                        cur_xy = self._current_xy()
                        if cur_xy is not None:
                            tv = self._graph.vertices[segment_target]
                            d = math.hypot(cur_xy[0] - tv.x, cur_xy[1] - tv.y)
                            if d <= self._preempt_distance:
                                # 다음 vertex goal 미리 발사 — nav2 가 자동 preempt
                                # 현재 nav_gh 의 result_future 는 CANCELED 로 해결될 예정.
                                # 명시 cancel 하지 않음 (cmd_vel 끊김 방지) — nav2 BT 가
                                # 새 goal 받자마자 이전 BT halt + 새 goal 시작.
                                self._dbg(
                                    f"preempt @ segment {i} (d={d:.2f}m ≤ "
                                    f"{self._preempt_distance:.2f}m) — fire next"
                                )
                                preempted = True
                                nav_gh = None   # finally cancel skip — nav2 가 자동 preempt
                                break
                    if gh.is_cancel_requested:
                        self.get_logger().info(
                            f"navigate_to_vertex: client cancel @ segment {i} → "
                            f"nav2 NavigateToPose cancel"
                        )
                        self._dbg(
                            f"client cancel → nav2 cancel "
                            f"(target={target!r}, segment={i}/{len(seq)-1})",
                            level="warn",
                        )
                        try:
                            cancel_future = nav_gh.cancel_goal_async()
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
                                self._dbg(
                                    f"nav2 cancel ack (segment {i})"
                                )
                        except Exception as e:
                            self.get_logger().warning(f"nav2 cancel failed: {e}")
                            self._dbg(f"nav2 cancel FAILED: {e}", level="err")
                        nav_gh = None
                        gh.canceled()
                        result.success = False
                        result.message = "canceled by client"
                        result.final_vertex = seq[last_idx]
                        return result
                    time.sleep(0.05)

                if preempted:
                    # preempt path — result_future 는 곧 CANCELED 로 해결되지만 우리는
                    # 이미 다음 segment 로 넘어감. nav2 가 새 goal 받으면 자동 preempt.
                    last_idx = i
                    self._publish_feedback(gh, seq, last_idx)
                    continue

                wrapper = get_result_future.result()
                nav_gh = None   # 정상 종료 — finally skip
                succeeded = wrapper.status == 4

                if not succeeded:
                    gh.abort()
                    result.success = False
                    result.message = (
                        f"nav2 status={_nav2_status_str(wrapper.status)} "
                        f"(segment {i} → {segment_target!r})"
                    )
                    result.final_vertex = seq[last_idx]
                    self._dbg(
                        f"abort: nav2 status={_nav2_status_str(wrapper.status)} "
                        f"(segment {i})",
                        level="warn",
                    )
                    return result

                # segment 성공 → last_idx 갱신, feedback publish
                last_idx = i
                self._publish_feedback(gh, seq, last_idx)
                self._dbg(f"segment {i} done ({segment_target!r})")

            except Exception as e:
                import traceback
                self.get_logger().error(
                    f"navigate_to_vertex exception @ segment {i}: {e}\n"
                    f"{traceback.format_exc()}"
                )
                self._dbg(
                    f"abort: exception {type(e).__name__}: {e} (segment {i})",
                    level="err",
                )
                try:
                    gh.abort()
                except Exception:
                    pass
                result.success = False
                result.message = f"exception @ segment {i}: {e}"
                result.final_vertex = seq[last_idx]
                return result
            finally:
                # ★ safety net per segment — nav_gh 가 active 상태로 남으면
                # nav2 controller 가 cmd_vel 계속 publish (좀비). 어떤 종료
                # 경로에서도 cancel forward 보장.
                if nav_gh is not None:
                    try:
                        nav_gh.cancel_goal_async()
                        self._dbg(
                            f"orphan nav_gh canceled in finally "
                            f"(target={target!r}, segment={i})",
                            level="err",
                        )
                    except Exception as e:
                        self.get_logger().warning(f"orphan cancel failed: {e}")
                        self._dbg(f"orphan cancel FAILED: {e}", level="err")

        # 모든 segment 성공
        gh.succeed()
        result.success = True
        result.message = ""
        result.final_vertex = target
        self._dbg(f"SUCCESS (target={target!r}, segments={len(seq)-1})")
        return result

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

    def _vertex_pose(self, name: str) -> PoseStamped:
        """vertex name → PoseStamped (map frame).

        NavigateToPose 의 단일 goal 로 사용. lane 보간은 nav2 의 global planner
        가 담당 (graph_router 는 vertex sequence 만 결정 — L1).
        """
        v = self._graph.vertices[name]
        return self._make_pose(v.x, v.y, v.yaw)

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
