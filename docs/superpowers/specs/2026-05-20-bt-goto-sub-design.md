# Goto BT — 이동 SubTree 디자인 (carry → goto rename batch)

날짜: 2026-05-20
브랜치: `kang/feat-BT-lullaby-carry`
선행 작업: [`2026-05-20-lullaby-bt-design.md`](2026-05-20-lullaby-bt-design.md) — 자장가 SubTree (이번 작업의 `UIPublish` / `ui_event` 토픽을 제공)
관련 문서:
- [`controller/gogoping-controller/docs/subtree-flow.md`](../../../controller/gogoping-controller/docs/subtree-flow.md) — 5 SubTree 의사코드 (CarrySubTree 섹션 폐기 대상)
- [`controller/gogoping-controller/docs/state-bt.md`](../../../controller/gogoping-controller/docs/state-bt.md) — ASSIST TaskSelector 분기
- [`controller/gogoping-controller/docs/conventions.md`](../../../controller/gogoping-controller/docs/conventions.md) §4.1 — UIPublish 패턴
- [`controller/gogoping-controller/docs/nav-cancel-chain.md`](../../../controller/gogoping-controller/docs/nav-cancel-chain.md) — NavigateToVertex cancel 함정 3개

## 1. 배경

GogoPing 의 ASSIST state 는 교사 보조 task 3개 (carry / follow / lullaby) 로 구성. `carry` 는 원래 "짐 운반" 의미로 3 mode (manual / goto / follow) 분기 + 짐 떨어짐 감지 (LoadStabilityCheck) 를 가질 예정이었으나:

- **짐 감지 sensor 미보유** — Vic Pinky 하드웨어에 짐 무게/유무 sensor 없음. 발표 시점 추가 계획 없음. `LoadStabilityCheck` 가 stub 으로 항상 OK 리턴이면 무의미한 노드.
- **manual mode** 는 MANUAL state 의 `ManualTorqueHold` 와 사실상 중복. 짐 들고 사람이 직접 미는 시나리오는 MANUAL state 진입으로 처리.
- **follow mode** ("짐 들고 따라가기") 는 유치원 시나리오에서 use case 불명확. ASSIST 의 follow task 가 단독 추종 처리.

→ `carry` task / SubTree / mode 분기 / 짐 감지를 **전부 폐기**하고, 단순 "vertex 까지 이동" 동작으로 단순화. 동작 의미가 "운반" 이 아닌 "이동" 이라 이름도 **`goto`** 로 rename. 운반 시나리오는 user 가 `follow` task + `goto` task 를 **순차 chain** 하는 패턴 (composition).

> 본 변경은 [`controller/gogoping-controller/CLAUDE.md`](../../../controller/gogoping-controller/CLAUDE.md) 의 "변경 시 사용자 확인 필요" 항목 중 **BT 구조 변경** (SubTree 5개 중 1개 폐기 → 신규 SubTree 로 교체 + ASSIST TaskSelector vocabulary 변경) 카테고리에 해당. 사용자 본인 (코드베이스 소유자) 승인하에 진행.

현재 `_stubs/stub_carry.py` (StubRunningThenSuccess 30 tick) placeholder. 본 디자인이 실 구현 + rename batch 로 교체.

## 2. 목표 / 비목표

### 목표
- ASSIST 안에 `goto` task 추가 — `NavigateToVertex(destination_key)` 한 줄로 lane 따라 이동.
- 도착 시 UI 알림 ("도착했습니다") publish — `ui_event` 토픽 (자장가 작업이 깔아둠).
- ASSIST 의 TaskSelector 패턴 (lullaby/follow 와 동일) 을 따른다.
- `carry` 라는 task / 키 / 필드 / 매핑을 코드/docs 전체에서 일관되게 `goto` 로 rename.
- 같이 폐기되는 자산 (carry mode 분기 / 짐 감지 / 빈 패키지 / unused behavior) 정리.

