# py_trees Parallel + Monitor 동작 검증 (30분 Spike)

`Parallel(SuccessOnSelected=[X])` 와 `RUNNING` 만 리턴하는 monitor 의 조합이 실제로 의도대로 동작하는지 확인. **본격 코딩 전에 1회 수행**.

## 무엇을 검증하는가

`state-bt.md` 머리말과 `conventions.md` 의 monitor 컨벤션은 다음을 가정한다:

1. `Parallel(SuccessOnSelected=[TaskSelector], ...)` 의 root status:
   - TaskSelector SUCCESS → root SUCCESS ✅
   - TaskSelector RUNNING, monitor RUNNING → root RUNNING ✅
   - Monitor 가 어쩌다 SUCCESS 리턴 → root 영향 안 받아야 함
   - 어떤 자식이 FAILURE 리턴 → root 동작은? (정책 검증 필요)
2. Monitor 가 항상 RUNNING + 가끔 `fsm.trigger()` 호출 → 트리 계속 tick
3. `tree.shutdown()` 호출 시 자식 노드의 `terminate(new_status)` 가 **반드시** 호출
4. `py_trees.timers.Timer(duration=N)` 가 실제 wall-clock N 초 후 SUCCESS

## 검증 절차

### Step 1. 환경

```bash
cd ~/pingdergarten
pip install py_trees==2.2.*       # vendor 와 같은 메이저 버전
python -c "import py_trees; print(py_trees.__version__)"
```

### Step 2. Minimal spike 스크립트

`/tmp/spike_parallel.py` 같은 임시 파일에 작성. 코드는 아래 4 가지 테스트 케이스를 각각 함수로:

```python
import py_trees
from py_trees.common import Status, ParallelPolicy


class AlwaysRunningMonitor(py_trees.behaviour.Behaviour):
    """우리 monitor 가정: 항상 RUNNING, 가끔 부수효과."""
    def __init__(self, name, trigger_at=None):
        super().__init__(name)
        self.cnt = 0
        self.trigger_at = trigger_at  # 이 tick 에 trigger 호출 (print)

    def update(self):
        self.cnt += 1
        if self.cnt == self.trigger_at:
            print(f"  [{self.name}] tick {self.cnt} → fsm.trigger() (시뮬레이션)")
        return Status.RUNNING

    def terminate(self, new_status):
        print(f"  [{self.name}] terminate({new_status.name})")


class SucceedsAfter(py_trees.behaviour.Behaviour):
    def __init__(self, name, after):
        super().__init__(name); self.after = after; self.cnt = 0
    def update(self):
        self.cnt += 1
        return Status.SUCCESS if self.cnt >= self.after else Status.RUNNING
    def terminate(self, new_status):
        print(f"  [{self.name}] terminate({new_status.name})")


class FailsAt(py_trees.behaviour.Behaviour):
    def __init__(self, name, at):
        super().__init__(name); self.at = at; self.cnt = 0
    def update(self):
        self.cnt += 1
        return Status.FAILURE if self.cnt >= self.at else Status.RUNNING
    def terminate(self, new_status):
        print(f"  [{self.name}] terminate({new_status.name})")


def tick_until_done(root, max_ticks=10):
    for i in range(max_ticks):
        root.tick_once()
        print(f"Tick {i}: root={root.status.name}")
        if root.status in (Status.SUCCESS, Status.FAILURE):
            return root.status
    return root.status


def test_1_main_task_success():
    """기대: monitor 2개 RUNNING, main 3 tick 후 SUCCESS → root SUCCESS"""
    print("\n=== Test 1: SuccessOnSelected — main SUCCESS 시 root SUCCESS ===")
    root = py_trees.composites.Parallel(
        name="P1",
        policy=ParallelPolicy.SuccessOnSelected(
            children=[]
        ),
        children=[],
    )
    main = SucceedsAfter("MainTask", after=3)
    m1 = AlwaysRunningMonitor("Mon1", trigger_at=2)
    m2 = AlwaysRunningMonitor("Mon2")
    root.add_children([m1, m2, main])
    root.policy.children = [main]
    result = tick_until_done(root)
    assert result == Status.SUCCESS, f"expected SUCCESS got {result}"


def test_2_monitor_failure_propagates():
    """기대: monitor 가 FAILURE 면 root FAILURE 인가? (정책 확인)"""
    print("\n=== Test 2: Monitor FAILURE → root 영향 ===")
    main = SucceedsAfter("MainTask", after=10)
    m_fail = FailsAt("MonFail", at=3)
    root = py_trees.composites.Parallel(
        name="P2",
        policy=ParallelPolicy.SuccessOnSelected(children=[main]),
        children=[m_fail, main],
    )
    result = tick_until_done(root)
    print(f"→ Monitor FAILURE 시 root status = {result.name}")


def test_3_shutdown_calls_terminate():
    """기대: tree.shutdown() 호출 시 모든 자식의 terminate() 호출됨"""
    print("\n=== Test 3: shutdown → terminate 전파 ===")
    main = SucceedsAfter("MainTask", after=100)  # 안 끝남
    m1 = AlwaysRunningMonitor("Mon1")
    root = py_trees.composites.Parallel(
        name="P3",
        policy=ParallelPolicy.SuccessOnSelected(children=[main]),
        children=[m1, main],
    )
    tree = py_trees.trees.BehaviourTree(root)
    for _ in range(2):
        tree.tick()
    print("→ shutdown 호출:")
    tree.shutdown()
    # 위 print 에 'terminate(INVALID)' 가 m1, MainTask 둘 다 찍혀야 함


def test_4_timer_wall_clock():
    """기대: Timer(duration=1.0) 이 약 1초 후 SUCCESS"""
    print("\n=== Test 4: py_trees.timers.Timer wall-clock 정확도 ===")
    import time
    from py_trees.timers import Timer
    t = Timer(name="T", duration=1.0)
    start = time.time()
    while t.status != Status.SUCCESS:
        t.tick_once()
        time.sleep(0.05)
    elapsed = time.time() - start
    print(f"→ Timer SUCCESS, elapsed={elapsed:.2f}s (target=1.00s)")


if __name__ == "__main__":
    test_1_main_task_success()
    test_2_monitor_failure_propagates()
    test_3_shutdown_calls_terminate()
    test_4_timer_wall_clock()
```

