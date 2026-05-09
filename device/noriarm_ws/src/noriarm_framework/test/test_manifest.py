"""게임 매니페스트 로더 단위 테스트.

YAML 파싱 + 스키마 검증 + 헬퍼 (camera_by_id 등) 가 깨지지 않게 가드한다. ROS2 의존성
없이 순수 Python 테스트 — `pytest device/noriarm_ws/src/noriarm_framework/test` 로 실행.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from noriarm_framework.manifest import (
    GameConfig,
    ManifestError,
    load_manifest,
)


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "game.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


_MINIMAL = """
name: demo
display: "Demo"
hardware:
  cameras:
    - id: cam0
      role: marker_detection
      sim:  { source: webcam, index: 0 }
      real: { source: usb, by_id: "abc" }
  arms:
    - id: arm0
      model: omx_f
      ros_namespace: /noriarm/arm0
      controller_topic: /arm_controller/joint_trajectory
      controller_joint_names: [joint1, joint2, joint3, joint4, joint5]
      sim:  { backend: gazebo }
      real: { backend: dynamixel, port: /dev/ttyUSB0 }
policy:
  kind: rule_based
  module: noriarm_framework.games.ox_quiz.policy_rule
"""


def test_load_minimal_manifest(tmp_path: Path) -> None:
    cfg = load_manifest(_write(tmp_path, _MINIMAL))
    assert isinstance(cfg, GameConfig)
    assert cfg.name == "demo"
    assert cfg.display == "Demo"
    assert [c.id for c in cfg.cameras] == ["cam0"]
    assert [a.id for a in cfg.arms] == ["arm0"]
    assert cfg.policy.kind == "rule_based"
    assert cfg.runtime.rate_hz == 30.0  # default


def test_camera_arm_lookup(tmp_path: Path) -> None:
    cfg = load_manifest(_write(tmp_path, _MINIMAL))
    cam = cfg.camera_by_id("cam0")
    assert cam.device("sim")["source"] == "webcam"
    assert cam.device("real")["source"] == "usb"
    arm = cfg.arm_by_id("arm0")
    assert arm.backend("sim")["backend"] == "gazebo"
    assert arm.backend("real")["port"] == "/dev/ttyUSB0"


def test_extra_policy_options_are_preserved(tmp_path: Path) -> None:
    # _MINIMAL 은 0-인덴트 YAML 이고 policy 섹션이 2-스페이스 들여쓰기 — 같은 깊이로 이어붙인다.
    body = _MINIMAL + "  trajectory_map:\n    O: episode_0_trajectory.json\n    X: episode_1_trajectory.json\n"
    cfg = load_manifest(_write(tmp_path, body))
    assert cfg.policy.extra["trajectory_map"]["O"] == "episode_0_trajectory.json"


def test_runtime_overrides(tmp_path: Path) -> None:
    body = _MINIMAL + textwrap.dedent(
        """\
        runtime:
          rate_hz: 10
          episode_timeout_s: 5
        """
    )
    cfg = load_manifest(_write(tmp_path, body))
    assert cfg.runtime.rate_hz == 10.0
    assert cfg.runtime.episode_timeout_s == 5.0


def test_missing_required_fields(tmp_path: Path) -> None:
    body = """
    name: bad
    hardware: {}
    policy:
      kind: rule_based
      module: x
    """
    with pytest.raises(ManifestError, match=r"cameras 또는 hardware\.arms"):
        load_manifest(_write(tmp_path, body))


def test_duplicate_ids_rejected(tmp_path: Path) -> None:
    body = """
    name: bad
    hardware:
      cameras:
        - id: cam
          role: r
          sim:  { source: webcam }
          real: { source: usb }
        - id: cam
          role: r
          sim:  { source: webcam }
          real: { source: usb }
      arms: []
    policy:
      kind: rule_based
      module: x
    """
    with pytest.raises(ManifestError, match="중복"):
        load_manifest(_write(tmp_path, body))


def test_unknown_path_raises(tmp_path: Path) -> None:
    with pytest.raises(ManifestError):
        load_manifest(tmp_path / "missing.yaml")
