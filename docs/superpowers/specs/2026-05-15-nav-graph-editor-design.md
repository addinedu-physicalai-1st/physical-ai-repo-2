# Nav Graph Editor — Design Spec

- **작성일**: 2026-05-15
- **브랜치**: `kang/improve-nav-gragh`
- **관련 SR**: nav-graph 편집 기능 추가 (admin UI / server / graph_router_node)
- **목적**: 현재 yaml 직접 편집해야 했던 vertex/lane 그래프를 admin UI 에서 시각적으로 편집하고 실행 중인 graph_router 에 즉시 반영하는 기능 추가

## 배경

현재 graph routing 은 다음 yaml 두 개로 정의된다:

- `controller/gogoping-controller/src/gogoping/gogoping_navigation/config/waypoints.yaml` — vertex
- `controller/gogoping-controller/src/gogoping/gogoping_navigation/config/lanes.yaml` — lane (양방향 표준)

편집은 텍스트 에디터로 수동, 적용은 `graph_router_node` 재시작 필요. UI 에서 빠르게 그래프를 다듬으면서 즉시 검증하는 흐름을 만든다.

## 요구사항 — 기능 일람

| # | 기능 | 인터랙션 |
|---|---|---|
| 1 | 노드 추가 | 편집 모드 ON → 빈 곳 좌클릭-드래그 (화살표 = yaw) → release → 이름 입력 팝업 (`QInputDialog`) → Enter |
| 2 | 노드 취소 (undo) | 헤더 `[↶ 취소]` — 가장 최근 추가 한 개만 즉시 제거 (1-step). 기존 우클릭 "삭제" 와 별개 |
| 3 | 노드 이동 | 편집 모드 ON → 노드 좌클릭-드래그 → release → 화살표 yaw 미리보기 → 클릭으로 확정 / ESC 로 yaw 유지 |
| 4 | 간선 잇기 | 편집 모드 ON → 노드 짧은 좌클릭 (drag<12px) → 다른 노드 클릭 → lane 생성. 같은 노드 다시 / ESC → 취소 |
| 5 | 간선 끊기 | 편집 모드 ON → 간선 (회색선) 클릭 → 강조 → **Delete** 키 → 제거 |
| 6 | 자동 간선 | 헤더 `[⚡ 자동 간선]` 클릭 → 작은 dialog: threshold 입력칸 (기본 자동 추정값 미리 채움) + `[기존 lane 모두 교체]` 체크박스 → [확인] 으로 일괄 lane 생성 |
| 7 | 초기화 | 헤더 `[⟲ 초기화]` — `*.default.yaml` snapshot 으로 working 덮어쓰기 |
| 8 | 기본값 갱신 | 헤더 `[💾 기본값 갱신]` — 현재 working 을 `*.default.yaml` 로 동결 |
| 9 | 호버 하이라이트 | 편집 모드 ON 일 때, 마우스가 노드/간선 위에 있으면 강조 — 클릭 타겟 시각화 |

## 기존 동작의 변경

| 동작 | Before | After |
|---|---|---|
| 빈 곳 좌클릭/드래그 (graph 모드) | Nav2 Goal — `/waypoints/goto-pose` 호출 | **무동작** (편집 모드 OFF 일 때) |
| Shift+좌클릭-드래그 | `/waypoints/initialpose` (AMCL 재초기화) | **유지** |
| 노드 우클릭 메뉴 | 경로 미리보기 / graph navigate / 삭제 | **유지** (편집 모드 무관) |
| 사이드 리스트 클릭 | graph navigate | **유지** |
| 휠 클릭 드래그 / Ctrl+휠 | pan / zoom | **유지** |

`/waypoints/goto-pose` endpoint 자체는 유지 (별도 호출자 가능성). admin UI 의 호출만 제거.

## 아키텍처 결정

| 결정 | 내용 |
|---|---|
| A. 데이터 모듈 | lanes 도 `service/control-service/control_service/waypoints/yaml_store.py` 안에 함수 추가. 별도 모듈 분리 X |
| B. default snapshot | yaml 옆 sibling 파일 (`waypoints.default.yaml`, `lanes.default.yaml`). git 에 같이 commit |
| C. 편집 UI 위치 | `WaypointMapCard` 에 헤더 툴바로 확장. 새 화면 안 만듦. graph 모드일 때만 툴바 표시 |
| D. 그래프 동기화 | 편집 후 즉시 yaml write + `graph_router_node.reload_graph` ROS service 자동 호출 — node 재시작 불필요 |
| E. nav2 active 시 편집 | 편집 모드 진입 자체를 disable. 진입 후 active 가 시작되면 자동 이탈 |
| F. 단일 사용자 가정 | 다중 admin UI 동시 편집은 스코프 제외 (락 / CRDT 불필요) |

