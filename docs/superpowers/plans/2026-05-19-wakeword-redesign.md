# Wake-word 재설계 (cycle 6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 학습 데이터를 "wake word + zero pad" 에서 "wake word at random offset within continuous 2.7s ambient" 로 재구조화하여 브라우저 raw audio 가 학습 분포와 일치하도록 만들고, 3음절 한국어 hard negatives 로 false-accept 도 잡는다.

**Architecture:** openwakeword 의 melspec + embedding + binary classifier 3-stage 파이프라인 유지. `mix_into_ambient` 새 builder 가 학습 positives 를 production 입력 분포와 매칭. 브라우저는 raw audio 만 흘림 (VAD-compact 등 inference-side hack 제거).

**Tech Stack:** Python (numpy, soundfile, librosa), openwakeword, MMS-TTS Korean, ONNX runtime, conda env `wakeword`, TypeScript / Vue 3.

**Spec:** [docs/superpowers/specs/2026-05-19-wakeword-redesign-design.md](../specs/2026-05-19-wakeword-redesign-design.md)

---

## File Structure

| 파일 | 역할 |
|---|---|
| `service/ai-service/ai_service/wake_training/mix.py` (새) | `mix_into_ambient` 함수 단일 모듈. wake WAV + ambient pool → 2.7s continuous clip. |
| `service/ai-service/ai_service/tests/test_wake_training_mix.py` (새) | mix builder 단위 테스트 (pytest). |
| `data/wake_training/hard_neg_words.txt` (새) | 한국어 3음절 단어 시드 list (~50). |
| `scripts/wakeword/synth_hard_negatives.py` (새) | MMS-TTS 로 hard negative word list 합성 → `data/wake_training/negative/hard_3syl/`. |
| `scripts/wakeword/record_realworld.py` (수정) | `hard-negative` 서브커맨드 추가 — 실음성 hard neg 녹음. |
| `scripts/wakeword/extract_features.py` (수정) | positive 추출에 `mix_into_ambient` 사용 + N=3 variants. hard-neg 디렉토리 추가. |
| `scripts/wakeword/evaluate.py` (수정) | eval positive 도 mix builder 통과. hard-neg metric 분리 보고. |
| `service/web-service/robot-web/src/composables/useWakeWord.ts` (수정) | VAD-compact / stride / dump 제거. raw audio path 로 회귀. |
| `service/web-service/robot-web/src/composables/useVoiceController.ts` (수정) | WAKE_THRESHOLDS 갱신, log threshold 조정. useTTS fix 유지. |
| `wakeword-plan.md` (수정) | cycle 6 결과 섹션 추가. |

---

## Task 1: `mix.py` — 출력 길이/타입

**Files:**
- Create: `service/ai-service/ai_service/wake_training/mix.py`
- Test: `service/ai-service/ai_service/tests/test_wake_training_mix.py`

- [ ] **Step 1: Write the failing test**

```python
# service/ai-service/ai_service/tests/test_wake_training_mix.py
import numpy as np
import pytest

from ai_service.wake_training.mix import mix_into_ambient


@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.fixture
def wake_clip():
    # 0.7s of synthetic sine wave at 16kHz
    sr = 16000
    t = np.arange(int(0.7 * sr)) / sr
    return (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


@pytest.fixture
def ambient_pool():
    # 3 clips of 5s ambient at 16kHz (white noise low amplitude)
    rng = np.random.default_rng(0)
    return [
        (rng.standard_normal(int(5 * 16000)) * 0.02).astype(np.float32)
        for _ in range(3)
    ]


def test_output_length_and_dtype(wake_clip, ambient_pool, rng):
    out, meta = mix_into_ambient(wake_clip, ambient_pool, rng)
    assert out.shape == (43200,)
    assert out.dtype == np.float32
    assert isinstance(meta, dict)
    assert 'offset_sec' in meta
    assert 'snr_db' in meta
    assert 'ambient_idx' in meta
```

- [ ] **Step 2: Run test to verify it fails**

```bash
conda run -n wakeword pytest service/ai-service/ai_service/tests/test_wake_training_mix.py::test_output_length_and_dtype -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ai_service.wake_training.mix'`

- [ ] **Step 3: Write minimal implementation**

```python
# service/ai-service/ai_service/wake_training/mix.py
"""Wake-word + continuous ambient mix builder — production 분포에 맞춰
학습용 2.7s positive 클립을 만든다.

학습 데이터를 "wake word + literal zero" 에서 "wake at random offset within
continuous ambient" 로 바꿔, 브라우저가 흘리는 raw audio 와 분포 일치시킨다.
"""
from __future__ import annotations

import numpy as np

_TARGET_SR = 16000


def mix_into_ambient(
    wake: np.ndarray,
    ambient_pool: list[np.ndarray],
    rng: np.random.Generator,
    target_sec: float = 2.7,
    snr_db_range: tuple[float, float] = (5.0, 20.0),
) -> tuple[np.ndarray, dict]:
    """wake word 를 ambient 위에 random offset 으로 mix.

    Returns:
        out: float32, length = round(target_sec * 16000) = 43200 for default
        meta: {'offset_sec', 'snr_db', 'ambient_idx', 'wake_duration_sec'}
    """
    if not ambient_pool:
        raise ValueError("ambient_pool 가 비어있다")
    target_samples = int(round(target_sec * _TARGET_SR))
    amb_idx = int(rng.integers(0, len(ambient_pool)))
    amb_src = ambient_pool[amb_idx]
    # slice or cyclic concat to target_samples
    if amb_src.size >= target_samples:
        start = int(rng.integers(0, amb_src.size - target_samples + 1))
        ambient = amb_src[start:start + target_samples].astype(np.float32, copy=True)
    else:
        reps = int(np.ceil(target_samples / max(amb_src.size, 1)))
        ambient = np.tile(amb_src, reps)[:target_samples].astype(np.float32, copy=True)
    # offset
    wake_arr = np.asarray(wake, dtype=np.float32).reshape(-1)
    wake_len = min(wake_arr.size, target_samples)
    max_offset = target_samples - wake_len
    offset = int(rng.integers(0, max(1, max_offset + 1)))
    # SNR scaling
    snr_db = float(rng.uniform(*snr_db_range))
    rms_wake = float(np.sqrt(np.mean(wake_arr[:wake_len].astype(np.float64) ** 2) + 1e-12))
    rms_amb = float(np.sqrt(np.mean(ambient.astype(np.float64) ** 2) + 1e-12))
    if rms_amb > 1e-9 and rms_wake > 1e-9:
        target_rms_amb = rms_wake / (10 ** (snr_db / 20.0))
        ambient *= np.float32(target_rms_amb / rms_amb)
    # mix
    out = ambient
    out[offset:offset + wake_len] += wake_arr[:wake_len]
    np.clip(out, -1.0, 1.0, out=out)
    meta = {
        'offset_sec': offset / _TARGET_SR,
        'snr_db': snr_db,
        'ambient_idx': amb_idx,
        'wake_duration_sec': wake_len / _TARGET_SR,
    }
    return out, meta
```

