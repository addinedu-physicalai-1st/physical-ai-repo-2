import { describe, expect, it } from 'vitest';
import {
  FRAME_TYPE_AUDIO,
  FRAME_TYPE_END,
  FRAME_TYPE_HEADER,
  FRAME_TYPE_MOTION,
  parseFrame,
  type StreamHeader,
} from '../src/eduping/danceStreamFraming';

function makeFrame(type: number, tMs: number, payload: ArrayBuffer | Uint8Array): ArrayBuffer {
  const body = payload instanceof ArrayBuffer ? new Uint8Array(payload) : payload;
  const buf = new ArrayBuffer(9 + body.byteLength);
  const view = new DataView(buf);
  view.setUint8(0, type);
  view.setBigUint64(1, BigInt(tMs), false); // big-endian
  new Uint8Array(buf, 9).set(body);
  return buf;
}

describe('parseFrame', () => {
  it('parses header frame to JSON metadata', () => {
    const meta: StreamHeader = {
      slug: 'x',
      sample_rate: 16000,
      motion_hz: 50,
      tick_ms: 20,
      joint_names: ['j1', 'j2'],
      motion_duration_s: 1.0,
      audio_duration_s: 1.0,
    };
    const payload = new TextEncoder().encode(JSON.stringify(meta));
    const f = makeFrame(FRAME_TYPE_HEADER, 0, payload);
    const parsed = parseFrame(f);
    expect(parsed.type).toBe(FRAME_TYPE_HEADER);
    expect(parsed.tMs).toBe(0);
    expect((parsed as { header: StreamHeader }).header.sample_rate).toBe(16000);
  });

  it('parses motion frame to Float32Array', () => {
    const floats = new Float32Array([0.1, -0.2, 0.3]);
    const f = makeFrame(FRAME_TYPE_MOTION, 200, floats.buffer);
    const parsed = parseFrame(f);
    expect(parsed.type).toBe(FRAME_TYPE_MOTION);
    expect(parsed.tMs).toBe(200);
    const positions = (parsed as { positions: Float32Array }).positions;
    expect(positions.length).toBe(3);
    expect(positions[1]).toBeCloseTo(-0.2);
  });

  it('parses audio frame to PCM bytes (s16le)', () => {
    const pcm = new Uint8Array([0x10, 0x20, 0x30, 0x40]);
    const f = makeFrame(FRAME_TYPE_AUDIO, 20, pcm);
    const parsed = parseFrame(f);
    expect(parsed.type).toBe(FRAME_TYPE_AUDIO);
    expect((parsed as { pcm: Uint8Array }).pcm.byteLength).toBe(4);
  });

  it('parses end frame', () => {
    const f = makeFrame(FRAME_TYPE_END, 1000, new Uint8Array());
    const parsed = parseFrame(f);
    expect(parsed.type).toBe(FRAME_TYPE_END);
    expect(parsed.tMs).toBe(1000);
  });

  it('throws on frame shorter than 9 bytes', () => {
    const short = new ArrayBuffer(5);
    expect(() => parseFrame(short)).toThrow(/too short/);
  });

  it('throws on unknown frame type', () => {
    // 0xff is not in {0x01, 0x02, 0x03, 0x04}
    const buf = new ArrayBuffer(9);
    new DataView(buf).setUint8(0, 0xff);
    expect(() => parseFrame(buf)).toThrow(/unknown frame type/);
  });
});
