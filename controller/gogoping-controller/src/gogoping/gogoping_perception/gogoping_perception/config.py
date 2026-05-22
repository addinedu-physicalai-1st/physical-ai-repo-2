"""gogoping_perception 튜닝 상수.

YOLO + ByteTrack + ReID 의 하이퍼파라미터를 한 곳에 모음. follow_node 의
control 상수 (CMD_VEL_HZ 등) 와는 분리.
"""

# ---------- YOLO ----------
YOLO_MODEL_NAME = "yolov8s.pt"
# 시연 친화적 낮은 임계값 — 상반신/부분 frame 도 검출. 후속에서 카메라 환경에 맞춰 튜닝.
YOLO_CONF_THRESHOLD = 0.20
YOLO_PERSON_CLASS = 0  # COCO class id
YOLO_IMG_SIZE = 640
# device=None → ultralytics 자동 (cuda 0 우선 → cpu fallback)
YOLO_DEVICE: str | None = None

# ---------- ByteTrack ----------
# ultralytics 내장 yaml. custom 튜닝 필요 시 패키지 share 로 옮긴 뒤 절대경로.
TRACKER_NAME = "bytetrack.yaml"

# ---------- ReID ----------
# track_id 유지 시 ReID skip. drift 후 재매칭 시에만 비교.
# 단일 사용자 시연 환경 — InsightFace face embedding 과 OSNet body embedding 의 cross-modal
# 한계 회피용 낮은 임계값. 갤러리 정책 개선 후 0.5~0.7 권장.
REID_SIM_THRESHOLD = 0.0

# ---------- Publish ----------
TRACKING_STATE_HZ = 5
LOST_TIMEOUT_S = 5.0  # last successful track 이후 이 시간 지나면 mode="lost"

# ---------- WS video client ----------
# control-service streaming gateway 의 /ws/video-stream.
# ROS DDS 의 image topic multicast 대신 단일 TCP connection 으로 영상 수신
# (공유 LAN 환경에서 다른 팀에 부하 끼치지 않기 위함).
WS_VIDEO_URL = "ws://localhost:8100/ws/video-stream"
WS_CLIENT_ID = "perception-gogoping"
WS_CLIENT_KIND = "service"
WS_SUBSCRIBE_ROBOT = "gogoping"
WS_SUBSCRIBE_STREAM = 0
WS_RECONNECT_DELAY_S = 2.0
