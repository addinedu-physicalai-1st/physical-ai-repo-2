/**
 * GogoPing WebRTC video consumer — control-service signaling 을 통해
 * gogoping_camera 의 1080p H.264 track 을 받는다.
 *
 * **Singleton 패턴**: 페이지 전체에 PeerConnection + WebSocket 한 쌍만 유지한다.
 * 여러 컴포넌트 (App.vue / FollowFaceAuth / FollowMode / ...) 가 useWebRTCStream
 * 을 호출해도 모두 같은 stream Ref 를 공유한다. refCount=0 이 되는 시점에만
 * 실제로 connection teardown.
 *
 * 흐름:
 *   1) WS /ws/webrtc/signaling connect, role=consumer
 *   2) hello 송신 + 자기 PC (recvonly transceiver) + createOffer → 송신
 *   3) server answer 수신 → setRemoteDescription
 *   4) ontrack (또는 transceiver.receiver.track) → MediaStream → stream Ref
 *   5) ICE candidate 양방향
 */
import { ref, onBeforeUnmount, type Ref } from 'vue';

export type WebRTCStreamStatus = 'idle' | 'connecting' | 'connected' | 'closed';

export interface WebRTCStreamHandle {
  stream: Ref<MediaStream | null>;
  status: Ref<WebRTCStreamStatus>;
  stop: () => void;
  /** 외부에서 강제 reconnect — track 이 ended 상태일 때 컴포넌트가 호출. */
  forceReconnect: () => void;
}

// ─── module-level singleton state ────────────────────────────────────────────
let sharedStream: Ref<MediaStream | null> | null = null;
let sharedStatus: Ref<WebRTCStreamStatus> | null = null;
let sharedStop: (() => void) | null = null;
let sharedForceReconnect: (() => void) | null = null;
let refCount = 0;

