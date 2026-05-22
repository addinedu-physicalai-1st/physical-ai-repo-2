# Follow Behaviors

카메라 pan 제어 + 추종 관련. `bt/behaviors/follow/` 안.

---

## pan_camera_sweep {#pan_camera_sweep}  *(구현됨)*

[bt/behaviors/follow/pan_camera_sweep.py](../../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/follow/pan_camera_sweep.py)

카메라 pan 을 시간 기반 시퀀스로 좌우 sweep — 도착한 vertex 에서 "주변 둘러보기" 동작.

| 항목 | 값 |
|---|---|
| 기본 시퀀스 | `90° → 30° → 150° → 90°` (4 step) |
| 기본 step duration | `1.5s` (각 step hold) — 총 ≈ 6초 |
| ROS publish | `ctx.camera_pan.publish_pan(deg)` → `/servo_bridge/cmd_pan` (std_msgs/Float32). watchdog (1000ms) 안에서 servo_bridge 가 20Hz 재송신하므로 step 진입 시 1회만 publish. |
| Blackboard | R/W 없음 — 파라미터로 받은 시퀀스만 사용 |
| Status | RUNNING (elapsed < step_duration) / SUCCESS (모든 step 완료) |
| terminate(INVALID) | `ctx.camera_pan.center()` 1회 publish (90° 복귀). terminate(SUCCESS/FAILURE) 는 cleanup 없음 (마지막 step 이 이미 center) |
| 인자 | `name`, `context`, `steps_deg=(90,30,150,90)`, `step_duration_sec=1.5`, `now_fn=time.monotonic` (테스트 mock 용) |
| Used in | BT_patrol_sub (각 visit 의 마지막 자식), BT_follow_sub (예정), BT_hide_and_seek_sub (예정) |
| 테스트 | [tests/test_gogoping_pan_camera_sweep.py](../../../../../tests/test_gogoping_pan_camera_sweep.py) — 13 케이스 |

### 안전 / 동시성

- `/servo_bridge/cmd_pan` 은 admin-app `CameraPanCard` / control-service `camera_pan/ros_bridge.py` 와 공유 — last-writer-wins. 본 sweep 중 admin 측 다른 publisher 가 끼어들면 그쪽 setpoint 가 적용됨. 데모 시점엔 동시 사용 피할 것.
- publish 예외 (publisher 미준비 등) 는 swallow + log — sweep 자체는 죽지 않고 다음 step 진행.

---

## 스켈레톤 (미구현)

- **face_tracking** — 얼굴 좌표 → 카메라 pan 각도 (gogoping_camera_pan 호출). Used in: BT_follow_sub
- **wait_for_reappear** — `target_visible = True` 될 때까지 timeout 까지 RUNNING. Used in: BT_follow_sub
- **raise_camera_pan** — 카메라 각도 올림 (follow 시작 시). Used in: BT_follow_sub
