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
def test_route_path_topic_relayed_as_sse(monkeypatch):
    """graph_router /route_path (nav_msgs/Path) 수신 → route_path SSE emit.
    RViz 와 동일 토픽을 구독하므로 BT 자율주행이든 navigate 든 admin 에 전달된다."""
    monkeypatch.setenv("ROS_DOMAIN_ID", "210")
    pytest.importorskip("rclpy")
    import queue
    import time
    import rclpy
    from nav_msgs.msg import Path
    from geometry_msgs.msg import PoseStamped
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from control_service.waypoints.ros_bridge import TOPIC_ROUTE_PATH

    rclpy.init()
    pub_node = rclpy.create_node("test_route_path_pub")
    qos = QoSProfile(
        depth=1,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
        reliability=ReliabilityPolicy.RELIABLE,
    )
    pub = pub_node.create_publisher(Path, TOPIC_ROUTE_PATH, qos)

    b = WaypointsRosBridge()
    b.start()
    q: queue.Queue = queue.Queue()
    b.register_listener(q)
    try:
        path = Path()
        path.header.frame_id = "map"
        for x, y in [(1.0, 2.0), (3.0, 4.0)]:
            ps = PoseStamped()
            ps.pose.position.x = x
            ps.pose.position.y = y
            path.poses.append(ps)
        got = None
        for _ in range(20):
            pub.publish(path)
            rclpy.spin_once(pub_node, timeout_sec=0.1)
            time.sleep(0.1)
            try:
                while True:
                    ev = q.get_nowait()
                    if ev.get("type") == "route_path":
                        got = ev
            except queue.Empty:
                pass
            if got is not None:
                break
        assert got is not None, "route_path SSE 미수신"
        assert got["points"] == [(1.0, 2.0), (3.0, 4.0)]
    finally:
        b.shutdown()
        pub_node.destroy_node()
        rclpy.shutdown()


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
