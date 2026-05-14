# Perception Behaviors

`gogoping_vision` 토픽 → blackboard 어댑터. `bt/behaviors/perception/` 안.

모두 *(스켈레톤)*. 자세한 인터페이스는 코드 작성 시 본 파일 갱신.

- **is_target_visible** — `blackboard.target_visible` 값 확인 (Condition). Used in: BT_follow_sub
- **detect_target_person** — YOLO + ReID 추론 결과 구독, blackboard 업데이트. Used in: BT_follow_sub
- **found_child** — `blackboard.found` 값 확인 (Condition). Used in: BT_hide_and_seek_sub
- **child_face_tracker** — 놀이 상대 아이 얼굴 발견 시 `blackboard.found = True`. Used in: BT_hide_and_seek_sub
- **load_stability_check** — 짐 떨어짐 감지 (manual 모드일 때 비활성). Used in: BT_carry_sub
