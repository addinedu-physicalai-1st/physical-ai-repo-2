"""Admin UI client_id 영속 (PLAN §10 Q2: 1회 생성 후 캐시).

`~/.config/pingdergarten-admin/client_id` 에 uuid4 1줄 저장.
앱 매 실행 시 같은 client_id 사용 → 서버 측 client 식별 일관.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path


_CONFIG_DIR_ENV = "XDG_CONFIG_HOME"
_APP_NAME = "pingdergarten-admin"
_FILENAME = "client_id"


def _config_dir() -> Path:
    base = os.environ.get(_CONFIG_DIR_ENV) or os.path.expanduser("~/.config")
    return Path(base) / _APP_NAME


def get_or_create_client_id() -> str:
    """캐시된 client_id 반환. 없으면 uuid4 새로 만들어 저장."""
    path = _config_dir() / _FILENAME
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            # uuid 형식 검증
            uuid.UUID(existing)
            return existing
    except (FileNotFoundError, ValueError, OSError):
        pass

    new_id = str(uuid.uuid4())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_id + "\n", encoding="utf-8")
    except OSError:
        # 영속 실패해도 앱 실행은 계속 (휘발성 id)
        pass
    return new_id
