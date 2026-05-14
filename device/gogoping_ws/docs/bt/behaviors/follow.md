# Follow Behaviors

카메라 pan 제어 + 추종 관련. `bt/behaviors/follow/` 안.

모두 *(스켈레톤)*.

- **face_tracking** — 얼굴 좌표 → 카메라 pan 각도 (gogoping_camera_pan 호출). Used in: BT_follow_sub
- **wait_for_reappear** — `target_visible = True` 될 때까지 timeout 까지 RUNNING. Used in: BT_follow_sub
- **raise_camera_pan** — 카메라 각도 올림 (carry/follow 시작 시). Used in: BT_carry_sub (goto), BT_follow_sub
- **pan_camera_sweep** — 카메라 pan 좌우 sweep (탐색용). Used in: BT_follow_sub, BT_hide_and_seek_sub
