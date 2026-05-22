/**
 * MediaPipe Hands wrapper — 손 1개 (max) lite 모델 트래커.
 *
 * 결과는 reactive ref `hand` 에 푸시. 매 frame send 안 함 — 이미 처리 중이면 skip
 * (`detect` 가 false 반환). DepthViewer 가 자체 throttle (3frame 마다 호출) + busy
 * guard 의 이중 안전망.
 *
 * locateFile 은 noriarm/OXVisionPreview.vue 와 동일 CDN.
 */
import { ref, type Ref } from 'vue';
import { Hands, type Results } from '@mediapipe/hands';

export interface HandPoint {
  /** palm center pixel u (0..imageW) — landmark 9 (middle MCP). */
  u: number;
  /** palm center pixel v (0..imageH). */
  v: number;
  /** all 21 landmarks in pixel space. */
  landmarks: Array<{ u: number; v: number }>;
  /** detection confidence (left/right handedness score). */
  score: number;
}

export interface UseHandTracker {
  hand: Ref<HandPoint | null>;
  /** Returns false if previous detect still pending (skip). */
  detect(img: ImageBitmap | HTMLCanvasElement | HTMLVideoElement): boolean;
  close(): Promise<void>;
}

export function useHandTracker(): UseHandTracker {
  const hands = new Hands({
    locateFile: (file) =>
      `https://cdn.jsdelivr.net/npm/@mediapipe/hands@0.4/${file}`,
  });
  hands.setOptions({
    maxNumHands: 1,
    modelComplexity: 0,         // 0=lite (5–10ms/frame on mid laptop)
    minDetectionConfidence: 0.5,
    minTrackingConfidence: 0.5,
  });

  const hand = ref<HandPoint | null>(null);
  let busy = false;

  hands.onResults((results: Results) => {
    busy = false;
    const lms = results.multiHandLandmarks?.[0];
    if (!lms || lms.length === 0) {
      hand.value = null;
      return;
    }
    const img = results.image as ImageBitmap | HTMLCanvasElement;
    const w = (img as { width: number }).width;
    const h = (img as { height: number }).height;
    const palm = lms[9];
    const score = results.multiHandedness?.[0]?.score ?? 0;
    hand.value = {
      u: palm.x * w,
      v: palm.y * h,
      landmarks: lms.map((l) => ({ u: l.x * w, v: l.y * h })),
      score,
    };
  });

  function detect(img: ImageBitmap | HTMLCanvasElement | HTMLVideoElement): boolean {
    if (busy) return false;
    busy = true;
    // MediaPipe runtime accepts ImageBitmap (verified in shipped solutions API)
    // but the TS types only allow HTMLImageElement | HTMLVideoElement | HTMLCanvasElement.
    hands.send({ image: img as unknown as HTMLImageElement }).catch((e) => {
      console.warn('hands.send failed:', e);
      busy = false;
    });
    return true;
  }

  async function close(): Promise<void> {
    await hands.close();
  }

  return { hand, detect, close };
}
