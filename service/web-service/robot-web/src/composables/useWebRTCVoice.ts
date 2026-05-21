/**
 * WebRTC 음성 채널 — 서버와 양방향 audio + DataChannel.
 *
 * Phase 1 (현재): PC 연결 + outbound mic + inbound audio playback + DataChannel
 * scaffold 만. 서버측 VAD/STT/intent/TTS 통합 전. 다른 곳 (useServerSTT/useTTS)
 * 과 병행 동작하면서 mic 충돌 없이 connection + first audio frame 만 검증.
 *
 * 시그널링: POST /api/voice/webrtc/offer (vanilla ICE — trickle 안 함).
 * STUN 도 같은 LAN 일 땐 불필요하지만 안전하게 google STUN 한 개 박아둠.
 */
import { ref, type Ref } from 'vue';

// 음성 경로 디버그 로그 (WebRTC 연결 lifecycle + DC msg + wake score) on/off.
// 평소엔 false, 임계값 튜닝·연결 트러블슈팅 시 true. warn 은 항상 출력.
export const LOG_VOICE_DEBUG = false;

function dlog(...args: unknown[]): void {
  if (LOG_VOICE_DEBUG) console.log(...args);
}

export interface UseWebRTCVoiceOptions {
  /** robot id — /offer 시 서버에 동봉하여 session.robot 미리 세팅. wake 없이도
   *  ai-service intent dispatch 가 올바른 robot persona 로 라우팅되게 함. */
  robot: string;
  /** PC 가 'connected' 상태로 진입 시. */
  onConnected?: () => void;
  /** PC 가 close/failed 로 끝났을 때. */
  onClosed?: () => void;
  /** 서버에서 DataChannel 메시지 (JSON 파싱 결과). */
  onMessage?: (msg: unknown) => void;
  /** 에러 표시용. */
  onError?: (message: string) => void;
}

export interface UseWebRTCVoiceReturn {
  start: () => Promise<void>;
  stop: () => void;
  /** DataChannel send. PC/DC 미연결이면 warn 만 찍고 drop. */
  send: (msg: unknown) => void;
  /** 로컬 mic 의 outbound track on/off. PC/DC 는 그대로 유지 — 텍스트 모드에서 사용. */
  setMicEnabled: (enabled: boolean) => void;
  isConnected: Ref<boolean>;
  /** 서버 outbound TTS 가 도착하는 audio element — lip-sync 가 createMediaStreamSource 로 분석. */
  remoteAudioEl: Ref<HTMLAudioElement | null>;
  /** 서버 outbound MediaStream — Web Audio analyser 등 추가 처리에 직접 활용 가능. */
  remoteStream: Ref<MediaStream | null>;
  /** 로컬 mic 의 0~1 RMS — SiriBlob 시각화용. */
  micLevel: Ref<number>;
}

const RTC_CONFIG: RTCConfiguration = {
  iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
};

const CLIENT_ID_STORAGE_KEY = 'pingdergarten:webrtcClientId';

/** 브라우저별 영속 UUID — 새 offer 마다 동봉. 서버는 같은 client_id 의 이전 세션을
 *  evict 하고 새 PC 로 교체 (refresh). 다른 client_id 는 독립 세션으로 공존. */
function getOrCreateClientId(): string {
  try {
    let id = localStorage.getItem(CLIENT_ID_STORAGE_KEY);
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem(CLIENT_ID_STORAGE_KEY, id);
    }
    return id;
  } catch {
    // localStorage 사용 불가 (private mode 등) — 휘발성 UUID 사용.
    return crypto.randomUUID();
  }
}

