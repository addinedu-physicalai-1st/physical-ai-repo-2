from __future__ import annotations

import asyncio
import struct
from pathlib import Path

import pytest

from control_service.eduping.dance_stream import (
    FRAME_TYPE_AUDIO,
    FRAME_TYPE_END,
    FRAME_TYPE_HEADER,
    FRAME_TYPE_MOTION,
    iter_dance_frames,
)


def _find_repo_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "pyproject.toml").exists():
            return p
    raise RuntimeError(f"repo root (pyproject.toml) not found from {start}")


REPO_ROOT = _find_repo_root(Path(__file__).resolve())
ROUTINES_ROOT = REPO_ROOT / "shared"
SLUG = "awesome-tomato"

pytestmark = pytest.mark.skipif(
    not (ROUTINES_ROOT / "openarm_dance" / SLUG / "song.mp3").exists(),
    reason=f"fixture dance {SLUG!r} 없음",
)


def _collect(slug: str) -> list[tuple[int, int, bytes]]:
    """(type, t_ms, payload) 리스트로 한 번에 받기."""
    async def runner() -> list[tuple[int, int, bytes]]:
        out: list[tuple[int, int, bytes]] = []
        async for ftype, t_ms, payload in iter_dance_frames(ROUTINES_ROOT, slug, realtime=False):
            out.append((ftype, t_ms, payload))
        return out

    return asyncio.run(runner())


def test_first_frame_is_header_with_sample_rate_and_joint_names() -> None:
    frames = _collect(SLUG)
    assert frames, "frame 이 안 나옴"
    ftype, t_ms, payload = frames[0]
    assert ftype == FRAME_TYPE_HEADER
    assert t_ms == 0
    import json
    meta = json.loads(payload)
    assert meta["sample_rate"] == 16_000
    assert meta["motion_hz"] == 50
    assert isinstance(meta["joint_names"], list)
    assert len(meta["joint_names"]) > 0


def test_last_frame_is_end() -> None:
    frames = _collect(SLUG)
    assert frames[-1][0] == FRAME_TYPE_END


def test_motion_and_audio_frames_are_interleaved_at_same_t_ms() -> None:
    frames = _collect(SLUG)
    # header 제외 → end 제외
    body = [(f, t) for (f, t, _) in frames[1:-1]]
    # 같은 t_ms 에 motion + audio 한 쌍씩 (순서 상관 없음)
    by_t: dict[int, set[int]] = {}
    for ftype, t_ms in body:
        by_t.setdefault(t_ms, set()).add(ftype)
    # 첫 1초 (50 frames) 까지 검사 — 전체 검사 비용 큼
    keys = sorted(by_t.keys())[:50]
    for k in keys:
        assert FRAME_TYPE_MOTION in by_t[k]
        assert FRAME_TYPE_AUDIO in by_t[k]


def test_motion_frame_payload_is_float32_per_joint() -> None:
    frames = _collect(SLUG)
    motion = next((p for (f, _t, p) in frames if f == FRAME_TYPE_MOTION), None)
    assert motion is not None
    assert len(motion) % 4 == 0
    # header 의 joint_names 수와 motion payload 의 float32 갯수가 일치해야 함
    import json
    header_payload = next(p for (f, _t, p) in frames if f == FRAME_TYPE_HEADER)
    joint_count = len(json.loads(header_payload)["joint_names"])
    assert len(motion) // 4 == joint_count
    assert joint_count >= 8  # OpenArm 은 최소 8 joints


def test_audio_frame_payload_is_20ms_of_pcm_s16le_16k() -> None:
    frames = _collect(SLUG)
    audio = next((p for (f, _t, p) in frames if f == FRAME_TYPE_AUDIO), None)
    assert audio is not None
    assert len(audio) == 640
