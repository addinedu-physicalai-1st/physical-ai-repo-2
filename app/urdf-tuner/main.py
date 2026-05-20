#!/usr/bin/env python3
"""Vic Pinky URDF dimension tuner — robotics calibration console.

Edits config/robot_dims.yaml via PyQt5. YAML 은 SI (m / rad) 로 저장하고,
GUI 는 mm / rad / deg / cm 등 보정 작업에 자연스러운 단위로 표시·입력.

Baseline
--------
공장 출하 값은 같은 config 디렉토리의 robot_dims.factory.yaml 에 별도 보존.
"Reset to default" 가 이 파일을 read. GUI 는 절대 factory 파일을 덮어쓰지 않음.

Sections
--------
* Wheel            — radius / thickness / separation / x_offset / z_offset
* LIDAR mount      — mount xyz + rpy
* LIDAR laser      — laser xyz + rpy
* Calibration      — UMBmark 류 보정 (실측 거리·각도 → wheel.radius/separation)
* RViz preview     — display.launch.xml subprocess + Save 시 auto-restart
"""

from __future__ import annotations

import math
import os
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QPalette, QColor
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Paths

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_DIR = _REPO_ROOT / "controller/gogoping-controller/src/vic_pinky/vicpinky_description/config"
YAML_PATH = _CONFIG_DIR / "robot_dims.yaml"
FACTORY_YAML_PATH = _CONFIG_DIR / "robot_dims.factory.yaml"
WS_ROOT = _REPO_ROOT / "controller/gogoping-controller"

YAML_HEADER = (
    "# Vic Pinky 로봇 dimension. app/urdf-tuner GUI 가 편집.\n"
    "# 이 파일은 두 곳에서 read — single source of truth:\n"
    "#   1) vicpinky_description/urdf/robot_core.xacro (URDF 시각/TF/collision)\n"
    "#   2) vicpinky_bringup/bringup.py            (실 주행 odom + cmd_vel 변환)\n"
    "# 공장 baseline 은 robot_dims.factory.yaml 별도 보존.\n"
    "\n"
)


# Hardcoded fallback — factory yaml 이 사라졌을 때만 사용.
_FALLBACK_DEFAULTS = {
    "wheel": {
        "radius": 0.0825, "thickness": 0.05, "separation": 0.4288,
        "x_offset": 0.0, "z_offset": -0.0048,
    },
    "lidar": {
        "mount_x": 0.185, "mount_y": 0.0, "mount_z": 0.12,
        "mount_roll": 0.0, "mount_pitch": 0.0, "mount_yaw": 0.0,
        "laser_x": 0.0, "laser_y": 0.0, "laser_z": 0.03,
        "laser_roll": 0.0, "laser_pitch": 0.0, "laser_yaw": math.pi,
    },
}


def load_factory_defaults() -> dict:
    """공장 baseline. factory yaml 우선, 없으면 hardcoded fallback."""
    merged = {k: dict(v) for k, v in _FALLBACK_DEFAULTS.items()}
    if FACTORY_YAML_PATH.exists():
        with FACTORY_YAML_PATH.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for section, vals in data.items():
            if section in merged and isinstance(vals, dict):
                merged[section].update(vals)
    return merged


# ---------------------------------------------------------------------------
# Field specs

@dataclass(frozen=True)
class Field:
    """Spec for one editable dim.

    `low_disp`/`high_disp`/`step_disp` are in the *display* unit (mm or rad).
    Internal YAML value = display value / `scale`.
    """
    key: str
    label: str
    low_disp: float
    high_disp: float
    step_disp: float
    suffix: str
    scale: float
    decimals: int = 3
    tooltip: str = ""


_MM = 1000.0
_RAD = 1.0
_RAD_LIM = math.pi * 2