- [ ] **Step 4: Run test to verify it passes**

```bash
conda run -n wakeword pytest service/ai-service/ai_service/tests/test_wake_training_mix.py::test_output_length_and_dtype -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add service/ai-service/ai_service/wake_training/mix.py \
        service/ai-service/ai_service/tests/test_wake_training_mix.py
git commit -m "feat(wake): mix_into_ambient builder skeleton + output shape test"
```

---

## Task 2: `mix.py` — SNR 정확도

**Files:**
- Modify: `service/ai-service/ai_service/tests/test_wake_training_mix.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append to test_wake_training_mix.py
def test_snr_within_tolerance(wake_clip, ambient_pool):
    """meta['snr_db'] 가 실제 측정 SNR 과 ±1.5dB 이내."""
    rng = np.random.default_rng(7)
    out, meta = mix_into_ambient(wake_clip, ambient_pool, rng)
    off = int(meta['offset_sec'] * 16000)
    wake_len = int(meta['wake_duration_sec'] * 16000)
    sig_segment = out[off:off + wake_len]
    # 발화 구간 전체 power − 같은 길이 ambient-only 구간 power 차이로 SNR 추정
    # ambient-only 추정: 발화 직전 동일 길이 (없으면 직후)
    if off >= wake_len:
        amb_segment = out[off - wake_len:off]
    else:
        amb_segment = out[off + wake_len:off + 2 * wake_len]
    p_sig = float(np.mean(sig_segment.astype(np.float64) ** 2))
    p_amb = float(np.mean(amb_segment.astype(np.float64) ** 2))
    # p_sig = p_wake + p_amb_scaled  →  p_wake = p_sig - p_amb
    p_wake = max(p_sig - p_amb, 1e-12)
    measured_snr = 10 * np.log10(p_wake / max(p_amb, 1e-12))
    assert abs(measured_snr - meta['snr_db']) < 1.5, (
        f"measured {measured_snr:.2f}dB vs meta {meta['snr_db']:.2f}dB"
    )
```

- [ ] **Step 2: Run test to verify it fails or passes**

```bash
conda run -n wakeword pytest service/ai-service/ai_service/tests/test_wake_training_mix.py::test_snr_within_tolerance -v
```

Expected: PASS (Task 1 의 구현이 SNR 도 처리). FAIL 이면 mix.py 의 SNR 계산을 점검.

- [ ] **Step 3: 기능 추가 없음 — Task 1 코드가 이미 충분**

(이 task 는 빨간 테스트 추가가 아닌 green 검증. 다음 step 으로 진행)

- [ ] **Step 4: 전체 테스트 재실행으로 회귀 없음 확인**

```bash
conda run -n wakeword pytest service/ai-service/ai_service/tests/test_wake_training_mix.py -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add service/ai-service/ai_service/tests/test_wake_training_mix.py
git commit -m "test(wake): SNR accuracy within 1.5dB tolerance for mix builder"
```

---

## Task 3: `mix.py` — offset placement 정확도

**Files:**
- Modify: `service/ai-service/ai_service/tests/test_wake_training_mix.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append
def test_offset_places_wake_at_reported_position(wake_clip, ambient_pool):
    """meta['offset_sec'] 위치에서 RMS 가 ambient-only 구간보다 명확히 큰지."""
    rng = np.random.default_rng(11)
    out, meta = mix_into_ambient(wake_clip, ambient_pool, rng,
                                  snr_db_range=(10.0, 10.0))  # 고정 SNR 로 시그널이 ambient 보다 약 3x 큼
    off = int(meta['offset_sec'] * 16000)
    wake_len = int(meta['wake_duration_sec'] * 16000)
    # wake 구간 RMS
    wake_rms = float(np.sqrt(np.mean(out[off:off + wake_len] ** 2)))
    # 비교용 ambient 구간 — wake 외 0.2s (3200 샘플) 영역
    ambient_region = np.concatenate([out[:off], out[off + wake_len:]])
    amb_rms = float(np.sqrt(np.mean(ambient_region ** 2))) if ambient_region.size else 0.0
    assert wake_rms > amb_rms * 2.0, (
        f"wake_rms {wake_rms:.4f} <= 2× amb_rms {amb_rms:.4f} at offset {off}"
    )
```

- [ ] **Step 2: Run test**

```bash
conda run -n wakeword pytest service/ai-service/ai_service/tests/test_wake_training_mix.py::test_offset_places_wake_at_reported_position -v
```

Expected: PASS

- [ ] **Step 3: 기능 추가 없음**

- [ ] **Step 4: 회귀 확인**

```bash
conda run -n wakeword pytest service/ai-service/ai_service/tests/test_wake_training_mix.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add service/ai-service/ai_service/tests/test_wake_training_mix.py
git commit -m "test(wake): mix builder places wake at reported offset"
```

---

## Task 4: `mix.py` — 짧은 ambient cyclic 처리

**Files:**
- Modify: `service/ai-service/ai_service/tests/test_wake_training_mix.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append
def test_short_ambient_cycled_to_fill(wake_clip):
    """ambient 클립이 1s 만 있어도 cyclic concat 으로 2.7s 채워짐."""
    rng = np.random.default_rng(13)
    short_amb = (rng.standard_normal(16000) * 0.02).astype(np.float32)  # 1s
    out, _ = mix_into_ambient(wake_clip, [short_amb], rng)
    assert out.shape == (43200,)
    # 출력 어디든 RMS > 0 (zero gap 없음)
    chunk_rms = np.array([
        np.sqrt(np.mean(out[i:i+1600] ** 2)) for i in range(0, 43200, 1600)
    ])
    assert (chunk_rms > 1e-5).all(), f"some chunks have ~0 RMS: {chunk_rms}"
```

- [ ] **Step 2: Run test**

```bash
conda run -n wakeword pytest service/ai-service/ai_service/tests/test_wake_training_mix.py::test_short_ambient_cycled_to_fill -v
```

Expected: PASS

