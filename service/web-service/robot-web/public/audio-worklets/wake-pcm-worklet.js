// 호출어 인식용 raw PCM 추출 worklet.
//
// AudioContext({sampleRate: 16000}) 로 만들면 브라우저가 마이크 입력을 16kHz 로
// 리샘플해서 quantum (보통 128 샘플) 단위로 process() 에 전달한다.
// 이 worklet 은 그 quantum 을 누적해 HOP 길이 chunk (Float32Array, mono 16kHz) 가
// 모일 때마다 main thread 로 postMessage 한다.
//
// 호출어 파이프라인 (useWakeWord) 은 1 chunk = 1 새 embedding frame = 80ms.
//
// Mono 입력 가정. stereo 가 들어오면 첫 채널만 쓴다.

const HOP_SAMPLES = 1280; // 80ms at 16kHz

class WakePcmWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = new Float32Array(HOP_SAMPLES);
    this._filled = 0;
  }

  process(inputs) {
    const channels = inputs[0];
    if (!channels || channels.length === 0) return true;
    const ch0 = channels[0];
    if (!ch0 || ch0.length === 0) return true;

    let i = 0;
    while (i < ch0.length) {
      const remaining = HOP_SAMPLES - this._filled;
      const take = Math.min(remaining, ch0.length - i);
      this._buffer.set(ch0.subarray(i, i + take), this._filled);
      this._filled += take;
      i += take;
      if (this._filled >= HOP_SAMPLES) {
        // copy + zero-fill for next chunk — postMessage 가 비동기라 같은 버퍼 재사용 위험.
        const out = new Float32Array(HOP_SAMPLES);
        out.set(this._buffer);
        this.port.postMessage(out, [out.buffer]);
        this._filled = 0;
      }
    }
    return true;
  }
}

registerProcessor('wake-pcm-worklet', WakePcmWorklet);
