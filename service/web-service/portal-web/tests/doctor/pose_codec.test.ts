import { describe, expect, it } from 'vitest';
import {
  encodeTarget, decodeTarget, encodeState, decodeState,
  MAGIC, MSG_TARGET, MSG_STATE,
  SERVO_STATUS_OK, SERVO_STATUS_SLOWED,
  type TargetFrame, type StateFrame, type ArmTarget, type ArmState,
} from '../../src/doctor/pose_codec';

function armTarget(over: Partial<ArmTarget> = {}): ArmTarget {
  return { x: 0.3, y: 0.1, z: 0.45, qx: 0, qy: 0, qz: 0, qw: 1, gripper: 0.55, ...over };
}

describe('pose_codec target', () => {
  it('round-trip both arms', () => {
    const src: TargetFrame = {
      tsMs: 1234567,
      left: armTarget({ x: 0.3 }),
      right: armTarget({ x: -0.3, gripper: 0.2 }),
    };
    const buf = encodeTarget(src);
    expect(buf.byteLength).toBe(37);
    const view = new DataView(buf);
    expect(view.getUint8(0)).toBe(MAGIC);
    expect(view.getUint8(1)).toBe(MSG_TARGET);
    const dst = decodeTarget(buf);
    expect(dst.tsMs).toBe(1234567);
    expect(dst.left!.x).toBeCloseTo(0.3, 3);
    expect(dst.right!.x).toBeCloseTo(-0.3, 3);
    expect(dst.left!.gripper).toBeCloseTo(0.55, 2);
    expect(dst.right!.gripper).toBeCloseTo(0.20, 2);
  });

  it('left only', () => {
    const src: TargetFrame = { tsMs: 42, left: armTarget(), right: null };
    const buf = encodeTarget(src);
    expect(buf.byteLength).toBe(22);
    const dst = decodeTarget(buf);
    expect(dst.left).not.toBeNull();
    expect(dst.right).toBeNull();
  });

  it('right only', () => {
    const src: TargetFrame = { tsMs: 99, left: null, right: armTarget({ x: -0.1 }) };
    const buf = encodeTarget(src);
    expect(buf.byteLength).toBe(22);
    const dst = decodeTarget(buf);
    expect(dst.left).toBeNull();
    expect(dst.right).not.toBeNull();
    expect(dst.right!.x).toBeCloseTo(-0.1, 3);
  });

  it('signed quaternion', () => {
    const src: TargetFrame = {
      tsMs: 1,
      left: armTarget({ qx: 0.5, qy: -0.5, qz: 0.5, qw: -0.5 }),
      right: null,
    };
    const dst = decodeTarget(encodeTarget(src));
    expect(dst.left!.qw).toBeCloseTo(-0.5, 3);
    expect(dst.left!.qy).toBeCloseTo(-0.5, 3);
  });

  it('rejects bad magic', () => {
    const buf = encodeTarget({ tsMs: 0, left: armTarget(), right: null });
    new DataView(buf).setUint8(0, 0xff);
    expect(() => decodeTarget(buf)).toThrow();
  });

  it('rejects truncated buffer (flags claim two arms but only one present)', () => {
    const full = encodeTarget({ tsMs: 1, left: armTarget(), right: armTarget() });
    // slice off the last arm block — 37 - 15 = 22 bytes, but flags still say 0x3
    const truncated = full.slice(0, 22);
    expect(() => decodeTarget(truncated)).toThrow();
  });
});

describe('pose_codec state', () => {
  it('round-trip', () => {
    const src: StateFrame = {
      tsMs: 999,
      left: {
        joints: [0.1, -0.2, 0.3, 0.4, -0.5, 0.0, 1.0],
        gripper: 0.54,
        servoStatus: SERVO_STATUS_OK,
      } satisfies ArmState,
      right: {
        joints: [0, 0, 0, 0, 0, 0, 0],
        gripper: 0.20,
        servoStatus: SERVO_STATUS_SLOWED,
      } satisfies ArmState,
    };
    const buf = encodeState(src);
    expect(buf.byteLength).toBe(37);
    expect(new DataView(buf).getUint8(1)).toBe(MSG_STATE);
    const dst = decodeState(buf);
    expect(dst.left.joints[2]).toBeCloseTo(0.3, 3);
    expect(dst.right.servoStatus).toBe(SERVO_STATUS_SLOWED);
  });
});
