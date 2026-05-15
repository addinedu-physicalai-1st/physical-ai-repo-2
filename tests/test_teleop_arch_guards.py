"""클린 아키텍처 가드 — grep 기반 import 방향 검증.

AC #15, #16, #17, #18 검증.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------- AC #15


def test_admin_ui_has_no_rclpy_import() -> None:
    forbidden = ["import rclpy", "from rclpy", "import rospy", "from rclpy_action"]
    admin_ui = REPO / "app" / "admin-app"
    for py in admin_ui.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{py} contains {token!r}"


# --------------------------------------------------------------- AC #16


def test_teleop_card_does_not_import_control_server() -> None:
    src = (REPO / "app" / "admin-app" / "widgets" / "teleop_card.py").read_text(
        encoding="utf-8"
    )
    assert "control_service" not in src
    assert "services.control_server" not in src


# --------------------------------------------------------------- AC #17


def test_router_has_no_pyqt_import() -> None:
    src = (REPO / "service" / "control-service" / "control_service" / "teleop" / "router.py").read_text(
        encoding="utf-8"
    )
    for token in ("PyQt5", "PySide2", "PySide6", "qtpy"):
        assert token not in src, f"router.py imports {token}"


# --------------------------------------------------------------- AC #18


def test_launch_uses_push_ros_namespace() -> None:
    src = (
        REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_bringup"
        / "launch" / "pi.launch.py"
    ).read_text(encoding="utf-8")
    assert "PushRosNamespace('gogoping')" in src or \
           'PushRosNamespace("gogoping")' in src
