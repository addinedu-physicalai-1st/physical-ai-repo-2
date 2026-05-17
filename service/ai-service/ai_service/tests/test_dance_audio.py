from pathlib import Path

import pytest

from control_service.eduping.dance_audio import decode_to_pcm_s16le_mono_16k


def _find_repo_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "pyproject.toml").exists():
            return p
    raise RuntimeError(f"repo root (pyproject.toml) not found from {start}")


REPO_ROOT = _find_repo_root(Path(__file__).resolve())
FIXTURE_SONG = REPO_ROOT / "shared" / "openarm_dance" / "awesome-tomato" / "song.mp3"


@pytest.mark.skipif(not FIXTURE_SONG.exists(), reason="fixture mp3 없음")
def test_decode_returns_pcm_with_expected_sample_rate_and_width() -> None:
    pcm, sample_rate = decode_to_pcm_s16le_mono_16k(FIXTURE_SONG)
    assert sample_rate == 16_000
    assert isinstance(pcm, bytes)
    # 16-bit = 2 bytes/sample, mono. 곡이 비어있지 않음
    assert len(pcm) > 0
    assert len(pcm) % 2 == 0


def test_decode_unknown_extension_raises(tmp_path: Path) -> None:
    bogus = tmp_path / "song.xyz"
    bogus.write_bytes(b"\x00" * 10)
    with pytest.raises(ValueError, match="unsupported"):
        decode_to_pcm_s16le_mono_16k(bogus)
