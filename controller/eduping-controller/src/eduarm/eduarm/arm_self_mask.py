"""URDF 기반 로봇 팔 self-filter (순수 기하 — ROS/TF 없이 단위 테스트 가능).

가리기 팔이 D435 화면에 겹쳐 person bbox depth 를 오염시키는 문제를, 팔의 알려진
geometry(캡슐) 를 카메라 광학 프레임으로 변환해 해당 픽셀을 마스킹(제외)해 해결한다.

좌표계: REalSense 광학 프레임(REP-103) — Z forward, X right, Y down, 단위 m.
노드가 TF(`openarm_{side}_link{i}` → `d435_color_optical_frame`)로 link 원점을 이
프레임으로 변환해 consecutive link 쌍을 캡슐 세그먼트로 넘긴다. 본 모듈은 그 캡슐과
depth 백프로젝션 포인트만 비교한다 — TF·카메라 종속성 없음.
"""
from __future__ import annotations

import numpy as np

Segment = tuple[np.ndarray, np.ndarray, float]  # (p0(3,), p1(3,), radius_m)


def backproject(
    depth_mm: np.ndarray, x0: int, y0: int, fx: float, fy: float, cx: float, cy: float
) -> np.ndarray:
    """depth crop(H×W, mm) → (H, W, 3) 광학 프레임 포인트(m). invalid(0)은 z=0 으로 남는다.

    x0,y0 = crop 좌상단의 전체 이미지 픽셀 좌표 (intrinsics 는 전체 이미지 기준).
    핀홀: X=(u-cx)/fx·Z, Y=(v-cy)/fy·Z, Z=depth.
    """
    h, w = depth_mm.shape
    z = depth_mm.astype(np.float32) / 1000.0
    u = (np.arange(w, dtype=np.float32) + x0)[None, :]
    v = (np.arange(h, dtype=np.float32) + y0)[:, None]
    x = (u - cx) / fx * z
    y = (v - cy) / fy * z
    return np.stack([x, y, z], axis=-1)


def _point_segment_distance(points: np.ndarray, p0: np.ndarray, p1: np.ndarray) -> np.ndarray:
    """points (N,3) 각 점 → 선분 p0-p1 최단거리 (N,)."""
    d = p1 - p0
    seg_len2 = float(d @ d)
    if seg_len2 < 1e-12:
        return np.linalg.norm(points - p0, axis=1)
    t = np.clip((points - p0) @ d / seg_len2, 0.0, 1.0)
    proj = p0[None, :] + t[:, None] * d[None, :]
    return np.linalg.norm(points - proj, axis=1)


def arm_pixel_mask(points: np.ndarray, segments: list[Segment]) -> np.ndarray:
    """points (N,3) m, segments=[(p0,p1,radius)] → (N,) bool. 어떤 캡슐 안이면 True.

    invalid(z<=0) 포인트는 항상 False (마스킹 대상 아님).
    """
    n = points.shape[0]
    mask = np.zeros(n, dtype=bool)
    valid = points[:, 2] > 0.0
    if not valid.any() or not segments:
        return mask
    for p0, p1, radius in segments:
        within = _point_segment_distance(points, np.asarray(p0, dtype=np.float64),
                                         np.asarray(p1, dtype=np.float64)) <= radius
        mask |= within & valid
    return mask
