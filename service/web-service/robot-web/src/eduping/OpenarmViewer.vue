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
import type { Object3D } from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import URDFLoader from 'urdf-loader';
import { useEdupingStateWs, type JointSnapshot } from '@/composables/useEdupingStateWs';
import type { JointSnapshot as StreamJointSnapshot } from './useDanceStream';
import Icon from '@/common/Icon.vue';
import {
  useDepthCloudInScene,
  type HandBbox,
  type UseDepthCloudInScene,
} from './useDepthCloudInScene';
import {
  useDepthVoxelInScene,
  type UseDepthVoxelInScene,
} from './useDepthVoxelInScene';
import type { UseDepthStream } from './useDepthStream';

interface CameraSyncState {
  position: [number, number, number];
  target: [number, number, number];
}

const props = withDefaults(
  defineProps<{
    source?: 'leader' | 'follower';
    externalSnapshot?: StreamJointSnapshot | null;
    /** 로봇을 월드 Y축 기준으로 추가 회전 (degrees, CW from top-down = negative).
     * 무궁화 게임에서 카메라 정면을 향하도록 -45 사용. */
    extraYawDeg?: number;
    /** Admin highlight — joint 이름 (예: 'openarm_left_joint1') 또는 null.
     * 호출 시 그 joint 가 움직이는 link 의 mesh 들을 emissive 빨간색으로 swap. */
    highlightedJoint?: string | null;
    /** Bi-directional camera sync — OrbitControls 변경 시 emit, prop 변경 시 적용.
     * 부모가 두 viewer 에 같은 ref 를 v-model:cameraSync 로 묶으면 양쪽이 동기화. */
    cameraSync?: CameraSyncState | null;
    /** true 이면 cameraSync v-model 동기화 활성 (compare 팝업 등). */
    linkCamera?: boolean;
    /** QWebEngine compare 등 — 낮은 DPR·FPS 로 GPU 부하 감소. */
    renderLite?: boolean;
    /** D435 라이브 포인트 클라우드 합성 — 뎁스카메라 뷰 모드에서만 true. */
    showDepthCloud?: boolean;
    /** 부모가 만든 depth WS 인스턴스를 공유 — DepthViewer 가 HUD/추적용으로 한 개,
     *  cloud 용으로 별도 WS 안 띄우게. */
    depthStream?: UseDepthStream | null;
    depthPointSize?: number;
    /** Cloud decimation stride (N px 마다 1 점). 2 = 점 1/4 = ~4배 가벼움. 기본 1 (full). */
    depthStride?: number;
    depthCloudScale?: number;
    depthMaxM?: number;
    /** D435 FoV frustum 의 near plane (m). 기본 0.3 (D435 minZ). 더 크게 잡으면
     *  카메라 바로 앞 빈 공간 시각화 — high-five zone 을 frustum 뒤쪽으로 밀어낼 때. */
    depthFrustumNearM?: number;
    /** D435 FoV frustum 의 far plane (m). 미지정 시 depthMaxM 와 동일. 분리 옵션 —
     *  point cloud 는 멀리까지 렌더 (큰 maxDepthM) 하면서 frustum (=hand-accept 영역)
     *  만 좁게 그릴 때 사용. cloud 는 frustum 밖에서도 보이지만 hand POST 는 frustum
     *  안에서만 발사 (DepthViewer 의 HIGHFIVE_MAX_Z_M 으로 별도 게이트). */
    depthFrustumFarM?: number;
    depthColorMode?: 'rgb' | 'depth' | 'silhouette';
    /** Silhouette mode 의 z band — 사람 거리 범위 (m). default 0.5~2.5. */
    depthBandMinM?: number;
    depthBandMaxM?: number;
    /** Cloud cull 범위 (m, world XZ). 1.0 = grid 안만 렌더. 손을 옆으로 넓게 벌리면
     *  한 쪽 손이 cull 되어 silhouette 에서 안 보임 → 2.0 정도로 키워 lateral 범위 확장. */
    depthWorldBoundXZ?: number;
    /** 손 bbox (image-uv 좌표) — null 이면 전체 cloud, 값 있으면 그 안만. */
    handBbox?: HandBbox | null;
    /** Client-side voxelizer (octomap-like cube grid) 표시. moveit-ros-perception
     *  미설치 환경에서 RViz octomap 시각 효과 흉내. cloud + voxel 둘 다 켜도 됨. */
    showDepthVoxels?: boolean;
    /** Voxel 한 변 (m). default 0.05 (5cm). */
    depthVoxelSize?: number;
  }>(),
  {
    source: 'leader',
    externalSnapshot: null,
    extraYawDeg: 0,
    highlightedJoint: null,
    cameraSync: null,
    linkCamera: false,
    renderLite: false,
    showDepthCloud: false,
    depthStream: null,
    depthPointSize: 4.0,
    depthStride: 1,
    depthCloudScale: 1.0,
    depthMaxM: 3.0,
    depthFrustumNearM: 0.3,
    depthFrustumFarM: undefined,
    depthColorMode: 'rgb',
    depthBandMinM: 0.5,
    depthBandMaxM: 2.5,
    depthWorldBoundXZ: 1.0,
    handBbox: null,
    showDepthVoxels: false,
    depthVoxelSize: 0.05,
  },
);

