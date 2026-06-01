/**
 * MediaPipe Tasks Vision HandLandmarker wrapper — GPU-delegated, on the MAIN thread.
 *
 * ⚠ A Web-Worker offload was attempted twice (2026-06-01) and FAILS both ways:
 *   - delegate:'GPU'  → "worker init FAILED" (no usable GL context in a worker)
 *   - delegate:'CPU'  → "ModuleFactory not set" (MediaPipe's Emscripten WASM glue
 *                        does not load inside a Vite module worker)
 * So MediaPipe stays on the main thread with the GPU delegate (fastest per-detect →
 * smallest main-thread block). The depth-view lag is reduced INSTEAD by offloading
 * the zstd depth-decompress to a worker (pure JS, works fine) — see useDepthStream.
 *
 * Migrated from @mediapipe/hands (2026-05-27): the old full-model TFLite GPU delegate
 * fought three.js's WebGL context → WASM hard-abort. tasks-vision's `delegate:'GPU'`
 * runs its own isolated GL context. detectForVideo() is SYNCHRONOUS (returns the
 * result directly). Landmarks are normalized [0..1] → convert with image dims.
 */
import { ref, type Ref } from 'vue';
import { HandLandmarker, FilesetResolver } from '@mediapipe/tasks-vision';

export interface HandPoint {
  /** palm center pixel u (0..imageW). */
  u: number;
  /** palm center pixel v (0..imageH). */
  v: number;
  /** all 21 landmarks in pixel space. */
  landmarks: Array<{ u: number; v: number }>;
  /** Left/right handedness classification confidence (0..1) — NOT presence score. */
  score: number;
  /** MediaPipe's left/right classification (SUBJECT view, mirrored). */
  handedness: 'Left' | 'Right' | 'Unknown';
}

export interface UseHandTracker {
  /** First detected hand (back-compat for existing single-hand consumers). */
  hand: Ref<HandPoint | null>;
  /** All detected hands (max 2). Always present, possibly empty. */
  hands: Ref<HandPoint[]>;
  /** True once the WASM + model finished loading. */
  ready: Ref<boolean>;
  /** Returns false if the tracker isn't ready / is dead. */
  detect(img: ImageBitmap | HTMLCanvasElement | HTMLVideoElement): boolean;
  close(): Promise<void>;
}

// CDN paths — same source as the old @mediapipe/hands. WASM + model files.
const WASM_BASE = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10/wasm';
const MODEL_PATH =
  'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task';

export function useHandTracker(): UseHandTracker {
  console.log('[useHandTracker] constructing HandLandmarker (tasks-vision, GPU, main thread)');
  const hand = ref<HandPoint | null>(null);
  const hands = ref<HandPoint[]>([]);
  const ready = ref(false);
  let landmarker: HandLandmarker | null = null;
  let initFailed = false;
  // detectForVideo requires monotonically-increasing timestamps.
  let lastTimestampMs = 0;
  let consecutiveFailures = 0;
  const MAX_CONSECUTIVE_FAILURES = 5;
  let dead = false;

  (async () => {
    try {
      const fileset = await FilesetResolver.forVisionTasks(WASM_BASE);
      landmarker = await HandLandmarker.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: MODEL_PATH, delegate: 'GPU' },
        runningMode: 'VIDEO',
        numHands: 2,
        minHandDetectionConfidence: 0.35,
        minHandPresenceConfidence: 0.35,
        minTrackingConfidence: 0.35,
      });
      ready.value = true;
      console.log('[useHandTracker] HandLandmarker ready (GPU delegate, main thread)');
    } catch (err) {
      initFailed = true;
      console.error('[useHandTracker] init FAILED:', err);
    }
  })();

  function detect(img: ImageBitmap | HTMLCanvasElement | HTMLVideoElement): boolean {
    if (dead || initFailed || landmarker === null) return false;
    let ts = Math.floor(performance.now());
    if (ts <= lastTimestampMs) ts = lastTimestampMs + 1;
    lastTimestampMs = ts;
    try {
      const result = landmarker.detectForVideo(img as unknown as HTMLVideoElement, ts);
      consecutiveFailures = 0;
      const w = (img as { width: number }).width;
      const h = (img as { height: number }).height;
      const N = result.landmarks?.length ?? 0;
      const out: HandPoint[] = [];
      for (let i = 0; i < N; i++) {
        const lms = result.landmarks[i];
        if (!lms || lms.length === 0) continue;
        // Palm center = centroid of the 5 palm-base landmarks (0,5,9,13,17).
        const wrist = lms[0];
        const idxMcp = lms[5];
        const midMcp = lms[9];
        const ringMcp = lms[13];
        const pinkyMcp = lms[17];
        const px = (wrist.x + idxMcp.x + midMcp.x + ringMcp.x + pinkyMcp.x) / 5;
        const py = (wrist.y + idxMcp.y + midMcp.y + ringMcp.y + pinkyMcp.y) / 5;
        const cat = result.handednesses?.[i]?.[0];
        const score = cat?.score ?? 0;
        const handednessLabel = cat?.categoryName === 'Left'
          ? 'Left'
          : cat?.categoryName === 'Right' ? 'Right' : 'Unknown';
        out.push({
          u: px * w,
          v: py * h,
          landmarks: lms.map((l) => ({ u: l.x * w, v: l.y * h })),
          score,
          handedness: handednessLabel,
        });
      }
      hands.value = out;
      hand.value = out[0] ?? null;
      return true;
    } catch (err) {
      consecutiveFailures += 1;
      console.warn(
        `[useHandTracker] detect failed (${consecutiveFailures}/${MAX_CONSECUTIVE_FAILURES}):`,
        err,
      );
      if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
        dead = true;
        hand.value = null;
        hands.value = [];
        console.error('[useHandTracker] tracker dead — reload page');
      }
      return false;
    }
  }

  async function close(): Promise<void> {
    if (landmarker !== null) {
      landmarker.close();
      landmarker = null;
    }
  }

  return { hand, hands, ready, detect, close };
}
