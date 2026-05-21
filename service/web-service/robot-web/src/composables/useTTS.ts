/**
 * TTS — WebRTC 통합 후 클라이언트 TTS 책임 완전 축소.
 *
 * 남은 것:
 *   - attachRemoteLipSync: WebRTC remote audio stream 용 lip-sync (서버 tts_start
 *     payload 의 text + duration_ms 로 한글 음절 인덱스 진행).
 *   - cancel: 진행 중 lip-sync detach.
 *   - isSpeaking ref (DC tts_start/end 기반으로 useVoiceController 가 set).
 *
 * 제거된 것 (서버 outbound 가 대체):
 *   - speak(text), speakFromHub, playStreaming, playBuffered, MediaSource pump.
 *   - playWakeAck — wakeAck audio/voice reply 모두 제거. 호출어 단독 발화는
 *     클라이언트가 wake_on/wake_off 효과음만 재생, 서버는 dispatch skip.
 */
import { onBeforeUnmount, ref } from 'vue';
import { useVoiceStore } from '@/stores/voice';

/** 한글 음절 / 숫자만 추출 — 쉼표·공백 등은 lip-sync 진행률 매핑에서 제외. */
function hangulAndDigitsForLipsync(text: string): string {
  const out: string[] = [];
  for (const ch of text) {
    const c = ch.charCodeAt(0);
    if (c >= 0xac00 && c <= 0xd7a3) out.push(ch);
    else if (ch >= '0' && ch <= '9') out.push(ch);
  }
  if (out.length > 0) return out.join('');
  const compact = text.replace(/\s+/g, '').trim();
  return compact.length > 0 ? compact : ' ';
}

function lipsyncCharIndex(currentTime: number, duration: number, len: number): number {
  if (len <= 0) return 0;
  if (!Number.isFinite(duration) || duration <= 0) return 0;
  const p = Math.min(1, Math.max(0, currentTime / duration));
  return Math.min(len - 1, Math.floor(p * len));
}

export function useTTS(): {
  attachRemoteLipSync: (
    remoteStream: MediaStream,
    text: string,
    durationMs: number,
  ) => () => void;
  cancel: () => void;
  isSpeaking: ReturnType<typeof ref<boolean>>;
} {
  const voiceStore = useVoiceStore();
  const isSpeaking = ref(false);
  let remoteLipSyncDetach: (() => void) | null = null;

  /** WebRTC remote audio 가 재생 중일 때 lip-sync attach. tts_end 시 호출자가 detach 함수 호출. */
  function attachRemoteLipSync(
    remoteStream: MediaStream,
    text: string,
    durationMs: number,
  ): () => void {
    // 이전 attach 가 살아있으면 detach.
    remoteLipSyncDetach?.();
    remoteLipSyncDetach = null;
    // remoteStream 인자는 추후 analyser 재도입을 위해 유지 (현재 미사용).
    void remoteStream;

    const startedAt = performance.now();
    const durationSec = durationMs / 1000;
    let finished = false;

    // Chrome 의 known issue: `<audio>.srcObject = stream` 로 재생 중인 동일 stream 에
    // `createMediaStreamSource` 를 호출하면 audio element 가 silent 가 됨. 임시로
    // RMS analyser 를 끄고 sine fallback envelope 만 사용. 입 모양은 움직이지만
    // 정밀도는 떨어짐. 추후 audio track clone 등으로 다시 도입 가능.
    const syncText = hangulAndDigitsForLipsync(text);

    isSpeaking.value = true;
    voiceStore.setSpeaking(true);

    let rafId = 0;
    let lastIdx = -1;
    const tick = (): void => {
      if (finished) {
        voiceStore.setSpeechEnvelope(0);
        return;
      }
      const elapsed = (performance.now() - startedAt) / 1000;
      const len = syncText.length;
      const idx = lipsyncCharIndex(elapsed, durationSec, len);
      if (idx !== lastIdx) {
        lastIdx = idx;
        voiceStore.setCurrentChar(syncText.charAt(idx));
      }
      const wobble = Math.sin(elapsed * 38) * 0.5 + Math.sin(elapsed * 21) * 0.35;
      voiceStore.setSpeechEnvelope(0.08 + Math.abs(wobble) * 0.22);
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);

    const detach = (): void => {
      finished = true;
      cancelAnimationFrame(rafId);
      isSpeaking.value = false;
      voiceStore.setSpeaking(false);
      voiceStore.setCurrentChar('');
      voiceStore.setSpeechEnvelope(0);
      if (remoteLipSyncDetach === detach) remoteLipSyncDetach = null;
    };
    remoteLipSyncDetach = detach;
    return detach;
  }

  function cancel(): void {
    remoteLipSyncDetach?.();
    remoteLipSyncDetach = null;
    voiceStore.setCurrentChar('');
    voiceStore.setSpeechEnvelope(0);
    isSpeaking.value = false;
    voiceStore.setSpeaking(false);
  }

  onBeforeUnmount(() => cancel());

  return { attachRemoteLipSync, cancel, isSpeaking };
}
