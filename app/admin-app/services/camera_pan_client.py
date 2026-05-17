"""Camera pan/tilt client — HTTP/WS only. rclpy import 금지.

admin-app (Qt) 가 Control Server 의 /camera_pan/* 와 통신.
teleop_client.py 와 같은 패턴.
"""

from __future__ import annotations

import json
import threading
from typing import Callable

import httpx


class CameraPanClient:
    """Control Server camera_pan endpoint 클라이언트.

    - post_cmd: REST POST /camera_pan/cmd  ({pan?: float, tilt?: float})
    - get_health: REST GET /camera_pan/health
    - connect_state_ws: WS /camera_pan/state — daemon thread, on_msg(dict)
    """

    def __init__(self, base_url: str = "http://localhost:8000") -> None:
        self._base = base_url.rstrip("/")
        self._http = httpx.Client(timeout=1.0)
        self._ws_thread: threading.Thread | None = None
        self._ws_stop = threading.Event()

    def post_cmd(self, pan: float | None = None, tilt: float | None = None) -> bool:
        body: dict = {}
        if pan is not None:
            body["pan"] = float(pan)
        if tilt is not None:
            body["tilt"] = float(tilt)
        if not body:
            return False
        try:
            r = self._http.post(f"{self._base}/camera_pan/cmd", json=body)
        except httpx.HTTPError:
            return False
        return r.status_code == 200

    def get_health(self) -> dict | None:
        try:
            r = self._http.get(f"{self._base}/camera_pan/health")
        except httpx.HTTPError:
            return None
        if r.status_code != 200:
            return None
        return r.json()

    def connect_state_ws(self, on_msg: Callable[[dict], None]) -> None:
        if self._ws_thread is not None:
            return
        self._ws_stop.clear()

        def _run() -> None:
            url = self._base.replace("http", "ws", 1) + "/camera_pan/state"
            while not self._ws_stop.is_set():
                try:
                    from websockets.sync.client import connect
                    with connect(url, open_timeout=2.0) as ws:
                        while not self._ws_stop.is_set():
                            raw = ws.recv(timeout=1.0)
                            try:
                                on_msg(json.loads(raw))
                            except (ValueError, TypeError):
                                continue
                except Exception:
                    self._ws_stop.wait(1.0)

        self._ws_thread = threading.Thread(target=_run, daemon=True)
        self._ws_thread.start()

    def stop(self) -> None:
        self._ws_stop.set()
        try:
            self._http.close()
        except Exception:
            pass
