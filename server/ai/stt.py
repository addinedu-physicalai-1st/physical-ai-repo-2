"""STT (Speech-to-Text) — faster-whisper 기반 짧은 utterance transcribe.

휴대전화에서 Web Speech API 의 마이크 인디케이터 깜빡임을 없애기 위해, 클라이언트가
단일 MediaRecorder stream 으로 클립을 모아 POST /api/stt 로 보내고 여기서 텍스트로 변환한다.

환경변수:
  STT_MODEL_SIZE — faster-whisper 모델 크기 (기본: "tiny", 가능: tiny | base | small | medium | large-v3)
  STT_DEVICE     — "cpu" (기본) | "cuda"
  STT_COMPUTE    — compute_type (기본: "int8")

테스트에서는 `set_transcriber()` 로 fake 를 주입한다.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Callable, Protocol

logger = logging.getLogger(__name__)

_model = None  # faster_whisper.WhisperModel — lazy
_fake_transcribe: Callable[[bytes, str], str] | None = None


class _Transcriber(Protocol):
    def __call__(self, audio_bytes: bytes, language: str) -> str: ...


def set_transcriber(fn: _Transcriber | None) -> None:
    """테스트 훅 — None 으로 호출하면 실제 모델 사용으로 복귀."""
    global _fake_transcribe
    _fake_transcribe = fn


def _get_model():
    """faster-whisper 모델 lazy init. import 도 lazy — 의존성 없을 때 import 실패 회피."""
    global _model
    if _model is not None:
        return _model
    from faster_whisper import WhisperModel  # type: ignore[import-not-found]

    # tiny: 한국어 한 단어 인식률이 너무 낮음. small: 정확하지만 CPU 에서 한 클립 200-400ms.
    # base 가 호출어/짧은 명령 대화에서 latency/정확도 균형점.
    size = os.environ.get("STT_MODEL_SIZE", "base")
    device = os.environ.get("STT_DEVICE", "cpu")
    compute = os.environ.get("STT_COMPUTE", "int8")
    # CPU 추론 시 사용할 thread 개수. CTranslate2 의 기본값(=physical core 수의 절반 정도)
    # 보다 늘리면 단일 짧은 utterance 의 transcribe latency 가 줄어든다.
    try:
        cpu_threads = int(os.environ.get("STT_CPU_THREADS", "8"))
    except ValueError:
        cpu_threads = 8
    logger.info(
        f"loading faster-whisper {size} on {device}/{compute} threads={cpu_threads} (lazy init)"
    )
    _model = WhisperModel(
        size,
        device=device,
        compute_type=compute,
        cpu_threads=cpu_threads,
    )
    return _model


# 호출어/모드 단어를 미리 주입해 짧은 발화에서 모델이 비슷한 음으로 잘못 옮기는 빈도를 낮춘다.
# Whisper 의 `initial_prompt` 은 디코딩 컨텍스트로만 쓰이고 출력엔 포함되지 않는다.
_KO_INITIAL_PROMPT = (
    "에듀핑, 고고핑, 노리암. 등원, 하원, 율동, 인사, 사진, 출석, 자장가, 숨바꼭질, OX 퀴즈, 블럭쌓기, 가게놀이."
)


def transcribe(audio_bytes: bytes, language: str = "ko") -> str:
    """단발 utterance (webm/opus / mp4/aac / wav) 를 텍스트로 변환.

    실패 시 빈 문자열 반환 (라우터에서 적절히 핸들링).
    """
    if _fake_transcribe is not None:
        return _fake_transcribe(audio_bytes, language)

    if not audio_bytes:
        return ""

    # faster-whisper 는 ffmpeg 가 내부에서 컨테이너 디코딩.
    # 클라이언트의 MediaRecorder 가 다양한 MIME 으로 보내도 ffmpeg 이 알아서 디코딩.
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(audio_bytes)
        path = Path(f.name)

    try:
        model = _get_model()
        # vad_filter=False: 클라이언트(useServerSTT)가 이미 RMS VAD 로 utterance 를 잘라 보낸다.
        # Whisper 내부 Silero VAD 는 짧은 한 단어 wake word ("에듀핑" ~600ms) 를 통째로 묵음 처리해서
        # 빈 문자열을 돌려주는 경우가 있어, 호출어 인식이 깨진다.
        # beam_size=1 + best_of=1 + 이전 context off → 짧은 발화 latency 최소화.
        # initial_prompt 으로 호출어/모드 어휘를 미리 알려 디코딩이 첫 토큰부터 올바른 방향으로 가게 한다.
        prompt = _KO_INITIAL_PROMPT if language == "ko" else None
        segments, _info = model.transcribe(
            str(path),
            language=language,
            vad_filter=False,
            beam_size=1,
            best_of=1,
            condition_on_previous_text=False,
            initial_prompt=prompt,
        )
        text = "".join(seg.text for seg in segments).strip()
        return text
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
