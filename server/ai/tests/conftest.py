"""공유 테스트 픽스처 — 일과표 JSON 등 레포 파일을 한 번만 읽는다."""

import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def shared_school_schedule() -> dict[str, str]:
    """`shared/school_schedule.json` — 하드코딩 대신 실제 원본과 동기."""
    path = _REPO_ROOT / "shared" / "school_schedule.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    out = {str(k).strip(): str(v).strip() for k, v in data.items() if str(k).strip() and str(v).strip()}
    assert out, "school_schedule.json 비어 있음"
    return out
