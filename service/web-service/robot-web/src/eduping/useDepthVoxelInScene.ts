/**
 * 클라이언트 사이드 voxel rendering — D435 depth frame 을 voxel grid 로 다운샘플해
 * 작은 cube 들로 시각화 (RViz 의 octomap_rviz_plugins/OccupancyGrid 시각 효과 흉내).
 *
 * 백엔드 MoveIt 의 /octomap_full 토픽이 안 떠있을 때 (moveit-ros-perception 미설치)
 * 클라이언트만으로 octomap-like 표시. 같은 D435 depth 데이터를 voxelize 만 하는 거라
 * RViz 의 OccupancyGrid 와 시각적으로 거의 동일.
 *
 * 부착:
 *   useDepthCloudInScene 와 동일하게 URDF 의 d435_color_optical_frame 자식으로 mount.
 *   parent chain 이 좌표 변환 → voxel cube 의 world position 이 그대로 robot scene 의
 *   world 와 맞물림.
 *
 * 성능:
 *   - 매 frame voxelize 하면 60Hz 에서 CPU 가 부담. throttle = N frame 마다 1 회 만.
 *   - InstancedMesh 1개 + matrix array reuse — 매 update 마다 mesh 재생성 X.
 *   - max voxel 수 제한 (default 4096) — 초과 시 가까운 (낮은 z) 우선.
 */
import * as THREE from 'three';
import type { UseDepthStream, DecodedDepthFrame } from './useDepthStream';
import type { URDFRobot } from 'urdf-loader';
import {
  voxelizeDepthFrame,
  unpackVoxelKey,
  type VoxelizeBuffers,
} from './voxelizeDepthFrame';

export interface UseDepthVoxelInSceneOpts {
  robot: URDFRobot;
  depthStream: UseDepthStream;
  /** Voxel 한 변 크기 (m). 작을수록 세밀하지만 voxel 수 폭증. default 0.05m (5cm). */
  voxelSize?: number;
  /** 표시 voxel 최대 수. 초과 시 가까운 (낮은 z) 만. default 4096. */
  maxVoxels?: number;
  /** Voxelize 주기 — N depth frame 마다 1회 (D435 가 15fps 이면 N=3 → 5Hz). default 3. */
  throttleFrames?: number;
  /** 가까운/먼 depth clip (m). default 0.3-2.5. */
  minDepthM?: number;
  maxDepthM?: number;
  /** Voxel 색 — depth jet 컬러맵 자동 적용. 단색 원하면 fixedColor 지정. */
  fixedColor?: THREE.ColorRepresentation;
  /** Voxel 투명도 (0~1). default 0.4. */
  opacity?: number;
  /** Pixel sampling stride (1 = 모든 픽셀, 3 = 1/9). default 3. */
  voxelizeStride?: number;
  /** D435 FoV 와이어프레임 frustum 표시 (RealSense viewer 의 녹색 박스). 기본 false. */
  showFrustum?: boolean;
  /** Frustum near plane (m). 기본 0.3 (D435 minZ). */
  frustumNearM?: number;
  /** Frustum far plane (m). 기본 maxDepthM. */
  frustumFarM?: number;
}

export interface UseDepthVoxelInScene {
  setVisible(v: boolean): void;
  dispose(): void;
}

const OPTICAL_FRAME_LINK = 'd435_color_optical_frame';

