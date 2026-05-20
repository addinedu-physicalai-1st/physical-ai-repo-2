"""Chromium / Qt WebEngine GPU flags — call before QApplication()."""

from __future__ import annotations

import os
import sys


def apply_chromium_gpu_flags() -> None:
    """Prefer hardware WebGL in QWebEngineView (Linux often defaults to SwiftShader).

    Respects existing QTWEBENGINE_CHROMIUM_FLAGS — only appends missing tokens.
  Set the whole variable yourself to override.
    """
    defaults = [
        "--enable-gpu",
        "--enable-webgl",
        "--ignore-gpu-blocklist",
        "--enable-accelerated-2d-canvas",
        "--disable-software-rasterizer",
    ]
    if sys.platform.startswith("linux"):
        defaults.append("--use-gl=desktop")
    elif sys.platform == "darwin":
        defaults.append("--use-gl=angle")
        defaults.append("--use-angle=metal")

    existing = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").split()
    merged = list(existing)
    for flag in defaults:
        if flag not in merged:
            merged.append(flag)
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(merged)
