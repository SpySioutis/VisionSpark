import { onBeforeUnmount } from 'vue'

/**
 * Short non-speech sounds (earcons) for state changes. One AudioContext,
 * created lazily and resumed in a user gesture; a soft tick while working.
 * Earcons always play; spoken cues still go through speakStatus(), which
 * respects the "announce" toggle.
 */
export function useEarcons({ isDisposed }) {
  let ctx = null
  let workingTimer = null

  function audio() {
    if (typeof window === 'undefined') {
      return null
    }
    const AC = window.AudioContext || window.webkitAudioContext
    if (!AC) {
      return null
    }
    if (!ctx) {
      try {
        ctx = new AC()
      } catch {
        return null
      }
    }
    if (ctx.state === 'suspended') {
      ctx.resume().catch(() => {})
    }
    return ctx
  }

  function beep(freq, ms, gainValue = 0.15, delaySec = 0) {
    const ac = audio()
    if (!ac || isDisposed()) {
      return
    }
    try {
      const osc = ac.createOscillator()
      const gain = ac.createGain()
      const t0 = ac.currentTime + delaySec
      osc.frequency.value = freq
      gain.gain.setValueAtTime(0.0001, t0)
      gain.gain.exponentialRampToValueAtTime(gainValue, t0 + 0.01)
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + ms / 1000)
      osc.connect(gain)
      gain.connect(ac.destination)
      osc.start(t0)
      osc.stop(t0 + ms / 1000 + 0.05)
    } catch {
      // Audio unavailable: stay silent.
    }
  }

  function vibrate(ms) {
    if (typeof navigator === 'undefined') {
      return
    }
    try {
      navigator.vibrate?.(ms)
    } catch {
      // Not supported: ignore.
    }
  }

  const ready = () => beep(880, 90)
  const captured = () => {
    beep(660, 80)
    beep(990, 100, 0.15, 0.09)
    vibrate(60)
  }
  const done = () => {
    beep(784, 90)
    beep(1047, 140, 0.15, 0.1)
  }
  const error = () => {
    beep(220, 200)
    vibrate(200)
  }
  const recStart = () => beep(520, 70)
  const recStop = () => beep(390, 70)

  function startWorking() {
    stopWorking()
    const tick = () => {
      if (!isDisposed()) {
        beep(440, 50, 0.06)
      }
    }
    tick()
    workingTimer = setInterval(tick, 1000)
  }

  function stopWorking() {
    if (workingTimer !== null) {
      clearInterval(workingTimer)
      workingTimer = null
    }
  }

  function dispose() {
    stopWorking()
    if (ctx) {
      ctx.close().catch(() => {})
      ctx = null
    }
  }

  onBeforeUnmount(dispose)

  return {
    ready,
    captured,
    startWorking,
    stopWorking,
    done,
    error,
    recStart,
    recStop,
  }
}