- [ ] **Step 3: 기능 추가 없음**

- [ ] **Step 4: 회귀 확인**

```bash
conda run -n wakeword pytest service/ai-service/ai_service/tests/test_wake_training_mix.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add service/ai-service/ai_service/tests/test_wake_training_mix.py
git commit -m "test(wake): cyclic concat for ambient shorter than target_sec"
```

---

## Task 5: `mix.py` — determinism

**Files:**
- Modify: `service/ai-service/ai_service/tests/test_wake_training_mix.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append
def test_determinism_with_same_seed(wake_clip, ambient_pool):
    """동일 seed 의 rng 두 개로 두 번 호출하면 byte-identical."""
    rng_a = np.random.default_rng(99)
    rng_b = np.random.default_rng(99)
    out_a, meta_a = mix_into_ambient(wake_clip, ambient_pool, rng_a)
    out_b, meta_b = mix_into_ambient(wake_clip, ambient_pool, rng_b)
    assert np.array_equal(out_a, out_b)
    assert meta_a == meta_b
```

- [ ] **Step 2: Run test**

```bash
conda run -n wakeword pytest service/ai-service/ai_service/tests/test_wake_training_mix.py::test_determinism_with_same_seed -v
```

Expected: PASS

- [ ] **Step 3: 기능 추가 없음**

- [ ] **Step 4: 회귀 확인**

```bash
conda run -n wakeword pytest service/ai-service/ai_service/tests/test_wake_training_mix.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add service/ai-service/ai_service/tests/test_wake_training_mix.py
git commit -m "test(wake): mix builder is deterministic with seeded rng"
```

---

## Task 6: Hard negative seed word list

**Files:**
- Create: `data/wake_training/hard_neg_words.txt`

- [ ] **Step 1: Create seed list file**

`data/wake_training/hard_neg_words.txt` 에 다음 내용 (한 줄 한 단어):

```text
안녕해
어떻게
이상해
행복해
사진해
자장가
어디서
학교에
어머니
아버지
선생님
가까이
친구야
미안해
사랑해
일어나
들어가
도와줘
들어와
잠시만
빨리해
사과해
어디야
누구야
어느쪽
새로운
즐거워
재밌어
따뜻해
시원해
조심해
힘들어
무서워
신기해
대단해
열심히
편안해
귀여워
보고싶
짜증나
배고파
졸려요
깨끗해
빠르게
천천히
가만히
조용히
앉으세
가져와
물어봐
대답해
이리와
저리가
앞으로
위로요
아래로
멀리서
시작해
끝났어
계속해
```

- [ ] **Step 2: Verify file**

```bash
wc -l data/wake_training/hard_neg_words.txt
```

Expected: `60 data/wake_training/hard_neg_words.txt`

- [ ] **Step 3: (No impl step — seed data only)**

- [ ] **Step 4: (No verification beyond Step 2)**

- [ ] **Step 5: Commit**

```bash
git add data/wake_training/hard_neg_words.txt
git commit -m "data(wake): seed 60 Korean 3-syllable hard-negative words"
```

---

## Task 7: `synth_hard_negatives.py` 합성 스크립트

**Files:**
- Create: `scripts/wakeword/synth_hard_negatives.py`

- [ ] **Step 1: Write skeleton + smoke test (no separate test file — script main as test)**

```python
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
```

- [ ] **Step 2: Smoke test (5 words only)**

```bash
conda run -n wakeword python scripts/wakeword/synth_hard_negatives.py --count-limit 5 --per-word 2
```

Expected:
- 출력에 `[hard-neg] 5 words × 2 variants = 10 files` 와 `[hard-neg] done — 10 files`
- `ls data/wake_training/negative/hard_3syl/*.wav | wc -l` → 10

- [ ] **Step 3: (Script 자체가 구현 + 검증)**

- [ ] **Step 4: Full run (전체 60 단어, 단어당 3)**

```bash
conda run -n wakeword python scripts/wakeword/synth_hard_negatives.py
ls data/wake_training/negative/hard_3syl/*.wav | wc -l
```

Expected: 180 files (60 × 3). 합성 시간 약 5-10분.

- [ ] **Step 5: Commit**

```bash
git add scripts/wakeword/synth_hard_negatives.py
git commit -m "feat(wake): synth_hard_negatives.py — MMS-TTS for 3-syllable hard negs"
```

(WAV 자체는 `.gitignore` 의 `data/` 패턴으로 제외됨 — 확인: `git status data/wake_training/negative/hard_3syl/` 가 빈 출력이면 OK.)

---

## Task 8: `record_realworld.py` — `hard-negative` 서브커맨드

**Files:**
- Modify: `scripts/wakeword/record_realworld.py`

- [ ] **Step 1: Read existing positive_mode to mirror structure**

```bash
grep -n "def positive_mode\|def negative_mode\|sub = p.add_subparsers" scripts/wakeword/record_realworld.py | head
```

(Step 1 단순 inspection — 코드 변경 없음)

- [ ] **Step 2: Add `hard_negative_mode` function**

`scripts/wakeword/record_realworld.py` 의 `negative_mode` 함수 바로 아래 (마지막 mode 함수 뒤) 에 추가:

```python
def hard_negative_mode(args: argparse.Namespace) -> None:
    """실음성 hard negative 녹음 — 사용자 prompt loop 로 3음절 단어 발화 캡쳐."""
    import soundfile as sf

    if args.device is None:
        args.device = auto_detect_input_device()

    word_list_path: Path = args.word_list
    if not word_list_path.is_file():
        raise SystemExit(f"word list 없음: {word_list_path}")
    words = [w.strip() for w in word_list_path.read_text(encoding="utf-8").splitlines() if w.strip()]
    if args.limit > 0:
        words = words[:args.limit]

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[hard-neg] {len(words)} 단어 녹음. {SEED_PREFIX}_ prefix.")
    print(f"  키: [Enter]=녹음  r=재녹음  s=skip  q=종료  p=미리듣기\n")

    saved = 0
    skipped = 0
    for i, word in enumerate(words):
        prompt_head = f"[{i+1}/{len(words)}] '{word}'"
        key = input(f"{prompt_head}  > ").strip().lower()
        if key == "q":
            break
        if key == "s":
            skipped += 1
            continue
        print(f"  🎙️ 녹음 중 ({args.max_sec}s)...", end="", flush=True)
        samples = record_segment(args.max_sec, device=args.device)
        trimmed, dur, rms, status = trim_and_validate(samples)
        print(f" dur={dur:.2f}s rms={rms:.3f} status={status}")
        if status != "ok":
            print(f"    품질 낮음 — skip")
            continue
        while True:
            act = input("    저장? [Y / r=재녹음 / p=미리듣기 / s=skip]: ").strip().lower()
            if act == "p":
                play_back(trimmed)
                continue
            if act in ("", "y"):
                fname = f"{SEED_PREFIX}_{i:05d}_{word}.wav"
                sf.write(out_dir / fname, trimmed, SR, subtype="FLOAT")
                saved += 1
                break
            if act == "s":
                skipped += 1
                break
            if act == "r":
                break  # 다음 input 단계로 — 같은 word 다시
    print(f"\n[hard-neg] saved={saved} skipped={skipped}")
```

