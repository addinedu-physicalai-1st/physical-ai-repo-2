"""Camera pan/tilt auto-tracking 튜닝 상수.

servo_bridge 의 `~/cmd_pan`, `~/cmd_tilt` (Float32, degrees) topic 으로 publish.

servo 좌표계 (servo_bridge.py 의 절대각):
- pan : 5° (왼쪽 끝) — 90° (정면) — 175° (오른쪽 끝)
- tilt: 30° — 90° (정면) — 150° (위쪽 또는 아래쪽 — 실물 따라 다름)

home 좌표는 servo 의 절대 각도로 직접 publish.
사용자 설정 — 추종 모드 진입 시 tilt 기본 100° (정면에서 ~10° 올린 위치).
"""

# ---------- Pan ----------
PAN_HOME_DEG = 90.0          # servo center — 정면
PAN_MIN_DEG = 45.0           # 좌측 한계
PAN_MAX_DEG = 135.0          # 우측 한계
# bbox jitter robust 와 빠른 추적의 balance — 30 너무 민감, 60 못 따라감 → 40.
PAN_DEAD_ZONE_PX = 40
PAN_P_GAIN_DEG_PER_PX = 0.05 # 100px offset → 5° (사람 따라가는 충분한 속도)
PAN_STEP_LIMIT_DEG = 6.0     # 사용자 빠르게 이동해도 따라갈 수 있게 6°/tick (60°/s @ 10Hz)

# ---------- Tilt ----------
TILT_HOME_DEG = 100.0        # 사용자 요청 — 정면에서 약간 위 (얼굴 인식 우선)
TILT_MIN_DEG = 60.0          # 아래쪽 한계 (home - 40°)
TILT_MAX_DEG = 140.0         # 위쪽 한계 (home + 40°)
TILT_DEAD_ZONE_PX = 40
TILT_P_GAIN_DEG_PER_PX = 0.05
TILT_STEP_LIMIT_DEG = 6.0

# ---------- Frame geometry (perception 의 fast preset 과 동기) ----------
FRAME_W_PX = 640
FRAME_H_PX = 480

# ---------- Control ----------
TRACK_HZ = 10.0
LOST_TIMEOUT_S = 2.0   # tracking_state 가 이 시간 안 오면 home 복귀.
                       # 짧은 detection drop 은 마지막 위치 유지 (auto_tracker._tick).

# ---------- Topics ----------
# servo_bridge node 의 default node name 이 "servo_bridge" 라 subscribe 경로는
# `/servo_bridge/cmd_pan` (~/cmd_pan 의 expansion). keyboard_teleop / pan_scanner
# 도 같은 topic 사용 — 충돌 없음 (시점 다름: 추종 vs 수동).
TRACKING_STATE_TOPIC = "/gogoping/tracking_state"
CMD_PAN_TOPIC  = "/servo_bridge/cmd_pan"
CMD_TILT_TOPIC = "/servo_bridge/cmd_tilt"
