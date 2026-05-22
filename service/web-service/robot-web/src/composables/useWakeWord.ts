/**
 * 호출어 인식 (onnxruntime-web) — 마이크 PCM 을 Silero VAD 게이트 → melspec →
 * embedding → robot 별 binary 분류기로 흘려서, 점수가 임계값을 (연속 N step)
 * 넘으면 onWake(robotId) 콜백을 발행한다.
 *
 * 파이프라인 데이터 흐름:
 *   AudioContext(sampleRate=16000) → AudioWorkletNode (wake-pcm-worklet) →
 *   80ms (1280-sample) chunk → RMS gate → Silero VAD (512-sample chunks) →
 *   AudioRing(43200 samples = 2.7s) → melspec ONNX → 76 mel frames →
 *   embedding ONNX → robot 별 분류기 ONNX → score → confirm window (연속 K) →
 *   onWake.
 *
 * 디자인 메모:
 *   - 호출 위치 (useVoiceController) 가 STT MediaStream 을 별개로 잡으므로 이 모듈도
 *     자기 stream 을 따로 잡는다. 브라우저가 동일 마이크 다중 소비를 처리한다.
 *   - 모델 6 개 (Silero VAD 1 + melspec 1 + embed 1 + robot 3) 는 `start()` 첫 호출
 *     시 lazy 로딩. 이후 호출은 재사용.
 *   - VAD 게이트: 비음성 noise (식기·박수·BGM) 가 wake 분류기에 들어가서 false-positive
 *     를 내는 것을 차단. 서버 측 (control_service/webrtc_voice.py) 의 SileroVAD 와
 *     동일 모델·동일 hysteresis 파라미터 사용. 단, 서버는 STT utterance segmentation
 *     용, 클라이언트는 wake-pre 게이트 용 — 역할 다름.
 *   - Multi-frame confirmation (WAKE_CONFIRM_FRAMES): 단발 spike 거름. 연속 K step
 *     모두 임계 초과 시에만 fire. K=2 면 +80ms 지연.
 */
import { onBeforeUnmount, ref, type Ref } from 'vue';
import * as ort from 'onnxruntime-web';
import {
  AudioRing,
  EmbedRing,
  decideWakeHits,
  type WakeHit,
} from './wakeBuffers';
import { LOG_VOICE_DEBUG } from './useWebRTCVoice';

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

// Silero VAD v5 — chunk 512 samples (32ms @ 16kHz). state shape (2,1,128).
const VAD_CHUNK_SAMPLES = 512;
// VAD speaking 종료 후 grace window — wake 음절 마지막 부분이 ring 에 다 들어올 때까지
// inference 유지. 호출어 ("에듀핑") 길이 ~600ms 중 마지막 음절 직후에 VAD 가 silence
// 로 떨어져도 다음 1~2 step 은 더 돌려서 wake 점수 산출.
const VAD_GRACE_MS = 600;
// Silero VAD hysteresis — 서버 SileroVAD 와 정렬 (control_service/webrtc_voice.py).
const VAD_POSITIVE_THRESHOLD = 0.5;
const VAD_NEGATIVE_THRESHOLD = 0.35;
const VAD_MIN_SPEECH_FRAMES = 2;
const VAD_MIN_SILENCE_FRAMES = 8;
// 연속 K step max score 모두 임계 초과 시에만 wake 발화 — 단발 spike 거름.
const WAKE_CONFIRM_FRAMES = 2;

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
  /**
   * 분류기 ONNX 파일명 suffix. 미지정 → `<robotId>.onnx` (기존 openWakeWord 학습 +
   * `<robotId>.onnx.data` 사이드카). 'v2' → `<robotId>_v2.onnx` (livekit-wakeword
   * Piper 학습, single-file). 둘 다 (16,96) embedding 입력은 같지만:
   *  · 입력 tensor name 이 'x' vs 'embeddings' — session.inputNames[0] 으로 동적 바인딩.
   *  · v2 학습 측 (livekit-wakeword data/features.py) 의 mel 입력은 sf.read 의
   *    raw [-1,1] float. 기존 frontend 의 *32767 int16-cast 가 들어가면 mel power 가
   *    10⁹ 배 부풀어 학습 분포와 어긋나 score 가 0 부근에 박힘. v2 에선 audio scale skip.
   */
  modelVariant?: string;
  /**
   * true 면 RMS 무음 게이트 + Silero VAD 게이트 둘 다 우회. whisper 류 작은 목소리 /
   * 디버깅 용. 평상시엔 CPU 부담 + 비음성 noise false-positive 위험 때문에 false.
   */
  bypassGate?: boolean;
}

