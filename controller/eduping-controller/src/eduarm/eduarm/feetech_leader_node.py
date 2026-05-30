"""feetech_leader_node — 실물 openarm_mini (Feetech STS3215 양팔) → JointState publisher.

lerobot 의 `openarm_mini.OpenArmMini.get_action()` 변환 파이프라인을 직접 ROS2 노드로
포팅. lerobot 패키지 자체는 import 하지 않음 (torch 등 헤비 의존성 회피).
scservo_sdk (pip: `feetech-servo-sdk`) 만 의존.

토픽: `/eduping/leader/joint_states` (sensor_msgs/JointState, 16 joints)
명명: URDF (openarm_description) 와 동일 —
       openarm_{right|left}_joint1..joint7  (revolute, rad)
       openarm_{right|left}_finger_joint1   (prismatic, m)

ROS 파라미터:
  - topic            (str, default '/eduping/leader/joint_states')
  - rate_hz          (float, default 50.0)
  - port_right       (str, default '/dev/ttyUSB0')
  - port_left        (str, default '/dev/ttyUSB1')
  - baudrate         (int, default 1000000)
  - calibration_path (str, default '~/.cache/huggingface/lerobot/calibration/teleoperators/openarm_mini/my_mini_leader_arm.json')

calibration JSON 형식 (lerobot 호환 — 양팔 16 모터 평탄 매핑):
  {
    "right_joint_1": {"id": 1, "drive_mode": 0, "homing_offset": -1543,
                       "range_min": 0, "range_max": 4095},
    ...,
    "right_gripper": {"id": 8, "drive_mode": 1, "homing_offset": 1756,
                       "range_min": 1575, "range_max": 2047},
    "left_joint_1": {...}, ...
  }

변환 파이프라인 (lerobot openarm_mini.py 동일):
  1. sync_read Present_Position (raw uint16, 0..4095)
  2. normalize:
       joint: degrees = (raw - mid) * 360 / 4095        where mid = (rmin + rmax)/2
       gripper: norm100 = (raw - rmin) / (rmax - rmin) * 100
                degrees = norm100 * GRIPPER_TELEOP_TO_DEGREES (-0.65)
  3. 부호 반전 (motor 별):
       RIGHT_MOTORS_TO_FLIP = {joint_1..5, joint_7}
       LEFT_MOTORS_TO_FLIP  = {joint_1, joint_3..7}
  4. JOINT_REMAP — leader joint_6 ↔ follower joint_7
  5. degrees → radians, JointState publish
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState



# --- lerobot/openarm_mini.py 의 상수 (1:1 포팅) -----------------------------

RIGHT_MOTORS_TO_FLIP: frozenset[str] = frozenset(
    {"joint_1", "joint_2", "joint_3", "joint_4", "joint_5", "joint_7"}
)
LEFT_MOTORS_TO_FLIP: frozenset[str] = frozenset(
    {"joint_1", "joint_3", "joint_4", "joint_5", "joint_6", "joint_7"}
)
JOINT_REMAP: dict[str, str] = {"joint_6": "joint_7", "joint_7": "joint_6"}
GRIPPER_TELEOP_TO_DEGREES: float = -0.65
# URDF 의 finger_joint1 (prismatic) 가동 범위 — openarm_description/openarm.urdf
GRIPPER_STROKE_M: float = 0.044
# 그리퍼 mounting 방향 — raw=range_min 이 physically "closed" 상태인지 여부.
# right 는 정상 (rmin=close), left 는 mirror mount 라 rmax=close.
GRIPPER_RMIN_IS_CLOSED: dict[str, bool] = {"right": True, "left": False}

MOTOR_NAMES_PER_ARM: tuple[str, ...] = (
    "joint_1", "joint_2", "joint_3", "joint_4",
    "joint_5", "joint_6", "joint_7", "gripper",
)
MOTOR_IDS_PER_ARM: tuple[int, ...] = tuple(range(1, 9))  # 1..8

# STS3215 control table (lerobot motors/feetech/tables.py)
ADDR_PRESENT_POSITION = 56
LEN_PRESENT_POSITION = 2
ADDR_TORQUE_ENABLE = 40
LEN_TORQUE_ENABLE = 1
STS3215_RESOLUTION = 4096  # ticks per turn — mid normalization uses (res - 1) = 4095
COMM_SUCCESS = 0


# --- scservo_sdk 타임아웃 버그 패치 -------------------------------------
def _patch_set_packet_timeout(self, packet_length):  # noqa: N802
    """scservo_sdk PortHandler.setPacketTimeout 의 타임아웃 과소 계산 버그 패치.

    비공식 PyPI `feetech-servo-sdk` 의 setPacketTimeout 은 sync_read 처럼 여러 모터
    응답을 한 timeout 창 안에 받아야 하는 경우 타임아웃을 너무 짧게 잡아
    RX_TIMEOUT (comm=-6) 을 유발한다. 개별 ping (self-check) 은 통과하지만
    GroupSyncRead (read_degrees) 만 실패하던 증상의 원인.

    lerobot 의 동일 패치 (motors/feetech/feetech.py, gitee ftservo issue IBY2S6) 를
    1:1 적용 — packet 길이 비례분 + 3바이트 여유 + 50ms 고정 마진.
    공식 FTServo_Python 에는 수정돼 있으나 PyPI 미배포라 런타임 패치로 대응.
    """
    self.packet_start_time = self.getCurrentTime()
    self.packet_timeout = (self.tx_time_per_byte * packet_length) + (self.tx_time_per_byte * 3.0) + 50


# --- calibration --------------------------------------------------------


@dataclass
class MotorCal:
    id: int
    drive_mode: int
    homing_offset: int
    range_min: int
    range_max: int

    @property
    def mid(self) -> float:
        return (self.range_min + self.range_max) / 2.0


def load_calibration(path: Path) -> dict[str, MotorCal]:
    """양팔 16개 모터 calibration 을 dict[full_name → MotorCal] 로 로드."""
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    cal: dict[str, MotorCal] = {}
    for full_name, fields in raw.items():
        cal[full_name] = MotorCal(
            id=int(fields["id"]),
            drive_mode=int(fields["drive_mode"]),
            homing_offset=int(fields["homing_offset"]),
            range_min=int(fields["range_min"]),
            range_max=int(fields["range_max"]),
        )
    return cal


# --- arm reader ---------------------------------------------------------


class _ArmReader:
    """한 팔 (시리얼 포트 한 개 + 8 모터) 의 sync_read 헬퍼."""

    def __init__(self, side: str, port: str, baudrate: int, calibration: dict[str, MotorCal]) -> None:
        import scservo_sdk as scs

        self.side = side
        self.port_name = port
        self.calibration = calibration  # right_/left_ prefix 포함

        self._port = scs.PortHandler(port)
        # scservo_sdk setPacketTimeout 버그 패치 — sync_read RX_TIMEOUT(comm=-6) 방지.
        # lerobot FeetechMotorsBus 와 동일하게 PortHandler 인스턴스 메서드를 교체.
        self._port.setPacketTimeout = _patch_set_packet_timeout.__get__(self._port, scs.PortHandler)
        self._packet = scs.PacketHandler(0)  # protocol version 0 (STS series)
        if not self._port.openPort():
            raise RuntimeError(f"포트 열기 실패: {port}")
        if not self._port.setBaudRate(baudrate):
            self._port.closePort()
            raise RuntimeError(f"baudrate {baudrate} 설정 실패: {port}")

        self._sync = scs.GroupSyncRead(self._port, self._packet, ADDR_PRESENT_POSITION, LEN_PRESENT_POSITION)
        for mid in MOTOR_IDS_PER_ARM:
            if not self._sync.addParam(mid):
                self._port.closePort()
                raise RuntimeError(f"{port}: sync_read addParam(id={mid}) 실패")

    def ping_all(self) -> tuple[list[tuple[str, int, int]], list[tuple[str, int, int]]]:
        """8 모터 한 번씩 ping. (found, missing) 반환.

        - found  : [(motor_name, motor_id, model_number), ...]
        - missing: [(motor_name, motor_id, comm_result), ...]   comm 0=SUCCESS, 그 외는 lib 코드
        """
        found: list[tuple[str, int, int]] = []
        missing: list[tuple[str, int, int]] = []
        for motor_name, mid in zip(MOTOR_NAMES_PER_ARM, MOTOR_IDS_PER_ARM):
            model, comm, _err = self._packet.ping(self._port, mid)
            if comm == COMM_SUCCESS:
                found.append((motor_name, mid, int(model)))
            else:
                missing.append((motor_name, mid, int(comm)))
        return found, missing

    def close(self) -> None:
        try:
            self._port.closePort()
        except Exception:  # noqa: BLE001
            pass

    def read_degrees(self) -> dict[str, float]:
        """8 모터의 위치를 degrees 단위 dict 로. lerobot openarm_mini 변환 후 값.

        반환 키는 unprefixed motor 명 (joint_1..gripper). caller 에서 JOINT_REMAP/
        prefix/부호 반전 적용.
        """
        comm = self._sync.txRxPacket()
        if comm != COMM_SUCCESS:
            raise IOError(f"{self.side} sync_read 실패 (comm={comm})")

        out: dict[str, float] = {}
        for motor_name, mid in zip(MOTOR_NAMES_PER_ARM, MOTOR_IDS_PER_ARM):
            full = f"{self.side}_{motor_name}"
            cal = self.calibration.get(full)
            if cal is None:
                raise KeyError(f"calibration 에 {full!r} 없음")
            raw = self._sync.getData(mid, ADDR_PRESENT_POSITION, LEN_PRESENT_POSITION)
            if motor_name == "gripper":
                # raw 가 calibrated range 밖으로 나가거나 uint16 wrap (4095↔0) 되면
                # val 부호가 뒤집혀 UI 가 반대로 보임 — clamp 로 saturate.
                raw_clamped = max(cal.range_min, min(cal.range_max, raw))
                span = max(cal.range_max - cal.range_min, 1)
                norm100 = (raw_clamped - cal.range_min) / span * 100.0
                out[motor_name] = norm100 * GRIPPER_TELEOP_TO_DEGREES
            else:
                out[motor_name] = (raw - cal.mid) * 360.0 / (STS3215_RESOLUTION - 1)
        return out


# --- ROS node -----------------------------------------------------------


class FeetechLeaderNode(Node):
    def __init__(self) -> None:
        super().__init__("feetech_leader_node")

        default_cal = Path.home() / ".cache" / "huggingface" / "lerobot" / "calibration" / \
            "teleoperators" / "openarm_mini" / "my_mini_leader_arm.json"

        self.declare_parameter("topic", "/eduping/leader/joint_states")
        self.declare_parameter("rate_hz", 50.0)
        self.declare_parameter("port_right", "/dev/ttyUSB0")
        self.declare_parameter("port_left", "/dev/ttyUSB1")
        self.declare_parameter("baudrate", 1000000)
        self.declare_parameter("calibration_path", str(default_cal))
        # check_only=True → self-check 후 즉시 종료 (publisher/timer 등록 안 함).
        self.declare_parameter("check_only", False)

        topic: str = self.get_parameter("topic").get_parameter_value().string_value
        rate_hz: float = self.get_parameter("rate_hz").get_parameter_value().double_value
        if rate_hz <= 0:
            rate_hz = 50.0
        port_right: str = self.get_parameter("port_right").get_parameter_value().string_value
        port_left: str = self.get_parameter("port_left").get_parameter_value().string_value
        baudrate: int = int(self.get_parameter("baudrate").get_parameter_value().integer_value or 1_000_000)
        cal_path = Path(self.get_parameter("calibration_path").get_parameter_value().string_value).expanduser()

        if not cal_path.exists():
            self.get_logger().fatal(f"calibration JSON 없음: {cal_path}")
            raise SystemExit(2)
        calibration = load_calibration(cal_path)
        # calibration JSON 키는 lerobot 가 생성 — `right_joint_1..gripper`, `left_joint_1..gripper`
        # (URDF 명 아님). MOTOR_NAMES_PER_ARM × side 로 구성.
        expected_cal_keys = [
            f"{side}_{name}" for side in ("right", "left") for name in MOTOR_NAMES_PER_ARM
        ]
        missing = [n for n in expected_cal_keys if n not in calibration]
        if missing:
            self.get_logger().fatal(f"calibration 누락 키: {missing}")
            raise SystemExit(2)

        self.get_logger().info(
            f"feetech_leader: topic={topic} rate={rate_hz}Hz "
            f"right={port_right} left={port_left} baud={baudrate} cal={cal_path.name}"
        )

        try:
            self._right = _ArmReader("right", port_right, baudrate, calibration)
        except Exception:
            raise
        try:
            self._left = _ArmReader("left", port_left, baudrate, calibration)
        except Exception:
            self._right.close()
            raise

        # 모터 self-check — 양팔 8개씩 ping. 누락 있으면 fail-fast.
        self._self_check()

        # check_only 모드 — publisher/timer 등록 없이 정상 종료 (preflight 용)
        if self.get_parameter("check_only").get_parameter_value().bool_value:
            self._right.close()
            self._left.close()
            self.get_logger().info("✓ 모터 self-check 통과 (check_only — 종료)")
            raise SystemExit(0)

        self._pub = self.create_publisher(JointState, topic, 10)
        self._timer = self.create_timer(1.0 / rate_hz, self._tick)
        self._fail_streak = 0

    def _self_check(self) -> None:
        """양팔 8 모터씩 ping → 표 형태 로그 + 누락 있으면 SystemExit."""
        log = self.get_logger()
        any_missing = False
        for arm, reader in (("right", self._right), ("left", self._left)):
            found, missing = reader.ping_all()
            log.info(f"[{arm}] motor self-check — {reader.port_name}")
            for name, mid, model in found:
                log.info(f"  ✓ id={mid:>2}  {name:<10}  model={model}")
            for name, mid, comm in missing:
                log.error(f"  ✗ id={mid:>2}  {name:<10}  NO RESPONSE (comm={comm})")
            if missing:
                any_missing = True
                missing_ids = ", ".join(f"id={mid}" for _, mid, _ in missing)
                log.error(
                    f"[{arm}] {len(MOTOR_IDS_PER_ARM)}개 중 {len(missing)}개 응답 없음 "
                    f"({missing_ids}) — 전원/ID/시리얼 wiring 확인"
                )
        if any_missing:
            self._right.close()
            self._left.close()
            log.fatal("모터 self-check 실패 — leader 노드 종료")
            raise SystemExit(2)

    def _tick(self) -> None:
        try:
            right_deg = self._right.read_degrees()
            left_deg = self._left.read_degrees()
        except Exception as exc:  # noqa: BLE001
            self._fail_streak += 1
            if self._fail_streak in (1, 10, 50):
                self.get_logger().warn(f"read 실패 (streak={self._fail_streak}): {exc}")
            return
        if self._fail_streak:
            self.get_logger().info(f"read 복구 (이전 streak={self._fail_streak})")
            self._fail_streak = 0

        names: list[str] = []
        positions: list[float] = []
        for side, deg_map in (("right", right_deg), ("left", left_deg)):
            flips = RIGHT_MOTORS_TO_FLIP if side == "right" else LEFT_MOTORS_TO_FLIP
            for motor_name in MOTOR_NAMES_PER_ARM:
                target = JOINT_REMAP.get(motor_name, motor_name)
                val_deg = deg_map[motor_name]
                if motor_name != "gripper" and motor_name in flips:
                    val_deg = -val_deg
                # URDF 명으로 publish — joint_N → openarm_{side}_jointN, gripper → openarm_{side}_finger_joint1
                if target == "gripper":
                    urdf_name = f"openarm_{side}_finger_joint1"
                else:
                    urdf_name = f"openarm_{side}_{target.replace('_', '')}"
                names.append(urdf_name)
                if motor_name == "gripper":
                    # URDF finger_joint1 (prismatic): 0 m = 활짝 열림, 0.044 m = 완전히 닫힘.
                    # read_degrees gripper: raw=rmin → val_deg=0, raw=rmax → val_deg=-65.
                    # right (rmin=close): rmin → 0.044 m (closed), rmax → 0 m (open)
                    # left  (rmax=close): rmin → 0 m (open),       rmax → 0.044 m (closed)
                    raw_norm = min(1.0, abs(val_deg) / abs(GRIPPER_TELEOP_TO_DEGREES * 100.0))
                    closed_amount = (1.0 - raw_norm) if GRIPPER_RMIN_IS_CLOSED[side] else raw_norm
                    positions.append(closed_amount * GRIPPER_STROKE_M)
                else:
                    positions.append(math.radians(val_deg))

        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = names
        msg.position = positions
        self._pub.publish(msg)

    def destroy_node(self) -> bool:
        try:
            self._right.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._left.close()
        except Exception:  # noqa: BLE001
            pass
        return super().destroy_node()


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    try:
        node = FeetechLeaderNode()
    except SystemExit:
        rclpy.shutdown()
        raise
    except Exception as exc:
        rclpy.shutdown()
        raise SystemExit(f"feetech_leader_node 초기화 실패: {exc}") from exc
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            node.destroy_node()
        except Exception:  # noqa: BLE001
            pass
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
