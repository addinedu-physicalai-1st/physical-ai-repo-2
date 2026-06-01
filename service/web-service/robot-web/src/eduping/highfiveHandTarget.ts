/**
 * Palm 3D unproject + POST /api/eduping/highfive/hand-target — DepthViewer · HighfiveDetector 공용.
 */
import type { DecodedDepthFrame } from './useDepthStream';
import type { HandPoint } from './useHandTracker';

// frustum near plane 과 일치 — 카메라 바로 앞 (얼굴, 어깨 등) 은 hand-accept 영역 밖.
// box 를 robot 쪽으로 당김 (40~60cm) — gripper 의 자연 reach 와 match.
// 2026-06-01: box 를 openarm 쪽으로 당김 (depth 0.35~0.60 → 0.30~0.50) — 측정상 arm
// contact reach ~0.49m (world X), 카메라 0.075 → reachable depth ≲0.42. far 0.60(world
// X 0.675) 은 reach 밖이라 tap 이 허공. far 를 0.50(world X 0.575)으로 당겨 box 의 더
// 많은 부분이 닿게. 여전히 short 면 더 당길 것 (far→~0.42).
export const HIGHFIVE_MIN_Z_M = 0.44;
export const HIGHFIVE_MAX_Z_M = 0.50;
/** POST throttle — 30ms ≈ 33Hz update. red ball 이 hand 움직임을 거의 실시간으로
 *  따라가게. */
export const HIGHFIVE_POST_INTERVAL_MS = 30;
/** "박스 안이면 반드시 follow" — 3-frame 안정성 요구는 연속 움직임에선 POST 가
 *  영원히 안 나가 arm 이 "유지" 로 굳음. 1 frame = detected 즉시 POST.
 *  HIGHFIVE_POST_INTERVAL_MS throttle 이 jitter spam 방지. */
export const HIGHFIVE_PALM_STABLE_FRAMES = 1;
/** Palm 0.5cm 이상 움직였을 때 재전송 — 작은 움직임도 red ball 이 실시간으로
 *  따라가도록 작게. 0.02 (2cm) 였을 때는 느린 손 움직임에 red ball 이 정지된 채로
 *  보였다. */
export const HIGHFIVE_PALM_MOVE_M = 0.005;
/** "유지" 상태도 100ms 마다 heartbeat — red ball 이 최신 위치에 stable 하게.
 *  400ms 였을 때는 정지 손에서 red ball 이 2.5Hz update 라 깜빡거리는 느낌. */
export const HIGHFIVE_HEARTBEAT_INTERVAL_MS = 100;
/** 프레임 간 안정 판정 거리 (m). */
export const HIGHFIVE_PALM_STABLE_EPS_M = 0.04;

/** Palm-vs-backhand 판정 deadband — sin(angle) 단위. 0.20 ≈ 11° — 손이 약간 기울어도
 *  통과. 예전 0.35 는 MediaPipe 가 LEFT 손 handedness 신뢰도가 낮을 때 cross-product
 *  부호가 흔들려 reject 되는 빈도 ↑ — 왼손 detection rate 가 낮은 주요 원인이었음.
 *  palm 만 high-five trigger, 명확한 backhand 는 여전히 거부. */
const PALM_FACING_DEADBAND = 0.20;

/** 손바닥이 카메라를 향하고 있을 때만 true. 손등 (backhand) · 옆면 (profile) 은 false.
 *
 *  Method: image-space 에서 wrist(0) → index_mcp(5) 와 wrist(0) → pinky_mcp(17) 두
 *  vector 의 2D signed cross product. magnitude 로 정규화하면 |sin(두 vector 사이 각)|
 *  이 나오고 부호는 손이 palm 인지 back 인지 정함.
 *
 *    RIGHT 손: palm-facing → cross < 0 ; backhand → cross > 0
 *    LEFT  손: palm-facing → cross > 0 ; backhand → cross < 0
 *
 *  손가락 방향 (위/옆/아래) 회전과 무관 — wrist 기준 두 vector 가 함께 회전해 부호 유지.
 *  손목 축 둘레 회전 (palm ↔ back) 만이 부호 뒤집음. profile (손이 카메라에 옆면) 일 때
 *  두 vector 가 시각적으로 겹쳐 cross 가 0 근처 → deadband 로 거름. */