WHEEL_FIELDS = [
    Field("radius",     "Radius",     1.0,    500.0,  0.1,  "mm",  _MM, 3),
    Field("thickness",  "Thickness",  1.0,    500.0,  0.1,  "mm",  _MM, 3),
    Field("separation", "Separation", 1.0,   2000.0,  0.1,  "mm",  _MM, 3),
    Field("x_offset",   "X offset",  -1000.0, 1000.0, 0.1,  "mm",  _MM, 3, "앞(+) / 뒤(-)"),
    Field("z_offset",   "Z offset",  -1000.0, 1000.0, 0.1,  "mm",  _MM, 3, "위(+) / 아래(-)"),
]

LIDAR_MOUNT_FIELDS = [
    Field("mount_x",    "X",     -1000.0, 1000.0, 0.1,  "mm",  _MM, 3),
    Field("mount_y",    "Y",     -1000.0, 1000.0, 0.1,  "mm",  _MM, 3),
    Field("mount_z",    "Z",     -1000.0, 1000.0, 0.1,  "mm",  _MM, 3),
    Field("mount_roll", "Roll",  -_RAD_LIM, _RAD_LIM, 0.01, "rad", _RAD, 4),
    Field("mount_pitch","Pitch", -_RAD_LIM, _RAD_LIM, 0.01, "rad", _RAD, 4),
    Field("mount_yaw",  "Yaw",   -_RAD_LIM, _RAD_LIM, 0.01, "rad", _RAD, 4),
]

LIDAR_LASER_FIELDS = [
    Field("laser_x",    "X",     -1000.0, 1000.0, 0.1,  "mm",  _MM, 3),
    Field("laser_y",    "Y",     -1000.0, 1000.0, 0.1,  "mm",  _MM, 3),
    Field("laser_z",    "Z",     -1000.0, 1000.0, 0.1,  "mm",  _MM, 3),
    Field("laser_roll", "Roll",  -_RAD_LIM, _RAD_LIM, 0.01, "rad", _RAD, 4),
    Field("laser_pitch","Pitch", -_RAD_LIM, _RAD_LIM, 0.01, "rad", _RAD, 4),
    Field("laser_yaw",  "Yaw",   -_RAD_LIM, _RAD_LIM, 0.01, "rad", _RAD, 4),
]


# ---------------------------------------------------------------------------
# Aesthetic — light engineering console

