# 코딩 컨벤션 (gogoping_modes)

`fsm` / `bt` / `interfaces` 구현자들이 따르는 공통 패턴. **두 번째 behavior 짜기 전에 이 문서 한 번 읽고 시작.**

---

## 1. `context.py` — 공유 객체 저장소

ROS Node / FSM 인스턴스 / interfaces 인스턴스 / 로거를 하나의 dataclass 로 묶어 모든 behavior 에 주입.

```python
# gogoping_modes/context.py
from dataclasses import dataclass
import rclpy.node

from .fsm.robot_fsm import RobotFSM
from .interfaces.nav2_client import Nav2Client
from .interfaces.camera_pan_client import CameraPanClient
from .interfaces.ui_publisher import UIPublisher
from .interfaces.battery_subscriber import BatterySubscriber
from .interfaces.collision_subscriber import CollisionSubscriber
from .interfaces.db_logger import DBLogger


@dataclass
class Context:
    node: rclpy.node.Node      # 로깅 / 파라미터 / 새 client 생성용
    fsm: RobotFSM              # state 전이 (trigger 호출)
    # interfaces
    nav2: Nav2Client
    camera_pan: CameraPanClient
    ui: UIPublisher
    battery: BatterySubscriber
    collision: CollisionSubscriber
    db_logger: DBLogger
```

> **규칙**
> - `Context` 는 **불변** — 부팅 시 1회 생성 후 필드 추가/교체 금지
> - behavior 는 `Context` 의 필드를 **참조만** 한다 (예: `self.context.nav2.send_goal(...)`)
> - Blackboard 는 `Context` 에 두지 않는다 — py_trees 의 전역 blackboard 를 노드별 `attach_blackboard_client()` 로 접근

## 2. Behavior 구현 패턴

### 2.1 생성자: Context 주입 + blackboard 권한 등록

```python
# bt/behaviors/common/battery_low_monitor.py
import py_trees
from py_trees.common import Status, Access
from gogoping_modes.bt.blackboard import Keys
from gogoping_modes.context import Context


class BatteryLowMonitor(py_trees.behaviour.Behaviour):
    LOW_ENTER = 20.0   # 진입 임계
    LOW_EXIT = 25.0    # 진출 (hysteresis)

    def __init__(self, name: str, context: Context):
        super().__init__(name)
        self.ctx = context
        self.bb = self.attach_blackboard_client(name=name)
        self.bb.register_key(key=Keys.BATTERY_LEVEL, access=Access.READ)
        self._fired = False  # edge-triggered

    def update(self) -> Status:
        level = self.bb.get(Keys.BATTERY_LEVEL)
        if not self._fired and level <= self.LOW_ENTER:
            self.bb.set(Keys.ERROR_SOURCE, self.name)  # multi-writer 추적
            self.ctx.fsm.trigger("battery_low")
            self._fired = True
        elif self._fired and level >= self.LOW_EXIT:
            self._fired = False  # hysteresis 복귀
        return Status.RUNNING    # monitor 는 항상 RUNNING
```

### 2.2 외부 호출은 반드시 `interfaces/` 거쳐서

```python
# bt/behaviors/navigation/navigate_to_pose.py
class NavigateToPose(py_trees.behaviour.Behaviour):
    def __init__(self, name: str, context: Context, target_key: str):
        super().__init__(name)
        self.ctx = context
        self.target_key = target_key  # blackboard key 이름
        self.bb = self.attach_blackboard_client(name=name)
        self.bb.register_key(key=target_key, access=Access.READ)
        self._goal_handle = None

    def initialise(self):
        pose_name = self.bb.get(self.target_key)
        self._goal_handle = self.ctx.nav2.send_goal(pose_name)  # 비동기 시작

    def update(self) -> Status:
        return self.ctx.nav2.poll_status(self._goal_handle)     # RUNNING / SUCCESS / FAILURE

    def terminate(self, new_status: Status):
        if new_status != Status.SUCCESS and self._goal_handle:
            self.ctx.nav2.cancel(self._goal_handle)              # cleanup
        self._goal_handle = None
```

> **규칙**
> - rclpy 의 `Node` / publisher / action client 를 behavior 안에서 **직접 만들지 않는다** — 반드시 `interfaces/` 의 client 클래스로 캡슐화
> - `terminate(new_status)` 는 **idempotent** — 여러 번 호출되어도 안전. 진행 중 외부 작업 (Nav2 액션 등) 은 여기서 cancel
> - 시간 측정은 `time.time()` 사용 (tick count 의존 금지). `initialise()` 에서 시작 시각 기록.

