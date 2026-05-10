"""Pure-function nav_graph.yaml loader.

ROS 의존성 없음. yaml → vertices/adjacency 변환과 무결성 검증만.
PoseStamped 생성 같은 ROS 메시지 만들기는 호출자 (rclpy 노드) 가 담당.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import yaml


def load_graph(yaml_path: str | Path) -> tuple[dict[int, dict], dict[int, list[int]]]:
    """nav_graph.yaml → (vertices_by_idx, adjacency).

    Returns
    -------
    vertices : {idx: vertex_dict, ...}
        vertex_dict 는 yaml 의 한 행 그대로 (idx, name, x, y, theta?, type?, ...)
    adj : {from_idx: [to_idx, ...], ...}
        bidirectional lane 은 양쪽 방향으로 자동 추가.
    """
    path = Path(yaml_path)
    with path.open(encoding='utf-8') as f:
        data = yaml.safe_load(f)

    vertices: dict[int, dict] = {v['idx']: v for v in data.get('vertices', [])}
    adj: dict[int, list[int]] = {}
    for lane in data.get('lanes', []):
        a, b = int(lane['from']), int(lane['to'])
        adj.setdefault(a, []).append(b)
        if lane.get('bidirectional', False):
            adj.setdefault(b, []).append(a)

    return vertices, adj


def validate_graph(vertices: dict[int, dict], adj: dict[int, list[int]]) -> list[str]:
    """그래프 무결성 검증. 문제 메시지 리스트 반환 (빈 리스트면 OK)."""
    issues: list[str] = []

    seen_idx = set(vertices.keys())
    for v in vertices.values():
        for required in ('idx', 'name', 'x', 'y'):
            if required not in v:
                issues.append(f"vertex idx={v.get('idx', '?')} missing field '{required}'")

    for from_idx, to_list in adj.items():
        if from_idx not in seen_idx:
            issues.append(f"lane references unknown from_idx={from_idx}")
        for to_idx in to_list:
            if to_idx not in seen_idx:
                issues.append(f"lane references unknown to_idx={to_idx}")

    return issues


def nearest_vertex_idx(
    vertices: dict[int, dict], x: float, y: float
) -> int:
    """주어진 좌표에서 가장 가까운 vertex 의 idx 반환 (유클리드)."""
    return min(
        vertices.values(),
        key=lambda v: math.hypot(v['x'] - x, v['y'] - y),
    )['idx']


def vertex_to_pose_dict(vertex: dict) -> dict[str, float]:
    """vertex dict → PoseStamped 호환 dict (yaw → quaternion z/w).

    실제 geometry_msgs/PoseStamped 메시지 빌드는 호출자가 함 — 이 모듈은 ROS 무관.
    """
    yaw = float(vertex.get('theta', 0.0))
    return {
        'x': float(vertex['x']),
        'y': float(vertex['y']),
        'z': 0.0,
        'qx': 0.0,
        'qy': 0.0,
        'qz': math.sin(yaw / 2.0),
        'qw': math.cos(yaw / 2.0),
    }
