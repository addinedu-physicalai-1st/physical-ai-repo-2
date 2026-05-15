"""shared/waypoints.yaml 단일 read/write 진입점."""

from __future__ import annotations

import math
import os
import shutil
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


# 가장 최근에 add() 한 노드 이름 — undo_last_add() 의 단일 step 대상.
# 모듈 변수 (단일 서버 프로세스 가정). 서버 재시작 시 리셋.
_RECENT_ADD: str | None = None


def add(name: str, x: float, y: float, yaw: float) -> Waypoint:
    global _RECENT_ADD
    wps, patrols = load()
    wp = Waypoint(name=name, x=float(x), y=float(y), yaw=float(yaw))
    save([*wps, wp], patrols)
    _RECENT_ADD = name
    return wp


def undo_last_add() -> Waypoint | None:
    """가장 최근에 add() 한 노드 1개만 되돌림.
    - 아무것도 add 안 했거나 이미 undo 후엔 None.
    - 해당 노드에 lane 이 잇혀있으면 WaypointStoreError('node_has_lanes')."""
    global _RECENT_ADD
    if _RECENT_ADD is None:
        return None
    name = _RECENT_ADD
    if any(ln.from_ == name or ln.to == name for ln in load_lanes()):
        raise WaypointStoreError("node_has_lanes")
    try:
        wp = get(name)
    except KeyError:
        _RECENT_ADD = None
        return None
    wps, patrols = load()
    save([w for w in wps if w.name != name], patrols)
    _RECENT_ADD = None
    return wp


def rename(old: str, new: str) -> Waypoint:
    """노드 이름 변경 + lanes / patrols 참조 cascade 갱신.
    new 가 이미 다른 노드의 이름이면 WaypointStoreError."""
    new = new.strip()
    if not new:
        raise WaypointStoreError("new name is empty")
    wps, patrols = load()
    if old == new:
        # no-op 이지만 노드 존재 확인은 함
        return get(old)
    names = {w.name for w in wps}
    if old not in names:
        raise KeyError(old)
    if new in names:
        raise WaypointStoreError(f"이미 같은 이름의 노드가 있어요: '{new}'")
    new_list = [
        Waypoint(name=new if w.name == old else w.name, x=w.x, y=w.y, yaw=w.yaw, id=w.id)
        for w in wps
    ]
    # patrols cascade — old 가 들어가있던 자리를 new 로
    new_patrols = {
        p: [new if m == old else m for m in members]
        for p, members in patrols.items()
    }
    save(new_list, new_patrols)
    # lanes cascade — from/to 갱신
    existing_lanes = load_lanes()
    updated_lanes = [
        Lane(
            from_=new if ln.from_ == old else ln.from_,
            to=new if ln.to == old else ln.to,
            bidirectional=ln.bidirectional,
        )
        for ln in existing_lanes
    ]
    if updated_lanes != existing_lanes:
        save_lanes(updated_lanes)
    return next(w for w in new_list if w.name == new)


def update(name: str, x: float, y: float, yaw: float) -> Waypoint:
    """노드 좌표/yaw 만 변경. 이름은 그대로. patrol/lane 참조에 영향 없음."""
    wps, patrols = load()
    found = None
    new_list: list[Waypoint] = []
    for w in wps:
        if w.name == name:
            found = Waypoint(name=w.name, x=float(x), y=float(y), yaw=float(yaw), id=w.id)
            new_list.append(found)
        else:
            new_list.append(w)
    if found is None:
        raise KeyError(name)
    save(new_list, patrols)
    return found


def remove(name: str) -> list["Lane"]:
    """노드 + 해당 노드 참여 lane cascade 제거.
    반환: 함께 제거된 lane 목록 (UI 가 confirm dialog 에 표시용)."""
    wps, patrols = load()
    if not any(w.name == name for w in wps):
        raise KeyError(name)
    for pname, members in patrols.items():
        if name in members:
            raise WaypointStoreError(
                f"'{name}' 은 patrol '{pname}' 에서 사용 중 — 먼저 patrol 에서 빼주세요"
            )
    existing_lanes = load_lanes()
    cascaded = [ln for ln in existing_lanes if ln.from_ == name or ln.to == name]
    kept_lanes = [ln for ln in existing_lanes if ln.from_ != name and ln.to != name]
    # lanes 먼저 저장 — validate 의 from/to 검증은 노드 삭제 전이라 통과
    save_lanes(kept_lanes)
    save([w for w in wps if w.name != name], patrols)
    return cascaded


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


