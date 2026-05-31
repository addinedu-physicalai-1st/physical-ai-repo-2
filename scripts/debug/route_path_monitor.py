#!/usr/bin/env python3
"""nav viz 인과사슬 통합 트레이스 — mid-motion 재goal 시 무엇이 막히는지.

한 타임라인에 4개 토픽을 같이 찍어 "새 goal → 새 액션 → 새 경로 발행" 사슬 중
어디서 끊기는지 본다:

  ROUTE  /graph_router/route_path  poses=N  ← L1 파란선 (N=0 이면 CLEAR)
  NAV    /gogoping/debug/nav_events         ← graph_router 이벤트(act_navigate start, abort…)
  STATE  /gogoping/state_str                ← FSM state 전이 (GOTO→GOTO 면 변화 없음)
  PLAN   /plan                     poses=N  ← nav2 빨강 global plan (reroute 됐나)

읽는 법 — 이동 중 새 goal 눌렀을 때:
  • NAV 에 'act_navigate start' 가 뜨면 → graph_router 가 새 goal 받음
       그 뒤 ROUTE poses=N 안 뜨면 → 414 전에 abort (NAV 의 abort 사유 확인)
  • NAV 에 아무것도 안 뜨면 → 새 goal 이 graph_router 까지 안 옴 (상위 레벨 문제)
  • STATE 가 GOTO→GOTO(변화 없음)면 → control-service 의 state-change clear 도 안 돔

사용:
  python3 scripts/debug/route_path_monitor.py
  (다른 곳에서 GOTO → 이동 중 다시 GOTO, 누른 시각 기억)
"""
from __future__ import annotations

import time

import rclpy
from nav_msgs.msg import Path
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

_t0 = time.monotonic()


def _ts() -> str:
    return f"[{time.monotonic() - _t0:8.3f}s]"


class NavVizTrace(Node):
    def __init__(self) -> None:
        super().__init__("nav_viz_trace")

        latched = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE,
        )
        # L1 route_path (latched)
        self.create_subscription(
            Path, "/graph_router/route_path", self._on_route, latched
        )
        # graph_router 이벤트
        self.create_subscription(
            String, "/gogoping/debug/nav_events", self._on_nav, 20
        )
        # FSM state
        self.create_subscription(
            String, "/gogoping/state_str", self._on_state, 10
        )
        # nav2 global plan
        self.create_subscription(Path, "/plan", self._on_plan, 10)

        self._last_state = None
        self._last_plan_end = None
        self.get_logger().info(
            "watching ROUTE/NAV/STATE/PLAN … 이동 중 재goal 후 출력 붙여줘 (Ctrl+C 종료)"
        )

    def _on_route(self, msg: Path) -> None:
        n = len(msg.poses)
        if n:
            p0, p1 = msg.poses[0].pose.position, msg.poses[-1].pose.position
            extra = f"  ({p0.x:.2f},{p0.y:.2f})→({p1.x:.2f},{p1.y:.2f})"
        else:
            extra = "  ← CLEAR(빈 Path)"
        print(f"{_ts()} ROUTE  poses={n:<4}{extra}", flush=True)

    def _on_nav(self, msg: String) -> None:
        print(f"{_ts()} NAV    {msg.data}", flush=True)

    def _on_state(self, msg: String) -> None:
        arrow = "" if self._last_state is None else f"  ({self._last_state}→{msg.data})"
        self._last_state = msg.data
        print(f"{_ts()} STATE  {msg.data}{arrow}", flush=True)

    def _on_plan(self, msg: Path) -> None:
        # 3hz replan spam 억제 — goal(끝점) 이 0.3m 이상 바뀔 때만 (= 새 목표/reroute)
        if not msg.poses:
            end = None
        else:
            p = msg.poses[-1].pose.position
            end = (round(p.x, 1), round(p.y, 1))
        if end == self._last_plan_end:
            return
        self._last_plan_end = end
        tail = f"  end={end}" if end else "  ← empty"
        print(f"{_ts()} PLAN   poses={len(msg.poses)}{tail}  (새 목표/reroute)", flush=True)


def main() -> None:
    rclpy.init()
    node = NavVizTrace()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
