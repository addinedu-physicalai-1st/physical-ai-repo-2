# patrol behaviors

PATROL(순찰 빌딩블록) 모드 전용 leaf.

각 항목 — *(스켈레톤)* 표시는 아직 코드 구현 전.

---

## select_vertex  *(구현됨)*

고정된 vertex 이름을 `blackboard.target_vertex_name` 에 W 한 뒤 즉시 SUCCESS. NavigateToVertex 가 같은 키를 R 하므로 SubTree 빌드 시 vertex 마다 `SelectVertex → NavigateToVertex` Sequence 를 동적으로 생성하면 N 개 vertex 순회 가능.

| 항목 | 값 |
|---|---|
| Blackboard | W: `target_vertex_name` (string literal, NavigateToVertex.DEFAULT_TARGET_KEY 와 일치) |
| 인자 | `name`, `vertex_name`, `target_key="target_vertex_name"` |
| Status | SUCCESS (즉시) |
| terminate | no-op |
| Used in | BT_patrol_sub — 각 `visit_<vertex>` Sequence 의 첫 자식. 추후 BT_hide_and_seek_sub 의 search 단계에서도 동일 패턴 가능. |
| 파일 | [`bt/behaviors/patrol/select_vertex.py`](../../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/patrol/select_vertex.py) |
| 테스트 | [tests/test_gogoping_select_vertex.py](../../../../../tests/test_gogoping_select_vertex.py) — 5 케이스 (SUCCESS / BB write / overwrite / multi-instance no conflict / custom_target_key) |

```python
visit_A = py_trees.composites.Sequence("visit_A", memory=True, children=[
    SelectVertex("select_A", vertex_name="A"),
    NavigateToVertex("nav_A"),
    PanCameraSweep("sweep_A", ctx),
])
```
