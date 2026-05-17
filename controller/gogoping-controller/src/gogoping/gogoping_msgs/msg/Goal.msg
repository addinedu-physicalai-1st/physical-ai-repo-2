# GogoPing 의 "원하는 상태" — UI / Control Server 가 SetGoal.srv 로 발행.
#
# 의미:
#   mode="IDLE"             — 대기 (작업 없음). ASSIST/PLAY/MANUAL 중에 발행하면 task 취소 후 IDLE.
#                              ERROR 중에 발행하면 reset trigger 발화 → IDLE.
#   mode="ASSIST", task=*   — 교사 보조 (carry / follow / lullaby)
#   mode="PLAY",   task=*   — 아이 놀이 (hideseek)
#   mode="MANUAL"           — 토크 OFF, 사람이 직접 밀어서 이동. task 불필요.
#                              cancel / battery_low / fault / return_command 시 torque 자동 ON.
#   mode="RETURNING"        — 도크 복귀 강제 명령 (수동). 자동 복귀는 battery_low / idle_timeout
#                              / SubTree FAILURE fallback 으로 별도 발생.
#
# 같은 goal 재발행 = 무해 (idempotent). 다른 goal 발행 = preempt.
# CHARGING / ERROR 는 mode 로 발행 불가 — CHARGING 진입은 docked, ERROR 진입은 fault 트리거만.
#
# command_listener 가 본 Goal 을 받아 현재 state 와 비교 → 필요한 FSM trigger 자체 발화.
# 즉 UI 는 FSM trigger 이름 (assist_command, manual_command, fault, reset 등) 을 몰라도 됨.

string mode             # "IDLE" / "ASSIST" / "PLAY" / "MANUAL" / "RETURNING"
string task             # "carry" / "follow" / "lullaby" / "hideseek" — mode=ASSIST/PLAY 시
string carry_mode       # "manual" / "goto" / "follow" — task=carry 시  (※ UI 의 "수동" mode 와 다름 — 운반 의 carry_mode)
string destination_key  # named_pose 키 — carry+goto 시
string target_id        # child_id / teacher_id — follow / hideseek / carry+follow 시
