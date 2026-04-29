import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { api, ApiError } from '@/api/client'

describe('api client', () => {
  beforeEach(() => {
    global.fetch = vi.fn()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('GET parses JSON on 2xx', async () => {
    ;(global.fetch as any).mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    )
    const result = await api.get<{ ok: boolean }>('/api/x')
    expect(result).toEqual({ ok: true })
  })

  it('throws ApiError on non-2xx with status code', async () => {
    ;(global.fetch as any).mockResolvedValue(new Response('nope', { status: 401 }))
    await expect(api.get('/api/x')).rejects.toBeInstanceOf(ApiError)
  })

  it('sends credentials on every request', async () => {
    ;(global.fetch as any).mockResolvedValue(new Response('{}', { status: 200 }))
    await api.get('/api/x')
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/x',
      expect.objectContaining({ credentials: 'include' })
    )
  })

  it('postForm uses x-www-form-urlencoded', async () => {
    ;(global.fetch as any).mockResolvedValue(new Response('{}', { status: 200 }))
    await api.postForm('/api/auth/cookie/login', { username: 'a@b', password: 'p' })
    const call = (global.fetch as any).mock.calls[0]
    expect(call[1].headers['Content-Type']).toBe('application/x-www-form-urlencoded')
    expect(call[1].body).toBe('username=a%40b&password=p')
  })

  it('returns undefined on 204', async () => {
    ;(global.fetch as any).mockResolvedValue(new Response(null, { status: 204 }))
    const result = await api.post('/api/x', {})
    expect(result).toBeUndefined()
  })
})
