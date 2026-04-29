import { describe, it, expect } from 'vitest'
import { useChildStore } from '@/stores/child'

describe('child store', () => {
  it('starts with no selection', () => {
    const s = useChildStore()
    expect(s.selectedChildId).toBeNull()
  })

  it('select sets and clear resets', () => {
    const s = useChildStore()
    s.select(7)
    expect(s.selectedChildId).toBe(7)
    s.clear()
    expect(s.selectedChildId).toBeNull()
  })
})
