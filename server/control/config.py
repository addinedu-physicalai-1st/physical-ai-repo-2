"""Control Service settings — env override 가능."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ai_hub_url: str = "http://localhost:8001"
    request_timeout_s: float = 30.0
    control_port: int = 8000

    # DB
    database_url: str = "postgresql+asyncpg://pingder:pingder@localhost:5432/pingdergarten"
    test_database_url: str = (
        "postgresql+asyncpg://pingder:pingder@localhost:5432/pingdergarten_test"
    )

    # 파일 저장소
    face_image_dir: str = "server/storage/face-images"

    # fastapi-users
    secret: str = "dev-secret-change-me"
    cookie_max_age: int = 60 * 60 * 24 * 7   # 7일

    # 얼굴 인식 / 로봇 디바이스
    robot_device_token: str = "dev-robot-token-change-me"
    face_match_threshold: float = 0.45  # cosine distance — 작을수록 엄격

    class Config:
        env_prefix = ""
        env_file = ".env"
        extra = "ignore"


settings = Settings()
