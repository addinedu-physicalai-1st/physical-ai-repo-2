#!/usr/bin/env python3
"""Streaming WebSocket 수신 probe — 단계 8 통합 검증용.

Admin UI 없이 명령행에서 WS 연결, 영상 frame 수신·통계 출력.
JPEG 디코드까지 검증 가능 (--save-frame).

사용:
  python ws_probe.py --robot gogoping
  python ws_probe.py --robot gogoping --duration 30           # 30초 측정
  python ws_probe.py --robot gogoping --save-frame /tmp/x.jpg  # 첫 frame 저장
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import time
import uuid
from pathlib import Path

WS_FRAME_HEADER_FMT = "!BBBBIQI"
WS_FRAME_HEADER_SIZE = 20
ROBOT_IDS = {"gogoping": 1, "eduping": 2, "noriarm": 3}
ID_TO_NAME = {v: k for k, v in ROBOT_IDS.items()}


def main() -> int:
    p = argparse.ArgumentParser(description="Streaming WS 수신 probe")
    p.add_argument("--url", default="ws://localhost:8100/ws/video-stream")
    p.add_argument("--robot", choices=list(ROBOT_IDS), default="gogoping")
    p.add_argument("--stream", type=int, default=0)
    p.add_argument("--duration", type=float, default=10.0,
                   help="측정 시간 초 (기본 10)")
    p.add_argument("--save-frame", default=None,
                   help="첫 JPEG frame 저장 경로")
    p.add_argument("--cookie", default=None,
                   help="session cookie 값 (auth 활성 시)")
    args = p.parse_args()

    try:
        from websockets.sync.client import connect
    except ImportError:
        print("websockets 모듈 필요: pip install websockets", file=sys.stderr)
        return 2

    extra_headers = []
    if args.cookie:
        extra_headers.append(("Cookie", f"session={args.cookie}"))

    client_id = str(uuid.uuid4())
    print(f"[probe] connecting {args.url} (client_id={client_id})", flush=True)

    started = time.monotonic()
    frames = 0
    bytes_total = 0
    first_frame_at = None
    saved = False
    seqs: list[int] = []

    with connect(
        args.url,
        open_timeout=5.0,
        additional_headers=extra_headers or None,
        max_size=2_000_000,
    ) as ws:
        # welcome
        msg = json.loads(ws.recv(timeout=5.0))
        assert msg["type"] == "welcome", f"welcome 안 옴: {msg}"
        print(f"[probe] welcome: session_id={msg.get('session_id')}", flush=True)

        # hello
        ws.send(json.dumps({
            "type": "hello",
            "client_id": client_id,
            "client_kind": "probe",
            "ts_ms": int(time.time() * 1000),
        }))
        ack = json.loads(ws.recv(timeout=5.0))
        assert ack["type"] == "hello_ack"
        print(f"[probe] hello_ack: active_robots={ack.get('active_robots')}",
              flush=True)

        # subscribe
        ws.send(json.dumps({
            "type": "subscribe", "robot": args.robot, "stream": args.stream,
            "ts_ms": int(time.time() * 1000),
        }))
        sub_ack = json.loads(ws.recv(timeout=5.0))
        assert sub_ack["type"] == "subscribed"
        print(f"[probe] subscribed: {sub_ack['robot']}/{sub_ack['stream']}",
              flush=True)

        deadline = started + args.duration
        while time.monotonic() < deadline:
            try:
                raw = ws.recv(timeout=1.0)
            except TimeoutError:
                continue
            if isinstance(raw, str):
                msg = json.loads(raw)
                if msg.get("type") == "ping":
                    ws.send(json.dumps({
                        "type": "pong", "ts_ms": int(time.time() * 1000),
                    }))
                continue
            # binary frame
            if len(raw) < WS_FRAME_HEADER_SIZE:
                continue
            mtype, rid, sid, _resv, seq, ts, size = struct.unpack(
                WS_FRAME_HEADER_FMT, raw[:WS_FRAME_HEADER_SIZE],
            )
            if mtype != 0x10:
                continue
            jpeg = raw[WS_FRAME_HEADER_SIZE:WS_FRAME_HEADER_SIZE + size]
            if first_frame_at is None:
                first_frame_at = time.monotonic()
                latency_ms = (int(time.time() * 1000) - ts)
                print(
                    f"[probe] FIRST frame: robot={ID_TO_NAME.get(rid, rid)}/"
                    f"{sid} seq={seq} size={size}B latency={latency_ms}ms",
                    flush=True,
                )
                if args.save_frame and not saved:
                    Path(args.save_frame).write_bytes(bytes(jpeg))
                    print(f"[probe] saved → {args.save_frame}", flush=True)
                    saved = True
            frames += 1
            bytes_total += len(raw)
            seqs.append(seq)

    elapsed = time.monotonic() - started
    print()
    print("[probe] === 측정 결과 ===")
    print(f"  duration       : {elapsed:.2f}s")
    print(f"  frames         : {frames}")
    print(f"  fps            : {frames / elapsed:.2f}")
    print(f"  bandwidth      : {bytes_total / elapsed / 1e6 * 8:.2f} Mbps")
    if first_frame_at is not None:
        print(f"  first_frame    : +{first_frame_at - started:.3f}s after subscribe")
    # frame_seq 결손 검출
    if len(seqs) >= 2:
        gaps = sum(1 for a, b in zip(seqs, seqs[1:]) if b - a > 1)
        print(f"  seq_gaps       : {gaps} (frame 손실 추정)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
