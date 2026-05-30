"""근접 안전정지 판정 (순수 로직).

naive depth-min 은 로봇 자기 팔·바닥·구조물이 0.6m 안에 잡혀 영구 block 되는 문제가
있었다. 그래서 **사람 검출 게이트**로 전환: YOLO 가 찾은 사람 bbox 영역의 depth 만
보고, 그 사람이 가까우면 block. 팔·바닥은 "사람"이 아니라 무시된다.

ROS/카메라/YOLO 없이 단위 테스트 가능하도록 분리 — 노드가 (depth, person_bboxes) 를
넘겨 호출한다.
"""
from __future__ import annotations

import numpy as np

NEAR_MM_DEFAULT = 600     # 0.60 m — 사람이 이내면 정지
CLEAR_MM_DEFAULT = 650    # 0.65 m — 밖이면 해제 (히스테리시스)
PERSON_PCTL_DEFAULT = 20  # 안전정지용: 사람 bbox 내 가까운 쪽 백분위 = 최근접부 추정. 정지는
#                            fail-safe 라 민감해도 됨(과검출 OK).
REACH_PCTL_DEFAULT = 50   # 게임 도달용: 중앙값. 소수 near 픽셀(가리기 팔이 bbox 에 겹침,
#                            윤곽 flying-pixel)이 과반이 아니면 무시 → 사람 몸통 실제 거리.
#                            도달 오검출은 게임을 끊으므로 robust 가 우선.
REACH_SELF_FLOOR_MM_DEFAULT = 400  # 이보다 가까운 픽셀은 "로봇 자기 팔"로 보고 제외. 가리기
#                            팔은 카메라 바로 앞(다가오는 아이보다 항상 가까움)이라 depth 로
#                            직접 분리 — extrinsic 보정 불필요. 실물 arm 거리에 맞춰 튜닝.
MIN_VALID_PX_DEFAULT = 30  # bbox 내 유효 depth 픽셀 최소 — 이하면 측정 불가로 무시


def person_distance_mm(
    depth_mm: np.ndarray,
    bbox: tuple[float, float, float, float],
    *,
    percentile: int = PERSON_PCTL_DEFAULT,
    min_valid_px: int = MIN_VALID_PX_DEFAULT,
    self_floor_mm: int = 0,
) -> float | None:
    """사람 bbox(x1,y1,x2,y2, color=aligned-depth 프레임 픽셀) 영역의 대표 거리(mm).

    bbox 는 배경을 포함하므로 percentile 로 대표값을 뽑는다(safety=20 최근접, reach=50 median).
    self_floor_mm>0 이면 그보다 가까운 픽셀(로봇 자기 팔 등)을 제외 후 계산 — extrinsic 보정
    없이 depth 만으로 자기 팔 분리. 유효 픽셀이 너무 적으면(사람이 팔에 완전 가림 등) None.
    """
    h, w = depth_mm.shape
    x1 = max(0, int(bbox[0]))
    y1 = max(0, int(bbox[1]))
    x2 = min(w, int(bbox[2]))
    y2 = min(h, int(bbox[3]))
    if x2 <= x1 or y2 <= y1:
        return None
    crop = depth_mm[y1:y2, x1:x2]
    valid = crop[crop > 0]
    if self_floor_mm > 0:
        valid = valid[valid >= self_floor_mm]
    if valid.size < min_valid_px:
        return None
    return float(np.percentile(valid, percentile))


def decide_block(
    person_dists: list[float | None],
    prev_blocked: bool,
    *,
    near_mm: int = NEAR_MM_DEFAULT,
    clear_mm: int = CLEAR_MM_DEFAULT,
) -> bool:
    """사람 거리 목록 중 임계 이내가 하나라도 있으면 block. 히스테리시스(정지 near, 해제 clear).

    사람이 없거나(빈 목록) 거리 측정 불가(None) 면 block 아님 — 팔/바닥은 애초에 사람
    bbox 가 아니라 목록에 안 들어온다.
    """
    threshold = clear_mm if prev_blocked else near_mm
    return any(d is not None and d < threshold for d in person_dists)


ON_FRAMES_DEFAULT = 2   # block 진입: 연속 N프레임 근접 (오검출 1프레임 무시)
OFF_FRAMES_DEFAULT = 6  # block 해제: 연속 M프레임 clear (가리기 팔 occlusion 으로 사람이
#                          잠깐 사라져도 유지 — 떨림 방지, off 를 크게 해 sticky)


def step_debounce(
    prev: bool,
    raw: bool,
    streak: int,
    *,
    on_frames: int = ON_FRAMES_DEFAULT,
    off_frames: int = OFF_FRAMES_DEFAULT,
) -> tuple[bool, int]:
    """프레임 단위 시간 디바운스. 검출 깜빡임(occlusion/근접 crop)이 그대로 block 토글로
    전파되는 것을 막는다.

    streak = 현재 상태(prev)와 반대 방향으로 raw 가 연속 유지된 프레임 수. raw 가 prev 와
    같으면 streak 리셋. 반대면 누적해, 켜기엔 on_frames·끄기엔 off_frames 도달 시 flip.
    off_frames 를 크게 두면 "sticky block" — 잠깐의 검출 소실에 풀리지 않는다.

    반환: (새 상태, 새 streak).
    """
    if raw == prev:
        return prev, 0
    streak += 1
    need = on_frames if raw else off_frames
    if streak >= need:
        return raw, 0
    return prev, streak