### 비목표
- 짐 떨어짐 감지 (LoadStabilityCheck) — sensor 미보유. 후속에서도 추가 계획 없음.
- 음성 안내 (TTS) — UI 알림 dict publish 만. frontend 가 화면/오디오 처리.
- 도착 후 사용자 ack 대기 (`WaitForUserAck`) — 즉시 SUCCESS → IDLE. motor 정지 상태라 짐 하역 안전.
- 자유 좌표 (NavigateToPose) 지원 — vertex 이름 (graph_router) 만.
- carry 의 manual/follow mode 부활.
- `gogoping_carry/` 빈 패키지 활용 — carry 개념 자체가 사라지므로 잔류 의미 없음 (본 작업에서 삭제).

## 3. 아키텍처 (decision summary)

| 결정 | 값 | 이유 |
|---|---|---|
| task 이름 | `goto` (rename from `carry`) | 동작이 사실상 "vertex 이동" 이라 솔직한 이름. carry 라는 단어는 운반 시나리오의 user-level chain (follow+goto) 안에서만 의미. |
| SubTree root | `Sequence(memory=True)` | LullabySubTree 와 일관. 자식 2개 (NavigateToVertex + UIPublish) 의 단순 순차. mode 분기 / 백그라운드 perception 없음. |
| 목적지 지정 | `destination_key` (named vertex) | graph_router 다익스트라 → lane 따라 안전 이동. ReturnSubTree 와 동일 패턴. 자유 좌표 X (carry 는 안전 1순위). |
| 도착 알림 | `UIPublish(message={"event": "announce", "text": "도착했습니다"})` | hideseek 의 announce / 자장가 stop 과 같은 `ui_event` 토픽 패턴. fire-and-SUCCESS — 즉시 IDLE 복귀. |
| 도착 후 종료 정책 | SubTree SUCCESS → `assist_done` → IDLE | `WaitForUserAck` 도입 안 함 (단순성 우선). 짐 하역은 IDLE state 에서 (motor 정지 안전). |
| 신규 behavior | **0개** | NavigateToVertex (구현 ✅) + UIPublish (자장가 작업이 추가 ✅) 둘 다 기존 자산 조합. |
| 신규 blackboard 키 | **0개** | `destination_key` (기존, command_listener W) 만 사용. |
| 신규 FSM trigger | **0개** | `assist_request(task="goto")` — 기존 trigger, kwargs 값만 vocabulary 변경. |
| Goal.msg `carry_mode` 필드 | **삭제** | task=goto 가 되면 carry_mode 의미 자체가 없어짐. ROS msg 변경 — service / control-service / 빌드 캐시 영향. |

## 4. 변경 범위 (Scope)

### 4.1 신규 파일

| 파일 | 책임 |
|---|---|
| `controller/gogoping-controller/src/.../bt/trees/sub_trees/BT_goto_sub.py` | `build_goto_subtree(ctx)` — `Sequence(NavigateToVertex + UIPublish)` 리턴 |

### 4.2 rename / 수정 파일

