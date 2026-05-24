"""NoriArm 가게놀이 게임 — bimanual SmolVLA HTTP / ACT (TBD).

설계 결정 (block_stacking 과 다른 점):
  - ROS 우회. `runner_entry.py` 가 LeRobot BiOmxFollower (Dynamixel 직결) 와
    5090 `inference_server.py` 사이를 직접 다리 놓는다. 노리암 framework 의
    `GameRunner` / ROS publisher 경로 안 씀.
  - 이유: 학습 데이터 단위 (-100..100 motor `.pos`) ↔ ROS `/joint_states` (radian)
    불일치를 LeRobot 가 내부에서 이미 처리하는데, 직접 우회하면 변환 코드 0줄.
  - 따라서 `game.yaml` 의 arms·cameras 필드는 manifest 스키마 통과용 (load_manifest
    가 요구). 실제 카메라 디바이스 경로 / 모터 포트는 `runner_entry.py` 가 LeRobot
    BiOmxFollowerConfig 로 직접 들고 있다.

`game.yaml` 의 단일 진실원에서 GameConfig 를 로드해 노출한다 — control_service
라우터, runner_entry, 테스트가 모두 같은 인스턴스를 공유.
"""
from __future__ import annotations

import os
from functools import lru_cache
from importlib import resources

from noriarm_framework.manifest import GameConfig, load_manifest

# NORIARM_STOREPLAY_GAME_YAML 환경변수로 다른 manifest preset 선택 가능.
# 디폴트: game.yaml (SmolVLA HTTP, 노트북 inference_server 데몬 호출).
# 예: NORIARM_STOREPLAY_GAME_YAML=game_act_phase5_roi.yaml → ACT in-process + R11 ROI.
_ENV_GAME_YAML = "NORIARM_STOREPLAY_GAME_YAML"


@lru_cache(maxsize=1)
def load_store_play_config() -> GameConfig:
    """현재 활성 manifest 를 1 회 로드 후 캐시.

    파일명은 `NORIARM_STOREPLAY_GAME_YAML` env 로 override 가능 — 같은 패키지 디렉토리
    안의 `*.yaml` 만 허용 (보안: 외부 경로 차단). 미지정 시 'game.yaml'.
    """
    yaml_name = os.environ.get(_ENV_GAME_YAML, "game.yaml")
    # 패키지 디렉토리 외부 경로 차단 — basename 만 사용.
    yaml_name = os.path.basename(yaml_name)
    if not yaml_name.endswith(".yaml"):
        raise RuntimeError(
            f"{_ENV_GAME_YAML}={yaml_name!r} — '.yaml' 확장자 파일만 허용"
        )
    with resources.path(__name__, yaml_name) as p:
        return load_manifest(p)


def store_play_paraphrases() -> dict[str, list[str]]:
    """item id → 영어 paraphrase 리스트. game.yaml 의 policy.paraphrases 그대로."""
    cfg = load_store_play_config()
    raw = cfg.policy.extra.get("paraphrases") or {}
    if not isinstance(raw, dict):
        raise RuntimeError(
            "store_play/game.yaml policy.paraphrases 형식 오류 — dict 가 아님"
        )
    out: dict[str, list[str]] = {}
    for k, v in raw.items():
        if not isinstance(v, list) or not v:
            continue
        out[str(k)] = [str(p) for p in v]
    return out


def store_play_items() -> list[str]:
    """paraphrase 매니페스트에 정의된 item id 목록."""
    return sorted(store_play_paraphrases().keys())


def build_policy(config: GameConfig):
    """이 game 은 framework 의 정책 빌더 path 를 사용하지 않는다.

    `runner_entry.py` 가 LeRobot 표준 객체 (BiOmxFollower + inference_server HTTP)
    로 직접 추론한다. framework 의 `load_policy(config)` 가 이 함수를 부른다면
    설계 가정이 깨진 상황 — 에러 raise.
    """
    raise NotImplementedError(
        "store_play 는 BiOmxFollower 직결 path. framework load_policy 우회가 정상. "
        "이 함수가 호출됐다면 runner_entry 가 아닌 다른 곳에서 정책을 빌드하려 한 것 — 호출자 확인."
    )


__all__ = [
    "load_store_play_config",
    "store_play_paraphrases",
    "store_play_items",
    "build_policy",
]
