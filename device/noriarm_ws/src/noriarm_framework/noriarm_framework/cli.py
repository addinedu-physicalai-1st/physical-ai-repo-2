"""NoriArm 게임 프레임워크 CLI.

진입점:
    python -m noriarm_framework run --game ox_quiz --target sim
    python -m noriarm_framework validate --game ox_quiz
    python -m noriarm_framework list

설치 후에는 `noriarm` 콘솔 스크립트로도 호출 가능 (setup.py entry_points).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from noriarm_framework.manifest import GameConfig, ManifestError, load_manifest
from noriarm_framework.runner import RunnerConfig, run


def _games_root() -> Path:
    """패키지 안의 games 디렉토리 — 소스/설치 어느 쪽이든 동일하게 동작."""
    return Path(__file__).resolve().parent / "games"


def _list_games() -> list[Path]:
    root = _games_root()
    return sorted(p / "game.yaml" for p in root.iterdir() if (p / "game.yaml").is_file())


def _resolve_manifest(game: str) -> Path:
    p = _games_root() / game / "game.yaml"
    if not p.is_file():
        raise SystemExit(f"게임을 찾을 수 없음: {game} (검색 경로: {_games_root()})")
    return p


def cmd_list(_: argparse.Namespace) -> int:
    paths = _list_games()
    if not paths:
        print(f"등록된 게임이 없습니다 (검색 경로: {_games_root()})")
        return 0
    for path in paths:
        try:
            cfg = load_manifest(path)
            print(f"  {cfg.name:<16} {cfg.display}  [{path.parent.name}]")
        except ManifestError as e:
            print(f"  {path.parent.name:<16} (invalid: {e})")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        cfg = load_manifest(_resolve_manifest(args.game))
    except ManifestError as e:
        print(f"매니페스트 검증 실패: {e}")
        return 1
    print(f"OK — {cfg.name} ({cfg.display})")
    print(f"  cameras: {[c.id for c in cfg.cameras]}")
    print(f"  arms:    {[a.id for a in cfg.arms]}")
    print(f"  policy:  kind={cfg.policy.kind} module={cfg.policy.module}")
    # SR-NORI-004 의 실하드웨어 검증은 후속 SR 에서 추가.
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_manifest(_resolve_manifest(args.game))
    inputs: dict[str, str] = {}
    for raw in args.input or []:
        if "=" not in raw:
            raise SystemExit(f"--input 은 KEY=VAL 형식: {raw!r}")
        k, v = raw.split("=", 1)
        inputs[k.strip()] = v.strip()
    run(
        RunnerConfig(
            config=cfg,
            target=args.target,
            inputs=inputs,
            max_steps=args.max_steps,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="noriarm", description=__doc__)
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="등록된 게임 목록")
    p_list.set_defaults(func=cmd_list)

    p_val = sub.add_parser("validate", help="매니페스트 검증")
    p_val.add_argument("--game", required=True)
    p_val.set_defaults(func=cmd_validate)

    p_run = sub.add_parser("run", help="게임 실행")
    p_run.add_argument("--game", required=True)
    p_run.add_argument("--target", choices=["sim", "real"], default="sim")
    p_run.add_argument(
        "--input",
        action="append",
        metavar="KEY=VAL",
        help="정책 obs.extra 에 주입할 값 (여러 번 지정 가능). 예: --input answer=O",
    )
    p_run.add_argument("--max-steps", type=int, default=None, help="디버깅용 — n 스텝 후 종료")
    p_run.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