| 파일 | 변경 |
|---|---|
| `controller/gogoping-controller/src/.../bt/trees/main_trees/BT_assist_main.py` | `carry_branch` → `goto_branch` (Sequence 이름 + CheckTask 값 + import + builder 호출). `StubCarry()` 제거, `build_goto_subtree(ctx)` 호출. docstring 의 task vocabulary 갱신. |
| `controller/gogoping-controller/src/.../bt/blackboard.py` | `Keys.CARRY_MODE` 상수 삭제. `Keys.LOAD_DROPPED` 상수 삭제. `_DEFAULTS` 에서 두 키 제거. `ASSIST_TASK` 의 코멘트 vocabulary 갱신 (`"carry"` → `"goto"`). 클래스 docstring "25개" → "23개". |
| `controller/gogoping-controller/src/.../bt/tree_inspector.py` | docstring 예시 (line 11, 17-18, 38, 153) — `carry` → `goto`, `StubCarry` → `BT_goto_sub`. 패턴 매칭 로직 (`BT_*_sub` 이름 기반) 은 그대로 작동. |
| `controller/gogoping-controller/src/.../bt/behaviors/common/command_listener.py` | line 122/132/278 의 `carry_mode` 처리 라인 삭제. line 163 `_ASSIST_SUB_TASKS = ("carry", "follow", "lullaby")` → `("goto", "follow", "lullaby")`. |
| `controller/gogoping-controller/src/.../utils/goal_reconciler.py` | `_ASSIST_TASKS` 값 `carry` → `goto`. `_CARRY_MODES` 상수 삭제. `_K_CARRY_MODE` 상수 삭제. line 109-117 의 carry-specific validation 블록을 goto-specific 으로 재작성 (`task == "goto"` 이고 `destination_key` 없으면 `"missing_destination"`). line 230-231 `if task == "carry": set(_K_CARRY_MODE, ...)` 블록 삭제. docstring/주석 vocabulary 갱신. |
| `controller/gogoping-controller/src/.../gogoping_msgs/msg/Goal.msg` | `string carry_mode` 필드 삭제. task 코멘트 vocabulary 갱신 (`carry` → `goto`). `carry+goto`, `carry+follow` 등 조합 표현 정리. |
| `controller/gogoping-controller/src/.../gogoping_msgs/srv/SetGoal.srv` | 에러 코드 주석: `"missing_carry_mode"` 라인 삭제. `"missing_destination"` 의 설명 (`carry+goto` → `task=goto`). `"missing_target_id"` 의 설명에서 `carry+follow` 제거. |
| `service/control-service/control_service/gogoping/mode_to_goal.py` | `carry_mode` dataclass field 삭제 (line 35). dict 변환에서 제거 (line 43). 예시/docstring 의 `task="carry", carry_mode="goto"` → `task="goto"` (line 5, 80-81). |
| `service/control-service/control_service/gogoping/ros_bridge.py` | line 195 `req.goal.carry_mode = goal.carry_mode` 삭제. |
| `service/control-service/control_service/gogoping/router.py` | line 56 docstring 의 task vocabulary 갱신. |
| `service/control-service/control_service/main.py` | line 248 코멘트의 `carry-goto` → `goto`. |
| `service/web-service/robot-web/src/gogoping/composables/useGogopingStateWs.ts` | line 37 `case 'carry': return '운반';` → `case 'goto': return '이동';` (한글 라벨도 함께 갱신). |

### 4.3 삭제 파일

| 파일 | 비고 |
|---|---|
| `controller/gogoping-controller/src/.../bt/behaviors/_stubs/stub_carry.py` | placeholder 제거 |
| `controller/gogoping-controller/src/.../bt/behaviors/_stubs/__init__.py` | `StubCarry` export 라인 제거 (`StubFollow` 는 유지 — follow 작업 진행 전) |
| `controller/gogoping-controller/src/gogoping/gogoping_carry/` | 빈 패키지 전체 (package.xml / setup.py / setup.cfg / `gogoping_carry/` 디렉토리) 삭제. carry 개념 자체가 사라지므로 잔류 의미 없음. |

### 4.4 테스트

| 파일 | 신규/수정 | 시나리오 |
|---|---|---|
| `tests/test_gogoping_goto_subtree_builder.py` | **신규** | 빌더 리턴이 `Sequence` · 자식 2개 (NavigateToVertex + UIPublish) · name="BT_goto_sub" · UIPublish 의 message dict 검증 (4 시나리오) |
| `tests/test_gogoping_goal_reconciler.py` (또는 기존 파일 수정) | **수정** | carry-related 시나리오 (carry/manual, carry/goto+missing_destination, carry/follow+missing_target_id) → goto-only 시나리오 (goto+missing_destination, goto+invalid_destination_key 는 NavigateToVertex 위임이라 reconciler 검증 아님). |
| `scripts/test.sh` | **수정** | goto subtree builder 테스트 명령 추가. carry 관련 테스트 명령 있으면 제거. |

