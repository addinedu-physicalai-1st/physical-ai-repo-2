"""Pure helpers for the servo_bridge.ino serial protocol.

Kept ROS-free so unit tests don't need rclpy.

Protocol:
    host -> uno : "PT:<pan>,<tilt>\\n"   (integer degrees)
    uno  -> host: "OK:<pan>,<tilt>\\n"
"""

from __future__ import annotations

from dataclasses import dataclass


def clamp(v: float, lo: float, hi: float) -> float:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def rate_limit(prev: float, target: float, max_step: float) -> float:
    """Move from prev toward target by at most max_step (>=0)."""
    if max_step <= 0:
        return target
    delta = target - prev
    if delta > max_step:
        return prev + max_step
    if delta < -max_step:
        return prev - max_step
    return target


def encode_cmd(pan: float, tilt: float) -> bytes:
    return f"PT:{int(round(pan))},{int(round(tilt))}\n".encode("ascii")


@dataclass
class Ack:
    pan: int
    tilt: int


def parse_ack(line: str) -> Ack | None:
    """Parse one line from the Uno. Returns None for non-OK / malformed lines."""
    line = line.strip()
    if not line.startswith("OK:"):
        return None
    body = line[3:]
    if "," not in body:
        return None
    p_str, t_str = body.split(",", 1)
    try:
        return Ack(pan=int(p_str), tilt=int(t_str))
    except ValueError:
        return None
