/**
 * D435 depth pointcloud renderer — 백엔드의 1m 필터 + decimated 점들을 THREE.Points 로.
 *
 * Wire format (little-endian, control_service.doctor.pointcloud_relay 와 동일):
 *   uint32 count
 *   float32 × 3 × count   (world frame xyz, m)
 *
 * 백엔드가 미리 optical → world 변환 + 1m depth filter + decimation 수행.
 * 프런트는 raw vertex 만 갱신 — 색은 z 높이 기반 (낮을수록 짙은 핑크, 높을수록 cyan).
 */
import * as THREE from 'three';

const MAX_POINTS = 30000;
const POINT_SIZE = 0.012;

export interface PointCloudLayer {
  mesh: THREE.Points;
  updateFromFrame(buffer: ArrayBuffer): void;
  dispose(): void;
}

export function createPointCloudLayer(): PointCloudLayer {
  const geom = new THREE.BufferGeometry();
  const positions = new Float32Array(MAX_POINTS * 3);
  const colors = new Float32Array(MAX_POINTS * 3);
  geom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geom.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  geom.setDrawRange(0, 0);

  const mat = new THREE.PointsMaterial({
    size: POINT_SIZE,
    vertexColors: true,
    sizeAttenuation: true,
    transparent: true,
    opacity: 0.85,
  });

  const mesh = new THREE.Points(geom, mat);
  mesh.frustumCulled = false;

  function updateFromFrame(buffer: ArrayBuffer): void {
    if (buffer.byteLength < 4) return;
    const view = new DataView(buffer);
    const count = view.getUint32(0, true);
    const expected = 4 + count * 12;
    if (buffer.byteLength < expected) {
      console.warn('[pointcloud] truncated frame', { count, byteLength: buffer.byteLength });
      return;
    }
    const n = Math.min(count, MAX_POINTS);
    const posAttr = geom.getAttribute('position') as THREE.BufferAttribute;
    const colorAttr = geom.getAttribute('color') as THREE.BufferAttribute;
    // Float32Array view 로 한 번에 복사 (DataView 루프보다 빠름).
    const src = new Float32Array(buffer, 4, n * 3);
    positions.set(src);
    // 컬러 계산 — z 만 봐서 사이즈 줄임.
    for (let i = 0; i < n; i++) {
      const z = positions[i * 3 + 2];
      const t = z < 0 ? 0 : z > 1 ? 1 : z;
      colors[i * 3]     = 0.86 - 0.69 * t;
      colors[i * 3 + 1] = 0.16 + 0.69 * t;
      colors[i * 3 + 2] = 0.47 + 0.53 * t;
    }
    posAttr.needsUpdate = true;
    colorAttr.needsUpdate = true;
    geom.setDrawRange(0, n);
  }

  function dispose(): void {
    geom.dispose();
    mat.dispose();
  }

  return { mesh, updateFromFrame, dispose };
}
