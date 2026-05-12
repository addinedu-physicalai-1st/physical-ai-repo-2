/**
 * 자연 촬영 — 노트북 내장 카메라 video stream 에서 happy/sad 표정을 검출하고
 * 임계 초과 시 단일 프레임을 캡처해 Control Server 로 업로드한다.
 *
 * 사용처: NoriArm UI 의 OX 퀴즈 — 게임 한 세션당 최대 1장.
 *
 * 동작:
 *   - face-api.js (TinyFaceDetector + FaceExpressionNet) 를 lazy 로드해 5fps 추론
 *   - happy ≥ 0.75 또는 sad ≥ 0.60 가 연속 3프레임 지속되면 캡처 1회
 *   - 캡처 후 검출 루프 정지 — 한 세션당 1장 락 (`captured.value = true`)
 *   - 모드 이탈 시 외부에서 `reset()` 호출해 다시 1장 가능
 */
import { computed, onUnmounted, ref, shallowRef } from 'vue';

const MODEL_URL = '/models/face-api';
const INFER_INTERVAL_MS = 200; // 5 fps
const SUSTAIN_FRAMES = 3; // ~600ms 연속 지속
const HAPPY_THRESHOLD = 0.75;
const SAD_THRESHOLD = 0.6;
const JPEG_QUALITY = 0.82;
const MAX_WIDTH = 640;

type FaceApi = typeof import('@vladmandic/face-api');

// 모듈 전역 — face-api 모델은 무거우니 한 번만 로드.
let _faceApi: FaceApi | null = null;
let _modelLoadPromise: Promise<FaceApi> | null = null;

async function loadFaceApi(): Promise<FaceApi> {
  if (_faceApi) return _faceApi;
  if (_modelLoadPromise) return _modelLoadPromise;
  _modelLoadPromise = (async () => {
    const mod = await import('@vladmandic/face-api');
    await Promise.all([
      mod.nets.tinyFaceDetector.loadFromUri(MODEL_URL),
      mod.nets.faceExpressionNet.loadFromUri(MODEL_URL),
    ]);
    _faceApi = mod;
    return mod;
  })();
  return _modelLoadPromise;
}

export interface EmotionCaptureOptions {
  robot: string; // "noriarm"
  mode: string; // "ox-quiz" (서버 파일명 슬러그용)
  /** 검출 시작 — 부모가 phase 등 외부 조건으로 토글 */
  enabled: () => boolean;
  /** 캡처가 성공했을 때 부모에게 알림 */
  onCaptured?: (info: { emotion: 'happy' | 'sad'; score: number; photoId: number; url: string }) => void;
}

export interface EmotionCaptureHandle {
  /** video element 를 전달해 검출 시작. 같은 stream 위에 추론 루프 attach. */
  attach: (video: HTMLVideoElement) => void;
  /** stream detach + 추론 정지. 모드 이탈·언마운트 시 호출. */
  detach: () => void;
  /** 세션 락 해제 — 다음 세션에서 다시 1장 가능. */
  reset: () => void;
  /** 한 번 캡처됐는지 (UI 의 "사진 N장 찍었어요" 라인용) */
  captured: import('vue').Ref<boolean>;
  /** 마지막 캡처된 감정 (라벨 토스트용) */
  lastEmotion: import('vue').Ref<'happy' | 'sad' | null>;
  /** 셔터 플래시 트리거 (UI 가 watch 해서 CSS 애니메이션 발동). 캡처 직후 1회 토글. */
  flashTick: import('vue').Ref<number>;
  /** 모델 로드·카메라 권한 등에서 막혔는지 (UI 가 회색 처리 등에 사용 가능) */
  ready: import('vue').ComputedRef<boolean>;
}