## 3. `main.py` 와 BT swap 루프

FSM state 가 바뀌면 그에 맞는 MainTree 로 교체. py_trees `BehaviourTree` 의 `setup → tick → shutdown` lifecycle 활용.

## ROS namespace 규약

`gogoping_modes` 노드는 **namespace `gogoping`** 으로 띄운다:

```python
node = rclpy.create_node("gogoping_modes", namespace="gogoping")
```

interfaces / behaviors 의 topic / service / action 이름은 **모두 상대 path** 로
적는다 (예: `"state"`, `"set_goal"`, `"release_torque"`). namespace 가 자동으로
prefix 해서 `/gogoping/state`, `/gogoping/set_goal` 등으로 노출된다.

- 절대 path (`/gogoping/...`) 를 코드에 박지 않는다 — 멀티 robot / launch override 막힘.
- 멀티 robot 시 launch 에서 `namespace:=gogoping_2` 등으로 덮으면 끝.

---

```python
# gogoping_modes/main.py
import rclpy
import py_trees
from py_trees.common import Status

from .context import Context
from .fsm.robot_fsm import RobotFSM
from .bt.blackboard import init_blackboard
from .bt.trees.main_trees import build_main_tree
from .interfaces import (
    Nav2Client, CameraPanClient, UIPublisher,
    BatterySubscriber, CollisionSubscriber, DBLogger,
)


class GogopingModes:
    TICK_HZ = 10.0

    def __init__(self, node):
        init_blackboard()
        fsm = RobotFSM(initial="IDLE")
        self.ctx = Context(
            node=node, fsm=fsm,
            nav2=Nav2Client(node),
            camera_pan=CameraPanClient(node),
            ui=UIPublisher(node),
            battery=BatterySubscriber(node),
            collision=CollisionSubscriber(node),
            db_logger=DBLogger(node),
        )
        self.tree: py_trees.trees.BehaviourTree | None = None
        self._current_state: str | None = None
        fsm.add_callback("on_state_change", self._on_state_change)
        self._timer = node.create_timer(1.0 / self.TICK_HZ, self._tick)

    def _on_state_change(self):
        new_state = self.ctx.fsm.current_state
        if new_state == self._current_state:
            return
        if self.tree is not None:
            self.tree.shutdown()                          # 자식 노드 모두 terminate()
        root = build_main_tree(new_state, self.ctx)       # main_trees/BT_<state>_main.build()
        self.tree = py_trees.trees.BehaviourTree(root)
        self.tree.setup(timeout=5.0)
        self._current_state = new_state

    def _tick(self):
        if self.tree is None:
            return
        self.tree.tick()
        root_status = self.tree.root.status
        if root_status == Status.SUCCESS:
            self._on_tree_success()
        elif root_status == Status.FAILURE:
            self._on_tree_failure()

    def _on_tree_success(self):
        # MainTree root SUCCESS = task 완료 → task_done trigger (4 task state 공통)
        _TASK_STATES = {"GOTO", "FOLLOW", "LULLABY", "HIDEANDSEEK"}
        if self._current_state in _TASK_STATES:
            self.ctx.fsm.trigger("task_done")

    def _on_tree_failure(self):
        # FollowSubTree Loss Recovery 끝까지 실패 등 → RETURNING 으로 도피
        self.ctx.fsm.trigger("return_request")


def main():
    rclpy.init()
    # namespace="gogoping" — 본 노드의 모든 토픽/서비스에 /gogoping/* prefix.
    node = rclpy.create_node("gogoping_modes", namespace="gogoping")
    app = GogopingModes(node)
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
```

> **규칙**
> - 트리 교체는 **FSM `on_state_change` 콜백 한 군데에서만**. behavior 내부에서 `tree.shutdown()` 호출 금지
> - tick rate 는 `TICK_HZ` 한 상수로 통제. behavior 안에서 `rate.sleep()` 같은 거 쓰지 않음
> - rclpy executor 는 **default single-threaded** — multi-threaded 안 씀 (blackboard race 회피)

## 4. Tree 빌더 (`bt/trees/main_trees/`, `sub_trees/`)

각 `BT_*.py` 는 단일 `build(context)` 함수 (또는 `build(context, **kwargs)`) 를 export.

