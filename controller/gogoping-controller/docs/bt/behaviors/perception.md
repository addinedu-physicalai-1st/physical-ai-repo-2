# Perception Behaviors

`gogoping_vision` 토픽 → blackboard 어댑터. `bt/behaviors/perception/` 안.

- **is_target_visible** *(스켈레톤)* — `blackboard.target_visible` 값 확인 (Condition). Used in: BT_follow_sub
- **detect_target_person** *(스켈레톤)* — YOLO + ReID 추론 결과 구독, blackboard 업데이트. Used in: BT_follow_sub
- **found_child** *(스켈레톤)* — `blackboard.found` 값 확인 (Condition). Used in: BT_hide_and_seek_sub
- **child_face_tracker** *(스켈레톤)* — 놀이 상대 아이 얼굴 발견 시 `blackboard.found = True`. Used in: BT_hide_and_seek_sub

---

## hide_seek_caught_monitor  *(구현됨)*

`registered_ids ⊆ caught_ids` 이면 SUCCESS, 아니면 RUNNING — patrol / return parallel 의 short-circuit.

- read: `Keys.HIDESEEK_REGISTERED_IDS`, `Keys.HIDESEEK_CAUGHT_IDS`
- write: 없음
- registered_ids 가 비어있으면 RUNNING — 모집 전 잘못된 노드 진입 시 의미 없는 즉시 SUCCESS 방지 (정상 흐름에선 [`await_recruit_complete`](common.md#await_recruit_complete) 가 먼저 RUNNING → registered_ids 셋 되면 SUCCESS → 그 다음 patrol 진입).
- patrol / return parallel 안에서 SuccessOnOne 정책으로 작동 — 모든 등록자가 caught 되면 parallel 즉시 SUCCESS → Sequence 다음 step (patrol 의 경우 return, return 의 경우 end).
- caught_ids 갱신 흐름: UI 인식 파이프라인 (`useHideSeekRecognition`) 이 매칭 → POST `/api/gogoping/play/hideseek/caught {child_id, caught_at_waypoint?}` → ros_bridge 가 `HIDESEEK_CAUGHT_IDS` append.

| 항목 | 값 |
|---|---|
| 인자 | `name` |
| Status | RUNNING (caught 미달) / SUCCESS (caught ⊇ registered) |
| Used in | BT_hide_and_seek_sub 의 patrol / return parallel |
| 파일 | [`bt/behaviors/perception/hide_seek_caught_monitor.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/perception/hide_seek_caught_monitor.py) |
| 테스트 | [tests/test_gogoping_hide_seek_caught_monitor.py](../../../../../tests/test_gogoping_hide_seek_caught_monitor.py) |
