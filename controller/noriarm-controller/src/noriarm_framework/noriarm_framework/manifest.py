"""게임 매니페스트 (game.yaml) 스키마 + 로더.

각 게임은 `games/<name>/game.yaml` 에 자기가 요구하는 카메라·OMX 팔·정책 종류를
선언한다. 카메라/팔의 실제 디바이스는 sim/real 양쪽 매핑을 모두 적어두고, 런타임에
`--target sim|real` 플래그로 어느 쪽을 쓸지 정한다.

스키마 예시는 `games/ox_quiz/game.yaml` 참조.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ManifestError(ValueError):
    """매니페스트 형식이 잘못됐을 때."""


# --- 하드웨어 ---------------------------------------------------------------


@dataclass(frozen=True)
class CameraSpec:
    id: str
    role: str  # marker_detection / overhead / gripper 등 자유 문자열
    sim: dict[str, Any]
    real: dict[str, Any]
    resolution: tuple[int, int] = (1280, 720)
    fps: int = 30

    def device(self, target: str) -> dict[str, Any]:
        return self.sim if target == "sim" else self.real


@dataclass(frozen=True)
class ArmSpec:
    id: str
    model: str  # omx_f / omx_l 등 — open_manipulator_description 의 URDF 모델 이름
    ros_namespace: str  # ROS2 namespace, 예: /noriarm/pointer
    sim: dict[str, Any]
    real: dict[str, Any]
    controller_topic: str  # JointTrajectory publish 대상 — 예: /arm_controller/joint_trajectory
    controller_joint_names: tuple[str, ...]  # arm_controller 가 소유한 joint 이름 (순서 유의)
    role: str = ""

    def backend(self, target: str) -> dict[str, Any]:
        return self.sim if target == "sim" else self.real


# --- 정책 ------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyConfig:
    kind: str  # "rule_based" / "smolvla" / 기타
    module: str  # 동적 import 경로, 예: "noriarm_framework.games.ox_quiz.policy_rule"
    extra: dict[str, Any] = field(default_factory=dict)


# --- 게임 -------------------------------------------------------------------


@dataclass(frozen=True)
class RuntimeConfig:
    rate_hz: float = 30.0
    episode_timeout_s: float = 60.0


@dataclass(frozen=True)
class GameConfig:
    name: str
    display: str
    cameras: tuple[CameraSpec, ...]
    arms: tuple[ArmSpec, ...]
    policy: PolicyConfig
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    source_path: Path | None = None

    def camera_by_id(self, camera_id: str) -> CameraSpec:
        for cam in self.cameras:
            if cam.id == camera_id:
                return cam
        raise KeyError(camera_id)

    def arm_by_id(self, arm_id: str) -> ArmSpec:
        for arm in self.arms:
            if arm.id == arm_id:
                return arm
        raise KeyError(arm_id)


# --- 로더 ------------------------------------------------------------------


def load_manifest(path: str | Path) -> GameConfig:
    """`game.yaml` 한 파일을 GameConfig 로 변환한다.

    검증 실패 시 ManifestError 를 던진다 — 누락 필드, 빈 cameras/arms, 잘못된 sim/real
    매핑 등.
    """
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise ManifestError(f"매니페스트 파일이 없음: {p}")
    with p.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ManifestError(f"매니페스트는 매핑이어야 함 (got {type(raw).__name__}): {p}")
    return _build_config(raw, source=p)


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise ManifestError(f"{where}: 필수 키 '{key}' 누락")
    return mapping[key]


def _build_config(raw: dict[str, Any], source: Path) -> GameConfig:
    name = _require(raw, "name", str(source))
    display = raw.get("display", name)

    hardware = _require(raw, "hardware", str(source))
    if not isinstance(hardware, dict):
        raise ManifestError(f"{source}: hardware 는 매핑이어야 함")

    cameras_raw = hardware.get("cameras", [])
    arms_raw = hardware.get("arms", [])
    if not cameras_raw and not arms_raw:
        raise ManifestError(f"{source}: hardware.cameras 또는 hardware.arms 중 하나는 있어야 함")

    cameras = tuple(_build_camera(c, source) for c in cameras_raw)
    arms = tuple(_build_arm(a, source) for a in arms_raw)

    _check_unique_ids([c.id for c in cameras], "cameras", source)
    _check_unique_ids([a.id for a in arms], "arms", source)

    policy_raw = _require(raw, "policy", str(source))
    policy = _build_policy(policy_raw, source)

    runtime_raw = raw.get("runtime", {}) or {}
    runtime = RuntimeConfig(
        rate_hz=float(runtime_raw.get("rate_hz", 30.0)),
        episode_timeout_s=float(runtime_raw.get("episode_timeout_s", 60.0)),
    )

    return GameConfig(
        name=name,
        display=display,
        cameras=cameras,
        arms=arms,
        policy=policy,
        runtime=runtime,
        source_path=source,
    )


def _build_camera(c: dict[str, Any], source: Path) -> CameraSpec:
    where = f"{source}: cameras[{c.get('id', '?')}]"
    cam_id = _require(c, "id", where)
    role = _require(c, "role", where)
    sim = _require(c, "sim", where)
    real = _require(c, "real", where)
    if not isinstance(sim, dict) or not isinstance(real, dict):
        raise ManifestError(f"{where}: sim / real 은 매핑이어야 함")
    resolution = c.get("resolution", [1280, 720])
    if len(resolution) != 2:
        raise ManifestError(f"{where}: resolution 은 [width, height] 2 개 값")
    return CameraSpec(
        id=cam_id,
        role=role,
        sim=sim,
        real=real,
        resolution=(int(resolution[0]), int(resolution[1])),
        fps=int(c.get("fps", 30)),
    )


def _build_arm(a: dict[str, Any], source: Path) -> ArmSpec:
    where = f"{source}: arms[{a.get('id', '?')}]"
    arm_id = _require(a, "id", where)
    model = _require(a, "model", where)
    ns = _require(a, "ros_namespace", where)
    sim = _require(a, "sim", where)
    real = _require(a, "real", where)
    if not isinstance(sim, dict) or not isinstance(real, dict):
        raise ManifestError(f"{where}: sim / real 은 매핑이어야 함")
    controller_topic = _require(a, "controller_topic", where)
    joint_names_raw = _require(a, "controller_joint_names", where)
    if not isinstance(joint_names_raw, list) or not joint_names_raw:
        raise ManifestError(f"{where}: controller_joint_names 는 비어있지 않은 리스트")
    return ArmSpec(
        id=arm_id,
        model=model,
        ros_namespace=ns,
        sim=sim,
        real=real,
        controller_topic=str(controller_topic),
        controller_joint_names=tuple(str(j) for j in joint_names_raw),
        role=a.get("role", ""),
    )


def _build_policy(p: dict[str, Any], source: Path) -> PolicyConfig:
    where = f"{source}: policy"
    kind = _require(p, "kind", where)
    module = _require(p, "module", where)
    extra = {k: v for k, v in p.items() if k not in {"kind", "module"}}
    return PolicyConfig(kind=kind, module=module, extra=extra)


def _check_unique_ids(ids: list[str], section: str, source: Path) -> None:
    seen: set[str] = set()
    for i in ids:
        if i in seen:
            raise ManifestError(f"{source}: {section} 에서 id '{i}' 중복")
        seen.add(i)
