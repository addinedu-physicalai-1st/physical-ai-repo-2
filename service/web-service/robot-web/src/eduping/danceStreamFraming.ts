/**
 * dance unified stream 의 binary frame parser.
 * Backend 사양은 `control_service/eduping/dance_stream.py` docstring 참조.
 */

export const FRAME_TYPE_MOTION = 0x01;
export const FRAME_TYPE_AUDIO = 0x02;
export const FRAME_TYPE_HEADER = 0x03;
export const FRAME_TYPE_END = 0x04;

export interface StreamHeader {
  slug: string;
  sample_rate: number;
  motion_hz: number;
  tick_ms: number;
  joint_names: string[];
  motion_duration_s: number;
  audio_duration_s: number;
}

export type ParsedFrame =
  | { type: typeof FRAME_TYPE_HEADER; tMs: number; header: StreamHeader }
  | { type: typeof FRAME_TYPE_MOTION; tMs: number; positions: Float32Array }
  | { type: typeof FRAME_TYPE_AUDIO; tMs: number; pcm: Uint8Array }
  | { type: typeof FRAME_TYPE_END; tMs: number };

export function parseFrame(buf: ArrayBuffer): ParsedFrame {
  if (buf.byteLength < 9) {
    throw new Error(`frame too short: ${buf.byteLength}`);
  }
  const view = new DataView(buf);
  const type = view.getUint8(0);
  // big-endian uint64 — JS Number 까지 safe (Number.MAX_SAFE_INTEGER 보다 작음, ~285,616년)
  const tMsBig = view.getBigUint64(1, false);
  const tMs = Number(tMsBig);
  const payloadOffset = 9;
  const payloadLen = buf.byteLength - payloadOffset;

  switch (type) {
    case FRAME_TYPE_HEADER: {
      const json = new TextDecoder().decode(new Uint8Array(buf, payloadOffset, payloadLen));
      return { type: FRAME_TYPE_HEADER, tMs, header: JSON.parse(json) as StreamHeader };
    }
    case FRAME_TYPE_MOTION: {
      // Float32Array 는 4-byte aligned ArrayBuffer 가 필요 — copy.
      const copy = new ArrayBuffer(payloadLen);
      new Uint8Array(copy).set(new Uint8Array(buf, payloadOffset, payloadLen));
      return { type: FRAME_TYPE_MOTION, tMs, positions: new Float32Array(copy) };
    }
    case FRAME_TYPE_AUDIO: {
      return { type: FRAME_TYPE_AUDIO, tMs, pcm: new Uint8Array(buf, payloadOffset, payloadLen) };
    }
    case FRAME_TYPE_END:
      return { type: FRAME_TYPE_END, tMs };
    default:
      throw new Error(`unknown frame type 0x${type.toString(16)}`);
  }
}
