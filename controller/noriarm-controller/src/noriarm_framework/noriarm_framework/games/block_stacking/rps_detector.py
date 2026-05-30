"""front 카메라로 가위/바위/보 감지.

mediapipe 0.10+ tasks API (GestureRecognizer) 사용.
모델 파일: gesture_recognizer.task (이 파일과 같은 디렉토리)

판별은 두 신호의 앙상블:
  1. mediapipe 의 학습된 제스처 분류기 (Closed_Fist/Open_Palm/Victory) + confidence
  2. 손가락 신전 여부를 손 축에 투영해 계산하는 기하 분류기 (scale/회전 불변)
각 프레임의 두 신호를 confidence 가중으로 누적 투표하고, 1·2위 간 margin 이
확보됐을 때만 결과를 확정한다.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

logger = logging.getLogger(__name__)

_MODEL_PATH = Path(__file__).parent / "gesture_recognizer.task"

# mediapipe 내장 제스처 라벨 → 가위/바위/보
_GESTURE_MAP = {
    "Closed_Fist": "바위",
    "Open_Palm": "보",
    "Victory": "가위",
}
# 내장 분류기 신뢰도가 이 값 이상일 때만 투표에 반영
_MP_MIN_SCORE = 0.55
# 기하 분류기 한 표의 가중치 (내장 분류기는 score 만큼 가중)
_GEO_WEIGHT = 0.6
# 결과 확정에 필요한 1위 누적 점수 하한 (스쳐 지나간 1~2 프레임 노이즈 배제)
_MIN_BEST_SCORE = 2.0


def _finger_states(lm: list[tuple[float, float, float]], hand_up: np.ndarray) -> list[bool]:
    """index/middle/ring/pinky 신전 여부.

    각 손가락 tip 과 PIP 관절을 손목 기준으로 hand_up 축에 투영해 비교.
    tip 이 PIP 보다 더 위(손끝 방향)면 신전. 손 크기/거리/회전에 불변.
    """
    wrist = np.array(lm[0])

    def proj(i: int) -> float:
        return float(np.dot(np.array(lm[i]) - wrist, hand_up))

    states = []
    for tip, pip in [(8, 6), (12, 10), (16, 14), (20, 18)]:
        states.append(proj(tip) > proj(pip) + 0.02)
    return states


def _thumb_extended(lm: list[tuple[float, float, float]]) -> bool:
    """엄지 신전(벌어짐) 여부 — tip(4) 가 IP(3)·MCP(2) 보다 검지 MCP(5) 에서 멀면 펴짐."""
    idx_mcp = np.array(lm[5])
    tip_d = np.linalg.norm(np.array(lm[4]) - idx_mcp)
    ip_d = np.linalg.norm(np.array(lm[3]) - idx_mcp)
    return tip_d > ip_d * 1.1


def _classify_from_landmarks(hand_landmarks) -> str | None:
    """hand_landmarks(NormalizedLandmark 21개)로 가위/바위/보 판별.

    손목→중지MCP 벡터를 손의 '위' 방향으로 삼아 각 손가락의 신전 여부를 판단.
    손 방향(각도)에 무관하게 동작.
    """
    lm = [(l.x, l.y, l.z) for l in hand_landmarks]
    hand_up = np.array(lm[9]) - np.array(lm[0])
    norm = np.linalg.norm(hand_up)
    if norm < 1e-6:
        return None
    hand_up = hand_up / norm

    ext = _finger_states(lm, hand_up)
    n = sum(ext)

    # 가위: 검지·중지만 신전, 약지·소지 접힘
    if ext[0] and ext[1] and not ext[2] and not ext[3]:
        return "가위"
    # 보: 네 손가락 모두(또는 엄지 포함 충분히) 신전
    if n >= 4 or (n >= 3 and _thumb_extended(lm)):
        return "보"
    # 바위: 모두 접힘
    if n == 0:
        return "바위"
    return None


def _gesture_from_result(result) -> tuple[str, float] | None:
    """mediapipe 내장 분류기 결과 → (가위/바위/보, score). 매핑 불가 시 None."""
    if not result.gestures:
        return None
    top = result.gestures[0][0]  # 첫 손, 1위 카테고리
    label = _GESTURE_MAP.get(top.category_name)
    if label is None:
        return None
    return label, float(top.score)


def _detect_from_frames(read_frame, *, timeout_s: float, min_detections: int) -> str | None:
    """read_frame() 으로 BGR 프레임(또는 None)을 받아 가위/바위/보 판별.

    read_frame: () -> np.ndarray | None  — 최신 BGR 프레임을 돌려주는 콜백.
    """
    BaseOptions = mp.tasks.BaseOptions
    GestureRecognizer = mp.tasks.vision.GestureRecognizer
    GestureRecognizerOptions = mp.tasks.vision.GestureRecognizerOptions
    VisionRunningMode = mp.tasks.vision.RunningMode

    options = GestureRecognizerOptions(
        base_options=BaseOptions(model_asset_path=str(_MODEL_PATH)),
        running_mode=VisionRunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=0.5,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    # confidence 가중 누적 투표
    votes: dict[str, float] = {"가위": 0.0, "바위": 0.0, "보": 0.0}
    total_detected = 0
    last_ts = -1

    with GestureRecognizer.create_from_options(options) as recognizer:
        t_start = time.monotonic()
        t_end = t_start + timeout_s
        while time.monotonic() < t_end:
            frame = read_frame()
            if frame is None:
                time.sleep(0.01)
                continue
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            ts_ms = int((time.monotonic() - t_start) * 1000)
            if ts_ms <= last_ts:  # VIDEO 모드는 단조 증가 타임스탬프 요구
                ts_ms = last_ts + 1
            last_ts = ts_ms
            result = recognizer.recognize_for_video(mp_image, ts_ms)
            if not result.hand_landmarks:
                continue

            frame_voted = False

            # 신호 1: 내장 분류기 (score 가중)
            mp_g = _gesture_from_result(result)
            if mp_g is not None and mp_g[1] >= _MP_MIN_SCORE:
                votes[mp_g[0]] += mp_g[1]
                frame_voted = True

            # 신호 2: 기하 분류기 (고정 가중)
            geo = _classify_from_landmarks(result.hand_landmarks[0])
            if geo is not None:
                votes[geo] += _GEO_WEIGHT
                frame_voted = True

            if frame_voted:
                total_detected += 1
                if total_detected >= min_detections:
                    break

    if total_detected == 0:
        logger.warning("rps_detector: 손 감지 실패 (%.1fs)", timeout_s)
        return None

    ranked = sorted(votes.items(), key=lambda kv: kv[1], reverse=True)
    best, best_v = ranked[0]
    second_v = ranked[1][1]
    # 1위 누적 점수가 하한 미달이거나 2위와 동률이면 애매 → 미확정(재시도)
    if best_v < _MIN_BEST_SCORE or best_v <= second_v:
        logger.warning("rps_detector: 결과 애매 votes=%s", votes)
        return None

    logger.info("rps_detector: votes=%s → %s", votes, best)
    return best


def detect_rps_gesture(
    camera_path: str | None = None,
    *,
    timeout_s: float = 5.0,
    min_detections: int = 8,
    read_frame=None,
) -> str | None:
    """timeout_s 초 동안 프레임을 읽어 가위/바위/보를 반환. 실패·애매 시 None.

    read_frame 콜백이 주어지면 그 콜백(공유 카메라)에서 프레임을 받는다.
    아니면 camera_path 로 직접 cv2.VideoCapture 를 연다(standalone 테스트용).
    """
    try:
        if read_frame is not None:
            return _detect_from_frames(
                read_frame, timeout_s=timeout_s, min_detections=min_detections
            )

        if camera_path is None:
            logger.warning("rps_detector: camera_path/read_frame 둘 다 없음")
            return None

        src = int(camera_path) if str(camera_path).isdigit() else camera_path
        cap = cv2.VideoCapture(src, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)
        if not cap.isOpened():
            logger.warning("rps_detector: 카메라 열기 실패 — %s", camera_path)
            return None
        try:
            for _ in range(5):
                cap.read()  # 워밍업 프레임 버리기

            def _read():
                ret, frame = cap.read()
                return frame if ret else None

            return _detect_from_frames(
                _read, timeout_s=timeout_s, min_detections=min_detections
            )
        finally:
            cap.release()

    except Exception as e:
        logger.warning("rps_detector: 예외 — %s", e)
        return None