const emit = defineEmits<{
  (e: 'update:cameraSync', value: CameraSyncState): void;
  (e: 'viewer-ready'): void;
  (e: 'viewer-mesh-progress', payload: {
    ready: number;
    total: number;
    gripperReady: number;
    gripperTotal: number;
  }): void;
  (e: 'viewer-error', message: string): void;
}>();

// Guard against feedback loops: when applying an external cameraSync we call
// `controls.update()` which synchronously fires the 'change' event; without
// this flag that 'change' would re-emit and bounce the state back through the
// parent → the other viewer → us, forever.
let _applyingCameraSync = false;
// Threshold for "did the camera actually move enough to bother emitting?" —
// floating-point dithering during damping otherwise causes a flood.
const _CAM_EPS = 1e-4;
let _lastEmittedSync: CameraSyncState | null = null;
let _cameraSyncLastEmitMs = 0;

const containerRef = ref<HTMLDivElement | null>(null);
const status = ref<'loading' | 'ready' | 'error'>('loading');
const errorMsg = ref('');

let renderer: THREE.WebGLRenderer | null = null;
let scene: THREE.Scene | null = null;
let camera: THREE.PerspectiveCamera | null = null;
let controls: OrbitControls | null = null;
let robot: any = null;
let depthCloud: UseDepthCloudInScene | null = null;
let depthVoxels: UseDepthVoxelInScene | null = null;
let animationId = 0;
let resizeObserver: ResizeObserver | null = null;
/** False until URDF + STL meshes are in GPU — blocks pose apply during compare warmup. */
let _meshesLoaded = false;
let _meshReadyPollId = 0;
let _meshStableFrames = 0;
const _MESH_STABLE_REQUIRED = 4;

// OpenArm 은 OMX-F 보다 크다. 좁은 portrait viewport (mugunghwa 게임 카드 안) 에서도
// 양팔 + 베이스 + 그리퍼 끝까지 다 보이도록 카메라를 1.6m → 2.4m 로 더 멀리.
// FOV 45° 기준, target=(0,0.4,0) 에서 거리 ~2.4m → horizontal half-angle ~22.5° →
// 화면 양옆 ~1m 의 margin 확보.
const VIEW_TARGET = new THREE.Vector3(0.0, 0.4, 0.0);
const CAMERA_POSITION = new THREE.Vector3(1.8, 1.05, 1.5);

// 백엔드와 URDF 둘 다 동일 명명 (openarm_{right|left}_joint1..7, openarm_{right|left}_finger_joint1).
// 변환 레이어 없이 setJointValue 에 그대로 전달.

// Admin highlight — simple solid-red material swap, restored on unhighlight.
// Lightweight: no postprocessing, no clones, no scale, no depth tricks. The
// highlight covers exactly the link's actual geometry (no offset issues), at
// the cost of being smaller / harder to see on tiny links — the user picked
// this lightweight version after trying outline + scale variants.
let _highlightMaterial: THREE.MeshStandardMaterial | null = null;
const _origState = new Map<THREE.Mesh, THREE.Material | THREE.Material[]>();

function _ensureHighlightMaterial(): THREE.MeshStandardMaterial {
  if (!_highlightMaterial) {
    _highlightMaterial = new THREE.MeshStandardMaterial({
      color: 0xff0033,
      emissive: 0xff2244,
      emissiveIntensity: 1.5,
      roughness: 0.4,
      metalness: 0.0,
    });
  }
  return _highlightMaterial;
}

function clearJointHighlight(): void {
  for (const [mesh, origMaterial] of _origState) {
    mesh.material = origMaterial;
  }
  _origState.clear();
}

