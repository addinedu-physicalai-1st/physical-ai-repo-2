#!/usr/bin/env python3
"""Loopback 검증용 가짜 카메라 송출기 (Pi/cv2 없이 실행).

camera_streamer.py 와 동일한 28B 헤더 + JPEG 프로토콜 (PLAN §5.1) 로
synthetic JPEG frame 을 Control Server 에 UDP 송신한다. 단계 8 통합 검증
에서 Vic Pinky 가 없을 때 server + admin-ui 파이프라인을 단독 검증.

JPEG 페이로드는 PIL 로 즉석 생성 (PIL 없으면 정적 더미 JPEG 사용).
camera_streamer.py 와 같은 manual STOP/START 신호 listener 도 포함 →
admin-ui 의 SR-CAM-005 도 검증 가능.

사용:
  python fake_streamer.py --robot gogoping
  python fake_streamer.py --robot gogoping --server-ip 127.0.0.1
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
from io import BytesIO
from pathlib import Path
from typing import Optional

# camera_streamer.py 의 ROBOT_IDS / 상수 재사용
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from camera_streamer import (   # noqa: E402
    ACTION_START,
    ACTION_STOP,
    CTRL_HEADER_FMT,
    CTRL_HEADER_SIZE,
    DEFAULT_CONTROL_SERVER_HOST,
    MAGIC_CTRL,
    MAGIC_PING,
    MAX_JPEG_SIZE,
    ROBOT_IDS,
    VIDEO_HEADER_FMT,
    Config,
    resolve_server_ip_from_machine_ips,
)


def _make_dummy_jpeg(seq: int, robot: str) -> bytes:
    """동적 JPEG (PIL 있으면 그라데이션 + seq 텍스트), 없으면 정적."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        # 정적 더미 — 1x1 검정 JPEG
        return (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xdb\x00C\x00" + b"\x10" * 64 +
            b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
            b"\xff\xc4\x00\x14\x00\x01" + b"\x00" * 15 + b"\x08"
            b"\xff\xc4\x00\x14\x10\x01" + b"\x00" * 15 + b"\x00"
            b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xc8\xff\xd9"
        )

    img = Image.new("RGB", (640, 480))
    draw = ImageDraw.Draw(img)
    # 그라데이션
    for y in range(480):
        c = int(255 * y / 480)
        draw.line([(0, y), (640, y)], fill=(c, 64, 255 - c))
    draw.rectangle([16, 16, 624, 80], fill=(0, 0, 0))
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    text = f"{robot} #{seq}"
    draw.text((24, 28), text, fill=(255, 255, 255), font=font)
    draw.text((24, 50), time.strftime("%H:%M:%S"), fill=(255, 255, 0), font=font)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


class _FakeState:
    """수동 STOP/START 신호 listener (camera_streamer 와 동일 프로토콜)."""

    def __init__(self, port: int) -> None:
        self._port = port
        self._lock = threading.Lock()
        self._enabled = True
        self._last_intent_seq = 0
        self._stop = threading.Event()
        self._log = logging.getLogger("ctrl")

    def is_streaming(self) -> bool:
        with self._lock:
            return self._enabled

    def stop(self) -> None:
        self._stop.set()

    def start(self) -> None:
        threading.Thread(
            target=self._listen, name="ctrl-listener", daemon=True,
        ).start()

    def _listen(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", self._port))
        except OSError as exc:
            self._log.error("ctrl bind 실패 port %d: %s", self._port, exc)
            return
        sock.settimeout(1.0)
        self._log.info("ctrl listen UDP %d (default ON)", self._port)
        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(64)
            except socket.timeout:
                continue
            except OSError:
                break
            if len(data) < CTRL_HEADER_SIZE:
                continue
            try:
                magic, ver, action, _r, seq = struct.unpack(
                    CTRL_HEADER_FMT, data[:CTRL_HEADER_SIZE],
                )
            except struct.error:
                continue
            if magic != MAGIC_CTRL or ver != 1:
                continue
            with self._lock:
                if seq <= self._last_intent_seq:
                    continue
                self._last_intent_seq = seq
                if action == ACTION_START and not self._enabled:
                    self._enabled = True
                    self._log.info("manual START seq=%d from %s", seq, addr)
                elif action == ACTION_STOP and self._enabled:
                    self._enabled = False
                    self._log.info("manual STOP seq=%d from %s", seq, addr)
        try:
            sock.close()
        except OSError:
            pass


def main() -> int:
    p = argparse.ArgumentParser(description="Loopback 가짜 카메라 송출기 (PIL 권장)")
    p.add_argument("--server-ip", default=os.environ.get("CAMERA_SERVER_IP"))
    p.add_argument("--robot", choices=list(ROBOT_IDS), required=False,
                   default=os.environ.get("CAMERA_ROBOT", "gogoping"))
    p.add_argument("--fps", type=int, default=25)
    p.add_argument("--stream-id", type=int, default=0)
    p.add_argument("--limit", type=int, default=0,
                   help="송신할 frame 수 (기본 0 = 무한)")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args()

    server_ip = args.server_ip or resolve_server_ip_from_machine_ips() or "127.0.0.1"

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("fake")

    cfg = Config(
        server_ip=server_ip, robot=args.robot, camera_device="N/A",
        width=640, height=480, fps=args.fps,
        jpeg_quality=70, stream_id=args.stream_id,
    )
    state = _FakeState(port=cfg.control_listen_port)
    state.start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = (cfg.server_ip, cfg.video_port)
    log.info(
        "robot=%s(0x%02x) target=%s:%d ctrl-listen=%d fps=%d",
        cfg.robot, cfg.robot_id, cfg.server_ip, cfg.video_port,
        cfg.control_listen_port, cfg.fps,
    )

    def _shutdown(signum, _f) -> None:
        log.info("signal %d — shutting down", signum)
        state.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    period = 1.0 / cfg.fps
    next_tick = time.monotonic()
    seq = 0
    sent = 0
    while True:
        if state.is_streaming():
            jpeg = _make_dummy_jpeg(seq, cfg.robot)
            if len(jpeg) > MAX_JPEG_SIZE:
                log.warning("frame %dB > %dB", len(jpeg), MAX_JPEG_SIZE)
            else:
                crc = zlib.crc32(jpeg) & 0xFFFFFFFF
                ts = int(time.time() * 1000)
                header = struct.pack(
                    VIDEO_HEADER_FMT,
                    MAGIC_PING, 1, cfg.robot_id, cfg.stream_id, 0,
                    seq, ts, len(jpeg), crc,
                )
                try:
                    sock.sendto(header + jpeg, target)
                    sent += 1
                except OSError as exc:
                    log.warning("sendto: %s", exc)
                seq = (seq + 1) & 0xFFFFFFFF
                if args.limit and sent >= args.limit:
                    log.info("limit %d 도달 — 종료", args.limit)
                    break
        next_tick += period
        sleep_for = next_tick - time.monotonic()
        if sleep_for > 0:
            time.sleep(sleep_for)
        else:
            next_tick = time.monotonic()

    state.stop()
    sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
