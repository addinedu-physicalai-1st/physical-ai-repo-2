"""Control Server ↔ ROS2 다리.

FastAPI 앱이 lifespan 으로 한 번 만들고, 라우터가 들어오는 요청을 이쪽으로 위임한다.
스레드 하나가 rclpy spin 을 돌리고, asyncio 루프 (FastAPI) 와 콜백을 안전하게 주고받기
위해 listener 콜백 호출 시 `loop.call_soon_threadsafe` 사용.

이 모듈은 ROS 환경이 source 된 상태에서만 import 가 성공한다. import 실패는
`BridgeUnavailable` 로 감싸 라우터가 503 으로 응답할 수 있게 한다.
"""
from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


def _norm_to_rad(mode: str) -> Callable[[float], float]:
    """lerobot 정규화 값 → URDF 라디안 변환 함수.

    OMX 의 모터 calibration 디폴트 (range_min=0 ticks, range_max=4095 ticks, mid=2047.5)
    에서 mid 가 URDF 의 home (joint=0 rad) 라고 가정한다. 정규화의 양 끝은 모터 풀 회전
    (±π rad) 으로 매핑.
        m100_100   : -100..+100  → -π..+π     (val × π/100)
        range_0_100: 0..100      → -π..+π    ((val−50) × π/50)
        degrees    : -180..+180  → -π..+π     (val × π/180)
    """
    if mode == "m100_100":
        return lambda v: v * math.pi / 100
    if mode == "range_0_100":
        return lambda v: (v - 50) * math.pi / 50
    if mode == "degrees":
        return lambda v: v * math.pi / 180
    logger.warning(f"unknown joint_norm_mode={mode!r} — 'degrees' 로 fallback")
    return lambda v: v * math.pi / 180


class BridgeUnavailable(RuntimeError):
    """ROS 환경 미설정으로 bridge 를 만들 수 없음."""


# --- import 시점 ROS 가용성 검사 (라우터의 503 응답에 활용) ---------------

try:
    import rclpy  # noqa: F401
    from rclpy.node import Node
    from sensor_msgs.msg import JointState
    from trajectory_msgs.msg import JointTrajectory  # noqa: F401  (real 타깃에서 사용)

    _ROS_AVAILABLE = True
except Exception as _e:  # pragma: no cover - env-specific
    _ROS_AVAILABLE = False
    _ROS_IMPORT_ERROR = _e


def ros_available() -> bool:
    return _ROS_AVAILABLE


# --- 매니페스트 / 정책 / trajectory 헬퍼는 noriarm_framework 에서 그대로 사용 ---


def _load_framework():
    """noriarm_framework 를 lazy import. PYTHONPATH 에 추가돼 있어야 한다."""
    try:
        from noriarm_framework.manifest import GameConfig, load_manifest
        from noriarm_framework.policy import (
            Action,
            GameContext,
            IdleAction,
            Observation,
            ReplayTrajectoryAction,
        )
        from noriarm_framework.trajectory import deg_to_rad, load_trajectory
    except ImportError as e:  # pragma: no cover
        raise BridgeUnavailable(
            "noriarm_framework 를 import 할 수 없음. "
            "device/noriarm_ws/src/noriarm_framework 가 PYTHONPATH 에 있어야 합니다."
        ) from e

    # _ros_runner.load_policy 은 rclpy 임포트하므로 우리도 동일 경로로.
    from noriarm_framework._ros_runner import load_policy

    return {
        "GameConfig": GameConfig,
        "load_manifest": load_manifest,
        "Action": Action,
        "GameContext": GameContext,
        "IdleAction": IdleAction,
        "Observation": Observation,
        "ReplayTrajectoryAction": ReplayTrajectoryAction,
        "deg_to_rad": deg_to_rad,
        "load_trajectory": load_trajectory,
        "load_policy": load_policy,
    }


# --- Bridge ----------------------------------------------------------------


JointStateListener = Callable[[dict], Any]


