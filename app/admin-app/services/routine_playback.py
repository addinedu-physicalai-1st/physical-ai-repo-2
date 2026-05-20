"""Standalone playback for recorded EduPing OpenArm routines (dances/greetings).

Reads `shared/openarm_*/{slug}/motion.yaml` directly from the repo, linearly
interpolates between keyframes at the recording's `sample_hz`, and emits each
frame as a synthetic joint snapshot via a callback. Used by the admin app to
preview a routine through the 3D viewer — when paired with the viewer's
`window.setEdupingJointLimits` clipping, this lets the user verify that
saved limits actually constrain the recorded motion.

Crucially: this NEVER touches the real arm. It's a viewer-side simulation
that uses the SAME joint-state pump path as the live rclpy subscriber, so all
the existing limit-clipping and joint-name handling apply automatically.

Independent of any backend service — reads YAML files via PyYAML (already a
common dep). If PyYAML is unavailable, listing returns empty.
"""
from __future__ import annotations

import bisect
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

JointStateCallback = Callable[[dict], Any]


def _try_yaml() -> Any:
    try:
        import yaml
        return yaml
    except Exception as e:  # noqa: BLE001
        logger.info("PyYAML import 실패 — routine 재생 비활성: %s", e)
        return None


def _shared_root() -> Path:
    """Repo's `shared/` directory — independent of cwd."""
    # app/admin-app/services/<this>.py → up 3 = repo root
    return Path(__file__).resolve().parents[3] / "shared"


# Routine "kinds" mapped to their on-disk subdir.
_KIND_DIRS = {
    "dance": "openarm_dance",
    "greeting": "openarm_greeting",
    "mugunghwa": "openarm_mugunghwa",  # single file, not per-slug
}


def list_routines() -> list[dict[str, str]]:
    """Returns [{kind, slug, display_name, path, duration_s}, ...].

    Walks shared/openarm_dance/, openarm_greeting/, openarm_mugunghwa/.
    Missing dirs are silently skipped. Each entry's `path` is the absolute
    motion.yaml path.
    """
    yaml = _try_yaml()
    if yaml is None:
        return []
    root = _shared_root()
    out: list[dict[str, str]] = []

    # Dance/greeting: shared/openarm_<kind>/<slug>/motion.yaml + meta.json
    for kind in ("dance", "greeting"):
        kind_dir = root / _KIND_DIRS[kind]
        if not kind_dir.is_dir():
            continue
        for slug_dir in sorted(kind_dir.iterdir()):
            if not slug_dir.is_dir():
                continue
            motion = slug_dir / "motion.yaml"
            if not motion.is_file():
                continue
            display = slug_dir.name
            duration = 0.0
            meta = slug_dir / "meta.json"
            if meta.is_file():
                try:
                    import json as _json
                    data = _json.loads(meta.read_text(encoding="utf-8"))
                    display = str(data.get("display_name") or display)
                    duration = float(data.get("duration_s") or 0.0)
                except Exception:  # noqa: BLE001
                    pass
            out.append({
                "kind": kind,
                "slug": slug_dir.name,
                "display_name": display,
                "path": str(motion),
                "duration_s": str(duration),
            })

    # Mugunghwa: single motion.yaml file, no slug.
    mug = root / _KIND_DIRS["mugunghwa"] / "motion.yaml"
    if mug.is_file():
        out.append({
            "kind": "mugunghwa",
            "slug": "mugunghwa",
            "display_name": "무궁화꽃이 피었습니다 (가리기 동작)",
            "path": str(mug),
            "duration_s": "0",
        })

    return out


class _LoadedRoutine:
    """Parsed motion.yaml — joint_names, keyframes (sorted by t), duration_s."""

    __slots__ = ("joint_names", "kf_times", "kf_positions", "duration_s")

    def __init__(
        self,
        joint_names: list[str],
        keyframes: list[tuple[float, list[float]]],
    ) -> None:
        keyframes.sort(key=lambda kf: kf[0])
        self.joint_names = joint_names
        self.kf_times = [kf[0] for kf in keyframes]
        self.kf_positions = [kf[1] for kf in keyframes]
        self.duration_s = keyframes[-1][0] if keyframes else 0.0

    def interp(self, t: float) -> list[float]:
        if not self.kf_times:
            return []
        if t <= self.kf_times[0]:
            return list(self.kf_positions[0])
        if t >= self.kf_times[-1]:
            return list(self.kf_positions[-1])
        i = bisect.bisect_right(self.kf_times, t) - 1
        i = max(0, min(i, len(self.kf_times) - 2))
        ta, tb = self.kf_times[i], self.kf_times[i + 1]
        a, b = self.kf_positions[i], self.kf_positions[i + 1]
        if tb - ta <= 1e-9:
            return list(a)
        alpha = (t - ta) / (tb - ta)
        return [pa + (pb - pa) * alpha for pa, pb in zip(a, b)]


