"""메모리 누수 추적용 debug 라우터 — /debug/mem*.

배경: streaming app (장시간 떠있는 단일 uvicorn worker) 이 시간당 GB 로 RSS 가
자라 OOM (2026-05-30, multiprocessing-fork 자식 RSS 7.6GB 선제 KILL). 누수 site 를
정적 코드 읽기로는 단정 못 해서, 실제 부하(admin UI WebRTC consumer)를 걸어두고
이 엔드포인트로 "시간에 따라 커지는 allocation/객체"를 집어 범인을 확정한다.

세 가지 관점:
  1) tracemalloc diff — startup baseline 대비 증가한 allocation 을 file:line 별 정렬.
     누수는 매 스냅샷마다 size 가 단조 증가하는 라인으로 드러남.
  2) gc 객체 타입 히스토그램 — RTCPeerConnection / av.VideoFrame / VideoPacket 등이
     close/unsubscribe 후에도 누적되는지 개수로 추적 (consumer 재연결 churn 누수 감지).
  3) 프로세스 RSS (/proc/self/status VmRSS) — 절대 메모리 추세.

켜기: STREAMING_TRACEMALLOC=1 (기본 on — 누수 추적 기간). 끄려면 0.
tracemalloc 오버헤드(allocation 마다 traceback 기록)가 부담되면 추적 끝난 뒤 0 으로.

사용:
  curl -s localhost:8100/debug/memtop | jq          # baseline 대비 top growth
  curl -s 'localhost:8100/debug/memtop?limit=40&frames=5' | jq
  curl -s -XPOST localhost:8100/debug/memsnap        # baseline 재설정 (이 시점부터 diff)
  curl -s localhost:8100/debug/memtypes | jq         # gc 객체 타입 top
"""
from __future__ import annotations

import gc
import logging
import os
import tracemalloc
from collections import Counter

from fastapi import APIRouter

_log = logging.getLogger("streaming.debug")

# startup baseline. /debug/memsnap 으로 갱신 가능.
_baseline: tracemalloc.Snapshot | None = None


def tracemalloc_enabled() -> bool:
    return os.environ.get("STREAMING_TRACEMALLOC", "1") not in ("0", "false", "False", "")


def start_tracemalloc(frames: int = 10) -> None:
    """startup 에서 호출. tracemalloc 켜고 baseline 스냅샷 저장."""
    global _baseline
    if not tracemalloc_enabled():
        _log.info("tracemalloc 비활성 (STREAMING_TRACEMALLOC=0)")
        return
    if not tracemalloc.is_tracing():
        tracemalloc.start(frames)
    _baseline = tracemalloc.take_snapshot()
    _log.info("tracemalloc baseline 저장 (frames=%d) — /debug/memtop 으로 diff 확인", frames)


def _proc_rss_mb() -> float | None:
    """/proc/self/status VmRSS (MB). Linux 전용, 실패 시 None."""
    try:
        with open("/proc/self/status", "r") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1])
                    return round(kb / 1024.0, 1)
    except OSError:
        return None
    return None


def make_debug_router() -> APIRouter:
    router = APIRouter(prefix="/debug", tags=["debug"])

    @router.get("/memtop")
    async def memtop(limit: int = 25, frames: int = 1) -> dict:
        """baseline 대비 메모리 증가 top — file:line 별 정렬 (frames=1) 또는 traceback.

        size_diff 가 양수로 큰 라인 = 누수 후보. 1~2분 간격으로 두세 번 떠서
        같은 라인의 size_diff 가 계속 커지면 그게 범인.
        """
        rss = _proc_rss_mb()
        if not tracemalloc.is_tracing():
            return {
                "rss_mb": rss,
                "tracing": False,
                "hint": "STREAMING_TRACEMALLOC=1 로 재시작하면 allocation 추적 가능",
            }
        current = tracemalloc.take_snapshot()
        key = "traceback" if frames > 1 else "lineno"
        if _baseline is not None:
            stats = current.compare_to(_baseline, key)
            top = []
            for s in stats[:limit]:
                frame = s.traceback[0]
                top.append({
                    "file": f"{frame.filename}:{frame.lineno}",
                    "size_diff_kb": round(s.size_diff / 1024.0, 1),
                    "count_diff": s.count_diff,
                    "size_now_kb": round(s.size / 1024.0, 1),
                    "count_now": s.count,
                    "traceback": s.traceback.format() if frames > 1 else None,
                })
            mode = "diff_vs_baseline"
        else:
            stats = current.statistics(key)
            top = [{
                "file": f"{s.traceback[0].filename}:{s.traceback[0].lineno}",
                "size_now_kb": round(s.size / 1024.0, 1),
                "count_now": s.count,
            } for s in stats[:limit]]
            mode = "absolute_no_baseline"
        traced_cur, traced_peak = tracemalloc.get_traced_memory()
        return {
            "rss_mb": rss,
            "tracing": True,
            "mode": mode,
            "traced_current_mb": round(traced_cur / 1e6, 1),
            "traced_peak_mb": round(traced_peak / 1e6, 1),
            "top": top,
        }

    @router.post("/memsnap")
    async def memsnap() -> dict:
        """baseline 을 지금 시점으로 재설정 — 이후 /debug/memtop diff 의 기준점."""
        global _baseline
        if not tracemalloc.is_tracing():
            return {"ok": False, "reason": "tracemalloc not tracing"}
        _baseline = tracemalloc.take_snapshot()
        return {"ok": True, "rss_mb": _proc_rss_mb(), "msg": "baseline reset"}

    @router.get("/memtypes")
    async def memtypes(limit: int = 30) -> dict:
        """gc 추적 객체의 타입별 개수 top — 누적되는 객체 타입 식별.

        예: close 한 RTCPeerConnection 이나 av.VideoFrame 개수가 시간에 따라 계속
        늘면 그 lifecycle 정리 누락이 누수. tracemalloc 과 교차검증.
        """
        gc.collect()
        counts: Counter[str] = Counter()
        for obj in gc.get_objects():
            counts[type(obj).__name__] += 1
        top = [{"type": t, "count": c} for t, c in counts.most_common(limit)]
        return {
            "rss_mb": _proc_rss_mb(),
            "gc_tracked_total": sum(counts.values()),
            "top": top,
        }

    return router
