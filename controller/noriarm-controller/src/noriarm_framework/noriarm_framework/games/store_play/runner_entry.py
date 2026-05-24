"""가게놀이 서브프로세스 진입점 — LeRobot BiOmxFollower 직결.

설계 (block_stacking 과 다른 점):
  - ROS 우회. BiOmxFollower (Dynamixel 직결) + OpenCVCamera 사용.
    학습 데이터 (`minssuung/store_play_v2_en`) 가 LeRobot motor `.pos` 단위로
    수집됨 → ROS `/joint_states` (radian) 거치면 단위 불일치. LeRobot 가 그 변환을
    이미 검증한 코드로 처리.
  - `policy.kind` 분기: SmolVLA HTTP (데몬) / ACT in-process — game.yaml 만 바꾸면 전환.

chunk_provider 인터페이스:
    provider(state: list[float], images: dict[str, np.ndarray], task: str) -> list[list[float]]
  - state: 12-dim float (left 6 + right 6, motor `.pos` 정규화)
  - images: {camera1/2/3: HWC uint8 RGB ndarray}  (LeRobot OpenCVCamera 기본 출력)
  - task: 영어 prompt — paraphrase 중 하나.

흐름:
  1. game.yaml 읽기 — policy.kind 에 따라 chunk_provider 빌드.
  2. (smolvla_http) /health probe / (act_local) ACTPolicy.from_pretrained 동기 로드.
  3. BiOmxFollower.connect() — Dynamixel + 카메라 3대.
  4. stdout "READY\\n" → Control Server 가 "START\\n" 보냄.
  5. loop (30Hz): obs → provider → action → BiOmxFollower.send_action.
  6. SIGTERM 시 robot.disconnect() (follower torque OFF) 후 종료.
"""
from __future__ import annotations

import argparse
import base64
import io
import logging
import os
import signal
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

import numpy as np

from noriarm_framework.games.store_play import load_store_play_config
from noriarm_framework.manifest import GameConfig

logger = logging.getLogger("store_play.runner")

_ENV_INFERENCE_URL = "NORIARM_STOREPLAY_INFERENCE_URL"

# 학습 데이터 motor 순서 — inference_server.py 의 MOTOR_ORDER 와 1:1.
MOTOR_ORDER: tuple[str, ...] = (
    "left_shoulder_pan.pos", "left_shoulder_lift.pos", "left_elbow_flex.pos",
    "left_wrist_flex.pos", "left_wrist_roll.pos", "left_gripper.pos",
    "right_shoulder_pan.pos", "right_shoulder_lift.pos", "right_elbow_flex.pos",
    "right_wrist_flex.pos", "right_wrist_roll.pos", "right_gripper.pos",
)

# game.yaml policy.camera_keys 와 1:1, inference_server expected_image_keys 와도 일치.
CAMERA_KEYS: tuple[str, ...] = ("camera1", "camera2", "camera3")

# 실물 카메라 udev symlink — game.yaml hardware.cameras 의 real.device 와 매칭.
_CAMERA_DEVICES: dict[str, str] = {
    "camera1": "/dev/cam_top",
    "camera2": "/dev/cam_wrist_left",
    "camera3": "/dev/cam_wrist_right",
}

# Chunk provider 타입 — state + raw RGB images + task → chunk (action sequence).
ChunkProvider = Callable[[list[float], dict[str, np.ndarray], str], list[list[float]]]


# ==================================================================== robot

def _build_robot():
    """LeRobot BiOmxFollower + OpenCV cameras 인스턴스 — run_remote_inference.py 와 동일."""
    from lerobot.cameras.opencv import OpenCVCameraConfig
    from lerobot.robots.bi_omx_follower import BiOmxFollower
    from lerobot.robots.bi_omx_follower.config_bi_omx_follower import (
        BiOmxFollowerConfig,
    )

    cameras = {
        key: OpenCVCameraConfig(
            index_or_path=Path(path),
            width=640,
            height=480,
            fps=30,
            fourcc="MJPG",
            warmup_s=5,
        )
        for key, path in _CAMERA_DEVICES.items()
    }
    cfg = BiOmxFollowerConfig(
        left_arm_port="/dev/omx_left_follower",
        right_arm_port="/dev/omx_right_follower",
        id="store_play_bimanual",
        cameras=cameras,
    )
    return BiOmxFollower(cfg)