### 4.5 문서 갱신 (같은 commit 으로)

| 문서 | 변경 |
|---|---|
| `controller/gogoping-controller/docs/subtree-flow.md` | CarrySubTree 섹션 (line 19-37) 전체 삭제 → GotoSubTree (Sequence + NavigateToVertex + UIPublish) 의사코드로 교체. 상단 표 (line 10) 의 carry+follow 행 삭제. line 102 의 카테고리 설명 갱신 (운반 → 이동 + composition 패턴). |
| `controller/gogoping-controller/docs/state-bt.md` | ASSIST TaskSelector (line 50) `CheckTask("carry") → CarrySubTree (stub)` → `CheckTask("goto") → BT_goto_sub (✅)`. |
| `controller/gogoping-controller/docs/blackboard-schema.md` | `assist_task` 값 vocabulary 갱신 (line 27). `carry_mode` 행 (line 29) 삭제. `load_dropped` 행 (line 43) 삭제. `destination_key` 설명에서 "carry goto" → "goto" (line 49). `Keys` 예시 (line 88, 96) 갱신. 초기값 표 (line 131-132) 갱신. |
| `controller/gogoping-controller/docs/bt/status.md` | Stubs 카운트 1/4 → 1/3 (stub_carry 삭제). Behaviors common 카운트 유지 (check_carry_mode 가 이미 ☐ 였음). perception 카운트 0/5 → 0/4 (load_stability_check 삭제). manual 카운트 1/3 → 1/1 (enable_manual_control, wait_for_exit 삭제). 합계 갱신. BT_carry_sub 행 (line 45) → `BT_goto_sub ✅` 로 교체. StubCarry 행 (line 58) 삭제. check_carry_mode 행 (line 79) 삭제. line 32 BT_assist_main 설명의 carry 분기 → goto. line 39 walking skeleton 설명의 carry → goto. line 171 admin UI 의 sub combo 옵션 carry → goto. |
| `controller/gogoping-controller/docs/bt/behaviors/common.md` | `check_carry_mode` 섹션 (line 143-) 삭제. command_listener 의 Blackboard write 키 목록 (line 18) 에서 `carry_mode` 제거. line 139 Used in 의 `carry/follow/lullaby` → `goto/follow/lullaby`. line 168 UIPublish 의 Used in 의 `BT_carry_sub` → `BT_goto_sub`. |
| `controller/gogoping-controller/docs/bt/behaviors/perception.md` | `load_stability_check` 항목 (line 11) 삭제. |
| `controller/gogoping-controller/docs/bt/behaviors/manual.md` | `(추후) carry 수동 모드 behaviors` 섹션 (line 25-30) 전체 삭제. |
| `controller/gogoping-controller/docs/gogoping-file-structure.md` | carry 관련 라인 (line 76-77, 80, 88, 91, 116, 124-125, 136-138, 158, 169, 178) 전부 — `BT_carry_sub` → `BT_goto_sub`, `(manual/goto/follow)` mode 표현 삭제, `check_carry_mode` / `enable_manual_control` / `wait_for_exit` / `load_stability_check` / `stub_carry.py` / `BT_carry_sub.py` 항목 정리. |
| `controller/gogoping-controller/docs/fsm-triggers.md` | `assist_request` 의 task 값 (line 21) `carry/follow/lullaby` → `goto/follow/lullaby`. line 21 의 "carry 시 carry_mode + destination_key, follow 또는 carry+follow 시 target_person_id" → "goto 시 destination_key, follow 시 target_person_id". line 88 `assist_request, task="carry"` → `task="goto"`. line 117 vocabulary 갱신. |
| `controller/gogoping-controller/docs/bt/trees/BT_carry_sub.md` | 파일 rename → `BT_goto_sub.md`. 내용 채움 (root composite + behavior 매트릭스 + trigger 매트릭스 + data flow 요약). |

