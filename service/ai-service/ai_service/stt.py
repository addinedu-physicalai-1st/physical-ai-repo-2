"""STT (Speech-to-Text) — faster-whisper 기반 짧은 utterance transcribe.

control-service `webrtc_voice` 가 WebRTC inbound audio 를 Silero VAD 로 잘라
`transcribe_pcm(numpy_pcm, language)` 를 in-process 호출.

device/compute/size 는 머신에 맞춰 자동 감지 (`_autodetect_runtime`):
  - CUDA GPU 감지되면  cuda / float16 / small (5-10배 빠름, 정확도 ↑)
  - GPU 없으면         cpu  / int8    / base  (CPU 안전 디폴트)

테스트에서는 `set_transcriber()` 로 fake 를 주입한다.
"""
from __future__ import annotations

import logging
from typing import Callable, Protocol

logger = logging.getLogger(__name__)

_model = None  # faster_whisper.WhisperModel — lazy
_fake_transcribe: Callable[["object", str], str] | None = None


class _Transcriber(Protocol):
    def __call__(self, pcm: "object", language: str) -> str: ...


def set_transcriber(fn: _Transcriber | None) -> None:
    """테스트 훅 — None 으로 호출하면 실제 모델 사용으로 복귀."""
    global _fake_transcribe
    _fake_transcribe = fn


def _autodetect_runtime() -> tuple[str, str, str]:
    """(device, compute, size) — CUDA GPU 있으면 GPU 프리셋, 없으면 CPU 프리셋.

    CPU 에선 base 가 호출어/짧은 명령 latency/정확도 균형점. GPU 에선 small 이
    정확도 ↑ 면서도 한 클립 100-200ms 라 base 와 latency 차이 미미.

    size 는 STT_WHISPER_SIZE 환경변수로 override (예: medium/large-v3) — 한국어 짧은
    발화 정확도 더 필요할 때. medium 은 ~2.5GB VRAM / ~300-500ms/clip.
    """
    import os

    size_override = os.environ.get("STT_WHISPER_SIZE", "").strip()
    try:
        import ctranslate2  # type: ignore[import-not-found]
        if ctranslate2.get_cuda_device_count() > 0:
            return ("cuda", "float16", size_override or "small")
    except Exception:
        # ctranslate2 import 실패 또는 CUDA 런타임 부재 — CPU 폴백.
        pass
    return ("cpu", "int8", size_override or "base")


def _get_model():
    """faster-whisper 모델 lazy init. import 도 lazy — 의존성 없을 때 import 실패 회피."""
    global _model
    if _model is not None:
        return _model
    from faster_whisper import WhisperModel  # type: ignore[import-not-found]

    device, compute, size = _autodetect_runtime()
    # CPU 추론 thread — CTranslate2 의 기본값(=physical core 수의 절반 정도) 보다 늘리면
    # 짧은 utterance latency 가 줄어든다. GPU 경로에선 사용 안 됨.
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
# robot 미지정 fallback — 모든 호출어 + 일반 단어.
_KO_INITIAL_PROMPT_DEFAULT = (
    "에듀핑, 고고핑, 노리암. 등원, 하원, 율동, 인사, 사진, 출석, 자장가, 숨바꼭질, OX 퀴즈, 블럭쌓기, 가게놀이."
)

# noriarm 가게놀이 음식 단어 — 짧은 "딸기 줘" 발화 STT 정확도. _ko_prompt_for 가 주입.
_NORIARM_FOOD_KEYWORDS = "딸기, 포도, 키위, 브로콜리, 파인애플 줘"
# robot 별 prompt 일 때 같이 보낼 일반 단어. 다른 robot 의 wake word 는 빼고
# 그 robot 의 wake + alias + mode + 일반 어휘만 prompt 로.
_KO_PROMPT_COMMON_TAIL = "인사, 사진, 출석, 자장가."


