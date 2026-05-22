"""gogoping_follow 튜닝 상수 — Nav2 통합."""

# ---------- Follow geometry ----------
FOLLOW_DISTANCE_M = 1.5       # target 의 뒤 몇 m 지점을 goal 로 삼나
GOAL_CHANGE_THRESHOLD_M = 0.3 # 이전 goal 과 이 만큼 떨어져야 새 goal 발행

# ---------- LiDAR fusion ----------
LIDAR_BEARING_WINDOW_DEG = 5.0  # bbox bearing ±이 각도 의 LiDAR 빔 평균
LIDAR_MAX_M = 8.0               # 이 이상이면 측정 신뢰 안 함

# ---------- Control loop ----------
NAV2_GOAL_HZ = 2.0            # control loop 주기 — Nav2 액션 reissue 검사
STATE_STALE_TIMEOUT_S = 5.0   # /gogoping/tracking_state 가 이 시간 안 오면 lost

# ---------- frame names ----------
MAP_FRAME = "map"
BASE_FRAME = "base_link"
