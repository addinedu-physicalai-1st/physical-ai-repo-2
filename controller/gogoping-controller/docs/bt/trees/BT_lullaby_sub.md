# BT_lullaby_sub

자장가 SubTree — LULLABY state MainTree (BT_lullaby_main) 의 body. mp3 재생 시작/정지
신호를 `/gogoping/ui_event` 토픽에 publish (재생 자체는 robot-web frontend).

[bt/trees/sub_trees/BT_lullaby_sub.py](../../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/sub_trees/BT_lullaby_sub.py)

## Root composite

```
LullabyAudio (단일 leaf, name="BT_lullaby_sub")
  ├─ initialise():  ctx.ui.publish_event({event: "lullaby_play", src: "lullaby.mp3", loop: True})
  ├─ update():      Status.RUNNING (영구 — 외부 trigger 가 BT swap 으로 종료)
  └─ terminate():   ctx.ui.publish_event({event: "lullaby_stop"})  (idempotent, _stop_published flag)
```

Composite (Sequence/Parallel) 없음 — "publish 시작 + 영구 RUNNING + publish 종료" 한
책임이라 단일 behavior 로 충분. [subtree-flow.md](../../subtree-flow.md) 의 의사코드
`Sequence(PlayAudio, WaitForStopCommand)` 두 단계는 본 `LullabyAudio` 한 노드에 응집 —
terminate 시 stop publish 가 같은 클래스 책임 안에 들어가 race 회피.

이름 `BT_lullaby_sub` — `tree_inspector._find_subtree` 의 `BT_*_sub` 패턴 매칭 → admin
UI BT SUB 영역에 자동 표시.

## 사용 behavior

- [LullabyAudio](../behaviors/lullaby.md#lullaby_audio) — lullaby/lullaby_audio.py

## 진입 / 종료 trigger

### 진입
| Trigger | 발화 주체 | 동작 |
|---|---|---|
| `lullaby_request` | `command_listener` (SetGoal target_state=LULLABY) | FSM IDLE → LULLABY → BT swap → BT_lullaby_main body 로 직접 호출 → BT_lullaby_sub.initialise() → play publish |

### 종료
| Trigger | 발화 주체 | terminate? | stop publish? |
|---|---|---|---|
| `cancel` (LULLABY → IDLE) | `command_listener` (SetGoal target_state=IDLE) | ✅ | ✅ |
| `goto_request` / `follow_request` / `hideseek_request` | `command_listener` (LULLABY → 다른 task state 직접 전이) | ✅ | ✅ |
| `return_request` (LULLABY → RETURNING) | `command_listener` (SetGoal target_state=RETURNING) | ✅ | ✅ |
| `manual_request` | `command_listener` | ✅ | ✅ |
| `battery_low` (LULLABY → LOW_BATTERY_RETURNING) | `battery_low_monitor` | ✅ | ✅ |
| `fault` (LULLABY → ERROR) | `map_boundary_monitor` / `hardware_health_monitor` | ✅ | ✅ |

모든 종료 경로에서 stop publish 보장 — `main.py._build_tree_for_state` 의
`root.stop(INVALID) + tree.shutdown()` 이 RUNNING 자식의 `terminate()` 전파 보장
(`ManualTorqueHold` 의 torque ON 복원과 동일 메커니즘).

## UI 이벤트 스키마

publish 되는 두 메시지 (frontend contract):

```json
// 진입 시
{"event": "lullaby_play", "src": "lullaby.mp3", "loop": true}

// 종료 시
{"event": "lullaby_stop"}
```

`src` 는 robot-web 의 정적 리소스 이름 — frontend 의 `<audio>` element 가 해석.
곡 선택 UI 는 현재 없음 (한 곡 하드코딩).

## 데이터 흐름

```
사용자 "자장가" 클릭 (robot-web / admin UI)
  ↓ POST /api/gogoping/mode
control-service → SetGoal.srv → /gogoping/set_goal
  ↓
command_listener → goal_reconciler
  └─ fsm.trigger("lullaby_request")
FSM IDLE → LULLABY → BT swap
  ↓
BT_lullaby_main → build_lullaby_subtree(ctx) → LullabyAudio (body 직접 삽입)
       ↓ initialise()
     /gogoping/ui_event ← {"event": "lullaby_play", "src": "lullaby.mp3", "loop": true}
       ↓
     robot-web frontend → <audio src="lullaby.mp3" loop>.play()
     ↓ update() = RUNNING (지속)

[사용자 "대기" 클릭]
  ↓ fsm.trigger("cancel") → LULLABY → IDLE → BT swap
main.py → root.stop(INVALID) + tree.shutdown()
  → LullabyAudio.terminate(INVALID)
       ↓
     /gogoping/ui_event ← {"event": "lullaby_stop"}
       ↓
     robot-web frontend → <audio>.pause()
```

## 상태

- 코드: ✅ ([BT_lullaby_sub.py](../../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/sub_trees/BT_lullaby_sub.py))
- 의존 behavior: [LullabyAudio](../behaviors/lullaby.md#lullaby_audio) (✅), [UIPublisher.publish_event()](../../../src/gogoping/gogoping_modes/gogoping_modes/interfaces/ui_publisher.py) (✅)
- 테스트: 빌더 2 + LullabyAudio 7 = 9 시나리오 통과
- frontend `<audio>` 구독 코드 — 별도 PR (본 작업 범위 외)