export function useDepthVoxelInScene(
  opts: UseDepthVoxelInSceneOpts,
): UseDepthVoxelInScene {
  const opticalLink = opts.robot.links?.[OPTICAL_FRAME_LINK];
  if (!opticalLink) {
    console.warn(
      `[useDepthVoxelInScene] ${OPTICAL_FRAME_LINK} link not in URDF — skipping`,
    );
    return { setVisible: () => {}, dispose: () => {} };
  }

  const voxelSize = opts.voxelSize ?? 0.05;
  const maxVoxels = opts.maxVoxels ?? 4096;
  const throttleFrames = opts.throttleFrames ?? 3;
  const minDepthM = opts.minDepthM ?? 0.3;
  const maxDepthM = opts.maxDepthM ?? 2.5;
  // RViz octomap 의 OccupancyGrid 와 비슷한 무게감을 주려고 0.4 → 0.85. 너무
  // 불투명하면 뒤쪽 로봇 mesh 가 가려지므로 80% 안팎이 균형점.
  const opacity = opts.opacity ?? 0.85;

  // 작은 cube 한 개 — InstancedMesh 가 instance 당 matrix 로 위치·색 다르게.
  const boxGeom = new THREE.BoxGeometry(voxelSize * 0.9, voxelSize * 0.9, voxelSize * 0.9);
  const material = new THREE.MeshBasicMaterial({
    transparent: opacity < 1,
    opacity,
    color: 0xffffff,
    vertexColors: true,
  });
  const mesh = new THREE.InstancedMesh(boxGeom, material, maxVoxels);
  mesh.count = 0;
  mesh.name = 'depth_voxel_grid';
  // depth clear → 다른 robot mesh 와 z-fight 안 일어남.
  mesh.renderOrder = 1;
  // BoxGeometry 의 boundingSphere 가 5cm 원점 근처 — three.js 가 그걸로 culling
  // 하면 instance 들이 멀리 떨어진 위치에 있어도 mesh 전체가 cull 되어 voxel 이
  // 안 보이는 경우 발생 (optical_link 가 view frustum 경계에 걸칠 때). instance
  // 별 boundingSphere 갱신 비용 (O(N)) 대신 culling off — voxel 수가 ≤ maxVoxels
  // (=4096) 이라 off-screen 렌더링 비용도 무시 가능.
  mesh.frustumCulled = false;
  // Voxel 컬러: depth 에 따른 jet (cold/blue → warm/red). vertexColors=true 라
  // setColorAt 으로 per-instance 색.
  const colorBuf = new Float32Array(maxVoxels * 3);
  mesh.instanceColor = new THREE.InstancedBufferAttribute(colorBuf, 3);
  opticalLink.add(mesh);

  // 재사용 버퍼.
  const dummy = new THREE.Object3D();
  const voxelizeStride = opts.voxelizeStride ?? 3;
  const buffers: VoxelizeBuffers = {
    outKey: new Int32Array(maxVoxels),
    outDepth: new Float32Array(maxVoxels),
    scratchMap: new Map<number, number>(),
  };

  let frameCounter = 0;
  let disposed = false;
  let visible = true;
  let frustum: THREE.LineSegments | null = null;

  function ensureFrustum(
    w: number, h: number, fx: number, fy: number, cx: number, cy: number,
  ): void {
    if (frustum || !opts.showFrustum) return;
    const nearZ = opts.frustumNearM ?? 0.3;
    const farZ = opts.frustumFarM ?? maxDepthM;
    const corner = (u: number, v: number, z: number) => [
      ((u - cx) * z) / fx,
      ((v - cy) * z) / fy,
      z,
    ];
    const N = [
      corner(0, 0, nearZ),         corner(w - 1, 0, nearZ),
      corner(w - 1, h - 1, nearZ), corner(0, h - 1, nearZ),
    ];
    const F = [
      corner(0, 0, farZ),         corner(w - 1, 0, farZ),
      corner(w - 1, h - 1, farZ), corner(0, h - 1, farZ),
    ];
    const e = (a: number[], b: number[]) => [...a, ...b];
    const verts = new Float32Array([
      ...e(N[0], N[1]), ...e(N[1], N[2]), ...e(N[2], N[3]), ...e(N[3], N[0]),
      ...e(F[0], F[1]), ...e(F[1], F[2]), ...e(F[2], F[3]), ...e(F[3], F[0]),
      ...e(N[0], F[0]), ...e(N[1], F[1]), ...e(N[2], F[2]), ...e(N[3], F[3]),
    ]);
    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.BufferAttribute(verts, 3));
    const material = new THREE.LineBasicMaterial({
      color: 0x22ee22, transparent: true, opacity: 0.5, depthTest: true,
    });
    frustum = new THREE.LineSegments(geom, material);
    opticalLink.add(frustum);
  }

  // Jet colormap — RViz 와 동일.
  function jetColor(t: number, out: THREE.Color): void {
    const tc = Math.min(1, Math.max(0, t));
    const r = Math.min(1, Math.max(0, 1.5 - Math.abs(4 * tc - 3)));
    const g = Math.min(1, Math.max(0, 1.5 - Math.abs(4 * tc - 2)));
    const b = Math.min(1, Math.max(0, 1.5 - Math.abs(4 * tc - 1)));
    out.setRGB(r, g, b);
  }

  function onFrame(frame: DecodedDepthFrame): void {
    if (disposed || !visible) return;
    ensureFrustum(
      frame.depthW, frame.depthH,
      frame.fx, frame.fy, frame.cx, frame.cy,
    );
    frameCounter = (frameCounter + 1) % throttleFrames;
    if (frameCounter !== 0) return;

    const cellCount = voxelizeDepthFrame({
      depth: frame.depth,
      depthW: frame.depthW,
      depthH: frame.depthH,
      fx: frame.fx, fy: frame.fy, cx: frame.cx, cy: frame.cy,
      depthScale: frame.depthScale,
      minDepthM, maxDepthM,
      voxelSize, stride: voxelizeStride, maxVoxels,
      buffers,
    });

    const tmpColor = new THREE.Color();
    for (let i = 0; i < cellCount; i++) {
      const { vx, vy, vz } = unpackVoxelKey(buffers.outKey[i]);
      dummy.position.set(
        (vx + 0.5) * voxelSize,
        (vy + 0.5) * voxelSize,
        (vz + 0.5) * voxelSize,
      );
      dummy.rotation.set(0, 0, 0);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
      if (opts.fixedColor) {
        tmpColor.set(opts.fixedColor);
      } else {
        jetColor(
          (buffers.outDepth[i] - minDepthM) / (maxDepthM - minDepthM),
          tmpColor,
        );
      }
      mesh.setColorAt(i, tmpColor);
    }
    mesh.count = cellCount;
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }

  opts.depthStream.onFrame(onFrame);

  return {
    setVisible(v: boolean): void {
      visible = v;
      mesh.visible = v;
    },
    dispose(): void {
      disposed = true;
      if (frustum) {
        opticalLink.remove(frustum);
        frustum.geometry.dispose();
        (frustum.material as THREE.Material).dispose();
        frustum = null;
      }
      opticalLink.remove(mesh);
      boxGeom.dispose();
      material.dispose();
    },
  };
}
