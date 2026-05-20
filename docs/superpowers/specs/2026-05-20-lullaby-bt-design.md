# Lullaby BT — 자장가 SubTree 디자인

날짜: 2026-05-20
브랜치: `kang/feat-BT-lullaby-carry`
관련 문서:
- [`controller/gogoping-controller/docs/subtree-flow.md`](../../../controller/gogoping-controller/docs/subtree-flow.md) — 5 SubTree 의사코드
- [`controller/gogoping-controller/docs/bt/trees/BT_lullaby_sub.md`](../../../controller/gogoping-controller/docs/bt/trees/BT_lullaby_sub.md) — 트리별 상세 (본 작업이 채움)
- [`controller/gogoping-controller/docs/conventions.md`](../../../controller/gogoping-controller/docs/conventions.md) §4.1 — UIPublish 패턴

## 1. 배경

GogoPing 의 ASSIST state 안에 3 task — carry / follow / **lullaby**. lullaby 는 교사가
울거나 잠 안 자는 아이를 달랠 때 자장가 mp3 를 틀어주는 보조 작업. 현재
`_stubs/stub_lullaby.py` (StubInfiniteRunning) 으로 placeholder 상태. 본 디자인이
실 구현으로 교체.

## 2. 목표 / 비목표

### 목표
- mp3 재생 시작/정지를 BT 의 lullaby SubTree 가 책임진다 (재생 자체는 frontend).
- 사용자가 "대기" / 다른 모드 / "복귀" 등 어떤 종료 경로를 타든 mp3 정지 신호가
  반드시 publish 되어야 한다 (frontend 가 영원히 자장가 재생하는 사고 방지).
- ASSIST 의 TaskSelector 패턴 (carry/follow 와 동일) 을 따른다.
- 같이 만드는 범용 `UIPublish` (즉시 SUCCESS) 는 추후 hideseek 의 announce /
  countdown_start / "찾았다!" 등에 재사용 가능해야 한다.

### 비목표
- 로봇 자체 스피커로 재생 (이번 범위 외, frontend mp3 element 가 재생).
- 자장가 곡 선택 UI / 여러 곡 라이브러리 (`lullaby.mp3` 한 곡 하드코딩).
- 자동 종료 (시간 기반 / 아이 잠들면 감지 등) — 무한 RUNNING, 외부 trigger 만 종료.
- robot-web frontend 의 `<audio>` element 코드 — 별도 PR.
- 자장가 재생 중 카메라 pan / 베이스 motion (정지 유지).

## 3. 아키텍처 (decision summary)

| 결정 | 값 | 이유 |
|---|---|---|
| SubTree root | 단일 `LullabyAudio` behavior (composite 없음) | "publish 시작 + 영구 RUNNING + publish 종료" 한 책임이라 트리 구성 불필요. over-engineering 회피 |
| publish 채널 | 신규 토픽 `/gogoping/ui_event` (`std_msgs/String` JSON) | `/gogoping/state` 는 1Hz snapshot 이라 lullaby_play 시작에 최대 1s 지연. 일회성 이벤트용 별도 토픽 분리 |
| stop publish 책임 | `LullabyAudio.terminate()` 에 응집. `_stop_published` flag 로 idempotent | terminate 가 RUNNING 자식의 cleanup 보장 — main.py 의 `root.stop(INVALID) + tree.shutdown()` 패턴이 보장 |
| 종료 조건 | 외부 trigger 만 (cancel / *_request / battery_low / fault) | "자장가 완료" 라는 자연스러운 종료점 없음. 시간 기반 자동 종료는 과한 추상화 |
| mp3 경로 | BT 에 하드코딩 (`AUDIO_SRC = "lullaby.mp3"`) | 곡 선택 UI 없음. SetGoal msg 에 audio 필드 추가도 over-engineering |
| 로봇 motion | 없음 (cmd_vel 미발행) | BT_assist_main 의 monitor 들만 RUNNING. ManualTorqueHold 도 미배치 → 자장가 중 motor enable 유지 (사용자가 따로 들어 옮기지 않음) |
| `UIPublish` (범용) | 같이 추가 — 즉시 SUCCESS | hideseek 의 announce 류와 자장가 stop 같은 1회성 publish 가 다수 예상. 이번 작업에 같이 |
| `UIPublish` 의 message 전달 | 빌더 시점에 dict 리터럴 | 자장가는 dict 가 정해져 있음. carry/hideseek 등 동적 메시지가 필요해질 때 callable 인자 옵션 검토 (지금은 X) |

