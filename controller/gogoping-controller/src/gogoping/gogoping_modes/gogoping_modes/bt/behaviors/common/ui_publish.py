"""UIPublish — 범용 UI 알림 behavior.

빌더 시점에 ``message: dict`` 받아 매 활성화마다 ``ctx.ui.publish_event(message)`` 1회
호출 후 즉시 ``SUCCESS`` (한 activation cycle 안에서 첫 update 가 SUCCESS 리턴 →
parent 가 다음 자식으로 이동 → 이번 cycle 에서는 추가 publish 불가).

Selector(memory=False) 등에서 **재활성화** 되면 initialise 가 다시 호출되고 update 가
다시 publish — 이는 의도된 동작 (예: hideseek 의 announce 가 매 waypoint loop iteration
마다 재발화). 의도와 다른 "전체 트리 수명 동안 정확히 1회" 가 필요하면 이 behavior 가
아니라 1-shot decorator + 별도 flag behavior 를 써야 함.

용도 (예):
- HideAndSeek: ``UIPublish("AnnounceFound", ctx, message={"event":"announce", "text":"찾았다!"})``
- HideAndSeek: ``UIPublish("StartCountdown", ctx, message={"event":"countdown_start", "seconds":30})``
- Carry/Lullaby: 추후 announce / 안내 알림 등

자장가 본체 (지속 + cleanup 책임) 는 별도 ``LullabyAudio`` 사용.

자세한 명세: ``docs/bt/behaviors/common.md#ui_publish``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import py_trees
from py_trees.common import Status

if TYPE_CHECKING:
    from ....context import Context


class UIPublish(py_trees.behaviour.Behaviour):
    """``message`` dict 1회 publish 후 즉시 ``SUCCESS``.

    Parameters
    ----------
    name : str
        py_trees 노드 이름 (admin UI BT MAIN 영역에 표시).
    context : Context
        ``ctx.ui.publish_event`` 사용.
    message : dict
        publish 할 payload — ``{"event": <type>, ...}`` 스키마.
    """

    def __init__(self, name: str, context: "Context", *, message: dict):
        super().__init__(name)
        self.ctx = context
        self._message = message

    def update(self) -> Status:
        self.ctx.ui.publish_event(self._message)
        return Status.SUCCESS

    def terminate(self, new_status: Status) -> None:  # noqa: ARG002
        # no-op — 1회성 publish 후 유지할 자원 없음.
        pass
