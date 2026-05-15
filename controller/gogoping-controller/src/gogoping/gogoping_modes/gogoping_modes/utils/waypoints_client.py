"""hide-and-seek 등 BT 노드가 control-server 에서 patrol 을 가져오기 위한 헬퍼.
실패 시 로컬 캐시 fallback. control-server 의존성을 단일 실패점에서 제거한다."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import httpx

log = logging.getLogger(__name__)


def _control_url() -> str:
    return os.environ.get("PINGDER_CONTROL_URL", "http://localhost:8000")


def _cache_path(patrol_name: str) -> Path:
    base = Path(os.environ.get("PINGDER_BT_CACHE_DIR", "/tmp/pingder"))
    return base / f"{patrol_name}.json"


def fetch_patrol(patrol_name: str) -> list[tuple[float, float, float]]:
    """Control-server 의 GET /waypoints/patrol/{name} 으로 patrol 멤버 조회.
    성공 시 로컬 캐시에 저장. 실패 시 캐시 fallback. 캐시도 없으면 RuntimeError."""
    cache = _cache_path(patrol_name)
    try:
        r = httpx.get(
            f"{_control_url()}/waypoints/patrol/{patrol_name}",
            timeout=2.0,
        )
        r.raise_for_status()
        data = r.json()
        wps = [(w["x"], w["y"], w["yaw"]) for w in data.get("waypoints", [])]
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(wps))
        return wps
    except (httpx.HTTPError, OSError) as e:
        log.warning(f"control-server 도달 불가 — 캐시 사용: {e}")
        if not cache.exists():
            raise RuntimeError(
                f"control-server 응답 없음, 캐시도 없음 ({cache})"
            )
        return [tuple(w) for w in json.loads(cache.read_text())]
