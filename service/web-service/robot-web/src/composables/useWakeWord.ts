/**
 * 호출어 인식 (onnxruntime-web) — 마이크 PCM 을 melspec → embedding → robot 별 binary
 * 분류기로 흘려서, 점수가 임계값을 넘으면 onWake(robotId) 콜백을 발행한다.
 *
 * 파이프라인 데이터 흐름:
 *   AudioContext(sampleRate=16000) → AudioWorkletNode (wake-pcm-worklet) →
 *   80ms (1280-sample) chunk → AudioRing(12560 samples = 785ms) →
 *   melspec ONNX → 76 mel frames → embedding ONNX → 1 embed frame →
 *   EmbedRing(16 frames × 96 dim) → robot 별 분류기 ONNX → score →
 *   decideWakeHits → onWake.
 *
 * 디자인 메모:
 *   - 호출 위치 (useVoiceController) 가 STT MediaStream 을 별개로 잡으므로 이 모듈도
 *     자기 stream 을 따로 잡는다. 브라우저가 동일 마이크 다중 소비를 처리한다.
 *   - 모델 5 개는 `start()` 첫 호출 시 lazy 로딩. 이후 호출은 재사용.
 *   - score 계산은 worklet 메시지마다 = ~80ms 주기. UI thread 의 ONNX 추론 비용은
 *     CPU 0.x% 수준 (5MB 모델, 1 inference 마다 수 ms).
 */
import { onBeforeUnmount, ref, type Ref } from 'vue';
import * as ort from 'onnxruntime-web';
import {
  AudioRing,
  EmbedRing,
  decideWakeHits,
  type WakeHit,
} from './wakeBuffers';

// onnxruntime-web 의 WASM/glue 파일 (ort-wasm-*.wasm, *.mjs) 은 ort 내부 dynamic
// import 로 받아온다. Vite 가 public/ 의 .mjs 를 import 경로로 거부하므로 CDN 으로
// 우회. 오프라인 배포가 필요해지면 별도 mirror 호스트를 두고 여기서 그 URL 로 교체.
ort.env.wasm.wasmPaths =
  'https://cdn.jsdelivr.net/npm/onnxruntime-web@1.26.0/dist/';

const SAMPLE_RATE = 16000;
const HOP_SAMPLES = 1280; // 80ms — must match worklet
// 학습 측 (extract_features.py clip_seconds=2.7) 과 동일한 길이의 audio 로 melspec
// 호출해야 동일 spectral 분포가 나옴. AudioRing 짧으면 melspec ONNX 가 짧은 input
// 으로 producing 한 frame 들이 학습 시 frame 분포와 어긋나 score 가 0 에 머무른다.
const AUDIO_RING_SAMPLES = 43200; // 2.7s — matches train clip_seconds=2.7
// 학습 측 _get_embeddings: 76-frame mel window step 8 → embedding 1 frame.
const MEL_WINDOW = 76;
const MEL_STEP = 8;
const EMBED_DIM = 96;
// classifier 입력 (16, 96). 학습 측 evaluate 는 sliding stride 1 max — 동일하게.
const CLF_WINDOW = 16;
const CLF_STRIDE = 1;

const ASSET_BASE = '/models/wakeword';
const WORKLET_PATH = '/audio-worklets/wake-pcm-worklet.js';

/** robot id → 점수 임계값. useVoiceController 가 env 또는 shared/robots.json 기반으로 주입. */
export type WakeThresholds = Record<string, number>;

