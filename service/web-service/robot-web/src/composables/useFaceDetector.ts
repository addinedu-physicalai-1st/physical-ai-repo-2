/**
 * MediaPipe FaceDetection 래퍼 — `<video>` 또는 `<img>` 입력 frame 에서 face bbox 추출.
 *
 * 사용처 (AttendanceCamera, MugunghwaGame, RecruitPhase) 가 매 frame 자체적으로
 * requestAnimationFrame 루프를 돌므로 본 컴포저블은 send/onResults 만 노출.
 *
 * ⚠ 2026-06-01: tasks-vision FaceDetector 로 이관했다가 되돌림. tasks-vision 의
 * GPU delegate 는 자체 GL context 를 만드는데, AttendanceCamera 처럼 three.js WebGL
 * 이 없는 (2D canvas 만 있는) 화면에선 검출이 조용히 no-op 돼 "얼굴 인식 중…" 이
 * 영원히 안 풀렸다. solutions API (FaceDetection) 는 자체 WASM/GL 로 host context 없이
 * 동작 → 등원/하원/무궁화에서 검증된 경로라 이걸 유지한다.
 */
import { FaceDetection, type Detection, type Results } from '@mediapipe/face_detection';
import type { Bbox } from './useFaceTracker';

export interface UseFaceDetectorOptions {
  /** 'short' = 2m 이내 가까운 거리 (default), 'full' = 5m 이내. */
  model?: 'short' | 'full';
  /** 검출 confidence 임계 (0..1, default 0.6). */
  minDetectionConfidence?: number;
  /** 검출된 bbox 리스트 콜백. 매 frame 호출됨. */
  onDetections: (faces: Array<{ bbox: Bbox; score: number }>) => void;
}

export function useFaceDetector(opts: UseFaceDetectorOptions): {
  start(): void;
  send(image: HTMLVideoElement | HTMLImageElement | HTMLCanvasElement): Promise<void>;
  close(): void;
} {
  let detector: FaceDetection | null = null;

  function start(): void {
    if (detector) return;
    detector = new FaceDetection({
      locateFile: (file) =>
        `https://cdn.jsdelivr.net/npm/@mediapipe/face_detection@0.4/${file}`,
    });
    detector.setOptions({
      model: opts.model ?? 'short',
      minDetectionConfidence: opts.minDetectionConfidence ?? 0.6,
    });
    detector.onResults((results: Results) => {
      const faces: Array<{ bbox: Bbox; score: number }> = [];
      // Results.image 는 GpuBuffer (HTMLCanvasElement | HTMLImageElement | ImageBitmap).
      // 세 타입 모두 런타임에서 .width / .height 를 지원하지만 TypeScript 공용 타입에선
      // 불완전하므로 unknown 을 경유해 캐스팅한다.
      const img = results.image as unknown as { width: number; height: number };
      const w = img.width;
      const h = img.height;
      for (const d of (results.detections ?? []) as Detection[]) {
        const rb = d.boundingBox;
        if (!rb) continue;
        // MediaPipe bbox 는 정규화 좌표 (0..1). image 크기로 픽셀 변환.
        const x1 = (rb.xCenter - rb.width / 2) * w;
        const y1 = (rb.yCenter - rb.height / 2) * h;
        const x2 = (rb.xCenter + rb.width / 2) * w;
        const y2 = (rb.yCenter + rb.height / 2) * h;
        // Detection 타입 정의에 score 필드가 없으나 런타임 객체에는 존재한다.
        // unknown 경유 캐스팅으로 안전하게 추출.
        const score = ((d as unknown as Record<string, unknown>)['score'] as number[] | undefined)?.[0] ?? 0;
        faces.push({ bbox: [x1, y1, x2, y2], score });
      }
      opts.onDetections(faces);
    });
  }

  async function send(image: HTMLVideoElement | HTMLImageElement | HTMLCanvasElement): Promise<void> {
    if (!detector) return;
    await detector.send({ image });
  }

  function close(): void {
    if (detector) {
      void detector.close();
      detector = null;
    }
  }

  return { start, send, close };
}
