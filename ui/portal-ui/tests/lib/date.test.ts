import { describe, it, expect } from 'vitest'
import { localDateKey } from '@/lib/date'

describe('localDateKey', () => {
  it('formats local date as YYYY-MM-DD', () => {
    const d = new Date(2026, 4, 5, 12, 0, 0)  // 2026-05-05 12:00 local
    expect(localDateKey(d)).toBe('2026-05-05')
  })

  it('uses local time, not UTC', () => {
    // KST 자정 직후를 시뮬레이션 — 로컬은 5월 5일이지만 UTC 는 5월 4일
    // toISOString().slice(0,10) 은 '2026-05-04', localDateKey 는 '2026-05-05'
    const d = new Date(2026, 4, 5, 0, 30, 0)  // 2026-05-05 00:30 local
    expect(localDateKey(d)).toBe('2026-05-05')
  })

  it('pads single-digit month and day', () => {
    const d = new Date(2026, 0, 3, 12, 0, 0)  // 2026-01-03
    expect(localDateKey(d)).toBe('2026-01-03')
  })

  it('defaults to current time when no arg', () => {
    const result = localDateKey()
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })
})
