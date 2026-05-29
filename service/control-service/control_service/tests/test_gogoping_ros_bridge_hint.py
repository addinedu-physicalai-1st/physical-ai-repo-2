"""GogopingRosBridge.publish_follow_hint 단위 테스트."""
import sys
from unittest.mock import MagicMock

import pytest

# ROS 미source 환경에서도 import 통과 — publish_follow_hint 안의 `from std_msgs.msg import String`
# 가 mock 모듈에서 attribute 로 가져와 동작. msg.data 도 mock attribute 라 assert 통과.
sys.modules.setdefault("std_msgs", MagicMock())
sys.modules.setdefault("std_msgs.msg", MagicMock())

from control_service.gogoping.ros_bridge import (  # noqa: E402
    BridgeUnavailable,
    GogopingRosBridge,
)


def _make_bridge_with_publisher():
    """rclpy 없이 publisher 만 mock 한 bridge 인스턴스."""
    bridge = GogopingRosBridge.__new__(GogopingRosBridge)
    bridge._follow_hint_pub = MagicMock()
    return bridge


def test_publish_follow_hint_valid_right():
    bridge = _make_bridge_with_publisher()
    bridge.publish_follow_hint("right")
    bridge._follow_hint_pub.publish.assert_called_once()
    msg = bridge._follow_hint_pub.publish.call_args[0][0]
    assert msg.data == "right"


def test_publish_follow_hint_valid_left():
    bridge = _make_bridge_with_publisher()
    bridge.publish_follow_hint("left")
    msg = bridge._follow_hint_pub.publish.call_args[0][0]
    assert msg.data == "left"


def test_publish_follow_hint_invalid_raises():
    bridge = _make_bridge_with_publisher()
    with pytest.raises(ValueError, match="invalid direction"):
        bridge.publish_follow_hint("up")
    bridge._follow_hint_pub.publish.assert_not_called()


def test_publish_follow_hint_no_publisher_raises():
    bridge = GogopingRosBridge.__new__(GogopingRosBridge)
    bridge._follow_hint_pub = None
    with pytest.raises(BridgeUnavailable):
        bridge.publish_follow_hint("right")
