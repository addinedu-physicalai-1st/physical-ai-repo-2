"""Tree inspector — py_trees root → admin BT 위젯 snapshot dict.

호출자: ``main.py._tick()`` 의 1Hz publish 루프.
출력 포맷: ``app/admin-app/widgets/bt_state_inline.py`` 의 ``update_snapshot()`` 호환.

snapshot 구조::

    {
      "robot_id": "gogoping",
      "fsm_state": "ASSIST",
      "assist_task": "lullaby",  # blackboard.ASSIST_TASK ("" / "goto" / "follow" / "lullaby")
      "play_task": "",            # blackboard.PLAY_TASK ("" / "hideseek")
      "main_tree": {
        "name": "BT_assist_main",
        "children": [
          {"name": "CommandListener",                       "status": "RUNNING"},
          {"name": "CheckTask(assist_task=='goto')",        "status": "SUCCESS"},
          {"name": "BT_goto_sub",                           "status": "RUNNING"},
          {"name": "CheckTask(assist_task=='follow')",      "status": "INVALID"},
          {"name": "StubFollow",                            "status": "INVALID"},
          ...
        ]
      },
      "sub_tree": null,    # + 에 BT_*_sub 이름 패턴 매칭 시 채워짐
      "battery_level": 87.3,  # blackboard.BATTERY_LEVEL (0~100 %, None = 미수신)
      "robot_pose": {"x": 3.2, "y": -1.4, "yaw": 0.78},  # blackboard.ROBOT_POSE (None = odom 미수신)
      "in_map": true,         # map_cache.is_outside 부정. True/False/None (None = 맵 미수신)
      "ts": 1730000035.123
    }

## 두 가지 flatten 정책

- **main_tree.children**: root 의 모든 leaf 를 깊이 우선으로 평탄화 후 (name, status) 만.
  composite (Selector/Sequence/Parallel) 자체는 표시 안 함 — 자식만. RUNNING 가 아닌
  leaves (SUCCESS/FAILURE/INVALID) 도 포함해서 진행도 표시 (admin 위젯이 status 별
  시각 차별 적용).
- **sub_tree**: ``BT_*_sub`` naming convention 으로 식별. + 진짜 SubTree 가 생기면
  자동으로 잡힘. BT_*_sub 이름이 아닌 노드는 *main_tree.children* 에 그대로 평탄화됨.
"""
from __future__ import annotations

import time
from typing import Any

import py_trees
from py_trees.common import Access

from .blackboard import Keys


# composite 클래스 이름 — py_trees 내장 (Selector / Sequence / Parallel).
_COMPOSITE_CLASS_NAMES = frozenset({"Selector", "Sequence", "Parallel"})

_MAX_DEPTH = 6  # 안전망 — 사이클 / 무한 nesting 방지

# blackboard 읽기 전용 client — 첫 호출 시 lazy 생성, snapshot() 매 호출마다 재사용
_bb_reader: py_trees.blackboard.Client | None = None


def _ensure_bb_reader() -> py_trees.blackboard.Client:
    global _bb_reader
    if _bb_reader is None:
        _bb_reader = py_trees.blackboard.Client(name="tree_inspector_reader")
        _bb_reader.register_key(key=Keys.BATTERY_LEVEL, access=Access.READ)
        _bb_reader.register_key(key=Keys.ROBOT_POSE, access=Access.READ)
        _bb_reader.register_key(key=Keys.ASSIST_TASK, access=Access.READ)
        _bb_reader.register_key(key=Keys.PLAY_TASK, access=Access.READ)
        _bb_reader.register_key(key=Keys.IDLE_ENTERED_AT, access=Access.READ)
        _bb_reader.register_key(key=Keys.IDLE_TIMEOUT_SECONDS, access=Access.READ)
        _bb_reader.register_key(key=Keys.SEARCH_WAYPOINTS, access=Access.READ)
        _bb_reader.register_key(key=Keys.PATROL_CURRENT_INDEX, access=Access.READ)
    return _bb_reader


