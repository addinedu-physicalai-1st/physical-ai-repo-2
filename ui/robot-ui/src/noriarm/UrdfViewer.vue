<script setup lang="ts">
/**
 * OMX-F URDF 를 three.js 로 그리고, Control Server 의 SSE
 * (`/api/noriarm/joint-states/stream`) 로 받은 joint 값을 실시간 반영한다.
 *
 * - URDF / STL 은 `public/urdf/omx_f/` 에 정적 호스팅 (URDFLoader 의 packages 매핑으로
 *   `package://open_manipulator_description/...` 를 그쪽으로 리다이렉트).
 * - mock 모드 등으로 SSE 가 안 오면 그냥 default pose 정적 표시.
 * - 컴포넌트 unmount 시 EventSource / 애니메이션 / three.js 리소스 정리.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import URDFLoader from 'urdf-loader';

const containerRef = ref<HTMLDivElement | null>(null);
const status = ref<'loading' | 'ready' | 'error'>('loading');
const errorMsg = ref('');

let renderer: THREE.WebGLRenderer | null = null;
let scene: THREE.Scene | null = null;
let camera: THREE.PerspectiveCamera | null = null;
let controls: OrbitControls | null = null;
let robot: any = null;
let animationId = 0;
let eventSource: EventSource | null = null;
let resizeObserver: ResizeObserver | null = null;

// 디폴트 뷰 — 위에서 거의 수직 내려다봄 (사용자가 OrbitControls 로 미세조정 가능).
const VIEW_TARGET = new THREE.Vector3(0.135, 0.199, -0.015);
const CAMERA_POSITION = new THREE.Vector3(0.12, 0.933, -0.015);

interface JointStateMessage {
  name: string[];
  position: number[];
  velocity?: number[];
}

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

  // 바닥 그리드 — Y-up 기준 XZ 평면.
  const grid = new THREE.GridHelper(1.2, 24, 0x99b8c9, 0xcbd9e2);
  grid.position.y = -0.001; // z-fight 방지
  scene.add(grid);

  // 마우스로 회전·줌·팬. damping 으로 부드럽게.
  controls = new OrbitControls(camera, renderer.domElement);
  controls.target.copy(VIEW_TARGET);
  controls.enableDamping = true;
  controls.dampingFactor = 0.12;
  controls.minDistance = 0.2;
  controls.maxDistance = 2.0;
  controls.update();
}

/**
 * 로봇 앞 바닥에 O/X 안내판(가로 25 cm × 세로 15 cm × 높이 1 cm)을 배치한다. 윗면을 절반으로
 * 나누어 왼쪽 O / 오른쪽 X 표시 — 시뮬에서 trajectory 가 어느 답을 가리키는지 시각적으로
 * 식별하기 위함. URDF 와 무관한 정적 데코라 scene 에 직접 추가한다.
 */
function addAnswerBoard(): void {
  if (!scene) return;
  // 축 매핑 (URDF 가 rotation.x = -π/2 로 회전된 후 기준):
  //   월드 +X = 로봇 정면, 월드 -Z = 로봇 왼쪽 (ROS +Y), 월드 +Z = 로봇 오른쪽.
  // → 보드 장축(25 cm) 을 월드 Z(좌우) 로, 단축(15 cm) 을 월드 X(앞뒤) 로.
  const FORWARD = 0.15; // X 방향 (로봇 앞뒤)
  const SIDE = 0.25;    // Z 방향 (로봇 좌우)
  const H = 0.01;       // Y (높이)

  // BoxGeometry +Y face UV 규칙:
  //   캔버스 top(cy=0)    → 월드 -Z = 로봇 왼쪽  ⇒ 여기에 O 그림.
  //   캔버스 bottom(cy=H) → 월드 +Z = 로봇 오른쪽 ⇒ 여기에 X 그림.
  const canvas = document.createElement('canvas');
  canvas.width = 384;
  canvas.height = Math.round(canvas.width * (SIDE / FORWARD)); // 640
  const ctx = canvas.getContext('2d')!;
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = '#1f3a4d';
  ctx.lineWidth = 6;
  ctx.beginPath();
  ctx.moveTo(0, canvas.height / 2);
  ctx.lineTo(canvas.width, canvas.height / 2);
  ctx.stroke();
  ctx.font = 'bold 260px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  // 글씨를 90° 회전 — 카메라(위에서 내려다 본) 시점에서 정자체로 보이게 하기 위함.
  const drawRotated = (text: string, cx: number, cy: number, color: string) => {
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(Math.PI / 2);
    ctx.fillStyle = color;
    ctx.fillText(text, 0, 0);
    ctx.restore();
  };
  drawRotated('O', canvas.width / 2, canvas.height * 0.25, '#2d8b57');
  drawRotated('X', canvas.width / 2, canvas.height * 0.75, '#c14545');

  const topTex = new THREE.CanvasTexture(canvas);
  topTex.colorSpace = THREE.SRGBColorSpace;
  topTex.anisotropy = 4;

  const sideMat = new THREE.MeshStandardMaterial({ color: 0xf2f2f2 });
  const topMat = new THREE.MeshStandardMaterial({ map: topTex });
  // BoxGeometry face 순서: +X, -X, +Y(top), -Y, +Z, -Z
  const board = new THREE.Mesh(
    new THREE.BoxGeometry(FORWARD, H, SIDE),
    [sideMat, sideMat, topMat, sideMat, sideMat, sideMat],
  );
  // 발판 바로 앞: OMX-F base footprint 절반(~0.035 m) 보다 살짝 떨어진 곳에 보드 후면이 닿게.
  board.position.set(0.115, H / 2, 0);
  scene.add(board);
}

