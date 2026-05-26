"""gogoping_camera ROS entry point.

asyncio event loop (aiortc + signaling) 와 ROS spin 을 한 process 안에서 운영.
ROS rclpy 는 별 thread 의 SingleThreadedExecutor 로 spin, 메인 thread 는 asyncio.run().
D435Capture 는 자체 thread (Task 4).
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import threading
from typing import Optional

import rclpy
import rclpy.executors
# NVENC monkey-patch — aiortc 의 H.264 encoder 를 libx264 → h264_nvenc 로 교체.
# import 시점에 적용되므로 RTCPeerConnection 사용 전에 먼저 import.
from . import nvenc_patch  # noqa: F401
from aiortc import RTCPeerConnection, RTCRtpSender, RTCSessionDescription, RTCIceCandidate
from aiortc.sdp import candidate_from_sdp
from rclpy.node import Node

from . import config
from .d435_capture import D435Capture
from .signaling_client import SignalingClient
from .webrtc_track import D435VideoTrack

_log = logging.getLogger("gogoping_camera.webrtc_node")


def _cleanup_stale_shm() -> None:
    """이전 비정상 종료 후 /dev/shm/gogoping_* 가 남아있으면 정리.
    D435Capture(__init__) 가 SharedMemory(create=True) 호출 시 FileExistsError 방지."""
    for name in ("gogoping_color_640", "gogoping_depth_640", "gogoping_meta"):
        path = f"/dev/shm/{name}"
        if os.path.exists(path):
            try:
                os.unlink(path)
                _log.info("stale shm removed: %s", path)
            except OSError:
                pass


class WebRTCNode(Node):
    def __init__(self) -> None:
        super().__init__("gogoping_camera_webrtc")
        self.get_logger().info("gogoping_camera WebRTC node starting")
        self._capture: Optional[D435Capture] = None
        self._pc: Optional[RTCPeerConnection] = None
        self._track: Optional[D435VideoTrack] = None
        self._signaling: Optional[SignalingClient] = None

    async def run_async(self) -> None:
        self._capture = D435Capture()
        self._capture.start()

        self._signaling = SignalingClient(
            url=config.SIGNALING_URL,
            peer_id=config.SIGNALING_PEER_ID,
            on_message=self._on_signaling,
        )
        await self._signaling.start()
        # idle forever — until cancel
        await asyncio.Event().wait()

    async def _on_signaling(self, msg: dict) -> None:
        mtype = msg.get("type")
        if mtype == "connected":
            # signaling WS 연결 직후 통보 (signaling_client 가 hello 보낸 직후 호출).
            # client-as-offerer: producer 가 자기 PC + offer 만들어 보냄.
            await self._send_offer()
        elif mtype == "answer":
            if self._pc is None:
                return
            await self._pc.setRemoteDescription(
                RTCSessionDescription(sdp=msg["sdp"], type="answer"),
            )
        elif mtype == "ice":
            cand_json = msg.get("candidate")
            if cand_json is None or self._pc is None:
                return
            cand = _cand_from_json(cand_json)
            if cand is None:
                return   # end-of-candidates / 빈 candidate
            await self._pc.addIceCandidate(cand)
        elif mtype == "bye":
            await self._teardown_pc()

    async def _send_offer(self) -> None:
        """client-as-offerer: producer 가 자기 PC 만들고 video track 추가 후 offer 송신.

        H.264 를 codec preference 최상위로 설정 → SDP 협상에서 H.264 우선 선택.
        nvenc_patch 와 결합되어 NVENC hardware encoder 가 사용됨.
        """
        await self._teardown_pc()
        self._pc = RTCPeerConnection()
        self._track = D435VideoTrack(self._capture)
        transceiver = self._pc.addTransceiver(self._track, direction="sendonly")

        # H.264 codec preference 강제 (SDP 협상 시 우선 선택)
        caps = RTCRtpSender.getCapabilities("video")
        h264_codecs = [c for c in caps.codecs if c.mimeType == "video/H264"]
        if h264_codecs:
            transceiver.setCodecPreferences(h264_codecs)

        offer = await self._pc.createOffer()
        await self._pc.setLocalDescription(offer)
        await self._signaling.send({"type": "offer", "sdp": self._pc.localDescription.sdp})

    async def _teardown_pc(self) -> None:
        if self._pc is not None:
            try:
                await self._pc.close()
            except Exception:
                pass
            self._pc = None
            self._track = None

    async def shutdown(self) -> None:
        await self._teardown_pc()
        if self._signaling is not None:
            await self._signaling.stop()
        if self._capture is not None:
            self._capture.stop()


def _cand_to_json(cand) -> dict:
    return {"candidate": cand.candidate, "sdpMid": cand.sdpMid, "sdpMLineIndex": cand.sdpMLineIndex}


def _cand_from_json(c: dict) -> RTCIceCandidate | None:
    """server 가 보낸 SDP candidate 문자열 → RTCIceCandidate.

    aiortc 의 RTCIceCandidate 는 candidate SDP 문자열을 그대로 받지 않고
    parsing 된 필드들을 받음. `candidate_from_sdp` 헬퍼가 그 parsing 수행.
    빈 candidate (end-of-candidates 시그널) 는 None.
    """
    candidate_str = (c.get("candidate") or "").strip()
    if not candidate_str:
        return None
    if candidate_str.startswith("candidate:"):
        candidate_str = candidate_str[len("candidate:"):]
    cand = candidate_from_sdp(candidate_str)
    cand.sdpMid = c.get("sdpMid")
    cand.sdpMLineIndex = c.get("sdpMLineIndex")
    return cand


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    # 비정상 종료 후 잔존 shm 정리 (FileExistsError 방지)
    _cleanup_stale_shm()
    rclpy.init()
    node = WebRTCNode()

    # ROS spin 은 별 thread 에서
    executor = rclpy.executors.SingleThreadedExecutor()
    executor.add_node(node)
    ros_thread = threading.Thread(target=executor.spin, name="ros-spin", daemon=True)
    ros_thread.start()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _sigint(*_a):
        loop.call_soon_threadsafe(loop.stop)

    signal.signal(signal.SIGINT, _sigint)
    signal.signal(signal.SIGTERM, _sigint)

    try:
        loop.run_until_complete(node.run_async())
    except asyncio.CancelledError:
        pass
    finally:
        loop.run_until_complete(node.shutdown())
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
