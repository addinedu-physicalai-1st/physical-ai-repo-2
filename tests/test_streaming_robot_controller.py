"""service/control-service/control_service/streaming/robot_controller.py 단위 테스트.

PLAN §3.6, §5.2, SR-CAM-005.

자동 트리거 없음 — manual_start/manual_stop 만. intent_seq 단조 증가.
"""

from __future__ import annotations

import struct
from unittest.mock import MagicMock, patch

import pytest

from control_service.streaming import config as scfg
from control_service.streaming.protocol import (
    ACTION_START,
    ACTION_STOP,
    CTRL_HEADER_FMT,
    MAGIC_CTRL,
)
from control_service.streaming.robot_controller import RobotController


@pytest.fixture
def fake_machines(monkeypatch) -> dict:
    """machine_ips.json 을 메모리 dict 로 대체."""
    machines = {
        "vic": {"mac": "x", "ip": "10.0.0.2", "found_at": "now"},
    }
    monkeypatch.setattr(scfg, "load_machine_ips", lambda: machines)
    return machines


@pytest.fixture
def fast_retransmit(monkeypatch) -> None:
    """1초 × 3회 재전송 → 0.001초 × 3회 로 단축."""
    monkeypatch.setattr(scfg.settings, "control_retransmit_count", 3)
    monkeypatch.setattr(scfg.settings, "control_retransmit_interval_s", 0.001)


@pytest.fixture
def controller(fake_machines, fast_retransmit) -> RobotController:
    ctl = RobotController()
    # 실 UDP send 차단 — sendto 호출만 기록
    ctl._sock = MagicMock()
    yield ctl


# ------------------------------------------------- 초기화


def test_loads_only_robots_with_host_in_machine_ips(controller: RobotController) -> None:
    # gogoping (vic) 만 등록, eduping/noriarm 은 host=None → skip
    assert controller.has_robot(1) is True
    assert controller.has_robot(2) is False
    assert controller.has_robot(3) is False


def test_known_robots_returns_only_registered(controller: RobotController) -> None:
    assert controller.known_robots() == [1]


def test_machine_ips_missing_host_skipped(monkeypatch) -> None:
    """machine_ips.json 에 'vic' 항목이 없으면 robot 1 도 미등록."""
    monkeypatch.setattr(scfg, "load_machine_ips", lambda: {})
    ctl = RobotController()
    ctl._sock = MagicMock()
    assert ctl.has_robot(1) is False


# ------------------------------------------------- manual_start/stop


async def test_manual_start_sends_start_packet(controller: RobotController) -> None:
    ok = await controller.manual_start(1)
    assert ok is True
    # sendto 가 3회 호출됨 (control_retransmit_count=3)
    assert controller._sock.sendto.call_count == 3
    # 첫 패킷 검증
    pkt, addr = controller._sock.sendto.call_args_list[0].args
    magic, ver, action, _resv, seq = struct.unpack(CTRL_HEADER_FMT, pkt)
    assert magic == MAGIC_CTRL
    assert action == ACTION_START
    assert seq == 1
    assert addr == ("10.0.0.2", 9012)   # gogoping control port (role 2)


async def test_manual_stop_sends_stop_packet(controller: RobotController) -> None:
    ok = await controller.manual_stop(1)
    assert ok is True
    pkt, _addr = controller._sock.sendto.call_args_list[0].args
    _, _, action, _, _ = struct.unpack(CTRL_HEADER_FMT, pkt)
    assert action == ACTION_STOP


async def test_unknown_robot_returns_false(controller: RobotController) -> None:
    """machine_ips 에 host 등록 안 된 robot 은 False 반환."""
    ok = await controller.manual_start(2)   # eduping
    assert ok is False
    assert controller._sock.sendto.call_count == 0


# ------------------------------------------------- intent_seq 단조 증가


async def test_intent_seq_monotonic_within_robot(controller: RobotController) -> None:
    """같은 로봇에 대한 연속 액션은 seq 가 1, 2, 3, ... 단조 증가."""
    seqs = []
    for _ in range(4):
        controller._sock.reset_mock()
        await controller.manual_start(1)
        pkt, _ = controller._sock.sendto.call_args_list[0].args
        _, _, _, _, seq = struct.unpack(CTRL_HEADER_FMT, pkt)
        seqs.append(seq)
    assert seqs == [1, 2, 3, 4]


async def test_intent_seq_independent_per_robot(monkeypatch) -> None:
    """로봇마다 독립적인 seq counter."""
    machines = {
        "vic": {"mac": "x", "ip": "10.0.0.2", "found_at": "now"},
        "edu": {"mac": "y", "ip": "10.0.0.3", "found_at": "now"},
    }
    monkeypatch.setattr(scfg, "load_machine_ips", lambda: machines)
    monkeypatch.setattr(scfg.settings, "control_retransmit_count", 1)
    monkeypatch.setattr(scfg.settings, "control_retransmit_interval_s", 0.001)
    monkeypatch.setattr(scfg, "ROBOT_HOST", {1: "vic", 2: "edu", 3: None})

    ctl = RobotController()
    ctl._sock = MagicMock()

    await ctl.manual_start(1)   # robot 1 seq=1
    await ctl.manual_start(2)   # robot 2 seq=1
    await ctl.manual_stop(1)    # robot 1 seq=2

    pkts = [c.args[0] for c in ctl._sock.sendto.call_args_list]
    seqs = [struct.unpack(CTRL_HEADER_FMT, p)[4] for p in pkts]
    assert seqs == [1, 1, 2]


# ------------------------------------------------- 자동 트리거 없음 검증


def test_no_subscribe_count_methods_exposed(controller: RobotController) -> None:
    """RobotController 는 add/remove_subscriber 같은 자동 트리거 메서드를 노출하지 않는다.

    PLAN §1.5: 자동 STOP/START 제거됨. manual_* 만.
    """
    assert not hasattr(controller, "add_subscriber")
    assert not hasattr(controller, "remove_subscriber")
