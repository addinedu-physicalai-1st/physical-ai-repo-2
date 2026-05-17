"""[sim 디버그 전용] 가제보 entity 텔레포트 서비스.

운영(실물 Pi) 환경에선 실행하지 않음 — sim 전용 (``device-gogoping-sim.sh`` 가 띄움).

토픽 / 서비스 (namespace=`gogoping` 이라 절대 경로는 ``/gogoping/...``):

- srv  ``sim/teleport_pose``   ``gogoping_msgs/srv/SetGazeboPose``

호출 시 subprocess 로 ``gz service`` CLI 실행 — `/world/<world_name>/set_pose`
서비스에 ``gz.msgs.Pose`` 메시지 송신. 가제보 엔진이 entity 즉시 텔레포트.

ROS param:
- ``world_name`` (str, 기본 ``pingdergarten``) — gz service path 의 world 부분
- ``entity_name`` (str, 기본 ``gogopingpinky``) — spawn 시점 robot_name (``$(var namespace)pinky``)
- ``z`` (float, 기본 0.05) — 텔레포트 시 z 좌표 (바닥 sinking 방지 위해 약간 띄움)
- ``timeout_ms`` (int, 기본 2000) — gz service 호출 timeout

AMCL 가 텔레포트 후 LIDAR scan 으로 자체 재수렴 (~1초).
"""

from __future__ import annotations

import math
import subprocess
from typing import TYPE_CHECKING

import rclpy
from rclpy.node import Node

from gogoping_msgs.srv import SetGazeboPose


if TYPE_CHECKING:
    pass


class SimTeleportNode(Node):
    """SetGazeboPose.srv server — gz service `set_pose` 로 brigde."""

    def __init__(self) -> None:
        super().__init__("sim_teleport_node")

        self.declare_parameter("world_name", "pingdergarten")
        self.declare_parameter("entity_name", "gogopingpinky")
        self.declare_parameter("z", 0.05)
        self.declare_parameter("timeout_ms", 2000)

        self._srv = self.create_service(
            SetGazeboPose,
            "sim/teleport_pose",
            self._on_teleport,
        )

        world = self.get_parameter("world_name").value
        entity = self.get_parameter("entity_name").value
        self.get_logger().info(
            f"sim_teleport_node ready — srv /gogoping/sim/teleport_pose, "
            f"world={world!r}, entity={entity!r}"
        )

    def _on_teleport(
        self,
        request: SetGazeboPose.Request,
        response: SetGazeboPose.Response,
    ) -> SetGazeboPose.Response:
        world = self.get_parameter("world_name").value
        entity = self.get_parameter("entity_name").value
        z = float(self.get_parameter("z").value)
        timeout_ms = int(self.get_parameter("timeout_ms").value)

        # yaw → quaternion (z 축 회전만)
        half = float(request.yaw) / 2.0
        qw = math.cos(half)
        qz = math.sin(half)

        # gz service 의 req 메시지 (gz.msgs.Pose, textproto 형식)
        req_msg = (
            f'name: "{entity}", '
            f'position: {{x: {float(request.x)}, y: {float(request.y)}, z: {z}}}, '
            f'orientation: {{x: 0, y: 0, z: {qz}, w: {qw}}}'
        )

        cmd = [
            "gz", "service",
            "-s", f"/world/{world}/set_pose",
            "--reqtype", "gz.msgs.Pose",
            "--reptype", "gz.msgs.Boolean",
            "--timeout", str(timeout_ms),
            "--req", req_msg,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=(timeout_ms / 1000.0) + 1.0,
            )
            stdout = (result.stdout or "").strip()
            stderr = (result.stderr or "").strip()
            ok = result.returncode == 0 and "data: true" in stdout
            response.accepted = ok
            if ok:
                response.reason = ""
            else:
                response.reason = (
                    stderr or stdout or f"gz_failed_code_{result.returncode}"
                )
        except FileNotFoundError:
            response.accepted = False
            response.reason = "gz_cli_not_found"
        except subprocess.TimeoutExpired:
            response.accepted = False
            response.reason = "timeout"
        except Exception as e:
            response.accepted = False
            response.reason = f"exception: {e}"

        self.get_logger().info(
            f"teleport ({request.x:.2f}, {request.y:.2f}, yaw={request.yaw:.2f}) → "
            f"accepted={response.accepted} reason={response.reason!r}"
        )
        return response


def main() -> None:
    rclpy.init()
    node = SimTeleportNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
