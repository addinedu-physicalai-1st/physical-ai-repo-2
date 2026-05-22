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
  /** MediaPipe 가 `onResults` 를 최소 1회 호출했는지 — model 다운로드 + WebGL 컨텍스트
   *  초기화가 끝났다는 신호. 손이 실제로 검출됐는지와는 무관. UI 의 'loading…' 표시
   *  해제용으로 사용한다 (손이 안 보여도 트래커는 살아있음). */
  ready: Ref<boolean>;
  /** Returns false if previous detect still pending (skip). */
  detect(img: ImageBitmap | HTMLCanvasElement | HTMLVideoElement): boolean;
  close(): Promise<void>;
}

export function useHandTracker(): UseHandTracker {
  console.log('[useHandTracker] constructing Hands instance');
  const hands = new Hands({
    locateFile: (file) => {
      const url = `https://cdn.jsdelivr.net/npm/@mediapipe/hands@0.4/${file}`;
      console.log('[useHandTracker] locateFile →', url);
      return url;
    },
  });
  hands.setOptions({
    maxNumHands: 1,
    modelComplexity: 0,         // 0=lite (5–10ms/frame on mid laptop)
    minDetectionConfidence: 0.5,
    minTrackingConfidence: 0.5,
  });

  const hand = ref<HandPoint | null>(null);
  const ready = ref(false);
  let busy = false;

  // Force the WASM + model download up-front via initialize(). Otherwise the first
  // hands.send() implicitly triggers init but if WASM fails to load (CDN block,
  // network), send() never resolves and onResults never fires → loading 무한.
  // initialize() returns a Promise we can hook up to set ready independently of
  // actual hand detections.
  hands
    .initialize()
    .then(() => {
      console.log('[useHandTracker] MediaPipe Hands ready (WASM + model loaded)');
      if (!ready.value) ready.value = true;
    })
    .catch((err) => {
      console.error('[useHandTracker] MediaPipe Hands init FAILED:', err);
      // ready 그대로 false — UI 'loading…' 으로 남아 사용자에게 시각 신호.
    });

  hands.onResults((results: Results) => {
    busy = false;
    if (!ready.value) ready.value = true;
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

  let firstSendLogged = false;
  function detect(img: ImageBitmap | HTMLCanvasElement | HTMLVideoElement): boolean {
    if (busy) return false;
    if (!firstSendLogged) {
      console.log('[useHandTracker] first detect() call — passing image to MediaPipe');
      firstSendLogged = true;
    }
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

  return { hand, ready, detect, close };
}