- [ ] **Step 3: Wire subparser**

`parse_args()` 안 `sub = p.add_subparsers(dest="mode", required=True)` 블록의 `mic_test_mode` 추가 부분 근처에 다음 추가:

```python
    hn = sub.add_parser("hard-negative", help="3음절 한국어 hard negative 발화 녹음 (prompt loop)")
    hn.add_argument(
        "--word-list",
        type=Path,
        default=REPO_ROOT / "data" / "wake_training" / "hard_neg_words.txt",
    )
    hn.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "data" / "wake_training" / "negative" / "hard_3syl_realworld",
    )
    hn.add_argument("--max-sec", type=float, default=1.5)
    hn.add_argument("--limit", type=int, default=30, help=">0 면 word list 상위 N개만 (default 30)")
    hn.add_argument("--device", type=int, default=None)
```

그리고 `main()` 의 mode dispatch 에 추가:

```python
    elif args.mode == "hard-negative":
        hard_negative_mode(args)
```

- [ ] **Step 4: Smoke test — print help**

```bash
conda run -n pdg python scripts/wakeword/record_realworld.py hard-negative --help
```

Expected: argparse help 출력에 `--word-list`, `--limit` 등 보임. (실제 녹음은 수동 단계라 자동 검증 불가.)

- [ ] **Step 5: Commit**

```bash
git add scripts/wakeword/record_realworld.py
git commit -m "feat(wake): hard-negative recording subcommand for record_realworld.py"
```

---

## Task 9: `extract_features.py` — ambient pool 헬퍼

**Files:**
- Modify: `scripts/wakeword/extract_features.py`

- [ ] **Step 1: Add helper function**

`scripts/wakeword/extract_features.py` 의 `_extract_batch` 함수 바로 위에 다음 helper 추가 (import 도 같이 갱신):

파일 상단 import 블록 갱신 — 기존:
```python
from __future__ import annotations
import argparse
import sys
from pathlib import Path
```

다음으로:
```python
from __future__ import annotations
import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
```

그리고 `_list_wavs` 아래쪽에:

```python
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
```

- [ ] **Step 2: Smoke test — import + helper call**

```bash
conda run -n wakeword python -c "
import sys
sys.path.insert(0, 'scripts/wakeword')
from extract_features import _load_ambient_pool
from pathlib import Path
pool = _load_ambient_pool(
    Path('data/wake_training/negative/realworld'),
    Path('data/wake_training/noise/esc50'),
)
print(f'pool size: {len(pool)}, total dur: {sum(c.size for c in pool)/16000:.1f}s')
"
```

Expected: `pool size: <N>, total dur: <T>s` — `N` 은 직접 녹음 ambient + ESC-50 합산, `T` 는 분 단위 이상.

- [ ] **Step 3: (구현 — Step 1 에 포함됨)**

- [ ] **Step 4: (검증 — Step 2 에 포함됨)**

- [ ] **Step 5: Commit**

```bash
git add scripts/wakeword/extract_features.py
git commit -m "feat(wake): _load_ambient_pool helper for mix-into-ambient extraction"
```

---

## Task 10: `extract_features.py` — positive 에 mix builder 적용

**Files:**
- Modify: `scripts/wakeword/extract_features.py`

- [ ] **Step 1: Patch `_extract_batch` 와 `main`**

기존 `_extract_batch` 시그니처:
```python
def _extract_batch(wavs: list[Path], af, clip_samples: int):
```
를 다음으로 교체:

```python
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
    import numpy as np
    import soundfile as sf

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
```

`main` 안에서 ambient pool 로드 및 positive 호출 분기:

기존 main 의 `targets` loop 부분:
```python
    for label, src_root, dst_root in targets:
        ...
        for sub_id, wavs in groups.items():
            ...
            feats = _extract_batch(wavs, af, clip_samples)
            np.save(dst, feats)
```
를 다음으로 교체:

```python
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
```

또한 argparse 에 `--variants` 추가:

```python
    p.add_argument("--variants", type=int, default=3, help="positive WAV 당 mix variants 수")
```

- [ ] **Step 2: Smoke test — eduping 한 robot 만 추출**

```bash
# 캐시 무효화
rm -f data/wake_training/features/positive/eduping.npy
conda run -n wakeword python scripts/wakeword/extract_features.py --kind positive --variants 3
```

Expected:
- `[ambient] N clips loaded` 보임
- `[positive/eduping] 680 WAV × 3 variants → embedding ...` 형태
- 출력 `.npy` 의 shape 0번이 약 680 × 3 = 2040

검증:
```bash
conda run -n wakeword python -c "
import numpy as np
a = np.load('data/wake_training/features/positive/eduping.npy')
print(a.shape, a.dtype)
"
```
Expected: `(2040, 24, 96) float32` (또는 source 갯수에 비례).

- [ ] **Step 3: (구현 — Step 1)**

- [ ] **Step 4: 모든 robot positive 재추출**

```bash
rm -f data/wake_training/features/positive/*.npy
conda run -n wakeword python scripts/wakeword/extract_features.py --kind positive
```

Expected: 3 robot 의 .npy 가 생성됨 (각 약 N × 3).

- [ ] **Step 5: Commit**

```bash
git add scripts/wakeword/extract_features.py
git commit -m "feat(wake): extract_features uses mix_into_ambient for positives (3 variants)"
```

---

## Task 11: `extract_features.py` — hard-neg 디렉토리 추가

**Files:**
- Modify: `scripts/wakeword/extract_features.py`

- [ ] **Step 1: Add hard-neg directory to negative targets**

`main` 의 targets 구성 부분:
```python
    if args.kind in ("all", "negative"):
        targets.append(("negative", args.negative_dir, args.out_dir / "negative"))
```
를 다음으로 교체:

