"""error_log 테이블 INSERT (Day 2 TODO).

# STUB: replace Day 2
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import rclpy.node


class DBLogger:
    """Day 2 에 control-server REST 호출 (POST /api/error_log) 또는 직접 DB 접근으로 구현.

    예상 API: log_error(reason: str, source: str, state: str).
    """

    def __init__(self, node: "rclpy.node.Node"):
        self.node = node
