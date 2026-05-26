"""Streaming module 설정 — 포트 매핑, 로봇 호스트 lookup, 타임아웃.

관련 SR: SR-CAM-001/002 (docs/implementation-plan.md §2.7).
포트 컨벤션: 9_DD_R (DD=robot_id 01~99, R=role 0~9. 본 파일 함수 참조).
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic_settings import BaseSettings


# ---- robot_id 매핑 (PLAN §5.1) ----

ROBOT_IDS = {"gogoping": 0x01, "eduping": 0x02, "noriarm": 0x03}
ID_TO_NAME = {v: k for k, v in ROBOT_IDS.items()}


# ---- 포트 매핑 (PLAN §0 / §5) ----
# 공식: port = 9000 + robot_id*10 + role
# role 0 = 예약 (로봇 장비와 websocket — 추후 SR)
# role 1 = Pi → Server 제어 (telemetry/ACK/error 보고 — 추후 SR)
# role 2 = Server → Pi 제어 (수동 STOP/START + intent_seq)
# role 3 = Pi → Server 영상 stream 0 (primary)
# role 4..9 = Pi → Server 영상 stream 1..6 (총 7 streams / 로봇)

def control_port(robot_id: int) -> int:
    """Server → Pi 제어 송신 포트 (role 2)."""
    return 9000 + robot_id * 10 + 2


def video_port(robot_id: int, stream_id: int = 0) -> int:
    """Pi → Server 영상 수신 포트 (role 3 + stream_id, stream_id 0..6)."""
    return 9000 + robot_id * 10 + 3 + stream_id


def reserved_ws_port(robot_id: int) -> int:
    """예약 (role 0, 추후 SR)."""
    return 9000 + robot_id * 10 + 0


def pi_to_server_control_port(robot_id: int) -> int:
    """Pi → Server 제어 (role 1, 추후 SR)."""
    return 9000 + robot_id * 10 + 1


# ---- machine_ips.json hostname 매핑 (PLAN §8 단계 3) ----

CONTROL_SERVER_HOST = "tonyno"   # 자기 자신 (sanity / 로깅용)

# robot_id → machine_ips.json 의 hostname key
# 이번 SR 은 gogoping=vic 만 활성. EduPing/NoriArm 은 Q6 결정 후 추후 SR.
ROBOT_HOST: dict[int, str | None] = {
    1: "vic",     # gogoping (Vic Pinky 라즈베리파이)
    2: None,      # eduping  — Q6, 추후 SR
    3: None,      # noriarm  — Q6, 추후 SR
}

REPO_ROOT = Path(__file__).resolve().parents[4]
MACHINE_IPS_PATH = REPO_ROOT / "shared" / "machine_ips.json"


def load_machine_ips() -> dict:
    """[shared/machine_ips.json](../../../shared/machine_ips.json) 로드 (실패 시 빈 dict)."""
    try:
        return json.loads(MACHINE_IPS_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


# ---- 설정 ----

class Settings(BaseSettings):
    # WebSocket 포트 (TCP control plane — 8XXX 권역, AI Hub 8001 / pgweb 8081 옆)
    streaming_port: int = 8100

    # Heartbeat (PLAN §5.3)
    heartbeat_interval_s: float = 30.0
    heartbeat_timeout_s: float = 60.0

    # 부팅 sanity check (PLAN §3.6)
    boot_check_delay_s: float = 5.0

    # 제어 패킷 재전송 (PLAN §5.2)
    control_retransmit_count: int = 3
    control_retransmit_interval_s: float = 1.0

    # WS 클라이언트 send_queue 크기 (frame 단위)
    client_send_queue_size: int = 8

    # WS 핸드셰이크 cookie 인증 (PLAN §5.4, Q4)
    # 운영 환경: True (fastapi-users 세션 쿠키 검증)
    # 개발 환경: False (admin-app 가 로그인 흐름 추가 전까지 임시 false 가능)
    # 환경변수 STREAMING_REQUIRE_AUTH=true|false 로 override
    require_auth: bool = False

    # gogoping UDP 영상 수신 활성화 — D435 + WebRTC 로 전환됨.
    # eduping/noriarm 은 계속 UDP 사용. 운영 중 fallback 필요 시
    # STREAMING_GOGOPING_UDP_ENABLED=true 로 다시 켤 수 있음.
    gogoping_udp_enabled: bool = False

    class Config:
        env_prefix = "STREAMING_"
        extra = "ignore"


settings = Settings()