function _highlightMesh(mesh: THREE.Mesh): void {
  if (_origState.has(mesh)) return;
  _origState.set(mesh, mesh.material);
  mesh.material = _ensureHighlightMaterial();
}

function applyJointHighlight(jointName: string): void {
  clearJointHighlight();
  if (!robot) {
    console.warn('[OpenarmViewer] highlight requested before URDF load:', jointName);
    return;
  }
  const joint = robot.joints?.[jointName];
  if (!joint) {
    const known = robot.joints ? Object.keys(robot.joints).join(', ') : '(none)';
    console.warn(
      `[OpenarmViewer] joint not found: '${jointName}'. known: ${known}`,
    );
    return;
  }
  // urdf-loader 는 URDF joint 를 Object3D 로 만들고, 그 자식으로 URDFLink (= 다음 링크)
  // 를 매단다. 그 link 안에는 또 다른 URDFJoint 가 있고, 거기 다음 link 가 매달려 chain
  // 을 이룬다. 그냥 joint.traverse 하면 chain 전체가 빨개진다 — 우리가 원하는 건
  // **이 joint 가 직접 움직이는 link 만** 빨개지는 것. nested URDFJoint 경계에서 prune.
  // 단, mimic joint (gripper_joint_2 가 gripper_joint_1 을 mimic 하듯) 은 같은
  // 메커니즘의 일부 — 함께 빨개져야 그리퍼 양쪽 jaw 가 다 보인다.
  function walkPruneAtJoints(node: any): void {
    if (node?.isMesh && node.material) {
      _highlightMesh(node);
    }
    for (const child of node?.children ?? []) {
      if (child?.isURDFJoint) continue;  // stop at the next joint
      walkPruneAtJoints(child);
    }
  }
  function highlightFromJoint(j: any): void {
    for (const child of j?.children ?? []) {
      if (child?.isURDFJoint) continue;
      walkPruneAtJoints(child);
    }
  }
  highlightFromJoint(joint);
  // urdf-loader 의 URDFJoint.mimicJoints — 이 joint 를 mimic 하는 자식 joint 들의 배열.
  // gripper 의 경우 finger_joint_2 가 finger_joint_1 을 mimic → 둘이 동시에 강조돼야
  // 양쪽 finger jaw 가 모두 빨개진다.
  const mimics = joint.mimicJoints;
  if (Array.isArray(mimics)) {
    for (const m of mimics) {
      highlightFromJoint(m);
    }
  }
}

// Debug helper — `window.listOpenarmJoints()` 로 콘솔에서 사용 가능한 joint 명 확인.
(window as any).listOpenarmJoints = (): string[] => {
  return robot?.joints ? Object.keys(robot.joints) : [];
};


// --------------------------------------------------------------------------
// Auto-find safe joint limits via collision-aware sweep.
// --------------------------------------------------------------------------
//
// For each non-fixed joint, with all other joints at zero, sweep its value
// from 0 toward urdf_upper (and 0 toward urdf_lower) in N steps, checking
// pairwise link-bounding-box intersection at each step. Stop at the first
// step where the moving link's subtree hits the body frame or the OPPOSITE
// arm. The last collision-free angle becomes safeMax (or safeMin).
//
// Limitations (documented for the caller):
//  * Other joints held at zero — interference between SIMULTANEOUSLY moving
//    joints isn't found. This is the conservative single-axis safe range.
//  * Bounding boxes are axis-aligned (world AABB). Elongated rotated links
//    can over-estimate collisions. False positives are SAFER than false
//    negatives for this use case so it's the right side to err.
//  * Stops at the first collision, doesn't search past it for re-safe
//    regions — assumes safe ranges are contiguous around the rest pose.

interface SafeLimitsResult {
  [jointName: string]: { min: number; max: number };
}

function _adjacencyKey(a: string, b: string): string {
  return a < b ? `${a}|${b}` : `${b}|${a}`;
}

function _buildAdjacencySet(rbot: any): Set<string> {
  // Pairs of LINK names that are directly connected by a URDF joint always
  // touch at the joint — exclude them from collision detection.
  const adj = new Set<string>();
  if (!rbot?.joints) return adj;
  for (const joint of Object.values(rbot.joints) as any[]) {
    // Walk up to find the enclosing URDFLink (the joint's parent in the
    // URDF graph). Three.js parent traversal.
    let p = joint.parent;
    while (p && !p.isURDFLink) p = p.parent;
    // Walk down children to find the first URDFLink (the joint's child).
    let childLink: any = null;
    for (const child of joint.children ?? []) {
      if (child?.isURDFLink) {
        childLink = child;
        break;
      }
    }
    if (p?.name && childLink?.name) {
      adj.add(_adjacencyKey(p.name, childLink.name));
    }
  }
  return adj;
}