class NoriarmRosBridge:
    """rclpy lifecycle + /joint_states pub-sub + 게임 trajectory 재생.

    한 인스턴스 = 한 게임 (현재는 ox_quiz). 다중 게임이 들어오면 게임 별로 매니페스트와
    정책을 별도 인스턴스로 들면 된다.
    """

    def __init__(self, manifest_path: str | Path) -> None:
        if not _ROS_AVAILABLE:
            raise BridgeUnavailable(
                f"rclpy / 메시지 타입 import 실패 — ROS 환경이 source 되었는지 확인. ({_ROS_IMPORT_ERROR})"
            )
        self._manifest_path = Path(manifest_path).resolve()
        self._fw = _load_framework()
        self._config = self._fw["load_manifest"](self._manifest_path)
        self._policy = self._fw["load_policy"](self._config)

        self._node: Node | None = None
        self._js_sub = None
        self._js_pub = None
        self._spin_thread: threading.Thread | None = None
        self._stopping = threading.Event()

        self._loop: asyncio.AbstractEventLoop | None = None
        self._listeners: set[JointStateListener] = set()

        # 단순화: arm 1개 + joint_state mode 만 (OX 퀴즈 전제).
        if len(self._config.arms) != 1:
            raise BridgeUnavailable("현재 bridge 는 단일 arm 게임만 지원")
        self._arm = self._config.arms[0]

    # -------------------------------------------------------- lifecycle

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._node is not None:
            return
        self._loop = loop
        rclpy.init()
        self._node = rclpy.create_node("control_noriarm_bridge")

        topic = self._arm.sim.get("joint_state_topic", "/joint_states")
        self._js_pub = self._node.create_publisher(JointState, topic, 10)
        self._js_sub = self._node.create_subscription(
            JointState, topic, self._on_joint_state, 10
        )
        logger.info(
            f"NoriarmRosBridge 시작: game={self._config.name} topic={topic} arm={self._arm.id}"
        )
        # 정책도 reset.
        ctx = self._fw["GameContext"](game_name=self._config.name, target="sim")
        self._policy.reset(ctx)

        self._stopping.clear()
        self._spin_thread = threading.Thread(target=self._spin_loop, daemon=True)
        self._spin_thread.start()

    def stop(self) -> None:
        if self._node is None:
            return
        self._stopping.set()
        if self._spin_thread is not None:
            self._spin_thread.join(timeout=2.0)
        try:
            self._node.destroy_node()
        finally:
            self._node = None
            try:
                rclpy.shutdown()
            except Exception:
                pass
        logger.info("NoriarmRosBridge 종료")

    def _spin_loop(self) -> None:
        while not self._stopping.is_set() and rclpy.ok():
            rclpy.spin_once(self._node, timeout_sec=0.1)

    # ----------------------------------------------- /joint_states pub/sub

    def add_joint_state_listener(self, cb: JointStateListener) -> Callable[[], None]:
        self._listeners.add(cb)

        def unsubscribe() -> None:
            self._listeners.discard(cb)

        return unsubscribe

    def _on_joint_state(self, msg: "JointState") -> None:  # noqa: F821 (ROS type)
        # rclpy spin 스레드에서 호출됨 — asyncio 루프로 안전하게 forward.
        if self._loop is None:
            return
        payload = {
            "name": list(msg.name),
            "position": list(msg.position),
            "velocity": list(msg.velocity),
            "stamp": {
                "sec": int(msg.header.stamp.sec),
                "nanosec": int(msg.header.stamp.nanosec),
            },
        }
        for cb in list(self._listeners):
            try:
                self._loop.call_soon_threadsafe(cb, payload)
            except RuntimeError:
                # 루프 셧다운 중 — 무시.
                pass

    # ------------------------------------------------- 게임 동작

    async def play_answer(self, answer: str) -> dict:
        """정책 → action → trajectory 재생을 비동기 background task 로 시작.

        Trajectory 를 먼저 load 해서 duration_s 를 응답에 포함 — UI 가 그 시간만큼 기다린
        뒤 다음 문제로 넘어갈 수 있게.
        """
        Observation = self._fw["Observation"]
        ReplayTrajectoryAction = self._fw["ReplayTrajectoryAction"]
        IdleAction = self._fw["IdleAction"]
        load_trajectory = self._fw["load_trajectory"]

        obs = Observation(extra={"answer": answer})
        action = self._policy.step(obs)

        if isinstance(action, IdleAction):
            return {"ok": True, "action": "idle", "answer": answer}
        if isinstance(action, ReplayTrajectoryAction):
            path = self._manifest_path.parent / action.name
            traj = load_trajectory(path)
            asyncio.create_task(self._play_trajectory(traj, action.name))
            return {
                "ok": True,
                "action": "replay_trajectory",
                "name": action.name,
                "duration_s": traj.duration_s,
            }
        return {"ok": False, "reason": f"unknown action {action!r}"}

    async def _play_trajectory(self, traj: Any, name: str) -> None:
        names = list(self._arm.sim.get("joint_state_names") or [])
        if not names:
            logger.error("joint_state_names 가 매니페스트에 없음 — 재생 취소")
            return
        # 컬럼별 정규화 모드 → URDF 라디안 변환 함수 리스트. 매니페스트 누락 시 'degrees'.
        modes = list(self._arm.sim.get("joint_norm_modes") or ["degrees"] * len(names))
        if len(modes) != len(names):
            logger.warning(
                f"joint_norm_modes 길이가 joint_state_names 와 다름 — 'degrees' 로 fallback"
            )
            modes = ["degrees"] * len(names)
        converters = [_norm_to_rad(m) for m in modes]

        # URDF mimic joint (예: gripper_joint_2 = -1 * gripper_joint_1) 는 urdf-loader 가
        # 자동 처리 — bridge 는 source joint 만 publish 한다.
        sliced = traj.slice_columns(len(names))
        period = 1.0 / sliced.hz
        logger.info(
            f"trajectory 재생 시작: {name} frames={sliced.num_frames} duration={sliced.duration_s:.2f}s "
            f"modes={modes}"
        )
        for frame in sliced.frames_deg:
            if self._stopping.is_set() or self._node is None:
                break
            positions = [converters[i](frame[i]) for i in range(len(names))]
            msg = JointState()
            msg.header.stamp = self._node.get_clock().now().to_msg()
            msg.name = names
            msg.position = positions
            self._js_pub.publish(msg)
            await asyncio.sleep(period)
        # 정책을 다시 reset 해서 다음 답을 받을 수 있게.
        ctx = self._fw["GameContext"](game_name=self._config.name, target="sim")
        self._policy.reset(ctx)
        logger.info("trajectory 재생 완료, 정책 reset")

    # ---------------------------------------------- 정보 조회

    def info(self) -> dict:
        return {
            "ros_available": _ROS_AVAILABLE,
            "running": self._node is not None,
            "game": self._config.name,
            "arm_id": self._arm.id,
            "joint_state_topic": self._arm.sim.get("joint_state_topic"),
            "joint_state_names": list(self._arm.sim.get("joint_state_names") or []),
            "listeners": len(self._listeners),
        }
