"""gogoping_follow 튜닝 상수 — Nav2 통합."""

# ---------- Follow geometry ----------
FOLLOW_DISTANCE_M = 1.0         # target 뒤 goal 거리 (한 걸음 반 = 안전거리)
GOAL_CHANGE_THRESHOLD_M = 0.3   # 이전 goal 과 이 거리 이상 차이날 때만 새 goal — Nav2 reissue spam 회피

# ---------- Hybrid mode thresholds (distance-based, with hysteresis) ----------
# distance_m 으로 STOP / REACTIVE / NAV2 결정. hysteresis 로 mode flapping 방지.
# 영역: <stop_max=STOP / stop_max~reactive_max=REACTIVE / >nav2_min=NAV2.
STOP_MAX_DISTANCE_M     = 0.9   # 이 미만이면 STOP (안전거리)
REACTIVE_MAX_DISTANCE_M = 1.7   # REACTIVE → NAV2 hysteresis 상단
NAV2_MIN_DISTANCE_M     = 1.2   # NAV2 → REACTIVE hysteresis 하단
INITIAL_MODE_THRESHOLD_M = 1.4  # IDLE/STOP → ACTIVE 진입 시 REACTIVE/NAV2 분기

# EMA filter alpha — angle_deg jitter 가 estimate_follow_goal 의 atan2(dy,dx)
# 진동으로 amplify 되는 것을 smoothing 으로 억제. 0.15 ≈ 5Hz → 1.4s 시정수.
TRACKING_STATE_EMA_ALPHA = 0.15

# ---------- REACTIVE mode P-control (moca-style) ----------
# distance / angle error 로부터 cmd_vel 직접 계산 (Nav2 거치지 않음).
REACTIVE_KP_LIN              = 0.5    # m/s per m
REACTIVE_KP_ANG              = 0.6    # rad/s per rad
REACTIVE_MAX_LIN             = 0.3    # m/s
REACTIVE_MAX_ANG             = 0.4    # rad/s — doorway sharp turn 보수적
REACTIVE_DIST_DEADBAND_M     = 0.05
REACTIVE_ANGLE_DEADBAND_DEG  = 5.0
CMD_VEL_RAW_TOPIC = "/gogoping/cmd_vel_raw"  # safety_filter input

# ---------- LiDAR fusion ----------
LIDAR_BEARING_WINDOW_DEG = 5.0  # bbox bearing ± 이 각도 의 LiDAR 빔 평균
LIDAR_MAX_M = 8.0
# LiDAR 가 robot 에 180° 회전 장착 (vicpinky_description robot_dims.yaml laser_yaw=π).
# scan angle 0° = 물리 후면. 카메라 bearing (base_link, 0=정면) 으로 조회 시 이 offset 더함.
LIDAR_YAW_OFFSET_RAD = 3.14159265358979

# ---------- Control loop ----------
NAV2_GOAL_HZ = 2.0
STATE_STALE_TIMEOUT_S = 5.0   # tracking_state 가 이 시간 안 오면 lost

# ---------- Frame names ----------
MAP_FRAME = "map"
BASE_FRAME = "base_link"

# ---------- Close-Follow (doorway 통과 시 거리 단축, 현재 비활성) ----------
# vertex 이름에 "입구"/"출입구" 포함 시 doorway 로 판정 (waypoints.yaml).
# trigger_dist 0 으로 비활성화 — lost 예방은 RECOVERY + voice-guided 가 담당.
FOLLOW_DISTANCE_CLOSE_M     = 0.35
STOP_MAX_CLOSE_M            = 0.25
CLOSE_TRIGGER_DIST_M        = 0.0   # 0 = close 비활성화
CLOSE_RELEASE_DIST_M        = 2.0
CLOSE_ANGLE_STABLE_DEG      = 15.0
CLOSE_ANGLE_STABLE_S        = 1.0

# ---------- Recovery (자동 회복) ----------
# tracking 잃은 후 RECOVERY_LOST_TIMEOUT_S 지속되면 RECOVERY 진입.
# Phase A (FULL_SWEEP, PAN 30°↔150°) → Phase B (본체 25° 회전, PAN 마지막 위치 쪽)
# → Phase C (NARROW_SWEEP, PAN 15°↔165°). B/C 반복, 본체 누적 ≥ 360° → WAITING_HINT.
RECOVERY_LOST_TIMEOUT_S        = 4.0   # ReID jitter 흡수 (짧은 lost 무시)
RECOVERY_PAN_RATE_DEG_S        = 10.0
RECOVERY_DWELL_S               = 1.5   # legacy graph 모드 — 미사용
RECOVERY_HINT_DWELL_S          = 2.5
RECOVERY_MAX_CANDIDATE_DIST_M  = 5.0   # legacy graph 모드 — 미사용
RECOVERY_PAN_MIN_DEG           = 5.0
RECOVERY_PAN_MAX_DEG           = 175.0
RECOVERY_PAN_CENTER_DEG        = 90.0
RECOVERY_PAN_LEFT_DEG          = 150.0  # WAITING_HINT "왼쪽" hint 응답
RECOVERY_PAN_RIGHT_DEG         = 30.0   # WAITING_HINT "오른쪽" hint 응답
RECOVERY_PAN_FRONT_DEG         = 90.0   # WAITING_HINT "앞" hint 응답
HINT_BACK_TURN_RATE_RAD_S      = 0.6

# Chassis 회전 비대칭 보정 — 같은 angular.z 명령에 우회전(CW)이 좌회전(CCW)보다
# 더 큰 응답. 우회전 명령을 줄여 좌/우 회전량을 같게 맞춤. 1.0 = 보정 없음.
# RECOVERY BODY_TURN / VOICE_RESUME / HINT back 모든 본체 회전에 적용.
CHASSIS_TURN_SCALE_LEFT  = 1.0
CHASSIS_TURN_SCALE_RIGHT = 0.7

# Body-search Phase A/B/C state machine 상수.
RECOVERY_FULL_PAN_LEFT_DEG     = 150.0
RECOVERY_FULL_PAN_RIGHT_DEG    = 30.0
RECOVERY_NARROW_PAN_HALF_DEG   = 75.0   # PAN_FRONT 기준 ±. 15°↔165° (거의 풀 sweep)
RECOVERY_BODY_TURN_DEG         = 25.0
RECOVERY_BODY_TURN_RATE_RAD_S  = 0.6
RECOVERY_BODY_MAX_TOTAL_DEG    = 360.0  # 누적 ≥ 이 값 → WAITING_HINT

# ---------- Topics (Recovery) ----------
HINT_TOPIC                     = "/gogoping/follow_hint"
PAN_CMD_TOPIC                  = "/servo_bridge/cmd_pan"

# ---------- Voice-Guided Search (운영자 음성 보조) ----------
# "고고핑 추종 위치확인" → VOICE_SEARCH, "고고핑 추종 위치이동" → VOICE_RESUME.
VOICE_SEARCH_PAN_RATE_DEG_S    = 10.0
VOICE_SEARCH_PAN_LEFT_DEG      = 5.0
VOICE_SEARCH_PAN_RIGHT_DEG     = 175.0
VOICE_SEARCH_PAN_HOME_DEG      = 90.0
VOICE_FOUND_TIMEOUT_S          = 60.0
VOICE_RESUME_TURN_RATE_RAD_S   = 0.6
VOICE_TILT_HOME_DEG            = 90.0   # VOICE_RESUME 끝에 TILT home (정면 수평)
FOLLOW_STATE_TOPIC             = "/gogoping/follow_state"
TILT_CMD_TOPIC                 = "/servo_bridge/cmd_tilt"
