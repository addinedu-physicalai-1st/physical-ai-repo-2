import { onBeforeUnmount, ref, type Ref } from 'vue';

interface AudioContextWithWebkit extends Window {
  webkitAudioContext?: typeof AudioContext;
}

/**
 * 마이크 입력의 RMS 볼륨을 0~1 범위 reactive 값으로 노출.
 * 시각 피드백 (Siri 블롭) 용. STT 와 별개의 getUserMedia 스트림.
 */
export function useAudioLevel(): {
  start: () => Promise<void>;
  stop: () => void;
  level: Ref<number>;
} {
  const level = ref(0);
  let stream: MediaStream | null = null;
  let audioContext: AudioContext | null = null;
  let analyser: AnalyserNode | null = null;
  let dataArray: Uint8Array | null = null;
  let rafId: number | null = null;
  let starting = false;

  function tick(): void {
    if (!analyser || !dataArray) return;
    analyser.getByteTimeDomainData(dataArray);
    let sumSquares = 0;
    for (let i = 0; i < dataArray.length; i++) {
      const v = (dataArray[i] - 128) / 128;
      sumSquares += v * v;
    }
    const rms = Math.sqrt(sumSquares / dataArray.length);
    // RMS 는 보통 0~0.3 수준 — 4배 amplify 후 clamp
    const next = Math.min(1, rms * 4);
    // 약간의 smoothing
    level.value = level.value * 0.6 + next * 0.4;
    rafId = window.requestAnimationFrame(tick);
  }

  async function start(): Promise<void> {
    if (audioContext || starting) return;
    starting = true;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const Ctor =
        window.AudioContext ?? (window as unknown as AudioContextWithWebkit).webkitAudioContext;
      if (!Ctor) throw new Error('AudioContext not supported');
      audioContext = new Ctor();
      const source = audioContext.createMediaStreamSource(stream);
      analyser = audioContext.createAnalyser();
      analyser.fftSize = 512;
      analyser.smoothingTimeConstant = 0.85;
      source.connect(analyser);
      dataArray = new Uint8Array(analyser.frequencyBinCount);
      tick();
    } finally {
      starting = false;
    }
  }

  function stop(): void {
    if (rafId !== null) {
      window.cancelAnimationFrame(rafId);
      rafId = null;
    }
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
    }
    if (audioContext) {
      void audioContext.close();
      audioContext = null;
    }
    analyser = null;
    dataArray = null;
    level.value = 0;
  }

  onBeforeUnmount(() => stop());

  return { start, stop, level };
}
