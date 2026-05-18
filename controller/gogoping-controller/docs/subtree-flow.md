SubTree

# follow 의 두 경로 (★ 재사용 패턴)

**`FollowSubTree` 자체는 한 개, 호출 경로는 두 개.**

| 경로 | 명령 | 컨텍스트 | 추가 가드 |
|---|---|---|---|
| (1) ASSIST 직속 | `assist_request, task=follow, target_id=...` | 단독 추종 (운반 없음) | 없음 |
| (2) CarrySubTree 의 follow 모드 | `assist_request, task=carry, carry_mode=follow, target_id=...` | 짐 운반 + 추종 | `LoadStabilityCheck` |

→ 추종 로직 (1.5m 유지 / Loss Recovery 등) 은 `FollowSubTree` 한 곳에만 작성, 상위 컨텍스트가 가드를 추가한다.

# audio / announce 노드 표기 — 의사코드

`PlayAudio` / `AnnounceTask` / `AnnounceArrival` / `CountdownWithAudio` / `AnnounceFound` / `AnnounceNotFound` 는 BT 노드처럼 그려져 있지만 실제로는 모두 **`bt/behaviors/common/ui_publish.py` 의 `UIPublish(message=...)` 단일 behavior 호출의 의사코드**. `CountdownWithAudio` 는 `Sequence(UIPublish(start_countdown), Timer(N))` 패턴. 자세한 코드 sketch 는 [conventions.md §4.1](conventions.md).

 -------------------------------------------------------------------------------
CarrySubTree
  Parallel (SuccessOnSelected=[CarryCore])
    ├─ Selector (LoadCheckGuard, memory=False)   ※ manual 모드일 때 비활성
    │     ├─ CheckCarryMode("manual")            # manual → SUCCESS → 짐 감시 skip
    │     └─ LoadStabilityCheck                  # 그 외 → 짐 떨어짐 감지 시 FAILURE
    └─ CarryCore (Selector, memory=False)
          ├─ Sequence: CheckCarryMode("manual") → CarryManualMode
          ├─ Sequence: CheckCarryMode("goto")   → CarryGotoMode
          └─ Sequence: CheckCarryMode("follow") → FollowSubTree    ★ 재사용

CarryManualMode (Sequence)
  ├─ EnableManualControl             (terminate 시 priority "auto" 복원)
  └─ WaitForExit

CarryGotoMode (Sequence)
  ├─ RaiseCameraPan(angle_for_carry)
  ├─ AnnounceTask
  ├─ NavigateToPose(destination_key)
  └─ AnnounceArrival
  
  
  -------------------------------------------------------------------------------
  FollowSubTree
  Parallel (SuccessOnSelected=[FollowCore])
    ├─ FaceTracking
    └─ FollowCore (Sequence, memory=True)
          ├─ RaiseCameraPan(angle_for_follow)
          └─ FollowLoop (Selector, memory=False)
                ├─ Sequence (정상 추종)
                │     ├─ IsTargetVisible
                │     ├─ DetectTargetPerson
                │     ├─ MaintainDistance(1.5m)
                │     └─ CheckArrival
                │
                └─ Sequence (Loss Recovery — 제자리에서 찾기)
                      ├─ StopBase
                      └─ FindTarget (Selector, memory=False)
                            ├─ WaitForReappear(3s)
                            ├─ Sequence
                            │     ├─ PanCameraSweep
                            │     └─ WaitForReappear(7s)
                            └─ Failure
                      ※ Failure → FollowSubTree FAILURE → main.py 의 _on_tree_failure() 가
                        return_request trigger 발사 → RETURNING 진입 (conventions.md §3 참조)
    
  -------------------------------------------------------------------------------                              
 LullabySubTree (Sequence, memory=True)
  ├─ PlayAudio("lullaby.mp3", loop=true)
  └─ WaitForStopCommand

   -------------------------------------------------------------------------------
 HideAndSeekSubTree
  Parallel (SuccessOnSelected=[HideSeekCore])
    └─ HideSeekCore (Sequence, memory=True)
          ├─ NavigateToPose(hide_position_key)
          ├─ CountdownWithAudio(30s)
          ├─ Parallel (SuccessOnSelected=[SearchAndAnnounce])
          │     ├─ ChildFaceTracker
          │     └─ SearchAndAnnounce (Selector, memory=False)
          │           │  ※ waypoint 별 Sequence 는 build 시 search_waypoints 리스트로부터 동적 생성
          │           ├─ Sequence (waypoint i, i=0..N-1)
          │           │     ├─ NavigateToPose(search_waypoints[i])
          │           │     ├─ PanCameraSweep
          │           │     ├─ FoundChild?
          │           │     └─ AnnounceFound
          │           └─ AnnounceNotFound
          └─ NavigateToPose(home_position_key)
 -------------------------------------------------------------------------------
ReturnSubTree = OneShot(ON_COMPLETION) of:
  Sequence (memory=True)
    ├─ NavigateToVertex(target_key="charging_dock_approach_key")  # "충전소입구" vertex 까지 graph routing
    ├─ AlignToDock                                                 # CHARGING_DOCK_TARGET_YAW 까지 회전
    ├─ ReverseIntoDock                                              # N초 후진
    └─ VerifyDockingContact                                         # docked trigger 자동 발사 → CHARGING

# 접점 센서는 미구현 — VerifyDockingContact 가 "후진 끝났으면 도킹 완료" 간주
# 후 docked trigger 발사. 추후 docking_contact 토픽 통합 시 검증 추가.
# 자세한 명세: docs/bt/trees/BT_return_sub.md
------------------------------------------------------------------------------- 
1. CarrySubTree (운반)
3가지 모드 중 사용자가 선택:
Manual — UI 화살표로 직접 조작
Goto — 특정 위치 지정 → 자동 이동
Follow — 사람 따라가기 (FollowSubTree 재사용)

진행 중 짐 떨어지면 중단.

2. FollowSubTree (추종)
카메라 올림 → 사람 인식 → 1.5m 거리 유지하며 따라가기
사람 잃으면: 제자리 정지 → 3초 대기 → 카메라 좌우 흔들기 → 7초 더 대기 → 못 찾으면 실패 (RETURNING 으로)

3. LullabySubTree (자장가)
자장가 재생 → "그만" 명령까지 대기

4. HideAndSeekSubTree (숨바꼭질)
숨는 위치로 이동 → 30초 카운트다운 → 등록된 waypoint 들 순회하며 탐색 (이동 + 카메라 sweep)
→ 찾으면 "찾았다!", 다 돌았는데 못 찾으면 "못 찾았어요" → 원위치 복귀
**한 번 실행 후 종료** (라운드/반복 개념 없음). 다시 하려면 사용자가 UI 에서 재요청.

5. ReturnSubTree (도킹 복귀) — 4단계
graph_router 로 "충전소입구" vertex 까지 lane 따라 이동 → 도크 등진 yaw 로 제자리 회전 → N초 후진 → docked trigger 자동 발사 (VerifyDockingContact) → CHARGING 전이 → OneShot 잠금 (재실행 X).
자동 도킹 접점 센서는 미구현 — 시간 기반 후진 끝나면 무조건 도킹 완료 간주.