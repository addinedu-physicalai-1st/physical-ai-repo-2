"""Control Server 의 NoriArm 통합 — Robot UI ↔ ROS2 다리.

Robot UI 의 OX 퀴즈 등 NoriArm 게임이 호출하는 REST + SSE 엔드포인트를 제공한다.
ROS2 (rclpy / sensor_msgs) 의존성은 모두 `ros_bridge.py` 에 캡슐화되어 있고, 라우터가
호출하는 시점에만 초기화된다. ROS 환경이 source 되어 있지 않으면 503 으로 명확히
실패한다.
"""