function _collidingPairs(rbot: any, adjacent: Set<string>): Array<[string, string]> {
  const linkBoxes: Array<[string, THREE.Box3]> = [];
  for (const [name, link] of Object.entries(rbot.links) as any[]) {
    const box = new THREE.Box3().setFromObject(link);
    // Skip links that have no actual geometry (degenerate empty boxes).
    if (box.isEmpty()) continue;
    linkBoxes.push([name, box]);
  }
  const hits: Array<[string, string]> = [];
  for (let i = 0; i < linkBoxes.length; i++) {
    for (let j = i + 1; j < linkBoxes.length; j++) {
      if (adjacent.has(_adjacencyKey(linkBoxes[i][0], linkBoxes[j][0]))) continue;
      if (linkBoxes[i][1].intersectsBox(linkBoxes[j][1])) {
        hits.push([linkBoxes[i][0], linkBoxes[j][0]]);
      }
    }
  }
  return hits;
}

// Recording scan — given a recorded routine's joint_names + frames, iterate
// every frame and check for self-collision. Track per-joint min/max observed
// across all COLLISION-FREE frames. Return those bounds as the safe limits.
//
// This is more relevant than the per-joint sweep above because it considers
// joints moving SIMULTANEOUSLY (the actual recorded motion), not one-at-a-time
// with others held at rest. Limits derived here will allow the recording to
// play through the safe parts without clipping, while still clipping any
// frames where a self-collision would occur.
(window as any).scanRecordingForSafeOpenarmLimits = (
  recording: { joint_names: string[]; frames: number[][] },
): SafeLimitsResult | null => {
  if (!robot) return null;
  if (!recording || !Array.isArray(recording.joint_names)
      || !Array.isArray(recording.frames)) {
    return null;
  }
  const startTs = performance.now();
  const adjacent = _buildAdjacencySet(robot);
  const jointNames = recording.joint_names;
  const frames = recording.frames;

  // Snapshot current pose so we can restore.
  const originalAngles: Record<string, number> = {};
  for (const [name, joint] of Object.entries(robot.joints) as [string, any][]) {
    originalAngles[name] = typeof joint.angle === 'number' ? joint.angle : 0;
  }

  // Track per-joint observed-safe range as the recording plays.
  const observed: Record<string, { min: number; max: number } | null> = {};
  for (const name of jointNames) observed[name] = null;

  let safeFrameCount = 0;
  let collisionFrameCount = 0;

  for (let fi = 0; fi < frames.length; fi++) {
    const frame = frames[fi];
    if (!Array.isArray(frame) || frame.length !== jointNames.length) continue;
    // Apply frame pose
    for (let i = 0; i < jointNames.length; i++) {
      robot.setJointValue(jointNames[i], frame[i]);
    }
    robot.updateMatrixWorld(true);
    if (_collidingPairs(robot, adjacent).length === 0) {
      safeFrameCount++;
      for (let i = 0; i < jointNames.length; i++) {
        const name = jointNames[i];
        const v = frame[i];
        const o = observed[name];
        if (o === null) {
          observed[name] = { min: v, max: v };
        } else {
          if (v < o.min) o.min = v;
          if (v > o.max) o.max = v;
        }
      }
    } else {
      collisionFrameCount++;
    }
  }

  // Restore pose.
  for (const [name, val] of Object.entries(originalAngles)) {
    robot.setJointValue(name, val);
  }
  robot.updateMatrixWorld(true);

  // Convert to result; for joints with NO safe frames fall back to URDF.
  const result: SafeLimitsResult = {};
  for (const name of jointNames) {
    const o = observed[name];
    if (o !== null) {
      result[name] = { min: o.min, max: o.max };
    } else {
      const joint = (robot.joints as any)?.[name];
      const lo = joint?.limit?.lower ?? -Math.PI;
      const hi = joint?.limit?.upper ?? Math.PI;
      result[name] = { min: lo, max: hi };
    }
  }

  const dt = Math.round(performance.now() - startTs);
  console.log(
    `[OpenarmViewer] scanRecordingForSafeOpenarmLimits: ${frames.length} frames `
    + `(${safeFrameCount} safe, ${collisionFrameCount} collision) in ${dt}ms`,
  );
  return result;
};

