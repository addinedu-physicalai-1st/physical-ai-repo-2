"""IdleTimeoutMonitor — IDLE 진입 후 N초 무명령 시 ``idle_timeout`` 발화.

BT_idle_main 에만 배치 — 무인 환경에서 자율 도크 복귀 (IDLE → RETURNING).

monitor 컨벤션 (``docs/conventions.md`` §2):
- 매 tick RUNNING 리턴 (SUCCESS / FAILURE 금지)
- edge-triggered — 1회 발화 후 재발화 안 함 (initialise() 에서 리셋)
- ``initialise()`` 가 BT swap 마다 호출 → IDLE 재진입 시 timer 리셋 (battery_low 등이 IDLE 떠난 후 다시 돌아오면 timer 새로 시작)

타이밍 소스: ``time.monotonic()`` — 시스템 시계 변경에 영향 받지 않음.

ROS param ``idle_timeout_seconds`` (기본 60.0) 로 임계값 조정 — `context.node.declare_parameter`
에서 한 번만 등록 (이미 다른 곳에서 등록돼 있어도 ParameterAlreadyDeclaredException 안전).
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

import py_trees
from py_trees.common import Status

if TYPE_CHECKING:
    from ....context import Context


_DEFAULT_TIMEOUT_S = 86400.0
_PARAM_NAME = "idle_timeout_seconds"


class IdleTimeoutMonitor(py_trees.behaviour.Behaviour):
    """IDLE 진입 후 ``idle_timeout_seconds`` 경과 시 ``idle_timeout`` trigger."""

    def __init__(self, name: str, context: "Context"):
        super().__init__(name)
        self.ctx = context
        self._entered_at: float | None = None
        self._fired = False
        self._timeout_s = _DEFAULT_TIMEOUT_S

        # ROS param 등록 — 이미 다른 곳에서 등록돼 있어도 안전
        node = getattr(self.ctx, "node", None)
        if node is not None:
            try:
                node.declare_parameter(_PARAM_NAME, _DEFAULT_TIMEOUT_S)
            except Exception:
                pass  # 이미 등록된 경우 (Rclpy ParameterAlreadyDeclaredException) 무시
            try:
                self._timeout_s = float(
                    node.get_parameter(_PARAM_NAME).get_parameter_value().double_value
                ) or _DEFAULT_TIMEOUT_S
            except Exception:
                self._timeout_s = _DEFAULT_TIMEOUT_S

    def initialise(self) -> None:
        """IDLE 진입 시각 저장 + 발화 플래그 리셋."""
        self._entered_at = time.monotonic()
        self._fired = False

    def update(self) -> Status:
        if not self._fired and self._entered_at is not None:
            elapsed = time.monotonic() - self._entered_at
            if elapsed >= self._timeout_s:
                self._fired = True
                self.ctx.fsm.trigger("idle_timeout")
        return Status.RUNNING

    def terminate(self, new_status: Status) -> None:
        # idempotent — 별도 cleanup 없음 (timer 는 단순 변수)
        pass
