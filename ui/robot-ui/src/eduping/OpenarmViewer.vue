<script setup lang="ts">
/**
 * OpenArm v10 URDF 를 three.js 로 그리고, /api/eduping/state WS 로 받은 joint 값을
 * 실시간 반영. UrdfViewer (noriarm) 패턴 미러.
 *
 * - URDF / 메쉬는 `public/urdf/openarm_v10/` 정적 호스팅 + URDFLoader packages 매핑.
 * - prop `source` 로 leader / follower 선택 (기본 leader — 녹화 검수에 사용).
 * - 백엔드 joint 명 (joint_1..joint_7, gripper) → URDF 명 (openarm_joint1..7,
 *   openarm_finger_joint1) 매핑.
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import URDFLoader from 'urdf-loader';
import { useEdupingStateWs, type JointSnapshot } from '@/composables/useEdupingStateWs';

const props = withDefaults(defineProps<{ source?: 'leader' | 'follower' }>(), {
  source: 'leader',
});

const containerRef = ref<HTMLDivElement | null>(null);
const status = ref<'loading' | 'ready' | 'error'>('loading');
const errorMsg = ref('');

let renderer: THREE.WebGLRenderer | null = null;
let scene: THREE.Scene | null = null;
let camera: THREE.PerspectiveCamera | null = null;
let controls: OrbitControls | null = null;
let robot: any = null;
let animationId = 0;
let resizeObserver: ResizeObserver | null = null;

// OpenArm 은 OMX-F 보다 크다 — 카메라 거리 ~1m.
const VIEW_TARGET = new THREE.Vector3(0.0, 0.4, 0.0);
const CAMERA_POSITION = new THREE.Vector3(1.2, 0.7, 1.0);

// 백엔드와 URDF 둘 다 동일 명명 (openarm_{right|left}_joint1..7, openarm_{right|left}_finger_joint1).
// 변환 레이어 없이 setJointValue 에 그대로 전달.

const stateWs = useEdupingStateWs();

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

  const grid = new THREE.GridHelper(2.0, 20, 0x99b8c9, 0xcbd9e2);
  grid.position.y = -0.001;
  scene.add(grid);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.target.copy(VIEW_TARGET);
  controls.enableDamping = true;
  controls.dampingFactor = 0.12;
  controls.minDistance = 0.4;
  controls.maxDistance = 4.0;
  controls.update();
}

function loadUrdf(): void {
  const loader = new URDFLoader();
  loader.packages = {
    openarm_description: '/urdf/openarm_v10',
  };
  loader.load(
    '/urdf/openarm_v10/openarm.urdf',
    (loaded: any) => {
      // ROS URDF 는 Z-up — three.js Y-up 로 회전.
      loaded.rotation.x = -Math.PI / 2;
      scene!.add(loaded);
      robot = loaded;
      status.value = 'ready';
    },
    undefined,
    (err: unknown) => {
      console.error('[OpenarmViewer] URDF load failed', err);
      status.value = 'error';
      errorMsg.value = 'URDF 로드 실패';
    },
  );
}

function applyJointState(snap: JointSnapshot | null): void {
  if (!robot || !snap) return;
  const { joint_names: names, positions } = snap;
  for (let i = 0; i < names.length; i++) {
    try {
      robot.setJointValue(names[i], positions[i]);
    } catch {
      /* unknown joint — silently skip */
    }
  }
}

function startAnimation(): void {
  const tick = () => {
    animationId = requestAnimationFrame(tick);
    controls?.update();
    if (renderer && scene && camera) renderer.render(scene, camera);
  };
  tick();
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

watch(
  () => (props.source === 'follower' ? stateWs.follower.value : stateWs.leader.value),
  (snap) => applyJointState(snap),
  { deep: false },
);

onMounted(() => {
  if (!containerRef.value) return;
  const w = containerRef.value.clientWidth || 480;
  const h = containerRef.value.clientHeight || 360;
  setupScene(w, h);
  loadUrdf();
  startAnimation();
  setupResize();
  stateWs.start();
});

onBeforeUnmount(() => {
  stateWs.stop();
  cancelAnimationFrame(animationId);
  resizeObserver?.disconnect();
  resizeObserver = null;
  controls?.dispose();
  controls = null;

  if (renderer) {
    renderer.domElement.remove();
    renderer.dispose();
    renderer = null;
  }
  scene?.traverse((obj: any) => {
    if (obj.geometry?.dispose) obj.geometry.dispose();
    const mat = obj.material;
    if (mat) {
      if (Array.isArray(mat)) mat.forEach((m: any) => m.dispose?.());
      else mat.dispose?.();
    }
  });
  scene = null;
  camera = null;
  robot = null;
});
</script>

<template>
  <div class="openarm-viewer-wrap">
    <div ref="containerRef" class="openarm-viewer-canvas" />
    <div v-if="status === 'loading'" class="openarm-status">URDF 로드 중…</div>
    <div v-if="status === 'error'" class="openarm-status openarm-status-error">{{ errorMsg }}</div>
    <div class="openarm-source-badge" :class="`source-${props.source}`">
      {{ props.source === 'leader' ? '리더 (입력)' : '팔로워 (출력)' }}
      <span v-if="!stateWs.connected.value" class="dot-disconnected">●</span>
    </div>
    <div v-if="stateWs.realActive.value" class="real-badge">🤖 실물 연결됨</div>
  </div>
</template>

<style scoped>
.openarm-viewer-wrap {
  position: relative;
  width: 100%;
  height: 100%;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: inset 0 0 0 1px rgba(40, 110, 160, 0.15);
}
.openarm-viewer-canvas {
  width: 100%;
  height: 100%;
}
.openarm-status {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  color: #5b7a8c;
  pointer-events: none;
}
.openarm-status-error {
  color: #c14545;
}
.openarm-source-badge {
  position: absolute;
  top: 12px;
  left: 12px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  background: rgba(255, 255, 255, 0.85);
  color: #355569;
  user-select: none;
}
.openarm-source-badge.source-leader {
  color: #2563eb;
}
.openarm-source-badge.source-follower {
  color: #0d9488;
}
.dot-disconnected {
  margin-left: 4px;
  color: #c14545;
}
.real-badge {
  position: absolute;
  top: 10px;
  right: 10px;
  padding: 4px 10px;
  border-radius: 999px;
  background: #fef3c7;
  color: #92400e;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid #f59e0b;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}
</style>
