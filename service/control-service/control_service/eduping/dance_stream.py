"""율동 통합 스트림 producer — motion frame + PCM chunk 를 같은 t_ms 위에 묶어 yield.

`iter_dance_frames(...)` 는 `(type: int, t_ms: int, payload: bytes)` 튜플을 yield 한다.
WS 인코딩 (헤더 + payload concat) 은 Task 3 의 router 가 담당.

frame types:
  0x01 motion  payload = float32 LE × N joints  (4N bytes)
  0x02 audio   payload = PCM s16le mono 16kHz × 320 samples  (640 bytes, 20ms)
  0x03 header  payload = JSON utf-8 (meta: sample_rate, motion_hz, joint_names, duration_s, ...)
  0x04 end     payload = empty

같은 t_ms 에 motion + audio 한 쌍. 곡이 motion 보다 짧으면 audio frame 만 생략, motion 은 끝까지 계속.

WS wire format (router 에서 직렬화):
  type(1 byte) | t_ms(8 byte big-endian uint64) | payload(variable)
"""
from __future__ import annotations

import asyncio
import json
import math
import struct
import time
from pathlib import Path
from typing import AsyncIterator

from .dance_audio import TARGET_SAMPLE_RATE, decode_to_pcm_s16le_mono_16k
from .joint_limits import clip_positions as _clip_joint_positions

FRAME_TYPE_MOTION = 0x01
FRAME_TYPE_AUDIO = 0x02
FRAME_TYPE_HEADER = 0x03
FRAME_TYPE_END = 0x04

MOTION_TICK_HZ = 50
TICK_MS = 1000 // MOTION_TICK_HZ  # 20
AUDIO_SAMPLES_PER_TICK = TARGET_SAMPLE_RATE * TICK_MS // 1000  # 320
AUDIO_BYTES_PER_TICK = AUDIO_SAMPLES_PER_TICK * 2  # s16 = 2byte


def trapezoidal_profile(
    start: list[float], end: list[float], v_max: float, a_max: float, dt: float = TICK_MS / 1000.0
) -> list[tuple[float, list[float]]]:
    """가장 큰 |delta| joint 가 v_max cruise · a_max 가속/감속, 나머지는 같은 시간 안에서
    time-scaled. (t, pos) 튜플 리스트 반환, 시작/끝 속도 0.

    profile:
      t_acc = v_max / a_max,  d_acc = ½·v_max·t_acc
      2·d_acc ≥ d_max  → 삼각 (v_max 못 미침)
      else            → 사다리꼴, T = 2·t_acc + (d_max - 2·d_acc)/v_max
    """
    n = len(start)
    if len(end) != n:
        raise ValueError(f"start/end joint count mismatch: {n} vs {len(end)}")
    deltas = [e - s for s, e in zip(start, end)]
    d_max = max((abs(d) for d in deltas), default=0.0)
    if d_max < 1e-6:
        return [(0.0, list(start)), (dt, list(end))]

    t_acc = v_max / a_max
    d_acc = 0.5 * v_max * t_acc
    if 2.0 * d_acc >= d_max:
        t_acc = math.sqrt(d_max / a_max)
        t_cruise = 0.0
    else:
        t_cruise = (d_max - 2.0 * d_acc) / v_max
    T = 2.0 * t_acc + t_cruise

    out: list[tuple[float, list[float]]] = []
    t = 0.0
    while t < T:
        if t <= t_acc:
            d = 0.5 * a_max * t * t
        elif t <= t_acc + t_cruise:
            d = 0.5 * v_max * t_acc + v_max * (t - t_acc)
        else:
            tau = T - t
            d = d_max - 0.5 * a_max * tau * tau
        s = max(0.0, min(1.0, d / d_max))
        out.append((t, [sp + s * dp for sp, dp in zip(start, deltas)]))
        t += dt
    out.append((T, list(end)))
    return out