export function useWebRTCVoice(options: UseWebRTCVoiceOptions): UseWebRTCVoiceReturn {
  const isConnected = ref(false);
  const remoteAudioEl: Ref<HTMLAudioElement | null> = ref(null);
  const remoteStream: Ref<MediaStream | null> = ref(null);
  const micLevel: Ref<number> = ref(0);

  let pc: RTCPeerConnection | null = null;
  let localStream: MediaStream | null = null;
  let dc: RTCDataChannel | null = null;
  let levelCtx: AudioContext | null = null;
  let levelAnalyser: AnalyserNode | null = null;
  let levelData: Uint8Array | null = null;
  let levelRafId: number | null = null;

  async function start(): Promise<void> {
    if (pc) {
      console.warn('[WebRTC] already started');
      return;
    }
    dlog('[WebRTC] starting…');

    try {
      pc = new RTCPeerConnection(RTC_CONFIG);
    } catch (e) {
      options.onError?.(`RTCPeerConnection 생성 실패: ${(e as Error).message}`);
      return;
    }

    pc.onconnectionstatechange = (): void => {
      const state = pc?.connectionState;
      dlog('[WebRTC] connection state:', state);
      if (state === 'connected') {
        isConnected.value = true;
        options.onConnected?.();
      } else if (state === 'failed' || state === 'closed' || state === 'disconnected') {
        isConnected.value = false;
        if (state !== 'disconnected') options.onClosed?.();
      }
    };

    pc.oniceconnectionstatechange = (): void => {
      dlog('[WebRTC] ICE state:', pc?.iceConnectionState);
    };

    // 인바운드 — 서버가 보낸 TTS audio. <audio> 에 srcObject 로 attach.
    // Chrome 은 DOM 에 attach 되지 않은 audio element 의 WebRTC MediaStream 을 silent
    // 로 출력하는 known issue 가 있음. body 에 hidden 으로 append 해서 실제 스피커로
    // 출력되게 한다.
    pc.ontrack = (event): void => {
      if (event.track.kind !== 'audio') return;
      const stream = event.streams[0] ?? new MediaStream([event.track]);
      if (!remoteAudioEl.value) {
        const el = new Audio();
        el.autoplay = true;
        el.style.display = 'none';
        el.setAttribute('data-webrtc-remote', 'true');
        document.body.appendChild(el);
        remoteAudioEl.value = el;
      }
      remoteAudioEl.value.srcObject = stream;
      remoteStream.value = stream;
      remoteAudioEl.value.play().catch((err) => {
        console.warn('[WebRTC] remote audio autoplay failed:', err);
      });
      dlog('[WebRTC] remote audio track attached');
    };

    // DataChannel — 클라가 먼저 생성. 서버 (aiortc) 가 ondatachannel 로 받는다.
    dc = pc.createDataChannel('control');
    dc.onopen = (): void => {
      dlog('[WebRTC] DataChannel open');
    };
    dc.onclose = (): void => {
      dlog('[WebRTC] DataChannel close');
    };
    dc.onerror = (ev): void => {
      console.warn('[WebRTC] DataChannel error:', ev);
    };
    dc.onmessage = (ev: MessageEvent): void => {
      let parsed: unknown = ev.data;
      try {
        parsed = JSON.parse(ev.data as string);
      } catch {
        /* 텍스트 그대로 전달 */
      }
      dlog('[WebRTC] DC msg:', parsed);
      options.onMessage?.(parsed);
    };

    // 아웃바운드 — 마이크 캡처 후 PC 에 track 추가.
    try {
      localStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (e) {
      options.onError?.(`마이크 권한 필요: ${(e as Error).message}`);
      stop();
      return;
    }
    for (const track of localStream.getAudioTracks()) {
      pc.addTrack(track, localStream);
    }

    // SiriBlob 시각화용 mic level 분석 — WebRTC 와 무관한 별도 Web Audio 그래프.
    try {
      const Ctor =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (Ctor) {
        levelCtx = new Ctor();
        if (levelCtx.state === 'suspended') {
          try { await levelCtx.resume(); } catch { /* noop */ }
        }
        const source = levelCtx.createMediaStreamSource(localStream);
        levelAnalyser = levelCtx.createAnalyser();
        levelAnalyser.fftSize = 512;
        levelAnalyser.smoothingTimeConstant = 0.6;
        source.connect(levelAnalyser);
        levelData = new Uint8Array(levelAnalyser.frequencyBinCount);
        tickLevel();
      }
    } catch (e) {
      console.warn('[WebRTC] level analyser setup failed:', e);
    }

    // 시그널링 — vanilla ICE: createOffer → setLocalDescription → ICE 다 모일 때까지
    // 잠시 대기 → 서버로 send. trickle 없이 한 번에 끝내 코드 단순.
    let offer: RTCSessionDescriptionInit;
    try {
      offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await waitForIceGathering(pc);
    } catch (e) {
      options.onError?.(`offer 생성 실패: ${(e as Error).message}`);
      stop();
      return;
    }

    try {
      const clientId = getOrCreateClientId();
      const res = await fetch('/api/voice/webrtc/offer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sdp: pc.localDescription!.sdp,
          type: pc.localDescription!.type,
          client_id: clientId,
          robot: options.robot,
        }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new Error(`HTTP ${res.status}: ${text}`);
      }
      const answer = (await res.json()) as RTCSessionDescriptionInit;
      await pc.setRemoteDescription(answer);
      dlog('[WebRTC] answer applied, waiting for ICE…');
    } catch (e) {
      options.onError?.(`signaling 실패: ${(e as Error).message}`);
      stop();
    }
  }

  function tickLevel(): void {
    if (!levelAnalyser || !levelData) return;
    levelAnalyser.getByteTimeDomainData(levelData as unknown as Uint8Array);
    let sumSq = 0;
    for (let i = 0; i < levelData.length; i++) {
      const v = (levelData[i]! - 128) / 128;
      sumSq += v * v;
    }
    const rms = Math.sqrt(sumSq / levelData.length);
    const next = Math.min(1, rms * 4);
    micLevel.value = micLevel.value * 0.6 + next * 0.4;
    levelRafId = window.requestAnimationFrame(tickLevel);
  }

  function stop(): void {
    dlog('[WebRTC] stopping');
    if (levelRafId !== null) {
      window.cancelAnimationFrame(levelRafId);
      levelRafId = null;
    }
    if (levelCtx) {
      void levelCtx.close();
      levelCtx = null;
    }
    levelAnalyser = null;
    levelData = null;
    micLevel.value = 0;
    try { dc?.close(); } catch { /* noop */ }
    dc = null;
    if (remoteAudioEl.value) {
      try { remoteAudioEl.value.pause(); } catch { /* noop */ }
      remoteAudioEl.value.srcObject = null;
      try { remoteAudioEl.value.remove(); } catch { /* noop */ }
      remoteAudioEl.value = null;
    }
    remoteStream.value = null;
    if (localStream) {
      localStream.getTracks().forEach((t) => t.stop());
      localStream = null;
    }
    if (pc) {
      try { pc.close(); } catch { /* noop */ }
      pc = null;
    }
    isConnected.value = false;
  }

  function send(msg: unknown): void {
    if (!dc || dc.readyState !== 'open') {
      console.warn('[WebRTC] DC not open, drop msg', msg);
      return;
    }
    dc.send(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }

  function setMicEnabled(enabled: boolean): void {
    if (!localStream) return;
    for (const track of localStream.getAudioTracks()) {
      track.enabled = enabled;
    }
  }

  return { start, stop, send, setMicEnabled, isConnected, remoteAudioEl, remoteStream, micLevel };
}

/** ICE gathering 완료 대기 — vanilla ICE 용. timeout 1s 후 그냥 진행 (호스트만이라도). */
function waitForIceGathering(pc: RTCPeerConnection, timeoutMs = 1000): Promise<void> {
  if (pc.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => {
      pc.removeEventListener('icegatheringstatechange', onChange);
      resolve();
    }, timeoutMs);
    const onChange = (): void => {
      if (pc.iceGatheringState === 'complete') {
        window.clearTimeout(timer);
        pc.removeEventListener('icegatheringstatechange', onChange);
        resolve();
      }
    };
    pc.addEventListener('icegatheringstatechange', onChange);
  });
}
