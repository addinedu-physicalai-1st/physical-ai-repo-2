<script setup lang="ts">
/**
 * 건강검진 — EduPing 화면 = 의사 화상 (WebRTC remote, main) + D435 RGB 자기 PIP.
 *
 * WebRTC:
 *   송신: D435 RGB (WS → canvas → captureStream) + 노트북 mic (getUserMedia audio)
 *   수신: 의사 cam + mic (P2P 직접)
 *
 * D435 RGB 는 여전히 /ws/eduping/rgb 로 받아 canvas 그림 → captureStream(15) 로
 * MediaStreamTrack 만들어 RTCPeerConnection 에 addTrack.
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useModeStore } from '@/stores/mode';
import { useProximityOverride } from '@/composables/useProximityOverride';
import { useTelehealthWebRTC } from './useTelehealthWebRTC';

const modeStore = useModeStore();
useProximityOverride();  // 건강검진 — 아이가 팔/카메라에 가까이 오는 모드라 근접 정지 우회
function exitHealthCheck(): void { modeStore.setMode('대기'); }

const EDUPING_RGB_PATH = '/ws/eduping/rgb?role=consumer';

const remoteVideoRef = ref<HTMLVideoElement | null>(null);
const selfPipRef = ref<HTMLCanvasElement | null>(null);
const selfStatus = ref<'connecting' | 'open' | 'streaming' | 'closed'>('connecting');

// D435 RGB 수신용 WS — canvas 에 그리고 captureStream 으로 WebRTC track 만듦.
let rgbWs: WebSocket | null = null;
let rgbBackoff = 1000;
let rgbReconnect: number | null = null;
let stopped = false;

async function drawJpegToSelf(blob: Blob): Promise<void> {
  const c = selfPipRef.value;
  if (!c) return;
  let bm: ImageBitmap | null = null;
  try { bm = await createImageBitmap(blob); } catch { return; }
  if (c.width !== bm.width || c.height !== bm.height) {
    c.width = bm.width; c.height = bm.height;
  }
  c.getContext('2d')?.drawImage(bm, 0, 0);
  bm.close();
}

function connectRgb(): void {
  if (stopped) return;
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${proto}//${location.host}${EDUPING_RGB_PATH}`;
  selfStatus.value = 'connecting';
  const ws = new WebSocket(url);
  ws.binaryType = 'arraybuffer';
  rgbWs = ws;
  ws.onopen = () => { selfStatus.value = 'open'; rgbBackoff = 1000; };
  ws.onclose = () => { selfStatus.value = 'closed'; scheduleReconnect(); };
  ws.onerror = () => { /* onclose 가 따라옴 */ };
  ws.onmessage = (ev) => {
    if (!(ev.data instanceof ArrayBuffer)) return;
    selfStatus.value = 'streaming';
    void drawJpegToSelf(new Blob([ev.data], { type: 'image/jpeg' }));
  };
}

function scheduleReconnect(): void {
  if (stopped || rgbReconnect !== null) return;
  rgbReconnect = window.setTimeout(() => {
    rgbReconnect = null;
    rgbBackoff = Math.min(rgbBackoff * 2, 30000);
    connectRgb();
  }, rgbBackoff) as unknown as number;
}

// WebRTC — eduping 역할. D435 canvas.captureStream + 노트북 mic 송신, 의사 영상 수신.
const telehealth = useTelehealthWebRTC({
  role: 'eduping',
  acquireLocalStream: async () => {
    const c = selfPipRef.value;
    if (!c) {
      console.warn('[hc-cam] self canvas not ready for captureStream');
      return null;
    }
    // D435 canvas 영상 track.
    const canvasStream = (c as HTMLCanvasElement).captureStream(15);
    // 노트북 mic audio track 별도로 받아서 합침.
    try {
      const mic = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      for (const t of mic.getAudioTracks()) canvasStream.addTrack(t);
    } catch (e) {
      console.warn('[hc-cam] mic getUserMedia failed — 영상만 송신', e);
    }
    return canvasStream;
  },
});

onMounted(() => {
  connectRgb();
  // canvas 가 mount 되고 한 프레임 정도 후에 RTC 시작 — captureStream 이 빈 canvas
  // 잡아도 OK 지만, 약간 지연 두면 첫 프레임 드로잉 후 stream 이 더 안정적.
  setTimeout(() => { void telehealth.start(); }, 300);
});

onBeforeUnmount(() => {
  stopped = true;
  if (rgbReconnect !== null) { window.clearTimeout(rgbReconnect); rgbReconnect = null; }
  if (rgbWs) { try { rgbWs.close(); } catch { /* ignore */ } rgbWs = null; }
  telehealth.stop();
});