```python
    if args.kind in ("all", "negative"):
        targets.append(("negative", args.negative_dir, args.out_dir / "negative"))
        # hard-neg 두 종류 — 합성 + 실음성
        hard_synth = DATA_ROOT / "negative" / "hard_3syl"
        hard_real = DATA_ROOT / "negative" / "hard_3syl_realworld"
        for hn_dir in (hard_synth, hard_real):
            if hn_dir.is_dir() and any(hn_dir.glob("*.wav")):
                # hard-neg 들은 각각 단일 그룹으로 묶음 — sub_id 가 디렉토리 이름
                targets.append((
                    "negative",
                    hn_dir.parent,  # parent → _list_wavs 가 sub_id 기준 그룹화
                    args.out_dir / "negative",
                ))
                break  # 한 번만 추가 (parent 가 같음)
```

**잠깐 — 이 구조는 `_list_wavs` 가 sub-dir 의 wav 를 sub_id 별로 묶기 때문에 자연스럽게 `hard_3syl`, `hard_3syl_realworld` 가 각각 별도 `.npy` 로 생김.** 기존 `realworld/` 도 같이 묶이지만 사이즈 비대해서 따로 두는 게 낫다 — 위 분기는 단순화. 실제 구현은 다음과 같이:

```python
    if args.kind in ("all", "negative"):
        targets.append(("negative", args.negative_dir, args.out_dir / "negative"))
```

`args.negative_dir` 가 `data/wake_training/negative` 라 그 하위의 모든 sub-dir (`realworld`, `hard_3syl`, `hard_3syl_realworld`) 가 자동으로 잡힘. **이 task 는 코드 변경 없이 디렉토리 존재 만 확인하면 됨**:

```bash
ls data/wake_training/negative/
```

Expected: `realworld/`, `hard_3syl/` (Task 7 산출물), 옵션으로 `hard_3syl_realworld/`.

- [ ] **Step 2: Smoke test — negative extraction**

```bash
rm -f data/wake_training/features/negative/hard_3syl.npy
conda run -n wakeword python scripts/wakeword/extract_features.py --kind negative
ls data/wake_training/features/negative/
```

Expected: `hard_3syl.npy`, `realworld.npy` (이미 있으면 캐시) 둘 다 보임.

- [ ] **Step 3: (코드 변경 없음 — `_list_wavs` 의 자동 sub-dir 그룹화로 자연 지원)**

- [ ] **Step 4: 검증**

```bash
conda run -n wakeword python -c "
import numpy as np
a = np.load('data/wake_training/features/negative/hard_3syl.npy')
print('hard_3syl:', a.shape)
"
```

Expected: shape[0] ≈ 180 (60 단어 × 3 variants), dtype float32.

- [ ] **Step 5: (Task 10 의 commit 에 포함됨 — 별도 commit 불필요)**

만약 위 단계에서 `extract_features.py` 에 새 코드를 안 넣었다면 commit 도 없음. 출력 .npy 들은 `.gitignore` 로 제외.

---

## Task 12: `evaluate.py` — eval positive 도 mix builder

**Files:**
- Modify: `scripts/wakeword/evaluate.py`

- [ ] **Step 1: Patch `_load_features_dir` + add mix-eval branch**

기존 `evaluate.py` 의 `_load_features_dir` 가 `.npy` 만 로드함. 우리는 학습 측 features 를 그대로 쓰면 됨 — `extract_features.py` 가 이미 mix 적용한 features 를 생성.

문제: 학습 features 는 robot 당 N × variants 의 mix 결과. 평가에 그대로 쓰면 학습/평가 split 없음 → 과추정.

**간단한 해결**: features 의 hold-out 20% 를 eval set 으로. 코드에서:

`evaluate_robot` 함수 시작부:
```python
def evaluate_robot(
    robot_id: str,
    onnx_path: Path,
    features: dict,
    thresholds: list[float],
    window: int,
) -> None:
    import onnxruntime as ort
    print(f"\n[evaluate] === {robot_id} ===  model={onnx_path}")
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])

    # --- positive: per-clip max score ---
    pos = features["positive"].get(robot_id)
    if pos is None:
        ...
```
를 다음으로 수정 — hold-out split 추가:

```python
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
```

(나머지 함수는 그대로)

- [ ] **Step 2: Smoke test — 기존 onnx 로 evaluate 실행**

```bash
conda run -n wakeword python scripts/wakeword/evaluate.py --robot eduping 2>&1 | tail -30
```

Expected: `hold-out=NN (seed=1234)` 라인 보임. threshold table 출력. 기존보다 hold-out 만 평가하므로 FRR 가 약간 변동 가능.

- [ ] **Step 3: (구현 — Step 1)**

- [ ] **Step 4: (검증 — Step 2)**

- [ ] **Step 5: Commit**

```bash
git add scripts/wakeword/evaluate.py
git commit -m "feat(wake): evaluate.py uses 20% hold-out for positive FRR"
```

---

## Task 13: `evaluate.py` — hard-neg metric 분리 보고

**Files:**
- Modify: `scripts/wakeword/evaluate.py`

- [ ] **Step 1: Patch evaluate_robot — hard-neg 별도 보고**

기존 negative loop:
```python
    # speech
    for sid, arr in features["negative"].items():
        neg_arrays.append((f"neg/{sid}", arr))
```
는 그대로 두고, threshold table 다음에 hard-neg 별도 출력 추가. `evaluate_robot` 끝부분 (threshold 표 출력 후) 에 다음 추가:

```python
    # --- hard-neg 분리 보고 ---
    hard_sources = ("hard_3syl", "hard_3syl_realworld")
    print(f"\n  [hard-neg breakdown]")
    print(f"  {'source':>22} {'τ=0.5 trig%':>14} {'τ=0.9 trig%':>14} {'τ=0.99 trig%':>14}")
    print(f"  {'-'*22} {'-'*14} {'-'*14} {'-'*14}")
    for src in hard_sources:
        arr = features["negative"].get(src)
        if arr is None:
            continue
        w, _ = slice_windows_with_owner(arr, window, stride=1)
        s = _predict(sess, w)
        # per-clip max — clip 단위 trigger rate
        n_clips = arr.shape[0]
        clip_max = np.zeros(n_clips, dtype=np.float32)
        owner = _ if isinstance(_, np.ndarray) else None  # safety
        # use slice helper return for owner
        w2, owner2 = slice_windows_with_owner(arr, window, stride=1)
        np.maximum.at(clip_max, owner2, s)
        trig = lambda t: f"{(clip_max > t).mean() * 100:>13.1f}%"
        print(f"  {src:>22} {trig(0.5):>14} {trig(0.9):>14} {trig(0.99):>14}")
```