def _read_idle_countdown(fsm_state: str) -> tuple[float | None, float | None]:
    """IDLE 일 때 (remaining, total) 반환. 아니면 (None, total). 모니터 미설치 시 (None, None).

    - remaining = max(0, total - (monotonic_now - entered_at)). 모니터가 IDLE 진입 직후
      ``IDLE_ENTERED_AT`` 을 monotonic 으로 set, terminate 시 -1.0 으로 리셋.
    - total 은 IDLE 외 상태에서도 표시 — admin UI 가 "총 X분 / IDLE 시 카운트다운" 형태로
      쓸 수 있음.
    """
    bb = _ensure_bb_reader()
    try:
        total = float(bb.get(Keys.IDLE_TIMEOUT_SECONDS))
    except (KeyError, TypeError, ValueError):
        return None, None
    if fsm_state != "IDLE":
        return None, total
    try:
        entered_at = float(bb.get(Keys.IDLE_ENTERED_AT))
    except (KeyError, TypeError, ValueError):
        return None, total
    if entered_at < 0:
        return None, total
    elapsed = time.monotonic() - entered_at
    return max(0.0, total - elapsed), total


def _read_battery_level() -> float | None:
    """blackboard.BATTERY_LEVEL 을 안전하게 읽어 float 반환. 실패 시 None."""
    bb = _ensure_bb_reader()
    try:
        return float(bb.get(Keys.BATTERY_LEVEL))
    except (KeyError, TypeError, ValueError):
        return None


def _read_str_key(key: str) -> str:
    """blackboard 의 str 키를 안전하게 읽어 반환. 실패 시 빈 문자열."""
    bb = _ensure_bb_reader()
    try:
        return str(bb.get(key) or "")
    except (KeyError, TypeError):
        return ""