@dataclass(frozen=True)
class Lane:
    """양방향 (또는 단방향) lane. yaml key `from` 는 파이썬 예약어라 `from_` 으로."""
    from_: str
    to: str
    bidirectional: bool = True


class LaneStoreError(Exception):
    pass


def _lanes_path() -> Path:
    return Path(os.environ.get(
        "PINGDER_LANES_FILE",
        str(_path().parent / "lanes.yaml"),
    ))


def load_lanes() -> list[Lane]:
    """lanes.yaml → list[Lane]. 없으면 빈 리스트."""
    p = _lanes_path()
    if not p.exists():
        return []
    raw = p.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    data = yaml.safe_load(raw) or {}
    out: list[Lane] = []
    for entry in data.get("lanes", []) or []:
        out.append(Lane(
            from_=entry["from"],
            to=entry["to"],
            bidirectional=bool(entry.get("bidirectional", True)),
        ))
    return out


def _default_path() -> Path:
    return Path(os.environ.get(
        "PINGDER_WAYPOINTS_DEFAULT_FILE",
        str(_path().parent / "waypoints.default.yaml"),
    ))


def _lanes_default_path() -> Path:
    return Path(os.environ.get(
        "PINGDER_LANES_DEFAULT_FILE",
        str(_lanes_path().parent / "lanes.default.yaml"),
    ))


def snapshot_default() -> None:
    """working waypoints.yaml → waypoints.default.yaml."""
    src = _path()
    dst = _default_path()
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def restore_default() -> int:
    """waypoints.default.yaml → working. 반환: 노드 개수."""
    src = _default_path()
    if not src.exists():
        raise FileNotFoundError(f"{src} 없음 — 먼저 snapshot_default() 호출 필요")
    dst = _path()
    shutil.copyfile(src, dst)
    return len(load()[0])


def snapshot_default_lanes() -> None:
    """working lanes.yaml → lanes.default.yaml."""
    src = _lanes_path()
    if not src.exists():
        save_lanes([])   # 빈 working 도 동결 가능하게 빈 파일 생성
    dst = _lanes_default_path()
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def restore_default_lanes() -> int:
    """lanes.default.yaml → working. 반환: lane 개수."""
    src = _lanes_default_path()
    if not src.exists():
        raise FileNotFoundError(f"{src} 없음")
    dst = _lanes_path()
    shutil.copyfile(src, dst)
    return len(load_lanes())


def _lanes_match(a: Lane, from_: str, to: str) -> bool:
    """양방향 lane 의 어느 방향이든 매칭."""
    if a.bidirectional:
        return (a.from_ == from_ and a.to == to) or (a.from_ == to and a.to == from_)
    return a.from_ == from_ and a.to == to


def add_lane(from_: str, to: str, bidirectional: bool = True) -> Lane:
    existing = load_lanes()
    for ln in existing:
        if _lanes_match(ln, from_, to):
            raise LaneStoreError("lane_exists")
    new = Lane(from_=from_, to=to, bidirectional=bidirectional)
    save_lanes([*existing, new])  # save_lanes 의 validate 가 from/to 존재 검증
    return new


def remove_lane(from_: str, to: str) -> None:
    existing = load_lanes()
    kept = [ln for ln in existing if not _lanes_match(ln, from_, to)]
    if len(kept) == len(existing):
        raise KeyError(f"lane({from_}→{to}) 없음")
    save_lanes(kept)


def save_lanes(lanes: list[Lane]) -> None:
    """atomic write — tmp → fsync → os.replace().
    validate: 모든 from/to 가 waypoints.yaml 에 존재해야 함."""
    wp_names = {w.name for w in load()[0]}
    for ln in lanes:
        if ln.from_ not in wp_names:
            raise LaneStoreError(f"lane.from='{ln.from_}' waypoint 없음")
        if ln.to not in wp_names:
            raise LaneStoreError(f"lane.to='{ln.to}' waypoint 없음")
    data = {"lanes": [
        {"from": ln.from_, "to": ln.to, "bidirectional": ln.bidirectional}
        for ln in lanes
    ]}
    p = _lanes_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".lanes-", suffix=".tmp", dir=str(p.parent))
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
