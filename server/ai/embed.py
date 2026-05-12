"""Ollama 임베딩 호출 — RAG 용 텍스트 → 벡터 변환.

설정 모델: bge-m3 (1024 차원). 프로젝트 표준.
chat 모델과는 별개로 임베딩 전용 모델을 별도 호출한다.
"""
import httpx

from server.ai.config import EMBED_DIM, EMBED_MODEL, settings


class EmbedError(Exception):
    pass


async def embed_text(text: str) -> list[float]:
    """텍스트 → 1024 차원 벡터. 실패 시 EmbedError raise."""
    payload = {"model": EMBED_MODEL, "input": text}
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
            response = await client.post(
                f"{settings.ollama_host}/api/embed",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise EmbedError(f"Ollama embed 통신 실패: {exc}") from exc

    embeddings = data.get("embeddings")
    if not embeddings or not isinstance(embeddings, list):
        raise EmbedError(f"빈 임베딩 응답: {data}")
    vec = embeddings[0]
    if len(vec) != EMBED_DIM:
        raise EmbedError(f"임베딩 차원 불일치: {len(vec)} (기대 {EMBED_DIM})")
    return vec
