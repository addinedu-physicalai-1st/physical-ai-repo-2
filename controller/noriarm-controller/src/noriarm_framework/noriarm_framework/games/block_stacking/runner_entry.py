"""블럭쌓기 서브프로세스 진입점.

Control Server 가 `python -m noriarm_framework.games.block_stacking.runner_entry --target {sim|real}` 로 spawn.

흐름:
  1. game.yaml 로드 + ACT 정책 인스턴스 생성 (build_policy).
  2. ACTPolicyAdapter.load_policy_blocking() — torch weights 메모리/GPU 로드.
  3. stdout 에 "READY\\n" 출력 + flush — Control Server 가 이를 보고 다음 단계 진행.
  4. stdin 에서 한 줄 읽기 — "START\\n" 받으면 rclpy + GameRunner 실행.
  5. SIGTERM 시 깨끗이 종료 (rclpy shutdown).
"""
from __future__ import annotations

import argparse
import signal
import sys

from noriarm_framework.games.block_stacking import load_block_stacking_config
from noriarm_framework.runner import RunnerConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=("sim", "real"), default="sim")
    args = parser.parse_args(argv)

    config = load_block_stacking_config()

    # ACT 정책 로드 — 모델 weights 메모리/GPU 로딩까지 동기 완료.
    from noriarm_framework._ros_runner import load_policy

    policy = load_policy(config)
    if hasattr(policy, "load_policy_blocking"):
        print("[runner_entry] ACT 모델 로딩 중...", flush=True)
        policy.load_policy_blocking()
        print("[runner_entry] ACT 모델 로딩 완료", flush=True)

    # Control Server 에게 ready 신호.
    print("READY", flush=True)

    # stdin "START\n" 대기.
    line = sys.stdin.readline()
    if line.strip() != "START":
        print(f"[runner_entry] 예상 'START' 인데 '{line.strip()}' 받음 — 종료", flush=True)
        return 2

    # SIGTERM 핸들러 — rclpy.shutdown() 을 트리거.
    import rclpy

    def _handle_sigterm(signum, frame):  # noqa: ARG001
        print("[runner_entry] SIGTERM — 종료 진행", flush=True)
        try:
            rclpy.shutdown()
        except Exception:
            pass

    signal.signal(signal.SIGTERM, _handle_sigterm)

    # GameRunner 진입 — 정책은 이미 load 된 상태.
    cfg = RunnerConfig(config=config, target=args.target, inputs={})
    rclpy.init()
    try:
        from noriarm_framework._ros_runner import GameRunner

        runner = GameRunner(cfg, policy)
        try:
            runner.run()
        finally:
            runner.destroy_node()
    finally:
        try:
            rclpy.shutdown()
        except Exception:
            pass

    print("EXIT", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
