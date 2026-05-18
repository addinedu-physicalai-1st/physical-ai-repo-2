"""routine YAML 읽기/쓰기 + 슬롯/라이브러리 경로 헬퍼.

레이아웃 (shared/ 아래):
  openarm_greeting/{morning,evening}.yaml         # 슬롯 (모션만)
  openarm_dance/<slug>/motion.yaml                # 라이브러리 (모션)
  openarm_dance/<slug>/song.{mp3,wav,m4a}         # 라이브러리 (곡)
  openarm_dance/<slug>/meta.json                  # 라이브러리 (메타)

YAML 형식:
  name: <str>
  kind: greeting | dance
  recorded_at: ISO8601
  sample_hz: <int>           # 정보 표시용
  joint_names: [...]
  keyframes:
    - { t: <float>, pos: [<8 floats>] }
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from .joint_names import NUM_JOINTS, OPENARM_JOINT_NAMES

logger = logging.getLogger(__name__)

GREETING_SLOTS: tuple[str, ...] = ("morning", "evening")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
AUDIO_EXTS: tuple[str, ...] = (".mp3", ".wav", ".m4a")


# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------


@dataclass
class Keyframe:
    t: float
    pos: list[float]

    def __post_init__(self) -> None:
        if len(self.pos) != NUM_JOINTS:
            raise ValueError(f"keyframe pos must have {NUM_JOINTS} values, got {len(self.pos)}")


@dataclass
class Routine:
    name: str
    kind: str  # "greeting" | "dance"
    keyframes: list[Keyframe]
    sample_hz: int = 50
    recorded_at: str = ""
    joint_names: list[str] = field(default_factory=lambda: list(OPENARM_JOINT_NAMES))

    @property
    def duration_s(self) -> float:
        return self.keyframes[-1].t if self.keyframes else 0.0

    def to_yaml_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "recorded_at": self.recorded_at,
            "sample_hz": self.sample_hz,
            "joint_names": list(self.joint_names),
            "keyframes": [{"t": float(k.t), "pos": [float(x) for x in k.pos]} for k in self.keyframes],
        }


# ---------------------------------------------------------------------------
# path helpers
# ---------------------------------------------------------------------------


def greeting_yaml_path(routines_root: Path, slot: str) -> Path:
    if slot not in GREETING_SLOTS:
        raise ValueError(f"unknown greeting slot {slot!r}; expected one of {GREETING_SLOTS}")
    return routines_root / "openarm_greeting" / f"{slot}.yaml"


def mugunghwa_yaml_path(routines_root: Path) -> Path:
    """무궁화꽃이 피었습니다 (SR-PLAY-004) 의 양팔 가리기 모션 단일 파일.
    재생은 정방향 (가리기) + 역재생 (떼기) 두 번 — 별도 슬롯을 두지 않는다."""
    return routines_root / "openarm_mugunghwa" / "motion.yaml"


def dance_dir(routines_root: Path, slug: str) -> Path:
    if not SLUG_RE.match(slug):
        raise ValueError(f"invalid dance slug {slug!r}; must match {SLUG_RE.pattern}")
    return routines_root / "openarm_dance" / slug


def dance_motion_path(routines_root: Path, slug: str) -> Path:
    return dance_dir(routines_root, slug) / "motion.yaml"


def dance_song_path(routines_root: Path, slug: str) -> Path | None:
    """첫 번째로 발견된 song.* 반환, 없으면 None."""
    d = dance_dir(routines_root, slug)
    if not d.exists():
        return None
    for ext in AUDIO_EXTS:
        p = d / f"song{ext}"
        if p.exists():
            return p
    return None


def dance_meta_path(routines_root: Path, slug: str) -> Path:
    return dance_dir(routines_root, slug) / "meta.json"


# ---------------------------------------------------------------------------
# read / write
# ---------------------------------------------------------------------------


def load_routine(path: Path) -> Routine:
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected mapping at root")
    keyframes_raw = raw.get("keyframes") or []
    keyframes = [Keyframe(t=float(k["t"]), pos=list(k["pos"])) for k in keyframes_raw]
    return Routine(
        name=str(raw.get("name", path.stem)),
        kind=str(raw.get("kind", "greeting")),
        keyframes=keyframes,
        sample_hz=int(raw.get("sample_hz", 50)),
        recorded_at=str(raw.get("recorded_at", "")),
        joint_names=list(raw.get("joint_names", OPENARM_JOINT_NAMES)),
    )


def save_routine(path: Path, routine: Routine) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        yaml.safe_dump(routine.to_yaml_dict(), f, sort_keys=False, allow_unicode=True)
    tmp.replace(path)


# ---------------------------------------------------------------------------
# meta.json (dance only)
# ---------------------------------------------------------------------------


def write_dance_meta(
    routines_root: Path, slug: str, *, display_name: str, duration_s: float, sample_hz: int
) -> None:
    meta = {
        "slug": slug,
        "display_name": display_name,
        "duration_s": round(duration_s, 3),
        "sample_hz": sample_hz,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    p = dance_meta_path(routines_root, slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_dance_meta(routines_root: Path, slug: str) -> dict[str, Any] | None:
    p = dance_meta_path(routines_root, slug)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# library listing
# ---------------------------------------------------------------------------


def list_dances(routines_root: Path) -> list[dict[str, Any]]:
    """라이브러리 목록 (메타 + 곡 파일 존재 여부)."""
    base = routines_root / "openarm_dance"
    if not base.exists():
        return []
    out: list[dict[str, Any]] = []
    for d in sorted(p for p in base.iterdir() if p.is_dir() and SLUG_RE.match(p.name)):
        meta = read_dance_meta(routines_root, d.name) or {"slug": d.name, "display_name": d.name}
        meta["has_song"] = dance_song_path(routines_root, d.name) is not None
        meta["has_motion"] = (d / "motion.yaml").exists()
        out.append(meta)
    return out


def read_mugunghwa(routines_root: Path) -> dict[str, Any] | None:
    """무궁화 단일 모션 메타 — 미녹화는 None."""
    p = mugunghwa_yaml_path(routines_root)
    if not p.exists():
        return None
    try:
        r = load_routine(p)
    except Exception as exc:  # noqa: BLE001
        logger.warning("mugunghwa motion 읽기 실패: %s", exc)
        return None
    return {
        "duration_s": round(r.duration_s, 3),
        "keyframe_count": len(r.keyframes),
        "recorded_at": r.recorded_at,
        "sample_hz": r.sample_hz,
    }


def list_greetings(routines_root: Path) -> dict[str, dict[str, Any] | None]:
    """슬롯 두 개 상태."""
    out: dict[str, dict[str, Any] | None] = {}
    for slot in GREETING_SLOTS:
        p = greeting_yaml_path(routines_root, slot)
        if not p.exists():
            out[slot] = None
            continue
        try:
            r = load_routine(p)
            out[slot] = {
                "slot": slot,
                "duration_s": round(r.duration_s, 3),
                "keyframe_count": len(r.keyframes),
                "recorded_at": r.recorded_at,
                "sample_hz": r.sample_hz,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("greeting slot %s 읽기 실패: %s", slot, exc)
            out[slot] = None
    return out


# ---------------------------------------------------------------------------
# keyframe builders / utilities
# ---------------------------------------------------------------------------


def build_keyframes(samples: Iterable[tuple[float, list[float]]]) -> list[Keyframe]:
    """raw (t, pos) 시퀀스를 Keyframe 리스트로. 시작 t=0 으로 정규화."""
    samples = list(samples)
    if not samples:
        return []
    t0 = samples[0][0]
    return [Keyframe(t=t - t0, pos=list(pos)) for (t, pos) in samples]


def remap_joint_order(
    src_names: list[str], src_pos: list[float], dst_names: list[str]
) -> list[float]:
    """src 명명 → dst 명명 순서로 재정렬. dst 에 없는 joint 는 0.0."""
    idx_by_name = {n: i for i, n in enumerate(src_names)}
    out: list[float] = []
    for name in dst_names:
        i = idx_by_name.get(name)
        out.append(float(src_pos[i]) if i is not None else 0.0)
    return out
