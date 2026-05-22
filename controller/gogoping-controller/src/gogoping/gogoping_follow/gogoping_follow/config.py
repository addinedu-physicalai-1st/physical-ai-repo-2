"""gogoping_follow 튜닝 상수."""

# --- ReID ---
REID_BACKBONE = "osnet_x0_25"
REID_FEATURE_DIM = 512
REID_GALLERY_MAX = 50
REID_AUTO_CALIB_INTERVAL = 30   # frame 마다 갤러리 확장 평가
REID_AUTO_CALIB_THRESH = 0.94   # 코사인 sim 이하 시 새 템플릿 추가
REID_LOCK_FRAMES = 5            # ID 락 안정화 프레임 수

# --- HSV fallback ---
HSV_BINS = (16, 16, 16)         # 16H + 16S + 16V

# --- YOLO detector ---
YOLO_MODEL_NAME = "yolov8s.pt"  # 또는 ncnn 변환본 경로
YOLO_CONF_THRESHOLD = 0.40
YOLO_PERSON_CLASS_ID = 0

# --- P 컨트롤 ---
KP_DIST = 0.003                  # bbox area 기반 linear_x
KP_ANGLE = 0.001                 # bbox center offset 기반 angular_z
TARGET_BBOX_AREA_PX = 360        # 목표 bbox 한 변 (sqrt(area))
ANGLE_DEADZONE_PX = 45           # 카메라 중심 ±45px 안은 회전 안 함

# --- 속도 한계 ---
LINEAR_X_MAX = 0.30              # m/s
ANGULAR_Z_MAX = 0.80             # rad/s

# --- LiDAR clamp ---
LIDAR_HARD_STOP_M = 0.30         # 이하 거리 진입 시 즉시 정지
LIDAR_SLOW_M = 0.60              # 이하 거리에서 linear_x 0.5x

# --- 매칭 loss 처리 ---
LOST_TIMEOUT_S = 5.0             # 시야 로스트 후 searching 진입 전 대기

# --- Publish rate ---
TRACKING_STATE_HZ = 5            # tracking_state publish 주기
CMD_VEL_HZ = 20
