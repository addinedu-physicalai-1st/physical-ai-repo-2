# gogoping_modes 의 현재 상태 + 추구 중인 goal 의 결합 스냅샷.
#
# state_publisher 가 다음 시점에 publish:
#   - FSM state 변경 시 (RobotFSM.add_callback("on_state_change") 훅)
#   - Goal 변경 시 (SetGoal.srv 수락 시)
#   - 주기적 heartbeat (1 Hz)
#
# robot-web / admin-app 가 /gogoping/status WS 로 구독.

# FSM 현재 state (10 상태 중 하나) — string, 대문자
string current_state    # "IDLE" / "CHARGING" / "GOTO" / "FOLLOW" / "LULLABY" /
                        # "HIDEANDSEEK" / "MANUAL" / "RETURNING" /
                        # "LOW_BATTERY_RETURNING" / "ERROR"

# 최근 수락된 goal (없으면 target_state="" 등 빈 문자열)
gogoping_msgs/Goal current_goal

# ERROR state 시 사유 — blackboard.error_reason 미러
# (current_state != "ERROR" 일 때는 빈 문자열)
string error_reason

# publish 시각 (옵션 — 클라이언트 latency 추적용)
builtin_interfaces/Time stamp
