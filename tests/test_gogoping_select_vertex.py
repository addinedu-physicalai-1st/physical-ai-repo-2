"""SelectVertex behavior 단위 테스트.

- update() 가 즉시 SUCCESS
- blackboard.target_vertex_name 에 생성자 vertex_name 이 W 됨
- 여러 인스턴스가 같은 키에 W 등록해도 register 충돌 없음
"""
from __future__ import annotations

import sys
from pathlib import Path

import py_trees
from py_trees.common import Status

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

from gogoping_modes.bt.behaviors.patrol.select_vertex import (  # noqa: E402
    TARGET_VERTEX_KEY,
    SelectVertex,
)


def _reader_client(name: str):
    """target_vertex_name READ 권한 client — 테스트가 BB 값을 확인하기 위함."""
    c = py_trees.blackboard.Client(name=name)
    c.register_key(key=TARGET_VERTEX_KEY, access=py_trees.common.Access.READ)
    return c


def setup_function():
    """매 테스트 전에 global blackboard 청소 — 이전 테스트의 client 잔재 제거."""
    py_trees.blackboard.Blackboard.clear()


def test_update_returns_success():
    b = SelectVertex(name="select_A", vertex_name="A")
    assert b.update() == Status.SUCCESS


def test_writes_vertex_name_to_blackboard():
    b = SelectVertex(name="select_A", vertex_name="교실A")
    b.update()
    reader = _reader_client("reader")
    assert reader.get(TARGET_VERTEX_KEY) == "교실A"


def test_overwrites_on_subsequent_tick():
    b = SelectVertex(name="select_B", vertex_name="B1")
    b.update()
    reader = _reader_client("reader2")
    assert reader.get(TARGET_VERTEX_KEY) == "B1"
    # 같은 인스턴스 재 tick — 값 그대로 유지 (고정 vertex_name 이라)
    b.update()
    assert reader.get(TARGET_VERTEX_KEY) == "B1"


def test_multiple_instances_no_register_conflict():
    """vertex 마다 인스턴스 N 개 만들어도 register 충돌 없음 (unique client name)."""
    a = SelectVertex(name="select_A", vertex_name="A")
    b = SelectVertex(name="select_B", vertex_name="B")
    c = SelectVertex(name="select_C", vertex_name="C")
    # 순차 tick — last writer 가 최종 값
    a.update(); b.update(); c.update()
    reader = _reader_client("reader3")
    assert reader.get(TARGET_VERTEX_KEY) == "C"


def test_custom_target_key():
    """target_key 인자로 다른 BB 키에 W 도 가능."""
    b = SelectVertex(name="select_custom", vertex_name="X", target_key="alt_vertex")
    b.update()
    c = py_trees.blackboard.Client(name="reader_alt")
    c.register_key(key="alt_vertex", access=py_trees.common.Access.READ)
    assert c.get("alt_vertex") == "X"
