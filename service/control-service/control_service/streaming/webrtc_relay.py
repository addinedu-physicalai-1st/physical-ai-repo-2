"""server-side aiortc PeerConnection 관리.

흐름:
  Producer (gogoping 노트북) ───PC_p──► server (MediaRelay) ───PC_c1──► Admin UI consumer 1
                                                          ───PC_c2──► Admin UI consumer 2 ...

server 는 producer 의 incoming track 을 MediaRelay.subscribe() 로 N consumer 에 forwarding.
재인코딩 안 함 — RTP packet 그대로 relay.

각 PC pair (producer ↔ server, server ↔ consumer) 는 독립적으로 SDP/ICE 협상.
signaling 라우터 (별 모듈) 가 PC 인스턴스를 본 모듈에 위임.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, Optional

from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaRelay

_log = logging.getLogger("streaming.webrtc_relay")


class WebRTCRelay:
    """Producer 1개 + consumer N 개의 aiortc PeerConnection 관리.

    producer_pc 는 producer 가 hello 시 한 번 생성. consumer_pcs 는 consumer 마다 생성.
    producer.track 이 들어오면 relay.subscribe(track) 로 모든 consumer 에 forward.
    """

    def __init__(self) -> None:
        self._relay = MediaRelay()
        self._producer_pc: Optional[RTCPeerConnection] = None
        self._producer_track: Optional[MediaStreamTrack] = None
        self._consumer_pcs: Dict[str, RTCPeerConnection] = {}    # peer_id → pc
        self._lock = asyncio.Lock()

    def has_producer(self) -> bool:
        return self._producer_track is not None

    async def attach_producer(self) -> RTCPeerConnection:
        async with self._lock:
            await self._close_producer_locked()
            pc = RTCPeerConnection()
            # client-as-offerer 패턴: producer 가 자기 PC 에 addTrack 후 createOffer.
            # server 는 받은 offer 의 m=section 으로 video track receive 가능.
            self._producer_pc = pc

            @pc.on("track")
            def _on_track(track: MediaStreamTrack) -> None:
                _log.info("producer track received: kind=%s id=%s", track.kind, track.id)
                self._producer_track = track
                # 기존 consumer 에 forward 추가.
                # buffered=False — 라이브 영상은 최신 프레임만 의미. 기본값 True 면 consumer
                # 마다 무한 asyncio.Queue 가 생겨 느린/움직임 많은 상황(예: 숨바꼭질 순찰)에서
                # 프레임이 쌓여 지연 폭증 → freeze(검정)/burst 재생.
                for cid, cpc in self._consumer_pcs.items():
                    cpc.addTrack(self._relay.subscribe(track, buffered=False))

            @pc.on("connectionstatechange")
            async def _on_state() -> None:
                _log.info("producer pc state: %s", pc.connectionState)
                if pc.connectionState == "failed":
                    await self._close_producer_locked()

            return pc

    async def attach_consumer(self, peer_id: str) -> RTCPeerConnection:
        async with self._lock:
            await self._close_consumer_locked(peer_id)
            pc = RTCPeerConnection()
            self._consumer_pcs[peer_id] = pc

            # client-as-offerer: addTrack 은 router 의 setRemoteDescription(offer) 후에
            # 호출. 미리 addTrack 하면 SDP m-section 매칭 안 돼서 video forward 안 됨.

            @pc.on("connectionstatechange")
            async def _on_state() -> None:
                _log.info("consumer[%s] pc state: %s", peer_id, pc.connectionState)
                if pc.connectionState == "failed":
                    await self._close_consumer_locked(peer_id)

            return pc

    def attach_track_to_consumer(self, pc: RTCPeerConnection) -> None:
        """consumer 의 PC 에 producer_track 을 sendonly 로 forward.

        setRemoteDescription(consumer recvonly offer) 시 aiortc 가 server-side 에
        recvonly transceiver 를 자동 생성 (default direction). 우리는 그 transceiver 의
        direction 을 sendonly 로 명시 변경 + sender 의 track 을 producer_track 으로 교체.
        그 후 createAnswer 가 m=video sendonly answer 생성.

        반드시 setRemoteDescription 후 createAnswer 전에 호출.
        """
        if self._producer_track is None:
            return
        # buffered=False — 라이브 relay. _on_track 의 forward 와 동일 이유 (지연 누적 방지).
        track = self._relay.subscribe(self._producer_track, buffered=False)
        for transceiver in pc.getTransceivers():
            if transceiver.kind == "video":
                transceiver.sender.replaceTrack(track)
                transceiver.direction = "sendonly"
                return
        # video transceiver 가 setRemoteDescription 으로 자동 생성 안 됐을 때 fallback
        pc.addTrack(track)

    async def detach_producer(self) -> None:
        async with self._lock:
            await self._close_producer_locked()

    async def detach_consumer(self, peer_id: str) -> None:
        async with self._lock:
            await self._close_consumer_locked(peer_id)

    async def _close_producer_locked(self) -> None:
        if self._producer_pc is not None:
            try:
                await self._producer_pc.close()
            except Exception:
                pass
            self._producer_pc = None
            self._producer_track = None

    async def _close_consumer_locked(self, peer_id: str) -> None:
        pc = self._consumer_pcs.pop(peer_id, None)
        if pc is not None:
            try:
                await pc.close()
            except Exception:
                pass
