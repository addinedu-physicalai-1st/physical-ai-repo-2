# Nav Cancel Chain — RETURNING / LOW_BATTERY_RETURNING

도크 복귀 중 다른 state 로 전이될 때 nav2 goal 까지 cancel 이 forward 되는 전체
시퀀스. 과거에 3가지 함정을 다 밟아봤음 (race / async event loop / orphan goal) —
다 fix 됐지만 미래에 새 nav behavior 추가 시 같은 함정 반복 안 하게 정리.

## Cancel chain (정상 시나리오)

```
사용자 / monitor                  BT (gogoping_modes)              graph_router                    nav2
       │                                  │                              │                          │
       │  SetGoal.srv                     │                              │                          │
       ├─────────────────────────────────▶│                              │                          │
       │                                  │ fsm.trigger("return_request")│                          │
       │                                  ├─ _on_state_change            │                          │
       │                                  │  → _pending_state="RETURNING"│                          │
       │                                  │  (deferred — 다음 _tick)     │                          │
       │                                  │                              │                          │
       │                              ⏱ next _tick (≤100ms)               │                          │
       │                                  │ root.stop(INVALID)            │                          │
       │                                  │  → 자식 terminate(INVALID)    │                          │
       │                                  │ build BT_returning_main       │                          │
       │                                  │ ReturnSubTree.initialise()    │                          │
       │                                  │ NavTo.initialise()            │                          │
       │                                  │  send_goal_async(충전소입구) │                          │
       │                                  ├─────────────────────────────▶│                          │
       │                                  │                              │ gh accepted              │
       │                                  │◀─────────────────────────────┤                          │
       │                                  │                              │ _act_navigate (sync)     │
       │                                  │                              │ nav_ac.send_goal_async   │
       │                                  │                              ├─────────────────────────▶│
       │                                  │                              │                  accepted│
       │                                  │                              │◀─────────────────────────┤
       │                                  │                              │ polling loop             │
       │                                  │                              │  while not done():       │
       │                                  │                              │    time.sleep(0.05)      │
       │  cancel / *_request              │                              │                          │
       ├─────────────────────────────────▶│                              │                          │
       │                                  │ fsm.trigger("cancel")        │                          │
       │                                  │  → _pending_state="IDLE"     │                          │
       │                              ⏱ next _tick                       │                          │
       │                                  │ root.stop(INVALID)            │                          │
       │                                  │  → NavTo.terminate(INVALID)   │                          │
       │                                  │    gh.cancel_goal_async()     │                          │
       │                                  ├─────────────────────────────▶│                          │
       │                                  │                              │ cancel_callback ACCEPT   │
       │                                  │                              │ polling 의 next iter:    │
       │                                  │                              │  gh.is_cancel_requested  │
       │                                  │                              │  → nav_gh.cancel_goal_async
       │                                  │                              ├─────────────────────────▶│
       │                                  │                              │                          │ controller stop
       │                                  │                              │                  ack     │ cmd_vel=0
       │                                  │                              │◀─────────────────────────┤
       │                                  │                              │ gh.canceled()             │
       │                                  │                              │ return result             │
       │                                  │                              │ (nav_gh = None — finally  │
       │                                  │                              │  의 safety net skip)      │
```

핵심 invariant:
1. **state 변경 → BT swap 은 1 tick 지연** (`_on_state_change` 가 즉시 swap 안 함 — `_pending_state` 만 기록, 다음 `_tick` 에서 처리). 이유: service callback thread / 본인 트리 update 에서 fsm.trigger 호출돼도 reentrancy 안전.
2. **BT swap 시 `root.stop(INVALID)` 가 자식 terminate(INVALID) 전파** — NavTo.terminate(INVALID) → `gh.cancel_goal_async()`.
3. **graph_router 의 polling 이 `gh.is_cancel_requested` 검출 → `nav_gh.cancel_goal_async()` forward** — nav2 가 controller stop.
4. **finally 의 safety net** — 위 3개가 다 정상 작동하면 도달 안 함. 그러나 예외 / 외부 cancel 등 비정상 종료 시 nav_gh orphan 방지.

> **NavigateToPose chain 변경 (2026-05-28)**: graph_router 가 vertex 단위로 nav2 NavigateToPose 를 순차 호출 (이전 NavigateThroughPoses 1-shot 에서 변경). 위 invariant 3, 4 는 **각 segment iteration 마다** 동일하게 적용 — `_act_navigate` 의 `for i in range(1, len(seq))` 안의 `try/finally` 가 매 segment 의 `nav_gh` orphan 을 보장. cancel 시에는 현재 segment 의 nav2 goal 만 cancel + sequence loop 탈출 (다음 segment 진입 안 함).

## 과거 함정 3개 (다 fix 됨)

### 함정 1 — NavTo race (goal_handle 미수신 상태에서 terminate)

**증상**: 사용자가 RETURNING 진입 직후 (~100ms 안) cancel 누르면 robot 이 계속 충전소로 이동.

**원인**: `NavTo.initialise()` 의 `send_goal_async()` 응답이 callback 으로 도착하기 전 (~10~100ms) `terminate(INVALID)` 호출되면 `_goal_handle is None` 이라 cancel 분기 SKIP. 그 뒤 callback 도착 시 `_goal_handle = gh` set 되지만 이미 behavior 죽은 상태 — cancel 호출 못함 → nav2 좀비.

**Fix** ([navigate_to_vertex.py](../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/navigation/navigate_to_vertex.py)):
- `_cancel_pending: bool` flag 추가
- `terminate(INVALID)` 시 `_goal_handle is None` 이면 `_cancel_pending = True`
- `_on_goal_response` 가 gh 받자마자 `_cancel_pending` 체크 → True 면 즉시 `gh.cancel_goal_async()` 호출 후 return (result 콜백 등록 skip — behavior 는 이미 죽었음)

