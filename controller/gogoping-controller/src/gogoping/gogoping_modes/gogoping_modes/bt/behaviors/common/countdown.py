"""Countdown — N 초 경과 시 SUCCESS, 아니면 RUNNING.

`initialise()` 시점 (RUNNING 진입) 의 monotonic 시각을 anchor 로 잡고,
`update()` 마다 경과 시간을 확인. interrupt 후 재진입 시 `terminate()` 가
anchor 를 None 으로 리셋 → 다음 `initialise()` 가 새 N 초 카운트 시작.

사용 예: BT_hide_and_seek_sub 의 countdown phase — 30초 카운트다운.
별도 UI 이벤트 (countdown_start / 챈트) 는 SetHideseekPhase + 클라이언트
타이머가 담당. 본 behaviour 는 순수 시간 기준 게이트.

Debug skip: ``check_skip_key`` 가 주어지면 update() 마다 그 blackboard 키를
체크 — True 면 즉시 SUCCESS + 키를 False 로 리셋 (재진입 깨끗하게).
"""
from __future__ import annotations

import time

import py_trees
from py_trees.common import Access


class Countdown(py_trees.behaviour.Behaviour):
    """seconds 만큼 RUNNING 후 SUCCESS.

    Parameters
    ----------
    name : str
    seconds : float
        카운트다운 길이.
    check_skip_key : str | None
        지정 시 매 update() 마다 blackboard 의 이 키를 체크 — True 면 즉시 SUCCESS.
        SUCCESS 후 키를 False 로 reset 해 다음 카운트다운 진입 시 다시 정상 동작.
    """

    def __init__(
        self,
        name: str,
        seconds: float,
        check_skip_key: str | None = None,
    ) -> None:
        super().__init__(name=name)
        self._seconds = float(seconds)
        self._anchor: float | None = None
        self._skip_key = check_skip_key
        if check_skip_key is not None:
            self.bb = self.attach_blackboard_client(name=self.name)
            self.bb.register_key(key=check_skip_key, access=Access.WRITE)
        else:
            self.bb = None

    def initialise(self) -> None:
        self._anchor = time.monotonic()

    def _check_skip(self) -> bool:
        if self.bb is None or self._skip_key is None:
            return False
        try:
            v = bool(self.bb.get(self._skip_key))
        except (KeyError, AttributeError):
            return False
        if v:
            # 즉시 reset — 재진입 시 다시 정상 카운트.
            try:
                self.bb.set(self._skip_key, False)
            except (KeyError, AttributeError):
                pass
            return True
        return False

    def update(self) -> py_trees.common.Status:
        if self._check_skip():
            return py_trees.common.Status.SUCCESS
        if self._anchor is None:
            self._anchor = time.monotonic()
        elapsed = time.monotonic() - self._anchor
        if elapsed >= self._seconds:
            return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.RUNNING

    def terminate(self, new_status: py_trees.common.Status) -> None:
        # SUCCESS / INVALID 양쪽 모두 anchor 를 None 으로 — 재진입 시 새로 시작.
        self._anchor = None