## 4. 변경 범위 (Scope)

### 4.1 새/수정 파일

| 파일 | 변경 | 책임 |
|---|---|---|
| `controller/gogoping-controller/src/.../interfaces/ui_publisher.py` | **수정** | `publish_event(message: dict)` 메서드 + `TOPIC_EVENT = "ui_event"` publisher 추가 |
| `controller/gogoping-controller/src/.../bt/behaviors/common/ui_publish.py` | **신규** | `UIPublish(name, ctx, *, message: dict)` — `update()` 가 `ctx.ui.publish_event(message)` 호출 후 즉시 `SUCCESS` |
| `controller/gogoping-controller/src/.../bt/behaviors/common/lullaby_audio.py` | **신규** | `LullabyAudio(name, ctx)` — initialise=play publish, update=영구 RUNNING, terminate=stop publish (idempotent) |
| `controller/gogoping-controller/src/.../bt/trees/sub_trees/BT_lullaby_sub.py` | **신규** | `build_lullaby_subtree(ctx)` — `LullabyAudio(name="BT_lullaby_sub", ctx)` 리턴 |
| `controller/gogoping-controller/src/.../bt/trees/main_trees/BT_assist_main.py` | **수정** | `StubLullaby()` → `build_lullaby_subtree(ctx)` 교체, import 정리 |
| `controller/gogoping-controller/src/.../bt/behaviors/_stubs/stub_lullaby.py` | **삭제** | placeholder 제거 |
| `controller/gogoping-controller/src/.../bt/behaviors/_stubs/__init__.py` | **수정** | `StubLullaby` export 라인 제거 |

### 4.2 테스트

| 파일 | 신규/수정 | 시나리오 |
|---|---|---|
| `tests/test_gogoping_lullaby_audio.py` | **신규** | initialise→play publish · update RUNNING · terminate→stop publish · idempotent stop · re-entry 시 flag 리셋 · publish_event 인자 검증 (6 시나리오) |
| `tests/test_gogoping_ui_publish.py` | **신규** | update=SUCCESS · publish_event 1회 호출 · idempotent · 임의 message dict 통과 (4 시나리오) |
| `tests/test_gogoping_lullaby_subtree_builder.py` | **신규** | 빌더 리턴 타입 / name="BT_lullaby_sub" 검증 (2 시나리오) |
| `scripts/test.sh` | **수정** | 위 3 테스트 명령 추가 |

### 4.3 문서 갱신 (같은 commit 으로)

| 문서 | 변경 |
|---|---|
| `controller/gogoping-controller/docs/bt/trees/BT_lullaby_sub.md` | TBD placeholder → 완전 채움 (root composite + behaviors + trigger 매트릭스) |
| `controller/gogoping-controller/docs/bt/behaviors/common.md` | `ui_publish` *(스켈레톤)* → *(구현됨)* 갱신, `lullaby_audio` 섹션 신규 추가 |
| `controller/gogoping-controller/docs/bt/status.md` | Trees SubTree 1/5 → 2/5, common 7/11 → 9/11, Behaviors 13/34 → 15/34, 합계 63/94 → 65/94 |
| `controller/gogoping-controller/docs/gogoping-file-structure.md` | `ui_publish` 에 (✅), `lullaby_audio` 항목 추가, `BT_lullaby_sub.py` 에 (✅) |
| `controller/gogoping-controller/docs/subtree-flow.md` | LullabySubTree 의 의사코드 → 실 구현 노트 추가 ("PlayAudio + WaitForStopCommand 두 단계는 LullabyAudio 한 노드에 응집") |
| `controller/gogoping-controller/docs/state-bt.md` | ASSIST 의 LullabySubTree (stub) → ✅ |

## 5. 컴포넌트 상세

### 5.1 `UIPublisher.publish_event()` (`interfaces/ui_publisher.py` 수정)

