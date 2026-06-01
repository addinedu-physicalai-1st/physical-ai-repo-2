"""gogoping_camera D435 + WebRTC 파라미터.

캡처 해상도와 다운스케일/NVENC 파라미터는 한 곳에서 관리. ROS parameter 로
override 가능하도록 webrtc_node 에서 declare_parameter() 로 노출 예정.
"""
from __future__ import annotations

# ── D435 캡처 ────────────────────────────────────────────────────────────────
# 캡처 해상도를 perception(YOLO) 입력(640×480)에 맞춤 — 다운스케일 resize 가 passthrough 가
# 되고 USB/CPU/NVENC 부하 최소화. perception 은 어차피 640 이라 무영향, WebRTC 시청 화면만 640×480.
# (이전 1080p30 → LiDAR 시리얼 starvation 유발. D435 는 USB3 단독 버스 권장.)
CAMERA_COLOR_W = 640
CAMERA_COLOR_H = 480
CAMERA_COLOR_FPS = 15
CAMERA_DEPTH_W = 640
CAMERA_DEPTH_H = 480
CAMERA_DEPTH_FPS = 15

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
# 640×480@15 에 맞춰 축소 (이전 1080p30 시절 값). WebRTC 시청용 인코딩만 영향 —
# perception/YOLO 는 shm raw frame 을 읽으므로 무관.
H264_BITRATE = 1_000_000          # 1 Mbps (640×480@15 엔 충분)
H264_BITRATE_MAX = 1_500_000
H264_GOP_SIZE = 20                # 키프레임 ~1.3초 (15fps) — bitrate/encode 부하 ↓
H264_PRESET = "p4"                # NVENC preset (p1 fastest .. p7 quality)
H264_TUNE = "ll"                  # low latency
H264_RC = "cbr"
H264_BF = 0                       # B-frame 비활성 (latency 우선)
H264_PROFILE = "main"

# ── Signaling ────────────────────────────────────────────────────────────────
SIGNALING_URL = "ws://localhost:8100/ws/webrtc/signaling"
SIGNALING_PEER_ROLE = "producer"
SIGNALING_PEER_ID = "gogoping"
