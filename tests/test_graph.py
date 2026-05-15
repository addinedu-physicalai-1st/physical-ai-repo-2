"""Graph (vertex + 거리 자동 lane + 다익스트라) 단위 테스트."""
from __future__ import annotations

from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                      / "controller" / "gogoping-controller" / "src" / "gogoping"
                      / "gogoping_navigation"))
from gogoping_navigation.graph import (  # noqa: E402
    DEFAULT_LANE_THRESHOLD_M,
    Graph,
    GraphError,
    Vertex,
)


WAYPOINTS_YAML = (Path(__file__).resolve().parents[1]
                  / "controller" / "gogoping-controller" / "src" / "gogoping"
                  / "gogoping_navigation" / "config" / "waypoints.yaml")


def _g(*verts: Vertex, threshold: float = DEFAULT_LANE_THRESHOLD_M) -> Graph:
    return Graph(list(verts), lane_threshold_m=threshold)


def test_empty_vertices_raises():
    with pytest.raises(GraphError, match="empty"):
        Graph([])


def test_duplicate_name_raises():
    with pytest.raises(GraphError, match="중복"):
        _g(Vertex("a", 0, 0), Vertex("a", 1, 1))


def test_lane_within_threshold():
    g = _g(Vertex("a", 0, 0), Vertex("b", 1, 0))
    assert ("a", "b", 1.0) in [(f, t, round(d, 3)) for f, t, d in g.lanes()]


def test_lane_outside_threshold_excluded():
    g = _g(Vertex("a", 0, 0), Vertex("b", 5, 0))
    assert g.lanes() == []


def test_lanes_bidirectional_no_duplicate():
    g = _g(Vertex("a", 0, 0), Vertex("b", 1, 0), Vertex("c", 0, 1))
    lanes = g.lanes()
    keys = {(f, t) if f < t else (t, f) for f, t, _ in lanes}
    assert len(keys) == len(lanes)


def test_nearest_vertex():
    g = _g(Vertex("a", 0, 0), Vertex("b", 10, 0), Vertex("c", 5, 5))
    assert g.nearest_vertex(0.1, 0.0) == "a"
    assert g.nearest_vertex(9.9, 0.0) == "b"
    assert g.nearest_vertex(5.0, 4.0) == "c"


def test_route_same_node():
    g = _g(Vertex("a", 0, 0), Vertex("b", 1, 0))
    assert g.route("a", "a") == ["a"]


def test_route_direct_neighbor():
    g = _g(Vertex("a", 0, 0), Vertex("b", 1, 0))
    assert g.route("a", "b") == ["a", "b"]


def test_route_multi_hop():
    # a -- b -- c (대각선 a~c 는 threshold 초과)
    g = _g(
        Vertex("a", 0, 0),
        Vertex("b", 1, 0),
        Vertex("c", 2, 0),
        threshold=1.5,
    )
    assert g.route("a", "c") == ["a", "b", "c"]


def test_route_unknown_endpoint():
    g = _g(Vertex("a", 0, 0), Vertex("b", 1, 0))
    with pytest.raises(GraphError, match="not in graph"):
        g.route("a", "z")


def test_route_disconnected():
    g = _g(Vertex("a", 0, 0), Vertex("b", 10, 0))   # 거리 10 > threshold 1.7
    with pytest.raises(GraphError, match="no path"):
        g.route("a", "b")


def test_route_picks_shortest():
    # threshold 1.2 — 가로/세로만 lane, 대각선(√2≈1.414) 제외.
    # a-b-d (1+1) vs a-c-d (1+1) 둘 다 valid 한 직선 경로.
    g = _g(
        Vertex("a", 0, 0),
        Vertex("b", 1, 0),
        Vertex("c", 0, 1),
        Vertex("d", 1, 1),
        threshold=1.2,
    )
    path = g.route("a", "d")
    assert path[0] == "a" and path[-1] == "d"
    assert len(path) == 3   # 1 hop 중간 (대각선 막힘)


def test_threshold_changes_connectivity():
    verts = [Vertex("a", 0, 0), Vertex("b", 1.6, 0), Vertex("c", 3.2, 0)]
    g_loose = Graph(verts, lane_threshold_m=1.7)
    g_tight = Graph(verts, lane_threshold_m=1.5)
    assert ("a", "b") in [(f, t) for f, t, _ in g_loose.lanes()]
    assert g_tight.lanes() == []


@pytest.mark.skipif(not WAYPOINTS_YAML.exists(),
                    reason="waypoints.yaml 없음 (개발 환경)")
def test_from_real_yaml():
    g = Graph.from_yaml(WAYPOINTS_YAML)
    # 사용자 의도 검증 — 운동장22 의 4-neighbor
    lanes = {(f, t) if f < t else (t, f) for f, t, _ in g.lanes()}
    assert ("운동장12", "운동장22") in lanes
    assert ("운동장21", "운동장22") in lanes
    assert ("운동장22", "운동장23") in lanes
    assert ("운동장22", "운동장32") in lanes
    # 대각선은 제외 (운동장11 거리 1.86 > 1.7)
    assert ("운동장11", "운동장22") not in lanes

    # 놀이방5 → 놀이방4 만 (놀이방3 은 같은 x 지만 거리 6.36 > 1.7)
    assert ("놀이방4", "놀이방5") in lanes
    assert ("놀이방3", "놀이방5") not in lanes

    # route — 출입구1 에서 운동장22 까지 경로 존재
    path = g.route("출입구1", "운동장22")
    assert path[0] == "출입구1"
    assert path[-1] == "운동장22"
    assert len(path) >= 3   # 최소 한 vertex 거쳐야


# ---- Task 7: auto_edge 순수 함수 ----
def test_auto_edge_distance_threshold():
    from gogoping_navigation.graph import auto_edge, Vertex
    verts = [
        Vertex(name="A", x=0.0, y=0.0),
        Vertex(name="B", x=1.0, y=0.0),
        Vertex(name="C", x=0.0, y=1.0),
        Vertex(name="D", x=1.0, y=1.0),
    ]
    lanes = auto_edge(verts, threshold=1.0)
    pairs = {tuple(sorted([a, b])) for a, b, _bidir in lanes}
    assert pairs == {("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")}


def test_auto_edge_threshold_excludes_diagonals():
    from gogoping_navigation.graph import auto_edge, Vertex
    verts = [
        Vertex(name="A", x=0.0, y=0.0),
        Vertex(name="B", x=1.0, y=1.0),
    ]
    # 거리 sqrt(2) ≈ 1.414
    assert auto_edge(verts, threshold=1.5) != []
    assert auto_edge(verts, threshold=1.0) == []


def test_auto_edge_dedupes_pairs():
    from gogoping_navigation.graph import auto_edge, Vertex
    verts = [
        Vertex(name="A", x=0.0, y=0.0),
        Vertex(name="B", x=0.5, y=0.0),
    ]
    lanes = auto_edge(verts, threshold=1.0)
    assert len(lanes) == 1   # A↔B 한 번만
