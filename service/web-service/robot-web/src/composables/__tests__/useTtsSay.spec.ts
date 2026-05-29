import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useTtsSay } from '../useTtsSay';

describe('useTtsSay', () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let playMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: async () => new Blob(['FAKE_MP3'], { type: 'audio/mpeg' }),
    });
    playMock = vi.fn().mockResolvedValue(undefined);
    global.URL.createObjectURL = vi.fn(() => 'blob:test');
    global.Audio = vi.fn(() => ({ play: playMock })) as unknown as typeof Audio;
  });

  it('POST /api/tts/say 호출 — 정확한 url + body', async () => {
    const { sayText } = useTtsSay({ fetch: fetchMock });
    await sayText('선생님 찾았습니다');
    expect(fetchMock).toHaveBeenCalledWith('/api/tts/say', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: '선생님 찾았습니다' }),
    });
  });

  it('mp3 blob → Audio.play 호출', async () => {
    const { sayText } = useTtsSay({ fetch: fetchMock });
    await sayText('테스트');
    expect(playMock).toHaveBeenCalled();
  });

  it('서버 503 → throw', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 503 });
    const { sayText } = useTtsSay({ fetch: fetchMock });
    await expect(sayText('실패')).rejects.toThrow(/503/);
  });
});
