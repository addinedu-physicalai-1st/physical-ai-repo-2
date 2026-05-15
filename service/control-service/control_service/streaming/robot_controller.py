"""수동 admin STOP/START 송신.

PLAN §3.6, §5.2, SR-CAM-005.
자동 트리거 (subscriber 카운트 기반) 없음. admin 의 명시적 액션만.

Pi IP 는 [shared/machine_ips.json](../../../shared/machine_ips.json) 에서 hostname 으로 조회.
1초 간격 3회 재전송 (idempotent + intent_seq 단조 증가).
"""
from __future__ import annotations

import asyncio
import logging
import socket
from collections import defaultdict

from control_service.streaming import config as scfg
from control_service.streaming.protocol import (
    ACTION_START, ACTION_STOP, encode_ctrl_packet,
)


_log = logging.getLogger("streaming.controller")


class RobotController:
    """admin 의 명시적 STOP/START 요청을 Pi 에 송신."""

    def __init__(self) -> None:
        self._intent_seq: dict[int, int] = defaultdict(int)
        self._addrs: dict[int, tuple[str, int]] = self._load_addrs()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def _load_addrs(self) -> dict[int, tuple[str, int]]:
        machines = scfg.load_machine_ips()
        out: dict[int, tuple[str, int]] = {}
        for robot_id, host in scfg.ROBOT_HOST.items():
            if not host:   # eduping/noriarm 은 추후 SR (Q6)
                continue
            entry = machines.get(host)
            if entry is None:
                _log.warning(
                    "machine_ips.json 에 host '%s' 없음 (robot %d)",
                    host, robot_id,
                )
                continue
            ip = str(entry.get("ip", "")).strip()
            if not ip:
                _log.warning("host '%s' 의 ip 비어있음 (robot %d)", host, robot_id)
                continue
            out[robot_id] = (ip, scfg.control_port(robot_id))
            _log.info(
                "robot %d (%s) → %s:%d",
                robot_id, host, ip, scfg.control_port(robot_id),
            )
        return out

    def has_robot(self, robot_id: int) -> bool:
        return robot_id in self._addrs

    def known_robots(self) -> list[int]:
        return sorted(self._addrs.keys())

    async def manual_start(self, robot_id: int) -> bool:
        return await self._send_async(robot_id, ACTION_START)

    async def manual_stop(self, robot_id: int) -> bool:
        return await self._send_async(robot_id, ACTION_STOP)

    async def _send_async(self, robot_id: int, action: int) -> bool:
        addr = self._addrs.get(robot_id)
        if addr is None:
            _log.warning(
                "robot %d 의 IP 가 등록되지 않음 (machine_ips.json 확인)",
                robot_id,
            )
            return False

        self._intent_seq[robot_id] += 1
        seq = self._intent_seq[robot_id]
        pkt = encode_ctrl_packet(action, seq)
        action_name = "START" if action == ACTION_START else "STOP"
        retransmit = scfg.settings.control_retransmit_count
        interval = scfg.settings.control_retransmit_interval_s
        _log.info(
            "%s robot %d (seq=%d) → %s:%d × %d",
            action_name, robot_id, seq, addr[0], addr[1], retransmit,
        )
        for i in range(retransmit):
            try:
                self._sock.sendto(pkt, addr)
            except OSError as exc:
                _log.warning(
                    "sendto 실패 (%d/%d): %s", i + 1, retransmit, exc,
                )
            if i < retransmit - 1:
                await asyncio.sleep(interval)
        return True

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass
