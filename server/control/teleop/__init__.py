"""Teleop 패키지 — admin-ui 의 GogoPing Teleop 카드를 위한 REST/WS gateway.

ros_bridge: rclpy node (별도 thread spin) — /gogoping/cmd_vel pub, odom/scan sub.
router: FastAPI APIRouter — POST /teleop/cmd_vel, WS /teleop/state, GET /teleop/health.
"""
