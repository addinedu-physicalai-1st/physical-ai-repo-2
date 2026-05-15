import edge_tts
import logging

async def generate_tts(text: str, voice: str = "ko-KR-SunHiNeural") -> bytes:
    """text 를 음성 바이너리(mp3)로 변환."""
    try:
        communicate = edge_tts.Communicate(text, voice)
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        return audio_data
    except Exception as e:
        logging.error(f"[tts] edge-tts generation failed: {e}")
        return b""