def _obs_to_state_vec(obs: dict[str, Any]) -> list[float]:
    return [float(obs[k]) for k in MOTOR_ORDER]


def _action_vec_to_dict(action: list[float]) -> dict[str, float]:
    return {k: float(v) for k, v in zip(MOTOR_ORDER, action, strict=True)}


# =================================================== chunk providers (분기)

def _build_chunk_provider(config: GameConfig) -> ChunkProvider:
    """game.yaml policy.kind 보고 provider 빌드. 모델 로딩 (heavy I/O) 도 여기서."""
    kind = config.policy.kind
    if kind == "smolvla_http":
        return _make_smolvla_http_provider(config)
    if kind == "act_local":
        return _make_act_local_provider(config)
    raise NotImplementedError(
        f"store_play policy.kind={kind!r} 미지원. 'smolvla_http' 또는 'act_local' 만 가능."
    )


# -------------------------------------------------- smolvla HTTP (데몬)

def _make_smolvla_http_provider(config: GameConfig) -> ChunkProvider:
    """노트북 또는 5090 inference_server.py 의 /chunk 호출. 모델 로딩은 서버 책임."""
    import requests  # lazy

    extra = config.policy.extra or {}
    manifest_url = extra.get("inference_url")
    if not manifest_url:
        raise RuntimeError("smolvla_http: policy.inference_url 누락")
    env_url = os.environ.get(_ENV_INFERENCE_URL)
    server = (env_url or str(manifest_url)).rstrip("/")
    if env_url:
        logger.info("env %s 로 inference_url override: %s", _ENV_INFERENCE_URL, env_url)
    timeout_s = float(extra.get("request_timeout_s", 30.0))
    jpeg_quality = int(extra.get("jpeg_quality", 85))

    # 1회 health probe — 데몬이 떠있고 모델 로드 됐는지 확인. fail-fast.
    r = requests.get(f"{server}/health", timeout=5.0)
    r.raise_for_status()
    health = r.json()
    if not health.get("loaded"):
        raise RuntimeError(f"inference_server policy 미로드: {health}")
    logger.info("inference_server health OK: %s", health)

    def provider(state: list[float], images: dict[str, np.ndarray], task: str) -> list[list[float]]:
        images_b64 = {key: _encode_jpeg_b64(images[key], quality=jpeg_quality) for key in CAMERA_KEYS}
        resp = requests.post(
            f"{server}/chunk",
            json={"state": state, "images": images_b64, "task": task},
            timeout=timeout_s,
        )
        resp.raise_for_status()
        return resp.json()["actions"]

    return provider


def _encode_jpeg_b64(img: np.ndarray, *, quality: int) -> str:
    """HWC uint8 RGB ndarray → base64 JPEG. inference_server PIL convert RGB 와 호환."""
    from PIL import Image  # lazy

    if img.dtype != np.uint8:
        img = (
            (np.clip(img, 0, 1) * 255).astype(np.uint8)
            if img.max() <= 1.0
            else img.astype(np.uint8)
        )
    pil = Image.fromarray(img)
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")


# -------------------------------------------------- ACT in-process (노트북 GPU)

