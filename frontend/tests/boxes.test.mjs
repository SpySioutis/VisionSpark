import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import { bestBox, describeBox, guideForBox, paddedCropRect, scaleBox } from '../src/lib/boxes.js'

describe('scaleBox', () => {
  it('maps a SAM box into natural-image pixels', () => {
    assert.deepEqual(
      scaleBox(
        { x1: 92, y1: 248, x2: 439, y2: 652, w: 512, h: 683 },
        1024,
        1366,
      ),
      { x1: 184, y1: 496, x2: 878, y2: 1304 },
    )
  })

  it('returns null for boxes that cannot be scaled', () => {
    assert.equal(scaleBox(null, 100, 100), null)
    assert.equal(
      scaleBox({ x1: 0, y1: 0, x2: 10, y2: 10, w: 0, h: 10 }, 100, 100),
      null,
    )
    assert.equal(
      scaleBox({ x1: 0, y1: 0, x2: 10, y2: 10, w: 10, h: 10 }, Number.NaN, 100),
      null,
    )
  })
})

describe('paddedCropRect', () => {
  it('expands by 5% on each side', () => {
    assert.deepEqual(
      paddedCropRect({ x1: 100, y1: 100, x2: 200, y2: 300 }, 1000, 1000),
      { cx1: 95, cy1: 90, cx2: 205, cy2: 310 },
    )
  })

  it('clamps to the image bounds', () => {
    assert.deepEqual(
      paddedCropRect({ x1: 0, y1: 0, x2: 100, y2: 100 }, 1000, 1000),
      { cx1: 0, cy1: 0, cx2: 105, cy2: 105 },
    )
  })

  it('returns null when nothing remains after clipping', () => {
    assert.equal(
      paddedCropRect({ x1: 10, y1: 10, x2: 10, y2: 10 }, 1000, 1000),
      null,
    )
  })
})

describe('describeBox', () => {
  it('names the center cell and large boxes', () => {
    assert.deepEqual(
      describeBox({ x1: 250, y1: 250, x2: 750, y2: 750, w: 1000, h: 1000 }),
      { position: 'center', size: 'large' },
    )
  })

  it('names corners and small boxes', () => {
    assert.deepEqual(
      describeBox({ x1: 0, y1: 0, x2: 100, y2: 100, w: 1000, h: 1000 }),
      { position: 'topLeft', size: 'small' },
    )
    assert.deepEqual(
      describeBox({ x1: 700, y1: 700, x2: 950, y2: 950, w: 1000, h: 1000 }),
      { position: 'bottomRight', size: 'medium' },
    )
  })

  it('names edge cells', () => {
    const cases = [
      [{ x1: 450, y1: 50, x2: 550, y2: 150 }, 'top'],
      [{ x1: 50, y1: 450, x2: 150, y2: 550 }, 'left'],
      [{ x1: 850, y1: 450, x2: 950, y2: 550 }, 'right'],
      [{ x1: 450, y1: 850, x2: 550, y2: 950 }, 'bottom'],
      [{ x1: 850, y1: 50, x2: 950, y2: 150 }, 'topRight'],
      [{ x1: 50, y1: 850, x2: 150, y2: 950 }, 'bottomLeft'],
    ]
    for (const [box, position] of cases) {
      assert.equal(
        describeBox({ ...box, w: 1000, h: 1000 }).position,
        position,
      )
    }
  })

  it('treats an area fraction of exactly 0.05 as medium', () => {
    assert.deepEqual(
      describeBox({ x1: 0, y1: 0, x2: 100, y2: 500, w: 1000, h: 1000 }),
      { position: 'topLeft', size: 'medium' },
    )
  })

  it('falls back to center/small for invalid boxes', () => {
    assert.deepEqual(describeBox(null), { position: 'center', size: 'small' })
    assert.deepEqual(
      describeBox({ x1: 0, y1: 0, x2: 1, y2: 1, w: 0, h: 1 }),
      { position: 'center', size: 'small' },
    )
  })
})

describe('bestBox', () => {
  it('picks the highest confidence, missing last', () => {
    const low = { x1: 0, y1: 0, x2: 10, y2: 10, w: 100, h: 100, c: 0.5 }
    const high = { x1: 0, y1: 0, x2: 10, y2: 10, w: 100, h: 100, c: 0.9 }
    const missing = { x1: 0, y1: 0, x2: 90, y2: 90, w: 100, h: 100, c: null }
    assert.equal(bestBox([low, missing, high]), high)
    assert.equal(bestBox([low, missing]), low)
  })

  it('breaks confidence ties by largest area', () => {
    const small = { x1: 0, y1: 0, x2: 10, y2: 10, w: 100, h: 100, c: 0.7 }
    const big = { x1: 0, y1: 0, x2: 50, y2: 50, w: 100, h: 100, c: 0.7 }
    assert.equal(bestBox([small, big]), big)
  })

  it('skips degenerate boxes and returns null when none is usable', () => {
    assert.equal(bestBox([]), null)
    assert.equal(bestBox(null), null)
    assert.equal(
      bestBox([{ x1: 10, y1: 10, x2: 10, y2: 20, w: 100, h: 100, c: 0.9 }]),
      null,
    )
  })
})

describe('guideForBox', () => {
  it('names the centered and directional cases', () => {
    assert.equal(
      guideForBox({ x1: 30, y1: 30, x2: 70, y2: 70, w: 100, h: 100 }),
      'centered',
    )
    assert.equal(
      guideForBox({ x1: 0, y1: 30, x2: 30, y2: 70, w: 100, h: 100 }),
      'moveLeft',
    )
    assert.equal(
      guideForBox({ x1: 70, y1: 30, x2: 100, y2: 70, w: 100, h: 100 }),
      'moveRight',
    )
    assert.equal(
      guideForBox({ x1: 30, y1: 0, x2: 70, y2: 30, w: 100, h: 100 }),
      'moveUp',
    )
    assert.equal(
      guideForBox({ x1: 30, y1: 70, x2: 70, y2: 100, w: 100, h: 100 }),
      'moveDown',
    )
  })

  it('picks the larger axis on diagonals', () => {
    assert.equal(
      guideForBox({ x1: 0, y1: 20, x2: 40, y2: 60, w: 100, h: 100 }),
      'moveLeft',
    )
    assert.equal(
      guideForBox({ x1: 20, y1: 0, x2: 60, y2: 40, w: 100, h: 100 }),
      'moveUp',
    )
  })

  it('names too small and too close', () => {
    assert.equal(
      guideForBox({ x1: 40, y1: 40, x2: 60, y2: 60, w: 100, h: 100 }),
      'moveCloser',
    )
    assert.equal(
      guideForBox({ x1: 2, y1: 2, x2: 98, y2: 98, w: 100, h: 100 }),
      'moveBack',
    )
    assert.equal(
      guideForBox({ x1: 0, y1: 30, x2: 99, y2: 70, w: 100, h: 100 }),
      'moveBack',
    )
  })

  it('prioritises too close over off-center', () => {
    assert.equal(
      guideForBox({ x1: 0, y1: 60, x2: 99, y2: 95, w: 100, h: 100 }),
      'moveBack',
    )
  })

  it('treats near-boundary boxes as centered', () => {
    assert.equal(
      guideForBox({ x1: 20, y1: 20, x2: 60, y2: 80, w: 100, h: 100 }),
      'centered',
    )
  })
})
