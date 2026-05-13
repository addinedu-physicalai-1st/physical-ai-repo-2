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
import subprocess
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
    from control_msgs.action import FollowJointTrajectory, GripperCommand
    from controller_manager_msgs.srv import SwitchController
    from rclpy.action import ActionClient
    from rclpy.node import Node
    from sensor_msgs.msg import JointState
    from std_msgs.msg import Float64MultiArray
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
        self._executor: Any = None
        self._js_pub = None
        self._spin_thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

        self._leader = _JsState()
        self._follower = _JsState()
        self._recording = _RecordingState()
        # Playback: bridge 내부 보간기 — sim_twin_node 없이도 UI follower 채널에 동작.
        self._playback_thread: threading.Thread | None = None
        self._playback_stop = threading.Event()
        # Real follower 의 ros2_control action client 4 종 — start() 에서 생성.
        self._ac_right_arm: Any = None
        self._ac_left_arm: Any = None
        self._ac_right_gripper: Any = None
        self._ac_left_gripper: Any = None
        # Live teleop — forward_position_controller 토픽 publisher + 컨트롤러 스위칭 서비스.
        self._pub_right_forward: Any = None
        self._pub_left_forward: Any = None
        self._switch_controller_cli: Any = None
        # "실물 follower 연결됨" 캐시 (tmux 세션 hardware_type 검사 TTL).
        self._real_active_at: float = 0.0
        self._real_active_val: bool = False
        # Live teleop 독립 상태 — 녹화와 무관하게 leader → forward_position 패스스루 ON/OFF.
        self._teleop_active: bool = False

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
        from rclpy.executors import SingleThreadedExecutor

        self._loop = loop
        if not rclpy.ok():
            rclpy.init()
        self._node = rclpy.create_node("control_eduping_bridge")
        self._js_pub = self._node.create_publisher(JointTrajectory, TOPIC_TRAJECTORY, 10)
        self._node.create_subscription(JointState, TOPIC_LEADER, self._on_leader, 50)
        self._node.create_subscription(JointState, TOPIC_FOLLOWER, self._on_follower, 50)
        # Real follower action clients — server 가 아직 안 떠 있을 수 있으니 wait 은 send 시점.
        self._ac_right_arm = ActionClient(
            self._node, FollowJointTrajectory, "/right_joint_trajectory_controller/follow_joint_trajectory"
        )
        self._ac_left_arm = ActionClient(
            self._node, FollowJointTrajectory, "/left_joint_trajectory_controller/follow_joint_trajectory"
        )
        self._ac_right_gripper = ActionClient(
            self._node, GripperCommand, "/right_gripper_controller/gripper_cmd"
        )
        self._ac_left_gripper = ActionClient(
            self._node, GripperCommand, "/left_gripper_controller/gripper_cmd"
        )
        # Live teleop publishers + switch service client.
        self._pub_right_forward = self._node.create_publisher(
            Float64MultiArray, "/right_forward_position_controller/commands", 10
        )
        self._pub_left_forward = self._node.create_publisher(
            Float64MultiArray, "/left_forward_position_controller/commands", 10
        )
        self._switch_controller_cli = self._node.create_client(
            SwitchController, "/controller_manager/switch_controller"
        )
        # teleop 패턴 — 명시 SingleThreadedExecutor 에 본 노드만 add. 노리암/teleop 와
        # 같은 프로세스에 공존할 때 rclpy.spin_once 글로벌 default executor 경합 회피.
        self._executor = SingleThreadedExecutor()
        self._executor.add_node(self._node)
        self._spin_thread = threading.Thread(
            target=self._spin, name="eduping-rclpy", daemon=True
        )
        self._spin_thread.start()
        logger.info(
            "EdupingRosBridge started — leader_sub=%s follower_sub=%s traj_pub=%s root=%s",
            TOPIC_LEADER, TOPIC_FOLLOWER, TOPIC_TRAJECTORY, self._routines_root,
        )

    def stop(self) -> None:
        self._stopping.set()
        # teleop 켜져있으면 종료 전에 끔 — 컨트롤러를 joint_trajectory 로 복귀시켜야 다음 재생 정상.
        if self._teleop_active:
            try:
                self.set_live_teleop(False)
            except Exception:  # noqa: BLE001
                pass
        self._stop_playback()
        if self._executor is not None:
            try:
                self._executor.shutdown()
            except Exception:  # noqa: BLE001
                pass
            self._executor = None
        if self._node is not None:
            try:
                self._node.destroy_node()
            except Exception:  # noqa: BLE001
                pass
            self._node = None
        # rclpy.shutdown() 은 다른 bridge 와 공유될 수 있어 호출하지 않음.

    def _spin(self) -> None:
        if self._executor is None:
            return
        try:
            self._executor.spin()
        except Exception as exc:  # noqa: BLE001
            logger.debug("eduping executor spin 종료: %s", exc)

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
            mirror = self._teleop_active
        if mirror:
            self._mirror_leader_to_follower(names, pos)

    def _mirror_leader_to_follower(self, names: list[str], pos: list[float]) -> None:
        """녹화 중 live teleop — 양팔 7개씩 forward_position_controller 토픽에 publish.

        그리퍼는 GripperActionController 라 streaming 안 됨 — mirror 제외.
        """
        right_idx, left_idx = [], []
        for i in range(1, 8):
            r_name = f"openarm_right_joint{i}"
            l_name = f"openarm_left_joint{i}"
            try:
                right_idx.append(names.index(r_name))
                left_idx.append(names.index(l_name))
            except ValueError:
                return  # 이름이 다르면 (구 녹화 leader 등) 스킵
        if self._pub_right_forward is not None:
            m = Float64MultiArray()
            m.data = [float(pos[i]) for i in right_idx]
            self._pub_right_forward.publish(m)
        if self._pub_left_forward is not None:
            m = Float64MultiArray()
            m.data = [float(pos[i]) for i in left_idx]
            self._pub_left_forward.publish(m)

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
                "real_active": self.is_real_follower_active(),
            }

    def is_real_follower_active(self) -> bool:
        """tmux 의 eduping-device 세션에 hardware_type=real bringup 이 떠있는지 — 3s TTL 캐시."""
        now = time.monotonic()
        if now - self._real_active_at <= 3.0:
            return self._real_active_val
        active = False
        try:
            result = subprocess.run(
                ["tmux", "display-message", "-t", "eduping-device", "-p", "#{pane_start_command}"],
                capture_output=True,
                text=True,
                timeout=0.5,
            )
            if result.returncode == 0 and (
                "hardware_type:=real" in result.stdout
                or "hardware_type=real" in result.stdout
            ):
                active = True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            active = False
        self._real_active_val = active
        self._real_active_at = now
        return active

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

    # ---------- live teleop (녹화 / 재생과 독립) -----------------------------

    def set_live_teleop(self, enabled: bool) -> dict:
        """leader → forward_position_controller passthrough 토글.

        켤 때: joint_trajectory_controller 비활성 + forward_position_controller 활성으로 스위치.
        끌 때: 역방향 스위치.
        controller 스위치 실패 시 teleop 플래그 OFF 유지 + 에러 메시지 반환.
        """
        if enabled:
            with self._lock:
                if self._teleop_active:
                    return {"active": True, "switch": "noop"}
            ok = self._switch_controllers(
                activate=["right_forward_position_controller", "left_forward_position_controller"],
                deactivate=["right_joint_trajectory_controller", "left_joint_trajectory_controller"],
            )
            if not ok:
                return {"active": False, "switch": "failed", "hint": "실물 bringup 가 떠 있는지 확인"}
            with self._lock:
                self._teleop_active = True
            return {"active": True, "switch": "ok"}
        else:
            with self._lock:
                if not self._teleop_active:
                    return {"active": False, "switch": "noop"}
                self._teleop_active = False
            self._switch_controllers(
                activate=["right_joint_trajectory_controller", "left_joint_trajectory_controller"],
                deactivate=["right_forward_position_controller", "left_forward_position_controller"],
            )
            return {"active": False, "switch": "ok"}

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
        from eduarm.routines_io import (  # type: ignore[import-not-found]
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

    def play_routine(
        self, kind: str, name: str, *, speed: float = 1.0, target: str = "sim"
    ) -> dict:
        if speed <= 0:
            speed = 1.0
        if target == "real" and self._teleop_active:
            raise ValueError(
                "실물 동기화 (teleop) 가 켜져있는 상태에서는 실물 재생 불가 — 토글 끄고 다시 시도하세요."
            )
        from eduarm.routines_io import (  # type: ignore[import-not-found]
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
        # 내부 보간 루프 시동 — UI follower 채널 (sim 검수용). 실물 publish 시엔
        # 실제 robot 의 /joint_states 가 _follower 를 덮어쓰니 시각화도 실제 거동.
        self._start_playback(routine.joint_names, routine.keyframes, speed)

        result = {
            "ok": True,
            "target": target,
            "path": str(path),
            "frame_count": len(msg.points),
            "duration_s": round(routine.duration_s / speed, 3),
            "speed": speed,
        }
        if target == "real":
            real_status = self._send_real_follower_goals(routine, speed)
            result["real"] = real_status
        return result

    def _send_real_follower_goals(self, routine: Any, speed: float) -> dict:
        """4 controller (양팔 trajectory + 양 gripper) 에 action goal 분배.

        녹화 YAML 의 joint 명이 URDF 명 (`openarm_{side}_jointN`, `openarm_{side}_finger_joint1`)
        와 동일하다는 전제. 양팔은 FollowJointTrajectory 로 모든 keyframe, 그리퍼는
        GripperCommand 로 마지막 keyframe 값만 (단발 action) 전송.

        action server 가 미가동 (실물 bringup 안 됨) 이면 그 채널은 skip 하고 다른
        채널만 처리 — 부분 실패도 status 에 반영.
        """
        names = list(routine.joint_names)
        right_arm = [f"openarm_right_joint{i}" for i in range(1, 8)]
        left_arm = [f"openarm_left_joint{i}" for i in range(1, 8)]
        right_grip = "openarm_right_finger_joint1"
        left_grip = "openarm_left_finger_joint1"

        try:
            idx_right = [names.index(n) for n in right_arm]
            idx_left = [names.index(n) for n in left_arm]
            idx_rgrip = names.index(right_grip)
            idx_lgrip = names.index(left_grip)
        except ValueError as e:
            raise ValueError(f"녹화에 URDF joint 누락 — re-record 필요: {e}") from None

        # 양팔 trajectory goal 빌드
        right_goal = FollowJointTrajectory.Goal()
        right_goal.trajectory.joint_names = right_arm
        left_goal = FollowJointTrajectory.Goal()
        left_goal.trajectory.joint_names = left_arm
        for kf in routine.keyframes:
            t = float(kf.t) / speed
            sec = int(t)
            nsec = int((t - sec) * 1e9)
            d = Duration(sec=sec, nanosec=nsec)

            r_pt = JointTrajectoryPoint()
            r_pt.positions = [float(kf.pos[i]) for i in idx_right]
            r_pt.time_from_start = d
            right_goal.trajectory.points.append(r_pt)

            l_pt = JointTrajectoryPoint()
            l_pt.positions = [float(kf.pos[i]) for i in idx_left]
            l_pt.time_from_start = d
            left_goal.trajectory.points.append(l_pt)

        # 그리퍼 — 마지막 keyframe 값을 단발로
        final = routine.keyframes[-1].pos
        rgrip_goal = GripperCommand.Goal()
        rgrip_goal.command.position = float(final[idx_rgrip])
        rgrip_goal.command.max_effort = 5.0
        lgrip_goal = GripperCommand.Goal()
        lgrip_goal.command.position = float(final[idx_lgrip])
        lgrip_goal.command.max_effort = 5.0

        targets = [
            ("right_arm", self._ac_right_arm, right_goal),
            ("left_arm", self._ac_left_arm, left_goal),
            ("right_gripper", self._ac_right_gripper, rgrip_goal),
            ("left_gripper", self._ac_left_gripper, lgrip_goal),
        ]
        status: dict[str, str] = {}
        for label, client, goal in targets:
            if client is None:
                status[label] = "client missing"
                continue
            if not client.wait_for_server(timeout_sec=1.5):
                logger.warning("[%s] action server 미가동 — skip", label)
                status[label] = "server unavailable"
                continue
            client.send_goal_async(goal)
            status[label] = "sent"
            logger.info("[%s] goal sent", label)
        return status

    def _switch_controllers(self, *, activate: list[str], deactivate: list[str]) -> bool:
        """controller_manager 의 switch_controller 호출. 실물 bringup 안 떠 있으면 False."""
        cli = self._switch_controller_cli
        if cli is None:
            logger.warning("switch_controller client 미초기화 (bridge.start 호출 안 됨)")
            return False
        if not cli.wait_for_service(timeout_sec=1.5):
            logger.warning(
                "switch_controller 서비스 미가동 — controller_manager (실물 bringup) 가 떠 있는지 확인"
            )
            return False
        req = SwitchController.Request()
        req.activate_controllers = list(activate)
        req.deactivate_controllers = list(deactivate)
        req.strictness = SwitchController.Request.STRICT
        req.activate_asap = True
        logger.info(
            "switch_controller 호출 — activate=%s deactivate=%s (STRICT)", activate, deactivate
        )
        future = cli.call_async(req)
        deadline = time.monotonic() + 3.0
        while not future.done() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not future.done():
            logger.warning("switch_controller 응답 타임아웃 (3s)")
            return False
        try:
            resp = future.result()
        except Exception as exc:  # noqa: BLE001
            logger.warning("switch_controller exception: %s", exc)
            return False
        ok = bool(getattr(resp, "ok", False))
        msg = getattr(resp, "message", "")
        if not ok:
            logger.warning(
                "switch_controller 거부됨 — ok=False message=%r. controller 가 'inactive' 상태에 "
                "있는지 'ros2 control list_controllers' 로 확인",
                msg,
            )
            return False
        logger.info("switch_controller OK — message=%r", msg)
        return True

    def _start_playback(self, joint_names: list[str], keyframes: list[Any], speed: float) -> None:
        self._stop_playback()
        self._playback_stop.clear()
        self._playback_thread = threading.Thread(
            target=self._playback_loop,
            args=(list(joint_names), list(keyframes), float(speed)),
            name="eduping-playback",
            daemon=True,
        )
        self._playback_thread.start()

    def _stop_playback(self) -> None:
        thr = self._playback_thread
        if thr is not None and thr.is_alive():
            self._playback_stop.set()
            thr.join(timeout=1.0)
        self._playback_thread = None

    def _playback_loop(self, names: list[str], keyframes: list[Any], speed: float) -> None:
        if not keyframes:
            return
        period = 1.0 / 30.0
        start = time.monotonic()
        end_t = float(keyframes[-1].t)
        while not self._playback_stop.is_set():
            now = time.monotonic()
            elapsed = (now - start) * speed
            if elapsed >= end_t:
                pos = [float(x) for x in keyframes[-1].pos]
                with self._lock:
                    self._follower = _JsState(joint_names=list(names), positions=pos, received_at_s=now)
                break
            # 선형 보간 — 양 끝 keyframe 사이에서.
            pos = _interp_keyframes(keyframes, elapsed)
            with self._lock:
                self._follower = _JsState(joint_names=list(names), positions=pos, received_at_s=now)
            time.sleep(period)


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


def _interp_keyframes(keyframes: list[Any], t: float) -> list[float]:
    """keyframes 사이를 선형 보간. t 가 마지막을 넘으면 끝 위치 반환."""
    if t <= keyframes[0].t:
        return [float(x) for x in keyframes[0].pos]
    for i in range(len(keyframes) - 1):
        a, b = keyframes[i], keyframes[i + 1]
        if a.t <= t <= b.t:
            span = max(b.t - a.t, 1e-9)
            ratio = (t - a.t) / span
            return [float(a.pos[j]) + ratio * float(b.pos[j] - a.pos[j]) for j in range(len(a.pos))]
    return [float(x) for x in keyframes[-1].pos]


# --- exceptions -------------------------------------------------------------


class RecordingConflict(RuntimeError):
    """이미 녹화 중일 때 다시 시작 시도."""


class RecordingNotActive(RuntimeError):
    """녹화 중 아닐 때 stop 시도."""
