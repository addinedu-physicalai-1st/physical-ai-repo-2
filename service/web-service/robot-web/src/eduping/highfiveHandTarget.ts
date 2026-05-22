/**
 * Palm 3D unproject + POST /api/eduping/highfive/hand-target — DepthViewer · HighfiveDetector 공용.
 */
import type { DecodedDepthFrame } from './useDepthStream';
import type { HandPoint } from './useHandTracker';

export const HIGHFIVE_MIN_Z_M = 0.30;
export const HIGHFIVE_MAX_Z_M = 1.5;
/** 모션(2s) + 마진 — highfive_node 와 동기화. */
export const HIGHFIVE_POST_INTERVAL_MS = 2800;
/** 연속 프레임 palm 위치 안정 (≈0.3s @ 15fps). */
export const HIGHFIVE_PALM_STABLE_FRAMES = 8;
/** palm 이 이 거리 이상 움직였을 때만 재전송 (m). */
export const HIGHFIVE_PALM_MOVE_M = 0.12;
/** 프레임 간 안정 판정 거리 (m). */
export const HIGHFIVE_PALM_STABLE_EPS_M = 0.04;

export function palmDistanceM(a: Palm3D, b: Palm3D): number {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  const dz = a.z - b.z;
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

export interface Palm3D {
  x: number;
  y: number;
  z: number;
}

export type PalmResult =
  | { ok: true; palm: Palm3D }
  | { ok: false; reason: 'no_depth' | 'out_of_range' };

export function palmFromFrame(frame: DecodedDepthFrame, hand: HandPoint): PalmResult {
  const u = Math.round(Math.min(Math.max(hand.u, 0), frame.depthW - 1));
  const v = Math.round(Math.min(Math.max(hand.v, 0), frame.depthH - 1));
  const raw = frame.depth[v * frame.depthW + u];
  if (raw === 0) return { ok: false, reason: 'no_depth' };
  const z_m = raw * frame.depthScale;
  if (z_m < HIGHFIVE_MIN_Z_M || z_m > HIGHFIVE_MAX_Z_M) {
    return { ok: false, reason: 'out_of_range' };
  }
  const x_m = ((u - frame.cx) * z_m) / frame.fx;
  const y_m = ((v - frame.cy) * z_m) / frame.fy;
  return { ok: true, palm: { x: x_m, y: y_m, z: z_m } };
}

export async function postHighfiveHandTarget(palm: Palm3D): Promise<boolean> {
  const res = await fetch('/api/eduping/highfive/hand-target', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ x: palm.x, y: palm.y, z: palm.z }),
  });
  return res.ok;
}

export async function postReturnHomeSim(): Promise<void> {
  await fetch('/api/eduping/arm/return-home', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target: 'sim' }),
  });
}
