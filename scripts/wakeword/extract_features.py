#!/usr/bin/env python3
"""호출어 학습용 임베딩 추출 — WAV → Google speech embedding (96-dim seq).

openwakeword.utils.AudioFeatures (melspec.onnx + embedding_model.onnx) 으로
positive·negative WAV 의 sequence embedding 을 추출해 .npy 로 저장한다.

출력 구조:
  data/wake_training/features/
    positive/<robot_id>.npy   shape: (N_clips, n_frames, 96)
    negative/speech_kr.npy    shape: (M_clips, n_frames, 96)
    negative/esc50.npy        shape: (K_clips, n_frames, 96)

사용:
  conda run -n wakeword python scripts/wakeword/extract_features.py
  conda run -n wakeword python scripts/wakeword/extract_features.py --kind positive
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

REPO_ROOT = Path(__file__).resolve().parents[2]
# wakeword conda env 에는 `pip install -e .` 가 안 깔려 있으므로 sys.path 주입.
sys.path.insert(0, str(REPO_ROOT / "service" / "ai-service"))
DATA_ROOT = REPO_ROOT / "data" / "wake_training"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument(
        "--kind",
        choices=("all", "positive", "negative", "noise"),
        default="all",
    )
    p.add_argument(
        "--positive-dir",
        type=Path,
        default=DATA_ROOT / "positive",
        help="positive WAV 루트 (각 robot id sub-dir)",
    )
    p.add_argument(
        "--negative-dir",
        type=Path,
        default=DATA_ROOT / "negative",
        help="negative WAV 루트 (각 source sub-dir)",
    )
    p.add_argument(
        "--noise-dir",
        type=Path,
        default=DATA_ROOT / "noise",
        help="noise WAV 루트 (각 source sub-dir, e.g. esc50)",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=DATA_ROOT / "features",
    )
    p.add_argument(
        "--ncpu",
        type=int,
        default=4,
        help="AudioFeatures 의 멀티프로세스 워커 수",
    )
    p.add_argument(
        "--clip-seconds",
        type=float,
        default=2.7,
        help="각 WAV 를 이 길이로 pad/crop 한 뒤 embedding 추출. "
        "Google speech embedding stride ~167ms 라서 2.7s ≈ 16 frame (openwakeword 표준)",
    )
    p.add_argument("--variants", type=int, default=3, help="positive WAV 당 mix variants 수")
    return p.parse_args()


def _list_wavs(root: Path) -> dict[str, list[Path]]:
    """root/sub_id/*.wav 를 sub_id 별로 묶어 반환."""
    out: dict[str, list[Path]] = {}
    if not root.is_dir():
        return out
    for sub in sorted(root.iterdir()):
        if not sub.is_dir():
            continue
        wavs = sorted(sub.glob("*.wav"))
        if wavs:
            out[sub.name] = wavs
    return out


def _load_ambient_pool(realworld_dir: Path, esc50_dir: Path) -> list[np.ndarray]:
    """ambient pool 로드 — realworld + ESC-50 wav 들을 float32 mono 16k 로."""
    paths: list[Path] = []
    if realworld_dir.is_dir():
        paths.extend(sorted(realworld_dir.glob("*.wav")))
    if esc50_dir.is_dir():
        paths.extend(sorted(esc50_dir.glob("*.wav")))
    if not paths:
        raise SystemExit(
            f"ambient pool 비어있음 — {realworld_dir} 또는 {esc50_dir} 에 wav 필요"
        )
    pool: list[np.ndarray] = []
    for p in paths:
        d, sr = sf.read(p, dtype="float32", always_2d=False)
        if d.ndim > 1:
            d = d.mean(axis=1)
        if sr != 16000:
            import librosa
            d = librosa.resample(d, orig_sr=sr, target_sr=16000).astype(np.float32, copy=False)
        pool.append(d)
    print(f"[ambient] {len(pool)} clips loaded ({sum(c.size for c in pool) / 16000:.1f}s total)")
    return pool


def _extract_batch(
    wavs: list[Path],
    af,
    clip_samples: int,
    *,
    mix_pool: list[np.ndarray] | None = None,
    variants: int = 1,
    seed: int = 0,
):
    """WAV 리스트 → embedding (N×variants, T, 96) numpy array.

    mix_pool 주어지면 wake-into-ambient mix builder 통과 (positives 만).
    None 이면 기존 zero-pad 동작 유지 (negatives 용 fallback).
    """
    from ai_service.wake_training.mix import mix_into_ambient

    rng = np.random.default_rng(seed)
    use_mix = mix_pool is not None and len(mix_pool) > 0
    n_out = len(wavs) * (variants if use_mix else 1)
    batch = np.zeros((n_out, clip_samples), dtype=np.int16)

    out_idx = 0
    for i, wav in enumerate(wavs):
        data, sr = sf.read(wav, always_2d=False, dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        if sr != 16000:
            import librosa
            data = librosa.resample(data, orig_sr=sr, target_sr=16000)
        if not use_mix:
            # legacy zero-pad path (negatives)
            if data.size < clip_samples:
                data = np.pad(data, (0, clip_samples - data.size))
            elif data.size > clip_samples:
                data = data[:clip_samples]
            batch[out_idx] = (np.clip(data, -1.0, 1.0) * 32767.0).astype(np.int16)
            out_idx += 1
        else:
            for _ in range(variants):
                clip, _meta = mix_into_ambient(data, mix_pool, rng)
                batch[out_idx] = (np.clip(clip, -1.0, 1.0) * 32767.0).astype(np.int16)
                out_idx += 1

    feats = af.embed_clips(batch, batch_size=64, ncpu=1)
    return np.asarray(feats, dtype=np.float32)


def main() -> int:
    args = parse_args()

    try:
        from openwakeword.utils import AudioFeatures
    except ImportError:
        print("[extract_features] openwakeword 미설치 — wakeword conda env 에서 실행", file=sys.stderr)
        return 1

    af = AudioFeatures(ncpu=args.ncpu, inference_framework="onnx")
    clip_samples = int(args.clip_seconds * 16000)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    targets = []
    if args.kind in ("all", "positive"):
        targets.append(("positive", args.positive_dir, args.out_dir / "positive"))
    if args.kind in ("all", "negative"):
        targets.append(("negative", args.negative_dir, args.out_dir / "negative"))
    if args.kind in ("all", "noise"):
        targets.append(("noise", args.noise_dir, args.out_dir / "noise"))

    # positive 만 mix-into-ambient 사용. negative/noise 는 그대로 zero-pad.
    mix_pool: list[np.ndarray] | None = None
    if args.kind in ("all", "positive"):
        mix_pool = _load_ambient_pool(
            DATA_ROOT / "negative" / "realworld",
            DATA_ROOT / "noise" / "esc50",
        )

    for label, src_root, dst_root in targets:
        dst_root.mkdir(parents=True, exist_ok=True)
        groups = _list_wavs(src_root)
        if not groups:
            print(f"[extract_features] {label}: {src_root} 비어있음 — skip")
            continue
        for sub_id, wavs in groups.items():
            dst = dst_root / f"{sub_id}.npy"
            use_mix = (label == "positive")
            expected_n = len(wavs) * (args.variants if use_mix else 1)
            if dst.exists():
                feats = np.load(dst)
                if feats.shape[0] == expected_n:
                    print(f"  [{label}/{sub_id}] 캐시 일치 ({feats.shape}) — skip")
                    continue
                else:
                    print(f"  [{label}/{sub_id}] 캐시 mismatch (cached {feats.shape[0]} vs expected {expected_n}) — 재추출")
            print(f"  [{label}/{sub_id}] {len(wavs)} WAV × {(args.variants if use_mix else 1)} variants → embedding ...")
            feats = _extract_batch(
                wavs,
                af,
                clip_samples,
                mix_pool=mix_pool if use_mix else None,
                variants=args.variants if use_mix else 1,
                seed=hash(f"{label}/{sub_id}") & 0xFFFFFFFF,
            )
            np.save(dst, feats)
            print(f"    saved {dst}  shape={feats.shape}")

    print("[extract_features] DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
