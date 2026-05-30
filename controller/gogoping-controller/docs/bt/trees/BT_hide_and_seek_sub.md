# BT_hide_and_seek_sub

HIDEANDSEEK state MainTree (BT_hide_and_seek_main) 의 body. **6-step Sequence** —
출입구(play_area)로 이동 → 모집 → 카운트다운 → 순찰 (탐색) → 복귀 → end idle 의 전체 hideseek 워크플로우.

[bt/trees/sub_trees/BT_hide_and_seek_sub.py](../../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/sub_trees/BT_hide_and_seek_sub.py)

## Root composite

빌더 `build_hide_and_seek_sub(ctx)` 는 blackboard 의 `hideseek_play_area_key` + `search_waypoints` 두 값에 따라 셋 중 하나를 반환:

| 조건 | 반환 |
|---|---|
| 두 값 모두 채워짐 | `Sequence("BT_hide_and_seek_sub", memory=True)` — 6 step |
| `hideseek_play_area_key` 비어있음 | `Failure` leaf (이름 = `BT_hide_and_seek_sub_no_play_area`) |
| `search_waypoints` 빈 리스트 | `Failure` leaf (이름 = `BT_hide_and_seek_sub_no_waypoints`) |

정상 경로에선 [goal_reconciler](../../../src/gogoping/gogoping_modes/gogoping_modes/utils/goal_reconciler.py) 가 두 값 결손을 미리 거부 — `Failure` 분기는 ForceState 디버그 우회 시 방어용.

### 6-step 구조

```
Sequence("BT_hide_and_seek_sub", memory=True)
├─ step_move_to_play           Sequence(memory=True)
│   ├─ SetDestinationKey(play_area)
│   ├─ SetHideseekPhase("move_to_play")
│   └─ BT_goto_sub             — destination 까지 nav + 도착 알림
├─ step_recruit                Sequence(memory=True)
│   ├─ SetHideseekPhase("recruit")
│   └─ AwaitRecruitComplete    — HIDESEEK_REGISTERED_IDS 채워질 때까지 RUNNING
├─ step_countdown              Sequence(memory=True)
│   ├─ SetHideseekPhase("countdown")
│   └─ Countdown(30s)
├─ step_patrol                 Sequence(memory=True)
│   ├─ SetHideseekPhase("patrol")
│   └─ Parallel(SuccessOnOne, name="patrol_with_caught_monitor")
│       ├─ BT_patrol_sub       — search_waypoints 순회 + 카메라 sweep
│       └─ HideSeekCaughtMonitor — 등록자 전원 caught 시 SUCCESS
├─ step_return                 Sequence(memory=True)
│   ├─ SetDestinationKey(play_area)
│   ├─ SetHideseekPhase("return")
│   └─ Parallel(SuccessOnOne, name="return_with_caught_monitor")
│       ├─ BT_goto_sub         — play_area 복귀
│       └─ HideSeekCaughtMonitor
└─ step_end                    Sequence(memory=True)
    ├─ SetHideseekPhase("end")
    └─ py_trees.behaviours.Running()   — 영구 RUNNING (root SUCCESS 차단)
```

### step_patrol / step_return Parallel — SuccessOnOne

자식 둘 중 하나라도 SUCCESS 면 parallel SUCCESS → Sequence 다음 step. 의미:

- `BT_patrol_sub` SUCCESS (모든 waypoint 순회 완료) → 미발견자 남았더라도 다음 step (return) 진행
- `HideSeekCaughtMonitor` SUCCESS (모든 등록자 caught) → 더 순찰할 필요 없으니 즉시 다음 step

복귀 중에도 동일 — 마지막 한 명을 복귀 동선 위에서 잡으면 즉시 step_end 로 진입.

### step_end — 영구 RUNNING idle

