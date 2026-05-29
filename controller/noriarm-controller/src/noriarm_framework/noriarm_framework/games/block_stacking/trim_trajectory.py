#!/usr/bin/env python3
"""Trajectory 앞뒤 정지 구간 트림 + 일정 패딩 추가.

사용법:
    python trim_trajectory.py rps_scissors_trajectory.json
    python trim_trajectory.py rps_scissors_trajectory.json --threshold 1.0 --pad 0.5
"""
import argparse
import json
from pathlib import Path


def trim(frames: list[list[float]], threshold: float) -> tuple[int, int]:
    """정지 구간을 제외한 실제 모션 구간 [start, end) 인덱스 반환."""
    n = len(frames)

    def max_change(i: int) -> float:
        return max(abs(frames[i][j] - frames[i - 1][j]) for j in range(len(frames[i])))

    start = 1
    for i in range(1, n):
        if max_change(i) > threshold:
            start = i
            break

    end = n - 1
    for i in range(n - 1, 0, -1):
        if max_change(i) > threshold:
            end = i + 1
            break

    return start, end


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", help="trajectory JSON 파일 경로 (스크립트 디렉토리 기준 or 절대경로)")
    parser.add_argument("--threshold", type=float, default=0.5,
                        help="정지 판정 임계값 (m100_100 단위, 기본 0.5)")
    parser.add_argument("--pad", type=float, default=0.5,
                        help="앞뒤에 추가할 홀드 시간(초, 기본 0.5)")
    args = parser.parse_args()

    base = Path(__file__).parent
    path = Path(args.file) if Path(args.file).is_absolute() else base / args.file

    data = json.loads(path.read_text())
    frames = data["trajectory"]
    hz = float(data.get("hz", 30))
    pad_frames = max(1, int(args.pad * hz))

    before = len(frames)
    start, end = trim(frames, args.threshold)
    core = frames[start:end]

    if not core:
        print("! 모션 구간을 찾지 못했습니다. --threshold 값을 낮춰보세요.")
        return

    padded = [core[0]] * pad_frames + core + [core[-1]] * pad_frames

    data["trajectory"] = padded
    data["num_frames"] = len(padded)
    path.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False))

    after = len(padded)
    print(f"트림 완료: {before}프레임 → 모션구간 {end - start}프레임 + 패딩 {pad_frames}×2 = {after}프레임 ({after / hz:.1f}초)")
    print(f"저장: {path}")


if __name__ == "__main__":
    main()