export function useEmotionCapture(options: EmotionCaptureOptions): EmotionCaptureHandle {
  const captured = ref(false);
  const lastEmotion = ref<'happy' | 'sad' | null>(null);
  const flashTick = ref(0);
  const modelLoaded = ref(false);
  const videoRef = shallowRef<HTMLVideoElement | null>(null);
  let timer: number | null = null;
  let sustainCount = 0;
  let sustainEmotion: 'happy' | 'sad' | null = null;
  let inflight = false;
  let sessionId = crypto.randomUUID();

  async function ensureModels(): Promise<FaceApi | null> {
    try {
      const api = await loadFaceApi();
      modelLoaded.value = true;
      return api;
    } catch (err) {
      console.warn('[useEmotionCapture] face-api load failed', err);
      return null;
    }
  }

  function clearLoop(): void {
    if (timer != null) {
      window.clearInterval(timer);
      timer = null;
    }
    sustainCount = 0;
    sustainEmotion = null;
  }

  async function tick(): Promise<void> {
    if (inflight) return;
    if (captured.value) return; // 락 — 세션당 1장
    if (!options.enabled()) return;
    const video = videoRef.value;
    if (!video || video.readyState < 2 || video.videoWidth === 0) return;
    const api = _faceApi;
    if (!api) return;
    inflight = true;
    try {
      const result = await api
        .detectSingleFace(video, new api.TinyFaceDetectorOptions({ inputSize: 224, scoreThreshold: 0.5 }))
        .withFaceExpressions();
      if (!result) {
        sustainCount = 0;
        sustainEmotion = null;
        return;
      }
      const exp = result.expressions;
      // FaceExpressions 의 7 클래스 중 happy/sad 만 트리거
      const happy = exp.happy ?? 0;
      const sad = exp.sad ?? 0;
      let hit: 'happy' | 'sad' | null = null;
      let hitScore = 0;
      if (happy >= HAPPY_THRESHOLD) {
        hit = 'happy';
        hitScore = happy;
      } else if (sad >= SAD_THRESHOLD) {
        hit = 'sad';
        hitScore = sad;
      }
      if (hit === null) {
        sustainCount = 0;
        sustainEmotion = null;
        return;
      }
      if (sustainEmotion !== hit) {
        sustainEmotion = hit;
        sustainCount = 1;
      } else {
        sustainCount += 1;
      }
      if (sustainCount >= SUSTAIN_FRAMES) {
        // 캡처 + 업로드. 임계 만족 — 락을 즉시 걸어 중복 호출 방지.
        captured.value = true;
        clearLoop();
        const ok = await captureAndUpload(video, hit, hitScore);
        if (!ok) {
          // 업로드 실패 시 락 해제해서 다음 임계 초과 때 재시도
          captured.value = false;
        }
      }
    } catch (err) {
      // 단일 프레임 추론 실패는 로깅만 — 다음 tick 으로 회복
      console.debug('[useEmotionCapture] inference err', err);
    } finally {
      inflight = false;
    }
  }

  async function captureAndUpload(
    video: HTMLVideoElement,
    emotion: 'happy' | 'sad',
    score: number,
  ): Promise<boolean> {
    const blob = await snapshotJpeg(video);
    if (!blob) return false;
    try {
      const form = new FormData();
      form.append('file', blob, 'shot.jpg');
      form.append('robot', options.robot);
      form.append('mode', options.mode);
      form.append('emotion', emotion);
      form.append('score', String(score));
      form.append('session_id', sessionId);
      const r = await fetch('/api/photos/natural', { method: 'POST', body: form });
      if (!r.ok) return false;
      const data = (await r.json()) as { photo_id: number; url: string };
      lastEmotion.value = emotion;
      flashTick.value += 1;
      options.onCaptured?.({ emotion, score, photoId: data.photo_id, url: data.url });
      return true;
    } catch (err) {
      console.warn('[useEmotionCapture] upload failed', err);
      return false;
    }
  }

  async function snapshotJpeg(video: HTMLVideoElement): Promise<Blob | null> {
    const vw = video.videoWidth;
    const vh = video.videoHeight;
    if (vw === 0 || vh === 0) return null;
    const scale = Math.min(1, MAX_WIDTH / vw);
    const w = Math.round(vw * scale);
    const h = Math.round(vh * scale);
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    ctx.drawImage(video, 0, 0, w, h);
    return new Promise<Blob | null>((resolve) => {
      canvas.toBlob((b) => resolve(b), 'image/jpeg', JPEG_QUALITY);
    });
  }

  function attach(video: HTMLVideoElement): void {
    videoRef.value = video;
    if (timer != null) return;
    void ensureModels().then((api) => {
      if (!api) return;
      timer = window.setInterval(() => {
        void tick();
      }, INFER_INTERVAL_MS);
    });
  }

  function detach(): void {
    clearLoop();
    videoRef.value = null;
  }

  function reset(): void {
    captured.value = false;
    lastEmotion.value = null;
    sustainCount = 0;
    sustainEmotion = null;
    sessionId = crypto.randomUUID();
  }

  const ready = computed(() => modelLoaded.value);

  onUnmounted(() => {
    clearLoop();
  });

  return { attach, detach, reset, captured, lastEmotion, flashTick, ready };
}
