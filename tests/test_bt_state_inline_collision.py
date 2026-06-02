"""BTStateInline 의 CollisionMonitor leaf 가 collision_state 에 따라 시각 차별되는지.

CollisionMonitor leaf 는 항상 RUNNING 만 반환 → 트리뷰 기본 렌더로는 "ok" / "stop" 구분 불가.
그래서 snapshot 의 top-level ``collision_state`` 를 leaf 렌더에 주입해, "stop" 일 때 다른
leaf 와 구분되는 경고 표시(⛔ + danger 색)로 그린다.

순수 함수 ``_render_child_html`` 만 검증 — QApplication 불필요. PyQt5 미설치 시 skip.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PyQt5")

from theme import COLORS  # noqa: E402
from widgets.bt_state_inline import _render_child_html  # noqa: E402


def test_collision_monitor_stop_renders_warning():
    """collision_state="stop" → CollisionMonitor leaf 가 danger 색 + ⛔ 경고로."""
    html = _render_child_html(
        {"name": "CollisionMonitor", "status": "RUNNING"},
        collision_state="stop",
    )
    assert "CollisionMonitor" in html
    assert "⛔" in html
    assert COLORS["danger"] in html


def test_collision_monitor_ok_renders_normal_running():
    """collision_state="ok" → 평범한 RUNNING 표시(● bold), 경고 표시 없음."""
    html = _render_child_html(
        {"name": "CollisionMonitor", "status": "RUNNING"},
        collision_state="ok",
    )
    assert "●" in html
    assert "⛔" not in html


def test_collision_monitor_missing_state_renders_normal():
    """collision_state 미전달(None)이어도 기존처럼 RUNNING 렌더 — 회귀 방지."""
    html = _render_child_html({"name": "CollisionMonitor", "status": "RUNNING"})
    assert "●" in html
    assert "⛔" not in html


def test_other_leaf_unaffected_by_collision_stop():
    """stop 이어도 CollisionMonitor 가 아닌 leaf 는 일반 RUNNING 렌더 그대로."""
    html = _render_child_html(
        {"name": "CommandListener", "status": "RUNNING"},
        collision_state="stop",
    )
    assert "●" in html
    assert "⛔" not in html


def test_disabled_escalation_still_shows_live_collision_stop():
    """escalation disable(_disabled) 여도 충돌 감지는 살아있으니 stop 이면 ⛔ 표시.

    nav2 collision_monitor 노드 + collision_subscriber 는 disable_error_safety 와 무관하게
    항상 동작 → leaf 가 5분 escalation off 여도 live collision_state 를 그대로 보여줘야 한다.
    "실행 중인데 disabled" 거짓 표시 방지.
    """
    html = _render_child_html(
        {"name": "CollisionMonitor", "status": "RUNNING", "disabled": True},
        collision_state="stop",
    )
    assert "⛔" in html
    assert "disabled" not in html


def test_disabled_escalation_ok_shows_running_not_disabled():
    """escalation disable + ok → ● 감시 중 표시 (disabled 아님). 감지는 항상 실행 중."""
    html = _render_child_html(
        {"name": "CollisionMonitor", "status": "RUNNING", "disabled": True},
        collision_state="ok",
    )
    assert "●" in html
    assert "disabled" not in html
