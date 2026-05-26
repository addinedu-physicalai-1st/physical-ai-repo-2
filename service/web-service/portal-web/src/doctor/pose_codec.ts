/**
 * Binary teleop wire protocol — TS mirror of
 * service/control-service/control_service/streaming/teleop_protocol.py.
 * Spec: docs/superpowers/specs/2026-05-26-doctor-ui-telemedicine-design.md §4
 *
 * Header (little-endian, 7 bytes):
 *   magic u8 = 0xDC | msg_type u8 | flags u8 | ts_ms u32
 * Arm block 15 B.
 */

export const MAGIC = 0xdc;
export const MSG_TARGET = 0x01;
export const MSG_STATE = 0x02;

export const SERVO_STATUS_OK = 0;
export const SERVO_STATUS_SLOWED = 1;
export const SERVO_STATUS_STOPPED = 2;
export const SERVO_STATUS_ERROR = 3;

const HEADER_SIZE = 7;
const ARM_BLOCK_SIZE = 15;
const POS_SCALE = 1000;
const QUAT_SCALE = 32767;
const JOINT_SCALE = 10000;

export interface ArmTarget {
  x: number; y: number; z: number;
  qx: number; qy: number; qz: number; qw: number;
  gripper: number; // 0..1
}

export interface TargetFrame {
  tsMs: number;
  left: ArmTarget | null;
  right: ArmTarget | null;
}

export interface ArmState {
  joints: number[]; // length 7, rad
  gripper: number;  // 0..1 actual
  servoStatus: number;
}

export interface StateFrame {
  tsMs: number;
  left: ArmState;
  right: ArmState;
}

function clampInt16(v: number): number {
  return Math.max(-32768, Math.min(32767, Math.round(v)));
}
function clampUint8(v: number): number {
  return Math.max(0, Math.min(255, Math.round(v)));
}

function writeArmTarget(view: DataView, off: number, a: ArmTarget): void {
  view.setInt16(off,      clampInt16(a.x * POS_SCALE), true);
  view.setInt16(off + 2,  clampInt16(a.y * POS_SCALE), true);
  view.setInt16(off + 4,  clampInt16(a.z * POS_SCALE), true);
  view.setInt16(off + 6,  clampInt16(a.qx * QUAT_SCALE), true);
  view.setInt16(off + 8,  clampInt16(a.qy * QUAT_SCALE), true);
  view.setInt16(off + 10, clampInt16(a.qz * QUAT_SCALE), true);
  view.setInt16(off + 12, clampInt16(a.qw * QUAT_SCALE), true);
  view.setUint8(off + 14, clampUint8(a.gripper * 255));
}

function readArmTarget(view: DataView, off: number): ArmTarget {
  return {
    x:  view.getInt16(off,      true) / POS_SCALE,
    y:  view.getInt16(off + 2,  true) / POS_SCALE,
    z:  view.getInt16(off + 4,  true) / POS_SCALE,
    qx: view.getInt16(off + 6,  true) / QUAT_SCALE,
    qy: view.getInt16(off + 8,  true) / QUAT_SCALE,
    qz: view.getInt16(off + 10, true) / QUAT_SCALE,
    qw: view.getInt16(off + 12, true) / QUAT_SCALE,
    gripper: view.getUint8(off + 14) / 255,
  };
}

export function encodeTarget(frame: TargetFrame): ArrayBuffer {
  const armCount = (frame.left ? 1 : 0) + (frame.right ? 1 : 0);
  const buf = new ArrayBuffer(HEADER_SIZE + armCount * ARM_BLOCK_SIZE);
  const view = new DataView(buf);
  const flags = (frame.left ? 0x1 : 0) | (frame.right ? 0x2 : 0);
  view.setUint8(0, MAGIC);
  view.setUint8(1, MSG_TARGET);
  view.setUint8(2, flags);
  view.setUint32(3, frame.tsMs >>> 0, true);
  let off = HEADER_SIZE;
  if (frame.left)  { writeArmTarget(view, off, frame.left);  off += ARM_BLOCK_SIZE; }
  if (frame.right) { writeArmTarget(view, off, frame.right); }
  return buf;
}

export function decodeTarget(buf: ArrayBuffer): TargetFrame {
  if (buf.byteLength < HEADER_SIZE) throw new Error('target frame too short');
  const view = new DataView(buf);
  if (view.getUint8(0) !== MAGIC) throw new Error(`bad magic 0x${view.getUint8(0).toString(16)}`);
  if (view.getUint8(1) !== MSG_TARGET) throw new Error('expected MSG_TARGET');
  const flags = view.getUint8(2);
  const tsMs = view.getUint32(3, true);
  const armCount = ((flags & 0x1) ? 1 : 0) + ((flags & 0x2) ? 1 : 0);
  const expected = HEADER_SIZE + armCount * ARM_BLOCK_SIZE;
  if (buf.byteLength < expected) {
    throw new Error(`target frame too short: ${buf.byteLength} < ${expected}`);
  }
  let off = HEADER_SIZE;
  let left: ArmTarget | null = null;
  let right: ArmTarget | null = null;
  if (flags & 0x1) { left = readArmTarget(view, off); off += ARM_BLOCK_SIZE; }
  if (flags & 0x2) { right = readArmTarget(view, off); }
  return { tsMs, left, right };
}

function writeArmState(view: DataView, off: number, s: ArmState): void {
  if (s.joints.length !== 7) throw new Error(`expected 7 joints, got ${s.joints.length}`);
  for (let i = 0; i < 7; i++) {
    view.setInt16(off + i * 2, clampInt16(s.joints[i] * JOINT_SCALE), true);
  }
  view.setUint8(off + 14, clampUint8(s.gripper * 255));
}

function readArmState(view: DataView, off: number, servoStatus: number): ArmState {
  const joints = new Array<number>(7);
  for (let i = 0; i < 7; i++) {
    joints[i] = view.getInt16(off + i * 2, true) / JOINT_SCALE;
  }
  return { joints, gripper: view.getUint8(off + 14) / 255, servoStatus };
}

export function encodeState(frame: StateFrame): ArrayBuffer {
  const buf = new ArrayBuffer(HEADER_SIZE + 2 * ARM_BLOCK_SIZE);
  const view = new DataView(buf);
  const flags = (frame.left.servoStatus & 0x3) | ((frame.right.servoStatus & 0x3) << 2);
  view.setUint8(0, MAGIC);
  view.setUint8(1, MSG_STATE);
  view.setUint8(2, flags);
  view.setUint32(3, frame.tsMs >>> 0, true);
  writeArmState(view, HEADER_SIZE, frame.left);
  writeArmState(view, HEADER_SIZE + ARM_BLOCK_SIZE, frame.right);
  return buf;
}

export function decodeState(buf: ArrayBuffer): StateFrame {
  if (buf.byteLength < HEADER_SIZE + 2 * ARM_BLOCK_SIZE) throw new Error('state frame too short');
  const view = new DataView(buf);
  if (view.getUint8(0) !== MAGIC) throw new Error('bad magic');
  if (view.getUint8(1) !== MSG_STATE) throw new Error('expected MSG_STATE');
  const flags = view.getUint8(2);
  const tsMs = view.getUint32(3, true);
  const left = readArmState(view, HEADER_SIZE, flags & 0x3);
  const right = readArmState(view, HEADER_SIZE + ARM_BLOCK_SIZE, (flags >> 2) & 0x3);
  return { tsMs, left, right };
}
