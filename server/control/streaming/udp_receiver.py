"""UDP 영상 수신 스레드.

PLAN §6 — 로봇별 1개 daemon thread, blocking recvfrom (GIL release),
asyncio 와의 다리는 loop.call_soon_threadsafe(hub.publish, packet).
"""
from __future__ import annotations

import asyncio
import logging
import socket
import threading
from typing import TYPE_CHECKING

from server.control.streaming.protocol import parse_video_packet

if TYPE_CHECKING:
    from server.control.streaming.frame_hub import FrameHub


class UdpFrameReceiver(threading.Thread):
    """단일 로봇의 영상 UDP 패킷 수신 + 파싱 + asyncio dispatch."""

    def __init__(
        self,
        robot_id: int,
        port: int,
        hub: "FrameHub",
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        super().__init__(name=f"udp-recv-r{robot_id}", daemon=True)
        self._robot_id = robot_id
        self._port = port
        self._hub = hub
        self._loop = loop
        self._stop_event = threading.Event()
        self._sock: socket.socket | None = None
        self._frames_received = 0
        self._frames_dropped = 0
        self._log = logging.getLogger(f"streaming.udp.r{robot_id}")

    @property
    def robot_id(self) -> int:
        return self._robot_id

    @property
    def port(self) -> int:
        return self._port

    @property
    def frames_received(self) -> int:
        return self._frames_received

    @property
    def frames_dropped(self) -> int:
        return self._frames_dropped

    def stop(self) -> None:
        self._stop_event.set()
        sock = self._sock
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # 영상 frame 이 65KB 이내라 recv buffer 크게
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024)
        except OSError:
            pass
        try:
            sock.bind(("0.0.0.0", self._port))
        except OSError as exc:
            self._log.error("bind UDP %d 실패: %s", self._port, exc)
            return
        sock.settimeout(1.0)
        self._sock = sock
        self._log.info(
            "listen UDP %d (robot_id=%d)", self._port, self._robot_id,
        )

        while not self._stop_event.is_set():
            try:
                data, _addr = sock.recvfrom(70_000)
            except socket.timeout:
                continue
            except OSError:
                break

            packet = parse_video_packet(data)
            if packet is None:
                self._frames_dropped += 1
                continue
            if packet.robot_id != self._robot_id:
                # 다른 robot_id 의 패킷이 잘못 온 경우 (포트 매핑 오류 등)
                self._frames_dropped += 1
                continue

            self._frames_received += 1
            try:
                self._loop.call_soon_threadsafe(self._hub.publish, packet)
            except RuntimeError:
                # loop 종료
                break

        try:
            sock.close()
        except OSError:
            pass
        self._sock = None
        self._log.info(
            "stopped (received=%d dropped=%d)",
            self._frames_received, self._frames_dropped,
        )
