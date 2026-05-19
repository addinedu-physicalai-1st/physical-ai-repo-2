#!/usr/bin/env python3
"""호출어 분류기 평가 — ONNX 모델에 대한 FRR/FAR 측정.

각 호출어 모델에 대해:
- Positive clip 별로 sliding window max 점수 → FRR (호출어 미인식률)
- Negative window 별 점수 → FAR (false accept 발생률, /hour 환산)

사용:
  conda run -n wakeword python scripts/wakeword/evaluate.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
FEATURES_ROOT = REPO_ROOT / "data" / "wake_training" / "features"
DEFAULT_MODELS = REPO_ROOT / "service" / "ai-service" / "ai_service" / "models" / "wakeword"

# Google speech embedding output: ~80ms 마다 1 frame. 16-frame window = 1.28s.
EMBED_FRAME_HZ = 12.5


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--features-dir", type=Path, default=FEATURES_ROOT)
    p.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS)
    p.add_argument("--window", type=int, default=16)
    p.add_argument(
        "--robot",
        default="all",
        help="평가할 robot id (eduping/gogoping/noriarm/all)",
    )
    p.add_argument(
        "--thresholds",
        nargs="+",
        type=float,
        default=[0.3, 0.5, 0.7, 0.9, 0.95, 0.99],
    )
    return p.parse_args()


def slice_windows_with_owner(feats: np.ndarray, win: int, stride: int = 1):
    """(N, T, D) → (M, win, D), owner: 각 window 가 속한 clip 의 idx (길이 M)."""
    if feats.size == 0:
        return (
            np.empty((0, win, feats.shape[-1] if feats.ndim == 3 else 96), dtype=np.float32),
            np.empty((0,), dtype=np.int64),
        )
    n, t, d = feats.shape
    if t < win:
        feats = np.pad(feats, ((0, 0), (win - t, 0), (0, 0)), mode="edge")
        t = win
    windows = []
    owners = []
    for clip_idx in range(n):
        for s in range(0, t - win + 1, stride):
            windows.append(feats[clip_idx, s : s + win])
            owners.append(clip_idx)
    return np.stack(windows).astype(np.float32), np.asarray(owners, dtype=np.int64)


def _load_features_dir(root: Path) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    if not root.is_dir():
        return out
    for npy in sorted(root.glob("*.npy")):
        out[npy.stem] = np.load(npy)
    return out


def _predict(sess, x: np.ndarray, batch_size: int = 512) -> np.ndarray:
    """배치 단위로 ONNX 추론, 1-D score 배열 반환."""
    input_name = sess.get_inputs()[0].name
    out = []
    for s in range(0, len(x), batch_size):
        chunk = x[s : s + batch_size]
        scores = sess.run(None, {input_name: chunk})[0]
        out.append(np.asarray(scores).reshape(-1))
    return np.concatenate(out) if out else np.empty((0,), dtype=np.float32)


def evaluate_robot(
    robot_id: str,
    onnx_path: Path,
    features: dict,
    thresholds: list[float],
    window: int,
    holdout_ratio: float = 0.2,
    seed: int = 1234,
) -> None:
    import onnxruntime as ort

    print(f"\n[evaluate] === {robot_id} ===  model={onnx_path}")
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])

    # --- positive: hold-out 20% per-clip max score ---
    pos_all = features["positive"].get(robot_id)
    if pos_all is None:
        print(f"  positive features 없음 — skip")
        return
    n_total = pos_all.shape[0]
    rng_split = np.random.default_rng(seed)
    perm = rng_split.permutation(n_total)
    n_holdout = max(1, int(round(n_total * holdout_ratio)))
    holdout_idx = perm[:n_holdout]
    pos = pos_all[holdout_idx]
    print(f"  positive: total={n_total} hold-out={n_holdout} (seed={seed})")

    pos_win, pos_owner = slice_windows_with_owner(pos, window, stride=1)
    pos_scores = _predict(sess, pos_win)
    n_clips = pos.shape[0]
    pos_clip_max = np.zeros(n_clips, dtype=np.float32)
    np.maximum.at(pos_clip_max, pos_owner, pos_scores)
    print(f"  positive: {n_clips} clips, score mean={pos_scores.mean():.3f} max={pos_scores.max():.3f}")

    # --- negative: speech + noise + cross-robot positive ---
    neg_arrays = []
    # speech
    for sid, arr in features["negative"].items():
        neg_arrays.append((f"neg/{sid}", arr))
    # noise
    for sid, arr in features["noise"].items():
        neg_arrays.append((f"noise/{sid}", arr))
    # cross-robot
    for other in features["positive"]:
        if other != robot_id:
            neg_arrays.append((f"cross/{other}", features["positive"][other]))

    all_neg_scores = []
    total_neg_audio_sec = 0.0
    for label, arr in neg_arrays:
        w, _ = slice_windows_with_owner(arr, window, stride=4)
        s = _predict(sess, w)
        n_windows = len(s)
        # 각 window 는 80ms hop × 1 stride → 80 * stride = 320ms 의 streaming 결정.
        # 더 보수적으로: 각 window 의 audio 는 window * 80ms = 1280ms.
        # streaming context 에서는 stride hop 만큼만 새 결정이 일어남.
        audio_sec = n_windows * 4 * (1.0 / EMBED_FRAME_HZ)
        total_neg_audio_sec += audio_sec
        all_neg_scores.append(s)
        print(
            f"  {label}: {len(w)} windows, "
            f"mean={s.mean():.4f} max={s.max():.3f} >0.5 ratio={(s > 0.5).mean():.4f}"
        )
    if not all_neg_scores:
        print("  negative features 없음 — skip")
        return
    neg_scores = np.concatenate(all_neg_scores)
    neg_hours = total_neg_audio_sec / 3600.0
    print(
        f"  total negative: {len(neg_scores)} windows = {total_neg_audio_sec:.0f}s "
        f"= {neg_hours:.2f}h (streaming 환산)"
    )

    # --- 임계값별 FRR / FAR ---
    print(f"\n  {'threshold':>10} {'FRR':>8} {'FAR/hr':>10} {'FA count':>10}")
    print(f"  {'-'*10} {'-'*8} {'-'*10} {'-'*10}")
    for tau in thresholds:
        frr = float((pos_clip_max < tau).mean())
        fa_count = int((neg_scores > tau).sum())
        far_per_hr = fa_count / max(neg_hours, 1e-9)
        print(f"  {tau:>10.3f} {frr:>8.3f} {far_per_hr:>10.2f} {fa_count:>10d}")

    # --- hard-neg 분리 보고 ---
    hard_sources = ("hard_3syl", "hard_3syl_realworld")
    print(f"\n  [hard-neg breakdown]")
    print(f"  {'source':>22} {'N':>5} {'τ=0.5 trig%':>14} {'τ=0.9 trig%':>14} {'τ=0.99 trig%':>14}")
    print(f"  {'-'*22} {'-'*5} {'-'*14} {'-'*14} {'-'*14}")
    for src in hard_sources:
        arr = features["negative"].get(src)
        if arr is None:
            continue
        w, owner = slice_windows_with_owner(arr, window, stride=1)
        s = _predict(sess, w)
        n_clips = arr.shape[0]
        clip_max = np.zeros(n_clips, dtype=np.float32)
        np.maximum.at(clip_max, owner, s)
        trig = lambda t: f"{(clip_max > t).mean() * 100:>11.1f}%"
        print(f"  {src:>22} {n_clips:>5} {trig(0.5):>14} {trig(0.9):>14} {trig(0.99):>14}")


def main() -> int:
    args = parse_args()

    features = {
        "positive": _load_features_dir(args.features_dir / "positive"),
        "negative": _load_features_dir(args.features_dir / "negative"),
        "noise": _load_features_dir(args.features_dir / "noise"),
    }
    if not features["positive"]:
        print("positive features 없음 — extract_features.py 먼저", file=sys.stderr)
        return 1

    robots = (
        list(features["positive"].keys())
        if args.robot == "all"
        else [args.robot]
    )
    for robot_id in robots:
        onnx_path = args.models_dir / f"{robot_id}.onnx"
        if not onnx_path.exists():
            print(f"[evaluate] {onnx_path} 없음 — train.py 먼저", file=sys.stderr)
            continue
        evaluate_robot(robot_id, onnx_path, features, args.thresholds, args.window)

    print("\n[evaluate] DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
