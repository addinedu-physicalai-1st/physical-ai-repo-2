"""collision_subscriber 의 action_type → COLLISION_STATE 매핑 테스트 (pure)."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

from gogoping_modes.interfaces.collision_subscriber import (  # noqa: E402
    collision_state_from_action,
)


def test_do_nothing_is_ok():
    assert collision_state_from_action(0) == "ok"


def test_stop_action_is_stop():
    assert collision_state_from_action(1) == "stop"  # STOP


def test_other_nonzero_actions_are_stop():
    # stop-only 설정이지만 방어적으로 nonzero(slowdown/approach 등)도 stop 취급
    for a in (2, 3, 4):
        assert collision_state_from_action(a) == "stop"
