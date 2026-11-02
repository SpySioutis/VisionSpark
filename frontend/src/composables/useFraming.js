import { onBeforeUnmount, ref } from 'vue'
import { FRAME_H, FRAME_W, classifyFrame, computeStats } from '../lib/framing.js'

const TICK_MS = 200
const HOLD_SAMPLES = 2
const CUE_COOLDOWN_MS = 2500
const WARMUP_MS = 1000
const OK_SAMPLES = 4

/**
 * Level-1 framing guidance: while the camera is live, sample a 160x120
 * frame every 200 ms, speak short cues (dark / moving / blurry), and
 * auto-capture after 4 consecutive steady, sharp, bright-enough samples
 * (unless autoCapture is off, as with live SAM guidance).
 */
export function useFraming({
  videoEl,
  isLive,
  torchSupported,
  isSpeaking,
  isDisposed,
  speak,
  t,
  earcons,
  onAutoCapture,
  autoCapture = true,
}) {
  const canvas = document.createElement('canvas')
  canvas.width = FRAME_W
  canvas.height = FRAME_H
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  let timer = null
  let prevLuma = null
  let lastState = null
  let heldCount = 0
  let okCount = 0
  let liveSince = null
  let lastCueAt = 0
  // Latest { brightness, sharpness, motion }, or null when not tracking.
  // Level-3 guidance reads motion for its stillness gate.
  const lastStats = ref(null)

  function reset() {
    prevLuma = null
    lastState = null
    heldCount = 0
    okCount = 0
    liveSince = null
    lastStats.value = null
  }

  function cueKey(state) {
    if (state === 'dark') {
      return torchSupported.value ? 'cueDarkTorch' : 'cueDark'
    }
    if (state === 'moving') {
      return 'cueMoving'
    }
    return 'cueBlurry'
  }

  function tick() {
    if (isDisposed()) {
      stop()
      return
    }
    const video = videoEl.value
    if (!isLive() || !video || !video.videoWidth || !ctx) {
      reset()
      return
    }
    if (liveSince === null) {
      liveSince = Date.now()
    }
    let pixels
    try {
      ctx.drawImage(video, 0, 0, FRAME_W, FRAME_H)
      pixels = ctx.getImageData(0, 0, FRAME_W, FRAME_H).data
    } catch {
      return
    }
    const stats = computeStats(pixels, prevLuma)
    prevLuma = stats.luma
    lastStats.value = {
      brightness: stats.brightness,
      sharpness: stats.sharpness,
      motion: stats.motion,
    }
    const state = classifyFrame(stats)
    if (state === lastState) {
      heldCount += 1
    } else {
      lastState = state
      heldCount = 1
    }
    if (state !== 'ok' && heldCount >= HOLD_SAMPLES) {
      const now = Date.now()
      if (now - lastCueAt >= CUE_COOLDOWN_MS && !isSpeaking.value) {
        lastCueAt = now
        speak(t(cueKey(state)))
      }
    }
    // Auto-capture only counts steady samples after the warm-up, so the
    // camera's exposure has settled first.
    if (Date.now() - liveSince < WARMUP_MS) {
      okCount = 0
    } else if (state === 'ok') {
      okCount += 1
    } else {
      okCount = 0
    }
    if (autoCapture && okCount >= OK_SAMPLES) {
      stop()
      earcons.ready()
      onAutoCapture()
    }
  }

  function start() {
    stop()
    reset()
    lastCueAt = 0
    timer = setInterval(tick, TICK_MS)
  }

  function stop() {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
    reset()
  }

  onBeforeUnmount(stop)

  return { start, stop, lastStats }
}
