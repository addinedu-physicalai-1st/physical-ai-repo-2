"""Pingdergarten Admin UI 진입점."""

from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from datetime import datetime

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QMouseEvent
from PyQt5.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config.client_id import get_or_create_client_id
from dashboards import EduPingDashboard, GogoPingDashboard, NoriArmDashboard
from services.stream_client import StreamClient
from theme import COLORS, ROBOTS, apply_theme
from widgets import Icon, StatusBadge


class NavButton(QPushButton):
    """체크 가능한 사이드바 네비 버튼. [icon] [name / tagline] 가로 배치."""

    def __init__(self, kind: str, name: str, tagline: str, color: str, parent=None):
        super().__init__("", parent)
        self.setObjectName("navBtn")
        self.setCheckable(True)
        self.setMinimumHeight(64)
        self.setCursor(Qt.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(12)

        # 아이콘 박스 (옅은 배경 원)
        avatar = QFrame(self)
        avatar.setFixedSize(40, 40)
        avatar.setStyleSheet(
            f"background: {_soften(color, 0.20)}; border-radius: 20px;"
        )
        a_lay = QVBoxLayout(avatar)
        a_lay.setContentsMargins(0, 0, 0, 0)
        a_lay.addWidget(Icon(kind, size=22, color=color), 0, Qt.AlignCenter)
        avatar.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(avatar, 0, Qt.AlignVCenter)

        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        n = QLabel(name)
        n.setStyleSheet(
            "font-weight: 700; font-size: 11pt; background: transparent;"
        )
        n.setAttribute(Qt.WA_TransparentForMouseEvents)
        t = QLabel(tagline)
        t.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 9pt; background: transparent;"
        )
        t.setAttribute(Qt.WA_TransparentForMouseEvents)
        text_box.addWidget(n)
        text_box.addWidget(t)
        lay.addLayout(text_box, 1)


def _soften(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r = int(h[0:2], 16); g = int(h[2:4], 16); b = int(h[4:6], 16)
    return (f"#{int(255 - (255 - r) * alpha):02X}"
            f"{int(255 - (255 - g) * alpha):02X}"
            f"{int(255 - (255 - b) * alpha):02X}")


class Sidebar(QWidget):
    """좌측 네비. 브랜드 + 로봇 버튼 + 시계 푸터."""

    def __init__(self, on_select, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setMinimumWidth(220)
        self.setMaximumWidth(320)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 24, 10, 20)
        lay.setSpacing(14)

        # 브랜드
        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        brand_avatar = QFrame()
        brand_avatar.setFixedSize(40, 40)
        brand_avatar.setStyleSheet(
            f"background: {COLORS['panel']}; border-radius: 20px;"
        )
        ba = QVBoxLayout(brand_avatar)
        ba.setContentsMargins(0, 0, 0, 0)
        ba.addWidget(Icon("rainbow", size=24, color=COLORS["primary"]),
                     0, Qt.AlignCenter)
        brand_row.addWidget(brand_avatar)

        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        title = QLabel("Pingdergarten")
        title.setObjectName("brand")
        sub = QLabel("ADMIN · 사랑의 에듀핑")
        sub.setObjectName("brandSub")
        brand_text.addWidget(title)
        brand_text.addWidget(sub)
        brand_row.addLayout(brand_text)
        brand_row.addStretch(1)
        lay.addLayout(brand_row)

        lay.addSpacing(8)

        section = QLabel("로봇 친구들")
        section.setObjectName("sectionTitle")
        lay.addWidget(section)

        # 로봇 버튼
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, NavButton] = {}
        for i, key in enumerate(("noriarm", "gogoping", "eduping")):
            meta = ROBOTS[key]
            btn = NavButton(meta["icon"], meta["name"], meta["tagline"],
                            meta["color"])
            btn.clicked.connect(lambda _=False, k=key: on_select(k))
            self._group.addButton(btn, i)
            self._buttons[key] = btn
            lay.addWidget(btn)

        lay.addStretch(1)

        # 시계 푸터
        footer = QFrame()
        footer.setObjectName("cardSoft")
        fl = QVBoxLayout(footer)
        fl.setContentsMargins(14, 12, 14, 12)
        fl.setSpacing(6)
        self.clock = QLabel("--:--:--")
        self.clock.setStyleSheet(
            f"font-size: 17pt; font-weight: 800; color: {COLORS['text']};"
        )
        self.clock.setAlignment(Qt.AlignCenter)
        date = QLabel(datetime.now().strftime("%Y년 %m월 %d일 %a"))
        date.setObjectName("brandSub")
        date.setAlignment(Qt.AlignCenter)
        fl.addWidget(self.clock)
        fl.addWidget(date)
        lay.addWidget(footer)

        version = QLabel("v0.1 · mock data")
        version.setObjectName("sidebarFooter")
        version.setAlignment(Qt.AlignCenter)
        lay.addWidget(version)

        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(1000)
        self._tick()

    def select(self, key: str) -> None:
        self._buttons[key].setChecked(True)

    def _tick(self) -> None:
        self.clock.setText(datetime.now().strftime("%H:%M:%S"))