(window as any).autoFindSafeOpenarmLimits = (numSteps = 24): SafeLimitsResult | null => {
  if (!robot) return null;
  const startTs = performance.now();
  const adjacent = _buildAdjacencySet(robot);

  // Snapshot current pose so we can restore it after the sweep.
  const originalAngles: Record<string, number> = {};
  for (const [name, joint] of Object.entries(robot.joints) as [string, any][]) {
    originalAngles[name] = typeof joint.angle === 'number' ? joint.angle : 0;
  }

  // Reset every joint to zero — baseline for per-joint sweep.
  for (const name of Object.keys(robot.joints)) {
    robot.setJointValue(name, 0);
  }
  robot.updateMatrixWorld(true);

  const result: SafeLimitsResult = {};
  for (const [name, joint] of Object.entries(robot.joints) as [string, any][]) {
    if (!joint.limit || joint.jointType === 'fixed') continue;
    const urdfLo = joint.limit.lower;
    const urdfHi = joint.limit.upper;
    if (typeof urdfLo !== 'number' || typeof urdfHi !== 'number') continue;

    // Sweep 0 → urdfHi. Stop at first collision; safeHi = previous step.
    let safeHi = 0;
    for (let i = 1; i <= numSteps; i++) {
      const v = (urdfHi - 0) * (i / numSteps);
      robot.setJointValue(name, v);
      robot.updateMatrixWorld(true);
      if (_collidingPairs(robot, adjacent).length > 0) break;
      safeHi = v;
    }
    // Sweep 0 → urdfLo (negative direction).
    robot.setJointValue(name, 0);
    robot.updateMatrixWorld(true);
    let safeLo = 0;
    for (let i = 1; i <= numSteps; i++) {
      const v = (urdfLo - 0) * (i / numSteps);
      robot.setJointValue(name, v);
      robot.updateMatrixWorld(true);
      if (_collidingPairs(robot, adjacent).length > 0) break;
      safeLo = v;
    }
    // If both directions found a safe range, use them; else fall back to URDF.
    if (safeLo === 0 && safeHi === 0) {
      // Couldn't move at all without collision — keep URDF as-is (don't lock).
      result[name] = { min: urdfLo, max: urdfHi };
    } else {
      result[name] = { min: safeLo, max: safeHi };
    }

    // Reset for next joint's sweep.
    robot.setJointValue(name, 0);
    robot.updateMatrixWorld(true);
  }

  // Restore the pose we found the arm in.
  for (const [name, val] of Object.entries(originalAngles)) {
    robot.setJointValue(name, val);
  }
  robot.updateMatrixWorld(true);

  const dt = Math.round(performance.now() - startTs);
  console.log(`[OpenarmViewer] autoFindSafeOpenarmLimits: ${Object.keys(result).length} joints in ${dt}ms`);
  return result;
};

watch(
  () => props.highlightedJoint,
  (jn) => {
    if (jn) applyJointHighlight(jn);
    else clearJointHighlight();
  },
);

// External cameraSync prop changes (driven by sibling viewer's emit through the
// parent's ref) → apply to our camera+controls. Guarded by _applyingCameraSync
// inside _applyCameraSync so the resulting OrbitControls 'change' doesn't echo
// back. _camStateNearEqual short-circuit avoids work when the incoming state
// is what we just emitted.
watch(
  () => props.cameraSync,
  (sync) => {
    if (!props.linkCamera || !sync) return;
    if (_lastEmittedSync && _camStateNearEqual(_lastEmittedSync, sync)) return;
    _applyCameraSync(sync);
  },
);

const stateWs = useEdupingStateWs();

