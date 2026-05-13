#!/usr/bin/env python3
"""
scripts/eduping-leader-scan.py — feetech 양팔 leader 시리얼 버스 ID 스캔.

기본 ping (id 1..8) 으로 응답 없는 모터가 있을 때, 같은 버스에 어떤 ID 가
어떤 baudrate 에서 떠 있는지 한 번에 확인하는 진단 도구.

사용 (conda env 'pdg' 활성 상태에서):
    scripts/eduping-leader-scan.py                       # 양쪽 포트, 1Mbps, id 0..29
    scripts/eduping-leader-scan.py --all-baud            # STS3215 지원 baud 전부 (1M/500k/250k/128k/115200/76800/57600/38400)
    scripts/eduping-leader-scan.py --all-ids             # id 0..253 전 범위 (느림)
    scripts/eduping-leader-scan.py --all-baud --all-ids  # 둘 다 (한 포트 ~2분)
    scripts/eduping-leader-scan.py --port /dev/op_mini_left
"""
import argparse
import sys

try:
    import scservo_sdk as scs
except ImportError:
    sys.exit("scservo_sdk 없음 — conda activate pdg 후 재실행 (또는 pip install feetech-servo-sdk)")


# STS3215 가 지원하는 baudrate 표 전부 (datasheet)
ALL_STS_BAUDS = [1_000_000, 500_000, 250_000, 128_000, 115_200, 76_800, 57_600, 38_400]


def scan_port(port_name: str, baudrates: list[int], max_id: int) -> None:
    port = scs.PortHandler(port_name)
    packet = scs.PacketHandler(0)
    if not port.openPort():
        print(f"  ✗ openPort 실패: {port_name}")
        return
    print(f"=== {port_name}  (ids 0..{max_id})  ===")
    for baud in baudrates:
        if not port.setBaudRate(baud):
            print(f"  baud={baud:>8} setBaudRate 실패")
            continue
        found = []
        for mid in range(0, max_id + 1):
            model, comm, _ = packet.ping(port, mid)
            if comm == 0:
                found.append((mid, model))
        if found:
            line = ", ".join(f"id={i}(model={m})" for i, m in found)
            print(f"  baud={baud:>8} → {line}")
        else:
            print(f"  baud={baud:>8} → (none)")
    port.closePort()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", action="append", help="스캔할 포트 (여러 번 지정 가능). 미지정 시 양팔 둘 다.")
    ap.add_argument("--all-baud", action="store_true", help="STS3215 지원 baud 전부 시도")
    ap.add_argument("--all-ids", action="store_true", help="id 0..253 전 범위 스캔 (느림 — baud 당 ~15초)")
    args = ap.parse_args()

    ports = args.port or ["/dev/op_mini_right", "/dev/op_mini_left"]
    bauds = ALL_STS_BAUDS if args.all_baud else [1_000_000]
    max_id = 253 if args.all_ids else 29

    for p in ports:
        scan_port(p, bauds, max_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
