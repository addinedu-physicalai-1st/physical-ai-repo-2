<script setup lang="ts">
/**
 * Doctor teleop 메인 뷰 — three.js 캔버스 + URDF + state WS 구독 (시각화 전용).
 *
 * 본 뷰는 read-only viewer:
 *   - 입력 X — 마우스로 로봇 움직일 수단 없음
 *   - 로봇을 움직이려면: (1) leader arm 으로 텔레옵, 또는
 *                       (2) RViz 의 MotionPlanning 패널에서 moveit plan/execute
 *   - 실 입력 → JTC → /joint_states → control bridge → WSS state frame → 본 뷰
 *
 * URL: `/doctor/teleop?eduping_id=ed-01`
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { createDoctorScene, type DoctorScene } from './teleop3d/DoctorScene';
import {
  applyJoints,
  loadRobot,
  splitBimanual,
  type LoadedArm,
} from './teleop3d/ArmUrdf';
import { createPointCloudLayer, type PointCloudLayer } from './teleop3d/PointCloud';
import { useDoctorTeleopWS } from './useDoctorTeleopWS';
import { useTelehealthWebRTC } from './useTelehealthWebRTC';
import type { StateFrame } from './pose_codec';

const route = useRoute();
const edupingId = (route.query.eduping_id as string) || 'ed-01';

// 청진기 압전(FSR) 값이 이 값을 넘으면 = 청진기가 닿음 → 심박 파형 표시.
const FSR_HEARTBEAT_THRESHOLD = 200;

const canvasRef = ref<HTMLCanvasElement | null>(null);
const remoteVideoRef = ref<HTMLVideoElement | null>(null);
const selfVideoRef = ref<HTMLVideoElement | null>(null);
const ecgCanvasRef = ref<HTMLCanvasElement | null>(null);
const wsStatus = ref<'connecting' | 'open' | 'closed'>('connecting');
const armsReady = ref(false);
const teleopActive = ref(false);
const fsrRaw = ref<number | null>(null);
const heartbeatActive = ref(false);

// ── 심박(ECG) 파형 스트립 ────────────────────────────────────────────
// 청진기 미접촉 시: 점선 평탄선("---"). 접촉(FSR > threshold) 시: 스크롤하는
// 심전도 모양 파형. 데이터는 합성(샘플 캡처가 아님) — 닿았다는 신호의 시각화.
const ECG_LEN = 360;          // 링버퍼 길이 (≈ 2초 윈도우)
const ECG_RATE = 180;         // 초당 샘플 수 (스크롤 속도)
const ecgBuf = new Float32Array(ECG_LEN);
let ecgHead = 0;
let heartClock = 0;           // 접촉 중일 때만 진행하는 심박 위상 시계 (초)
let ecgCarry = 0;             // 프레임 간 잔여 샘플 누적
let ecgLastT = 0;

// 한 박동 위상 p∈[0,1) → 진폭. P-Q-R-S-T 가우시안 합 (전형적 ECG 모양).
function ecgWave(t: number): number {
  const period = 0.7;         // ≈ 86 bpm
  let p = (t % period) / period;
  if (p < 0) p += 1;
  const g = (c: number, a: number, w: number): number =>
    a * Math.exp(-((p - c) ** 2) / (2 * w * w));
  return (
    g(0.18, 0.12, 0.035) +    // P
    g(0.33, -0.11, 0.012) +   // Q
    g(0.37, 1.0, 0.018) +     // R (큰 스파이크)
    g(0.41, -0.30, 0.013) +   // S
    g(0.62, 0.22, 0.045)      // T
  );
}

function sizeEcgCanvas(): void {
  const cv = ecgCanvasRef.value;
  if (!cv) return;
  const dpr = window.devicePixelRatio || 1;
  const rect = cv.getBoundingClientRect();
  cv.width = Math.max(1, Math.round(rect.width * dpr));
  cv.height = Math.max(1, Math.round(rect.height * dpr));
}

function drawEcg(now: number): void {
  const cv = ecgCanvasRef.value;
  if (!cv) return;
  const ctx = cv.getContext('2d');
  if (!ctx) return;
  const dpr = window.devicePixelRatio || 1;
  const w = cv.width / dpr;
  const h = cv.height / dpr;

  // 경과 시간만큼 새 샘플 push (프레임율과 무관한 일정 스크롤 속도).
  if (ecgLastT === 0) ecgLastT = now;
  let dt = (now - ecgLastT) / 1000;
  ecgLastT = now;
  if (dt > 0.1) dt = 0.1;     // 탭 비활성 등으로 인한 큰 점프 클램프
  const active = heartbeatActive.value;
  ecgCarry += ECG_RATE * dt;
  let n = Math.floor(ecgCarry);
  ecgCarry -= n;
  if (n > ECG_LEN) n = ECG_LEN;
  const dtPerSample = 1 / ECG_RATE;
  for (let i = 0; i < n; i++) {
    let amp = 0;
    if (active) {
      heartClock += dtPerSample;
      amp = ecgWave(heartClock);
    }
    ecgBuf[ecgHead] = amp;
    ecgHead = (ecgHead + 1) % ECG_LEN;
  }

  // 렌더.
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const baseY = h * 0.66;
  const scaleY = h * 0.5;
  ctx.lineWidth = 1.7;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  if (active) {
    ctx.strokeStyle = '#3ddc84';
    ctx.setLineDash([]);
    ctx.shadowColor = 'rgba(61,220,132,0.6)';
    ctx.shadowBlur = 6;
  } else {
    ctx.strokeStyle = 'rgba(140,160,170,0.75)';
    ctx.setLineDash([6, 6]);   // 대기 상태 → 점선 "---"
    ctx.shadowBlur = 0;
  }
  ctx.beginPath();
  for (let i = 0; i < ECG_LEN; i++) {
    const idx = (ecgHead + i) % ECG_LEN;
    const x = (i / (ECG_LEN - 1)) * w;
    const y = baseY - ecgBuf[idx] * scaleY;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.shadowBlur = 0;
}

// WebRTC — 의사 cam+mic 송신 + EduPing D435 RGB + mic 수신.
let localStream: MediaStream | null = null;
const telehealth = useTelehealthWebRTC({
  role: 'doctor',
  acquireLocalStream: async () => {
    try {
      localStream = await navigator.mediaDevices.getUserMedia({
        // 의사 송신 화질 — 320×240 은 eduping 쪽에서 흐릿. 720p ideal (카메라 한계 시 자동 하향).
        video: {
          width: { ideal: 1280 },
          height: { ideal: 720 },
          frameRate: { ideal: 30 },
        },
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      // self-PIP 에 attach.
      if (selfVideoRef.value) {
        selfVideoRef.value.srcObject = localStream;
        try { await selfVideoRef.value.play(); } catch { /* ignore */ }
      }
      return localStream;
    } catch (e) {
      console.error('[doctor-teleop] getUserMedia failed', e);
      return null;
    }
  },
});

