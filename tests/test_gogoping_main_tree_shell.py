"""build_active_main_tree helper 단위 테스트.

monitor flag 조합별로 어떤 자식이 추가/제외되는지, body 가 마지막에 들어가는지,
policy 가 의도대로 SuccessOnSelected 인지 검증.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import py_trees
from py_trees.common import ParallelPolicy
import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

from gogoping_modes.bt.trees.main_trees._shell import build_active_main_tree  # noqa: E402


def _ctx():
    """모든 interface 가 mock 인 가짜 Context — behavior 생성 시 ROS 호출 안 함."""
    return SimpleNamespace(
        node=MagicMock(),
        fsm=MagicMock(),
        battery=MagicMock(),
        pose=MagicMock(),
        cmd_vel=MagicMock(),
        ui=MagicMock(),
        nav=MagicMock(),
        graph=MagicMock(),
    )


def _child_names(tree):
    return [c.name for c in tree.children]


def test_default_includes_battery_low_collision_hw_command():
    body = py_trees.behaviours.Success(name="DummyBody")
    tree = build_active_main_tree("MainTree[GOTO]", _ctx(), body=body)
    names = _child_names(tree)
    assert "BatteryLowMonitor" in names
    assert "MapBoundaryMonitor" in names
    assert "HardwareHealthMonitor" in names
    assert "CommandListener" in names
    assert names[-1] == "DummyBody"   # body 는 항상 마지막


def test_manual_policy_disables_battery_collision_hw():
    body = py_trees.behaviours.Success(name="ManualTorqueHold")
    tree = build_active_main_tree(
        "MainTree[MANUAL]", _ctx(), body=body,
        include_battery_low=False,
        include_collision=False,
        include_hw_health=False,
    )
    names = _child_names(tree)
    assert "BatteryLowMonitor" not in names
    assert "HardwareHealthMonitor" not in names
    assert "MapBoundaryMonitor" in names    # MANUAL 도 MapBoundary 만 예외 배치
    assert "CommandListener" in names


def test_low_battery_return_disables_command_listener():
    body = py_trees.behaviours.Success(name="ReturnBody")
    tree = build_active_main_tree(
        "MainTree[LOW_BATTERY_RETURNING]", _ctx(), body=body,
        include_battery_low=False,        # 이미 자기가 결과물
        include_command_listener=False,   # lockdown
    )
    names = _child_names(tree)
    assert "CommandListener" not in names


def test_charging_uses_battery_full_not_low():
    body = py_trees.behaviours.Success(name="ChargingBody")
    tree = build_active_main_tree(
        "MainTree[CHARGING]", _ctx(), body=body,
        include_battery_low=False,
        include_battery_full=True,
        include_collision=False,
    )
    names = _child_names(tree)
    assert "BatteryFullMonitor" in names
    assert "BatteryLowMonitor" not in names


def test_idle_includes_idle_timeout():
    body = py_trees.behaviours.Success(name="IdleBody")
    tree = build_active_main_tree(
        "MainTree[IDLE]", _ctx(), body=body,
        include_idle_timeout=True,
        include_collision=False,
    )
    names = _child_names(tree)
    assert "IdleTimeoutMonitor" in names


def test_body_is_selected_for_root_success():
    """task state 의 경우 body SUCCESS → root SUCCESS 가 되도록 SuccessOnSelected.

    그래야 main.py 의 _on_tree_success 가 task_done 발화 가능.
    """
    body = py_trees.behaviours.Success(name="GoToBody")
    tree = build_active_main_tree(
        "MainTree[GOTO]", _ctx(), body=body,
        task_body=True,
    )
    # policy 가 SuccessOnSelected 인지
    assert isinstance(tree.policy, ParallelPolicy.SuccessOnSelected)
    # selected children 안에 body 가 (instance 동일성으로) 들어있는지
    assert any(c is body for c in tree.policy.children)


def test_non_task_body_uses_success_on_all():
    """task body 가 아니면 SuccessOnAll (IDLE/CHARGING/MANUAL/ERROR 등)."""
    body = py_trees.behaviours.Success(name="IdleBody")
    tree = build_active_main_tree(
        "MainTree[IDLE]", _ctx(), body=body,
        task_body=False,
    )
    assert isinstance(tree.policy, ParallelPolicy.SuccessOnAll)
