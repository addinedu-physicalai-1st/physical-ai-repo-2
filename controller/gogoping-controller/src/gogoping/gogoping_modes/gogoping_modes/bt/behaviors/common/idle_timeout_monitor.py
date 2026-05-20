"""IdleTimeoutMonitor — IDLE 진입 후 N초 무명령 시 ``idle_timeout`` 발화.

BT_idle_main 에만 배치 — 무인 환경에서 자율 도크 복귀 (IDLE → RETURNING).

monitor 컨벤션 (``docs/conventions.md`` §2):
- 매 tick RUNNING 리턴 (SUCCESS / FAILURE 금지)
- edge-triggered — 1회 발화 후 재발화 안 함 (initialise() 에서 리셋)
- ``initialise()`` 가 BT swap 마다 호출 → IDLE 재진입 시 timer 리셋 (battery_low 등이 IDLE 떠난 후 다시 돌아오면 timer 새로 시작)

타이밍 소스: ``time.monotonic()`` — 시스템 시계 변경에 영향 받지 않음.

ROS param ``idle_timeout_seconds`` (기본 86400.0 = 24시간 — 시연/데모 환경에서 자동
복귀 없이 안정적) 로 임계값 조정 — `context.node.declare_parameter` 에서 한 번만 등록
(이미 다른 곳에서 등록돼 있어도 ParameterAlreadyDeclaredException 안전).
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

import py_trees
from py_trees.common import Access, Status

from ...blackboard import Keys

if TYPE_CHECKING:
    from ....context import Context


_DEFAULT_TIMEOUT_S = 86400.0
_PARAM_NAME = "idle_timeout_seconds"


class IdleTimeoutMonitor(py_trees.behaviour.Behaviour):
    """IDLE 진입 후 ``idle_timeout_seconds`` 경과 시 ``idle_timeout`` trigger.

    Blackboard write (admin UI 카운트다운 표시용):
      - ``IDLE_ENTERED_AT``: initialise=time.monotonic(), terminate=-1.0
      - ``IDLE_TIMEOUT_SECONDS``: __init__ 에서 param 값. admin UI 의 카운트다운 totals.
    """

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

        # Blackboard write 권한 — admin UI 카운트다운 publish 용.
        # conventions.md §2.1 — attach_blackboard_client + register_key WRITE.
        self.bb = self.attach_blackboard_client(name=self.name)
        self.bb.register_key(key=Keys.IDLE_ENTERED_AT, access=Access.WRITE)
        self.bb.register_key(key=Keys.IDLE_TIMEOUT_SECONDS, access=Access.WRITE)
        # __init__ 시점에 timeout 값 1회 publish — IDLE 안 들어가도 admin UI 가
        # totals 표시할 수 있도록.
        self.bb.set(Keys.IDLE_TIMEOUT_SECONDS, self._timeout_s)

        # 런타임 param 변경 즉시 반영 — admin UI 의 조정 슬라이더가 SetParameters 호출
        # 시 self._timeout_s + blackboard 갱신 + (선택) fired 플래그 리셋.
        # add_on_set_parameters_callback 은 같은 노드에서 여러 개 등록 가능 — IDLE
        # 외 다른 monitor 가 이미 등록했어도 안전. 콜백은 SetParametersResult 반환.
        if node is not None:
            try:
                node.add_on_set_parameters_callback(self._on_set_params)
            except Exception:
                # rclpy 버전에 따라 메서드명/시그니처 다를 수 있음 — 실패 시 silent
                # (그래도 다음 IDLE 진입 시 param 값을 다시 읽지는 않으므로 즉시 반영만
                # 안 될 뿐 기존 노드 동작은 영향 없음)
                pass

    def _on_set_params(self, params: list) -> "SetParametersResult":   # type: ignore[name-defined]
        """ROS param SetParameters 콜백 — idle_timeout_seconds 즉시 반영.

        admin UI 가 ``/api/gogoping/idle_timeout`` 호출 → control-service SetParameters
        client → 이 콜백. self._timeout_s + blackboard 갱신. IDLE 중이면 update() 가
        다음 tick 에 새 임계로 판정 (이미 임계 초과 상태면 다음 tick 에 idle_timeout
        trigger 발화 — 자연스러움).
        """
        from rcl_interfaces.msg import SetParametersResult
        for p in params:
            if p.name == _PARAM_NAME:
                try:
                    new_value = float(p.value)
                except (TypeError, ValueError):
                    return SetParametersResult(successful=False, reason="not a float")
                if new_value < 1.0 or new_value > 86400.0:
                    return SetParametersResult(
                        successful=False, reason="out of range [1.0, 86400.0]",
                    )
                self._timeout_s = new_value
                self.bb.set(Keys.IDLE_TIMEOUT_SECONDS, self._timeout_s)
                # 임계가 짧아졌고 이미 그 시간이 경과한 IDLE 상태라면 _fired 리셋해서
                # 다음 update() 가 즉시 발화하게. (시각적으로 카운트다운이 0 으로
                # 떨어진 직후 RETURNING 으로 전이.)
                self._fired = False
        return SetParametersResult(successful=True)

    def initialise(self) -> None:
        """IDLE 진입 시각 저장 + 발화 플래그 리셋 + blackboard publish."""
        self._entered_at = time.monotonic()
        self._fired = False
        self.bb.set(Keys.IDLE_ENTERED_AT, self._entered_at)
        # 현재 timeout 값 publish — _on_set_params 가 이미 갱신했지만 IDLE 재진입 시점에
        # 다시 한번 보정.
        self.bb.set(Keys.IDLE_TIMEOUT_SECONDS, self._timeout_s)

    def update(self) -> Status:
        if not self._fired and self._entered_at is not None:
            elapsed = time.monotonic() - self._entered_at
            if elapsed >= self._timeout_s:
                self._fired = True
                self.ctx.fsm.trigger("idle_timeout")
        return Status.RUNNING

    def terminate(self, new_status: Status) -> None:
        # IDLE 떠남 — admin UI 가 "IDLE 아님" 으로 표시하도록 -1.0 publish.
        # idempotent (단순 set).
        self.bb.set(Keys.IDLE_ENTERED_AT, -1.0)
