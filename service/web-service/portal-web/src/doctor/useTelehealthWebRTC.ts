/**
 * Doctor portal ↔ EduPing robot-web 간 WebRTC 화상통화 composable.
 *
 * 송신:
 *   getUserMedia(video+audio) → addTrack → RTCPeerConnection → P2P
 *
 * 수신:
 *   ontrack 으로 remote MediaStream 받음 → ref 로 노출 (UI 가 video element 에 srcObject)
 *
 * Signaling:
 *   /ws/doctor/signal?role=doctor 로 SDP/ICE 교환.
 *   peer 가 들어왔다는 알림 ({type:peer, present:true}) 받으면 doctor 가 offer 생성.
 *   eduping 은 offer 기다렸다가 answer.
 *
 * doctor 가 polite=false (always offer), eduping 이 polite=true (always answer).
 */
import { onBeforeUnmount, ref, shallowRef, type Ref } from 'vue';

export type WebRTCRole = 'doctor' | 'eduping';

export interface TelehealthOpts {
  role: WebRTCRole;
  /** 로컬 송신 MediaStream factory — null 반환 시 송신 안 함. */
  acquireLocalStream(): Promise<MediaStream | null>;
}

export interface Telehealth {
  status: Ref<'idle' | 'signaling' | 'connecting' | 'connected' | 'closed' | 'error'>;
  remoteStream: Ref<MediaStream | null>;
  start(): Promise<void>;
  stop(): void;
}

const STUN_SERVERS: RTCIceServer[] = [
  { urls: 'stun:stun.l.google.com:19302' },
];

export function useTelehealthWebRTC(opts: TelehealthOpts): Telehealth {
  const status = ref<Telehealth['status']['value']>('idle');
  const remoteStream = shallowRef<MediaStream | null>(null);

  let pc: RTCPeerConnection | null = null;
  let ws: WebSocket | null = null;
  let localStream: MediaStream | null = null;
  let stopped = false;
  let peerPresent = false;
  let makingOffer = false;
  let isPolite = opts.role === 'eduping';   // eduping 이 polite (offer 양보).

  function send(obj: object): void {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  }

  async function ensurePc(): Promise<void> {
    if (pc) return;
    pc = new RTCPeerConnection({ iceServers: STUN_SERVERS });
    pc.onicecandidate = (ev) => {
      if (ev.candidate) send({ type: 'ice', candidate: ev.candidate.toJSON() });
    };
    pc.ontrack = (ev) => {
      // ontrack 은 track 단위로 발생 — 같은 stream 이 비디오/오디오 두 번.
      if (ev.streams[0]) remoteStream.value = ev.streams[0];
    };
    pc.onconnectionstatechange = () => {
      if (!pc) return;
      const s = pc.connectionState;
      if (s === 'connected') status.value = 'connected';
      else if (s === 'failed' || s === 'closed' || s === 'disconnected') {
        status.value = s === 'failed' ? 'error' : 'closed';
      } else if (s === 'connecting' || s === 'new') {
        status.value = 'connecting';
      }
    };
    pc.onnegotiationneeded = async () => {
      if (!pc || opts.role !== 'doctor') return;
      try {
        makingOffer = true;
        await pc.setLocalDescription();
        send({ type: 'offer', sdp: pc.localDescription!.sdp });
      } catch (e) {
        console.error('[telehealth] negotiation failed', e);
      } finally {
        makingOffer = false;
      }
    };

    // 로컬 미디어 attach.
    localStream = await opts.acquireLocalStream();
    if (localStream) {
      for (const track of localStream.getTracks()) {
        const sender = pc.addTrack(track, localStream);
        if (track.kind === 'video') {
          // 송신 비트레이트 — 기본값이 낮아 720p 라도 흐릿하게 보임. LAN 이므로 넉넉히 잡고
          // 대역 부족 시 해상도 대신 프레임을 먼저 떨어뜨려 선명도 유지.
          try {
            const params = sender.getParameters();
            if (!params.encodings || params.encodings.length === 0) {
              params.encodings = [{}];
            }
            params.encodings[0].maxBitrate = 2_500_000; // ~2.5 Mbps @720p
            (params as RTCRtpSendParameters & { degradationPreference?: string }).degradationPreference =
              'maintain-resolution';
            void sender.setParameters(params).catch((e) => {
              console.warn('[telehealth] video setParameters failed', e);
            });
          } catch (e) {
            console.warn('[telehealth] sender params skip', e);
          }
        }
      }
    }
  }

  async function onSignal(text: string): Promise<void> {
    let msg: { type: string; sdp?: string; candidate?: RTCIceCandidateInit; present?: boolean };
    try { msg = JSON.parse(text); } catch { return; }
    if (msg.type === 'peer') {
      peerPresent = !!msg.present;
      // doctor 쪽: peer 들어오면 offer trigger.
      if (peerPresent && opts.role === 'doctor' && pc) {
        // negotiationneeded 가 트랙 추가 시 이미 fire 했을 수 있음. 안전하게 명시 offer.
        try {
          makingOffer = true;
          await pc.setLocalDescription();
          send({ type: 'offer', sdp: pc.localDescription!.sdp });
        } catch (e) {
          console.error('[telehealth] offer on peer-present failed', e);
        } finally {
          makingOffer = false;
        }
      }
      return;
    }
    if (!pc) return;
    if (msg.type === 'offer' && msg.sdp) {
      const offerCollision = makingOffer || pc.signalingState !== 'stable';
      const ignoreOffer = !isPolite && offerCollision;
      if (ignoreOffer) {
        console.warn('[telehealth] ignoring offer (collision, not polite)');
        return;
      }
      await pc.setRemoteDescription({ type: 'offer', sdp: msg.sdp });
      await pc.setLocalDescription();
      send({ type: 'answer', sdp: pc.localDescription!.sdp });
    } else if (msg.type === 'answer' && msg.sdp) {
      await pc.setRemoteDescription({ type: 'answer', sdp: msg.sdp });
    } else if (msg.type === 'ice' && msg.candidate) {
      try {
        await pc.addIceCandidate(msg.candidate);
      } catch (e) {
        if (!makingOffer) console.warn('[telehealth] addIceCandidate failed', e);
      }
    }
  }

  async function start(): Promise<void> {
    if (stopped) return;
    if (status.value !== 'idle') return;
    status.value = 'signaling';

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${location.host}/ws/doctor/signal?role=${opts.role}`;
    ws = new WebSocket(url);
    ws.onopen = async () => {
      await ensurePc();
    };
    ws.onmessage = (ev) => { void onSignal(String(ev.data)); };
    ws.onclose = () => { if (status.value !== 'closed') status.value = 'closed'; };
    ws.onerror = () => { status.value = 'error'; };
  }

  function stop(): void {
    stopped = true;
    if (pc) {
      try { pc.close(); } catch { /* ignore */ }
      pc = null;
    }
    if (localStream) {
      for (const t of localStream.getTracks()) t.stop();
      localStream = null;
    }
    if (ws) {
      try { ws.close(); } catch { /* ignore */ }
      ws = null;
    }
    remoteStream.value = null;
    status.value = 'closed';
  }

  onBeforeUnmount(() => stop());

  return { status, remoteStream, start, stop };
}
