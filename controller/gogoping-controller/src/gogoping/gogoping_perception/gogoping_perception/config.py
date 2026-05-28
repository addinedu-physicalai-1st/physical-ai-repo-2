"""gogoping_perception 튜닝 상수.

YOLO + ByteTrack + ReID 의 하이퍼파라미터를 한 곳에 모음. follow_node 의
control 상수 (CMD_VEL_HZ 등) 와는 분리.
"""

# ---------- YOLO ----------
# yolov8s (~21.5M params) → yolov8n (~3.2M params) — 추론 빠름, 단일 클래스(person)
# 근거리 추종이라 mAP 차이 거의 무영향. 속도/지연 테스트용.
YOLO_MODEL_NAME = "yolov8n.pt"
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
REID_SIM_THRESHOLD = 0.55
# Asymmetric hysteresis — track_id 유지 분기에서 sim 이 이 값 아래로 떨어지면
# 잘못 lock 된 것으로 보고 해제 → drift 분기에서 LOCK 임계값(0.7) 으로 재매칭.
# 0.30 = 정상 자세 변동(0.4~0.5)은 통과, 다른 사람으로 ID 가 바뀐 경우(보통 < 0.3) 만 해제.
REID_SIM_UNLOCK_THRESHOLD = 0.30
# drift 재매칭 시 후보의 distance 가 마지막 target distance 에서 이 값 이상 떨어져
# 있으면 거부 (다른 거리의 사람이 sim 만 우연히 높은 경우 차단). 0 = depth 비활성.
# 5Hz publish 기준 1.0m 점프 → 5m/s — 일반 보행 1.5m/s 의 3배. 보수적 마진.
REID_MAX_DISTANCE_JUMP_MM = 1000

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
# 가까이 추종 (FOLLOW_DISTANCE_M=0.5m) 의 stop 임계값 — follow goal 보다 작아야
# robot 이 사람에 도달 가능. follow=500, safety=400 으로 100mm 마진 확보.
SAFE_DISTANCE_MM = 300   # FOLLOW_DISTANCE_MIN_M(0.35) 보다 작아야 follow STOP 이 먼저 동작.
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
