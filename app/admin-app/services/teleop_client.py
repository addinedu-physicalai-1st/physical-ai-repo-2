"""Teleop client — HTTP/WS only. rclpy import 금지.

admin-app (Qt) 가 Control Server 의 teleop endpoint 와 통신하기 위한 얇은 클라이언트.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Callable

import httpx


class TeleopClient:
    """Control Server teleop endpoint 클라이언트.

    - post_cmd_vel: REST POST /teleop/cmd_vel
    - get_health:   REST GET /teleop/health
    - connect_state_ws: WS /teleop/state — 별도 thread 에서 수신, on_msg(dict) 콜백.
    """

    def __init__(self, base_url: str = "http://localhost:8000") -> None:
        self._base = base_url.rstrip("/")
        self._http = httpx.Client(timeout=1.0)
        self._ws_thread: threading.Thread | None = None
        self._ws_stop = threading.Event()

    # ------------------------------------------------------------------ REST

    def post_cmd_vel(self, linear: float, angular: float) -> bool:
        """cmd_vel 한 번 발행. 성공시 True, 실패(네트워크/5xx) 시 False."""
        ts_ms = int(time.time() * 1000)
        try:
            r = self._http.post(
                f"{self._base}/teleop/cmd_vel",
                json={"linear": float(linear),
                      "angular": float(angular),
                      "ts_ms": ts_ms},
            )
        except httpx.HTTPError:
            return False
        return r.status_code == 200

    def get_health(self) -> dict | None:
        try:
            r = self._http.get(f"{self._base}/teleop/health")
        except httpx.HTTPError:
            return None
        if r.status_code != 200:
            return None
        return r.json()

    # -------------------------------------------------------------------- WS

    def connect_state_ws(self, on_msg: Callable[[dict], None]) -> None:
        """WS /teleop/state 연결. 별도 daemon thread 에서 메시지를 수신해 on_msg 호출.

        끊기면 1 초 후 자동 재연결을 무한히 시도한다 (stop() 으로 중단).
        websockets 패키지가 없거나 연결 실패해도 예외를 던지지 않고 조용히 재시도.
        """
        if self._ws_thread is not None:
            return
        self._ws_stop.clear()

        def _run() -> None:
            url = self._base.replace("http", "ws", 1) + "/teleop/state"
            while not self._ws_stop.is_set():
                try:
                    # websockets 의 sync API 사용 (1.0+)
                    from websockets.sync.client import connect
                    with connect(url, open_timeout=2.0) as ws:
                        while not self._ws_stop.is_set():
                            raw = ws.recv(timeout=1.0)
                            try:
                                on_msg(json.loads(raw))
                            except (ValueError, TypeError):
                                continue
                except Exception:
                    # 재연결 대기
                    self._ws_stop.wait(1.0)

        self._ws_thread = threading.Thread(target=_run, daemon=True)
        self._ws_thread.start()

    def stop(self) -> None:
        self._ws_stop.set()
        try:
            self._http.close()
        except Exception:
            pass
