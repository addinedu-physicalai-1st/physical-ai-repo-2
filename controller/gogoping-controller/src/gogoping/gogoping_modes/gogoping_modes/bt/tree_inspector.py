"""Tree inspector — py_trees root → admin BT 위젯 snapshot dict.

호출자: ``main.py._tick()`` 의 1Hz publish 루프.
출력 포맷: ``app/admin-app/widgets/bt_state_inline.py`` 의 ``update_snapshot()`` 호환.

snapshot 구조::

    {
      "robot_id": "gogoping",
      "fsm_state": "ASSIST",
      "main_tree": {
        "name": "BT_assist_main",
        "children": [
          {"name": "CommandListener",                       "status": "RUNNING"},
          {"name": "CheckTask(assist_task=='carry')",       "status": "SUCCESS"},
          {"name": "StubCarry",                             "status": "RUNNING"},
          {"name": "CheckTask(assist_task=='follow')",      "status": "INVALID"},
          {"name": "StubFollow",                            "status": "INVALID"},
          ...
        ]
      },
      "sub_tree": null,    # Day 3+ 에 BT_*_sub 이름 패턴 매칭 시 채워짐
      "ts": 1730000035.123
    }

## 두 가지 flatten 정책

- **main_tree.children**: root 의 모든 leaf 를 깊이 우선으로 평탄화 후 (name, status) 만.
  composite (Selector/Sequence/Parallel) 자체는 표시 안 함 — 자식만. RUNNING 가 아닌
  leaves (SUCCESS/FAILURE/INVALID) 도 포함해서 진행도 표시 (admin 위젯이 status 별
  시각 차별 적용).
- **sub_tree**: ``BT_*_sub`` naming convention 으로 식별. Day 3+ 진짜 SubTree 가 생기면
  자동으로 잡힘. Day 1 walking skeleton 의 stub 들 (StubCarry 등) 은 BT_*_sub 이름이
  아니라 *main_tree.children* 에 그대로 평탄화됨.
"""
from __future__ import annotations

import time
from typing import Any


# composite 클래스 이름 — py_trees 내장 (Selector / Sequence / Parallel).
_COMPOSITE_CLASS_NAMES = frozenset({"Selector", "Sequence", "Parallel"})

_MAX_DEPTH = 6  # 안전망 — 사이클 / 무한 nesting 방지


def snapshot(
    fsm_state: str,
    root_tree: Any,
    robot_id: str = "gogoping",
) -> dict:
    """py_trees root 의 현재 상태를 admin BT 위젯 호환 dict 로 변환.

    Parameters
    ----------
    fsm_state : str
        FSM 의 ``current_state`` ("IDLE" / "ASSIST" / "PLAY" / "MANUAL" / ...)
    root_tree : py_trees.behaviour.Behaviour
        ``MainTree`` 의 root composite.
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

    return {
        "robot_id": robot_id,
        "fsm_state": fsm_state,
        "main_tree": main_block,
        "sub_tree": sub_block,
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
    """단일 노드 → {name, status}."""
    name = getattr(node, "name", "?")
    status = getattr(node, "status", None)
    status_name = status.name if status is not None else "INVALID"
    return {"name": name, "status": status_name}


def _find_subtree(node: Any, depth: int) -> Any | None:
    """RUNNING 인 BT_*_sub 첫 매칭 노드 반환 (없으면 None).

    Day 1 단계엔 stub 들이 BT_*_sub 이름이 아니므로 None 반환. Day 3+ 진짜
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
