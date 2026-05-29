from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription([
        Node(
            package="gogoping_perception",
            executable="perception_node",
            name="gogoping_perception_node",
            output="screen",
        ),
        Node(
            package="gogoping_perception",
            executable="safety_monitor",
            name="gogoping_safety_monitor",
            output="screen",
            emulate_tty=True,
        ),
        # NOTE: safety_filter(cmd_vel_raw→cmd_vel relay)는 nav 런치
        # (sim_with_nav2.launch.xml / navigation_real.launch.xml)로 이동했다.
        # 이동(relay)은 nav 와 항상 함께 떠야 하고 perception(detector)과 독립이어야
        # sim/실물 모두 perception 없이도 주행 가능. 여기서 또 띄우면 nav 런치의 것과
        # publisher 가 중복돼 /gogoping/cmd_vel 이 충돌한다.
    ])
