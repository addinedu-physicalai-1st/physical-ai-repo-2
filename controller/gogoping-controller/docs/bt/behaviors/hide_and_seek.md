# hide_and_seek behaviors

HIDEANDSEEK(숨바꼭질) 모드 전용 leaf.

각 항목 — *(스켈레톤)* 표시는 아직 코드 구현 전.

---

## set_destination_key  *(구현됨)*

`blackboard.DESTINATION_KEY = key` 후 즉시 SUCCESS — `build_goto_subtree(ctx)` 가 인자를 안 받고 `Keys.DESTINATION_KEY` 만 R 하므로, hideseek 처럼 한 sequence 안에서 goto 를 여러 번 호출하려면 매 진입 시 destination 을 미리 셋팅한다.

- write: `Keys.DESTINATION_KEY`
- 블랙보드 키 자체는 GOTO state 의 reconciler 가 다른 흐름에서 W (state 동시 진입 불가라 충돌 없음). 본 behaviour 는 그 키를 다른 state 안에서도 셋팅하기 위한 helper.

| 항목 | 값 |
|---|---|
| 인자 | `name`, `key: str` |
| Status | SUCCESS (즉시) |
| Used in | BT_hide_and_seek_sub — `play_area` / patrol_* 진입 직전 |
| 파일 | [`bt/behaviors/hide_and_seek/set_destination_key.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/hide_and_seek/set_destination_key.py) |

## set_hideseek_phase  *(구현됨)*

`blackboard.HIDESEEK_PHASE = phase` 문자열 셋 후 즉시 SUCCESS — UI 에 현재 숨바꼭질 단계 알림.

- write: `Keys.HIDESEEK_PHASE`
- snapshot 의 `hideseek_phase` 필드로 흘러나가 robot-web 의 `useHideseekPhaseStore` → `HideAndSeekGame.syncFromBtPhase` 로 전이.
- phase 값: `"move_to_play"` / `"recruit"` / `"countdown"` / `"patrol"` / `"return"` / `"end"` / `""` (비활성).
- BT_hide_and_seek_sub Sequence 의 각 step 진입 직전에 끼워 넣음. 같은 값 재셋팅은 무해.

| 항목 | 값 |
|---|---|
| 인자 | `name`, `phase: str` |
| Status | SUCCESS (즉시) |
| Used in | BT_hide_and_seek_sub — 각 step 의 첫 자식 |
| 파일 | [`bt/behaviors/hide_and_seek/set_hideseek_phase.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/hide_and_seek/set_hideseek_phase.py) |

## await_recruit_complete  *(구현됨)*

`blackboard.HIDESEEK_REGISTERED_IDS` 가 빈 리스트가 아니면 SUCCESS, 아니면 RUNNING — control-service 의 모집 종료 API 게이트.

- read: `Keys.HIDESEEK_REGISTERED_IDS`
- 진입 흐름: UI 의 recruit phase "출발" 버튼 → POST `/api/gogoping/play/hideseek/recruit-complete {child_ids: [...]}` → ros_bridge 가 `HIDESEEK_REGISTERED_IDS = child_ids` 세팅 → 본 behaviour SUCCESS → Sequence 다음 ([`countdown`](#countdown)).
- reconciler 가 HIDEANDSEEK 진입 시마다 본 키를 `[]` 로 reset — "다시 하기" 재진입 시 처음엔 RUNNING 으로 시작.

| 항목 | 값 |
|---|---|
| 인자 | `name` |
| Status | RUNNING (registered_ids 비어있음) / SUCCESS (1개 이상) |
| Used in | BT_hide_and_seek_sub 의 recruit step |
| 파일 | [`bt/behaviors/hide_and_seek/await_recruit_complete.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/hide_and_seek/await_recruit_complete.py) |
| 테스트 | [tests/test_gogoping_await_recruit_complete.py](../../../../../tests/test_gogoping_await_recruit_complete.py) |

## countdown  *(구현됨)*

지정한 `seconds` 만큼 RUNNING 후 SUCCESS — 순수 시간 게이트.

- `initialise()` 가 `time.monotonic()` 을 anchor 로 잡고, `update()` 마다 경과 시간 확인.
- `terminate()` 가 anchor 를 `None` 으로 리셋 — interrupt 후 재진입 시 새 N 초 카운트 시작.
- read/write 없음 (블랙보드 의존 X). UI 단계 알림 (countdown_start / 챈트) 은 [`set_hideseek_phase`](#set_hideseek_phase) 와 클라이언트 타이머 책임.

| 항목 | 값 |
|---|---|
| 인자 | `name`, `seconds: float` |
| Status | RUNNING → SUCCESS (elapsed ≥ seconds) |
| terminate | anchor None 으로 리셋 |
| Used in | BT_hide_and_seek_sub 의 countdown step (30초) |
| 파일 | [`bt/behaviors/hide_and_seek/countdown.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/hide_and_seek/countdown.py) |
| 테스트 | [tests/test_gogoping_countdown_behavior.py](../../../../../tests/test_gogoping_countdown_behavior.py) |

## hide_seek_caught_monitor  *(구현됨)*

`registered_ids ⊆ caught_ids` 이면 SUCCESS, 아니면 RUNNING — patrol / return parallel 의 short-circuit.

- read: `Keys.HIDESEEK_REGISTERED_IDS`, `Keys.HIDESEEK_CAUGHT_IDS`
- write: 없음
- registered_ids 가 비어있으면 RUNNING — 모집 전 잘못된 노드 진입 시 의미 없는 즉시 SUCCESS 방지 (정상 흐름에선 [`await_recruit_complete`](#await_recruit_complete) 가 먼저 RUNNING → registered_ids 셋 되면 SUCCESS → 그 다음 patrol 진입).
- patrol / return parallel 안에서 SuccessOnOne 정책으로 작동 — 모든 등록자가 caught 되면 parallel 즉시 SUCCESS → Sequence 다음 step (patrol 의 경우 return, return 의 경우 end).
- caught_ids 갱신 흐름: UI 인식 파이프라인 (`useHideSeekRecognition`) 이 매칭 → POST `/api/gogoping/play/hideseek/caught {child_id, caught_at_waypoint?}` → ros_bridge 가 `HIDESEEK_CAUGHT_IDS` append.

| 항목 | 값 |
|---|---|
| 인자 | `name` |
| Status | RUNNING (caught 미달) / SUCCESS (caught ⊇ registered) |
| Used in | BT_hide_and_seek_sub 의 patrol / return parallel |
| 파일 | [`bt/behaviors/hide_and_seek/hide_seek_caught_monitor.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/hide_and_seek/hide_seek_caught_monitor.py) |
| 테스트 | [tests/test_gogoping_hide_seek_caught_monitor.py](../../../../../tests/test_gogoping_hide_seek_caught_monitor.py) |
