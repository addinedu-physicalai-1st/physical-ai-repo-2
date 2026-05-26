"""ACT (Action Chunking Transformer) 정책 어댑터.

lerobot 의 ACTPolicy 를 noriarm_framework 의 Policy 프로토콜에 맞춰 감싼다.

분리 이유:
  - lerobot 은 obs/action dict 의 키·shape 규약이 자기 데이터셋 schema 에 묶여 있다.
  - 우리는 obs.images / obs.joint_states 같은 일반화된 필드를 받으므로 변환 레이어
    가 필요하다.
  - lerobot 미설치 환경 (CI 등) 에서도 import 만큼은 성공해야 — 무거운 torch
    의존성을 lazy 로 미룬다.

체크포인트 다운로드는 본 모듈이 책임지지 않는다 — Control Server 의 부트스트랩이
미리 `huggingface_hub.snapshot_download` 로 받아둔다 (scripts/noriarm_check_models.py).
`from_pretrained(repo_id)` 호출 시 lerobot/hf_hub 가 캐시에서 즉시 로드.
"""
from __future__ import annotations

import logging
import math
import threading
from typing import Any

import numpy as np

from noriarm_framework.manifest import GameConfig
from noriarm_framework.policy import (
    Action,
    Actions,
    GameContext,
    Observation,
    Policy,
)

logger = logging.getLogger(__name__)


# lerobot 정규화 ↔ URDF 라디안 변환 — service/.../ros_bridge.py 의 _norm_to_rad 와 동일.
# m100_100: -100..100 → -π..π, range_0_100: 0..100 → -π..π, degrees: -180..180 → -π..π.
def _norm_to_rad(value: float, mode: str) -> float:
    if mode == "m100_100":
        return value * math.pi / 100
    if mode == "range_0_100":
        return (value - 50) * math.pi / 50
    if mode == "degrees":
        return value * math.pi / 180
    return float(value)  # unknown → identity


def _rad_to_norm(value: float, mode: str) -> float:
    if mode == "m100_100":
        return value * 100 / math.pi
    if mode == "range_0_100":
        return (value * 50 / math.pi) + 50
    if mode == "degrees":
        return value * 180 / math.pi
    return float(value)


