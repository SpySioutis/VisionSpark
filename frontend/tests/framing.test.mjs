import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import {
  FRAME_H,
  FRAME_W,
  FRAMING_THRESHOLDS,
  classifyFrame,
  computeStats,
} from '../src/lib/framing.js'

function solidFrame(value) {
  const rgba = new Uint8Array(FRAME_W * FRAME_H * 4)
  for (let i = 0; i < FRAME_W * FRAME_H; i += 1) {
    rgba[i * 4] = value
    rgba[i * 4 + 1] = value
    rgba[i * 4 + 2] = value
    rgba[i * 4 + 3] = 255
  }
  return rgba
}

function checkerFrame() {
  const rgba = new Uint8Array(FRAME_W * FRAME_H * 4)
  for (let y = 0; y < FRAME_H; y += 1) {
    for (let x = 0; x < FRAME_W; x += 1) {
      const value = (x + y) % 2 === 0 ? 255 : 0
      const i = (y * FRAME_W + x) * 4
      rgba[i] = value
      rgba[i + 1] = value
      rgba[i + 2] = value
      rgba[i + 3] = 255
    }
  }
  return rgba
}

describe('computeStats', () => {
  it('measures brightness as mean luma', () => {
    const { brightness, motion } = computeStats(solidFrame(128), null)
    assert.ok(Math.abs(brightness - 128) < 1e-6)
    assert.equal(motion, 0)
  })

  it('gives a flat frame zero sharpness', () => {
    const { sharpness } = computeStats(solidFrame(128), null)
    assert.equal(sharpness, 0)
  })

  it('gives a checkerboard high sharpness', () => {
    const { sharpness } = computeStats(checkerFrame(), null)
    assert.ok(sharpness > 100000)
  })

  it('measures motion against the previous luma plane', () => {
    const prev = computeStats(solidFrame(100), null).luma
    const { motion } = computeStats(solidFrame(120), prev)
    assert.ok(Math.abs(motion - 20) < 1e-6)
    const same = computeStats(solidFrame(120), computeStats(solidFrame(120), null).luma)
    assert.equal(same.motion, 0)
  })
})

describe('classifyFrame', () => {
  it('checks dark, moving, and blurry in that order', () => {
    assert.equal(
      classifyFrame({ brightness: 10, motion: 50, sharpness: 0 }),
      'dark',
    )
    assert.equal(
      classifyFrame({ brightness: 120, motion: 50, sharpness: 0 }),
      'moving',
    )
    assert.equal(
      classifyFrame({ brightness: 120, motion: 0, sharpness: 0 }),
      'blurry',
    )
    assert.equal(
      classifyFrame({ brightness: 120, motion: 0, sharpness: 1000 }),
      'ok',
    )
  })

  it('classifies real frames end to end', () => {
    assert.equal(classifyFrame(computeStats(solidFrame(10), null)), 'dark')
    assert.equal(classifyFrame(computeStats(solidFrame(128), null)), 'blurry')
    assert.equal(classifyFrame(computeStats(checkerFrame(), null)), 'ok')
  })

  it('honours custom thresholds', () => {
    const stats = { brightness: 50, motion: 5, sharpness: 70 }
    assert.equal(classifyFrame(stats), 'ok')
    assert.equal(
      classifyFrame(stats, { ...FRAMING_THRESHOLDS, dark: 60 }),
      'dark',
    )
  })
})
