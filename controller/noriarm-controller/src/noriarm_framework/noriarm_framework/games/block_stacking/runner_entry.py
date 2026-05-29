"""블럭쌓기 서브프로세스 진입점 — LeRobot OmxFollower 직결, ROS 불필요.

흐름:
  1. ACT 모델 로드 + OmxFollower (카메라 포함) 연결
  2. stdout "READY" → Control Server 가 "START" 보냄
  3. 추론 루프 (30Hz): obs → ACT → send_action + 홈 복귀 감지
  4. 홈 복귀 감지 시: EVENT {"type": "home_event", "count": N}
  5. max_home_events 도달 또는 SIGTERM/SIGINT: robot.disconnect() → EXIT

홈 복귀 감지 알고리즘 (store_play 와 동일):
  - task 시작 포즈를 start_pose 로 저장.
  - move_thresh 이상 이탈 후 home_thresh 이내로 stable_frames 동안 유지되면 1회 카운트.
  - L∞ (관절별 절대편차 최댓값) — 특정 관절이 안 돌아왔는데 L2 평균만 작아서 종료하는 버그 방지.
  - 홈 감지 후 start_pose 를 현재 포즈로 갱신 — 다음 홈 감지 준비.
"""
from __future__ import annotations

import json
import logging
import signal
import sys
import threading
import time
from pathlib import Path

import numpy as np

logger = logging.getLogger("block_stacking.runner")

# OMX-F single arm — rps_player.py 의 모터 순서와 일치해야 함.
MOTOR_ORDER: tuple[str, ...] = (
    "shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos",
    "wrist_flex.pos", "wrist_roll.pos", "gripper.pos",
)

_ARM_PORT = "/dev/omx_follower"
_FRONT_CAM = "/dev/v4l/by-id/usb-Alcorlink_Corp._USB_2.0_Camera-video-index0"
_WRIST_CAM = "/dev/v4l/by-id/usb-Sonix_Technology_Co.__Ltd._USB_2.0_Camera_SN0001-video-index0"


# ================================================================= robot build

def _build_robot():
    from lerobot.cameras.opencv import OpenCVCameraConfig
    from lerobot.robots.omx_follower import OmxFollower
    from lerobot.robots.omx_follower.config_omx_follower import OmxFollowerConfig

    cameras = {
        "front": OpenCVCameraConfig(
            index_or_path=Path(_FRONT_CAM),
            width=640, height=480, fps=30, fourcc="MJPG",
        ),
        "wrist": OpenCVCameraConfig(
            index_or_path=Path(_WRIST_CAM),
            width=640, height=480, fps=30, fourcc="MJPG",
        ),
    }
    return OmxFollower(OmxFollowerConfig(port=_ARM_PORT, cameras=cameras))


def _obs_to_state_vec(obs: dict) -> list[float]:
    return [float(obs[k]) for k in MOTOR_ORDER]


# ================================================================ ACT provider

