<script setup lang="ts">
/**
 * Dual-robot OpenArm viewer in a SINGLE three.js scene.
 *
 * Two URDF instances loaded into one scene at ±X offset, rendered through one
 * renderer with one animation loop and one OrbitControls. Half the WebGL
 * setup of running two `OpenarmViewer` instances, which is the cheap fix for
 * the comparison popup lag.
 *
 * Receives two independent joint snapshots (`snapBefore` / `snapAfter`) and
 * applies each to its corresponding robot instance every frame.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import URDFLoader from 'urdf-loader';
import type { JointSnapshot as StreamJointSnapshot } from '@/eduping/useDanceStream';

const props = defineProps<{
  snapBefore: StreamJointSnapshot | null;
  snapAfter: StreamJointSnapshot | null;
}>();

const containerRef = ref<HTMLDivElement | null>(null);
const status = ref<'loading' | 'ready' | 'error'>('loading');
const errorMsg = ref('');

let renderer: THREE.WebGLRenderer | null = null;
let scene: THREE.Scene | null = null;
let camera: THREE.PerspectiveCamera | null = null;
let controls: OrbitControls | null = null;
let robotBefore: any = null;
let robotAfter: any = null;
let animationId = 0;
let resizeObserver: ResizeObserver | null = null;
let loadedCount = 0;

const ROBOT_X_OFFSET = 0.85;
const VIEW_TARGET = new THREE.Vector3(0.0, 0.4, 0.0);
const CAMERA_POSITION = new THREE.Vector3(0.0, 1.5, 3.2);

function setupScene(width: number, height: number): void {
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0xeaf3fa);

  camera = new THREE.PerspectiveCamera(45, width / height, 0.01, 100);
  camera.position.copy(CAMERA_POSITION);
  camera.lookAt(VIEW_TARGET);

  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(width, height);
  containerRef.value!.appendChild(renderer.domElement);

  scene.add(new THREE.AmbientLight(0xffffff, 0.65));
  const dir = new THREE.DirectionalLight(0xffffff, 0.85);
  dir.position.set(1, 2, 1);
  scene.add(dir);

  const grid = new THREE.GridHelper(4.0, 40, 0x99b8c9, 0xcbd9e2);
  grid.position.y = -0.001;
  scene.add(grid);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.target.copy(VIEW_TARGET);
  controls.enableDamping = true;
  controls.dampingFactor = 0.12;
  controls.minDistance = 0.4;
  controls.maxDistance = 6.0;
  controls.update();
}

function loadOneRobot(xOffset: number, onLoaded: (r: any) => void): void {
  const loader = new URDFLoader();
  loader.packages = { openarm_description: '/urdf/openarm_v10' };
  loader.load(
    '/urdf/openarm_v10/openarm.urdf',
    (loaded: any) => {
      loaded.rotation.x = -Math.PI / 2;
      const wrapper = new THREE.Group();
      wrapper.add(loaded);
      wrapper.position.x = xOffset;
      scene!.add(wrapper);
      onLoaded(loaded);
      loadedCount += 1;
      if (loadedCount === 2) status.value = 'ready';
    },
    undefined,
    (err: unknown) => {
      console.error('[OpenarmDualViewer] URDF load failed', err);
      status.value = 'error';
      errorMsg.value = 'URDF 로드 실패';
    },
  );
}

function loadUrdf(): void {
  loadOneRobot(-ROBOT_X_OFFSET, (r) => { robotBefore = r; });
  loadOneRobot(+ROBOT_X_OFFSET, (r) => { robotAfter = r; });
}

function applySnap(robot: any, snap: StreamJointSnapshot | null): void {
  if (!robot || !snap) return;
  for (let i = 0; i < snap.jointNames.length; i++) {
    try {
      robot.setJointValue(snap.jointNames[i], snap.positions[i]);
    } catch {
      /* unknown joint — silently skip */
    }
  }
}

function startAnimation(): void {
  const RENDER_INTERVAL_MS = 33; // 30 FPS cap — matches the source viewer
  let lastRenderMs = 0;
  const tick = (nowMs: number) => {
    animationId = requestAnimationFrame(tick);
    if (nowMs - lastRenderMs < RENDER_INTERVAL_MS) return;
    lastRenderMs = nowMs;
    applySnap(robotBefore, props.snapBefore);
    applySnap(robotAfter, props.snapAfter);
    controls?.update();
    if (renderer && scene && camera) renderer.render(scene, camera);
  };
  animationId = requestAnimationFrame(tick);
}

function setupResize(): void {
  if (!containerRef.value || !camera || !renderer) return;
  resizeObserver = new ResizeObserver(() => {
    if (!containerRef.value || !camera || !renderer) return;
    const w = containerRef.value.clientWidth;
    const h = containerRef.value.clientHeight;
    if (w === 0 || h === 0) return;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  });
  resizeObserver.observe(containerRef.value);
}

onMounted(() => {
  if (!containerRef.value) return;
  const w = containerRef.value.clientWidth || 1280;
  const h = containerRef.value.clientHeight || 640;
  setupScene(w, h);
  loadUrdf();
  startAnimation();
  setupResize();
});

onBeforeUnmount(() => {
  if (animationId) cancelAnimationFrame(animationId);
  if (resizeObserver) resizeObserver.disconnect();
  if (renderer) {
    renderer.dispose();
    const dom = renderer.domElement;
    if (dom.parentElement) dom.parentElement.removeChild(dom);
  }
  scene = null;
  camera = null;
  controls = null;
  robotBefore = null;
  robotAfter = null;
  renderer = null;
});
</script>

<template>
  <div ref="containerRef" class="dual-viewer-wrap">
    <div v-if="status === 'loading'" class="overlay">URDF 로드 중…</div>
    <div v-else-if="status === 'error'" class="overlay error">{{ errorMsg }}</div>
    <div class="side-label side-label-before">분석 전 (원본 한계)</div>
    <div class="side-label side-label-after">분석 후 (안전 한계)</div>
  </div>
</template>

<style scoped>
.dual-viewer-wrap {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
}
.dual-viewer-wrap :deep(canvas) {
  display: block;
  width: 100%;
  height: 100%;
}
.overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(15, 23, 42, 0.55);
  color: white;
  font-weight: 700;
}
.overlay.error {
  color: #fecaca;
}
.side-label {
  position: absolute;
  top: 12px;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 700;
  color: white;
  pointer-events: none;
}
.side-label-before {
  left: 18px;
  background: #b91c1c;
}
.side-label-after {
  right: 18px;
  background: #047857;
}
</style>
