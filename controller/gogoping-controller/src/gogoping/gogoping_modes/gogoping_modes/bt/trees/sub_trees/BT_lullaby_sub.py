"""BT_lullaby_sub — 자장가 SubTree.

LULLABY state MainTree (BT_lullaby_main) 의 body 로 직접 호출됨 (평탄화 이후 TaskSelector 없음).

흐름:
    LullabyAudio (단일 leaf)
      ├─ initialise: ctx.ui.publish_event({event: "lullaby_play", src: "lullaby.mp3", loop: True})
      ├─ update:     영구 RUNNING — 외부 trigger 가 BT swap 으로 종료
      └─ terminate:  ctx.ui.publish_event({event: "lullaby_stop"})  (idempotent)

자장가는 "publish 시작 + 영구 RUNNING + publish 종료" 한 책임이라 composite (Sequence/
Parallel) 없이 단일 behavior. 트리 의사코드 (``docs/subtree-flow.md``) 의 ``PlayAudio``
+ ``WaitForStopCommand`` 두 단계는 본 ``LullabyAudio`` 한 노드에 응집 — terminate 시
stop publish 가 같은 클래스 책임 안에 들어가 race 회피.

이름 ``BT_lullaby_sub`` — ``tree_inspector._find_subtree`` 의 ``BT_*_sub`` 패턴 매칭 →
admin UI BT SUB 영역에 자동 표시.

자세한 명세: ``docs/bt/trees/BT_lullaby_sub.md``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import py_trees

from ...behaviors.common.lullaby_audio import LullabyAudio

if TYPE_CHECKING:
    from ....context import Context


def build_lullaby_subtree(ctx: "Context") -> py_trees.behaviour.Behaviour:
    """LULLABY MainTree 의 body. 단일 ``LullabyAudio`` 리턴.

    name="BT_lullaby_sub" 필수 — tree_inspector 패턴 매칭으로 admin UI SUB 영역 표시.
    """
    return LullabyAudio(name="BT_lullaby_sub", context=ctx)


__all__ = ["build_lullaby_subtree"]