## 5. 컴포넌트 상세

### 5.1 `BT_goto_sub` 빌더 (`bt/trees/sub_trees/BT_goto_sub.py` 신규)

```python
"""ASSIST 의 goto_branch 의 자식. NavigateToVertex + 도착 알림.

운반 시나리오는 user 가 follow task + goto task 를 순차 chain (composition).
이 SubTree 자체는 단일 이동 동작만 책임.

자세한 명세: docs/bt/trees/BT_goto_sub.md
"""
from __future__ import annotations

import py_trees

from ....context import Context
from ...behaviors.common.ui_publish import UIPublish
from ...behaviors.navigation.navigate_to_vertex import NavigateToVertex


_ARRIVAL_MSG = {"event": "announce", "text": "도착했습니다"}


def build_goto_subtree(ctx: Context) -> py_trees.behaviour.Behaviour:
    """name="BT_goto_sub" — tree_inspector 의 BT_*_sub 패턴 매칭 → admin UI BT SUB 영역 표시."""
    return py_trees.composites.Sequence(
        name="BT_goto_sub",
        memory=True,
        children=[
            NavigateToVertex("NavigateToVertex", ctx),  # destination_key 는 blackboard 에서 R
            UIPublish("AnnounceArrival", ctx, message=_ARRIVAL_MSG),
        ],
    )
```

- `Sequence(memory=True)` — NavigateToVertex SUCCESS 후 UIPublish 진행. NavigateToVertex FAILURE 면 UIPublish 건너뛰고 즉시 SubTree FAILURE.
- `_ARRIVAL_MSG` 는 모듈 상수 — 테스트 검증 용이. 자장가 spec 의 `PLAY_MSG`/`STOP_MSG` 패턴과 일관.
- `NavigateToVertex` 는 destination_key 를 blackboard 에서 직접 R (생성자 인자 X) — 기존 구현.

### 5.2 `BT_assist_main` 교체

```python
# 변경 전
from ...behaviors._stubs import StubCarry, StubFollow
from ..sub_trees.BT_lullaby_sub import build_lullaby_subtree
# ...
py_trees.composites.Sequence(
    name="carry_branch", memory=True,
    children=[
        CheckTask(Keys.ASSIST_TASK, "carry"),
        StubCarry(),    # STUB with build_carry(ctx)
    ],
),

# 변경 후
from ...behaviors._stubs import StubFollow         # StubCarry 제거
from ..sub_trees.BT_goto_sub import build_goto_subtree    # 신규
from ..sub_trees.BT_lullaby_sub import build_lullaby_subtree
# ...
py_trees.composites.Sequence(
    name="goto_branch", memory=True,
    children=[
        CheckTask(Keys.ASSIST_TASK, "goto"),
        build_goto_subtree(ctx),
    ],
),
```

모듈 docstring 의 TaskSelector 동작 설명 vocabulary 도 갱신 (`carry` → `goto`).

### 5.3 `goal_reconciler` validation 재작성

```python
# 변경 전 (line 70~117 발췌)
_ASSIST_TASKS = ("carry", "follow", "lullaby")
_CARRY_MODES = ("manual", "goto", "follow")
_K_CARRY_MODE = "carry_mode"

if mode == "ASSIST" and task == "carry":
    carry_mode = goal.get("carry_mode", "")
    if not carry_mode:
        return "missing_carry_mode"
    if carry_mode not in _CARRY_MODES:
        return "invalid_carry_mode"
    if carry_mode == "goto" and not goal.get("destination_key"):
        return "missing_destination"
    if carry_mode == "follow" and not goal.get("target_id"):
        return "missing_target_id"

# 변경 후
_ASSIST_TASKS = ("goto", "follow", "lullaby")
# _CARRY_MODES, _K_CARRY_MODE 상수 자체 삭제

if mode == "ASSIST" and task == "goto":
    if not goal.get("destination_key"):
        return "missing_destination"
```

