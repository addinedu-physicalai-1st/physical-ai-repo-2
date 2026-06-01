// @vitest-environment node
// 순수 typed-array 연산만 — DOM/jsdom 불필요. robot-web 의 jsdom 설치는
// html-encoding-sniffer CJS/ESM 충돌로 현재 깨져있어 (기존 테스트 동일 영향)
// node 환경으로 명시 고정.
import { describe, it, expect } from 'vitest';
import {
  voxelizeDepthFrame,
  packVoxelKey,
  unpackVoxelKey,
  PACK_OFFSET,
  type VoxelizeBuffers,
  type VoxelizeOpts,
} from '../src/eduping/voxelizeDepthFrame';

function makeBuffers(maxVoxels: number): VoxelizeBuffers {
  return {
    outKey: new Int32Array(maxVoxels),
    outDepth: new Float32Array(maxVoxels),
    scratchMap: new Map<number, number>(),
  };
}

function flatDepth(w: number, h: number, mm: number): Uint16Array {
  const a = new Uint16Array(w * h);
  a.fill(mm);
  return a;
}

const INTRINSICS = { fx: 380, fy: 380, cx: 320, cy: 240, depthScale: 0.001 };

describe('packVoxelKey / unpackVoxelKey', () => {
  it('round-trips signed cell coords', () => {
    const cases: Array<[number, number, number]> = [
      [0, 0, 0],
      [10, -10, 25],
      [-50, 30, 0],
      [127 - PACK_OFFSET, 127 - PACK_OFFSET, 250],
      [-PACK_OFFSET, -PACK_OFFSET, 0],
    ];
    for (const [vx, vy, vz] of cases) {
      const k = packVoxelKey(vx, vy, vz);
      expect(unpackVoxelKey(k)).toEqual({ vx, vy, vz });
    }
  });
});

describe('voxelizeDepthFrame', () => {
  it('returns 0 for an all-zero depth frame', () => {
    const bufs = makeBuffers(64);
    const opts: VoxelizeOpts = {
      depth: new Uint16Array(64 * 48),
      depthW: 64, depthH: 48,
      ...INTRINSICS,
      minDepthM: 0.3, maxDepthM: 2.5,
      voxelSize: 0.05, stride: 2, maxVoxels: 64,
      buffers: bufs,
    };
    expect(voxelizeDepthFrame(opts)).toBe(0);
  });

  it('produces exactly one cell at the centre when depth is uniform and voxel is large', () => {
    const depth = flatDepth(8, 8, 1000);
    const bufs = makeBuffers(16);
    const n = voxelizeDepthFrame({
      depth, depthW: 8, depthH: 8,
      ...INTRINSICS,
      minDepthM: 0.3, maxDepthM: 2.5,
      voxelSize: 10.0,
      stride: 1, maxVoxels: 16,
      buffers: bufs,
    });
    expect(n).toBe(1);
    expect(bufs.outDepth[0]).toBeCloseTo(1.0, 5);
  });

  it('drops pixels outside [minDepthM, maxDepthM]', () => {
    const depth = flatDepth(4, 4, 100);
    const bufs = makeBuffers(16);
    expect(voxelizeDepthFrame({
      depth, depthW: 4, depthH: 4,
      ...INTRINSICS,
      minDepthM: 0.3, maxDepthM: 2.5,
      voxelSize: 0.05, stride: 1, maxVoxels: 16,
      buffers: bufs,
    })).toBe(0);
  });

  it('respects stride (skips pixels)', () => {
    // 4x4 frame with z stepping 0.1m per pixel → distinct vz per pixel at voxelSize=0.05.
    // stride 1 = 16 cells; stride 2 visits (0,0),(2,0),(0,2),(2,2) = 4 cells.
    const depth = new Uint16Array(16);
    for (let i = 0; i < 16; i++) depth[i] = 500 + i * 100;
    const bufs1 = makeBuffers(64);
    const bufs2 = makeBuffers(64);
    const base = {
      depth, depthW: 4, depthH: 4,
      ...INTRINSICS,
      minDepthM: 0.3, maxDepthM: 2.5,
      voxelSize: 0.05, maxVoxels: 64,
    };
    const n1 = voxelizeDepthFrame({ ...base, stride: 1, buffers: bufs1 });
    const n2 = voxelizeDepthFrame({ ...base, stride: 2, buffers: bufs2 });
    expect(n1).toBe(16);
    expect(n2).toBe(4);
  });

  it('keeps nearest depth when a cell is hit twice', () => {
    const depth = new Uint16Array(2 * 1);
    depth[0] = 1500; depth[1] = 1200;
    const bufs = makeBuffers(4);
    const n = voxelizeDepthFrame({
      depth, depthW: 2, depthH: 1,
      ...INTRINSICS,
      minDepthM: 0.3, maxDepthM: 2.5,
      voxelSize: 10.0,
      stride: 1, maxVoxels: 4,
      buffers: bufs,
    });
    expect(n).toBe(1);
    expect(bufs.outDepth[0]).toBeCloseTo(1.2, 5);
  });

  it('clears scratchMap before scanning (re-entrant)', () => {
    const bufs = makeBuffers(16);
    bufs.scratchMap.set(0xdead, 0);
    const depth = flatDepth(4, 4, 1000);
    const n = voxelizeDepthFrame({
      depth, depthW: 4, depthH: 4,
      ...INTRINSICS,
      minDepthM: 0.3, maxDepthM: 2.5,
      voxelSize: 10.0, stride: 1, maxVoxels: 16,
      buffers: bufs,
    });
    expect(n).toBe(1);
    expect(bufs.scratchMap.has(0xdead)).toBe(false);
  });

  it('caps at maxVoxels and stops inserting new cells', () => {
    // 16 distinct z values → 16 distinct vz cells, capped to 5.
    const depth = new Uint16Array(16);
    for (let i = 0; i < 16; i++) depth[i] = 500 + i * 100;
    const bufs = makeBuffers(5);
    const n = voxelizeDepthFrame({
      depth, depthW: 4, depthH: 4,
      ...INTRINSICS,
      minDepthM: 0.3, maxDepthM: 2.5,
      voxelSize: 0.05, stride: 1, maxVoxels: 5,
      buffers: bufs,
    });
    expect(n).toBe(5);
  });
});
