#!/usr/bin/env python3
"""실환경 wake-word 녹음 도구 — positive(호출어 발화) / negative(주변 소음) 수집.

사용 예:
  # 호출어 발화 — 17 phrase × 10 = 170 sample
  python scripts/wakeword/record_realworld.py positive

  # 한 로봇만, 횟수 조정
  python scripts/wakeword/record_realworld.py positive --robot eduping --per-phrase 20

  # 주변 소음 30분
  python scripts/wakeword/record_realworld.py negative --duration-min 30

  # 마이크 device 변경
  python scripts/wakeword/record_realworld.py positive --device 8

기존 같은 prefix(`9999_`) 파일이 있으면 그 다음 index 부터 이어 녹음.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
_ROBOTS_JSON = REPO_ROOT / "shared" / "robots.json"

SR = 16000  # 학습/추론용 target sample rate
# ALSA 일부 device 가 16kHz native 지원 안 함 (`paInvalidSampleRate`). 그래서
# 48kHz 로 캡쳐 후 librosa.resample 로 16kHz 로 변환해서 저장.
CAPTURE_SR = 48000
SEED_PREFIX = "9999"  # real-world recording 표시. MMS=0000, F5=0001 과 구분.


def list_phrases() -> list[tuple[str, str]]:
    """shared/robots.json 에서 (robot_id, phrase) 목록을 펼쳐 반환.

    canonical (wakeWord) + alias (wakeWordAliases, canonical 중복 제외) 합쳐서.
    어느 branch 에서도 동작하도록 ai_service 의존성 없이 JSON 직접 파싱.
    """
    data = json.loads(_ROBOTS_JSON.read_text(encoding="utf-8"))
    out: list[tuple[str, str]] = []
    for r in data["robots"]:
        rid = r["id"]
        canonical = r["wakeWord"]
        aliases = [a for a in r.get("wakeWordAliases", []) if a != canonical]
        for p in (canonical, *aliases):
            out.append((rid, p))
    return out


def record_segment(seconds: float, device: int | None = None) -> np.ndarray:
    """48kHz mono 캡쳐 → 16kHz 로 resample 한 mono float32 반환."""
    import librosa
    import sounddevice as sd

    rec = sd.rec(
        int(seconds * CAPTURE_SR),
        samplerate=CAPTURE_SR,
        channels=1,
        dtype="float32",
        device=device,
    )
    sd.wait()
    data = rec[:, 0]
    if CAPTURE_SR != SR:
        data = librosa.resample(data, orig_sr=CAPTURE_SR, target_sr=SR).astype(
            np.float32, copy=False
        )
    return data


def trim_and_validate(
    samples: np.ndarray, min_sec: float = 0.3, min_rms: float = 0.005
) -> tuple[np.ndarray, float, float, str]:
    """trim 후 (samples, dur, rms, status) 반환. status 는 'ok' / 'too_short' / 'too_quiet' / 'empty'."""
    import librosa

    trimmed, _ = librosa.effects.trim(samples, top_db=30)
    duration = trimmed.size / SR
    if trimmed.size == 0:
        return trimmed, 0.0, 0.0, "empty"
    rms = float(np.sqrt(np.mean(trimmed**2) + 1e-9))
    if duration < min_sec:
        return trimmed, duration, rms, "too_short"
    if rms < min_rms:
        return trimmed, duration, rms, "too_quiet"
    return trimmed, duration, rms, "ok"


def auto_detect_input_device(probe_sec: float = 0.3) -> int | None:
    """모든 입력 device 에 짧게 ambient 캡쳐 → RMS 가장 큰 것 선택.

    노트북에 mic 가 여러 개 있고 (e.g. sof-hda-dsp hw:1,0 / hw:1,6) 그 중 하나만
    실제로 신호가 들어오는 환경 대응. 신호 없는 device 는 RMS ≈ 0, 진짜 mic 는
    조용한 방이라도 ~0.001+ 이라 구분 가능.
    """
    import sounddevice as sd

    candidates = [
        (i, d) for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0
    ]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][0]

    print(f"[mic] auto-detect: {len(candidates)} 개 input device 별 ambient {probe_sec}s 캡쳐 ...")
    best_idx: int | None = None
    best_rms = 0.0
    for idx, info in candidates:
        name = str(info.get("name", "?"))[:40]
        try:
            samples = record_segment(probe_sec, device=idx)
            rms = float(np.sqrt(np.mean(samples**2) + 1e-9))
            print(f"  [{idx}] {name:<40}  rms={rms:.4f}")
            if rms > best_rms:
                best_rms = rms
                best_idx = idx
        except Exception as exc:  # noqa: BLE001
            print(f"  [{idx}] {name:<40}  FAIL ({exc.__class__.__name__})")

    if best_idx is None:
        return None
    if best_rms < 0.0005:
        print(
            "  ⚠️ 모든 device 가 너무 조용함 — mic mute 확인. "
            "수동 지정은 `--device <id>`."
        )
    print(f"  → 선택: device [{best_idx}] (rms={best_rms:.4f})")
    return best_idx


def pick_output_device() -> tuple[int | None, str, int]:
    """출력 device 우선순위: pulse/default (PA 라우팅) → analog (laptop 스피커) → 나머지.

    HDMI / Digital / direct ALSA hw 는 회피 — laptop 스피커로 routing 안 되거나 hw
    가 input 전용이라 PaUnanticipatedHostError 가 떨어짐.
    """
    import sounddevice as sd

    devices = sd.query_devices()
    outputs = [
        (i, d) for i, d in enumerate(devices) if d["max_output_channels"] > 0
    ]
    if not outputs:
        return None, "?", CAPTURE_SR

    def name(d: dict) -> str:
        return str(d.get("name", ""))

    def is_pa(d: dict) -> bool:
        ln = name(d).lower()
        return any(k in ln for k in ("pulse", "pipewire", "default"))

    def is_digital(d: dict) -> bool:
        ln = name(d).lower()
        return any(k in ln for k in ("hdmi", "digital", "iec958", "s/pdif", "spdif"))

    pa = [(i, d) for i, d in outputs if is_pa(d)]
    analog = [
        (i, d) for i, d in outputs if not is_digital(d) and not is_pa(d)
    ]
    chosen_list = pa or analog or outputs
    idx, info = chosen_list[0]
    sr = int(float(info.get("default_samplerate", CAPTURE_SR)))
    return idx, name(info), sr


def play_back(samples: np.ndarray) -> None:
    """16kHz mono 를 default output device 의 native rate 로 resample 해서 재생.

    ALSA 가 임의 SR 을 안 받아주는 경우 (대부분 48000 만 지원), default output
    의 default_samplerate 를 그대로 써서 PaInvalidSampleRate 회피.
    """
    import librosa
    import sounddevice as sd

    out_idx, out_name, out_sr = pick_output_device()

    if out_sr != SR:
        play_samples = librosa.resample(
            samples, orig_sr=SR, target_sr=out_sr
        ).astype(np.float32, copy=False)
    else:
        play_samples = samples
    # 짧은 wake word 라 RMS 가 낮아 안 들리는 경우 대비해 boost
    play_samples = np.clip(play_samples * 3.0, -1.0, 1.0).astype(np.float32, copy=False)
    print(f"    🔊 재생: {out_name[:40]} @ {out_sr}Hz  ({samples.size / SR:.2f}s)")
    try:
        sd.play(play_samples, out_sr, device=out_idx)
        sd.wait()
    except Exception as exc:  # noqa: BLE001
        print(f"    (재생 실패: {exc.__class__.__name__} — out_sr={out_sr}. p 건너뛰자)")


def positive_mode(args: argparse.Namespace) -> None:
    import soundfile as sf

    if args.device is None:
        args.device = auto_detect_input_device()

    phrases = list_phrases()
    if args.robot != "all":
        phrases = [(rid, p) for rid, p in phrases if rid == args.robot]
        if not phrases:
            raise SystemExit(f"unknown robot: {args.robot}")

    out_root: Path = args.out_dir
    targets: list[tuple[str, str, int]] = []
    for rid, phrase in phrases:
        robot_dir = out_root / rid
        robot_dir.mkdir(parents=True, exist_ok=True)
        existing = len(list(robot_dir.glob(f"{SEED_PREFIX}_*_{phrase}.wav")))
        need = max(0, args.per_phrase - existing)
        for i in range(need):
            targets.append((rid, phrase, existing + i))

    total = len(targets)
    if total == 0:
        print("[positive] 모든 phrase 가 목표 횟수 충족됨 — 종료")
        return

    print(f"[positive] {total} sample 녹음 시작. (per_phrase={args.per_phrase})")
    print(
        f"  흐름: prompt 표시 → Enter → {args.max_sec}s 녹음 → 결과 확인 → 저장/재녹음/skip\n"
        f"  키: [Enter]=녹음  r=재녹음(저장 전)  u=직전 저장 취소+재녹음\n"
        f"      s=skip  q=종료  p=미리듣기 (확인 단계에서만)\n"
    )

    saved = 0
    skipped = 0
    # 직전에 저장한 sample 추적 — u 키로 취소+재녹음 가능 (1단계만)
    last_saved: tuple[int, Path] | None = None

    i = 0
    while i < total:
        rid, phrase, sub_idx = targets[i]
        prompt_head = f"[{i + 1}/{total}] {rid:<10} → \"{phrase}\""

        key = input(f"{prompt_head}  > ").strip().lower()
        if key == "q":
            break
        if key == "s":
            skipped += 1
            i += 1
            last_saved = None
            continue
        if key == "u":
            if last_saved is None:
                print("    직전 저장 없음 — undo 불가")
                continue
            prev_i, prev_path = last_saved
            if prev_path.exists():
                prev_path.unlink()
                print(f"    🗑️  취소: {prev_path.name}")
            saved -= 1
            i = prev_i  # 직전 target 으로 되돌아감 → 자동 재녹음
            last_saved = None
            continue

        time.sleep(0.2)
        print(f"  🎙️ 녹음 중 ({args.max_sec}s)...", end="", flush=True)
        samples = record_segment(args.max_sec, device=args.device)
        raw_peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        trimmed, dur, rms, status = trim_and_validate(samples)
        mark = "✓" if status == "ok" else "✗"
        print(
            f" dur={dur:.2f}s rms={rms:.3f} peak={raw_peak:.3f} {mark}"
        )

        if status != "ok":
            reason = {
                "too_short": "trim 후 0.3s 미만 — 발화 너무 짧거나 안 잡힘",
                "too_quiet": "RMS 너무 낮음 — 마이크 멀거나 볼륨 낮음 (또는 --device 다른 id 시도)",
                "empty": "신호 없음 — device 확인 (`python ... mic-test`)",
            }[status]
            print(f"    품질 낮음 ({status}): {reason}")
            continue

        # 저장 확인 단계
        while True:
            act = input(
                f"    저장? [Y / r=재녹음 / p=미리듣기 / s=skip / q=종료]: "
            ).strip().lower()
            if act == "p":
                play_back(trimmed)
                continue
            if act == "q":
                print(f"\n[positive] saved={saved} skipped={skipped} 종료")
                return
            if act in ("", "y"):
                fname = f"{SEED_PREFIX}_{sub_idx:05d}_{phrase}.wav"
                out_path = out_root / rid / fname
                sf.write(out_path, trimmed, SR, subtype="FLOAT")
                saved += 1
                last_saved = (i, out_path)
                i += 1
                break
            if act == "r":
                # 같은 prompt 다시 녹음 (i 그대로)
                break
            if act == "s":
                skipped += 1
                i += 1
                last_saved = None
                break

    print(f"\n[positive] saved={saved} skipped={skipped} (총 {total} 중 {i} 진행)")


def negative_mode(args: argparse.Namespace) -> None:
    import soundfile as sf

    if args.device is None:
        args.device = auto_detect_input_device()

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    chunk_sec = args.chunk_sec
    total_sec = args.duration_min * 60.0
    n_expected = int(total_sec // chunk_sec)

    existing = sorted(out_dir.glob("realworld_*.wav"))
    next_idx = len(existing)
    if existing:
        print(
            f"[negative] 기존 {len(existing)}개 발견 — 이어서 {next_idx:06d} 부터 저장"
        )

    print(
        f"[negative] {args.duration_min:.0f} 분 ({n_expected} × {chunk_sec:.0f}s "
        f"청크) → {out_dir}"
    )
    print(f"  마이크: device={args.device}  (None = system default)")
    print(f"  Ctrl+C 로 중간 종료 가능. Enter 누르면 시작.")
    input()

    print(f"  🎙️ 시작 — {time.strftime('%H:%M:%S')}")
    start = time.time()
    saved = 0
    try:
        while (time.time() - start) < total_sec:
            samples = record_segment(chunk_sec, device=args.device)
            fname = f"realworld_{next_idx:06d}.wav"
            sf.write(out_dir / fname, samples, SR, subtype="FLOAT")
            saved += 1
            next_idx += 1
            elapsed = time.time() - start
            mm, ss = divmod(int(elapsed), 60)
            tm, ts = divmod(int(total_sec), 60)
            rms = float(np.sqrt(np.mean(samples**2) + 1e-9))
            print(
                f"  [{mm:02d}:{ss:02d}/{tm:02d}:{ts:02d}] saved={saved}  "
                f"last={fname} rms={rms:.3f}",
                end="\r",
                flush=True,
            )
    except KeyboardInterrupt:
        print("\n  중단됨")

    print(f"\n[negative] DONE. saved={saved} → {out_dir}")


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
                break
    print(f"\n[hard-neg] saved={saved} skipped={skipped}")


def mic_test_mode(args: argparse.Namespace) -> None:
    """3초 녹음해서 device 별 입력 신호가 잡히는지 확인."""
    import sounddevice as sd

    devices = sd.query_devices()
    candidates: list[int] = []
    if args.device is not None:
        candidates = [args.device]
    else:
        candidates = [i for i, d in enumerate(devices) if d["max_input_channels"] > 0]

    print(f"[mic-test] {len(candidates)} device 테스트 (각 3초). 말소리 한 번씩 내봐.")
    for d in candidates:
        info = devices[d]
        print(f"\n  device[{d}] {info['name']}  in_ch={info['max_input_channels']}")
        input("    Enter 누르면 3초 녹음 시작 ... ")
        try:
            samples = record_segment(3.0, device=d)
            peak = float(np.max(np.abs(samples)))
            rms = float(np.sqrt(np.mean(samples**2) + 1e-9))
            # trim 후 RMS 도 표시
            _, _, trim_rms, status = trim_and_validate(samples, min_sec=0.0, min_rms=0.0)
            print(
                f"    captured: peak={peak:.3f}  raw_rms={rms:.3f}  "
                f"trim_rms={trim_rms:.3f}  ({'OK' if rms > 0.005 else 'WEAK'})"
            )
        except Exception as e:
            print(f"    ERROR: {e}")

    print(
        "\n  raw_rms 가장 큰 device 가 진짜 mic. positive/negative 시 "
        "`--device <id>` 로 지정."
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="mode", required=True)

    mt = sub.add_parser("mic-test", help="3초씩 녹음해서 어느 device 가 진짜 mic 인지 확인")
    mt.add_argument("--device", type=int, default=None, help="특정 device 하나만 테스트")

    pp = sub.add_parser("positive", help="호출어 발화 녹음 (phrase prompt loop)")
    pp.add_argument("--robot", default="all", help="eduping/gogoping/noriarm/all")
    pp.add_argument("--per-phrase", type=int, default=10, help="phrase 당 목표 횟수")
    pp.add_argument(
        "--max-sec",
        type=float,
        default=1.5,
        help="녹음 buffer 길이. 호출어 자체 ~0.7s + Enter→발화 반응 시간 buffer. "
        "빠르면 1.0, 느긋하면 2.5 권장",
    )
    pp.add_argument("--device", type=int, default=None, help="sounddevice input id")
    pp.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "data" / "wake_training" / "positive",
    )

    ng = sub.add_parser("negative", help="주변 잡담/소음 continuous 녹음")
    ng.add_argument("--duration-min", type=float, default=30.0)
    ng.add_argument("--chunk-sec", type=float, default=5.0)
    ng.add_argument("--device", type=int, default=None, help="sounddevice input id")
    ng.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "data" / "wake_training" / "negative" / "realworld",
    )

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

    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.mode == "positive":
        positive_mode(args)
    elif args.mode == "negative":
        negative_mode(args)
    elif args.mode == "hard-negative":
        hard_negative_mode(args)
    elif args.mode == "mic-test":
        mic_test_mode(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
