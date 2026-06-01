/**
 * Doctor 3D scene 스켈레톤 — three.js 셋업 (scene/camera/renderer/controls).
 * URDF / handles / depth cloud 는 별도 모듈에서 scene 에 add.
 *
 * 좌표계: ROS 관례 (Z-up). camera.up 을 (0,0,1) 로 두고 OrbitControls 가 그 기준으로
 * orbit 하도록 설정.
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

export interface DoctorScene {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  controls: OrbitControls;
  dispose(): void;
}

export function createDoctorScene(canvas: HTMLCanvasElement): DoctorScene {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x202428);

  // AxesHelper (+x red / +y green / +z blue), 30cm 길이 — base_link 위치 가늠.
  scene.add(new THREE.AxesHelper(0.3));

  // 2m × 2m 그라운드 그리드 (10cm 간격). default 는 XZ 평면이라 Z-up 좌표계로 회전.
  const grid = new THREE.GridHelper(2, 20, 0x444444, 0x222222);
  grid.rotation.x = Math.PI / 2;
  scene.add(grid);

  // ambient + key light — URDF mesh 디테일이 보이도록.
  scene.add(new THREE.AmbientLight(0xffffff, 0.6));
  const dir = new THREE.DirectionalLight(0xffffff, 0.6);
  dir.position.set(1, 2, 3);
  scene.add(dir);

  const camera = new THREE.PerspectiveCamera(
    45,
    canvas.clientWidth / Math.max(1, canvas.clientHeight),
    0.05,
    20,
  );
  // 로봇 뒤에서 살짝 위에서 내려다보는 각도.
  camera.position.set(-0.893, 0.003, 2.726);
  camera.up.set(0, 0, 1);

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);

  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.target.set(0.174, 0.008, 0.473);

  function onResize(): void {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (w === 0 || h === 0) return;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h, false);
  }
  window.addEventListener('resize', onResize);

  return {
    scene,
    camera,
    renderer,
    controls,
    dispose() {
      window.removeEventListener('resize', onResize);
      controls.dispose();
      renderer.dispose();
    },
  };
}
