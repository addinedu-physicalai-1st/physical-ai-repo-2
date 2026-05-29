import numpy as np
import zstandard as zstd

from eduarm.depth_frame import Intr, build_depth_frame
# control_service 사본 — 이 테스트는 conda(jazzy) 에서 돌아 둘 다 import 가능.
from control_service.streaming.depth_protocol import decode_depth_frame, encode_depth_frame as cs_encode
from eduarm.depth_frame import encode_depth_frame as eduarm_encode, DepthFrame as EduarmFrame


def _sample():
    depth = np.arange(6, dtype=np.uint16).reshape(2, 3) * 100  # 0,100,...,500 (mm units)
    color = np.zeros((2, 3, 3), dtype=np.uint8)
    intr = Intr(fx=210.0, fy=211.0, cx=160.5, cy=120.5)
    return depth, color, intr


def test_build_depth_frame_roundtrips_through_control_service_decoder():
    depth, color, intr = _sample()
    frame = build_depth_frame(
        depth, color, intr, depth_scale=0.001,
        robot_id=0x02, frame_seq=7, ts_ms=123456789, jpeg_quality=80,
    )
    decoded = decode_depth_frame(eduarm_encode(frame))
    assert decoded is not None
    assert decoded.robot_id == 0x02
    assert decoded.frame_seq == 7
    assert decoded.ts_ms == 123456789
    assert decoded.depth_w == 3 and decoded.depth_h == 2
    assert decoded.color_w == 3 and decoded.color_h == 2
    assert abs(decoded.fx - 210.0) < 1e-3
    assert abs(decoded.depth_scale - 0.001) < 1e-6
    # depth roundtrip — zstd 복원 후 원본 일치
    raw = zstd.ZstdDecompressor().decompress(decoded.depth_zstd)
    assert np.frombuffer(raw, dtype=np.uint16).reshape(2, 3).tolist() == depth.tolist()
    assert decoded.depth_min_mm == 100 and decoded.depth_max_mm == 500  # 0 은 무시


def test_eduarm_and_control_service_encoders_are_byte_identical():
    """두 사본이 어긋나면 즉시 실패 — 와이어 포맷 단일 진실 보장."""
    depth, color, intr = _sample()
    frame = build_depth_frame(
        depth, color, intr, depth_scale=0.001,
        robot_id=0x02, frame_seq=1, ts_ms=42, jpeg_quality=70,
    )
    # 동일 필드로 control_service DepthFrame 구성
    from control_service.streaming.depth_protocol import DepthFrame as CsFrame
    cs_frame = CsFrame(**{f: getattr(frame, f) for f in frame.__dataclass_fields__})
    assert eduarm_encode(frame) == cs_encode(cs_frame)
