"""WebSocket /ws/depth-stream/{producer|consumer} 핸들러.

Producer (laptop streamer):
  POST connect → 매 frame binary push → server 가 DepthHub 에 publish.
  인증: STREAMING_REQUIRE_AUTH 와 동일 (dev=anonymous).
  Path param `{robot}` 으로 어느 로봇용 frame 인지 식별.

Consumer (robot-web viewer):
  Video WS 와 동일 패턴 — welcome / hello / subscribe / pong.
  binary frame = encode_depth_frame(DepthFrame).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from control_service.streaming import config as scfg
from control_service.streaming.auth import authenticate_ws_session
from control_service.streaming.client_registry import ClientRegistry, WSClient
from control_service.streaming.depth_hub import DepthHub
from control_service.streaming.depth_protocol import (
    decode_depth_frame, encode_depth_frame,
)
from control_service.streaming.protocol import HelloMsg, PongMsg, SubscribeMsg


_log = logging.getLogger("streaming.depth_ws")

HELLO_TIMEOUT_S = 5.0

WS_CLOSE_UNAUTH = 4401
WS_CLOSE_BAD_REQUEST = 4400
WS_CLOSE_TIMEOUT = 4408


def _ts() -> int:
    return int(time.time() * 1000)


def make_depth_ws_router(registry: ClientRegistry, hub: DepthHub) -> APIRouter:
    router = APIRouter(tags=["streaming-depth-ws"])

    @router.websocket("/ws/depth-stream/producer/{robot}")
    async def depth_producer(ws: WebSocket, robot: str) -> None:
        user_id = await authenticate_ws_session(ws)
        if user_id is None:
            await ws.close(code=WS_CLOSE_UNAUTH)
            return
        if robot not in scfg.ROBOT_IDS:
            await ws.close(code=WS_CLOSE_BAD_REQUEST, reason="unknown robot")
            return
        robot_id = scfg.ROBOT_IDS[robot]
        await ws.accept()
        _log.info("depth producer connected: robot=%s id=0x%02x user=%s",
                  robot, robot_id, user_id)
        frames_received = 0
        frames_dropped = 0
        try:
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                data = msg.get("bytes")
                if data is None:
                    # text 메시지 무시 (ping 같은 keepalive 가 올 수 있음)
                    continue
                frame = decode_depth_frame(data)
                if frame is None or frame.robot_id != robot_id:
                    frames_dropped += 1
                    continue
                hub.publish(frame)
                frames_received += 1
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            _log.warning("depth producer %s error: %s", robot, exc)
        finally:
            _log.info(
                "depth producer disconnected: robot=%s received=%d dropped=%d",
                robot, frames_received, frames_dropped,
            )

    @router.websocket("/ws/depth-stream")
    async def depth_consumer(ws: WebSocket) -> None:
        user_id = await authenticate_ws_session(ws)
        if user_id is None:
            await ws.close(code=WS_CLOSE_UNAUTH)
            return

        await ws.accept()
        await ws.send_json({
            "type": "welcome", "session_id": user_id, "ts_ms": _ts(),
        })

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
        _log.info("depth consumer connected: %s (kind=%s)",
                  client.client_id, client.client_kind)

        recv_task = asyncio.create_task(_recv_loop(ws, client, hub))
        send_task = asyncio.create_task(_send_loop(ws, client))
        hb_task = asyncio.create_task(_heartbeat_loop(ws, client))

        try:
            _done, pending = await asyncio.wait(
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
            hub.unsubscribe_all(client)
            registry.remove(client.client_id)
            _log.info("depth consumer disconnected: %s", client.client_id)

    return router


async def _safe_close(ws: WebSocket, code: int, reason: str = "") -> None:
    try:
        await ws.close(code=code, reason=reason)
    except Exception:
        pass


async def _recv_loop(ws: WebSocket, client: WSClient, hub: DepthHub) -> None:
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
        _log.warning("depth recv_loop %s: %s", client.client_id, exc)
        return


async def _handle_subscribe(
    ws: WebSocket, client: WSClient, hub: DepthHub, payload: dict,
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
    hub.subscribe(client, robot_id)
    await ws.send_json({
        "type": "subscribed", "robot": msg.robot, "stream": -1, "ts_ms": _ts(),
    })


async def _handle_unsubscribe(
    ws: WebSocket, client: WSClient, hub: DepthHub, payload: dict,
) -> None:
    try:
        msg = SubscribeMsg(**payload)   # unsubscribe 도 같은 schema
    except ValidationError as exc:
        await ws.send_json({
            "type": "error", "code": "invalid_message",
            "detail": str(exc), "ts_ms": _ts(),
        })
        return
    robot_id = scfg.ROBOT_IDS[msg.robot]
    hub.unsubscribe(client, robot_id)
    await ws.send_json({
        "type": "unsubscribed", "robot": msg.robot, "stream": -1, "ts_ms": _ts(),
    })


async def _send_loop(ws: WebSocket, client: WSClient) -> None:
    try:
        while True:
            frame = await client.send_queue.get()
            await ws.send_bytes(encode_depth_frame(frame))
    except WebSocketDisconnect:
        return
    except Exception as exc:
        _log.warning("depth send_loop %s: %s", client.client_id, exc)
        return


async def _heartbeat_loop(ws: WebSocket, client: WSClient) -> None:
    try:
        while True:
            await asyncio.sleep(scfg.settings.heartbeat_interval_s)
            try:
                await ws.send_json({"type": "ping", "ts_ms": _ts()})
            except Exception:
                return
            idle = time.monotonic() - client.last_pong_at
            if idle > scfg.settings.heartbeat_timeout_s:
                await _safe_close(ws, WS_CLOSE_TIMEOUT, "heartbeat timeout")
                return
    except asyncio.CancelledError:
        raise
    except Exception:
        return
