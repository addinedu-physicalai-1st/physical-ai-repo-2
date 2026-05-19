"""Base driver (vic_pinky_bringup) 의 motor torque on/off 제어용 service client.

`/gogoping/set_torque` (`std_srvs/SetBool`) 호출 wrapper.
- ``release_torque()`` (data=False) — motor disable, free-wheel. 사용자가 직접 밀기 가능.
- ``enable_torque()``  (data=True)  — motor enable. cmd_vel 다시 받음.

ManualTorqueHold behavior 가 initialise() 에서 release, terminate() 에서 enable 호출.

## Fire-and-forget 패턴

main.py 가 ``rclpy.spin(node)`` (SingleThreadedExecutor) 를 사용하므로 BT tick callback
안에서 service call 의 응답을 동기 wait 하면 같은 thread 가 spin 못 해 future 가
영원히 complete 안 됨 → 모든 BT 동작 굳음. 그래서 ``call_async`` 후 응답 안 기다리고
바로 리턴 — request 는 rmw 큐에 들어가서 spin 시 자동 송신됨.

실 동작 확인은 Pi bringup 의 ``[set_torque] torque ON/OFF`` 로그 또는 모터 응답으로.
idempotent — 같은 상태 재호출 무해.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from std_srvs.srv import SetBool

if TYPE_CHECKING:
    import rclpy.node


_SERVICE_NAME = "/gogoping/set_torque"


class BaseDriverClient:
    """std_srvs/SetBool 클라이언트 — torque on/off fire-and-forget."""

    def __init__(self, node: "rclpy.node.Node"):
        self.node = node
        self._client = node.create_client(SetBool, _SERVICE_NAME)
        self._logger = node.get_logger()

    def release_torque(self) -> bool:
        """Motor disable (free-wheel). request 큐 등록 성공 = True."""
        return self._call(False)

    def enable_torque(self) -> bool:
        """Motor enable (cmd_vel 다시 동작). request 큐 등록 성공 = True."""
        return self._call(True)

    def _call(self, data: bool) -> bool:
        req = SetBool.Request()
        req.data = data
        self._client.call_async(req)   # fire-and-forget — 응답 안 기다림
        return True
