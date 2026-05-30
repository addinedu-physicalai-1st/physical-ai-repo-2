"""사람 근접 거리 — ultralytics Results + depth → 정면 박스 내 최근접 사람 거리(m).

graph_router 의 person_close 트리거(/gogoping/person_proximity)용. ROS 의존 없음.
핵심 기하는 frontal_box.nearest_person_in_box 위임 (이미 테스트됨).
"""
from __future__ import annotations

from dataclasses import dataclass

from gogoping_perception.frontal_box import nearest_person_in_box


@dataclass(frozen=True)
class ProximityCfg:
    fx: float
    cx: float
    forward_m: float
    lateral_m: float


def _person_detections(results) -> list[tuple]:
    if not results:
        return []
    r = results[0]
    if r.boxes is None or len(r.boxes.xyxy) == 0:
        return []
    xyxy = r.boxes.xyxy.cpu().numpy()
    return [tuple(map(int, b.tolist())) for b in xyxy]


def nearest_person_distance_m(results, depth, cfg: ProximityCfg) -> float:
    """정면 박스 안 최근접 사람 거리(m). 없으면 +inf."""
    dets = _person_detections(results)
    if not dets:
        return float("inf")
    return nearest_person_in_box(
        detections=dets, depth=depth,
        fx=cfg.fx, cx=cfg.cx,
        box_forward_m=cfg.forward_m, box_lateral_m=cfg.lateral_m,
    )