let scene: DoctorScene | null = null;
let armLeft: LoadedArm | null = null;
let armRight: LoadedArm | null = null;
let raf = 0;
let teleop: ReturnType<typeof useDoctorTeleopWS> | null = null;
let statusTimer = 0;
let pointcloudLayer: PointCloudLayer | null = null;
let pointcloudWs: WebSocket | null = null;
let pointcloudBackoff = 1000;
let pointcloudReconnect: number | null = null;
let pointcloudStopped = false;

function connectPointCloud(): void {
  if (pointcloudStopped) return;
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${proto}//${location.host}/ws/doctor/pointcloud?role=consumer`;
  const ws = new WebSocket(url);
  ws.binaryType = 'arraybuffer';
  pointcloudWs = ws;
  ws.onopen = () => { pointcloudBackoff = 1000; };
  ws.onclose = () => { schedulePointCloudReconnect(); };
  ws.onerror = () => { /* onclose follows */ };
  ws.onmessage = (ev) => {
    if (!(ev.data instanceof ArrayBuffer) || !pointcloudLayer) return;
    pointcloudLayer.updateFromFrame(ev.data);
  };
}

function schedulePointCloudReconnect(): void {
  if (pointcloudStopped || pointcloudReconnect !== null) return;
  pointcloudReconnect = window.setTimeout(() => {
    pointcloudReconnect = null;
    pointcloudBackoff = Math.min(pointcloudBackoff * 2, 30000);
    connectPointCloud();
  }, pointcloudBackoff) as unknown as number;
}

function onState(state: StateFrame): void {
  if (armLeft) applyJoints(armLeft, state.left.joints, state.left.gripper);
  if (armRight) applyJoints(armRight, state.right.joints, state.right.gripper);
}

