/**
 * 순수 depth-frame voxelizer — three.js 의존 0.
 *
 * caller 가 output typed array + scratch Map 을 소유 → hot path 에서 alloc 0.
 * 반환값: outKey/outDepth 에 기록된 cell 수 (≤ maxVoxels).
 *
 * 키 패킹: 축 당 8bit. vx/vy 는 부호 (PACK_OFFSET 더해서 0..255 로 맵핑).
 * vz 는 부호 없음 (depth 는 항상 양수). voxelSize=0.05m / maxDepthM=2.5m 기준
 * 일반 cell 범위 vx,vy ≈ ±40, vz ≈ 0..50 — 8bit 안에 충분히 들어옴. 박스 밖
 * cell 은 bounds check 로 drop.
 */
export const PACK_OFFSET = 128;
const PACK_RANGE = 256;

export function packVoxelKey(vx: number, vy: number, vz: number): number {
  return ((vx + PACK_OFFSET) << 16) | ((vy + PACK_OFFSET) << 8) | vz;
}

export function unpackVoxelKey(key: number): { vx: number; vy: number; vz: number } {
  return {
    vx: ((key >> 16) & 0xff) - PACK_OFFSET,
    vy: ((key >> 8) & 0xff) - PACK_OFFSET,
    vz: key & 0xff,
  };
}

export interface VoxelizeBuffers {
  /** cell 당 packed key; length = maxVoxels */
  outKey: Int32Array;
  /** cell 당 최근접 depth (m); length = maxVoxels */
  outDepth: Float32Array;
  /** packedKey → outKey/outDepth 의 삽입 index */
  scratchMap: Map<number, number>;
}

export interface VoxelizeOpts {
  depth: Uint16Array;
  depthW: number;
  depthH: number;
  fx: number;
  fy: number;
  cx: number;
  cy: number;
  /** meters per uint16 unit (D435 기본 0.001) */
  depthScale: number;
  minDepthM: number;
  maxDepthM: number;
  voxelSize: number;
  /** u/v 의 픽셀 stride (1 = 모든 픽셀) */
  stride: number;
  maxVoxels: number;
  buffers: VoxelizeBuffers;
}

/**
 * Depth frame 을 스캔 → optical-frame XYZ 로 unproject → packed key 로 cell 누적.
 * @returns buffers.outKey / buffers.outDepth 에 기록된 cell 수.
 */
export function voxelizeDepthFrame(opts: VoxelizeOpts): number {
  const {
    depth, depthW, depthH, fx, fy, cx, cy, depthScale,
    minDepthM, maxDepthM, voxelSize, stride, maxVoxels, buffers,
  } = opts;
  const { outKey, outDepth, scratchMap } = buffers;

  scratchMap.clear();
  let cellCount = 0;

  const invFx = 1 / fx;
  const invFy = 1 / fy;
  const invVoxel = 1 / voxelSize;

  for (let v = 0; v < depthH; v += stride) {
    const row = v * depthW;
    const yScale = (v - cy) * invFy;
    for (let u = 0; u < depthW; u += stride) {
      const raw = depth[row + u];
      if (raw === 0) continue;
      const z = raw * depthScale;
      if (z < minDepthM || z > maxDepthM) continue;
      const x = (u - cx) * invFx * z;
      const y = yScale * z;
      const vx = Math.floor(x * invVoxel) + PACK_OFFSET;
      const vy = Math.floor(y * invVoxel) + PACK_OFFSET;
      const vz = Math.floor(z * invVoxel);
      if (vx < 0 || vy < 0 || vz < 0
        || vx >= PACK_RANGE || vy >= PACK_RANGE || vz >= PACK_RANGE) continue;
      const key = (vx << 16) | (vy << 8) | vz;
      const existing = scratchMap.get(key);
      if (existing === undefined) {
        if (cellCount >= maxVoxels) continue;
        scratchMap.set(key, cellCount);
        outKey[cellCount] = key;
        outDepth[cellCount] = z;
        cellCount++;
      } else if (z < outDepth[existing]) {
        outDepth[existing] = z;
      }
    }
  }
  return cellCount;
}