def _gogoping_waypoint_keywords() -> str:
    """gogoping 목적지(방) 이름 — "놀이방으로 가" 류 발화의 방 이름 STT 정확도.

    waypoints.yaml 의 vertex 이름 중 사람이 부르는 방 이름만 주입한다. 내부 경로
    노드 (`놀-1`/`수-3`/`복-4`/`놀이방입구-상` 등 hyphen 포함) 는 발화 대상이 아니라
    prompt 노이즈가 되므로 제외 → `놀이방, 수면실, 충전소, 출입구, 복도 ...` 만 남는다.
    yaml read 는 가벼움 (< 1ms) 이라 매 utterance 갱신 — yaml 편집이 재배포 없이 반영.
    """
    try:
        from control_service.waypoints import yaml_store as ys
        wps, _ = ys.load()
        names = [w.name for w in wps if w.name and "-" not in w.name]
    except Exception:
        names = []
    return ", ".join(names)


def _ko_prompt_for(
    robot: "str | None",
    extra_keywords: "list[str] | None" = None,
) -> str:
    """robot 별 wake 이름 + 그 robot 의 mode + 일반 단어 + (있으면) extra keyword.

    extra_keywords 는 클라가 현재 mode/stage/library 컨텍스트에서 동적으로 보낸
    expected 단어들 (예: 율동 모드의 등록 곡명, 무궁화 ready 의 '건너뛰기').
    """
    if robot is None and not extra_keywords:
        return _KO_INITIAL_PROMPT_DEFAULT
    parts: list[str] = []
    if robot is not None:
        from ai_service.robots import modes_for, wake_words_for

        names = wake_words_for(robot)
        if names:
            parts.append(", ".join(names))
        mode_words = [m for m in modes_for(robot) if m != "대기"]
        if mode_words:
            parts.append(", ".join(mode_words))
        # 가게놀이 음식 요청 ("딸기 줘" 등) STT 정확도 — noriarm 일 때 음식 단어 주입.
        if robot == "noriarm":
            parts.append(_NORIARM_FOOD_KEYWORDS)
        # "놀이방으로 가" 류 발화 — gogoping 일 때 목적지(방) 이름 주입.
        if robot == "gogoping":
            waypoints = _gogoping_waypoint_keywords()
            if waypoints:
                parts.append(waypoints)
    if extra_keywords:
        cleaned = [k.strip() for k in extra_keywords if k and k.strip()]
        if cleaned:
            parts.append(", ".join(cleaned))
    parts.append(_KO_PROMPT_COMMON_TAIL)
    return ". ".join(parts) if parts else _KO_INITIAL_PROMPT_DEFAULT


def transcribe_pcm(
    pcm: "object",
    language: str = "ko",
    robot: "str | None" = None,
    extra_keywords: "list[str] | None" = None,
) -> str:
    """numpy Float32 PCM mono 16kHz → 텍스트.

    WebRTC 경로 — 이미 16kHz Float32 mono 로 디코딩·리샘플된 audio 를 받아
    파일/ffmpeg 우회. faster-whisper.model.transcribe 가 ndarray 도 지원한다.
    """
    if _fake_transcribe is not None:
        return _fake_transcribe(pcm, language)

    if pcm is None or (hasattr(pcm, "size") and pcm.size == 0):  # type: ignore[union-attr]
        return ""

    model = _get_model()
    # vad_filter=False: 호출자 (webrtc_voice) 가 이미 Silero VAD 로 utterance 를 잘라온다.
    # Whisper 내부 Silero VAD 는 짧은 한 단어 wake word ("에듀핑" ~600ms) 를 통째로 묵음
    # 처리해서 빈 문자열을 돌려주는 경우가 있어, 호출어 인식이 깨진다.
    # beam_size=5: 짧은 한국어 발화 ("율동" 이 "율통" 으로 떨어지는 식) 의 오인식
    # 줄이려고 다양한 후보 탐색. 짧은 발화 한정이라 latency 영향 미미.
    prompt = _ko_prompt_for(robot, extra_keywords) if language == "ko" else None
    segments, _info = model.transcribe(
        pcm,
        language=language,
        vad_filter=False,
        beam_size=5,
        best_of=1,
        condition_on_previous_text=False,
        initial_prompt=prompt,
    )
    return "".join(seg.text for seg in segments).strip()
