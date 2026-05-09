"""WebSocket /ws/video-stream 핸들러.

PLAN §5.3 (WS 메시지 형식), §5.4 (인증), §3.1~§3.5 (시나리오), §6 (스레드 모델).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from server.control.streaming import config as scfg
from server.control.streaming.auth import authenticate_ws_session
from server.control.streaming.client_registry import ClientRegistry, WSClient
from server.control.streaming.frame_hub import FrameHub
from server.control.streaming.protocol import (
    HelloMsg, PongMsg, SubscribeMsg, UnsubscribeMsg,
    encode_ws_frame,
)


_log = logging.getLogger("streaming.ws")

HELLO_TIMEOUT_S = 5.0

# WebSocket close codes (1xxx은 표준, 4xxx은 application 정의)
WS_CLOSE_UNAUTH = 4401
WS_CLOSE_BAD_REQUEST = 4400
WS_CLOSE_TIMEOUT = 4408


def _ts() -> int:
    return int(time.time() * 1000)


def make_ws_router(registry: ClientRegistry, hub: FrameHub) -> APIRouter:
    router = APIRouter(tags=["streaming-ws"])

    @router.websocket("/ws/video-stream")
    async def stream_ws(ws: WebSocket) -> None:
        # 1. 쿠키 인증 (PLAN §5.4)
        user_id = await authenticate_ws_session(ws)
        if user_id is None:
            await ws.close(code=WS_CLOSE_UNAUTH)
            return

        await ws.accept()
        await ws.send_json({
            "type": "welcome",
            "session_id": user_id,
            "ts_ms": _ts(),
        })

        # 2. hello 대기 (5초 timeout)
        try:
            raw = await asyncio.wait_for(
                ws.receive_text(), timeout=HELLO_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            await _safe_close(ws, WS_CLOSE_TIMEOUT, "hello timeout")
            return
        except WebSocketDisconnect:
            return

        try:
            payload = json.loads(raw)
            hello = HelloMsg(**payload)
        except (json.JSONDecodeError, ValidationError, TypeError):
            await ws.send_json({
                "type": "error", "code": "invalid_message",
                "detail": "expected hello", "ts_ms": _ts(),
            })
            await _safe_close(ws, WS_CLOSE_BAD_REQUEST)
            return

        # 3. 클라이언트 등록 + ack
        send_queue: asyncio.Queue = asyncio.Queue(
            maxsize=scfg.settings.client_send_queue_size,
        )
        client = WSClient(
            client_id=hello.client_id,
            client_kind=hello.client_kind,
            ws=ws,
            send_queue=send_queue,
            user_id=user_id,
        )
        # 같은 client_id 가 이미 있으면 기존 연결 종료 (재연결 시 깔끔)
        existing = registry.get(client.client_id)
        if existing is not None:
            hub.unsubscribe_all(existing)
            registry.remove(client.client_id)
            try:
                await existing.ws.close(code=4409, reason="reconnect")
            except Exception:
                pass

        registry.add(client)
        await ws.send_json({
            "type": "hello_ack",
            "client_id": client.client_id,
            "active_robots": list(scfg.ROBOT_IDS),
            "ts_ms": _ts(),
        })
        _log.info(
            "client connected: %s (kind=%s, user=%s)",
            client.client_id, client.client_kind, user_id,
        )

        # 4. recv / send / heartbeat 동시 실행
        recv_task = asyncio.create_task(_recv_loop(ws, client, hub))
        send_task = asyncio.create_task(_send_loop(ws, client))
        hb_task = asyncio.create_task(_heartbeat_loop(ws, client))

        try:
            done, pending = await asyncio.wait(
                {recv_task, send_task, hb_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            for t in pending:
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
        finally:
            # 5. cleanup — 모든 구독 해제 (Pi 신호 송신 X — default ON)
            hub.unsubscribe_all(client)
            registry.remove(client.client_id)
            _log.info("client disconnected: %s", client.client_id)


    return router


async def _safe_close(ws: WebSocket, code: int, reason: str = "") -> None:
    try:
        await ws.close(code=code, reason=reason)
    except Exception:
        pass


async def _recv_loop(
    ws: WebSocket, client: WSClient, hub: FrameHub,
) -> None:
    """클라이언트 → 서버 메시지 처리."""
    try:
        while True:
            raw = await ws.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue

            mtype = payload.get("type")
            if mtype == "subscribe":
                await _handle_subscribe(ws, client, hub, payload)
            elif mtype == "unsubscribe":
                await _handle_unsubscribe(ws, client, hub, payload)
            elif mtype == "pong":
                try:
                    PongMsg(**payload)
                except ValidationError:
                    pass
                client.last_pong_at = time.monotonic()
            else:
                await ws.send_json({
                    "type": "error", "code": "invalid_message",
                    "detail": f"unknown type: {mtype}", "ts_ms": _ts(),
                })
    except WebSocketDisconnect:
        return
    except Exception as exc:
        _log.warning("recv_loop %s: %s", client.client_id, exc)
        return


async def _handle_subscribe(
    ws: WebSocket, client: WSClient, hub: FrameHub, payload: dict,
) -> None:
    try:
        msg = SubscribeMsg(**payload)
    except ValidationError as exc:
        await ws.send_json({
            "type": "error", "code": "invalid_message",
            "detail": str(exc), "ts_ms": _ts(),
        })
        return

    robot_id = scfg.ROBOT_IDS[msg.robot]
    hub.subscribe(client, robot_id, msg.stream)
    await ws.send_json({
        "type": "subscribed",
        "robot": msg.robot,
        "stream": msg.stream,
        "ts_ms": _ts(),
    })


async def _handle_unsubscribe(
    ws: WebSocket, client: WSClient, hub: FrameHub, payload: dict,
) -> None:
    try:
        msg = UnsubscribeMsg(**payload)
    except ValidationError as exc:
        await ws.send_json({
            "type": "error", "code": "invalid_message",
            "detail": str(exc), "ts_ms": _ts(),
        })
        return

    robot_id = scfg.ROBOT_IDS[msg.robot]
    hub.unsubscribe(client, robot_id, msg.stream)
    await ws.send_json({
        "type": "unsubscribed",
        "robot": msg.robot,
        "stream": msg.stream,
        "ts_ms": _ts(),
    })


async def _send_loop(ws: WebSocket, client: WSClient) -> None:
    """client.send_queue → ws.send_bytes."""
    try:
        while True:
            packet = await client.send_queue.get()
            await ws.send_bytes(encode_ws_frame(packet))
    except WebSocketDisconnect:
        return
    except Exception as exc:
        _log.warning("send_loop %s: %s", client.client_id, exc)
        return


async def _heartbeat_loop(ws: WebSocket, client: WSClient) -> None:
    """30초 ping. 60초 무응답 → close (PLAN §5.3)."""
    try:
        while True:
            await asyncio.sleep(scfg.settings.heartbeat_interval_s)
            try:
                await ws.send_json({"type": "ping", "ts_ms": _ts()})
            except Exception:
                return
            idle = time.monotonic() - client.last_pong_at
            if idle > scfg.settings.heartbeat_timeout_s:
                _log.info(
                    "client %s heartbeat timeout (idle=%.1fs)",
                    client.client_id, idle,
                )
                await _safe_close(ws, WS_CLOSE_TIMEOUT, "heartbeat timeout")
                return
    except asyncio.CancelledError:
        raise
    except Exception:
        return
