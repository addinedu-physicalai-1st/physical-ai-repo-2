# BT_patrol_sub

빌드 시 받은 vertex 이름 list 를 순서대로 돌며 각 vertex 도착 시 카메라 좌우 sweep — 일종의 "둘러보기" 빌딩 블록. 추후 술래잡기 (`BT_hide_and_seek_sub`) 의 탐색 단계 등에서 재사용 예정.

본 SubTree 는 **building block** — FSM trigger 결선은 별도 (호출자가 책임). 본 PR 단계에선 단독 결선 없음.

## Root composite

`Sequence(memory=True)` — vertex 마다 동적으로 자식 1개 생성.

```
BT_patrol_sub (Sequence, memory=True)
  ├─ FailureIsSuccess "safe_visit_<A>"
  │     └─ Sequence "visit_<A>" (memory=True)
  │           ├─ SelectVertex     (select_<A>)   — BB.target_vertex_name = "<A>"
  │           ├─ NavigateToVertex (nav_<A>)      — graph_router /navigate_to_vertex
  │           └─ PanCameraSweep   (sweep_<A>)    — 90 → 30 → 150 → 90 (1.5s × 4)
  ├─ FailureIsSuccess "safe_visit_<B>"
  │     └─ Sequence "visit_<B>" …
  └─ FailureIsSuccess "safe_visit_<C>"
        └─ Sequence "visit_<C>" …
```

### Skip-on-failure 정책

각 visit Sequence 를 `FailureIsSuccess` decorator 로 감싸 한 vertex 의 nav 실패가 전체 순찰 중단을 일으키지 않게 함:

- vertex `B` 의 NavigateToVertex 가 FAILURE (경로 없음 / nav2 거부 / 잘못된 이름) → visit_B Sequence FAILURE → decorator 가 SUCCESS 로 보고 → root Sequence 가 다음 visit_C 진행.
- PanCameraSweep 은 publish 1회씩만 하므로 FAILURE 가 잘 나오지 않지만, 같은 보호 받음.

### 빈 list 거부

`build_patrol_sub(ctx, [])` 또는 `build_patrol_sub(ctx, ["A", "", "C"])` 는 `ValueError`. vertex 가 없는 순찰은 의미가 없으므로 빌드 시점에 fail-fast.

## 사용 behavior

- [common/select_vertex](../behaviors/common.md#select_vertex)  *(구현됨)*
- [navigation/navigate_to_vertex](../behaviors/navigation.md#navigate_to_vertex)  *(구현됨)*
- [follow/pan_camera_sweep](../behaviors/follow.md#pan_camera_sweep)  *(구현됨)*

신규 blackboard 키 / FSM trigger / ROS interface **없음**.

## Blackboard

| 키 | 접근 | 비고 |
|---|---|---|
| `target_vertex_name` | W (SelectVertex), R (NavigateToVertex) | 매 visit 마다 갱신. string literal — Keys 미등재 (NavigateToVertex.DEFAULT_TARGET_KEY 와 일치). |

## 빌더 시그니처

```python
from gogoping_modes.bt.trees.sub_trees.BT_patrol_sub import build_patrol_sub

root = build_patrol_sub(ctx, waypoints=["교실A", "운동장", "복도1"])
# → Sequence("BT_patrol_sub", memory=True) with 3 FailureIsSuccess children
```

| 인자 | 타입 | 설명 |
|---|---|---|
| `ctx` | `Context` | `ctx.camera_pan` 사용 (PanCameraSweep) |
| `waypoints` | `Sequence[str]` | vertex name list (waypoints.yaml 의 name). 빈 list / 빈 name reject. |

## 호출 흐름 (예정)

본 빌더는 현재 단독 코드 — 어디서 호출할지는 추후 결정. 가능 패턴:

- **HIDEANDSEEK 의 search 단계**: `BT_hide_and_seek_sub` 가 (nav → countdown → BT_patrol_sub → return) 형태로 조립.
- **단독 디버그 진입**: admin 측에서 SetGoal.srv 또는 별도 service 로 직접 트리거.

## 테스트

[tests/test_gogoping_patrol_subtree_builder.py](../../../../../tests/test_gogoping_patrol_subtree_builder.py) — 9 케이스:

- root: Sequence(memory=True), name='BT_patrol_sub'
- 자식 수 = vertex 수, 각 자식 = FailureIsSuccess
- 각 visit Sequence 안에 [Select, Nav, Sweep] 순서
- SelectVertex 의 vertex_name 매핑
- 빈 list / 빈 name reject
- name 에 vertex 포함 (admin UI tree_inspector 추적용)
