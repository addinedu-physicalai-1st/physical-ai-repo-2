#!/usr/bin/env python3
"""GogoPing/EduPing/NoriArm 카메라 UDP 송출 스크립트.

Pi 측에서 USB 웹캠 영상을 MJPEG 으로 캡처해 Control Server 에 UDP 단일
패킷 = 단일 frame 형식으로 송신한다. 별도 스레드에서 admin 의 수동
START/STOP 제어 신호를 listen 한다.

기본 동작 (default ON): 실행 직후 즉시 송출 시작. 자동 종료 트리거 없음.
admin 의 수동 STOP 신호 수신 시에만 송출 일시 중지.

설계: device/gogoping_stream_ws/PLAN.md
관련 SR: SR-CAM-001 (docs/implementation-plan.md §2.7)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socket
import struct
import sys
import threading
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2

# robot_id 매핑 (PLAN §5.1)
ROBOT_IDS = {"gogoping": 0x01, "eduping": 0x02, "noriarm": 0x03}

# 패킷 magic
MAGIC_PING = b"PING"
MAGIC_CTRL = b"CTRL"

# 제어 action (PLAN §5.2)
ACTION_START = 0x01
ACTION_STOP = 0x02

# 영상 헤더 28B (PLAN §5.1)
# magic[4s] + version[B] + robot_id[B] + stream_id[B] + flags[B]
# + frame_seq[I] + ts_ms[Q] + jpeg_size[I] + crc32[I]
VIDEO_HEADER_FMT = "!4sBBBBIQII"
VIDEO_HEADER_SIZE = struct.calcsize(VIDEO_HEADER_FMT)
assert VIDEO_HEADER_SIZE == 28

# 제어 헤더 12B (PLAN §5.2)
# magic[4s] + version[B] + action[B] + reserved[H] + intent_seq[I]
CTRL_HEADER_FMT = "!4sBBHI"
CTRL_HEADER_SIZE = struct.calcsize(CTRL_HEADER_FMT)
assert CTRL_HEADER_SIZE == 12

# UDP 페이로드 한계 — IPv4 max 65507B - 28B 헤더 = 65479B 까지 가능.
# 65400 으로 약간 보수적 마진 (q70 의 가변 frame size 수용).
MAX_JPEG_SIZE = 65400

# STOP 후 카메라 핸들 release 까지 keep-alive
CAMERA_KEEPALIVE_S = 60.0

# Control Server hostname (machine_ips.json 의 key)
DEFAULT_CONTROL_SERVER_HOST = "tonyno"
# Env var 로 hostname override 가능 (예: CONTROL_SERVER_NAME=leekt)
CONTROL_SERVER_HOST_ENV = "CONTROL_SERVER_NAME"


@dataclass
class Config:
    server_ip: str
    robot: str
    camera_device: str
    width: int
    height: int
    fps: int
    jpeg_quality: int
    stream_id: int

    @property
    def robot_id(self) -> int:
        return ROBOT_IDS[self.robot]

    @property
    def base_port(self) -> int:
        # gogoping=9010, eduping=9020, noriarm=9030
        return 9000 + ROBOT_IDS[self.robot] * 10

    @property
    def video_port(self) -> int:
        # role 3 = primary, role 4..9 = additional (stream_id 0..6)
        return self.base_port + 3 + self.stream_id

    @property
    def control_listen_port(self) -> int:
        # role 2 = Server → Pi 제어
        return self.base_port + 2

    @property
    def reserved_ws_port(self) -> int:
        # role 0 = 예약 (로봇 장비와 websocket — 추후 SR)
        return self.base_port + 0


def resolve_server_ip_from_machine_ips(host: Optional[str] = None) -> Optional[str]:
    """[shared/machine_ips.json](../../../shared/machine_ips.json) 에서 Control Server IP lookup.

    host 우선순위:
      1. 인자 host (None 이 아니면)
      2. env CONTROL_SERVER_NAME
      3. DEFAULT_CONTROL_SERVER_HOST ('tonyno')

    Pi 측 프로젝트 루트는 보통 ~/pingdergarten 또는 /home/<user>/pingdergarten.
    이 스크립트의 부모 디렉토리들을 거슬러 올라가며 shared/machine_ips.json 을 찾음.
    """
    if not host:
        host = os.environ.get(CONTROL_SERVER_HOST_ENV) or DEFAULT_CONTROL_SERVER_HOST
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / "shared" / "machine_ips.json"
        if candidate.is_file():
            try:
                data = json.loads(candidate.read_text())
                entry = data.get(host)
                if entry and "ip" in entry:
                    return str(entry["ip"])
            except (json.JSONDecodeError, OSError):
                return None
    return None


class StateController:
    """Server 의 수동 START/STOP 제어 신호를 listen.

    intent_seq 가 단조 증가하지 않으면 옛 신호로 간주해 폐기.
    streaming_enabled 플래그를 lock 보호로 토글한다.

    기본값: streaming_enabled=True (실행 직후 송출).
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._streaming_enabled = True   # default ON (PLAN §1.5)
        self._last_intent_seq = 0
        self._last_stop_at: Optional[float] = None
        self._stop_event = threading.Event()
        self._listener_thread: Optional[threading.Thread] = None
        self._log = logging.getLogger("ctrl")

    def start(self) -> None:
        self._listener_thread = threading.Thread(
            target=self._listen, name="ctrl-listener", daemon=True,
        )
        self._listener_thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def is_streaming(self) -> bool:
        with self._lock:
            return self._streaming_enabled

    def can_release_camera(self) -> bool:
        with self._lock:
            if self._streaming_enabled:
                return False
            if self._last_stop_at is None:
                return False
            return (time.monotonic() - self._last_stop_at) >= CAMERA_KEEPALIVE_S

    def _listen(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", self._config.control_listen_port))
        except OSError as exc:
            self._log.error(
                "control listener bind 실패 port %d: %s",
                self._config.control_listen_port, exc,
            )
            return
        sock.settimeout(1.0)
        self._log.info(
            "control listener bound on UDP %d (default ON)",
            self._config.control_listen_port,
        )

        while not self._stop_event.is_set():
            try:
                data, addr = sock.recvfrom(64)
            except socket.timeout:
                continue
            except OSError:
                break
            self._handle_packet(data, addr)

        try:
            sock.close()
        except OSError:
            pass

    def _handle_packet(self, data: bytes, addr) -> None:
        if len(data) < CTRL_HEADER_SIZE:
            return
        try:
            magic, ver, action, _reserved, seq = struct.unpack(
                CTRL_HEADER_FMT, data[:CTRL_HEADER_SIZE],
            )
        except struct.error:
            return
        if magic != MAGIC_CTRL or ver != 1:
            return

        with self._lock:
            if seq <= self._last_intent_seq:
                # 옛 신호 (UDP 순서 뒤바뀜) — 폐기
                return
            self._last_intent_seq = seq
            if action == ACTION_START:
                if not self._streaming_enabled:
                    self._streaming_enabled = True
                    self._last_stop_at = None
                    self._log.info("manual START seq=%d from %s", seq, addr)
            elif action == ACTION_STOP:
                if self._streaming_enabled:
                    self._streaming_enabled = False
                    self._last_stop_at = time.monotonic()
                    self._log.info("manual STOP seq=%d from %s", seq, addr)


class VideoStreamer:
    """카메라 캡처 + UDP 영상 송신 메인 루프.

    StateController 의 streaming_enabled 가 True 일 때만 캡처/송신.
    STOP 후 CAMERA_KEEPALIVE_S 초 경과 시 카메라 핸들 release.
    """

    def __init__(self, config: Config, state: StateController) -> None:
        self._config = config
        self._state = state
        self._cap: Optional[cv2.VideoCapture] = None
        self._send_sock: Optional[socket.socket] = None
        self._frame_seq = 0
        self._stop_event = threading.Event()
        self._log = logging.getLogger("video")

    def stop(self) -> None:
        self._stop_event.set()

    def _open_camera(self) -> None:
        if self._cap is not None and self._cap.isOpened():
            return
        cap = cv2.VideoCapture(self._config.camera_device)
        # MJPEG fourcc 강제 — HW 압축 사용
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._config.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._config.height)
        cap.set(cv2.CAP_PROP_FPS, self._config.fps)
        if not cap.isOpened():
            raise RuntimeError(
                f"카메라를 열 수 없습니다: {self._config.camera_device}"
            )
        self._cap = cap
        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = cap.get(cv2.CAP_PROP_FPS)
        self._log.info(
            "camera opened: %s %dx%d @ %.1ffps",
            self._config.camera_device, actual_w, actual_h, actual_fps,
        )

    def _release_camera(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            self._log.info("camera released (idle %ds)", int(CAMERA_KEEPALIVE_S))

    def _open_socket(self) -> None:
        if self._send_sock is None:
            self._send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def _capture_and_send(self) -> None:
        cap = self._cap
        sock = self._send_sock
        if cap is None or sock is None:
            return
        ok, frame = cap.read()
        if not ok or frame is None:
            return
        ok, jpeg_buf = cv2.imencode(
            ".jpg", frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), self._config.jpeg_quality],
        )
        if not ok:
            return
        jpeg_bytes = jpeg_buf.tobytes()
        if len(jpeg_bytes) > MAX_JPEG_SIZE:
            self._log.warning(
                "frame %dB > %dB — drop (해상도/quality 낮춰야 함)",
                len(jpeg_bytes), MAX_JPEG_SIZE,
            )
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

    def run(self) -> None:
        self._open_socket()
        target_period = 1.0 / self._config.fps
        next_tick = time.monotonic()

        while not self._stop_event.is_set():
            if self._state.is_streaming():
                if self._cap is None:
                    try:
                        self._open_camera()
                    except RuntimeError as exc:
                        self._log.error("%s", exc)
                        time.sleep(1.0)
                        continue
                self._capture_and_send()
            else:
                if self._cap is not None and self._state.can_release_camera():
                    self._release_camera()

            # FPS 제어 (단순 슬립, 밀리면 catch-up 안 함)
            next_tick += target_period
            now = time.monotonic()
            sleep_for = next_tick - now
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                next_tick = now

        self._release_camera()
        if self._send_sock is not None:
            self._send_sock.close()
            self._send_sock = None


