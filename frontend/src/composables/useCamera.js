import { nextTick, onBeforeUnmount, ref } from 'vue'

const MAX_CAPTURE_EDGE = 1600

/**
 * Camera capture. The stream starts only after an explicit user action and
 * every track is stopped on capture, stop, image switch, or unmount.
 *
 * Calls onCapture(file) with the captured JPEG; the owner wires it to its
 * own image state.
 */
export function useCamera({ t, speakStatus, isDisposed, onCapture }) {
  const cameraSupported =
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia
  const camStatus = ref('idle') // 'idle' | 'starting' | 'live' | 'error'
  // Translatable message descriptors ({ key, params }) or null, so the UI
  // re-renders them when the locale changes. Rendered via msgText().
  const camDetail = ref(null)
  const camFlash = ref(null)
  const videoEl = ref(null)
  let mediaStream = null
  let cameraGen = 0

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
    stopTracks()
    if (!isDisposed()) {
      camStatus.value = 'idle'
      camFlash.value = null
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
        video: { facingMode: { ideal: 'environment' } },
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
    } catch (error) {
      if (gen !== cameraGen || isDisposed()) {
        return
      }
      stopTracks()
      camStatus.value = 'error'
      camDetail.value = cameraError(error)
    }
  }

  function capturePhoto() {
    const video = videoEl.value
    if (!video || camStatus.value !== 'live' || !video.videoWidth) {
      stopTracks()
      camStatus.value = 'error'
      camDetail.value = { key: 'camErrNoFrame' }
      return
    }
    const scale = Math.min(
      1,
      MAX_CAPTURE_EDGE / Math.max(video.videoWidth, video.videoHeight),
    )
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(video.videoWidth * scale)
    canvas.height = Math.round(video.videoHeight * scale)
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      stopTracks()
      camStatus.value = 'error'
      camDetail.value = { key: 'camErrCapture' }
      return
    }
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
    canvas.toBlob(
      (blob) => {
        if (isDisposed()) {
          return
        }
        if (!blob) {
          stopTracks()
          camStatus.value = 'error'
          camDetail.value = { key: 'camErrCapture' }
          return
        }
        onCapture(new File([blob], 'camera-photo.jpg', { type: 'image/jpeg' }))
        stopTracks()
        camStatus.value = 'idle'
        camFlash.value = { key: 'camCaptured' }
        // Defer so the invalidated-answer watcher (queued by setSelectedFile)
        // flushes first and cannot cancel this announcement.
        nextTick(() => {
          if (!isDisposed()) {
            speakStatus(t('speakPhotoReady'))
          }
        })
      },
      'image/jpeg',
      0.85,
    )
  }

  onBeforeUnmount(() => {
    cameraGen += 1
    stopTracks()
  })

  return {
    cameraSupported,
    camStatus,
    camDetail,
    camFlash,
    videoEl,
    startCamera,
    stopCamera,
    capturePhoto,
  }
}
