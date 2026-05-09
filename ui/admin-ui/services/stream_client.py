"""Streaming WebSocket 클라이언트 (PyQt5).

PLAN §5.3 (메시지 형식), §8 단계 6 (Admin UI 위젯), SR-CAM-004.

기존 [services/teleop_client.py](teleop_client.py) 와 같은 패턴:
- `websockets.sync.client.connect` (sync API) 를 daemon thread 안에서 사용
- 끊기면 1초 후 자동 재연결, 재연결 후 활성 구독 자동 복원
- pyqtSignal 로 GUI 스레드에 frame/상태 전달
"""

from __future__ import annotations

import json
import logging
import queue
import struct
import threading
import time
from dataclasses import dataclass
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal


_log = logging.getLogger("admin.stream_client")


# WS binary frame 헤더 (PLAN §5.3, 20B)
WS_FRAME_HEADER_FMT = "!BBBBIQI"
WS_FRAME_HEADER_SIZE = 20
WS_MSG_VIDEO_FRAME = 0x10

# robot 이름 ↔ id (PLAN §5.1)
ROBOT_IDS = {"gogoping": 0x01, "eduping": 0x02, "noriarm": 0x03}
ID_TO_NAME = {v: k for k, v in ROBOT_IDS.items()}


@dataclass(frozen=True)
class _Cmd:
    """worker thread 에 보낼 명령 (subscribe/unsubscribe/disconnect)."""
    kind: str   # "subscribe" / "unsubscribe" / "stop"
    robot: str = ""
    stream: int = 0