## 데이터 모델

### 파일 레이아웃

```
controller/gogoping-controller/src/gogoping/gogoping_navigation/config/
├── waypoints.yaml             # working copy
├── waypoints.default.yaml     # default snapshot (NEW)
├── lanes.yaml                 # working copy
└── lanes.default.yaml         # default snapshot (NEW)
```

### 스키마 (기존 그대로)

```yaml
# waypoints.yaml
waypoints:
  - {id: 1, name: "운동장11", x: 3.832, y: -3.18, yaw: 0.0}
patrols: {}

# lanes.yaml
lanes:
  - {from: "운동장11", to: "운동장12", bidirectional: true}
```

### `yaml_store.py` 확장

```python
# waypoints — 신규 함수
def update(name, x, y, yaw) -> Waypoint
def restore_default() -> int                    # *.default.yaml → working
def snapshot_default() -> None                  # working → *.default.yaml

# 기존 remove 동작 변경 — lane cascade 추가
def remove(name) -> list[Lane]:
    """노드 삭제 + 해당 노드 참여 lane 도 같이 제거.
    반환: 함께 제거된 lane 목록 (UI 가 confirm dialog 표시용)."""

# lanes — 신규 (현재 load_lanes 만)
@dataclass(frozen=True)
class Lane:
    from_: str
    to: str
    bidirectional: bool = True

def save_lanes(lanes: list[Lane]) -> None       # atomic write
def add_lane(from_, to, bidirectional=True) -> Lane
def remove_lane(from_, to) -> None              # 양방향이면 어느 방향이든 매칭
def restore_default_lanes() -> int
def snapshot_default_lanes() -> None

# undo (서버 메모리 — 프로세스 재시작 시 리셋)
# _RECENT_ADD 는 yaml_store 모듈 변수 — 단일 서버 프로세스 가정.
_RECENT_ADD: dict | None = None
def undo_last_add() -> Waypoint | None
```

### `Graph` (graph_router_node.py)

```python
self._reload_srv = self.create_service(
    Trigger, "/graph_router/reload_graph", self._on_reload
)

def _on_reload(self, req, resp):
    self._graph = Graph.from_yaml(self._wp_path, lanes_path=self._lanes_path)
    resp.success = True
    return resp
```

`Graph.from_yaml` 그대로 재사용. in-place 교체. 진행 중 routing 은 이미 발행된 path 따라 nav2 가 계속 진행. 다음 routing 부터 새 그래프 적용.

## REST API + ROS service

### 신규 endpoints

| 메서드 | 경로 | 용도 | body |
|---|---|---|---|
| `PATCH` | `/waypoints/{name}` | 노드 이동 | `{x, y, yaw}` |
| `POST` | `/waypoints/click` | 클릭으로 노드 추가 | `{name, x, y, yaw}` |
| `POST` | `/waypoints/undo` | 가장 최근 추가 1개 제거 | — |
| `POST` | `/waypoints/lanes` | 간선 잇기 (항상 `bidirectional=true`) | `{from, to}` |
| `DELETE` | `/waypoints/lanes` | 간선 끊기 | `{from, to}` |
| `POST` | `/waypoints/lanes/auto` | 자동 간선 | `{threshold, replace_existing?}` |
| `POST` | `/waypoints/reset` | 초기화 (default → working) | — |
| `POST` | `/waypoints/snapshot-default` | 기본값 갱신 (working → default) | — |
| `GET` | `/waypoints/health` | (확장) `nav_active: bool` 포함 | — |

**단방향 lane 은 UI 에서 미지원** — 기존 `lanes.yaml` 도 전부 `bidirectional: true` 라 일관성을 위해 신규 UI 는 양방향만 생성. 단방향이 필요하면 yaml 직접 편집.

### nav2 active 시 백엔드 거부 (방어층)

UI 가 막아도 다른 클라이언트 (REST 직접 호출) 가 우회할 수 있으므로 **모든 write endpoint 는 서버에서도 nav2 active 검증**:

```
nav_active=true 일 때 write 시도 → 409 nav_busy
```

UI 토스트 + 자동 편집 모드 이탈.

