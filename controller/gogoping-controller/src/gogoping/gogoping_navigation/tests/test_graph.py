"""graph.py — Vertex, Graph, heading-aware Dijkstra unit tests."""
import math
from pathlib import Path

import pytest

from gogoping_navigation.graph import Graph, GraphError, Vertex


def test_vertex_default_can_rotate_false():
    v = Vertex(name="A", x=0.0, y=0.0)
    assert v.can_rotate is False


def test_vertex_explicit_can_rotate_true():
    v = Vertex(name="charge", x=0.0, y=0.0, can_rotate=True)
    assert v.can_rotate is True


def _build_corridor_graph() -> Graph:
    """남↔북 직선 복도 + 옆 라인 (평행 vertex).

         B1 ── B2     (옆 라인, x=1)
         │     │
         A1 ── A2     (메인 라인, x=0)
    """
    verts = [
        Vertex(name="A1", x=0.0, y=0.0, can_rotate=False),
        Vertex(name="A2", x=0.0, y=2.0, can_rotate=False),
        Vertex(name="B1", x=1.0, y=0.0, can_rotate=False),
        Vertex(name="B2", x=1.0, y=2.0, can_rotate=False),
    ]
    manual_lanes = [("A1", "A2"), ("B1", "B2"), ("A1", "B1"), ("A2", "B2")]
    return Graph(verts, manual_lanes=manual_lanes)


def test_route_with_heading_simple_forward():
    """heading 과 다음 lane 방향이 일치 → 직진 경로."""
    g = _build_corridor_graph()
    # A1 (heading=북, yaw=π/2) → A2 — 직진. lane 방향이 +y 이므로 yaw=π/2.
    path = g.route("A1", "A2", start_yaw=math.pi / 2)
    assert path == ["A1", "A2"]


def test_route_with_heading_blocks_reverse_at_non_rotation_vertex():
    """heading=북 인데 목적지가 남 → reverse 거부 → no path (해당 graph 에 우회 없음)."""
    verts = [
        Vertex(name="A1", x=0.0, y=2.0, can_rotate=False),
        Vertex(name="A2", x=0.0, y=0.0, can_rotate=False),
    ]
    g = Graph(verts, manual_lanes=[("A1", "A2")])
    # A1 → A2 는 yaw=-π/2 방향. robot heading=π/2. |Δ| = π. can_rotate=False → 거부.
    with pytest.raises(GraphError, match="no.*path"):
        g.route("A1", "A2", start_yaw=math.pi / 2)


def test_route_with_heading_allows_reverse_at_rotation_vertex():
    """can_rotate=True 면 어떤 heading 이라도 출발 가능."""
    verts = [
        Vertex(name="charge", x=0.0, y=2.0, can_rotate=True),
        Vertex(name="next", x=0.0, y=0.0, can_rotate=False),
    ]
    g = Graph(verts, manual_lanes=[("charge", "next")])
    # heading=북 (yaw=π/2) 인데 charge.can_rotate=True 라 OK.
    path = g.route("charge", "next", start_yaw=math.pi / 2)
    assert path == ["charge", "next"]


def test_route_with_heading_uses_side_step_for_reverse():
    """A2 (heading=북) 에서 A1 으로 — 옆 라인 우회.

    A2 → B2 (동, |Δ|=90° OK) → B1 (남, |Δ|=90° OK) → A1 (서, |Δ|=90° OK).
    """
    g = _build_corridor_graph()
    path = g.route("A2", "A1", start_yaw=math.pi / 2)
    assert path == ["A2", "B2", "B1", "A1"]


def test_route_blocked_vertex_excluded():
    """blocked set 에 있는 vertex 는 경로에서 제외."""
    g = _build_corridor_graph()
    path = g.route("A1", "A2")
    assert path == ["A1", "A2"]
    path2 = g.route("A1", "A2", blocked={"B1"})
    assert path2 == ["A1", "A2"]


def test_route_blocked_forces_detour():
    """블락된 vertex 회피 — 경로 없으면 GraphError."""
    verts = [
        Vertex(name="A", x=0.0, y=0.0),
        Vertex(name="mid", x=1.0, y=0.0),
        Vertex(name="B", x=2.0, y=0.0),
    ]
    g = Graph(verts, manual_lanes=[("A", "mid"), ("mid", "B")])
    assert g.route("A", "B") == ["A", "mid", "B"]
    with pytest.raises(GraphError, match="no path"):
        g.route("A", "B", blocked={"mid"})


def test_route_blocked_dst_raises():
    g = _build_corridor_graph()
    with pytest.raises(GraphError, match="is blocked"):
        g.route("A1", "A2", blocked={"A2"})


def test_graph_from_yaml_loads_can_rotate(tmp_path: Path):
    yaml_text = """
waypoints:
- name: A
  x: 0.0
  y: 0.0
  yaw: 0.0
  can_rotate: true
- name: B
  x: 1.0
  y: 0.0
  yaw: 0.0
"""
    p = tmp_path / "wp.yaml"
    p.write_text(yaml_text)
    g = Graph.from_yaml(p)
    assert g.vertices["A"].can_rotate is True
    assert g.vertices["B"].can_rotate is False
