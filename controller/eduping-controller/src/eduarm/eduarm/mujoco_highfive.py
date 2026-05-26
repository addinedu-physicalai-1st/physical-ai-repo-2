#!/usr/bin/env python3
"""EduPing(OpenArm) 하이파이브 — MuJoCo 컴플라이언트 접촉 데모.

왼팔을 하이파이브 준비 자세(손 들어 손바닥 앞)로 **임피던스로 유지**하고,
이동 가능한 "사람 손"(mocap 박스)을 사용자가 끌어다 로봇 손바닥을 친다.
임피던스라 슬랩을 부드럽게 받아주고(give) 다시 준비 자세로 복귀한다 — 아이가
손을 세게 쳐도 딱딱하게 안 막고 흡수하는 안전한 하이파이브. 접촉력이 임계를
넘으면 "하이파이브!"로 인식한다.

벤더 모델은 못 고치므로 MjSpec 으로 런타임에 손 객체를 추가한다.

실행 (로컬 GUI 필요):
    source /home/kyle/venv/pingdergarten/bin/activate
    python controller/eduping-controller/src/eduarm/eduarm/mujoco_highfive.py

뷰어 조작:
    손(살색 박스)을 더블클릭 → Ctrl+오른쪽 드래그로 끌어 로봇 손바닥을 친다
    H   준비 자세로 리셋
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import deque
from pathlib import Path

import mujoco
import mujoco.viewer
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mujoco_l1_float import DEFAULT_MODEL, build_arm_mapping  # noqa: E402
from mujoco_l2_impedance import impedance_tau  # noqa: E402

HIGHFIVE_POSE = {"left_joint2": -2.0, "left_joint4": 1.0}  # 왼손 ↑·앞, 손바닥 전방
HAND_POS = (0.42, 0.52, 0.87)        # "사람 손" 시작 위치 (로봇 손바닥 앞)
PALM_SIZE = (0.02, 0.05, 0.06)       # 손바닥 충돌체 half-extent (x 두껍게 = 터널링↓)
ARM_KP = 8.0                         # 팔 관절 강성 (낮을수록 슬랩에 팔이 더 접히며 밀림)
FINGER_KP = 30.0                     # 그리퍼(손가락) 유지 강성 — 단단히 잡아 안 벌어지게
DAMP_RATIO = 0.7
TAU_CAP = 20.0                       # 소프트웨어 토크상한 [Nm]
HIGHFIVE_FORCE = 8.0                 # "하이파이브!" 인식 임계 [N]
COOLDOWN_S = 1.0                     # 연속 인식 방지


def build_model_with_hand(scene_path: Path):
    """벤더 scene 에 이동 가능한 "사람 손"(mocap)을 추가해 컴파일.

    손바닥(box)만 충돌체 — 살은 물렁(soft contact) + priority 로 우선.
    손가락 4 + 엄지는 시각용(contype/conaffinity=0, 충돌 없음)으로 사람 손 모양만.
    손바닥 법선은 -x(로봇 쪽), 손가락은 +z(위) = 펼친 하이파이브 손.
    """
    SKIN = [0.95, 0.78, 0.62, 1.0]
    spec = mujoco.MjSpec.from_file(str(scene_path))
    body = spec.worldbody.add_body(name="human_hand", pos=list(HAND_POS))
    body.mocap = True  # 마우스로 옮기고 중력에 안 떨어짐

    palm = body.add_geom(
        name="hand_geom", type=mujoco.mjtGeom.mjGEOM_BOX, size=list(PALM_SIZE), rgba=SKIN,
    )
    palm.solref = [0.05, 1.0]
    palm.solimp = [0.6, 0.9, 0.01, 0.5, 2.0]
    palm.priority = 1

    # 손가락 4개 (위로 뻗은 캡슐) — 시각용
    for i, yy in enumerate((-0.033, -0.011, 0.011, 0.033)):
        f = body.add_geom(
            name=f"finger{i}", type=mujoco.mjtGeom.mjGEOM_CAPSULE,
            size=[0.009, 0.032, 0], pos=[0.0, yy, 0.09], rgba=SKIN,
        )
        f.contype = 0
        f.conaffinity = 0
    # 엄지 (옆으로) — 시각용
    thumb = body.add_geom(
        name="thumb", type=mujoco.mjtGeom.mjGEOM_CAPSULE,
        size=[0.011, 0.026, 0], pos=[0.0, -0.06, 0.03], rgba=SKIN,
    )
    thumb.contype = 0
    thumb.conaffinity = 0

    model = spec.compile()
    model.opt.integrator = mujoco.mjtIntegrator.mjINT_IMPLICITFAST
    hgid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "hand_geom")
    return model, hgid


def contact_force_on(model, data, geom_id: int) -> float:
    """주어진 geom 이 낀 모든 접촉의 normal force 합 [N]."""
    total = 0.0
    f6 = np.zeros(6)
    for i in range(data.ncon):
        c = data.contact[i]
        if geom_id in (c.geom1, c.geom2):
            mujoco.mj_contactForce(model, data, i, f6)
            total += abs(f6[0])
    return total


def build_control(model):
    """모든 motor(토크) 액추에이터에 대한 (act, dof, qpos, gear, q_des, kp).

    팔 관절 = HIGHFIVE_POSE 목표 + ARM_KP, 그리퍼(finger) = 0 유지 + FINGER_KP(단단히).
    position 액추에이터(오른 그리퍼)는 제외 — 그쪽은 ctrl 0 으로 닫힘 유지된다.
    그리퍼를 잡아야 슬랩이 손가락에 안 먹히고 팔로 전달돼 팔이 접히며 밀린다.
    """
    nu = model.nu
    jn = [
        mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, model.actuator_trnid[i, 0]) or ""
        for i in range(nu)
    ]
    act = np.array([i for i in range(nu) if model.actuator_biastype[i] == 0], dtype=int)
    dof = np.array([model.jnt_dofadr[model.actuator_trnid[i, 0]] for i in act], dtype=int)
    qpos = np.array([model.jnt_qposadr[model.actuator_trnid[i, 0]] for i in act], dtype=int)
    gear = model.actuator_gear[act, 0]
    q_des = np.zeros(len(act))
    kp = np.empty(len(act))
    for k, i in enumerate(act):
        name = jn[i]
        kp[k] = FINGER_KP if "finger" in name else ARM_KP
        for suffix, val in HIGHFIVE_POSE.items():
            if name.endswith(suffix):
                q_des[k] = val
    return act, dof, qpos, gear, q_des, kp


def main() -> None:
    ap = argparse.ArgumentParser(description="OpenArm high-five compliant contact (MuJoCo)")
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="scene.xml 경로")
    args = ap.parse_args()
    if not args.model.exists():
        raise SystemExit(f"[ERROR] 모델 파일 없음: {args.model}")

    model, hgid = build_model_with_hand(args.model)
    data = mujoco.MjData(model)

    act, dof, qpos, gear, q_des, kp = build_control(model)
    model.dof_damping[dof] = 2.0 * DAMP_RATIO * np.sqrt(kp)
    data.qpos[qpos] = q_des                # 준비 자세 + 그리퍼 닫힘에서 시작
    mujoco.mj_forward(model, data)

    def key_callback(keycode: int) -> None:
        if keycode == 72:  # H
            mujoco.mj_resetData(model, data)
            data.qpos[qpos] = q_des
            mujoco.mj_forward(model, data)
            print("[reset] 준비 자세로")

    print("=" * 60)
    print(" OpenArm 하이파이브 (컴플라이언트 접촉)")
    print(f" 팔Kp={ARM_KP} 그리퍼Kp={FINGER_KP} 토크상한={TAU_CAP}Nm  인식 임계={HIGHFIVE_FORCE}N")
    print(" 살색 손을 더블클릭 → Ctrl+우드래그로 끌어 손바닥을 치세요 | H=리셋")
    print("=" * 60)

    last_hi = 0.0
    recent_f: deque[float] = deque(maxlen=8)  # 한 스텝 측정 글리치 제거용
    with mujoco.viewer.launch_passive(model, data, key_callback=key_callback) as viewer:
        while viewer.is_running():
            t0 = time.time()
            mujoco.mjv_applyPerturbPose(model, data, viewer.perturb, 0)  # 손 이동
            mujoco.mj_step1(model, data)

            recent_f.append(contact_force_on(model, data, hgid))
            f = float(np.median(recent_f))  # 글리치(접촉 생성 순간 큰 튐) 제거
            tau = impedance_tau(data, dof, qpos, q_des, kp, TAU_CAP)
            data.ctrl[:] = 0.0
            data.ctrl[act] = tau / gear

            mujoco.mj_step2(model, data)

            if f > HIGHFIVE_FORCE and (t0 - last_hi) > COOLDOWN_S:
                print(f"👋 하이파이브!  (접촉 {f:.0f}N — 부드럽게 받음)")
                last_hi = t0

            viewer.sync()
            sleep = model.opt.timestep - (time.time() - t0)
            if sleep > 0:
                time.sleep(sleep)


if __name__ == "__main__":
    main()