function loadUrdf(): void {
  const loader = new URDFLoader();
  loader.packages = {
    open_manipulator_description: '/urdf/omx_f',
  };
  loader.load(
    '/urdf/omx_f/omx_f.urdf',
    (loadedRobot: any) => {
      // ROS URDF 는 Z-up — three.js 의 Y-up 으로 회전.
      loadedRobot.rotation.x = -Math.PI / 2;
      scene!.add(loadedRobot);
      robot = loadedRobot;
      status.value = 'ready';
    },
    undefined,
    (err: unknown) => {
      console.error('[UrdfViewer] URDF load failed', err);
      status.value = 'error';
      errorMsg.value = 'URDF 로드 실패';
    },
  );
}

function applyJointState(msg: JointStateMessage): void {
  if (!robot) return;
  const { name, position } = msg;
  for (let i = 0; i < name.length; i++) {
    try {
      robot.setJointValue(name[i], position[i]);
    } catch {
      // 알 수 없는 joint 이름은 조용히 무시.
    }
  }
}

function openEventSource(): void {
  // 같은 origin 의 Vite proxy 가 Control Server (:8000) 으로 forward.
  eventSource = new EventSource('/api/noriarm/joint-states/stream');
  eventSource.onmessage = (e) => {
    if (!e.data) return;
    try {
      applyJointState(JSON.parse(e.data) as JointStateMessage);
    } catch (err) {
      console.warn('[UrdfViewer] SSE parse 실패', err);
    }
  };
  eventSource.onerror = () => {
    // 연결 실패는 mock 모드 / Control Server 미기동 시 자연. URDF 는 그대로 표시.
    console.info('[UrdfViewer] SSE 연결 안 됨 — static URDF 만 표시');
  };
}

function startAnimation(): void {
  const tick = () => {
    animationId = requestAnimationFrame(tick);
    controls?.update(); // damping 활성 시 매 프레임 업데이트 필요
    if (renderer && scene && camera) {
      renderer.render(scene, camera);
    }
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

onMounted(() => {
  if (!containerRef.value) return;
  const w = containerRef.value.clientWidth || 480;
  const h = containerRef.value.clientHeight || 360;
  setupScene(w, h);
  addAnswerBoard();
  loadUrdf();
  startAnimation();
  setupResize();
  openEventSource();
});

onBeforeUnmount(() => {
  cancelAnimationFrame(animationId);
  eventSource?.close();
  eventSource = null;
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
  <div class="urdf-viewer-wrap">
    <div ref="containerRef" class="urdf-viewer-canvas" />
    <div v-if="status === 'loading'" class="urdf-status">URDF 로드 중…</div>
    <div v-if="status === 'error'" class="urdf-status urdf-status-error">{{ errorMsg }}</div>
  </div>
</template>

<style scoped>
.urdf-viewer-wrap {
  position: relative;
  width: 100%;
  height: 100%;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: inset 0 0 0 1px rgba(40, 110, 160, 0.15);
}
.urdf-viewer-canvas {
  width: 100%;
  height: 100%;
}
.urdf-status {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  color: #5b7a8c;
  pointer-events: none;
}
.urdf-status-error {
  color: #c14545;
}
</style>