async def iter_home_ramp_frames(
    *,
    joint_names: list[str],
    start_pos: list[float],
    end_pos: list[float],
    v_max: float,
    a_max: float,
    realtime: bool = True,
) -> AsyncIterator[tuple[int, int, bytes]]:
    """현재 pose → HOME 으로 trapezoidal 보간 motion-only 프레임 시퀀스.

    Audio 는 보내지 않음 (PLAYING → HOME_RAMP 전환 시 클라이언트가 자연스레 무음).
    iter_dance_frames 와 동일 frame format/타이밍 규칙.
    """
    keyframes = trapezoidal_profile(start_pos, end_pos, v_max, a_max, TICK_MS / 1000.0)
    duration_s = keyframes[-1][0] if keyframes else 0.0
    joint_count = len(joint_names)

    meta = {
        "slug": "__home__",
        "sample_rate": TARGET_SAMPLE_RATE,
        "motion_hz": MOTION_TICK_HZ,
        "tick_ms": TICK_MS,
        "joint_names": list(joint_names),
        "motion_duration_s": round(duration_s, 3),
        "audio_duration_s": 0.0,
    }
    yield (FRAME_TYPE_HEADER, 0, json.dumps(meta, ensure_ascii=False).encode("utf-8"))

    start_mono = time.monotonic()
    for t_s, pos in keyframes:
        t_ms = int(round(t_s * 1000))
        # 관리자 UI 가 좁힌 안전 범위로 clip — joint_limits.json 의 라이브 캐시 적용.
        clipped = _clip_joint_positions(joint_names, pos)
        payload = struct.pack(f"<{joint_count}f", *clipped)
        yield (FRAME_TYPE_MOTION, t_ms, payload)
        if realtime:
            target = start_mono + t_s
            now = time.monotonic()
            if target > now:
                await asyncio.sleep(target - now)

    yield (FRAME_TYPE_END, int(round(duration_s * 1000)), b"")


def _interp_joint_positions(
    keyframes: list, t_s: float, joint_count: int
) -> list[float]:
    """t_s 의 위치를 keyframes 사이 linear interpolation 으로 추정.

    keyframes 는 routines_io.Keyframe 객체 리스트. 시간 정렬 가정.
    범위 밖이면 양 끝 값 clamp.
    """
    if not keyframes:
        return [0.0] * joint_count
    if t_s <= keyframes[0].t:
        return list(keyframes[0].pos)
    if t_s >= keyframes[-1].t:
        return list(keyframes[-1].pos)
    # binary search
    lo, hi = 0, len(keyframes) - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if keyframes[mid].t <= t_s:
            lo = mid
        else:
            hi = mid
    a, b = keyframes[lo], keyframes[hi]
    span = b.t - a.t
    alpha = (t_s - a.t) / span if span > 0 else 0.0
    return [pa + (pb - pa) * alpha for pa, pb in zip(a.pos, b.pos)]


async def iter_dance_frames(
    routines_root: Path, slug: str, *, realtime: bool = True
) -> AsyncIterator[tuple[int, int, bytes]]:
    """율동을 type/t_ms/payload frame 시퀀스로 yield.

    realtime=True 면 tick 사이 `asyncio.sleep` 으로 wall-clock 보조 — 실제 스트리밍.
    False 면 sleep 없이 즉시 dump — 테스트에서 사용.
    """
    from eduarm.routines_io import (  # type: ignore[import-not-found]
        dance_motion_path,
        dance_song_path,
        load_routine,
    )

    motion_path = dance_motion_path(routines_root, slug)
    routine = load_routine(motion_path)
    joint_count = len(routine.joint_names)
    motion_total_s = routine.duration_s

    song_path = dance_song_path(routines_root, slug)
    pcm = b""
    sample_rate = TARGET_SAMPLE_RATE
    if song_path is not None:
        pcm, sample_rate = decode_to_pcm_s16le_mono_16k(song_path)
    audio_total_s = (len(pcm) // 2) / sample_rate if pcm else 0.0

    total_s = max(motion_total_s, audio_total_s)
    total_ticks = int(total_s * 1000 // TICK_MS) + 1

    # 0x03 header
    meta = {
        "slug": slug,
        "sample_rate": sample_rate,
        "motion_hz": MOTION_TICK_HZ,
        "tick_ms": TICK_MS,
        "joint_names": list(routine.joint_names),
        "motion_duration_s": round(motion_total_s, 3),
        "audio_duration_s": round(audio_total_s, 3),
    }
    yield (FRAME_TYPE_HEADER, 0, json.dumps(meta, ensure_ascii=False).encode("utf-8"))

    start_mono = time.monotonic()
    for i in range(total_ticks):
        t_ms = i * TICK_MS
        t_s = t_ms / 1000.0

        if t_s <= motion_total_s:
            pos = _interp_joint_positions(routine.keyframes, t_s, joint_count)
            clipped = _clip_joint_positions(routine.joint_names, pos)
            payload = struct.pack(f"<{joint_count}f", *clipped)
            yield (FRAME_TYPE_MOTION, t_ms, payload)

        if pcm:
            audio_off = AUDIO_BYTES_PER_TICK * i
            if audio_off + AUDIO_BYTES_PER_TICK <= len(pcm):
                yield (FRAME_TYPE_AUDIO, t_ms, pcm[audio_off : audio_off + AUDIO_BYTES_PER_TICK])

        if realtime:
            target = start_mono + (i + 1) * (TICK_MS / 1000.0)
            now = time.monotonic()
            if target > now:
                await asyncio.sleep(target - now)

    yield (FRAME_TYPE_END, int(total_s * 1000), b"")
