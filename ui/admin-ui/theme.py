"""Pingdergarten Admin UI 테마.

OS 라이트/다크 모드 영향을 받지 않도록 Fusion 스타일 + 명시적 QPalette + QSS 를
사용한다. 색상은 유치원 컨셉(파스텔, 따뜻한 크림 배경, 둥근 모서리)에 맞춘다.
"""

from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication


COLORS = {
    "bg":         "#FFF6E9",
    "bg_alt":     "#FFEFD5",
    "panel":      "#FFFFFF",
    "border":     "#FFE4D1",
    "border_strong": "#F4C9A8",
    "sidebar":    "#FFEAD2",
    "sidebar_active": "#FFFFFF",
    "text":       "#3F3530",
    "text_muted": "#9C8A7C",
    "text_soft":  "#6E5F54",
    "primary":    "#FF8FAB",
    "primary_dim":"#FFC2D1",
    "accent":     "#FFC371",
    "sky":        "#7EC8E3",
    "mint":       "#A8E6CF",
    "lavender":   "#C5B0E8",
    "sun":        "#FFD56B",
    "success":    "#7DCEA0",
    "warning":    "#FFAB76",
    "danger":     "#FF8A80",
    "track":      "#FFE9D6",
}

ROBOTS = {
    "noriarm": {
        "name": "NoriArm",
        "icon": "arm",
        "tagline": "놀이·정리정돈 친구",
        "color": COLORS["lavender"],
        "color_soft": "#EFE6FB",
    },
    "gogoping": {
        "name": "GogoPing",
        "icon": "vehicle",
        "tagline": "등하원·운반 친구",
        "color": COLORS["sky"],
        "color_soft": "#E1F2F9",
    },
    "eduping": {
        "name": "EduPing",
        "icon": "book",
        "tagline": "교실 보조 친구",
        "color": COLORS["mint"],
        "color_soft": "#E5F7EE",
    },
}


STYLESHEET = f"""
* {{
    font-family: "Apple SD Gothic Neo", "Pretendard", "Noto Sans KR", "Helvetica Neue", sans-serif;
    color: {COLORS['text']};
}}

QMainWindow, QWidget#mainBg {{
    background-color: {COLORS['bg']};
}}

QWidget#sidebar {{
    background-color: {COLORS['sidebar']};
    border-right: 1px solid {COLORS['border']};
}}

QLabel#brand {{
    font-size: 20px;
    font-weight: 800;
    color: {COLORS['text']};
    padding: 4px 0 2px 0;
}}

QLabel#brandSub {{
    font-size: 11px;
    color: {COLORS['text_muted']};
    letter-spacing: 1px;
}}

QPushButton#navBtn {{
    text-align: left;
    padding: 12px 14px;
    border: none;
    border-radius: 14px;
    background: transparent;
    font-size: 14px;
    font-weight: 600;
    color: {COLORS['text_soft']};
}}
QPushButton#navBtn:hover {{
    background: rgba(255, 255, 255, 0.55);
    color: {COLORS['text']};
}}
QPushButton#navBtn:checked {{
    background: {COLORS['sidebar_active']};
    color: {COLORS['text']};
}}

QLabel#sidebarFooter {{
    font-size: 11px;
    color: {COLORS['text_muted']};
}}

QFrame#card {{
    background: {COLORS['panel']};
    border: 1px solid {COLORS['border']};
    border-radius: 18px;
}}

QFrame#cardSoft {{
    background: {COLORS['bg_alt']};
    border: 1px solid {COLORS['border']};
    border-radius: 18px;
}}

QLabel#cardTitle {{
    font-size: 13px;
    font-weight: 700;
    color: {COLORS['text_soft']};
    letter-spacing: 0.5px;
}}

QLabel#metricLabel {{
    font-size: 12px;
    color: {COLORS['text_muted']};
}}

QLabel#metricValue {{
    font-size: 14px;
    font-weight: 700;
    color: {COLORS['text']};
}}

QLabel#hero {{
    font-size: 24px;
    font-weight: 800;
}}

QLabel#heroSub {{
    font-size: 13px;
    color: {COLORS['text_muted']};
}}

QLabel#sectionTitle {{
    font-size: 12px;
    font-weight: 700;
    color: {COLORS['text_muted']};
    letter-spacing: 1.2px;
}}

QProgressBar {{
    background-color: {COLORS['track']};
    border: none;
    border-radius: 8px;
    height: 14px;
    text-align: center;
    color: {COLORS['text']};
    font-size: 10px;
    font-weight: 700;
}}
QProgressBar::chunk {{
    background-color: {COLORS['primary']};
    border-radius: 8px;
}}

QListWidget {{
    background: transparent;
    border: none;
    outline: 0;
}}
QListWidget::item {{
    padding: 8px 10px;
    border-radius: 10px;
    color: {COLORS['text']};
}}
QListWidget::item:hover {{
    background: {COLORS['bg_alt']};
}}
QListWidget::item:selected {{
    background: {COLORS['primary_dim']};
    color: {COLORS['text']};
}}

QScrollBar:vertical {{
    background: transparent;
    width: 8px;
}}
QScrollBar::handle:vertical {{
    background: {COLORS['border_strong']};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QToolTip {{
    background: {COLORS['panel']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 4px 6px;
}}
"""


def apply_theme(app: QApplication) -> None:
    """Fusion 스타일 + 명시적 팔레트 + QSS 를 적용한다."""
    app.setStyle("Fusion")

    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(COLORS["bg"]))
    pal.setColor(QPalette.WindowText, QColor(COLORS["text"]))
    pal.setColor(QPalette.Base, QColor(COLORS["panel"]))
    pal.setColor(QPalette.AlternateBase, QColor(COLORS["bg_alt"]))
    pal.setColor(QPalette.Text, QColor(COLORS["text"]))
    pal.setColor(QPalette.Button, QColor(COLORS["panel"]))
    pal.setColor(QPalette.ButtonText, QColor(COLORS["text"]))
    pal.setColor(QPalette.Highlight, QColor(COLORS["primary"]))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ToolTipBase, QColor(COLORS["panel"]))
    pal.setColor(QPalette.ToolTipText, QColor(COLORS["text"]))
    pal.setColor(QPalette.PlaceholderText, QColor(COLORS["text_muted"]))
    pal.setColor(QPalette.Light, QColor(COLORS["panel"]))
    pal.setColor(QPalette.Mid, QColor(COLORS["border"]))
    pal.setColor(QPalette.Dark, QColor(COLORS["border_strong"]))
    pal.setColor(QPalette.Shadow, QColor(0, 0, 0, 24))
    app.setPalette(pal)

    app.setStyleSheet(STYLESHEET)