// 의사 영상/오디오 remote stream 도착 시 main video 에 attach.
watch(telehealth.remoteStream, (s) => {
  if (remoteVideoRef.value && s) {
    remoteVideoRef.value.srcObject = s;
    void remoteVideoRef.value.play().catch(() => {});
  }
});
</script>

<template>
  <div class="hc-cam">
    <header class="bar">
      <button class="exit" @click="exitHealthCheck">← 나가기</button>
      <span class="title">🩺 건강검진</span>
      <span class="spacer" />
      <span class="status" :data-state="telehealth.status.value" title="의사 영상">
        의사: {{ telehealth.status.value }}
      </span>
      <span class="status" :data-state="selfStatus" title="D435 RGB">D435: {{ selfStatus }}</span>
    </header>
    <div class="stage">
      <video ref="remoteVideoRef" class="main-cam" autoplay playsinline />
      <div v-if="telehealth.status.value !== 'connected'" class="overlay">
        <div class="overlay-card">
          <p class="big">의사 연결 대기중</p>
          <p class="hint">의사가 portal-web 의 진찰 화면을 열면 자동으로 영상이 표시됩니다.</p>
        </div>
      </div>
      <div class="self-pip-wrap">
        <span class="pip-label">내 모습 (D435)</span>
        <canvas ref="selfPipRef" class="self-pip" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.hc-cam {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  background: linear-gradient(135deg, rgba(255, 241, 242, 0.96) 0%, rgba(255, 228, 230, 0.96) 100%);
  z-index: 50;
}
.bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 28px;
  background: rgba(255, 255, 255, 0.7);
  border-bottom: 1px solid rgba(219, 39, 119, 0.15);
  backdrop-filter: blur(8px);
}
.exit {
  background: rgba(255, 255, 255, 0.8);
  color: rgba(219, 39, 119, 0.85);
  border: 1px solid rgba(219, 39, 119, 0.3);
  font-weight: 600;
  padding: 6px 14px;
  border-radius: 999px;
  cursor: pointer;
  font-size: 14px;
}
.exit:hover { background: rgba(219, 39, 119, 0.15); }
.title {
  font-size: 22px;
  font-weight: 800;
  color: rgba(219, 39, 119, 0.85);
  letter-spacing: -0.3px;
}
.spacer { flex: 1; }
.status {
  font-size: 12px;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.7);
  color: #6b7280;
  border: 1px solid rgba(219, 39, 119, 0.18);
}
.status[data-state="streaming"], .status[data-state="open"], .status[data-state="connected"] {
  background: rgba(91, 169, 120, 0.15);
  color: #2f7d52;
  border-color: rgba(91, 169, 120, 0.35);
}
.status[data-state="closed"], .status[data-state="error"] {
  background: rgba(217, 83, 79, 0.12);
  color: #b54848;
  border-color: rgba(217, 83, 79, 0.35);
}
.stage {
  position: relative;
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  min-height: 0;
}
.main-cam {
  width: 100%;
  height: 100%;
  background: #fff;
  border-radius: 18px;
  border: 4px solid rgba(255, 255, 255, 0.9);
  box-shadow: 0 12px 36px rgba(219, 39, 119, 0.18);
  object-fit: contain;
}
.overlay {
  position: absolute;
  inset: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.overlay-card {
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(219, 39, 119, 0.2);
  border-radius: 14px;
  padding: 22px 28px;
  text-align: center;
  box-shadow: 0 6px 24px rgba(219, 39, 119, 0.12);
}
.overlay-card .big {
  margin: 0 0 8px 0;
  font-size: 20px;
  font-weight: 700;
  color: rgba(219, 39, 119, 0.9);
}
.overlay-card .hint { margin: 0; font-size: 13px; color: #6b7280; max-width: 320px; }
.self-pip-wrap {
  position: absolute;
  bottom: 28px;
  left: 28px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.pip-label {
  font-size: 11px;
  font-weight: 600;
  color: rgba(219, 39, 119, 0.8);
  background: rgba(255, 255, 255, 0.85);
  padding: 3px 10px;
  border-radius: 999px;
  align-self: flex-start;
  border: 1px solid rgba(219, 39, 119, 0.18);
}
.self-pip {
  width: 220px;
  height: 165px;
  background: #fff;
  border-radius: 12px;
  border: 3px solid rgba(255, 255, 255, 0.95);
  box-shadow: 0 8px 24px rgba(219, 39, 119, 0.22);
  object-fit: cover;
}
</style>
