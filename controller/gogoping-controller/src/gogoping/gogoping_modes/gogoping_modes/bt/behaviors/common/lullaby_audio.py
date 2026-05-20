"""LullabyAudio — BT_lullaby_sub 본체 behavior.

자장가 모드 진입 시 ``ctx.ui.publish_event(PLAY_MSG)`` 발행 → 외부 trigger 까지
영구 RUNNING → 종료 시 ``ctx.ui.publish_event(STOP_MSG)`` 발행 (idempotent).

mp3 재생 자체는 robot-web frontend 의 ``<audio>`` element 가 담당 — BT 는 이벤트만
publish. ``docs/bt/trees/BT_lullaby_sub.md`` 의 데이터 흐름 참조.

종료 보장:
- ``main.py._build_tree_for_state`` 가 BT swap 시 ``root.stop(INVALID) + tree.shutdown()``
  호출 → RUNNING 자식의 ``terminate(INVALID)`` 전파 → STOP_MSG publish 보장.
- ``_stop_published`` flag 가 ``terminate()`` 중복 호출 대비 idempotent. **__init__ 초기값
  True** — initialise 없이 cold terminate 시 STOP_MSG publish 안 함 (재생 안 시작했는데
  정지 신호 보내는 안티-패턴 회피). ``initialise()`` 가 False 로 리셋 → play publish 된
  lifetime 안에서만 stop publish 보장. 재진입 (Selector(memory=False) 등) 시 정상 동작.

자세한 명세: ``docs/bt/behaviors/common.md#lullaby_audio``, ``docs/bt/trees/BT_lullaby_sub.md``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import py_trees
from py_trees.common import Status

if TYPE_CHECKING:
    from ....context import Context


class LullabyAudio(py_trees.behaviour.Behaviour):
    """자장가 — initialise=play, update=RUNNING, terminate=stop (idempotent)."""

    AUDIO_SRC = "lullaby.mp3"  # robot-web 정적 리소스 이름. frontend 가 해석.

    PLAY_MSG = {"event": "lullaby_play", "src": AUDIO_SRC, "loop": True}
    STOP_MSG = {"event": "lullaby_stop"}

    def __init__(self, name: str, context: "Context"):
        super().__init__(name)
        self.ctx = context
        # 초기값 True — initialise 없이 cold terminate 호출 시 STOP_MSG publish 안 함.
        # initialise() 가 False 로 리셋 → play publish 된 lifetime 안에서만 stop publish.
        self._stop_published = True

    def initialise(self) -> None:
        # 재진입 가능 — flag 리셋 후 새로 play publish
        self._stop_published = False
        self.ctx.ui.publish_event(self.PLAY_MSG)

    def update(self) -> Status:
        # 외부 trigger (cancel / *_request / battery_low / fault) 가 BT swap 으로 종료.
        return Status.RUNNING

    def terminate(self, new_status: Status) -> None:  # noqa: ARG002
        # idempotent — 여러 번 호출돼도 stop publish 는 1회만.
        if self._stop_published:
            return
        self.ctx.ui.publish_event(self.STOP_MSG)
        self._stop_published = True