onMounted(async () => {
  if (!canvasRef.value) return;
  scene = createDoctorScene(canvasRef.value);

  // URDF — package URI 는 urdf-loader 의 packages map 으로 풀어준다.
  // 실패해도 빈 scene 으로라도 페이지가 뜨도록 try/catch.
  try {
    const robot = await loadRobot('/openarm/openarm_bimanual.urdf', {
      openarm_description: '/openarm',
    });
    const split = splitBimanual(robot);
    armLeft = split.left;
    armRight = split.right;
    scene.scene.add(robot);
    armsReady.value = true;
  } catch (e) {
    console.warn('[doctor-teleop] URDF load failed — empty scene', e);
  }

  teleop = useDoctorTeleopWS({
    edupingId,
    onState,
    onEvent: (evt) => {
      if (evt.type === 'fsr' && typeof evt.raw === 'number') {
        fsrRaw.value = evt.raw;
        heartbeatActive.value = evt.raw > FSR_HEARTBEAT_THRESHOLD;
        return;
      }
      console.info('[doctor-teleop] event', evt);
    },
  });

  // D435 pointcloud layer — control-service 가 1m 필터 + decimate 후 WS push.
  pointcloudLayer = createPointCloudLayer();
  scene.scene.add(pointcloudLayer.mesh);
  connectPointCloud();

  // WebRTC 화상통화 시작 — getUserMedia + signaling.
  void telehealth.start();

  const sync = (): void => { wsStatus.value = teleop!.status.value; };
  sync();
  statusTimer = window.setInterval(sync, 250);

  sizeEcgCanvas();
  window.addEventListener('resize', sizeEcgCanvas);

  const tick = (now: number): void => {
    raf = requestAnimationFrame(tick);
    scene!.controls.update();
    scene!.renderer.render(scene!.scene, scene!.camera);
    drawEcg(now);
  };
  raf = requestAnimationFrame(tick);
});

onBeforeUnmount(() => {
  cancelAnimationFrame(raf);
  if (statusTimer) window.clearInterval(statusTimer);
  window.removeEventListener('resize', sizeEcgCanvas);
  pointcloudStopped = true;
  if (pointcloudReconnect !== null) { window.clearTimeout(pointcloudReconnect); pointcloudReconnect = null; }
  if (pointcloudWs) { try { pointcloudWs.close(); } catch { /* ignore */ } pointcloudWs = null; }
  pointcloudLayer?.dispose();
  telehealth.stop();
  if (teleop && teleopActive.value) {
    teleop.sendEvent({ type: 'teleop', action: 'stop' });
  }
  teleop?.close();
  scene?.dispose();
});

// remoteStream 변화 시 video element 에 attach.
watch(telehealth.remoteStream, (s) => {
  if (remoteVideoRef.value && s) {
    remoteVideoRef.value.srcObject = s;
    void remoteVideoRef.value.play().catch(() => {});
  }
});

function toggleTeleop(): void {
  if (!teleop) return;
  const next = !teleopActive.value;
  teleop.sendEvent({ type: 'teleop', action: next ? 'start' : 'stop' });
  teleopActive.value = next;
}
</script>

<template>
  <div class="doctor-teleop">
    <header>
      <button class="back" @click="$router.back()">← 종료</button>
      <span class="title">{{ edupingId }} · 진찰 중</span>
      <span class="spacer" />
      <button class="teleop" :data-active="teleopActive" :disabled="wsStatus !== 'open'" @click="toggleTeleop">
        {{ teleopActive ? '■ Telehealth 정지' : '▶ Telehealth 시작' }}
      </button>
      <span class="status" :data-state="wsStatus">WS: {{ wsStatus }}</span>
    </header>
    <div class="split">
      <!-- 좌측 절반: three.js 시뮬레이션 -->
      <div class="pane sim-pane">
        <canvas ref="canvasRef" class="viewport" />
        <span class="pane-label">시뮬레이션</span>
        <div class="stetho-panel">
          <div class="stetho-fsr">
            <span class="fsr-title">청진기 FSR</span>
            <span class="fsr-val">{{ fsrRaw ?? '--' }}</span>
          </div>
          <div class="ecg-head">
            <span class="ecg-heart" :data-beating="heartbeatActive">♥</span>
            <span class="ecg-label">심박</span>
            <span class="ecg-state" :data-active="heartbeatActive">
              {{ heartbeatActive ? '측정 중' : '청진기 대기' }}
            </span>
          </div>
          <canvas ref="ecgCanvasRef" class="ecg-canvas" />
        </div>
      </div>
      <!-- 우측 절반: EduPing 환경 카메라 (WebRTC remote stream — D435 RGB + 로봇 mic) -->
      <div class="pane robotcam-pane">
        <video ref="remoteVideoRef" class="viewport" autoplay playsinline />
        <span class="pane-label">EduPing 카메라 ({{ telehealth.status.value }})</span>
        <div class="self-pip-wrap">
          <video ref="selfVideoRef" class="self-pip" autoplay muted playsinline />
        </div>
      </div>
    </div>
    <footer>
      <span>read-only viewer — 로봇 조작: leader arm 또는 RViz MotionPlanning</span>
      <span class="spacer" />
      <span v-if="!armsReady" class="warn">URDF 미로드 — 콘솔 확인</span>
    </footer>
  </div>
