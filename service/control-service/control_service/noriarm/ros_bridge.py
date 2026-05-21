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


def _home_pose_listener_factory(
    *,
    joint_names: list[str],
    on_event: Callable[[int], None],
) -> Callable[[dict], None]:
    """SSE forward 콜백과 동일한 dict payload 를 받아 HomePoseDetector 를 돌리는 헬퍼.

    bridge.add_joint_state_listener() 에 등록할 콜백을 만든다. 게임이 끝나고
    detector 가 리셋되어야 할 때는 unsubscribe 한 뒤 다시 factory 를 호출한다.
    """
    from noriarm_framework.games.block_stacking.home_pose import HomePoseDetector  # lazy

    detector = HomePoseDetector(holding_s=0.5)
    expected = list(joint_names)

    def on_payload(payload: dict) -> None:
        names = payload.get("name") or []
        position = payload.get("position") or []
        idx_map = {n: i for i, n in enumerate(names)}
        try:
            joints = [position[idx_map[n]] for n in expected]
        except (KeyError, IndexError):
            return  # 우리가 원하는 5 축이 다 안 들어옴 — 무시.
        stamp = payload.get("stamp") or {}
        t = float(stamp.get("sec", 0)) + float(stamp.get("nanosec", 0)) * 1e-9
        before = detector.events
        after = detector.update(t=t, joint_positions=joints)
        if after > before:
            on_event(after)

    return on_payload


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
    from rclpy.action import ActionClient
    from rclpy.node import Node
    from sensor_msgs.msg import JointState
    from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

    _ROS_AVAILABLE = True
except Exception as _e:  # pragma: no cover - env-specific
    _ROS_AVAILABLE = False
    _ROS_IMPORT_ERROR = _e

# control_msgs (그리퍼 액션) 는 별도 try — 환경에 따라 ros_control 만 있고 control_msgs
# 가 빠진 경우가 있어 분리. 없으면 그리퍼 동작은 no-op.
try:
    from control_msgs.action import GripperCommand  # type: ignore[import-not-found]

    _HAS_GRIPPER_ACTION = True