function setupScene(width: number, height: number): void {
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0xeaf3fa);

  camera = new THREE.PerspectiveCamera(45, width / height, 0.01, 100);
  camera.position.copy(CAMERA_POSITION);
  camera.lookAt(VIEW_TARGET);

  const lite = props.renderLite;
  // Always ask for the discrete GPU — compare mode used low-power before and
  // could force software / iGPU paths inside Qt WebEngine.
  renderer = new THREE.WebGLRenderer({
    antialias: !lite,
    powerPreference: 'high-performance',
    failIfMajorPerformanceCaveat: false,
  });
  renderer.setPixelRatio(
    lite ? 1 : Math.min(window.devicePixelRatio, 2),
  );
  renderer.setSize(width, height);
  containerRef.value!.appendChild(renderer.domElement);
  try {
    const gl = renderer.getContext();
    const ext = gl.getExtension('WEBGL_debug_renderer_info');
    if (ext) {
      (window as Window & { __webglGpu?: { vendor: string; renderer: string } }).__webglGpu = {
        vendor: String(gl.getParameter(ext.UNMASKED_VENDOR_WEBGL)),
        renderer: String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)),
      };
    }
  } catch {
    /* optional diagnostic */
  }

  scene.add(new THREE.AmbientLight(0xffffff, 0.65));
  const dir = new THREE.DirectionalLight(0xffffff, 0.85);
  dir.position.set(1, 2, 1);
  scene.add(dir);

  const grid = new THREE.GridHelper(
    2.0,
    lite ? 10 : 20,
    0x99b8c9,
    0xcbd9e2,
  );
  grid.position.y = -0.001;
  scene.add(grid);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.target.copy(VIEW_TARGET);
  controls.enableDamping = true;
  controls.dampingFactor = 0.12;
  controls.minDistance = 0.4;
  controls.maxDistance = 4.0;
  controls.update();

  // Camera sync: emit 'change' from OrbitControls → parent (when not currently
  // applying an external sync). Parent's reactive ref propagates to the other
  // viewer, where the cameraSync watch applies the new pose.
  controls.addEventListener('change', () => {
    if (_applyingCameraSync || !camera || !controls) return;
    if (!props.linkCamera) return;
    const nowMs = performance.now();
    if (nowMs - _cameraSyncLastEmitMs < 100) return;
    const next: CameraSyncState = {
      position: [camera.position.x, camera.position.y, camera.position.z],
      target: [controls.target.x, controls.target.y, controls.target.z],
    };
    if (_lastEmittedSync && _camStateNearEqual(_lastEmittedSync, next)) return;
    _lastEmittedSync = next;
    _cameraSyncLastEmitMs = nowMs;
    emit('update:cameraSync', next);
  });
}

function _camStateNearEqual(a: CameraSyncState, b: CameraSyncState): boolean {
  for (let i = 0; i < 3; i++) {
    if (Math.abs(a.position[i] - b.position[i]) > _CAM_EPS) return false;
    if (Math.abs(a.target[i] - b.target[i]) > _CAM_EPS) return false;
  }
  return true;
}

function _applyCameraSync(sync: CameraSyncState): void {
  if (!camera || !controls) return;
  _applyingCameraSync = true;
  try {
    camera.position.set(sync.position[0], sync.position[1], sync.position[2]);
    controls.target.set(sync.target[0], sync.target[1], sync.target[2]);
    controls.update();
  } finally {
    _applyingCameraSync = false;
  }
}

function urdfLinkNameForObject(obj: Object3D): string | null {
  let p: Object3D | null = obj;
  while (p) {
    if ((p as { isURDFLink?: boolean }).isURDFLink && p.name) return p.name;
    p = p.parent;
  }
  return null;
}

function isMeshGeometryReady(mesh: THREE.Mesh): boolean {
  const pos = mesh.geometry?.attributes?.position;
  if (!pos || pos.count === 0) return false;
  mesh.geometry.computeBoundingBox();
  const box = mesh.geometry.boundingBox;
  return !!(box && !box.isEmpty());
}

function isGripperLinkName(linkName: string): boolean {
  return /hand|finger/i.test(linkName);
}

/** Gripper uses hand.stl + finger.stl for collision; wait for those, not just arm links. */
function countGripperStlMeshes(root: Object3D): { required: number; ready: number } {
  let required = 0;
  let ready = 0;
  root.traverse((child) => {
    const mesh = child as THREE.Mesh;
    if (!mesh.isMesh) return;
    const linkName = urdfLinkNameForObject(mesh);
    if (!linkName || !isGripperLinkName(linkName)) return;
    const label = `${linkName}/${mesh.name}`.toLowerCase();
    const isStlCollision =
      label.includes('collision')
      || label.includes('.stl')
      || label.includes('finger.stl')
      || label.includes('hand.stl');
    if (!isStlCollision) return;
    required += 1;
    if (isMeshGeometryReady(mesh)) ready += 1;
  });
  return { required, ready };
}

/** openarm.urdf: 2× hand.stl + 4× finger.stl collision meshes. */
const MIN_GRIPPER_STL_MESHES = 6;

