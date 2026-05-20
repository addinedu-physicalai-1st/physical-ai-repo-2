# BT_goto_sub

ASSIST 의 `goto` task 본체. `destination_key` (waypoints.yaml 의 vertex 이름) 까지 graph_router 의 lane 따라 이동, 도착 시 `/gogoping/ui_event` 토픽으로 알림.

자세한 설계 배경 (carry → goto rename 사유 포함): [`docs/superpowers/specs/2026-05-20-bt-goto-sub-design.md`](../../../../docs/superpowers/specs/2026-05-20-bt-goto-sub-design.md).

## Root composite

`Sequence(memory=True)`

```
BT_goto_sub (Sequence, memory=True)
  ├─ NavigateToVertex(target_key=Keys.DESTINATION_KEY)
  └─ UIPublish("AnnounceArrival", ctx, message={"event":"announce","text":"도착했습니다"})
```

## 사용 behavior

- [navigation/navigate_to_vertex](../behaviors/navigation.md#navigate_to_vertex) — `destination_key` blackboard 값 → graph_router action. cancel chain 적용 (`docs/nav-cancel-chain.md`).
- [common/ui_publish](../behaviors/common.md#ui_publish) — `ctx.ui.publish_event(message)` 1회 호출 후 즉시 SUCCESS.

신규 behavior / blackboard 키 / FSM trigger 모두 **없음**. 기존 자산만 조합.

## Blackboard

| 키 | 접근 | 설명 |
|---|---|---|
| `destination_key` | R (NavigateToVertex 가 직접) | command_listener 가 SetGoal.srv 수신 시 W. waypoints.yaml 의 vertex 이름. |

## 진입 / 종료 trigger

| 이벤트 | 처리 |
|---|---|
| 진입 | `command_listener` SetGoal.srv → `assist_task="goto"`, `destination_key=<vertex>` → `assist_request(task="goto")` → ASSIST 진입 → TaskSelector(`goto` 분기) → BT_goto_sub |
| SUCCESS | NavigateToVertex SUCCESS → UIPublish SUCCESS → Sequence SUCCESS → MainTree root SUCCESS → `_on_tree_success()` → `assist_done` → IDLE |
| FAILURE | NavigateToVertex FAILURE (경로 불가 / destination_key 빈 값 / 잘못된 vertex 이름) → Sequence FAILURE → `_on_tree_failure()` → `return_request` → RETURNING |
| Cancel | `cancel` trigger → ASSIST→IDLE → BT swap → `terminate(INVALID)` cascade → NavigateToVertex 의 `_cancel_pending` flag → graph_router action cancel → cmd_vel=0 |
| battery_low / fault | Parallel sibling monitor 발화 → 동일 cancel cascade |

## 알려진 이슈

본 SubTree 자체에는 알려진 이슈 없음. NavigateToVertex 의 cancel chain 함정 3개 (NavTo race / `_on_state_change` reentrancy / async event loop orphan) 는 모두 `docs/nav-cancel-chain.md` 에 명시 + 이미 구현 단에서 처리됨.