```python
# bt/trees/main_trees/BT_idle_main.py
import py_trees
from gogoping_modes.context import Context
from gogoping_modes.bt.behaviors.common.battery_low_monitor import BatteryLowMonitor
from gogoping_modes.bt.behaviors.common.hardware_health_monitor import HardwareHealthMonitor
from gogoping_modes.bt.behaviors.common.command_listener import CommandListener


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return py_trees.composites.Parallel(
        name="BT_idle_main",
        policy=py_trees.common.ParallelPolicy.SuccessOnAll(synchronise=False),
        children=[
            BatteryLowMonitor("BatteryLowMonitor", ctx),
            HardwareHealthMonitor("HardwareHealthMonitor", ctx),
            CommandListener("CommandListener", ctx),
        ],
    )
```

> **규칙**
> - 빌더는 **순수 함수** — `Context` 와 인자만으로 트리 생성. 전역 상태 참조 금지
> - 빌더가 합성하는 SubTree 는 다른 빌더 호출로 가져옴 (예: `from gogoping_modes.bt.trees.sub_trees.BT_goto_sub import build as build_goto`)

### 4.1 동적 빌드 패턴 — `HideAndSeekSubTree`

기본은 static 트리. `HideAndSeekSubTree` 만 예외 — `search_waypoints` 리스트 크기에 따라 N 개의 Search Sequence 를 build 시점에 생성한다.

**전제**
- 사용자가 hide-and-seek 명령을 보낼 때 `command_listener` 가 `blackboard.search_waypoints` 를 먼저 세팅 → 그 다음 `play_request` trigger 발사
- FSM transition 콜백이 `BT_play_main.build(ctx)` 호출 → 내부에서 `BT_hide_and_seek_sub.build(ctx)` 호출 → 그 시점에 blackboard 읽기

```python
# bt/trees/sub_trees/BT_hide_and_seek_sub.py
import py_trees
from py_trees.common import ParallelPolicy

from gogoping_modes.context import Context
from gogoping_modes.bt.blackboard import Keys
from gogoping_modes.bt.behaviors.navigation.navigate_to_pose import NavigateToPose
from gogoping_modes.bt.behaviors.perception.child_face_tracker import ChildFaceTracker
from gogoping_modes.bt.behaviors.perception.found_child import FoundChild
from gogoping_modes.bt.behaviors.follow.pan_camera_sweep import PanCameraSweep
# UI 알림 (announce / countdown start 등) 은 범용 UIPublish 한 behavior 로 처리
from gogoping_modes.bt.behaviors.common.ui_publish import UIPublish
from py_trees.timers import Timer  # 시간 대기는 py_trees 빌트인


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    """search_waypoints 리스트로부터 N 개 Search Sequence 동적 생성."""
    bb = py_trees.blackboard.Blackboard()
    waypoints: list[str] = bb.get(Keys.SEARCH_WAYPOINTS) or []

    # SearchAndAnnounce Selector — waypoint 별 Sequence + 끝에 AnnounceNotFound
    search_children = [
        _build_search_sequence(ctx, waypoint_name=wp, idx=i)
        for i, wp in enumerate(waypoints)
    ]
    search_children.append(
        UIPublish("AnnounceNotFound", ctx, message={"event": "announce", "text": "못 찾았어요"})
    )

    search_and_announce = py_trees.composites.Selector(
        name="SearchAndAnnounce", memory=False, children=search_children,
    )

    search_phase = py_trees.composites.Parallel(
        name="SearchPhase",
        policy=ParallelPolicy.SuccessOnSelected(children=[search_and_announce]),
        children=[
            ChildFaceTracker("ChildFaceTracker", ctx),
            search_and_announce,
        ],
    )

    hide_seek_core = py_trees.composites.Sequence(
        name="HideSeekCore", memory=True,
        children=[
            NavigateToPose("NavToHide", ctx, target_key=Keys.HIDE_POSITION_KEY),
            py_trees.composites.Sequence(
                name="Countdown30s", memory=True,
                children=[
                    UIPublish("StartCountdown", ctx,
                              message={"event": "countdown_start", "seconds": 30}),
                    Timer(name="Wait30s", duration=30.0),
                ],
            ),
            search_phase,
            NavigateToPose("NavToHome", ctx, target_key=Keys.HOME_POSITION_KEY),
        ],
    )

    return py_trees.composites.Parallel(
        name="BT_hide_and_seek_sub",
        policy=ParallelPolicy.SuccessOnSelected(children=[hide_seek_core]),
        children=[hide_seek_core],
    )


def _build_search_sequence(ctx: Context, *, waypoint_name: str, idx: int):
    return py_trees.composites.Sequence(
        name=f"Search_{idx}_{waypoint_name}", memory=True,
        children=[
            # 동적 빌드라 pose_name 을 리터럴로 주입 (target_key 대신)
            NavigateToPose(f"NavTo_{waypoint_name}", ctx, pose_name=waypoint_name),
            PanCameraSweep("PanSweep", ctx),
            FoundChild("FoundChild?", ctx),
            UIPublish("AnnounceFound", ctx, message={"event": "announce", "text": "찾았다!"}),
        ],
    )
```

