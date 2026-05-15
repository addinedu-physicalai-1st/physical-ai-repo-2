export class ApiError extends Error {
  constructor(
    public status: number,
    public path: string,
    /** FastAPI `detail` 또는 본문 일부 */
    public detail?: string,
  ) {
    super(detail?.trim() || `HTTP ${status} on ${path}`)
    this.name = 'ApiError'
  }
}

function formatErrorBody(body: unknown): string | undefined {
  if (body == null || typeof body !== 'object') return undefined
  const d = (body as { detail?: unknown }).detail
  if (typeof d === 'string') return d
  if (Array.isArray(d)) {
    return d
      .map((item) => {
        if (item && typeof item === 'object' && 'msg' in item) {
          return String((item as { msg: unknown }).msg)
        }
        return String(item)
      })
      .filter(Boolean)
      .join('; ')
  }
  return undefined
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = { 'Content-Type': 'application/json', ...(init.headers ?? {}) }
  const res = await fetch(path, { ...init, credentials: 'include', headers })
  if (!res.ok) {
    let detail: string | undefined
    const ct = res.headers.get('content-type') ?? ''
    if (ct.includes('application/json')) {
      try {
        detail = formatErrorBody(await res.json())
      } catch {
        /* ignore */
      }
    } else {
      try {
        const text = await res.text()
        if (text.trim()) detail = text.trim().slice(0, 500)
      } catch {
        /* ignore */
      }
    }
    throw new ApiError(res.status, path, detail)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),

  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body) }),

  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),

  delete: (path: string) => request<void>(path, { method: 'DELETE' }),

  postForm: <T>(path: string, data: Record<string, string>) =>
    request<T>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams(data).toString(),
    }),
}
