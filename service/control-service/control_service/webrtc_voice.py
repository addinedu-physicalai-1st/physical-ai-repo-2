"""음성 WebRTC — 브라우저와 양방향 audio + DataChannel.

Phase 3c (현재): chat intent 의 reply 를 ai-service /voice/tts 로 합성 (edge-tts MP3),
av 로 PCM 디코드 → OutboundTTSTrack 으로 push → 브라우저가 RTP audio 로 수신·재생.
DC `tts_start` / `tts_end` 로 클라이언트 lip-sync / state 동기화.

설계 메모:
  - PC 는 단일 세션 (한 태블릿당 하나).
  - aiortc 가 Opus 디코드 → av.AudioFrame (보통 48kHz s16 stereo).
  - av.AudioResampler 로 16kHz mono s16 → Float32 -1..1 변환.
  - Silero VAD 는 ai_service.stt 의 onnxruntime 와 같은 패키지 사용, 모델은
    robot-web public 의 silero_vad.onnx 재활용 (단일 source of truth).
  - whisper inference 는 ai_service.stt.transcribe_pcm 직접 호출 (in-process).
  - utterance 끝나면 백그라운드 task 로 transcribe + DC send — 다음 utterance 차단 안 됨.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from pathlib import Path
from typing import Optional

import fractions
import io
import time

import av  # type: ignore[import-not-found]
import httpx
import numpy as np
import onnxruntime as ort
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaStreamError
from av.audio.frame import AudioFrame  # type: ignore[import-not-found]
from av.audio.resampler import AudioResampler  # type: ignore[import-not-found]
from fastapi import APIRouter
from pydantic import BaseModel

from ai_service import stt as stt_engine
from control_service.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice/webrtc", tags=["voice", "webrtc"])

_VAD_MODEL_PATH = Path(__file__).resolve().parent / "assets" / "silero_vad.onnx"
_WAKE_ACK_MP3_PATH = Path(__file__).resolve().parent / "assets" / "wake_ack.mp3"

# wakeAck "네!" PCM 캐시 — module load 시 한 번 디코드 후 재사용.
# 클라이언트 로컬 재생 대신 WebRTC outbound 로 push 해야 브라우저 AEC 가 reference
# signal 로 잡아 mic 에서 정확히 제거됨. → 연속 발화 ("에듀핑인사해") 시 사용자 명령
# 이 wakeAck 잔향에 묻히지 않고 깨끗히 캡처됨.
_wake_ack_pcm: Optional[bytes] = None


def _get_wake_ack_pcm() -> bytes:
    global _wake_ack_pcm
    if _wake_ack_pcm is None:
        if not _WAKE_ACK_MP3_PATH.exists():
            raise FileNotFoundError(f"wakeAck mp3 not found: {_WAKE_ACK_MP3_PATH}")
        with open(_WAKE_ACK_MP3_PATH, "rb") as f:
            mp3 = f.read()
        _wake_ack_pcm = _decode_mp3_to_pcm48k(mp3)
        logger.info(f"[webrtc] cached wakeAck PCM: {len(_wake_ack_pcm)} bytes")
    return _wake_ack_pcm

# Silero VAD 단일 ONNX 세션 — 모든 PC 가 공유 (stateless, state 는 호출자가 보관).
_vad_session: Optional[ort.InferenceSession] = None

# client_id → (PeerConnection, Session). 로봇별 (EduPing / GogoPing / NoriArm) 등
# 여러 브라우저 세션을 동시에 운영. 같은 client_id 가 재접속 (refresh) 하면 이전
# PC 는 백그라운드 정리 후 교체.
_sessions: dict[str, tuple[RTCPeerConnection, "_Session"]] = {}

# wake 후 gate 가 열려있는 시간 — 사용자가 명령을 시작할 때까지 + 발화 길이 여유.
# 너무 짧으면 사용자가 머뭇하면 닫혀버리고, 너무 길면 임의 발화가 잘못 잡힘.
GATE_OPEN_TIMEOUT_S = 6.0


class OfferBody(BaseModel):
    sdp: str
    type: str
    # 브라우저별 영속 UUID — localStorage 에서 첫 방문 시 생성·저장 후 매번 동봉.
    # 같은 client_id 로 새 offer 가 오면 이전 세션 close 후 교체 (refresh 케이스).
    client_id: str


class AnswerBody(BaseModel):
    sdp: str
    type: str
    client_id: str


def _get_vad_session() -> ort.InferenceSession:
    global _vad_session
    if _vad_session is None:
        if not _VAD_MODEL_PATH.exists():
            raise FileNotFoundError(f"Silero VAD model not found: {_VAD_MODEL_PATH}")
        logger.info(f"[webrtc] loading Silero VAD: {_VAD_MODEL_PATH}")
        _vad_session = ort.InferenceSession(
            str(_VAD_MODEL_PATH),
            providers=["CPUExecutionProvider"],
        )
    return _vad_session


class SileroVAD:
    """Streaming Silero VAD v5 — chunk 당 (prob, event) 반환.

    event ∈ {'start', 'end', None}. 디바운싱 (히스테리시스 + min frames) 으로
    spurious bounce 억제.
    """

    STATE_SHAPE = (2, 1, 128)
    SR = np.array(16000, dtype=np.int64)

    def __init__(
        self,
        session: ort.InferenceSession,
        positive_threshold: float = 0.5,
        negative_threshold: float = 0.35,
        min_speech_frames: int = 2,
        min_silence_frames: int = 8,
    ) -> None:
        self.session = session
        self.state = np.zeros(self.STATE_SHAPE, dtype=np.float32)
        self.speaking = False
        self.speech_frame_count = 0
        self.silence_frame_count = 0
        self.positive_threshold = positive_threshold
        self.negative_threshold = negative_threshold
        self.min_speech_frames = min_speech_frames
        self.min_silence_frames = min_silence_frames

    def feed(self, chunk: np.ndarray) -> tuple[float, Optional[str]]:
        if chunk.shape != (512,):
            raise ValueError(f"expected (512,) Float32 chunk, got {chunk.shape}")
        out = self.session.run(
            None,
            {
                "input": chunk.reshape(1, 512),
                "state": self.state,
                "sr": self.SR,
            },
        )
        prob = float(out[0][0, 0])
        self.state = out[1]
        event = self._advance(prob)
        return prob, event

    def reset(self) -> None:
        self.state.fill(0)
        self.speaking = False
        self.speech_frame_count = 0
        self.silence_frame_count = 0

    def _advance(self, prob: float) -> Optional[str]:
        if not self.speaking:
            if prob >= self.positive_threshold:
                self.speech_frame_count += 1
                self.silence_frame_count = 0
                if self.speech_frame_count >= self.min_speech_frames:
                    self.speaking = True
                    return "start"
            else:
                self.speech_frame_count = 0
        else:
            if prob < self.negative_threshold:
                self.silence_frame_count += 1
                if self.silence_frame_count >= self.min_silence_frames:
                    self.speaking = False
                    self.speech_frame_count = 0
                    self.silence_frame_count = 0
                    return "end"
            else:
                self.silence_frame_count = 0
        return None


async def _safe_close(pc: RTCPeerConnection) -> None:
    """PC 정리 — timeout 으로 stall 방어. background task 로 호출."""
    try:
        await asyncio.wait_for(pc.close(), timeout=2.0)
    except asyncio.TimeoutError:
        logger.warning("[webrtc] pc.close() timed out (2s)")
    except Exception:
        logger.exception("[webrtc] pc.close() failed")


def _evict_session(client_id: str) -> None:
    """sessions dict 에서 제거 + background close. 호출자 block 안 함."""
    prev = _sessions.pop(client_id, None)
    if prev is not None:
        prev_pc, prev_session = prev
        prev_session.close_gate("evicted")
        asyncio.create_task(_safe_close(prev_pc))


class OutboundTTSTrack(MediaStreamTrack):
    """서버 → 브라우저 outbound 오디오 트랙.

    내부 byte buffer 에 PCM (int16 LE @ 48kHz mono) 을 쌓아두고, recv() 가 호출되면
    20ms (960 sample) 만큼 잘라 av.AudioFrame 으로 반환. 데이터 없으면 무음으로 패딩
    하여 RTP stream 이 끊기지 않게 유지. 페이싱은 aiortc RTP sender 가 pts 기준으로
    조절하므로 우리는 정확한 pts 만 박아주면 됨.
    """

    kind = "audio"
    SAMPLE_RATE = 48000
    CHANNELS = 1
    SAMPLES_PER_FRAME = 960  # 20ms
    BYTES_PER_FRAME = SAMPLES_PER_FRAME * 2  # int16

    def __init__(self) -> None:
        super().__init__()
        self._buffer = bytearray()
        self._lock = asyncio.Lock()
        self._pts = 0
        self._time_base = fractions.Fraction(1, self.SAMPLE_RATE)
        self._silence_frame = bytes(self.BYTES_PER_FRAME)
        self._start_time: Optional[float] = None

    async def push_pcm(self, pcm_int16_le: bytes) -> None:
        """48kHz mono int16 LE PCM 누적. push 자체는 빠름 (frame pacing 은 recv 가 담당)."""
        if not pcm_int16_le:
            return
        async with self._lock:
            self._buffer.extend(pcm_int16_le)

    async def clear(self) -> None:
        """현재 버퍼 비움 — barge-in 시 즉시 TTS 끊기 용."""
        async with self._lock:
            self._buffer.clear()

    def buffered_ms(self) -> int:
        return int(len(self._buffer) / 2 / self.SAMPLE_RATE * 1000)

    async def recv(self) -> AudioFrame:
        # Pacing — aiortc RTP sender 가 track.recv() 를 가능한 빨리 호출하므로
        # 우리가 wall-clock 기준으로 20ms 마다 한 프레임씩 내보내야 함. 안 하면
        # 모든 프레임을 즉시 반환 → RTP sender 가 burst 로 보냄 → browser jitter
        # buffer overflow → 짧게 들리다 끊김.
        # PC 종료 시 sender task 가 cancel → asyncio.sleep CancelledError →
        # MediaStreamError 로 변환해 graceful end 신호. (안 그러면 stale frame 을
        # 닫힌 transport 로 send 시도 → "socket.send() raised exception" 노이즈.)
        try:
            loop = asyncio.get_event_loop()
            if self._start_time is None:
                self._start_time = loop.time()
            target = self._start_time + (self._pts / self.SAMPLE_RATE)
            wait = target - loop.time()
            if wait > 0:
                await asyncio.sleep(wait)
        except asyncio.CancelledError:
            raise MediaStreamError

        # readyState 가 ended 면 즉시 종료 (PC.close() → track.stop() 후).
        if self.readyState != "live":
            raise MediaStreamError

        async with self._lock:
            if len(self._buffer) >= self.BYTES_PER_FRAME:
                chunk = bytes(self._buffer[: self.BYTES_PER_FRAME])
                del self._buffer[: self.BYTES_PER_FRAME]
            else:
                # 남은 데이터 + 무음 패딩 (전부 비어있어도 OK — silence)
                remaining = bytes(self._buffer)
                self._buffer.clear()
                pad = self.BYTES_PER_FRAME - len(remaining)
                chunk = remaining + b"\x00" * pad

        # PCM bytes → numpy int16 → av.AudioFrame
        arr = np.frombuffer(chunk, dtype=np.int16).reshape(1, -1)
        frame = AudioFrame.from_ndarray(arr, format="s16", layout="mono")
        frame.rate = self.SAMPLE_RATE
        frame.pts = self._pts
        frame.time_base = self._time_base
        self._pts += self.SAMPLES_PER_FRAME
        return frame


class _Session:
    """PC 1개의 세션 상태. on_track / on_datachannel / on_message 클로저가 공유."""

    def __init__(self, log_id: str = "") -> None:
        self.log_id = log_id
        self.dc: Optional[object] = None
        self.gate_open: bool = False
        self.robot: Optional[str] = None
        self._gate_close_task: Optional[asyncio.Task] = None
        self.outbound_tts: Optional[OutboundTTSTrack] = None

    def open_gate(self, robot: Optional[str]) -> None:
        self.robot = robot
        self.gate_open = True
        logger.info(f"[webrtc:{self.log_id}] gate OPEN (robot={robot}) — closes in {GATE_OPEN_TIMEOUT_S}s")
        if self._gate_close_task is not None and not self._gate_close_task.done():
            self._gate_close_task.cancel()
        self._gate_close_task = asyncio.create_task(self._close_after_timeout())

    def close_gate(self, reason: str = "") -> None:
        if self.gate_open:
            logger.info(f"[webrtc:{self.log_id}] gate CLOSE ({reason})")
        self.gate_open = False
        if self._gate_close_task is not None and not self._gate_close_task.done():
            self._gate_close_task.cancel()
        self._gate_close_task = None

    async def _close_after_timeout(self) -> None:
        try:
            await asyncio.sleep(GATE_OPEN_TIMEOUT_S)
            self.close_gate("timeout")
        except asyncio.CancelledError:
            pass

    def send(self, payload: dict) -> None:
        dc = self.dc
        if dc is None:
            logger.warning(f"[webrtc:{self.log_id}] no DC to send {payload!r}")
            return
        try:
            dc.send(json.dumps(payload))  # type: ignore[attr-defined]
        except Exception:
            logger.exception(f"[webrtc:{self.log_id}] DC send failed: {payload!r}")


@router.post("/offer", response_model=AnswerBody)
async def webrtc_offer(body: OfferBody) -> AnswerBody:
    """SDP offer 수신 → PC 생성 + answer 반환.

    같은 client_id 의 이전 세션이 있으면 background 정리 후 새로 만든다 (refresh).
    다른 client_id 는 독립 세션으로 공존.
    """
    client_id = body.client_id
    log_id = client_id[:8]  # 디버깅용 짧은 prefix

    # refresh 케이스: 같은 client_id 가 이미 등록되어 있으면 evict.
    if client_id in _sessions:
        logger.info(f"[webrtc:{log_id}] evicting previous session for same client_id")
        _evict_session(client_id)

    pc = RTCPeerConnection()
    session = _Session(log_id=log_id)
    # Outbound TTS 트랙을 PC 에 미리 attach — answer SDP 에 m=audio sendrecv 가
    # 들어가 브라우저가 ontrack 으로 받음 → <audio srcObject> 가 재생.
    session.outbound_tts = OutboundTTSTrack()
    pc.addTrack(session.outbound_tts)
    _sessions[client_id] = (pc, session)
    logger.info(f"[webrtc:{log_id}] new session — active count: {len(_sessions)}")

    @pc.on("connectionstatechange")
    async def on_connectionstatechange() -> None:  # noqa: D401
        logger.info(f"[webrtc:{log_id}] connection state: {pc.connectionState}")
        if pc.connectionState in ("failed", "closed"):
            session.close_gate("connection ended")
            existing = _sessions.get(client_id)
            if existing is not None and existing[0] is pc:
                del _sessions[client_id]
                logger.info(f"[webrtc:{log_id}] session removed — active count: {len(_sessions)}")

    @pc.on("track")
    def on_track(track) -> None:  # noqa: D401
        logger.info(f"[webrtc:{log_id}] track received: kind={track.kind} id={track.id}")
        if track.kind == "audio":
            asyncio.create_task(_consume_audio(track, session, log_id))

    @pc.on("datachannel")
    def on_datachannel(channel) -> None:  # noqa: D401
        logger.info(f"[webrtc:{log_id}] datachannel opened: label={channel.label}")
        session.dc = channel

        @channel.on("message")
        def on_message(message) -> None:
            try:
                msg = json.loads(message) if isinstance(message, str) else {}
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"[webrtc:{log_id}] non-JSON dc msg: {message!r}")
                return
            _handle_client_msg(session, msg, log_id)

    offer = RTCSessionDescription(sdp=body.sdp, type=body.type)
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return AnswerBody(
        sdp=pc.localDescription.sdp,
        type=pc.localDescription.type,
        client_id=client_id,
    )


def _handle_client_msg(session: _Session, msg: dict, log_id: str = "") -> None:
    """클라이언트 → 서버 DataChannel 메시지 처리."""
    msg_type = msg.get("type")
    if msg_type == "wake":
        session.open_gate(robot=msg.get("robot"))
        # 진행 중 TTS (있으면) 즉시 끊고 wakeAck "네!" 로 교체 — mid-TTS barge-in 지원.
        if session.outbound_tts is not None:
            asyncio.create_task(_replace_outbound_with_wake_ack(session))
    elif msg_type == "speak":
        # 명시적 TTS 요청 — 모드 전환 안내, goto_vertex 확인 멘트 등.
        text = (msg.get("text") or "").strip()
        if text:
            asyncio.create_task(_speak_reply(text, session))
    elif msg_type == "dispatch_text":
        # 타이핑 명령 — wake gate 우회. STT 단계는 없고 바로 intent + TTS 사이클.
        text = (msg.get("text") or "").strip()
        if text:
            asyncio.create_task(_dispatch_text_only(text, session))
    elif msg_type == "tts_cancel":
        if session.outbound_tts is not None:
            asyncio.create_task(session.outbound_tts.clear())
    else:
        logger.info(f"[webrtc:{log_id}] dc msg: {msg!r}")


async def _replace_outbound_with_wake_ack(session: _Session) -> None:
    """outbound buffer 비움 → wakeAck PCM push. wake msg 처리에서 호출."""
    track = session.outbound_tts
    if track is None:
        return
    try:
        pcm = _get_wake_ack_pcm()
    except Exception:
        logger.exception(f"[webrtc:{session.log_id}] wakeAck PCM unavailable")
        return
    await track.clear()
    await track.push_pcm(pcm)


async def _dispatch_text_only(text: str, session: _Session) -> None:
    """STT 우회 — 주어진 텍스트로 곧장 intent + TTS 사이클. CommandBar 타이핑용."""
    session.send({"type": "stt_final", "text": text})  # UI echo
    try:
        intent = await _dispatch_intent(text, session.robot or "eduping")
    except Exception:
        logger.exception(f"[webrtc:{session.log_id}] dispatch_text intent failed")
        return
    logger.info(f"[webrtc:{session.log_id}] dispatch_text intent → {intent!r}")
    session.send({"type": "intent", **intent})
    if intent.get("kind") == "chat":
        reply = (intent.get("reply") or "").strip()
        if reply and session.outbound_tts is not None:
            await _speak_reply(reply, session)


async def _consume_audio(track, session: _Session, log_id: str = "") -> None:
    """리샘플 → Silero VAD → (gate 가 열려있을 때만) utterance 누적 → whisper."""
    try:
        vad_session = _get_vad_session()
    except Exception:
        logger.exception(f"[webrtc:{log_id}] Silero VAD load failed — audio consumer abort")
        return

    vad = SileroVAD(vad_session)
    resampler = AudioResampler(format="s16", layout="mono", rate=16000)

    # 누적 PCM (Float32 -1..1) — 512 sample chunk 단위로 VAD 에 흘려보냄.
    pcm_acc = np.empty(0, dtype=np.float32)
    CHUNK = 512

    # 발화 도중 모은 chunk 들 + 직전 chunk preroll (첫 자음 잘림 방지).
    utterance_chunks: list[np.ndarray] = []
    preroll: deque[np.ndarray] = deque(maxlen=2)  # 2 chunk = 64ms

    frame_count = 0
    try:
        while True:
            try:
                frame: AudioFrame = await track.recv()
            except MediaStreamError:
                logger.info(f"[webrtc:{log_id}] audio track ended after {frame_count} frames")
                break

            frame_count += 1
            if frame_count == 1:
                logger.info(
                    f"[webrtc:{log_id}] first audio frame: rate={frame.rate} samples={frame.samples} "
                    f"layout={frame.layout.name} fmt={frame.format.name}"
                )

            # 16kHz mono s16 으로 리샘플.
            for resampled in resampler.resample(frame):
                arr = resampled.to_ndarray()
                if arr.ndim == 2:
                    arr = arr[0]
                audio_f32 = arr.astype(np.float32) / 32768.0
                pcm_acc = np.concatenate([pcm_acc, audio_f32])

                while pcm_acc.size >= CHUNK:
                    chunk = pcm_acc[:CHUNK].copy()
                    pcm_acc = pcm_acc[CHUNK:]
                    prob, event = vad.feed(chunk)

                    if event == "start":
                        utterance_chunks = list(preroll) + [chunk]
                        preroll.clear()
                        logger.info(f"[webrtc:{log_id}] VAD start (prob={prob:.3f}) gate={session.gate_open}")
                    elif event == "end":
                        utterance_chunks.append(chunk)
                        full = np.concatenate(utterance_chunks)
                        duration_ms = int(full.size / 16)
                        utterance_chunks = []
                        logger.info(
                            f"[webrtc:{log_id}] VAD end (prob={prob:.3f}) — utterance {duration_ms}ms gate={session.gate_open}"
                        )
                        # gate 가 닫혀있으면 transcribe 안 함 (CPU 절약 + 의도치 않은 발화 차단).
                        if not session.gate_open:
                            continue
                        if duration_ms < 200:
                            continue  # 너무 짧은 spurious utterance skip
                        # transcribe 후에 gate 닫음 — 응답 사이클 끝나면 다시 wake 필요.
                        # (phase 3b/c 에서 intent + TTS 끝난 후 닫는 걸로 옮겨질 수 있음)
                        session.close_gate("utterance captured")
                        asyncio.create_task(_transcribe_and_send(full, session))
                    elif vad.speaking:
                        utterance_chunks.append(chunk)
                    else:
                        preroll.append(chunk)
    except Exception:
        logger.exception(f"[webrtc:{log_id}] audio consumer crashed after {frame_count} frames")


async def _transcribe_and_send(pcm: np.ndarray, session: _Session) -> None:
    """whisper transcribe → DC `stt_final` → /voice/intent → DC `intent` → TTS push."""
    try:
        text = await asyncio.to_thread(stt_engine.transcribe_pcm, pcm, "ko")
    except Exception:
        logger.exception(f"[webrtc:{session.log_id}] transcribe failed")
        return
    logger.info(f"[webrtc:{session.log_id}] STT → {text!r}")
    session.send({"type": "stt_final", "text": text})
    if not text.strip():
        logger.info(f"[webrtc:{session.log_id}] empty transcript — skip intent dispatch")
        return
    robot = session.robot or "eduping"
    try:
        intent = await _dispatch_intent(text, robot)
    except Exception:
        logger.exception(f"[webrtc:{session.log_id}] intent dispatch failed")
        return
    logger.info(f"[webrtc:{session.log_id}] intent → {intent!r}")
    session.send({"type": "intent", **intent})

    # chat 응답이면 TTS 합성 + outbound 로 push. goto_vertex / sub_command 등은
    # 클라이언트가 자체 처리 (e.g. navigate API) 하므로 서버 TTS 안 함.
    if intent.get("kind") == "chat":
        reply = (intent.get("reply") or "").strip()
        if reply and session.outbound_tts is not None:
            await _speak_reply(reply, session)


async def _dispatch_intent(text: str, robot: str) -> dict:
    """ai-service /voice/intent 호출 — 기존 control-service /api/voice/intent 와 동일."""
    payload = {"text": text, "robot": robot, "class_roster": []}
    async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
        response = await client.post(
            f"{settings.ai_hub_url}/voice/intent",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


async def _speak_reply(text: str, session: _Session) -> None:
    """ai-service /voice/tts → av 로 PCM 디코드 → outbound track push.

    tts_start payload 에 text + duration_ms 동봉 — 클라이언트 lip-sync 가 한글 음절
    인덱스 계산에 사용. tts_start 는 decode 완료 후 실제 audio push 시점에 송신해
    audio 시작과 lip-sync 타이밍이 일치.
    """
    track = session.outbound_tts
    if track is None:
        return

    # 새 발화 시작 — 이전 buffer 가 남아있으면 즉시 비움 (말이 겹치지 않게).
    await track.clear()
    t0 = time.monotonic()

    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
            async with client.stream(
                "GET",
                f"{settings.ai_hub_url}/voice/tts",
                params={"text": text},
            ) as response:
                if response.status_code != 200:
                    logger.warning(f"[webrtc:{session.log_id}] TTS upstream {response.status_code}")
                    session.send({"type": "tts_end"})
                    return
                mp3 = bytearray()
                async for chunk in response.aiter_bytes():
                    mp3.extend(chunk)

        pcm = await asyncio.to_thread(_decode_mp3_to_pcm48k, bytes(mp3))
        pcm_total = len(pcm) // 2
        if pcm_total == 0:
            logger.warning(f"[webrtc:{session.log_id}] decoded TTS empty")
            session.send({"type": "tts_end"})
            return

        duration_s = pcm_total / OutboundTTSTrack.SAMPLE_RATE
        duration_ms = int(duration_s * 1000)
        session.send({"type": "tts_start", "text": text, "duration_ms": duration_ms})
        await track.push_pcm(pcm)
        logger.info(
            f"[webrtc:{session.log_id}] TTS pushed {pcm_total} samples ({duration_ms}ms) "
            f"in {(time.monotonic()-t0)*1000:.0f}ms"
        )
        await asyncio.sleep(duration_s)
        session.send({"type": "tts_end"})
    except Exception:
        logger.exception(f"[webrtc:{session.log_id}] TTS speak failed")
        session.send({"type": "tts_end"})


def _decode_mp3_to_pcm48k(mp3_bytes: bytes) -> bytes:
    """MP3 bytes → 48kHz mono int16 LE PCM bytes. (동기, thread 에서 호출)"""
    container = av.open(io.BytesIO(mp3_bytes))
    try:
        resampler = AudioResampler(format="s16", layout="mono", rate=OutboundTTSTrack.SAMPLE_RATE)
        out = bytearray()
        for packet in container.demux(audio=0):
            for frame in packet.decode():
                for resampled in resampler.resample(frame):
                    arr = resampled.to_ndarray()
                    if arr.ndim == 2:
                        arr = arr[0]
                    out.extend(arr.tobytes())
        # flush resampler
        for resampled in resampler.resample(None):
            arr = resampled.to_ndarray()
            if arr.ndim == 2:
                arr = arr[0]
            out.extend(arr.tobytes())
        return bytes(out)
    finally:
        container.close()