export interface UseWakeWordReturn {
  start: () => Promise<void>;
  stop: () => Promise<void>;
  isRunning: Ref<boolean>;
  /** 직전 inference 의 robot 별 score (디버그·UI 시각화용). */
  lastScores: Ref<Record<string, number>>;
}

const DEFAULT_COOLDOWN_MS = 1500;

/** Silero VAD v5 streaming runner — chunk (512 float32) 당 prob + start/end event.
 *  서버 control_service/webrtc_voice.py 의 SileroVAD 와 동일 hysteresis. */
class SileroVAD {
  static readonly SR_TENSOR = new ort.Tensor('int64', BigInt64Array.from([16000n]), [1]);
  state = new Float32Array(2 * 1 * 128);
  speaking = false;
  private speechCount = 0;
  private silenceCount = 0;

  constructor(private readonly session: ort.InferenceSession) {}

  async feed(chunk: Float32Array): Promise<{ prob: number; event: 'start' | 'end' | null }> {
    if (chunk.length !== VAD_CHUNK_SAMPLES) {
      throw new Error(`VAD expects ${VAD_CHUNK_SAMPLES} samples, got ${chunk.length}`);
    }
    const input = new ort.Tensor('float32', chunk, [1, VAD_CHUNK_SAMPLES]);
    const stateT = new ort.Tensor('float32', this.state, [2, 1, 128]);
    const out = await this.session.run({ input, state: stateT, sr: SileroVAD.SR_TENSOR });
    // 서버처럼 출력 순서 0=prob, 1=new state. ONNX 모델 정의 기준.
    const outputs = Object.values(out);
    const prob = (outputs[0].data as Float32Array)[0] ?? 0;
    this.state = new Float32Array(outputs[1].data as Float32Array);
    return { prob, event: this.advance(prob) };
  }

  reset(): void {
    this.state.fill(0);
    this.speaking = false;
    this.speechCount = 0;
    this.silenceCount = 0;
  }

  private advance(prob: number): 'start' | 'end' | null {
    if (!this.speaking) {
      if (prob >= VAD_POSITIVE_THRESHOLD) {
        this.speechCount += 1;
        this.silenceCount = 0;
        if (this.speechCount >= VAD_MIN_SPEECH_FRAMES) {
          this.speaking = true;
          return 'start';
        }
      } else {
        this.speechCount = 0;
      }
    } else {
      if (prob < VAD_NEGATIVE_THRESHOLD) {
        this.silenceCount += 1;
        if (this.silenceCount >= VAD_MIN_SILENCE_FRAMES) {
          this.speaking = false;
          this.speechCount = 0;
          this.silenceCount = 0;
          return 'end';
        }
      } else {
        this.silenceCount = 0;
      }
    }
    return null;
  }
}

