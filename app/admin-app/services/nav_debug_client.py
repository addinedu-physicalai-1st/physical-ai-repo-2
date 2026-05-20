"""NavDebug WS client — ``/ws/nav-debug-events`` 구독.

StateClient 와 같은 패턴 — daemon thread 에서 WS recv, 끊기면 1초 후 재연결.

받는 payload 포맷:
    {"ts": 1.0, "source": "NavTo", "level": "info|warn|err", "msg": "..."}

사용 (admin-app main.py):
    self.nav_debug_client = NavDebugClient()
    self.nav_debug_client.connect(self.dashboard.nav_debug_log.append_event)
    # closeEvent 에서 self.nav_debug_client.stop()

콜백은 *daemon thread* 에서 호출됨 — NavDebugLogCard 는 Qt signal 로 main thread 로
marshal 한다.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)


class NavDebugClient:
    PATH = "/ws/nav-debug-events"

    def __init__(self, base_url: str = "http://localhost:8000") -> None:
        self._base = base_url.rstrip("/")
        self._ws_thread: threading.Thread | None = None
        self._ws_stop = threading.Event()

    def connect(self, on_event: Callable[[dict], None]) -> None:
        if self._ws_thread is not None:
            return
        self._ws_stop.clear()

        ws_url = self._base.replace("http", "ws", 1) + self.PATH

        def _run() -> None:
            while not self._ws_stop.is_set():
                try:
                    from websockets.sync.client import connect
                except ImportError:
                    logger.warning(
                        "websockets 패키지 없음 — nav-debug-events WS 비활성."
                    )
                    return

                try:
                    with connect(ws_url, open_timeout=2.0) as ws:
                        while not self._ws_stop.is_set():
                            try:
                                raw = ws.recv(timeout=1.0)
                            except TimeoutError:
                                continue
                            try:
                                payload = json.loads(raw)
                            except (ValueError, TypeError) as e:
                                logger.warning(f"invalid nav_event JSON: {e}")
                                continue
                            try:
                                on_event(payload)
                            except Exception as e:
                                logger.warning(f"on_event callback 오류: {e}")
                except Exception as e:
                    logger.debug(f"nav-debug-events WS 끊김, 재시도: {e}")
                    self._ws_stop.wait(timeout=1.0)

        self._ws_thread = threading.Thread(
            target=_run, name="nav_debug_ws", daemon=True,
        )
        self._ws_thread.start()
        logger.info(f"NavDebugClient connected: {ws_url}")

    def stop(self) -> None:
        self._ws_stop.set()
        if self._ws_thread is not None and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=1.5)
        self._ws_thread = None


__all__ = ["NavDebugClient"]
