# Perception Behaviors

`gogoping_vision` 토픽 → blackboard 어댑터. `bt/behaviors/perception/` 안.

- **is_target_visible** *(스켈레톤)* — `blackboard.target_visible` 값 확인 (Condition). Used in: BT_follow_sub
- **detect_target_person** *(스켈레톤)* — YOLO + ReID 추론 결과 구독, blackboard 업데이트. Used in: BT_follow_sub
- **found_child** *(스켈레톤)* — `blackboard.found` 값 확인 (Condition). Used in: BT_hide_and_seek_sub
- **child_face_tracker** *(스켈레톤)* — 놀이 상대 아이 얼굴 발견 시 `blackboard.found = True`. Used in: BT_hide_and_seek_sub

