# Manual Behaviors

수동 모드 (carry manual) 전용. `bt/behaviors/manual/` 안.

모두 *(스켈레톤)*.

- **enable_manual_control** — camera_pan 우선순위 manual 전환 (terminate 시 auto 복원). Used in: BT_carry_sub (manual mode)
- **wait_for_exit** — `carry_mode` 변경 / cancel 명령까지 RUNNING. Used in: BT_carry_sub (manual mode)