</template>

<style scoped>
.doctor-teleop {
  display: grid;
  grid-template-rows: 40px 1fr 32px;
  height: 100dvh;
  max-height: 100dvh;
  overflow: hidden;
}
.split {
  display: grid;
  grid-template-columns: 1fr 1fr;
  width: 100%;
  height: 100%;
  min-height: 0;
  gap: 1px;
  background: #000;
}
.pane { position: relative; width: 100%; height: 100%; min-height: 0; overflow: hidden; background: #0d0e10; }
.viewport { width: 100%; height: 100%; display: block; object-fit: contain; }
.robotcam-pane .viewport { background: #000; }
.self-pip-wrap {
  position: absolute;
  bottom: 12px;
  right: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-end;
}
.cam-select {
  font-size: 11px;
  padding: 3px 6px;
  background: rgba(0, 0, 0, 0.75);
  color: #fff;
  border: 1px solid #444;
  border-radius: 4px;
  width: 180px;
  box-sizing: border-box;
}
.pane-label {
  position: absolute;
  top: 10px;
  left: 12px;
  font-size: 11px;
  letter-spacing: 0.5px;
  color: #cfd6dd;
  background: rgba(0,0,0,0.55);
  padding: 3px 8px;
  border-radius: 12px;
}
.self-pip {
  width: 180px;
  height: 135px;
  background: #000;
  border: 2px solid #2bd9ff;
  border-radius: 6px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.5);
  display: block;
}
header, footer {
  background: #1b1e22;
  color: #eaeaea;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 12px;
  font-size: 13px;
}
.back {
  background: transparent;
  color: #eaeaea;
  border: 1px solid #3a3f44;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
}
.spacer { flex: 1; }
.status[data-state="open"] { color: #6fcf97; }
.status[data-state="closed"] { color: #eb5757; }
.warn { color: #f2c94c; }
.teleop {
  background: #2bd97a;
  color: #1b1e22;
  border: none;
  padding: 6px 14px;
  border-radius: 4px;
  cursor: pointer;
  font-weight: 600;
}
.teleop[data-active="true"] { background: #eb5757; color: #fff; }
.teleop:disabled { opacity: 0.4; cursor: not-allowed; }
.stetho-panel {
  position: absolute;
  top: 10px;
  left: 10px;
  z-index: 10;
  width: 360px;
  box-sizing: border-box;
  padding: 12px 14px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  font-variant-numeric: tabular-nums;
  pointer-events: auto;
}
.stetho-fsr {
  display: flex;
  align-items: center;
  gap: 10px;
}
.fsr-title { font-size: 13px; opacity: 0.8; }
.fsr-val { font-size: 30px; font-weight: 700; color: #4fd1c5; min-width: 48px; }
.ecg-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  margin-bottom: 4px;
}
.ecg-heart { font-size: 17px; line-height: 1; color: #8aa0aa; }
.ecg-heart[data-beating="true"] {
  color: #ff5b6e;
  animation: ecg-beat 0.7s ease-in-out infinite;
}
.ecg-label { font-size: 13px; opacity: 0.85; }
.ecg-state { margin-left: auto; font-size: 12px; opacity: 0.8; }
.ecg-state[data-active="true"] { color: #3ddc84; opacity: 1; }
.ecg-canvas { width: 100%; height: 96px; display: block; }
@keyframes ecg-beat {
  0%, 100% { transform: scale(1); }
  15% { transform: scale(1.35); }
  30% { transform: scale(1); }
}
</style>
