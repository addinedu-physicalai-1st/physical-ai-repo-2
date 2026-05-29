"""Safety monitor 그룹별 disable flag — 시연/디버그 환경에서 자동 전이 차단.

사용 시나리오:
    - 시연 중 배터리 모니터가 감지한 low → 자동 RETURNING 으로 시연 끊기는 것 방지
    - 디버그 중 HW health / map boundary 오탐으로 ERROR (terminal) lockdown 방지

그룹 (사용자 요청 기준):
    - ``battery`` : BatteryLowMonitor + BatteryFullMonitor
    - ``error``   : HardwareHealthMonitor + MapBoundaryMonitor + (추후) CollisionEventHandler

각 monitor 의 ``__init__`` 에서 ``is_safety_disabled(node, "battery"|"error")`` 호출 후
``self._disabled = ...`` 저장. ``update()`` 첫줄에 disabled 체크 + RUNNING 반환.

Launch 시 스크립트가 ``--ros-args -p disable_battery_safety:=true`` 등으로 전달.
ROS param 이라 같은 노드의 다른 monitor 들이 동일 param 을 ``declare_parameter`` 해도
``ParameterAlreadyDeclaredException`` 만 silent 처리되므로 충돌 없음.
"""
from __future__ import annotations

from typing import Any


_GROUP_PARAM = {
    "battery":   "disable_battery_safety",
    "error":     "disable_error_safety",
    # proximity : 사람(1.5m)/벽(0.5m) 근접 정지·reroute·후진. 실제 반응은 graph_router
    #             (_act_navigate_impl) 가 수행하고, BT 의 ProximitySafetyMonitor 는 관측·표시용.
    #             graph_router 도 동일 param 명(disable_proximity_safety)을 직접 읽어 분기 skip.
    "proximity": "disable_proximity_safety",
}


def is_safety_disabled(node: Any, group: str, monitor_name: str = "") -> bool:
    """``group`` (``"battery"`` | ``"error"``) 안전 모니터가 disable 됐는지.

    노드의 ROS param 을 한 번 declare (idempotent) 후 값 읽음. node 가 None 이거나
    param 시스템 오류면 False (= 안전 모니터 활성) 로 안전 fallback.

    ``monitor_name`` 이 주어지고 disable 인 경우, 노드 로그에 **WARNING 1회** 출력
    ("...disabled — safety group 'X' off") — 시연 환경에서 자동복귀/ERROR 차단되고
    있음을 즉시 인지 가능. monitor 의 ``__init__`` 에서 1번씩 호출되므로 시작 시점에
    동일 group 의 monitor 마다 한 줄씩 출력.
    """
    param_name = _GROUP_PARAM.get(group)
    if param_name is None or node is None:
        return False
    try:
        node.declare_parameter(param_name, False)
    except Exception:
        # 이미 다른 monitor 가 declare — 정상.
        pass
    try:
        disabled = bool(
            node.get_parameter(param_name).get_parameter_value().bool_value
        )
    except Exception:
        return False

    if disabled and monitor_name:
        try:
            node.get_logger().warning(
                f"[{monitor_name}] DISABLED — safety group '{group}' off "
                f"({param_name}=true). 시연/디버그 모드: 자동 전이 차단."
            )
        except Exception:
            pass
    return disabled


__all__ = ["is_safety_disabled"]