QSS = """
* {
    font-family: "Source Sans 3", "Cantarell", "Ubuntu", "Noto Sans CJK KR", sans-serif;
    font-size: 12px;
}
QMainWindow, QWidget#root, QScrollArea, QScrollArea > QWidget > QWidget {
    background-color: #f4f5f8;
    color: #1f2330;
}

QLabel#title-eyebrow {
    color: #8a92a3;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 3px;
}
QLabel#title-main {
    color: #1f2330;
    font-size: 20px;
    font-weight: 300;
    letter-spacing: 5px;
}
QLabel#title-version {
    color: #b45309;
    font-family: "JetBrains Mono", "Cascadia Code", "Source Code Pro", monospace;
    font-size: 10px;
    letter-spacing: 1px;
}
QLabel#path-label {
    color: #6b7280;
    font-family: "JetBrains Mono", "Cascadia Code", "Source Code Pro", monospace;
    font-size: 10px;
}
QLabel#info-banner {
    color: #1e3a5f;
    background-color: #eff6ff;
    border: 1px solid #bfdbfe;
    border-left: 3px solid #3b82f6;
    border-radius: 4px;
    padding: 8px 12px;
    font-size: 11px;
}
QLabel#section-hint {
    color: #6b7280;
    font-size: 10px;
}
QLabel#mono {
    font-family: "JetBrains Mono", "Cascadia Code", "Source Code Pro", monospace;
}
QLabel#preview {
    font-family: "JetBrains Mono", "Cascadia Code", "Source Code Pro", monospace;
    color: #374151;
    font-size: 11px;
    padding: 6px 8px;
    background-color: #f4f5f8;
    border: 1px solid #e0e3eb;
    border-radius: 3px;
}

QGroupBox {
    background-color: #ffffff;
    border: 1px solid #e0e3eb;
    border-radius: 6px;
    margin-top: 18px;
    padding: 14px 12px 10px 12px;
    font-weight: 700;
    letter-spacing: 2px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    top: 2px;
    padding: 2px 8px;
    color: #1f2330;
    background-color: #ffffff;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 3px;
}
QGroupBox[accent="amber"]  { border-left: 3px solid #d97706; }
QGroupBox[accent="indigo"] { border-left: 3px solid #4f46e5; }
QGroupBox[accent="cyan"]   { border-left: 3px solid #0891b2; }
QGroupBox[accent="green"]  { border-left: 3px solid #059669; }
QGroupBox[accent="pink"]   { border-left: 3px solid #db2777; }

QGroupBox#sub {
    background-color: #fafbfc;
    border: 1px solid #e0e3eb;
    border-radius: 5px;
    margin-top: 14px;
    padding: 10px 10px 8px 10px;
}
QGroupBox#sub::title {
    color: #6b7280;
    background-color: #fafbfc;
    font-size: 9px;
    letter-spacing: 2px;
}

QLabel { color: #374151; }

QDoubleSpinBox {
    background-color: #ffffff;
    border: 1px solid #d4d8e0;
    border-radius: 4px;
    padding: 5px 8px;
    color: #b45309;
    font-family: "JetBrains Mono", "Cascadia Code", "Source Code Pro", monospace;
    font-size: 12px;
    selection-background-color: #d97706;
    selection-color: #ffffff;
    min-width: 92px;
}
QDoubleSpinBox:focus  { border: 1px solid #d97706; }
QDoubleSpinBox:hover  { border: 1px solid #b0b6c2; }
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background-color: #f4f5f8;
    border: none;
    border-left: 1px solid #e0e3eb;
    width: 16px;
}
QDoubleSpinBox::up-button   { border-top-right-radius: 3px; }
QDoubleSpinBox::down-button { border-bottom-right-radius: 3px; }
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: #e9ecf2;
}
QDoubleSpinBox::up-arrow {
    image: none;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-bottom: 4px solid #6b7280;
    width: 0; height: 0;
}
QDoubleSpinBox::down-arrow {
    image: none;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-top: 4px solid #6b7280;
    width: 0; height: 0;
}

QPushButton {
    background-color: #ffffff;
    border: 1px solid #d4d8e0;
    border-radius: 4px;
    padding: 7px 14px;
    color: #1f2330;
    font-weight: 500;
    letter-spacing: 0.4px;
    font-size: 11px;
}
QPushButton:hover    { background-color: #f4f5f8; border-color: #b0b6c2; }
QPushButton:pressed  { background-color: #e9ecf2; }
QPushButton:disabled { color: #b0b6c2; background-color: #ffffff; border-color: #e0e3eb; }

QPushButton#primary {
    background-color: #d97706;
    border: 1px solid #d97706;
    color: #ffffff;
    font-weight: 700;
    letter-spacing: 1px;
}
QPushButton#primary:hover    { background-color: #b45309; border-color: #b45309; }
QPushButton#primary:pressed  { background-color: #92400e; }
QPushButton#danger:hover     { border-color: #dc2626; color: #dc2626; }
QPushButton#run {
    background-color: #ecfdf5;
    border: 1px solid #a7f3d0;
    color: #047857;
    font-weight: 700;
}
QPushButton#run:hover  { background-color: #d1fae5; border-color: #059669; }
QPushButton#stop:hover { border-color: #dc2626; color: #dc2626; }

QCheckBox { color: #374151; spacing: 8px; padding: 2px; font-size: 11px; }
QCheckBox::indicator {
    width: 14px; height: 14px;
    border: 1px solid #d4d8e0;
    border-radius: 3px;
    background-color: #ffffff;
}
QCheckBox::indicator:hover   { border-color: #b0b6c2; }
QCheckBox::indicator:checked {
    background-color: #059669;
    border-color: #059669;
}

QFrame#divider {
    background-color: #e0e3eb;
    max-height: 1px;
    min-height: 1px;
}

QScrollBar:vertical {
    background-color: #f4f5f8;
    width: 10px;
    margin: 4px 2px 4px 0;
}
QScrollBar::handle:vertical {
    background-color: #d4d8e0;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background-color: #b0b6c2; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

QToolTip {
    background-color: #1f2330;
    color: #f4f5f8;
    border: 1px solid #d97706;
    padding: 4px 8px;
}
"""