def _read_robot_pose() -> dict | None:
    """blackboard.ROBOT_POSE 를 안전하게 읽어 {x, y, yaw} 반환. 실패 시 None."""
    bb = _ensure_bb_reader()
    try:
        pose = bb.get(Keys.ROBOT_POSE)
        if not isinstance(pose, dict):
            return None
        return {
            "x": float(pose.get("x", 0.0)),
            "y": float(pose.get("y", 0.0)),
            "yaw": float(pose.get("yaw", 0.0)),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _read_patrol() -> dict | None:
    """blackboard 의 patrol 진행 상태 → {vertices, current_index} 또는 None.

    - vertices: BB.SEARCH_WAYPOINTS (list[str])
    - current_index: BB.PATROL_CURRENT_INDEX (-1 = idle, N = 완료)

    vertices 비어있고 current_index <= -1 이면 patrol 자체 미진행 — None 반환.
    """
    bb = _ensure_bb_reader()
    try:
        vertices_raw = bb.get(Keys.SEARCH_WAYPOINTS)
        idx_raw = bb.get(Keys.PATROL_CURRENT_INDEX)
    except (KeyError, TypeError):
        return None
    vertices = list(vertices_raw) if isinstance(vertices_raw, (list, tuple)) else []
    try:
        current_index = int(idx_raw) if idx_raw is not None else -1
    except (TypeError, ValueError):
        current_index = -1
    if not vertices and current_index <= -1:
        return None
    return {"vertices": vertices, "current_index": current_index}


def snapshot(
    fsm_state: str,
    root_tree: Any,
    map_cache: Any = None,
    robot_id: str = "gogoping",
) -> dict:
    """py_trees root 의 현재 상태를 admin BT 위젯 호환 dict 로 변환.

    Parameters
    ----------
    fsm_state : str
        FSM 의 ``current_state`` ("IDLE" / "ASSIST" / "PLAY" / "MANUAL" / ...)
    root_tree : py_trees.behaviour.Behaviour
        ``MainTree`` 의 root composite.
    map_cache : MapCache or None
        ``is_outside(x, y)`` 메서드 제공. None 이면 snapshot 의 ``in_map`` 도 None.
        실제 운영엔 ``ctx.map_cache`` 가 주입됨.
    robot_id : str
        snapshot 의 ``robot_id`` 필드 — admin 의 ``BTStateBar`` 가 행 식별에 사용 (현재
        는 1로봇이라 항상 ``"gogoping"``).
    """
    main_block = {
        "name": getattr(root_tree, "name", "?"),
        "children": _flatten_leaves(root_tree, depth=0),
    }

    sub_root = _find_subtree(root_tree, depth=0)
    sub_block: dict | None = None
    if sub_root is not None:
        sub_block = {
            "name": sub_root.name,
            "children": _flatten_leaves(sub_root, depth=0),
        }

    pose = _read_robot_pose()
    in_map: bool | None = None
    if pose is not None and map_cache is not None:
        try:
            outside = map_cache.is_outside(pose["x"], pose["y"])
            if outside is not None:
                in_map = not bool(outside)
        except Exception:
            in_map = None

    idle_remaining, idle_total = _read_idle_countdown(fsm_state)

    return {
        "robot_id": robot_id,
        "fsm_state": fsm_state,
        "assist_task": _read_str_key(Keys.ASSIST_TASK),   # "" / "goto" / "follow" / "lullaby"
        "play_task": _read_str_key(Keys.PLAY_TASK),       # "" / "hideseek"
        "main_tree": main_block,
        "sub_tree": sub_block,
        "battery_level": _read_battery_level(),
        "robot_pose": pose,
        "in_map": in_map,
        # IDLE → RETURNING 자동 복귀 카운트다운 — admin UI IdleTimeoutPanel 가 표시.
        # remaining: IDLE 일 때만 float, 아니면 None. total: 항상 float (totals 표시용).
        "idle_seconds_remaining": idle_remaining,
        "idle_timeout_seconds": idle_total,
        # patrol 진행 상태 — admin UI waypoint_map_card 가 시각화 (번호 / X / 강조).
        # None = patrol 미진행 (SEARCH_WAYPOINTS 빈 + current_index = -1).
        "patrol": _read_patrol(),
        "ts": time.time(),
    }


def _flatten_leaves(node: Any, depth: int) -> list[dict]:
    """node 의 모든 leaf 를 depth-first 로 평탄화. composite 자체는 제외."""
    if depth >= _MAX_DEPTH:
        return [_leaf_dict(node)]
    children = getattr(node, "children", None)
    if not children:
        return [_leaf_dict(node)]
    out: list[dict] = []
    for child in children:
        cls_name = type(child).__name__
        if cls_name in _COMPOSITE_CLASS_NAMES and getattr(child, "children", None):
            # composite — 재귀 (composite 본인은 안 표시)
            out.extend(_flatten_leaves(child, depth + 1))
        else:
            out.append(_leaf_dict(child))
    return out


def _leaf_dict(node: Any) -> dict:
    """단일 노드 → ``{name, status, disabled?}``.

    ``disabled`` 는 monitor 에 ``_disabled`` 속성이 있고 ``True`` 일 때만 ``True`` 로 포함
    (utils/safety_flags.py 의 is_safety_disabled 결과 저장한 monitor). admin UI 의
    BTStateInline 이 dim/strikethrough 로 시각 차별. ``_disabled`` 없거나 False 면
    키 자체를 생략 — snapshot 페이로드 부풀림 방지.
    """
    name = getattr(node, "name", "?")
    status = getattr(node, "status", None)
    status_name = status.name if status is not None else "INVALID"
    out: dict = {"name": name, "status": status_name}
    if getattr(node, "_disabled", False):
        out["disabled"] = True
    return out


def _find_subtree(node: Any, depth: int) -> Any | None:
    """RUNNING 인 BT_*_sub 첫 매칭 노드 반환 (없으면 None).

    현재 단계엔 stub 들이 BT_*_sub 이름이 아니므로 None 반환. + 진짜
    SubTree 작성 시 자동으로 잡힘.
    """
    if depth >= _MAX_DEPTH:
        return None
    name = getattr(node, "name", "")
    if name.startswith("BT_") and name.endswith("_sub"):
        # status 가 RUNNING 일 때만 — 비활성 SubTree 는 표시 안 함
        from py_trees.common import Status
        if getattr(node, "status", None) == Status.RUNNING:
            return node
    children = getattr(node, "children", None)
    if not children:
        return None
    for child in children:
        found = _find_subtree(child, depth + 1)
        if found is not None:
            return found
    return None


__all__ = ["snapshot"]
