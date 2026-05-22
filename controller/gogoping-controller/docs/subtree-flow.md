SubTree

# follow 의 두 경로 (★ 재사용 패턴)

**`FollowSubTree` 자체는 한 개, 호출 경로는 두 개.**

| 경로 | 명령 | 컨텍스트 | 추가 가드 |
|---|---|---|---|
| (1) ASSIST 직속 | `assist_request, task=follow, target_id=...` | 단독 추종 | 없음 |

→ 추종 로직 (1.5m 유지 / Loss Recovery 등) 은 `FollowSubTree` 한 곳에만 작성.
운반 시나리오는 user 가 follow task + goto task 를 순차 chain (composition) 으로 구성.

# audio / announce 노드 표기 — 의사코드

`PlayAudio` / `AnnounceTask` / `AnnounceArrival` / `CountdownWithAudio` / `AnnounceFound` / `AnnounceNotFound` 는 BT 노드처럼 그려져 있지만 실제로는 모두 **`bt/behaviors/common/ui_publish.py` 의 `UIPublish(message=...)` 단일 behavior 호출의 의사코드**. `CountdownWithAudio` 는 `Sequence(UIPublish(start_countdown), Timer(N))` 패턴. 자세한 코드 sketch 는 [conventions.md §4.1](conventions.md).

-------------------------------------------------------------------------------
GotoSubTree (Sequence, memory=True)
  ├─ NavigateToVertex(destination_key)
  └─ UIPublish(message={"event":"announce","text":"도착했습니다"})

# 운반 시나리오 = user 가 follow task + goto task 를 순차 chain (composition).
# 짐 감지 / mode 분기 / 음성 안내 / 카메라 동작 모두 없음. SubTree 본체는 단일 이동.
# 자세한 명세: docs/superpowers/specs/2026-05-20-bt-goto-sub-design.md

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
 LullabySubTree = LullabyAudio (단일 leaf, 의사코드 PlayAudio + WaitForStopCommand 응집)
   ├─ initialise():  publish_event({event:"lullaby_play", src:"lullaby.mp3", loop:True})
   ├─ update():      RUNNING (영구 — 외부 trigger 가 BT swap 으로 종료)
   └─ terminate():   publish_event({event:"lullaby_stop"})  (idempotent)
 # ※ 의사코드의 PlayAudio + WaitForStopCommand 두 단계는 LullabyAudio 한 노드에 응집.
 #   terminate 시 stop publish 가 같은 클래스 책임 안에 들어가 race 회피.
 #   자세한 명세: docs/bt/trees/BT_lullaby_sub.md

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
PatrolSubTree (building block — mode/task 단위 SubTree 아님)
  Sequence (memory=True, name="BT_patrol_sub")
    ├─ FailureIsSuccess("safe_visit_A") of Sequence("visit_A", memory=True):
    │     ├─ SelectVertex(vertex_name="A")    # BB.target_vertex_name = "A"
    │     ├─ NavigateToVertex                  # graph_router action
    │     └─ PanCameraSweep                    # 90 → 30 → 150 → 90 (1.5s × 4)
    ├─ FailureIsSuccess("safe_visit_B") of …
    └─ FailureIsSuccess("safe_visit_C") of …

# build_patrol_sub(ctx, waypoints) — 빌드 시 vertex list 받아 동적 자식 생성.
# 한 vertex 실패 시 다음 vertex 계속 (skip-on-failure).
# 자세한 명세: docs/bt/trees/BT_patrol_sub.md
------------------------------------------------------------------------------- 
1. GotoSubTree (이동) — vertex 까지 lane 따라 이동, 도착 시 알림. 운반은 user 가 follow + goto chain.

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

---

### 빌딩 블록 (mode/task 단위 SubTree 아님)

**PatrolSubTree** — vertex list 를 순서대로 돌며 각 vertex 에서 카메라 좌우 sweep.
한 vertex 실패는 skip 후 다음 진행 (`FailureIsSuccess` decorator). 본 SubTree 자체는
어느 mode/task 에도 결선돼 있지 않다 — 호출자가 빌더 `build_patrol_sub(ctx, waypoints)` 로
사용. 추후 `HideAndSeekSubTree` 의 search 단계 등에서 재사용 예정.