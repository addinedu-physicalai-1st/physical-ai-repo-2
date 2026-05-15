import pytest

from control_service.waypoints.ros_bridge import WaypointsRosBridge


def test_start_requires_ros_domain_id(monkeypatch):
    monkeypatch.delenv("ROS_DOMAIN_ID", raising=False)
    b = WaypointsRosBridge()
    with pytest.raises(RuntimeError, match="ROS_DOMAIN_ID"):
        b.start()


def test_initial_state_is_not_ok():
    b = WaypointsRosBridge()
    h = b.health()
    assert h["ros_ok"] is False
    assert h["nav_action_available"] is False


def test_odom_snapshot_returns_none_initially():
    b = WaypointsRosBridge()
    assert b.odom_snapshot() is None


def test_latest_plan_returns_none_initially():
    b = WaypointsRosBridge()
    assert b.latest_plan() is None


def test_current_goal_status_idle():
    b = WaypointsRosBridge()
    s = b.current_goal_status()
    assert s["status"] == "idle"


def test_register_unregister_listener():
    b = WaypointsRosBridge()
    import queue
    q = queue.Queue()
    b.register_listener(q)
    assert q in b._sse_listeners
    b.unregister_listener(q)
    assert q not in b._sse_listeners


def test_emit_pushes_to_listeners():
    b = WaypointsRosBridge()
    import queue
    q = queue.Queue()
    b.register_listener(q)
    b._emit({"type": "test"})
    assert q.get_nowait() == {"type": "test"}


@pytest.mark.ros
def test_pose_from_tf2_with_real_ros(monkeypatch):
    """tf2 map→base_link 가 publish 되면 odom_snapshot 이 그 값을 반환."""
    monkeypatch.setenv("ROS_DOMAIN_ID", "210")
    pytest.importorskip("rclpy")
    import rclpy
    import time
    from geometry_msgs.msg import TransformStamped
    from tf2_ros import TransformBroadcaster

    rclpy.init()
    pub_node = rclpy.create_node("test_tf_pub")
    br = TransformBroadcaster(pub_node)

    b = WaypointsRosBridge()
    b.start()
    try:
        # publish map → base_link transform
        for _ in range(10):
            t = TransformStamped()
            t.header.stamp = pub_node.get_clock().now().to_msg()
            t.header.frame_id = "map"
            t.child_frame_id = "base_link"
            t.transform.translation.x = 1.5
            t.transform.translation.y = -2.5
            t.transform.rotation.w = 1.0  # yaw = 0
            br.sendTransform(t)
            rclpy.spin_once(pub_node, timeout_sec=0.1)
            time.sleep(0.1)
        snap = b.odom_snapshot()
        assert snap is not None, "snapshot 미수신 — tf2 transform 가 안 들어옴"
        x, y, yaw = snap
        assert x == pytest.approx(1.5, abs=0.01)
        assert y == pytest.approx(-2.5, abs=0.01)
    finally:
        b.shutdown()
        pub_node.destroy_node()
        rclpy.shutdown()
