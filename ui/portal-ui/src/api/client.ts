export class ApiError extends Error {
  constructor(public status: number, public path: string) {
    super(`HTTP ${status} on ${path}`)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = { 'Content-Type': 'application/json', ...(init.headers ?? {}) }
  const res = await fetch(path, { ...init, credentials: 'include', headers })
  if (!res.ok) throw new ApiError(res.status, path)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),

  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body) }),

  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),

  postForm: <T>(path: string, data: Record<string, string>) =>
    request<T>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams(data).toString(),
    }),
}
