"""공유 테스트 픽스처 — 일과표 JSON 등 레포 파일을 한 번만 읽는다.

또한 `eduarm` 모듈 (controller/eduping-controller/src/eduarm) 을 sys.path 에 얹어,
colcon build 없이도 단위 테스트가 import 할 수 있게 한다.
"""

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]

# `eduarm` 은 ROS workspace 패키지 (colcon build 산출물)이지만 일부 모듈만 import
# 하는 단위 테스트에서는 src 트리를 직접 sys.path 에 얹어 쓰는 편이 가볍다.
_EDUARM_SRC = _REPO_ROOT / "controller" / "eduping-controller" / "src" / "eduarm"
if _EDUARM_SRC.exists() and str(_EDUARM_SRC) not in sys.path:
    sys.path.insert(0, str(_EDUARM_SRC))


@pytest.fixture(scope="module")
def shared_school_schedule() -> dict[str, str]:
    """`shared/school_schedule.json` — 하드코딩 대신 실제 원본과 동기."""
    path = _REPO_ROOT / "shared" / "school_schedule.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    out = {str(k).strip(): str(v).strip() for k, v in data.items() if str(k).strip() and str(v).strip()}
    assert out, "school_schedule.json 비어 있음"
    return out
