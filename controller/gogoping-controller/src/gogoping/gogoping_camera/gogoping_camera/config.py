"""gogoping_camera D435 + WebRTC 파라미터.

캡처 해상도와 다운스케일/NVENC 파라미터는 한 곳에서 관리. ROS parameter 로
override 가능하도록 webrtc_node 에서 declare_parameter() 로 노출 예정.
"""
from __future__ import annotations

# ── D435 캡처 ────────────────────────────────────────────────────────────────
CAMERA_COLOR_W = 1920
CAMERA_COLOR_H = 1080
CAMERA_COLOR_FPS = 30
CAMERA_DEPTH_W = 848    # D435 IR native sweet spot
CAMERA_DEPTH_H = 480
CAMERA_DEPTH_FPS = 30

# ── perception 다운스케일 ────────────────────────────────────────────────────
PERCEPTION_PRESETS = {
    "fast":     {"downscale": (640, 480),  "imgsz": 640},
    "balanced": {"downscale": (960, 540),  "imgsz": 960},
    "accurate": {"downscale": (1280, 720), "imgsz": 1280},
}
ACTIVE_PRESET = "fast"

# ── NVENC H.264 ──────────────────────────────────────────────────────────────
# robot-web (LAN P2P, MediaRelay smoothing 없음) 깜빡임 방지 — bitrate burst 줄이고
# 키프레임 주기 짧게 (loss 발생해도 다음 keyframe 까지 회복 시간 단축).
H264_BITRATE = 2_000_000          # 2 Mbps
H264_BITRATE_MAX = 3_000_000
H264_GOP_SIZE = 5                 # 키프레임 0.17초 (30fps) — 손실 회복 빠르게
H264_PRESET = "p4"                # NVENC preset (p1 fastest .. p7 quality)
H264_TUNE = "ll"                  # low latency
H264_RC = "cbr"
H264_BF = 0                       # B-frame 비활성 (latency 우선)
H264_PROFILE = "main"

# ── Signaling ────────────────────────────────────────────────────────────────
SIGNALING_URL = "ws://localhost:8100/ws/webrtc/signaling"
SIGNALING_PEER_ROLE = "producer"
SIGNALING_PEER_ID = "gogoping"
