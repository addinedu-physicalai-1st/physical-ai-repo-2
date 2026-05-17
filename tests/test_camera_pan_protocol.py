"""Unit tests for gogoping_camera_pan.protocol — clamp / rate_limit / parse_ack / encode_cmd.

ROS-free. Adds the package dir to sys.path so we don't depend on a colcon install.
"""

from __future__ import annotations

import pathlib
import sys

PKG_ROOT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "controller"
    / "gogoping-controller"
    / "src"
    / "gogoping"
    / "gogoping_camera_pan"
)
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from gogoping_camera_pan.protocol import (  # noqa: E402
    Ack,
    clamp,
    encode_cmd,
    parse_ack,
    rate_limit,
)


class TestClamp:
    def test_within_range_passthrough(self):
        assert clamp(50.0, 0.0, 100.0) == 50.0

    def test_below_min(self):
        assert clamp(-10.0, 0.0, 100.0) == 0.0

    def test_above_max(self):
        assert clamp(150.0, 0.0, 100.0) == 100.0

    def test_at_boundaries(self):
        assert clamp(0.0, 0.0, 100.0) == 0.0
        assert clamp(100.0, 0.0, 100.0) == 100.0


class TestRateLimit:
    def test_small_step_reaches_target(self):
        assert rate_limit(90.0, 95.0, max_step=10.0) == 95.0

    def test_large_step_clipped_positive(self):
        assert rate_limit(90.0, 180.0, max_step=10.0) == 100.0

    def test_large_step_clipped_negative(self):
        assert rate_limit(90.0, 0.0, max_step=10.0) == 80.0

    def test_zero_max_step_jumps_to_target(self):
        # max_step <= 0 means rate limiting disabled.
        assert rate_limit(90.0, 180.0, max_step=0.0) == 180.0

    def test_already_at_target(self):
        assert rate_limit(90.0, 90.0, max_step=5.0) == 90.0


class TestEncodeCmd:
    def test_integers(self):
        assert encode_cmd(90, 90) == b"PT:90,90\n"

    def test_rounds_floats(self):
        assert encode_cmd(89.6, 90.4) == b"PT:90,90\n"

    def test_negatives(self):
        assert encode_cmd(-5, 0) == b"PT:-5,0\n"


class TestParseAck:
    def test_valid(self):
        assert parse_ack("OK:90,90\n") == Ack(pan=90, tilt=90)

    def test_valid_without_newline(self):
        assert parse_ack("OK:5,150") == Ack(pan=5, tilt=150)

    def test_extra_whitespace(self):
        assert parse_ack("  OK:30,120  \r\n") == Ack(pan=30, tilt=120)

    def test_non_ok_prefix_returns_none(self):
        assert parse_ack("BOOT:hello\n") is None

    def test_missing_comma_returns_none(self):
        assert parse_ack("OK:90\n") is None

    def test_non_int_returns_none(self):
        assert parse_ack("OK:abc,xyz\n") is None

    def test_empty_returns_none(self):
        assert parse_ack("") is None