`_apply_blackboard` (line 230-231) 의 `if task == "carry": blackboard.set(_K_CARRY_MODE, ...)` 블록은 통째로 삭제.

### 5.4 `Goal.msg` 변경

```
# 변경 전
string task             # "carry" / "follow" / "lullaby" / "hideseek" — mode=ASSIST/PLAY 시
string carry_mode       # "manual" / "goto" / "follow" — task=carry 시
string destination_key  # named_pose 키 — carry+goto 시
string target_id        # child_id / teacher_id — follow / hideseek / carry+follow 시

# 변경 후
string task             # "goto" / "follow" / "lullaby" / "hideseek" — mode=ASSIST/PLAY 시
# (carry_mode 필드 삭제)
string destination_key  # named_pose 키 — task=goto 시
string target_id        # child_id / teacher_id — follow / hideseek 시
```

상단 코멘트 (line 6) 의 `carry / follow / lullaby` 도 `goto / follow / lullaby` 로.

## 6. Data flow (end-to-end)

```
교사 (robot-web / admin UI) "교실A 로 가" 입력
  ↓ POST /api/gogoping/mode {mode: ASSIST, task: goto, destination_key: "교실A"}
control-service GogopingRosBridge
  ↓ SetGoal.srv → /gogoping/set_goal
command_listener._on_set_goal_request → goal_reconciler.reconcile()
  ├─ validate: task=goto + destination_key 비어있지 않음 → OK
  ├─ blackboard.assist_task = "goto"
  ├─ blackboard.destination_key = "교실A"
  └─ fsm.trigger("assist_request", task="goto")
FSM IDLE → ASSIST
  ↓ on_state_change callback (_pending_state 기록만)
main.py._tick 첫머리 → BT swap (build_main_tree("ASSIST", ctx))
  ↓ 다음 tick @ 10Hz
BT_assist_main → TaskSelector → goto_branch
  → CheckTask("goto") = SUCCESS
  → build_goto_subtree(ctx) → Sequence(NavigateToVertex + UIPublish)
       ↓ NavigateToVertex.initialise()
       send_goal_async → graph_router /navigate_to_vertex action
            ↓ 다익스트라 lane 경로 계산 → nav2 NavigateThroughPoses
       ↓ update() = RUNNING (도착 시 SUCCESS)

[... 이동 ...]

NavigateToVertex SUCCESS → UIPublish.update()
  ↓ ctx.ui.publish_event({"event": "announce", "text": "도착했습니다"})
       ↓
  /gogoping/ui_event (std_msgs/String JSON)
       ↓
  robot-web frontend subscribe → 화면 알림 표시
  ↓ UIPublish SUCCESS → Sequence SUCCESS → SubTree SUCCESS
SuccessOnSelected: TaskSelector SUCCESS → BT_assist_main root SUCCESS
  ↓ main.py._on_tree_success()
fsm.trigger("assist_done") → ASSIST → IDLE
  ↓ BT swap → BT_idle_main
  → 교사가 짐 하역 (motor 정지 상태, 안전) → 다음 명령 대기
```

## 7. 종료 경로 매트릭스

