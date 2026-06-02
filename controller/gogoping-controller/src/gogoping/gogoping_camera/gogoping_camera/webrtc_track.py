"""aiortc VideoStreamTrack — D435 1080p frame 을 h264_nvenc 로 인코딩.

aiortc 의 RTCRtpSender 가 SDP 협상 시 codec 을 결정. 본 트랙은 raw frame 만 제공하고
실제 인코딩은 aiortc 내부에서 PyAV 의 codec 으로 진행. NVENC 강제는
RTCRtpSender.getCapabilities → setCodecPreferences 로 H.264 우선시키고, codec_options
로 nvenc 파라미터 전달.

aiortc 1.9+ 에서 codec_options 지원 — 미지원 버전이면 aiortc.codecs.h264 의
RTCCodecCapability 를 monkeypatch 해야 함 (별도 헬퍼).
"""
from __future__ import annotations

import asyncio
import fractions
import logging
import time
from typing import Optional

import av
from aiortc import VideoStreamTrack

from . import config
from .d435_capture import CapturedFrame, D435Capture

_log = logging.getLogger("gogoping_camera.webrtc_track")

VIDEO_CLOCK_RATE = 90_000   # H.264 표준 90kHz
VIDEO_PTIME = 1 / 30
VIDEO_TIME_BASE = fractions.Fraction(1, VIDEO_CLOCK_RATE)


class D435VideoTrack(VideoStreamTrack):
    """D435Capture.latest_frame() 을 aiortc 가 pull 할 수 있도록 wrapping.

    recv() 는 aiortc 내부 코덱 (h264_nvenc 가 협상으로 선택되면) 에 av.VideoFrame 제공.
    color_full (1920×1080 BGR) 을 그대로 보냄 — 다운스케일된 small frame 은 perception 용.
    """

    kind = "video"

    def __init__(self, capture: D435Capture) -> None:
        super().__init__()
        self._capture = capture
        self._start_ts: Optional[float] = None
        self._frame_count = 0

    async def recv(self) -> av.VideoFrame:
        # aiortc 가 30fps 페이스로 호출하지만 D435 도 30fps 라 거의 일치.
        # capture 가 늦으면 일시적으로 같은 frame 두 번 반환 가능 (aiortc 가 알아서 처리).
        loop = asyncio.get_event_loop()
        frame = await loop.run_in_executor(None, self._capture.latest_frame, 1.0)
        if frame is None:
            # capture timeout — 1초 이상 D435 frame 없음. 빈 frame 으로 채워서 stream 유지.
            empty = av.VideoFrame(width=config.CAMERA_COLOR_W, height=config.CAMERA_COLOR_H, format="bgr24")
            empty.planes[0].update(bytes(config.CAMERA_COLOR_W * config.CAMERA_COLOR_H * 3))
            return await self._stamp(empty)

        vframe = av.VideoFrame.from_ndarray(frame.color_full, format="bgr24")
        return await self._stamp(vframe)

    async def _stamp(self, vframe: av.VideoFrame) -> av.VideoFrame:
        # PTS 는 첫 recv() 시점 기준 monotonic elapsed — wall clock jump (NTP) 보호.
        if self._start_ts is None:
            self._start_ts = time.monotonic()
        elapsed = time.monotonic() - self._start_ts
        vframe.pts = int(elapsed * VIDEO_CLOCK_RATE)
        vframe.time_base = VIDEO_TIME_BASE
        self._frame_count += 1
        return vframe


def configure_h264_nvenc_options() -> dict:
    """aiortc 가 PyAV codec 을 열 때 전달할 options.

    aiortc 1.9 의 H.264 encoder 가 codec_options dict 를 받음 (직접 set 또는
    monkey-patch). Phase 1 에서는 aiortc 기본 사용 + ffmpeg 가 가능하면 nvenc 자동 선택
    되도록 환경 변수 또는 PyAV codec context 강제. 다음 dict 는 webrtc_node 에서
    track 생성 직후 ext (확장 함수) 로 적용.
    """
    return {
        "preset": config.H264_PRESET,
        "tune": config.H264_TUNE,
        "rc": config.H264_RC,
        "bf": str(config.H264_BF),
        "g": str(config.H264_GOP_SIZE),
        "b": f"{config.H264_BITRATE}",
        "maxrate": f"{config.H264_BITRATE_MAX}",
        "profile": config.H264_PROFILE,
    }
