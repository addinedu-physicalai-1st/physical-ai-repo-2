# Safety Reroute — proximity_event + reroute 정책

> graph_router 의 사람·벽 감지·정지·재개·우회 로직 명세. 2026-05-28 추가.

## 1. 데이터 흐름

```
perception_node (YOLO + depth)
    │ /gogoping/person_proximity (Float32, m or inf)
    ▼
safety_monitor (정면 박스 필터 + level 결정)
    │ /gogoping/proximity_event (String JSON)
    ▼
graph_router_node (액션 polling 안에서 분기)
    │ /navigate_to_pose cancel + /cmd_vel (backup)
    ▼
nav2 stack
```

## 2. /gogoping/proximity_event 스키마

JSON encoded `std_msgs/String`.

```json
{
  "ts": 1779955200.123,
  "level": "ok",
  "person_dist_m": 1.42,
  "wall_dist_m": null
}
```

| 필드 | 타입 | 의미 |
|---|---|---|
| `ts` | float | publish 시각 (epoch seconds) |
| `level` | str | "ok" / "person_close" / "wall_close" |
| `person_dist_m` | float \| null | 정면 박스 안 가장 가까운 사람 거리. 없으면 null |
| `wall_dist_m` | float \| null | 정면 ROI 안 가장 가까운 벽 거리. 없으면 null |

Publish 주기: 10 Hz.

## 3. 정면 박스 정의 (robot frame)

- forward: `0 ~ PERSON_FRONT_DIST_M (0.9m)`
- lateral: `±PERSON_LATERAL_LIMIT_M (±0.5m)`

YOLO bbox 의 image 중심 픽셀 → depth → robot frame:
- `forward_m = depth_mm / 1000`
- `lateral_m = (bbox_cx - CAMERA_CX_PX) / CAMERA_FX_PX * forward_m`

박스 안 = `forward_m ≤ 1.5 AND |lateral_m| ≤ 0.5`.

## 4. wall_dist_m

depth ROI: 화면 가로 중앙 50% × 세로 하단 60%. tracking_bbox 영역 제외. 그 영역의 최소 depth (mm) → m.

## 5. graph_router_node 반응 정책

| level | 액션 | 후속 |
|---|---|---|
| `ok` | nav 계속 / pause 해제 후 재발사 | — |
| `person_close` | cancel 후 pause loop | 60s 내 ok → 재발사. 60s 초과 → blocked + reroute |
| `wall_close` | cancel → LiDAR 후방 ±45° clearance 체크 → backup or reroute | 3회 backup 실패 시 blocked + reroute. stuck (odom 변화 < 3cm) 시 abort |

## 6. blocked vertex

`set[str]` — `_restart_with_reroute` 호출 시 통과 금지. **현재 액션 한정** — 다음 액션에서 자동 reset.

`Graph.route(src, dst, start_yaw, blocked)` 가 blocked 회피해 새 경로 계산. 대체 경로 없으면 `GraphError` → `gh.abort()` + reason="reroute failed".

## 7. SAFETY_BYPASS_STATES

`config.SAFETY_BYPASS_STATES = ["MANUAL"]` — 이 상태에서는 `evaluate_proximity_level` 가 강제 `"ok"` 반환. graph_router 의 pause/backup 자동 비활성.

## 8. FOLLOW 자동 제외

graph_router 는 GOTO / HIDEANDSEEK / RETURNING / LOW_BATTERY_RETURNING 의 vertex-to-vertex navigation 만 처리. FOLLOW 는 graph_router 를 사용하지 않으므로 본 spec 의 새 로직과 무관. FOLLOW 의 자체 추종 + 기존 safety_filter 가 별도 동작.

## 9. config 상수 (gogoping_perception/config.py)

```python
PERSON_FRONT_DIST_M = 0.9
PERSON_LATERAL_LIMIT_M = 0.5
WALL_FRONT_DIST_M = 0.5
CAMERA_FX_PX = 615.0
CAMERA_CX_PX = 320.0
YOLO_NAV_MODES = ("GOTO", "FOLLOW", "HIDEANDSEEK", "RETURNING", "LOW_BATTERY_RETURNING", "LULLABY")
```

## 10. config 상수 (graph_router_node.py)

```python
SUSTAIN_TIMEOUT_S = 60.0
BACKUP_DISTANCE_M = 0.15
BACKUP_MAX_RETRIES = 3
BACKUP_SPEED_MPS = 0.05
BACKUP_REAR_CLEARANCE_M = 0.25
BACKUP_STUCK_DELTA_M = 0.03
REAR_SECTOR_HALF_RAD = 0.785398
```

## 11. 관찰

- `/gogoping/debug/nav_events` 로 PAUSE / RESUME / BACKUP / REROUTE / STUCK 이벤트 로그.
- admin UI NavDebugLogCard 에 실시간 표시.

## 12. 알려진 한계

- AMCL drift 미감지 (60s pause 는 짧다고 판단).
- 운동장 free-roam (lane 없는 자유 이동) 미구현.
- backup 후진 시 사람 후방 동적 감지 미구현 — LiDAR clearance 는 backup 직전 측정만.
- reroute 시 caller (BT/admin UI) 가 새 액션 재발사해야 함 (action 안에서 재진입 미지원, 단순화 트레이드오프).
