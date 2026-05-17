"""mp3/wav/m4a → PCM s16le mono 16kHz 디코드.

스트리밍 시연에서 audio 청크 송출 전 한 번 전체 디코드. 56kB(awesome-tomato 56s) 정도라
메모리 부담 없음. 디코드 자체는 ffmpeg subprocess (pydub) — eduping 노트북에 ffmpeg 필요.
"""
from __future__ import annotations

from pathlib import Path

from pydub import AudioSegment  # type: ignore[import-not-found]

TARGET_SAMPLE_RATE = 16_000  # Hz
TARGET_WIDTH = 2  # bytes (s16)
TARGET_CHANNELS = 1


def decode_to_pcm_s16le_mono_16k(path: Path) -> tuple[bytes, int]:
    """곡 파일을 PCM s16le mono 16kHz raw bytes 로 변환.

    Returns (pcm_bytes, sample_rate).
    """
    suffix = path.suffix.lower()
    if suffix not in (".mp3", ".wav", ".m4a"):
        raise ValueError(f"unsupported audio extension: {suffix}")
    fmt = {".mp3": "mp3", ".wav": "wav", ".m4a": "m4a"}[suffix]
    seg = AudioSegment.from_file(path, format=fmt)
    seg = seg.set_channels(TARGET_CHANNELS).set_frame_rate(TARGET_SAMPLE_RATE).set_sample_width(TARGET_WIDTH)
    return seg.raw_data, TARGET_SAMPLE_RATE
