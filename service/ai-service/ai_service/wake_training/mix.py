"""Wake-word + continuous ambient mix builder — production 분포에 맞춰
학습용 2.7s positive 클립을 만든다.

학습 데이터를 "wake word + literal zero" 에서 "wake at random offset within
continuous ambient" 로 바꿔, 브라우저가 흘리는 raw audio 와 분포 일치시킨다.
"""
from __future__ import annotations

import numpy as np

_TARGET_SR = 16000


def mix_into_ambient(
    wake: np.ndarray,
    ambient_pool: list[np.ndarray],
    rng: np.random.Generator,
    target_sec: float = 2.7,
    snr_db_range: tuple[float, float] = (5.0, 20.0),
) -> tuple[np.ndarray, dict]:
    """wake word 를 ambient 위에 random offset 으로 mix.

    Returns:
        out: float32, length = round(target_sec * 16000) = 43200 for default
        meta: {'offset_sec', 'snr_db', 'ambient_idx', 'wake_duration_sec'}
    """
    if not ambient_pool:
        raise ValueError("ambient_pool 가 비어있다")
    target_samples = int(round(target_sec * _TARGET_SR))
    amb_idx = int(rng.integers(0, len(ambient_pool)))
    amb_src = ambient_pool[amb_idx]
    # slice or cyclic concat to target_samples
    if amb_src.size >= target_samples:
        start = int(rng.integers(0, amb_src.size - target_samples + 1))
        ambient = amb_src[start:start + target_samples].astype(np.float32, copy=True)
    else:
        reps = int(np.ceil(target_samples / max(amb_src.size, 1)))
        ambient = np.tile(amb_src, reps)[:target_samples].astype(np.float32, copy=True)
    # offset
    wake_arr = np.asarray(wake, dtype=np.float32).reshape(-1)
    wake_len = min(wake_arr.size, target_samples)
    max_offset = target_samples - wake_len
    offset = int(rng.integers(0, max(1, max_offset + 1)))
    # SNR scaling
    snr_db = float(rng.uniform(*snr_db_range))
    rms_wake = float(np.sqrt(np.mean(wake_arr[:wake_len].astype(np.float64) ** 2) + 1e-12))
    rms_amb = float(np.sqrt(np.mean(ambient.astype(np.float64) ** 2) + 1e-12))
    if rms_amb > 1e-9 and rms_wake > 1e-9:
        target_rms_amb = rms_wake / (10 ** (snr_db / 20.0))
        ambient *= np.float32(target_rms_amb / rms_amb)
    # mix
    out = ambient
    out[offset:offset + wake_len] += wake_arr[:wake_len]
    np.clip(out, -1.0, 1.0, out=out)
    meta = {
        'offset_sec': offset / _TARGET_SR,
        'snr_db': snr_db,
        'ambient_idx': amb_idx,
        'wake_duration_sec': wake_len / _TARGET_SR,
    }
    return out, meta
