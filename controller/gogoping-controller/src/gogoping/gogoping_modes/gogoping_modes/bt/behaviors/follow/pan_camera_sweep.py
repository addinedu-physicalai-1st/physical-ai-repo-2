"""PanCameraSweep — 카메라 pan 을 시간 기반 시퀀스로 좌우 sweep 후 SUCCESS.

기본 시퀀스: ``90° → 30° → 150° → 90°``. 각 step ``1.5초`` hold (총 ≈ 6초).
서보 watchdog (1000ms) 안에서 servo_bridge 가 20Hz 로 setpoint 재송신하므로 본 behavior 는
step 진입 시 1회만 ``ctx.camera_pan.publish_pan(deg)`` 호출.

순찰 (BT_patrol_sub) 의 vertex 마다 ``NavigateToVertex`` 다음에 본 sweep 1회를 끼워 넣어
"도착 → 좌우 확인" 동작을 만든다.

## Cancel 안전

상위 트리 swap (force-state / cancel) 으로 ``terminate(Status.INVALID)`` 가 들어오면
``ctx.camera_pan.center()`` 한 번 publish — 다음 step 발행 막고 90° 로 복귀. 외부에서
다시 활성화돼도 ``initialise()`` 가 step 0 부터 재시작.

## ROS 의존성

``ctx.camera_pan`` (CameraPanClient) 의 publisher 가 ``main.py`` 의 Context 생성 시점에
이미 만들어져 있다는 가정. setup() 추가 작업 없음.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable, Sequence

import py_trees
from py_trees.common import Status

if TYPE_CHECKING:
    from ....context import Context


# 기본 시퀀스 — center → 좌 → 우 → center.
DEFAULT_STEPS_DEG: tuple[float, ...] = (90.0, 30.0, 150.0, 90.0)
DEFAULT_STEP_DURATION_SEC: float = 1.5


class PanCameraSweep(py_trees.behaviour.Behaviour):
    """카메라 pan sweep behavior.

    Parameters
    ----------
    name : str
        py_trees node name.
    context : Context
        ``ctx.camera_pan`` (CameraPanClient) 사용.
    steps_deg : Sequence[float], optional
        sweep 각도 시퀀스. 기본 ``(90, 30, 150, 90)``.
    step_duration_sec : float, optional
        각 step hold 초. 기본 ``1.5``.
    now_fn : Callable[[], float], optional
        시간 소스 (테스트용 mock). 기본 ``time.monotonic``.
    """

    def __init__(
        self,
        name: str,
        context: "Context",
        *,
        steps_deg: Sequence[float] = DEFAULT_STEPS_DEG,
        step_duration_sec: float = DEFAULT_STEP_DURATION_SEC,
        now_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(name)
        self.ctx = context
        self._steps: tuple[float, ...] = tuple(float(s) for s in steps_deg)
        if not self._steps:
            raise ValueError("PanCameraSweep: steps_deg must be non-empty")
        self._step_duration: float = float(step_duration_sec)
        if self._step_duration <= 0:
            raise ValueError("PanCameraSweep: step_duration_sec must be > 0")
        self._now: Callable[[], float] = now_fn
        # 런타임 상태 — initialise 에서 reset.
        self._step_idx: int = 0
        self._step_started_at: float = 0.0

    # ------------------------------------------------------------------- lifecycle

    def initialise(self) -> None:
        """step 0 진입 — 첫 각도 즉시 publish."""
        self._step_idx = 0
        self._step_started_at = self._now()
        try:
            self.ctx.camera_pan.publish_pan(self._steps[0])
        except Exception as e:
            # publisher 미준비 등 — log 만 하고 진행 (다음 step 에서 또 시도)
            self._log_warn(f"publish_pan 실패 (step 0): {e!r}")

    def update(self) -> Status:
        elapsed = self._now() - self._step_started_at
        if elapsed < self._step_duration:
            return Status.RUNNING
        # 다음 step 으로
        self._step_idx += 1
        if self._step_idx >= len(self._steps):
            return Status.SUCCESS
        self._step_started_at = self._now()
        try:
            self.ctx.camera_pan.publish_pan(self._steps[self._step_idx])
        except Exception as e:
            self._log_warn(f"publish_pan 실패 (step {self._step_idx}): {e!r}")
        return Status.RUNNING

    def terminate(self, new_status: Status) -> None:
        """cancel (INVALID) 시 90° 복귀. SUCCESS/FAILURE 는 마지막 step 이 이미 center 라 별도 처리 X."""
        if new_status == Status.INVALID:
            try:
                self.ctx.camera_pan.center()
            except Exception as e:
                self._log_warn(f"center() 실패 (terminate INVALID): {e!r}")

    # ------------------------------------------------------------------- helpers

    def _log_warn(self, msg: str) -> None:
        node = getattr(self.ctx, "node", None)
        if node is not None:
            try:
                node.get_logger().warning(f"[{self.name}] {msg}")
                return
            except Exception:
                pass
        # logger 미접근 — 테스트 환경 등
        print(f"[PanCameraSweep:{self.name}] {msg}")
