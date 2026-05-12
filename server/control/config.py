"""Control Service settings.

`SECRET`, `DATABASE_URL`, `ROBOT_DEVICE_TOKEN` 세 가지만 `.env` / 환경변수로
override 된다. 나머지 (쿠키 수명·얼굴 매칭 임계값·AI Hub URL 등) 는 튜닝 노브로
취급해 이 파일을 직접 수정한다.
"""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # env_prefix 를 실제로 쓰이지 않는 토큰으로 잠가, validation_alias 가 명시된 필드만
    # 환경변수 / .env 와 결합되도록 한다.
    model_config = SettingsConfigDict(
        env_prefix="__DISABLED__",
        env_file=".env",
        extra="ignore",
    )

    # --- env override 가능 (per-env 시크릿/연결정보) ---
    secret: str = Field(
        default="dev-secret-change-me",
        validation_alias="SECRET",
    )
    # DB. test DB URL 은 database_url 끝에 `_test` 를 붙여 derive 한다 (conftest 참조).
    database_url: str = Field(
        default="postgresql+asyncpg://pingder:pingder@localhost:5432/pingdergarten",
        validation_alias="DATABASE_URL",
    )
    robot_device_token: str = Field(
        default="dev-robot-token-change-me",
        validation_alias="ROBOT_DEVICE_TOKEN",
    )

    # --- 튜닝 노브 (env override 불가, 코드 수정으로만 변경) ---
    ai_hub_url: str = "http://localhost:8001"
    request_timeout_s: float = 30.0
    # 파일 저장소
    face_image_dir: str = "server/storage/face-images"
    # fastapi-users 세션 쿠키 수명(초). 7일.
    cookie_max_age: int = 60 * 60 * 24 * 7
    # 얼굴 매칭 cosine distance — 작을수록 엄격.
    face_match_threshold: float = 0.45


settings = Settings()
