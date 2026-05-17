"""Robot state WS client + 디버그 REST helper.

teleop_client.py 와 같은 패턴 — daemon thread 에서 WS 수신, 끊기면 1초 후 재연결.

사용 (admin-app main.py):
    self.state_client = StateClient()
    self.state_client.connect(self.topbar.bt_state.update_snapshot)
    # closeEvent 에서 self.state_client.stop()

REST helper:
    self.state_client.post_force_state("ERROR")
    # 디버그용 — control-server /api/gogoping/debug/force-state 호출

받은 payload 포맷: ``gogoping_modes.bt.tree_inspector.snapshot`` 의 dict 그대로 —
``app/admin-app/widgets/bt_state_inline.py`` 의 ``update_snapshot()`` 시그니처와 호환.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Callable

import httpx

logger = logging.getLogger(__name__)


class StateClient:
    """Control Server `/ws/robot-state` WS 구독자.

    별도 daemon thread 에서 메시지 수신 → ``on_snapshot(dict)`` 콜백.
    websockets 라이브러리 없거나 서버 미가동이어도 예외 던지지 않고 조용히 재시도.
    """

    PATH = "/ws/robot-state"

    def __init__(self, base_url: str = "http://localhost:8000") -> None:
        self._base = base_url.rstrip("/")
        self._ws_thread: threading.Thread | None = None
        self._ws_stop = threading.Event()

    def connect(self, on_snapshot: Callable[[dict], None]) -> None:
        """WS 연결 시작. 별도 thread 에서 메시지마다 ``on_snapshot(payload)`` 호출.

        끊기면 1초 후 자동 재연결을 무한히 시도. ``stop()`` 으로 중단.

        주의: ``on_snapshot`` 은 *daemon thread* 에서 호출됨. Qt 위젯 갱신은 thread-safe
        하지 않으므로 ``QMetaObject.invokeMethod`` 또는 Qt signal/slot 으로 main thread
        로 marshal 해야 함 (BTStateInline 의 ``update_snapshot`` 이 단순 setText 만 하므로
        대부분의 경우 안전하지만, 엄격 환경에선 signal 사용 권장).
        """
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
                        "websockets 패키지 없음 — robot-state WS 비활성. "
                        "`pip install websockets` 후 admin-app 재시작."
                    )
                    return  # 재시도 의미 없음

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
                                logger.warning(f"invalid state JSON: {e}")
                                continue
                            try:
                                on_snapshot(payload)
                            except Exception as e:
                                logger.warning(f"on_snapshot callback 오류: {e}")
                except Exception as e:
                    # 연결 실패 / 끊김 — 1초 대기 후 재시도
                    logger.debug(f"robot-state WS 끊김, 재시도: {e}")
                    self._ws_stop.wait(timeout=1.0)

        self._ws_thread = threading.Thread(
            target=_run, name="robot_state_ws", daemon=True,
        )
        self._ws_thread.start()
        logger.info(f"StateClient connected: {ws_url}")

    def stop(self) -> None:
        """WS 종료. ``connect`` 후 호출 안 하면 daemon thread 가 프로세스 종료 시 정리."""
        self._ws_stop.set()
        if self._ws_thread is not None and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=1.5)
        self._ws_thread = None

    # ----------------------------------------------------------- 디버그 REST

    def post_force_state(
        self,
        target_state: str,
        sub_task: str = "",
        on_result: Callable[[str, bool, str], None] | None = None,
    ) -> None:
        """**디버그** — ``POST /api/gogoping/debug/force-state``.

        별도 thread 에서 HTTP 호출 (Qt main thread 차단 방지). 응답 시
        ``on_result(state, ok, reason)`` 콜백 — Qt signal 또는 단순 함수.

        admin UI 의 DebugStatePanel 적용 버튼이 호출.
        ``sub_task`` 비어있지 않으면 blackboard.assist_task / play_task 같이 세팅됨.
        """
        url = f"{self._base}/api/gogoping/debug/force-state"

        def _run() -> None:
            ok = False
            reason = ""
            try:
                with httpx.Client(timeout=2.0) as client:
                    r = client.post(
                        url,
                        json={"target_state": target_state, "sub_task": sub_task},
                    )
                    if r.status_code == 200:
                        data = r.json()
                        ok = bool(data.get("accepted"))
                        reason = str(data.get("reason", ""))
                    else:
                        reason = f"http_{r.status_code}"
            except httpx.HTTPError as e:
                reason = f"http_error: {e}"
            except Exception as e:
                reason = f"unexpected: {e}"
            if on_result is not None:
                try:
                    on_result(target_state, ok, reason)
                except Exception as e:
                    logger.warning(f"force_state on_result 콜백 오류: {e}")

        threading.Thread(target=_run, name=f"force_state_{target_state}", daemon=True).start()


__all__ = ["StateClient"]
