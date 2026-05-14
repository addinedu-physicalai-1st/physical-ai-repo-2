"""음성 STT — 휴대전화 MediaRecorder 클립을 받아 텍스트로 변환.

데스크톱은 브라우저 Web Speech API 가 직접 STT 처리. 휴대전화는 webkitSpeechRecognition
의 마이크 인디케이터 깜빡임 회피를 위해 단일 stream 으로 클립을 모아 이 엔드포인트로 보낸다.

요구사항: ffmpeg 가 서버 호스트에 설치되어 있어야 한다 (faster-whisper 가 내부에서 호출).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from server.ai import stt as stt_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["voice"])

# 짧은 utterance 만 받는다 (휴대전화 1-2 문장). 큰 파일은 거부.
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB


@router.post("/stt")
async def post_stt(
    audio: UploadFile = File(...),
    language: str = Form("ko"),
) -> dict:
    """multipart/form-data: audio (webm/opus or mp4/aac), language. → { text }."""
    data = await audio.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "audio 가 비어 있습니다")
    if len(data) > _MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"audio 가 너무 큼 (>{_MAX_BYTES} bytes)")

    logger.info(f"STT received {len(data)} bytes ({audio.content_type}) lang={language}")
    try:
        text = stt_engine.transcribe(data, language=language)
    except Exception as exc:  # noqa: BLE001 — 모델 로딩/디코딩 모든 실패를 500 으로
        logger.exception("STT transcribe failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"STT 실패: {exc}") from exc

    logger.info(f"STT → {text!r}")
    return {"text": text}
