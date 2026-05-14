# Recovery Behaviors

ERROR state 전용 — 안전 정지 + alert + 로깅. `bt/behaviors/recovery/` 안.

모두 *(스켈레톤)*. Used in: BT_error_main 만.

- **stop_all_motors** — `cmd_vel = 0` + 로봇팔 정지 (안전 정지)
- **notify_admin_ui** — WebSocket 으로 에러 alert publish
- **log_error_to_db** — error_log 테이블 INSERT (디버깅용)