export interface UseWakeWordOptions {
  /** 호출어가 감지됐을 때 호출. 가장 높은 점수의 robot 만 1회 발화 (멀티-동시 발화 방지). */
  onWake: (hit: WakeHit) => void;
  /** robot id → ONNX 파일명 (확장자 제외). 미지정 시 id 자체를 파일명으로 사용. */
  robotIds: string[];
  /** robot 별 임계값. 미지정 시 0.9. */
  thresholds?: WakeThresholds;
  /** 발화 후 재발화 최소 간격 (ms). 너무 짧으면 같은 호출이 여러 번 잡힘. */
  cooldownMs?: number;
  /** 디버그용 — 매 score 마다 호출. */
  onScore?: (scores: Record<string, number>) => void;
  /** 에러 콜백. */
  onError?: (msg: string) => void;
  /**
   * 매 inference step 직전에 호출. false 반환 시 mel/embed/classifier 전부 skip.
   * 호출자가 voice.state 기반으로 wake_detected/speaking/dispatching 동안
   * 메인 thread 를 비워 robot motion / TTS 재생이 부드럽게 흐르도록 제어.
   * mic ring 은 계속 채워지므로 다음에 inference 재개 시 끊김 없음.
   */
  isEnabled?: () => boolean;
}

export interface UseWakeWordReturn {
  start: () => Promise<void>;
  stop: () => Promise<void>;
  isRunning: Ref<boolean>;
  /** 직전 inference 의 robot 별 score (디버그·UI 시각화용). */
  lastScores: Ref<Record<string, number>>;
}

const DEFAULT_COOLDOWN_MS = 1500;