(`_` 가 owner array 라서 그대로 써도 됨 — `slice_windows_with_owner` 가 tuple 반환.)

깔끔하게 정리한 버전:
```python
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
```

- [ ] **Step 2: Smoke test**

```bash
conda run -n wakeword python scripts/wakeword/evaluate.py --robot eduping 2>&1 | tail -20
```

Expected: 출력 끝에 `[hard-neg breakdown]` 섹션, hard_3syl row 가 N=180, τ=0.99 trig 가 낮을수록 좋음 (학습 후엔 5% 이하 목표).

- [ ] **Step 3: (구현 — Step 1)**

- [ ] **Step 4: (검증 — Step 2)**

- [ ] **Step 5: Commit**

```bash
git add scripts/wakeword/evaluate.py
git commit -m "feat(wake): evaluate.py reports hard-neg trigger rate breakdown"
```

---

## Task 14: 전체 재학습 + offline 평가

**Files:** (코드 변경 없음 — 파이프라인 실행)

- [ ] **Step 1: Pre-flight — 모든 feature .npy 무효화 (mix-builder 적용 후)**

```bash
rm -f data/wake_training/features/positive/*.npy
rm -f data/wake_training/features/negative/*.npy
rm -f data/wake_training/features/noise/*.npy
```

- [ ] **Step 2: Full feature extraction**

```bash
conda run -n wakeword python scripts/wakeword/extract_features.py
```

Expected: 모든 카테고리 추출, 약 15-30분 소요 (positive × 3 variants, hard_3syl 추가).

검증:
```bash
ls -la data/wake_training/features/positive/ data/wake_training/features/negative/ data/wake_training/features/noise/
```
- positive: eduping/gogoping/noriarm.npy 셋, 각 shape[0] ~2000 이상
- negative: realworld.npy, hard_3syl.npy (+ 옵션 hard_3syl_realworld.npy), speech_kr.npy (있다면)
- noise: esc50.npy

- [ ] **Step 3: 재학습 (3 robot)**

```bash
conda run -n wakeword python scripts/wakeword/train.py
```

Expected: 약 30-60분 (GPU 있으면 더 짧음). 3개 `.onnx` 파일이 `service/ai-service/ai_service/models/wakeword/` 에 저장됨.

검증:
```bash
ls -la service/ai-service/ai_service/models/wakeword/*.onnx
```
- eduping.onnx, gogoping.onnx, noriarm.onnx 셋 모두 최근 mtime.

- [ ] **Step 4: Offline 평가 + 결과 캡쳐**

```bash
conda run -n wakeword python scripts/wakeword/evaluate.py 2>&1 | tee /tmp/cycle6_eval.log
cat /tmp/cycle6_eval.log
```

각 robot 마다 다음 metric 기록:
- positive hold-out FRR @ τ ∈ {0.5, 0.9, 0.95, 0.99}
- negative FA/hr @ τ
- hard-neg trigger % @ τ ∈ {0.5, 0.9, 0.99}

**Decision gate**:
- FRR @ τ=0.95 < 15% AND FA/hr < 2.0 AND hard_3syl @ τ=0.95 trig < 5% → 다음 단계 (Task 15)
- 미달이면 stop, 분석 후 plan 갱신:
  - FRR 높음 → real-voice 추가 녹음 (Approach B)
  - hard-neg trig 높음 → word list 확장 (`hard_neg_words.txt` 50→100+) 후 Task 7 재실행
  - FA/hr 높음 → cross-oversample 늘리기 (train.py `--cross-oversample 30+`)

- [ ] **Step 5: Deploy + commit log**

```bash
# 새 onnx 를 브라우저 디렉토리로 복사
cp service/ai-service/ai_service/models/wakeword/eduping.onnx \
   service/ai-service/ai_service/models/wakeword/gogoping.onnx \
   service/ai-service/ai_service/models/wakeword/noriarm.onnx \
   service/web-service/robot-web/public/models/wakeword/

# eval log 저장
mkdir -p logs
cp /tmp/cycle6_eval.log logs/cycle6_eval.log
git add logs/cycle6_eval.log
git commit -m "wake: cycle 6 eval log (mix-into-ambient + hard negs)"
```

(`.onnx` / `.onnx.data` 는 이미 untracked 라서 따로 add — 필요시 `git add service/web-service/robot-web/public/models/wakeword/*.onnx*`.)

---

## Task 15: 브라우저 cleanup — `useWakeWord.ts`

**Files:**
- Modify: `service/web-service/robot-web/src/composables/useWakeWord.ts`

- [ ] **Step 1: Strip VAD-compact + stride + dump helper**

`useWakeWord.ts` 의 `runStep` 함수의 시작 부분 — 다음 블록 (`VAD-compact` 부터 `MIN_VOICED_CHUNKS` 분기 끝까지) 을 제거:

찾기: `// ─ VAD-compact: 학습 데이터는 wake word`
끝까지 (다음 `// ─ Step 1: int16 scale ...` 직전까지) 모두 제거. 그리고 변수명 `rawAudio` 를 `audio` 로 되돌림.

수정 후 `runStep` 본문 시작:
```ts
    try {
      const audio = audioRing.snapshot(); // 43200 samples (2.7s)
      // ─ Step 1: int16 scale (학습 측 _get_melspectrogram 의 int16 → float32 cast 와 일치)
      const scaledAudio = new Float32Array(audio.length);
      for (let i = 0; i < audio.length; i++) {
        const v = audio[i];
        const clipped = v < -1 ? -1 : v > 1 ? 1 : v;
        scaledAudio[i] = Math.round(clipped * 32767);
      }
```

또한 worklet onmessage 의 stride 분기:
```ts
      let stepHopCount = 0;
      const INFERENCE_STRIDE = 2;
      workletNode.port.onmessage = (ev: MessageEvent<Float32Array>) => {
        const chunk = ev.data;
        if (!chunk || chunk.length !== HOP_SAMPLES) return;
        audioRing.push(chunk);
        stepHopCount += 1;
        if (stepHopCount % INFERENCE_STRIDE !== 0) return;
        void runStep();
      };
```
를 다음으로 단순화:

```ts
      workletNode.port.onmessage = (ev: MessageEvent<Float32Array>) => {
        const chunk = ev.data;
        if (!chunk || chunk.length !== HOP_SAMPLES) return;
        audioRing.push(chunk);
        void runStep();
      };
```

