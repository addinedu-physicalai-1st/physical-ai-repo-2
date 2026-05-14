# Graph Routing

Vertex 그래프 + 다익스트라로 lane 따라 이동. nav2 의 `NavigateThroughPoses` 위에 한 층.

## 데이터 (어디 적나)

`device/gogoping_ws/src/gogoping/gogoping_navigation/config/`
| 파일 | 용도 |
|---|---|
| [waypoints.yaml](../src/gogoping/gogoping_navigation/config/waypoints.yaml) | vertex 정의: `id, name, x, y, yaw` flat list |
| [lanes.yaml](../src/gogoping/gogoping_navigation/config/lanes.yaml) | 양방향 lane: `from, to, bidirectional` (사용자 직접 정의 — 자동 생성 X) |

좌표계는 [maps/map.yaml](../src/gogoping/gogoping_navigation/maps/map.yaml) 와 동일 (origin `[-11, -9, 0]`, resolution 0.025). yaw 라디안.

## 실행 노드

`graph_router_node` — [gogoping_navigation/graph_router_node.py](../src/gogoping/gogoping_navigation/gogoping_navigation/graph_router_node.py)
시작 시 두 yaml 로드 → 그래프 만들고 `/gogoping/odom` 구독.

```bash
ros2 launch gogoping_navigation graph_router.launch.xml
# 옵션: odom_topic:=/odom  follow_action:=/navigate_through_poses  frame_id:=map
```

device-gogoping-pi.sh / device-gogoping-sim.sh 가 이 launch 를 tmux window 로 자동 기동.

## 어디에서 어떻게 호출하나 (호출자별)

### A. BT (Behavior Tree) — 가장 일반적

[gogoping_modes/bt/behaviors/navigation/navigate_to_vertex.py](../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/navigation/navigate_to_vertex.py)

py_trees Behaviour. blackboard 에 `target_vertex_name` 만 세팅하면 됨.

```python
from gogoping_modes.bt.behaviors.navigation.navigate_to_vertex import NavigateToVertex

# Sequence 안에서:
nav = NavigateToVertex()  # default: target_key="target_vertex_name"
# nav.setup(node=context.node)  # main.py 의 BT 초기화 시
```

상태:
- `RUNNING` — 이동 중
- `SUCCESS` — 도착
- `FAILURE` — vertex 없음 / 경로 없음 / nav2 거부 / 취소 (`feedback_message` 에 사유)

terminate(INVALID) 시 진행 중 goal 자동 cancel.

### B. ROS service / action 직접 호출

서비스: `/graph_router/route` ([RouteToVertex.srv](../src/gogoping/gogoping_msgs/srv/RouteToVertex.srv)) — 시각화/디버깅용. 로봇 안 움직임.
```bash
ros2 service call /graph_router/route gogoping_msgs/srv/RouteToVertex \
    "{target_name: '운동장11', start: {x: 0.0, y: 0.0, z: 0.0}}"
# start (0,0,0) → 현재 odom 사용
```

액션: `/graph_router/navigate_to_vertex` ([NavigateToVertex.action](../src/gogoping/gogoping_msgs/action/NavigateToVertex.action)) — 실제 이동.
```bash
ros2 action send_goal /graph_router/navigate_to_vertex \
    gogoping_msgs/action/NavigateToVertex "{target_name: '운동장11'}" --feedback
```

### C. REST (외부 — UI / 스크립트)

[server/control/waypoints/router.py](../../../../server/control/waypoints/router.py)

| Endpoint | 용도 |
|---|---|
| `POST /waypoints/route {name}` | 경로 시퀀스만 반환 (시각화/디버깅) |
| `POST /waypoints/navigate {name}` | 실제 이동 — graph routing |
| `GET /waypoints` | vertex + lanes 목록 (admin UI 시각화용) |
| `GET /waypoints/events` (SSE) | `route_progress` 이벤트 — 현재 통과 vertex |

server 의 [ros_bridge.py](../../../../server/control/waypoints/ros_bridge.py) 가 ROS service/action client 보유. `route_to(name)` (동기) / `navigate_to_vertex(name, goal_id)` (비동기 + SSE).

