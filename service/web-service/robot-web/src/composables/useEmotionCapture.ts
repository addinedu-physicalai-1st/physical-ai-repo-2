/**
 * 자연 촬영 — 노트북 내장 카메라 video stream 에서 happy/sad 표정을 검출하고
 * 임계 초과 시 JPEG 를 캡처해 Control Server 로 업로드한다.
 *
 * 사용처: NoriArm UI 의 OX 퀴즈 등 — 세션 동안 표정이 다시 잡히면 추가 촬영 가능.
 *
 * 동작:
 *   - face-api.js (TinyFaceDetector + FaceExpressionNet) 를 lazy 로드해 5fps 추론
 *   - happy/sad 가 임계 이상으로 연속 SUSTAIN_FRAMES 프레임 지속되면 JPEG 업로드 1회
 *   - 업로드 성공 후 CAPTURE_COOLDOWN_MS 동안은 재촬영만 막고, 추론 루프는 유지 (HUD 갱신)
 *   - 모드 이탈 시 `reset()` 으로 쿨다운·누적 상태 초기화
 */
import { computed, onUnmounted, ref, shallowRef } from 'vue';

const MODEL_URL = '/models/face-api';
const INFER_INTERVAL_MS = 200; // 5 fps
const SUSTAIN_FRAMES = 3; // ~600ms 연속 지속
/** 직전 업로드 직후 같은 표정으로 연속 저장되는 것 방지 */
const CAPTURE_COOLDOWN_MS = 2800;
/** 너무 높으면 자연스러운 미소에서도 태그/업로드가 거의 안 뜸 */
const HAPPY_THRESHOLD = 0.62;
const SAD_THRESHOLD = 0.48;
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
  /** 추론 주기(ms). 기본 200(5fps). 율동처럼 다른 무거운 루프와 공존할 때 늘려서 GPU 경합 줄임. */
  inferIntervalMs?: number;
}

export interface EmotionCaptureHandle {
  /** video element 를 전달해 검출 시작. 같은 stream 위에 추론 루프 attach. */
  attach: (video: HTMLVideoElement) => void;
  /** stream detach + 추론 정지. 모드 이탈·언마운트 시 호출. */
  detach: () => void;
  /** 세션 상태 초기화 — 쿨다운·누적 해제 후 다시 촬영 가능. */
  reset: () => void;
  /** 한 번이라도 성공 업로드가 있었는지 (짧은 피드백·스타일용; 쿨다운 후에도 true 유지 가능) */
  captured: import('vue').Ref<boolean>;
  /** 마지막 캡처된 감정 (라벨 토스트용) */
  lastEmotion: import('vue').Ref<'happy' | 'sad' | null>;
  /** 셔터 플래시 트리거 (UI 가 watch 해서 CSS 애니메이션 발동). 캡처 직후 1회 토글. */
  flashTick: import('vue').Ref<number>;
  /** 모델 로드·카메라 권한 등에서 막혔는지 (UI 가 회색 처리 등에 사용 가능) */
  ready: import('vue').ComputedRef<boolean>;
  /** 현재 프레임에서 얼굴 검출 여부 — 라이브 HUD (촬영 전에도 표시) */
  faceDetected: import('vue').Ref<boolean>;
  liveHappy: import('vue').Ref<number>;
  liveSad: import('vue').Ref<number>;
  /** 임계 만족 중 연속 프레임 수 (촬영 직전 1…SUSTAIN_FRAMES) */
  sustainProgress: import('vue').Ref<number>;
  /** 업로드 실패 시 짧은 메시지; 성공 시 null */
  uploadError: import('vue').Ref<string | null>;
  /** 직전 촬영 업로드 후 쿨다운 중 — HUD 는 숨기고 얼굴 비율 표시는 유지 */
  inCaptureCooldown: import('vue').Ref<boolean>;
}