def _load_routine(path: str) -> _LoadedRoutine | None:
    yaml = _try_yaml()
    if yaml is None:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:  # noqa: BLE001
        logger.warning("routine 로드 실패 %s: %s", path, e)
        return None
    if not isinstance(data, dict):
        return None
    joint_names = data.get("joint_names")
    raw_kfs = data.get("keyframes")
    if not isinstance(joint_names, list) or not isinstance(raw_kfs, list):
        return None
    keyframes: list[tuple[float, list[float]]] = []
    for kf in raw_kfs:
        if not isinstance(kf, dict):
            continue
        try:
            t = float(kf["t"])
            pos = [float(p) for p in kf["pos"]]
        except (KeyError, TypeError, ValueError):
            continue
        if len(pos) != len(joint_names):
            continue
        keyframes.append((t, pos))
    if not keyframes:
        return None
    return _LoadedRoutine([str(n) for n in joint_names], keyframes)


def load_recording_dense(path: str, hz: float = 30.0) -> dict | None:
    """녹화를 균등 시간 간격(`hz`Hz)으로 dense 하게 sample → JS 비교 popup 용.

    Compare popup 은 PyQt 의 frame pump 없이 JS 안에서 자체 재생한다 → Qt/JS
    bridge 왕복을 매 frame 마다 안 해도 됨 → lag 감소. 그 대신 popup 이 keyframe
    interp 까지 하기엔 너무 복잡해서, PyQt 가 미리 dense frame 배열을 깐다.

    Returns {"joint_names": [...], "frames": [[float, ...], ...],
             "frame_hz": hz, "duration_s": float} or None.
    """
    routine = _load_routine(path)
    if routine is None or routine.duration_s <= 0 or hz <= 0:
        return None
    dt = 1.0 / float(hz)
    n_frames = max(1, int(routine.duration_s * hz) + 1)
    frames: list[list[float]] = []
    for i in range(n_frames):
        t = i * dt
        if t > routine.duration_s:
            t = routine.duration_s
        frames.append(routine.interp(t))
    return {
        "joint_names": list(routine.joint_names),
        "frames": frames,
        "frame_hz": float(hz),
        "duration_s": float(routine.duration_s),
    }


def load_recording_for_scan(path: str) -> dict | None:
    """녹화 YAML 을 읽어 JS-가능한 dict 로 변환 — viewer 의 충돌 분석용.

    Returns {"joint_names": [...], "frames": [[float, ...], ...]} or None.
    frames 는 keyframe pose 들을 시간 순서대로 그대로 펼친다 (interp 없음).
    JS 측은 매 frame 에 robot.setJointValue → updateMatrixWorld → AABB 충돌 검사.
    """
    routine = _load_routine(path)
    if routine is None:
        return None
    return {
        "joint_names": list(routine.joint_names),
        "frames": [list(p) for p in routine.kf_positions],
    }