function gripperMeshesReady(root: Object3D): boolean {
  const stl = countGripperStlMeshes(root);
  if (stl.required > 0) {
    return stl.ready === stl.required && stl.ready >= MIN_GRIPPER_STL_MESHES;
  }
  // Fallback if loader omits "collision" in names — every mesh on hand/finger links.
  let required = 0;
  let ready = 0;
  root.traverse((child) => {
    const mesh = child as THREE.Mesh;
    if (!mesh.isMesh) return;
    const linkName = urdfLinkNameForObject(mesh);
    if (!linkName || !isGripperLinkName(linkName)) return;
    required += 1;
    if (isMeshGeometryReady(mesh)) ready += 1;
  });
  return required > 0 && ready === required;
}

function countRobotMeshes(root: Object3D): { total: number; ready: number } {
  let total = 0;
  let ready = 0;
  root.traverse((child) => {
    const mesh = child as THREE.Mesh;
    if (!mesh.isMesh) return;
    total += 1;
    if (isMeshGeometryReady(mesh)) ready += 1;
  });
  return { total, ready };
}

function robotMeshesReady(root: Object3D): boolean {
  const { total, ready } = countRobotMeshes(root);
  if (total === 0 || ready !== total) return false;
  return gripperMeshesReady(root);
}

function cancelMeshReadyPoll(): void {
  if (_meshReadyPollId !== 0) {
    cancelAnimationFrame(_meshReadyPollId);
    _meshReadyPollId = 0;
  }
}

function finishMeshLoad(): void {
  if (_meshesLoaded || !robot) return;
  _meshesLoaded = true;
  cancelMeshReadyPoll();
  status.value = 'ready';
  if (props.externalSnapshot) {
    applyExternalSnapshot(props.externalSnapshot);
  }
  emit('viewer-ready');
}

function waitForMeshesThenFinish(): void {
  if (!robot) return;
  cancelMeshReadyPoll();
  _meshStableFrames = 0;
  const deadline = performance.now() + 120_000;
  const poll = () => {
    _meshReadyPollId = 0;
    if (!robot || _meshesLoaded) return;
    const { total, ready } = countRobotMeshes(robot);
    const grip = countGripperStlMeshes(robot);
    emit('viewer-mesh-progress', {
      ready,
      total,
      gripperReady: grip.ready,
      gripperTotal: grip.required,
    });
    if (robotMeshesReady(robot)) {
      _meshStableFrames += 1;
      if (_meshStableFrames >= _MESH_STABLE_REQUIRED) {
        finishMeshLoad();
        return;
      }
    } else {
      _meshStableFrames = 0;
    }
    if (performance.now() >= deadline) {
      const msg = `STL 로드 시간 초과 (${ready}/${total})`;
      status.value = 'error';
      errorMsg.value = msg;
      emit('viewer-error', msg);
      return;
    }
    _meshReadyPollId = requestAnimationFrame(poll);
  };
  poll();
}

