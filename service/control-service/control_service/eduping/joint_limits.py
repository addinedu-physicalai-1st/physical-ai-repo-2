"""EduPing OpenArm v10 (듀얼 암) 관절 한계 저장/조회/적용.

OpenArm v10 은 좌/우 각 7 arm joints + 1 finger (prismatic) → 총 16 joints.
관리자 UI 에서 슬라이더로 좁힌 안전 범위를 JSON 한 파일에 보관하고, dance / greeting
replay frame 마다 동일 한계로 clip 해 학습 데이터가 한계를 벗어나는 경우 강제로
잘라낸다. 모터·스틸 베이스 충돌 방지가 목적.

각 joint 의 ABSOLUTE 한계는 URDF 가 정의 — DEFAULT_JOINT_SPECS 의 (lower, upper) 가
그 값. 관리자는 그 안에서 좁힐 수 있지만 넘어가는 값은 set_limits 가 URDF 한계로
clamp 한다 (하드웨어 안전 가드).

라이브 상태는 모듈 전역 dict — Control Server 라이프타임 동안 유지되며 GET/POST
요청과 dance_stream import 가 같은 객체를 본다. POST 시 디스크 (JSON) 도 함께 갱신.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

# OpenArm v10 URDF 의 모든 활성 joint 와 그 URDF 한계 (rad / m).
# arm joints: revolute (rad). finger: prismatic (m).
# 좌/우 j1, j2 는 mirror 구조라 lower/upper 부호가 반대 — URDF 그대로 옮긴 것.
# (joint_name, korean_label, urdf_lower, urdf_upper, unit)
DEFAULT_JOINT_SPECS: tuple[tuple[str, str, float, float, str], ...] = (
    # --- 왼팔 ---
    ("openarm_left_joint1",         "왼팔 J1 (어깨 회전)",      -3.490659,  1.396263, "rad"),
    ("openarm_left_joint2",         "왼팔 J2 (어깨 들기)",      -3.316125,  0.174533, "rad"),
    ("openarm_left_joint3",         "왼팔 J3 (어깨 비틀기)",    -1.570796,  1.570796, "rad"),
    ("openarm_left_joint4",         "왼팔 J4 (팔꿈치)",          0.0,        2.443461, "rad"),
    ("openarm_left_joint5",         "왼팔 J5 (팔뚝 비틀기)",    -1.570796,  1.570796, "rad"),
    ("openarm_left_joint6",         "왼팔 J6 (손목 굽힘)",      -0.785398,  0.785398, "rad"),
    ("openarm_left_joint7",         "왼팔 J7 (손목 회전)",      -1.570796,  1.570796, "rad"),
    ("openarm_left_finger_joint1",  "왼팔 그리퍼",                0.0,        0.044,    "m"),
    # --- 오른팔 ---
    ("openarm_right_joint1",        "오른팔 J1 (어깨 회전)",    -1.396263,  3.490659, "rad"),
    ("openarm_right_joint2",        "오른팔 J2 (어깨 들기)",    -0.174533,  3.316125, "rad"),
    ("openarm_right_joint3",        "오른팔 J3 (어깨 비틀기)",  -1.570796,  1.570796, "rad"),
    ("openarm_right_joint4",        "오른팔 J4 (팔꿈치)",        0.0,        2.443461, "rad"),
    ("openarm_right_joint5",        "오른팔 J5 (팔뚝 비틀기)",  -1.570796,  1.570796, "rad"),
    ("openarm_right_joint6",        "오른팔 J6 (손목 굽힘)",    -0.785398,  0.785398, "rad"),
    ("openarm_right_joint7",        "오른팔 J7 (손목 회전)",    -1.570796,  1.570796, "rad"),
    ("openarm_right_finger_joint1", "오른팔 그리퍼",              0.0,        0.044,    "m"),
)


def _by_name() -> dict[str, tuple[str, float, float, str]]:
    """joint_name → (label, urdf_lower, urdf_upper, unit) 빠른 조회용."""
    return {name: (label, lo, hi, unit) for name, label, lo, hi, unit in DEFAULT_JOINT_SPECS}


_BY_NAME = _by_name()
_NAMES: tuple[str, ...] = tuple(name for name, *_ in DEFAULT_JOINT_SPECS)


def _urdf_limits(name: str) -> tuple[float, float]:
    spec = _BY_NAME.get(name)
    if spec is None:
        # 미등록 joint — 극단으로 막아도 의미 없으니 매우 넓게 (clip 효과 없음).
        return (-1e9, 1e9)
    _label, lo, hi, _unit = spec
    return (lo, hi)


def _default_limits() -> dict[str, dict[str, float]]:
    """기본 한계 = URDF 의 lower/upper. 사용자가 좁히지 않은 상태."""
    return {
        name: {"min": lo, "max": hi}
        for name, _label, lo, hi, _unit in DEFAULT_JOINT_SPECS
    }


def _limits_path() -> Path:
    """저장 위치 — control_service 패키지 옆 (단일 설정 파일)."""
    return Path(__file__).resolve().parent / "joint_limits.json"


_lock = threading.Lock()
_cache: dict[str, dict[str, float]] | None = None


def _normalize_row(name: str, row: dict) -> dict[str, float] | None:
    if not isinstance(row, dict):
        return None
    try:
        lo = float(row["min"])
        hi = float(row["max"])
    except (KeyError, TypeError, ValueError):
        return None
    if lo > hi:
        lo, hi = hi, lo
    urdf_lo, urdf_hi = _urdf_limits(name)
    lo = max(urdf_lo, min(urdf_hi, lo))
    hi = max(urdf_lo, min(urdf_hi, hi))
    return {"min": lo, "max": hi}


def _load_from_disk() -> dict[str, dict[str, float]]:
    path = _limits_path()
    if not path.exists():
        return _default_limits()
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"joint_limits.json 로드 실패 ({path}) — 기본값 사용: {e}")
        return _default_limits()
    out = _default_limits()
    if isinstance(data, dict):
        for name in _NAMES:
            normalized = _normalize_row(name, data.get(name))
            if normalized is not None:
                out[name] = normalized
    return out


def get_limits() -> dict[str, dict[str, float]]:
    """현재 한계 dict 의 deep copy. 호출자가 mutate 해도 캐시 무영향."""
    global _cache
    with _lock:
        if _cache is None:
            _cache = _load_from_disk()
        return {n: dict(v) for n, v in _cache.items()}


def set_limits(new_limits: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    """관리자 UI 에서 POST 한 값으로 한계 갱신 + 디스크 저장. 정규화된 dict 반환."""
    global _cache
    cleaned = _default_limits()
    if isinstance(new_limits, dict):
        for name in _NAMES:
            normalized = _normalize_row(name, new_limits.get(name))
            if normalized is not None:
                cleaned[name] = normalized

    with _lock:
        _cache = cleaned
        try:
            path = _limits_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as f:
                json.dump(cleaned, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.warning(f"joint_limits.json 저장 실패: {e}")
    return {n: dict(v) for n, v in cleaned.items()}


def clip_positions(joint_names: Iterable[str], positions: list[float]) -> list[float]:
    """frame 의 (joint_names, positions) 를 한계로 clip.

    길이 mismatch 시 그대로 통과. 등록 안 된 joint 도 그대로 통과 (mimic joint 등).
    """
    names = list(joint_names)
    if len(names) != len(positions):
        return positions
    limits = get_limits()
    out: list[float] = []
    for name, val in zip(names, positions):
        row = limits.get(name)
        if row is None:
            out.append(val)
            continue
        lo = row["min"]
        hi = row["max"]
        if val < lo:
            out.append(lo)
        elif val > hi:
            out.append(hi)
        else:
            out.append(val)
    return out


def joint_names() -> tuple[str, ...]:
    return _NAMES


def joint_specs() -> tuple[tuple[str, str, float, float, str], ...]:
    """UI 가 슬라이더 라벨·단위·URDF 한계 (slider min/max) 를 그릴 때 사용."""
    return DEFAULT_JOINT_SPECS