### 응답 표준

성공 시 200/201, body 에 새 상태 동봉:

```json
{
  "ok": true,
  "waypoints": [...],
  "lanes": [...]
}
```

SSE `{type:"waypoints"}` 이벤트를 자동 broadcast — 다른 클라이언트 자동 새로고침.

### 모든 write 가 묶어서 수행하는 후처리

```
1) yaml atomic write
2) graph_router_node /graph_router/reload_graph 호출
3) SSE broadcast
```

UI 는 한 endpoint 만 호출하면 됨.

### 부분 실패 (yaml ok, reload 실패)

응답 207:

```json
{
  "ok": false,
  "yaml_saved": true,
  "graph_reloaded": false,
  "detail": "reload_graph timeout"
}
```

UI 는 토스트 + 헤더에 영구 배너 "실시간 반영 실패 — graph_router 재시작 필요" 표시.

### ROS service (신규)

| service | type | 호출자 |
|---|---|---|
| `/graph_router/reload_graph` | `std_srvs/Trigger` | server (write endpoint 의 후처리 단계) |

## UI 상태머신

### MapView 의 편집 모드 상태 변수

```python
_edit_mode: bool
_edit_state: str
_pressed_node: str | None
_selected_node: str | None       # LINK_PENDING 의 1차 선택
_selected_lane: tuple[str, str] | None
_yaw_preview: dict | None        # {name, new_x, new_y}
_hover_target: dict | None       # {kind: "node"|"lane", id}
```

### 편집 모드 상태 전이 (편집 모드 ON 일 때만)

| state | mouse left press | mouse left release | mouse move | 키 |
|---|---|---|---|---|
| READY | 노드: → NODE_PRESSED · 간선: → LANE_SELECTED · 빈 곳: → EMPTY_PRESSED | — | hover 갱신 | — |
| NODE_PRESSED | — | drag<12px: → LINK_PENDING (`_selected_node = _pressed_node`)<br>drag≥12px: → NODE_DRAG → release → YAW_PREVIEW | drag≥12px: → NODE_DRAG | ESC → READY |
| NODE_DRAG | — | release: → YAW_PREVIEW (`new_x,y = end`) | drag preview | ESC → READY (취소) |
| YAW_PREVIEW | **press → yaw 확정** (PATCH) → READY | — | 화살표 yaw 실시간 회전 | ESC → yaw 유지·위치만 PATCH → READY |
| LINK_PENDING | 다른 노드: lane 생성 → READY · 같은 노드: 취소 → READY · 빈 곳: 취소 → READY | — | hover 갱신 | ESC → READY |
| LANE_SELECTED | 다른 곳 click: 새 분기 | — | hover 갱신 | Delete → 끊기·READY · ESC → READY |
| EMPTY_PRESSED | — | drag<12px: → READY (무동작)<br>drag≥12px: → ADD_DRAG → release → 이름 팝업 | drag≥12px: → ADD_DRAG | ESC → READY |
| ADD_DRAG | — | release: 이름 팝업 → POST → READY | drag preview | ESC → READY (팝업 cancel 도 동일) |

### 편집 모드 진입/이탈 규칙

| 트리거 | 결과 |
|---|---|
| [편집 모드] 토글 클릭 | health 호출 → `nav_active=false` 면 진입, true 면 거부 + 토스트 |
| SSE `goal_status: active` 수신 | 진행 중 selection 모두 reset → 자동 이탈 + 알림 |
| [편집 모드] 다시 클릭 | 이탈 |
| READY 상태에서 ESC 두 번 | 이탈 (단축키) |

### Hit testing

- 노드: 마우스 widget 좌표 ↔ 노드 widget 좌표 거리 < `NODE_HIT_PX` (16px)
- 간선: 선분과의 perpendicular distance < `LANE_HIT_PX` (8px) **AND** lane 위 투영점이 양 끝 사이
- 노드 hit > 간선 hit (겹치면 노드)

### 시각 피드백

| 상태 | 표시 |
|---|---|
| 편집 모드 ON | 헤더 옆 배너 "✏ 편집 모드 — ESC 두 번으로 종료" |
| hover 노드 | 테두리 굵게 + 진한 파랑 |
| hover 간선 | 회색 → 검정 굵게 |
| LINK_PENDING 1차 선택 | 큰 링 강조 + 마우스까지 점선 |
| LANE_SELECTED | 코랄색 굵게 + "Delete 키로 끊기" hint |
| NODE_DRAG | 반투명 노드 마우스 따라감 + 원위치 점선 |
| YAW_PREVIEW | 노드 안착 + 노드→마우스 화살표 + "클릭=확정 / ESC=yaw 유지" hint |
| ADD_DRAG | 보라색 화살표 (add 모드 구분) |

