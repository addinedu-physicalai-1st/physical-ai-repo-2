import numpy as np
import pytest

from ai_service.wake_training.mix import mix_into_ambient


@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.fixture
def wake_clip():
    # 0.7s of synthetic sine wave at 16kHz
    sr = 16000
    t = np.arange(int(0.7 * sr)) / sr
    return (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


@pytest.fixture
def ambient_pool():
    # 3 clips of 5s ambient at 16kHz (white noise low amplitude)
    rng = np.random.default_rng(0)
    return [
        (rng.standard_normal(int(5 * 16000)) * 0.02).astype(np.float32)
        for _ in range(3)
    ]


def test_output_length_and_dtype(wake_clip, ambient_pool, rng):
    out, meta = mix_into_ambient(wake_clip, ambient_pool, rng)
    assert out.shape == (43200,)
    assert out.dtype == np.float32
    assert isinstance(meta, dict)
    assert 'offset_sec' in meta
    assert 'snr_db' in meta
    assert 'ambient_idx' in meta
    assert 'wake_duration_sec' in meta


def test_snr_within_tolerance(wake_clip, ambient_pool):
    """meta['snr_db'] 가 실제 측정 SNR 과 ±1.5dB 이내."""
    rng = np.random.default_rng(7)
    out, meta = mix_into_ambient(wake_clip, ambient_pool, rng)
    off = int(meta['offset_sec'] * 16000)
    wake_len = int(meta['wake_duration_sec'] * 16000)
    sig_segment = out[off:off + wake_len]
    if off >= wake_len:
        amb_segment = out[off - wake_len:off]
    else:
        amb_segment = out[off + wake_len:off + 2 * wake_len]
    p_sig = float(np.mean(sig_segment.astype(np.float64) ** 2))
    p_amb = float(np.mean(amb_segment.astype(np.float64) ** 2))
    p_wake = max(p_sig - p_amb, 1e-12)
    measured_snr = 10 * np.log10(p_wake / max(p_amb, 1e-12))
    assert abs(measured_snr - meta['snr_db']) < 1.5, (
        f"measured {measured_snr:.2f}dB vs meta {meta['snr_db']:.2f}dB"
    )


def test_offset_places_wake_at_reported_position(wake_clip, ambient_pool):
    """meta['offset_sec'] 위치에서 RMS 가 ambient-only 구간보다 명확히 큰지."""
    rng = np.random.default_rng(11)
    out, meta = mix_into_ambient(wake_clip, ambient_pool, rng,
                                  snr_db_range=(10.0, 10.0))
    off = int(meta['offset_sec'] * 16000)
    wake_len = int(meta['wake_duration_sec'] * 16000)
    wake_rms = float(np.sqrt(np.mean(out[off:off + wake_len] ** 2)))
    ambient_region = np.concatenate([out[:off], out[off + wake_len:]])
    amb_rms = float(np.sqrt(np.mean(ambient_region ** 2))) if ambient_region.size else 0.0
    assert wake_rms > amb_rms * 2.0, (
        f"wake_rms {wake_rms:.4f} <= 2× amb_rms {amb_rms:.4f} at offset {off}"
    )


def test_short_ambient_cycled_to_fill(wake_clip):
    """ambient 클립이 1s 만 있어도 cyclic concat 으로 2.7s 채워짐."""
    rng = np.random.default_rng(13)
    short_amb = (rng.standard_normal(16000) * 0.02).astype(np.float32)  # 1s
    out, _ = mix_into_ambient(wake_clip, [short_amb], rng)
    assert out.shape == (43200,)
    chunk_rms = np.array([
        np.sqrt(np.mean(out[i:i+1600] ** 2)) for i in range(0, 43200, 1600)
    ])
    assert (chunk_rms > 1e-5).all(), f"some chunks have ~0 RMS: {chunk_rms}"


def test_determinism_with_same_seed(wake_clip, ambient_pool):
    """동일 seed 의 rng 두 개로 두 번 호출하면 byte-identical."""
    rng_a = np.random.default_rng(99)
    rng_b = np.random.default_rng(99)
    out_a, meta_a = mix_into_ambient(wake_clip, ambient_pool, rng_a)
    out_b, meta_b = mix_into_ambient(wake_clip, ambient_pool, rng_b)
    assert np.array_equal(out_a, out_b)
    assert meta_a == meta_b