### D. robot-ui 음성/텍스트 (보조 모드)

[ui/robot-ui/src/composables/useVoiceController.ts](../../../../ui/robot-ui/src/composables/useVoiceController.ts) + [server/ai/hub.py](../../../../server/ai/hub.py)

```
"고고핑 운동장11로 가"
   ↓ STT
robot-ui → POST /api/voice/intent
   ↓
server/ai/hub.py 분류기 (_try_goto_vertex)
   ↓ 응답
{kind: "goto_vertex", name: "운동장11"}
   ↓
robot-ui handler → POST /waypoints/navigate {name: "운동장11"}
   ↓
(이하 C 와 동일)
```

- 보조 모드의 `restrictedVoiceMode` 우회 키워드: `"로 가|로 이동|에 가|로 갑|에 갑|로 갈|에 갈| 가자| 가줘"` 또는 `"복귀|돌아가|돌아와|충전소|충전 ?하러"`
- vertex name 매칭 실패 시 LLM chat fallback (분류기 내부)

### E. Admin UI (PyQt) 사용자 인터랙션

[ui/admin-ui/widgets/waypoint_map_card.py](../../../../ui/admin-ui/widgets/waypoint_map_card.py)

- **graph map 모드** — lanes 회색선 자동 표시
- **vertex 좌클릭** → graph navigate (실제 이동)
- **vertex 우클릭** → 메뉴: 경로 미리보기 / graph navigate / 강조 해제 / 삭제

## 핵심 모듈 (순수 파이썬)

[gogoping_navigation/graph.py](../src/gogoping/gogoping_navigation/gogoping_navigation/graph.py) — rclpy 무관.
- `Graph.from_yaml(waypoints_path, lanes_path=None)` — lanes_path 있으면 그것 사용, 없으면 거리 기반 자동 (테스트용)
- `Graph.nearest_vertex(x, y) -> name` — (x, y) 와 가장 가까운 vertex
- `Graph.route(src_name, dst_name) -> [name, ...]` — 다익스트라 결과
- `Graph.lanes() -> [(from, to, distance), ...]` — 시각화용

테스트: [tests/test_graph.py](../../../../tests/test_graph.py) (14 case, scripts/test.sh 등록)

## 데이터 변경 시 워크플로우

| 변경 | 영향 |
|---|---|
| `waypoints.yaml` 좌표 수정 | 다익스트라 가중치만 바뀜. lane 자체는 유지. graph_router 재시작만 |
| `waypoints.yaml` vertex 추가/삭제 | lanes.yaml 의 from/to 검증 필요 (없으면 GraphError). 재시작 |
| `lanes.yaml` lane 추가/삭제 | 다익스트라 결과 즉시 반영. 재시작 |
| 경로가 마음에 안 들면 | 다익스트라가 거리 동률일 때 임의 선택 → 우회로 lane 을 lanes.yaml 에서 제거 |

## 한계

- **lane 그래프 = 정해진 통로만**. lane 위에 일시 장애물 (사람 등) 은 nav2 의 local costmap 회피 (수~수십 cm). 큰 우회는 안 됨
- **vertex 좌표가 통로 중앙에 있어야** nav2 가 lane 따라감. vertex 가 벽 가까우면 nav2 가 밀어냄
- **odom 기반 nearest_vertex** — sim spawn / AMCL initial pose 가 의도한 vertex 근처에 있어야 출발점이 맞음

## 시각화 검증

`/tmp/graph_visualize.png`, `/tmp/graph_manual.png` 같은 PNG 로 admin UI 띄우지 않고 lane/route 검증 가능. 스크립트는 일회성.

```bash
python3 -c "
import sys; sys.path.insert(0, 'device/gogoping_ws/src/gogoping/gogoping_navigation')
from gogoping_navigation.graph import Graph
from pathlib import Path
g = Graph.from_yaml(Path('device/gogoping_ws/src/gogoping/gogoping_navigation/config/waypoints.yaml'),
                    lanes_path=Path('device/gogoping_ws/src/gogoping/gogoping_navigation/config/lanes.yaml'))
print(g.route('출입구1', '운동장22'))
"
```
