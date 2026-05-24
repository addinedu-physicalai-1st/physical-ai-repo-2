# BT_hide_and_seek_sub

PLAY/hideseek 의 sub tree. **현재 구현: patrol 만** — vertex 목록을 받아 순회하며 각 vertex 에서 카메라 좌우 sweep. 진짜 hideseek (아이 인식 / FOUND 처리 / target_id 매칭) 은 추후 확장.

`BT_play_main` 의 `hideseek_branch` 안에서 `CheckTask(play_task=="hideseek")` 다음에 호출된다.

## Root composite

빌더 `build_hide_and_seek_sub(ctx)` 는 blackboard 의 `search_waypoints` 값에 따라 두 가지 중 하나를 반환:

| 조건 | 반환 |
|---|---|
| `search_waypoints` 가 비어있지 않음 | [`BT_patrol_sub`](BT_patrol_sub.md) (Sequence) |
| `search_waypoints` 빈 리스트 / 미설정 | `Failure` leaf (이름 = `BT_hide_and_seek_sub_no_waypoints`) |

정상 경로에선 [goal_reconciler](../../../src/gogoping/gogoping_modes/gogoping_modes/utils/goal_reconciler.py) 가 `missing_search_waypoints` 로 빈 리스트를 미리 거부 — `Failure` 분기는 ForceState 디버그 우회 시 방어용.

## 사용 behavior

직접 사용하는 behavior 는 없음 — 하위 [`build_patrol_sub`](BT_patrol_sub.md) 가 사용:
- [select_vertex](../behaviors/common.md#select_vertex)
- [navigate_to_vertex](../behaviors/navigation.md#navigate_to_vertex)
- [pan_camera_sweep](../behaviors/follow.md#pan_camera_sweep)

## blackboard 의존성

| Key | R/W | Note |
|---|---|---|
| `search_waypoints` | R | list[str]. 빌더가 빌드 시점에 1회 읽음. command_listener → goal_reconciler 가 W |
| `target_person_id` | (미사용) | 진짜 hideseek 확장 시 사용 예정. 현 빌더는 안 읽음 |

## 진입 / 종료 trigger

- 진입: 트리거 없음 — `BT_play_main` 의 selector 가 build 결과를 자식으로 직접 삽입.
- 종료: 자식 (patrol_sub) 의 SUCCESS/FAILURE 가 그대로 부모로 전파.

## 추후 확장 (TODO)

진짜 hideseek 구현 시 본 빌더는 다음과 같이 확장될 것:

```
Sequence(memory=True)
├─ build_patrol_sub(ctx, wps)      # 현재 단일 자식
├─ TargetRecognition(target_id)    # 추후 — 아이 얼굴 인식
├─ ApproachFound                   # 추후
└─ AnnounceFound                   # 추후
```

또는 `Parallel(FOUND 모니터링 + patrol)` 패턴. 본격 구현 시점에 결정.

## 상태

- 코드: ✅ ([BT_hide_and_seek_sub.py](../../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/sub_trees/BT_hide_and_seek_sub.py))
- 단위 테스트: ✅ [tests/test_gogoping_hide_and_seek_subtree_builder.py](../../../../../tests/test_gogoping_hide_and_seek_subtree_builder.py) (5 케이스)
- 자식 [BT_patrol_sub](BT_patrol_sub.md): ✅
- 진짜 hideseek 확장: ☐
