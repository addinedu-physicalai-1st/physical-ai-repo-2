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


def _containment(inner: Bbox, outer: Bbox) -> float:
    """inner(얼굴) 가 outer(사람) 박스에 얼마나 들어가 있나 — inter / inner_area (0..1)."""
    ix1, iy1 = max(inner[0], outer[0]), max(inner[1], outer[1])
    ix2, iy2 = min(inner[2], outer[2]), min(inner[3], outer[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    inner_area = max(0.0, inner[2] - inner[0]) * max(0.0, inner[3] - inner[1])
    return inter / inner_area if inner_area > 0 else 0.0


def match_recognize_to_tracks(
    matches: list[dict],
    tracks: list[dict],
    containment_threshold: float = 0.5,
) -> dict[int, int]:
    """recognize-multi 의 얼굴 bbox 를 YOLO person track 에 greedy 매칭.

    recognize 는 InsightFace **얼굴** bbox, track 은 YOLO **사람(class 0)** bbox 라 크기가
    크게 달라 IoU 는 부적합 (얼굴이 사람 박스 안의 작은 영역 → IoU ≪ 0.3 → 바인딩 실패).
    얼굴이 사람 박스에 얼마나 포함되는가(containment = inter/face_area)로 매칭한다.

    matches: [{"child_id": int, "bbox": [x1,y1,x2,y2]}, ...]   # 얼굴
    tracks:  [{"track_id": int, "bbox": (x1,y1,x2,y2)}, ...]    # 사람
    반환: {track_id: child_id}
    """
    pairs: list[tuple[float, int, int]] = []
    for mi, m in enumerate(matches):
        mb = m.get("bbox")
        if not mb or len(mb) < 4:
            continue
        face: Bbox = (mb[0], mb[1], mb[2], mb[3])
        for ti, t in enumerate(tracks):
            v = _containment(face, t["bbox"])
            if v >= containment_threshold:
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