## 동시성 & 에러 처리

### nav2 active 처리

| 시점 | 처리 |
|---|---|
| [편집 모드] 클릭 시점 | health 호출 → `nav_active=true` 면 진입 거부 + 토스트 |
| 편집 중 active 시작 | SSE 수신 → 진행 중 drag/selection reset → 자동 이탈 + 알림 |

### 데이터 무결성

| 동작 | 처리 |
|---|---|
| 노드 추가 — 이름 중복 | 409 → 팝업 재표시 |
| 노드 삭제 | 기존 patrol 검증 + **lane cascade** (자동 제거). UI 가 "연결된 lane N 개 함께 제거" 확인 dialog |
| 노드 이동 (PATCH) | rename 아니라 참조 깨지지 않음. validate 만 통과 |
| 간선 잇기 — 이미 있음 (양방향 매칭) | 409 `lane_exists` |
| 간선 끊기 — 없는 쌍 | 404 |

### undo 한계

| 상황 | 처리 |
|---|---|
| undo 한 노드가 이미 lane 에 잇혀짐 | 409 `node_has_lanes`. 사용자가 lane 먼저 끊기 또는 우클릭 "삭제" 사용 |
| 서버 재시작 | `_RECENT_ADD` 리셋 → [↶ 취소] disable |
| 두 번째 undo | 408 `nothing_to_undo` |

### default snapshot 생애주기

| 상황 | 처리 |
|---|---|
| `*.default.yaml` 부재 (clean checkout) | [초기화] 버튼 disable + tooltip "[기본값 갱신] 으로 만들어 주세요" |
| **첫 PR 에 default 파일 같이 commit** | 현재 working yaml 복사본을 default 로 git 에 넣음 |
| [기본값 갱신] | 확인 dialog: "노드 N / 간선 M 개 기본값으로 동결. 되돌릴 수 없음" |
| [초기화] | 확인 dialog: "편집 결과 버리고 기본값으로 복구. 되돌릴 수 없음" |

### 자동 간선 멱등성

| 동작 | 처리 |
|---|---|
| 같은 threshold 두 번 | dedup 결과 동일. 응답 `{added: 0, skipped: N}`, "변경 없음" 토스트 |
| `replace_existing=false` (기본) | 기존 lane 보존, threshold 이하 새 쌍만 추가 |
| `replace_existing=true` (체크박스) | 기존 모두 제거 후 재생성 |
| threshold 기본값 | 노드 간 평균 거리의 median — UI 측 추정 후 미리 채움 |

### REST 호출 실패 정책

| HTTP code | 처리 |
|---|---|
| 2xx | 응답 body 의 새 상태로 UI 즉시 반영 |
| 4xx | `detail` 을 토스트로 표시. UI 상태 변경 안 함 |
| 5xx / network error | 토스트 "서버 오류 — 잠시 후 다시 시도". 5초 후 GET `/waypoints` 로 새로고침 |

### 테스트 격리

| 환경변수 | 용도 |
|---|---|
| `PINGDER_WAYPOINTS_FILE` | 기존 — waypoints.yaml monkeypatch |
| `PINGDER_LANES_FILE` (신규) | lanes.yaml monkeypatch |
| `PINGDER_WAYPOINTS_DEFAULT_FILE`, `PINGDER_LANES_DEFAULT_FILE` (신규) | default snapshot 경로 |

## 테스트 전략

기존 [scripts/test.sh](../../../scripts/test.sh) 가 단일 진입점. 새 테스트는 모두 거기에 등록.

### 단위 테스트

| 파일 | 범위 |
|---|---|
| `tests/test_yaml_store_lanes.py` (NEW) | `add_lane / remove_lane / save_lanes / 양방향 매칭 / validate / atomic write` |
| `tests/test_yaml_store_node_edit.py` (NEW) | `update / remove cascade / undo_last_add / restore_default / snapshot_default` |
| `tests/test_graph_auto_edge.py` (NEW) | `auto_edge(waypoints, threshold)` 순수 함수 — dedup, threshold 경계, replace_existing |

### 통합 테스트