export function useWakeWord(options: UseWakeWordOptions): UseWakeWordReturn {
  const isRunning = ref(false);
  const lastScores = ref<Record<string, number>>({});

  let stream: MediaStream | null = null;
  let audioContext: AudioContext | null = null;
  let workletNode: AudioWorkletNode | null = null;
  let sourceNode: MediaStreamAudioSourceNode | null = null;

  let melspecSess: ort.InferenceSession | null = null;
  let embedSess: ort.InferenceSession | null = null;
  let vadSess: ort.InferenceSession | null = null;
  let vad: SileroVAD | null = null;
  let robotSessions: Map<string, ort.InferenceSession> = new Map();

  const audioRing = new AudioRing(AUDIO_RING_SAMPLES);
  let lastWakeAt = 0;
  // EmbedRing 은 더 이상 사용 안 함 — runStep 에서 매번 audio ring 전체로
  // sliding embedding 24 개 + sliding classifier 9 개 계산 후 max score 사용
  // (학습 측 evaluate 와 동일 흐름).
  void EmbedRing;

  let inflight = false;
  let vadBusy = false;
  // worklet chunk (1280) → VAD chunk (512) 분할용 누적 버퍼. 매 worklet 메시지마다
  // 새 sample 을 이어붙이고 512 단위로 잘라 VAD 에 feed. carry 는 남겨둠.
  let vadCarry = new Float32Array(0);
  // VAD speaking 또는 직전 grace window 동안만 runStep 허용. ms 기준.
  let lastVadSpeechAt = 0;
  // 최근 K step 의 robot 별 score — 연속 임계 초과 confirmation 용.
  const recentScores: Map<string, number[]> = new Map();

  async function fetchBytes(url: string): Promise<Uint8Array> {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`fetch ${url} failed: ${r.status}`);
    return new Uint8Array(await r.arrayBuffer());
  }

  /**
   * 학습 export 가 external-data (`<name>.onnx` + `<name>.onnx.data`) 면 sidecar 까지
   * 같이 로드. 단일 파일 export (livekit-wakeword v2 처럼 weights 가 .onnx 안에 inline)
   * 면 .data fetch 가 404 → single-file 로 fallback.
   */
  async function createClassifierSession(
    onnxUrl: string,
    sessOpts: ort.InferenceSession.SessionOptions,
  ): Promise<ort.InferenceSession> {
    const model = await fetchBytes(onnxUrl);
    const dataUrl = `${onnxUrl}.data`;
    const dataResp = await fetch(dataUrl);
    if (!dataResp.ok) {
      return ort.InferenceSession.create(model, sessOpts);
    }
    const dataBytes = new Uint8Array(await dataResp.arrayBuffer());
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
    // melspec / embedding / Silero VAD 모두 single-file (external data 없음) — URL 직접.
    melspecSess = await ort.InferenceSession.create(
      `${ASSET_BASE}/melspectrogram.onnx`,
      sessOpts,
    );
    embedSess = await ort.InferenceSession.create(
      `${ASSET_BASE}/embedding_model.onnx`,
      sessOpts,
    );
    vadSess = await ort.InferenceSession.create(
      `${ASSET_BASE}/silero_vad.onnx`,
      sessOpts,
    );
    vad = new SileroVAD(vadSess);
    // robot 별 분류기 — variant 미지정 시 `<robot>.onnx` (+ `<robot>.onnx.data`),
    // 'v2' 등 지정 시 `<robot>_<variant>.onnx`. v2 는 livekit-wakeword 의 single-file
    // ONNX 라 .data sidecar 없음 → createClassifierSession 안에서 fallback.
    const suffix = options.modelVariant ? `_${options.modelVariant}` : '';
    for (const robotId of options.robotIds) {
      const sess = await createClassifierSession(
        `${ASSET_BASE}/${robotId}${suffix}.onnx`,
        sessOpts,
      );
      robotSessions.set(robotId, sess);
    }
  }

  /** worklet chunk (1280) → VAD chunk (512) 분할 + state 갱신 + 게이트 확인 후 runStep. */
  async function processVadAndStep(chunk: Float32Array): Promise<void> {
    if (!vad) return;
    if (vadBusy) return; // CPU 따라잡지 못한 경우 skip — 다음 chunk 에서 만회.
    vadBusy = true;
    try {
      const merged = new Float32Array(vadCarry.length + chunk.length);
      merged.set(vadCarry);
      merged.set(chunk, vadCarry.length);
      let off = 0;
      while (off + VAD_CHUNK_SAMPLES <= merged.length) {
        // tensor 는 buffer 를 keep ref 할 수 있어 매 chunk copy.
        const slice = new Float32Array(
          merged.buffer,
          merged.byteOffset + off * Float32Array.BYTES_PER_ELEMENT,
          VAD_CHUNK_SAMPLES,
        ).slice();
        const { prob, event } = await vad.feed(slice);
        if (LOG_VOICE_DEBUG && event) console.log(`[wake-vad] ${event} prob=${prob.toFixed(3)}`);
        if (vad.speaking) lastVadSpeechAt = performance.now();
        off += VAD_CHUNK_SAMPLES;
      }
      vadCarry = merged.slice(off);
    } catch (e) {
      options.onError?.(`vad step error: ${(e as Error).message}`);
    } finally {
      vadBusy = false;
    }

    // 게이트 — speaking 중이거나, speaking 끝난 후 grace window 이내일 때만 wake step.
    // bypassGate (debug / whisper) 면 VAD 결과와 무관하게 항상 runStep.
    if (!options.bypassGate && performance.now() - lastVadSpeechAt > VAD_GRACE_MS) {
      // 게이트 닫힘 — score history 도 끊김으로 비워서 spike 가 confirm 에 끼지 않게.
      if (recentScores.size > 0) recentScores.clear();
      return;
    }
    void runStep();
  }

  async function runStep(): Promise<void> {
    if (!melspecSess || !embedSess || !audioRing.isReady()) return;
    if (inflight) return; // 이전 step 진행 중이면 skip (CPU 따라잡지 못한 경우)
    if (options.isEnabled && !options.isEnabled()) return; // 외부에서 pause 요청
    inflight = true;
    try {
      const audio = audioRing.snapshot(); // 43200 samples (2.7s)

      // ─ Step 1: 학습 파이프라인의 audio scale 와 정렬.
      //  · openWakeWord (기존 `<robot>.onnx`): 학습 측 _get_melspectrogram 이 int16 cast →
      //    frontend 도 *32767 로 맞춤.
      //  · livekit-wakeword v2 (`<robot>_v2.onnx`): data/features.py 가 sf.read 의 raw
      //    [-1,1] float 그대로 mel 에 넘김. *32767 하면 mel power 가 10⁹ 배 부풀어 학습
      //    분포와 어긋남.
      const scaleToInt16 = !options.modelVariant;
      const scaledAudio = new Float32Array(audio.length);
      for (let i = 0; i < audio.length; i++) {
        const v = audio[i];
        const clipped = v < -1 ? -1 : v > 1 ? 1 : v;
        scaledAudio[i] = scaleToInt16 ? Math.round(clipped * 32767) : clipped;
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
        // 기존 분류기는 입력 이름 'x', livekit-wakeword v2 는 'embeddings' — 모델마다
        // 다르므로 session 메타에서 첫 입력명을 가져와 동적 바인딩.
        const inputName = sess.inputNames[0];
        const out = await sess.run({ [inputName]: clfIn });
        const arr = Object.values(out)[0].data as Float32Array;
        let best = 0;
        for (let i = 0; i < arr.length; i++) if (arr[i] > best) best = arr[i];
        scores[robotId] = best;
      }
      lastScores.value = scores;
      options.onScore?.(scores);

      // Multi-frame confirmation — 직전 K-1 step + 현재 step 모두 임계 초과 시만 fire.
      // 단발 spike (식기 부딪힘 등) 는 보통 한 step 만 튀고 다음 step 에서 떨어짐.
      for (const robotId of options.robotIds) {
        const history = recentScores.get(robotId) ?? [];
        history.push(scores[robotId] ?? 0);
        while (history.length > WAKE_CONFIRM_FRAMES) history.shift();
        recentScores.set(robotId, history);
      }

      const hits = decideWakeHits(scores, options.thresholds ?? {});
      if (hits.length === 0) return;
      const confirmed = hits.filter((hit) => {
        const history = recentScores.get(hit.robotId) ?? [];
        if (history.length < WAKE_CONFIRM_FRAMES) return false;
        const thr = options.thresholds?.[hit.robotId] ?? 0.9;
        return history.every((s) => s >= thr);
      });
      if (confirmed.length === 0) return;
      const now = performance.now();
      if (now - lastWakeAt < (options.cooldownMs ?? DEFAULT_COOLDOWN_MS)) return;
      lastWakeAt = now;
      // confirm 후엔 history 비움 — cooldown 동안 잔재로 즉시 재발화 막음.
      recentScores.clear();
      options.onWake(confirmed[0]);
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
      // AEC/NS/AGC 셋 다 true — 학습 데이터가 raw 16kHz (sounddevice +
      // librosa.resample) 라 이론적으로 NS/AGC 가 mel 분포를 비틀 우려가 있지만
      // 실측 결과 wake score 정상. AEC 가 TTS 자기 feedback 까지 제거해 별도
      // echo 가드 (suppressUntil / speakerEchoGuard / isLikelyEchoOfRobotReply)
      // 필요 없음.
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      audioContext = new AudioContext({ sampleRate: SAMPLE_RATE });
      await audioContext.audioWorklet.addModule(WORKLET_PATH);
      sourceNode = audioContext.createMediaStreamSource(stream);
      workletNode = new AudioWorkletNode(audioContext, 'wake-pcm-worklet');
      // 2 단계 게이트:
      //   1. RMS — 마이크 noise floor (~0.003) 도 안 되는 완전 무음은 VAD 호출도 skip.
      //   2. Silero VAD — voice / non-voice 구별. speaking 또는 직전 grace window 내
      //      에서만 wake 분류기 실행. 비음성 noise (식기·박수·BGM) 가 분류기에 들어가
      //      false-positive 내는 것을 차단.
      // ring 은 게이트와 무관하게 항상 채워서 wake 발생 시 ring 안에 2.7s context 보장.
      const SILENCE_RMS_THRESHOLD = 0.005;
      workletNode.port.onmessage = (ev: MessageEvent<Float32Array>) => {
        const chunk = ev.data;
        if (!chunk || chunk.length !== HOP_SAMPLES) return;
        audioRing.push(chunk);
        if (!options.bypassGate) {
          let s2 = 0;
          for (let i = 0; i < chunk.length; i++) s2 += chunk[i] * chunk[i];
          if (Math.sqrt(s2 / chunk.length) < SILENCE_RMS_THRESHOLD) return;
        }
        void processVadAndStep(chunk);
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
      // VAD state 와 누적 버퍼 / score history 리셋 — 재시작 시 직전 세션 잔재 제거.
      vad?.reset();
      vadCarry = new Float32Array(0);
      lastVadSpeechAt = 0;
      recentScores.clear();
    } catch (e) {
      options.onError?.(`wake stop error: ${(e as Error).message}`);
    }
  }

  onBeforeUnmount(() => {
    void stop();
  });

  return { start, stop, isRunning, lastScores };
}
