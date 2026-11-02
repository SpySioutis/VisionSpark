// Pure framing analysis for guided capture (no DOM): brightness, sharpness,
// and motion from a small camera frame, plus classification into one cue.

export const FRAME_W = 160
export const FRAME_H = 120

// Starting thresholds, to be tuned on real phones.
export const FRAMING_THRESHOLDS = { dark: 40, moving: 10, blurry: 60 }

/**
 * Compute brightness (mean luma), sharpness (variance of the 4-neighbour
 * Laplacian over interior pixels), and motion (mean |Y - previous Y|).
 * rgba: the frame's RGBA bytes; prevLuma: the previous luma plane or null.
 * Returns { brightness, sharpness, motion, luma }.
 */
export function computeStats(rgba, prevLuma) {
  const n = FRAME_W * FRAME_H
  const luma = new Float32Array(n)
  let sum = 0
  for (let i = 0; i < n; i += 1) {
    const y = 0.299 * rgba[i * 4] + 0.587 * rgba[i * 4 + 1] + 0.114 * rgba[i * 4 + 2]
    luma[i] = y
    sum += y
  }
  const brightness = sum / n
  let lapSum = 0
  let lapSq = 0
  let count = 0
  for (let y = 1; y < FRAME_H - 1; y += 1) {
    for (let x = 1; x < FRAME_W - 1; x += 1) {
      const i = y * FRAME_W + x
      const lap =
        4 * luma[i] - luma[i - 1] - luma[i + 1] - luma[i - FRAME_W] - luma[i + FRAME_W]
      lapSum += lap
      lapSq += lap * lap
      count += 1
    }
  }
  const mean = lapSum / count
  const sharpness = lapSq / count - mean * mean
  let motion = 0
  if (prevLuma && prevLuma.length === n) {
    let diff = 0
    for (let i = 0; i < n; i += 1) {
      diff += Math.abs(luma[i] - prevLuma[i])
    }
    motion = diff / n
  }
  return { brightness, sharpness, motion, luma }
}

/**
 * Classify frame stats into 'dark', 'moving', 'blurry', or 'ok', checked
 * in that order.
 */
export function classifyFrame(stats, thresholds = FRAMING_THRESHOLDS) {
  if (stats.brightness < thresholds.dark) {
    return 'dark'
  }
  if (stats.motion > thresholds.moving) {
    return 'moving'
  }
  if (stats.sharpness < thresholds.blurry) {
    return 'blurry'
  }
  return 'ok'
}
