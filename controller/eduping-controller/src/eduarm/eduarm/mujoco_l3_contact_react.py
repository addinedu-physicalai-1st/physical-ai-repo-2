#!/usr/bin/env python3
"""EduPing(OpenArm) L3 — MuJoCo 접촉 감지 + 안전 반응(guarded move).

L2(가변 강성 임피던스) 위에 "예기치 못한 접촉을 느끼면 멈추고 물러난다"를 얹는다.
시뮬에 "아이" 대용 고정 물체(구)를 두고, 팔이 목표로 가다 물체에 닿으면:

    접촉력 > 임계  →  목표를 현재 자세로 고정(밀기 중단) + 그 자리를 단단히 유지

= 아이에게 부딪히면 더 밀어붙이지 않고 그 지점에 정지(흔들면 제자리 복귀). MuJoCo 가 강한
실제 접촉(rigid contact) 영역이라 충돌력이 사실적으로 계산된다.

벤더 모델은 못 고치므로 MjSpec 으로 런타임에 물체를 추가한다.
감지는 child geom 접촉력으로 한다(시뮬 ground-truth). 실물에선 토크 기반
외력 추정(disturbance observer, qfrc_constraint 류)으로 같은 일을 한다.

실행 (로컬 GUI 필요):
    source /home/kyle/venv/pingdergarten/bin/activate
    python controller/eduping-controller/src/eduarm/eduarm/mujoco_l3_contact_react.py

뷰어 조작:
    (시작 시 왼팔이 목표로 이동하며 물체로 들어간다)
    R   접촉 반응 ON/OFF 토글 — OFF 면 그냥 밀어붙임(force↑), ON 이면 닿자마자 멈춤
    H   홈으로 리셋 후 다시 시도
    공(주황) 옮기기: 더블클릭으로 선택 → Ctrl+오른쪽드래그=이동, Ctrl+왼쪽드래그=회전
                   (공을 팔에 직접 갖다 대 접촉 반응을 일으켜 볼 수 있다)
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

CHILD_POS = (0.28, 0.52, 0.50)   # 왼팔 경로 위 고정 물체 위치
CHILD_SIZE = 0.10                # 반경 [m]
GOAL = {"left_joint2": -1.2, "left_joint4": 1.0}  # 왼팔을 물체로 보내는 목표
FORCE_THRESH = 5.0               # 접촉 반응 트리거 [N]
TASK_KP = 40.0                   # 평소(작업) 강성
HOLD_KP = 40.0                   # 반응 후 유지 강성 (정지 후 단단히, 흔들면 빠르게 복귀)
DAMP_RATIO = 0.7                 # 감쇠비 ζ — 1.0 은 과감쇠(느림), 낮출수록 빠른 복귀(약간 오버슈트)
TAU_CAP = 20.0                   # 소프트웨어 토크상한 [Nm]
APPROACH_TIME = 3.0              # 목표까지 서서히 접근하는 시간 [s] (느린 접근 = 부드러운 접촉)


def build_model_with_child(scene_path: Path, pos=CHILD_POS, size=CHILD_SIZE):
    """벤더 scene 을 MjSpec 으로 로드하고 고정 "아이" 구를 추가해 컴파일."""
    spec = mujoco.MjSpec.from_file(str(scene_path))
    body = spec.worldbody.add_body(name="child", pos=list(pos))
    body.mocap = True  # mocap: 중력/접촉에 안 밀려 그 자리 유지 + 뷰어에서 마우스로 이동 가능
    g = body.add_geom(
        name="child_geom",
        type=mujoco.mjtGeom.mjGEOM_SPHERE,
        size=[size, 0, 0],
        rgba=[1.0, 0.6, 0.2, 1.0],
    )
    # 아이 몸은 물렁하다 — soft contact 로 모델링(현실적 + 강체 침투 폭발 방지).
    g.solref = [0.05, 1.0]                  # 접촉 시간상수↑ = 더 부드럽게
    g.solimp = [0.6, 0.9, 0.01, 0.5, 2.0]   # (dmin,dmax,width,mid,power) 최대 접촉강성↓
    g.priority = 1                          # child 접촉 파라미터 우선(강체 팔 geom 에 안 묻히게)
    model = spec.compile()
    model.opt.integrator = mujoco.mjtIntegrator.mjINT_IMPLICITFAST
    cgid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "child_geom")
    return model, cgid


def child_contact_force(model: mujoco.MjModel, data: mujoco.MjData, child_geom: int) -> float:
    """child geom 이 낀 모든 접촉의 normal force 합 [N]."""
    total = 0.0
    f6 = np.zeros(6)
    for i in range(data.ncon):
        c = data.contact[i]
        if child_geom in (c.geom1, c.geom2):
            mujoco.mj_contactForce(model, data, i, f6)
            total += abs(f6[0])  # contact frame x = normal
    return total


def goal_qpos(model, arm_act) -> np.ndarray:
    """GOAL 관절만 목표값, 나머지는 0(홈)인 q_des 배열."""
    q = np.zeros(len(arm_act))
    for k, i in enumerate(arm_act):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, model.actuator_trnid[i, 0]) or ""
        for suffix, val in GOAL.items():
            if name.endswith(suffix):
                q[k] = val
    return q


def main() -> None:
    ap = argparse.ArgumentParser(description="OpenArm L3 contact detection + safe reaction (MuJoCo)")
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="scene.xml 경로")
    args = ap.parse_args()
    if not args.model.exists():
        raise SystemExit(f"[ERROR] 모델 파일 없음: {args.model}")

    model, cgid = build_model_with_child(args.model)
    data = mujoco.MjData(model)

    arm_act, arm_dof, gear = build_arm_mapping(model)
    arm_qpos = np.array(
        [model.jnt_qposadr[model.actuator_trnid[i, 0]] for i in arm_act], dtype=int
    )
    goal = goal_qpos(model, arm_act)
    q_cmd0 = data.qpos[arm_qpos].copy()
    max_step = float(np.max(np.abs(goal - q_cmd0))) / (APPROACH_TIME / model.opt.timestep)

    state = {"reaction": True, "reacted": False, "q_hold": None, "q_cmd": q_cmd0.copy()}

    def key_callback(keycode: int) -> None:
        if keycode == 82:  # R
            state["reaction"] = not state["reaction"]
            print(f"[reaction] {'ON (닿으면 멈춤)' if state['reaction'] else 'OFF (밀어붙임)'}")
        elif keycode == 72:  # H
            mujoco.mj_resetData(model, data)
            state["reacted"] = False
            state["q_cmd"] = data.qpos[arm_qpos].copy()
            print("[reset] 홈으로")

    print("=" * 64)
    print(" OpenArm L3 접촉 감지 + 안전 반응  (왼팔이 물체로 이동)")
    print(f" 모델: {args.model}  | child @ {CHILD_POS} r={CHILD_SIZE}")
    print(f" 임계={FORCE_THRESH}N  task_Kp={TASK_KP} hold_Kp={HOLD_KP} 토크상한={TAU_CAP}Nm")
    print(" R=반응 ON/OFF | H=리셋 | 공: 더블클릭 후 Ctrl+우드래그로 이동")
    print("=" * 64)

    last_print = 0.0
    recent_f: deque[float] = deque(maxlen=15)  # 표시용 — 한 스텝 측정 글리치 제거
    with mujoco.viewer.launch_passive(model, data, key_callback=key_callback) as viewer:
        while viewer.is_running():
            t0 = time.time()
            # force perturbation(팔 드래그)은 뷰어가 자동 적용하지만, mocap "포즈"는 아님 →
            # 공을 마우스로 옮기려면 매 스텝 직접 적용해야 한다.
            mujoco.mjv_applyPerturbPose(model, data, viewer.perturb, 0)   # 공(mocap) 이동
            mujoco.mj_step1(model, data)

            f = child_contact_force(model, data, cgid)
            recent_f.append(f)
            # 반응 트리거 (래치): 접촉력이 임계를 넘으면 그 자리서 멈추고 단단히 유지
            if state["reaction"] and not state["reacted"] and f > FORCE_THRESH:
                state["reacted"] = True
                state["q_hold"] = data.qpos[arm_qpos].copy()
                print(f"[react] 접촉 감지 {f:.1f}N → 정지 + 단단히 유지")

            if state["reacted"]:
                q_des, kp_val = state["q_hold"], HOLD_KP
            else:
                # 목표로 서서히 램프 → 느린 접근 → 부드러운 접촉
                state["q_cmd"] += np.clip(goal - state["q_cmd"], -max_step, max_step)
                q_des, kp_val = state["q_cmd"], TASK_KP

            kp = np.full(len(arm_act), kp_val)
            model.dof_damping[arm_dof] = 2.0 * DAMP_RATIO * np.sqrt(kp)
            tau = impedance_tau(data, arm_dof, arm_qpos, q_des, kp, TAU_CAP)
            data.ctrl[:] = 0.0
            data.ctrl[arm_act] = tau / gear

            mujoco.mj_step2(model, data)
            viewer.sync()

            now = time.time()
            if now - last_print > 0.5:
                mode = "REACTED" if state["reacted"] else ("armed" if state["reaction"] else "OFF")
                f_show = float(np.median(recent_f)) if recent_f else 0.0  # 글리치 제거
                print(f"  child force = {f_show:6.1f} N   [{mode}]")
                last_print = now

            sleep = model.opt.timestep - (now - t0)
            if sleep > 0:
                time.sleep(sleep)


if __name__ == "__main__":
    main()