마지막 step 의 `py_trees.behaviours.Running()` 이 RUNNING 을 지속 → root Sequence 가 SUCCESS 안 되고 → `main.py._on_tree_success()` 의 `task_done` trigger 발화 차단 → HIDEANDSEEK 상태 유지 → `mode='숨바꼭질'` 유지 → frontend `HideAndSeekGame` 마운트 유지 → `EndPhase` UI 가 사용자 명시 close 까지 보임.

종료 경로: 사용자가 EndPhase 의 "대기로" 클릭 → `postModeClick("대기")` → `cancel` trigger → HIDEANDSEEK → IDLE → BT swap → step_end 의 `Running()` 가 `terminate(INVALID)` 받고 UI 언마운트.

## 사용 behavior / 하위 트리

본 빌더가 직접 인스턴스화:

- [set_destination_key](../behaviors/common.md#set_destination_key) — Step 1, 5 destination 셋
- [set_hideseek_phase](../behaviors/common.md#set_hideseek_phase) — Step 1~6 phase 마커
- [await_recruit_complete](../behaviors/common.md#await_recruit_complete) — Step 2
- [countdown](../behaviors/common.md#countdown) — Step 3 (30s)
- [hide_seek_caught_monitor](../behaviors/perception.md#hide_seek_caught_monitor) — Step 4, 5 parallel

하위 트리 빌더 호출:

- [BT_goto_sub](BT_goto_sub.md) — Step 1, 5 (play_area 이동 / 복귀)
- [BT_patrol_sub](BT_patrol_sub.md) — Step 4 (search_waypoints 순회)

## blackboard 의존성

| Key | R/W | 본 빌더 안에서 누가 |
|---|---|---|
| `hideseek_play_area_key` | R | 빌더 자체 (build 시점에 1회 읽어 SetDestinationKey 의 const 인자로 박음) |
| `search_waypoints` | R | 빌더 자체 (BT_patrol_sub 에 전달) |
| `hideseek_registered_ids` | R | Step 2 (AwaitRecruitComplete), Step 4·5 (HideSeekCaughtMonitor) |
| `hideseek_caught_ids` | R | Step 4·5 (HideSeekCaughtMonitor) |
| `destination_key` | W | Step 1·5 의 SetDestinationKey → 직후 BT_goto_sub 의 NavigateToVertex 가 R |
| `hideseek_phase` | W | Step 1~6 의 SetHideseekPhase ("move_to_play" / "recruit" / "countdown" / "patrol" / "return" / "end") — snapshot 으로 흘러가 UI 라우팅 |

전체 R/W 매트릭스: [docs/blackboard-schema.md](../../blackboard-schema.md).

## 진입 / 종료 trigger

- 진입: 트리거 없음 — `BT_hide_and_seek_main` 의 `build_active_main_tree()` 가 body 로 직접 삽입.
- 종료: 자식 (전체 Sequence) 은 step_end 의 `Running()` 때문에 정상적으론 SUCCESS 안 됨. 외부 trigger (cancel / battery_low / fault / 다른 mode 요청) 가 BT swap 으로 강제 종료.

## 상태

- 코드: ✅ ([BT_hide_and_seek_sub.py](../../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/sub_trees/BT_hide_and_seek_sub.py))
- 단위 테스트:
  - ✅ [tests/test_gogoping_hide_and_seek_subtree_builder.py](../../../../../tests/test_gogoping_hide_and_seek_subtree_builder.py) (5 케이스 — Failure 분기 / waypoint 순서 보존 / Sequence 반환)
  - ✅ [tests/test_gogoping_hideseek_subtree_sequence.py](../../../../../tests/test_gogoping_hideseek_subtree_sequence.py) (4 케이스 — 6 step phase marker / end Running / 결손 분기)
- 자식 [BT_goto_sub](BT_goto_sub.md): ✅
- 자식 [BT_patrol_sub](BT_patrol_sub.md): ✅
- 사용 behavior 5개 (Countdown / AwaitRecruitComplete / HideSeekCaughtMonitor / SetHideseekPhase / SetDestinationKey): ✅
