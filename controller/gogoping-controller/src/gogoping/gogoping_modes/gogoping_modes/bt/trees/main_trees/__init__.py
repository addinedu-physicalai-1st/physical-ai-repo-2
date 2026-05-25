"""MainTree 빌더 dispatcher — FSM state 이름 → BT root.

평탄화 (2026-05-25): 8 → 10 state. ASSIST/PLAY 제거, GOTO/FOLLOW/LULLABY/HIDEANDSEEK 추가.

``main.py._on_state_change`` 에서 ``build_main_tree(state, ctx)`` 호출.
state 이름이 STATES 와 일치하면 해당 모듈의 ``build(ctx)`` 위임.
"""
from __future__ import annotations

import py_trees

from ....context import Context
from . import (
    BT_charging_main,
    BT_error_main,
    BT_follow_main,
    BT_goto_main,
    BT_hide_and_seek_main,
    BT_idle_main,
    BT_low_battery_returning_main,
    BT_lullaby_main,
    BT_manual_main,
    BT_returning_main,
)


_BUILDERS = {
    "IDLE":                BT_idle_main.build,
    "CHARGING":            BT_charging_main.build,
    "GOTO":                BT_goto_main.build,
    "FOLLOW":              BT_follow_main.build,
    "LULLABY":             BT_lullaby_main.build,
    "HIDEANDSEEK":         BT_hide_and_seek_main.build,
    "MANUAL":              BT_manual_main.build,
    "RETURNING":           BT_returning_main.build,
    "LOW_BATTERY_RETURNING":  BT_low_battery_returning_main.build,
    "ERROR":               BT_error_main.build,
}


def build_main_tree(state: str, ctx: Context) -> py_trees.behaviour.Behaviour:
    """state 에 해당하는 MainTree root 반환. 미정의 state 면 ValueError."""
    builder = _BUILDERS.get(state)
    if builder is None:
        raise ValueError(f"no MainTree builder for state {state!r}")
    return builder(ctx)


__all__ = ["build_main_tree"]
