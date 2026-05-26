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

# ---------- Perception presets ----------
# perception 다운스케일/imgsz — gogoping_camera.config.PERCEPTION_PRESETS 와 동기.
# 별 import 대신 명시 (camera 패키지가 perception 에 의존 X 원칙).
PERCEPTION_PRESETS = {
    "fast":     {"downscale": (640, 480),  "imgsz": 640},
    "balanced": {"downscale": (960, 540),  "imgsz": 960},
    "accurate": {"downscale": (1280, 720), "imgsz": 1280},
}
ACTIVE_PRESET = "fast"

# ---------- Depth fusion ----------
# bbox 중심의 depth 거리 측정 — 픽셀 한 점이 아니라 작은 patch 의 median 사용
DEPTH_PATCH_SIZE = 5   # 5×5 patch 중심에서 median
DEPTH_MIN_MM = 200     # 20cm — 너무 가까우면 노이즈
DEPTH_MAX_MM = 8000    # 8m — D435 spec 한계

# ---------- ReID enrollment (depth-aware auto-enroll) ----------
# 추종 시작 후 body embedding 누적 frame 수. 0.5s @ 30fps.
ENROLLMENT_N_FRAMES = 15
# enrollment timeout — 이 시간 안에 N 미달이라도 모인 만큼 평균 후 ACTIVE 전이.
ENROLLMENT_TIMEOUT_S = 3.0
# 첫 frame face matching cosine sim threshold — control-service 의 face_match_threshold 와 동일.
ENROLLMENT_FACE_THRESHOLD = 0.6
# face matching retry 최대 frame 수 — 그 후 fallback to "가장 큰 bbox" 1회 시도.
ENROLLMENT_FACE_RETRY_FRAMES = 5

# ---------- Depth-aware mask ----------
# bbox 내 depth median 기준 ±tolerance mm pixel 만 살림 (배경 제거).
DEPTH_MASK_TOLERANCE_MM = 200
# valid pixel 비율 — 이 미만이면 mask 안 씌우고 full bbox 사용 (fallback).
DEPTH_MASK_MIN_VALID_RATIO = 0.3

# ---------- Safety monitor (depth-based) ----------
# 사람과 최소 안전 거리. tracking_state.distance_mm 가 이 값 미만이면 stop.
# 개발 테스트용 — 1m 는 실내에서 너무 잦게 trigger 되어 70cm 로 좁힘. 실 운영 시 1m 검토.
SAFE_DISTANCE_MM = 700
# 사람 외 obstacle 거리 threshold (ROI 안 pixel 의 depth).
OBSTACLE_THRESHOLD_MM = 500
# OBSTACLE_THRESHOLD_MM 미만 pixel 의 최소 개수 — 이상이면 stop. false positive 방지.
OBSTACLE_MIN_PIXELS = 1000
# ROI: 화면 하단 60% 만 obstacle 검사 (천장/벽 무시). 0.0~1.0 (y 시작 비율).
OBSTACLE_ROI_TOP_RATIO = 0.4   # 화면 위 40% 무시 (= 하단 60%)
# safety publish rate (Hz).
SAFETY_PUBLISH_HZ = 10
# 한 번 stop trigger 후 hold 시간 (초) — chatter 방지.
SAFETY_CHATTER_HOLD_S = 1.0
# safety_filter 의 cmd_vel_raw 미수신 timeout (초) — 이상 시 zero publish (stale 방지).
SAFETY_STALE_TIMEOUT_S = 0.5
# safety 가 bypass 되는 FSM state (대소문자 매칭). "MANUAL" 일 때 항상 False.
SAFETY_BYPASS_STATES = ["MANUAL"]
