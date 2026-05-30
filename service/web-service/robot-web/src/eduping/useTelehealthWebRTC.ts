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
 *   서버가 peer (재)등록 시 양쪽에 {type:peer, present:bool} broadcast.
 *   doctor 가 polite=false (always offer), eduping 이 polite=true (always answer).
 *
 * 자동 재연결 (새로고침 불필요):
 *   - 시그널링 WS 가 끊기면 backoff 로 재접속.
 *   - presence:true 가 올 때마다 PeerConnection 을 **fresh 로 재생성** → 상대가 늦게/다시
 *     붙어도 깨끗한 세션으로 재협상. (낡은 PC 재사용은 ICE 가 안 살아남.)
 *   - PC 가 'failed' 면 WS 를 끊었다 다시 붙임 → 서버가 presence 재broadcast → 양쪽 재생성.
 */
import { onBeforeUnmount, ref, shallowRef, type Ref } from 'vue';

export type WebRTCRole = 'doctor' | 'eduping';

export interface TelehealthOpts {
  role: WebRTCRole;
  /** 로컬 송신 MediaStream factory — null 반환 시 송신 안 함. 재연결마다 다시 호출될 수 있음. */
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

type SignalMsg = { type: string; sdp?: string; candidate?: RTCIceCandidateInit; present?: boolean };

export function useTelehealthWebRTC(opts: TelehealthOpts): Telehealth {
  const status = ref<Telehealth['status']['value']>('idle');
  const remoteStream = shallowRef<MediaStream | null>(null);

  let pc: RTCPeerConnection | null = null;
  let ws: WebSocket | null = null;
  let localStream: MediaStream | null = null;
  let stopped = false;
  let started = false;
  let peerPresent = false;
  let makingOffer = false;
  let buildingPc: Promise<void> | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let backoff = 1000;
  const isPolite = opts.role === 'eduping';

  function send(obj: object): void {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  }

  function teardownPc(): void {
    if (pc) {
      try { pc.close(); } catch { /* ignore */ }
      pc = null;
    }
    if (localStream) {
      for (const t of localStream.getTracks()) t.stop();
      localStream = null;
    }
    remoteStream.value = null;
  }

  async function buildPc(): Promise<void> {
    teardownPc();
    const npc = new RTCPeerConnection({ iceServers: STUN_SERVERS });
    npc.onicecandidate = (ev) => {
      if (ev.candidate) send({ type: 'ice', candidate: ev.candidate.toJSON() });
    };
    npc.ontrack = (ev) => {
      if (pc === npc && ev.streams[0]) remoteStream.value = ev.streams[0];
    };
    npc.onconnectionstatechange = () => {
      if (pc !== npc) return;
      const s = npc.connectionState;
      if (s === 'connected') status.value = 'connected';
      else if (s === 'connecting' || s === 'new' || s === 'disconnected') status.value = 'connecting';
      else if (s === 'failed') { status.value = 'error'; reconnectSignaling(); }
    };
    // 로컬 미디어 attach (재연결마다 새로 획득).
    const stream = await opts.acquireLocalStream();
    localStream = stream;
    if (stream) {
      for (const track of stream.getTracks()) npc.addTrack(track, stream);
    }
    pc = npc;
  }

  /** PC 가 없으면 생성 (진행 중이면 그 build 를 기다림). */
  async function ensurePc(): Promise<void> {
    if (pc) return;
    if (!buildingPc) buildingPc = buildPc().finally(() => { buildingPc = null; });
    await buildingPc;
  }

  /** presence:true → 항상 fresh PC 로 재생성 후, doctor 면 offer. */
  async function rebuildAndMaybeOffer(): Promise<void> {
    buildingPc = buildPc().finally(() => { buildingPc = null; });
    await buildingPc;
    if (opts.role === 'doctor' && peerPresent && pc) {
      try {
        makingOffer = true;
        await pc.setLocalDescription();
        send({ type: 'offer', sdp: pc.localDescription!.sdp });
      } catch (e) {
        console.error('[telehealth] offer failed', e);
      } finally {
        makingOffer = false;
      }
    }
  }

  async function onSignal(text: string): Promise<void> {
    let msg: SignalMsg;
    try { msg = JSON.parse(text); } catch { return; }

    if (msg.type === 'peer') {
      peerPresent = !!msg.present;
      if (peerPresent) {
        await rebuildAndMaybeOffer();
      } else {
        teardownPc();
        if (!stopped) status.value = 'signaling';
      }
      return;
    }
    if (msg.type === 'offer' && msg.sdp) {
      await ensurePc();
      if (!pc) return;
      const offerCollision = makingOffer || pc.signalingState !== 'stable';
      if (!isPolite && offerCollision) {
        console.warn('[telehealth] ignoring offer (collision, not polite)');
        return;
      }
      try {
        await pc.setRemoteDescription({ type: 'offer', sdp: msg.sdp });
        await pc.setLocalDescription();
        send({ type: 'answer', sdp: pc.localDescription!.sdp });
      } catch (e) {
        console.warn('[telehealth] answer failed', e);
      }
    } else if (msg.type === 'answer' && msg.sdp) {
      if (!pc) return;
      try { await pc.setRemoteDescription({ type: 'answer', sdp: msg.sdp }); }
      catch (e) { console.warn('[telehealth] setRemoteDescription(answer) failed', e); }
    } else if (msg.type === 'ice' && msg.candidate) {
      if (!pc) return;
      try { await pc.addIceCandidate(msg.candidate); }
      catch (e) { if (!makingOffer) console.warn('[telehealth] addIceCandidate failed', e); }
    }
  }

  function openWs(): void {
    if (stopped) return;
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    status.value = 'signaling';
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${location.host}/ws/doctor/signal?role=${opts.role}`;
    const sock = new WebSocket(url);
    ws = sock;
    sock.onopen = () => { backoff = 1000; };
    sock.onmessage = (ev) => { void onSignal(String(ev.data)); };
    sock.onclose = () => { if (ws === sock) { ws = null; handleDisconnect(); } };
    sock.onerror = () => { /* onclose 가 뒤따름 */ };
  }

  function handleDisconnect(): void {
    teardownPc();
    peerPresent = false;
    if (stopped) { status.value = 'closed'; return; }
    status.value = 'signaling';
    scheduleReconnect();
  }

  function scheduleReconnect(): void {
    if (stopped || reconnectTimer) return;
    reconnectTimer = setTimeout(() => { reconnectTimer = null; openWs(); }, backoff);
    backoff = Math.min(backoff * 2, 10000);
  }

  /** PC 실패 시 WS 를 끊어 재접속 유도 → 서버가 presence 재broadcast → 양쪽 fresh PC. */
  function reconnectSignaling(): void {
    if (stopped) return;
    if (ws) { try { ws.close(); } catch { /* ignore */ } }
    // onclose → handleDisconnect → scheduleReconnect.
  }

  async function start(): Promise<void> {
    if (stopped || started) return;
    started = true;
    openWs();
  }

  function stop(): void {
    stopped = true;
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    teardownPc();
    if (ws) { try { ws.close(); } catch { /* ignore */ } ws = null; }
    status.value = 'closed';
  }

  onBeforeUnmount(() => stop());

  return { status, remoteStream, start, stop };
}