```python
class UIPublisher:
    TOPIC_STATE = "state"        # 기존 (1Hz BT snapshot)
    TOPIC_EVENT = "ui_event"     # 신규 (1회성 이벤트)
    QOS_DEPTH = 1

    def __init__(self, node):
        self.node = node
        self._pub = node.create_publisher(String, self.TOPIC_STATE, self.QOS_DEPTH)
        self._event_pub = node.create_publisher(String, self.TOPIC_EVENT, self.QOS_DEPTH)

    def publish_state(self, snapshot: dict) -> None:        # 기존 그대로
        msg = String()
        msg.data = json.dumps(snapshot, ensure_ascii=False)
        self._pub.publish(msg)

    def publish_event(self, message: dict) -> None:          # 신규
        """일회성 UI 이벤트 publish — frontend 가 audio/announce 등 처리."""
        msg = String()
        msg.data = json.dumps(message, ensure_ascii=False)
        self._event_pub.publish(msg)
```

- 토픽 경로: namespace `gogoping` 자동 prefix → `/gogoping/ui_event`
- QoS depth=1 (latched 아님). 1회성 메시지라 누적 안 함
- JSON `ensure_ascii=False` — 한국어 announce 텍스트 보존

### 5.2 `UIPublish` (`bt/behaviors/common/ui_publish.py` 신규)

```python
class UIPublish(py_trees.behaviour.Behaviour):
    """message dict 1회 publish 후 즉시 SUCCESS — 범용 알림 behavior."""

    def __init__(self, name: str, context: Context, *, message: dict):
        super().__init__(name)
        self.ctx = context
        self._message = message

    def update(self) -> Status:
        self.ctx.ui.publish_event(self._message)
        return Status.SUCCESS

    def terminate(self, new_status: Status) -> None:
        # 즉시 SUCCESS 이므로 진행 중 자원 없음 — no-op
        pass
```

- `message` 는 빌더 시점에 dict 리터럴로 고정 (예: `{"event": "announce", "text": "찾았다!"}`)
- 추후 hideseek 의 SearchAndAnnounce / CountdownWithAudio 에서 재사용

### 5.3 `LullabyAudio` (`bt/behaviors/common/lullaby_audio.py` 신규)

```python
class LullabyAudio(py_trees.behaviour.Behaviour):
    """자장가 SubTree 본체.

    initialise()  — lullaby_play event publish (mp3 시작 신호)
    update()      — 영구 RUNNING (외부 trigger 가 BT swap 으로 종료)
    terminate()   — lullaby_stop event publish (idempotent, _stop_published flag)
    """

    AUDIO_SRC = "lullaby.mp3"  # robot-web 정적 리소스 이름 (frontend 가 해석)

    PLAY_MSG = {"event": "lullaby_play", "src": AUDIO_SRC, "loop": True}
    STOP_MSG = {"event": "lullaby_stop"}

    def __init__(self, name: str, context: Context):
        super().__init__(name)
        self.ctx = context
        self._stop_published = False

    def initialise(self) -> None:
        # 재진입 가능 — flag 리셋 후 새로 play publish
        self._stop_published = False
        self.ctx.ui.publish_event(self.PLAY_MSG)

    def update(self) -> Status:
        return Status.RUNNING

    def terminate(self, new_status: Status) -> None:
        if self._stop_published:
            return
        self.ctx.ui.publish_event(self.STOP_MSG)
        self._stop_published = True
```

- `_stop_published` flag — `terminate()` 가 여러 번 호출돼도 stop publish 는 한 번만
- `initialise()` 가 flag 리셋 → 같은 인스턴스 재사용 (Selector(memory=False) 재진입) 시 정상 동작
- `PLAY_MSG` / `STOP_MSG` 는 클래스 상수 — 테스트에서 검증 용이

### 5.4 `BT_lullaby_sub` 빌더 (`bt/trees/sub_trees/BT_lullaby_sub.py` 신규)

```python
def build_lullaby_subtree(ctx: Context) -> py_trees.behaviour.Behaviour:
    """ASSIST 의 lullaby_branch 의 자식. 단일 LullabyAudio 리턴.

    name="BT_lullaby_sub" — tree_inspector 의 BT_*_sub 패턴 매칭 → admin UI BT SUB 영역 표시.
    """
    return LullabyAudio(name="BT_lullaby_sub", context=ctx)
```

- 단일 behavior 만 리턴 (Sequence/Parallel 없음) — over-engineering 회피
- 이름이 `BT_*_sub` 패턴이라 admin UI SUB 영역에 자동으로 잡힘