| 시나리오 | 발화 trigger | NavigateToVertex.terminate? | cmd_vel=0? | UIPublish 도착 알림? |
|---|---|---|---|---|
| 정상 도착 | NavigateToVertex 자연 SUCCESS | (SUCCESS 경로) | (도착이므로 자동) | ✅ "도착했습니다" |
| 사용자 "대기" (cancel) | `cancel` (ASSIST→IDLE) | ✅ INVALID → `_cancel_pending` flag → action cancel | ✅ | ❌ (Sequence 의 UIPublish 단계 도달 전 terminate) |
| 사용자 다른 task (follow/lullaby) | reconciler 가 `assist_task` 갱신 — TaskSelector(memory=False) 매 tick 재평가 → goto_branch RUNNING 끊김 | ✅ INVALID → action cancel | ✅ | ❌ |
| 사용자 "복귀" | `return_request` (ASSIST→RETURNING) | ✅ INVALID → action cancel | ✅ | ❌ |
| 배터리 ≤20% | `battery_low` (ASSIST→LOW_BATTERY_RETURN) | ✅ INVALID → action cancel | ✅ | ❌ |
| HW fault / 맵 이탈 | `fault` (ASSIST→ERROR) | ✅ INVALID → action cancel | ✅ | ❌ |
| 경로 불가 / nav2 abort | NavigateToVertex 자체 FAILURE → SubTree FAILURE → `_on_tree_failure()` → `return_request` → RETURNING | (FAILURE 경로) | ✅ | ❌ |
| `destination_key` 빈 값 / 잘못된 vertex | NavigateToVertex initialise 즉시 FAILURE (graph_router action reject) → 위와 동일 RETURNING 경로 | (FAILURE 경로) | (이동 시작 전) | ❌ |

**모든 cancel/fault 경로에서 cmd_vel=0 보장** — `nav-cancel-chain.md` 함정 3개 (NavTo race / `_on_state_change` reentrancy / async event loop orphan) 는 모두 `NavigateToVertex` 가 이미 처리. BT_goto_sub 측 추가 대응 불필요.

## 8. Testing

### 8.1 단위 — `tests/test_gogoping_goto_subtree_builder.py` (신규, 4 시나리오)

`Context` 를 `MagicMock` 으로 만들어 빌더 결과 검증:

1. `build_goto_subtree(ctx)` 가 `py_trees.composites.Sequence` 인스턴스 리턴
2. 자식 2개 — `NavigateToVertex` 와 `UIPublish` (타입 검증)
3. 이름이 `"BT_goto_sub"` (`tree_inspector` 의 `BT_*_sub` 매칭 보장)
4. `UIPublish` 의 `message` 인자가 `{"event": "announce", "text": "도착했습니다"}` 정확히 매치

### 8.2 단위 — `tests/test_gogoping_goal_reconciler.py` (수정)

기존 carry-related 시나리오 → goto-only 시나리오로 교체:

| 기존 시나리오 | 신규 시나리오 |
|---|---|
| `task=carry, carry_mode=""` → `"missing_carry_mode"` | (삭제) |
| `task=carry, carry_mode="invalid"` → `"invalid_carry_mode"` | (삭제) |
| `task=carry, carry_mode=goto, destination_key=""` → `"missing_destination"` | `task=goto, destination_key=""` → `"missing_destination"` |
| `task=carry, carry_mode=follow, target_id=""` → `"missing_target_id"` | (삭제 — follow task 만의 책임으로 남음) |
| `task=carry, carry_mode=goto, destination_key="X"` → accepted | `task=goto, destination_key="X"` → accepted, blackboard.destination_key="X" |

### 8.3 scripts/test.sh

```bash
pytest controller/gogoping-controller/src/gogoping/gogoping_modes/tests/test_gogoping_goto_subtree_builder.py -v
```

기존 `test_gogoping_carry_*.py` 명령이 있으면 제거 (현재 carry 단위테스트 파일 부재 — `grep test_*carry*` 결과 없음).

### 8.4 통합 — 수동 검증 (sim 환경)

