"""gogoping_perception 튜닝 상수.

YOLO + ByteTrack + ReID 의 하이퍼파라미터를 한 곳에 모음. follow_node 의
control 상수 (CMD_VEL_HZ 등) 와는 분리.
"""

# ---------- YOLO ----------
# yolov8n (~3.2M params) — 단일 클래스 (person) 근거리 추종이라 mAP 차이 무영향, 속도 우선.
YOLO_MODEL_NAME = "yolov8n.pt"
# 0.40 — 진짜 사람 위주 검출. 상반신/일부 frame 통과, 사물(마네킹/인형 등) 1차 차단.
# 0.5+ 는 멀리/가려진 사람 놓침 위험.
YOLO_CONF_THRESHOLD = 0.40
YOLO_PERSON_CLASS = 0  # COCO class id
YOLO_IMG_SIZE = 640
# device 명시 — None(auto)은 노드 시작 시 CUDA 미준비/VRAM full 이면 조용히 CPU 로
# 폴백한다. CPU 추론은 yolov8n@640 도 ~1.3s/frame(0.8fps)라 proximity 정지가 사실상
# 작동 못 함. "cuda:0" 고정으로 silent fallback 차단 (GPU 부재 시엔 load 에러로 즉시
# 드러나는 편이 0.8fps 로 조용히 도는 것보다 낫다). CPU 강제 디버깅 시에만 "cpu".
YOLO_DEVICE: str | None = "cuda:0"

# ---------- MediaPipe Pose validation (사물 오인식 2차 차단) ----------
# YOLO bbox crop 안에서 Pose 추론 → visible landmark ≥ MIN 이면 사람, 아니면 사물.
# 마네킹/인형/의자 등은 keypoint 거의 안 잡혀 걸러짐. ENABLED=False 면 검증 skip.
POSE_ENABLED = True
POSE_MIN_VISIBLE_LANDMARKS = 5     # 33개 중 (얼굴/어깨 등 상반신 5개)
POSE_VISIBILITY_THRESHOLD  = 0.5   # landmark visibility 점수 임계 (0~1)
POSE_MIN_BBOX_SIDE_PX      = 40    # bbox 너무 작으면 skip (멀리 있는 사람 보호)

# ---------- ByteTrack ----------
# ultralytics 내장 yaml. custom 튜닝 필요 시 패키지 share 로 옮긴 뒤 절대경로.
TRACKER_NAME = "bytetrack.yaml"

# ---------- ReID ----------
# track_id 유지 시 ReID skip, drift 시에만 비교. ByteTrack track_id 가 occlusion/jitter
# 로 자주 바뀌는 환경에서 LOCK 임계 낮춰 matched=false 빈도 줄임 (single-user 시연).
# 갤러리 정책 개선 후 0.5~0.7 권장.
REID_SIM_THRESHOLD = 0.40
# Asymmetric hysteresis — track_id 유지 분기에서 이 값 미만이면 lock 해제 → drift.
# UNLOCK < LOCK 이라 한 번 lock 되면 자세 변동 흡수.
REID_SIM_UNLOCK_THRESHOLD = 0.20
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

# ---------- graph_router 심화 (2026-05-28) ----------
# YOLO 항상 가동시킬 nav 모드들 — IDLE/CHARGING/MANUAL/ERROR 는 OFF.
YOLO_NAV_MODES: tuple[str, ...] = (
    "GOTO", "FOLLOW", "HIDEANDSEEK",
    "RETURNING", "LOW_BATTERY_RETURNING",
    # LULLABY 제외 — 제자리 모드라 proximity 주행정지 무의미, YOLO 불필요 (디버깅 결정)
)
# 정면 박스 (robot frame, m) — graph_router 의 사람 감지 영역
PERSON_FRONT_DIST_M: float = 0.6   # 디버깅값 (사람 0.6m 정지)
PERSON_LATERAL_LIMIT_M: float = 0.5
# 카메라 intrinsic (D435 default — 실측 후 튜닝)
CAMERA_FX_PX: float = 615.0
CAMERA_CX_PX: float = 320.0
# (person-only: 장애물 wall_close / 중앙밴드 obstacle 거리 관련 상수는 제거됨.
#  충돌 안전용 OBSTACLE_THRESHOLD_MM / MIN_PIXELS / ROI_TOP_RATIO 는 evaluate_safety 에서 사용.)