| 파일 | 범위 |
|---|---|
| `tests/test_router_lanes.py` (NEW) | FastAPI TestClient — 모든 신규 endpoint 의 path / 응답 / bridge 호출 검증. reload 실패 → 207 |
| `tests/test_graph_router_reload.py` (NEW) | rclpy — `/graph_router/reload_graph` 호출, vertex 수 비교 |

### UI 테스트

| 파일 | 범위 |
|---|---|
| `tests/test_waypoint_map_card_edit.py` (NEW) | pytest-qt — 편집 모드 토글, 상태머신 전이 (LINK_PENDING / NODE_DRAG / YAW_PREVIEW / LANE_SELECTED / ADD_DRAG), 각 endpoint 호출 검증, SSE active 자동 이탈 |

### [scripts/test.sh](../../../scripts/test.sh) 추가

```bash
pytest tests/test_yaml_store_lanes.py
pytest tests/test_yaml_store_node_edit.py
pytest tests/test_graph_auto_edge.py
pytest tests/test_router_lanes.py
pytest tests/test_graph_router_reload.py
pytest tests/test_waypoint_map_card_edit.py
```

### 수동 QA 체크리스트

- [ ] sim 띄우고 admin UI 에서 편집 모드 토글 → 노드 추가/이동/간선 잇기·끊기/자동 간선 한 사이클
- [ ] 편집 후 graph_router 재시작 없이 새 vertex 로 navigate 성공
- [ ] nav2 이동 중 편집 모드 진입 거부 확인
- [ ] 이동 시작 시 편집 모드 자동 이탈 확인
- [ ] [초기화] 후 working == default 확인
- [ ] [기본값 갱신] 후 default 파일 변경 확인

## 비스코프 (이번 PR 에서 안 함)

- 노드 **이름 변경** (rename) — 후속 PR. cascade (lanes / patrols) 처리 필요해서 별도
- 노드 **다중 선택** + 일괄 동작
- 무제한 undo / redo 스택 (현재는 1-step undo 만)
- 다중 admin UI 동시 편집 (CRDT / 락)
- 자동 간선의 **벽 통과 검사 (LoS)** — 맵 raster 스캔 필요해 복잡. v2
- 노드 추가 시 자동 lane 연결 (kNN / nearest auto-link)
- robot-web 등 다른 클라이언트에서의 그래프 편집

## 후속 SR 후보 (지금 안 함, 메모만)

- graph 모드의 **빈 곳 좌클릭 → nearest vertex graph routing** (이번엔 "무동작" 으로 결정. 일관성 개선 필요시 별도 SR)
- 노드 이름 변경 (rename)
- 자동 간선 — LoS 또는 Delaunay
- patrol 편집 UI

## 파일 변경 요약 (구현 시 영향 범위)

| 파일 | 변경 종류 |
|---|---|
| `service/control-service/control_service/waypoints/yaml_store.py` | 확장 (lanes / update / undo / default snapshot) |
| `service/control-service/control_service/waypoints/router.py` | 신규 endpoint 9개 + health 확장 |
| `service/control-service/control_service/waypoints/ros_bridge.py` | `reload_graph` 서비스 클라이언트 + `nav_active` 노출 |
| `controller/gogoping-controller/src/gogoping/gogoping_navigation/gogoping_navigation/graph_router_node.py` | `reload_graph` 서비스 추가 |
| `controller/gogoping-controller/src/gogoping/gogoping_navigation/gogoping_navigation/graph.py` | `auto_edge(threshold)` 함수 추가 (순수 함수) |
| `controller/gogoping-controller/src/gogoping/gogoping_navigation/config/waypoints.default.yaml` | 신규 (working 복사본) |
| `controller/gogoping-controller/src/gogoping/gogoping_navigation/config/lanes.default.yaml` | 신규 (working 복사본) |
| `app/admin-app/widgets/waypoint_map_card.py` | 대규모 확장 — 편집 모드 토글, 상태머신, hover, hit-test, 신규 헤더 툴바, 이름 팝업, 확인 dialog |
| `tests/test_yaml_store_lanes.py` | 신규 |
| `tests/test_yaml_store_node_edit.py` | 신규 |
| `tests/test_graph_auto_edge.py` | 신규 |
| `tests/test_router_lanes.py` | 신규 |
| `tests/test_graph_router_reload.py` | 신규 |
| `tests/test_waypoint_map_card_edit.py` | 신규 |
| `scripts/test.sh` | 6개 라인 추가 |
