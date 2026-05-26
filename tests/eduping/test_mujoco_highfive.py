"""EduPing 하이파이브 — MuJoCo 컴플라이언트 접촉 헤드리스 검증 (GUI 불필요).

  - 손 없을 때 팔이 하이파이브 준비 자세를 유지 (안 떨어짐)
  - "사람 손"을 손바닥으로 옮기면 접촉력이 인식 임계를 넘음 (하이파이브 감지)
  - 손을 떼면 임피던스로 준비 자세에 복귀 (슬랩 흡수 후 리턴)
mujoco / 모델 미설치면 자동 skip.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

mujoco = pytest.importorskip("mujoco")

REPO = Path(__file__).resolve().parents[2]
HF_PATH = REPO / "controller/eduping-controller/src/eduarm/eduarm/mujoco_highfive.py"
MODEL = REPO / "controller/eduping-controller/src/openarm_mujoco/v1/scene.xml"


@pytest.fixture(scope="module")
def hf():
    if not HF_PATH.exists():
        pytest.skip(f"하이파이브 모듈 없음: {HF_PATH}")
    if not MODEL.exists():
        pytest.skip(f"openarm_mujoco 모델 없음: {MODEL}")
    spec = importlib.util.spec_from_file_location("mujoco_highfive", HF_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _setup(hf):
    model, hgid = hf.build_model_with_hand(MODEL)
    act, dof, qpos, gear, q_des, kp = hf.build_control(model)
    model.dof_damping[dof] = 2.0 * hf.DAMP_RATIO * np.sqrt(kp)
    return model, hgid, act, dof, qpos, gear, q_des, kp


def _step(hf, model, data, arm_act, arm_dof, arm_qpos, gear, q_des, kp):
    mujoco.mj_step1(model, data)
    tau = hf.impedance_tau(data, arm_dof, arm_qpos, q_des, kp, hf.TAU_CAP)
    data.ctrl[:] = 0.0
    data.ctrl[arm_act] = tau / gear
    mujoco.mj_step2(model, data)


def test_holds_highfive_pose(hf):
    """손 없이 1.5초 — 팔이 준비 자세를 유지(안 떨어짐)."""
    model, hgid, arm_act, arm_dof, arm_qpos, gear, q_des, kp = _setup(hf)
    data = mujoco.MjData(model)
    data.qpos[arm_qpos] = q_des
    data.mocap_pos[0] = [0.6, 0.52, 0.88]  # 손 멀리
    mujoco.mj_forward(model, data)
    for _ in range(750):
        _step(hf, model, data, arm_act, arm_dof, arm_qpos, gear, q_des, kp)
    drift = float(np.max(np.abs(data.qpos[arm_qpos] - q_des)))
    assert drift < 0.1, f"준비 자세 유지 실패(드리프트 {drift:.3f})"


def test_detects_highfive_and_recovers(hf):
    """손을 손바닥으로 밀면 접촉력이 인식 임계 초과, 떼면 준비 자세 복귀."""
    model, hgid, arm_act, arm_dof, arm_qpos, gear, q_des, kp = _setup(hf)
    data = mujoco.MjData(model)
    data.qpos[arm_qpos] = q_des
    mujoco.mj_forward(model, data)

    peak = 0.0
    # 슬랩: 손을 0.45 → 0.27 로 밀어 손바닥 접촉
    for k in range(1500):
        x = max(0.27, 0.45 - k * 0.0006)
        data.mocap_pos[0] = [x, 0.52, 0.88]
        _step(hf, model, data, arm_act, arm_dof, arm_qpos, gear, q_des, kp)
        peak = max(peak, hf.contact_force_on(model, data, hgid))
    assert peak > hf.HIGHFIVE_FORCE, f"하이파이브 접촉 감지 실패(peak {peak:.1f}N)"

    # 손 떼기 → 복귀
    for _ in range(1500):
        data.mocap_pos[0] = [0.6, 0.52, 0.88]
        _step(hf, model, data, arm_act, arm_dof, arm_qpos, gear, q_des, kp)
    drift = float(np.max(np.abs(data.qpos[arm_qpos] - q_des)))
    assert drift < 0.1, f"슬랩 후 준비 자세 복귀 실패(드리프트 {drift:.3f})"
