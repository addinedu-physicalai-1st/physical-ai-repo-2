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
import json
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

# UI 미리보기 — runner 가 카메라를 V4L2 점유하므로 브라우저가 직접 못 잡음.
# ROI masked 프레임을 5fps 로 /tmp 에 JPEG 저장 → control_service /preview/{cam} 이 서빙.
# (rerun 으로 대체 가능하지만 dev 의 control_service 가 이 파일을 읽으므로 호환 유지.)
_PREVIEW_DIR = "/tmp"
_PREVIEW_PREFIX = "storeplay_preview"
_PREVIEW_INTERVAL_S = 0.2  # 5fps
_preview_last_write: list[float] = [0.0]


def _save_preview(images_rgb: dict[str, np.ndarray]) -> None:
    """ROI masked RGB 프레임을 5fps throttle 로 /tmp 에 JPEG 저장 (UI 미리보기).
    실패해도 추론 무관. 키는 모델 cam key (top/wrist_left/wrist_right).
    control_service.noriarm.store_play 의 /sessions/{sid}/preview/{cam} endpoint 가 이 JPG 를 서빙.
    """
    now = time.monotonic()
    if now - _preview_last_write[0] < _PREVIEW_INTERVAL_S:
        return
    _preview_last_write[0] = now
    try:
        import cv2

        for cam, img in images_rgb.items():
            bgr = img[:, :, ::-1]  # RGB → BGR (cv2.imwrite 는 BGR 기대)
            tmp = f"{_PREVIEW_DIR}/.{_PREVIEW_PREFIX}_{cam}.tmp.jpg"
            dst = f"{_PREVIEW_DIR}/{_PREVIEW_PREFIX}_{cam}.jpg"
            # 임시 파일에 쓴 뒤 atomic rename — control_service 가 부분 쓰기 읽는 것 방지.
            if cv2.imwrite(tmp, bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 70]):
                os.replace(tmp, dst)
    except Exception:
        pass


# rerun 시각화 — 모델이 보는 ROI masked 프레임 + 관절상태 + 게이트 상태를 네이티브
# rerun 창에 스트리밍. runner 1 프로세스당 1회 spawn (DISPLAY 필요). 실패해도 추론 무관.
_RR_ON: list[bool] = [False]
# rerun 로깅 throttle — 매 frame 카메라 3장 풀 전송하면 CPU/RAM 폭주(뷰어 14GB+, provider
# 40→100ms)라서 모니터링용으로 ~5fps 만. 추론 루프(30Hz)는 그대로, rerun 만 솎아냄.
_RR_INTERVAL_S = 0.033  # ~30fps 풀로깅. 뷰어 부담 큼 — 떨림 / spike 늘면 0.1 로 복귀.
_rr_last: list[float] = [0.0]


def _rr_init() -> None:
    """rerun 네이티브 뷰어 spawn + 연결 (runner 당 1회). 실패 시 조용히 비활성 — 추론은 계속.
    memory_limit 로 뷰어 RAM 상한 — 안 걸면 history 누적으로 수십 GB 까지 부풀어 CPU 포화."""
    try:
        import rerun as rr

        rr.init("storeplay_inference")
        rr.spawn(memory_limit="2GB")  # 네이티브 뷰어 창 (DISPLAY 필요), RAM 상한 2GB
        _RR_ON[0] = True
        logger.info("rerun 뷰어 spawn 완료 — cam/state/status 스트리밍 (~10fps throttle)")
    except Exception as e:
        logger.warning("rerun 비활성 (spawn 실패: %s) — 추론은 계속", e)


def _rr_log(seq: int, masked: dict[str, np.ndarray] | None, state, status: str, detected) -> None:
    """ROI masked 프레임(모델 입력) + 관절상태 + 상태텍스트를 rerun 에 로그. _RR_ON 일 때만.
    masked 키는 모델 cam key (top/wrist_left/wrist_right), RGB HWC uint8.
    """
    if not _RR_ON[0]:
        return
    now = time.monotonic()
    if now - _rr_last[0] < _RR_INTERVAL_S:  # ~5fps throttle — CPU/RAM 보호
        return
    _rr_last[0] = now
    try:
        import rerun as rr

        rr.set_time("frame", sequence=seq)
        for cam, img in (masked or {}).items():
            rr.log(f"cam/{cam}", rr.Image(img))  # RGB
        if state is not None:
            for name, v in zip(MOTOR_ORDER, state, strict=False):
                rr.log(f"state/{name}", rr.Scalars(float(v)))
        det = sorted(detected) if detected else []
        rr.log("status", rr.TextLog(f"{status} | detected={det}"))
    except Exception:
        pass

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
            # warmup_s 작게 — connect 후 모델로드+wake+홈+핸드셰이크로 10s+ 스트리밍하며
            # 노출 자동 안정화됨. 5s×3 순차(=15s) 는 부팅의 최대 죽은시간이라 1.5s 로 단축.
            warmup_s=1.5,
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


