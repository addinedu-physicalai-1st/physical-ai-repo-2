"""runner_entry.py 서브프로세스 lifecycle 래퍼.

asyncio.subprocess 로 spawn → stdout 의 "READY" 줄을 읽을 때까지 대기 (모델 로드
완료 신호) → "START\\n" stdin write → SIGTERM 으로 종료.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from typing import Callable, Sequence

logger = logging.getLogger(__name__)


class RunnerProcess:
    """runner_entry.py 서브프로세스 lifecycle.

    block_stacking 의 단일 task 패턴 + store_play 의 long-lived 패턴 둘 다 지원.
    - 단일 task: start → wait_ready → send_start → terminate (block_stacking 기존 흐름)
    - long-lived: start → wait_ready → send_start → send_prompt × N → send_quit
      각 send_prompt 후 wait_task_done 으로 task 완료 신호 (TASK_DONE 줄) 대기.
    """

    def __init__(
        self,
        argv: Sequence[str],
        *,
        env_extra: dict[str, str] | None = None,
        on_event: "Callable[[dict], None] | None" = None,
    ) -> None:
        self._argv = list(argv)
        self._env_extra = env_extra or {}
        self._proc: asyncio.subprocess.Process | None = None
        self._ready_event = asyncio.Event()
        self._exit_code: int | None = None
        self._stdout_task: asyncio.Task | None = None
        # long-lived (store_play) 용 — TASK_DONE 줄을 큐로 받아 매 task 마다 wait 가능.
        self._task_done_queue: asyncio.Queue[bool] = asyncio.Queue(maxsize=8)
        # runner → UI 이벤트 콜백 — runner 가 "EVENT {json}" stdout 으로 보내면 호출.
        # store_play 의 bell_rung / missing 등 도메인 이벤트를 SSE 로 흘리는 통로.
        self._on_event = on_event

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
            # uvicorn 이 application logger.info 를 stdout 에 안 흘려서 runner 출력(크래시
            # traceback 포함)이 control 로그에 안 보임 → print 로 직접 흘림 (디버깅 필수).
            print(f"[runner] {text}", flush=True)
            if text == "READY":
                self._ready_event.set()
            elif text == "TASK_DONE":
                try:
                    self._task_done_queue.put_nowait(True)
                except asyncio.QueueFull:
                    pass  # 미소비 신호 누적 시 drop — 호출자가 timely consume 가정.
            elif text.startswith("EVENT ") and self._on_event is not None:
                # runner 도메인 이벤트 ("EVENT {json}") → UI 콜백 (SSE).
                try:
                    self._on_event(json.loads(text[len("EVENT "):]))
                except Exception:
                    pass  # 잘못된 EVENT 줄 무시 — 추론에 영향 없음.

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

    # ────────────────── long-lived (store_play) 전용 ──────────────────

    async def send_prompt(self, prompt: str) -> None:
        """'PROMPT <task>\\n' 보내서 runner 가 task 1회 실행하게 함."""
        assert self._proc is not None and self._proc.stdin is not None
        safe = prompt.replace("\n", " ").replace("\r", " ").strip()
        line = f"PROMPT {safe}\n".encode()
        self._proc.stdin.write(line)
        await self._proc.stdin.drain()

    async def wait_task_done(self, *, timeout_s: float) -> bool:
        """runner 의 TASK_DONE stdout 줄 대기. True=받음, False=timeout."""
        try:
            await asyncio.wait_for(self._task_done_queue.get(), timeout=timeout_s)
            return True
        except asyncio.TimeoutError:
            return False

    async def send_abort(self) -> None:
        """SIGUSR1 — 진행 중 task 만 중단 (runner 는 계속 살아있어 다음 PROMPT 대기)."""
        if self._proc is None or self._proc.returncode is not None:
            return
        try:
            self._proc.send_signal(signal.SIGUSR1)
        except (ProcessLookupError, ValueError):
            pass  # ValueError: windows 에서 SIGUSR1 미지원.

    async def send_quit(self) -> None:
        """'QUIT\\n' 보내서 runner 가 cleanly disconnect 후 종료하게 함."""
        if self._proc is None or self._proc.returncode is not None:
            return
        if self._proc.stdin is None or self._proc.stdin.is_closing():
            return
        try:
            self._proc.stdin.write(b"QUIT\n")
            await self._proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ────────────────────────────────────────────────────────────────

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
