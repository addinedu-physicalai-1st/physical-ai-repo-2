#!/usr/bin/env python3
"""sim 의 robot_state_publisher 갱신 + Gazebo entity 재 spawn.

urdf-tuner GUI 의 sub-process 로 호출. rclpy 가 PyQt5 와 같은 프로세스에
import 되면 event loop 가 복잡해지므로 분리.

usage
-----
  python sync_to_sim.py \\
      --xacro <path-to.urdf.xacro> \\
      --namespace gogoping \\
      --rsp-node /gogoping/robot_state_publisher \\
      --entity-name gogoping/pinky \\
      --world default \\
      --targets rsp,gazebo
"""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
import time


def xacro_to_urdf(xacro_path: str, namespace: str) -> str:
    cmd = ["xacro", xacro_path]
    if namespace:
        cmd.append(f"namespace:={namespace}/")
    r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return r.stdout


def push_rsp(rsp_node: str, urdf: str, *, timeout_s: float = 5.0) -> None:
    """robot_state_publisher 의 robot_description parameter 를 동적 갱신.

    robot_state_publisher (jazzy 이상) 는 robot_description 변경 시 새 URDF 로
    내부 model 을 교체 → /tf 다음 publish 부터 새 값 반영.
    """
    import rclpy
    from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue
    from rcl_interfaces.srv import SetParameters

    rclpy.init()
    try:
        node = rclpy.create_node("urdf_tuner_sync_rsp")
        srv_name = f"{rsp_node}/set_parameters"
        cli = node.create_client(SetParameters, srv_name)
        if not cli.wait_for_service(timeout_sec=3.0):
            raise RuntimeError(f"service unavailable: {srv_name}")
        req = SetParameters.Request(parameters=[
            Parameter(
                name="robot_description",
                value=ParameterValue(
                    type=ParameterType.PARAMETER_STRING,
                    string_value=urdf,
                ),
            )
        ])
        fut = cli.call_async(req)
        rclpy.spin_until_future_complete(node, fut, timeout_sec=timeout_s)
        if not fut.done():
            raise RuntimeError("SetParameters timed out")
        res = fut.result()
        if not res.results or not res.results[0].successful:
            reason = res.results[0].reason if res.results else "?"
            raise RuntimeError(f"SetParameters failed: {reason}")
        node.destroy_node()
    finally:
        rclpy.shutdown()


def get_pose(namespace: str, *, timeout_s: float = 3.0):
    """현재 robot pose (x, y, yaw) — /odom 마지막 메시지에서."""
    import rclpy
    from nav_msgs.msg import Odometry

    rclpy.init()
    try:
        node = rclpy.create_node("urdf_tuner_sync_pose")
        topic = f"/{namespace}/odom" if namespace else "/odom"
        latest = {"msg": None}

        def cb(msg):
            latest["msg"] = msg

        node.create_subscription(Odometry, topic, cb, 10)
        end = time.time() + timeout_s
        while time.time() < end and latest["msg"] is None:
            rclpy.spin_once(node, timeout_sec=0.1)
        if latest["msg"] is None:
            return None
        p = latest["msg"].pose.pose
        q = p.orientation
        yaw = math.atan2(
            2 * (q.w * q.z + q.x * q.y),
            1 - 2 * (q.y * q.y + q.z * q.z),
        )
        node.destroy_node()
        return (p.position.x, p.position.y, yaw)
    finally:
        rclpy.shutdown()


def respawn_gazebo(world: str, entity_name: str, namespace: str, pose) -> None:
    """Gazebo entity 를 같은 위치에 delete + recreate."""
    # delete
    req = f'name: "{entity_name}" type: MODEL'
    subprocess.run(
        [
            "gz", "service", "-s", f"/world/{world}/remove",
            "--reqtype", "gz.msgs.Entity",
            "--reptype", "gz.msgs.Boolean",
            "--timeout", "3000",
            "--req", req,
        ],
        check=False,
        timeout=10,
    )
    time.sleep(0.8)
    # re-spawn
    x, y, yaw = pose if pose else (0.0, 0.0, 0.0)
    topic = f"/{namespace}/robot_description" if namespace else "/robot_description"
    subprocess.run(
        [
            "ros2", "run", "ros_gz_sim", "create",
            "-name", entity_name,
            "-topic", topic,
            "-x", f"{x:.4f}", "-y", f"{y:.4f}", "-z", "0.10",
            "-Y", f"{yaw:.4f}",
        ],
        check=True,
        timeout=15,
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--xacro", required=True, help="Path to .urdf.xacro")
    p.add_argument("--namespace", default="gogoping")
    p.add_argument("--rsp-node", default="/gogoping/robot_state_publisher")
    p.add_argument("--entity-name", default="gogoping/pinky")
    p.add_argument("--world", default="default")
    p.add_argument("--targets", default="rsp",
                   help="comma-list: rsp,gazebo  (e.g. 'rsp' or 'rsp,gazebo')")
    args = p.parse_args()

    targets = [t.strip() for t in args.targets.split(",") if t.strip()]
    urdf = xacro_to_urdf(args.xacro, args.namespace)

    if "rsp" in targets:
        push_rsp(args.rsp_node, urdf)
        print(f"[sync] RSP  ok  →  {args.rsp_node}")

    if "gazebo" in targets:
        pose = get_pose(args.namespace)
        if pose is None:
            print("[sync] WARN: no odom — respawning at origin", file=sys.stderr)
        respawn_gazebo(args.world, args.entity_name, args.namespace, pose)
        loc = f"({pose[0]:.2f}, {pose[1]:.2f}, yaw={pose[2]:.2f})" if pose else "origin"
        print(f"[sync] GZ   ok  →  {args.entity_name}  @ {loc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