### 5.5 `BT_assist_main` 교체

```python
# 변경 전
from ...behaviors._stubs import StubCarry, StubFollow, StubLullaby
# ...
children=[
    CheckTask(Keys.ASSIST_TASK, "lullaby"),
    StubLullaby(),  # STUB
],

# 변경 후
from ...behaviors._stubs import StubCarry, StubFollow         # StubLullaby 제거
from ..sub_trees.BT_lullaby_sub import build_lullaby_subtree  # 신규
# ...
children=[
    CheckTask(Keys.ASSIST_TASK, "lullaby"),
    build_lullaby_subtree(ctx),
],
```

## 6. Data flow (end-to-end)

```
사용자 (robot-web / admin UI) "자장가" 클릭
  ↓ POST /api/gogoping/mode {mode: ASSIST, task: lullaby}
control-service GogopingRosBridge
  ↓ SetGoal.srv → /gogoping/set_goal
command_listener._on_set_goal_request → goal_reconciler.reconcile()
  ├─ blackboard.assist_task = "lullaby"
  └─ fsm.trigger("assist_request", task="lullaby")
FSM IDLE → ASSIST
  ↓ on_state_change callback
main.py._on_state_change → BT swap (build_main_tree("ASSIST", ctx))
  ↓ 다음 tick @ 10Hz
BT_assist_main → TaskSelector → lullaby_branch
  → CheckTask("lullaby") = SUCCESS
  → build_lullaby_subtree(ctx) → LullabyAudio(name="BT_lullaby_sub")
       ↓ initialise() 1회
       ctx.ui.publish_event({event: "lullaby_play", src: "lullaby.mp3", loop: true})
            ↓
       /gogoping/ui_event (std_msgs/String JSON)
            ↓
       robot-web frontend subscribe → <audio src="lullaby.mp3" loop> 재생
       ↓ update() = RUNNING (외부 trigger 까지 지속)

[... 시간 흐름 ...]

사용자 "대기" 클릭 → SetGoal mode=IDLE
  ↓ reconciler → fsm.trigger("cancel") → ASSIST → IDLE
main.py._on_state_change → BT swap
  ├─ tree.root.stop(INVALID) — RUNNING 자식 모두 terminate(INVALID)
  │    └─ LullabyAudio.terminate(INVALID)
  │         ↓
  │       ctx.ui.publish_event({event: "lullaby_stop"})
  │            ↓
  │       /gogoping/ui_event → robot-web → <audio>.pause()
  └─ tree.shutdown() + 새 BT_idle_main 빌드
```

## 7. 종료 경로 매트릭스

| 시나리오 | 발화 trigger | LullabyAudio.terminate? | stop publish? |
|---|---|---|---|
| 사용자 "대기" | `cancel` (ASSIST→IDLE) | ✅ INVALID | ✅ |
| 사용자 다른 모드 (carry/follow) | reconciler 가 `assist_task` 갱신 — same ASSIST, TaskSelector 가 다른 branch → lullaby_branch RUNNING 끊김 | ✅ INVALID | ✅ |
| 사용자 "복귀" | `return_request` (ASSIST→RETURNING) | ✅ INVALID | ✅ |
| 배터리 ≤20% | `battery_low` (ASSIST→LOW_BATTERY_RETURN) | ✅ INVALID | ✅ |
| HW fault / 맵 이탈 | `fault` (ASSIST→ERROR) | ✅ INVALID | ✅ |
| 다른 active mode (PLAY/MANUAL) | `play_request`/`manual_request` | ✅ INVALID | ✅ |

**모든 종료 경로에서 stop publish 보장** — `main.py._build_tree_for_state` 가 BT swap 시
`root.stop(INVALID)` + `tree.shutdown()` 호출하므로 RUNNING 자식의 `terminate()` 가 전파됨.
이는 `ManualTorqueHold` 의 torque ON 복원과 동일한 메커니즘.

## 8. Testing

### 8.1 단위 — `tests/test_gogoping_lullaby_audio.py` (신규, 6 시나리오)

`Context` 를 `MagicMock` 으로 만들어 `ctx.ui.publish_event` 호출 검증:

1. `initialise()` 후 `publish_event(PLAY_MSG)` 1회 호출
2. `update()` 가 항상 `Status.RUNNING` 리턴 (10회 반복 검증)
3. `terminate(INVALID)` 시 `publish_event(STOP_MSG)` 1회 호출
4. `terminate(...)` 두 번 호출해도 stop publish 는 1회 (idempotent)
5. `initialise → terminate → initialise → terminate` 시 stop 도 두 번 (flag 가 initialise 에서 리셋)
6. `update()` 호출 횟수 무관 publish_event(PLAY) 는 initialise 에서만 (call_count 검증)

### 8.2 단위 — `tests/test_gogoping_ui_publish.py` (신규, 4 시나리오)

1. `update()` 한 번 만에 `Status.SUCCESS`
2. `ctx.ui.publish_event(message)` 정확히 1회 호출 with 같은 dict
3. `initialise()` 가 idempotent (publish_event call_count 영향 없음)
4. 다른 `message` 인스턴스로 만들면 그 메시지가 정확히 전달됨

### 8.3 빌더 — `tests/test_gogoping_lullaby_subtree_builder.py` (신규, 2 시나리오)

1. `build_lullaby_subtree(ctx)` 가 `LullabyAudio` 인스턴스 리턴
2. 이름이 `"BT_lullaby_sub"` 인지 (`tree_inspector` 의 `BT_*_sub` 매칭 보장)

### 8.4 scripts/test.sh

3 개 신규 테스트 명령 추가:
```bash
pytest controller/gogoping-controller/src/gogoping/gogoping_modes/tests/test_gogoping_lullaby_audio.py -v
pytest controller/gogoping-controller/src/gogoping/gogoping_modes/tests/test_gogoping_ui_publish.py -v
pytest controller/gogoping-controller/src/gogoping/gogoping_modes/tests/test_gogoping_lullaby_subtree_builder.py -v
```

### 8.5 통합 — 발표 데모 (수동)

ROS 통합은 별도 수동 검증 (sim 환경):
1. `device-gogoping-sim.sh` 기동
2. admin UI 또는 `ros2 service call /gogoping/set_goal ...` 로 자장가 진입
3. `ros2 topic echo /gogoping/ui_event` → `lullaby_play` 메시지 1회 확인
4. admin UI "대기" 클릭 → `lullaby_stop` 메시지 1회 확인
5. admin UI BT SUB 영역에 `BT_lullaby_sub` 표시 확인
6. robot-web frontend 의 audio element 실제 재생/정지 — 본 작업 범위 외 (별도 PR)

## 9. 위험 / 트레이드오프

| 위험 | 완화책 |
|---|---|
| frontend 가 `lullaby_play` 못 받으면 mp3 안 켜짐 (BT 는 RUNNING) | frontend 가 `/gogoping/ui_event` 구독 추가는 별도 PR — 본 작업은 BT side 만. ROS topic echo 로 검증 가능. frontend 미구현 상태에서도 BT 는 정상 동작 (publish 만 함). |
| 노드 crash 시 `terminate()` 호출 안 되어 frontend 가 영원히 재생 | node crash → ROS DDS 가 publisher 연결 끊김 감지 → frontend 가 토픽 끊김 timeout 으로 자동 정지. 본 처리는 frontend 책임. |
| publish_event 가 매번 새 JSON 직렬화 — 성능? | self_audio 진입/종료 시 각 1회만. 무시할 수준. |
| BT swap 직후 LullabyAudio.initialise 가 호출되지 않는 경우 (composite 안에서 SUCCESS 처리되어 skip 등) | TaskSelector(memory=False) + lullaby_branch Sequence(memory=True) + CheckTask 통과 시 LullabyAudio 가 tick → 처음이면 initialise 호출. py_trees 표준 동작 — `BT_return_sub` 와 같은 패턴 (이미 검증). |

## 10. 추후 작업 (본 spec 밖)

- robot-web frontend 가 `/gogoping/ui_event` 구독 + audio element 재생 — 별도 PR
- 자장가 곡 라이브러리 / UI 선택 — 본 spec 의 SetGoal msg 확장 결정 후
- 자장가 중 카메라 pan 느린 흔들기 (분위기 연출) — 별도 behavior 추가 가능
- 운반 BT (carry SubTree) — 별도 spec, 본 작업 직후 동일 흐름으로 진행