function createConnection(peerId: string): WebRTCStreamHandle {
  const stream = ref<MediaStream | null>(null);
  const status = ref<WebRTCStreamStatus>('idle');

  let pc: RTCPeerConnection | null = null;
  let ws: WebSocket | null = null;
  let stopped = false;
  let reconnectTimer: number | null = null;
  // exponential backoff: producer 가 없거나 server 가 reject 하는 상황에서 1s 주기로
  // reconnect 가 폭주하면 server _consumers dict 에 stale PC 가 쌓여 NVENC backpressure
  // + main video 가 stale stream 에 binding 되는 문제 발생. 1→2→4→8→16→30s 로 늘림.
  let reconnectDelayMs = 1000;
  const RECONNECT_MAX_MS = 30_000;

  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const wsUrl = `${protocol}://${window.location.host}/ws/webrtc/signaling`;

  function teardownPc(): void {
    if (pc) {
      try { pc.close(); } catch { /* ignore */ }
      pc = null;
    }
  }

  function connect(): void {
    if (stopped) return;
    status.value = 'connecting';
    ws = new WebSocket(wsUrl);

    ws.onopen = async () => {
      try {
        console.log('[useWebRTCStream] ws.onopen, peerId=', peerId);
        ws?.send(JSON.stringify({ type: 'hello', role: 'consumer', peer_id: peerId }));
        // 새 PC — 이전 PC 있으면 teardown (재진입 안전)
        teardownPc();
        pc = new RTCPeerConnection({ iceServers: [] });
        const transceiver = pc.addTransceiver('video', { direction: 'recvonly' });
        // H.264 codec preference 강제 (server 측 NVENC encoder 와 매칭).
        // VP8 (software) 대신 H.264 hardware decode 로 latency 추가 개선.
        try {
          const caps = RTCRtpReceiver.getCapabilities('video');
          if (caps) {
            const h264 = caps.codecs.filter(c => c.mimeType === 'video/H264');
            if (h264.length > 0) {
              transceiver.setCodecPreferences(h264);
            }
          }
        } catch (e) {
          console.warn('[useWebRTCStream] setCodecPreferences failed', e);
        }

        pc.ontrack = (ev) => {
          // aiortc 의 MediaRelay.subscribe(track) 가 보낸 track 은 SDP a=msid 없을 수
          // 있어 ev.streams 빈 배열. 그 때 track 만으로 새 MediaStream 구성.
          if (ev.streams && ev.streams.length > 0) {
            stream.value = ev.streams[0];
          } else if (ev.track) {
            const ms = new MediaStream();
            ms.addTrack(ev.track);
            stream.value = ms;
          }
          status.value = 'connected';
          // 실제 미디어 수신 시점에 backoff 리셋 — 다음 끊김에는 1s 부터 다시 시작.
          reconnectDelayMs = 1000;
        };

        pc.onicecandidate = (ev) => {
          ws?.send(JSON.stringify({ type: 'ice', candidate: ev.candidate ?? null }));
        };

        pc.onconnectionstatechange = () => {
          if (!pc) return;
          if (pc.connectionState === 'connected') {
            status.value = 'connected';
          } else if (pc.connectionState === 'failed') {
            // 'failed' 만 reconnect 트리거. 'disconnected' 는 일시적인 네트워크
            // hiccup 일 수 있어 (WebRTC 표준 동작) close 하지 않는다. 'failed'
            // 는 더 강한 신호 — 실제로 연결이 죽었을 때만 ws close.
            try { ws?.close(); } catch { /* ignore */ }
          }
        };

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        ws?.send(JSON.stringify({ type: 'offer', sdp: pc.localDescription?.sdp }));
      } catch (e) {
        console.error('[useWebRTCStream] onopen error', e);
        try { ws?.close(); } catch { /* ignore */ }
      }
    };

    ws.onmessage = async (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === 'answer' && pc) {
          await pc.setRemoteDescription({ type: 'answer', sdp: msg.sdp });
          // fallback: ontrack 가 발화 안 했거나 ev.streams 빈 배열이면 transceiver.receiver.track
          // 을 직접 가져와 stream 구성
          if (!stream.value) {
            for (const t of pc.getTransceivers()) {
              const track = t.receiver?.track;
              if (track && track.kind === 'video') {
                const ms = new MediaStream();
                ms.addTrack(track);
                stream.value = ms;
                status.value = 'connected';
                break;
              }
            }
          }
        } else if (msg.type === 'ice' && msg.candidate && pc) {
          await pc.addIceCandidate(msg.candidate);
        }
      } catch (e) {
        console.error('[useWebRTCStream] onmessage error', e);
      }
    };

    ws.onclose = () => {
      status.value = 'closed';
      teardownPc();
      // stream.value 는 그대로 유지 — 끊겨도 마지막 frame 으로 freeze 시켜두고
      // 새 track 이 ontrack 으로 들어오면 새 MediaStream 인스턴스로 교체. placeholder
      // 깜빡임 방지. (각 reconnect 가 새 PC + 새 MediaStream 이라 ref 동일성 충돌 없음.)
      if (!stopped) {
        reconnectTimer = window.setTimeout(connect, reconnectDelayMs);
        reconnectDelayMs = Math.min(reconnectDelayMs * 2, RECONNECT_MAX_MS);
      }
    };

    ws.onerror = () => {
      // onclose 가 이어서 호출되므로 별도 처리 불필요 (reconnect 트리거 됨)
    };
  }

  connect();

  function stop(): void {
    stopped = true;
    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    teardownPc();
    if (ws && ws.readyState <= 1) {
      try { ws.close(); } catch { /* ignore */ }
    }
    ws = null;
    stream.value = null;
    status.value = 'closed';
  }

  function forceReconnect(): void {
    // ws.close 가 onclose 발화 → teardownPc + reconnect 자동. backoff 도 다음
    // ontrack 에서 1s 로 리셋되므로 빠르게 복구.
    reconnectDelayMs = 1000;
    if (ws && ws.readyState <= 1) {
      try { ws.close(); } catch { /* ignore */ }
    } else {
      // ws 이미 죽었으면 직접 reconnect 트리거
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      teardownPc();
      reconnectTimer = window.setTimeout(connect, 100);
    }
  }

  return { stream, status, stop, forceReconnect };
}

/**
 * Singleton — 첫 호출 시 connection 생성, 이후 호출은 같은 handle 공유.
 * 각 호출자는 컴포넌트 unmount 시 refCount-- 만 함. refCount=0 이 되면 실제 teardown.
 */
export function useWebRTCStream(peerId: string = 'robot-web'): WebRTCStreamHandle {
  if (sharedStream === null || sharedStatus === null || sharedStop === null) {
    const handle = createConnection(peerId);
    sharedStream = handle.stream;
    sharedStatus = handle.status;
    sharedStop = handle.stop;
    sharedForceReconnect = handle.forceReconnect;
  }
  refCount++;

  onBeforeUnmount(() => {
    refCount--;
    if (refCount <= 0 && sharedStop) {
      sharedStop();
      sharedStream = null;
      sharedStatus = null;
      sharedStop = null;
      sharedForceReconnect = null;
      refCount = 0;
    }
  });

  return {
    stream: sharedStream,
    status: sharedStatus,
    stop: sharedStop,
    forceReconnect: sharedForceReconnect!,
  };
}

/**
 * Singleton 에 강제 reconnect 명령 — provide/inject 만 받는 컴포넌트가 stale track 감지 시 호출.
 * useWebRTCStream() 호출 없이도 외부에서 트리거 가능.
 */
export function forceReconnectWebRTCStream(): void {
  sharedForceReconnect?.();
}
