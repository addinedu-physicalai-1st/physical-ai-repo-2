#!/usr/bin/env python3
"""MuJoCo physics twin — sim_twin_node 의 drop-in 대체.

Topic contract 는 sim_twin 과 동일:
  sub  /eduping/joint_trajectory  (trajectory_msgs/JointTrajectory)  — 다음 target.
  pub  /joint_states              (sensor_msgs/JointState) @ 50Hz    — 현재 자세.

차이:
  · sim_twin = trajectory waypoint 시간보간으로 qpos 합성 (kinematic).
  · mujoco_twin = position-PD actuator + MuJoCo physics step (inertia·gravity·collision
    포함). 즉 trajectory 가 명령이고 arm 이 dynamics 로 따라간다 — 실물과 행동 동일.

URDF 처리 (startup 1회):
  /robot_description (transient_local QoS) 에서 expanded URDF 받아옴 →
    1) self-closing frame-only link 에 tiny inertia 부여
    2) <mimic> 제거 (MuJoCo URDF parser 미지원, gripper 양쪽 슬라이드는 그냥 독립)
    3) `package://openarm_description` 를 install/share 절대경로로 치환
    4) `.dae` visual 무시 (`discardvisual=true`) — collision STL 만 사용
    5) MjSpec 로 position actuator 18개 추가 (joint 마다 P+D)

Viewer:
  `viewer_enabled` 파라미터 (default true) — true 면 mujoco.viewer.launch_passive
  로 별도 GLFW 창을 띄움. 사용자 노트북에서 sim_twin 의 UI 없는 텍스트보다 직관적.

Thread layout:
  · main: rclpy.spin → 콜백 처리 (trajectory 수신, joint_states publish).
  · physics worker: 500Hz mj_step 루프. Lock 으로 ctrl 배열 보호.
  · viewer (있으면): launch_passive 의 백그라운드 스레드.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Optional

import mujoco
import mujoco.viewer
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import (
    QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy,
)
from geometry_msgs.msg import PointStamped
from sensor_msgs.msg import CameraInfo, Image, JointState
from std_msgs.msg import String
from trajectory_msgs.msg import JointTrajectory


MESH_SHARE_ROOT = (
    "/home/joey/Desktop/physical-ai-repo-2/physical-ai-repo-2/"
    "controller/eduping-controller/install/openarm_description/share/openarm_description"
)
# URDF effort limits (N·m). actuator forcerange = ±이 값. impedance controller 가
# 실 모터 한계 넘는 토크 못 보내게 — sim2real 안전성.
JOINT_EFFORT = {
    "joint1": 40.0, "joint2": 40.0, "joint3": 27.0,
    "joint4": 27.0, "joint5": 7.0, "joint6": 7.0, "joint7": 7.0,
    "finger": 333.0,
}
# MuJoCo internal position-PD (2026-05-27 마지막): Cartesian impedance 시도 →
# op-space inertia 보정 없이는 7DOF redundancy + Coriolis 결합으로 진동.
# 안정 우선해서 motor (torque mode) → position 으로 복귀.
# Per-joint Kp 는 큰 joint (shoulder) 일수록 ↑, wrist 일수록 ↓.
ARM_KP = {
    "joint1": 300.0, "joint2": 600.0, "joint3": 200.0,
    "joint4": 200.0, "joint5": 80.0, "joint6": 50.0, "joint7": 50.0,
}
ARM_KD_RATIO = 0.40  # 0.25 → 0.40: 약간 overdamped — TAP→PULL 같은 빠른 방향 전환
                     # 에서 PD ringing 줄이고 인간-스러운 settling.
# Compliance drop — present-and-press 의 접촉 직후에만 arm kp 를 낮춰 "give in".
# 핵심: window 가 approach 동안 (예전 35~55%) 켜져 있으면 arm 이 reach 하는 내내
# 물러서 (soft) gravity 로 ~10cm 처져 (droop) gripper 가 사람 손 아래로 갔다.
# present-and-press 는 반대로 — approach 는 STIFF (정확히 hand 까지 도달), 접촉
# 순간/직후에만 SOFT (사람 손을 안 밀도록 give in). 그래서 window 를 contact
# 시점 (tap phase 끝) 에 맞춤. 0.65 = 약한 give-in.
COMPLIANCE_KP_SCALE = 0.65
# 전체 trajectory 의 fractional 시간 범위 [start, end]. motion = raise(0~41%) →
# raise_hold(~46%) → tap(~56%) → press_hold(~62%) → rebound → return (총 8.2s).
# contact (tap 끝 ~ press_hold) 는 ~51~57% → 그 구간을 SOFT 로. 0.51~0.58 로 갱신
# (예전 0.54~0.62 는 3-phase 7.0s 기준이라 새 timing 과 어긋남).
COMPLIANCE_FRAC_START = 0.51
COMPLIANCE_FRAC_END = 0.58
FINGER_KP = 50.0
FINGER_KD_RATIO = 0.3
# Target EMA filter — across-trajectory IK jump (특히 joint5 — TRAC-IK home seed
# 기준이라 across-call 불연속) 부드럽게 흡수.
TARGET_EMA_ALPHA = 0.15   # 0.05 → 0.15: target 을 빠르게 따라가서 trajectory 의
                          # 일정 속도 (smoothstep) 가 실제로 그대로 보이게 — 예전엔
                          # 너무 느린 EMA 가 "느렸다 빨랐다" 처럼 느껴졌음.
# Trajectory 만료 — 새 POST 가 2s 동안 안 오면 active 비움 + EMA 보존 (마지막 target
# 유지 → joint 들이 그 자세 hold).
TRAJ_TIMEOUT_S = 2.0

PHYS_HZ = 500.0
PUB_HZ = 50.0

# High-five hand-accept zone (browser 의 green wireframe box) — depth 카메라 광학
# 프레임에서 Z=0.35~0.55m 사이가 hand-target 발사 영역. MuJoCo viewer 에 동일한
# 박스를 world frame 으로 그려서 "어디 손 둬야 하는지" 시각화.
# Green box depth range (2026-05-28 v3): viewer 에서 gripper 가 box 앞면에서 멈춰
# user reach 못 닿는 것 확인 → box 를 gripper 쪽으로 당김 (40~60cm). 어깨 ≤ stretched
# pose 의 실제 EE world depth 와 매칭 (대략 45cm). TODO(향후): MuJoCo FK 로 TAP pose
# gripper world Z 를 계산해 자동 align.
HIGHFIVE_NEAR_M = 0.28
HIGHFIVE_FAR_M = 0.42
# Depth → voxel rendering. user_scn 에 BOX geom 으로 표시 (사용자 위치 확인용).
VOXEL_SIZE_M = 0.04
VOXEL_NEAR_M = 0.25
VOXEL_FAR_M = 1.5
VOXEL_PIXEL_STRIDE = 16
VOXEL_MAX_COUNT = 600
# Hand-point sphere (debug visualization) — /eduping/highfive/hand_point 의 world
# 좌표에 빨간 구를 그려 "시스템이 인식한 손 위치" 표시. detection / unproject /
# IK reach 문제 빠르게 diagnose 용. HAND_POINT_TTL_S 안에 새 point 안 오면 사라짐.
HAND_POINT_SPHERE_R_M = 0.04
HAND_POINT_TTL_S = 12.0   # 전체 high-five cycle (10.05s + cooldown + margin) 동안
                          # red ball 유지 — 단발 trigger (test script, one-shot API)
                          # 에서도 TAP 시점에 red ball 이 보임. 브라우저가 33Hz heartbeat
                          # 으로 계속 publish 하는 정상 사용에선 TTL 길어도 무해 (계속
                          # refresh).
# Gripper PALM (blue) sphere — hand body local -X (broad slap/palm face) + 작은 +Z
# (finger 방향). highfive_node.GRIPPER_BLUE_LOCAL_OFFSET 와 반드시 동일 (closed-loop
# 이 이 점을 red=사람 손바닥 에 수렴시켜 palm-to-palm). 양팔 render 는 각 arm 의
# link_mat (hand frame→world) 로 offset 회전 → 팔마다 다른 world orientation 자동 반영.
GRIPPER_CONTACT_SPHERE_R_M = 0.04
GRIPPER_CONTACT_LOCAL_OFFSET = np.array([-0.04, 0.0, 0.02], dtype=np.float64)
# d435_depth_optical_frame → world transform 은 URDF 가 single source of truth.
# 예전엔 hardcoded R/T 로 박아 URDF mount (d435_mount_xyz, d435_mount_rpy) 가 바뀔
# 때마다 MuJoCo 의 depth voxels / hand-sphere 가 browser 와 어긋났다. 모델 로드 시
# mj_forward 한 번 호출 → d435_depth_optical_frame body 의 xpos / xmat 를 캐시.
# fixed joint chain 이라 시뮬레이션 도중 변하지 않음.
D435_OPTICAL_BODY = "d435_color_optical_frame"



def _process_urdf_to_mjcf(urdf_text: str) -> str:
    """URDF → actuator 가 추가된 MJCF text."""
    src = re.sub(
        r'<link name="([^"]+)"\s*/>',
        r'<link name="\1"><inertial><mass value="1e-6"/>'
        r'<inertia ixx="1e-9" ixy="0" ixz="0" iyy="1e-9" iyz="0" izz="1e-9"/>'
        r'</inertial></link>',
        urdf_text,
    )
    src = re.sub(r"<mimic[^/]*/>", "", src)
    src = src.replace("package://openarm_description", MESH_SHARE_ROOT)
    src = src.replace(
        '<robot name="openarm">',
        '<robot name="openarm"><mujoco>'
        '<compiler balanceinertia="true" discardvisual="true" '
        'strippath="false" fusestatic="false"/>'
        "</mujoco>",
    )
    spec = mujoco.MjSpec.from_string(src)
    # MuJoCo URDF parser 가 finger 메쉬 dedup 실수 — 4개 finger link (좌/우 arm
    # × 좌/우 finger) 가 같은 finger.stl 을 ±Y scale 로 referencing. parser 가
    # 첫 2개 (left arm) 에선 finger / finger1 두 mesh 를 만들지만 right_right_
    # finger 에 다시 finger (mirror 없음) 를 잘못 할당. 결과: right gripper 의
    # mirrored finger 가 같은 쪽에 겹쳐 보임. MjSpec 으로 명시적 재할당.
    rrf = spec.body("openarm_right_right_finger")
    if rrf is not None:
        for g in rrf.geoms:
            if g.meshname == "finger":
                g.meshname = "finger1"
    # Mimic 대체 — URDF 의 <mimic joint=finger_joint1/> 가 MuJoCo URDF parser 에서
    # 무시돼서 mujoco_twin 에선 finger1 / finger2 가 독립적으로 움직였음. MJCF
    # equality constraint 로 다시 묶음: joint2 qpos = joint1 qpos (identity polycoef).
    for arm in ("left", "right"):
        eq = spec.add_equality()
        eq.type = mujoco.mjtEq.mjEQ_JOINT
        eq.name1 = f"openarm_{arm}_finger_joint1"
        eq.name2 = f"openarm_{arm}_finger_joint2"
        # polycoef [a0..a4]: qpos2 = a0 + a1·qpos1 + a2·qpos1² + … — identity = a1=1.
        eq.data[0] = 0.0
        eq.data[1] = 1.0
        eq.data[2] = 0.0
        eq.data[3] = 0.0
        eq.data[4] = 0.0
    for jnt in spec.joints:
        if jnt.type not in (mujoco.mjtJoint.mjJNT_HINGE, mujoco.mjtJoint.mjJNT_SLIDE):
            continue
        is_finger = "finger" in jnt.name
        if is_finger:
            kp = FINGER_KP
            kd_ratio = FINGER_KD_RATIO
            effort = JOINT_EFFORT["finger"]
        else:
            # Per-joint Kp + Kd ratio — 큰 어깨 (joint2) 일수록 stiff, wrist 작게.
            # MuJoCo internal PD 라 outside controller 없이 안정. effort limit 으로
            # 슬램 방지. Cartesian impedance 는 op-space inertia 보정 미구현 동안 보류.
            kp = ARM_KP.get(
                next((s for s in ARM_KP if s in jnt.name), "joint7"), 100.0,
            )
            kd_ratio = ARM_KD_RATIO
            effort = JOINT_EFFORT.get(
                next((s for s in JOINT_EFFORT if s in jnt.name), "joint7"), 20.0,
            )
        act = spec.add_actuator()
        act.name = jnt.name
        act.target = jnt.name
        act.trntype = mujoco.mjtTrn.mjTRN_JOINT
        act.gaintype = mujoco.mjtGain.mjGAIN_FIXED
        act.gainprm[0] = kp
        act.biastype = mujoco.mjtBias.mjBIAS_AFFINE
        act.biasprm[0] = 0.0
        act.biasprm[1] = -kp
        act.biasprm[2] = -kp * kd_ratio
        act.forcelimited = mujoco.mjtLimited.mjLIMITED_TRUE
        act.forcerange[0] = -effort
        act.forcerange[1] = effort
    spec.compile()  # validates
    return spec.to_xml()


class MujocoTwinNode(Node):
    def __init__(self) -> None:
        super().__init__("sim_twin_node")  # 같은 이름 → 기존 토픽 contract 호환
        # Viewer 는 main thread 에서 띄움 (GLFW+Wayland 요구사항). main() 가
        # ros executor 를 background thread 로 돌리고 본인 thread 에 viewer 점유.
        self.declare_parameter("viewer_enabled", True)
        self._viewer_enabled = self.get_parameter(
            "viewer_enabled").get_parameter_value().bool_value

        self._model: Optional[mujoco.MjModel] = None
        self._data: Optional[mujoco.MjData] = None
        self._joint_names: list[str] = []
        # actuator_id_by_joint_name — control 배열 인덱싱.
        self._act_idx: dict[str, int] = {}
        self._ctrl_lock = threading.Lock()
        self._physics_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        # Active trajectory — physics loop 가 매 step 마다 elapsed time 으로 보간.
        # last-waypoint-only target 을 ctrl 에 박으면 step input → PD 가 max force
        # 로 슬램 → ringing. 시간 기반 보간으로 quintic 그대로 따라가야 함.
        # (start_mono, waypoints) 여기서 waypoints = [(t_from_start_s, {jn: pos})].
        self._traj_lock = threading.Lock()
        self._active_traj: Optional[tuple[float, list[tuple[float, dict[str, float]]]]] = None
        # Target EMA — across-trajectory jumps (특히 joint5 IK discontinuity) 를
        # 부드럽게 흡수. 매 physics step 마다 _sample_target_qpos 안에서 갱신.
        self._target_ema: dict[str, float] = {}

        # /robot_description 가 transient_local 로 latch 돼있어 늦게 join 해도 받을 수 있음.
        rd_qos = QoSProfile(
            depth=1,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._rd_sub = self.create_subscription(
            String, "/robot_description", self._on_robot_description, rd_qos,
        )
        self._traj_sub = self.create_subscription(
            JointTrajectory, "/eduping/joint_trajectory",
            self._on_traj, 10,
        )
        self._js_pub = self.create_publisher(JointState, "/joint_states", 10)
        # Publish loop runs on a timer at PUB_HZ — 콜백은 main spin 안에서 호출.
        self._pub_timer = self.create_timer(1.0 / PUB_HZ, self._publish_joint_state)
        # CameraInfo subscription — depth 카메라 intrinsics 받아서 hand-accept
        # 박스의 X/Y 크기 (FOV 기반) 계산.
        info_qos = QoSProfile(
            depth=2,
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            history=QoSHistoryPolicy.KEEP_LAST,
        )
        # Aligned-depth (color intrinsics 적용) 사용 — browser DepthViewer 가 받는
        # depth 스트림과 동일한 unproject 결과를 얻기 위해. 예전엔 /d435/depth/*
        # (depth lens, fx≈384, 넓은 FOV) 였는데 browser 의 aligned 스트림 (color lens,
        # fx≈605, 좁은 FOV) 과 달라 같은 손도 위치/크기가 어긋났다.
        self._cam_info_sub = self.create_subscription(
            CameraInfo, "/d435/aligned_depth_to_color/camera_info",
            self._on_camera_info, info_qos,
        )
        self._depth_sub = self.create_subscription(
            Image, "/d435/aligned_depth_to_color/image_raw",
            self._on_depth, info_qos,
        )
        self._cam_intr: Optional[tuple[float, float, float, float]] = None
        self._voxels_lock = threading.Lock()
        self._voxels_world: np.ndarray = np.zeros((0, 3), dtype=np.float32)
        # Hand-point debug visualization — highfive_node 가 publish 하는 손 위치를
        # 빨간 sphere 로 viewer 에 표시. detection / unproject 가 어디로 hand 를
        # 잡았는지 한 눈에 확인.
        self._hand_sub = self.create_subscription(
            PointStamped, "/eduping/highfive/hand_point",
            self._on_hand_point, 10,
        )
        self._hand_world: Optional[np.ndarray] = None
        self._hand_seen_at_mono_s: float = 0.0
        # robot_description 도착 전 콜백 보호용 identity defaults. 도착 시
        # _on_robot_description 가 URDF FK 값으로 덮어씀.
        self._depth_opt_to_world_R: np.ndarray = np.eye(3, dtype=np.float64)
        self._depth_opt_to_world_T: np.ndarray = np.zeros(3, dtype=np.float64)
        self.get_logger().info(
            "mujoco_twin_node ready — waiting for /robot_description …",
        )

    def _on_robot_description(self, msg: String) -> None:
        if self._model is not None:
            return  # 이미 load 됐으면 무시
        try:
            mjcf = _process_urdf_to_mjcf(msg.data)
            model = mujoco.MjModel.from_xml_string(mjcf)
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f"URDF → MJCF 실패: {exc}")
            return
        data = mujoco.MjData(model)
        self._model = model
        self._data = data
        # Joint name → qpos addr mapping + actuator id mapping.
        for j_id in range(model.njnt):
            name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, j_id)
            if name is None:
                continue
            self._joint_names.append(name)
        for a_id in range(model.nu):
            name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_ACTUATOR, a_id)
            if name is not None:
                self._act_idx[name] = a_id
        # Cache base actuator gains so compliance scaling can multiply against them
        # without losing the original tuning. Only arm joints (not fingers) get
        # compliance — fingers stay rigid for stable grasping.
        self._base_gain_kp = np.zeros(model.nu, dtype=np.float64)
        self._base_bias_p = np.zeros(model.nu, dtype=np.float64)
        self._base_bias_d = np.zeros(model.nu, dtype=np.float64)
        self._arm_actuator_ids: list[int] = []
        for a_id in range(model.nu):
            self._base_gain_kp[a_id] = model.actuator_gainprm[a_id, 0]
            self._base_bias_p[a_id] = model.actuator_biasprm[a_id, 1]
            self._base_bias_d[a_id] = model.actuator_biasprm[a_id, 2]
            name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_ACTUATOR, a_id)
            if name is not None and "finger" not in name:
                self._arm_actuator_ids.append(a_id)
        # Numpy array of arm actuator IDs for vectorized gain writes.
        self._arm_actuator_ids_np = np.array(
            self._arm_actuator_ids, dtype=np.int64,
        )
        self._current_kp_scale = 1.0  # tracks last applied compliance scale
        # Pre-computed absolute monotonic times for the compliance window. Set when
        # a new trajectory arrives in _on_traj; checked per-step without holding the
        # trajectory lock. (None = no active compliance window.)
        self._compliance_window_start_s: Optional[float] = None
        self._compliance_window_end_s: Optional[float] = None
        # Gripper hand body IDs for blue contact-sphere rendering. The "*_hand" body
        # sits at j8 — finger root. blue ball offset 으로 j8 와 finger tip 중간 표시.
        # link7 (wrist) 보다 더 진짜 grasping center 에 가깝다. MuJoCo URDF parser
        # 가 fixed-joint body 를 merge 했을 수 있어 fallback 으로 link7 사용.
        self._hand_right_body_id = mujoco.mj_name2id(
            model, mujoco.mjtObj.mjOBJ_BODY, "openarm_right_hand",
        )
        if self._hand_right_body_id < 0:
            self._hand_right_body_id = mujoco.mj_name2id(
                model, mujoco.mjtObj.mjOBJ_BODY, "openarm_right_link7",
            )
        self._hand_left_body_id = mujoco.mj_name2id(
            model, mujoco.mjtObj.mjOBJ_BODY, "openarm_left_hand",
        )
        if self._hand_left_body_id < 0:
            self._hand_left_body_id = mujoco.mj_name2id(
                model, mujoco.mjtObj.mjOBJ_BODY, "openarm_left_link7",
            )
        self.get_logger().info(
            f"Blue contact spheres anchored: right={self._hand_right_body_id} "
            f"left={self._hand_left_body_id} (>=0 means found)",
        )
        self.get_logger().info(
            f"MuJoCo model loaded — {model.nq} dof, {model.nu} actuators, "
            f"{len(self._joint_names)} joints, {len(self._arm_actuator_ids)} arm",
        )
        # d435_depth_optical_frame → world 변환을 URDF FK 로 한 번 계산해서 캐시.
        # 고정 joint chain 이라 sim 도중 변하지 않음. URDF mount 가 바뀌면 자동 반영.
        mujoco.mj_forward(model, data)
        body_id = mujoco.mj_name2id(
            model, mujoco.mjtObj.mjOBJ_BODY, D435_OPTICAL_BODY,
        )
        if body_id < 0:
            self.get_logger().error(
                f"URDF 에 {D435_OPTICAL_BODY} 가 없음 — depth voxels / hand sphere "
                "는 world origin 기준으로 잘못 그려질 수 있음",
            )
            self._depth_opt_to_world_R = np.eye(3, dtype=np.float64)
            self._depth_opt_to_world_T = np.zeros(3, dtype=np.float64)
        else:
            self._depth_opt_to_world_R = data.xmat[body_id].reshape(3, 3).copy()
            self._depth_opt_to_world_T = data.xpos[body_id].copy()
            self.get_logger().info(
                f"{D435_OPTICAL_BODY} world pose: "
                f"T={self._depth_opt_to_world_T.tolist()} "
                f"R[0]={self._depth_opt_to_world_R[0].tolist()}",
            )
        # 초기 ctrl = 0 (home) — qpos 도 0 인 상태에서 시작.
        # 합본 physics+viewer 루프는 main thread (run_loop) 에서 돌림.
        # 별도 physics thread 없음 — viewer 가 background thread 에서 mjData
        # 접근하면 mj_step 과 race → segfault. 단일 스레드 통합이 MuJoCo 권장.

    # _physics_loop 제거 — run_main_loop (main thread) 가 physics+viewer 통합 처리.

    def _sample_target_qpos(self) -> dict[str, float]:
        """Active trajectory 의 elapsed time 보간 → joint_name → target qpos.
        결과에 EMA 적용해서 across-trajectory 점프 흡수. Trajectory 만료 후엔
        EMA 가 마지막 target 유지 (arm 이 그 자세 hold) — 비우면 ctrl=0 으로
        떨어져서 큰 모션 발생."""
        raw = self._sample_target_raw()
        for jn, q in raw.items():
            if jn in self._target_ema:
                self._target_ema[jn] = (
                    self._target_ema[jn]
                    + TARGET_EMA_ALPHA * (q - self._target_ema[jn])
                )
            else:
                self._target_ema[jn] = q
        return dict(self._target_ema)

    def _sample_target_raw(self) -> dict[str, float]:
        with self._traj_lock:
            active = self._active_traj
        if active is None:
            return {}
        start_t, wp = active
        elapsed = time.monotonic() - start_t
        traj_end = wp[-1][0]
        if elapsed > traj_end + TRAJ_TIMEOUT_S:
            with self._traj_lock:
                self._active_traj = None
            return {}
        if elapsed <= wp[0][0]:
            return dict(wp[0][1])
        if elapsed >= traj_end:
            return dict(wp[-1][1])
        for i in range(len(wp) - 1):
            t0, p0 = wp[i]
            t1, p1 = wp[i + 1]
            if t0 <= elapsed <= t1:
                alpha = (elapsed - t0) / max(t1 - t0, 1e-6)
                alpha = max(0.0, min(1.0, alpha))  # clip (non-monotonic 방어)
                return {jn: p0[jn] + alpha * (p1.get(jn, p0[jn]) - p0[jn])
                        for jn in p0}
        return dict(wp[-1][1])

    def _apply_compliance_scaling(self) -> None:
        """Per-physics-step actuator stiffness modulation.

        Uses pre-computed absolute compliance window times (set in _on_traj) so the
        hot path is just two float comparisons — no lock, no division, no acquire of
        active trajectory. Vectorized numpy writes when the scale actually changes.

        Only arm actuators (self._arm_actuator_ids) get modulated; fingers stay
        rigid for stable grasping (matters more for real hardware than sim).
        """
        if not self._arm_actuator_ids:
            return
        target_scale = 1.0
        ws = self._compliance_window_start_s
        we = self._compliance_window_end_s
        if ws is not None and we is not None:
            now_mono = time.monotonic()
            if ws <= now_mono <= we:
                target_scale = COMPLIANCE_KP_SCALE
        if abs(target_scale - self._current_kp_scale) < 1e-6:
            return  # no change → skip writes
        # Vectorized write across all arm actuators.
        arm_ids = self._arm_actuator_ids_np
        self._model.actuator_gainprm[arm_ids, 0] = (
            self._base_gain_kp[arm_ids] * target_scale
        )
        self._model.actuator_biasprm[arm_ids, 1] = (
            self._base_bias_p[arm_ids] * target_scale
        )
        self._model.actuator_biasprm[arm_ids, 2] = (
            self._base_bias_d[arm_ids] * target_scale
        )
        self._current_kp_scale = target_scale

    def _update_ctrl(self) -> None:
        """매 physics step: arm joint 은 trajectory target, finger 는 항상 닫힘.
        MuJoCo 내부 position-PD 가 자동으로 Kp(target - q) - Kd·qd 계산. ctrl 은
        joint range 내로 clamp — 작은 IK 수치 오차로 limit 살짝 넘으면 soft
        constraint 가 oscillate (joint3/joint5 bouncing 의 원인).

        Compliance modulation: TAP/PULL 구간 (impact + recoil) 에서 arm kp 를
        COMPLIANCE_KP_SCALE 로 낮춰 "충돌 시 give in" 효과. HIGH/HOME 은 normal kp."""
        if self._model is None or self._data is None:
            return
        # Apply phase-aware compliance scaling to arm actuators.
        self._apply_compliance_scaling()
        # Finger 은 항상 닫힘 (qpos=0 = closed, axis 가 +qpos → fingers spread).
        # URDF max travel (0.044) 는 OPEN 12cm 벌어진 상태 — 잘못 알았음.
        for jn in (
            "openarm_left_finger_joint1", "openarm_left_finger_joint2",
            "openarm_right_finger_joint1", "openarm_right_finger_joint2",
        ):
            a_id = self._act_idx.get(jn)
            if a_id is not None:
                self._data.ctrl[a_id] = 0.0
        target_qpos_map = self._sample_target_qpos()
        if not target_qpos_map:
            return  # active trajectory 없으면 arm ctrl 유지 (마지막 target hold)
        for jn, q in target_qpos_map.items():
            if "finger" in jn:
                continue  # finger 은 위에서 닫힘 강제됨
            a_id = self._act_idx.get(jn)
            if a_id is None:
                continue
            j_id = mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_JOINT, jn)
            if j_id >= 0 and self._model.jnt_limited[j_id]:
                lo, hi = self._model.jnt_range[j_id]
                # Limit 에서 1° (0.017 rad) 안쪽으로 더 마진 — soft 가 발동 못 함.
                margin = 0.017
                q = max(lo + margin, min(hi - margin, q))
            self._data.ctrl[a_id] = float(q)

    def _render_user_scene(self, viewer) -> None:
        """user_scn 에 두 가지 시각화:
          1. Green 박스 — hand-accept zone (depth Z=0.35~0.55m, browser 의 green
             wireframe 과 동일).
          2. Depth voxels — 카메라가 본 점군을 5cm box 로 표시 (사용자가 자기 위치
             확인용). 매 depth frame 마다 갱신.
        Lock 으로 depth callback 과 race 방지. user_scn.maxgeom 안에서 cap."""
        scn = viewer.user_scn
        n = 0
        # ── 1. Green hand-accept box ─────────────────────────────────────────
        if self._cam_intr is not None and n < scn.maxgeom:
            fx, fy, cx, cy = self._cam_intr
            z_mid = (HIGHFIVE_NEAR_M + HIGHFIVE_FAR_M) * 0.5
            half_x_opt = cx / fx * z_mid
            half_y_opt = cy / fy * z_mid
            half_z_opt = (HIGHFIVE_FAR_M - HIGHFIVE_NEAR_M) * 0.5
            center_opt = np.array([0.0, 0.0, z_mid], dtype=np.float64)
            center_world = self._depth_opt_to_world_R @ center_opt + self._depth_opt_to_world_T
            mujoco.mjv_initGeom(
                scn.geoms[n],
                type=mujoco.mjtGeom.mjGEOM_BOX,
                size=np.array([half_x_opt, half_y_opt, half_z_opt], dtype=np.float64),
                pos=center_world,
                mat=self._depth_opt_to_world_R.flatten(),
                rgba=np.array([0.2, 1.0, 0.2, 0.18], dtype=np.float32),
            )
            n += 1
        # ── 2. Depth voxels (사용자가 자기 위치 보게) ─────────────────────────
        with self._voxels_lock:
            vox = self._voxels_world
        vox_count = min(len(vox), scn.maxgeom - n)
        vox_size = np.full(3, VOXEL_SIZE_M * 0.5, dtype=np.float64)
        vox_mat = np.eye(3, dtype=np.float64).flatten()
        vox_rgba = np.array([0.3, 0.7, 1.0, 0.85], dtype=np.float32)  # bright cyan, more opaque
        for i in range(vox_count):
            mujoco.mjv_initGeom(
                scn.geoms[n + i],
                type=mujoco.mjtGeom.mjGEOM_BOX,
                size=vox_size,
                pos=vox[i].astype(np.float64),
                mat=vox_mat,
                rgba=vox_rgba,
            )
        n += vox_count
        # ── 3. Hand-point sphere (debug — 시스템이 인식한 손 위치) ────────────
        if (self._hand_world is not None and n < scn.maxgeom
                and time.monotonic() - self._hand_seen_at_mono_s < HAND_POINT_TTL_S):
            mujoco.mjv_initGeom(
                scn.geoms[n],
                type=mujoco.mjtGeom.mjGEOM_SPHERE,
                size=np.full(3, HAND_POINT_SPHERE_R_M, dtype=np.float64),
                pos=self._hand_world.astype(np.float64),
                mat=np.eye(3, dtype=np.float64).flatten(),
                rgba=np.array([1.0, 0.2, 0.2, 0.95], dtype=np.float32),
            )
            n += 1
        # ── 4. Gripper contact-center spheres (시각 contact-target — 양팔 *_hand 의
        #    j8 와 finger tip 중간 위치) ─────────────────────────────────────────
        # hand body (j8) 의 world pose 에서 local offset 만큼 앞으로 — finger 중심.
        # blue 와 red 가 겹치면 정확히 손바닥 contact. 양팔 둘 다 그림.
        blue_rgba = np.array([0.2, 0.4, 1.0, 0.95], dtype=np.float32)
        sphere_size = np.full(3, GRIPPER_CONTACT_SPHERE_R_M, dtype=np.float64)
        for body_id in (self._hand_right_body_id, self._hand_left_body_id):
            if body_id < 0 or n >= scn.maxgeom:
                continue
            link_pos = self._data.xpos[body_id]    # (3,) world position
            link_mat = self._data.xmat[body_id].reshape(3, 3)   # rotation
            contact_world = link_pos + link_mat @ GRIPPER_CONTACT_LOCAL_OFFSET
            mujoco.mjv_initGeom(
                scn.geoms[n],
                type=mujoco.mjtGeom.mjGEOM_SPHERE,
                size=sphere_size,
                pos=contact_world,
                mat=np.eye(3, dtype=np.float64).flatten(),
                rgba=blue_rgba,
            )
            n += 1
        scn.ngeom = n

    def run_main_loop(self) -> None:
        """Main-thread loop: physics step + viewer sync 동일 스레드에서 인터리브.
        MuJoCo passive-viewer 권장 패턴 — viewer 의 내부 render 가 mjData 를 별도
        스레드에서 만지지 않게 한다 (이전 segfault 의 근본 원인). ROS spin 은 별도
        background thread 에서 돌고, control input (joint_trajectory) 는 thread-
        safe 한 self._active_traj 를 통해 들어옴."""
        # 모델 로드 대기 — /robot_description 도착해야 모델이 생긴다.
        while self._model is None and not self._stop.is_set():
            time.sleep(0.1)
        if self._model is None or self._data is None:
            return
        dt_phys = 1.0 / PHYS_HZ
        dt_view = 1.0 / 30.0
        self._model.opt.timestep = dt_phys
        # 기본 Euler integrator + 강한 position-PD (kp=200~600) + dt=2ms 는 안정
        # 한계 근처 — ctrl=0 (가만히) 인데도 qpos 가 ±1.5 rad 진동.
        # implicitfast 는 stiff 시스템에 unconditionally stable — Euler 대비 약간
        # 느리지만 진동 사라짐.
        self._model.opt.integrator = mujoco.mjtIntegrator.mjINT_IMPLICITFAST
        # 첫 kinematics — xpos/xmat 가 garbage 인 상태에서 _update_ctrl 가 읽지 않게.
        mujoco.mj_forward(self._model, self._data)
        if self._viewer_enabled:
            try:
                with mujoco.viewer.launch_passive(self._model, self._data) as v:
                    # user_scn.maxgeom defensive guard — MuJoCo 3.8 의 launch_passive
                    # 는 maxgeom=100000 으로 알아서 잡아주지만, 향후 버전/플랫폼에서
                    # 0 으로 떨어지면 user geom (green box + voxels) 가 silently drop
                    # 된다. max() 로 capacity 보장.
                    try:
                        v.user_scn.maxgeom = max(v.user_scn.maxgeom,
                                                 VOXEL_MAX_COUNT + 16)
                    except Exception as exc:  # noqa: BLE001
                        self.get_logger().warn(
                            f"user_scn.maxgeom 설정 실패: {exc} (현재 {v.user_scn.maxgeom})",
                        )
                    self.get_logger().info(
                        f"viewer ready — user_scn.maxgeom={v.user_scn.maxgeom}",
                    )
                    self._run_loop_body(v, dt_phys, dt_view)
            except Exception as exc:  # noqa: BLE001
                self.get_logger().warn(f"viewer 종료: {exc}")
        else:
            self._run_loop_body(None, dt_phys, dt_view)

    def _run_loop_body(self, viewer, dt_phys: float, dt_view: float) -> None:
        next_step = time.monotonic()
        next_sync = time.monotonic()
        while not self._stop.is_set():
            if viewer is not None and not viewer.is_running():
                break
            now = time.monotonic()
            if now >= next_step:
                self._update_ctrl()
                mujoco.mj_step(self._model, self._data)
                next_step += dt_phys
                # falling behind 면 resync.
                if next_step < now:
                    next_step = now + dt_phys
            if viewer is not None and now >= next_sync:
                self._render_user_scene(viewer)
                viewer.sync()
                next_sync += dt_view
                if next_sync < now:
                    next_sync = now + dt_view
            # 다음 physics step / render 까지 sleep. 예전 고정 0.5ms sleep 은 초당 ~2000
            # wake → ROS spin thread (depth voxelize 15Hz, joint publish 50Hz, hand_point)
            # 와 GIL 을 계속 뺏어 render 가 끊기고 CPU 도 낭비됐다. 다음 이벤트까지 자면
            # wake 가 ~500/s (physics rate) 로 줄어 GIL 경합 ↓ → mujoco render 부드럽고
            # 같은 머신의 browser depth view lag 도 완화. 타이밍 (next_step/next_sync) 은 그대로.
            next_evt = next_step if viewer is None else min(next_step, next_sync)
            dt_sleep = next_evt - time.monotonic()
            if dt_sleep > 0:
                time.sleep(dt_sleep)

    def _on_hand_point(self, msg: PointStamped) -> None:
        """highfive_node 가 받는 hand_point 를 viewer 의 빨간 sphere 로 시각화.
        frame_id 가 d435_depth_optical_frame[:left|:right] 라 가정 — DEPTH_OPT_TO_WORLD
        변환으로 world 좌표 계산. 다른 frame 이면 변환 부정확하지만 그래도 표시."""
        if msg.point.z <= 0.05:
            return
        pt_opt = np.array(
            [msg.point.x, msg.point.y, msg.point.z], dtype=np.float64,
        )
        self._hand_world = (self._depth_opt_to_world_R @ pt_opt
                            + self._depth_opt_to_world_T).astype(np.float32)
        self._hand_seen_at_mono_s = time.monotonic()
        # 디버그: throttle 로 spam 없이 hand_point 수신 확인.
        self.get_logger().info(
            f"hand_point recv → world={self._hand_world.tolist()}",
            throttle_duration_sec=2.0,
        )

    def _on_camera_info(self, msg: CameraInfo) -> None:
        if self._cam_intr is not None:
            return
        # K = [fx 0 cx ; 0 fy cy ; 0 0 1].
        self._cam_intr = (float(msg.k[0]), float(msg.k[4]),
                          float(msg.k[2]), float(msg.k[5]))
        self.get_logger().info(
            f"D435 intrinsics: fx={msg.k[0]:.1f} fy={msg.k[4]:.1f} "
            f"cx={msg.k[2]:.1f} cy={msg.k[5]:.1f}",
        )

    def _on_depth(self, msg: Image) -> None:
        """Depth frame → voxels (world frame) for MuJoCo viewer 시각화.
        Stride 로 downsample 후 unproject → voxelize → user_scn 에 BOX 로 그림."""
        if self._cam_intr is None or msg.encoding != "16UC1":
            return
        fx, fy, cx, cy = self._cam_intr
        H, W = msg.height, msg.width
        depth = np.frombuffer(msg.data, dtype=np.uint16).reshape(H, W)
        s = VOXEL_PIXEL_STRIDE
        depth_ds = depth[::s, ::s].astype(np.float32) / 1000.0  # mm → m
        h_ds, w_ds = depth_ds.shape
        us, vs = np.meshgrid(
            np.arange(0, W, s, dtype=np.float32)[:w_ds],
            np.arange(0, H, s, dtype=np.float32)[:h_ds],
        )
        mask = (depth_ds > VOXEL_NEAR_M) & (depth_ds < VOXEL_FAR_M)
        if not mask.any():
            with self._voxels_lock:
                self._voxels_world = np.zeros((0, 3), dtype=np.float32)
            return
        z = depth_ds[mask]
        u = us[mask]
        v = vs[mask]
        x_opt = (u - cx) * z / fx
        y_opt = (v - cy) * z / fy
        pts_opt = np.stack([x_opt, y_opt, z], axis=1)
        pts_world = pts_opt @ self._depth_opt_to_world_R.T + self._depth_opt_to_world_T
        # Voxelize: quantize to grid, dedupe.
        keys = np.round(pts_world / VOXEL_SIZE_M).astype(np.int32)
        _, idx = np.unique(keys, axis=0, return_index=True)
        voxels = (keys[idx] * VOXEL_SIZE_M).astype(np.float32)
        if len(voxels) > VOXEL_MAX_COUNT:
            voxels = voxels[:VOXEL_MAX_COUNT]
        with self._voxels_lock:
            self._voxels_world = voxels
        self.get_logger().info(
            f"voxels: {len(voxels)} (mask {mask.sum()})",
            throttle_duration_sec=3.0,
        )

    def _on_traj(self, msg: JointTrajectory) -> None:
        if self._model is None or not msg.points:
            return
        # 시간 기반 trajectory player 로 등록 — last-waypoint-only 로 박으면
        # ctrl 이 step input 받아 PD 가 슬램 → ringing. quintic waypoint 그대로
        # 시간순 보간해서 부드럽게 추종.
        wp: list[tuple[float, dict[str, float]]] = []
        for pt in msg.points:
            t_fs = float(pt.time_from_start.sec) + float(pt.time_from_start.nanosec) * 1e-9
            wp.append((t_fs, {jn: float(q) for jn, q in zip(msg.joint_names, pt.positions)}))
        # Snap-blend trajectory start to ACTUAL current qpos.
        # 문제: highfive_node 의 current_full 은 /joint_states publish lag (~50-100ms)
        # 만큼 stale → wp[0] 와 reality 가 미세하게 다름. wp[0] 만 snap 하면 wp[0]→wp[1]
        # 사이에 backwards 작은 점프 발생 (shake 원인). 해결: snap delta 를 첫 5개
        # waypoint 에 걸쳐 선형 decay 하면서 적용 — wp[0] full delta, wp[N] zero.
        # 결과: trajectory 가 실제 current 에서 시작해 부드럽게 원래 경로에 합류.
        N_BLEND = 5
        if wp:
            current_qpos = {}
            for j_name in wp[0][1].keys():
                j_id = mujoco.mj_name2id(
                    self._model, mujoco.mjtObj.mjOBJ_JOINT, j_name,
                )
                if j_id >= 0:
                    current_qpos[j_name] = float(
                        self._data.qpos[self._model.jnt_qposadr[j_id]],
                    )
                else:
                    current_qpos[j_name] = wp[0][1][j_name]
            delta = {j: current_qpos[j] - wp[0][1][j] for j in wp[0][1]}
            for i in range(min(N_BLEND, len(wp))):
                blend = 1.0 - (i / N_BLEND)  # 1.0, 0.8, 0.6, 0.4, 0.2
                wp[i] = (
                    wp[i][0],
                    {j: wp[i][1][j] + blend * delta.get(j, 0.0)
                     for j in wp[i][1]},
                )
        traj_start_mono = time.monotonic()
        with self._traj_lock:
            self._active_traj = (traj_start_mono, wp)
        # Pre-compute compliance window absolute times — _apply_compliance_scaling
        # 이 매 physics step (500Hz) 마다 lock 안 잡고 check 할 수 있게.
        if wp:
            traj_end = wp[-1][0]
            self._compliance_window_start_s = (
                traj_start_mono + traj_end * COMPLIANCE_FRAC_START
            )
            self._compliance_window_end_s = (
                traj_start_mono + traj_end * COMPLIANCE_FRAC_END
            )
        # Reset EMA to current qpos — 이전 gesture 의 stale target 잔류 방지.
        for j_name in list(self._target_ema.keys()):
            j_id = mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_JOINT, j_name)
            if j_id >= 0:
                self._target_ema[j_name] = float(
                    self._data.qpos[self._model.jnt_qposadr[j_id]],
                )

    def _publish_joint_state(self) -> None:
        if self._model is None or self._data is None:
            return
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = list(self._joint_names)
        # qpos 순서는 model.jnt_qposadr 기반 — joint 별로 1 dof 라 그냥 인덱싱 가능.
        positions: list[float] = []
        for j_name in self._joint_names:
            j_id = mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_JOINT, j_name)
            qpos_adr = self._model.jnt_qposadr[j_id]
            positions.append(float(self._data.qpos[qpos_adr]))
        msg.position = positions
        self._js_pub.publish(msg)

    def destroy_node(self) -> bool:
        self._stop.set()
        return super().destroy_node()


def main(args=None) -> int:
    rclpy.init(args=args)
    node = MujocoTwinNode()
    # ROS executor 를 background thread 에서 — viewer 가 main 점유.
    executor = rclpy.executors.SingleThreadedExecutor()
    executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, daemon=True, name="ros_spin")
    spin_thread.start()
    try:
        node.run_main_loop()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    main()