class ACTPolicyAdapter(Policy):
    """lerobot ACTPolicy 를 noriarm_framework 의 Policy 로 wrap.

    상태:
      - 초기: 모델 로드 전, step() 은 IdleAction 반환.
      - 로드 완료 후: step() 이 obs 를 lerobot dict 로 변환, ACT chunk 의 첫 액션을
        JointTargetsAction (절대 joint 목표) 으로 돌려준다.

    `load_policy_async()` 가 백그라운드 스레드에서 호출되도록 설계 — 가위바위보
    재생 중 모델 가중치를 메모리·GPU 로 올린다.
    """

    def __init__(
        self,
        *,
        repo_id: str,
        joint_names: tuple[str, ...],
        camera_keys: tuple[str, ...] = ("top", "gripper"),
        device: str | None = None,
        joint_norm_modes: tuple[str, ...] | None = None,
    ) -> None:
        self._repo_id = repo_id
        self._joint_names = tuple(joint_names)
        # ACT 학습 데이터 단위 (lerobot 정규화). state 입력은 rad→norm, action 출력은
        # norm→rad 양방향 변환에 사용. None 이면 identity (이미 라디안이라 가정).
        self._joint_norm_modes = tuple(joint_norm_modes) if joint_norm_modes else None
        self._camera_keys = tuple(camera_keys)
        self._device = device  # None → lerobot 가 cuda → cpu fallback
        self._policy: Any = None
        # 동시 호출 보호 — 첫 caller 가 실제 로드, 후속 caller 는 Event 로 대기.
        # busy-wait 대신 OS 레벨 condition wait 으로 CPU 점유 0.
        self._load_lock = threading.Lock()
        self._load_started = False
        self._loaded_event = threading.Event()
        self._load_error: Exception | None = None

    # -------------------------------------------------- lifecycle
    def reset(self, ctx: GameContext) -> None:
        # lerobot 정책의 내부 step counter 등을 리셋.
        if self._policy is not None and hasattr(self._policy, "reset"):
            try:
                self._policy.reset()
            except Exception as e:  # noqa: BLE001
                logger.warning("ACTPolicy reset 실패 (무시): %s", e)

    def load_policy_async(self) -> threading.Thread:
        """백그라운드 스레드에서 모델 로드. caller 는 thread.join() 로 대기."""
        t = threading.Thread(target=self.load_policy_blocking, daemon=True)
        t.start()
        return t

    def load_policy_blocking(self) -> None:
        """동기 모델 로드. 동시 호출 안전:
          - 1st caller — 실제 from_pretrained 실행, 완료 시 Event set.
          - 2nd+ caller — Event.wait() 로 1st 완료 대기. 1st 가 실패했으면 동일 예외 re-raise.
          - 이미 로드 완료된 상태면 즉시 반환.

        주의: 로드 실패 시 `_load_error` 가 캐시되어, 이후 모든 호출
        (새로운 `load_policy_async` 포함) 이 동일 예외를 re-raise 한다.
        재시도하려면 새로운 `ACTPolicyAdapter` 인스턴스를 생성해야 한다.
        """
        with self._load_lock:
            if self._policy is not None:
                return
            if self._load_started:
                is_waiter = True
            else:
                self._load_started = True
                is_waiter = False
        if is_waiter:
            self._loaded_event.wait()
            if self._load_error is not None:
                raise self._load_error
            return
        # 1st caller — 실제 로드. lock 밖에서 — 다른 caller 가 lock 만 빠르게 잡고 waiter 로 빠지게.
        try:
            self._policy = _load_lerobot_act_policy(self._repo_id, self._device)
            logger.info(
                "ACTPolicy 로드 완료: repo=%s device=%s", self._repo_id, self._device
            )
        except Exception as e:
            self._load_error = e
            self._loaded_event.set()  # waiter 들도 깨워서 동일 예외를 받게.
            raise
        self._loaded_event.set()

    # -------------------------------------------------- 추론
    def step(self, obs: Observation) -> Action:
        if self._policy is None:
            return Actions.idle()
        # obs.state (라디안) → norm 변환해서 ACT 입력 분포와 일치시킨다.
        obs_normed = self._normalize_obs_state(obs)
        try:
            joint_target = _select_action(self._policy, obs_normed, self._camera_keys)
        except Exception as e:  # noqa: BLE001
            logger.exception("ACTPolicy step 실패: %s", e)
            return Actions.idle()
        n = len(self._joint_names)
        positions = np.asarray(joint_target[:n], dtype=np.float64)
        # ACT action (norm) → 라디안 변환. controller 는 라디안 받음.
        if self._joint_norm_modes is not None:
            positions = np.array(
                [
                    _norm_to_rad(positions[i], self._joint_norm_modes[i])
                    for i in range(n)
                ],
                dtype=np.float64,
            )
        return Actions.joint_targets(
            arm_id="pointer",
            joint_names=self._joint_names,
            positions=positions,
            duration_s=0.1,  # 30Hz 추론 루프 가정 — 다음 step 직전까지 이동.
        )

    def _normalize_obs_state(self, obs: Observation) -> Observation:
        """obs.joint_states 의 라디안 값을 norm 으로 변환한 새 Observation 반환."""
        if self._joint_norm_modes is None or not obs.joint_states:
            return obs
        modes = self._joint_norm_modes
        new_states: dict[str, np.ndarray] = {}
        for key, arr in obs.joint_states.items():
            a = np.asarray(arr, dtype=np.float64)
            n = min(len(a), len(modes))
            normed = np.array(
                [_rad_to_norm(a[i], modes[i]) for i in range(n)],
                dtype=np.float64,
            )
            if len(a) > n:
                normed = np.concatenate([normed, a[n:]])
            new_states[key] = normed
        # Observation 은 dataclass — replace 로 새 인스턴스 생성.
        from dataclasses import replace
        return replace(obs, joint_states=new_states)

    @property
    def loaded(self) -> bool:
        return self._policy is not None


