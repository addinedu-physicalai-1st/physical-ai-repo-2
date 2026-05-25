# GogoPing 의 "원하는 상태" — UI / Control Server 가 SetGoal.srv 로 발행.
#
# target_state 가 직접 FSM state 이름. 외부에서 요청 가능한 state:
#   IDLE         — 대기 (active task 취소)
#   GOTO         — 지정 vertex 로 이동 (destination_key 필수)
#   FOLLOW       — 사람 추종 (target_id 필수)
#   LULLABY      — 자장가 재생 (추가 필드 없음)
#   HIDEANDSEEK  — 숨바꼭질 (target_id + search_waypoints 필수)
#   MANUAL       — 토크 OFF, 사람이 직접 밀기
#   RETURNING    — 도크 복귀 강제 명령
#
# 외부에서 요청 불가 (validator 가 reject) — 내부 trigger 전용:
#   CHARGING / LOW_BATTERY_RETURNING / ERROR
#
# 같은 goal 재발행 = 무해 (idempotent). 다른 goal 발행 = preempt (active ↔ active 직접 전이).
# command_listener 가 본 Goal 을 받아 reconciler 호출 → 적절한 FSM trigger 발화.
# UI 는 FSM trigger 이름 (goto_request, manual_request 등) 을 몰라도 됨.

string target_state         # 위 7개 중 하나 (string, 대문자)
string destination_key      # named_pose 키 — target_state=GOTO 시 필수
string target_id            # child_id / teacher_id — FOLLOW / HIDEANDSEEK 시 필수
string[] search_waypoints   # vertex name 리스트 — HIDEANDSEEK 시 필수 (빈 리스트 거부)
