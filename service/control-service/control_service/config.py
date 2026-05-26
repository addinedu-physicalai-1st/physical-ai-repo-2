"""Control Service settings.

`SECRET`, `DATABASE_URL`, `ROBOT_DEVICE_TOKEN`, `AI_HUB_URL` 네 가지가
`.env` / 환경변수로 override 된다. 나머지 (쿠키 수명·얼굴 매칭 임계값 등) 는
튜닝 노브로 취급해 이 파일을 직접 수정한다.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# 프로젝트 루트의 .env 를 로드 (uvicorn/pytest 의 cwd 와 무관하게 동작하도록 절대경로).
load_dotenv(Path(__file__).resolve().parents[3] / ".env")


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
    # 분리 운영 시 robot 박스가 backend 박스 IP 를 주입 (run_control.sh).
    # default 는 같은 머신에 ai-hub 가 있는 로컬 시나리오(run_server.sh) 가정.
    ai_hub_url: str = os.environ.get("AI_HUB_URL", "http://localhost:8001")

    # --- 튜닝 노브 (env 미연동, 코드 수정으로만 변경) ---
    request_timeout_s: float = 30.0
    # 보고서 생성은 Hub→Ollama 가 길 수 있어 별도 상한(초).
    ai_hub_report_timeout_s: float = 300.0
    # 파일 저장소
    face_image_dir: str = "db/storage/face-images"
    # 자연 촬영 사진 — db/storage/photos/{category}/YYYY/MM/DD/{name}.jpg 구조.
    # 카테고리는 `natural`, 추후 `posed` 등이 들어올 수 있다.
    photo_dir: str = "db/storage/photos"
    # fastapi-users 세션 쿠키 수명(초). 7일.
    cookie_max_age: int = 60 * 60 * 24 * 7
    # 얼굴 매칭 cosine distance — 작을수록 엄격.
    # 0.45 는 EduPing 단일 카메라 매칭 기준(같은 머신 등록↔조회). GogoPing 추종 게이트는
    # 등록(웹캠/스마트폰) ↔ D435 (1080p, 다른 조명/거리) 사이 도메인 차로 distance 가
    # 0.55~0.65 구간으로 튄다. photos.py 의 _FACE_MATCH_MAX_DISTANCE=0.75 보단 엄격하게,
    # 같은 머신 매칭 0.45 보단 느슨하게 가져가되, 0.6 은 경계선이라 인증 실패가 잦아
    # 0.7 로 완화 (개발 테스트). 실 운영 전 distance 분포 재측정 후 재조정.
    face_match_threshold: float = 0.7


settings = Settings()
