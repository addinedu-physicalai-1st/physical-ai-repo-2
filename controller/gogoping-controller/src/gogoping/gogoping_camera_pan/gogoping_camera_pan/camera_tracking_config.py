"""Camera pan/tilt auto-tracking 튜닝 상수.

servo_bridge 의 `~/cmd_pan`, `~/cmd_tilt` (Float32, degrees) topic 으로 publish.

servo 좌표계 (servo_bridge.py 의 절대각):
- pan : 5° (왼쪽 끝) — 90° (정면) — 175° (오른쪽 끝)
- tilt: 30° — 90° (정면) — 150° — 실물에 따라 위/아래 의미 다름.
"""

# ---------- Pan ----------
PAN_HOME_DEG = 90.0          # 정면
PAN_MIN_DEG = 45.0
PAN_MAX_DEG = 135.0
PAN_DEAD_ZONE_PX = 40        # bbox jitter robust + 추적 응답 balance
# 음수 — camera/servo mount 방향이 logic 기대와 반대 (사람 좌측 이동 시 servo 가 우측으로 가던 문제).
PAN_P_GAIN_DEG_PER_PX = -0.05
PAN_STEP_LIMIT_DEG = 6.0     # 60°/s @ 10Hz

# ---------- Tilt ----------
TILT_HOME_DEG = 90.0         # 정면 수평 고정
TILT_MIN_DEG = 60.0
TILT_MAX_DEG = 140.0
TILT_DEAD_ZONE_PX = 40
TILT_P_GAIN_DEG_PER_PX = -0.05  # PAN 과 동일 — mount 방향 반대 보정

# bbox 안에서 frame 중앙으로 잡을 vertical ratio. YOLO 전신 bbox 의 0.5 (허리 중앙) 면
# 얼굴이 frame 위로 잘림. 0.25 = 상반신 중심 (어깨~가슴), 얼굴이 자연스럽게 가운데.
BBOX_VERTICAL_FOCUS_RATIO = 0.25
TILT_STEP_LIMIT_DEG = 6.0

# ---------- Frame geometry (perception fast preset 과 동기) ----------
FRAME_W_PX = 640
FRAME_H_PX = 480

# ---------- Control ----------
TRACK_HZ = 10.0
LOST_TIMEOUT_S = 2.0   # tracking_state 가 이 시간 안 오면 home 복귀

# ---------- Topics ----------
# servo_bridge node 의 default name 이 "servo_bridge" 라 subscribe 경로는
# `/servo_bridge/cmd_pan`. keyboard_teleop / pan_scanner 도 같은 topic 사용 (시점 다름).
TRACKING_STATE_TOPIC = "/gogoping/tracking_state"
CMD_PAN_TOPIC  = "/servo_bridge/cmd_pan"
CMD_TILT_TOPIC = "/servo_bridge/cmd_tilt"
