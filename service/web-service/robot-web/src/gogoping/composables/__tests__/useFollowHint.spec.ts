import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useFollowHint, type HintDirection } from '../useFollowHint';

describe('useFollowHint', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, published: 'right' }),
    });
  });

  it('right hint 발행 — POST /api/gogoping/follow/hint + body', async () => {
    const { sendHint } = useFollowHint({ fetch: fetchMock });
    await sendHint('right');
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/gogoping/follow/hint',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ direction: 'right' }),
      },
    );
  });

  it('left/front/back 모두 같은 URL', async () => {
    const { sendHint } = useFollowHint({ fetch: fetchMock });
    for (const d of ['left', 'front', 'back'] as HintDirection[]) {
      await sendHint(d);
    }
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const bodies = fetchMock.mock.calls.map(([, opts]) => JSON.parse((opts as RequestInit).body as string));
    expect(bodies.map(b => b.direction)).toEqual(['left', 'front', 'back']);
  });

  it('서버 503 → throw', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 503,
      json: async () => ({ ok: false, error: 'ros_not_ready' }),
    });
    const { sendHint } = useFollowHint({ fetch: fetchMock });
    await expect(sendHint('right')).rejects.toThrow(/503/);
  });
});
