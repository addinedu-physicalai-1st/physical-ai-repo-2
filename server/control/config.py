"""Control Service settings.

`SECRET`, `DATABASE_URL`, `ROBOT_DEVICE_TOKEN` 세 가지만 `.env` / 환경변수로
override 된다. 나머지 (쿠키 수명·얼굴 매칭 임계값·AI Hub URL 등) 는 튜닝 노브로
취급해 이 파일을 직접 수정한다.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# 프로젝트 루트의 .env 를 로드 (uvicorn/pytest 의 cwd 와 무관하게 동작하도록 절대경로).
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


@dataclass
class Settings:
    # --- env override 가능 (per-env 시크릿/연결정보) ---
    secret: str = os.environ.get("SECRET", "dev-secret-change-me")
    # DB. test DB URL 은 database_url 끝에 `_test` 를 붙여 derive 한다 (conftest 참조).
    database_url: str = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://pingder:pingder@localhost:5432/pingdergarten",
    )
    robot_device_token: str = os.environ.get(
        "ROBOT_DEVICE_TOKEN", "dev-robot-token-change-me"
    )

    # --- 튜닝 노브 (env 미연동, 코드 수정으로만 변경) ---
    ai_hub_url: str = "http://localhost:8001"
    request_timeout_s: float = 30.0
    # 보고서 생성은 Hub→Ollama 가 길 수 있어 별도 상한(초).
    ai_hub_report_timeout_s: float = 300.0
    # 파일 저장소
    face_image_dir: str = "server/storage/face-images"
    # 자연 촬영 사진 — server/storage/photos/{category}/YYYY/MM/DD/{name}.jpg 구조.
    # 카테고리는 `natural`, 추후 `posed` 등이 들어올 수 있다.
    photo_dir: str = "server/storage/photos"
    # fastapi-users 세션 쿠키 수명(초). 7일.
    cookie_max_age: int = 60 * 60 * 24 * 7
    # 얼굴 매칭 cosine distance — 작을수록 엄격.
    face_match_threshold: float = 0.45


settings = Settings()
