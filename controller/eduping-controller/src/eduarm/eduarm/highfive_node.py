#!/usr/bin/env python3
"""EduPing high-five controller — hand point → scripted gesture (home→HIGH→TAP→PULL→home).

파이프라인:
  /eduping/highfive/hand_point  (PointStamped, frame_id=d435_depth_optical_frame[:left|:right])
    → 좌/우 arm 선택 (frame_id suffix 또는 hand y 부호)
    → DCP-RMP gate (obstacle suppress/reroute, amplitude scaling)
    → Scripted JointTrajectory phase chain → /eduping/joint_trajectory
  + Depth subscriber → static gate + dynamic obstacle frame-diff (DCP-RMP)
  + /eduping/highfive/status (5Hz JSON) — browser UI overlay 가 polling

Servo / IK reach 대신 scripted gesture 사용:
  Jazzy 의 moveit_servo PSM clock-type bug 로 servo 사용 불가. 또한 IK reach 보다
  "raise forearm + slap" 같은 정형화된 모션이 high-five 시각적으로 자연스러움.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import rclpy
from builtin_interfaces.msg import Duration as DurationMsg
from geometry_msgs.msg import PointStamped
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import (
    QoSDurabilityPolicy, QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy,
)
from rclpy.time import Time
from geometry_msgs.msg import PoseStamped, Quaternion
from moveit_msgs.msg import MoveItErrorCodes, PositionIKRequest, RobotState
from moveit_msgs.srv import GetPositionFK, GetPositionIK, GetStateValidity
from sensor_msgs.msg import Image, JointState
from std_msgs.msg import String
from tf2_geometry_msgs import do_transform_point
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
import tf2_ros

from .joint_names import OPENARM_JOINT_NAMES


# MoveItConfigsBuilder 가 v10 bimanual URDF 를 쓰며 root 는 world (base_link 미사용).
BASE_FRAME = "world"

LEFT_ARM_GROUP = "left_arm"
RIGHT_ARM_GROUP = "right_arm"

LEFT_JOINT_NAMES = [f"openarm_left_joint{i}" for i in range(1, 8)]
RIGHT_JOINT_NAMES = [f"openarm_right_joint{i}" for i in range(1, 8)]


def _mirror_arm_joints(j: list[float]) -> list[float]:
    """Sagittal (y→−y) mirror of a 7-DOF arm pose: negate j1,j2,j3,j5,j7; keep j4,j6.
    Verified by FK: mirror(right-arm IK solution for a y-mirrored target) lands the
    LEFT hand on the target (err 1.1cm). The LEFT arm's own TRAC-IK resolves its
    shoulder FLAT (j2≈0) no matter what (seed/constraint/Distance all ignored), so the
    left instead solves via the RIGHT group on a mirrored target — the right opens its
    shoulder — and mirrors the result back here. j4/j6 share range/sign across arms."""
    return [-j[0], -j[1], -j[2], j[3], -j[4], j[5], -j[6]]

# EE link names — MoveIt /compute_ik 의 ik_link_name 으로 사용. URDF v10 의 마지막
# arm link. orientation 은 home pose 의 link7 frame 기준.
LEFT_EE_LINK = "openarm_left_link7"     # arm group chain end (SRDF 의 left_arm group
RIGHT_EE_LINK = "openarm_right_link7"   # 는 joint1..joint7). IK tip 으로만 사용.
LEFT_HAND_LINK = "openarm_left_hand"    # j8 fixed body — gripper base. FK 로만 query.
RIGHT_HAND_LINK = "openarm_right_hand"  # closed-loop correction 에서 blue ball world
                                        # 위치 (hand + 4cm local Z) 계산에 사용.

# IK target orientation — position-only IK (kinematics_trac_ik.yaml) 라 실제론 무시됨.
# 6-DOF full-pose IK (slap-face 를 down-forward 로 강제) 를 시도했으나 LEFT arm 이
# 그 orientation 을 narrow reach envelope 에서 못 풀어 -31 → position-only 로 복귀.
# gripper 면 방향은 j6/j7 override 가 담당.
PALM_FACING_QUAT = Quaternion(x=0.0, y=0.0, z=0.0, w=1.0)
# IK 호출 timeout — 0.1s 이면 TRAC-IK 가 충분히 수렴 (config 의 0.05s × attempts=3).
IK_TIMEOUT_S = 0.1

# Quintic-timed waypoint count per phase — sim/MuJoCo 의 선형 보간 입장에서 충분.
TRAJECTORY_WAYPOINTS = 20

# y 부호 경계 히스테리시스 — 손이 중앙 근처에서 좌/우 팔이 바뀌며 flicker 방지.
# ±5cm dead band 면 거의 중심 (centerline) 에서만 sticky.
ARM_Y_LEFT_M = 0.05
ARM_Y_RIGHT_M = -0.05

# Obstacle avoidance — Deep Reactive Policy 의 DCP-RMP (Li 2025, CMU-RI-TR-25-29
# Ch.4) 채택. 두 single-purpose 정책을 결합한 RMP:
#   (1) Static gate: depth 픽셀 중 OBSTACLE_NEAR_M (25cm) 이내가 너무 많으면 suppress.
#   (2) Dynamic field: frame-to-frame depth diff 로 움직이는 점 검출 →
#       repulsive intensity R = exp(-d / DCP_LENGTH_M). R 이 크면:
#         - 발사 전: gesture amplitude 축소 (덜 뻗음)
#         - 발사 중: red zone (<DCP_RED_ZONE_M) 진입하면 abort → return home
OBSTACLE_NEAR_M = 0.25
# 300 → 150 (2026-05-28): 사용자가 손 옆/아래에 작은 물체 두면 reroute 안 됨 — 더 민감하게.
OBSTACLE_PIXEL_THRESH = 150
# 80 → 40: 작은 움직임도 dynamic 으로 잡아 reroute 빈도 ↑.
DCP_DEPTH_CHANGE_MM = 40
DCP_LENGTH_M = 0.30
DCP_RED_ZONE_M = 0.20
# HOME phase 의 softened red zone — 복귀 중에는 의도된 contact 가 끝났으므로
# child-safety 만 챙기면 됨. 8cm 안쪽 close-call 만 abort.
DCP_HOME_RED_ZONE_M = 0.10
DCP_AMPLITUDE_SHRINK = 0.7
DCP_MONITOR_HZ = 10.0
# Expected-contact band — TAP/PULL 직후 HOME phase 에 사용자 손이 still 가까이
# 있으면 그건 'expected contact' 의 잔상이라 abort 면제. _on_depth_obstacle 에서
# 손 깊이 ±5cm 안의 dynamic 검출은 무시.
EXPECTED_CONTACT_BAND_M = 0.05
# Reroute: dynamic obstacle 의 화면상 위치 (정규화 X, -1=좌단, +1=우단) 에 따라
# joint1 (shoulder yaw) deflection 으로 arm 을 obstacle 반대편으로 swing.
DCP_REROUTE_MAX_RAD = 0.4
# 0.25 → 0.15 (2026-05-28): 더 작은 off-center 변위도 reroute trigger.
DCP_CENTER_BLOCK_THRESH = 0.15
# Hand visibility grace — hand_point 받은 뒤 이 시간 안에는 dynamic obstacle 을
# (hand_depth - HAND_FRONT_MARGIN_M) 보다 가까운 것만 인정. 사용자 손/팔 자체가
# obstacle 로 잘못 인식되는 거 방지하면서, 손보다 앞에 있는 실제 obstacle 은 잡음.
HAND_GRACE_S = 1.5
# 0.10 → 0.05 (2026-05-28): 손 깊이에 가까운 (그러나 손이 아닌) 물체도 obstacle 로
# 인정. 손 자체 두께 ~5cm 라 5cm margin 이면 손은 여전히 제외.
HAND_FRONT_MARGIN_M = 0.05
# Hand world position 으로 IK 가 직접 reach. IK fail 시 graceful fallback —
# optical-frame norms (image X / Y, depth offset) 을 j1/j2/j4 deflection 으로
# scripted TAP pose 에 더해 arm 이 hand 쪽으로 lean 하게 만든다 (정확히 reach 는
# 못해도 방향성 유지).
HAND_TRACK_J1_GAIN_RAD = 0.7    # lateral (image X) → j1 (shoulder yaw)
HAND_TRACK_J2_GAIN_RAD = 0.6    # vertical (image Y) → j2 (shoulder pitch)
HAND_TRACK_J4_GAIN_RAD = 0.25   # depth (z) → j4 (elbow flex)
# 추가: vertical (image Y) → j4 (elbow flex) 동조. 손이 화면 위쪽 일수록 forearm 도
# 더 fold 해 gripper 가 위로 따라옴 (반대도 마찬가지). j2 만으론 vertical 추적이
# 어깨 pitch 호(arc) 안으로 제한돼서 "tap 항상 같은 forward 깊이" 처럼 보였다.
HAND_TRACK_J4_VERT_GAIN_RAD = 0.4
# Baseline vertical lift bias — fallback 으로도 평균적으로 hand 보다 살짝 낮게
# 잡히는 경향이 있어 추가로 j2 를 더 들어 올린다. hy_norm 과 무관하게 항상 적용.
HAND_TRACK_J2_BIAS_RAD = 0.22
# Optical Y norm divisor — D435 cy/fy ≈ 0.62 (4:3 sensor 약간 좁은 vertical FOV).
HAND_Y_NORM_DIVISOR = 0.62
# Depth norm centering — hand-accept zone 의 중심.
HAND_Z_CENTER_M = 0.50
HAND_Z_HALF_BAND_M = 0.10
# Motion = raise → (rebound/ready area 에서 멈춤) → tap → rebound → return.
# 사용자 요청 이상형 (2026-05-29): 팔을 들어 rebound area 에 한 번 서고, 거기서
# 손으로 살짝 jab(tap) 했다가 다시 area 로 튕겨 돌아오고, home 으로 내려온다.
# rebound area = tap 을 shoulder 쪽으로 REBOUND_BACK_M 당기고 REBOUND_DOWN_M 내린
# IK pose (아래 _publish_best). raise 와 recoil 의 공통 waypoint.
PRESENT_DURATION_S = 4.0    # home → rebound area: 천천히 raise. 사용자 "slow down raise"
                            # (2026-06-01) 3.0→4.0. TRACK_WINDOW_S 도 이 값 따라감.
RAISE_HOLD_S = 0.4         # rebound area 에서 잠깐 멈춤 ("stop at rebound area").
TAP_FORWARD_DURATION_S = 2.0  # rebound area → tap: 손으로 부드럽게 jab (forward+up).
                           # 사용자 (2026-06-01) "slow down tapping speed" → 0.9→1.4 로
                           # 늘려 peak 속도 ~35% ↓ = 더 gentle/slow 한 tap.
PRESS_HOLD_S = 0.5         # tap 에서 머무름 = 부드러운 press contact 가 느껴지도록.
# Rebound (recoil) = tap → rebound area 로 되돌아옴 (raise 가 멈췄던 그 자리).
# 거리/속도 history: 0.14@0.8s 는 rebound area 가 tap 과 너무 가까워 안 보임 (사용자
# "rebound area too close to tap area"). 0.22@0.5s 는 또렷했지만 너무 빨라 무리
# ("too strong, can hurt the robot"). 정답 = 거리는 0.22 (또렷) + 시간은 1.0s (느림)
# → peak velocity 0.22 m/s, 옛 0.5s snap(0.44)의 절반 = gentle 한데 separation 또렷.
REBOUND_BACK_M = 0.22
# Rebound area 는 tap 보다 REBOUND_DOWN_M 만큼 아래 (절대 안 솟게 — tablet 안전) +
# tap 과의 수직 separation 도 키움. 0.08 = 또렷한 diagonal 하강. REBOUND_MAX_Z 는
# rebound IK target Z 의 hard cap — rendered rebound 가 shoulder 위로 안 가도록
# (left arm 은 retract 시 rendered 가 target 보다 ~2cm 위로 솟음. cap 0.62 안전).
REBOUND_DOWN_M = 0.08
REBOUND_MAX_Z = 0.62
REBOUND_FRAC = 0.35        # (heuristic fallback 전용) rebound = tap→home 35% lerp.
                           # 0.50 은 rebound 점이 home 쪽 절반이라 settle 과 collinear
                           # → 한 번의 하강처럼 보여 "rebound 사라짐". 0.35 면 tap 에서
                           # 또렷이 떨어진 distinct recoil 점.
REBOUND_DURATION_S = 1.5   # tap → rebound area: 천천히 되돌아옴 (1.0→1.5 slow down). 거리 0.22 로 키웠지만
                           # 1.0s 라 velocity 낮아 gentle (0.5s snap 의 절반). separation
                           # ↑ + 속도 ↓ = 또렷하면서 안 셈.
REBOUND_HOLD_S = 0.6       # rebound area 로 돌아와 잠깐 멈춤 → recoil 또렷.
WITHDRAW_DURATION_S = 2.2  # rebound area → home: 차분히 settle.

# Live hand-tracking during the raise (track-during-raise, lock-at-tap) — 사용자
# (2026-06-01): blue 가 raise 동안 움직이는 red 의 height+width 를 따라가다가 tap 에서
# commit (tap/rebound/return lock). raise 가 끝나는 절대시각 = fire + TRACK_WINDOW_S.
# 그 동안 새 hand_point 를 ignore 하지 않고 re-aim (closed-loop 재실행 + 현재 자세에서
# 재 publish, raise duration = 남은 시간). ⚠ 예전에 제거됐던 mid-raise retarget 의 부활
# 이라 z_ceiling clamp(over-shoulder 방지) + 현재자세 시작(momentum jump 방지) + throttle
# (flood/shake 방지) 로 가드. 실물 전 sim 튜닝 필요.
TRACK_WINDOW_S = PRESENT_DURATION_S   # raise = tracking window. 이후 committed.
TRACK_REAIM_THROTTLE_S = 0.7          # re-aim 최소 간격 (closed-loop 가 ~0.5-1s).
TRACK_REAIM_MOVE_M = 0.04             # 손이 이만큼 움직여야 re-aim (jitter 무시).
TRACK_CL_BUDGET_S = 1.0               # deadline 이만큼 전엔 re-aim 중단 → closed-loop 이
                                       # deadline 전에 끝나 commit 이 깔끔. 이후 committed.
TRACK_MIN_RAISE_S = 0.6               # re-publish raise duration 하한 (snap 방지).

# Scripted gesture poses ([j1..j7]).
#
# 설계 원칙:
#   1. 손이 어깨 위로 올라가지 않게 — j2 shoulder pitch 와 j4 elbow flex 모두 절제.
#   2. 손을 앞쪽 (front) 으로 — j4 flex 줄이면 forearm 이 앞으로 펴짐.
#   3. 자기 몸 / 가슴에 부착된 tablet 안 침범 — 위 두 가지 + admin UI 의 safe travel
#      range broadcast 가 모터별 hard clamp.
#   4. 양팔 동시 발사 시 self-collision 없음 — j1 outward bias 로 양팔 spread.
# 모든 각도는 보수적 시작값. 시각화 후 admin UI 또는 본 파일 미세조정.
#
# HIGH : 어깨 살짝 들고 (j2≈14°), 팔꿈치 87° 정도 굽힌 forearm-앞 자세.
# TAP  : 팔꿈치 펴서 손바닥 앞으로 push.
# PULL : tap 후 약간 retract.
# joint4 (elbow flex) — URDF range (0, 2.443). j4=0 은 forearm 이 elbow 에서 수직
# down 으로 hanging (forward 가 아니라). j4=π/2 ≈1.57 이 forearm 을 upper-arm 과
# alignment — 진짜 "straight forward". j4>π/2 는 forearm 이 shoulder 쪽으로 fold
# back (high-five "raise" 자세). j4≈2.4 (138°) 면 forearm 이 머리 위로 올라가
# above-shoulder 위험. 적절 range: 1.4 (≈80°, horizontal forward) ~ 1.7 (≈97°).
_J4_HIGH = 1.15   # 약 66° — windup. forearm 이 forward-down 으로 ext (약간만 fold).
                  # 2.25 → blue Z=0.81 (shoulder+10cm), 1.40 → left arm windup Z=0.699
                  # (shoulder 와 동일선). 1.15 로 더 낮춰 left windup ≈ 0.67 (shoulder
                  # 아래 3cm), right ≈ 0.64 — 양팔 다 tablet PC clear. windup/PULL 둘
                  # 다 이 값 사용 (PULL = HIGH_POSE).
_J4_PUSH = 0.50   # 약 29° — TAP 순간 forearm 을 거의 직선 forward 로 stretch.
                  # HIGH 2.25 → PUSH 0.50 = 1.75 rad 의 큰 swing (windup → stretch).
_J4_PULL = 2.30   # 약 132° — TAP 후 다시 fold back, PUSH→PULL 1.80 rad rebound.
# joint7 (wrist roll, palm orientation) — URDF ±1.570, safe ±1.484. j6 가 wrist 를
# 위로 꺾은 상태에서 j7 ≈ +π/2 (1.484) 로 90° roll 하면 gripper "underside" (palm
# 면) 가 사용자 방향을 정면으로 향한다 — 손바닥으로 슬랩 하는 자세. 예전 0.7 (40°)
# 일 때는 gripper TIP 이 forward 라서 사용자가 "찌르는 듯" 한 느낌이었음.
_J7_HIGH_MAG = 1.484
# joint2 (shoulder pitch) lift — 어깨가 forward 로 살짝 기울어 upper-arm + forearm
# 직선 reach 가 길어짐. j4=1.6 (forearm horizontal) 과 paired 일 때 gripper 가
# shoulder 보다 살짝 위, 멀리. 0.35 ≈ 20° — above-shoulder threshold 아래.
_J2_PULL = 0.0    # PULL 에서 shoulder pitch 변화 없음 — 예전 +0.60 일 때 rebound
                  # 가 위로 솟아 (blue Z=0.89) tablet PC (body frame 의 chest mount) 위
                  # swing 위험. 현재는 elbow 만 fold (j4) → 자연스러운 "pull back" 만.
_J2_LIFT = 0.05   # 약 3° — HIGH peak 의 shoulder lift (seed only — closed-loop IK 가
                  # 최종 j2 결정). LEFT 은 IK 가 무조건 flat(~0) 으로 풀어 이 값 영향 없음.
# joint1 (shoulder yaw) outward — 양팔이 body 중앙에서 만나는 self-collision 방지.
# 양팔 동시 발사 시 ~30cm 옆으로 spread.
_J1_OUTWARD = 0.55   # 약 32° — high-five 가 충분히 높이 올라가 보이려면 j1 outward
                     # 가 크게 들어가야 함 (base rpy ±π/2 라 j1 회전이 어깨 높이도 영향)
# joint6 (wrist pitch) — URDF j6 ±0.785 (±45°) 가 hard limit. +0.7 (≈+40°) 으로 wrist
# 를 max tilt up — gripper 가 forearm 끝에서 위쪽으로 꺾여 palm 면이 forearm 과
# 수직.
# j5 (forearm roll) — IK 가 자유 결정하면 each gesture 마다 wrist 방향이 달라져
# gripper 의 underside 가 world frame 에서 일관되게 forward 향하지 않는다. j5 = ±π/2
# (sign_lr mirror) 로 forearm 을 90° roll 해서 j6 의 "tilt up" 방향이 world 의
# "tilt forward" 와 align 되게 한다 — gripper underside (palm 면) 가 HIGH→TAP 동안
# 항상 red ball (forward) 방향을 향함. URDF safe ±1.484, 1.48 = ~85°.
_J5_ROLL = 1.48
_J6_UP = 0.7
# joint3 (bicep roll) — humerus 축 주변 rotation. EE 높이 변화는 미미하고 forearm
# 의 ORIENTATION 만 바뀜 (1.0 rad 시 forearm 이 안쪽으로 꺾여 부자연스러운 자세).
# 따라서 0 유지 — 높이는 j2 (shoulder pitch) 가 담당.
_J3_RAISE = 0.0
# Joint1 (shoulder yaw) URDF limits — reroute + tracking 가 이 한도 안에서 clamp.
# LEFT range -3.49..+1.40, RIGHT range -1.40..+3.49 — 좀 더 보수적 ±1.2 양쪽.
_J1_SAFE_LIMIT = 1.2
# joint2 mirror: 양팔 base rpy 가 ±π/2 라 같은 signed value 로 같은 world 방향 lift.
# 만약 시각화에서 한쪽이 위/한쪽이 아래로 가면 LEFT 쪽 부호만 반전.
# joint1 outward: 양팔이 안쪽으로 모여 충돌하지 않게 어깨 yaw 를 바깥쪽으로.
HIGH_POSE_RIGHT = [+_J1_OUTWARD, +_J2_LIFT, +_J3_RAISE, _J4_HIGH, 0.0, +_J6_UP, +_J7_HIGH_MAG]
HIGH_POSE_LEFT  = [-_J1_OUTWARD, -_J2_LIFT, +_J3_RAISE, _J4_HIGH, 0.0, +_J6_UP, -_J7_HIGH_MAG]
TAP_POSE_RIGHT  = [+_J1_OUTWARD, +_J2_LIFT, +_J3_RAISE, _J4_PUSH, 0.0, +_J6_UP, +_J7_HIGH_MAG]
TAP_POSE_LEFT   = [-_J1_OUTWARD, -_J2_LIFT, +_J3_RAISE, _J4_PUSH, 0.0, +_J6_UP, -_J7_HIGH_MAG]
PULL_POSE_RIGHT = [+_J1_OUTWARD, +_J2_PULL, +_J3_RAISE, _J4_PULL, 0.0, +_J6_UP, +_J7_HIGH_MAG]
PULL_POSE_LEFT  = [-_J1_OUTWARD, -_J2_PULL, +_J3_RAISE, _J4_PULL, 0.0, +_J6_UP, -_J7_HIGH_MAG]
# Cooldown after gesture finishes (before next trigger accepted).
GESTURE_COOLDOWN_S = 0.2
# Re-arm gap — hand must be ABSENT (no hand_point) this long after a gesture before a
# new tap fires. Prevents double-tap from a hand left in the box (browser re-POSTs at
# ~100ms). > inter-POST gap + detection drops; short enough that lifting the hand
# briefly re-arms. Measured from max(busy_until, last_hand_point) — see _on_hand_point.
REARM_GAP_S = 0.8
# Mid-raise retarget 는 제거됨 — present phase 도중 republish 가 rendered gripper 를
# shoulder 위로 overshoot 시켜 (model-mismatch + momentum) tablet 위험이라, gesture 는
# trigger 시점 target 으로 commit 한다. 손이 크게 움직였으면 다음 gesture 가 잡음.
# Closed-loop watchdog — IK/FK chain 이 이 시간 안에 publish 못 하면 (서비스 hang
# 등) in-flight guard 강제 해제. 정상 closed-loop 는 5 iter ≈ 1s 안에 완료.
CL_WATCHDOG_S = 2.0
# Hand-disappeared mid-HIGH safe abort: 사용자가 raise 중에 손을 화면 밖으로
# 빼버리면 (또는 detection 끊기면) TAP 으로 진행하지 말고 READY 로 부드럽게 복귀.
# child 가 갑자기 손 내려서 robot 만 허공에 slap 하는 사고 방지.
# DepthViewer 는 "유지" (palm 정지) 일 때 400ms 마다 heartbeat POST 를 보내므로
# 1.2s 의 threshold 가 안전 margin 충분 (heartbeat 3 회 연속 누락 = 진짜 사라짐).
HAND_LOST_ABORT_S = 1.2

# Safety lock — gesture waypoint clamp.
#
# 단일 출처 (admin UI): joint limit 의 SOLE source 는 control_service 의 admin UI 가
# 저장한 safe travel range. URDF 의 하드웨어 한계는 단순 motor 회전 가능 범위라
# 어깨 / 가슴 tablet / 배경 등 mechanical obstacle 까지 반영하지 못함 — 관리자가 직접
# 환경에 맞춰 좁히는 값이 진짜 안전 범위.
#
# /eduping/safe_joint_limits (latched String, TRANSIENT_LOCAL) 로 broadcast → 본
# 노드 cache. broadcast 도착 전엔 gesture 발사 거부 (안전 fail-stop).
#
# SAFETY_MARGIN_RAD 는 admin 범위에서 추가 양쪽 안쪽 margin. URDF hard stop 슬램 +
# PD overshoot + 임시 perturbation 흡수.
SAFETY_MARGIN_RAD = 0.087  # ≈ 5° — admin 범위에서 추가 안쪽 여유.
# 9° → 5° 로 줄임 (2026-05-28): j6 wrist pitch 가 URDF ±45° hard limit 가까이 가야
# 충분히 손이 들림 — 9° margin 이면 ceiling 0.635 (36°), 5° 면 0.698 (40°).


@dataclass
class _ArmConfig:
    group: str
    joint_names: list[str]
    ee_link: str       # IK tip (must be inside SRDF arm chain).
    hand_link: str     # FK query target — fixed j8 body for blue-ball positioning.


LEFT_ARM = _ArmConfig(LEFT_ARM_GROUP, LEFT_JOINT_NAMES, LEFT_EE_LINK, LEFT_HAND_LINK)
RIGHT_ARM = _ArmConfig(RIGHT_ARM_GROUP, RIGHT_JOINT_NAMES, RIGHT_EE_LINK, RIGHT_HAND_LINK)

# OpenArm shoulder world coordinates (URDF v10 bimanual mount) — used to project
# unreachable hand targets onto the reach sphere so IK can find SOME solution
# instead of returning -31 for everything beyond ~43cm.
RIGHT_SHOULDER_WORLD = (0.0, -0.031, 0.698)
LEFT_SHOULDER_WORLD  = (0.0, +0.031, 0.698)
# Empirically measured from IK probe: at shoulder height max reach ≈ 0.43m.
# 0.44m is just past the dexterous boundary — slight singularity risk but extends
# the arm noticeably more for "natural stretch toward hand" feel.
MAX_REACH_M = 0.45   # link7 (IK tip) 의 어깨 기준 reach envelope. 실측 TRAC-IK 가
                     # 0.45m 이상에선 NO_IK_SOLUTION 자주 반환 → 0.45 가 신뢰 한계.
                     # 0.43→0.45 (2026-06-01, 사용자 "extend reach as far as IK allows"):
                     # ground-truth probe 에서 gripper contact 가 link7+~4cm 라 contact
                     # reach ~0.49m. 손이 그보다 멀면 (실측 0.65m) 여전히 못 닿아 short tap
                     # — box 가 reach 밖까지 보이는 한 far hand 는 short. j6 override 가
                     # edge IK 안정 (없으면 -31).
# Body-frame safety ceiling — gripper 가 어깨 위로 안 가야 함 (body 의 chest 에
# tablet PC 가 mounted 됨). shoulder world Z = 0.698. 이 값은 closed-loop 의 MoveIt
# target Z 를 clamp 한다 (실제 렌더 gripper 가 아니라).
# ⚠ PER-ARM — 두 팔의 MoveIt-FK ↔ MuJoCo-render Z 어긋남이 다르다:
#   RIGHT: render 가 target 보다 일정하게 ~11cm 아래 → ceiling 0.72 여도 렌더는
#          ~0.61 (random sweep maxZ 0.612 확인) → shoulder 0.698 아래 안전, 동시에
#          사람 손 (0.58–0.66) 위로 올라갈 여유.
#   LEFT:  centerline 쪽으로 가로질러 reach 하는 config (opt x≈0) 에선 render 가
#          target 과 거의 같다 (mismatch ~0) → ceiling 0.72 면 렌더가 0.73 까지 솟아
#          over-shoulder (random sweep #2/#4 maxZ 0.730/0.717). 그래서 LEFT 만
#          0.64 로 낮춤 → 렌더 0.58–0.64, shoulder 아래 안전 + 손 range bracket.
#   asymmetry 는 실제다 (project_highfive_closed_loop: "Left arm sits higher than
#   right for identical joint angles"). RIGHT ceiling 을 같이 낮추면 right 가
#   under-reach (render 0.53) 하니 per-arm 필수.
# ⚠ 2026-06-01 PARTIAL RAISE (사용자: "tap 이 red ball 아래에서 위로 uppercut — 같은 높이로").
# 카메라를 어깨 높이(0.69)로 올린 뒤 손이 0.65~0.70 에서 잡혀 예전 ceiling(0.72/0.64)이
# tap 을 red ball 아래로 clamp → render 5~8cm 밑 → uppercut. ceiling 을 안전 한도까지
# 올림 (render 가 shoulder 0.698 아래 유지):
#   RIGHT render≈ceiling−0.11 → 0.78 면 render~0.67 (margin ~3cm). hand 0.69 면 ~2cm uppercut 잔존.
#   LEFT  render≈ceiling(+최대 0.035, across-centerline 에선 mismatch~0) → 0.65 면 render≤0.685
#         (margin ~1.3cm). 0.68 은 render~0.71 = OVER-SHOULDER → tablet hit (금지).
# ⚠ FULL level (hand 0.69 에 render 0.69) 는 gripper 가 어깨 높이까지 가야 해서 chest
#   tablet 과 충돌 위험 (특히 LEFT across-centerline). tablet 이 제거/이동됐거나 위험을
#   감수할 때만 ceiling 을 더 올린다 (사용자 확인 필요). 현 값은 안전 범위 내 최대 완화.
#   tap 고점은 forward contact 지만 LEFT across reach 는 centerline(body) 쪽이라 주의.
# ⚠ 실물 전 sim 에서 trace/random_balls 로 over-shoulder=0 확인 (see [[highfive-shoulder-ceiling]]).
SHOULDER_Z_CEILING_RIGHT_M = 0.78
# 2026-06-01: LEFT 이제 mirror-solve (RIGHT group 으로 풀어 mirror) 라 RIGHT 과 동일
# kinematics → 동일 ceiling 0.78. 낮은 ceiling (0.74) 은 mirrored target 을 낮춰 어깨
# 안 들고 flat 으로 풀려서 j2 가 안 열렸음. 0.78 로 올려 target 을 높여 어깨 lift 유도
# (tablet 제거됨 → over-shoulder 안전 제약 없음).
SHOULDER_Z_CEILING_LEFT_M = 0.78
# Gripper-above-hand offset — 자연스러운 high-five 는 로봇 손이 사람 손보다 살짝
# 위에서 내려와 맞닿는다. closed-loop red target 의 Z 를 사람 손보다 이만큼 올려
# → 실제 gripper (blue) 가 사람 손 (red ball) 위에서 contact. ceiling 으로 cap 되므로
# 사람 손이 어깨 근처면 위로 못 올라가고 ceiling 에 머문다 (안전 우선).
# 0.05 — compliance 0.65 로 올린 뒤 droop 이 작아져 gripper 가 target 을 잘 추종.
# 사람 손보다 5cm 위를 target → 실제로 hand 위에서 contact. ceiling cap 우선.
# 2026-06-01: 사용자 "should be 7cm in z axis" — gripper 가 red ball 보다 Z(수직)로
# 7cm 위에서 멈추게. 0.05→0.07. (RIGHT 은 ~6-7cm 위 도달; LEFT 은 tablet ceiling 0.71
# 때문에 high hand 에서 7cm 까지 못 올라가 limited — variable mismatch 도 영향.)
TAP_ABOVE_HAND_M = 0.07
# Contact standoff — blue palm 은 red (사람 손바닥) 바로 "앞" (robot/shoulder 쪽) 에
# 멈춰야 한다. 절대 red 를 뚫고 지나가/위로 가면 안 됨 (사용자 피드백: "blue must be
# always in front a bit, it sometimes go over where the red ball is"). 그래서 closed-
# loop red target 을 shoulder→hand 축(approach 방향) 따라 이만큼 shoulder 쪽으로 당겨
# (BACK), blue 가 red 앞에 수렴. 수렴 variance 가 있어도 항상 red 앞에 머문다.
# (이전엔 +PRESS_INTO_HAND 로 손 너머로 밀어 가끔 red 를 뚫었음 — 방향 반전.)
# ⚠ PER-ARM — standoff→front gain 이 팔마다 다르다 (좌우 mismatch 방향 차이):
#   RIGHT 0.10 → front ~−3cm (red 앞에 살짝, meet 유지). 이게 목표 "in front a bit".
#   LEFT  0.06 → front ~−3cm. LEFT 는 gain 이 커서 0.10 이면 front −5~−9cm 로 너무
#                앞에 서 (meet 2/8 로 추락). 0.06 이 right 의 0.10 과 같은 ~−3cm.
# 둘 다: blue 가 red 를 절대 뚫지 않고(past-red=0) red 앞 ~3cm 에서 touch (gap 3–7cm).
# ⚠ standoff 를 너무 줄이면 (0.02 시도) tap pose 가 forward/up 으로 밀려 rebound
#   (shoulder 쪽 pull-back) 이 joint-space 에서 tap 에 collapse → raise 가 손까지
#   가고 tap/rebound phase 가 안 움직임 ("holds then returns", sim 에서 확인). 0.10/
#   0.06 이 tap/rebound 유지되는 검증값. touch 와 tap/rebound 는 trade-off.
# (standoff 가 closed-loop red target 을 shoulder→hand 축으로 shoulder 쪽 당김.
#  0 standoff 면 forward-overshoot calibration 때문에 blue 가 red 에 붙거나 뚫음.)
# 2026-06-01: ground-truth 측정상 blue 가 hand 보다 X 로 ~5-6cm short (standoff 가 target
# 을 shoulder 쪽으로 당겨) → 사용자 "blue doesn't tap red nicely". "tiny standoff" 요청대로
# 0.10/0.06 → 0.03 으로 줄여 blue 가 hand 바로 앞 ~2cm 에서 contact. (0 은 punch-through
# 위험이라 0.03 유지.)
# 2026-06-01: 사용자 "standoff 3~5cm off the hand" (blue 가 손 앞 3-5cm 에서 멈춤, 안 닿게).
# 측정상 standoff 0.03 에서 RIGHT 는 0.8cm PAST (너무 가까움), LEFT 는 ~3-4cm front.
# RIGHT render 가 MoveIt 보다 X +5.8cm 앞이라 standoff 를 0.08 로 키워야 ~4cm front. LEFT
# 는 0.03 유지 (이미 3-5cm). per-arm = render mismatch 비대칭 때문.
# 2026-06-01: standoff 는 approach(주로 X/depth) 방향 gap.
# RIGHT: 측정상 render 가 MoveIt target 보다 X +8cm 앞 → standoff 0.03 이면 hand 를 3.4cm
# 지나침(past). 사용자 "pull the right back to stop just in front" → standoff 0.09 로 키워
# blue 를 hand 앞 ~3cm 에서 멈춤 (blueX 0.51-standoff). LEFT 는 이미 12cm short 라 0.03 유지.
CONTACT_STANDOFF_RIGHT_M = 0.09
# LEFT mirror-solves the RIGHT, so its red target must mirror the right's → same
# standoff (scalar, approach-axis) as RIGHT. (Old 0.03 made the mirrored target land
# in the right group's flat regime → shoulder didn't open.)
CONTACT_STANDOFF_LEFT_M = 0.09
# Closed-loop FK feedback — IK 는 link7 위치만 target. 실제 blue ball 시각화는
# openarm_*_hand body + 4cm local Z 에 있고, 두 link 의 world offset 은 IK 가
# 매번 다른 j5/j6/j7 redundancy 해를 골라서 ±15cm 정도 흔들린다 (stress test 결과:
# right arm 평균 |Δ|=21cm, left arm 27cm).
#
# 해결: IK → FK(hand_link) → blue 계산 → residual (red - blue) → IK target 을
# residual 만큼 shift → 재 IK. 보통 1~2 iteration 으로 gap < 2cm 수렴.
#
# Gripper PALM offset (hand-body local frame) — blue ball = gripper 손바닥 (palm).
# closed-loop 이 이 점을 red (사람 손바닥) 에 수렴시켜 palm-to-palm 으로 맞닿게 한다.
# mujoco_twin.GRIPPER_CONTACT_LOCAL_OFFSET 와 동일 (render = closed-loop target 동일점).
# 방향: hand frame 에서 -X = broad slap face (palm normal), +Z = finger 방향.
# palm = -X (face 로) + 작은 +Z (finger contact 영역으로). +Z 를 작게 둠 — 예전 +Z 0.045
# 는 left arm 을 shoulder 쪽으로 들어올려 위험했음 (left frame 에서 +Z 가 위로 향함).
# +Z 0.02 면 lift 미미. URDF: fingers 가 +Z 0.015 에 attach, gripper X 로 얇음.
GRIPPER_BLUE_LOCAL_OFFSET = (-0.04, 0.0, 0.02)
# MoveIt-FK → MuJoCo-render 보정 — closed-loop 은 MoveIt /compute_fk 로 gripper
# 위치를 추정하는데, 실제 MuJoCo 가 렌더하는 팔과 kinematic model 이 ~10cm (Z) /
# ~5cm (Y) 어긋난다 (URDF vs 변환된 MJCF 의 base/link offset 차이로 추정 — 일정한
# 상수 offset, gravity sag 아님 — gravcomp 켜도 안 줄었음). 측정: MuJoCo gripper 가
# MoveIt FK 보다 Z 약 -10cm, Y 약 +5cm(right). target 에 이만큼 더해 closed-loop 이
# 수렴하면 MuJoCo 가 렌더하는 gripper 가 hand 에 맞닿는다. Y 는 per-arm mirror.
# 2026-06-01: RIGHT standoff 0.03→0.09 (X 를 hand 앞으로 당김) 이 approach 축(어깨쪽=위)
# 따라 target Z 를 ~2.3cm 올려 dz +7→+9.3cm. overshoot_Z 0.10→0.077 로 낮춰 +7cm 복원
# (X frontX +4cm 는 유지 — overshoot_Z 는 Z 만 건드림).
TAP_OVERSHOOT_RIGHT = (-0.02, -0.05, +0.077)
# LEFT 은 mirror 가 아니라 per-arm 측정값. palm contact point 기준 재측정 (2026-05-29):
# right palm gap 3.7cm (Y residual +1cm, good). left 는 Y +0.05 일 때 palm 이 hand 보다
# +6.5cm Y → mismatch_Y(left)≈+1.5cm (right 의 +6cm 와 다름). overshoot_Y 를 -0.015 로
# 낮춰 left palm 을 hand 에 center.
# 2026-06-01: overshoot_X +0.04 시도 → LEFT IK 발산 (gap 30cm, 낮은 fallback pose). LEFT
# 는 RIGHT 보다 X(depth) 로 ~5cm 덜 닿는 reach 비대칭이라 target 을 앞으로 밀면 reach 밖
# → 깨짐. -0.02 로 되돌림 (left tap gap ~7.5cm, X 만 ~6cm short).
# 2026-06-01 (tablet 제거 후): LEFT mismatch_Z 가 RIGHT(~10cm)보다 작아(~5-6cm) 같은
# overshoot_Z(0.10)면 left 가 +12cm 위로 over (right 은 +7cm). overshoot_Z 0.10→0.06 으로
# 낮춰 left render 를 right 의 +7cm 에 맞춤 (left mismatch variable 이라 ±2-3cm 흔들림).
# LEFT mirror-solves the RIGHT → red target must mirror the right's. overshoot =
# y-MIRROR of TAP_OVERSHOOT_RIGHT (-0.02,-0.05,+0.077): X,Z same, Y negated → +0.05.
TAP_OVERSHOOT_LEFT  = (-0.02, +0.05, +0.077)
# Initial IK target pre-compensation — gripper-Z 방향 forward offset 의 거친 추정치.
# link7 → hand body 10cm + hand body → blue ball 4cm = 14cm. high-five 자세에서 gripper-Z
# 는 대략 shoulder → red 방향과 일치하므로, 초기 target 을 그 방향으로 14cm 뒤로
# 당기면 link7 이 reach 안으로 들어와 IK 첫 시도 성공률 ↑. closed-loop 이 이후
# residual 로 정밀 보정.
GRIPPER_FORWARD_M = 0.14
CL_MAX_ITERS = 5                     # closed-loop 최대 iteration. 보통 3~4 에 수렴, edge
                                     # case 만 5 까지. 초과 시 best-so-far pose publish.
CL_CONVERGED_M = 0.02                # residual < 2cm 이면 수렴, publish.
# damping 없음 (= 1.0) — under-relaxation 적용했을 때 (0.7) single-shot 가 7.6cm 에서
# stuck. full-step 이 자연 수렴 빠르다. 발산 위험은 divergence guard + best-so-far 가
# 흡수.
CL_MAX_SHIFT_PER_ITER_M = 0.08   # 한 iteration 당 IK target shift 의 최대 magnitude.
                                 # residual 이 이보다 크면 방향만 유지하고 크기만 cap.
                                 # left arm 처럼 iter 0 이 23cm off 일 때 full-step
                                 # shift 가 reach 밖으로 나가 IK fail. cap 으로 reach
                                 # 안에서 점진적 수렴 보장.


class HighfiveNode(Node):
    def __init__(self) -> None:
        super().__init__("highfive_node")

        self._tf_buffer = tf2_ros.Buffer()
        self._tf_listener = tf2_ros.TransformListener(self._tf_buffer, self)

        self._sub = self.create_subscription(
            PointStamped, "/eduping/highfive/hand_point",
            self._on_hand_point, 10,
        )
        self._traj_pub = self.create_publisher(
            JointTrajectory, "/eduping/joint_trajectory", 10,
        )

        self._js_sub = self.create_subscription(
            JointState, "/joint_states", self._on_joint_state, 10,
        )
        self._last_joint_state: Optional[JointState] = None
        # /joint_states 는 한 메시지에 일부 joint 만 들어올 수 있어 누적 머지.
        self._joint_pos: dict[str, float] = {n: 0.0 for n in OPENARM_JOINT_NAMES}

        # Per-arm gesture busy until (cooldown 포함) — 양팔 독립 발사.
        self._gesture_busy_until_s: dict[str, float] = {
            LEFT_ARM_GROUP: 0.0, RIGHT_ARM_GROUP: 0.0,
        }
        # One-tap-per-presence latch — gesture 발사 후 disarm. 손이 box 안에 머무는 동안
        # browser 가 ~100ms 마다 re-POST 하므로 그대로 두면 cooldown 후 또 발사 (double-
        # tap). hand_point stream 에 REARM_GAP_S 이상 공백 (손이 실제로 빠짐) 이 생겨야
        # re-arm. 공백은 max(busy_until, last_hand_point) 기준 — gesture 중 팔이 손을
        # 잠깐 가려 POST 가 끊겨도 (gesture 끝나면 busy_until 이 reference) 오발 re-arm 안 함.
        self._armed: dict[str, bool] = {
            LEFT_ARM_GROUP: True, RIGHT_ARM_GROUP: True,
        }
        self._last_hand_point_at_s: dict[str, float] = {
            LEFT_ARM_GROUP: 0.0, RIGHT_ARM_GROUP: 0.0,
        }
        # Live-tracking state (track-during-raise, lock-at-tap). _track_deadline_s =
        # raise 가 끝나는 절대시각 (그 전까지 re-aim, 그 후 committed). _last_reaim_s =
        # 마지막 re-aim 시각 (throttle). _track_hand_world = 마지막 re-aim 손 world 위치
        # (move threshold).
        self._track_deadline_s: dict[str, float] = {
            LEFT_ARM_GROUP: 0.0, RIGHT_ARM_GROUP: 0.0,
        }
        self._last_reaim_s: dict[str, float] = {
            LEFT_ARM_GROUP: 0.0, RIGHT_ARM_GROUP: 0.0,
        }
        self._track_hand_world: dict[str, Optional[tuple[float, float, float]]] = {
            LEFT_ARM_GROUP: None, RIGHT_ARM_GROUP: None,
        }
        # Closed-loop in-flight guard — busy_until 은 trajectory publish 후에야 set
        # 되는데, 그 전 closed-loop IK/FK (~0.5-1s) 동안 33Hz hand_point 가 각각 새
        # closed-loop 를 또 launch → trajectory flood → raise 시작 때 shiver. 이 flag
        # 가 True 인 동안 새 hand_point 무시. watchdog: CL_WATCHDOG_S 넘으면 (IK 서비스
        # hang 등) 자동 해제해 stuck 방지.
        self._cl_in_progress: dict[str, bool] = {
            LEFT_ARM_GROUP: False, RIGHT_ARM_GROUP: False,
        }
        self._cl_started_s: dict[str, float] = {
            LEFT_ARM_GROUP: 0.0, RIGHT_ARM_GROUP: 0.0,
        }
        # Obstacle pixel cache + DCP-RMP dynamic field state.
        obstacle_qos = QoSProfile(
            depth=2,
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            history=QoSHistoryPolicy.KEEP_LAST,
        )
        self._depth_obstacle_sub = self.create_subscription(
            Image, "/d435/depth/image_rect_raw", self._on_depth_obstacle, obstacle_qos,
        )
        self._obstacle_pixel_count = 0
        # Status publisher — browser UI overlay 가 polling 해서 표시.
        self._status_pub = self.create_publisher(
            String, "/eduping/highfive/status", 10,
        )
        self._status_timer = self.create_timer(0.2, self._publish_status)
        # Safe joint limits — admin UI 가 좁힌 range 를 control_service 가 broadcast.
        # transient_local QoS 라 본 노드가 늦게 join 해도 latched 마지막 값을 받음.
        # 도착 전엔 _safe_limits = None → gesture 발사 거부 (fail-stop). URDF
        # hardcode fallback 제거됨 — admin UI 의 값이 환경별 mechanical obstacle 까지
        # 반영하므로 단일 source.
        self._safe_limits: Optional[dict[str, tuple[float, float]]] = None
        safe_qos = QoSProfile(
            depth=1,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._safe_limits_sub = self.create_subscription(
            String, "/eduping/safe_joint_limits", self._on_safe_limits, safe_qos,
        )
        # MoveIt self-collision pre-validation — startup 시 1회 호출 후 결과 cache.
        # /check_state_validity 는 move_group 이 노출하는 SRDF 기반 self-collision
        # checker. 9 configurations (right/left/bimanual × HIGH/TAP/PULL) 를 검사해
        # 부딪히는 pose 가 있으면 startup 시점에 loud warn — runtime 동안엔 추가 call
        # 없어 latency 0.
        self._validity_cli = self.create_client(
            GetStateValidity, "/check_state_validity",
        )
        self._validation_kicked = False
        # MoveIt IK — gesture trigger 시 hand 의 world 위치로 EE 보낼 joint values
        # 계산. TRAC-IK (kinematics_trac_ik.yaml 로 KDL override 됨) 가 7DOF redundant
        # 해를 잘 풀어줌. 호출 실패 / timeout 시 scripted TAP pose fallback.
        self._ik_cli = self.create_client(
            GetPositionIK, "/compute_ik",
        )
        # MoveIt FK — closed-loop correction 에서 IK 후 openarm_*_hand body world pose
        # 를 가져와 blue ball world 위치 계산 (hand + 4cm local Z).
        self._fk_cli = self.create_client(GetPositionFK, "/compute_fk")
        # DCP-RMP dynamic state — frame diff 로 dynamic obstacles 검출.
        self._prev_depth_mm: Optional[np.ndarray] = None
        self._dyn_closest_m: float = float("inf")
        self._dyn_x_norm: float = 0.0
        # 마지막으로 hand_point 받은 시각 + 그 손의 depth — dynamic obstacle 필터링.
        self._last_hand_seen_at_s: float = 0.0
        self._last_hand_depth_m: float = 0.5
        # Mid-gesture abort 추적 — monitor timer 가 dynamic obstacle 체크.
        self._abort_triggered: dict[str, bool] = {
            LEFT_ARM_GROUP: False, RIGHT_ARM_GROUP: False,
        }
        # Closed-loop FK feedback state — gesture trigger 시 채워지고 _on_ik_response
        # → _on_fk_correction_response chain 으로 흐르며 update 됨. key = arm.group.
        # 각 iteration 의 IK target / iter count / 현재까지 best IK pose 를 보관.
        self._cl_state: dict[str, dict] = {}
        self._monitor_timer = self.create_timer(
            1.0 / DCP_MONITOR_HZ, self._monitor_gesture_for_abort,
        )

        self.get_logger().info(
            "highfive_node ready — sub /eduping/highfive/hand_point → "
            "scripted gesture pub /eduping/joint_trajectory + DCP-RMP obstacle gate",
        )

    def _on_joint_state(self, msg: JointState) -> None:
        for name, pos in zip(msg.name, msg.position):
            if name in self._joint_pos:
                self._joint_pos[name] = float(pos)
        merged = JointState()
        merged.header = msg.header
        merged.name = list(OPENARM_JOINT_NAMES)
        merged.position = [self._joint_pos[n] for n in OPENARM_JOINT_NAMES]
        self._last_joint_state = merged

    def _on_hand_point(self, msg: PointStamped) -> None:
        """Scripted high-five gesture with hand-position tracking:
        - 손이 zone 에 보이면 home→HIGH→TAP→PULL→home 시퀀스 1회 발사.
        - 손의 화면상 lateral 위치 (optical X) 에 비례한 joint1 bias 로 EE 가 손
          쪽으로 swing.
        - hand_point 받는 동안은 dynamic obstacle 검출 grace (자기 손이 obstacle
          로 잘못 인식되는 거 방지).
        """
        # 1. Hand seen — grace 시간 + depth 갱신.
        self._last_hand_seen_at_s = self.get_clock().now().nanoseconds * 1e-9
        if msg.point.z > 0.05:
            self._last_hand_depth_m = float(msg.point.z)
        # 2. Arm hint.
        raw_frame = msg.header.frame_id
        if raw_frame.endswith(":left"):
            arm = LEFT_ARM
        elif raw_frame.endswith(":right"):
            arm = RIGHT_ARM
        else:
            # Suffix 없으면 hand Y 부호로 결정 (browser 가 항상 suffix 보내지만 fallback).
            tf_frame = raw_frame
            try:
                tform = self._tf_buffer.lookup_transform(
                    BASE_FRAME, tf_frame, Time(),
                    timeout=Duration(seconds=0.1),
                )
                msg.header.frame_id = tf_frame
                hand_y = do_transform_point(msg, tform).point.y
                arm = LEFT_ARM if hand_y >= 0.0 else RIGHT_ARM
            except (tf2_ros.LookupException, tf2_ros.ConnectivityException,
                    tf2_ros.ExtrapolationException):
                return
        now_s = self.get_clock().now().nanoseconds * 1e-9
        # Re-arm latch — a hand_point after a gap ≥ REARM_GAP_S (since the gesture end
        # OR the previous point) means the hand actually left and returned → arm a new
        # tap. A hand that merely lingers (re-POSTed ~every 100ms) keeps the gap tiny →
        # stays disarmed → no double-tap. ref = max(busy_until, last_point) so the arm
        # briefly occluding the hand mid-gesture can't falsely re-arm afterwards.
        ref_s = max(self._gesture_busy_until_s[arm.group],
                    self._last_hand_point_at_s[arm.group])
        self._last_hand_point_at_s[arm.group] = now_s
        if now_s - ref_s > REARM_GAP_S:
            self._armed[arm.group] = True
        # Closed-loop in-flight guard — IK/FK chain 진행 중이면 새 hand_point 전부
        # 무시 (flood 방지). watchdog 지나면 강제 해제 (hang self-heal).
        if self._cl_in_progress[arm.group]:
            if now_s - self._cl_started_s[arm.group] < CL_WATCHDOG_S:
                return
            self._cl_in_progress[arm.group] = False  # watchdog 발동 → 재시도 허용
            self.get_logger().warn(
                f"{arm.group} closed-loop watchdog 발동 (>{CL_WATCHDOG_S}s) — "
                "in-flight guard 해제",
            )
        # Tracking gate (track-during-raise, lock-at-tap) — gesture active (busy_until
        # 전) 중에도 raise(tracking) window 동안엔 새 hand 로 re-aim 해 blue 가 움직이는
        # red 를 따라간다. raise 가 끝나가면 (deadline − CL_BUDGET 이후) committed → 무시
        # 해서 tap/rebound/return 을 lock. 예전엔 이 retarget 이 over-shoulder/shake 를
        # 냈으나 z_ceiling clamp + 현재자세 시작 + 아래 throttle/move-threshold 로 가드.
        is_reaim = False
        if now_s < self._gesture_busy_until_s[arm.group]:
            if now_s >= self._track_deadline_s[arm.group] - TRACK_CL_BUDGET_S:
                return  # committed — tap 이후 lock, 새 hand 무시
            if now_s - self._last_reaim_s[arm.group] < TRACK_REAIM_THROTTLE_S:
                return  # re-aim throttle (closed-loop 가 ~0.5-1s 라 과발 방지)
            is_reaim = True  # raise 중 — move-threshold 통과하면 re-aim (hand_world 후 검사)
        # One-tap-per-presence: a NEW gesture (not a re-aim of an active one) fires only
        # if armed — i.e. the hand left and returned since the last tap (re-arm latch
        # above). A hand left in the box stays disarmed → no second tap.
        if not is_reaim:
            if not self._armed[arm.group]:
                return
            self._armed[arm.group] = False  # disarm until the hand leaves + returns
        # Obstacle gates 제거됨 — depth frame-diff 기반 dynamic obstacle 검출이
        # 사용자 본인 손/팔 움직임을 false positive 로 잡아 gesture 를 막거나 reroute
        # 시켜버리는 케이스가 많아 운용 가치 없음. 안전 layer 는 (1) admin UI safe
        # joint limits (2) SRDF self-collision pre-validation (3) hand-lost mid-HIGH
        # safe abort 세 가지로 충분.
        reroute_rad = 0.0
        amplitude_scale = 1.0
        self._abort_triggered[arm.group] = False

        # 3. Heuristic deflection — IK 실패 시 graceful fallback. Optical-frame
        # norms 를 j1/j2/j4 offset 으로 mapping 해 scripted TAP pose 에 더함. IK 가
        # 성공하면 무시되고 IK joints 사용. axis 양팔 mirror (j1/j2) 는 sign 으로 처리.
        sign_lr = -1.0 if arm is LEFT_ARM else +1.0
        hx_norm = hy_norm = hz_norm = 0.0
        if msg.point.z > 0.05:
            hx_norm = max(-1.0, min(1.0, msg.point.x / (msg.point.z * 0.82)))
            hy_norm = max(-1.0, min(1.0,
                                    msg.point.y / (msg.point.z * HAND_Y_NORM_DIVISOR)))
            hz_norm = max(-1.0, min(1.0,
                                    (msg.point.z - HAND_Z_CENTER_M) / HAND_Z_HALF_BAND_M))
        # j1 deflection: 양팔 base rpy ±π/2 라 같은 world 방향 deflection 은 OPPOSITE
        # 부호 joint value 가 필요. HIGH_POSE_RIGHT j1 = +_J1_OUTWARD, HIGH_POSE_LEFT
        # j1 = -_J1_OUTWARD 가 이미 mirror. fallback_j1 도 mirror 유지하려면 sign_lr
        # 곱하지 말고 raw hx_norm 의 부호를 그대로 따라가야 한다 — hand-on-right →
        # +deflection, hand-on-left → -deflection. 각 arm 은 자기 쪽 손만 처리해서
        # hx_norm 부호가 자동으로 mirror.
        fallback_j1 = HAND_TRACK_J1_GAIN_RAD * hx_norm
        fallback_j2 = sign_lr * (
            HAND_TRACK_J2_BIAS_RAD - HAND_TRACK_J2_GAIN_RAD * hy_norm
        )
        # j4: depth (가까울수록 +) + vertical (위쪽일수록 +, fold up). 두 축 모두
        # gripper world Z 를 위로 끌어올려 손 위치 따라가게 함.
        fallback_j4 = (
            -HAND_TRACK_J4_GAIN_RAD * hz_norm
            - HAND_TRACK_J4_VERT_GAIN_RAD * hy_norm
        )

        # 4. Hand world position 으로 IK target 빌드 후 async call.
        # IK 성공: solution 의 arm joint 값들을 TAP pose 로 사용 → 정확히 hand 위치 reach.
        # IK 실패: scripted TAP pose + fallback_{j1,j2,j4} deflection — 정확히는 못
        # 닿아도 hand 방향으로 lean.
        hand_world = self._transform_hand_to_world(msg)
        if hand_world is None:
            self.get_logger().warn(
                f"🖐 {arm.group}: TF lookup 실패 → scripted fallback (deflected)",
                throttle_duration_sec=2.0,
            )
            self._publish_scripted_gesture(
                arm, now_s, amplitude_scale,
                reroute_j1_rad=reroute_rad + fallback_j1,
                track_j2_rad=fallback_j2,
                track_j4_rad=fallback_j4,
            )
            return

        # Tracking bookkeeping. re-aim 이면 손이 충분히 움직였는지 (move threshold) 검사
        # 해 미세 jitter 로 인한 불필요 republish 차단. fresh fire 면 tracking deadline
        # (= raise 종료 절대시각) 설정.
        hw = (hand_world.point.x, hand_world.point.y, hand_world.point.z)
        if is_reaim:
            prev = self._track_hand_world[arm.group]
            if prev is not None:
                moved = math.sqrt(sum((a - b) ** 2 for a, b in zip(hw, prev)))
                if moved < TRACK_REAIM_MOVE_M:
                    return  # 손 거의 안 움직임 — re-aim 생략 (현재 trajectory 유지)
        else:
            self._track_deadline_s[arm.group] = now_s + TRACK_WINDOW_S
        self._last_reaim_s[arm.group] = now_s
        self._track_hand_world[arm.group] = hw

        self.get_logger().info(
            f"🖐 {arm.group}: {'re-aim' if is_reaim else 'gesture trigger'} (hand world="
            f"[{hand_world.point.x:+.2f},{hand_world.point.y:+.2f},"
            f"{hand_world.point.z:+.2f}])",
        )

        if not self._ik_cli.service_is_ready():
            # IK 서비스 없으면 순수 heuristic.
            self._publish_scripted_gesture(
                arm, now_s, amplitude_scale,
                reroute_j1_rad=reroute_rad + fallback_j1,
                track_j2_rad=fallback_j2,
                track_j4_rad=fallback_j4,
            )
            return
        # Closed-loop IK + FK feedback —
        #   1) IK 로 link7 을 red target 에 placement
        #   2) FK 로 openarm_*_hand 의 world pose 추출 → blue ball 위치 계산
        #   3) residual (red - blue) 만큼 IK target 을 shift 해서 재 IK
        #   4) gap < 2cm 또는 3 iteration 이면 publish
        # j6/j7 (wrist) 는 매 iteration 마다 scripted high-five 로 override → palm
        # 면이 일관되게 사용자 향함. j5 는 IK 가 결정 (sharp edge 위험 회피).
        ideal_seed = self._compute_ideal_high_five_seed(
            arm, fallback_j1, fallback_j2, fallback_j4,
        )
        # closed-loop 의 "red" = 실제 red + per-arm soft-Kp tracking overshoot
        #   − per-arm CONTACT_STANDOFF (shoulder→hand 축으로 shoulder 쪽 BACK — blue 가
        #   red 앞에 멈추게). FK 가 이 점으로 수렴 → palm 이 사람 손바닥 바로 앞에서 contact,
        #   절대 뚫고 지나가지 않음. Z 는 per-arm z_ceiling 으로 cap (tablet 안전).
        overshoot = (TAP_OVERSHOOT_LEFT if arm is LEFT_ARM
                     else TAP_OVERSHOOT_RIGHT)
        z_ceiling = (SHOULDER_Z_CEILING_LEFT_M if arm is LEFT_ARM
                     else SHOULDER_Z_CEILING_RIGHT_M)
        hsx, hsy, hsz = (RIGHT_SHOULDER_WORLD if arm is RIGHT_ARM
                         else LEFT_SHOULDER_WORLD)
        ax, ay, az = (hand_world.point.x - hsx, hand_world.point.y - hsy,
                      hand_world.point.z - hsz)
        anorm = math.sqrt(ax * ax + ay * ay + az * az) or 1.0
        contact_standoff = (CONTACT_STANDOFF_LEFT_M if arm is LEFT_ARM
                            else CONTACT_STANDOFF_RIGHT_M)
        standoff = contact_standoff / anorm
        red_xyz = (
            hand_world.point.x + overshoot[0] - ax * standoff,
            hand_world.point.y + overshoot[1] - ay * standoff,
            min(hand_world.point.z + overshoot[2] + TAP_ABOVE_HAND_M - az * standoff,
                z_ceiling),
        )
        # 초기 IK target = red 에서 shoulder 방향으로 GRIPPER_FORWARD_M 뒤로 — 첫
        # IK 시도가 reach 안에 들어가도록. closed-loop 이 residual 로 refine.
        sx, sy, sz = (RIGHT_SHOULDER_WORLD if arm is RIGHT_ARM
                      else LEFT_SHOULDER_WORLD)
        rdx, rdy, rdz = (red_xyz[0] - sx, red_xyz[1] - sy, red_xyz[2] - sz)
        rdist = math.sqrt(rdx * rdx + rdy * rdy + rdz * rdz)
        if rdist > 1e-3:
            scale = GRIPPER_FORWARD_M / rdist
            init_target = (
                red_xyz[0] - rdx * scale,
                red_xyz[1] - rdy * scale,
                red_xyz[2] - rdz * scale,
            )
        else:
            init_target = red_xyz
        self._cl_state[arm.group] = {
            "red": red_xyz,
            "target": init_target,
            "iter": 0,
            "ctx": (now_s, amplitude_scale, reroute_rad,
                    fallback_j1, fallback_j2, fallback_j4),
            "last_pose": None,
            # best-so-far — divergence 발생 시 이전 best 로 fallback.
            "best_pose": None,
            "best_gap_m": float("inf"),
        }
        # In-flight guard ON — closed-loop publish 까지 새 hand_point 무시 (flood
        # 방지). 임시 busy_until 도 set (publish 시 정확한 값으로 덮어씀).
        self._cl_in_progress[arm.group] = True
        self._cl_started_s[arm.group] = now_s
        self._gesture_busy_until_s[arm.group] = now_s + CL_WATCHDOG_S + 0.5
        req = self._build_ik_request_with_seed(arm, init_target, ideal_seed)
        future = self._ik_cli.call_async(req)
        future.add_done_callback(
            lambda f: self._on_ik_response(f, arm),
        )

    def _transform_hand_to_world(self, msg: PointStamped) -> Optional[PointStamped]:
        """frame_id 의 ":left"/":right" suffix 제거 후 BASE_FRAME 으로 변환."""
        raw_frame = msg.header.frame_id
        if raw_frame.endswith(":left"):
            actual_frame = raw_frame[:-5]
        elif raw_frame.endswith(":right"):
            actual_frame = raw_frame[:-6]
        else:
            actual_frame = raw_frame
        if actual_frame == BASE_FRAME:
            out = PointStamped()
            out.header = msg.header
            out.header.frame_id = BASE_FRAME
            out.point = msg.point
            return out
        try:
            tform = self._tf_buffer.lookup_transform(
                BASE_FRAME, actual_frame, Time(),
                timeout=Duration(seconds=0.1),
            )
        except (tf2_ros.LookupException, tf2_ros.ConnectivityException,
                tf2_ros.ExtrapolationException):
            return None
        m2 = PointStamped()
        m2.header.frame_id = actual_frame
        m2.header.stamp = msg.header.stamp
        m2.point = msg.point
        return do_transform_point(m2, tform)

    def _compute_ideal_high_five_seed(self, arm: _ArmConfig,
                                       fallback_j1: float, fallback_j2: float,
                                       fallback_j4: float) -> list[float]:
        """HIGH_POSE + heuristic deflections — "이 손 위치에 reach 하는 이상적
        high-five 자세". Multi-seed IK 의 ranking 기준 및 base seed."""
        high_pose = (HIGH_POSE_LEFT if arm is LEFT_ARM else HIGH_POSE_RIGHT)
        seed = list(high_pose)
        seed[0] = max(-_J1_SAFE_LIMIT,
                      min(_J1_SAFE_LIMIT, seed[0] + fallback_j1))
        seed[1] += fallback_j2
        seed[3] += fallback_j4
        return seed

    def _build_ik_request_with_seed(self, arm: _ArmConfig,
                                     target_xyz: tuple[float, float, float],
                                     seed_arm: list[float]) -> GetPositionIK.Request:
        """IK request 빌더 — target 은 world (BASE_FRAME) xyz, seed 는 7-DOF arm pose.

        target 이 어깨 reach sphere (MAX_REACH_M) 밖이면 shoulder→target 방향으로
        sphere 위에 투영. 너무 가깝거나 (10cm 미만) 좌표 깨지면 0.5 × dist 로 가운데
        잡음. Static TAP_* offset 은 closed-loop FK 가 흡수하므로 사용 안 함.
        """
        # LEFT solves via the RIGHT group on a y-mirrored target/seed (see
        # _mirror_arm_joints): the right opens its shoulder, the left's own IK doesn't.
        # The response handlers mirror the solution back to the left joints.
        if arm is LEFT_ARM:
            solve_group, solve_ee, solve_names = (
                RIGHT_ARM_GROUP, RIGHT_EE_LINK, RIGHT_JOINT_NAMES)
            target_xyz = (target_xyz[0], -target_xyz[1], target_xyz[2])
            seed_arm = _mirror_arm_joints(seed_arm)
        else:
            solve_group, solve_ee, solve_names = arm.group, arm.ee_link, arm.joint_names
        # target is now in the RIGHT arm's frame (left was mirrored to the right side).
        sx, sy, sz = RIGHT_SHOULDER_WORLD
        hx, hy, hz = target_xyz
        dx, dy, dz = hx - sx, hy - sy, hz - sz
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        target_dist = min(dist, MAX_REACH_M)
        if target_dist < 0.10:
            target_dist = max(0.10, dist * 0.5)
        if dist > 1e-3:
            scale = target_dist / dist
            tx = sx + dx * scale
            ty = sy + dy * scale
            tz = sz + dz * scale
        else:
            tx, ty, tz = hx, hy, hz
        req = GetPositionIK.Request()
        ik = PositionIKRequest()
        ik.group_name = solve_group
        ik.ik_link_name = solve_ee
        ps = PoseStamped()
        ps.header.frame_id = BASE_FRAME
        ps.header.stamp = self.get_clock().now().to_msg()
        ps.pose.position.x = tx
        ps.pose.position.y = ty
        ps.pose.position.z = tz
        ps.pose.orientation = PALM_FACING_QUAT  # position-only IK 라 무시됨
        ik.pose_stamped = ps
        ik.timeout = Duration(seconds=IK_TIMEOUT_S).to_msg()
        if self._last_joint_state is not None:
            ik.robot_state = RobotState()
            seed_js = JointState()
            seed_js.header = self._last_joint_state.header
            seed_js.name = list(self._last_joint_state.name)
            seed_js.position = list(self._last_joint_state.position)
            for jn, v in zip(solve_names[:7], seed_arm):
                if jn in seed_js.name:
                    seed_js.position[seed_js.name.index(jn)] = float(v)
            ik.robot_state.joint_state = seed_js
        ik.avoid_collisions = False
        req.ik_request = ik
        return req

    def _on_ik_response(self, future, arm: _ArmConfig) -> None:
        """Closed-loop chain stage 1 — IK response → FK on hand link.

        IK 성공 시 j6/j7 wrist override 적용한 pose 를 state 에 저장하고 FK 호출
        chain into `_on_fk_correction_response`. 거기서 blue ball 계산 + residual
        평가 → 수렴이면 publish, 아니면 IK target shift 후 재 IK.

        IK 실패 시 graceful fallback — 이전 iteration 의 pose (있으면) publish,
        없으면 scripted heuristic.
        """
        state = self._cl_state.get(arm.group)
        if state is None:
            return  # gesture cooldown 사이 stale callback
        ctx = state["ctx"]
        now_s, amplitude_scale, reroute_rad, fb_j1, fb_j2, fb_j4 = ctx
        ik_arm_pose: Optional[list[float]] = None
        try:
            result = future.result()
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(f"IK call 실패: {exc}")
            result = None
        if result is not None and result.error_code.val == MoveItErrorCodes.SUCCESS:
            full = dict(zip(
                result.solution.joint_state.name,
                result.solution.joint_state.position,
            ))
            try:
                # LEFT solved via the RIGHT group → solution is in right joints; mirror
                # back to left. RIGHT solved natively. (see _build_ik_request_with_seed)
                if arm is LEFT_ARM:
                    ik_arm_pose = _mirror_arm_joints(
                        [float(full[jn]) for jn in RIGHT_JOINT_NAMES])
                else:
                    ik_arm_pose = [float(full[jn]) for jn in arm.joint_names]
                # j6/j7 (wrist) scripted override, j5 IK 결정. position-only IK 라
                # orientation 이 free → j6 (pitch up) + j7 (roll, mirror) 로 palm 면
                # 방향 일관. (full-pose IK 로 slap-face 를 강제하려 했으나 LEFT arm
                # 이 -31 → position-only + override 로 복귀.) finger 은 mujoco 가 0.
                sign_lr = -1.0 if arm is LEFT_ARM else +1.0
                ik_arm_pose[5] = _J6_UP                  # wrist pitch
                ik_arm_pose[6] = sign_lr * _J7_HIGH_MAG  # wrist roll (mirror)
            except KeyError:
                self.get_logger().warn(
                    "IK 응답에 arm joints 누락 — graceful fallback 사용",
                )
                ik_arm_pose = None
        elif result is not None:
            self.get_logger().warn(
                f"IK error_code={result.error_code.val} → graceful fallback "
                f"(j1={fb_j1:+.2f} j2={fb_j2:+.2f} j4={fb_j4:+.2f}, "
                f"iter={state['iter']}).",
                throttle_duration_sec=2.0,
            )
        if ik_arm_pose is None:
            # 이번 iteration IK 실패. best-so-far 있으면 그걸 쓰고, 첫 iter 부터 실패면
            # scripted heuristic 으로 fallback.
            best_pose = state["best_pose"]
            best_gap = state["best_gap_m"]
            self._cl_state.pop(arm.group, None)
            if best_pose is not None:
                self.get_logger().info(
                    f"  {arm.group} closed-loop IK iter={state['iter']} 실패 — "
                    f"best (gap={best_gap*100:.1f}cm) pose publish.",
                )
                self._publish_scripted_gesture(
                    arm, now_s, amplitude_scale,
                    reroute_j1_rad=reroute_rad,
                    ik_tap_arm_pose=best_pose,
                )
            else:
                self._publish_scripted_gesture(
                    arm, now_s, amplitude_scale,
                    reroute_j1_rad=reroute_rad + fb_j1,
                    track_j2_rad=fb_j2, track_j4_rad=fb_j4,
                )
            return

        # IK 성공. last_pose 갱신 후 FK 호출 → blue ball 위치 계산.
        state["last_pose"] = ik_arm_pose
        if not self._fk_cli.service_is_ready():
            # FK 없으면 closed-loop 불가 — 첫 iter 의 IK pose 그대로 publish.
            self.get_logger().warn(
                "/compute_fk 없음 — closed-loop 우회, IK pose 그대로 publish",
                throttle_duration_sec=5.0,
            )
            self._cl_state.pop(arm.group, None)
            self._publish_scripted_gesture(
                arm, now_s, amplitude_scale,
                reroute_j1_rad=reroute_rad,
                ik_tap_arm_pose=ik_arm_pose,
            )
            return

        fk_req = GetPositionFK.Request()
        fk_req.header.frame_id = BASE_FRAME
        fk_req.fk_link_names = [arm.hand_link]
        js = JointState()
        js.name = list(OPENARM_JOINT_NAMES)
        js.position = [0.0] * len(OPENARM_JOINT_NAMES)
        for jn, v in zip(arm.joint_names[:7], ik_arm_pose):
            if jn in js.name:
                js.position[js.name.index(jn)] = float(v)
        fk_req.robot_state.joint_state = js
        fk_future = self._fk_cli.call_async(fk_req)
        fk_future.add_done_callback(
            lambda f: self._on_fk_correction_response(f, arm),
        )

    def _on_fk_correction_response(self, future, arm: _ArmConfig) -> None:
        """Closed-loop chain stage 2 — FK response → blue 계산 → residual 평가.

        매 iteration 마다 best-so-far pose (최소 gap) 를 추적해서 마지막에 best 를
        publish. divergence (gap 이 best 보다 1.5× 이상 커짐) 시 즉시 best 로 fallback —
        clamp saturation 또는 IK singularity branch jump 으로 인한 catastrophic
        outlier 방지.

        - blue ball world = hand_pos + R(q) @ GRIPPER_BLUE_LOCAL_OFFSET (slap surface)
        - residual = red_target - blue
        - 종료: 수렴 (gap < CL_CONVERGED_M), max iter, 발산 — 모두 best pose publish
        - 계속: IK target += CL_DAMPING × residual → 재 IK
        """
        state = self._cl_state.get(arm.group)
        if state is None:
            return
        ctx = state["ctx"]
        now_s, amplitude_scale, reroute_rad, fb_j1, fb_j2, fb_j4 = ctx
        last_pose = state["last_pose"]

        def _publish_best(reason: str) -> None:
            best_pose = state["best_pose"] or last_pose
            best_gap = state["best_gap_m"]
            # link7 target (closed-loop 가 수렴시킨 값) 을 shoulder 쪽으로 당겨 rebound
            # IK target 생성 — gripper 가 tap 에서 BACK 으로 물러나는 recoil (같은 Z).
            tgt = state["target"]
            self.get_logger().info(
                f"  {arm.group} closed-loop {reason} "
                f"(iter={state['iter']}, best gap={best_gap*100:.1f}cm) — TAP publish.",
            )
            self._cl_state.pop(arm.group, None)
            sx, sy, sz = (RIGHT_SHOULDER_WORLD if arm is RIGHT_ARM
                          else LEFT_SHOULDER_WORLD)
            dx, dy = tgt[0] - sx, tgt[1] - sy
            hdist = math.sqrt(dx * dx + dy * dy)
            # Rebound target = link7 target 을 shoulder 쪽으로 (X,Y) 당기고 Z 는
            # REBOUND_DOWN_M 만큼 내림. 같은 Z 로 두면 (특히 LEFT arm) IK 가 retract
            # 하며 gripper 를 위로 들어올려 shoulder 위 (Z>0.698) 로 over → tablet 위험
            # (random green-box sweep 에서 left 4/8 over-shoulder, maxZ 0.739).
            # back + DOWN 으로 당기면 rebound 가 절대 안 솟고 X retreat 는 그대로 보임.
            rbz = min(tgt[2] - REBOUND_DOWN_M, REBOUND_MAX_Z)
            if hdist > 1e-3:
                scale = min(REBOUND_BACK_M, hdist) / hdist
                rb_target = (tgt[0] - dx * scale, tgt[1] - dy * scale, rbz)
            else:
                rb_target = (tgt[0], tgt[1], rbz)
            # Rebound IK (position-only, seed=tap pose). shoulder 쪽이라 reach 안쪽
            # → 거의 항상 성공. 실패 시 _on_rebound_ik_response 가 lerp fallback.
            rb_req = self._build_ik_request_with_seed(arm, rb_target, best_pose)
            rb_future = self._ik_cli.call_async(rb_req)
            rb_future.add_done_callback(
                lambda f: self._on_rebound_ik_response(
                    f, arm, now_s, amplitude_scale, reroute_rad, best_pose),
            )

        try:
            result = future.result()
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(
                f"FK call 실패 ({arm.group}, iter={state['iter']}): {exc}",
            )
            _publish_best("FK 실패")
            return
        if (result is None
                or result.error_code.val != MoveItErrorCodes.SUCCESS
                or not result.pose_stamped):
            code = result.error_code.val if result else "no-result"
            self.get_logger().warn(
                f"FK error ({arm.group}, iter={state['iter']}): {code}",
            )
            _publish_best("FK error")
            return

        pose = result.pose_stamped[0].pose
        # palm point = hand_pos + R(q) @ GRIPPER_BLUE_LOCAL_OFFSET (full rotation —
        # offset 이 -X+Z 라 3 column 모두 필요). 이 점을 red 에 수렴 → palm-to-palm.
        qx, qy, qz, qw = (pose.orientation.x, pose.orientation.y,
                          pose.orientation.z, pose.orientation.w)
        ox, oy, oz = GRIPPER_BLUE_LOCAL_OFFSET
        xax = (1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy + qz * qw), 2 * (qx * qz - qy * qw))
        yax = (2 * (qx * qy - qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz + qx * qw))
        zax = (2 * (qx * qz + qy * qw), 2 * (qy * qz - qx * qw), 1 - 2 * (qx * qx + qy * qy))
        blue_x = pose.position.x + ox * xax[0] + oy * yax[0] + oz * zax[0]
        blue_y = pose.position.y + ox * xax[1] + oy * yax[1] + oz * zax[1]
        blue_z = pose.position.z + ox * xax[2] + oy * yax[2] + oz * zax[2]

        rx, ry, rz = state["red"]
        res_x = rx - blue_x
        res_y = ry - blue_y
        res_z = rz - blue_z
        gap = math.sqrt(res_x * res_x + res_y * res_y + res_z * res_z)
        prev_best = state["best_gap_m"]
        if gap < prev_best:
            state["best_pose"] = last_pose
            state["best_gap_m"] = gap
        self.get_logger().info(
            f"  {arm.group} closed-loop iter={state['iter']} "
            f"blue=({blue_x:+.2f},{blue_y:+.2f},{blue_z:+.2f}) "
            f"red=({rx:+.2f},{ry:+.2f},{rz:+.2f}) gap={gap*100:.1f}cm "
            f"(best {state['best_gap_m']*100:.1f}cm)",
        )

        if gap < CL_CONVERGED_M:
            _publish_best(f"converged gap={gap*100:.1f}cm")
            return
        if state["iter"] >= CL_MAX_ITERS - 1:
            _publish_best(f"max iters gap={gap*100:.1f}cm")
            return
        # Divergence guard — best 보다 3× 이상 나빠지면 중단. 작은 oscillation 은
        # 허용해 후속 iter 가 수렴할 기회. branch jump 같은 큰 발산만 차단.
        if prev_best < float("inf") and gap > prev_best * 3.0 + 0.05:
            _publish_best(f"divergence gap={gap*100:.1f}cm > 3×best")
            return

        # 새 IK target = 현재 target + residual. magnitude > CL_MAX_SHIFT_PER_ITER_M
        # 이면 방향 유지 + 크기만 cap → reach 밖으로 한 번에 점프하는 것 방지.
        shift_mag = math.sqrt(res_x * res_x + res_y * res_y + res_z * res_z)
        if shift_mag > CL_MAX_SHIFT_PER_ITER_M:
            scale = CL_MAX_SHIFT_PER_ITER_M / shift_mag
            res_x *= scale
            res_y *= scale
            res_z *= scale
        tx, ty, tz = state["target"]
        new_target = (tx + res_x, ty + res_y, tz + res_z)
        state["target"] = new_target
        state["iter"] += 1
        # 다음 IK 의 seed = 직전 IK pose (수렴 안정).
        req = self._build_ik_request_with_seed(arm, new_target, last_pose)
        ik_future = self._ik_cli.call_async(req)
        ik_future.add_done_callback(
            lambda f: self._on_ik_response(f, arm),
        )

    def _on_rebound_ik_response(self, future, arm: _ArmConfig, now_s: float,
                                amplitude_scale: float, reroute_rad: float,
                                tap_pose: list[float]) -> None:
        """Rebound IK 응답 → tap + rebound pose 로 gesture publish.

        rebound IK 성공: j6/j7 wrist override (tap 과 동일) 후 rebound pose 로 사용.
        실패: ik_rebound_arm_pose=None → _publish_scripted_gesture 가 lerp fallback.
        """
        rebound_pose: Optional[list[float]] = None
        try:
            result = future.result()
        except Exception:  # noqa: BLE001
            result = None
        if result is not None and result.error_code.val == MoveItErrorCodes.SUCCESS:
            full = dict(zip(
                result.solution.joint_state.name,
                result.solution.joint_state.position,
            ))
            try:
                if arm is LEFT_ARM:  # solved via right group → mirror back (see above)
                    rebound_pose = _mirror_arm_joints(
                        [float(full[jn]) for jn in RIGHT_JOINT_NAMES])
                else:
                    rebound_pose = [float(full[jn]) for jn in arm.joint_names]
                sign_lr = -1.0 if arm is LEFT_ARM else +1.0
                rebound_pose[5] = _J6_UP                  # wrist pitch (tap 과 동일)
                rebound_pose[6] = sign_lr * _J7_HIGH_MAG  # wrist roll (mirror)
            except KeyError:
                rebound_pose = None
        if rebound_pose is None:
            self.get_logger().info(
                f"  {arm.group} rebound IK 실패 — lerp fallback rebound",
            )
        self._publish_scripted_gesture(
            arm, now_s, amplitude_scale,
            reroute_j1_rad=reroute_rad,
            ik_tap_arm_pose=tap_pose,
            ik_rebound_arm_pose=rebound_pose,
        )

    def _monitor_gesture_for_abort(self) -> None:
        """Mid-gesture safety monitor — disabled.

        Hand-lost abort 도 제거: 어떤 어린이는 high-five 직전에 손을 살짝 내렸다
        다시 내미는 식으로 행동하는데, 그 때마다 home 으로 abort 하면 어색한
        후퇴 모션이 발생. 대신 published trajectory 가 마지막 commanded 자세까지
        진행한 뒤 그 자리에서 hold (mujoco_twin 의 TRAJ_TIMEOUT_S 동안 마지막
        target 유지) — 자연스러운 "기다리는" 모션. 새 hand_point 가 도착하면
        cooldown 이 풀린 뒤 새 gesture 가 그 자세 에서 이어짐."""
        return

    def _on_safe_limits(self, msg: String) -> None:
        """Admin UI 가 좁힌 safe travel range 를 cache. 다음 gesture 부터 적용.

        Admin (control_service.joint_limits) 가 이미 URDF 한계 안으로 정규화한 값을
        보내주므로 본 노드는 별도 hardware clamp 없이 그대로 받는다. min>max 인 행만
        교환해 입력 견고성 확보.
        """
        try:
            data = json.loads(msg.data) if msg.data else {}
        except (ValueError, TypeError):
            self.get_logger().warn("safe_joint_limits parse 실패 — 기존 cache 유지")
            return
        updated: dict[str, tuple[float, float]] = {}
        for name, row in (data.items() if isinstance(data, dict) else ()):
            if not isinstance(row, dict):
                continue
            try:
                lo = float(row["min"])
                hi = float(row["max"])
            except (KeyError, TypeError, ValueError):
                continue
            if lo > hi:
                lo, hi = hi, lo
            updated[name] = (lo, hi)
        if not updated:
            self.get_logger().warn("safe_joint_limits empty — 기존 cache 유지")
            return
        self._safe_limits = updated
        self.get_logger().info(
            f"safe_joint_limits 갱신 — {len(updated)} joints (margin "
            f"{SAFETY_MARGIN_RAD:.3f} rad 추가 적용)",
        )
        # 첫 갱신 시 self-collision pre-validation 발사 — move_group 이 안정 될 시간
        # 주려고 2s delay one-shot timer.
        if not self._validation_kicked:
            self._validation_kicked = True
            self._validation_timer = self.create_timer(
                2.0, self._kick_pose_validation,
            )

    def _kick_pose_validation(self) -> None:
        """one-shot — _validate_poses_against_moveit 호출 후 timer cancel."""
        self._validation_timer.cancel()
        self._validate_poses_against_moveit()

    def _validate_poses_against_moveit(self) -> None:
        """MoveIt /check_state_validity 로 HIGH/TAP/PULL 의 self-collision 사전검사.

        9 configurations 검사 (right HIGH/TAP/PULL, left HIGH/TAP/PULL, bimanual
        HIGH/TAP/PULL). 결과는 결과 callback 에서 비동기로 log — 한 번 검사 후 runtime
        에 추가 call 없어 gesture latency 영향 0.
        """
        if not self._validity_cli.wait_for_service(timeout_sec=5.0):
            self.get_logger().warn(
                "/check_state_validity 서비스 없음 — move_group 안 떴거나 ROS_DOMAIN "
                "다름. self-collision validation skip (runtime safety lock 은 정상 동작).",
            )
            return
        home = [0.0] * len(OPENARM_JOINT_NAMES)
        # (label, group_name, full_position_vector) 리스트.
        configs: list[tuple[str, str, list[float]]] = []
        for arm, arm_label, pose_set in [
            (RIGHT_ARM, "right", [
                ("HIGH", HIGH_POSE_RIGHT), ("TAP", TAP_POSE_RIGHT), ("PULL", PULL_POSE_RIGHT),
            ]),
            (LEFT_ARM, "left", [
                ("HIGH", HIGH_POSE_LEFT), ("TAP", TAP_POSE_LEFT), ("PULL", PULL_POSE_LEFT),
            ]),
        ]:
            for phase, arm_pose in pose_set:
                full = list(home)
                for jn, v in zip(arm.joint_names, arm_pose):
                    full[OPENARM_JOINT_NAMES.index(jn)] = float(v)
                configs.append((f"{arm_label}.{phase}", arm.group, full))
        # Bimanual — 양팔 동시 HIGH/TAP/PULL. self-collision 가능성 가장 높은 케이스.
        for phase, r_pose, l_pose in [
            ("HIGH", HIGH_POSE_RIGHT, HIGH_POSE_LEFT),
            ("TAP", TAP_POSE_RIGHT, TAP_POSE_LEFT),
            ("PULL", PULL_POSE_RIGHT, PULL_POSE_LEFT),
        ]:
            full = list(home)
            for jn, v in zip(RIGHT_ARM.joint_names, r_pose):
                full[OPENARM_JOINT_NAMES.index(jn)] = float(v)
            for jn, v in zip(LEFT_ARM.joint_names, l_pose):
                full[OPENARM_JOINT_NAMES.index(jn)] = float(v)
            configs.append((f"bimanual.{phase}", RIGHT_ARM.group, full))

        self.get_logger().info(
            f"MoveIt self-collision validation 시작 ({len(configs)} configs)...",
        )
        for label, group, positions in configs:
            req = GetStateValidity.Request()
            req.robot_state = RobotState()
            req.robot_state.joint_state = JointState()
            req.robot_state.joint_state.name = list(OPENARM_JOINT_NAMES)
            req.robot_state.joint_state.position = positions
            req.group_name = group
            future = self._validity_cli.call_async(req)
            future.add_done_callback(
                lambda f, lbl=label: self._on_validation_response(f, lbl),
            )

    def _on_validation_response(self, future, label: str) -> None:
        """validation 결과 log. invalid pose 는 어떤 link pair 가 부딪히는지도 함께."""
        try:
            result = future.result()
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(f"{label} validation error: {exc}")
            return
        if result is None:
            self.get_logger().warn(f"{label} validation: response 없음")
            return
        if result.valid:
            self.get_logger().info(f"  ✓ {label} — self-collision none")
            return
        # contacts list 가 있으면 충돌 link 쌍 인쇄.
        contact_pairs = []
        for c in getattr(result, "contacts", [])[:3]:
            contact_pairs.append(f"{c.contact_body_1}↔{c.contact_body_2}")
        msg = ", ".join(contact_pairs) if contact_pairs else "(no contact detail)"
        self.get_logger().warn(
            f"  ⚠ {label} — SELF-COLLISION: {msg} — pose 조정 필요!",
        )

    def _clamp_to_safe(self, positions: list[float]) -> Optional[list[float]]:
        """Trajectory waypoint 의 각 joint position 을 safe range + margin 으로 clamp.

        OPENARM_JOINT_NAMES 순서 기준 — gesture 가 만드는 trajectory 와 동일 순서.
        Admin broadcast 가 아직 도착 안 했으면 None 반환 — 호출자가 gesture skip.
        등록 안 된 joint (예: finger) 는 그대로 통과 (mujoco_twin 에서 항상 0 강제).
        """
        if self._safe_limits is None:
            return None
        out: list[float] = []
        for jn, v in zip(OPENARM_JOINT_NAMES, positions):
            limits = self._safe_limits.get(jn)
            if limits is None:
                out.append(v)
                continue
            lo, hi = limits
            lo += SAFETY_MARGIN_RAD
            hi -= SAFETY_MARGIN_RAD
            if lo > hi:  # margin 보다 좁은 admin 설정 — degenerate, 그대로 통과
                out.append(v)
                continue
            out.append(max(lo, min(hi, v)))
        return out

    def _publish_abort_to_home(self, arm: _ArmConfig, now_s: float) -> None:
        """Safe abort — current → home (zeros) 부드럽게 1.4s smoothstep.

        예전엔 0.5s slam 으로 child 근처에서 갑자기 팔이 떨어져 위험했음. 1.4s
        smoothstep 으로 늘려 안전성 확보."""
        if self._last_joint_state is None:
            return
        name_to_pos = dict(zip(
            self._last_joint_state.name, self._last_joint_state.position,
        ))
        current_full = [float(name_to_pos.get(jn, 0.0)) for jn in OPENARM_JOINT_NAMES]
        home_full = list(current_full)
        for jn in arm.joint_names:
            home_full[OPENARM_JOINT_NAMES.index(jn)] = 0.0
        traj = JointTrajectory()
        traj.joint_names = list(OPENARM_JOINT_NAMES)
        traj.header.stamp = self.get_clock().now().to_msg()
        # 부드러운 abort — 1.4s + smoothstep. 갑작스러운 motion 으로 child 놀라게
        # 하거나 모터 충격 주지 않음.
        abort_dur_s = 1.4
        # Abort 도 safe_limits 없으면 publish 못 함 — fail-stop. 단 home 복귀는 거의
        # 항상 안전한 자세라 fallback 으로 clamp 없이 publish (safety > completeness).
        for i in range(1, TRAJECTORY_WAYPOINTS + 1):
            t_norm = i / TRAJECTORY_WAYPOINTS
            s = 10 * t_norm**3 - 15 * t_norm**4 + 6 * t_norm**5
            t = t_norm * abort_dur_s
            raw_positions = [c + (g - c) * s for c, g in zip(current_full, home_full)]
            clamped = self._clamp_to_safe(raw_positions)
            pt = JointTrajectoryPoint()
            pt.positions = clamped if clamped is not None else raw_positions
            pt.time_from_start = DurationMsg(
                sec=int(t), nanosec=int((t % 1) * 1e9),
            )
            traj.points.append(pt)
        self._traj_pub.publish(traj)
        # Reset busy window so next gesture can fire after abort + brief hold.
        self._gesture_busy_until_s[arm.group] = now_s + abort_dur_s + 0.5

    def _publish_status(self) -> None:
        """5Hz status broadcast — browser UI overlay polls / WS streams 이걸 받음.
        Static gate / dynamic-close / rerouting / gesture-active 상태를 JSON 으로."""
        now_s = self.get_clock().now().nanoseconds * 1e-9
        active_arms = [
            g for g in (LEFT_ARM_GROUP, RIGHT_ARM_GROUP)
            if now_s < self._gesture_busy_until_s[g]
        ]
        aborted_arms = [
            g for g in (LEFT_ARM_GROUP, RIGHT_ARM_GROUP)
            if self._abort_triggered[g]
        ]
        static = self._obstacle_pixel_count > OBSTACLE_PIXEL_THRESH
        dyn_close = self._dyn_closest_m < DCP_RED_ZONE_M
        if static or dyn_close or aborted_arms:
            level = "danger"
        elif self._dyn_closest_m < DCP_LENGTH_M:
            level = "warn"
        else:
            level = "ok"
        status = {
            "ts": now_s,
            "level": level,
            "static_obstacle": static,
            "static_px": int(self._obstacle_pixel_count),
            "dyn_closest_m": float(self._dyn_closest_m if
                                   self._dyn_closest_m != float("inf") else -1),
            "dyn_x_norm": float(self._dyn_x_norm),
            "active_arms": active_arms,
            "aborted_arms": aborted_arms,
        }
        msg = String()
        msg.data = json.dumps(status)
        self._status_pub.publish(msg)

    def _on_depth_obstacle(self, msg: Image) -> None:
        """Depth frame 처리 — 두 가지 신호 갱신:
          (1) static OBSTACLE_NEAR_M 이내 픽셀 수 (binary gate 용).
          (2) DCP-RMP dynamic obstacle: 이전 frame 과 diff → depth 가 크게 변한
              픽셀 (8cm+) = moving point. 그중 카메라에서 가장 가까운 거리 cache."""
        if msg.encoding != "16UC1":
            return
        depth_mm = np.frombuffer(msg.data, dtype=np.uint16).reshape(
            msg.height, msg.width,
        ).astype(np.float32)
        thresh_mm = int(OBSTACLE_NEAR_M * 1000)
        # (1) Static close count.
        close_mask = (depth_mm > 50) & (depth_mm < thresh_mm)
        self._obstacle_pixel_count = int(close_mask.sum())
        # (2) Dynamic detection — frame-to-frame diff.
        # 사용자 손 visible 중에는 hand_depth 보다 HAND_FRONT_MARGIN_M 이상 앞쪽
        # 픽셀만 obstacle 로 인정 (손/팔 자체 배제). hand 안 보이면 모든 dynamic 인정.
        now_s = self.get_clock().now().nanoseconds * 1e-9
        hand_recent = (now_s - self._last_hand_seen_at_s) < HAND_GRACE_S
        # 첫 frame 이거나 해상도 바뀐 경우엔 dyn 상태 reset — stale 한 값 들고 다니지 않게.
        if (self._prev_depth_mm is None
                or self._prev_depth_mm.shape != depth_mm.shape):
            self._dyn_closest_m = float("inf")
            self._dyn_x_norm = 0.0
        if (self._prev_depth_mm is not None
                and self._prev_depth_mm.shape == depth_mm.shape):
            both_valid = (depth_mm > 50) & (self._prev_depth_mm > 50)
            change = np.abs(depth_mm - self._prev_depth_mm)
            dyn_mask = both_valid & (change > DCP_DEPTH_CHANGE_MM)
            if hand_recent:
                # 손보다 앞쪽 (가까운) 픽셀만 — 손/팔은 자동 배제.
                front_thresh_mm = (self._last_hand_depth_m
                                   - HAND_FRONT_MARGIN_M) * 1000.0
                dyn_mask = dyn_mask & (depth_mm < front_thresh_mm)
            if dyn_mask.any():
                closest_m = float(depth_mm[dyn_mask].min()) / 1000.0
                # Expected-contact filter — closest dynamic 가 손 깊이 ±5cm 안이면
                # 그건 사용자의 손/팔이 직접 닿은 결과지 새로운 위험이 아님.
                # HAND_FRONT_MARGIN 보다 더 좁은 band 라 손등이 마침 더 가까운 경우만
                # 잡힘. abort 면제 → TAP/PULL 의 자연스러운 follow-through 보존.
                if (hand_recent and
                        abs(closest_m - self._last_hand_depth_m)
                        < EXPECTED_CONTACT_BAND_M):
                    self._dyn_closest_m = float("inf")
                    self._dyn_x_norm = 0.0
                else:
                    self._dyn_closest_m = closest_m
                    cols = np.where(dyn_mask.any(axis=0))[0]
                    if cols.size > 0:
                        cx = float(cols.mean())
                        w = depth_mm.shape[1]
                        self._dyn_x_norm = (cx - w * 0.5) / (w * 0.5)
            else:
                self._dyn_closest_m = float("inf")
                self._dyn_x_norm = 0.0
        self._prev_depth_mm = depth_mm

    def _publish_scripted_gesture(self, arm: _ArmConfig, now_s: float,
                                  amplitude_scale: float = 1.0,
                                  reroute_j1_rad: float = 0.0,
                                  track_j2_rad: float = 0.0,
                                  track_j4_rad: float = 0.0,
                                  ik_tap_arm_pose: Optional[list[float]] = None,
                                  ik_rebound_arm_pose: Optional[list[float]] = None,
                                  ) -> None:
        """One-shot home → HIGH → TAP → PULL → home trajectory.

        amplitude_scale (DCP-RMP): 0.3~1.0 — HIGH/TAP/PULL pose 의 home 편차 축소.
        reroute_j1_rad: j1 (shoulder yaw) offset — DCP reroute + (fallback path 의)
            lateral 손위치 heuristic.
        track_j2_rad / track_j4_rad: graceful IK-fallback 의 j2 / j4 offset. IK 가
            성공해 ik_tap_arm_pose 가 제공되면 무시됨.
        ik_tap_arm_pose: IK 가 계산한 arm joints — TAP target 으로 직접 사용.
        모든 결과는 _clamp_to_safe waypoint level 에서 admin safe range 로 clamp."""
        # Closed-loop 끝 (publish 든 early-return 이든) — in-flight guard 해제.
        self._cl_in_progress[arm.group] = False
        if self._last_joint_state is None:
            self.get_logger().warn("joint_states 아직 수신 안 됨 — gesture skip",
                                   throttle_duration_sec=2.0)
            return
        if self._safe_limits is None:
            # safe_joint_limits broadcast 아직 못 받음 → unsafe 발사 거부 (fail-stop).
            # TRANSIENT_LOCAL 이라 거의 즉시 도착해야 정상. 지속되면 control_service
            # 의 _safe_limits_pub 가 startup 시 _republish_safe_limits 안 한 거.
            self.get_logger().warn(
                "safe_joint_limits 아직 수신 못 함 — gesture 발사 거부 (admin UI 또는 "
                "control_service 가 살아있는지 확인)",
                throttle_duration_sec=2.0,
            )
            return
        name_to_pos = dict(zip(
            self._last_joint_state.name, self._last_joint_state.position,
        ))
        current_full = [float(name_to_pos.get(jn, 0.0)) for jn in OPENARM_JOINT_NAMES]
        def _scaled_and_deflected(pose: list[float]) -> list[float]:
            # Amplitude scaling + per-joint offsets.
            # j1 은 _J1_SAFE_LIMIT 으로 직접 clamp. j2 / j4 의 최종 safety 는
            # _clamp_to_safe (waypoint level) 에서 처리.
            out = [v * amplitude_scale for v in pose]
            out[0] = max(-_J1_SAFE_LIMIT,
                         min(_J1_SAFE_LIMIT, out[0] + reroute_j1_rad))
            out[1] += track_j2_rad   # shoulder pitch (vertical)
            out[3] += track_j4_rad   # elbow flex (depth)
            return out
        if ik_tap_arm_pose is not None:
            # TAP = IK 해 (gripper 가 hand 위/at 에서 contact).
            tap_arm = list(ik_tap_arm_pose)
        else:
            tap_arm = _scaled_and_deflected(
                TAP_POSE_LEFT if arm is LEFT_ARM else TAP_POSE_RIGHT)
        home_arm = [0.0] * len(arm.joint_names)
        def _arm_to_full(arm_pose: list[float]) -> list[float]:
            full = list(current_full)
            for jn, v in zip(arm.joint_names, arm_pose):
                full[OPENARM_JOINT_NAMES.index(jn)] = float(v)
            return full
        home_full = _arm_to_full(home_arm)
        tap_full = _arm_to_full(tap_arm)
        # Rebound pose — 손에서 "튕겨 빠지는" recoil.
        #  - ik_rebound_arm_pose 제공 (closed-loop path): IK 가 tap 을 shoulder 쪽으로
        #    REBOUND_BACK_M 당긴 점 (같은 height) 으로 푼 해. gripper 가 손에서 BACK
        #    으로 물러남 (height 유지 → tablet 안전, 옆에서 또렷이 보이는 retreat).
        #  - 미제공 (heuristic fallback): tap→home lerp (back+down). IK 없을 때만.
        if ik_rebound_arm_pose is not None:
            rebound_arm = list(ik_rebound_arm_pose)
        else:
            rebound_arm = [t + (h - t) * REBOUND_FRAC
                           for t, h in zip(tap_arm, home_arm)]
        rebound_full = _arm_to_full(rebound_arm)
        # raise → (stop at rebound area) → tap → rebound → return — 사용자 이상형.
        #   1) raise:   home → rebound_area. 천천히 들어 ready 자세 (tap 보다 BACK+DOWN).
        #      끝에서 RAISE_HOLD_S 멈춤 ("stop at rebound area").
        #   2) tap:     rebound_area → tap. 손으로 부드럽게 jab (forward+up), 끝에서
        #      PRESS_HOLD_S 머물러 gentle press contact.
        #   3) rebound: tap → rebound_area. raise 가 섰던 그 자리로 부드럽게 튕겨 돌아옴
        #      (REBOUND_DURATION_S 느리게 = gentle, 무리 안 감) + REBOUND_HOLD_S 멈춤.
        #   4) return:  rebound_area → home. 차분히 내려옴.
        # rebound_area (rebound_full) 가 raise·recoil 공통 waypoint — recoil 이 "왔던
        # 자리로 복귀"라 과하지 않고 또렷. 전 phase quintic (smooth), windup pose 안 써
        # scripted-vs-IK mismatch contort 없음.
        # Tracking: raise duration = tracking deadline 까지 남은 시간. re-aim 으로 현재
        # 자세에서 재 publish 해도 raise 가 항상 같은 절대시각 (fire + TRACK_WINDOW_S) 에
        # 끝나 progress 가 보존된다 (매번 3s 처음부터 다시 올라가지 않음). closed-loop 이
        # ~1s 걸리므로 fresh fire 도 자연히 ~2s 로 단축됨. 하한 TRACK_MIN_RAISE_S.
        raise_dur = PRESENT_DURATION_S
        deadline = self._track_deadline_s.get(arm.group, 0.0)
        if deadline > 0.0:
            now_pub_s = self.get_clock().now().nanoseconds * 1e-9
            raise_dur = max(
                min(deadline - now_pub_s, PRESENT_DURATION_S), TRACK_MIN_RAISE_S,
            )
        phases = [
            (current_full,  rebound_full, raise_dur,               RAISE_HOLD_S,   "quintic"),
            (rebound_full,  tap_full,     TAP_FORWARD_DURATION_S,  PRESS_HOLD_S,   "quintic"),
            (tap_full,      rebound_full, REBOUND_DURATION_S,      REBOUND_HOLD_S, "quintic"),
            (rebound_full,  home_full,    WITHDRAW_DURATION_S,     0.0,            "quintic"),
        ]

        def _s_quintic(t: float) -> float:
            return 10 * t**3 - 15 * t**4 + 6 * t**5

        def _sdot_quintic(t: float) -> float:
            # quintic 의 t_norm 미분 (실제 속도 = 이것 / dur). phase 경계 t=0,1 에서 0 →
            # ease-in/out + hold 정지가 자연스럽게 보존된다.
            return 30 * t**2 - 60 * t**3 + 30 * t**4

        curve_fn = {"quintic": _s_quintic}
        curve_dot_fn = {"quintic": _sdot_quintic}
        traj = JointTrajectory()
        traj.joint_names = list(OPENARM_JOINT_NAMES)
        traj.header.stamp = self.get_clock().now().to_msg()
        t_accum = 0.0
        for (p0, p1, dur, hold, curve) in phases:
            s_fn = curve_fn[curve]
            sd_fn = curve_dot_fn[curve]
            for i in range(1, TRAJECTORY_WAYPOINTS + 1):
                t_norm = i / TRAJECTORY_WAYPOINTS
                s = s_fn(t_norm)
                sdot = sd_fn(t_norm) / dur   # joint 별 속도 계수 (1/s)
                t = t_accum + t_norm * dur
                pt = JointTrajectoryPoint()
                # safe_limits 게이트는 함수 진입 시 통과 보장 — clamp 가 None 반환 불가.
                clamped = self._clamp_to_safe(
                    [c + (g - c) * s for c, g in zip(p0, p1)]
                )
                assert clamped is not None
                pt.positions = clamped
                # 속도 프로파일 — 실물 JointTrajectoryController 가 waypoint 마다 감속·정지
                # 했다 가는 stutter (raise 시작 시 떨림/shake) 제거. quintic 해석적 속도 =
                # (Δpose)·sdot. sim (mujoco_twin) 은 velocities 무시(위치 선형보간)라 무영향.
                pt.velocities = [(g - c) * sdot for c, g in zip(p0, p1)]
                pt.time_from_start = DurationMsg(
                    sec=int(t), nanosec=int((t % 1) * 1e9),
                )
                traj.points.append(pt)
            t_accum += dur
            # Hold — endpoint 한 번 더 박아 sim_twin / mujoco_twin 의 EMA 가 그 위치 유지.
            if hold > 0:
                t_accum += hold
                pt = JointTrajectoryPoint()
                clamped_hold = self._clamp_to_safe(list(p1))
                assert clamped_hold is not None
                pt.positions = clamped_hold
                pt.velocities = [0.0] * len(clamped_hold)   # hold = 정지
                pt.time_from_start = DurationMsg(
                    sec=int(t_accum), nanosec=int((t_accum % 1) * 1e9),
                )
                traj.points.append(pt)
        self._traj_pub.publish(traj)
        gesture_total_s = t_accum
        # busy_until 으로 다음 gesture 까지 gate. 이 동안 새 hand_point 무시 (commit).
        self._gesture_busy_until_s[arm.group] = (
            now_s + gesture_total_s + GESTURE_COOLDOWN_S
        )
        self.get_logger().info(
            f"{arm.group} gesture published "
            f"({len(traj.points)} pts, {gesture_total_s:.1f}s + {GESTURE_COOLDOWN_S}s cooldown)",
        )


def main(args=None) -> int:
    rclpy.init(args=args)
    node = HighfiveNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    main()
