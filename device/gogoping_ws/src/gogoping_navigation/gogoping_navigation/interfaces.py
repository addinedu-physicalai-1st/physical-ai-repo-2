"""Python Protocol interfaces for BT/FSM dependency injection.

BT leaf 나 FSM 콜백이 구체 구현 (NavDispatcher, GraphRouter 등) 을 직접 import
하지 않도록 추상화. Mock 으로 단위 테스트 가능.
"""
from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable


@runtime_checkable
class NavDispatcherInterface(Protocol):
    """Nav2 NavigateThroughPoses 호출 추상화.

    구체 구현: gogoping_carry.nav_dispatcher.NavDispatcher
    Mock:     test 에서 직접 정의
    """

    def dispatch(
        self,
        poses: list,
        on_arrived: Callable[[], None],
        on_failed: Callable[[str], None],
    ) -> None:
        ...

    def cancel(self) -> None:
        ...


@runtime_checkable
class GraphRouterInterface(Protocol):
    """그래프 최단경로 계산 추상화.

    구체 구현: server/control/nav_router.py 의 GraphRouter
    또는 device 측 in-process 구현
    """

    def nearest_vertex(self, x: float, y: float) -> dict:
        ...

    def plan(
        self,
        start_xy: tuple[float, float],
        goal_xy: tuple[float, float],
    ) -> list[dict]:
        ...
