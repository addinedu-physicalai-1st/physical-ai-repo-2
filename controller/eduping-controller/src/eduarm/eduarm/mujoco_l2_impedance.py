#!/usr/bin/env python3
"""EduPing(OpenArm) L2 — MuJoCo 관절 임피던스(가변 강성) + 소프트웨어 토크상한.

L1(중력보상, 강성 0) 위에 관절 스프링을 얹어 임피던스를 만든다 (관절별):

    τ_cmd = g(q) + Kp·(q_des − q)          ← 액추에이터로 명령 (토크상한 clamp)
    감쇠   Kd·q̇ 는 모델 dof_damping 으로 실현 (MuJoCo 가 implicit 적분 → 안정)

왜 감쇠를 ctrl 이 아니라 dof_damping 으로?  말단관절(관성 小)은 고유진동수가 높아,
−Kd·q̇ 를 ctrl 에 직접 넣고 explicit 적분하면 발산한다. dof_damping 에 넣으면
implicitfast 적분기가 implicit 처리해 안정적이다. 하드웨어에선 이 Kd 가 MIT 명령의
Kd 항에 해당한다.

소프트웨어 토크상한: |τ_cmd| ≤ tau_cap. 모터 펌웨어 한계(±40/±27/±7Nm)보다 낮게
잡아 둘 수 있어, 임피던스가 폭주해도 관절이 낼 힘 자체를 못 박는다 = 아이 안전의 핵심.

강성 Kp 를 낮추면 더 물렁(안전·양보), 높이면 단단(정밀). Kp=0 = L1(float).

실행 (로컬 GUI 필요):
    source /home/kyle/venv/pingdergarten/bin/activate
    python controller/eduping-controller/src/eduarm/eduarm/mujoco_l2_impedance.py
옵션:
    --model PATH     scene.xml 경로
    --tau-cap NM     소프트웨어 토크상한 (기본 15)

뷰어 조작:
    SPACE   강성 프리셋 순환: stiff → medium → soft → float(0)
    R       현재 자세를 새 목표 q_des 로 설정
    [ / ]   토크상한 ↓ / ↑ (2 Nm 씩)
    Ctrl + 좌클릭 드래그   외력 인가 → 스프링백/양보 관찰
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import mujoco
import mujoco.viewer
import numpy as np

# 같은 패키지의 L1 헬퍼 재사용 (스크립트 직접 실행 대비 경로 주입)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mujoco_l1_float import DEFAULT_MODEL, build_arm_mapping  # noqa: E402

# 강성 프리셋 — (이름, Kp[Nm/rad], 감쇠비 ζ). Kd 는 Kp 에서 임계감쇠 근사로 산출.
PRESETS: list[tuple[str, float, float]] = [
    ("stiff", 40.0, 1.0),
    ("medium", 15.0, 1.0),
    ("soft", 5.0, 1.0),
    ("float", 0.0, 1.0),
]


def preset_gains(n_arm: int, preset_idx: int) -> tuple[np.ndarray, np.ndarray]:
    """프리셋 인덱스 → (Kp, Kd) 배열. Kd 는 임계감쇠 근사 2ζ√Kp (float 은 약한 고정 감쇠)."""
    _, kp, zeta = PRESETS[preset_idx]
    kp_v = np.full(n_arm, kp)
    if kp == 0.0:
        return kp_v, np.full(n_arm, 0.5)
    return kp_v, 2.0 * zeta * np.sqrt(kp_v)


def impedance_tau(
    data: mujoco.MjData,
    arm_dof: np.ndarray,
    arm_qpos: np.ndarray,
    q_des: np.ndarray,
    kp: np.ndarray,
    tau_cap: float,
) -> np.ndarray:
    """액추에이터로 명령할 토크: g(q) + Kp(q_des−q), 토크상한으로 clamp.

    감쇠(Kd·q̇)는 여기 포함하지 않는다 — 모델 dof_damping 으로 실현(implicit 적분).
    호출 전 data.qfrc_bias 가 현재 상태로 계산돼 있어야 한다 (mj_step1/mj_forward 직후).
    """
    tau = data.qfrc_bias[arm_dof] + kp * (q_des - data.qpos[arm_qpos])
    return np.clip(tau, -tau_cap, tau_cap)


def main() -> None:
    ap = argparse.ArgumentParser(description="OpenArm L2 joint impedance + torque cap (MuJoCo)")
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="scene.xml 경로")
    ap.add_argument("--tau-cap", type=float, default=15.0, help="소프트웨어 토크상한 [Nm]")
    args = ap.parse_args()

    if not args.model.exists():
        raise SystemExit(f"[ERROR] 모델 파일 없음: {args.model}")

    model = mujoco.MjModel.from_xml_path(str(args.model))
    # PD 피드백 안정화: 감쇠를 dof_damping(implicit)으로 처리하려면 implicit 적분기 필요.
    model.opt.integrator = mujoco.mjtIntegrator.mjINT_IMPLICITFAST
    data = mujoco.MjData(model)

    arm_act, arm_dof, gear = build_arm_mapping(model)
    arm_qpos = np.array(
        [model.jnt_qposadr[model.actuator_trnid[i, 0]] for i in arm_act], dtype=int
    )

    q_des = data.qpos[arm_qpos].copy()  # 시작 자세를 목표로
    state = {"preset": 0, "tau_cap": float(args.tau_cap)}

    def status() -> str:
        name, kp, _ = PRESETS[state["preset"]]
        return f"강성={name}(Kp={kp:.0f})  토크상한={state['tau_cap']:.0f}Nm"

    def key_callback(keycode: int) -> None:
        if keycode == 32:  # SPACE
            state["preset"] = (state["preset"] + 1) % len(PRESETS)
        elif keycode == 82:  # R
            q_des[:] = data.qpos[arm_qpos]
            print("[target] 현재 자세를 새 목표로 설정")
        elif keycode == 91:  # [
            state["tau_cap"] = max(1.0, state["tau_cap"] - 2.0)
        elif keycode == 93:  # ]
            state["tau_cap"] += 2.0
        print("[L2] " + status())

    print("=" * 64)
    print(" OpenArm L2 관절 임피던스 + 토크상한")
    print(f" 모델: {args.model}")
    print(" SPACE=강성 프리셋 | R=목표 재설정 | [ ]=토크상한 | Ctrl+드래그=외력")
    print(" " + status())
    print("=" * 64)

    with mujoco.viewer.launch_passive(model, data, key_callback=key_callback) as viewer:
        while viewer.is_running():
            t0 = time.time()
            mujoco.mj_step1(model, data)  # qfrc_bias 계산

            kp, kd = preset_gains(len(arm_act), state["preset"])
            model.dof_damping[arm_dof] = kd  # 감쇠는 모델에 (implicit 적분 → 안정)
            tau = impedance_tau(data, arm_dof, arm_qpos, q_des, kp, state["tau_cap"])

            data.ctrl[:] = 0.0
            data.ctrl[arm_act] = tau / gear

            mujoco.mj_step2(model, data)
            viewer.sync()

            sleep = model.opt.timestep - (time.time() - t0)
            if sleep > 0:
                time.sleep(sleep)


if __name__ == "__main__":
    main()
