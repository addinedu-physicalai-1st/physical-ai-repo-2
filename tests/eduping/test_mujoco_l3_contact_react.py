"""EduPing L3 — MuJoCo 접촉 감지 + 안전 반응 헤드리스 검증 (GUI 불필요).

왼팔이 고정 "아이"(soft) 물체로 서서히 접근할 때:
  - 반응 OFF → 계속 밀어붙여 접촉력이 유지됨
  - 반응 ON  → 닿자마자 정지+연성화 → 지속 접촉력이 크게 줄고 트리거가 발동
지속 접촉력은 한 스텝 측정 글리치를 피하려 최근 구간 중앙값으로 본다.
mujoco / 모델 미설치면 자동 skip.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

mujoco = pytest.importorskip("mujoco")

REPO = Path(__file__).resolve().parents[2]
L3_PATH = REPO / "controller/eduping-controller/src/eduarm/eduarm/mujoco_l3_contact_react.py"
MODEL = REPO / "controller/eduping-controller/src/openarm_mujoco/v1/scene.xml"


@pytest.fixture(scope="module")
def l3():
    if not L3_PATH.exists():
        pytest.skip(f"L3 모듈 없음: {L3_PATH}")
    if not MODEL.exists():
        pytest.skip(f"openarm_mujoco 모델 없음: {MODEL}")
    spec = importlib.util.spec_from_file_location("mujoco_l3_contact_react", L3_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(l3, reaction: bool, steps: int = 4000):
    """반응 on/off 로 왼팔을 물체로 서서히 보내며 접촉력 추이를 측정 (스크립트와 동일 램프)."""
    model, cgid = l3.build_model_with_child(MODEL)
    arm_act, arm_dof, gear = l3.build_arm_mapping(model)
    arm_qpos = np.array(
        [model.jnt_qposadr[model.actuator_trnid[i, 0]] for i in arm_act], dtype=int
    )
    goal = l3.goal_qpos(model, arm_act)

    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    q_cmd = data.qpos[arm_qpos].copy()
    max_step = float(np.max(np.abs(goal - q_cmd))) / (l3.APPROACH_TIME / model.opt.timestep)

    reacted = False
    q_hold = None
    forces: list[float] = []
    for _ in range(steps):
        mujoco.mj_step1(model, data)
        f = l3.child_contact_force(model, data, cgid)
        forces.append(f)
        if reaction and not reacted and f > l3.FORCE_THRESH:
            reacted = True
            q_hold = data.qpos[arm_qpos].copy()
        if reacted:
            q_des, kp_val = q_hold, l3.HOLD_KP
        else:
            q_cmd += np.clip(goal - q_cmd, -max_step, max_step)
            q_des, kp_val = q_cmd, l3.TASK_KP
        kp = np.full(len(arm_act), kp_val)
        model.dof_damping[arm_dof] = 2.0 * l3.DAMP_RATIO * np.sqrt(kp)
        tau = l3.impedance_tau(data, arm_dof, arm_qpos, q_des, kp, l3.TAU_CAP)
        data.ctrl[:] = 0.0
        data.ctrl[arm_act] = tau / gear
        mujoco.mj_step2(model, data)

    sustained = float(np.median(forces[-400:]))  # 한 스텝 글리치 무시
    return {"sustained": sustained, "reacted": reacted}


def test_reaction_triggers_on_contact(l3):
    """반응 ON: 물체에 닿으면 트리거가 발동한다."""
    assert _run(l3, reaction=True)["reacted"], "접촉했는데 반응 트리거가 발동 안 함"


def test_reaction_reduces_sustained_force(l3):
    """반응 ON 의 지속 접촉력이 OFF 보다 뚜렷하게 작다."""
    on = _run(l3, reaction=True)
    off = _run(l3, reaction=False)
    assert off["sustained"] > l3.FORCE_THRESH, f"반응 OFF 가 충분히 밀지 않음: {off['sustained']:.1f}N"
    assert on["sustained"] < 0.6 * off["sustained"], (
        f"반응 ON 이 접촉력을 충분히 못 줄임: on={on['sustained']:.1f}N off={off['sustained']:.1f}N"
    )