except Exception:  # pragma: no cover - env-specific
    GripperCommand = None  # type: ignore[assignment, misc]
    _HAS_GRIPPER_ACTION = False


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
            "controller/noriarm-controller/src/noriarm_framework 가 PYTHONPATH 에 있어야 합니다."
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
        self._jt_pub = None  # real arm_controller 용 JointTrajectory publisher
        self._gripper_client: Any = None  # real omx_f 의 GripperActionController action client
        self._target: str = "sim"  # start() 에서 자동 감지
        self._controller_joint_names: list[str] = []
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
        # 같은 프로세스의 다른 bridge 가 먼저 init 했을 수 있다.
        if not rclpy.ok():
            rclpy.init()
        self._node = rclpy.create_node("control_noriarm_bridge")

        topic = self._arm.sim.get("joint_state_topic", "/joint_states")
        self._js_pub = self._node.create_publisher(JointState, topic, 10)
        self._js_sub = self._node.create_subscription(
            JointState, topic, self._on_joint_state, 10
        )

        # 실물 OMX 연결 시 JointTrajectory publisher 도 같이 — arm_controller 가 받음.
        # /dev/omx_follower (또는 manifest 의 real.port) 존재 = real 타깃.
        real_port = (self._arm.real or {}).get("port") if hasattr(self._arm, "real") else None
        self._target = "real" if real_port and Path(real_port).exists() else "sim"

        controller_topic = getattr(self._arm, "controller_topic", None)
        controller_joints = list(getattr(self._arm, "controller_joint_names", []) or [])
        if self._target == "real" and controller_topic and controller_joints:
            self._jt_pub = self._node.create_publisher(JointTrajectory, controller_topic, 10)
            self._controller_joint_names = controller_joints
            logger.info(
                f"real 타깃 감지 ({real_port}) — JointTrajectory pub: "
                f"{controller_topic} joints={controller_joints}"
            )
            # omx_f bringup 의 gripper_controller 는 별도 GripperActionController —
            # arm_controller 가 받는 trajectory 의 gripper 컬럼은 어차피 잘리기 때문에
            # gripper 는 직접 액션으로 닫아준다.
            if _HAS_GRIPPER_ACTION and GripperCommand is not None:
                self._gripper_client = ActionClient(
                    self._node, GripperCommand, self.GRIPPER_ACTION_NAME,
                )
                logger.info(
                    f"GripperActionController client 준비: {self.GRIPPER_ACTION_NAME}"
                )
            else:
                logger.warning(
                    "control_msgs.action.GripperCommand import 실패 — 그리퍼 동작 비활성화"
                )
        else:
            logger.info(f"sim 타깃 (real_port={real_port}, exists={bool(real_port and Path(real_port).exists())})")

        logger.info(
            f"NoriarmRosBridge 시작: game={self._config.name} topic={topic} "
            f"arm={self._arm.id} target={self._target}"
        )
        # 정책도 reset.
        ctx = self._fw["GameContext"](game_name=self._config.name, target=self._target)
        self._policy.reset(ctx)

        self._stopping.clear()
        self._spin_thread = threading.Thread(target=self._spin_loop, daemon=True)
        self._spin_thread.start()

        # bridge 가 올라온 직후 그리퍼를 학습 데이터의 시작 자세로 옮긴다 — 닫힘 강제가
        # 아니라 trained 첫 프레임 그대로 (OX 퀴즈 학습은 시작이 open). 매 답마다 trajectory
        # 전체를 그리퍼 컬럼대로 다시 재생하므로 본 startup 명령은 "ready pose" 역할.
        if self._target == "real" and self._gripper_client is not None:
            initial_rad = self._bridge_start_gripper_initial_rad()
            if initial_rad is not None:
                asyncio.run_coroutine_threadsafe(
                    self._send_gripper_goal(
                        context="bridge-start", position=initial_rad,
                    ),
                    loop,
                )
            else:
                logger.info(
                    "bridge-start 그리퍼 자세 스킵 — trained 데이터에서 시작 자세를 못 구함"
                )

    # --------------------------------------------------- 그리퍼 (real omx_f)
    # 그리퍼 목표 각도는 절대 하드코딩하지 않는다 — 학습된 trajectory 의 그리퍼 컬럼을
    # 그대로 재생한다. trained 패턴 (예: OX 퀴즈) 은 open → close → open 의 자연스러운
    # 흐름인데 한 값으로 강제하면 그 흐름이 깨진다.
    GRIPPER_MAX_EFFORT = 5.0  # 모터 안전 한도 — 학습 데이터 외 ROS-level 상수.
    GRIPPER_ACTION_NAME = "/gripper_controller/gripper_cmd"

    def _gripper_column_to_rad(self, traj: Any) -> list[float] | None:
        """trajectory 의 그리퍼 컬럼 전체를 URDF rad 리스트로. 없으면 None."""
        n_arm = len(self._controller_joint_names)
        if traj.num_columns <= n_arm:
            return None
        gripper_idx = n_arm
        modes = list(self._arm.sim.get("joint_norm_modes") or [])
        mode = modes[gripper_idx] if gripper_idx < len(modes) else "range_0_100"
        convert = _norm_to_rad(mode)
        return [convert(row[gripper_idx]) for row in traj.frames_deg]

    def _bridge_start_gripper_initial_rad(self) -> float | None:
        """bridge-start 의 그리퍼 초기 자세 — manifest 의 첫 trajectory 의 frame 0 값.

        학습 데이터의 시작 pose 그대로 — OX 퀴즈에선 open. 못 구하면 None → 스킵.
        """
        try:
            tmap = self._config.policy.extra.get("trajectory_map") or {}
        except AttributeError:
            return None
        if not isinstance(tmap, dict) or not tmap:
            return None
        first_name = next(iter(tmap.values()))
        traj_path = self._manifest_path.parent / str(first_name)
        try:
            traj = self._fw["load_trajectory"](traj_path)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"bridge-start gripper 초기 자세 로드 실패 ({traj_path}): {e}")
            return None
        rads = self._gripper_column_to_rad(traj)
        if not rads:
            return None
        return rads[0]  # 학습 데이터의 첫 프레임 = trained 시작 자세

    async def _send_gripper_goal(self, *, context: str, position: float) -> None:
        """GripperCommand action goal 한 번 송신 — 결과까지 대기 (bridge-start 단발용).

        position 은 호출자가 trained 데이터에서 가져온다 (하드코딩 X).
        spin thread 가 future 를 완료시키므로 asyncio 측에서는 폴링만 한다.
        action server 미연결·거부·타임아웃은 경고만, 트레이젝토리 재생 등 다른 흐름 차단 X.
        """
        if self._gripper_client is None or GripperCommand is None:
            return
        target_rad = float(position)
        log_prefix = f"[gripper:{context}]"
        logger.info(
            f"{log_prefix} 자세 시도: action={self.GRIPPER_ACTION_NAME} "
            f"position={target_rad:.3f} rad max_effort={self.GRIPPER_MAX_EFFORT}"
        )
        # wait_for_server 는 동기 + 짧게.
        ready = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._gripper_client.wait_for_server(timeout_sec=2.0),
        )
        if not ready:
            logger.warning(
                f"{log_prefix}   ✗ action server '{self.GRIPPER_ACTION_NAME}' 미확인 (2s) — "
                "controller_manager 의 gripper_controller 가 spawn 됐는지 확인 "
                "(`ros2 control list_controllers`)"
            )
            return
        goal = GripperCommand.Goal()
        goal.command.position = target_rad
        goal.command.max_effort = float(self.GRIPPER_MAX_EFFORT)
        send_future = self._gripper_client.send_goal_async(goal)
        if not await self._await_rclpy_future(send_future, timeout_s=2.0):
            logger.warning(f"{log_prefix}   ✗ send_goal 응답 타임아웃")
            return
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            logger.warning(f"{log_prefix}   ✗ goal 거부됨 (handle={goal_handle})")
            return
        logger.info(f"{log_prefix}   ✓ goal accepted — 결과 대기 (최대 5s)")
        result_future = goal_handle.get_result_async()
        if not await self._await_rclpy_future(result_future, timeout_s=5.0):
            logger.warning(f"{log_prefix}   ⚠ 5s 안에 결과 안 옴 — 진행")
            return
        res = result_future.result()
        logger.info(
            f"{log_prefix}   ✓ 완료: status={res.status} "
            f"reached={res.result.reached_goal} stalled={res.result.stalled} "
            f"position={res.result.position:.3f} effort={res.result.effort:.3f}"
        )

    def _send_gripper_goal_fire_forget(self, *, position: float) -> None:
        """fire-and-forget GripperCommand — 결과 대기 없음. trajectory 재생용.

        action server 미준비면 조용히 스킵. send_goal_async 가 던지는 예외도 흡수
        (재생 도중 한 keyframe 이 미스되더라도 다음 keyframe 이 곧 따라옴).
        """
        if self._gripper_client is None or GripperCommand is None:
            return
        if not self._gripper_client.server_is_ready():
            return
        goal = GripperCommand.Goal()
        goal.command.position = float(position)
        goal.command.max_effort = float(self.GRIPPER_MAX_EFFORT)
        try:
            self._gripper_client.send_goal_async(goal)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"gripper send_goal_async 실패 (무시): {e}")

    async def _replay_gripper_trajectory(self, traj: Any) -> None:
        """학습 trajectory 의 그리퍼 컬럼을 녹화 hz 그대로 fire-and-forget 으로 재생.

        arm trajectory 는 한 message 로 controller 에 모두 넘어가지만 GripperAction-
        Controller 는 한 번에 하나의 goal 만 받는다 → 매 프레임 send_goal_async.
        sample rate 도 학습 데이터 (traj.hz) 에서 가져온다 — 자체 keyframe rate 를
        고르면 그게 또 하드코딩이고 transient 를 잘라먹어 stepped 모션이 보인다.
        """
        rads = self._gripper_column_to_rad(traj)
        if not rads:
            return
        n = len(rads)
        if traj.hz <= 0:
            return
        period = 1.0 / traj.hz
        logger.info(
            f"[gripper:replay-stream] 시작: frames={n} hz={traj.hz} "
            f"first={rads[0]:.3f} last={rads[-1]:.3f}"
        )
        for i in range(n):
            if self._stopping.is_set():
                return
            self._send_gripper_goal_fire_forget(position=rads[i])
            await asyncio.sleep(period)
        logger.info("[gripper:replay-stream] 완료")

    async def _await_rclpy_future(self, future: Any, *, timeout_s: float) -> bool:
        """rclpy.task.Future 가 spin thread 에서 완료되길 폴링으로 기다린다."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout_s
        while not future.done():
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(0.05)
        return True

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
        if self._target == "real" and self._jt_pub is not None:
            await self._play_real(traj, name)
        else:
            await self._play_sim(traj, name)
        # 정책을 다시 reset 해서 다음 답을 받을 수 있게.
        ctx = self._fw["GameContext"](game_name=self._config.name, target=self._target)
        self._policy.reset(ctx)

    async def _play_sim(self, traj: Any, name: str) -> None:
        """Sim 모드 — JointState 를 frame 마다 publish (URDF three.js 뷰어용)."""
        names = list(self._arm.sim.get("joint_state_names") or [])
        if not names:
            logger.error("joint_state_names 가 매니페스트에 없음 — 재생 취소")
            return
        modes = list(self._arm.sim.get("joint_norm_modes") or ["degrees"] * len(names))
        if len(modes) != len(names):
            logger.warning(
                f"joint_norm_modes 길이가 joint_state_names 와 다름 — 'degrees' 로 fallback"
            )
            modes = ["degrees"] * len(names)
        converters = [_norm_to_rad(m) for m in modes]

        sliced = traj.slice_columns(len(names))
        period = 1.0 / sliced.hz
        logger.info(
            f"sim 재생: {name} frames={sliced.num_frames} duration={sliced.duration_s:.2f}s"
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

    async def _play_real(self, traj: Any, name: str) -> None:
        """Real 모드 — JointTrajectory 한 메시지에 모든 frame 을 점으로 담아 publish.

        arm_controller (joint_trajectory_controller) 가 spline 보간으로 실행. 이렇게 하면
        프레임 단위 publish latency 없이 controller 가 RT 루프에서 정확한 타이밍 보장.

        arm trajectory 발사 직전에 그리퍼를 다시 닫는다 — 게임 중 미세하게 열리거나
        이전 답에서 jaws 가 풀린 경우 보정.
        """
        n = len(self._controller_joint_names)
        if n == 0:
            logger.error("controller_joint_names 가 매니페스트에 없음 — 재생 취소")
            return
        # 그리퍼는 학습 trajectory 의 그리퍼 컬럼대로 재생 — 한 자세로 강제하지 않는다.
        # 학습 곡선이 open→close→open 이면 그대로 따라간다. arm 재생과 병렬로 실행.
        gripper_task: asyncio.Task | None = None
        if self._target == "real" and self._gripper_client is not None:
            gripper_task = asyncio.create_task(self._replay_gripper_trajectory(traj))
        # controller 는 arm 만 받음 (gripper 별도 controller). joint_norm_modes 의 앞 n 개 사용.
        modes = list(self._arm.sim.get("joint_norm_modes") or ["degrees"] * n)[:n]
        converters = [_norm_to_rad(m) for m in modes]

        sliced = traj.slice_columns(n)
        period = 1.0 / sliced.hz

        msg = JointTrajectory()
        msg.joint_names = list(self._controller_joint_names)
        for i, frame in enumerate(sliced.frames_deg):
            pt = JointTrajectoryPoint()
            pt.positions = [converters[j](frame[j]) for j in range(n)]
            t = (i + 1) * period
            pt.time_from_start.sec = int(t)
            pt.time_from_start.nanosec = int((t - int(t)) * 1e9)
            msg.points.append(pt)

        if self._node is None:
            return
        self._jt_pub.publish(msg)
        logger.info(
            f"real publish: {name} points={len(msg.points)} duration={sliced.duration_s:.2f}s"
        )
        # arm_controller 가 알아서 실행 — 우리는 duration 만큼 idle 대기 (다음 답 전).
        await asyncio.sleep(sliced.duration_s)
        # 그리퍼 trajectory 재생이 끝났는지 확인 — keyframe pacing 으로 거의 동시에 끝나지만
        # subsampling 의 마지막 sleep 잔여가 있을 수 있어 살짝 더 대기. 예외도 surface.
        if gripper_task is not None:
            try:
                await asyncio.wait_for(gripper_task, timeout=1.0)
            except asyncio.TimeoutError:
                logger.warning("gripper replay 가 1s 안에 안 끝남 — 다음 답으로")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"gripper replay 에서 예외: {e}")
        logger.info("trajectory 재생 완료, 정책 reset")

    # ---------------------------------------------- block_stacking 세션
    async def start_block_stacking_session(
        self, on_home_event: Callable[[int], None]
    ) -> Callable[[], None]:
        """블럭쌓기 세션 시작 — home pose 이벤트 listener 를 붙이고 unsubscribe 함수 반환.

        ACT 추론은 별도 서브프로세스 (runner_entry) 가 담당. bridge 의 역할은
        /joint_states 를 구독하면서 HOME 임계 진입 이벤트를 카운트해 콜백으로
        흘려주는 것 한 가지.
        """
        cb = _home_pose_listener_factory(
            joint_names=list(self._arm.controller_joint_names),
            on_event=on_home_event,
        )
        return self.add_joint_state_listener(cb)

    async def play_rps_paper(self) -> dict:
        """RPS '보' trajectory replay 단발 호출 (서브프로세스 spawn 전에 bridge 가 직접 처리).

        block_stacking 의 ACT 게임 루프와 무관 — bridge 가 가진 publisher 로 OX 퀴즈
        replay 와 동일한 경로로 발사. block_stacking/rps_paper_trajectory.json 을
        package resource 로 로드.
        """
        from importlib import resources

        load_trajectory = self._fw["load_trajectory"]
        with resources.path(
            "noriarm_framework.games.block_stacking", "rps_paper_trajectory.json"
        ) as rps_path:
            traj = load_trajectory(rps_path)
        asyncio.create_task(self._play_trajectory(traj, "rps_paper_trajectory.json"))
        return {"ok": True, "action": "replay_trajectory", "duration_s": traj.duration_s}

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