def parse_args() -> Config:
    p = argparse.ArgumentParser(
        description="Pingdergarten 카메라 UDP 송출 (default ON, manual STOP/START)",
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
        help="로봇 이름 (env CAMERA_ROBOT)",
    )
    p.add_argument(
        "--camera-device",
        default=os.environ.get("CAMERA_DEVICE", "/dev/video0"),
        help="V4L2 디바이스 (기본 /dev/video0)",
    )
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--fps", type=int, default=25)
    p.add_argument(
        "--jpeg-quality", type=int, default=60,
        help="MJPEG quality 1..100 (기본 60, 가변 frame size 마진 확보)",
    )
    p.add_argument(
        "--stream-id", type=int, default=0,
        help="0=primary, 1..6=추가 stream (기본 0)",
    )
    p.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = p.parse_args()

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
    if not (1 <= args.jpeg_quality <= 100):
        p.error("--jpeg-quality 는 1..100")

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
    log = logging.getLogger("main")
    log.info(
        "config: server=%s robot=%s(0x%02x) cam=%s %dx%d@%d q=%d stream=%d",
        config.server_ip, config.robot, config.robot_id,
        config.camera_device, config.width, config.height,
        config.fps, config.jpeg_quality, config.stream_id,
    )
    log.info(
        "ports: ctrl-listen=UDP/%d video-send=UDP/%d→%s",
        config.control_listen_port, config.video_port, config.server_ip,
    )

    state = StateController(config)
    streamer = VideoStreamer(config, state)

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
