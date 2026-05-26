"""카메라 스트림 위젯 — JPEG 표시 + 상태 오버레이.

PLAN §8 단계 6, SR-CAM-004.

대시보드 카드 내부에 배치. showEvent 에서 자동 subscribe, hideEvent 에서 unsubscribe
(패턴 A — 배타적 전환). 받은 binary frame 의 (robot_id, stream_id) 가 자기 target
과 매칭되는 것만 표시.

GogoPing 은 1080p D435 + WebRTC 로 전환되어 `WebRTCStreamView` (QWebEngineView 기반)
로 별 처리. EduPing / NoriArm 은 UDP→WS JPEG 그대로 `CameraStreamView` 사용.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import TYPE_CHECKING

from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt5.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from theme import COLORS

# QWebEngineView 는 별도 패키지 (PyQtWebEngine) — 미설치 시 placeholder fallback.
try:
    from PyQt5.QtWebEngineWidgets import (  # type: ignore[import-not-found]
        QWebEnginePage,
        QWebEngineSettings,
        QWebEngineView,
    )

    _HAS_WEBENGINE = True

    class _LocalhostPermissivePage(QWebEnginePage):
        """Vite mkcert self-signed cert 를 localhost 한정으로 통과.

        OpenSSL 1.x ↔ 3.x 호환성 이슈로 https 자체가 못 뚫리는 환경에서도 일단
        cert 거부는 통과시킴 (page navigate 가 가능한 만큼). 실 동작에선 admin URL
        을 control-service 의 HTTP mirror (/admin-embed/) 로 두어 https 자체를 회피.
        """

        def certificateError(self, error):  # type: ignore[override]
            try:
                host = error.url().host()
            except Exception:
                host = ""
            return host in ("localhost", "127.0.0.1", "")

except ImportError:
    QWebEngineView = None  # type: ignore[assignment, misc]
    QWebEnginePage = None  # type: ignore[assignment, misc]
    QWebEngineSettings = None  # type: ignore[assignment, misc]
    _LocalhostPermissivePage = None  # type: ignore[assignment, misc]
    _HAS_WEBENGINE = False


if TYPE_CHECKING:
    from services.stream_client import StreamClient


# 표시 상태
_STATE_DISCONNECTED = 0   # WS 끊김
_STATE_WAITING = 1        # 연결됨, 첫 frame 미수신
_STATE_LIVE = 2           # frame 수신 중
_STATE_STALL = 3          # 5초 이상 frame 미수신 (subscriber 0 또는 Pi 정지)


class CameraStreamView(QWidget):
    """단일 (robot, stream) 영상 표시.

    - showEvent: stream_client.subscribe(robot, stream)
    - hideEvent: stream_client.unsubscribe(robot, stream)
    - frame_received signal 에서 자기 (robot, stream) 만 필터링
    - 5초 frame 없으면 STALL 상태로 표시 (운영자에게 시각적 피드백)
    """

    STALL_THRESHOLD_S = 5.0

    def __init__(
        self,
        robot: str,
        stream_client: "StreamClient",
        stream_id: int = 0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._robot = robot
        self._stream_id = stream_id
        self._client = stream_client
        self._pixmap: QPixmap | None = None
        self._last_frame_at: datetime | None = None
        self._frame_count = 0
        self._state = _STATE_DISCONNECTED
        self._target = (self._robot_id(), stream_id)

        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # signal 연결
        self._client.frame_received.connect(self._on_frame)
        self._client.connection_state_changed.connect(self._on_conn_state)

        # 1초 주기 stall/타임스탬프 갱신
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start(1000)

    def _robot_id(self) -> int:
        from services.stream_client import ROBOT_IDS
        return ROBOT_IDS.get(self._robot, 0)

    # ---------------------------------------------------------- lifecycle

    def showEvent(self, ev) -> None:   # noqa: N802
        super().showEvent(ev)
        self._client.subscribe(self._robot, self._stream_id)

    def hideEvent(self, ev) -> None:   # noqa: N802
        super().hideEvent(ev)
        self._client.unsubscribe(self._robot, self._stream_id)
        # 가려지면 마지막 프레임은 유지하지만 LIVE 표시는 끔
        if self._state == _STATE_LIVE:
            self._state = _STATE_WAITING

    # ---------------------------------------------------------- slots

    def _on_frame(self, robot_id: int, stream_id: int, jpeg: bytes) -> None:
        if (robot_id, stream_id) != self._target:
            return   # 다른 영상 frame — 무시
        img = QImage.fromData(jpeg, "JPG")
        if img.isNull():
            return
        self._pixmap = QPixmap.fromImage(img)
        self._last_frame_at = datetime.now()
        self._frame_count += 1
        self._state = _STATE_LIVE
        self.update()

    def _on_conn_state(self, connected: bool) -> None:
        if not connected:
            self._state = _STATE_DISCONNECTED
        elif self._pixmap is None:
            self._state = _STATE_WAITING
        self.update()

    def _on_tick(self) -> None:
        # stall 검출
        if (
            self._state == _STATE_LIVE
            and self._last_frame_at is not None
            and (datetime.now() - self._last_frame_at).total_seconds()
                > self.STALL_THRESHOLD_S
        ):
            self._state = _STATE_STALL
        self.update()   # 타임스탬프 라이브 갱신

    # ---------------------------------------------------------- paint

    def paintEvent(self, _ev) -> None:   # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()

        # 둥근 모서리 클립
        clip = QPainterPath()
        clip.addRoundedRect(float(rect.x()), float(rect.y()),
                            float(rect.width()), float(rect.height()), 14, 14)
        p.setClipPath(clip)

        # 배경
        bg = QLinearGradient(0, 0, 0, rect.height())
        bg.setColorAt(0, QColor("#1f2330"))
        bg.setColorAt(1, QColor("#11141d"))
        p.fillRect(rect, QBrush(bg))

        # frame 표시 — 위젯을 가득 채우도록 확대 (검정 letterbox 제거).
        # 영상 종횡비와 위젯 종횡비가 다르면 상/하 또는 좌/우 일부가 잘리지만,
        # 둥근 모서리 클립 안에서 자연스럽게 처리된다.
        if self._pixmap is not None and self._state in (_STATE_LIVE, _STATE_WAITING, _STATE_STALL):
            scaled = self._pixmap.scaled(
                rect.size(),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            offset_x = (rect.width() - scaled.width()) // 2
            offset_y = (rect.height() - scaled.height()) // 2
            p.drawPixmap(offset_x, offset_y, scaled)

            # STALL 시 살짝 어둡게
            if self._state == _STATE_STALL:
                p.fillRect(rect, QColor(0, 0, 0, 120))
        else:
            self._draw_placeholder(p, rect)

        # 비네트
        vg = QRadialGradient(
            float(rect.center().x()), float(rect.center().y()),
            max(rect.width(), rect.height()) * 0.7,
        )
        vg.setColorAt(0.6, QColor(0, 0, 0, 0))
        vg.setColorAt(1.0, QColor(0, 0, 0, 70))
        p.setBrush(QBrush(vg))
        p.setPen(Qt.NoPen)
        p.drawRect(rect)

        # 상태 뱃지
        self._draw_state_badge(p, rect)

        # 타임스탬프 (LIVE 일 때만)
        if self._state == _STATE_LIVE and self._last_frame_at is not None:
            self._draw_timestamp(p, rect, self._last_frame_at.strftime("%H:%M:%S"))

    def _draw_placeholder(self, p: QPainter, rect) -> None:
        p.setPen(QColor(255, 255, 255, 80))
        f = QFont(self.font())
        f.setPointSize(13)
        f.setBold(True)
        p.setFont(f)
        if self._state == _STATE_DISCONNECTED:
            text = "스트리밍 서버 연결 대기"
        elif self._state == _STATE_WAITING:
            text = f"{self._robot} 영상 대기 중"
        else:
            text = "영상 없음"
        p.drawText(rect, Qt.AlignCenter, text)

    def _draw_state_badge(self, p: QPainter, rect) -> None:
        if self._state == _STATE_LIVE:
            text = "LIVE"
            color = QColor(COLORS["danger"])
        elif self._state == _STATE_STALL:
            text = "신호 약함"
            color = QColor(COLORS.get("warning", "#E0A23A"))
        elif self._state == _STATE_WAITING:
            text = "대기 중"
            color = QColor("#88a4b0")
        else:
            text = "끊김"
            color = QColor("#888888")

        from PyQt5.QtCore import QRectF
        badge = QRectF(12, 12, 90, 26)
        p.setBrush(QColor(0, 0, 0, 150))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(badge, 13, 13)

        # 점 (LIVE 만 깜박임)
        dot_color = color
        if self._state == _STATE_LIVE and (datetime.now().microsecond // 500_000) % 2 == 0:
            dot_color = QColor("#FFFFFF")
        p.setBrush(dot_color)
        # QRectF 좌표는 float — QPointF overload 사용 (PyQt5 는 (x,y,w,h) overload 가 int 만 받음)
        from PyQt5.QtCore import QPointF
        p.drawEllipse(QPointF(badge.left() + 18, badge.center().y()), 4, 4)

        # 텍스트
        p.setPen(QColor("#FFFFFF"))
        f = QFont(self.font())
        f.setPointSize(10)
        f.setBold(True)
        p.setFont(f)
        p.drawText(
            badge.adjusted(30, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, text,
        )

    def _draw_timestamp(self, p: QPainter, rect, text: str) -> None:
        from PyQt5.QtCore import QRectF
        ts = QRectF(rect.width() - 110, 12, 96, 26)
        p.setBrush(QColor(0, 0, 0, 130))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(ts, 13, 13)
        p.setPen(QColor("#FFFFFF"))
        f = QFont(self.font())
        f.setPointSize(10)
        p.setFont(f)
        p.drawText(ts, Qt.AlignCenter, text)


class WebRTCStreamView(QWidget):
    """GogoPing D435 1080p WebRTC 영상 뷰어 — QWebEngineView 로 robot-web 임베드.

    `CameraStreamView` (WS JPEG → QPainter) 와 동일 슬롯 대체 위젯. control-service
    의 HTTP mirror (/admin-embed/, dist-admin/) 페이지를 임베드해 OpenSSL 1.x ↔ 3.x
    호환성 이슈 우회. 임베드 페이지의 useWebRTCStream('admin-ui') 가 /ws/webrtc/
    signaling 에 붙어 영상 받음. WebRTC SDP/ICE/DTLS/RTP/H.264 디코딩은 모두 Chromium
    engine 이 처리.

    셋업:
      1. cd service/web-service/robot-web && npm run build:admin
         (dist-admin/ 생성, base=/admin-embed/ 로 빌드)
      2. control-service streaming uvicorn 이 /admin-embed/ 로 mount
      3. admin-app 이 이 위젯으로 띄움

    URL override: env ADMIN_GOGOPING_VIDEO_URL (기본 /admin-embed/?embed=gogoping-video).
    PyQtWebEngine 미설치 환경에선 placeholder 라벨 표시 (fallback).
    """

    DEFAULT_URL = "http://localhost:8100/admin-embed/?embed=gogoping-video"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        url = os.environ.get("ADMIN_GOGOPING_VIDEO_URL", self.DEFAULT_URL)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if not _HAS_WEBENGINE or QWebEngineView is None:
            placeholder = QLabel(
                "PyQtWebEngine 미설치 — 가상환경에서\n"
                "  pip install PyQtWebEngine\n"
                "후 admin-app 재시작 필요"
            )
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setWordWrap(True)
            placeholder.setStyleSheet(
                f"color: {COLORS.get('text_muted', '#888')}; padding: 16px;"
            )
            layout.addWidget(placeholder)
            self._view = None
            return

        self._view = QWebEngineView(self)
        if _LocalhostPermissivePage is not None:
            self._page = _LocalhostPermissivePage(self._view)
            self._view.setPage(self._page)
        self._tune_settings(self._view)
        self._view.setUrl(QUrl(url))
        layout.addWidget(self._view)

    @staticmethod
    def _tune_settings(view: "QWebEngineView") -> None:
        """HW WebGL / accel canvas 활성 — embed 페이지가 H.264 HW decode 쓰도록."""
        if QWebEngineSettings is None:
            return
        try:
            s = view.settings()
            s.setAttribute(QWebEngineSettings.WebGLEnabled, True)
            s.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, True)
            for attr in ("LocalContentCanAccessRemoteUrls", "AllowRunningInsecureContent"):
                key = getattr(QWebEngineSettings, attr, None)
                if key is not None:
                    s.setAttribute(key, True)
        except Exception:  # noqa: BLE001
            pass