def _make_act_local_provider(config: GameConfig) -> ChunkProvider:
    """ACTPolicy.from_pretrained 동기 로드 후 in-process select_action.

    inference_server.py 의 predict_chunk 와 동일 로직. ACT 는 모델이 작아 (≤50M)
    노트북 GPU 4070 8GB 에 in-process 로 무난.
    """
    extra = config.policy.extra or {}
    repo_id = extra.get("repo_id")
    if not repo_id:
        raise RuntimeError("act_local: policy.repo_id 누락 (game.yaml policy 섹션)")
    device_str = str(extra.get("device") or "cuda")
    # 모델 학습 시 사용한 image key 와 hardware (CAMERA_KEYS) 의 매핑.
    # 학습 dataset 마다 컨벤션이 달라서 (v2_en phase5_roi 는 top/wrist_left/wrist_right,
    # 다른 학습본은 camera1/2/3) game.yaml 에서 명시. 미지정 시 camera 키 그대로 사용.
    raw_key_map = extra.get("image_key_map") or {}
    if not isinstance(raw_key_map, dict):
        raise RuntimeError("act_local: image_key_map 은 dict 여야 함")
    image_key_map: dict[str, str] = {
        str(k): str(v) for k, v in raw_key_map.items()
    } or {k: k for k in CAMERA_KEYS}

    # ROI masker — phase5_roi 학습본은 inference 시에도 동일 mask 처리 필요.
    # roi 섹션 있으면 활성화, 없으면 raw image 그대로 ACT 에 전달.
    roi_cfg = extra.get("roi")
    masker = None
    if roi_cfg:
        if not isinstance(roi_cfg, dict):
            raise RuntimeError("act_local: policy.roi 는 dict 여야 함")
        from noriarm_framework.games.store_play.roi_masker import build_roi_masker

        yolo_weights = roi_cfg.get("yolo_weights")
        if not yolo_weights:
            raise RuntimeError("act_local: roi.yolo_weights 누락")
        logger.info("ROI masker 로드 중: weights=%s", yolo_weights)
        masker = build_roi_masker(
            yolo_weights=str(yolo_weights),
            conf=float(roi_cfg.get("conf", 0.25)),
            iou=float(roi_cfg.get("iou", 0.5)),
            pad=int(roi_cfg.get("pad", 20)),
        )
        logger.info("ROI masker 로드 완료 — cam_policy 학습 코드와 동일 (top/wrist_left/wrist_right)")

    # heavy import 는 lazy — control_service venv import 부담 줄임.
    import torch
    from lerobot.policies.act.modeling_act import ACTPolicy  # type: ignore[import-not-found]
    from lerobot.policies.factory import make_pre_post_processors  # type: ignore[import-not-found]
    from lerobot.utils.control_utils import predict_action  # type: ignore[import-not-found]

    logger.info("ACT 모델 로드 중: repo=%s device=%s key_map=%s",
                repo_id, device_str, image_key_map)
    t0 = time.perf_counter()
    policy = ACTPolicy.from_pretrained(str(repo_id)).to(device_str).eval()
    preprocessor, postprocessor = make_pre_post_processors(
        policy_cfg=policy.config,
        pretrained_path=str(repo_id),
        preprocessor_overrides={"device_processor": {"device": device_str}},
    )
    n_chunk = int(policy.config.n_action_steps)
    device = torch.device(device_str)
    logger.info("ACT 로드 완료 (%.1fs, chunk_size=%d)", time.perf_counter() - t0, n_chunk)

    # 학습 모델이 기대하는 image 키 셋 검증 — 누락된 매핑 있으면 즉시 에러.
    expected_image_keys = {
        k for k in policy.config.input_features
        if k.startswith("observation.images.")
    }
    mapped_image_keys = {
        f"observation.images.{image_key_map.get(k, k)}" for k in CAMERA_KEYS
    }
    missing = expected_image_keys - mapped_image_keys
    if missing:
        raise RuntimeError(
            f"act_local: 모델이 기대하는 image 키 {sorted(missing)} 이 image_key_map 으로 "
            f"채워지지 않음. game.yaml policy.image_key_map 확인. 현재 매핑: {image_key_map}"
        )

    def provider(state: list[float], images: dict[str, np.ndarray], task: str) -> list[list[float]]:
        # 1) HW key (camera1/2/3) → 학습 모델 key (top/wrist_left/wrist_right) 매핑.
        remapped: dict[str, np.ndarray] = {
            image_key_map.get(hw_key, hw_key): images[hw_key] for hw_key in CAMERA_KEYS
        }
        # 2) ROI mask 적용 — phase5_roi 학습본이면 필수. 학습 데이터와 분포 일치 보장.
        if masker is not None:
            remapped = masker.mask_images(remapped, task)
        observation: dict[str, Any] = {
            "observation.state": np.asarray(state, dtype=np.float32),
        }
        for model_key, img in remapped.items():
            # HWC uint8 RGB ndarray — lerobot preprocessor 가 normalize/permute 처리.
            observation[f"observation.images.{model_key}"] = img
        chunk: list[list[float]] = []
        policy.reset()
        preprocessor.reset()
        postprocessor.reset()
        for _ in range(n_chunk):
            action = predict_action(
                observation,
                policy,
                device,
                preprocessor=preprocessor,
                postprocessor=postprocessor,
                use_amp=False,
                task=task,
            )
            chunk.append(action.detach().cpu().numpy().reshape(-1).tolist())
        return chunk

    return provider