# ──────────────────────────── wake 모션 (부팅 애니메이션) ────────────────────────────
# 모델 로드(추론 준비) 동안 녹화 trajectory 를 백그라운드로 루프 재생 → 준비되면 home 이동.
# trajectory 는 scripts/record_wake_trajectory.py 로 녹화한 npz {poses:(N,12), fps}.

def _arm_state_vec(robot) -> list[float]:
    """카메라 없이 양팔 관절 pose 만 읽어 MOTOR_ORDER 12-vec 반환.
    wake 모션은 팔 연결 직후(카메라 미연결) 시작하므로 get_observation(카메라 포함) 대신 사용."""
    obs: dict[str, Any] = {}
    obs.update({f"left_{k}": v for k, v in robot.left_arm.get_observation().items()})
    obs.update({f"right_{k}": v for k, v in robot.right_arm.get_observation().items()})
    return [float(obs[k]) for k in MOTOR_ORDER]


# 카메라 read 병렬화용 스레드풀 (3대 async_read 동시 호출 — bg thread 대기 누적 제거).
# BiOmxFollower.get_observation 은 팔 → 3캠 순차라 누적 대기로 ~40ms. 3캠을 동시에 부르면
# max(개별 대기)로 줄어 ~15ms 절감. 팔 read 는 빠르고 순차로 두고, 카메라만 병렬.
_cam_pool: Any | None = None  # ThreadPoolExecutor — 첫 호출 시 lazy 생성

def _fast_get_observation(robot) -> dict[str, Any]:
    """robot.get_observation 의 카메라 병렬 read 버전. dict format 은 동일.
    팔: 순차 (빠름). 카메라 3대: ThreadPoolExecutor 로 동시 async_read."""
    global _cam_pool
    if _cam_pool is None:
        from concurrent.futures import ThreadPoolExecutor
        _cam_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="cam-read")
    obs: dict[str, Any] = {}
    obs.update({f"left_{k}": v for k, v in robot.left_arm.get_observation().items()})
    obs.update({f"right_{k}": v for k, v in robot.right_arm.get_observation().items()})
    # 카메라 3대 동시 read
    futures = {key: _cam_pool.submit(cam.async_read) for key, cam in robot.cameras.items()}
    for key, fut in futures.items():
        obs[key] = fut.result()
    return obs


def _load_wake_traj(cfg: dict) -> tuple[np.ndarray | None, int]:
    """wake_motion config 에서 trajectory 로드. (poses Nx12, fps). 없으면 (None, 30)."""
    fps = int(cfg.get("fps", 30)) if cfg else 30
    if not cfg or not cfg.get("enabled"):
        return None, fps
    path = cfg.get("trajectory_path")
    if not path or not Path(path).exists():
        logger.warning("wake 모션 trajectory 파일 없음 (%s) — 모션 스킵, home 이동만", path)
        return None, fps
    try:
        d = np.load(path)
        poses = np.asarray(d["poses"], dtype=np.float32)
        if "fps" in d:
            fps = int(d["fps"])
        if poses.ndim != 2 or poses.shape[1] != len(MOTOR_ORDER):
            logger.warning("wake trajectory shape 이상 %s — 스킵", poses.shape)
            return None, fps
        return poses, fps
    except Exception as e:
        logger.warning("wake trajectory 로드 실패: %s — 스킵", e)
        return None, fps


# 모터 버스에 per-step 이동 상한(max_relative_target)이 없어서(=None), wake/home 이동의
# 부드러움은 전적으로 _ramp 의 step 크기에 의존. 관절당 한 frame 이동을 이 값으로 cap —
# 멀리 이동해도(임의 위치→home) step 을 늘려 항상 느리고 부드럽게. (추론 serve 는 _ramp 안 씀)
_WAKE_MAX_STEP_DELTA = 2.5  # 관절 단위/frame (@30Hz ≈ 75/s 상한)