def save_clipped_copy(
    *,
    source_path: str,
    source_kind: str,
    source_slug: str,
    limits: dict[str, dict[str, float]],
    suffix: str = "-safe",
) -> tuple[bool, str]:
    """Read the source motion.yaml, clip each keyframe to `limits`, and write a
    NEW directory next to the original — never overwrites the source.

    Layout for dance/greeting (per-slug dirs):
        shared/openarm_<kind>/<slug>/motion.yaml          (source, untouched)
        shared/openarm_<kind>/<slug><suffix>/motion.yaml  (new, clipped)
        shared/openarm_<kind>/<slug><suffix>/meta.json    (copy + display tweak)
    The song file (if dance) is copied so the new slug plays with audio.

    Returns (ok, message). `message` is the new directory path on success or an
    error string.
    """
    yaml = _try_yaml()
    if yaml is None:
        return False, "PyYAML 미설치 — 저장 불가"
    if source_kind not in ("dance", "greeting"):
        return False, "dance/greeting 만 저장 지원 (mugunghwa 는 게임 전용)"

    src_path = Path(source_path)
    if not src_path.is_file():
        return False, f"원본 파일 없음: {src_path}"

    try:
        with src_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:  # noqa: BLE001
        return False, f"원본 로드 실패: {e!r}"
    if not isinstance(data, dict):
        return False, "원본 형식 오류 (dict 아님)"

    raw_kfs = data.get("keyframes")
    joint_names_data = data.get("joint_names")
    if not isinstance(raw_kfs, list) or not isinstance(joint_names_data, list):
        return False, "원본 형식 오류 (keyframes / joint_names 누락)"

    # Build a per-joint (lo, hi) lookup; missing joints pass through.
    lim_lookup: dict[str, tuple[float, float]] = {}
    for name, row in (limits or {}).items():
        if not isinstance(row, dict):
            continue
        try:
            lo = float(row["min"])
            hi = float(row["max"])
        except (KeyError, TypeError, ValueError):
            continue
        if lo > hi:
            lo, hi = hi, lo
        lim_lookup[str(name)] = (lo, hi)

    clipped_count = 0
    new_keyframes = []
    for kf in raw_kfs:
        if not isinstance(kf, dict):
            continue
        try:
            t = float(kf["t"])
            pos = list(kf["pos"])
        except (KeyError, TypeError, ValueError):
            continue
        new_pos = []
        for i, name in enumerate(joint_names_data):
            v = float(pos[i]) if i < len(pos) else 0.0
            lim = lim_lookup.get(str(name))
            if lim is not None:
                lo, hi = lim
                if v < lo:
                    v = lo
                    clipped_count += 1
                elif v > hi:
                    v = hi
                    clipped_count += 1
            new_pos.append(v)
        new_keyframes.append({"t": t, "pos": new_pos})

    new_data = dict(data)
    new_slug = f"{source_slug}{suffix}"
    new_data["name"] = new_slug
    new_data["keyframes"] = new_keyframes

    src_dir = src_path.parent
    new_dir = src_dir.parent / new_slug
    if new_dir.exists():
        return False, f"이미 존재: {new_dir} — 기존 안전본 삭제 후 다시 시도"
    try:
        new_dir.mkdir(parents=True, exist_ok=False)
    except OSError as e:
        return False, f"디렉토리 생성 실패: {e}"

    new_path = new_dir / "motion.yaml"
    try:
        with new_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(new_data, f, allow_unicode=True, sort_keys=False)
    except Exception as e:  # noqa: BLE001
        return False, f"motion.yaml 저장 실패: {e!r}"

    # meta.json — copy and update slug/display_name + clip-count breadcrumb.
    src_meta = src_dir / "meta.json"
    if src_meta.is_file():
        try:
            import json as _json
            meta = _json.loads(src_meta.read_text(encoding="utf-8"))
            meta["slug"] = new_slug
            old_display = str(meta.get("display_name") or source_slug)
            meta["display_name"] = f"{old_display} (안전본)"
            meta["safe_clipped_from"] = source_slug
            meta["safe_clipped_count"] = clipped_count
            (new_dir / "meta.json").write_text(
                _json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            pass

    # Song copy — dance recordings only.
    if source_kind == "dance":
        for song_name in ("song.mp3", "song.wav", "song.m4a"):
            src_song = src_dir / song_name
            if src_song.is_file():
                try:
                    import shutil
                    shutil.copy2(src_song, new_dir / song_name)
                except Exception:  # noqa: BLE001
                    pass
                break

    return True, (
        f"저장 완료: {new_dir} (clip 적용 {clipped_count}개 좌표)"
    )


class RoutinePlayback:
    """Plays a recorded routine in a daemon thread, calling `on_frame(snap)`
    for each interpolated frame at the recording's native rate.

    Snap dict shape matches what the rclpy subscriber emits — so the admin
    dashboard can pipe `on_frame` straight into its `_joint_state_received`
    signal and the rest of the viewer plumbing works unchanged.

    Lifecycle: `start(path)` → runs in background → calls `on_frame(snap)`
    repeatedly and finally `on_finished()`. `stop()` is idempotent.
    """

    def __init__(
        self,
        *,
        on_frame: JointStateCallback,
        on_finished: Callable[[], Any] | None = None,
        rate_hz: float = 50.0,
    ) -> None:
        self._on_frame = on_frame
        self._on_finished = on_finished
        self._period_s = 1.0 / float(rate_hz)
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._progress_s = 0.0
        self._duration_s = 0.0
        self._last_error: str | None = None

    @property
    def progress_s(self) -> float:
        return self._progress_s

    @property
    def duration_s(self) -> float:
        return self._duration_s

    @property
    def is_playing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def start(self, path: str) -> bool:
        if self.is_playing:
            self.stop()
        routine = _load_routine(path)
        if routine is None:
            self._last_error = "routine 로드 실패 (PyYAML 미설치 또는 파일 손상)"
            return False
        self._last_error = None
        self._duration_s = routine.duration_s
        self._progress_s = 0.0
        self._stopping.clear()
        self._thread = threading.Thread(
            target=self._run, args=(routine,),
            name="admin-routine-playback", daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _run(self, routine: _LoadedRoutine) -> None:
        try:
            t_start = time.monotonic()
            while not self._stopping.is_set():
                t = time.monotonic() - t_start
                if t > routine.duration_s:
                    break
                self._progress_s = t
                positions = routine.interp(t)
                snap = {
                    "joint_names": list(routine.joint_names),
                    "positions": positions,
                    "velocities": [],
                    "stamp_sec": int(time.time()),
                    "stamp_nanosec": 0,
                }
                try:
                    self._on_frame(snap)
                except Exception as e:  # noqa: BLE001
                    logger.warning("on_frame 콜백 실패: %s", e)
                time.sleep(self._period_s)
            self._progress_s = routine.duration_s
        finally:
            if self._on_finished is not None:
                try:
                    self._on_finished()
                except Exception:  # noqa: BLE001
                    pass