```bash
python /tmp/spike_parallel.py
```

### Step 3. 합격 기준 (검증 후 결과 기록)

| 테스트 | 합격 조건 | 결과 |
|---|---|---|
| 1. Main SUCCESS → root SUCCESS | `Tick 2: root=SUCCESS` (main 의 3번째 tick 직전 또는 동시) | □ |
| 2. Monitor FAILURE → root | **결과를 기록**: SUCCESS / FAILURE / RUNNING 중 무엇? | □ → __________ |
| 3. shutdown → terminate | `Mon1` 과 `MainTask` 모두 `terminate(INVALID)` print | □ |
| 4. Timer wall-clock | elapsed ≈ 1.00s ± 0.1s | □ |

## 결과 따른 후속 결정

| Test 결과 | 의미 / 코드 컨벤션 |
|---|---|
| Test 2 = root FAILURE | **monitor 는 절대 FAILURE 리턴하면 안 됨** — `conventions.md` 의 "monitor 는 항상 RUNNING" 규칙이 강제됨. 위반 시 트리 전체 다운 |
| Test 2 = root SUCCESS | monitor FAILURE 는 무시됨 — 그래도 컨벤션상 monitor 는 RUNNING 유지 권장 |
| Test 2 = root RUNNING | py_trees 의 ParallelPolicy 가 FAILURE 를 selective 하게 처리 — 추가 조사 |
| Test 3 실패 (terminate 누락) | py_trees 버전 버그 의심 — 우리가 `tree.shutdown()` 직전 수동으로 `root.stop(INVALID)` 호출하는 안전망 추가 |
| Test 4 실패 (시간 오차 큼) | tick rate 가 너무 낮음 — `main.py` 의 `TICK_HZ` 를 올리거나 Timer 대신 직접 `time.time()` 비교 구현 |

## 회고 메모

스파이크 끝나면 결과를 본 문서 하단에 한 줄로 추가:

```
- 2026-MM-DD <name>: Test1 ✓ Test2(FAILURE→root=?) Test3 ✓ Test4(elapsed=?) — 컨벤션 변경: ___
```

스파이크는 1회로 충분 — 결과가 컨벤션 문서에 박히면 본 파일은 archive 후보.