def _ramp(robot, start: np.ndarray, end: np.ndarray, n_steps: int, dt: float,
          stop_event=None) -> None:
    """start→end 선형 보간 송신 (부드러운 이동, jerk 방지). 관절당 per-step 이동이
    _WAKE_MAX_STEP_DELTA 를 넘지 않도록 n_steps 를 거리에 맞게 자동 증가 (먼 이동=느리게)."""
    max_delta = float(np.abs(end - start).max())
    min_steps = int(np.ceil(max_delta / _WAKE_MAX_STEP_DELTA)) if max_delta > 0 else 1
    n_steps = max(1, n_steps, min_steps)
    for s in range(1, n_steps + 1):
        if (stop_event is not None and stop_event.is_set()) or (
            _SHUTDOWN is not None and _SHUTDOWN.is_set()
        ):
            return
        a = s / n_steps
        pose = (1.0 - a) * start + a * end
        t0 = time.perf_counter()
        robot.send_action(_action_vec_to_dict(pose.tolist()))
        el = time.perf_counter() - t0
        if el < dt:
            time.sleep(dt - el)


def _play_wake_motion(robot, traj: np.ndarray, fps: int, stop_event) -> None:
    """trajectory 루프 재생 (stop_event 까지). 시작 시 현재→traj[0] 부드럽게 ramp.
    별도 스레드에서 실행 — 모델 로드 중 모터 serial 은 이 스레드만 접근 (동시 접근 없음).
    예외는 삼켜서 부팅을 막지 않음."""
    dt = 1.0 / max(1, fps)
    try:
        def _stopped() -> bool:
            return stop_event.is_set() or (_SHUTDOWN is not None and _SHUTDOWN.is_set())

        cur = np.asarray(_arm_state_vec(robot), dtype=np.float32)  # 카메라 없이 팔 pose
        _ramp(robot, cur, traj[0], fps, dt, stop_event)  # 현재→첫 frame (부드럽게)
        while not _stopped():
            for pose in traj:
                if _stopped():
                    break
                t0 = time.perf_counter()
                robot.send_action(_action_vec_to_dict(pose.tolist()))
                el = time.perf_counter() - t0
                if el < dt:
                    time.sleep(dt - el)
    except Exception as e:
        logger.warning("wake 모션 재생 중 예외 (무시): %s", e)


