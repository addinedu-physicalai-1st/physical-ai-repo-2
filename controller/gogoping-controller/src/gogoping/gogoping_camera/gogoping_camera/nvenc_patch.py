"""aiortc 의 H.264 software encoder (libx264) 를 NVIDIA NVENC (h264_nvenc) 로
monkey-patch.

aiortc 1.14 의 `H264Encoder._encode_frame` 는 `av.CodecContext.create("libx264", "w")`
를 사용하는데, 이 모듈을 import 하면 그 method 가 NVENC 버전으로 교체된다.

효과:
  - 인코딩 latency: 15-30ms → 3-5ms (hardware)
  - CPU 부담: ~30% → 1-2%
  - NVENC unit 은 CUDA 와 독립이라 YOLO 와 자원 충돌 없음

사용:
  webrtc_node.py 같은 entry point 에서 가장 위에 `from . import nvenc_patch` 1줄.
"""
from __future__ import annotations

import fractions
import logging
from collections.abc import Iterator

import av
from aiortc.codecs import h264

from . import config

_log = logging.getLogger("gogoping_camera.nvenc_patch")


def _encode_frame_nvenc(
    self: h264.H264Encoder,
    frame: av.VideoFrame,
    force_keyframe: bool,
) -> Iterator[bytes]:
    """`libx264` → `h264_nvenc` 로 교체한 _encode_frame 본문.

    aiortc 1.14 의 원본을 거의 그대로 옮기되 codec name + options 만 NVENC 으로.
    """
    # 원본 aiortc 는 target_bitrate 가 ±10% 변하면 codec 재생성. NVENC + rc=cbr 는
    # init time bitrate 만 effective 라 재생성해도 효과 없는데, destroy/recreate 마다
    # 1-2초 동안 키프레임 손실 → 브라우저 디코더 freeze. 해상도 변경시만 reset.
    if self.codec and (
        frame.width != self.codec.width
        or frame.height != self.codec.height
    ):
        self.buffer_data = b""
        self.buffer_pts = None
        self.codec = None

    if force_keyframe:
        frame.pict_type = av.video.frame.PictureType.I
    else:
        frame.pict_type = av.video.frame.PictureType.NONE

    if self.codec is None:
        # LAN-only same-PC 시나리오라 aiortc 의 RTCP REMB 기반 self.target_bitrate
        # (보수적으로 1 Mbps 까지 떨어짐) 무시하고 config 의 4 Mbps 고정. 빠른 움직임
        # block artifact 방지. WAN 배포 시에는 target_bitrate 존중으로 돌릴 것.
        forced_bitrate = config.H264_BITRATE
        self.codec = av.CodecContext.create("h264_nvenc", "w")
        self.codec.width = frame.width
        self.codec.height = frame.height
        self.codec.bit_rate = forced_bitrate
        self.codec.pix_fmt = "yuv420p"
        self.codec.framerate = fractions.Fraction(h264.MAX_FRAME_RATE, 1)
        self.codec.time_base = fractions.Fraction(1, h264.MAX_FRAME_RATE)
        self.codec.options = {
            "preset": config.H264_PRESET,    # p4 (low-latency 균형)
            "tune": config.H264_TUNE,        # ll (low-latency)
            "rc": config.H264_RC,            # cbr
            # NVENC ffmpeg wrapper 가 codec.bit_rate 대신 options 의 b/maxrate 를
            # 보는 케이스가 있어 명시. bufsize 는 CBR VBV 버퍼.
            "b": str(forced_bitrate),
            "maxrate": str(config.H264_BITRATE_MAX),
            "bufsize": str(forced_bitrate * 2),
            "bf": str(config.H264_BF),       # 0 (B-frame 비활성)
            "g": str(config.H264_GOP_SIZE),  # 30 (1초 키프레임)
            "zerolatency": "1",
        }
        # NVENC 은 baseline 미지원 — main 또는 high
        self.codec.profile = config.H264_PROFILE  # "main"
        _log.info("NVENC H264 encoder initialized: %dx%d @ %d bps (forced, target=%d), preset=%s tune=%s",
                  frame.width, frame.height, forced_bitrate, self.target_bitrate,
                  config.H264_PRESET, config.H264_TUNE)

    data_to_send = b""
    for package in self.codec.encode(frame):
        data_to_send += bytes(package)

    if data_to_send:
        yield from h264.H264Encoder._split_bitstream(data_to_send)


# Monkey-patch: import 시점에 즉시 적용
h264.H264Encoder._encode_frame = _encode_frame_nvenc
_log.info("aiortc H264Encoder._encode_frame patched to use h264_nvenc")
