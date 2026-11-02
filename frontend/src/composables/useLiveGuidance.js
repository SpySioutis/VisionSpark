import { onBeforeUnmount } from 'vue'
import { backendUrl } from '../lib/api.js'
import { bestBox, guideForBox } from '../lib/boxes.js'

const GUIDE_MS = 1500
const GUIDE_EDGE = 640
const GUIDE_QUALITY = 0.7

/**
 * Level-3 live SAM guidance: while the camera is live, send a downscaled
 * still frame to /api/segment every 1.5 s and speak move cues from the
 * most confident box. Centered, large enough, and still means
 * auto-capture. Best-effort and silent on failure; never more than one
 * request in flight; aborted on stop.
 */
export function useLiveGuidance({
  videoEl,
  isLive,
  isSpeaking,
  isDisposed,
  speak,
  t,
  earcons,
  stillCheck,
  onAutoCapture,
}) {
  let timer = null
  let controller = null
  let inFlight = false
  let guideGen = 0

  function handleBoxes(boxes) {
    const best = bestBox(boxes)
    if (!best) {
      return
    }
    const guide = guideForBox(best)
    if (guide === 'centered') {
      if (stillCheck()) {
        stop()
        earcons.ready()
        onAutoCapture()
      }
      return
    }
    if (!isSpeaking.value && !isDisposed()) {
      speak(t(`guide${guide.slice('move'.length)}`))
    }
  }

  async function tick() {
    if (isDisposed()) {
      stop()
      return
    }
    const video = videoEl.value
    if (!isLive() || !video || !video.videoWidth || inFlight) {
      return
    }
    const scale = Math.min(
      1,
      GUIDE_EDGE / Math.max(video.videoWidth, video.videoHeight),
    )
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale))
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale))
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      return
    }
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise((resolve) => {
      canvas.toBlob(resolve, 'image/jpeg', GUIDE_QUALITY)
    })
    if (!blob || isDisposed() || !isLive()) {
      return
    }
    const gen = guideGen
    inFlight = true
    const ctrl = new AbortController()
    controller = ctrl
    try {
      const form = new FormData()
      form.append('image', blob, 'guide.jpg')
      form.append('prompt', 'label')
      const response = await fetch(`${backendUrl}/api/segment`, {
        method: 'POST',
        body: form,
        signal: ctrl.signal,
      })
      if (gen !== guideGen || isDisposed() || !isLive()) {
        return
      }
      if (!response.ok) {
        return
      }
      const data = await response.json()
      if (gen !== guideGen || isDisposed() || !isLive()) {
        return
      }
      handleBoxes(data?.boxes ?? [])
    } catch {
      // Aborted or unreachable: guidance is best-effort, stay silent.
    } finally {
      if (gen === guideGen) {
        inFlight = false
        controller = null
      }
    }
  }

  function start() {
    stop()
    guideGen += 1
    timer = setInterval(tick, GUIDE_MS)
  }

  function stop() {
    guideGen += 1
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
    controller?.abort()
    controller = null
    inFlight = false
  }

  onBeforeUnmount(stop)

  return { start, stop }
}