def _move_to_home(robot, home_pose: np.ndarray, *, fps: int, move_s: float) -> None:
    """현재 pose → home_pose 부드럽게 이동 (보간). 추론 준비 완료 후 호출."""
    try:
        cur = np.asarray(_arm_state_vec(robot), dtype=np.float32)
        _ramp(robot, cur, home_pose, max(1, int(fps * move_s)), 1.0 / max(1, fps))
        logger.info("홈 포지션 이동 완료")
    except Exception as e:
        logger.warning("홈 이동 실패 (무시): %s", e)


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
    # closed-loop 재추론 주기. game.yaml n_action_steps (없으면 모델 chunk_size).
    # roi_inference.py 와 동일하게 매 frame predict_action 호출하되, lerobot 가
    # n_action_steps 마다만 실제 추론하고 그 사이는 캐시 action 을 pop.
    # temporal_ensemble_coeff 가 설정되면 n_action_steps=1 강제 + ACTTemporalEnsembler 수동 생성
    # (roi_inference.py 와 동일). 액션을 시간평균(지수가중)해서 떨림 줄임 — 0.01=강한 smoothing.
    tec = extra.get("temporal_ensemble_coeff")
    if tec is not None:
        from lerobot.policies.act.modeling_act import ACTTemporalEnsembler
        policy.config.temporal_ensemble_coeff = float(tec)
        policy.config.n_action_steps = 1   # temporal ensemble 은 매 step 추론 필수
        policy.temporal_ensembler = ACTTemporalEnsembler(
            float(tec), policy.config.chunk_size,
        )
        policy.reset()
        n_action_steps = 1
        logger.info("temporal_ensemble_coeff=%.3f 활성 → n_action_steps=1 강제, chunk_size=%d",
                    float(tec), policy.config.chunk_size)
    else:
        # closed-loop 재추론 주기. game.yaml n_action_steps (없으면 모델 chunk_size).
        n_action_steps = int(extra.get("n_action_steps") or policy.config.n_action_steps)
        policy.config.n_action_steps = n_action_steps
    preprocessor, postprocessor = make_pre_post_processors(
        policy_cfg=policy.config,
        pretrained_path=str(repo_id),
        preprocessor_overrides={"device_processor": {"device": device_str}},
    )
    device = torch.device(device_str)
    chunk_size = getattr(policy.config, "chunk_size", n_action_steps)
    logger.info("ACT 로드 완료 (%.1fs, chunk_size=%d, n_action_steps=%d → %.2fs 마다 재추론)",
                time.perf_counter() - t0, chunk_size, n_action_steps, n_action_steps / 30.0)

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

    def _reset() -> None:
        """새 task(PROMPT) 시작 시 호출 — lerobot 내부 action queue / processor 초기화.
        직전 episode 의 stale 캐시 action 이 새 episode 첫 ~1초간 실행되는 것 방지.
        """
        policy.reset()
        preprocessor.reset()
        postprocessor.reset()

    def provider(state: list[float], images: dict[str, np.ndarray], task: str) -> list[list[float]]:
        # 1) HW key (camera1/2/3) → 학습 모델 key (top/wrist_left/wrist_right) 매핑.
        remapped: dict[str, np.ndarray] = {
            image_key_map.get(hw_key, hw_key): images[hw_key] for hw_key in CAMERA_KEYS
        }
        # 2) ROI mask 적용 — phase5_roi 학습본이면 필수. 매 frame 갱신 (closed-loop).
        if masker is not None:
            remapped = masker.mask_images(remapped, task)
            provider.last_detected = masker.last_detected  # runner 가 missing 판단에 사용.
            provider.last_masked = remapped  # rerun 로깅용 (loop 에서 _rr_log 가 읽음).
        # 2.5) UI 미리보기 — control_service /preview/{cam} endpoint 가 읽는 JPG (5fps).
        _save_preview(remapped)
        observation: dict[str, Any] = {
            "observation.state": np.asarray(state, dtype=np.float32),
        }
        for model_key, img in remapped.items():
            # HWC uint8 RGB ndarray — lerobot preprocessor 가 normalize/permute 처리.
            observation[f"observation.images.{model_key}"] = img
        # 3) predict_action 1회 — lerobot 가 n_action_steps 마다만 실제 추론, 그 외 캐시 pop.
        #    1 action 반환 → run loop 가 매 frame provider 재호출 = closed-loop.
        action = predict_action(
            observation,
            policy,
            device,
            preprocessor=preprocessor,
            postprocessor=postprocessor,
            use_amp=False,
            task=task,
        )
        return [action.detach().cpu().numpy().reshape(-1).tolist()]

    def detect(images: dict[str, np.ndarray], task: str) -> set:
        """게이트용 — ROI mask 만 돌려 YOLO 검출 class 갱신 (ACT 미실행, 가벼움).
        검출된 class 집합 반환. last_masked 도 갱신(rerun 로깅용)."""
        if masker is None:
            return set()
        remapped = {
            image_key_map.get(hw_key, hw_key): images[hw_key] for hw_key in CAMERA_KEYS
        }
        remapped = masker.mask_images(remapped, task)
        provider.last_detected = masker.last_detected
        provider.last_masked = remapped
        _save_preview(remapped)  # 게이트 중에도 UI 미리보기 갱신
        return masker.last_detected

    # _run_one_task 가 task 시작 시 호출 — PROMPT 마다 무조건 reset (동일 prompt 연속도 포함).
    provider.detect = detect  # type: ignore[attr-defined]  # 게이트 검출용 (ACT 미실행)
    provider.reset = _reset  # type: ignore[attr-defined]
    # runner 가 missing(target/plate 미검출) 판단에 읽음. masker 있을 때만 갱신.
    provider.last_detected = set()  # type: ignore[attr-defined]
    provider.last_masked = {}  # type: ignore[attr-defined]  # rerun 로깅용 직전 masked 프레임
    provider.roi_active = masker is not None  # type: ignore[attr-defined]
    return provider


# ============================================================ run loop