class TopBar(QWidget):
    """본문 상단 — 페이지 타이틀 + 시스템 뱃지."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(80)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(28, 16, 28, 12)
        lay.setSpacing(12)

        self.icon_box = QFrame()
        self.icon_box.setFixedSize(40, 40)
        self.icon_box.setStyleSheet(
            f"background: {COLORS['panel']}; border-radius: 20px; "
            f"border: 1px solid {COLORS['border']};"
        )
        ib = QVBoxLayout(self.icon_box)
        ib.setContentsMargins(0, 0, 0, 0)
        self.icon = Icon("arm", size=22, color=COLORS["lavender"])
        ib.addWidget(self.icon, 0, Qt.AlignCenter)
        lay.addWidget(self.icon_box)

        self.title = QLabel("대시보드")
        f = QFont()
        f.setPointSize(18)
        f.setBold(True)
        self.title.setFont(f)

        self.subtitle = QLabel("로봇 친구를 골라주세요")
        self.subtitle.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 10pt;"
        )

        text_box = QVBoxLayout()
        text_box.setSpacing(0)
        text_box.addWidget(self.title)
        text_box.addWidget(self.subtitle)
        lay.addLayout(text_box)
        lay.addStretch(1)

        self.network_badge = StatusBadge("ROS2 연결", COLORS["sky"])
        self.system_badge = StatusBadge("시스템 정상", COLORS["success"])
        lay.addWidget(self.network_badge)
        lay.addWidget(self.system_badge)

    def set_page(self, key: str) -> None:
        meta = ROBOTS[key]
        self.title.setText(f"{meta['name']} 대시보드")
        self.subtitle.setText(meta["tagline"])
        self.icon.set_kind(meta["icon"])
        self.icon.set_color(meta["color"])


class AdminWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pingdergarten Admin")
        self.resize(1400, 880)
        self.setMinimumSize(1180, 760)

        # SR-CAM-004 — 단일 StreamClient 인스턴스 (앱 라이프타임).
        # base_url 은 STREAMING_BASE_URL env 로 override 가능.
        client_id = get_or_create_client_id()
        base_url = os.environ.get("STREAMING_BASE_URL", "ws://localhost:8100")
        self.stream_client = StreamClient(
            client_id=client_id, base_url=base_url, client_kind="admin",
        )
        self.stream_client.start()

        root = QWidget()
        root.setObjectName("mainBg")
        self.setCentralWidget(root)
        root_lay = QHBoxLayout(root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        self.sidebar = Sidebar(self._select)
        root_lay.addWidget(self.sidebar, 1)
        
        right = QWidget()
        right.setObjectName("mainBg")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)
        self.topbar = TopBar()
        right_lay.addWidget(self.topbar)
        
        self.stack = QStackedWidget()
        self.pages: dict[str, QWidget] = {
            "noriarm":  NoriArmDashboard(),
            "gogoping": GogoPingDashboard(stream_client=self.stream_client),
            "eduping":  EduPingDashboard(),
        }
        for w in self.pages.values():
            self.stack.addWidget(w)
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_lay.addWidget(self.stack, 1)
        root_lay.addWidget(right, 4)

        self._select("noriarm")

    def _select(self, key: str) -> None:
        self.sidebar.select(key)
        self.stack.setCurrentWidget(self.pages[key])
        self.topbar.set_page(key)

    def closeEvent(self, ev) -> None:   # noqa: N802
        try:
            self.stream_client.stop()
        except Exception:
            pass
        super().closeEvent(ev)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Pingdergarten Admin")
    apply_theme(app)
    win = AdminWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
