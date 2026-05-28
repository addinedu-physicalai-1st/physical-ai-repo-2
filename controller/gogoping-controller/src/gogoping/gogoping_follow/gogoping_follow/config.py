"""gogoping_follow 튜닝 상수 — Nav2 통합."""

# ---------- Follow geometry ----------
FOLLOW_DISTANCE_M = 0.5         # target 의 뒤 몇 m 지점을 goal 로 삼나
GOAL_CHANGE_THRESHOLD_M = 0.3   # 이전 goal 과 이 거리 이상 차이날 때만 새 goal — Nav2 reissue spam 회피

# ---------- Hybrid mode thresholds (distance-based, with hysteresis) ----------
# distance_m 으로 STOP / REACTIVE / NAV2 결정. hysteresis 로 mode flapping 방지.
# REACTIVE 영역 < stop_max 면 STOP, stop_max~reactive_max REACTIVE, nav2_min~∞ NAV2.
STOP_MAX_DISTANCE_M     = 0.45  # 이 미만이면 STOP
REACTIVE_MAX_DISTANCE_M = 1.2   # REACTIVE → NAV2 hysteresis 상단
NAV2_MIN_DISTANCE_M     = 0.8   # NAV2 → REACTIVE hysteresis 하단
INITIAL_MODE_THRESHOLD_M = 1.0  # IDLE/STOP → ACTIVE 진입 시 REACTIVE/NAV2 갈림길

# EMA filter alpha — 작을수록 부드러움. 0.15 = 약 7 sample 시정수 (5 Hz → ~1.4s).
# angle_deg jitter 가 estimate_follow_goal 의 dy 를 흔들고 그게 goal orientation
# atan2(dy, dx) 진동으로 amplify 되는 것을 smoothing 으로 억제.
TRACKING_STATE_EMA_ALPHA = 0.15

# ---------- Phase C — REACTIVE mode P-control (moca-style) ----------
# distance / angle error 로부터 cmd_vel 직접 계산 (Nav2 거치지 않음).
# moca 의 follow_controller_node.py 의 P 제어 + deadband 패턴.
REACTIVE_KP_LIN              = 0.5    # m/s per (m of distance error)
REACTIVE_KP_ANG              = 0.6    # rad/s per (radian of angle error)
REACTIVE_MAX_LIN             = 0.3    # m/s — 추종 전진 속도 상한
REACTIVE_MAX_ANG             = 0.4    # rad/s — 회전 속도 상한 (doorway sharp turn 보수적)
REACTIVE_DIST_DEADBAND_M     = 0.05   # ±5cm 안 → linear 0
REACTIVE_ANGLE_DEADBAND_DEG  = 5.0    # ±5° 안 → angular 0
CMD_VEL_RAW_TOPIC = "/gogoping/cmd_vel_raw"  # safety_filter input

# ---------- LiDAR fusion ----------
LIDAR_BEARING_WINDOW_DEG = 5.0  # bbox bearing ±이 각도 의 LiDAR 빔 평균
LIDAR_MAX_M = 8.0               # 이 이상이면 측정 신뢰 안 함
# LiDAR 가 로봇에 180° 회전 장착 (vicpinky_description robot_dims.yaml laser_yaw=π).
# scan angle 0° = 물리 후면. estimate_follow_goal 이 scan 을 TF 안 거치고 직접
# 인덱싱하므로, 카메라 bearing(=base_link, 0=정면) 으로 LiDAR 조회 시 이 offset 을
# 더해 실제 빔 방향으로 보정. (실측 확인: 물리 정면 open → scan 180° 분면이 열림)
LIDAR_YAW_OFFSET_RAD = 3.14159265358979  # π — laser_link 가 base_link 대비 180° yaw

# ---------- Control loop ----------
NAV2_GOAL_HZ = 2.0            # control loop 주기 — Nav2 액션 reissue 검사
STATE_STALE_TIMEOUT_S = 5.0   # /gogoping/tracking_state 가 이 시간 안 오면 lost

# ---------- frame names ----------
MAP_FRAME = "map"
BASE_FRAME = "base_link"

# ---------- Phase D — Close-Follow (lost 예방) ----------
# doorway vertex 근처에서 추종 거리를 일시 단축 → 사용자가 문 통과 시 시야 이탈 방지.
# vertex 이름에 "입구" 또는 "출입구" 포함 시 doorway 로 판정 (waypoints.yaml).
FOLLOW_DISTANCE_CLOSE_M     = 0.35  # close 모드 시 추종 거리
STOP_MAX_CLOSE_M            = 0.25  # close 모드 시 STOP 임계 (안전 가드 동기 조정)
CLOSE_TRIGGER_DIST_M        = 1.5   # robot ↔ doorway vertex < 이 거리 → close ON
CLOSE_RELEASE_DIST_M        = 2.0   # > 이 거리 → close OFF (hysteresis)
CLOSE_ANGLE_STABLE_DEG      = 15.0  # |angle_deg| < 이 값 일 때 안정
CLOSE_ANGLE_STABLE_S        = 1.0   # 안정 지속 시간 (OFF 조건)

# ---------- Phase E — Recovery (자동 회복) ----------
# tracking 잃은 후 RECOVERY_LOST_TIMEOUT_S 지속되면 RECOVERY 진입.
# graph adjacency 로 인접 vertex 들 후보 → 각 방향 PAN 슬로우 스캔 → perception lock 시도.
RECOVERY_LOST_TIMEOUT_S        = 2.0   # tracking 잃은 후 RECOVERY 진입 임계
RECOVERY_PAN_RATE_DEG_S        = 10.0  # 슬로우 sweep 속도
RECOVERY_DWELL_S               = 1.5   # graph 후보 dwell
RECOVERY_HINT_DWELL_S          = 2.5   # hint 후 dwell (조금 더 길게)
RECOVERY_MAX_CANDIDATE_DIST_M  = 5.0   # 후보 vertex 최대 거리
RECOVERY_PAN_MIN_DEG           = 5.0
RECOVERY_PAN_MAX_DEG           = 175.0
RECOVERY_PAN_CENTER_DEG        = 90.0
RECOVERY_PAN_LEFT_DEG          = 150.0
RECOVERY_PAN_RIGHT_DEG         = 30.0
RECOVERY_PAN_FRONT_DEG         = 90.0
HINT_BACK_TURN_RATE_RAD_S      = 0.6   # "back" hint 시 base 180° 회전 속도

# ---------- Topics (Recovery) ----------
HINT_TOPIC                     = "/gogoping/follow_hint"
PAN_CMD_TOPIC                  = "/servo_bridge/cmd_pan"
