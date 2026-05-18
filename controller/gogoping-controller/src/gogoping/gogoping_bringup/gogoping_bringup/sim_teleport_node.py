"""[sim 디버그 전용] 가제보 entity 텔레포트 서비스 + /initialpose 미러.

운영(실물 Pi) 환경에선 실행하지 않음 — sim 전용 (``device-gogoping-sim.sh`` 가 띄움).

토픽 / 서비스 (namespace=`gogoping` 이라 절대 경로는 ``/gogoping/...``):

- srv  ``sim/teleport_pose``   ``gogoping_msgs/srv/SetGazeboPose``
- sub  ``/initialpose``        ``geometry_msgs/PoseWithCovarianceStamped``
    AMCL 재초기화 신호 (RViz 2D Pose Estimate, /waypoints/initialpose REST,
    /api/gogoping/debug/pose) 를 그대로 받아 Gazebo entity 도 같은 위치로 텔레포트.
    sim 에서 "로봇이 여기 있다" 라는 단일 신호로 통일 — admin UI 의 맵 Shift+클릭과
    TopBar Pose 입력 양쪽 다 RViz/AMCL + Gazebo 가 같이 움직이게 됨.

호출 시 subprocess 로 ``gz service`` CLI 실행 — `/world/<world_name>/set_pose`
서비스에 ``gz.msgs.Pose`` 메시지 송신. 가제보 엔진이 entity 즉시 텔레포트.

ROS param:
- ``world_name`` (str, 기본 ``pingdergarten``) — gz service path 의 world 부분
- ``entity_name`` (str, 기본 ``gogopingpinky``) — spawn 시점 robot_name (``$(var namespace)pinky``)
- ``z`` (float, 기본 0.05) — 텔레포트 시 z 좌표 (바닥 sinking 방지 위해 약간 띄움)
- ``timeout_ms`` (int, 기본 2000) — gz service 호출 timeout

AMCL 가 텔레포트 후 LIDAR scan 으로 자체 재수렴 (~1초). /initialpose 신호 자체가
AMCL 재수렴 트리거이기도 해서 sim 에선 두 효과가 동시에 일어남.
"""

from __future__ import annotations

import math
import subprocess
from typing import TYPE_CHECKING

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.node import Node

from gogoping_msgs.srv import SetGazeboPose


if TYPE_CHECKING:
    pass


class SimTeleportNode(Node):
    """SetGazeboPose.srv server + /initialpose subscriber — gz service `set_pose` bridge."""

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

        # /initialpose 미러 — sim 에서 RViz/admin-UI 의 위치 재초기화를 Gazebo 도 따라감.
        # AMCL 도 이 토픽을 구독하므로 동시에 파티클 재샘플링됨.
        self._initial_pose_sub = self.create_subscription(
            PoseWithCovarianceStamped,
            "/initialpose",
            self._on_initial_pose,
            10,
        )

        world = self.get_parameter("world_name").value
        entity = self.get_parameter("entity_name").value
        self.get_logger().info(
            f"sim_teleport_node ready — srv /gogoping/sim/teleport_pose, "
            f"sub /initialpose, world={world!r}, entity={entity!r}"
        )

    def _on_teleport(
        self,
        request: SetGazeboPose.Request,
        response: SetGazeboPose.Response,
    ) -> SetGazeboPose.Response:
        ok, reason = self._teleport_xy_yaw(
            float(request.x), float(request.y), float(request.yaw),
        )
        response.accepted = ok
        response.reason = reason
        self.get_logger().info(
            f"teleport(srv) ({request.x:.2f}, {request.y:.2f}, yaw={request.yaw:.2f}) → "
            f"accepted={response.accepted} reason={response.reason!r}"
        )
        return response

    def _on_initial_pose(self, msg: PoseWithCovarianceStamped) -> None:
        """``/initialpose`` 콜백 — 메시지의 (x, y, yaw) 로 Gazebo entity 텔레포트.

        AMCL 도 같은 토픽으로 파티클 재샘플링. 결과적으로 sim 에서 Gazebo 와 RViz/AMCL
        이 동일 위치로 동시 이동. 실패해도 service 경로가 별도로 있으므로 best-effort.
        """
        q = msg.pose.pose.orientation
        # quaternion → yaw (z 축 회전만 추출)
        yaw = math.atan2(
            2.0 * (q.w * q.z + q.x * q.y),
            1.0 - 2.0 * (q.y * q.y + q.z * q.z),
        )
        x = float(msg.pose.pose.position.x)
        y = float(msg.pose.pose.position.y)
        ok, reason = self._teleport_xy_yaw(x, y, yaw)
        self.get_logger().info(
            f"teleport(/initialpose) ({x:.2f}, {y:.2f}, yaw={yaw:.2f}) → "
            f"accepted={ok} reason={reason!r}"
        )

    def _teleport_xy_yaw(self, x: float, y: float, yaw: float) -> tuple[bool, str]:
        """gz service `set_pose` 호출 — (accepted, reason) 리턴.

        srv 핸들러와 topic 콜백이 공유. 실패 시 reason 에 사유 ("gz_cli_not_found" /
        "timeout" / stderr 내용 등) 가 담긴다.
        """
        world = self.get_parameter("world_name").value
        entity = self.get_parameter("entity_name").value
        z = float(self.get_parameter("z").value)
        timeout_ms = int(self.get_parameter("timeout_ms").value)

        # yaw → quaternion (z 축 회전만)
        half = yaw / 2.0
        qw = math.cos(half)
        qz = math.sin(half)

        # gz service 의 req 메시지 (gz.msgs.Pose, textproto 형식)
        req_msg = (
            f'name: "{entity}", '
            f'position: {{x: {x}, y: {y}, z: {z}}}, '
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
            if ok:
                return True, ""
            return False, (
                stderr or stdout or f"gz_failed_code_{result.returncode}"
            )
        except FileNotFoundError:
            return False, "gz_cli_not_found"
        except subprocess.TimeoutExpired:
            return False, "timeout"
        except Exception as e:
            return False, f"exception: {e}"


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
