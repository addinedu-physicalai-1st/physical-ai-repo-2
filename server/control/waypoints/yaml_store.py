"""shared/waypoints.yaml 단일 read/write 진입점."""

from __future__ import annotations

import math
import os
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path

import yaml

# repo root 기준 자동 경로 — 사용자 home 디렉토리 이름과 무관.
# server/control/waypoints/yaml_store.py → parents[3] = repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PATH = (
    _REPO_ROOT
    / "device" / "gogoping_ws" / "src" / "gogoping"
    / "gogoping_navigation" / "config" / "waypoints.yaml"
)


def _path() -> Path:
    """매 호출 시 환경변수 확인 — 테스트가 monkeypatch 로 바꿀 수 있도록."""
    return Path(os.environ.get("PINGDER_WAYPOINTS_FILE", str(DEFAULT_PATH)))


@dataclass(frozen=True)
class Waypoint:
    name: str
    x: float
    y: float
    yaw: float
    id: int | None = None


class WaypointStoreError(Exception):
    pass


def validate(data: dict) -> None:
    """schema + 참조 무결성."""
    wps = data.get("waypoints", []) or []
    names = set()
    for i, w in enumerate(wps):
        if not isinstance(w, dict):
            raise WaypointStoreError(f"waypoints[{i}] is not a dict")
        for k in ("name", "x", "y", "yaw"):
            if k not in w:
                raise WaypointStoreError(f"waypoints[{i}] missing '{k}'")
        if not isinstance(w["name"], str) or not w["name"].strip():
            raise WaypointStoreError(f"waypoints[{i}].name must be non-empty str")
        if w["name"] in names:
            raise WaypointStoreError(f"중복 이름: {w['name']}")
        names.add(w["name"])
        for k in ("x", "y", "yaw"):
            v = w[k]
            if not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v):
                raise WaypointStoreError(f"waypoints[{i}].{k} 가 NaN/Inf")
    patrols = data.get("patrols", {}) or {}
    for pname, members in patrols.items():
        if not isinstance(members, list):
            raise WaypointStoreError(f"patrols.{pname} must be list")
        for m in members:
            if m not in names:
                raise WaypointStoreError(
                    f"patrols.{pname} 의 '{m}' waypoint 없음"
                )


def load() -> tuple[list[Waypoint], dict[str, list[str]]]:
    p = _path()
    if not p.exists():
        return [], {}
    raw = p.read_text(encoding="utf-8").strip()
    if not raw:
        return [], {}
    data = yaml.safe_load(raw) or {}
    validate(data)
    wps = [Waypoint(**w) for w in data.get("waypoints", [])]
    patrols = data.get("patrols", {}) or {}
    return wps, patrols


def save(waypoints: list[Waypoint], patrols: dict[str, list[str]]) -> None:
    """atomic write — tmp → fsync → os.replace()."""
    data = {
        "waypoints": [asdict(w) for w in waypoints],
        "patrols": dict(patrols),
    }
    validate(data)
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".waypoints-", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def add(name: str, x: float, y: float, yaw: float) -> Waypoint:
    wps, patrols = load()
    wp = Waypoint(name=name, x=float(x), y=float(y), yaw=float(yaw))
    save([*wps, wp], patrols)
    return wp


def remove(name: str) -> None:
    wps, patrols = load()
    if not any(w.name == name for w in wps):
        raise KeyError(name)
    for pname, members in patrols.items():
        if name in members:
            raise WaypointStoreError(
                f"'{name}' 은 patrol '{pname}' 에서 사용 중 — 먼저 patrol 에서 빼주세요"
            )
    save([w for w in wps if w.name != name], patrols)


def get(name: str) -> Waypoint:
    for w in load()[0]:
        if w.name == name:
            return w
    raise KeyError(name)


def get_patrol(patrol_name: str) -> list[Waypoint]:
    wps, patrols = load()
    if patrol_name not in patrols:
        raise KeyError(patrol_name)
    by_name = {w.name: w for w in wps}
    return [by_name[m] for m in patrols[patrol_name]]