export function isPalmFacingCamera(hand: HandPoint): boolean {
  if (hand.handedness === 'Unknown') return false;
  const wrist = hand.landmarks[0];
  const indexMcp = hand.landmarks[5];
  const pinkyMcp = hand.landmarks[17];
  if (wrist === undefined || indexMcp === undefined || pinkyMcp === undefined) {
    return false;
  }
  const v1u = indexMcp.u - wrist.u;
  const v1v = indexMcp.v - wrist.v;
  const v2u = pinkyMcp.u - wrist.u;
  const v2v = pinkyMcp.v - wrist.v;
  const cross = v1u * v2v - v1v * v2u;
  const mag = Math.sqrt((v1u * v1u + v1v * v1v) * (v2u * v2u + v2v * v2v));
  if (mag < 1e-6) return false;
  const normalized = cross / mag;   // ≈ ±sin(angle)
  if (Math.abs(normalized) < PALM_FACING_DEADBAND) return false;
  return hand.handedness === 'Right' ? normalized < 0 : normalized > 0;
}

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

/** One Euro low-pass on a single axis. Reference: Casiez et al. 2012.
 *  Adaptive cutoff = minCutoff + beta * |derivative| → 손이 가만히 있을 때 강한
 *  smoothing, 빨리 움직일 때 cutoff ↑ 라 lag 없음. arm 이 jitter 따라 미세하게
 *  떠는 현상 (MediaPipe palm landmark 가 ±1cm noise) 을 제거하면서도 사용자
 *  실제 wave 동작은 그대로 통과. */
class OneEuroFilter {
  private prev: number | null = null;
  private prevDeriv = 0;
  private prevTsSec = 0;
  constructor(
    private readonly minCutoff = 1.0,
    private readonly beta = 0.007,
    private readonly dCutoff = 1.0,
  ) {}
  private alpha(cutoff: number, dtSec: number): number {
    const tau = 1.0 / (2 * Math.PI * cutoff);
    return 1.0 / (1.0 + tau / dtSec);
  }
  step(v: number, tsMs: number): number {
    const tsSec = tsMs / 1000;
    if (this.prev === null) {
      this.prev = v;
      this.prevTsSec = tsSec;
      return v;
    }
    const dt = Math.max(tsSec - this.prevTsSec, 1e-3);
    this.prevTsSec = tsSec;
    const dv = (v - this.prev) / dt;
    const dvHat =
      this.prevDeriv + this.alpha(this.dCutoff, dt) * (dv - this.prevDeriv);
    this.prevDeriv = dvHat;
    const cutoff = this.minCutoff + this.beta * Math.abs(dvHat);
    const a = this.alpha(cutoff, dt);
    const out = this.prev + a * (v - this.prev);
    this.prev = out;
    return out;
  }
  reset(): void {
    this.prev = null;
    this.prevDeriv = 0;
    this.prevTsSec = 0;
  }
}

export class PalmOneEuro {
  private readonly fx = new OneEuroFilter();
  private readonly fy = new OneEuroFilter();
  private readonly fz = new OneEuroFilter();
  step(p: Palm3D, tsMs: number): Palm3D {
    return {
      x: this.fx.step(p.x, tsMs),
      y: this.fy.step(p.y, tsMs),
      z: this.fz.step(p.z, tsMs),
    };
  }
  reset(): void {
    this.fx.reset();
    this.fy.reset();
    this.fz.reset();
  }
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

/** Mirror: user's LEFT hand → robot's RIGHT arm, user's RIGHT hand → robot's LEFT arm.
 *
 *  좌표 검증: 사용자가 robot 마주봄.
 *   - 사용자의 LEFT 손 = 본인 좌측 = 카메라 RIGHT (no-mirror 캡처) = opt X+
 *     → world Y NEGATIVE (TF: opt X+0.10 → world Y-0.10)
 *     → robot's RIGHT 팔 (shoulder y=-0.031) 의 same-side workspace
 *   - 사용자의 RIGHT 손 = 카메라 LEFT = opt X- = world Y+ → robot's LEFT 팔.
 *
 *  결과: 시각적으로 mirror (cross-body 인 듯) 하지만 robot 입장에선 각 팔이 자기
 *  side 에서 reach → centerline 안 넘음 → 양팔 동시에도 충돌 없음. */
export function mirrorArmForHand(handedness: 'Left' | 'Right' | 'Unknown'): 'left' | 'right' | null {
  if (handedness === 'Left') return 'right';
  if (handedness === 'Right') return 'left';
  return null;
}

export async function postHighfiveHandTarget(
  palm: Palm3D,
  arm: 'left' | 'right' | null = null,
): Promise<boolean> {
  const body: Record<string, number | string> = { x: palm.x, y: palm.y, z: palm.z };
  if (arm !== null) body.arm = arm;
  const res = await fetch('/api/eduping/highfive/hand-target', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
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
