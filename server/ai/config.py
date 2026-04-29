"""Settings — env 로 override 가능 (`OLLAMA_HOST`, `OLLAMA_MODEL`, `AI_PORT` 등)."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_chat_model: str = "gemma3:4b"
    request_timeout_s: float = 30.0
    ai_port: int = 8001

    class Config:
        env_prefix = ""


settings = Settings()
