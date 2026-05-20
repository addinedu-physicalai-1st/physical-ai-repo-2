# Nav Debug Log — `/gogoping/debug/nav_events`

cancel chain (SetGoal → reconcile → FSM → BT swap → NavTo → graph_router → nav2) 의
어느 단계에서 끊겼는지 실시간 추적용 일회성 디버깅 스트림. ros2 logger 와 별도 —
admin UI 의 NavDebugLogCard 화면에 한 줄씩 색상으로 표시.

## 토픽 명세

- **이름**: `/gogoping/debug/nav_events`
- **타입**: `std_msgs/msg/String`
- **QoS**: depth=20 (publisher), depth=20 (control-service subscriber). burst 안 잃게.
- **payload**: JSON 한 줄
  ```json
  {
    "ts": 1779252188.553,
    "source": "NavTo",
    "level": "info",
    "msg": "send → '충전소입구'"
  }
  ```

| 필드 | 타입 | 의미 |
|---|---|---|
| `ts` | float | epoch sec (publisher 의 `time.time()`) |
| `source` | str | event source — 한 글자 정렬 + 색상 매핑용 |
| `level` | str | `"info"` / `"warn"` / `"err"` |
| `msg` | str | free-form text |

## Publisher 9곳

| source | 위치 | event 종류 |
|---|---|---|
| `SetGoal` | [command_listener.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/command_listener.py) `_on_set_goal_request` | UI/voice 가 mode 요청 시 |
| `reconcile` | 동일 (`reconcile()` 결과 후) | goal reconciler 가 발사한 FSM trigger + accepted 여부 |
| `FSM` | [main.py](../../src/gogoping/gogoping_modes/gogoping_modes/main.py) `_on_state_change` | state 변경 (transitions 라이브러리 콜백) |
| `BT swap` | 동일, `_tick` 첫머리 | deferred BT swap 실행 시점 (state change 후 ≤100ms) |
| `NavTo` | [navigate_to_vertex.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/navigation/navigate_to_vertex.py) | `send` / `gh accepted` / `gh rejected` / `race cancel via pending flag` / `terminate(INVALID)` / `SUCCESS` / `FAILURE` |
| `graph_rt` | [graph_router_node.py](../../src/gogoping/gogoping_navigation/gogoping_navigation/graph_router_node.py) `_act_navigate` | `act_navigate start` / `nav2 goal accepted` / `abort: <reason>` / `client cancel → nav2 cancel` / `nav2 cancel ack` / `SUCCESS` / `orphan nav_gh canceled in finally` (★ 좀비 발생 시 표시) |

## 사용

### admin UI (PyQt5)
- GogoPing 대시보드 우측 DebugDrawer (▸ 토글) 의 네 번째 카드 "Nav Debug Log"
- 자동 scroll / Clear 버튼
- source 별 색상: SetGoal=cyan, FSM=yellow, BT swap=orange, NavTo=green, graph_rt=red-ish
- level=warn → amber, level=err → red 로 강조

### CLI (admin UI 안 띄울 때)
```bash
export ROS_DOMAIN_ID=<할당된 ID>
ros2 topic echo /gogoping/debug/nav_events
```

또는 control-service WS 직접:
```bash
# python websockets
python3 -c "
import asyncio, websockets
async def main():
    async with websockets.connect('ws://localhost:8000/ws/nav-debug-events') as ws:
        while True: print(await ws.recv())
asyncio.run(main())
"

# 또는 wscat
npx wscat -c ws://localhost:8000/ws/nav-debug-events
```

## 진단 매트릭스 — cancel chain 어디서 끊겼나

| 못 보이는 첫 event | 끊긴 지점 |
|---|---|
| `[SetGoal]` | admin UI / robot-web 이 SetGoal 자체를 안 보냄 |
| `[reconcile] accepted=False` | reconciler 거부 — 현재 state 가 명령 못 받음 (LOW_BATTERY_RETURN lockdown 등) |
| `[FSM]` | `transitions` trigger 실패 (invalid trigger 등) |
| `[BT swap]` (FSM 만 보임) | main thread `_tick` 멈춤 |
| `[NavTo terminate]` (BT swap 까진 있음) | 트리 `root.stop(INVALID)` 가 NavTo 까지 전파 안 됨 |
| `[graph_rt client cancel]` (NavTo terminate 보임) | `cancel_goal_async` 가 graph_router 에 도달 못함 (이미 종료된 goal — 정상일 수도) |
| `[graph_rt nav2 cancel ack]` (forward 는 보임) | nav2 가 cancel 처리 못함 — recovery loop 의심 |
| `[graph_rt orphan canceled in finally]` 가 보임 | **graph_router 의 `_act_navigate` 가 비정상 종료** — `try/finally` safety net 이 nav_gh orphan cancel. 정상 종료 경로가 아니므로 root cause 추가 진단 필요 |

## 자세한 cancel 시퀀스
[../nav-cancel-chain.md](../nav-cancel-chain.md).
