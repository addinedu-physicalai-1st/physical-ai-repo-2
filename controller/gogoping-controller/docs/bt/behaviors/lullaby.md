# lullaby behaviors

LULLABY(자장가) 모드 전용 leaf.

각 항목 — *(스켈레톤)* 표시는 아직 코드 구현 전.

---

## lullaby_audio  *(구현됨)*

자장가 SubTree 본체. `initialise()` 에 play publish, `update()` 영구 RUNNING, `terminate()`
에 stop publish (idempotent).

- read: 없음
- write: 없음
- mp3 재생 자체는 robot-web frontend 의 `<audio>` element 가 담당 (별도 PR) — BT 는
  `/gogoping/ui_event` 에 이벤트만 publish.
- `_stop_published` flag — `__init__` 초기값 `True` (cold terminate 시 publish 안 함).
  `initialise()` 가 `False` 로 리셋 → play publish 된 lifetime 안에서만 stop publish 보장.

| 항목 | 값 |
|---|---|
| Topic publish | `/gogoping/ui_event` (`std_msgs/String` JSON) — via `ctx.ui.publish_event()` |
| Messages | `PLAY_MSG = {"event": "lullaby_play", "src": "lullaby.mp3", "loop": True}` / `STOP_MSG = {"event": "lullaby_stop"}` |
| Status | initialise=play publish 1회 / update=RUNNING 영구 / terminate=stop publish (idempotent) |
| terminate(INVALID) | stop publish (`_stop_published` flag) |
| Used in | BT_lullaby_sub (단일 leaf) |
| 파일 | [`bt/behaviors/lullaby/lullaby_audio.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/lullaby/lullaby_audio.py) |
| 테스트 | 7 시나리오 (play publish / update RUNNING / stop publish / idempotent / 재진입 flag 리셋 / 메시지 상수 / cold terminate no-op) |
