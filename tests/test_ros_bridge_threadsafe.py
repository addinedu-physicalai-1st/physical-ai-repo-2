"""ros_bridge 의 동시 접근에서 race / deadlock 없음 + lock 보호 검증.

AC #21, #22, #23, #24 검증.
rclpy 가 없어도 돌도록 publish_cmd_vel 는 mock pub 로 대체.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from server.control.teleop.ros_bridge import RosBridge


# --------------------------------------------------------------- AC #24


def test_concurrent_publish_and_snapshot_no_race() -> None:
    """10 thread × 100 회 publish + snapshot 동시 호출, race/deadlock 없음."""
    b = RosBridge()
    b._pub = MagicMock()  # rclpy.Publisher 대체
    # geometry_msgs.msg.Twist import 가 publish_cmd_vel 안에서 일어남 — mock 환경에서는
    # 실제 import 가 동작하지 않을 수 있으니 monkey patch 한다.
    import server.control.teleop.ros_bridge as mod
    real_publish = mod.RosBridge.publish_cmd_vel

    def safe_publish(self, lin: float, ang: float) -> None:
        with self._lock:
            if self._pub is None:
                return
            self._pub.publish((lin, ang))
            import time
            self._last_cmd_at_s = time.monotonic()

    mod.RosBridge.publish_cmd_vel = safe_publish
    try:
        errors: list[Exception] = []

        def worker() -> None:
            try:
                for i in range(100):
                    b.publish_cmd_vel(float(i), float(-i))
                    _ = b.snapshot()
                    _ = b.last_cmd_age_s()
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        for t in threads:
            assert not t.is_alive(), "deadlock detected"
        assert not errors, f"errors during concurrent access: {errors}"
        assert b._pub.publish.call_count == 10 * 100
    finally:
        mod.RosBridge.publish_cmd_vel = real_publish


# --------------------------------------------------------------- AC #21


def test_lock_protects_state_mutations() -> None:
    """소스 grep — latest_state / publish 갱신이 with self._lock 안에 있다."""
    src = Path("server/control/teleop/ros_bridge.py").read_text(encoding="utf-8")
    # 모든 self._latest_*  /  self._last_cmd_at_s  대입은 with self._lock: 블록 다음 줄들에
    # 위치해야 한다. 단순화: 각 대입 직전 (앞 20줄) 에 'with self._lock:' 가 있는지 본다.
    target_writes = [
        "self._latest_odom",
        "self._latest_scan",
        "self._last_cmd_at_s",
    ]
    lines = src.splitlines()
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        for w in target_writes:
            if stripped.startswith(w + " ="):
                # 앞 20 줄 안에 'with self._lock:' 가 있는지
                window = "\n".join(lines[max(0, i - 20):i])
                assert "with self._lock:" in window, (
                    f"line {i+1} '{line.strip()}' is not under 'with self._lock:'"
                )


# --------------------------------------------------------------- AC #22


def test_rclpy_spin_only_in_one_function() -> None:
    """rclpy.spin / executor.spin 이 _spin 함수 안 1 곳에서만 호출된다.

    Thread(target=_spin, daemon=True) 가 정확히 1 곳.
    """
    src = Path("server/control/teleop/ros_bridge.py").read_text(encoding="utf-8")
    # spin() 호출 횟수
    spin_calls = re.findall(r"\.spin\(\)", src)
    assert len(spin_calls) == 1, f"expected 1 spin() call, got {len(spin_calls)}"
    # daemon=True 가 붙은 Thread 가 정확히 1 개
    daemon_threads = re.findall(r"threading\.Thread\([^)]*daemon\s*=\s*True", src)
    assert len(daemon_threads) == 1


# --------------------------------------------------------------- AC #23


def test_router_does_not_call_rclpy_directly() -> None:
    """asyncio router 안에서 rclpy.* 직접 호출 0.

    AST 로 import + 표현식 검사 — 주석/문자열 false positive 회피.
    """
    import ast

    src = Path("server/control/teleop/router.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    for node in ast.walk(tree):
        # import rclpy / from rclpy ...
        if isinstance(node, ast.Import):
            for n in node.names:
                assert not n.name.startswith("rclpy"), (
                    f"router.py imports {n.name}"
                )
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert not mod.startswith("rclpy"), (
                f"router.py from-imports {mod}"
            )
        # rclpy.X(...) 호출
        if isinstance(node, ast.Attribute):
            v = node.value
            if isinstance(v, ast.Name) and v.id == "rclpy":
                raise AssertionError(
                    f"router.py accesses rclpy.{node.attr}"
                )