> **연관 결정 — `NavigateToPose` 의 두 호출 방식**
> 일반 빌더는 `target_key=Keys.DESTINATION_KEY` 처럼 blackboard 키 이름을 주고 런타임에 읽음. 동적 빌더는 빌드 시점에 이미 값이 정해져 있으니 `pose_name="kitchen_door"` 처럼 리터럴 전달. 두 kwarg 중 정확히 하나만 받게 `__init__` 에서 검증.

> **연관 결정 — UI 알림은 `UIPublish` 단일 behavior**
> 오디오 재생 / 카운트다운 안내 / "찾았다!" 같은 알림은 모두 **`bt/behaviors/common/ui_publish.py` 의 범용 `UIPublish(name, ctx, message)`** 한 behavior 로 처리. `message` dict 만 다르게 전달. `audio/` 같은 별도 카테고리 안 만듦. 시간 대기는 `py_trees.timers.Timer` 빌트인 사용. WaitForStopCommand (UI 의 stop 신호 수신) 만 별도 behavior — blackboard 폴링 패턴이라 UI publish 와 성격 다름.

## 5. rclpy 사용 컨벤션 — 안 지키면 폭발하는 함정 3개

과거에 RETURNING cancel 시나리오 디버깅하며 다 한 번씩 밟아본 함정. 새 노드 / behavior /
action server 추가 시 반드시 따른다. 자세한 사례: [nav-cancel-chain.md](nav-cancel-chain.md).

### 5.1 `ActionServer.execute_callback` 은 **sync** 로 작성

```python
# ❌ 위험 — RuntimeError: no running event loop
async def _act_navigate(self, gh):
    ...
    await asyncio.sleep(0.05)        # 첫 await 에서 즉시 폭발

# ✅ sync — MultiThreadedExecutor 가 별도 thread 에서 실행
def _act_navigate(self, gh):
    ...
    while not future.done():
        time.sleep(0.05)
```

rclpy 의 `ActionServer` 는 `MultiThreadedExecutor` 환경에서 **running asyncio event loop
를 만들어주지 않는다**. async 패턴 사용 시 첫 `await` 에서 `RuntimeError` 발생 →
function 즉시 종료 → orphan goal handle.

callback group 은 `ReentrantCallbackGroup` 권장 — sync function 이 thread 를 block 해도
다른 callback (cancel_callback / TF / 다른 service) 은 별도 thread 에서 정상 동작.

### 5.2 외부 action goal handle 은 `try/finally` safety net 으로 cancel forward

내 노드가 다른 노드 (nav2 등) 의 action goal 을 들고 있을 때, **내 함수가 어떤 경로로
종료되든 그 goal 을 cancel 해야** 좀비 안 됨. 안 그러면 nav2 controller 가 `cmd_vel`
계속 publish — robot 안 멈춤.

```python
nav_gh = None
try:
    ...
    nav_gh = send_future.result()
    if not nav_gh.accepted:
        nav_gh = None    # active 아님 — finally skip
        return result
    ...
    # 정상 종료 경로마다 nav_gh = None 명시 (이중 cancel 방지)
    if cancel_path:
        nav_gh.cancel_goal_async()
        nav_gh = None
        return result
    ...
    nav_gh = None    # SUCCESS / nav2 자체 종료
    return result
finally:
    # safety net — 위의 어떤 분기에서도 nav_gh = None 못 했으면 orphan 방지
    if nav_gh is not None:
        try:
            nav_gh.cancel_goal_async()
        except Exception:
            pass
```

### 5.3 `logger.exception()` 금지