`window.__dumpWakeAudio` helper 는 dev tool 로 유지. `[wake-init]` 도 그대로.

또한 사용하지 않게 된 `_audioDebugFrames; void _audioDebugMaxRms; void _audioDebugLastReport;` 줄도 제거.

- [ ] **Step 2: 타입체크**

```bash
cd service/web-service/robot-web
npm run typecheck 2>&1 | tail -20
```

Expected: 0 errors.

- [ ] **Step 3: (구현 — Step 1)**

- [ ] **Step 4: 브라우저 dev server 띄워서 sanity**

```bash
# 별도 터미널
cd service/web-service/robot-web
npm run dev
```

브라우저 콘솔에서 `[wake-init] requested sr=16000 actual sr=16000` 1회만 보이고 inference loop 진입.

- [ ] **Step 5: Commit**

```bash
git add service/web-service/robot-web/src/composables/useWakeWord.ts
git commit -m "refactor(wake): remove inference-side VAD-compact and stride (training fix obsoletes them)"
```

---

## Task 16: 브라우저 cleanup — `useVoiceController.ts` 로그/threshold

**Files:**
- Modify: `service/web-service/robot-web/src/composables/useVoiceController.ts`

- [ ] **Step 1: Reset WAKE_THRESHOLDS placeholder + log threshold 강화**

`WAKE_THRESHOLDS` 블록을 다음으로 (cycle 6 evaluate 결과 후 RD-3 단계에서 robot별 실제값으로 갱신):

```ts
// ONNX wake 분류기 점수 임계값. cycle 6 evaluate 결과 기반 — robot별 FRR/FA
// trade-off 지점에서 선택. 갱신 시점에 evaluate.py 의 threshold table 참조.
const WAKE_THRESHOLDS: Record<string, number> = {
  eduping: 0.9,
  gogoping: 0.9,
  noriarm: 0.95,
};
```

(default 0.9 placeholder — Task 17 에서 evaluate 결과로 robot별 미세조정.)

`[wake] spike` 로그를 score ≥ 0.5 로 변경:

```ts
    onScore: (scores) => {
      const s = scores[robot.id] ?? 0;
      if (s >= 0.5) {
        // eslint-disable-next-line no-console
        console.log(`[wake] spike score=${s.toFixed(3)} state=${voice.state}`);
      }
    },
```

- [ ] **Step 2: 타입체크**

```bash
cd service/web-service/robot-web
npm run typecheck 2>&1 | tail -10
```

Expected: 0 errors.

- [ ] **Step 3: (구현 — Step 1)**

- [ ] **Step 4: (검증 — Step 2)**

- [ ] **Step 5: Commit**

```bash
git add service/web-service/robot-web/src/composables/useVoiceController.ts
git commit -m "refactor(wake): WAKE_THRESHOLDS placeholder 0.9 + log only spike >= 0.5"
```

---

## Task 17: Browser threshold — `cycle 6 eval` 결과 기반 robot별 미세조정

**Files:**
- Modify: `service/web-service/robot-web/src/composables/useVoiceController.ts`

- [ ] **Step 1: Cycle 6 eval log 에서 robot별 sweet-spot 찾기**

`logs/cycle6_eval.log` 또는 `/tmp/cycle6_eval.log` 의 threshold table 에서 각 robot 마다:
- FRR < 10% 면서 FA/hr 가 가장 낮은 τ
- 단, hard-neg trig 가 5% 이하인 τ 만

기록: 각 robot 의 선택 τ 값.

- [ ] **Step 2: WAKE_THRESHOLDS 갱신**

`useVoiceController.ts` 의 `WAKE_THRESHOLDS` 객체에서 robot별 값을 Step 1 의 측정값으로 교체. 예시 (실제 cycle 6 결과로 대체):

```ts
const WAKE_THRESHOLDS: Record<string, number> = {
  eduping: <측정값>,   // cycle 6: FRR X% / FA Y/hr at τ=Z
  gogoping: <측정값>,
  noriarm: <측정값>,
};
```

상단 주석에 cycle 6 결과 요약 한 줄 추가.

- [ ] **Step 3: 타입체크**

```bash
cd service/web-service/robot-web && npm run typecheck
```

Expected: 0 errors.

- [ ] **Step 4: 브라우저 dev server 재시작 후 score spike 와 threshold 가 매칭하는지 확인**

```bash
cd service/web-service/robot-web && npm run dev
```

콘솔에서 발화 시 `[wake] spike score=` 가 threshold 근처에서 HIT 발생.

- [ ] **Step 5: Commit**

```bash
git add service/web-service/robot-web/src/composables/useVoiceController.ts
git commit -m "tune(wake): WAKE_THRESHOLDS per-robot from cycle 6 evaluate"
```

---

## Task 18: Live browser end-to-end 테스트

**Files:** (코드 변경 없음 — 라이브 검증)

- [ ] **Step 1: Dev server 띄움**

```bash
cd service/web-service/robot-web
npm run dev
```

브라우저에서 https://localhost:5173 접속, mic 권한 허용.

- [ ] **Step 2: True positive 테스트 — wake word 10회**

각 호출어 ("에듀핑", "고고핑", "노리암") 10회 발화. 콘솔의 `[wake] HIT` 카운트.

Expected: 호출어당 8+/10 fire.

기록:
- eduping: __/10
- gogoping: __/10
- noriarm: __/10

- [ ] **Step 3: False positive 테스트 — 한국어 3음절 단어 10개**

다음 단어들을 큰 소리로 발화: 안녕해 어떻게 행복해 사진해 학교에 어머니 가까이 친구야 사랑해 들어가

Expected: 0~1 /10 fire (이전 cycle 의 "큰 소리 + 3음절 → fire" 문제 해소 확인).

기록:
- false-positive count: __/10

- [ ] **Step 4: Edge case — 큰 소리 외침**

"뭐라고!", "안녕해!" 등을 평소보다 크게 외쳐 fire 안 하는지 확인.

Expected: 0/N fire.

- [ ] **Step 5: 결과 기록 + commit**

```bash
mkdir -p logs
cat > logs/cycle6_browser_test.md <<EOF
# Cycle 6 Browser Live Test

날짜: $(date +%Y-%m-%d)
브라우저: Chrome on Linux
거리: ~50cm from laptop mic

## True positive
- eduping: __/10
- gogoping: __/10
- noriarm: __/10

## False positive (한국어 3음절 random words)
- count: __/10

## Edge case (큰 소리 외침)
- fire: __/N

## 결정
- [ ] 통과 → Task 19 (문서 갱신)
- [ ] 미달 → Approach B 진입 or word list 확장 후 재학습
EOF

# fill in numbers manually then:
git add logs/cycle6_browser_test.md
git commit -m "test(wake): cycle 6 browser live test results"
```

