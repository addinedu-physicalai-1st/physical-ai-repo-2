"""PanCameraSweep — 카메라 pan 을 rate(°/s) 기반으로 천천히 sweep (+ 선택적 tilt 브래킷).

기본 시퀀스: ``90° → 10° → 170° → 90°`` (중앙 → 좌 → 우 → 중앙).
각 step 은 **이동(move) → 정지(hold)** 2 phase:
  - move: ``pan_speed_deg_per_s`` 일정 속도로 이전 각도 → 목표 각도 보간 publish.
    이동 시간 = ``|Δ각도| / speed``. 예) 20°/s 면 80°→4초, 160°→8초.
  - hold: 목표 각도에서 그 step 의 ``hold_secs`` 동안 정지 (publish 유지).
    ``hold_secs`` 는 step 별 list (예: ``(0, 5, 5, 0)`` — 좌·우만 5초, 중앙은 0) 또는
    단일 float (전 step 동일).

tilt(위아래) 브래킷 — ``tilt_deg`` 지정 시:
  - ``initialise()`` 에서 tilt 를 ``tilt_deg`` 로 1회 설정 (sweep 시작 전).
  - 종료(``terminate`` — SUCCESS/INVALID 등) 시 tilt 를 ``rest_tilt_deg`` 로 복원.
  지정 안 하면 tilt 토픽을 건드리지 않음 (pan 전용 기존 동작).

servo_bridge 가 자체 ``rate_limit_deg_per_s`` 로 또 제한하지만, 본 behavior 의
보간 속도(기본 20°/s)가 그보다 훨씬 느리므로 servo 는 보간 setpoint 를 그대로 추종한다.
→ 카메라 sweep 만 천천히 돌고, 추종(follow)·teleop 등 다른 카메라 동작 속도엔 영향 없음.

순찰 (BT_patrol_sub) 의 vertex 마다 ``NavigateToVertex`` 다음에 본 sweep 1회를 끼워 넣어
"도착 → tilt 내려 천천히 좌우 확인 → tilt 원복" 동작을 만든다.

## Cancel 안전

상위 트리 swap (force-state / cancel) 으로 ``terminate(Status.INVALID)`` 가 들어오면
pan 은 ``ctx.camera_pan.center()`` 로 90° 복귀, tilt 는 ``rest_tilt_deg`` 로 복원.
외부에서 다시 활성화돼도 ``initialise()`` 가 step 0 부터 재시작.

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
DEFAULT_STEPS_DEG: tuple[float, ...] = (90.0, 10.0, 170.0, 90.0)
# 회전 속도 — 80°(center↔side)=4초, 160°(side↔side)=8초.
DEFAULT_PAN_SPEED_DEG_PER_S: float = 20.0
# step 별 hold — 좌·우(10/170)만 5초, 중앙(90)은 0.
DEFAULT_HOLD_SECS: tuple[float, ...] = (0.0, 5.0, 5.0, 0.0)
DEFAULT_REST_TILT_DEG: float = 90.0


class PanCameraSweep(py_trees.behaviour.Behaviour):
    """카메라 pan sweep behavior (rate 기반 점진 이동 + step별 hold + tilt 브래킷).

    Parameters
    ----------
    name : str
        py_trees node name.
    context : Context
        ``ctx.camera_pan`` (CameraPanClient) 사용.
    steps_deg : Sequence[float], optional
        sweep 각도 시퀀스. 기본 ``(90, 10, 170, 90)``. step 0 은 시작 위치라 이동 없이
        (이전 각도 미상) 해당 hold 만 적용.
    pan_speed_deg_per_s : float, optional
        이동 속도(°/s). 기본 ``20``. 이동 시간 = ``|Δ각도| / speed``.
    hold_secs : Sequence[float] | float, optional
        step 별 정지(hold) 초. 단일 float 면 전 step 동일. 기본 ``(0, 5, 5, 0)``.
    tilt_deg : float | None, optional
        sweep 시작 시 설정할 tilt 각도. ``None`` 이면 tilt 미사용. 기본 ``None``.
    rest_tilt_deg : float, optional
        sweep 종료 시 복원할 tilt 각도. 기본 ``90`` (중앙). ``tilt_deg`` 지정 시만 의미.
    now_fn : Callable[[], float], optional
        시간 소스 (테스트용 mock). 기본 ``time.monotonic``.
    """

    def __init__(
        self,
        name: str,
        context: "Context",
        *,
        steps_deg: Sequence[float] = DEFAULT_STEPS_DEG,
        pan_speed_deg_per_s: float = DEFAULT_PAN_SPEED_DEG_PER_S,
        hold_secs: "Sequence[float] | float" = DEFAULT_HOLD_SECS,
        tilt_deg: "float | None" = None,
        rest_tilt_deg: float = DEFAULT_REST_TILT_DEG,
        now_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(name)
        self.ctx = context
        self._steps: tuple[float, ...] = tuple(float(s) for s in steps_deg)
        if not self._steps:
            raise ValueError("PanCameraSweep: steps_deg must be non-empty")
        self._speed: float = float(pan_speed_deg_per_s)
        if self._speed <= 0:
            raise ValueError("PanCameraSweep: pan_speed_deg_per_s must be > 0")
        # hold_secs — scalar broadcast 또는 step 길이 일치 list.
        if isinstance(hold_secs, (int, float)):
            self._holds: tuple[float, ...] = tuple(float(hold_secs) for _ in self._steps)
        else:
            self._holds = tuple(float(h) for h in hold_secs)
            if len(self._holds) != len(self._steps):
                raise ValueError(
                    "PanCameraSweep: hold_secs length must match steps_deg"
                )
        if any(h < 0 for h in self._holds):
            raise ValueError("PanCameraSweep: hold_secs must be >= 0")
        self._tilt_deg: "float | None" = (
            None if tilt_deg is None else float(tilt_deg)
        )
        self._rest_tilt_deg: float = float(rest_tilt_deg)
        self._now: Callable[[], float] = now_fn
        # 런타임 상태 — initialise 에서 reset.
        self._step_idx: int = 0
        self._step_started_at: float = 0.0

    # ------------------------------------------------------------------- lifecycle

    def initialise(self) -> None:
        """tilt 설정(있으면) 후 step 0 진입 — 첫 각도 publish."""
        self._step_idx = 0
        self._step_started_at = self._now()
        if self._tilt_deg is not None:
            self._publish_tilt(self._tilt_deg)
        self._publish_pan(self._steps[0])

    def _move_duration(self, idx: int) -> float:
        """step idx 의 이동 시간 = |Δ각도| / speed. step 0 은 이동 없음(0)."""
        if idx <= 0:
            return 0.0
        return abs(self._steps[idx] - self._steps[idx - 1]) / self._speed

    def update(self) -> Status:
        idx = self._step_idx
        target = self._steps[idx]
        start = self._steps[idx - 1] if idx > 0 else target
        move_dur = self._move_duration(idx)
        elapsed = self._now() - self._step_started_at

        if elapsed < move_dur:
            # move phase — 일정 속도 보간.
            frac = elapsed / move_dur
            self._publish_pan(start + (target - start) * frac)
            return Status.RUNNING
        if elapsed < move_dur + self._holds[idx]:
            # hold phase — 목표 각도 유지.
            self._publish_pan(target)
            return Status.RUNNING
        # step 종료 → 다음 step.
        self._step_idx += 1
        if self._step_idx >= len(self._steps):
            return Status.SUCCESS
        self._step_started_at = self._now()
        return Status.RUNNING

    def terminate(self, new_status: Status) -> None:
        """종료 시 tilt 복원. cancel(INVALID) 이면 pan 도 90° 복귀.

        SUCCESS/FAILURE/INVALID 어느 경우든 tilt 는 rest 로 되돌린다 (sweep 이 tilt 를
        내렸으므로). pan 은 INVALID(트리 중간 끊김) 일 때만 강제 center — 정상 종료 시
        마지막 step 이 이미 center(90°) 라 불필요.
        """
        if self._tilt_deg is not None:
            self._publish_tilt(self._rest_tilt_deg)
        if new_status == Status.INVALID:
            try:
                self.ctx.camera_pan.center()
            except Exception as e:
                self._log_warn(f"center() 실패 (terminate INVALID): {e!r}")

    # ------------------------------------------------------------------- helpers

    def _publish_pan(self, deg: float) -> None:
        try:
            self.ctx.camera_pan.publish_pan(float(deg))
        except Exception as e:
            # publisher 미준비 등 — log 만 하고 진행 (다음 tick 에서 또 시도)
            self._log_warn(f"publish_pan 실패 (step {self._step_idx}): {e!r}")

    def _publish_tilt(self, deg: float) -> None:
        try:
            self.ctx.camera_pan.publish_tilt(float(deg))
        except Exception as e:
            self._log_warn(f"publish_tilt 실패 ({deg}°): {e!r}")

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
