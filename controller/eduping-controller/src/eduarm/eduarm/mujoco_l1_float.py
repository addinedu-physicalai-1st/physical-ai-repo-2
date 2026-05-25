#!/usr/bin/env python3
"""EduPing(OpenArm) L1 — MuJoCo 중력보상(gravity compensation) float 데모.

토크 제어 액추에이터로 중력+코리올리 보상 토크 g(q)+C(q,q̇)q̇ 를 매 스텝 인가해
양팔을 "무중력"처럼 띄운다. 외력을 주면 부드럽게 양보하고(backdrivable), 놓으면
그 자리에 머문다 = 임피던스 제어의 가장 안전한 극단(강성 0).

모델: enactic 공식 openarm_mujoco v1 (= 하드웨어 v10). 양팔 7DOF + 그리퍼.
액추에이터 forcerange 가 실제 DM 모터 토크한계(±40/±27/±7 Nm)와 동일하므로,
보상 토크가 한계를 넘으면 자동 saturation — 이게 곧 안전 토크상한이다.

실행 (로컬 GUI 필요):
    source /home/kyle/venv/pingdergarten/bin/activate   # 또는 본인 env
    python controller/eduping-controller/src/eduarm/eduarm/mujoco_l1_float.py

옵션:
    --model PATH   scene.xml 경로 (기본: openarm_mujoco/v1/scene.xml)
    --exact        액추에이터(토크한계 적용) 대신 qfrc_applied 로 정확 보상.
                   토크한계 무시하고 항상 완벽히 float — 파이프라인 확인용.

뷰어 조작:
    SPACE                   중력보상 ON/OFF 토글 (OFF 면 팔이 중력으로 추락)
    Ctrl + 좌클릭 드래그     선택 링크에 외력 인가 → 들어올린 뒤 놓아 backdrivable 확인
    더블클릭 = 바디 선택, 우클릭 드래그 = 토크 인가
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import mujoco
import mujoco.viewer
import numpy as np

# 이 파일: .../src/eduarm/eduarm/mujoco_l1_float.py → parents[2] = .../src
DEFAULT_MODEL = (
    Path(__file__).resolve().parents[2] / "openarm_mujoco" / "v1" / "scene.xml"
)

# (arm_act, arm_dof, gear) — 팔 액추에이터 인덱스 / 구동 dof / 기어비
ArmMapping = tuple[np.ndarray, np.ndarray, np.ndarray]


def arm_actuator_indices(model: mujoco.MjModel) -> list[int]:
    """그리퍼(finger)를 제외한 팔 관절 액추에이터 인덱스."""
    out = []
    for i in range(model.nu):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_ACTUATOR, i) or ""
        if "finger" not in name:
            out.append(i)
    return out


def build_arm_mapping(model: mujoco.MjModel) -> ArmMapping:
    """팔 액추에이터 → 구동 dof 인덱스 / 기어비 매핑을 만든다."""
    arm_act = np.array(arm_actuator_indices(model), dtype=int)
    arm_dof = np.array(
        [model.jnt_dofadr[model.actuator_trnid[i, 0]] for i in arm_act], dtype=int
    )
    gear = model.actuator_gear[arm_act, 0].copy()
    return arm_act, arm_dof, gear


def apply_gravity_comp(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    mapping: ArmMapping,
    *,
    enable: bool = True,
    exact: bool = False,
) -> None:
    """중력+코리올리 보상 토크를 ctrl/qfrc_applied 에 채운다.

    호출 전 data.qfrc_bias 가 현재 상태로 계산돼 있어야 한다
    (mj_step1 또는 mj_forward 직후). data.ctrl / data.qfrc_applied 를 매번 리셋한다.
    """
    arm_act, arm_dof, gear = mapping
    data.qfrc_applied[:] = 0.0
    data.ctrl[:] = 0.0
    if not enable:
        return
    if exact:
        # 일반화좌표에 bias 를 정확히 상쇄 → 토크한계 무시, 항상 완벽 float
        data.qfrc_applied[:] = data.qfrc_bias
    else:
        # 팔 액추에이터로 보상 (gear=1 이면 ctrl=토크[Nm]).
        # forcerange 초과분은 MuJoCo 가 자동 clamp = 안전 토크상한.
        data.ctrl[arm_act] = data.qfrc_bias[arm_dof] / gear


def main() -> None:
    ap = argparse.ArgumentParser(description="OpenArm L1 gravity-compensation float (MuJoCo)")
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="scene.xml 경로")
    ap.add_argument(
        "--exact",
        action="store_true",
        help="qfrc_applied 로 정확 보상 (토크한계 무시, 항상 완벽 float)",
    )
    args = ap.parse_args()

    if not args.model.exists():
        raise SystemExit(f"[ERROR] 모델 파일 없음: {args.model}")

    model = mujoco.MjModel.from_xml_path(str(args.model))
    data = mujoco.MjData(model)
    mapping = build_arm_mapping(model)

    state = {"grav": True}  # SPACE 로 토글 (클로저 캡처용)

    def key_callback(keycode: int) -> None:
        if keycode == 32:  # SPACE
            state["grav"] = not state["grav"]
            print(f"[grav-comp] {'ON ' if state['grav'] else 'OFF'} "
                  f"({'float' if state['grav'] else '중력으로 추락'})")

    mode = "exact (qfrc_applied)" if args.exact else "actuator (토크한계 적용)"
    print("=" * 60)
    print(f" OpenArm L1 중력보상 float  |  모드: {mode}")
    print(f" 모델: {args.model}")
    print(f" 팔 액추에이터 {len(mapping[0])}개 (그리퍼 제외)")
    print(" SPACE=보상 토글 | Ctrl+드래그=외력 | 들어올렸다 놓아보세요")
    print("=" * 60)

    with mujoco.viewer.launch_passive(
        model, data, key_callback=key_callback
    ) as viewer:
        while viewer.is_running():
            t0 = time.time()

            mujoco.mj_step1(model, data)  # qfrc_bias 계산
            apply_gravity_comp(model, data, mapping, enable=state["grav"], exact=args.exact)
            mujoco.mj_step2(model, data)  # 적분 (외력 xfrc_applied 포함)

            viewer.sync()

            sleep = model.opt.timestep - (time.time() - t0)
            if sleep > 0:
                time.sleep(sleep)


if __name__ == "__main__":
    main()