---

## Task 19: 문서 갱신 — `wakeword-plan.md` cycle 6 섹션

**Files:**
- Modify: `wakeword-plan.md`

- [ ] **Step 1: cycle 6 섹션 추가**

`wakeword-plan.md` 의 section 9 마지막에 (9.4 Cycle 4 실패 다음) 다음 섹션 추가:

```markdown
### 9.5 Cycle 6 — mix-into-ambient 재설계

**배경**: cycle 1-5 의 positive 가 "wake word + literal zero padding" 으로 만들어졌으나
브라우저가 흘리는 raw audio 는 continuous ambient 가 포함됨. mel mean 분포 차이
(학습 3.85 vs 브라우저 7.01) 로 모델이 본 적 없는 분포 → score 0.001 깔림.

**설계**: [docs/superpowers/specs/2026-05-19-wakeword-redesign-design.md](docs/superpowers/specs/2026-05-19-wakeword-redesign-design.md)

**셋업**:
- positive: 9999_ realworld (180) + 0000_ MMS (500) 을 `mix_into_ambient` builder
  로 2.7s continuous 클립 (wake word at random offset, SNR uniform(5,20)dB).
  N=3 variants per source → robot 당 ~2040 positives.
- ambient pool: `data/wake_training/negative/realworld/*` (직접 녹음 + 카페 ASMR)
  + `data/wake_training/noise/esc50/*`.
- hard negatives: 한국어 3음절 단어 60개 × 3 variants (MMS-TTS) + 실음성 30개.

**결과** (`logs/cycle6_eval.log`):

| robot | τ | FRR (hold-out) | FA/hr | hard_3syl trig |
|---|---|---|---|---|
| eduping | __ | __% | __ | __% |
| gogoping | __ | __% | __ | __% |
| noriarm | __ | __% | __ | __% |

**브라우저 검증** (`logs/cycle6_browser_test.md`):

| 항목 | 결과 |
|---|---|
| true positive | __/30 (3 wake words × 10) |
| false positive (random 3음절) | __/10 |

**조치**:
1. `service/ai-service/ai_service/models/wakeword/*.onnx` → cycle 6 결과로 교체.
2. `service/web-service/robot-web/public/models/wakeword/` 도 동일 배포.
3. 브라우저 inference-side preprocessing (VAD-compact, stride) 제거 — 학습 fix 로 불요.
4. `useVoiceController.ts` 의 `WAKE_THRESHOLDS` cycle 6 측정값으로 갱신.

**향후**:
- 실환경 추가 녹음으로 voice diversity 확장 (Approach B) — 필요 시 재시도.
- F5-TTS 재도입 — Cycle 4 의 short-text 한계 우회 (sentence embed + cut 방식).
```

비어있는 `__` 자리는 Task 14 / Task 18 의 실측값으로 채움.

- [ ] **Step 2: section 10 (다음 단계) 갱신**

`## 10. 다음 단계` 의 SR-C 행 옆에 `[x]` 표시. cycle 6 항목 추가.

기존:
```markdown
- [ ] **SR-C**: 브라우저 통합 — ...
```
를:
```markdown
- [x] **SR-C**: 브라우저 통합 — onnxruntime-web 로 .onnx 로드, AudioWorklet, 3-stage pipeline. (cycle 6 에서 raw audio path 로 단순화).
- [x] **Cycle 6**: mix-into-ambient 재설계 — 학습 분포를 production 입력에 매칭. hard negative (3음절 한국어) 추가. ([docs spec](docs/superpowers/specs/2026-05-19-wakeword-redesign-design.md))
```

- [ ] **Step 3: implementation-plan.md / implemented.md 처리**

CLAUDE.md 규칙에 따라, 만약 wakeword 가 `docs/implementation-plan.md` 의 SR 로 등록되어 있다면 그 row 를 `docs/implemented.md` 로 이동 + `구현 위치` / `완료일` 컬럼 추가. 확인:

```bash
grep -n "wake\|호출어" docs/implementation-plan.md | head -20
```

해당 SR 이 있으면 row 를 `docs/implemented.md` 의 같은 섹션으로 이동.

- [ ] **Step 4: 변경 검토**

```bash
git diff wakeword-plan.md docs/implementation-plan.md docs/implemented.md
```

- [ ] **Step 5: Commit**

```bash
git add wakeword-plan.md docs/implementation-plan.md docs/implemented.md
git commit -m "docs(wake): cycle 6 results — mix-into-ambient + hard negs"
```

---

## Self-Review

### Spec coverage
- [x] Section 1 (Architecture) — Task 15, 16 의 브라우저 단순화로 raw audio path 복원
- [x] Section 2 (mix builder) — Task 1-5 (mix.py + 5 tests) + Task 9-10 (integration in extract_features)
- [x] Section 3 (Browser cleanup) — Task 15-17
- [x] Section 3.5 (Hard negatives) — Task 6 (word list) + Task 7 (synth) + Task 8 (record)
- [x] Section 4 (Testing & validation) — Task 1-5 (unit) + Task 12-13 (offline eval) + Task 18 (live)
- [x] Section 5 (SR breakdown) — Task 1-13 maps to RD-1, Task 14 to RD-2, Task 15-18 to RD-3, Task 19 to RD-4

### Placeholder scan
- `WAKE_THRESHOLDS: <측정값>` in Task 17 Step 2 — intentional. 실제 evaluate 측정값 의존이라 Task 14 완료 후 채움. Plan 에서 명시.
- `__/10` in Task 18 Step 5 — 실측치 기록 자리. Plan 에서 명시.
- 그 외 TBD/TODO 없음.

### Type consistency
- `mix_into_ambient` 의 signature 가 Task 1-5 와 Task 10 (integration) 에서 동일하게 사용.
- `_load_ambient_pool` 의 시그니처가 Task 9 정의와 Task 10 호출 일치.
- `WAKE_THRESHOLDS` 형 `Record<string, number>` 전 task 동일.

### 잠재적 이슈
- Task 11 의 hard-neg 추가는 자동 sub-dir 그룹화로 처리 — 따로 코드 변경 없음. Task 10 의 commit 에 묶어도 됨.
- Task 14 의 `--cross-oversample` 인자는 기존 train.py 에 이미 존재 (`scripts/wakeword/train.py:42-47`).
