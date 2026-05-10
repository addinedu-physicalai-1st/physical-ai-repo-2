#!/usr/bin/env python3
"""GogoPing/EduPing/NoriArm 카메라 UDP 송출 — v4l2 직접 캡처 (저지연 모드).

[streamer.py](streamer.py) 와 동일한 와이어 프로토콜 (28B 헤더 + MJPEG)
이지만 cv2 의 BGR decode → JPEG re-encode 우회. linuxpy 로 v4l2 buffer 의 raw
MJPEG 바이트를 그대로 송신해서 ~15-35ms 지연 단축 + 이중 인코드 손실 제거.

설치 (Pi 측 1회):
  pip install linuxpy

실행:
  ros2 run gogoping_camera camera_streamer_v4l2 --robot gogoping
  ros2 launch gogoping_camera camera_stream.launch.py robot:=gogoping

공통 부분 (Config, StateController, machine_ips.json lookup, 헤더 포맷) 은
[streamer.py](streamer.py) 에서 import.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import struct
import sys
import threading
import time
import zlib
from typing import Optional

# 공통 로직 재사용 — 같은 패키지 내 streamer 모듈
from gogoping_camera.streamer import (
    CONTROL_SERVER_HOST_ENV,
    DEFAULT_CONTROL_SERVER_HOST,
    MAGIC_PING,
    MAX_JPEG_SIZE,
    ROBOT_IDS,
    Config,
    StateController,
    VIDEO_HEADER_FMT,
    resolve_server_ip_from_machine_ips,
)


def _to_bytes(frame) -> bytes:
    """linuxpy frame 객체 → bytes. API 차이 흡수."""
    if isinstance(frame, (bytes, bytearray, memoryview)):
        return bytes(frame)
    # linuxpy.video.device.Frame 은 bytes-protocol 또는 .data 속성
    for attr in ("data", "array"):
        v = getattr(frame, attr, None)
        if v is not None:
            try:
                return bytes(v)
            except (TypeError, ValueError):
                continue
    return bytes(frame)   # 마지막 시도 — 실패 시 raise


class V4L2VideoStreamer:
    """v4l2 직접 캡처 + UDP 영상 송신.

    cv2.imencode 없이 카메라 native MJPEG 바이트를 그대로 전송.
    StateController 가 streaming_enabled=False 일 때 캡처 정지.
    """

    def __init__(self, config: Config, state: StateController) -> None:
        self._config = config
        self._state = state
        self._device = None
        self._send_sock: Optional[socket.socket] = None
        self._frame_seq = 0
        self._stop_event = threading.Event()
        self._log = logging.getLogger("video.v4l2")

    def stop(self) -> None:
        self._stop_event.set()

    def _device_id(self) -> int:
        path = self._config.camera_device
        if path.startswith("/dev/video"):
            try:
                return int(path[len("/dev/video"):])
            except ValueError:
                return 0
        return 0

    def _open_camera(self) -> None:
        if self._device is not None:
            return
        try:
            from linuxpy.video.device import BufferType, Device
        except ImportError as exc:
            raise RuntimeError(
                f"linuxpy 모듈 없음: {exc}. Pi 측에서 `pip install linuxpy` 후 재시도."
            )

        dev_id = self._device_id()
        device = Device.from_id(dev_id)
        device.open()

        # set_format API 버전 호환성:
        # - 신버전: device.video_capture.set_format(w, h, "MJPG")
        # - 구버전: device.set_format(BufferType.VIDEO_CAPTURE, w, h, "MJPG")
        format_set = False
        capture_attr = getattr(device, "video_capture", None)
        if capture_attr is not None and hasattr(capture_attr, "set_format"):
            try:
                capture_attr.set_format(
                    self._config.width, self._config.height, "MJPG",
                )
                format_set = True
            except TypeError:
                # 시그니처 다른 버전 — 다음 fallback
                pass

        if not format_set:
            try:
                device.set_format(
                    BufferType.VIDEO_CAPTURE,
                    self._config.width,
                    self._config.height,
                    "MJPG",
                )
                format_set = True
            except Exception as exc:
                device.close()
                raise RuntimeError(
                    f"v4l2 set_format 실패 (MJPG {self._config.width}x{self._config.height}): {exc}"
                )

        # set_fps — 버전·카메라별 시그니처 다름. 시도하되 실패해도 진행.
        try:
            device.set_fps(BufferType.VIDEO_CAPTURE, self._config.fps)
        except (TypeError, AttributeError):
            try:
                device.set_fps(self._config.fps)
            except Exception:
                pass
        except Exception:
            pass

        self._device = device
        self._log.info(
            "v4l2 camera opened: /dev/video%d %dx%d @ %dfps MJPG (raw passthrough)",
            dev_id, self._config.width, self._config.height, self._config.fps,
        )

    def _release_camera(self) -> None:
        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None
            self._log.info("v4l2 camera released")

    def _open_socket(self) -> None:
        if self._send_sock is None:
            self._send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def _send_frame(self, jpeg_bytes: bytes) -> None:
        sock = self._send_sock
        if sock is None:
            return
        if len(jpeg_bytes) > MAX_JPEG_SIZE:
            self._log.warning(
                "frame %dB > %dB — drop (camera native MJPEG quality 너무 높음, "
                "v4l2-ctl 로 quality 조정 시도)",
                len(jpeg_bytes), MAX_JPEG_SIZE,
            )
            return
        if len(jpeg_bytes) < 100:
            # 비정상적으로 작은 frame (헤더만) — drop
            return

        crc = zlib.crc32(jpeg_bytes) & 0xFFFFFFFF
        ts_ms = int(time.time() * 1000)
        header = struct.pack(
            VIDEO_HEADER_FMT,
            MAGIC_PING, 1,
            self._config.robot_id, self._config.stream_id, 0,
            self._frame_seq, ts_ms, len(jpeg_bytes), crc,
        )
        try:
            sock.sendto(
                header + jpeg_bytes,
                (self._config.server_ip, self._config.video_port),
            )
        except OSError as exc:
            self._log.warning("sendto 실패: %s", exc)
            return
        self._frame_seq = (self._frame_seq + 1) & 0xFFFFFFFF

    def _capture_loop(self) -> None:
        """blocking iterator — stop_event 또는 streaming_enabled=False 시 break."""
        device = self._device
        if device is None:
            return
        # 신버전 linuxpy 는 device.video_capture 가 iterable, 구버전은 device 자체
        iterable = getattr(device, "video_capture", None) or device
        try:
            for frame in iterable:
                if self._stop_event.is_set():
                    return
                if not self._state.is_streaming():
                    return
                self._send_frame(_to_bytes(frame))
        except Exception as exc:
            self._log.warning("v4l2 iter 중단: %s", exc)
            self._release_camera()

    def run(self) -> None:
        self._open_socket()
        try:
            while not self._stop_event.is_set():
                if self._state.is_streaming():
                    if self._device is None:
                        try:
                            self._open_camera()
                        except RuntimeError as exc:
                            self._log.error("%s", exc)
                            self._stop_event.wait(1.0)
                            continue
                    self._capture_loop()
                else:
                    if self._device is not None and self._state.can_release_camera():
                        self._release_camera()
                    self._stop_event.wait(0.1)
        finally:
            self._release_camera()
            if self._send_sock is not None:
                self._send_sock.close()
                self._send_sock = None


def parse_args() -> Config:
    p = argparse.ArgumentParser(
        description="Pingdergarten 카메라 UDP 송출 — v4l2 직접 (저지연 모드)",
    )
    p.add_argument(
        "--server-ip",
        default=os.environ.get("CAMERA_SERVER_IP"),
        help=(
            "Control Server IP (env CAMERA_SERVER_IP). "
            "미지정 시 --control-server hostname 으로 shared/machine_ips.json 자동 lookup."
        ),
    )
    p.add_argument(
        "--control-server",
        default=os.environ.get(CONTROL_SERVER_HOST_ENV),
        help=(
            f"shared/machine_ips.json 의 hostname key (예: tonyno, leekt). "
            f"기본 '{DEFAULT_CONTROL_SERVER_HOST}', env {CONTROL_SERVER_HOST_ENV} 도 가능."
        ),
    )
    p.add_argument(
        "--robot",
        choices=list(ROBOT_IDS),
        default=os.environ.get("CAMERA_ROBOT"),
    )
    p.add_argument(
        "--camera-device",
        default=os.environ.get("CAMERA_DEVICE", "/dev/video0"),
    )
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--fps", type=int, default=25)
    p.add_argument(
        "--jpeg-quality", type=int, default=60,
        help=(
            "v4l2 모드에선 이 값은 참고용 — 카메라 native MJPEG quality 가 사용됨. "
            "frame size 가 65KB 초과하면 v4l2-ctl --set-ctrl=compression_quality=N 로 조정."
        ),
    )
    p.add_argument(
        "--stream-id", type=int, default=0,
        help="0=primary, 1..6=추가 stream",
    )
    p.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    # parse_known_args — ROS2 launch 가 주입하는 `--ros-args` 등을 무시.
    args, _unknown = p.parse_known_args()

    if not args.server_ip:
        args.server_ip = resolve_server_ip_from_machine_ips(args.control_server)
    if not args.server_ip:
        host = args.control_server or os.environ.get(
            CONTROL_SERVER_HOST_ENV
        ) or DEFAULT_CONTROL_SERVER_HOST
        p.error(
            f"--server-ip 또는 env CAMERA_SERVER_IP 필요 "
            f"(shared/machine_ips.json 의 '{host}' 항목 자동 lookup 도 실패)"
        )
    if not args.robot:
        p.error("--robot 또는 env CAMERA_ROBOT 가 필요합니다")
    if not (0 <= args.stream_id <= 6):
        p.error("--stream-id 는 0..6 범위")

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    return Config(
        server_ip=args.server_ip,
        robot=args.robot,
        camera_device=args.camera_device,
        width=args.width,
        height=args.height,
        fps=args.fps,
        jpeg_quality=args.jpeg_quality,
        stream_id=args.stream_id,
    )


def main() -> int:
    config = parse_args()
    log = logging.getLogger("main.v4l2")
    log.info(
        "config: server=%s robot=%s(0x%02x) cam=%s %dx%d@%d stream=%d (v4l2 direct)",
        config.server_ip, config.robot, config.robot_id,
        config.camera_device, config.width, config.height,
        config.fps, config.stream_id,
    )
    log.info(
        "ports: ctrl-listen=UDP/%d video-send=UDP/%d→%s",
        config.control_listen_port, config.video_port, config.server_ip,
    )

    state = StateController(config)
    streamer = V4L2VideoStreamer(config, state)

    def _shutdown(signum, _frame) -> None:
        log.info("signal %d — shutting down", signum)
        streamer.stop()
        state.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    state.start()
    streamer.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
