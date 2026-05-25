/**
 * 술래잡기 순찰/복귀 단계의 연속 얼굴 인식 파이프라인.
 * RecruitPhase 와 동일한 4 부품 (useFaceDetector + useFaceTracker +
 * useFaceIdentityCache + postRecognizeMulti) 사용. 매칭 결과를 등록자+미잡힘
 * 필터링 후 onCaught 콜백으로 발화.
 *
 * 모집 단계 (RecruitPhase) 는 카메라 정지 상태 (사람 모이는 곳) — STABLE 5 프레임.
 * 본 composable 은 로봇이 움직이는 중 (sweep + 노드 간 이동) 도 인식 — bbox 흔들림
 * 고려해 STABLE_FRAMES_REQUIRED 를 3 으로 낮춤.
 */
import { type Ref } from 'vue';
import { useFaceDetector } from '@/composables/useFaceDetector';
import { useFaceTracker, type TrackedFace } from '@/composables/useFaceTracker';
import { useFaceIdentityCache, type IdentityResult } from '@/composables/useFaceIdentityCache';
import { mapMatchesToTracks, postRecognizeMulti } from '@/composables/identifyTracksFromFrame';

const DEVICE_TOKEN = import.meta.env.VITE_ROBOT_TOKEN ?? 'dev-robot-token-change-me';
const STABLE_FRAMES_REQUIRED = 3;

export interface HideSeekRecognitionOptions {
  imgEl: Ref<HTMLImageElement | null>;
  captureCanvas: Ref<HTMLCanvasElement | null>;
  isRegistered: (childId: number) => boolean;
  isCaught: (childId: number) => boolean;
  onCaught: (childId: number, childName: string) => void;
}

export interface HideSeekRecognitionHandle {
  start: () => void;
  stop: () => void;
}

export function useHideSeekRecognition(
  opts: HideSeekRecognitionOptions,
): HideSeekRecognitionHandle {
  const tracker = useFaceTracker();
  let latestTracks: TrackedFace[] = [];

  const identityCache = useFaceIdentityCache({
    stableFramesRequired: STABLE_FRAMES_REQUIRED,
    identify: async (tracks): Promise<IdentityResult[]> => {
      const canvas = opts.captureCanvas.value;
      if (!canvas) return [];
      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob((b) => resolve(b), 'image/jpeg', 0.85),
      );
      if (!blob) return [];
      const matches = await postRecognizeMulti(blob, DEVICE_TOKEN);
      return mapMatchesToTracks(tracks, matches).map((p) => p.result);
    },
  });

  const detector = useFaceDetector({
    onDetections: (faces) => {
      latestTracks = tracker.update(faces.map((f) => ({ bbox: f.bbox })));
      void identityCache.feed(latestTracks).then(applyCaught);
    },
  });

  function applyCaught(): void {
    for (const t of latestTracks) {
      const childId = identityCache.getChildId(t.trackId);
      if (childId == null) continue;
      if (!opts.isRegistered(childId)) continue;
      if (opts.isCaught(childId)) continue;
      // bindings 의 childName 사용 (failed 가 아니라면 존재)
      const binding = identityCache.bindings.value.get(t.trackId);
      const childName = binding?.childName ?? `child_${childId}`;
      opts.onCaught(childId, childName);
    }
  }

  let rafId: number | null = null;

  async function loop(): Promise<void> {
    const img = opts.imgEl.value;
    const canvas = opts.captureCanvas.value;
    if (img && canvas && img.complete && img.naturalWidth > 0) {
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;
      const ctx = canvas.getContext('2d');
      if (ctx) {
        ctx.drawImage(img, 0, 0);
        try { await detector.send(canvas); } catch { /* noop */ }
      }
    }
    rafId = requestAnimationFrame(() => { void loop(); });
  }

  function start(): void {
    detector.start();
    rafId = requestAnimationFrame(() => { void loop(); });
  }

  function stop(): void {
    if (rafId !== null) cancelAnimationFrame(rafId);
    rafId = null;
    detector.close();
    tracker.reset();
    identityCache.reset();
    latestTracks = [];
  }

  return { start, stop };
}
