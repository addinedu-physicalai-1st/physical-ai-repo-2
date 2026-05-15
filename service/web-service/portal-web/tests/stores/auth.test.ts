import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth'

vi.mock('@/api/client', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    postForm: vi.fn(),
    patch: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    constructor(public status: number, public path: string) {
      super(`HTTP ${status}`)
    }
  },
}))

import { api, ApiError } from '@/api/client'

describe('auth store', () => {
  beforeEach(() => vi.clearAllMocks())

  it('starts unauthenticated', () => {
    const auth = useAuthStore()
    expect(auth.isAuthenticated).toBe(false)
    expect(auth.role).toBeNull()
  })

  it('login posts form-encoded credentials and fetches user', async () => {
    ;(api.postForm as any).mockResolvedValue({})
    ;(api.get as any).mockResolvedValue({ id: 1, email: 't@x', role: 'teacher', name: '선생님' })

    const auth = useAuthStore()
    await auth.login('t@x', 'pw')

    expect(api.postForm).toHaveBeenCalledWith('/api/auth/cookie/login', {
      username: 't@x',
      password: 'pw',
    })
    expect(auth.role).toBe('teacher')
    expect(auth.isAuthenticated).toBe(true)
  })

  it('logout clears user', async () => {
    ;(api.post as any).mockResolvedValue(undefined)
    const auth = useAuthStore()
    auth.user = { id: 1, email: 'x', role: 'parent', name: 'p' }
    await auth.logout()
    expect(auth.user).toBeNull()
    expect(api.post).toHaveBeenCalledWith('/api/auth/cookie/logout', {})
  })

  it('logout clears user even if server call fails', async () => {
    ;(api.post as any).mockRejectedValue(new ApiError(500, '/api/auth/cookie/logout'))
    const auth = useAuthStore()
    auth.user = { id: 1, email: 'x', role: 'parent', name: 'p' }
    await expect(auth.logout()).rejects.toBeInstanceOf(ApiError)
    expect(auth.user).toBeNull()
  })

  it('fetchMe sets user to null on 401', async () => {
    ;(api.get as any).mockRejectedValue(new ApiError(401, '/api/users/me'))
    const auth = useAuthStore()
    await auth.fetchMe()
    expect(auth.user).toBeNull()
  })

  it('fetchMe rethrows non-401 errors', async () => {
    ;(api.get as any).mockRejectedValue(new ApiError(500, '/api/users/me'))
    const auth = useAuthStore()
    await expect(auth.fetchMe()).rejects.toBeInstanceOf(ApiError)
  })
})