export function useEmotionCapture(options: EmotionCaptureOptions): EmotionCaptureHandle {
  const captured = ref(false);
  const lastEmotion = ref<'happy' | 'sad' | null>(null);
  const flashTick = ref(0);
  const modelLoaded = ref(false);
  const faceDetected = ref(false);
  const liveHappy = ref(0);
  const liveSad = ref(0);
  const sustainProgress = ref(0);
  const uploadError = ref<string | null>(null);
  const inCaptureCooldown = ref(false);
  const videoRef = shallowRef<HTMLVideoElement | null>(null);
  let timer: number | null = null;
  let sustainCount = 0;
  let sustainEmotion: 'happy' | 'sad' | null = null;
  let inflight = false;
  let captureCooldownUntil = 0;
  let cooldownClearTimer: number | null = null;

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
    if (cooldownClearTimer != null) {
      window.clearTimeout(cooldownClearTimer);
      cooldownClearTimer = null;
    }
    sustainCount = 0;
    sustainEmotion = null;
    sustainProgress.value = 0;
  }

  async function tick(): Promise<void> {
    if (inflight) return;
    if (!options.enabled()) {
      faceDetected.value = false;
      liveHappy.value = 0;
      liveSad.value = 0;
      sustainProgress.value = 0;
      sustainCount = 0;
      sustainEmotion = null;
      return;
    }
    const video = videoRef.value;
    if (!video || video.readyState < 2 || video.videoWidth === 0) return;
    const api = _faceApi;
    if (!api) return;
    inflight = true;
    // 추론 전 한 프레임 yield — driveMotion rAF 등 렌더링 콜백이 먼저 실행되도록.
    // WebGL readback(gl.readPixels)이 메인 스레드를 블록하기 전에 rAF 를 소진시켜
    // 율동 모션·오디오 싱크 지연을 최소화한다.
    await new Promise<void>((r) => requestAnimationFrame(r));
    const nowMs = Date.now();
    const inCooldown = nowMs < captureCooldownUntil;
    try {
      // inputSize 416: 작은 얼굴(무궁화·율동처럼 아이가 카메라에서 떨어져 있는 경우)도
      // 잡히게 함. 320 → 416 으로 추론 비용은 ~1.7× 늘지만 5fps 라 무리 없음.
      // scoreThreshold 0.25: 옆모습·부분 가림 등 약한 신호도 후보로 — emotion 임계는
      // 별도 (HAPPY/SAD_THRESHOLD) 라 false-positive 영향 적음.
      const result = await api
        .detectSingleFace(
          video,
          new api.TinyFaceDetectorOptions({ inputSize: 416, scoreThreshold: 0.25 }),
        )
        .withFaceExpressions();
      if (!result) {
        sustainCount = 0;
        sustainEmotion = null;
        faceDetected.value = false;
        liveHappy.value = 0;
        liveSad.value = 0;
        sustainProgress.value = 0;
        return;
      }
      const exp = result.expressions;
      // FaceExpressions 의 7 클래스 중 happy/sad 만 트리거
      const happy = exp.happy ?? 0;
      const sad = exp.sad ?? 0;
      faceDetected.value = true;
      liveHappy.value = happy;
      liveSad.value = sad;
      if (inCooldown) {
        sustainCount = 0;
        sustainEmotion = null;
        sustainProgress.value = 0;
        return;
      }
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
        sustainProgress.value = 0;
        return;
      }
      if (sustainEmotion !== hit) {
        sustainEmotion = hit;
        sustainCount = 1;
      } else {
        sustainCount += 1;
      }
      sustainProgress.value = sustainCount;
      if (sustainCount >= SUSTAIN_FRAMES) {
        sustainCount = 0;
        sustainEmotion = null;
        sustainProgress.value = 0;
        const ok = await captureAndUpload(video, hit, hitScore);
        if (ok) {
          captured.value = true;
          captureCooldownUntil = Date.now() + CAPTURE_COOLDOWN_MS;
          inCaptureCooldown.value = true;
          if (cooldownClearTimer != null) window.clearTimeout(cooldownClearTimer);
          cooldownClearTimer = window.setTimeout(() => {
            cooldownClearTimer = null;
            inCaptureCooldown.value = false;
            captureCooldownUntil = 0;
          }, CAPTURE_COOLDOWN_MS);
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
    uploadError.value = null;
    try {
      const form = new FormData();
      form.append('file', blob, 'shot.jpg');
      form.append('robot', options.robot);
      form.append('mode', options.mode);
      form.append('emotion', emotion);
      form.append('score', String(score));
      // 매 캡처마다 fresh UUID — 한 게임 안에서 happy/sad 가 여러 번 잡힐 때 각각 다른 Photo 행으로
      // 저장되어야 한다. 같은 sessionId 를 재사용하면 backend 가 trigger_session_id idempotency
      // 로 이전 행만 돌려줘서 한 게임당 1장만 DB 에 남는 사고가 있었음.
      form.append('session_id', crypto.randomUUID());
      const r = await fetch('/api/photos/natural', { method: 'POST', body: form });
      if (!r.ok) {
        uploadError.value = `사진 저장 실패 (${r.status})`;
        return false;
      }
      const data = (await r.json()) as { photo_id: number; url: string };
      lastEmotion.value = emotion;
      flashTick.value += 1;
      options.onCaptured?.({ emotion, score, photoId: data.photo_id, url: data.url });
      return true;
    } catch (err) {
      uploadError.value = '사진 저장에 연결하지 못했어요';
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
      }, options.inferIntervalMs ?? INFER_INTERVAL_MS);
    });
  }

  function detach(): void {
    clearLoop();
    inCaptureCooldown.value = false;
    captureCooldownUntil = 0;
    videoRef.value = null;
  }

  function reset(): void {
    captured.value = false;
    lastEmotion.value = null;
    sustainCount = 0;
    sustainEmotion = null;
    sustainProgress.value = 0;
    uploadError.value = null;
    captureCooldownUntil = 0;
    inCaptureCooldown.value = false;
    if (cooldownClearTimer != null) {
      window.clearTimeout(cooldownClearTimer);
      cooldownClearTimer = null;
    }
  }

  const ready = computed(() => modelLoaded.value);

  onUnmounted(() => {
    clearLoop();
  });

  return {
    attach,
    detach,
    reset,
    captured,
    lastEmotion,
    flashTick,
    ready,
    faceDetected,
    liveHappy,
    liveSad,
    sustainProgress,
    uploadError,
    inCaptureCooldown,
  };
}
