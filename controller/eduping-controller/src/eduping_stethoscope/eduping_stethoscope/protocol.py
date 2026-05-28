"""Pure helpers for the stethoscope_bridge.ino serial protocol.

Kept ROS-free so unit tests don't need rclpy.

Protocol:
    uno -> host : "F<raw>\n"   (raw = analogRead(A0), 정수 0..1023)
"""
from __future__ import annotations


def parse_line(line: str) -> int | None:
    """Parse one serial line "F<raw>" → int raw, or None if malformed."""
    s = line.strip()
    if not s.startswith("F"):
        return None
    try:
        return int(s[1:])
    except ValueError:
        return None
