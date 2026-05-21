"""runner_entry.py 서브프로세스 lifecycle 래퍼.

asyncio.subprocess 로 spawn → stdout 의 "READY" 줄을 읽을 때까지 대기 (모델 로드
완료 신호) → "START\\n" stdin write → SIGTERM 으로 종료.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Sequence

logger = logging.getLogger(__name__)


class RunnerProcess:
    def __init__(self, argv: Sequence[str], *, env_extra: dict[str, str] | None = None) -> None:
        self._argv = list(argv)
        self._env_extra = env_extra or {}
        self._proc: asyncio.subprocess.Process | None = None
        self._ready_event = asyncio.Event()
        self._exit_code: int | None = None
        self._stdout_task: asyncio.Task | None = None

    async def start(self) -> None:
        env = os.environ.copy()
        env.update(self._env_extra)
        self._proc = await asyncio.create_subprocess_exec(
            *self._argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        self._stdout_task = asyncio.create_task(self._consume_stdout())

    async def _consume_stdout(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            logger.info("[runner] %s", text)
            if text == "READY":
                self._ready_event.set()

    async def wait_ready(self, *, timeout_s: float) -> bool:
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout_s)
            return True
        except asyncio.TimeoutError:
            return False

    async def send_start(self) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(b"START\n")
        await self._proc.stdin.drain()

    async def terminate(self) -> None:
        if self._proc is None or self._proc.returncode is not None:
            return
        try:
            self._proc.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            pass

    async def wait_exit(self, *, timeout_s: float) -> int | None:
        if self._proc is None:
            return None
        try:
            self._exit_code = await asyncio.wait_for(
                self._proc.wait(), timeout=timeout_s
            )
            return self._exit_code
        except asyncio.TimeoutError:
            return None
        finally:
            if self._stdout_task is not None:
                self._stdout_task.cancel()

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.returncode is None
