"""EduPing L2 — MuJoCo 관절 임피던스 + 토크상한 헤드리스 검증 (GUI 불필요).

접촉을 끄고 컨트롤러만 격리해:
  - 목표(q_des)에서 변위시킨 팔이 임피던스로 q_des 에 수렴 (스프링백)
  - impedance_tau 가 토크상한을 절대 넘지 않음 (안전 clamp)
감쇠는 dof_damping(implicit) + implicitfast 적분기로 안정화 — 스크립트와 동일 방식.
mujoco / 모델(openarm_mujoco) 미설치면 자동 skip.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

mujoco = pytest.importorskip("mujoco")

REPO = Path(__file__).resolve().parents[2]
L2_PATH = REPO / "controller/eduping-controller/src/eduarm/eduarm/mujoco_l2_impedance.py"
MODEL = REPO / "controller/eduping-controller/src/openarm_mujoco/v1/scene.xml"


@pytest.fixture(scope="module")
def l2():
    if not L2_PATH.exists():
        pytest.skip(f"L2 모듈 없음: {L2_PATH}")
    spec = importlib.util.spec_from_file_location("mujoco_l2_impedance", L2_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _model():
    if not MODEL.exists():
        pytest.skip(f"openarm_mujoco 모델 없음: {MODEL}")
    m = mujoco.MjModel.from_xml_path(str(MODEL))
    m.opt.disableflags |= mujoco.mjtDisableBit.mjDSBL_CONTACT  # 컨트롤러 격리
    m.opt.integrator = mujoco.mjtIntegrator.mjINT_IMPLICITFAST  # 스크립트와 동일
    return m


def _arm_indices(l2, model):
    arm_act, arm_dof, gear = l2.build_arm_mapping(model)
    arm_qpos = np.array(
        [model.jnt_qposadr[model.actuator_trnid[i, 0]] for i in arm_act], dtype=int
    )
    return arm_act, arm_dof, arm_qpos, gear


def test_impedance_returns_to_target(l2):
    """목표에서 변위시킨 팔이 임피던스로 목표에 수렴 (스프링백)."""
    model = _model()
    arm_act, arm_dof, arm_qpos, gear = _arm_indices(l2, model)

    q_des = np.zeros(len(arm_act))            # 목표 = 홈
    kp = np.full(len(arm_act), 15.0)
    kd = 2.0 * np.sqrt(kp)
    model.dof_damping[arm_dof] = kd           # 감쇠는 모델에 (implicit)

    # 가동범위가 넓은 관절(1·3·5·7)만 변위 — 좁은 범위(joint2 등) 위반 회피
    names = [
        mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, model.actuator_trnid[i, 0])
        for i in arm_act
    ]
    disp = np.array(
        [0.5 if n.endswith(("joint1", "joint3", "joint5", "joint7")) else 0.0 for n in names]
    )

    data = mujoco.MjData(model)
    data.qpos[arm_qpos] = q_des + disp
    mujoco.mj_forward(model, data)
    err0 = float(np.max(np.abs(data.qpos[arm_qpos] - q_des)))

    for _ in range(4000):                     # 8초
        mujoco.mj_step1(model, data)
        tau = l2.impedance_tau(data, arm_dof, arm_qpos, q_des, kp, tau_cap=30.0)
        data.ctrl[:] = 0.0
        data.ctrl[arm_act] = tau / gear
        mujoco.mj_step2(model, data)

    err = float(np.max(np.abs(data.qpos[arm_qpos] - q_des)))
    assert err < 0.05, f"임피던스인데 목표로 수렴 안 함: err0={err0:.3f} → err={err:.3f}"


def test_torque_cap_clamps(l2):
    """큰 위치오차에서도 impedance_tau 가 토크상한을 넘지 않음."""
    model = _model()
    arm_act, arm_dof, arm_qpos, gear = _arm_indices(l2, model)

    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    q_des = np.full(len(arm_act), 5.0)        # 비현실적으로 큰 목표 오차 유도
    kp = np.full(len(arm_act), 100.0)

    cap = 8.0
    tau = l2.impedance_tau(data, arm_dof, arm_qpos, q_des, kp, tau_cap=cap)
    assert np.all(np.abs(tau) <= cap + 1e-9), f"토크상한 초과: max={np.max(np.abs(tau)):.2f} > {cap}"
