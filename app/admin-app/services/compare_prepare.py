"""Background preparation for admin compare playback (off GUI thread)."""

from __future__ import annotations

import json
from typing import Any

from PyQt5.QtCore import QThread, pyqtSignal


class ComparePrepareThread(QThread):
    """Load dense recording + serialize compare payload without blocking Qt."""

    finished_ok = pyqtSignal(dict, str)
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        recording_path: str,
        display_name: str,
        limits_before: dict[str, dict[str, float]],
        limits_after: dict[str, dict[str, float]],
        *,
        frame_hz: float = 20.0,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._path = recording_path
        self._display_name = display_name
        self._limits_before = limits_before
        self._limits_after = limits_after
        self._frame_hz = frame_hz

    def run(self) -> None:
        try:
            from services.routine_playback import load_recording_dense

            recording = load_recording_dense(self._path, hz=self._frame_hz)
            if recording is None:
                self.finished_err.emit("녹화 로드 실패")
                return
            recording["name"] = self._display_name
            payload = {
                "recording": recording,
                "limits_before": self._limits_before,
                "limits_after": self._limits_after,
            }
            payload_json = json.dumps(payload, separators=(",", ":"))
            self.finished_ok.emit(payload, payload_json)
        except Exception as e:  # noqa: BLE001
            self.finished_err.emit(f"{e!r}")