ROS 2 jazzy 의 `RcutilsLogger` 는 Python stdlib `logging.Logger` 와 다르다 — `.exception()`
메서드 없음. 호출하면 secondary `AttributeError` 가 원본 traceback 을 가린다.

```python
# ❌
self.get_logger().exception(f"failed: {e}")
# AttributeError: 'RcutilsLogger' object has no attribute 'exception'

# ✅
import traceback
self.get_logger().error(f"failed: {e}\n{traceback.format_exc()}")
```

---

## 6. 테스트 (단위 / 통합)

- **단위 (ROS 없이)**: `Context` 를 `unittest.mock.MagicMock()` 으로 만들어 behavior 단독 테스트. blackboard 는 py_trees 가 알아서 처리.
- **통합 (ROS 필요)**: `pytest` + `rclpy.init()` + 실제 Nav2 mock 노드. `scripts/test.sh` 에 등록.

---

## 빠른 체크리스트 (PR 전)

- [ ] behavior `__init__` 첫 인자가 `name`, 두 번째가 `context`
- [ ] blackboard 키 접근 전에 `register_key(... access=...)` 호출
- [ ] 모든 외부 ROS 호출이 `self.ctx.<interface>.*` 거침 (rclpy 직접 호출 X)
- [ ] `terminate()` 가 진행 중 작업 cancel + idempotent
- [ ] monitor 이면 SUCCESS / FAILURE 안 리턴, 항상 RUNNING + trigger 호출
- [ ] edge-triggered (같은 이벤트 매 tick 반복 호출 X)
- [ ] 새 blackboard 키 / FSM trigger 추가 시 [blackboard-schema.md](blackboard-schema.md) / [fsm-triggers.md](fsm-triggers.md) 같이 갱신
- [ ] **새 ActionServer 추가 시** [§5.1](#51-actionserverexecute_callback-은-sync-로-작성) (sync execute_callback) + [§5.2](#52-외부-action-goal-handle-은-tryfinally-safety-net-으로-cancel-forward) (try/finally) + [§5.3](#53-loggerexception-금지) (logger.error) 확인. 위반 시 좀비 goal / RuntimeError 함정 (사례: [nav-cancel-chain.md](nav-cancel-chain.md))

---

## 7. 새 task state 추가 체크리스트

평탄화 모델 (10 state) 에서 새 task 를 추가하려면 (예: NORIARM_HANDOFF):

1. `gogoping_msgs/msg/Goal.msg` 의 `target_state` 주석에 새 state 이름 추가
2. `gogoping_msgs/msg/GoalStatus.msg` 의 `current_state` 주석에 추가
3. `gogoping_msgs/srv/ForceState.srv` 의 `target_state` 주석에 추가
4. `fsm/robot_fsm.py` — `STATES` 추가, `_TASK_STATES` 에 추가 (task 면), `_request_sources_excluding(...)` 로 task_request trigger 추가
5. `bt/trees/sub_trees/BT_<task>_sub.py` 생성 — 핵심 행동
6. `bt/trees/main_trees/BT_<task>_main.py` 생성 — `build_active_main_tree(body=build_<task>_subtree(ctx), task_body=True, ...)`
7. `bt/trees/main_trees/__init__.py` — `_BUILDERS` dict 에 추가
8. `utils/goal_reconciler.py` — `_EXTERNAL_STATES` 에 추가, `_REQUEST_TRIGGER` 매핑 추가, body validation 추가
9. `service/control-service/control_service/gogoping/state_to_goal.py` — `_LABEL_TO_GOAL` 에 한국어 라벨 매핑 추가
10. `shared/robots.json` — gogoping.modeTree / defaultEmotionByMode 등 라벨 추가
11. `app/admin-app/widgets/debug_state_panel.py` — `_STATES` 에 추가
12. `app/admin-app/widgets/bt_state_inline.py` — `_STATE_COLORS` 에 색 추가
13. `tests/test_gogoping_fsm_transitions.py` — `_VALID_TRANSITIONS` 에 신규 trigger × source 추가
14. `tests/test_gogoping_goal_reconciler.py` — 새 target_state body validation 테스트 추가
15. 문서: `fsm-triggers.md`, `state-bt.md`, `bt/status.md`, `CLAUDE.md` 갱신

대부분 한두 줄씩이라 실제론 ~10분 작업. shell helper 가 monitor 셸을 다 흡수해서 BT 자체는 1 파일 (MainTree).
