"""서브프로세스 래퍼 — READY 대기 + START write + SIGTERM."""
from __future__ import annotations

import asyncio
import sys
import textwrap

import pytest

from control_service.noriarm.block_stacking_process import RunnerProcess


@pytest.mark.asyncio
async def test_wait_ready_returns_when_ready_printed(tmp_path) -> None:
    # 가짜 runner — READY 출력 후 stdin 한 줄 읽고 종료.
    script = tmp_path / "fake_runner.py"
    script.write_text(textwrap.dedent("""
        import sys, time
        print('READY', flush=True)
        line = sys.stdin.readline()
        print(f'GOT:{line.strip()}', flush=True)
    """))
    proc = RunnerProcess([sys.executable, str(script)])
    await proc.start()
    ok = await proc.wait_ready(timeout_s=5.0)
    assert ok
    await proc.send_start()
    rc = await proc.wait_exit(timeout_s=5.0)
    assert rc == 0


@pytest.mark.asyncio
async def test_terminate_sends_sigterm(tmp_path) -> None:
    script = tmp_path / "fake_runner.py"
    script.write_text(textwrap.dedent("""
        import sys, signal, time
        signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
        print('READY', flush=True)
        time.sleep(30)
    """))
    proc = RunnerProcess([sys.executable, str(script)])
    await proc.start()
    await proc.wait_ready(timeout_s=5.0)
    await proc.terminate()
    rc = await proc.wait_exit(timeout_s=5.0)
    assert rc == 0
