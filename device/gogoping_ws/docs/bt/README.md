# BT Docs

py_trees 기반 GogoPing Behavior Tree — 트리/behavior 별 상세 문서.

## 구조

| 경로 | 내용 |
|---|---|
| [status.md](status.md) | **구현 체크리스트** — 트리/behavior 별 ✅ / 🟡 / ☐ |
| [behaviors/](behaviors/) | 카테고리별 behavior 명세 (입출력 blackboard, 액션/서비스, 사용 예) |
| [trees/](trees/) | 각 트리의 root composite 구조 + 사용하는 behavior 목록 + 진입/종료 trigger |

[../gogoping-file-structure.md](../gogoping-file-structure.md) 는 폴더 트리 + 한 줄 요약 (overview), 본 디렉토리는 상세 (semantics).

## Behaviors (카테고리별 한 파일)

| 파일 | 카테고리 |
|---|---|
| [behaviors/common.md](behaviors/common.md) | battery / hardware monitor, command_listener, ui_publish 등 공통 |
| [behaviors/navigation.md](behaviors/navigation.md) | nav2 / graph_router 호출 (navigate_to_pose, **navigate_to_vertex**, docking 등) |
| [behaviors/perception.md](behaviors/perception.md) | gogoping_vision 토픽 → blackboard 어댑터 (yolo / face / load stability) |
| [behaviors/follow.md](behaviors/follow.md) | 카메라 pan + 추종 (face tracking, sweep, raise) |
| [behaviors/manual.md](behaviors/manual.md) | 수동 모드 carry (manual control / wait_for_exit) |
| [behaviors/recovery.md](behaviors/recovery.md) | 안전 정지 + alert + log (BT_error_main 전용) |

## Trees

| 파일 | 트리 |
|---|---|
| [trees/BT_idle_main.md](trees/BT_idle_main.md) | IDLE state — 명령 대기 + battery 감시 |
| [trees/BT_assist_main.md](trees/BT_assist_main.md) | ASSIST — TaskSelector → carry/follow/lullaby + return_command listener |
| [trees/BT_play_main.md](trees/BT_play_main.md) | PLAY — TaskSelector → hideseek + return_command listener |
| [trees/BT_charging_main.md](trees/BT_charging_main.md) | CHARGING — battery_full 감지 + 도킹 접점 감시 |
| [trees/BT_returning_main.md](trees/BT_returning_main.md) | RETURNING — BT_return_sub 호출 |
| [trees/BT_error_main.md](trees/BT_error_main.md) | ERROR — terminal (StopAll → Notify → Log) |
| [trees/BT_carry_sub.md](trees/BT_carry_sub.md) | 운반 — manual / goto / follow 3 mode |
| [trees/BT_follow_sub.md](trees/BT_follow_sub.md) | 추종 — 정상 ↔ Loss Recovery |
| [trees/BT_lullaby_sub.md](trees/BT_lullaby_sub.md) | 자장가 — UI mp3 재생, WaitForExit |
| [trees/BT_hide_and_seek_sub.md](trees/BT_hide_and_seek_sub.md) | 숨바꼭질 1회 (숨기 → 카운트 → 탐색 → 복귀) |
| [trees/BT_return_sub.md](trees/BT_return_sub.md) | 도킹 복귀 시퀀스 (NavTo → Align → Approach → Verify) |

## 컨벤션 — 새 기능 추가 시

1. **behavior 추가** → 해당 카테고리 .md (`behaviors/<category>.md`) 에 섹션 추가:
   - 한 문장 요약 / blackboard read·write 키 / 호출 액션·서비스 / 사용 트리 (Used in:)
   - 호출 패턴이 비표준이거나 외부 의존이 있으면 코드 예시도 (그렇지 않으면 생략)
2. **트리 추가/변경** → `trees/<tree_name>.md`:
   - root composite (Sequence / Selector / Parallel) 구조
   - 자식 노드 목록 + 각각이 어느 behavior 호출하는지
   - 진입 / 종료 trigger (FSM transition 도)
3. **[file-structure.md](../gogoping-file-structure.md) 한 줄 요약 + 링크 갱신**
   - `→ docs/bt/behaviors/<category>.md#<anchor>` 형식
4. **[status.md](status.md) 의 ☐ → ✅ / 🟡** 변경
5. 같은 commit 으로 모두 — 코드 변경과 문서 분리 금지
