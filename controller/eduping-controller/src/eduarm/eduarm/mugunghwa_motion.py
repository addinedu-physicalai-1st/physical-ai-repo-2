"""무궁화 device-local 판정 — ROS/카메라/네트워크 비의존 순수 로직.

mugunghwa_perception_node 가 import 한다. rclpy / cv2 / ultralytics 를 import 하지
않으므로 노드 없이 단독 pytest 가능. 임계/로직은 브라우저 MugunghwaGame.vue 의
관찰 단계(변위 기반 탈락)와 동일 의미를 이식한 것.
"""
from __future__ import annotations

Bbox = tuple[float, float, float, float]  # x1, y1, x2, y2


def centroid(bbox: Bbox) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _iou(a: Bbox, b: Bbox) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def match_recognize_to_tracks(
    matches: list[dict],
    tracks: list[dict],
    iou_threshold: float = 0.3,
) -> dict[int, int]:
    """recognize-multi 응답(matched=True 인 것만)의 bbox 를 track 에 greedy IoU 매칭.

    matches: [{"child_id": int, "bbox": [x1,y1,x2,y2]}, ...]
    tracks:  [{"track_id": int, "bbox": (x1,y1,x2,y2)}, ...]
    반환: {track_id: child_id}
    """
    pairs: list[tuple[float, int, int]] = []
    for mi, m in enumerate(matches):
        mb = m.get("bbox")
        if not mb or len(mb) < 4:
            continue
        mbbox: Bbox = (mb[0], mb[1], mb[2], mb[3])
        for ti, t in enumerate(tracks):
            v = _iou(mbbox, t["bbox"])
            if v >= iou_threshold:
                pairs.append((v, mi, ti))
    pairs.sort(key=lambda p: p[0], reverse=True)
    used_m: set[int] = set()
    used_t: set[int] = set()
    out: dict[int, int] = {}
    for _v, mi, ti in pairs:
        if mi in used_m or ti in used_t:
            continue
        used_m.add(mi)
        used_t.add(ti)
        out[tracks[ti]["track_id"]] = matches[mi]["child_id"]
    return out


def _displacement(track: dict, baseline: dict[int, tuple[float, float]]) -> float | None:
    tid = track["track_id"]
    base = baseline.get(tid)
    if base is None:
        return None
    cx, cy = centroid(track["bbox"])
    bx, by = base
    return ((cx - bx) ** 2 + (cy - by) ** 2) ** 0.5


def max_displacement(tracks: list[dict], baseline: dict[int, tuple[float, float]]) -> float:
    """baseline 이 있는 모든 track(바인딩 무관)의 최대 변위. 미식별 motion flash 판정용."""
    best = 0.0
    for t in tracks:
        d = _displacement(t, baseline)
        if d is not None and d > best:
            best = d
    return best


def select_movers(
    tracks: list[dict],
    baseline: dict[int, tuple[float, float]],
    bindings: dict[int, int],
    strict_px: float,
    loose_px: float,
) -> list[int]:
    """관찰 중 baseline 대비 변위로 탈락 child_id 선정.

    strict_px 이상 변위 track 전원 탈락. 없으면 loose_px 이상 중 최대 변위 1명.
    바인딩(track_id→child_id) + baseline 둘 다 있는 track 만 후보.
    반환: child_id 리스트 (중복 제거).
    """
    cand: list[tuple[int, float]] = []
    for t in tracks:
        tid = t["track_id"]
        if tid not in bindings:
            continue
        d = _displacement(t, baseline)
        if d is None:
            continue
        cand.append((bindings[tid], d))
    if not cand:
        return []
    strict = [cid for cid, d in cand if d >= strict_px]
    if strict:
        return list(dict.fromkeys(strict))
    max_d = max(d for _cid, d in cand)
    if max_d >= loose_px:
        return list(dict.fromkeys([cid for cid, d in cand if d == max_d]))
    return []
