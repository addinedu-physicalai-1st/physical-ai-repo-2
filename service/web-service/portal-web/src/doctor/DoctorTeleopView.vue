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

const canvasRef = ref<HTMLCanvasElement | null>(null);
const remoteVideoRef = ref<HTMLVideoElement | null>(null);
const selfVideoRef = ref<HTMLVideoElement | null>(null);
const wsStatus = ref<'connecting' | 'open' | 'closed'>('connecting');
const armsReady = ref(false);
const teleopActive = ref(false);
const fsrRaw = ref<number | null>(null);
const fsrPeak = ref<number | null>(null);
function resetFsrPeak(): void { fsrPeak.value = fsrRaw.value; }

// WebRTC — 의사 cam+mic 송신 + EduPing D435 RGB + mic 수신.
let localStream: MediaStream | null = null;
const telehealth = useTelehealthWebRTC({
  role: 'doctor',
  acquireLocalStream: async () => {
    try {
      localStream = await navigator.mediaDevices.getUserMedia({
        video: { width: 320, height: 240 },
        audio: true,
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
        if (fsrPeak.value === null || evt.raw > fsrPeak.value) fsrPeak.value = evt.raw;
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

  const tick = (): void => {
    raf = requestAnimationFrame(tick);
    scene!.controls.update();
    scene!.renderer.render(scene!.scene, scene!.camera);
  };
  tick();
});

onBeforeUnmount(() => {
  cancelAnimationFrame(raf);
  if (statusTimer) window.clearInterval(statusTimer);
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
        <div class="fsr-overlay">
          <span class="fsr-title">청진기 FSR</span>
          <span class="fsr-val">{{ fsrRaw ?? '--' }}</span>
          <span class="fsr-peak">peak {{ fsrPeak ?? '--' }}</span>
          <button class="fsr-reset" @click="resetFsrPeak">리셋</button>
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
.fsr-overlay {
  position: absolute;
  top: 10px;
  left: 10px;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  font-variant-numeric: tabular-nums;
  pointer-events: auto;
}
.fsr-title { font-size: 12px; opacity: 0.8; }
.fsr-val { font-size: 28px; font-weight: 700; color: #4fd1c5; min-width: 56px; }
.fsr-peak { font-size: 13px; opacity: 0.85; }
.fsr-reset { font-size: 11px; cursor: pointer; padding: 2px 8px; }
</style>