def _build_act_provider(config):
    """ACTPolicy 로드 → lerobot_record 와 동일한 pre/post processor 파이프라인.

    lerobot_record 의 실제 파이프라인:
      observation(numpy) → preprocessor → select_action → postprocessor → send_action
    preprocessor/postprocessor 없이 select_action 만 쓰면 역정규화가 빠져
    action 이 [-1..1] 범위로 나와 로봇이 중립 위치로 가서 멈춘다.
    """
    import torch
    from lerobot.policies.act.modeling_act import ACTPolicy  # type: ignore[import-not-found]
    from lerobot.policies.factory import make_pre_post_processors  # type: ignore[import-not-found]
    from lerobot.utils.control_utils import predict_action  # type: ignore[import-not-found]

    extra = config.policy.extra or {}
    repo_id = extra.get("repo_id")
    if not repo_id:
        raise RuntimeError("game.yaml policy.repo_id 누락")
    n_steps_override = extra.get("n_action_steps")
    temporal_coeff = extra.get("temporal_ensemble_coeff")
    task = str(extra.get("task") or "Game Block Stacking")

    device_str = str(extra.get("device") or "cuda")
    try:
        _dev = torch.device(device_str)
        if _dev.type == "cuda" and not torch.cuda.is_available():
            device_str = "cpu"
            logger.warning("CUDA 미사용 가능 — CPU fallback")
    except Exception:
        device_str = "cpu"
    device = torch.device(device_str)

    logger.info("ACT 모델 로드: repo=%s device=%s", repo_id, device_str)
    t0 = time.perf_counter()
    policy = ACTPolicy.from_pretrained(str(repo_id)).to(device).eval()
    if n_steps_override is not None:
        policy.config.n_action_steps = int(n_steps_override)
    if temporal_coeff is not None:
        policy.config.temporal_ensemble_coeff = float(temporal_coeff)
    
    logger.info("ACT 로드 완료 (%.1fs, n_action_steps=%d, temporal_coeff=%s)",
                time.perf_counter() - t0, policy.config.n_action_steps,
                policy.config.temporal_ensemble_coeff)

    preprocessor, postprocessor = make_pre_post_processors(
        policy_cfg=policy.config,
        pretrained_path=str(repo_id),
    )

    def reset() -> None:
        policy.reset()
        preprocessor.reset()
        postprocessor.reset()

    def provider(state: list[float], images: dict) -> list[float]:
        """단일 프레임 → 단일 action vector.
        observation 은 numpy dict 로 전달 — predict_action 이 내부에서
        prepare_observation_for_inference → preprocessor → select_action → postprocessor 수행.
        """
        observation: dict = {
            "observation.state": np.array(state, dtype=np.float32),
        }
        for key, img in images.items():
            if img is None:
                continue
            observation[f"observation.images.{key}"] = img  # HWC uint8 numpy

        action = predict_action(
            observation=observation,
            policy=policy,
            device=device,
            preprocessor=preprocessor,
            postprocessor=postprocessor,
            use_amp=False,
            task=task,
            robot_type="omx_follower",
        )
        return action.cpu().numpy().reshape(-1).tolist()

    provider.reset = reset  # type: ignore[attr-defined]
    return provider


# ================================================================= run loop

_SHUTDOWN = threading.Event()

# 홈 포즈 (m100_100 단위) — rps_paper_trajectory.json 첫/마지막 프레임과 동일
_HOME_POSE_M100 = [2.9785, -59.5703, 53.6621, 52.6855, 0.4395, 58.7402]


def _handle_sig(signum, frame) -> None:  # noqa: ARG001
    logger.info("signal %s — 종료 진행", signum)
    _SHUTDOWN.set()


def _go_home(robot, duration_s: float = 3.0) -> None:
    """현재 위치에서 홈 포즈로 선형 보간해 3초에 걸쳐 이동."""
    fps = 30
    steps = int(duration_s * fps)
    dt = 1.0 / fps
    try:
        obs = robot.get_observation()
        start = [float(obs[k]) for k in MOTOR_ORDER]
    except Exception:
        start = list(_HOME_POSE_M100)
    for i in range(1, steps + 1):
        t = i / steps
        action = {k: start[j] + (_HOME_POSE_M100[j] - start[j]) * t
                  for j, k in enumerate(MOTOR_ORDER)}
        try:
            robot.send_action(action)
        except Exception:
            break
        time.sleep(dt)


