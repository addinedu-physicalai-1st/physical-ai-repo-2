#!/usr/bin/env python3
"""Vic Pinky URDF dimension tuner — edits robot_dims.yaml via PyQt5 sliders.

Extras
------
* Calibration helpers — 실측값(전진거리·회전각) 입력 → wheel.radius / separation
  자동 보정. UMBmark 류의 단순 1차원 보정.
* RViz preview — display.launch.xml 을 subprocess 로 띄우고, Save 시 자동
  재시작해서 변경된 URDF 를 즉시 시각화.
"""

from __future__ import annotations

import math
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import yaml
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
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


DEFAULTS = {
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

_REPO_ROOT = Path(__file__).resolve().parents[2]
YAML_PATH = _REPO_ROOT / "controller/gogoping-controller/src/vic_pinky/vicpinky_description/config/robot_dims.yaml"
WS_ROOT = _REPO_ROOT / "controller/gogoping-controller"

YAML_HEADER = (
    "# Vic Pinky 로봇 dimension. app/urdf-tuner GUI 가 편집.\n"
    "# 이 파일은 두 곳에서 read — single source of truth:\n"
    "#   1) vicpinky_description/urdf/robot_core.xacro (URDF 시각/TF/collision)\n"
    "#   2) vicpinky_bringup/bringup.py            (실 주행 odom + cmd_vel 변환)\n"
    "# wheel.radius / separation 변경 후 실 로봇 적용 시 colcon build + 노드 재시작 필요.\n"
    "\n"
)

WHEEL_FIELDS = [
    ("radius", "Radius (m)", 0.001, 1.0, 0.001),
    ("thickness", "Thickness (m)", 0.001, 1.0, 0.001),
    ("separation", "Separation (m)", 0.001, 2.0, 0.001),
    ("x_offset", "X offset 앞(+)/뒤(-) (m)", -1.0, 1.0, 0.001),
    ("z_offset", "Z offset 위(+)/아래(-) (m)", -1.0, 1.0, 0.001),
]

LIDAR_MOUNT_FIELDS = [
    ("mount_x", "X (m)", -1.0, 1.0, 0.001),
    ("mount_y", "Y (m)", -1.0, 1.0, 0.001),
    ("mount_z", "Z (m)", -1.0, 1.0, 0.001),
    ("mount_roll", "Roll (rad)", -math.pi * 2, math.pi * 2, 0.01),
    ("mount_pitch", "Pitch (rad)", -math.pi * 2, math.pi * 2, 0.01),
    ("mount_yaw", "Yaw (rad)", -math.pi * 2, math.pi * 2, 0.01),
]

LIDAR_LASER_FIELDS = [
    ("laser_x", "X (m)", -1.0, 1.0, 0.001),
    ("laser_y", "Y (m)", -1.0, 1.0, 0.001),
    ("laser_z", "Z (m)", -1.0, 1.0, 0.001),
    ("laser_roll", "Roll (rad)", -math.pi * 2, math.pi * 2, 0.01),
    ("laser_pitch", "Pitch (rad)", -math.pi * 2, math.pi * 2, 0.01),
    ("laser_yaw", "Yaw (rad)", -math.pi * 2, math.pi * 2, 0.01),
]


def load_yaml() -> dict:
    if not YAML_PATH.exists():
        return {k: dict(v) for k, v in DEFAULTS.items()}
    with YAML_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    merged = {k: dict(v) for k, v in DEFAULTS.items()}
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


class TunerWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Vic Pinky URDF Tuner")
        self.resize(620, 900)

        self._spins: dict[tuple[str, str], QDoubleSpinBox] = {}
        self._suspend_change = False
        self._rviz_proc: subprocess.Popen | None = None

        central = QWidget()
        outer = QVBoxLayout(central)

        title = QLabel("Vic Pinky URDF Tuner")
        title.setFont(QFont("", 14, QFont.Bold))
        outer.addWidget(title)

        path_label = QLabel(f"YAML: {YAML_PATH}")
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path_label.setWordWrap(True)
        outer.addWidget(path_label)

        warn = QLabel(
            "ℹ️ wheel.radius / separation 은 URDF 시각/TF + bringup.py odom 양쪽\n"
            "    모두에 반영됩니다 (bringup.py 가 같은 YAML 을 read).\n"
            "    실 로봇 적용은 colcon build + 노드 재시작 필요."
        )
        warn.setStyleSheet(
            "background-color: #e3f2fd; color: #0d47a1;"
            " border: 1px solid #1976d2; padding: 8px; border-radius: 4px;"
        )
        warn.setWordWrap(True)
        outer.addWidget(warn)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_inner = QWidget()
        sections = QVBoxLayout(scroll_inner)

        sections.addWidget(self._build_group("🛞 Wheel", "wheel", WHEEL_FIELDS))
        sections.addWidget(self._build_group("📡 LIDAR mount", "lidar", LIDAR_MOUNT_FIELDS))
        sections.addWidget(self._build_group("📡 LIDAR laser", "lidar", LIDAR_LASER_FIELDS))
        sections.addWidget(self._build_calibration_group())
        sections.addWidget(self._build_rviz_group())
        sections.addStretch(1)

        scroll.setWidget(scroll_inner)
        outer.addWidget(scroll, stretch=1)

        button_row = QHBoxLayout()
        self.save_btn = QPushButton("💾 Save")
        self.save_btn.clicked.connect(self.on_save)
        self.reset_btn = QPushButton("Reset to Default")
        self.reset_btn.clicked.connect(self.on_reset)
        self.reload_btn = QPushButton("Reload from YAML")
        self.reload_btn.clicked.connect(self.on_reload)
        button_row.addWidget(self.save_btn)
        button_row.addWidget(self.reset_btn)
        button_row.addWidget(self.reload_btn)
        outer.addLayout(button_row)

        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.status_label)

        self.setCentralWidget(central)

        self._load_into_ui(load_yaml())
        self._set_status_saved()

    def _build_group(self, title: str, section: str, fields: list[tuple]) -> QGroupBox:
        group = QGroupBox(title)
        form = QFormLayout(group)
        for key, label, low, high, step in fields:
            spin = QDoubleSpinBox()
            spin.setDecimals(6)
            spin.setRange(low, high)
            spin.setSingleStep(step)
            spin.valueChanged.connect(self._on_value_changed)
            self._spins[(section, key)] = spin
            form.addRow(label, spin)
        return group

    def _build_calibration_group(self) -> QGroupBox:
        group = QGroupBox("🧪 Calibration helpers (실측 → 자동 보정)")
        outer = QVBoxLayout(group)

        # --- Linear (wheel.radius) ---
        linear_box = QGroupBox("Wheel radius — straight-line test")
        linear = QFormLayout(linear_box)

        self.lin_cmd = QDoubleSpinBox()
        self.lin_cmd.setDecimals(3); self.lin_cmd.setRange(0.01, 100.0); self.lin_cmd.setValue(1.0)
        self.lin_cmd.setSingleStep(0.1); self.lin_cmd.setSuffix(" m")
        linear.addRow("Commanded distance:", self.lin_cmd)

        self.lin_meas = QDoubleSpinBox()
        self.lin_meas.setDecimals(3); self.lin_meas.setRange(0.001, 100.0); self.lin_meas.setValue(1.0)
        self.lin_meas.setSingleStep(0.01); self.lin_meas.setSuffix(" m")
        linear.addRow("Measured distance:", self.lin_meas)

        self.lin_preview = QLabel("")
        linear.addRow(self.lin_preview)

        lin_apply = QPushButton("Apply to wheel.radius")
        lin_apply.clicked.connect(self.on_calib_radius)
        linear.addRow(lin_apply)

        self.lin_cmd.valueChanged.connect(self._update_calib_previews)
        self.lin_meas.valueChanged.connect(self._update_calib_previews)
        outer.addWidget(linear_box)

        # --- Angular (wheel.separation) ---
        ang_box = QGroupBox("Wheel separation — rotation test")
        ang = QFormLayout(ang_box)

        self.ang_cmd = QDoubleSpinBox()
        self.ang_cmd.setDecimals(2); self.ang_cmd.setRange(1.0, 10000.0); self.ang_cmd.setValue(360.0)
        self.ang_cmd.setSingleStep(10.0); self.ang_cmd.setSuffix(" °")
        ang.addRow("Commanded rotation:", self.ang_cmd)

        self.ang_meas = QDoubleSpinBox()
        self.ang_meas.setDecimals(2); self.ang_meas.setRange(0.1, 10000.0); self.ang_meas.setValue(360.0)
        self.ang_meas.setSingleStep(1.0); self.ang_meas.setSuffix(" °")
        ang.addRow("Measured rotation:", self.ang_meas)

        self.ang_preview = QLabel("")
        ang.addRow(self.ang_preview)

        ang_apply = QPushButton("Apply to wheel.separation")
        ang_apply.clicked.connect(self.on_calib_separation)
        ang.addRow(ang_apply)

        self.ang_cmd.valueChanged.connect(self._update_calib_previews)
        self.ang_meas.valueChanged.connect(self._update_calib_previews)
        outer.addWidget(ang_box)

        note = QLabel(
            "절차: 1m 직진 명령 후 실측 → 위 박스. 360° 회전 명령 후 실측 → 아래 박스.\n"
            "Apply 누르면 슬라이더 값이 갱신되고 '저장 안 됨' 상태가 됨. Save 로 YAML 반영."
        )
        note.setStyleSheet("color: #555; font-size: 11px;")
        note.setWordWrap(True)
        outer.addWidget(note)

        return group

    def _build_rviz_group(self) -> QGroupBox:
        group = QGroupBox("🖥️  RViz live preview")
        v = QVBoxLayout(group)

        row = QHBoxLayout()
        self.rviz_start_btn = QPushButton("🚀 Start RViz")
        self.rviz_start_btn.clicked.connect(self.on_rviz_start)
        self.rviz_stop_btn = QPushButton("🛑 Stop RViz")
        self.rviz_stop_btn.clicked.connect(self.on_rviz_stop)
        self.rviz_stop_btn.setEnabled(False)
        row.addWidget(self.rviz_start_btn)
        row.addWidget(self.rviz_stop_btn)
        v.addLayout(row)

        self.rviz_autoreload = QCheckBox("Save 시 자동 재시작 (URDF 즉시 반영)")
        self.rviz_autoreload.setChecked(True)
        v.addWidget(self.rviz_autoreload)

        self.rviz_status = QLabel("⏸  RViz 미실행")
        self.rviz_status.setStyleSheet("color: #666;")
        v.addWidget(self.rviz_status)

        info = QLabel(
            f"launch: ros2 launch vicpinky_description display.launch.xml\n"
            f"ws: {WS_ROOT}\n"
            f"※ ROS 환경 (source /opt/ros/<distro>/setup.bash + ws install) 이\n"
            f"   부모 셸에 source 된 상태에서 GUI 를 실행해야 합니다."
        )
        info.setStyleSheet("color: #555; font-size: 11px;")
        info.setWordWrap(True)
        v.addWidget(info)

        QTimer.singleShot(0, self._update_calib_previews)
        return group

    def _load_into_ui(self, data: dict) -> None:
        self._suspend_change = True
        try:
            for (section, key), spin in self._spins.items():
                val = data.get(section, {}).get(key, DEFAULTS[section][key])
                spin.setValue(float(val))
        finally:
            self._suspend_change = False
        self._update_calib_previews()

    def _collect_from_ui(self) -> dict:
        out: dict = {"wheel": {}, "lidar": {}}
        for (section, key), spin in self._spins.items():
            out[section][key] = spin.value()
        return out

    def _on_value_changed(self, _val: float) -> None:
        if self._suspend_change:
            return
        self._set_status_dirty()
        self._update_calib_previews()

    def _set_status_dirty(self) -> None:
        self.status_label.setText("● 저장 안 됨")
        self.status_label.setStyleSheet("color: #c62828; font-weight: bold;")

    def _set_status_saved(self) -> None:
        self.status_label.setText("✓ 저장됨")
        self.status_label.setStyleSheet("color: #2e7d32; font-weight: bold;")

    # ------------------------------------------------------------------
    # Calibration helpers

    def _update_calib_previews(self) -> None:
        cur_r = self._spins[("wheel", "radius")].value()
        cur_s = self._spins[("wheel", "separation")].value()
        new_r = self._calc_new_radius(cur_r)
        new_s = self._calc_new_separation(cur_s)
        if hasattr(self, "lin_preview"):
            self.lin_preview.setText(
                f"  → wheel.radius:     {cur_r:.6f}  →  {new_r:.6f}  m"
            )
        if hasattr(self, "ang_preview"):
            self.ang_preview.setText(
                f"  → wheel.separation: {cur_s:.6f}  →  {new_s:.6f}  m"
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
        new_val = self._calc_new_radius(spin.value())
        if not (spin.minimum() <= new_val <= spin.maximum()):
            QMessageBox.warning(
                self, "Out of range",
                f"새 값 {new_val:.6f} 이 허용 범위를 벗어납니다.",
            )
            return
        spin.setValue(new_val)
        self._set_status_dirty()

    def on_calib_separation(self) -> None:
        spin = self._spins[("wheel", "separation")]
        new_val = self._calc_new_separation(spin.value())
        if not (spin.minimum() <= new_val <= spin.maximum()):
            QMessageBox.warning(
                self, "Out of range",
                f"새 값 {new_val:.6f} 이 허용 범위를 벗어납니다.",
            )
            return
        spin.setValue(new_val)
        self._set_status_dirty()

    # ------------------------------------------------------------------
    # Save / reset / reload

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
        reply = QMessageBox.question(
            self,
            "Reset to Default",
            "슬라이더와 YAML 을 DEFAULTS 로 복원합니다. 계속할까요?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        defaults = {k: dict(v) for k, v in DEFAULTS.items()}
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

    # ------------------------------------------------------------------
    # RViz preview

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
        cmd = (
            f"source '{ws_setup}' && "
            f"exec ros2 launch vicpinky_description display.launch.xml"
        )
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
        self.rviz_status.setText("▶ RViz 실행 중")
        self.rviz_status.setStyleSheet("color: #2e7d32; font-weight: bold;")

    def on_rviz_stop(self) -> None:
        self._kill_rviz()
        self.rviz_start_btn.setEnabled(True)
        self.rviz_stop_btn.setEnabled(False)
        self.rviz_status.setText("⏸  RViz 미실행")
        self.rviz_status.setStyleSheet("color: #666;")

    def _restart_rviz(self) -> None:
        self._kill_rviz()
        try:
            self._spawn_rviz()
            self.rviz_status.setText("▶ RViz 재시작됨 (새 URDF 반영)")
            self.rviz_status.setStyleSheet("color: #2e7d32; font-weight: bold;")
        except OSError as e:
            QMessageBox.critical(self, "RViz restart failed", str(e))
            self.rviz_start_btn.setEnabled(True)
            self.rviz_stop_btn.setEnabled(False)
            self.rviz_status.setText("⏸  RViz 미실행 (재시작 실패)")
            self.rviz_status.setStyleSheet("color: #c62828;")

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._kill_rviz()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    win = TunerWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
