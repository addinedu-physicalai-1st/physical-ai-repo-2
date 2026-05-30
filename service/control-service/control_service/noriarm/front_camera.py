"""프론트 카메라 단일 소유자 (shared front camera).

V4L2 는 디바이스당 캡처 핸들을 1개만 허용한다. 프리뷰 MJPEG 스트림과 가위바위보
감지(rps_detector)가 각자 cv2.VideoCapture 로 같은 카메라를 열면 충돌해
"can't be used to capture by name" 로 둘 다 실패한다.

이 모듈은 cv2.VideoCapture 하나를 백그라운드 스레드로 돌리며 최신 프레임을 공유한다.
소비자는 acquire()/release() 로 참조하고, 참조 수가 0이 되면 카메라를 닫는다.
프레임은 read() 로 가져온다(최신 BGR 프레임 복사본 또는 None).
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# udev by-id 경로가 가장 안정적. 없으면 흔한 인덱스로 폴백.
_BY_ID = "/dev/v4l/by-id/usb-Alcorlink_Corp._USB_2.0_Camera-video-index0"
_FALLBACKS = ["/dev/video4", "/dev/video0"]

# 추론 runner(별도 프로세스)가 점유 중일 때 front 프레임을 받아오는 릴레이 파일.
# runner_entry.py 가 매 프레임 이 경로에 JPEG 를 atomically 써둔다. (경로 동기화 필요)
_RELAY = Path("/dev/shm/noriarm_front.jpg")


def _resolve_device() -> str:
    if Path(_BY_ID).exists():
        return _BY_ID
    for dev in _FALLBACKS:
        if Path(dev).exists():
            return dev
    return _BY_ID


class _FrontCamera:
    def __init__(self) -> None:
        self._lock = threading.Lock()          # refcount / open·close 보호
        self._frame_lock = threading.Lock()    # 최신 프레임 보호
        self._cap: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        self._frame: np.ndarray | None = None
        self._refcount = 0
        self._running = False
        # 외부 프로세스(추론 runner)가 디바이스를 점유하는 동안 True.
        # 이 동안에는 in-process 소비자(프리뷰/RPS)가 디바이스를 열지 않는다.
        self._external = False

    def acquire(self) -> None:
        """소비자 등록. 첫 소비자면 카메라를 연다(외부 점유 중이면 열지 않음)."""
        with self._lock:
            self._refcount += 1
            if self._refcount == 1 and not self._external:
                self._open()

    def release_to_external(self) -> None:
        """디바이스를 외부 프로세스(추론 runner)에 양도. 핸들을 닫고 점유 플래그를 세운다.

        refcount 는 유지 → 프리뷰 스트림 등 in-process 소비자는 살아있되,
        reclaim() 전까지 read() 는 None 을 돌려준다.
        """
        with self._lock:
            self._external = True
            self._close()
            try:
                _RELAY.unlink(missing_ok=True)  # 이전 추론의 잔상 제거
            except Exception:
                pass
            logger.info("front_camera: 외부(runner)에 양도 — 디바이스 해제")

    def reclaim(self) -> None:
        """외부 점유 종료. in-process 소비자가 있으면 디바이스를 다시 연다."""
        with self._lock:
            if not self._external:
                return
            self._external = False
            if self._refcount > 0:
                self._open()
            logger.info("front_camera: 디바이스 회수(reclaim)")

    def release(self) -> None:
        """소비자 해제. 마지막 소비자면 카메라를 닫는다."""
        with self._lock:
            self._refcount = max(0, self._refcount - 1)
            if self._refcount == 0:
                self._close()

    def read(self) -> np.ndarray | None:
        """최신 BGR 프레임 복사본 (없으면 None)."""
        with self._frame_lock:
            return None if self._frame is None else self._frame.copy()

    def latest_jpeg(self, quality: int = 70) -> bytes | None:
        """프리뷰용 최신 front JPEG 바이트.

        추론 runner 점유 중(external)이면 runner 가 써둔 릴레이 파일을 그대로 반환 →
        웹 프리뷰가 추론 중에도 runner 가 보는 front 카메라를 보여준다.
        평상시(RPS·idle)엔 공유 카메라 프레임을 인코딩.
        """
        if self._external:
            try:
                return _RELAY.read_bytes() if _RELAY.exists() else None
            except Exception:
                return None
        frame = self.read()
        if frame is None:
            return None
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buf.tobytes() if ok else None

    def is_open(self) -> bool:
        return self._cap is not None

    def wait_frame(self, timeout_s: float = 2.0) -> np.ndarray | None:
        """첫 프레임이 들어올 때까지 잠깐 대기 후 반환."""
        t_end = time.monotonic() + timeout_s
        while time.monotonic() < t_end:
            f = self.read()
            if f is not None:
                return f
            time.sleep(0.02)
        return self.read()

    # --- 내부 (_lock 보유 상태에서 호출) ---
    def _open(self) -> None:
        device = _resolve_device()
        cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)
        if not cap.isOpened():
            logger.warning("front_camera: 카메라 열기 실패 — %s", device)
            cap.release()
            self._refcount = 0
            return
        self._cap = cap
        self._frame = None
        self._running = True
        self._thread = threading.Thread(
            target=self._grab_loop, name="front-camera-grab", daemon=True
        )
        self._thread.start()
        logger.info("front_camera: open — %s", device)

    def _close(self) -> None:
        self._running = False
        t = self._thread
        if t is not None:
            t.join(timeout=1.0)
        self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        with self._frame_lock:
            self._frame = None
        logger.info("front_camera: close")

    def _grab_loop(self) -> None:
        cap = self._cap
        fail = 0
        while self._running and cap is not None:
            ret, frame = cap.read()  # 카메라 FPS 에 맞춰 블로킹 → 자연스러운 페이싱
            if not ret:
                fail += 1
                if fail > 100:
                    logger.warning("front_camera: 연속 read 실패 — grab 종료")
                    break
                time.sleep(0.02)
                continue
            fail = 0
            with self._frame_lock:
                self._frame = frame


# 프로세스 전역 단일 인스턴스
front_camera = _FrontCamera()
