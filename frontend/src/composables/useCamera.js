import { nextTick, onBeforeUnmount, ref } from 'vue'

// Requested camera resolution. Trying 3840x2160 on a phone is a one-line change.
const CAPTURE_WIDTH = 1920
const CAPTURE_HEIGHT = 1080
// Captures keep the full video resolution up to this edge, so SAM crops use
// every pixel. The quality ladder below keeps the file under the backend's
// 5 MiB upload limit.
const MAX_CAPTURE_EDGE = 3840
const MAX_CAPTURE_BYTES = 5 * 1024 * 1024
const CAPTURE_QUALITIES = [0.9, 0.8, 0.7]
const CAPTURE_SHRINK = 0.8
const CAPTURE_ATTEMPTS = 10

/**
 * Camera capture. The stream starts only after an explicit user action and
 * every track is stopped on capture, stop, image switch, or unmount.
 *
 * Calls onCapture(file) with the captured JPEG; the owner wires it to its
 * own image state.
 *
 * captureAnnouncement: undefined speaks t('speakPhotoReady') after capture;
 * null stays silent (the caller plays an earcon instead); a string is
 * spoken as-is.
 */
export function useCamera({ t, speakStatus, isDisposed, onCapture, captureAnnouncement }) {
  const cameraSupported =
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia
  // Browsers hide mediaDevices on plain-HTTP LAN addresses. When the camera
  // is missing for that reason, the UI points at the HTTPS mode instead.
  const cameraNeedsHttps =
    !cameraSupported &&
    typeof window !== 'undefined' &&
    window.isSecureContext === false
  const camStatus = ref('idle') // 'idle' | 'starting' | 'live' | 'error'
  // Translatable message descriptors ({ key, params }) or null, so the UI
  // re-renders them when the locale changes. Rendered via msgText().
  const camDetail = ref(null)
  const camFlash = ref(null)
  const videoEl = ref(null)
  // True while the live track reports a torch capability (Android Chrome;
  // iOS has none, so the button stays hidden there).
  const torchSupported = ref(false)
  let mediaStream = null
  let cameraGen = 0

  function currentTrack() {
    return mediaStream?.getVideoTracks?.()?.[0] ?? null
  }

  async function setTorch(on) {
    const track = currentTrack()
    if (!track?.applyConstraints) {
      return false
    }
    try {
      await track.applyConstraints({ advanced: [{ torch: on }] })
      return true
    } catch {
      return false
    }
  }

  function updateTorchSupport() {
    const caps = currentTrack()?.getCapabilities?.()
    if (!isDisposed()) {
      torchSupported.value = !!caps && 'torch' in caps
    }
  }

  function stopTracks() {
    if (mediaStream) {
      mediaStream.getTracks().forEach((track) => track.stop())
      mediaStream = null
    }
    if (videoEl.value) {
      videoEl.value.srcObject = null
    }
  }

  function stopCamera() {
    cameraGen += 1 // invalidate any in-flight getUserMedia request
    setTorch(false) // never rejects; stopping the tracks kills the light anyway
    stopTracks()
    if (!isDisposed()) {
      camStatus.value = 'idle'
      camFlash.value = null
      torchSupported.value = false
    }
  }

  function cameraError(error) {
    switch (error?.name) {
      case 'NotAllowedError':
      case 'SecurityError':
        return { key: 'camErrDenied' }
      case 'NotFoundError':
      case 'DevicesNotFoundError':
      case 'OverconstrainedError':
        return { key: 'camErrNoCam' }
      case 'NotReadableError':
      case 'TrackStartError':
        return { key: 'camErrBusy' }
      case 'AbortError':
        return { key: 'camErrAbort' }
      default:
        return { key: 'camErrGeneric' }
    }
  }

  async function startCamera() {
    if (
      !cameraSupported ||
      camStatus.value === 'starting' ||
      camStatus.value === 'live'
    ) {
      return
    }
    const gen = ++cameraGen
    camStatus.value = 'starting'
    camDetail.value = null
    camFlash.value = null
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: CAPTURE_WIDTH },
          height: { ideal: CAPTURE_HEIGHT },
        },
        audio: false,
      })
      if (gen !== cameraGen || isDisposed()) {
        stream.getTracks().forEach((track) => track.stop())
        return
      }
      mediaStream = stream
      await nextTick()
      if (gen !== cameraGen || isDisposed() || !videoEl.value) {
        stopTracks()
        return
      }
      videoEl.value.srcObject = stream
      try {
        await videoEl.value.play()
      } catch {
        // Autoplay attribute covers most cases; a paused frame can still render.
      }
      if (isDisposed()) {
        stopTracks()
        return
      }
      camStatus.value = 'live'
      updateTorchSupport()
    } catch (error) {
      if (gen !== cameraGen || isDisposed()) {
        return
      }
      stopTracks()
      camStatus.value = 'error'
      camDetail.value = cameraError(error)
    }
  }

  function encodeCanvas(canvas, quality) {
    return new Promise((resolve) => {
      canvas.toBlob((blob) => resolve(blob), 'image/jpeg', quality)
    })
  }

  // Encode the live frame at full resolution: JPEG qualities 0.9, 0.8, 0.7,
  // then shrink by 0.8 and repeat, until the file fits the upload limit.
  async function encodeCapture(video) {
    const edge = Math.max(video.videoWidth, video.videoHeight)
    let scale = Math.min(1, MAX_CAPTURE_EDGE / edge)
    for (let attempt = 0; attempt < CAPTURE_ATTEMPTS; attempt += 1) {
      const canvas = document.createElement('canvas')
      canvas.width = Math.max(1, Math.round(video.videoWidth * scale))
      canvas.height = Math.max(1, Math.round(video.videoHeight * scale))
      const ctx = canvas.getContext('2d')
      if (!ctx) {
        return null
      }
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
      for (const quality of CAPTURE_QUALITIES) {
        const blob = await encodeCanvas(canvas, quality)
        if (blob && blob.size <= MAX_CAPTURE_BYTES) {
          return new File([blob], 'camera-photo.jpg', { type: 'image/jpeg' })
        }
      }
      scale *= CAPTURE_SHRINK
    }
    return null
  }

  async function capturePhoto() {
    const video = videoEl.value
    if (!video || camStatus.value !== 'live' || !video.videoWidth) {
      stopTracks()
      camStatus.value = 'error'
      camDetail.value = { key: 'camErrNoFrame' }
      return
    }
    const file = await encodeCapture(video)
    if (isDisposed()) {
      return
    }
    if (!file) {
      stopTracks()
      camStatus.value = 'error'
      camDetail.value = { key: 'camErrCapture' }
      return
    }
    onCapture(file)
    stopTracks()
    camStatus.value = 'idle'
    camFlash.value = { key: 'camCaptured' }
    // Defer so the invalidated-answer watcher (queued by setSelectedFile)
    // flushes first and cannot cancel this announcement.
    nextTick(() => {
      if (isDisposed() || captureAnnouncement === null) {
        return
      }
      speakStatus(
        typeof captureAnnouncement === 'string'
          ? captureAnnouncement
          : t('speakPhotoReady'),
      )
    })
  }

  onBeforeUnmount(() => {
    cameraGen += 1
    stopTracks()
  })

  return {
    cameraSupported,
    cameraNeedsHttps,
    camStatus,
    camDetail,
    camFlash,
    videoEl,
    torchSupported,
    setTorch,
    startCamera,
    stopCamera,
    capturePhoto,
  }
}
