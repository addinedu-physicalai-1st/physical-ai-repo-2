import { describe, it, expect } from 'vitest'
import { estimateHeadPose, AngleTarget, matchesTarget } from '@/lib/headPose'

function frontalLandmarks() {
  const arr = Array.from({ length: 468 }, () => ({ x: 0, y: 0, z: 0 }))
  arr[1]   = { x: 0.5,  y: 0.5,  z: 0 }   // nose tip
  arr[10]  = { x: 0.5,  y: 0.3,  z: 0 }   // forehead
  arr[152] = { x: 0.5,  y: 0.7,  z: 0 }   // chin
  arr[234] = { x: 0.35, y: 0.5,  z: 0 }   // left temple
  arr[454] = { x: 0.65, y: 0.5,  z: 0 }   // right temple
  arr[168] = { x: 0.5,  y: 0.42, z: 0 }   // mid brow
  return arr
}

function turnedLeftLandmarks() {
  const arr = frontalLandmarks()
  arr[1] = { x: 0.4, y: 0.5, z: 0 }       // 코가 왼쪽
  return arr
}

describe('estimateHeadPose', () => {
  it('returns near-zero for frontal face', () => {
    const { yaw, pitch } = estimateHeadPose(frontalLandmarks())
    expect(Math.abs(yaw)).toBeLessThan(5)
    expect(Math.abs(pitch)).toBeLessThan(20)
  })

  it('returns negative yaw when looking left', () => {
    const { yaw } = estimateHeadPose(turnedLeftLandmarks())
    expect(yaw).toBeLessThan(-15)
  })
})

describe('matchesTarget', () => {
  it('frontal pose matches FRONT', () => {
    expect(matchesTarget({ yaw: 2, pitch: -3 }, AngleTarget.FRONT)).toBe(true)
  })
  it('frontal pose does NOT match LEFT', () => {
    expect(matchesTarget({ yaw: 2, pitch: 0 }, AngleTarget.LEFT)).toBe(false)
  })
  it('-50° yaw matches LEFT', () => {
    expect(matchesTarget({ yaw: -50, pitch: 0 }, AngleTarget.LEFT)).toBe(true)
  })
  it('+50° yaw matches RIGHT', () => {
    expect(matchesTarget({ yaw: 50, pitch: 0 }, AngleTarget.RIGHT)).toBe(true)
  })
  it('+25° pitch matches DOWN', () => {
    expect(matchesTarget({ yaw: 0, pitch: 25 }, AngleTarget.DOWN)).toBe(true)
  })
  it('-25° pitch matches UP', () => {
    expect(matchesTarget({ yaw: 0, pitch: -25 }, AngleTarget.UP)).toBe(true)
  })
})