# ============================================================ run loop

def _run_one_task(
    robot,
    provider: ChunkProvider,
    task: str,
    *,
    fps: int,
    episode_s: int,
) -> None:
    """단일 task — N frame 동안 obs → provider → action.

    종료 조건:
      - episode_s × fps frame 완료
      - _SHUTDOWN (SIGTERM/SIGINT) 또는 _ABORT_TASK (SIGUSR1) 신호
      - send_action 실패 (모터 에러)
    """
    queue: deque[list[float]] = deque()
    dt = 1.0 / fps
    n_frames = max(1, fps * episode_s)

    for i in range(n_frames):
        if _SHUTDOWN.is_set() or _ABORT_TASK.is_set():
            logger.info("task 중단 신호 — 루프 탈출 (frame %d/%d)", i, n_frames)
            break
        t0 = time.perf_counter()
        obs = robot.get_observation()

        if not queue:
            state_vec = _obs_to_state_vec(obs)
            images = {key: obs[key] for key in CAMERA_KEYS}
            try:
                t_inf = time.perf_counter()
                chunk = provider(state_vec, images, task)
                inf_ms = (time.perf_counter() - t_inf) * 1e3
            except Exception as e:
                logger.warning("chunk provider 실패 (frame %d): %s — 0.2s 후 retry", i, e)
                time.sleep(0.2)
                continue
            queue.extend(chunk)
            logger.info("chunk: %d actions, inference=%.0fms", len(chunk), inf_ms)

        action_vec = queue.popleft()
        try:
            robot.send_action(_action_vec_to_dict(action_vec))
        except Exception as e:
            logger.warning("send_action 실패 (frame %d): %s — task 종료", i, e)
            break

        loop_dt = time.perf_counter() - t0
        if loop_dt < dt:
            time.sleep(dt - loop_dt)


# ============================================================ signaling

# SIGTERM/SIGINT: 프로세스 전체 종료. SIGUSR1: 현재 task 만 중단 (idle 복귀).
_SHUTDOWN = None     # threading.Event — main() 에서 초기화
_ABORT_TASK = None   # threading.Event — main() 에서 초기화


def _handle_sigterm(signum, frame):  # noqa: ARG001
    print("[runner_entry] SIGTERM — 종료 진행", flush=True)
    if _SHUTDOWN is not None:
        _SHUTDOWN.set()
    if _ABORT_TASK is not None:
        _ABORT_TASK.set()  # 진행 중 task 도 같이 중단


def _handle_sigusr1(signum, frame):  # noqa: ARG001
    print("[runner_entry] SIGUSR1 — 현재 task 중단", flush=True)
    if _ABORT_TASK is not None:
        _ABORT_TASK.set()


# ============================================================ main

