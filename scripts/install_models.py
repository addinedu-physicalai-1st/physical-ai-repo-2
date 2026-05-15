"""필요한 ML 모델 가중치 자동 다운로드 — `scripts/run_server.sh` 가 startup 시 호출.

이미 받아져 있으면 no-op. 새 모델 추가는 `MODELS` 리스트에 한 줄.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# (filename, dest_dir) — filename 은 ultralytics 의 GitHub assets 저장소 기준 basename
MODELS: list[tuple[str, Path]] = [
    ("yolov8s-worldv2.pt", REPO_ROOT / "service" / "ai-service" / "ai_service" / "models"),
]


def install(filename: str, dest_dir: Path) -> bool:
    """이미 있으면 skip, 없으면 ultralytics 헬퍼로 다운로드. 다운로드 시 True 반환."""
    dest = dest_dir / filename
    if dest.exists():
        size_mb = dest.stat().st_size / (1024 * 1024)
        print(f"  [present] {dest.relative_to(REPO_ROOT)}  ({size_mb:.1f} MB)")
        return False

    try:
        from ultralytics.utils.downloads import attempt_download_asset
    except ImportError:
        print(
            f"  [error] ultralytics 미설치 — `pip install -e .` 실행 필요",
            file=sys.stderr,
        )
        sys.exit(1)

    dest_dir.mkdir(parents=True, exist_ok=True)
    print(f"  [download] {filename} → {dest_dir.relative_to(REPO_ROOT)}/")
    # attempt_download_asset 은 cwd 에 받는다 — 임시 chdir 로 dest_dir 에 받게 유도
    prev = Path.cwd()
    try:
        os.chdir(dest_dir)
        attempt_download_asset(filename)
    finally:
        os.chdir(prev)

    if not dest.exists():
        print(f"  [error] 다운로드 후 파일이 없음: {dest}", file=sys.stderr)
        sys.exit(1)
    size_mb = dest.stat().st_size / (1024 * 1024)
    print(f"  [done] {dest.relative_to(REPO_ROOT)}  ({size_mb:.1f} MB)")
    return True


def main() -> int:
    print(f"[install_models] {len(MODELS)} 개 모델 확인")
    for filename, dest_dir in MODELS:
        install(filename, dest_dir)
    print("[install_models] 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