# ---------------------------------------------------------------------------
# YAML I/O

def load_yaml() -> dict:
    defaults = load_factory_defaults()
    if not YAML_PATH.exists():
        return defaults
    with YAML_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    merged = {k: dict(v) for k, v in defaults.items()}
    for section, vals in data.items():
        if section in merged and isinstance(vals, dict):
            merged[section].update(vals)
    return merged


def save_yaml(data: dict) -> None:
    YAML_PATH.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    with YAML_PATH.open("w", encoding="utf-8") as f:
        f.write(YAML_HEADER)
        f.write(body)


# ---------------------------------------------------------------------------
# GUI

class TunerWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("URDF Tuner — Vic Pinky")
        self.resize(880, 720)

        self._fields: dict[tuple[str, str], Field] = {}
        self._spins: dict[tuple[str, str], QDoubleSpinBox] = {}
        self._suspend_change = False
        self._rviz_proc: subprocess.Popen | None = None

        central = QWidget(objectName="root")
        outer = QVBoxLayout(central)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(12)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_info_banner())

        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)

        body = QWidget()
        grid = QGridLayout(body)
        grid.setSpacing(12)
        grid.setContentsMargins(2, 4, 2, 4)

        # 2-column layout:
        #   col 0 (dims):  Wheel, LIDAR mount, LIDAR laser
        #   col 1 (tools): Calibration, RViz preview
        grid.addWidget(self._build_group("WHEEL", "wheel", WHEEL_FIELDS, "amber"), 0, 0)
        grid.addWidget(self._build_group("LIDAR · MOUNT", "lidar", LIDAR_MOUNT_FIELDS, "indigo"), 1, 0)
        grid.addWidget(self._build_group("LIDAR · LASER", "lidar", LIDAR_LASER_FIELDS, "cyan"), 2, 0)
        grid.addWidget(self._build_calibration_group(), 0, 1, 2, 1)
        grid.addWidget(self._build_rviz_group(), 2, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(3, 1)

        scroll.setWidget(body)
        outer.addWidget(scroll, stretch=1)

        outer.addWidget(self._build_divider())
        outer.addLayout(self._build_actions_row())
        outer.addWidget(self._build_status_label())

        self.setCentralWidget(central)
        self.setStyleSheet(QSS)

        self._load_into_ui(load_yaml())
        self._set_status_saved()

    # --- Layout builders ---------------------------------------------------

    def _build_header(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)

        row = QHBoxLayout()
        row.setSpacing(14)

        eyebrow = QLabel("VIC PINKY  ·  R&D")
        eyebrow.setObjectName("title-eyebrow")
        version = QLabel("v0.1  ·  DIMS.YAML")
        version.setObjectName("title-version")
        version.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(eyebrow, 1)
        row.addWidget(version, 0)

        main = QLabel("URDF · TUNER")
        main.setObjectName("title-main")

        path = QLabel(str(YAML_PATH))
        path.setObjectName("path-label")
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path.setWordWrap(True)

        v.addLayout(row)
        v.addWidget(main)
        v.addSpacing(2)
        v.addWidget(path)
        return wrap

    def _build_info_banner(self) -> QLabel:
        banner = QLabel(
            "wheel.radius / separation 은 URDF 시각·TF 와 bringup.py odom 양쪽에 "
            "반영됩니다.  실 로봇 적용 시 colcon build + 노드 재시작 필요."
        )
        banner.setObjectName("info-banner")
        banner.setWordWrap(True)
        return banner

    def _build_divider(self) -> QFrame:
        f = QFrame()
        f.setObjectName("divider")
        f.setFrameShape(QFrame.HLine)
        return f

    def _build_group(self, title: str, section: str,
                     fields: list[Field], accent: str) -> QGroupBox:
        group = QGroupBox(title)
        group.setProperty("accent", accent)
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        form.setVerticalSpacing(6)
        form.setHorizontalSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)

        for spec in fields:
            spin = QDoubleSpinBox()
            spin.setDecimals(spec.decimals)
            spin.setRange(spec.low_disp, spec.high_disp)
            spin.setSingleStep(spec.step_disp)
            spin.setSuffix(f"  {spec.suffix}")
            spin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            spin.setButtonSymbols(QDoubleSpinBox.UpDownArrows)
            spin.valueChanged.connect(self._on_value_changed)
            if spec.tooltip:
                spin.setToolTip(spec.tooltip)

            self._fields[(section, spec.key)] = spec
            self._spins[(section, spec.key)] = spin

            label_w = QLabel(spec.label)
            if spec.tooltip:
                label_w.setToolTip(spec.tooltip)
            form.addRow(label_w, spin)

        return group

    def _build_calibration_group(self) -> QGroupBox:
        group = QGroupBox("CALIBRATION  ·  MEASURED → CORRECTED")
        group.setProperty("accent", "green")
        v = QVBoxLayout(group)
        v.setSpacing(10)

        # Linear
        lin = QGroupBox("STRAIGHT-LINE  →  wheel.radius")
        lin.setObjectName("sub")
        lf = QFormLayout(lin)
        lf.setVerticalSpacing(5)
        lf.setHorizontalSpacing(10)
        lf.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)

        self.lin_cmd = self._make_unit_spin(100.0, 0.1, 10000.0, " cm", decimals=2, step=1.0)
        self.lin_meas = self._make_unit_spin(100.0, 0.1, 10000.0, " cm", decimals=2, step=0.5)
        lf.addRow("Commanded", self.lin_cmd)
        lf.addRow("Measured", self.lin_meas)

        self.lin_preview = QLabel("")
        self.lin_preview.setObjectName("preview")
        lf.addRow(self.lin_preview)

        lin_apply = QPushButton("APPLY  →  wheel.radius")
        lin_apply.clicked.connect(self.on_calib_radius)
        lf.addRow(lin_apply)

        self.lin_cmd.valueChanged.connect(self._update_calib_previews)
        self.lin_meas.valueChanged.connect(self._update_calib_previews)
        v.addWidget(lin)

        # Angular
        ang = QGroupBox("ROTATION  →  wheel.separation")
        ang.setObjectName("sub")
        af = QFormLayout(ang)
        af.setVerticalSpacing(5)
        af.setHorizontalSpacing(10)
        af.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)

        self.ang_cmd = self._make_unit_spin(360.0, 0.1, 10000.0, " °", decimals=2, step=10.0)
        self.ang_meas = self._make_unit_spin(360.0, 0.1, 10000.0, " °", decimals=2, step=1.0)
        af.addRow("Commanded", self.ang_cmd)
        af.addRow("Measured", self.ang_meas)

        self.ang_preview = QLabel("")
        self.ang_preview.setObjectName("preview")
        af.addRow(self.ang_preview)

        ang_apply = QPushButton("APPLY  →  wheel.separation")
        ang_apply.clicked.connect(self.on_calib_separation)
        af.addRow(ang_apply)

        self.ang_cmd.valueChanged.connect(self._update_calib_previews)
        self.ang_meas.valueChanged.connect(self._update_calib_previews)
        v.addWidget(ang)

        note = QLabel(
            "직진 명령 → 줄자 실측  /  회전 명령 → 마커·IMU 실측.\n"
            "APPLY 는 슬라이더만 갱신 — 💾 SAVE 로 YAML 반영."
        )
        note.setObjectName("section-hint")
        note.setWordWrap(True)
        v.addWidget(note)

        return group

    def _build_rviz_group(self) -> QGroupBox:
        group = QGroupBox("RVIZ  ·  LIVE PREVIEW")
        group.setProperty("accent", "pink")
        v = QVBoxLayout(group)
        v.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.rviz_start_btn = QPushButton("▶  START")
        self.rviz_start_btn.setObjectName("run")
        self.rviz_start_btn.clicked.connect(self.on_rviz_start)
        self.rviz_stop_btn = QPushButton("■  STOP")
        self.rviz_stop_btn.setObjectName("stop")
        self.rviz_stop_btn.clicked.connect(self.on_rviz_stop)
        self.rviz_stop_btn.setEnabled(False)
        row.addWidget(self.rviz_start_btn)
        row.addWidget(self.rviz_stop_btn)
        row.addStretch(1)
        v.addLayout(row)

        self.rviz_autoreload = QCheckBox("Save 시 자동 재시작")
        self.rviz_autoreload.setChecked(True)
        v.addWidget(self.rviz_autoreload)

        self.rviz_status = QLabel("●  IDLE")
        self.rviz_status.setObjectName("mono")
        self.rviz_status.setStyleSheet("color: #9a9aa5; font-weight: 700; font-size: 11px;")
        v.addWidget(self.rviz_status)

        info = QLabel(
            "ros2 launch vicpinky_description display_tuner.launch.xml\n"
            "※ 부모 셸에 ROS env source 필요."
        )
        info.setObjectName("section-hint")
        info.setWordWrap(True)
        v.addWidget(info)

        QTimer.singleShot(0, self._update_calib_previews)
        return group

    def _build_actions_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.reload_btn = QPushButton("RELOAD FROM YAML")
        self.reload_btn.clicked.connect(self.on_reload)
        self.reset_btn = QPushButton("RESET TO FACTORY")
        self.reset_btn.setObjectName("danger")
        self.reset_btn.setToolTip(
            f"공장 baseline (robot_dims.factory.yaml) 로 복원:\n{FACTORY_YAML_PATH}"
        )
        self.reset_btn.clicked.connect(self.on_reset)
        self.save_btn = QPushButton("💾  SAVE")
        self.save_btn.setObjectName("primary")
        self.save_btn.clicked.connect(self.on_save)

        row.addWidget(self.reload_btn)
        row.addWidget(self.reset_btn)
        row.addStretch(1)
        row.addWidget(self.save_btn)
        return row

    def _build_status_label(self) -> QLabel:
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setObjectName("mono")
        return self.status_label

    def _make_unit_spin(self, default: float, low: float, high: float,
                        suffix: str, decimals: int, step: float) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setDecimals(decimals)
        s.setRange(low, high)
        s.setSingleStep(step)
        s.setValue(default)
        s.setSuffix(suffix)
        s.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return s

    # --- State -----------------------------------------------------------

    def _load_into_ui(self, data: dict) -> None:
        self._suspend_change = True
        try:
            for (section, key), spec in self._fields.items():
                yaml_val = data.get(section, {}).get(key, _FALLBACK_DEFAULTS[section][key])
                self._spins[(section, key)].setValue(float(yaml_val) * spec.scale)
        finally:
            self._suspend_change = False
        self._update_calib_previews()

    def _collect_from_ui(self) -> dict:
        out: dict = {"wheel": {}, "lidar": {}}
        for (section, key), spin in self._spins.items():
            spec = self._fields[(section, key)]
            out[section][key] = spin.value() / spec.scale
        return out

    def _current_yaml_val(self, section: str, key: str) -> float:
        return self._spins[(section, key)].value() / self._fields[(section, key)].scale

    def _on_value_changed(self, _v: float) -> None:
        if self._suspend_change:
            return
        self._set_status_dirty()
        self._update_calib_previews()

    def _set_status_dirty(self) -> None:
        self.status_label.setText("●  UNSAVED  ·  저장 안 됨")
        self.status_label.setStyleSheet(
            "color: #dc2626; font-weight: 700; letter-spacing: 2px; font-size: 11px;"
        )

    def _set_status_saved(self) -> None:
        self.status_label.setText("✓  SAVED  ·  저장됨")
        self.status_label.setStyleSheet(
            "color: #059669; font-weight: 700; letter-spacing: 2px; font-size: 11px;"
        )

    # --- Calibration -----------------------------------------------------

    def _update_calib_previews(self) -> None:
        if not hasattr(self, "lin_preview"):
            return
        cur_r = self._current_yaml_val("wheel", "radius")
        cur_s = self._current_yaml_val("wheel", "separation")
        new_r = self._calc_new_radius(cur_r)
        new_s = self._calc_new_separation(cur_s)
        self.lin_preview.setText(
            f"radius:      {cur_r * 1000:>8.3f}  →  {new_r * 1000:>8.3f}  mm"
        )
        self.ang_preview.setText(
            f"separation:  {cur_s * 1000:>8.3f}  →  {new_s * 1000:>8.3f}  mm"
        )

    def _calc_new_radius(self, current: float) -> float:
        cmd = self.lin_cmd.value()
        meas = self.lin_meas.value()
        if cmd <= 0:
            return current
        return current * (meas / cmd)

    def _calc_new_separation(self, current: float) -> float:
        cmd = self.ang_cmd.value()
        meas = self.ang_meas.value()
        if meas <= 0:
            return current
        return current * (cmd / meas)

    def on_calib_radius(self) -> None:
        spin = self._spins[("wheel", "radius")]
        spec = self._fields[("wheel", "radius")]
        new_yaml = self._calc_new_radius(self._current_yaml_val("wheel", "radius"))
        new_disp = new_yaml * spec.scale
        if not (spin.minimum() <= new_disp <= spin.maximum()):
            QMessageBox.warning(
                self, "Out of range",
                f"새 값 {new_disp:.3f} mm 이 허용 범위 [{spin.minimum()}, {spin.maximum()}] 를 벗어납니다.",
            )
            return
        spin.setValue(new_disp)
        self._set_status_dirty()

    def on_calib_separation(self) -> None:
        spin = self._spins[("wheel", "separation")]
        spec = self._fields[("wheel", "separation")]
        new_yaml = self._calc_new_separation(self._current_yaml_val("wheel", "separation"))
        new_disp = new_yaml * spec.scale
        if not (spin.minimum() <= new_disp <= spin.maximum()):
            QMessageBox.warning(
                self, "Out of range",
                f"새 값 {new_disp:.3f} mm 이 허용 범위를 벗어납니다.",
            )
            return
        spin.setValue(new_disp)
        self._set_status_dirty()

    # --- Save / reset / reload ------------------------------------------

    def on_save(self) -> None:
        data = self._collect_from_ui()
        try:
            save_yaml(data)
        except OSError as e:
            QMessageBox.critical(self, "Save failed", f"Failed to write YAML:\n{e}")
            return
        self._set_status_saved()
        if self._rviz_proc is not None and self.rviz_autoreload.isChecked():
            self._restart_rviz()

    def on_reset(self) -> None:
        factory_note = (
            "robot_dims.factory.yaml" if FACTORY_YAML_PATH.exists()
            else "내장 fallback (factory yaml 없음)"
        )
        reply = QMessageBox.question(
            self, "Reset to factory",
            f"슬라이더와 YAML 을 공장 baseline 으로 복원합니다.\n\n"
            f"source: {factory_note}\n\n계속할까요?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        defaults = load_factory_defaults()
        self._load_into_ui(defaults)
        try:
            save_yaml(defaults)
        except OSError as e:
            QMessageBox.critical(self, "Save failed", f"Failed to write YAML:\n{e}")
            self._set_status_dirty()
            return
        self._set_status_saved()
        if self._rviz_proc is not None and self.rviz_autoreload.isChecked():
            self._restart_rviz()

    def on_reload(self) -> None:
        self._load_into_ui(load_yaml())
        self._set_status_saved()

    # --- RViz preview ----------------------------------------------------

    def _rviz_env_ok(self) -> str | None:
        if "ROS_DISTRO" not in os.environ:
            return "ROS_DISTRO 환경변수가 없습니다. /opt/ros/<distro>/setup.bash 를 먼저 source 하세요."
        if shutil.which("ros2") is None:
            return "ros2 CLI 를 PATH 에서 찾을 수 없습니다."
        ws_setup = WS_ROOT / "install" / "setup.bash"
        if not ws_setup.exists():
            return f"워크스페이스가 빌드되어 있지 않습니다:\n{ws_setup}\ncolcon build 후 다시 시도하세요."
        return None

    def _spawn_rviz(self) -> None:
        ws_setup = WS_ROOT / "install" / "setup.bash"
        cmd = f"source '{ws_setup}' && exec ros2 launch vicpinky_description display_tuner.launch.xml"
        self._rviz_proc = subprocess.Popen(
            ["bash", "-c", cmd],
            cwd=str(WS_ROOT),
            preexec_fn=os.setsid,
        )

    def _kill_rviz(self) -> None:
        if self._rviz_proc is None:
            return
        try:
            os.killpg(os.getpgid(self._rviz_proc.pid), signal.SIGINT)
            try:
                self._rviz_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(self._rviz_proc.pid), signal.SIGTERM)
                try:
                    self._rviz_proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(self._rviz_proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        self._rviz_proc = None

    def on_rviz_start(self) -> None:
        err = self._rviz_env_ok()
        if err is not None:
            QMessageBox.critical(self, "RViz 실행 불가", err)
            return
        try:
            self._spawn_rviz()
        except OSError as e:
            QMessageBox.critical(self, "RViz launch failed", str(e))
            return
        self.rviz_start_btn.setEnabled(False)
        self.rviz_stop_btn.setEnabled(True)
        self.rviz_status.setText("●  RUNNING")
        self.rviz_status.setStyleSheet("color: #059669; font-weight: 700; font-size: 11px;")

    def on_rviz_stop(self) -> None:
        self._kill_rviz()
        self.rviz_start_btn.setEnabled(True)
        self.rviz_stop_btn.setEnabled(False)
        self.rviz_status.setText("●  IDLE")
        self.rviz_status.setStyleSheet("color: #9a9aa5; font-weight: 700; font-size: 11px;")

    def _restart_rviz(self) -> None:
        self._kill_rviz()
        try:
            self._spawn_rviz()
            self.rviz_status.setText("●  RELOADED")
            self.rviz_status.setStyleSheet("color: #d97706; font-weight: 700; font-size: 11px;")
        except OSError as e:
            QMessageBox.critical(self, "RViz restart failed", str(e))
            self.rviz_start_btn.setEnabled(True)
            self.rviz_stop_btn.setEnabled(False)
            self.rviz_status.setText("●  ERROR")
            self.rviz_status.setStyleSheet("color: #dc2626; font-weight: 700; font-size: 11px;")

    def closeEvent(self, event) -> None:  # noqa: N802
        self._kill_rviz()
        super().closeEvent(event)


def _force_light_palette(app: QApplication) -> None:
    """OS 다크 테마가 Qt palette 를 invert 하는 걸 막는다."""
    p = QPalette()
    p.setColor(QPalette.Window, QColor("#f4f5f8"))
    p.setColor(QPalette.WindowText, QColor("#1f2330"))
    p.setColor(QPalette.Base, QColor("#ffffff"))
    p.setColor(QPalette.AlternateBase, QColor("#f4f5f8"))
    p.setColor(QPalette.Text, QColor("#1f2330"))
    p.setColor(QPalette.Button, QColor("#ffffff"))
    p.setColor(QPalette.ButtonText, QColor("#1f2330"))
    p.setColor(QPalette.ToolTipBase, QColor("#1f2330"))
    p.setColor(QPalette.ToolTipText, QColor("#f4f5f8"))
    p.setColor(QPalette.Highlight, QColor("#d97706"))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor("#b0b6c2"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#b0b6c2"))
    app.setPalette(p)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    _force_light_palette(app)
    win = TunerWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