def main(argv: list[str] | None = None) -> int:
    """Long-lived runner — 1회 spawn 후 stdin 명령으로 여러 task 수행.

    프로토콜:
      [Control Server → runner]   stdin 명령:
        - "START\\n"           최초 1회 — 모델/로봇 로드 후 명령 모드 진입.
        - "PROMPT <task>\\n"   새 task 시작 (예: "PROMPT give me strawberry").
        - "QUIT\\n"            cleanly disconnect 후 종료.
      [runner → Control Server]   stdout 출력:
        - "READY\\n"           모델/로봇 다 load 됐고 START 대기.
        - "TASK_DONE\\n"       방금 task 끝남 — 다음 PROMPT 대기.
        - "EXIT\\n"            disconnect 끝나고 종료 직전.
      [Control Server → runner]   시그널:
        - SIGUSR1              진행 중 task 중단 → TASK_DONE 출력 → 다시 PROMPT 대기.
        - SIGTERM/SIGINT       전체 종료 (cleanly disconnect 시도).
    """
    import threading

    global _SHUTDOWN, _ABORT_TASK
    _SHUTDOWN = threading.Event()
    _ABORT_TASK = threading.Event()

    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=("sim", "real"), default="real",
                        help="real: BiOmxFollower 직결. sim: 미지원 (TODO).")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--episode_s", type=int, default=60,
                        help="task 1회 최대 시간 (s). 정책이 종료 신호 안 보내면 강제 cut.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="[runner_entry] %(message)s",
        stream=sys.stdout,
    )

    if args.target != "real":
        print(
            f"[runner_entry] target={args.target} 미지원 (BiOmxFollower 는 real 만).",
            flush=True,
        )
        return 2

    config = load_store_play_config()

    # 1) chunk provider 빌드 (모델 로드 / health probe 포함 — 시간 걸리는 단계, 1회만).
    try:
        provider = _build_chunk_provider(config)
    except Exception as e:
        print(f"[runner_entry] chunk_provider 빌드 실패: {e}", flush=True)
        return 3

    # 2) 로봇 연결 (1회만 — 양팔 + 카메라 3대).
    logger.info("BiOmxFollower 연결 중...")
    robot = _build_robot()
    try:
        robot.connect()
    except Exception as e:
        print(f"[runner_entry] robot.connect 실패: {e}", flush=True)
        return 4
    logger.info("BiOmxFollower 연결됨 (12 motors + 3 cameras)")

    # 3) READY → Control Server 가 START 보냄 (초기 핸드셰이크 1회).
    print("READY", flush=True)
    line = sys.stdin.readline()
    if not line or line.strip() != "START":
        print(f"[runner_entry] 예상 'START' 인데 {line.strip()!r} 받음 — 종료", flush=True)
        try:
            robot.disconnect()
        except Exception:
            pass
        return 2

    # 4) signal handlers — START 직후 부착 (그 전엔 default 동작).
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)
    signal.signal(signal.SIGUSR1, _handle_sigusr1)

    logger.info("idle — PROMPT 대기 (kind=%s)", config.policy.kind)

    # 5) 명령 loop — PROMPT 받을 때마다 task 1회 실행.
    try:
        while not _SHUTDOWN.is_set():
            line = sys.stdin.readline()
            if not line:  # parent died / pipe closed
                logger.info("stdin EOF — 종료")
                break
            cmd = line.strip()
            if not cmd:
                continue
            if cmd == "QUIT":
                logger.info("QUIT 명령 — 종료")
                break
            if cmd.startswith("PROMPT "):
                task = cmd[len("PROMPT "):].strip()
                if not task:
                    logger.warning("PROMPT 명령 빈 task — 무시")
                    continue
                _ABORT_TASK.clear()  # 새 task 시작 — abort flag 리셋
                logger.info("task 시작: %r", task)
                t0 = time.perf_counter()
                _run_one_task(robot, provider, task, fps=args.fps, episode_s=args.episode_s)
                logger.info("task 종료: %r (%.1fs)", task, time.perf_counter() - t0)
                print("TASK_DONE", flush=True)
            else:
                logger.warning("알 수 없는 명령: %r — 무시", cmd)
    finally:
        try:
            robot.disconnect()
            logger.info("robot disconnect (follower torque OFF)")
        except Exception as e:
            logger.warning("disconnect 예외 (무시): %s", e)

    print("EXIT", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
