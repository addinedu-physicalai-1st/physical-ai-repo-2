"""Unit tests for eduping_stethoscope.protocol — parse_line.

ROS-free. Adds the package dir to sys.path so we don't depend on a colcon install.
"""
from __future__ import annotations

import pathlib
import sys

PKG_ROOT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "controller"
    / "eduping-controller"
    / "src"
    / "eduping_stethoscope"
)
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from eduping_stethoscope.protocol import parse_line  # noqa: E402


class TestParseLine:
    def test_valid_mid(self):
        assert parse_line("F512") == 512

    def test_valid_zero(self):
        assert parse_line("F0") == 0

    def test_valid_max(self):
        assert parse_line("F1023") == 1023

    def test_strips_whitespace_and_crlf(self):
        assert parse_line("  F300 \r\n") == 300

    def test_missing_prefix_returns_none(self):
        assert parse_line("512") is None

    def test_non_int_returns_none(self):
        assert parse_line("Fabc") is None

    def test_prefix_only_returns_none(self):
        assert parse_line("F") is None

    def test_empty_returns_none(self):
        assert parse_line("") is None
