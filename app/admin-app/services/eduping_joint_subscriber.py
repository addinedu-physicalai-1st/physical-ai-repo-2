"""Standalone OpenArm joint-state subscriber for the admin app.

Bypasses the control-service WS path — the admin app spawns its own rclpy node and
subscribes directly to `/joint_states` (or the topic specified by
`ADMIN_OPENARM_JOINT_TOPIC`). Each incoming `sensor_msgs/JointState` is forwarded
to registered listeners on the asyncio loop they were registered with.

This lets the EduPing tab render a live arm as long as the leader bringup
(`scripts/device-eduping-leader.sh`) is publishing to ROS on the same
ROS_DOMAIN_ID — no control-service required.

rclpy is imported lazily so the admin app still launches in environments where
ROS isn't sourced (the subscriber just becomes a no-op).
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)


JointStateListener = Callable[[dict], Any]


def _try_import_ros() -> tuple[Any, Any, Any] | None:
    try:
        import rclpy  # noqa: F401
        from rclpy.node import Node  # noqa: F401
        from sensor_msgs.msg import JointState  # noqa: F401
    except Exception as e:  # noqa: BLE001 - covers ImportError + system-level issues
        # Stash on the function so callers (and the UI) can read the actual reason.
        _try_import_ros.last_error = repr(e)  # type: ignore[attr-defined]
        logger.info(
            "rclpy/sensor_msgs import 실패 — 직접 ROS 구독 비활성. "
            "ROS env (`source /opt/ros/jazzy/setup.bash`) 가 필요. (%s)", e,
        )
        return None
    _try_import_ros.last_error = None  # type: ignore[attr-defined]
    return rclpy, Node, JointState


def last_import_error() -> str | None:
    """Returns the last rclpy/sensor_msgs import error message, or None if ok.

    Populated by `_try_import_ros()` (called from `start()`).
    """
    return getattr(_try_import_ros, "last_error", None)


class EdupingJointStateSubscriber:
    """Daemon-thread rclpy node listening to `/joint_states`.

    Public API mirrors the existing `StateClient` style — `start()` to begin,
    `add_listener(cb)` to register a snapshot callback, `stop()` for shutdown.
    Listeners are called from the rclpy spin thread; if they need to touch Qt
    widgets they must marshal back to the GUI thread themselves.
    """

    # 기본 토픽은 device-eduping-leader.sh 가 publish 하는 곳 — `eduarm.feetech_leader_node`
    # 가 16 joint (왼팔/오른팔 각 7 + finger 1) 를 한 메시지로 publish.
    # follower bringup (device-eduping.sh) 은 일반적으로 /joint_states 를 쓰므로 환경에
    # 따라 ADMIN_OPENARM_JOINT_TOPIC 로 override.
    DEFAULT_TOPIC = "/eduping/leader/joint_states"

    def __init__(self, *, topic: str | None = None) -> None:
        self._topic = topic or os.environ.get(
            "ADMIN_OPENARM_JOINT_TOPIC", self.DEFAULT_TOPIC,
        )
        self._listeners: list[JointStateListener] = []
        self._lock = threading.Lock()
        self._node: Any = None
        self._spin_thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._ros: tuple[Any, Any, Any] | None = None
        self._owns_rclpy_init = False
        self._available = False
        # Diagnostics — exposed so the UI can show "got N msgs from /topic".
        self._msg_count = 0
        import time as _time
        self._mono = _time.monotonic
        self._last_msg_mono: float = 0.0
        self._last_error: str | None = None

    @property
    def topic(self) -> str:
        return self._topic

    @property
    def available(self) -> bool:
        """True once start() succeeded (rclpy importable + node created)."""
        return self._available

    @property
    def msg_count(self) -> int:
        return self._msg_count

    @property
    def last_msg_mono(self) -> float:
        """Monotonic time (seconds) of the last incoming message, or 0 if never."""
        return self._last_msg_mono

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def add_listener(self, cb: JointStateListener) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(cb)

        def unsubscribe() -> None:
            with self._lock:
                try:
                    self._listeners.remove(cb)
                except ValueError:
                    pass

        return unsubscribe

    def start(self) -> bool:
        """Initialize rclpy + start spin thread. Returns True on success."""
        if self._node is not None:
            return True
        self._ros = _try_import_ros()
        if self._ros is None:
            self._last_error = last_import_error() or "rclpy import 실패 (원인 불명)"
            return False
        rclpy, Node, JointState = self._ros
        try:
            if not rclpy.ok():
                rclpy.init()
                self._owns_rclpy_init = True
            self._node = rclpy.create_node("admin_openarm_joint_subscriber")
            self._node.create_subscription(
                JointState, self._topic, self._on_state, 10,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("rclpy 노드 생성 실패: %s", e)
            self._last_error = f"노드 생성 실패: {e!r}"
            self._node = None
            return False
        self._last_error = None
        self._stopping.clear()
        self._spin_thread = threading.Thread(
            target=self._spin_loop, name="admin-openarm-spin", daemon=True,
        )
        self._spin_thread.start()
        self._available = True
        logger.info(
            "admin-app rclpy 구독 시작: topic=%s ROS_DOMAIN_ID=%s",
            self._topic, os.environ.get("ROS_DOMAIN_ID", "(unset)"),
        )
        return True

    def stop(self) -> None:
        self._stopping.set()
        if self._spin_thread is not None:
            self._spin_thread.join(timeout=2.0)
            self._spin_thread = None
        if self._node is not None:
            try:
                self._node.destroy_node()
            except Exception:  # noqa: BLE001
                pass
            self._node = None
        if self._owns_rclpy_init and self._ros is not None:
            rclpy = self._ros[0]
            try:
                rclpy.shutdown()
            except Exception:  # noqa: BLE001
                pass
            self._owns_rclpy_init = False
        self._available = False

    # ------------------------------------------------ internals

    def _on_state(self, msg: Any) -> None:
        # `position` / `velocity` are float64 arrays; cast to list for json-friendly snap.
        snap = {
            "joint_names": list(msg.name),
            "positions": [float(p) for p in msg.position],
            "velocities": (
                [float(v) for v in msg.velocity] if list(msg.velocity) else []
            ),
            "stamp_sec": int(msg.header.stamp.sec),
            "stamp_nanosec": int(msg.header.stamp.nanosec),
        }
        self._msg_count += 1
        self._last_msg_mono = self._mono()
        if self._msg_count == 1:
            logger.info(
                "첫 메시지 수신: topic=%s joints=%d", self._topic, len(snap["joint_names"]),
            )
        with self._lock:
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(snap)
            except Exception as e:  # noqa: BLE001
                logger.warning("joint-state listener 콜백 실패: %s", e)

    def _spin_loop(self) -> None:
        if self._ros is None or self._node is None:
            return
        rclpy = self._ros[0]
        # 50ms spin timeout — long enough to be cheap when idle, short enough
        # that stop() returns within ~1 cycle. Was 100ms; cut in half to make
        # callback latency more responsive without measurable CPU cost.
        while not self._stopping.is_set() and rclpy.ok():
            try:
                rclpy.spin_once(self._node, timeout_sec=0.05)
            except Exception as e:  # noqa: BLE001
                logger.warning("rclpy spin_once 실패: %s", e)
                break
