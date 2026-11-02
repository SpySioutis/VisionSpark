import { onBeforeUnmount, ref } from 'vue'
import { WAV_SAMPLE_RATE, encodeWav, resampleToMono16k } from '../lib/wav.js'

/**
 * Microphone recording for spoken questions: getUserMedia -> MediaRecorder
 * -> decodeAudioData -> mono 16 kHz WAV bytes (lib/wav.js).
 *
 * The owner starts/stops recording and POSTs the WAV itself. Stops share
 * one promise so an auto-stop and a manual stop never double-handle.
 * Every mic track stops right after recording (on iOS an open mic routes
 * playback to the earpiece).
 */
export function useVoiceQuestion({ isDisposed, earcons }) {
  const voiceSupported =
    typeof window !== 'undefined' &&
    window.isSecureContext &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== 'undefined'
  const recording = ref(false)
  // Translatable message descriptor ({ key }) or null. Rendered via msgText().
  const recordDetail = ref(null)
  let mediaStream = null
  let recorder = null
  let chunks = []
  let recordGen = 0
  let stopPromise = null

  function stopTracks() {
    if (mediaStream) {
      mediaStream.getTracks().forEach((track) => track.stop())
      mediaStream = null
    }
  }

  function micError(error) {
    switch (error?.name) {
      case 'NotAllowedError':
      case 'SecurityError':
        return { key: 'micErrDenied' }
      case 'NotFoundError':
      case 'DevicesNotFoundError':
      case 'OverconstrainedError':
        return { key: 'micErrNoMic' }
      case 'NotReadableError':
      case 'TrackStartError':
        return { key: 'micErrBusy' }
      default:
        return { key: 'micErrNoMic' }
    }
  }

  async function startRecording() {
    if (!voiceSupported || recording.value) {
      return false
    }
    const gen = ++recordGen
    recordDetail.value = null
    let stream
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
        video: false,
      })
    } catch (error) {
      if (gen !== recordGen || isDisposed()) {
        return false
      }
      recordDetail.value = micError(error)
      return false
    }
    if (gen !== recordGen || isDisposed()) {
      stream.getTracks().forEach((track) => track.stop())
      return false
    }
    mediaStream = stream
    chunks = []
    stopPromise = null
    try {
      recorder = new MediaRecorder(stream)
    } catch {
      stopTracks()
      recordDetail.value = { key: 'micErrNoMic' }
      return false
    }
    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        chunks.push(event.data)
      }
    }
    recorder.start()
    recording.value = true
    earcons.recStart()
    return true
  }

  async function doStop() {
    const stopped = new Promise((resolve) => {
      recorder.onstop = () => resolve()
    })
    try {
      recorder.stop()
    } catch {
      // Already stopped.
    }
    await stopped
    recording.value = false
    earcons.recStop()
    stopTracks()
    const taken = chunks
    const mimeType = recorder?.mimeType || 'audio/webm'
    recorder = null
    chunks = []
    if (taken.length === 0) {
      return { wav: null, durationS: 0 }
    }
    try {
      const buffer = await new Blob(taken, { type: mimeType }).arrayBuffer()
      const AC = window.AudioContext || window.webkitAudioContext
      const ac = new AC()
      let decoded
      try {
        decoded = await ac.decodeAudioData(buffer)
      } finally {
        ac.close().catch(() => {})
      }
      const channels = []
      for (let c = 0; c < decoded.numberOfChannels; c += 1) {
        channels.push(decoded.getChannelData(c))
      }
      const mono = resampleToMono16k(channels, decoded.sampleRate)
      return { wav: encodeWav(mono), durationS: mono.length / WAV_SAMPLE_RATE }
    } catch {
      return { wav: null, durationS: 0 }
    }
  }

  function stopRecording() {
    if (!stopPromise) {
      if (!recording.value) {
        return Promise.resolve(null)
      }
      stopPromise = doStop()
    }
    return stopPromise
  }

  function cancelRecording() {
    recordGen += 1
    stopPromise = null
    try {
      recorder?.stop()
    } catch {
      // Already stopped.
    }
    recorder = null
    chunks = []
    stopTracks()
    recording.value = false
  }

  onBeforeUnmount(() => {
    cancelRecording()
  })

  return {
    voiceSupported,
    recording,
    recordDetail,
    startRecording,
    stopRecording,
    cancelRecording,
  }
}