### 함정 2 — `_on_state_change` thread / reentrancy

**증상**: VerifyDockingContact 가 `update()` 안에서 `fsm.trigger("docked")` 호출 → 이전 동기 BT swap 코드가 *update 도중 본인 트리 stop* → py_trees 자료구조 부분 정리 race.

**원인**: `transitions` 라이브러리는 `fsm.trigger()` 가 `on_state_change` 콜백을 동기 호출. 과거 `_on_state_change` 가 직접 `_build_tree_for_state` 호출 → stop + build + setup 까지 한 thread 에서 즉시 실행.

**Fix** ([main.py](../src/gogoping/gogoping_modes/gogoping_modes/main.py)):
- `_on_state_change` 가 `_pending_state` 만 기록 (write 한 줄 — GIL 안전)
- 실제 BT swap 은 main thread 의 `_tick` 첫머리에서 처리
- 1 tick (~100ms @ 10Hz) latency 발생하지만 leaf 의 `terminate()` 가 cmd_vel=0 보장하므로 안전

### 함정 3 — graph_router 의 async + nav_gh orphan

**증상**: RETURNING → IDLE swap 후에도 cmd_vel 계속 흐름, robot 멈추지 않음.

**원인 a** (event loop): `_act_navigate` 가 `async def` + `await asyncio.sleep(0.05)`. rclpy ActionServer + MultiThreadedExecutor 환경에서는 **running asyncio event loop 가 없음** → 첫 `await` 에서 즉시 `RuntimeError: no running event loop` → function 종료.

**원인 b** (orphan): function 이 종료될 때 `nav_gh` 가 살아있는데 cancel 안 함 → nav2 goal 좀비 → controller_server 가 cmd_vel 계속 publish.

**Fix** ([graph_router_node.py](../src/gogoping/gogoping_navigation/gogoping_navigation/graph_router_node.py)):
- `_act_navigate` 를 **sync function** 으로 변환 (async 제거)
- `await future` → `while not future.done(): time.sleep(...)` + timeout
- `try / finally` 로 wrap — 어떤 종료 경로에서도 `nav_gh is not None` 이면 `cancel_goal_async()` 호출 (safety net)
- `RcutilsLogger` 에 `.exception` 없으므로 `.error(... + traceback.format_exc())` 사용

자세한 코딩 컨벤션: [conventions.md §5](conventions.md#5-rclpy-사용-컨벤션--안-지키면-폭발하는-함정-3개).

## 디버그 도구

debug event chain 으로 cancel chain 의 어느 단계에서 끊겼는지 실시간 추적 가능. admin
UI 의 NavDebugLogCard 에서 색상별 로그로 한 줄씩 표시. 자세한 사용법:
[bt/debug-tooling.md](bt/debug-tooling.md).

이상 시나리오 진단 시 다음 셸 명령도 유용:

```bash
export ROS_DOMAIN_ID=<할당된 ID>

# nav2 lifecycle 확인 (active 아니면 graph_router 가 즉시 abort)
ros2 lifecycle get /controller_server
ros2 lifecycle get /bt_navigator
ros2 lifecycle get /planner_server

# TF 확인 (map → gogoping/base_link 없으면 graph_router 가 "no tf" abort)
ros2 run tf2_ros tf2_echo map gogoping/base_link

# cmd_vel publisher 수 — 좀비 의심 시
ros2 topic info /gogoping/cmd_vel -v

# graph_router 자체 stderr — RuntimeError 등 traceback 확인
tmux capture-pane -t gogoping-sim:graph-router -p -S -200 | grep -iE "error|exception"
```


## 함정 #4 — pause / resume / reroute (2026-05-28 추가)

graph_router 가 segment 진행 중 `/gogoping/proximity_event` 을 polling 하며:
- `person_close` → 현재 nav2 NavigateToPose goal cancel + pause loop. 사라지면 (`ok`) 재발사. 60s sustain → blocked set 추가 + `_restart_with_reroute`.
- `wall_close` → cancel + LiDAR 후방 clearance check (`≥ 0.25m`) → 15cm backup → 재시도. 3 회 실패 → blocked + reroute. backup 중 odom 변화 < 3cm 면 stuck → abort.

### 시퀀스 (사람 정지·재개)

```
graph_router_node            nav2
─────────────────            ─────
send_goal(seg_target)  ──→ EXECUTING
proximity=person_close ←── (사람 등장)
   ↓
cancel_goal_async()    ──→ CANCELED
pause_start_ts = now
loop:
   if level==ok and elapsed<60s:
       send_goal(seg_target) ──→ EXECUTING (재시도)
   if elapsed >= 60s:
       blocked.add(seg_target) → _restart_with_reroute
```

### 시퀀스 (벽 backup)

```
graph_router_node           nav2 / motor
─────────────────           ───────────
send_goal(seg_target) ──→ EXECUTING
proximity=wall_close  ←── (벽 근처)
   ↓
cancel_goal_async()   ──→ CANCELED
rear_clearance < 0.25m? ── yes ── reroute
   │ no
   ↓
publish cmd_vel(-0.05) × 3s  ──→ 15cm backup
odom 변화 < 3cm? ── yes ── gh.abort("stuck_during_backup")
   │ no
   ↓
retry++ — retry >= 3? ── yes ── reroute
   │ no
   ↓
send_goal(seg_target) (재시도)
```

### 새 토픽

- `/gogoping/proximity_event` (std_msgs/String JSON)
- `/odom` 구독 (stuck 감지)
- `/scan` 구독 (후방 clearance)
- `/cmd_vel` publish (backup 직접 송출 — nav2 cancel 후에만)
