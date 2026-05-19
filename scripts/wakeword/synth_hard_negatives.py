#!/usr/bin/env python3
"""3음절 한국어 hard negative 셋 합성 — MMS-TTS 로 단어 list → wav.

기존 wake-word positive 합성 (`scripts/wakeword/synthesize.py`) 의 MMS 백엔드를
재사용. 단어당 N variants (default 3) 를 다른 augmentation 으로 만들어
`data/wake_training/negative/hard_3syl/<word>_<idx>.wav` 로 저장.

사용:
  conda run -n wakeword python scripts/wakeword/synth_hard_negatives.py
  conda run -n wakeword python scripts/wakeword/synth_hard_negatives.py --per-word 5 --count-limit 10
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "service" / "ai-service"))

from ai_service.wake_training.augment import build_augment  # noqa: E402
from ai_service.wake_training.tts import MmsKoSynth  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument(
        "--word-list",
        type=Path,
        default=REPO_ROOT / "data" / "wake_training" / "hard_neg_words.txt",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "data" / "wake_training" / "negative" / "hard_3syl",
    )
    p.add_argument("--per-word", type=int, default=3, help="단어당 augmented variants")
    p.add_argument("--count-limit", type=int, default=0, help=">0 면 단어 list 상위 N개만 합성 (smoke test 용)")
    p.add_argument("--seed", type=int, default=0)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    words = [w.strip() for w in args.word_list.read_text(encoding="utf-8").splitlines() if w.strip()]
    if args.count_limit > 0:
        words = words[:args.count_limit]
    print(f"[hard-neg] {len(words)} words × {args.per_word} variants = {len(words) * args.per_word} files")

    synth = MmsKoSynth()
    augment = build_augment()
    np.random.seed(args.seed)
    written = 0
    for w_idx, word in enumerate(words):
        try:
            res = synth.synthesize(word)
        except Exception as exc:  # noqa: BLE001
            print(f"  [skip] {word}: {exc.__class__.__name__}: {exc}")
            continue
        for v in range(args.per_word):
            aug = augment(samples=res.samples, sample_rate=res.sample_rate)
            fname = f"{w_idx:03d}_{v:02d}_{word}.wav"
            sf.write(args.out_dir / fname, aug, res.sample_rate, subtype="FLOAT")
            written += 1
    print(f"[hard-neg] done — {written} files → {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
