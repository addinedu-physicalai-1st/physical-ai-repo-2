"""front 카메라로 가위/바위/보 감지.

mediapipe 0.10+ tasks API (GestureRecognizer) 사용.
모델 파일: gesture_recognizer.task (이 파일과 같은 디렉토리)
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import cv2
import mediapipe as mp

logger = logging.getLogger(__name__)

_MODEL_PATH = Path(__file__).parent / "gesture_recognizer.task"

_GESTURE_MAP = {
    "Closed_Fist": "바위",
    "Open_Palm": "보",
    "Victory": "가위",
}


def detect_rps_gesture(
    camera_path: str,
    *,
    timeout_s: float = 5.0,
    min_detections: int = 8,
) -> str | None:
    """카메라에서 timeout_s 초 동안 프레임을 읽어 가위/바위/보를 반환. 실패 시 None."""
    try:
        BaseOptions = mp.tasks.BaseOptions
        GestureRecognizer = mp.tasks.vision.GestureRecognizer
        GestureRecognizerOptions = mp.tasks.vision.GestureRecognizerOptions
        VisionRunningMode = mp.tasks.vision.RunningMode

        options = GestureRecognizerOptions(
            base_options=BaseOptions(model_asset_path=str(_MODEL_PATH)),
            running_mode=VisionRunningMode.IMAGE,
            num_hands=1,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )

        src = int(camera_path) if str(camera_path).isdigit() else camera_path
        cap = cv2.VideoCapture(src)
        if not cap.isOpened():
            logger.warning("rps_detector: 카메라 열기 실패 — %s", camera_path)
            return None

        votes: dict[str, int] = {"가위": 0, "바위": 0, "보": 0}
        total_detected = 0
        t_end = time.monotonic() + timeout_s

        with GestureRecognizer.create_from_options(options) as recognizer:
            while time.monotonic() < t_end:
                ret, frame = cap.read()
                if not ret:
                    break
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                result = recognizer.recognize(mp_image)
                if result.gestures:
                    label = result.gestures[0][0].category_name
                    rps = _GESTURE_MAP.get(label)
                    if rps:
                        votes[rps] += 1
                        total_detected += 1
                        if total_detected >= min_detections:
                            break

        cap.release()

        if total_detected == 0:
            logger.warning("rps_detector: 손 감지 실패 (%.1fs)", timeout_s)
            return None

        best = max(votes, key=lambda k: votes[k])
        logger.info("rps_detector: votes=%s → %s", votes, best)
        return best

    except Exception as e:
        logger.warning("rps_detector: 예외 — %s", e)
        return None