class StreamClient(QObject):
    """Streaming WS 클라이언트.

    사용:
        client = StreamClient(client_id, base_url="ws://localhost:9100")
        client.frame_received.connect(on_frame)        # (robot_id, stream_id, jpeg)
        client.connection_state_changed.connect(on_state)  # bool
        client.start()
        client.subscribe("gogoping", 0)
        ...
        client.stop()
    """

    # robot_id, stream_id, jpeg bytes
    frame_received = pyqtSignal(int, int, bytes)
    # 연결됨 (True) / 끊김 (False)
    connection_state_changed = pyqtSignal(bool)
    # 에러 메시지 (string)
    error = pyqtSignal(str)

    def __init__(
        self,
        client_id: str,
        base_url: str = "ws://localhost:8100",
        client_kind: str = "admin",
        cookies: Optional[dict] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._client_id = client_id
        self._client_kind = client_kind
        self._base_url = base_url.rstrip("/")
        self._cookies = cookies or {}
        self._cmd_queue: queue.Queue[_Cmd] = queue.Queue()
        self._active_subs: set[tuple[str, int]] = set()    # 활성 구독 (재연결 시 복원)
        self._active_subs_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._connected = False

    # ------------------------------------------------------------ public API

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="stream-client", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self._cmd_queue.put_nowait(_Cmd(kind="stop"))
        except queue.Full:
            pass

    def subscribe(self, robot: str, stream: int = 0) -> None:
        if robot not in ROBOT_IDS:
            return
        with self._active_subs_lock:
            self._active_subs.add((robot, stream))
        self._cmd_queue.put(_Cmd(kind="subscribe", robot=robot, stream=stream))

    def unsubscribe(self, robot: str, stream: int = 0) -> None:
        if robot not in ROBOT_IDS:
            return
        with self._active_subs_lock:
            self._active_subs.discard((robot, stream))
        self._cmd_queue.put(_Cmd(kind="unsubscribe", robot=robot, stream=stream))

    @property
    def client_id(self) -> str:
        return self._client_id

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------ worker thread

    def _ws_url(self) -> str:
        return f"{self._base_url}/ws/video-stream"

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _set_connected(self, value: bool) -> None:
        if value != self._connected:
            self._connected = value
            self.connection_state_changed.emit(value)

    def _run(self) -> None:
        """daemon thread main loop — 끊기면 1초 후 재연결."""
        try:
            from websockets.sync.client import connect
            from websockets.exceptions import ConnectionClosed
        except ImportError as exc:
            self.error.emit(f"websockets 모듈 없음: {exc}")
            return

        url = self._ws_url()
        # cookie 헤더 구성 (선택)
        extra_headers = []
        if self._cookies:
            cookie_str = "; ".join(f"{k}={v}" for k, v in self._cookies.items())
            extra_headers = [("Cookie", cookie_str)]

        while not self._stop_event.is_set():
            try:
                _log.info("connecting %s", url)
                ws = connect(
                    url,
                    open_timeout=3.0,
                    close_timeout=2.0,
                    additional_headers=extra_headers or None,
                    max_size=2_000_000,   # frame 50KB << 2MB
                )
            except Exception as exc:
                self._set_connected(False)
                _log.warning("connect 실패: %s", exc)
                self._stop_event.wait(1.0)
                continue

            try:
                self._handle_session(ws)
            except Exception as exc:
                _log.warning("session 종료: %s", exc)
            finally:
                self._set_connected(False)
                try:
                    ws.close()
                except Exception:
                    pass

            if not self._stop_event.is_set():
                self._stop_event.wait(1.0)   # 재연결 대기

        _log.info("stream client thread exit")

    def _handle_session(self, ws) -> None:
        """단일 WS 세션 처리: welcome → hello → recv loop."""
        from websockets.exceptions import ConnectionClosed

        # 1. welcome 대기
        ws.settimeout(5.0) if hasattr(ws, "settimeout") else None
        try:
            raw = ws.recv(timeout=5.0)
        except (TimeoutError, ConnectionClosed):
            return
        try:
            msg = json.loads(raw) if isinstance(raw, str) else None
        except (json.JSONDecodeError, TypeError):
            msg = None
        if not isinstance(msg, dict) or msg.get("type") != "welcome":
            _log.warning("welcome 안 옴: %r", raw)
            return

        # 2. hello 송신
        hello = {
            "type": "hello",
            "client_id": self._client_id,
            "client_kind": self._client_kind,
            "ts_ms": self._now_ms(),
        }
        ws.send(json.dumps(hello))

        # 3. hello_ack 대기
        try:
            raw = ws.recv(timeout=5.0)
        except (TimeoutError, ConnectionClosed):
            return
        try:
            msg = json.loads(raw) if isinstance(raw, str) else None
        except (json.JSONDecodeError, TypeError):
            msg = None
        if not isinstance(msg, dict) or msg.get("type") != "hello_ack":
            _log.warning("hello_ack 안 옴: %r", raw)
            return

        self._set_connected(True)
        _log.info("connected — restoring %d subscriptions",
                  len(self._active_subs))

        # 4. 활성 구독 복원
        with self._active_subs_lock:
            for robot, stream in list(self._active_subs):
                self._cmd_queue.put(_Cmd(kind="subscribe", robot=robot, stream=stream))

        # 5. send/recv 분리 — recv loop 에서 양쪽 모두 처리
        ws.settimeout(0.05) if hasattr(ws, "settimeout") else None
        while not self._stop_event.is_set():
            # 명령 큐 처리
            try:
                while True:
                    cmd = self._cmd_queue.get_nowait()
                    self._handle_cmd(ws, cmd)
                    if cmd.kind == "stop":
                        return
            except queue.Empty:
                pass

            # recv (non-blocking 수준의 짧은 timeout)
            try:
                raw = ws.recv(timeout=0.05)
            except TimeoutError:
                continue
            except ConnectionClosed:
                return

            if isinstance(raw, bytes):
                self._handle_binary(raw)
            elif isinstance(raw, str):
                self._handle_text(ws, raw)

    def _handle_cmd(self, ws, cmd: _Cmd) -> None:
        if cmd.kind == "stop":
            try:
                ws.close()
            except Exception:
                pass
            return
        if cmd.kind in ("subscribe", "unsubscribe"):
            payload = {
                "type": cmd.kind,
                "robot": cmd.robot,
                "stream": cmd.stream,
                "ts_ms": self._now_ms(),
            }
            try:
                ws.send(json.dumps(payload))
            except Exception as exc:
                _log.warning("%s send 실패: %s", cmd.kind, exc)

    def _handle_text(self, ws, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        mtype = msg.get("type")
        if mtype == "ping":
            try:
                ws.send(json.dumps({"type": "pong", "ts_ms": self._now_ms()}))
            except Exception:
                pass
        elif mtype == "subscribed":
            _log.info("subscribed: %s/%s", msg.get("robot"), msg.get("stream"))
        elif mtype == "unsubscribed":
            _log.info("unsubscribed: %s/%s", msg.get("robot"), msg.get("stream"))
        elif mtype == "error":
            err = f"{msg.get('code')}: {msg.get('detail')}"
            _log.warning("server error: %s", err)
            self.error.emit(err)

    def _handle_binary(self, data: bytes) -> None:
        if len(data) < WS_FRAME_HEADER_SIZE:
            return
        try:
            mtype, robot_id, stream_id, _resv, _seq, _ts, jpeg_size = struct.unpack(
                WS_FRAME_HEADER_FMT, data[:WS_FRAME_HEADER_SIZE],
            )
        except struct.error:
            return
        if mtype != WS_MSG_VIDEO_FRAME:
            return
        end = WS_FRAME_HEADER_SIZE + jpeg_size
        if end > len(data):
            return
        jpeg = bytes(data[WS_FRAME_HEADER_SIZE:end])
        self.frame_received.emit(robot_id, stream_id, jpeg)