1. `device-gogoping-sim.sh` 기동
2. `ros2 service call /gogoping/set_goal gogoping_msgs/srv/SetGoal "{goal: {mode: 'ASSIST', task: 'goto', destination_key: '교실A'}}"` → accepted=True
3. `ros2 topic echo /gogoping/cmd_vel` → 이동 명령 흐름 확인
4. `ros2 topic echo /gogoping/ui_event` → 도착 시 `{"event":"announce","text":"도착했습니다"}` 1회 확인
5. 도착 후 `/gogoping/state` snapshot 에서 fsm.current_state == "IDLE" 확인
6. admin UI BT SUB 영역에 `BT_goto_sub` 표시 확인
7. **cancel 시나리오**: 이동 중 admin UI "대기" → 즉시 cmd_vel=0 + state=IDLE
8. **잘못된 destination 시나리오**: `destination_key: '없는방'` → reconciler accepted=True (validation 통과), NavigateToVertex 가 graph_router 에서 reject 받아 FAILURE → RETURNING 진입

## 9. 위험 / 트레이드오프

| 위험 | 완화책 |
|---|---|
| ROS msg (`Goal.msg`) 변경으로 service / control-service 빌드 캐시 stale | `colcon build --packages-select gogoping_msgs` 후 control-service 재시작 필요. spec 검증 시 명시. |
| `gogoping_carry/` 빈 패키지 삭제 시 다른 launch / setup.py 의존 끊김 | grep 결과 의존 없음 (확인 완료). 삭제 후 `colcon list` 로 패키지 목록 검증. |
| carry 라는 task 이름을 외부 사용자 (교사/admin) 가 이미 학습 | 발표 전 단계라 외부 사용자 없음. admin UI / robot-web 의 한글 라벨 (`useGogopingStateWs.ts`) 도 같이 갱신 (`"운반"` → `"이동"`) 으로 일관성. |
| 자장가 PR 직후 같은 코드 영역 (`BT_assist_main.py`, `blackboard.py`) 건드림 — diff 충돌 위험 | 자장가 작업이 이미 merge 됨 (현재 working tree clean). carry rename batch 는 새 commit. 충돌 없음. |
| `task` field rename 도중 (PR 진행 중) 누가 admin UI 에서 carry 명령 발사하면 reconciler 가 `"invalid_task"` 리턴 | 발표 전 단계 + 본 batch 가 single commit (또는 small commit chain) 으로 atomic 처리. PR merge 시점에 일관성 확보. |
| UIPublish 가 fire-and-SUCCESS 라 도착 알림 전달 보장 X (frontend 가 ui_event 토픽 구독 안 했으면 알림 누락) | 자장가 작업이 이미 동일 패턴 사용. frontend 의 ui_event 구독은 별도 PR (`useGogopingStateWs.ts` 등 자장가 commit 에 포함). |

## 10. 추후 작업 (본 spec 밖)

- `gogoping_follow/` 빈 패키지도 follow task 본격 구현 시점에 동일 평가 (활용 가치 없으면 삭제).
- 도착 알림에 destination 정보 포함 (`{"event": "arrival", "destination_key": "<vertex>"}`) — 단순 announce 로 충분하면 X.
- 잘못된 vertex 이름 처리를 reconciler 단계에서 미리 검증 (waypoints 캐시 조회). 현재는 NavigateToVertex 단계 위임.
- `WaitForUserAck` behavior — UI "완료" 버튼 받아야 SUCCESS. 짐 하역 동안 ASSIST 유지가 필요해지면 추가.
- ASSIST 안에서 follow → goto 자동 chain (composition 자동화). 현재는 user 가 두 번 명령 발사.

## 11. 메모리 인덱스 정리 (본 batch 작업 완료 시)

`/home/leekt/.claude/projects/-home-leekt-pingdergarten/memory/` 의 두 메모리는 본 spec 의 구현 완료 시점에 stale — 후속 정리 항목:

- `project_carry_no_load_sensor.md` — "구현 완료 (LoadStabilityCheck 제외 결정 반영)" 로 갱신 또는 archive.
- `project_carry_goto_only.md` — "구현 완료 (goto rename batch 반영)" 로 갱신 또는 archive. blast radius 표는 본 spec §4 가 source of truth 가 됨.
- `MEMORY.md` 인덱스 — 두 항목 정리.
