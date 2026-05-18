"""BT_return_sub 빌더 단위 테스트.

- _seed_blackboard 가 yaml 의 충전소입구 vertex.yaw 를 정확히 blackboard 에 세팅하는지
- build_return_subtree 가 OneShot(Sequence(NavTo, Align, Reverse)) 구조를 만드는지
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

import py_trees  # noqa: E402

from gogoping_modes.bt.blackboard import Keys, init_blackboard  # noqa: E402
from gogoping_modes.bt.trees.sub_trees.BT_return_sub import (  # noqa: E402
    _load_vertex_yaw,
    build_return_subtree,
)


class _Ctx:
    def __init__(self) -> None:
        self.node = None
        self.cmd_vel_pub = None


@pytest.fixture(autouse=True)
def _init_bb():
    init_blackboard()


def test_load_vertex_yaw_finds_charging_dock_entry():
    """yaml 의 충전소입구 yaw 가 -π/2 (=-1.5708) 인지 — Step 1 에서 사용자가 세팅."""
    yaw = _load_vertex_yaw("충전소입구")
    assert math.isclose(yaw, -math.pi / 2, abs_tol=1e-4)


def test_load_vertex_yaw_unknown_returns_zero():
    """존재하지 않는 vertex 는 0.0."""
    assert _load_vertex_yaw("존재하지않는vertex") == 0.0


def test_build_returns_oneshot_decorator():
    """빌더가 OneShot 데코레이터를 반환."""
    ctx = _Ctx()
    root = build_return_subtree(ctx)
    assert isinstance(root, py_trees.decorators.OneShot)


def test_build_inner_is_sequence_with_three_children():
    """OneShot 의 자식은 Sequence, 자식 3개."""
    ctx = _Ctx()
    root = build_return_subtree(ctx)
    inner = root.decorated
    assert isinstance(inner, py_trees.composites.Sequence)
    assert len(inner.children) == 3


def test_build_seeds_blackboard_with_approach_key_and_yaw():
    """빌더 호출 후 blackboard 에 충전소입구 + 그 yaw 가 세팅돼 있어야."""
    ctx = _Ctx()
    build_return_subtree(ctx)

    bb = py_trees.blackboard.Client(name="_read_bb")
    bb.register_key(key=Keys.CHARGING_DOCK_APPROACH_KEY, access=py_trees.common.Access.READ)
    bb.register_key(key=Keys.CHARGING_DOCK_TARGET_YAW, access=py_trees.common.Access.READ)

    assert bb.get(Keys.CHARGING_DOCK_APPROACH_KEY) == "충전소입구"
    assert math.isclose(
        bb.get(Keys.CHARGING_DOCK_TARGET_YAW), -math.pi / 2, abs_tol=1e-4
    )


def test_children_order_navigate_align_reverse():
    """Sequence 자식 순서가 NavigateToVertex → AlignToDock → ReverseIntoDock."""
    from gogoping_modes.bt.behaviors.navigation.align_to_dock import AlignToDock
    from gogoping_modes.bt.behaviors.navigation.navigate_to_vertex import NavigateToVertex
    from gogoping_modes.bt.behaviors.navigation.reverse_into_dock import ReverseIntoDock

    ctx = _Ctx()
    root = build_return_subtree(ctx)
    inner = root.decorated
    assert isinstance(inner.children[0], NavigateToVertex)
    assert isinstance(inner.children[1], AlignToDock)
    assert isinstance(inner.children[2], ReverseIntoDock)
