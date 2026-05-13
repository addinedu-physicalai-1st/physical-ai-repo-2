"""Eduping (OpenArm) ROS bridge — leader/follower state pump + recorder + player.

FastAPI 라이프사이클이 한 번 만들고, 라우터가 동기 메서드를 호출. rclpy spin 은 background
daemon thread 에서 단독으로 돌고, 외부 코드는 본 클래스의 thread-safe 메서드만 사용.

토픽:
  - 입력 sub  /eduping/leader/joint_states     (sensor_msgs/JointState)   — fake/feetech leader
  - 입력 sub  /joint_states                    (sensor_msgs/JointState)   — sim_twin / 실물 controller
  - 출력 pub  /eduping/joint_trajectory        (trajectory_msgs/JointTrajectory) — player
        실물 모드에서는 launch remap 으로 controller 토픽 (/joint_trajectory_controller/...) 으로 우회.

상태머신: idle | recording(kind, name, t_start, samples).
녹화/재생 셀렉트는 [shared/openarm_dance/<slug>/motion.yaml] 또는
[shared/openarm_greeting/{morning,evening}.yaml] 위치를 기준으로 한다.

ROS 미설정 환경에서는 import 자체는 성공하되 NewBridge() 가 BridgeUnavailable 을 던진다 —
라우터가 503 응답으로 graceful 처리.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# --- ROS 가용성 검사 (라우터 503 응답에 활용) ----------------------------

try:
    import rclpy  # noqa: F401
    from builtin_interfaces.msg import Duration
    from rclpy.node import Node
    from sensor_msgs.msg import JointState
    from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

    _ROS_AVAILABLE = True
    _ROS_IMPORT_ERROR: Exception | None = None
except Exception as _e:  # pragma: no cover - env-specific
    _ROS_AVAILABLE = False
    _ROS_IMPORT_ERROR = _e


def ros_available() -> bool:
    return _ROS_AVAILABLE


class BridgeUnavailable(RuntimeError):
    """ROS 환경 미설정으로 bridge 를 만들 수 없음."""


TOPIC_LEADER = "/eduping/leader/joint_states"
TOPIC_FOLLOWER = "/joint_states"
TOPIC_TRAJECTORY = "/eduping/joint_trajectory"

# routine 타입
KIND_DANCE = "dance"
KIND_GREETING = "greeting"


# --- 데이터 -----------------------------------------------------------------


@dataclass
class _JsState:
    joint_names: list[str] = field(default_factory=list)
    positions: list[float] = field(default_factory=list)
    received_at_s: float = 0.0


@dataclass
class _RecordingState:
    active: bool = False
    kind: str = ""           # dance | greeting
    name: str = ""           # slug or slot
    started_at_s: float = 0.0
    joint_names: list[str] = field(default_factory=list)
    samples: list[tuple[float, list[float]]] = field(default_factory=list)


# --- Bridge -----------------------------------------------------------------


class EdupingRosBridge:
    """rclpy lifecycle + leader/follower 모니터 + 녹화 state machine + trajectory publisher.

    `routines_root` = repo 의 `shared/` 디렉토리. 안에 openarm_dance / openarm_greeting.
    """

    def __init__(self, routines_root: Path) -> None:
        if not _ROS_AVAILABLE:
            raise BridgeUnavailable(
                f"rclpy / 메시지 타입 import 실패 — ROS 환경이 source 되었는지 확인. ({_ROS_IMPORT_ERROR})"
            )
        self._routines_root = Path(routines_root).resolve()
        if not self._routines_root.exists():
            raise BridgeUnavailable(f"routines_root 가 존재하지 않음: {self._routines_root}")

        self._lock = threading.Lock()
        self._node: Node | None = None
        self._js_pub = None
        self._spin_thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

        self._leader = _JsState()
        self._follower = _JsState()
        self._recording = _RecordingState()

        # listener: dict[topic_name, set[callback]] — WS hub 들이 등록.
        self._listeners_state: set[Callable[[dict], Any]] = set()
        self._listeners_recording: set[Callable[[dict], Any]] = set()

    # ---------- properties --------------------------------------------------

    @property
    def routines_root(self) -> Path:
        return self._routines_root

    # ---------- lifecycle ---------------------------------------------------

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._node is not None:
            return
        self._loop = loop
        if not rclpy.ok():
            rclpy.init()
        self._node = rclpy.create_node("control_eduping_bridge")
        self._js_pub = self._node.create_publisher(JointTrajectory, TOPIC_TRAJECTORY, 10)
        self._node.create_subscription(JointState, TOPIC_LEADER, self._on_leader, 50)
        self._node.create_subscription(JointState, TOPIC_FOLLOWER, self._on_follower, 50)
        self._spin_thread = threading.Thread(target=self._spin, name="eduping-rclpy", daemon=True)
        self._spin_thread.start()
        logger.info(
            "EdupingRosBridge started — leader_sub=%s follower_sub=%s traj_pub=%s root=%s",
            TOPIC_LEADER, TOPIC_FOLLOWER, TOPIC_TRAJECTORY, self._routines_root,
        )

    def stop(self) -> None:
        self._stopping.set()
        if self._node is not None:
            try:
                self._node.destroy_node()
            except Exception:  # noqa: BLE001
                pass
            self._node = None
        # rclpy.shutdown() 은 다른 bridge 와 공유될 수 있어 호출하지 않음.

    def _spin(self) -> None:
        node = self._node
        if node is None:
            return
        while not self._stopping.is_set() and rclpy.ok():
            try:
                rclpy.spin_once(node, timeout_sec=0.05)
            except Exception as exc:  # noqa: BLE001
                logger.debug("spin_once 예외: %s", exc)
                time.sleep(0.05)

    # ---------- subscribers -------------------------------------------------

    def _on_leader(self, msg: "JointState") -> None:
        names = list(msg.name)
        pos = [float(x) for x in msg.position]
        now = time.monotonic()
        with self._lock:
            self._leader = _JsState(joint_names=names, positions=pos, received_at_s=now)
            if self._recording.active:
                t_rel = now - self._recording.started_at_s
                # joint_names 정렬 보정 — recorder 는 leader 가 보낸 이름 그대로 저장.
                if not self._recording.joint_names:
                    self._recording.joint_names = list(names)
                self._recording.samples.append((t_rel, list(pos)))

    def _on_follower(self, msg: "JointState") -> None:
        names = list(msg.name)
        pos = [float(x) for x in msg.position]
        with self._lock:
            self._follower = _JsState(joint_names=names, positions=pos, received_at_s=time.monotonic())

    # ---------- snapshots (for WS hubs) ------------------------------------

    def state_snapshot(self) -> dict:
        with self._lock:
            return {
                "ts": time.time(),
                "leader": _js_to_dict(self._leader),
                "follower": _js_to_dict(self._follower),
            }

    def recording_snapshot(self) -> dict:
        with self._lock:
            r = self._recording
            if not r.active:
                return {"ts": time.time(), "active": False}
            return {
                "ts": time.time(),
                "active": True,
                "kind": r.kind,
                "name": r.name,
                "frame_count": len(r.samples),
                "elapsed_s": time.monotonic() - r.started_at_s,
                "joint_names": list(r.joint_names),
            }

    # ---------- recording control (called from FastAPI handlers) -----------

    def start_recording(self, kind: str, name: str) -> dict:
        if kind not in (KIND_DANCE, KIND_GREETING):
            raise ValueError(f"invalid kind {kind!r}")
        with self._lock:
            if self._recording.active:
                raise RecordingConflict(
                    f"이미 녹화 중: kind={self._recording.kind} name={self._recording.name}"
                )
            self._recording = _RecordingState(
                active=True,
                kind=kind,
                name=name,
                started_at_s=time.monotonic(),
                joint_names=[],
                samples=[],
            )
        return {"active": True, "kind": kind, "name": name}

    def stop_recording(self, save: bool) -> dict:
        with self._lock:
            r = self._recording
            if not r.active:
                raise RecordingNotActive("녹화 중이 아닙니다")
            self._recording = _RecordingState()  # reset

        result = {
            "saved": False,
            "kind": r.kind,
            "name": r.name,
            "frame_count": len(r.samples),
            "duration_s": (r.samples[-1][0] - r.samples[0][0]) if len(r.samples) >= 2 else 0.0,
        }
        if not save or not r.samples:
            return result

        # save → routines_io
        from pingdergarten_openarm.routines_io import (  # type: ignore[import-not-found]
            Routine,
            build_keyframes,
            dance_motion_path,
            greeting_yaml_path,
            save_routine,
        )

        keyframes = build_keyframes(r.samples)
        routine = Routine(
            name=r.name,
            kind=r.kind,
            keyframes=keyframes,
            sample_hz=_estimate_hz(r.samples),
            recorded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            joint_names=list(r.joint_names),
        )
        if r.kind == KIND_GREETING:
            target_path = greeting_yaml_path(self._routines_root, r.name)
        else:
            target_path = dance_motion_path(self._routines_root, r.name)
        save_routine(target_path, routine)
        result["saved"] = True
        result["path"] = str(target_path)
        result["duration_s"] = round(routine.duration_s, 3)
        return result

    # ---------- playback ----------------------------------------------------

    def play_routine(self, kind: str, name: str, *, speed: float = 1.0) -> dict:
        if speed <= 0:
            speed = 1.0
        from pingdergarten_openarm.routines_io import (  # type: ignore[import-not-found]
            dance_motion_path,
            greeting_yaml_path,
            load_routine,
        )

        if kind == KIND_GREETING:
            path = greeting_yaml_path(self._routines_root, name)
        elif kind == KIND_DANCE:
            path = dance_motion_path(self._routines_root, name)
        else:
            raise ValueError(f"invalid kind {kind!r}")
        if not path.exists():
            raise FileNotFoundError(f"routine 없음: {path}")
        routine = load_routine(path)
        if not routine.keyframes:
            raise ValueError(f"{path}: keyframes 비어있음")

        msg = JointTrajectory()
        msg.joint_names = list(routine.joint_names)
        for kf in routine.keyframes:
            t_scaled = kf.t / speed
            sec = int(t_scaled)
            nsec = int((t_scaled - sec) * 1e9)
            pt = JointTrajectoryPoint()
            pt.positions = [float(x) for x in kf.pos]
            pt.time_from_start = Duration(sec=sec, nanosec=nsec)
            msg.points.append(pt)

        if self._js_pub is None:
            raise BridgeUnavailable("publisher not initialized — start() 호출 안됨")
        self._js_pub.publish(msg)
        return {
            "ok": True,
            "path": str(path),
            "frame_count": len(msg.points),
            "duration_s": round(routine.duration_s / speed, 3),
            "speed": speed,
        }


# --- helpers ----------------------------------------------------------------


def _js_to_dict(js: _JsState) -> dict | None:
    if not js.joint_names:
        return None
    return {
        "joint_names": list(js.joint_names),
        "positions": list(js.positions),
        "age_s": max(0.0, time.monotonic() - js.received_at_s),
    }


def _estimate_hz(samples: list[tuple[float, list[float]]]) -> int:
    if len(samples) < 2:
        return 50
    duration = samples[-1][0] - samples[0][0]
    if duration <= 0:
        return 50
    return max(1, int(round((len(samples) - 1) / duration)))


# --- exceptions -------------------------------------------------------------


class RecordingConflict(RuntimeError):
    """이미 녹화 중일 때 다시 시작 시도."""


class RecordingNotActive(RuntimeError):
    """녹화 중 아닐 때 stop 시도."""