def _run(robot, provider, *, fps: int, episode_s: int, home_cfg: dict) -> None:
    """추론 루프. 홈 복귀 감지 시 stdout 으로 EVENT 발행."""
    dt = 1.0 / fps
    n_frames = fps * episode_s

    move_thresh = float(home_cfg.get("move_thresh", 40.0))
    home_thresh = float(home_cfg.get("home_thresh", 18.0))
    stable_frames = int(home_cfg.get("stable_frames", 15))
    max_home_events = int(home_cfg.get("max_home_events", 2))

    start_pose: np.ndarray | None = None
    moved_away = False
    home_count_frames = 0
    home_events = 0

    if callable(getattr(provider, "reset", None)):
        provider.reset()

    for i in range(n_frames):
        if _SHUTDOWN.is_set():
            break
        t0 = time.perf_counter()

        try:
            obs = robot.get_observation()
        except Exception as e:
            logger.warning("get_observation 실패 (frame %d): %s — skip", i, e)
            time.sleep(dt)
            continue

        state_vec = _obs_to_state_vec(obs)

        # ── 홈 복귀 감지 (L∞, store_play 알고리즘) ──
        cur = np.asarray(state_vec, dtype=np.float32)
        if start_pose is None:
            start_pose = cur.copy()
            logger.info("start_pose: %s", np.round(start_pose, 1).tolist())
        joint_dev = np.abs(cur - start_pose)
        max_dev = float(joint_dev.max())
        lag_i = int(joint_dev.argmax())
        if max_dev > move_thresh:
            moved_away = True
        if moved_away and max_dev < home_thresh:
            home_count_frames += 1
            if home_count_frames >= stable_frames:
                home_events += 1
                home_count_frames = 0
                moved_away = False
                start_pose = cur.copy()
                logger.info("홈 복귀 감지 #%d (frame=%d, max_dev=%.1f)", home_events, i, max_dev)
                print(f'EVENT {json.dumps({"type": "home_event", "count": home_events})}', flush=True)
                if home_events >= max_home_events:
                    logger.info("목표 홈 복귀 %d 회 완료 — 루프 종료", max_home_events)
                    print(f'EVENT {json.dumps({"type": "done"})}', flush=True)
                    break
        else:
            home_count_frames = 0
        if i % fps == 0:
            logger.info("frame=%d max_dev=%.1f@%s moved=%s hc=%d (move>%.0f home<%.0f)",
                        i, max_dev, MOTOR_ORDER[lag_i], moved_away,
                        home_count_frames, move_thresh, home_thresh)

        # ── ACT 추론 + send_action ──
        images = {
            "front": obs.get("front"),
            "wrist": obs.get("wrist"),
        }
        if any(v is None for v in images.values()):
            logger.warning("카메라 프레임 없음 (frame %d) — skip", i)
            time.sleep(dt)
            continue
        try:
            action_vec = provider(state_vec, images)
        except Exception as e:
            logger.warning("provider 실패 (frame %d): %s — retry", i, e)
            time.sleep(dt)
            continue
        if i % 30 == 0:
            logger.info("frame=%d inference OK, action=%s", i, [round(v, 1) for v in action_vec[:6]])

        action_dict = {k: float(v) for k, v in zip(MOTOR_ORDER, action_vec)}
        try:
            robot.send_action(action_dict)
        except Exception as e:
            logger.warning("send_action 실패 (frame %d): %s — 루프 종료", i, e)
            break

        elapsed = time.perf_counter() - t0
        if elapsed < dt:
            time.sleep(dt - elapsed)


# ================================================================= entry

def main() -> int:
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="[block_stacking.runner] %(message)s",
        stream=sys.stdout,
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--fps", type=int, default=None)
    parser.add_argument("--episode_s", type=int, default=None)
    args = parser.parse_args()

    from noriarm_framework.games.block_stacking import load_block_stacking_config
    config = load_block_stacking_config()

    # 1) ACT 모델 로드
    try:
        provider = _build_act_provider(config)
    except Exception as e:
        print(f"[block_stacking.runner] ACT 로드 실패: {e}", flush=True)
        return 3

    # 2) signal handlers — connect 전에 부착해서 어느 단계에서 종료돼도 처리
    signal.signal(signal.SIGTERM, _handle_sig)
    signal.signal(signal.SIGINT, _handle_sig)

    # 3) 로봇 + 카메라 연결
    logger.info("OmxFollower 연결 중...")
    robot = _build_robot()
    try:
        robot.connect()
    except Exception as e:
        print(f"[block_stacking.runner] robot.connect 실패: {e}", flush=True)
        return 4
    logger.info("OmxFollower 연결됨 (6 motors + 2 cameras)")

    # 4) READY → START 핸드셰이크
    print("READY", flush=True)
    line = sys.stdin.readline()
    if not line or line.strip() != "START":
        print(f"[block_stacking.runner] 예상 'START' 인데 {line.strip()!r} — 종료", flush=True)
        try:
            robot.disconnect()
        except Exception:
            pass
        return 2

    fps = args.fps if args.fps is not None else int(config.runtime.rate_hz)
    episode_s = args.episode_s if args.episode_s is not None else int(config.runtime.episode_timeout_s)
    home_cfg = config.policy.extra.get("home_detect") or {}
    logger.info("추론 시작 (fps=%d, episode_s=%d, home=%s)", fps, episode_s, home_cfg)

    # 5) 추론 루프
    try:
        _run(robot, provider, fps=fps, episode_s=episode_s, home_cfg=home_cfg)
        # SIGTERM(중간 종료)일 때만 홈 복귀 — 자연 종료(max_home_events)는 이미 홈에 있음
        if _SHUTDOWN.is_set():
            logger.info("중간 종료 — 홈 포즈로 복귀 중 (3초)...")
            _go_home(robot)
    finally:
        logger.info("disconnect 중...")
        try:
            robot.disconnect()
        except Exception:
            pass
        print("EXIT", flush=True)
        logger.info("종료")

    return 0


if __name__ == "__main__":
    sys.exit(main())
