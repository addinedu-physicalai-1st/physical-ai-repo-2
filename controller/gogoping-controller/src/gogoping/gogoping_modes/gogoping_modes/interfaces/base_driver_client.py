"""Base driver (vic_pinky_bringup) 의 motor torque on/off 제어용 service client.

`/gogoping/set_torque` (`std_srvs/SetBool`) 호출 wrapper.
- ``release_torque()`` (data=False) — motor disable, free-wheel. 사용자가 직접 밀기 가능.
- ``enable_torque()``  (data=True)  — motor enable. cmd_vel 다시 받음.

ManualTorqueHold behavior 가 initialise() 에서 release, terminate() 에서 enable 호출.

idempotent — driver 가 같은 상태 재호출 시 무해 (재 enable / 재 disable 모두 OK).
service 응답 안 와도 timeout 으로 차단되지 않게 짧은 wait 후 best-effort 보고.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from std_srvs.srv import SetBool

if TYPE_CHECKING:
    import rclpy.node


_SERVICE_NAME = "/gogoping/set_torque"
_WAIT_TIMEOUT_S = 0.5     # service availability wait
_CALL_TIMEOUT_S = 2.0     # 응답 timeout (실 호출 sync wait)


class BaseDriverClient:
    """std_srvs/SetBool 클라이언트 — torque on/off 동기 호출."""

    def __init__(self, node: "rclpy.node.Node"):
        self.node = node
        self._client = node.create_client(SetBool, _SERVICE_NAME)
        self._logger = node.get_logger()

    def release_torque(self) -> bool:
        """Motor disable (free-wheel). 성공 시 True, 실패/timeout 시 False."""
        return self._call(False)

    def enable_torque(self) -> bool:
        """Motor enable (cmd_vel 다시 동작). 성공 시 True, 실패/timeout 시 False."""
        return self._call(True)

    def _call(self, data: bool) -> bool:
        if not self._client.wait_for_service(timeout_sec=_WAIT_TIMEOUT_S):
            self._logger.warn(
                f"BaseDriverClient: {_SERVICE_NAME} 서비스 없음 — torque {'ON' if data else 'OFF'} skip"
            )
            return False
        req = SetBool.Request()
        req.data = data
        future = self._client.call_async(req)
        # py_trees behavior 의 initialise/terminate 안에서 호출 — node.spin 없이 future complete 기다림.
        # MultiThreadedExecutor 환경이라 별 thread 가 spin 해주는 걸 기대.
        import time
        deadline = time.monotonic() + _CALL_TIMEOUT_S
        while not future.done() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not future.done():
            self._logger.warn(
                f"BaseDriverClient: torque {'ON' if data else 'OFF'} 응답 timeout ({_CALL_TIMEOUT_S}s)"
            )
            return False
        result = future.result()
        if result is None or not result.success:
            self._logger.warn(
                f"BaseDriverClient: torque {'ON' if data else 'OFF'} 실패 — {getattr(result, 'message', 'no response')}"
            )
            return False
        return True
