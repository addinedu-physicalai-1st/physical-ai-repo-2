"""Doctor leader ↔ EduPing follower 양방향 teleop relay (cross-machine).

a-2 (eduping↔doctor ROS 도메인 분리) 에서 leader 관절 스트림과 follower
joint_states 는 ROS DDS 로 cross-machine 못 감 — 카메라(/ws/eduping/rgb) ·
FSR(/ws/eduping/stetho) 와 동일하게 WebSocket 으로 우회.

흐름:
    [Doctor 머신]                    [Control 서버]                 [woobuntu]
    feetech_leader_node                                            teleop_ws_robot_node
      → /eduping/leader/joint_states                                 ← /eduping/leader (로컬 publish)
      → leader_ws_uploader ──leader──→ /ws/eduping/teleop ──leader──→  → leader_passthrough (JTC)
        (role=leader_src)               (role=robot)                       → 실물 follower
                                              │
    doctor 3D ← StateFrame ← push loop ← hub.on_follower ←follower─ /joint_states(실물)

엔드포인트: ``/ws/eduping/teleop``
  - role=robot      (woobuntu): server→ 이쪽으로 leader 프레임 forward (active 일 때만).
                                이쪽→ server 로 follower joint_states 송신.
  - role=leader_src (doctor uploader): server 로 leader 프레임 송신 (producer only).

active gate — doctor UI "Telehealth 시작/정지" 이벤트가 ``set_active`` 호출.
정지 상태에선 leader 프레임을 robot 으로 forward 안 함 → follower 마지막 위치 hold.

Wire format: 양방향 모두 바이너리 joint frame (streaming.teleop_protocol MSG_JOINTS
0x03). leader 프레임은 relay 가 디코드 없이 bytes 그대로 forward 하고, follower
프레임만 디코드해 (names, positions) 콜백으로 넘긴다 (three.js StateFrame 소스).
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from control_service.streaming.teleop_protocol import decode_joints

log = logging.getLogger(__name__)

# follower 프레임 도착 시 호출 — (names, positions). control-service 가
# DoctorRosBridge.update_follower_state 로 연결 (three.js StateFrame 소스).
FollowerCb = Callable[[list, list], None]


class TeleopRelayHub:
    """leader_src → robot leader 프레임 forward + robot → follower 콜백.

    robot 0~1 (woobuntu), leader_src 0~1 (doctor uploader).
    같은 uvicorn event loop 안이라 forward 는 직접 ``await ws.send_text``.
    """

    def __init__(self) -> None:
        self._robot: WebSocket | None = None
        self._active = False
        self._follower_cb: Optional[FollowerCb] = None

    # ── gating ──────────────────────────────────────────────────────────
    def set_active(self, active: bool) -> None:
        if active != self._active:
            log.info("teleop relay active=%s", active)
        self._active = bool(active)

    @property
    def active(self) -> bool:
        return self._active

    def on_follower(self, cb: FollowerCb) -> None:
        self._follower_cb = cb

    # ── robot (woobuntu) ────────────────────────────────────────────────
    async def register_robot(self, ws: WebSocket) -> None:
        prev = self._robot
        if prev is not None:
            try:
                await prev.close(code=status.WS_1000_NORMAL_CLOSURE)
            except Exception:
                pass
        self._robot = ws
        log.info("teleop relay robot registered")

    async def unregister_robot(self, ws: WebSocket) -> None:
        if self._robot is ws:
            self._robot = None
            log.info("teleop relay robot gone")

    def _on_follower_bytes(self, data: bytes) -> None:
        cb = self._follower_cb
        if cb is None:
            return
        try:
            names, positions = decode_joints(data)
        except ValueError:
            return
        cb(names, positions)

    # ── leader_src (doctor uploader) ────────────────────────────────────
    async def forward_leader(self, data: bytes) -> None:
        """active 일 때만 robot 으로 leader 프레임 전달 (디코드 없이 bytes 그대로)."""
        if not self._active:
            return
        ws = self._robot
        if ws is None:
            return
        try:
            await ws.send_bytes(data)
        except Exception:
            # robot 끊김 — unregister 는 robot 핸들러 finally 에서.
            pass


def build_router(hub: TeleopRelayHub) -> APIRouter:
    r = APIRouter()

    @r.websocket("/ws/eduping/teleop")
    async def ws_handler(  # noqa: ANN202
        ws: WebSocket,
        role: str | None = Query(default=None),
    ) -> None:
        if role not in ("robot", "leader_src"):
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await ws.accept()
        try:
            if role == "robot":
                await hub.register_robot(ws)
                while True:
                    msg = await ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    raw = msg.get("bytes")
                    if raw:
                        hub._on_follower_bytes(raw)
            else:  # leader_src
                while True:
                    msg = await ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    raw = msg.get("bytes")
                    if raw:
                        await hub.forward_leader(raw)
        except WebSocketDisconnect:
            pass
        finally:
            if role == "robot":
                await hub.unregister_robot(ws)

    return r