def _run_one_task(
    robot,
    provider: ChunkProvider,
    task: str,
    *,
    fps: int,
    episode_s: int,
    home: dict[str, float] | None = None,
    bell: dict | None = None,
    gate: dict | None = None,
) -> None:
    """단일 task — obs → provider → action 루프.

    종료 조건:
      - 홈 복귀 감지 (서빙 후 시작 pose 로 복귀) — 정상 완료
      - episode_s × fps frame 완료 (홈 복귀 못 했을 때 safety cut)
      - _SHUTDOWN (SIGTERM/SIGINT) 또는 _ABORT_TASK (SIGUSR1) 신호
      - send_action 실패 (모터 에러)

    홈 복귀 감지: 학습 데이터가 "홈 시작 → 서빙(이탈) → 홈 복귀" 패턴 (분석 결과
    복귀율 100%, start→end 거리 평균 6.6 vs 최대 이탈 160). task 시작 pose 를 홈으로
    잡고, move_thresh 이상 이탈 후 home_thresh 이내로 stable_frames 동안 유지되면 완료.
    """
    queue: deque[list[float]] = deque()
    dt = 1.0 / fps
    n_frames = max(1, fps * episode_s)

    # 홈 복귀 감지 파라미터 (game.yaml runtime.home_detect, 없으면 실측 디폴트).
    h = home or {}
    move_thresh = float(h.get("move_thresh", 40.0))    # 이만큼 벗어나야 "이탈" 인정
    home_thresh = float(h.get("home_thresh", 18.0))    # 이 이내면 "홈"
    stable_frames = int(h.get("stable_frames", 15))    # 홈 유지 frame 수 (0.5s @30fps)
    home_enabled = bool(h.get("enabled", True))

    start_pose: np.ndarray | None = None
    moved_away = False
    home_count = 0

    # 카메라 일시 끊김(USB 대역폭 글리치 → Corrupt JPEG / async_read TimeoutError) 내성.
    # 한 frame 의 get_observation 실패로 task 전체가 죽지 않게 skip+retry. 단 연속
    # CAM_FAIL_ABORT frame(=3s) 끊기면 진짜 카메라 다운으로 보고 task 종료(60s 무한 skip 방지).
    cam_fail = 0
    CAM_FAIL_ABORT = fps * 3

    # ── 추론 루프 timing stats (1초마다 집계 → 로그) ──
    # loop_dt = obs+provider+send_action 한 사이클 시간. 30Hz 면 target dt=33.3ms.
    # over_budget = 33.3ms 초과 frame 수. fps_actual = 실제 처리율 (sleep 포함 평균).
    loop_max_ms = 0.0
    loop_sum_s = 0.0
    over_budget = 0
    last_inf_ms = 0.0  # 마지막 provider 시간 (chunk 사이엔 같은 값 유지)

    # 벨 누름 감지 — bell_pose 근접 시 EVENT bell_rung (task 당 1회) → UI "주문 나왔습니다".
    b = bell or {}
    bell_enabled = bool(b.get("enabled", False))
    bell_pose = (
        np.asarray(b["pose"], dtype=np.float32)
        if bell_enabled and b.get("pose") else None
    )
    bell_thresh = float(b.get("thresh", 14.0))
    bell_rung = False

    # target(과일) class — 서빙 시작 게이트가 접시와 함께 검출 확인에 사용. ACT+roi 일 때만.
    from noriarm_framework.games.store_play.roi_masker import prompt_to_target
    roi_active = bool(getattr(provider, "roi_active", False))
    target_cls = prompt_to_target(task) if roi_active else None

    # task 시작 시 정책 reset — 이전 episode 의 stale action queue 제거 (closed-loop 정합).
    reset_fn = getattr(provider, "reset", None)
    if callable(reset_fn):
        reset_fn()

    # ── 서빙 시작 게이트 (start-only) — 접시+target 둘 다 검출될 때까지 robot 정지(hold) ──
    # 사용자 요청: 접시/객체 안 보이면 "보일 때까지 강제로 못 움직이게". roi_active + target +
    # gate.enabled 일 때만. 게이트 중엔 send_action 안 함 → torque on 으로 home 유지. 검출되면
    # EVENT gate_ready 로 UI 배너 해제 후 서빙 루프 진입. 서빙 중 occlusion 은 게이트 안 함.
    detect_fn = getattr(provider, "detect", None)
    if roi_active and target_cls and gate and gate.get("enabled", True) and callable(detect_fn):
        gate_stable = int(gate.get("stable_frames", 5))
        ready_count = 0
        last_missing: list | None = None
        gate_aborted = False
        gi = 0
        while gi < n_frames:  # 안전 cap = episode_s. 평소엔 검출되면 즉시 통과.
            if _SHUTDOWN.is_set() or _ABORT_TASK.is_set():
                logger.info("gate 중 중단 신호 — 탈출")
                gate_aborted = True
                break
            t0 = time.perf_counter()
            try:
                obs = _fast_get_observation(robot)
            except Exception as e:
                cam_fail += 1
                logger.warning("gate get_observation 실패 (연속 %d): %s", cam_fail, e)
                if cam_fail >= CAM_FAIL_ABORT:
                    logger.error("gate: 카메라 연속 끊김 — task 종료")
                    gate_aborted = True
                    break
                time.sleep(dt)
                continue
            cam_fail = 0
            images = {k: obs[k] for k in CAMERA_KEYS}
            detected = detect_fn(images, task)
            missing = [c for c in (target_cls, "plate") if c not in detected]
            _rr_log(gi, getattr(provider, "last_masked", {}), _obs_to_state_vec(obs),
                    "GATE 대기" if missing else "GATE 통과", detected)
            if not missing:
                ready_count += 1
                if ready_count >= gate_stable:
                    logger.info("gate 통과 — 접시+%s 검출 → 서빙 시작", target_cls)
                    print(f'EVENT {json.dumps({"type": "gate_ready"})}', flush=True)
                    break
            else:
                ready_count = 0
                if missing != last_missing:  # 변할 때만 emit (throttle)
                    last_missing = missing
                    logger.info("gate 대기 — 미검출: %s", missing)
                    print(f'EVENT {json.dumps({"type": "gate_waiting", "missing": missing})}', flush=True)
            gi += 1
            loop_dt = time.perf_counter() - t0
            if loop_dt < dt:
                time.sleep(dt - loop_dt)
        if gate_aborted:
            return
        if gi >= n_frames:
            logger.warning("gate timeout (%ds) — 접시/target 끝내 미검출, task 종료", episode_s)
            print(f'EVENT {json.dumps({"type": "gate_timeout"})}', flush=True)
            return

    for i in range(n_frames):
        if _SHUTDOWN.is_set() or _ABORT_TASK.is_set():
            logger.info("task 중단 신호 — 루프 탈출 (frame %d/%d)", i, n_frames)
            break
        t0 = time.perf_counter()
        try:
            obs = _fast_get_observation(robot)
        except Exception as e:
            cam_fail += 1
            logger.warning("get_observation 실패 (frame %d, 연속 %d): %s — frame skip",
                           i, cam_fail, e)
            if cam_fail >= CAM_FAIL_ABORT:
                logger.error("카메라 %d frame(=%.0fs) 연속 끊김 — task 종료", cam_fail, CAM_FAIL_ABORT / fps)
                break
            time.sleep(dt)
            continue
        cam_fail = 0  # 성공 시 연속 실패 카운터 리셋
        state_vec = _obs_to_state_vec(obs)

        # ── 홈 복귀 감지 (per-joint L∞) ──
        # L2 는 큰 관절(어깨·팔꿈치)이 지배해서, 손목/그리퍼 한 관절이 20~25 어긋나도
        # L2<thresh 면 종료돼 버림 (손목 안 돌아왔는데 끝나는 버그). → 관절별 절대편차의
        # 최댓값(L∞)을 씀: "모든 관절이 각자 home_thresh 이내" 여야 홈 인정. 학습 teleop
        # 은 전 관절 p95≈4.2/p99≈7.5 로 정밀 복귀하므로 손목/그리퍼도 임계 안에 들어옴.
        if home_enabled:
            cur = np.asarray(state_vec, dtype=np.float32)
            if start_pose is None:
                start_pose = cur.copy()
                logger.info("home: start_pose=%s", np.round(start_pose, 1).tolist())
            joint_dev = np.abs(cur - start_pose)          # 관절별 절대편차 (12,)
            max_dev = float(joint_dev.max())               # L∞ — 가장 안 돌아온 관절
            lag_i = int(joint_dev.argmax())                # 그 관절 index
            if max_dev > move_thresh:
                moved_away = True
            if moved_away and max_dev < home_thresh:       # 모든 관절이 home_thresh 이내
                home_count += 1
                if home_count >= stable_frames:
                    logger.info("홈 복귀 감지 (frame %d, max_dev=%.1f) — task 완료", i, max_dev)
                    break
            else:
                home_count = 0
            # 진단: 1초마다 — 어느 관절(lag)이 얼마나 안 돌아왔는지 추적.
            if i % fps == 0:
                logger.info("home: frame=%d max_dev=%.1f@%s moved_away=%s hc=%d (move>%.0f, home<%.0f)",
                            i, max_dev, MOTOR_ORDER[lag_i], moved_away, home_count, move_thresh, home_thresh)

        # ── 벨 누름 감지 (task 당 1회 EVENT) ──
        if bell_pose is not None and not bell_rung:
            cur_b = np.asarray(state_vec, dtype=np.float32)
            bell_dist = float(np.linalg.norm(cur_b - bell_pose))
            if bell_dist < bell_thresh:
                bell_rung = True
                logger.info("벨 누름 감지 (frame %d, dist=%.1f)", i, bell_dist)
                # EVENT → control on_event → SSE → UI "주문 나왔습니다".
                print(f'EVENT {json.dumps({"type": "bell_rung", "prompt": task})}', flush=True)

        if not queue:
            images = {key: obs[key] for key in CAMERA_KEYS}
            try:
                t_inf = time.perf_counter()
                chunk = provider(state_vec, images, task)
                inf_ms = (time.perf_counter() - t_inf) * 1e3
            except Exception as e:
                logger.warning("provider 실패 (frame %d): %s — 0.2s 후 retry", i, e)
                time.sleep(0.2)
                continue
            queue.extend(chunk)
            last_inf_ms = inf_ms
            # ACT closed-loop 는 매 frame 1개 반환 → 로그 1초마다. SmolVLA chunk(>1) 는 매번.
            if len(chunk) > 1 or i % fps == 0:
                logger.info("frame %d: +%d action, provider=%.0fms", i, len(chunk), inf_ms)

        # rerun 로깅 — 모델이 보는 ROI masked 프레임 + 관절상태 + 검출 class (UI 카메라 대체).
        # 객체없음은 이제 서빙 시작 게이트가 담당 (서빙 중엔 occlusion 무시).
        _rr_log(i, getattr(provider, "last_masked", {}), state_vec, "서빙중",
                getattr(provider, "last_detected", set()))

        action_vec = queue.popleft()
        try:
            robot.send_action(_action_vec_to_dict(action_vec))
        except Exception as e:
            logger.warning("send_action 실패 (frame %d): %s — task 종료", i, e)
            break

        loop_dt = time.perf_counter() - t0
        # stats 집계: 매 frame loop_dt 적산 → 1초마다 (i % fps == 0) 한 줄 로그.
        loop_dt_ms = loop_dt * 1e3
        if loop_dt_ms > loop_max_ms:
            loop_max_ms = loop_dt_ms
        loop_sum_s += loop_dt
        if loop_dt > dt:
            over_budget += 1
        if i > 0 and i % fps == 0:
            actual_fps = fps / max(0.001, loop_sum_s)
            logger.info(
                "stats: provider=%.0fms loop avg=%.0fms max=%.0fms over_budget=%d/%d fps≈%.1f/%d",
                last_inf_ms, loop_sum_s * 1e3 / fps, loop_max_ms,
                over_budget, fps, actual_fps, fps,
            )
            loop_max_ms = 0.0
            loop_sum_s = 0.0
            over_budget = 0
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
    parser.add_argument("--fps", type=int, default=None,
                        help="없으면 game.yaml runtime.rate_hz 사용.")
    parser.add_argument("--episode_s", type=int, default=None,
                        help="task 1회 최대 시간 (s). 정책이 종료 신호(홈 복귀) 안 보내면 강제 cut. "
                             "없으면 game.yaml runtime.episode_timeout_s 사용.")
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
    _wake_cfg = config.policy.extra.get("wake_motion") or {}

    # 1) 양팔 먼저 연결 (빠름). wake 모션은 팔만 있으면 되므로 여기서 바로 시작 가능 —
    #    카메라(warmup 4.5s) + 모델 로드는 wake 가 도는 동안 뒤에서 진행. → UI "깨어나고 있어"
    #    뜨자마자(팔 연결 ~1s 후) 로봇이 움직이기 시작 (이전엔 카메라 connect 까지 ~5s 기다렸음).
    logger.info("양팔 연결 중...")
    robot = _build_robot()
    try:
        robot.left_arm.connect(True)
        robot.right_arm.connect(True)
    except Exception as e:
        print(f"[runner_entry] 양팔 connect 실패: {e}", flush=True)
        return 4
    logger.info("양팔 연결됨 — wake 모션 시작")

    # signal handlers — 팔 연결 직후 (부팅 중 SIGTERM/SIGINT → _SHUTDOWN → wake 즉시 정지 +
    # 체크포인트에서 disconnect). 부팅 중에도 모터가 살아 움직이므로 kill 시 정지/torque OFF 필요.
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)
    signal.signal(signal.SIGUSR1, _handle_sigusr1)

    # 2) wake 모션 즉시 시작 — 팔만으로 (카메라 미연결, _arm_state_vec 로 pose 읽음).
    import threading
    _wake_stop = threading.Event()
    _wake_thread = None
    _wake_traj, _wake_fps = _load_wake_traj(_wake_cfg)
    if _wake_traj is not None:
        _wake_thread = threading.Thread(
            target=_play_wake_motion, args=(robot, _wake_traj, _wake_fps, _wake_stop),
            daemon=True)
        _wake_thread.start()
        logger.info("wake 모션 재생 시작 (%d frame @%dHz)", len(_wake_traj), _wake_fps)

    def _boot_cleanup() -> None:
        _wake_stop.set()
        if _wake_thread is not None:
            _wake_thread.join(timeout=2.0)
        try:
            robot.disconnect()
        except Exception:
            pass

    # 3) 카메라 연결 (wake 재생되는 동안 — wake 는 팔 bus 만 쓰고 카메라 접근 안 함).
    try:
        for cam in robot.cameras.values():
            cam.connect()
    except Exception as e:
        _boot_cleanup()
        print(f"[runner_entry] 카메라 connect 실패: {e}", flush=True)
        return 4
    logger.info("카메라 3대 연결됨")

    # 4) chunk provider 빌드 (모델 로드 — wake 모션과 병렬). 모터 serial 은 wake 스레드만 접근.
    try:
        provider = _build_chunk_provider(config)
    except Exception as e:
        _boot_cleanup()
        print(f"[runner_entry] chunk_provider 빌드 실패: {e}", flush=True)
        return 3

    # 4) 추론 준비 완료 → wake 모션 정지 + 홈 포지션으로 부드럽게 이동.
    if _wake_thread is not None:
        _wake_stop.set()
        _wake_thread.join(timeout=2.0)
    # 부팅 중 SIGTERM/SIGINT 받았으면 (wake 는 이미 멈춤) READY 안 보내고 정리 후 종료.
    if _SHUTDOWN.is_set():
        logger.info("부팅 중 종료 신호 — disconnect 후 종료")
        try:
            robot.disconnect()
        except Exception:
            pass
        print("EXIT", flush=True)
        return 0
    if _wake_cfg.get("enabled") and _wake_cfg.get("home_pose"):
        _move_to_home(robot, np.asarray(_wake_cfg["home_pose"], dtype=np.float32),
                      fps=_wake_fps, move_s=float(_wake_cfg.get("home_move_s", 2.0)))

    # 5) READY → Control Server 가 START 보냄 (초기 핸드셰이크 1회).
    print("READY", flush=True)
    line = sys.stdin.readline()
    if not line or line.strip() != "START":
        print(f"[runner_entry] 예상 'START' 인데 {line.strip()!r} 받음 — 종료", flush=True)
        try:
            robot.disconnect()
        except Exception:
            pass
        return 2

    # (signal handlers 는 connect 직후 부착됨 — 부팅 윈도우 보호)

    # fps / episode_s — CLI 명시값 우선, 없으면 game.yaml runtime (단일 진실원).
    _fps = args.fps if args.fps is not None else int(config.runtime.rate_hz)
    _episode_s = args.episode_s if args.episode_s is not None else int(config.runtime.episode_timeout_s)

    # rerun 네이티브 뷰어 — game.yaml rerun.enabled 일 때만 spawn. 기본 OFF: 뷰어가 CPU/RAM
    # 을 크게 잡아먹어 추론·wake 재생을 느리게 만들어서. 시각화 필요할 때만 켤 것.
    if (config.policy.extra.get("rerun") or {}).get("enabled"):
        _rr_init()

    # 홈 복귀 / 벨 / 서빙 게이트 설정 (game.yaml policy.*) — 매 task 에 전달.
    _home_cfg = config.policy.extra.get("home_detect") or {}
    _bell_cfg = config.policy.extra.get("bell_detect") or {}
    _gate_cfg = config.policy.extra.get("serve_gate") or {}
    logger.info("idle — PROMPT 대기 (kind=%s, fps=%d, episode_s=%d, home=%s, bell=%s, gate=%s)",
                config.policy.kind, _fps, _episode_s, bool(_home_cfg),
                bool(_bell_cfg.get("enabled")), bool(_gate_cfg.get("enabled")))

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
                _run_one_task(
                    robot, provider, task,
                    fps=_fps, episode_s=_episode_s,
                    home=_home_cfg, bell=_bell_cfg, gate=_gate_cfg,
                )
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
