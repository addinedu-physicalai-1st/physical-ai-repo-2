/**
 * 고정 멘트 TTS — ai-service /api/tts/say (edge_tts) → mp3 stream → audio play.
 *
 * Voice-guided search 에서 follow_node mode 전이 시 / 사용자 음성 명령 직후
 * 고정 응답 멘트 발화에 사용. LLM 우회 (latency / cost ↓).
 */
export interface TtsSayDeps {
  fetch?: typeof fetch;
}

export interface UseTtsSay {
  sayText(text: string): Promise<void>;
}

export function useTtsSay(deps: TtsSayDeps = {}): UseTtsSay {
  const fetchFn = deps.fetch ?? globalThis.fetch.bind(globalThis);

  async function sayText(text: string): Promise<void> {
    const res = await fetchFn('/api/tts/say', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) throw new Error(`TTS failed: ${res.status}`);
    const blob = await res.blob();
    const audio = new Audio(URL.createObjectURL(blob));
    await audio.play();
  }

  return { sayText };
}