function loadUrdf(): void {
  _meshesLoaded = false;
  _meshStableFrames = 0;
  cancelMeshReadyPoll();
  emit('viewer-mesh-progress', {
    ready: 0, total: 0, gripperReady: 0, gripperTotal: 0,
  });

  const manager = new THREE.LoadingManager(
    () => waitForMeshesThenFinish(),
    undefined,
    (url) => {
      console.error('[OpenarmViewer] asset load failed', url);
      const msg = `URDF / STL 로드 실패: ${url}`;
      status.value = 'error';
      errorMsg.value = msg;
      emit('viewer-error', msg);
    },
  );

  const loader = new URDFLoader(manager);
  loader.packages = {
    openarm_description: '/urdf/openarm_v10',
  };
  loader.load(
    '/urdf/openarm_v10/openarm.urdf',
    (loaded: any) => {
      loaded.rotation.x = -Math.PI / 2;
      const wrapper = new THREE.Group();
      wrapper.add(loaded);
      wrapper.rotation.y = (props.extraYawDeg * Math.PI) / 180;
      scene!.add(wrapper);
      robot = loaded;
      // 뎁스카메라 뷰 모드에서만 cloud composable 마운트. URDF 의 d435_depth_optical_frame
      // link 가 부모 chain 으로 모든 좌표 변환을 처리하므로 cloud 가 robot 과 함께 움직임.
      if (props.showDepthCloud && props.depthStream && !depthCloud) {
        depthCloud = useDepthCloudInScene({
          robot,
          depthStream: props.depthStream,
          pointSize: props.depthPointSize,
          stride: props.depthStride,
          cloudScale: props.depthCloudScale,
          maxDepthM: props.depthMaxM,
          colorMode: props.depthColorMode,
          bandMinM: props.depthBandMinM,
          bandMaxM: props.depthBandMaxM,
          worldBoundXZ: props.depthWorldBoundXZ,
          // D435 FoV wireframe pyramid. far 가 별도 지정되면 cloud 의 maxDepthM 와
          // 분리 — cloud 는 멀리까지 점군 렌더, frustum (hand-accept 영역) 만 좁게.
          showFrustum: true,
          frustumNearM: props.depthFrustumNearM,
          frustumFarM: props.depthFrustumFarM,
        });
        if (props.handBbox) depthCloud.setHandBbox(props.handBbox);
      }
      // Voxel grid (octomap-like) — same depth stream, voxelized to cubes.
      // moveit-ros-perception 미설치라 /octomap_full 토픽이 없어도 시각 효과 동일.
      if (props.showDepthVoxels && props.depthStream && !depthVoxels) {
        depthVoxels = useDepthVoxelInScene({
          robot,
          depthStream: props.depthStream,
          voxelSize: props.depthVoxelSize,
          maxDepthM: props.depthMaxM,
          // D435 FoV 와이어프레임 — cloud frustum 과 동일 prop 재사용.
          showFrustum: true,
          frustumNearM: props.depthFrustumNearM,
          frustumFarM: props.depthFrustumFarM ?? props.depthMaxM,
        });
      }
      // STL loads are async — viewer-ready only after mesh poll passes.
      window.setTimeout(() => waitForMeshesThenFinish(), 50);
    },
    undefined,
    (err: unknown) => {
      console.error('[OpenarmViewer] URDF load failed', err);
      const msg = 'URDF 로드 실패';
      status.value = 'error';
      errorMsg.value = msg;
      emit('viewer-error', msg);
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

function applyExternalSnapshot(snap: StreamJointSnapshot | null): void {
  if (!robot || !snap || !_meshesLoaded) return;
  for (let i = 0; i < snap.jointNames.length; i++) {
    try {
      robot.setJointValue(snap.jointNames[i], snap.positions[i]);
    } catch {
      /* unknown joint — silently skip */
    }
  }
}

function startAnimation(): void {
  // Cap to ~30 FPS — full-rate rAF (60+ FPS) inside a QWebEngineView is heavy
  // on the host PyQt app and offers no benefit for a slowly-moving arm. 30 FPS
  // is still buttery; lab-style admin UIs don't need 60.
  const RENDER_INTERVAL_MS = props.renderLite ? 50 : 33;
  let lastRenderMs = 0;
  const tick = (nowMs: number) => {
    animationId = requestAnimationFrame(tick);
    if (nowMs - lastRenderMs < RENDER_INTERVAL_MS) return;
    lastRenderMs = nowMs;
    // externalSnapshot prop 이 있으면 dance stream 모드 — WS 무시하고 prop 값을 폴링.
    // (URDF 가 늦게 로드되어도 매 프레임 재적용되므로 watch 가 놓쳐도 복구됨.)
    // 없으면 기존 WS 채널 폴링. applyJointState 는 setJointValue idempotent — 같은 값이면 no-op.
    if (props.externalSnapshot) {
      applyExternalSnapshot(props.externalSnapshot);
    } else {
      const snap = props.source === 'follower' ? stateWs.follower.value : stateWs.leader.value;
      applyJointState(snap);
    }
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
  const w = containerRef.value.clientWidth || 480;
  const h = containerRef.value.clientHeight || 360;
  setupScene(w, h);
  loadUrdf();
  startAnimation();
  setupResize();
  // externalSnapshot prop 으로 외부에서 joint 를 주입받는 경우 WS 구독 불필요.
  if (!props.externalSnapshot) {
    stateWs.start();
  }
});

// handBbox prop 가 바뀔 때마다 depth cloud 의 bbox 필터를 갈음.
watch(
  () => props.handBbox,
  (next) => {
    depthCloud?.setHandBbox(next ?? null);
  },
);

onBeforeUnmount(() => {
  cancelMeshReadyPoll();
  _meshesLoaded = false;
  // Restore + drop highlight material singleton.
  clearJointHighlight();
  _highlightMaterial?.dispose();
  _highlightMaterial = null;
  depthCloud?.dispose();
  depthCloud = null;
  depthVoxels?.dispose();
  depthVoxels = null;
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
    <div v-if="stateWs.realActive.value" class="real-badge">
      <Icon name="robot" :size="14" />
      <span>실물 연결됨</span>
    </div>
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
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
</style>
