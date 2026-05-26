"""FastAPI WebSocket router — /ws/webrtc/signaling.

프로토콜: gogoping_camera/signaling_client.py 의 docstring 참조.

server 는 두 종류의 WS 연결을 받음:
  - role=producer  (gogoping 노트북, 1개)
  - role=consumer  (admin UI / robot-web, N 개)

producer 가 RTCPeerConnection 의 server-side endpoint 를 만들고, server 가 그 PC 에 SDP/ICE 를 forwarding.
"""
from __future__ import annotations

import json
import logging
from typing import Dict

from aiortc import RTCIceCandidate, RTCSessionDescription
from aiortc.exceptions import InvalidStateError
from aiortc.sdp import candidate_from_sdp
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .webrtc_relay import WebRTCRelay

_log = logging.getLogger("streaming.webrtc_router")

router = APIRouter()
_relay = WebRTCRelay()
_consumers: Dict[str, WebSocket] = {}
_producer_ws: WebSocket | None = None


@router.websocket("/ws/webrtc/signaling")
async def signaling_ws(ws: WebSocket) -> None:
    global _producer_ws
    await ws.accept()
    role = None
    peer_id = None
    pc = None
    try:
        # 첫 메시지 — hello
        hello_raw = await ws.receive_text()
        hello = json.loads(hello_raw)
        if hello.get("type") != "hello":
            await ws.close(code=4001)
            return
        role = hello.get("role")
        peer_id = hello.get("peer_id") or "anon"

        # client-as-offerer 패턴: server 는 hello 받고 PC 만 만들어두고 대기.
        # client 가 offer 보내면 setRemoteDescription → createAnswer → send.
        if role == "producer":
            _producer_ws = ws
            pc = await _relay.attach_producer()
        elif role == "consumer":
            # producer 가 아직 안 붙은 상태에서 consumer 가 들어오면 미디어 없는 빈
            # m=video answer 가 나가 브라우저 PC 가 곧 'failed' → ws close → reconnect 폭주.
            # 4503 (Service Unavailable) 로 명시 거부해 클라이언트가 backoff 갖게.
            if not _relay.has_producer():
                await ws.close(code=4503)
                return
            # 같은 peer_id 의 OLD ws 가 있으면 명시적으로 close — Chrome 다중 탭이나
            # HMR 로 stale consumer 가 누적돼 NVENC 부담 N배 + RTP fan-out 부담 N배가
            # 영상 freeze 의 원인. 마지막 connect 만 active 로 강제.
            old_ws = _consumers.get(peer_id)
            if old_ws is not None and old_ws is not ws:
                try:
                    await old_ws.close(code=4004)  # 4004: Replaced by newer connection
                except Exception:
                    pass
            _consumers[peer_id] = ws
            pc = await _relay.attach_consumer(peer_id)
        else:
            await ws.close(code=4002)
            return

        async for raw in ws.iter_text():
            msg = json.loads(raw)
            mtype = msg.get("type")
            try:
                if mtype == "offer":
                    # client 의 offer 수신 → server-side answer 생성 후 송신.
                    await pc.setRemoteDescription(RTCSessionDescription(sdp=msg["sdp"], type="offer"))
                    # consumer 면 producer_track 을 setRemoteDescription 후 addTrack 으로
                    # m=video section 의 server-side sender 에 연결. 순서 중요 — 미리
                    # addTrack 하면 SDP m-section 매칭 안 됨.
                    if role == "consumer":
                        _relay.attach_track_to_consumer(pc)
                    answer = await pc.createAnswer()
                    await pc.setLocalDescription(answer)
                    await ws.send_text(json.dumps({"type": "answer", "sdp": pc.localDescription.sdp}))
                elif mtype == "ice":
                    cand_json = msg.get("candidate")
                    if cand_json is None:
                        continue
                    cand = _cand_from_json(cand_json)
                    if cand is None:
                        continue   # end-of-candidates 시그널 또는 빈 candidate
                    await pc.addIceCandidate(cand)
                elif mtype == "bye":
                    break
                else:
                    _log.warning("unknown message type: %s", mtype)
            except InvalidStateError as e:
                # 다른 ws 가 같은 peer_id 로 들어오며 _close_consumer_locked 가 PC 를
                # 먼저 close → 이 ws 의 offer/ice 처리 race. ASGI 로 throw 안 하고 close.
                _log.info("PC race (role=%s peer_id=%s): %s — closing this ws", role, peer_id, e)
                break
    except WebSocketDisconnect:
        pass
    finally:
        if role == "producer":
            await _relay.detach_producer()
            if _producer_ws is ws:
                _producer_ws = None
        elif role == "consumer" and peer_id is not None:
            await _relay.detach_consumer(peer_id)
            _consumers.pop(peer_id, None)


def _cand_to_json(cand) -> dict:
    return {
        "candidate": cand.candidate,
        "sdpMid": cand.sdpMid,
        "sdpMLineIndex": cand.sdpMLineIndex,
    }


def _cand_from_json(c: dict) -> RTCIceCandidate | None:
    """브라우저가 보낸 SDP candidate 문자열 → RTCIceCandidate.

    aiortc 의 RTCIceCandidate 는 candidate SDP 문자열을 그대로 받지 않고
    parsing 된 필드들을 받음. `candidate_from_sdp` 헬퍼가 그 parsing 수행.
    빈 candidate (end-of-candidates 시그널) 는 None 반환.
    """
    candidate_str = (c.get("candidate") or "").strip()
    if not candidate_str:
        return None
    # SDP 의 candidate line 은 "candidate:foundation ..." prefix 가 붙어있을 수도 있음.
    if candidate_str.startswith("candidate:"):
        candidate_str = candidate_str[len("candidate:"):]
    cand = candidate_from_sdp(candidate_str)
    cand.sdpMid = c.get("sdpMid")
    cand.sdpMLineIndex = c.get("sdpMLineIndex")
    return cand
