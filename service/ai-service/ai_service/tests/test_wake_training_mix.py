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
