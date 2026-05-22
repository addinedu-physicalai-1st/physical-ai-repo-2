"""EduPing 노트북의 D435 → Control Server 깊이/컬러 WebSocket 송출.

영상 MJPEG (gogoping_camera/streamer.py) 과 분리: D435 의 16-bit depth 를 그대로
보존하기 위해 별도 WS 채널 (/ws/depth-stream/producer/eduping) 사용. uint16 depth
는 zstd 압축, color 는 JPEG.

기본 동작:
  - 320×240 @ 10fps (depth + color, color → depth 해상도로 align)
  - 매 frame 인코딩 후 WS 로 push
  - server 끊기면 1s/2s/4s... 최대 30s exponential backoff 로 reconnect
  - SIGINT/SIGTERM 에서 cleanly shutdown

서버는 [service/control-service/control_service/streaming/depth_ws_router.py]
의 producer 엔드포인트, 와이어 포맷은
[service/control-service/control_service/streaming/depth_protocol.py].
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
import websockets
import zstandard as zstd

try:
    import pyrealsense2 as rs
except ImportError as exc:   # pragma: no cover
    sys.stderr.write(
        f"[d435_depth_streamer] pyrealsense2 import 실패: {exc}\n"
        "  pip install -e . (또는 별도 `pip install pyrealsense2`)\n",
    )
    raise

from control_service.streaming.depth_protocol import (
    DepthFrame, encode_depth_frame,
)


ROBOT_IDS = {"gogoping": 0x01, "eduping": 0x02, "noriarm": 0x03}

# 연속 frame timeout 이 이 값 이상이면 pipeline 종료 → USB hardware_reset → 재연결.
_FRAME_TIMEOUT_RESET_STREAK = 15


@dataclass
class Config:
    server_host: str
    server_port: int
    robot: str
    width: int
    height: int
    fps: int
    jpeg_quality: int
    device_serial: Optional[str]

    @property
    def robot_id(self) -> int:
        return ROBOT_IDS[self.robot]

    @property
    def ws_url(self) -> str:
        return f"ws://{self.server_host}:{self.server_port}/ws/depth-stream/producer/{self.robot}"


def _make_pipeline(cfg: Config) -> tuple[rs.pipeline, rs.align, rs.intrinsics, float]:
    """RealSense pipeline 시작 + depth intrinsics + depth_scale 반환.

    D435 가 지원하는 depth 해상도: 256x144, 424x240, 480x270, 640x360, 640x480,
    848x480, 1280x720. 미지원 조합이면 rs.error('Couldn't resolve requests') 발생 →
    그 경우 사용자에게 명확한 안내 후 실패.
    """
    pipeline = rs.pipeline()
    rs_config = rs.config()
    if cfg.device_serial:
        rs_config.enable_device(cfg.device_serial)
    rs_config.enable_stream(rs.stream.depth, cfg.width, cfg.height, rs.format.z16, cfg.fps)
    rs_config.enable_stream(rs.stream.color, cfg.width, cfg.height, rs.format.bgr8, cfg.fps)

    try:
        profile = pipeline.start(rs_config)
    except RuntimeError as exc:
        raise RuntimeError(
            f"RealSense pipeline 시작 실패 ({cfg.width}x{cfg.height}@{cfg.fps}fps): {exc}. "
            "D435 가 지원하는 해상도/fps 조합인지 확인 — depth 는 424x240 / 480x270 / "
            "640x360 / 640x480 / 848x480 / 1280x720 만 지원하며 fps 는 보통 6/15/30/60/90 중 하나."
        ) from exc
    align = rs.align(rs.stream.depth)

    depth_sensor = profile.get_device().first_depth_sensor()
    depth_scale = float(depth_sensor.get_depth_scale())   # meters / unit (보통 0.001)

    depth_profile = profile.get_stream(rs.stream.depth).as_video_stream_profile()
    intrinsics = depth_profile.get_intrinsics()
    return pipeline, align, intrinsics, depth_scale


def _capture_frame(
    pipeline: rs.pipeline, align: rs.align,
) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """blocking — wait_for_frames + align. (depth_u16, color_bgr) 반환.

    Timeout 시 pyrealsense2 가 RuntimeError 던짐 — None 으로 변환해 호출자가 skip + retry.
    USB hiccup / 카메라 일시 미응답 시 streamer 가 죽지 않도록 함.
    """
    try:
        frames = pipeline.wait_for_frames(timeout_ms=2000)
    except RuntimeError:
        return None
    aligned = align.process(frames)
    depth_frame = aligned.get_depth_frame()
    color_frame = aligned.get_color_frame()
    if not depth_frame or not color_frame:
        return None
    depth = np.asanyarray(depth_frame.get_data())   # uint16, shape (h, w)
    color = np.asanyarray(color_frame.get_data())   # uint8 BGR
    return depth, color


def _hardware_reset_device(cfg: Config, log: logging.Logger) -> None:
    """Hung RealSense (pipeline open but no frames) — USB reset 후 재열거 대기."""
    ctx = rs.context()
    devices = ctx.query_devices()
    if len(devices) == 0:
        log.warning("hardware_reset: no RealSense devices found")
        return
    for dev in devices:
        serial = dev.get_info(rs.camera_info.serial_number)
        if cfg.device_serial and serial != cfg.device_serial:
            continue
        log.warning("hardware_reset serial=%s (wait for USB re-enumerate)", serial)
        try:
            dev.hardware_reset()
        except Exception as exc:
            log.error("hardware_reset failed: %s", exc)
        time.sleep(3.0)
        return
    log.warning("hardware_reset: no device matched serial=%s", cfg.device_serial)


def _encode_payload(
    depth: np.ndarray, color: np.ndarray, jpeg_quality: int, compressor: zstd.ZstdCompressor,
) -> tuple[bytes, bytes, int, int]:
    """(depth_zstd, color_jpeg, depth_min_mm, depth_max_mm)."""
    if depth.dtype != np.uint16:
        depth = depth.astype(np.uint16)
    depth_bytes = compressor.compress(depth.tobytes(order="C"))
    ok, jpeg_buf = cv2.imencode(".jpg", color, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
    if not ok:
        raise RuntimeError("cv2.imencode JPEG 실패")
    nonzero = depth[depth > 0]
    if nonzero.size:
        dmin = int(nonzero.min())
        dmax = int(nonzero.max())
    else:
        dmin = dmax = 0
    return depth_bytes, jpeg_buf.tobytes(), dmin, dmax


async def _stream_one_connection(cfg: Config, log: logging.Logger) -> None:
    """단일 WS 연결 — 끊기면 호출자가 backoff 후 재호출."""
    pipeline, align, intrinsics, depth_scale = _make_pipeline(cfg)
    compressor = zstd.ZstdCompressor(level=3)   # 3 = 빠르면서 ratio 적당
    frame_seq = 0
    period = 1.0 / cfg.fps

    log.info(
        "connecting to %s (depth_scale=%.6f m/unit, intrinsics fx=%.2f cx=%.2f)",
        cfg.ws_url, depth_scale, intrinsics.fx, intrinsics.ppx,
    )
    timeout_streak = 0
    try:
        async with websockets.connect(cfg.ws_url, max_size=8 * 1024 * 1024) as ws:
            log.info("WS open — streaming %d fps", cfg.fps)
            next_tick = time.monotonic()
            while True:
                captured = await asyncio.to_thread(_capture_frame, pipeline, align)
                if captured is None:
                    timeout_streak += 1
                    if timeout_streak == 1 or timeout_streak % 5 == 0:
                        log.warning(
                            "frame timeout — skip (%d consecutive)",
                            timeout_streak,
                        )
                    if timeout_streak >= _FRAME_TIMEOUT_RESET_STREAK:
                        raise RuntimeError(
                            f"RealSense: {timeout_streak} consecutive frame timeouts",
                        )
                    continue
                timeout_streak = 0
                depth, color = captured
                depth_zstd, color_jpeg, dmin, dmax = _encode_payload(
                    depth, color, cfg.jpeg_quality, compressor,
                )
                frame = DepthFrame(
                    robot_id=cfg.robot_id,
                    frame_seq=frame_seq, ts_ms=int(time.time() * 1000),
                    depth_w=depth.shape[1], depth_h=depth.shape[0],
                    color_w=color.shape[1], color_h=color.shape[0],
                    fx=float(intrinsics.fx), fy=float(intrinsics.fy),
                    cx=float(intrinsics.ppx), cy=float(intrinsics.ppy),
                    depth_scale=float(depth_scale),
                    depth_min_mm=dmin, depth_max_mm=dmax,
                    depth_zstd=depth_zstd, color_jpeg=color_jpeg,
                )
                await ws.send(encode_depth_frame(frame))
                frame_seq = (frame_seq + 1) & 0xFFFFFFFF

                next_tick += period
                now = time.monotonic()
                sleep_for = next_tick - now
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                else:
                    next_tick = now
    finally:
        try:
            pipeline.stop()
        except Exception:
            pass


async def _run(cfg: Config, log: logging.Logger, stop_event: asyncio.Event) -> None:
    backoff = 1.0
    while not stop_event.is_set():
        try:
            await _stream_one_connection(cfg, log)
            backoff = 1.0
        except (OSError, websockets.WebSocketException) as exc:
            log.warning("WS disconnect: %s — reconnecting in %.1fs", exc, backoff)
        except RuntimeError as exc:
            log.warning("RealSense error: %s — reconnecting in %.1fs", exc, backoff)
            if "frame timeouts" in str(exc):
                await asyncio.to_thread(_hardware_reset_device, cfg, log)
        except Exception as exc:
            log.exception("unexpected: %s — reconnecting in %.1fs", exc, backoff)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=backoff)
            return
        except asyncio.TimeoutError:
            pass
        backoff = min(backoff * 2.0, 30.0)


def parse_args() -> Config:
    p = argparse.ArgumentParser(
        description="EduPing D435 depth+color → Control Server WS streamer",
    )
    p.add_argument(
        "--server-host",
        default=os.environ.get("DEPTH_SERVER_HOST", "127.0.0.1"),
        help="Control Server 호스트 (env DEPTH_SERVER_HOST, 기본 127.0.0.1)",
    )
    p.add_argument(
        "--server-port", type=int,
        default=int(os.environ.get("DEPTH_SERVER_PORT", "8100")),
        help="Control Server streaming port (env DEPTH_SERVER_PORT, 기본 8100)",
    )
    p.add_argument(
        "--robot", choices=list(ROBOT_IDS),
        default=os.environ.get("DEPTH_ROBOT", "eduping"),
    )
    # D435 최소 depth 해상도 = 424x240, 최소 fps = 6/15. 320x240 은 미지원.
    p.add_argument("--width", type=int, default=int(os.environ.get("DEPTH_WIDTH", "424")))
    p.add_argument("--height", type=int, default=int(os.environ.get("DEPTH_HEIGHT", "240")))
    p.add_argument("--fps", type=int, default=int(os.environ.get("DEPTH_FPS", "15")))
    p.add_argument(
        "--jpeg-quality", type=int,
        default=int(os.environ.get("DEPTH_JPEG_QUALITY", "70")),
    )
    p.add_argument(
        "--device-serial",
        default=os.environ.get("DEPTH_DEVICE_SERIAL"),
        help="여러 RealSense 가 꽂혔을 때 특정 device 시리얼 지정 (선택)",
    )
    p.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args, _unknown = p.parse_known_args()

    if not (1 <= args.jpeg_quality <= 100):
        p.error("--jpeg-quality 는 1..100")
    if not (1 <= args.fps <= 60):
        p.error("--fps 는 1..60")

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    return Config(
        server_host=args.server_host,
        server_port=args.server_port,
        robot=args.robot,
        width=args.width,
        height=args.height,
        fps=args.fps,
        jpeg_quality=args.jpeg_quality,
        device_serial=args.device_serial,
    )


def main() -> int:
    cfg = parse_args()
    log = logging.getLogger("d435")
    log.info(
        "config: server=%s:%d robot=%s %dx%d@%d quality=%d",
        cfg.server_host, cfg.server_port, cfg.robot,
        cfg.width, cfg.height, cfg.fps, cfg.jpeg_quality,
    )

    stop_event = asyncio.Event()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _shutdown(signum: int, _frame) -> None:
        log.info("signal %d — shutting down", signum)
        loop.call_soon_threadsafe(stop_event.set)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        loop.run_until_complete(_run(cfg, log, stop_event))
    finally:
        loop.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
