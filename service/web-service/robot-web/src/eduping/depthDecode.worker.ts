/**
 * Depth-frame decoder, off the main thread.
 *
 * The zstd depth decompress (~600KB uint16 per frame, fzstd pure-JS) was a per-frame
 * main-thread cost (~3-5ms @15Hz ≈ 45-75ms/s) competing with the three.js render +
 * the (main-thread, synchronous) MediaPipe detect. fzstd is pure JS — no WASM/GL — so
 * unlike the MediaPipe HandLandmarker it runs fine in a worker. The main thread now
 * just hands the raw WS ArrayBuffer over (transferred) and gets the decoded frame back
 * (depth buffer transferred → zero-copy), then fans it out to its render listeners.
 *
 * Wire format mirrors control_service/streaming/depth_protocol.py encode_depth_frame().
 */
import { decompress as zstdDecompress } from 'fzstd';
import type { DecodedDepthFrame } from './useDepthStream';

const HEADER_SIZE = 60;
const MAGIC = 0x44505448; // "DPTH" big-endian as uint32

function decodeFrame(buf: ArrayBuffer): DecodedDepthFrame | null {
  if (buf.byteLength < HEADER_SIZE) return null;
  const dv = new DataView(buf);
  const magic = dv.getUint32(0, false);
  if (magic !== MAGIC) return null;
  const version = dv.getUint8(4);
  if (version !== 1) return null;
  const frameSeq = dv.getUint32(8, false);
  const tsHi = dv.getUint32(12, false);
  const tsLo = dv.getUint32(16, false);
  const tsMs = tsHi * 0x1_0000_0000 + tsLo;
  const depthW = dv.getUint16(20, false);
  const depthH = dv.getUint16(22, false);
  const colorW = dv.getUint16(24, false);
  const colorH = dv.getUint16(26, false);
  const fx = dv.getFloat32(28, false);
  const fy = dv.getFloat32(32, false);
  const cx = dv.getFloat32(36, false);
  const cy = dv.getFloat32(40, false);
  const depthScale = dv.getFloat32(44, false);
  const depthMinMm = dv.getUint16(48, false);
  const depthMaxMm = dv.getUint16(50, false);
  const depthSize = dv.getUint32(52, false);
  const colorSize = dv.getUint32(56, false);

  if (HEADER_SIZE + depthSize + colorSize !== buf.byteLength) return null;

  const depthZstd = new Uint8Array(buf, HEADER_SIZE, depthSize);
  const colorBytes = new Uint8Array(buf, HEADER_SIZE + depthSize, colorSize);

  let depthRaw: Uint8Array;
  try {
    depthRaw = zstdDecompress(depthZstd);
  } catch (e) {
    console.warn('[depthDecode] zstd decompress failed:', e);
    return null;
  }
  if (depthRaw.byteLength !== depthW * depthH * 2) {
    console.warn(
      `[depthDecode] size mismatch: got ${depthRaw.byteLength}, expected ${depthW * depthH * 2}`,
    );
    return null;
  }
  // wire format = uint16 LE. Copy into a fresh exact buffer so we can transfer it
  // back zero-copy (fzstd's output buffer may not be tightly sized).
  const depth = new Uint16Array(depthW * depthH);
  depth.set(new Uint16Array(depthRaw.buffer, depthRaw.byteOffset, depthW * depthH));

  const colorBlob = new Blob([colorBytes], { type: 'image/jpeg' });

  return {
    frameSeq, tsMs,
    depthW, depthH, colorW, colorH,
    fx, fy, cx, cy, depthScale,
    depthMinMm, depthMaxMm,
    depth, colorBlob,
  };
}

self.onmessage = (e: MessageEvent<ArrayBuffer>) => {
  const frame = decodeFrame(e.data);
  if (frame === null) {
    (self as unknown as Worker).postMessage({ ok: false });
    return;
  }
  (self as unknown as Worker).postMessage({ ok: true, frame }, [frame.depth.buffer]);
};
