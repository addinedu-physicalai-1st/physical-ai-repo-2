"""MainTree 빌더 dispatcher — FSM state 이름 → BT root.

``main.py._on_state_change`` 에서 ``build_main_tree(state, ctx)`` 호출.
state 이름이 STATES 와 일치하면 해당 모듈의 ``build(ctx)`` 위임.
"""
from __future__ import annotations

import py_trees

from ....context import Context
from . import (
    BT_assist_main,
    BT_charging_main,
    BT_error_main,
    BT_idle_main,
    BT_manual_main,
    BT_play_main,
    BT_returning_main,
)


_BUILDERS = {
    "CHARGING":  BT_charging_main.build,
    "IDLE":      BT_idle_main.build,
    "ASSIST":    BT_assist_main.build,
    "PLAY":      BT_play_main.build,
    "MANUAL":    BT_manual_main.build,
    "RETURNING": BT_returning_main.build,
    "ERROR":     BT_error_main.build,
}


def build_main_tree(state: str, ctx: Context) -> py_trees.behaviour.Behaviour:
    """state 에 해당하는 MainTree root 반환. 미정의 state 면 ValueError."""
    builder = _BUILDERS.get(state)
    if builder is None:
        raise ValueError(f"no MainTree builder for state {state!r}")
    return builder(ctx)


__all__ = ["build_main_tree"]
