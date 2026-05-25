"""EduPing L1 — MuJoCo 중력보상 컨트롤러 헤드리스 검증 (GUI 불필요).

접촉을 끄고 컨트롤러만 격리해, 중력부하가 걸리는 in-range 포즈에서:
  - 보상 ON  → 팔이 거의 안 움직임 (float)
  - 보상 OFF → 중력으로 떨어짐
mujoco / 모델(openarm_mujoco) 미설치면 자동 skip.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

mujoco = pytest.importorskip("mujoco")

# tests/eduping/<this> → parents[2] = repo root (worktree)
REPO = Path(__file__).resolve().parents[2]
MODULE = REPO / "controller/eduping-controller/src/eduarm/eduarm/mujoco_l1_float.py"
MODEL = REPO / "controller/eduping-controller/src/openarm_mujoco/v1/scene.xml"


@pytest.fixture(scope="module")
def l1():
    if not MODULE.exists():
        pytest.skip(f"L1 모듈 없음: {MODULE}")
    spec = importlib.util.spec_from_file_location("mujoco_l1_float", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _model():
    if not MODEL.exists():
        pytest.skip(f"openarm_mujoco 모델 없음 (submodule/clone): {MODEL}")
    m = mujoco.MjModel.from_xml_path(str(MODEL))
    # 컨트롤러만 격리 검증 — 접촉/자기충돌 폭발 제거
    m.opt.disableflags |= mujoco.mjtDisableBit.mjDSBL_CONTACT
    return m


def _loaded_pose(model) -> np.ndarray:
    """중력부하가 걸리는, 가동범위 안의 양팔 포즈."""
    pose = np.zeros(model.nq)

    def setq(joint: str, val: float) -> None:
        jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint)
        lo, hi = model.jnt_range[jid]
        if model.jnt_limited[jid]:
            val = float(np.clip(val, lo + 0.05, hi - 0.05))
        pose[model.jnt_qposadr[jid]] = val

    setq("openarm_left_joint2", 0.6)
    setq("openarm_left_joint4", -0.6)
    setq("openarm_right_joint2", -0.6)
    setq("openarm_right_joint4", 0.6)
    return pose


def _simulate(model, l1, pose, *, enable: bool, steps: int = 1500) -> float:
    """pose 에서 steps 만큼 적분 후 팔 관절 최대 드리프트(rad)."""
    data = mujoco.MjData(model)
    data.qpos[:] = pose
    mujoco.mj_forward(model, data)
    mapping = l1.build_arm_mapping(model)
    arm_dof = mapping[1]
    for _ in range(steps):
        mujoco.mj_step1(model, data)
        l1.apply_gravity_comp(model, data, mapping, enable=enable)
        mujoco.mj_step2(model, data)
    return float(np.max(np.abs(data.qpos[arm_dof] - pose[arm_dof])))


def test_gravity_comp_holds_arm(l1):
    """보상 ON: 3초 적분 후에도 팔이 제자리 (float)."""
    model = _model()
    pose = _loaded_pose(model)
    drift = _simulate(model, l1, pose, enable=True)
    assert drift < 0.02, f"보상 ON 인데 드리프트 큼: {drift:.4f} rad"


def test_without_comp_arm_falls(l1):
    """보상 OFF: 중력으로 떨어져 큰 드리프트."""
    model = _model()
    pose = _loaded_pose(model)
    drift = _simulate(model, l1, pose, enable=False)
    assert drift > 0.1, f"보상 OFF 인데 안 떨어짐: {drift:.4f} rad"