def _load_lerobot_act_policy(repo_id: str, device: str | None) -> Any:
    """lerobot ACTPolicy.from_pretrained() — lazy import.

    lerobot 의 API 가 버전마다 흔들리므로 import 경로 + from_pretrained 시그니처는
    런타임 검증. 실패 시 명시적 RuntimeError.

    lerobot 0.5.x 기준: `lerobot.policies.act.modeling_act.ACTPolicy`
    (구 0.1.x 의 `lerobot.common.policies.act.modeling_act` 경로는 제거됨)
    """
    try:
        from lerobot.policies.act.modeling_act import ACTPolicy  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError(
            "lerobot.policies.act.modeling_act.ACTPolicy import 실패 — "
            "lerobot 설치 확인. pyproject.toml 의 lerobot 의존성 점검."
        ) from e
    kwargs: dict[str, Any] = {}
    if device:
        kwargs["device"] = device
    policy = ACTPolicy.from_pretrained(repo_id, **kwargs)
    if hasattr(policy, "eval"):
        policy.eval()
    return policy


def _select_action(policy: Any, obs: Observation, camera_keys: tuple[str, ...]) -> np.ndarray:
    """obs → lerobot batch dict → policy.select_action() → np.ndarray (joint targets).

    lerobot 의 select_action 은 torch tensor 를 받는다. 각 batch dict 키는 datasets
    의 OBS_IMAGES / OBS_STATE 규약을 따른다.
    모델이 CUDA 에 있으면 batch tensor 도 같은 device 로 이동한다.
    """
    import torch  # lazy

    # 모델의 device 를 감지 — parameter 가 있으면 그걸 기준으로.
    try:
        device = next(policy.parameters()).device
    except StopIteration:
        device = torch.device("cpu")

    batch: dict[str, Any] = {}
    if obs.images:
        for key in camera_keys:
            img = obs.images.get(key)
            if img is None:
                continue
            # HWC uint8 → CHW float32 / 255, batch=1.
            tensor = torch.from_numpy(img).float().permute(2, 0, 1).unsqueeze(0) / 255.0
            batch[f"observation.images.{key}"] = tensor.to(device)
    if obs.joint_states:
        state = next(iter(obs.joint_states.values()), None)
        if state is not None:
            batch["observation.state"] = (
                torch.from_numpy(np.asarray(state)).float().unsqueeze(0).to(device)
            )
    with torch.inference_mode():
        action = policy.select_action(batch)
    if hasattr(action, "cpu"):
        action = action.cpu().numpy()
    return np.asarray(action).reshape(-1)


def build_policy(config: GameConfig) -> Policy:
    extra = config.policy.extra or {}
    repo_id = extra.get("repo_id")
    if not repo_id:
        raise RuntimeError("policy_act.build_policy: 'repo_id' 가 매니페스트에 필요")
    joint_names = extra.get("joint_names")
    if not joint_names:
        raise RuntimeError("policy_act.build_policy: 'joint_names' 가 매니페스트에 필요")
    camera_keys = tuple(extra.get("camera_keys") or ("top", "gripper"))
    device = extra.get("device")
    # 학습 단위 — arm.sim 의 joint_norm_modes 차용 (예: [m100_100]*5 + [range_0_100]).
    arm = config.arms[0] if config.arms else None
    norm_modes = arm.sim.get("joint_norm_modes") if arm else None
    return ACTPolicyAdapter(
        repo_id=str(repo_id),
        joint_names=tuple(str(j) for j in joint_names),
        camera_keys=camera_keys,
        device=str(device) if device else None,
        joint_norm_modes=tuple(str(m) for m in norm_modes) if norm_modes else None,
    )


__all__ = ["ACTPolicyAdapter", "build_policy"]
