"""safety_filter pure-logic unit tests."""
import pytest

from gogoping_perception.safety_filter import filter_twist


class _Twist:
    """가벼운 Twist stub — geometry_msgs/Twist 와 같은 필드 구조."""
    def __init__(self, lx=0.0, ly=0.0, lz=0.0, ax=0.0, ay=0.0, az=0.0):
        class V:
            pass
        self.linear = V()
        self.angular = V()
        self.linear.x = lx
        self.linear.y = ly
        self.linear.z = lz
        self.angular.x = ax
        self.angular.y = ay
        self.angular.z = az


def test_passthrough_when_safety_off():
    raw = _Twist(lx=0.3, az=0.5)
    out = filter_twist(raw, safety_stop=False)
    assert out.linear.x == 0.3
    assert out.angular.z == 0.5


def test_zero_override_when_safety_on():
    raw = _Twist(lx=0.3, az=0.5)
    out = filter_twist(raw, safety_stop=True)
    assert out.linear.x == 0.0
    assert out.linear.y == 0.0
    assert out.linear.z == 0.0
    assert out.angular.x == 0.0
    assert out.angular.y == 0.0
    assert out.angular.z == 0.0


def test_passthrough_zero_twist():
    raw = _Twist()
    out = filter_twist(raw, safety_stop=False)
    assert out.linear.x == 0.0
    assert out.angular.z == 0.0