export function useWakeWord(options: UseWakeWordOptions): UseWakeWordReturn {
  const isRunning = ref(false);
  const lastScores = ref<Record<string, number>>({});

  let stream: MediaStream | null = null;
  let audioContext: AudioContext | null = null;
  let workletNode: AudioWorkletNode | null = null;
  let sourceNode: MediaStreamAudioSourceNode | null = null;

  let melspecSess: ort.InferenceSession | null = null;
  let embedSess: ort.InferenceSession | null = null;
  let robotSessions: Map<string, ort.InferenceSession> = new Map();

  const audioRing = new AudioRing(AUDIO_RING_SAMPLES);
  let lastWakeAt = 0;
  // EmbedRing 은 더 이상 사용 안 함 — runStep 에서 매번 audio ring 전체로
  // sliding embedding 24 개 + sliding classifier 9 개 계산 후 max score 사용
  // (학습 측 evaluate 와 동일 흐름).
  void EmbedRing;

  let inflight = false;

  async function fetchBytes(url: string): Promise<Uint8Array> {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`fetch ${url} failed: ${r.status}`);
    return new Uint8Array(await r.arrayBuffer());
  }

  /** 외부 data 가 있는 모델 (학습 export 결과의 `<name>.onnx` + `<name>.onnx.data`) 로드. */
  async function createSessionWithExternal(
    onnxUrl: string,
    sessOpts: ort.InferenceSession.SessionOptions,
  ): Promise<ort.InferenceSession> {
    const model = await fetchBytes(onnxUrl);
    // 학습 export 가 dynamic_axes 로 batch dim 을 외부화 — `<name>.onnx.data` 가 weights.
    // onnxruntime-web 은 brwoser 파일시스템이 없어서 InferenceSession.create 의
    // `externalData` 옵션으로 byte buffer 를 명시적으로 넘겨야 한다.
    const dataUrl = `${onnxUrl}.data`;
    const dataBytes = await fetchBytes(dataUrl);
    // path 는 .onnx 내부에서 참조하는 파일명 그대로 (basename, no path).
    const externalDataName = dataUrl.split('/').pop() ?? 'model.onnx.data';
    return ort.InferenceSession.create(model, {
      ...sessOpts,
      externalData: [{ path: externalDataName, data: dataBytes }],
    });
  }

  async function loadModels(): Promise<void> {
    if (melspecSess) return;
    // CPU wasm provider — 브라우저에서 가장 호환성 좋음. WebGPU 는 모델 작아 이득 적음.
    const sessOpts: ort.InferenceSession.SessionOptions = {
      executionProviders: ['wasm'],
      graphOptimizationLevel: 'all',
    };
    // melspec / embedding 은 single-file (external data 없음) — URL 로 직접.
    melspecSess = await ort.InferenceSession.create(
      `${ASSET_BASE}/melspectrogram.onnx`,
      sessOpts,
    );
    embedSess = await ort.InferenceSession.create(
      `${ASSET_BASE}/embedding_model.onnx`,
      sessOpts,
    );
    // robot 별 분류기는 train.py 가 `<robot>.onnx.data` 사이드카로 weights 분리.
    for (const robotId of options.robotIds) {
      const sess = await createSessionWithExternal(
        `${ASSET_BASE}/${robotId}.onnx`,
        sessOpts,
      );
      robotSessions.set(robotId, sess);
    }
  }

  async function runStep(): Promise<void> {
    if (!melspecSess || !embedSess || !audioRing.isReady()) return;
    if (inflight) return; // 이전 step 진행 중이면 skip (CPU 따라잡지 못한 경우)
    if (options.isEnabled && !options.isEnabled()) return; // 외부에서 pause 요청
    inflight = true;
    try {
      const audio = audioRing.snapshot(); // 43200 samples (2.7s)

      // ─ Step 1: int16 scale (학습 측 _get_melspectrogram 의 int16 → float32 cast 와 일치)
      const scaledAudio = new Float32Array(audio.length);
      for (let i = 0; i < audio.length; i++) {
        const v = audio[i];
        const clipped = v < -1 ? -1 : v > 1 ? 1 : v;
        scaledAudio[i] = Math.round(clipped * 32767);
      }

      // ─ Step 2: melspec → (1, 1, n_frames, 32). n_frames ≈ ceil(samples/160) - 3.
      const audioTensor = new ort.Tensor('float32', scaledAudio, [1, audio.length]);
      const melOut = await melspecSess.run({ input: audioTensor });
      const melTensor = Object.values(melOut)[0];
      const melData = melTensor.data as Float32Array;
      const melDims = melTensor.dims as number[];
      // melDims: [1, 1, n_frames, 32]
      const nFrames = melDims[2];
      const melBins = melDims[3];
      if (melBins !== 32) {
        options.onError?.(`unexpected mel_bins=${melBins} (expected 32)`);
        return;
      }
      // melspec_transform = x/10 + 2 (학습 측 default)
      const mel = new Float32Array(nFrames * melBins);
      for (let i = 0; i < mel.length; i++) mel[i] = melData[i] / 10 + 2;

      // ─ Step 3: 76-frame sliding embedding windows, step 8.
      const nEmb = Math.floor((nFrames - MEL_WINDOW) / MEL_STEP) + 1;
      if (nEmb < CLF_WINDOW) {
        options.onError?.(
          `not enough mel frames: nFrames=${nFrames} → nEmb=${nEmb} (need ≥ ${CLF_WINDOW})`,
        );
        return;
      }
      // Batch (nEmb, 76, 32, 1) — embedding ONNX 1 call.
      const winBuf = new Float32Array(nEmb * MEL_WINDOW * melBins);
      for (let w = 0; w < nEmb; w++) {
        const srcStart = w * MEL_STEP * melBins;
        winBuf.set(
          mel.subarray(srcStart, srcStart + MEL_WINDOW * melBins),
          w * MEL_WINDOW * melBins,
        );
      }
      const embedIn = new ort.Tensor('float32', winBuf, [nEmb, MEL_WINDOW, melBins, 1]);
      const embedOut = await embedSess.run({ input_1: embedIn });
      const embedData = (Object.values(embedOut)[0].data as Float32Array);
      // embedOut shape: (nEmb, 1, 1, 96) → 평탄화하면 nEmb * 96 floats.
      // embedData[w*96 .. (w+1)*96] = w-번째 frame 의 96-dim embedding.

      // ─ Step 4: classifier — 16-frame sliding window stride 1, max score per robot.
      const nClf = nEmb - CLF_WINDOW + 1; // e.g. 24 - 16 + 1 = 9
      const clfBuf = new Float32Array(nClf * CLF_WINDOW * EMBED_DIM);
      for (let i = 0; i < nClf; i++) {
        const startEmb = i * CLF_STRIDE;
        clfBuf.set(
          embedData.subarray(startEmb * EMBED_DIM, (startEmb + CLF_WINDOW) * EMBED_DIM),
          i * CLF_WINDOW * EMBED_DIM,
        );
      }
      const clfIn = new ort.Tensor('float32', clfBuf, [nClf, CLF_WINDOW, EMBED_DIM]);
      const scores: Record<string, number> = {};
      for (const [robotId, sess] of robotSessions) {
        const out = await sess.run({ x: clfIn });
        const arr = Object.values(out)[0].data as Float32Array;
        let best = 0;
        for (let i = 0; i < arr.length; i++) if (arr[i] > best) best = arr[i];
        scores[robotId] = best;
      }
      lastScores.value = scores;
      options.onScore?.(scores);

      const hits = decideWakeHits(scores, options.thresholds ?? {});
      if (hits.length === 0) return;
      const now = performance.now();
      if (now - lastWakeAt < (options.cooldownMs ?? DEFAULT_COOLDOWN_MS)) return;
      lastWakeAt = now;
      options.onWake(hits[0]);
    } catch (e) {
      options.onError?.(`wake step error: ${(e as Error).message}`);
    } finally {
      inflight = false;
    }
  }

  async function start(): Promise<void> {
    if (isRunning.value) return;
    try {
      await loadModels();
      // 학습 데이터는 raw 16kHz (sounddevice + librosa.resample) 으로 만들어졌으므로
      // 브라우저 audio processing (AEC/NS/AGC) 가 wake word 의 spectral 분포를
      // 변형시키면 모델이 다른 도메인으로 인식해 score 가 0 에 머무른다.
      // 전부 false 로 raw 신호 → 학습 도메인 매칭. TTS 자기 feedback 은 useVoiceController
      // 의 wakeAck/isSpeaking/echoGuard 가드로 차단.
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        },
      });
      audioContext = new AudioContext({ sampleRate: SAMPLE_RATE });
      await audioContext.audioWorklet.addModule(WORKLET_PATH);
      sourceNode = audioContext.createMediaStreamSource(stream);
      workletNode = new AudioWorkletNode(audioContext, 'wake-pcm-worklet');
      // 무음 chunk 에서는 inference skip — 마이크 noise floor RMS ≈ 0.003,
      // 발화 시 ≥ 0.01. 0.005 임계값으로 발화 시작 전까지 mel/embed/clf 전부 건너뜀.
      // 발화 도중에는 매 chunk RMS > threshold 라 inference 정상 동작.
      // wake word 가 ring 에 들어있어도 무음 후속 chunk 에서는 skip — 이미 검출
      // 직후 cooldown 2.5s 가 작동하므로 손실 없음.
      const SILENCE_RMS_THRESHOLD = 0.005;
      workletNode.port.onmessage = (ev: MessageEvent<Float32Array>) => {
        const chunk = ev.data;
        if (!chunk || chunk.length !== HOP_SAMPLES) return;
        audioRing.push(chunk);
        let s2 = 0;
        for (let i = 0; i < chunk.length; i++) s2 += chunk[i] * chunk[i];
        if (Math.sqrt(s2 / chunk.length) < SILENCE_RMS_THRESHOLD) return;
        void runStep();
      };
      sourceNode.connect(workletNode);
      // worklet 출력은 destination 으로 안 보낸다 (스피커 mute)
      isRunning.value = true;
    } catch (e) {
      options.onError?.(`wake start failed: ${(e as Error).message}`);
      await stop();
      throw e;
    }
  }

  async function stop(): Promise<void> {
    isRunning.value = false;
    try {
      if (workletNode) {
        workletNode.port.onmessage = null;
        workletNode.disconnect();
        workletNode = null;
      }
      if (sourceNode) {
        sourceNode.disconnect();
        sourceNode = null;
      }
      if (audioContext) {
        await audioContext.close();
        audioContext = null;
      }
      if (stream) {
        stream.getTracks().forEach((t) => t.stop());
        stream = null;
      }
    } catch (e) {
      options.onError?.(`wake stop error: ${(e as Error).message}`);
    }
  }

  onBeforeUnmount(() => {
    void stop();
  });

  return { start, stop, isRunning, lastScores };
}
