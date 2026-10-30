<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ANSWER_LANG_NAME, LOCALES, STRINGS, VOICE_LANG, translate } from './i18n.js'

const backendUrl =
  import.meta.env.VITE_BACKEND_URL ?? 'http://localhost:8000'

// Backend reachability is checked automatically (on load, then every 30 s).
// There is no manual health check in the UI.
const status = ref('idle') // 'idle' | 'success' | 'error'
let statusTimer = null

// UI language (English, French, Spanish, Greek, Chinese).
// Persisted across visits; otherwise English.
const LOCALE_KEY = 'visionspark-locale'
function detectLocale() {
  try {
    const stored = localStorage.getItem(LOCALE_KEY)
    if (stored && STRINGS[stored]) {
      return stored
    }
  } catch {
    // Private mode or blocked storage: fall through to browser language.
  }
  // Default is always English; a stored choice wins when present.
  return 'en'
}
const locale = ref(detectLocale())
function t(key, params) {
  return translate(locale.value, key, params)
}
watch(locale, (value) => {
  try {
    localStorage.setItem(LOCALE_KEY, value)
  } catch {
    // Storage unavailable: the choice still applies for this visit.
  }
  if (typeof document !== 'undefined') {
    document.documentElement.lang = value
  }
})
if (typeof document !== 'undefined') {
  document.documentElement.lang = locale.value
}

// Color theme (System, Light, Dark), persisted like the locale. An
// explicit choice sets data-theme on <html>; System removes it so the
// OS preference in style.css applies.
const THEME_KEY = 'visionspark-theme'
function loadTheme() {
  try {
    const stored = localStorage.getItem(THEME_KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'system') {
      return stored
    }
  } catch {
    // Private mode or blocked storage: fall through to System.
  }
  return 'system'
}
const theme = ref(loadTheme())
function applyTheme() {
  if (typeof document === 'undefined') {
    return
  }
  if (theme.value === 'system') {
    document.documentElement.removeAttribute('data-theme')
  } else {
    document.documentElement.dataset.theme = theme.value
  }
}
watch(theme, (value) => {
  try {
    localStorage.setItem(THEME_KEY, value)
  } catch {
    // Storage unavailable: the choice still applies for this visit.
  }
  applyTheme()
})
applyTheme()

const MAX_BYTES = 5 * 1024 * 1024
const MAX_CAPTURE_EDGE = 1600
const selectedFile = ref(null)
const fileInputEl = ref(null)
const prompt = ref('label')
const segStatus = ref('idle') // 'idle' | 'loading' | 'success' | 'error'
const segDetail = ref('')
const boxes = ref([])

// Visual question answering reuses the uploaded image.
const question = ref('')
const askStatus = ref('idle') // 'idle' | 'loading' | 'success' | 'error'
const askDetail = ref('')
const answer = ref('')
// What the next (or last) answer covers: 'full' or 'region' + regionIndex.
const askTarget = ref('full')
const regionIndex = ref(0)
const answerSource = ref('')

// Audio-first wizard: one screen per action.
// 1 = Photo (capture/upload), 2 = Check (preview + find region),
// 3 = Ask (presets/question + target), 4 = Listen (answer, read aloud).
const step = ref(1)
const STEP_NAMES = ['wizPhoto', 'wizCheck', 'wizAsk', 'wizListen']
function stepName(n) {
  return t(STEP_NAMES[n - 1] ?? 'wizPhoto')
}

// Text-to-speech for the Q&A answer via the Web Speech API (no backend needed).
const speechSupported =
  typeof window !== 'undefined' &&
  'speechSynthesis' in window &&
  'SpeechSynthesisUtterance' in window
const isSpeaking = ref(false)
const speechNote = ref('')
let disposed = false

// Voice preferences: speaking rate, tone (pitch), per-language voice
// choice, auto-read and spoken-announcement toggles. Persisted across
// visits like the locale. Each `voices[locale]` entry is '' (system
// default), 'feminine', 'masculine', or a specific voiceURI, so switching
// languages never leaves a foreign-language voice selected.
const VOICE_PREFS_KEY = 'visionspark-voice-prefs'
const MIN_RATE = 0.5
const MAX_RATE = 2
const MIN_PITCH = 0.5
const MAX_PITCH = 1.5
function clampRate(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) {
    return 1
  }
  return Math.min(MAX_RATE, Math.max(MIN_RATE, n))
}
function clampPitch(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) {
    return 1
  }
  return Math.min(MAX_PITCH, Math.max(MIN_PITCH, n))
}
function loadVoicePrefs() {
  const prefs = { rate: 1, pitch: 1, voices: {}, autoRead: true, announce: true }
  try {
    const stored = JSON.parse(localStorage.getItem(VOICE_PREFS_KEY) ?? 'null')
    if (stored && typeof stored === 'object') {
      prefs.rate = clampRate(stored.rate)
      prefs.pitch = clampPitch(stored.pitch)
      if (stored.voices && typeof stored.voices === 'object') {
        for (const [code, choice] of Object.entries(stored.voices)) {
          if (typeof choice === 'string') {
            prefs.voices[code] = choice
          }
        }
      } else {
        // Migrate the pre-per-language single choice onto the current locale.
        const legacy = stored.voice ?? stored.voiceURI
        if (typeof legacy === 'string' && legacy) {
          prefs.voices[locale.value] = legacy
        }
      }
      prefs.autoRead = stored.autoRead !== false
      prefs.announce = stored.announce !== false
    }
  } catch {
    // Private mode or corrupt data: fall through to defaults.
  }
  return prefs
}
const voicePrefs = ref(loadVoicePrefs())
watch(
  voicePrefs,
  (value) => {
    try {
      localStorage.setItem(VOICE_PREFS_KEY, JSON.stringify(value))
    } catch {
      // Storage unavailable: the choice still applies for this visit.
    }
  },
  { deep: true },
)

// The voice choice for the current UI language (bound to the picker).
const currentVoice = computed({
  get: () => voicePrefs.value.voices[locale.value] ?? '',
  set: (value) => {
    voicePrefs.value.voices[locale.value] = value
  },
})

// System voices for the speech picker. Browsers load these
// asynchronously, so the list refreshes via onvoiceschanged.
const availableVoices = ref([])
function refreshVoices() {
  if (!speechSupported || disposed) {
    return
  }
  try {
    availableVoices.value = window.speechSynthesis.getVoices()
  } catch {
    availableVoices.value = []
  }
}
// Voices matching the UI language first; fall back to the full list when
// none match (some browsers report unusual language tags).
const matchingVoices = computed(() => {
  const prefix = (VOICE_LANG[locale.value] ?? 'en-US').split('-')[0].toLowerCase()
  const matching = availableVoices.value.filter((voice) =>
    (voice.lang ?? '').toLowerCase().startsWith(prefix),
  )
  return matching.length > 0 ? matching : availableVoices.value
})
const selectedVoice = computed(() => {
  const choice = currentVoice.value
  // Style shortcuts ('feminine'/'masculine') resolve dynamically in
  // resolveVoice(); only a stored voiceURI points at a specific voice.
  if (!choice || choice === 'feminine' || choice === 'masculine') {
    return null
  }
  return (
    availableVoices.value.find((voice) => voice.voiceURI === choice) ?? null
  )
})
// Picker options: matching voices, plus the stored choice on top when it
// is not among them (e.g. a voice whose language tag the browser reports
// oddly) so the select never renders blank.
const voiceOptions = computed(() => {
  if (selectedVoice.value && !matchingVoices.value.includes(selectedVoice.value)) {
    return [selectedVoice.value, ...matchingVoices.value]
  }
  return matchingVoices.value
})
// Best-effort guess of a system voice's perceived style from its name: the
// Web Speech API exposes no gender metadata, so Woman/Man matches these
// hints and falls back to the default voice when nothing matches.
// Whole-word matching keeps "man" from matching "german"/"woman" and
// "male" from matching "female".
const FEMININE_VOICE_HINTS = [
  'female', 'woman', 'women', 'lady', 'feminine', 'girl',
  'samantha', 'victoria', 'zira', 'aria', 'jenny', 'sonia', 'karen',
  'moira', 'tessa', 'veena', 'susan', 'kate', 'serena', 'amelie',
  'marie', 'anna', 'helena', 'katja', 'paulina',
]
const MASCULINE_VOICE_HINTS = [
  'male', 'man', 'men', 'masculine', 'boy',
  'daniel', 'david', 'alex', 'fred', 'guy', 'davis', 'jason',
  'george', 'thomas', 'paul', 'rafael', 'horst', 'pablo',
]
function guessVoiceGender(voice) {
  const text = `${voice?.name ?? ''} ${voice?.voiceURI ?? ''}`.toLowerCase()
  const has = (hint) => new RegExp(`\\b${hint}\\b`).test(text)
  if (FEMININE_VOICE_HINTS.some(has)) {
    return 'feminine'
  }
  if (MASCULINE_VOICE_HINTS.some(has)) {
    return 'masculine'
  }
  return null
}
function resolveVoice() {
  const choice = currentVoice.value
  if (!choice) {
    return null
  }
  if (choice === 'feminine' || choice === 'masculine') {
    return (
      matchingVoices.value.find((voice) => guessVoiceGender(voice) === choice) ??
      availableVoices.value.find((voice) => guessVoiceGender(voice) === choice) ??
      null
    )
  }
  return (
    availableVoices.value.find((voice) => voice.voiceURI === choice) ?? null
  )
}
function configureUtterance(utterance) {
  utterance.lang = VOICE_LANG[locale.value] ?? 'en-US'
  utterance.rate = clampRate(voicePrefs.value.rate)
  utterance.pitch = clampPitch(voicePrefs.value.pitch)
  const voice = resolveVoice()
  if (voice) {
    utterance.voice = voice
    utterance.lang = voice.lang
  }
}

function announceSpeech(text) {
  if (!disposed) {
    speechNote.value = text
  }
}

function cancelSpeech() {
  if (speechSupported) {
    window.speechSynthesis.cancel()
  }
  if (!disposed) {
    isSpeaking.value = false
  }
}

function stopSpeaking() {
  const wasSpeaking = isSpeaking.value
  cancelSpeech()
  if (wasSpeaking) {
    announceSpeech(t('srStopped'))
  }
}

function readAnswerAloud() {
  if (!speechSupported || !answer.value) {
    return
  }
  cancelSpeech()
  const utterance = new SpeechSynthesisUtterance(answer.value)
  configureUtterance(utterance)
  // Programmatic cancels set isSpeaking false synchronously first, so a
  // still-true flag here means a genuine end or error worth announcing.
  utterance.onend = () => {
    if (!disposed && isSpeaking.value) {
      isSpeaking.value = false
      speechNote.value = t('srDone')
    }
  }
  utterance.onerror = () => {
    if (!disposed && isSpeaking.value) {
      isSpeaking.value = false
      speechNote.value = t('srInterrupted')
    }
  }
  isSpeaking.value = true
  announceSpeech(t('srReading'))
  window.speechSynthesis.speak(utterance)
}

// Short spoken status updates ("Photo ready", "Found 3 objects").
// Uses the same synthesis queue as the answer so Stop cancels either one;
// the sr-only live region mirrors the text for screen-reader users.
// When announcements are off, only the live region updates (no audio).
function speakStatus(text) {
  if (!text || disposed) {
    return
  }
  if (!speechSupported || !voicePrefs.value.announce) {
    announceSpeech(text)
    return
  }
  cancelSpeech()
  const utterance = new SpeechSynthesisUtterance(text)
  configureUtterance(utterance)
  utterance.onend = () => {
    if (!disposed && isSpeaking.value) {
      isSpeaking.value = false
    }
  }
  utterance.onerror = () => {
    if (!disposed && isSpeaking.value) {
      isSpeaking.value = false
    }
  }
  isSpeaking.value = true
  announceSpeech(text)
  try {
    window.speechSynthesis.speak(utterance)
  } catch {
    if (!disposed) {
      isSpeaking.value = false
    }
  }
}

// Voice-preferences preview: speaks a sample with the current rate and
// voice even when spoken announcements are turned off.
function previewVoice() {
  if (!speechSupported || isSpeaking.value || disposed) {
    return
  }
  cancelSpeech()
  const utterance = new SpeechSynthesisUtterance(t('voicePreviewSample'))
  configureUtterance(utterance)
  utterance.onend = () => {
    if (!disposed && isSpeaking.value) {
      isSpeaking.value = false
    }
  }
  utterance.onerror = () => {
    if (!disposed && isSpeaking.value) {
      isSpeaking.value = false
    }
  }
  isSpeaking.value = true
  announceSpeech(t('srReading'))
  try {
    window.speechSynthesis.speak(utterance)
  } catch {
    if (!disposed) {
      isSpeaking.value = false
    }
  }
}

// Wizard navigation. Leaving step 1 stops a live camera (hidden video
// would keep streaming otherwise). Focus moves to the new step heading
// and the step is announced aloud, except step 4 with an answer — the
// answer itself is read instead so the two speeches do not collide.
function goStep(n) {
  const next = Math.min(4, Math.max(1, n))
  if (next !== 1 && (camStatus.value === 'live' || camStatus.value === 'starting')) {
    stopCamera()
  }
  step.value = next
  nextTick(() => {
    if (disposed) {
      return
    }
    const heading = document.getElementById(`step-${next}-heading`)
    if (heading) {
      heading.focus({ preventScroll: false })
    }
    if (next === 4 && askStatus.value === 'success') {
      return
    }
    speakStatus(
      `${t('wizKicker', { n: next, name: stepName(next) })}. ${stepHeading(next)}`,
    )
  })
}

function stepHeading(n) {
  switch (n) {
    case 1:
      return t('s1heading')
    case 2:
      return t('wizCheckHeading')
    case 3:
      return t('s2heading')
    default:
      return t('wizListenHeading')
  }
}

function startOver() {
  cancelSpeech()
  stopCamera()
  if (fileInputEl.value) {
    fileInputEl.value.value = ''
  }
  setSelectedFile(null)
  goStep(1)
}

// One-tap preset question: fills the question and asks immediately,
// so no typing is needed.
function askPreset(presetKey) {
  if (askStatus.value === 'loading' || !selectedFile.value) {
    return
  }
  question.value = t(presetKey)
  runAsk()
}

function primaryAction() {
  if (step.value === 1) {
    goStep(2)
  } else if (step.value === 2) {
    goStep(3)
  } else if (step.value === 3) {
    runAsk()
  } else {
    startOver()
  }
}

// Sticky-bar primary button: Continue → Continue → Ask → Start over.
const primaryDisabled = computed(() => {
  if (step.value === 1) {
    return !selectedFile.value
  }
  if (step.value === 2) {
    return segStatus.value === 'loading'
  }
  if (step.value === 3) {
    return askStatus.value === 'loading' || !selectedFile.value || !question.value.trim()
  }
  return false
})
const primaryLabel = computed(() => {
  if (step.value === 3) {
    return askStatus.value === 'loading' ? t('askingBtn') : t('askBtn')
  }
  if (step.value === 4) {
    return t('wizStartOver')
  }
  return t('wizNext')
})

// Settings dialog (language + voice preferences), opened from the header
// gear button. Native <dialog> gives modal focus handling and Esc-to-close;
// a backdrop click closes it too.
const settingsDialog = ref(null)
function openSettings() {
  if (settingsDialog.value && !settingsDialog.value.open) {
    settingsDialog.value.showModal()
  }
}
function closeSettings() {
  settingsDialog.value?.close()
}
function onSettingsBackdrop(event) {
  if (event.target === settingsDialog.value) {
    closeSettings()
  }
}

// A new (or cleared) answer invalidates any ongoing speech.
watch(answer, () => {
  cancelSpeech()
})

// Camera capture. The stream starts only after an explicit user action and
// every track is stopped on capture, stop, image switch, or unmount.
const cameraSupported =
  typeof navigator !== 'undefined' &&
  !!navigator.mediaDevices?.getUserMedia
const camStatus = ref('idle') // 'idle' | 'starting' | 'live' | 'error'
const camDetail = ref('')
const camFlash = ref('')
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
  if (!disposed) {
    camStatus.value = 'idle'
    camFlash.value = ''
  }
}

function cameraErrorMessage(error) {
  switch (error?.name) {
    case 'NotAllowedError':
    case 'SecurityError':
      return t('camErrDenied')
    case 'NotFoundError':
    case 'DevicesNotFoundError':
    case 'OverconstrainedError':
      return t('camErrNoCam')
    case 'NotReadableError':
    case 'TrackStartError':
      return t('camErrBusy')
    case 'AbortError':
      return t('camErrAbort')
    default:
      return t('camErrGeneric')
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
  camDetail.value = ''
  camFlash.value = ''
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: 'environment' } },
      audio: false,
    })
    if (gen !== cameraGen || disposed) {
      stream.getTracks().forEach((track) => track.stop())
      return
    }
    mediaStream = stream
    await nextTick()
    if (gen !== cameraGen || disposed || !videoEl.value) {
      stopTracks()
      return
    }
    videoEl.value.srcObject = stream
    try {
      await videoEl.value.play()
    } catch {
      // Autoplay attribute covers most cases; a paused frame can still render.
    }
    if (disposed) {
      stopTracks()
      return
    }
    camStatus.value = 'live'
  } catch (error) {
    if (gen !== cameraGen || disposed) {
      return
    }
    stopTracks()
    camStatus.value = 'error'
    camDetail.value = cameraErrorMessage(error)
  }
}

function capturePhoto() {
  const video = videoEl.value
  if (!video || camStatus.value !== 'live' || !video.videoWidth) {
    stopTracks()
    camStatus.value = 'error'
    camDetail.value = t('camErrNoFrame')
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
    camDetail.value = t('camErrCapture')
    return
  }
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
  canvas.toBlob(
    (blob) => {
      if (disposed) {
        return
      }
      if (!blob) {
        stopTracks()
        camStatus.value = 'error'
        camDetail.value = t('camErrCapture')
        return
      }
      setSelectedFile(
        new File([blob], 'camera-photo.jpg', { type: 'image/jpeg' }),
      )
      if (fileInputEl.value) {
        fileInputEl.value.value = ''
      }
      stopTracks()
      camStatus.value = 'idle'
      camFlash.value = t('camCaptured')
      // Defer so the invalidated-answer watcher (queued by setSelectedFile)
      // flushes first and cannot cancel this announcement.
      nextTick(() => {
        if (!disposed) {
          speakStatus(t('speakPhotoReady'))
        }
      })
    },
    'image/jpeg',
    0.85,
  )
}

// Image preview + overlay state. The SVG overlay uses the image's natural
// pixel dimensions as its viewBox so box coordinates map 1:1.
const previewUrl = ref(null)
const previewImgEl = ref(null)
const naturalSize = ref({ w: 0, h: 0 })
const imgError = ref('')

function revokePreview() {
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = null
  }
}

function setPreview() {
  revokePreview()
  naturalSize.value = { w: 0, h: 0 }
  imgError.value = ''
  if (selectedFile.value) {
    previewUrl.value = URL.createObjectURL(selectedFile.value)
  }
}

// Label size scales with the image so numbers stay readable on any resolution.
const labelSize = () => Math.max(14, Math.round(naturalSize.value.h * 0.035))

function labelY(box) {
  const s = labelSize()
  return box.y1 - 8 >= s ? box.y1 - 8 : box.y1 + s + 2
}

function onImgLoad(event) {
  naturalSize.value = {
    w: event.target.naturalWidth,
    h: event.target.naturalHeight,
  }
  imgError.value = ''
}

function onImgError() {
  naturalSize.value = { w: 0, h: 0 }
  imgError.value = t('imgErr')
}

// Crop a SAM box (source-pixel coords in the token's w/h frame) out of the
// original image at its intrinsic size, with 5% padding clamped to bounds.
function cropRegion(box, index) {
  return new Promise((resolve, reject) => {
    const fail = (message) => reject(new Error(message))
    const img = previewImgEl.value
    const nw = naturalSize.value.w
    const nh = naturalSize.value.h
    if (!img || !nw || !nh) {
      fail(t('cropLoading'))
      return
    }
    const coords = [box.x1, box.y1, box.x2, box.y2, box.w, box.h]
    if (
      !coords.every((n) => Number.isFinite(n)) ||
      box.w <= 0 ||
      box.h <= 0 ||
      box.x2 <= box.x1 ||
      box.y2 <= box.y1
    ) {
      fail(t('cropInvalid'))
      return
    }
    const sx = nw / box.w
    const sy = nh / box.h
    const padX = (box.x2 - box.x1) * sx * 0.05
    const padY = (box.y2 - box.y1) * sy * 0.05
    const cx1 = Math.max(0, Math.round(box.x1 * sx - padX))
    const cy1 = Math.max(0, Math.round(box.y1 * sy - padY))
    const cx2 = Math.min(nw, Math.round(box.x2 * sx + padX))
    const cy2 = Math.min(nh, Math.round(box.y2 * sy + padY))
    if (cx2 <= cx1 || cy2 <= cy1) {
      fail(t('cropEmpty'))
      return
    }
    const canvas = document.createElement('canvas')
    canvas.width = cx2 - cx1
    canvas.height = cy2 - cy1
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      fail(t('cropFail'))
      return
    }
    ctx.drawImage(img, cx1, cy1, cx2 - cx1, cy2 - cy1, 0, 0, canvas.width, canvas.height)
    canvas.toBlob(
      (blob) => {
        if (!blob) {
          fail(t('cropFail'))
          return
        }
        resolve(
          new File([blob], `region-${index + 1}.jpg`, { type: 'image/jpeg' }),
        )
      },
      'image/jpeg',
      0.9,
    )
  })
}

// Stale results belong to the previous prompt; clear them when it changes.
watch(prompt, () => {
  if (segStatus.value === 'loading') {
    return
  }
  segStatus.value = 'idle'
  segDetail.value = ''
  boxes.value = []
  // Region targets die with the boxes; fall back to the full image.
  askTarget.value = 'full'
  regionIndex.value = 0
})

// Same for the Q&A answer when the question changes.
watch(question, () => {
  if (askStatus.value === 'loading') {
    return
  }
  clearAnswer()
})

// An answer belongs to its target; changing it invalidates the answer.
watch(askTarget, () => {
  if (askStatus.value === 'loading') {
    return
  }
  clearAnswer()
})

watch(regionIndex, () => {
  if (askStatus.value === 'loading') {
    return
  }
  clearAnswer()
})

onBeforeUnmount(() => {
  disposed = true
  cameraGen += 1
  if (speechSupported) {
    try {
      if (window.speechSynthesis.onvoiceschanged === refreshVoices) {
        window.speechSynthesis.onvoiceschanged = null
      }
    } catch {
      // Already torn down.
    }
  }
  if (statusTimer !== null) {
    clearInterval(statusTimer)
    statusTimer = null
  }
  stopTracks()
  revokePreview()
  cancelSpeech()
})

function clearAnswer() {
  askStatus.value = 'idle'
  askDetail.value = ''
  answer.value = ''
  answerSource.value = ''
}

function resetResults() {
  segStatus.value = 'idle'
  segDetail.value = ''
  boxes.value = []
  askTarget.value = 'full'
  regionIndex.value = 0
  clearAnswer()
}

function setSelectedFile(file) {
  selectedFile.value = file
  resetResults()
  setPreview()
}

function onFileChange(event) {
  stopCamera()
  setSelectedFile(event.target.files?.[0] ?? null)
  if (selectedFile.value) {
    // Defer so the invalidated-answer watcher flushes first (see above).
    nextTick(() => {
      if (!disposed) {
        speakStatus(t('speakPhotoReady'))
      }
    })
  }
}

async function runSegmentation() {
  if (!selectedFile.value) {
    return
  }
  if (selectedFile.value.size > MAX_BYTES) {
    segStatus.value = 'error'
    segDetail.value = t('errTooBig')
    speakStatus(segDetail.value)
    return
  }
  const trimmedPrompt = prompt.value.trim()
  if (!trimmedPrompt) {
    segStatus.value = 'error'
    segDetail.value = t('errPromptEmpty')
    speakStatus(segDetail.value)
    return
  }
  const sentFile = selectedFile.value
  const sentPrompt = trimmedPrompt
  segStatus.value = 'loading'
  segDetail.value = ''
  boxes.value = []
  try {
    const form = new FormData()
    form.append('image', sentFile)
    form.append('prompt', sentPrompt)
    const response = await fetch(`${backendUrl}/api/segment`, {
      method: 'POST',
      body: form,
    })
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      throw new Error(body?.detail ?? `HTTP ${response.status}`)
    }
    const data = await response.json()
    // Drop late responses if the user moved on to another image or prompt.
    if (selectedFile.value !== sentFile || prompt.value.trim() !== sentPrompt) {
      segStatus.value = 'idle'
      segDetail.value = ''
      boxes.value = []
      return
    }
    boxes.value = data?.boxes ?? []
    regionIndex.value = 0
    if (boxes.value.length === 0 && askTarget.value === 'region') {
      askTarget.value = 'full'
    }
    // A region answer refers to the previous boxes; a full-image answer
    // about the same image stays valid.
    if (askStatus.value === 'success' && answerSource.value !== t('srcFull')) {
      clearAnswer()
    }
    segStatus.value = 'success'
    segDetail.value =
      boxes.value.length === 0
        ? t('noObjects')
        : boxes.value.length === 1
          ? t('foundOne')
          : t('foundN', { count: boxes.value.length })
    // Let invalidated-answer watchers settle first so they cannot cancel
    // this announcement (same pattern as the answer speech in runAsk).
    await nextTick()
    if (!disposed && segStatus.value === 'success') {
      speakStatus(segDetail.value)
    }
  } catch (error) {
    if (selectedFile.value !== sentFile || prompt.value.trim() !== sentPrompt) {
      segStatus.value = 'idle'
      segDetail.value = ''
      boxes.value = []
      return
    }
    segStatus.value = 'error'
    segDetail.value = error instanceof Error ? error.message : t('unknownErr')
    speakStatus(segDetail.value)
  }
}

async function runAsk() {
  if (!selectedFile.value) {
    return
  }
  const trimmedQuestion = question.value.trim()
  if (!trimmedQuestion) {
    askStatus.value = 'error'
    askDetail.value = t('errNoQuestion')
    speakStatus(askDetail.value)
    return
  }
  // Resolve which pixels to send. Region mode never silently falls back:
  // without a valid box the request is refused with a clear message.
  let imageToSend = selectedFile.value
  let sourceLabel = t('srcFull')
  const sentKind = askTarget.value
  const sentRegion = regionIndex.value
  if (askTarget.value === 'region') {
    const box = boxes.value[regionIndex.value]
    if (!box) {
      askStatus.value = 'error'
      askDetail.value = t('regionGone')
      speakStatus(askDetail.value)
      return
    }
    const preCropFile = selectedFile.value
    try {
      imageToSend = await cropRegion(box, sentRegion)
    } catch (error) {
      askStatus.value = 'error'
      askDetail.value = error instanceof Error ? error.message : t('unknownErr')
      speakStatus(askDetail.value)
      return
    }
    if (
      selectedFile.value !== preCropFile ||
      askTarget.value !== 'region' ||
      regionIndex.value !== sentRegion
    ) {
      return
    }
    sourceLabel = t('srcRegion', { n: sentRegion + 1 })
  }
  if (imageToSend.size > MAX_BYTES) {
    askStatus.value = 'error'
    askDetail.value = t('errTooBig')
    speakStatus(askDetail.value)
    return
  }
  const sentFile = selectedFile.value
  const sentQuestion = trimmedQuestion
  // Answers come back in the selected UI language.
  const answerLang = ANSWER_LANG_NAME[locale.value]
  const upstreamQuestion = answerLang
    ? `${trimmedQuestion}\n\nPlease answer in ${answerLang}.`
    : trimmedQuestion
  askStatus.value = 'loading'
  askDetail.value = ''
  answer.value = ''
  answerSource.value = ''
  // Let the answer watcher settle first so it cannot cancel this speech.
  await nextTick()
  if (!disposed && askStatus.value === 'loading') {
    speakStatus(t('askLoading'))
  }
  try {
    const form = new FormData()
    form.append('image', imageToSend)
    form.append('question', upstreamQuestion)
    const response = await fetch(`${backendUrl}/api/ask`, {
      method: 'POST',
      body: form,
    })
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      throw new Error(body?.detail ?? `HTTP ${response.status}`)
    }
    const data = await response.json()
    // Drop late responses if the user moved on to another image, question,
    // or question target.
    if (
      selectedFile.value !== sentFile ||
      question.value.trim() !== sentQuestion ||
      askTarget.value !== sentKind ||
      (sentKind === 'region' && regionIndex.value !== sentRegion)
    ) {
      askStatus.value = 'idle'
      askDetail.value = ''
      answer.value = ''
      answerSource.value = ''
      return
    }
    answer.value = data?.answer ?? ''
    answerSource.value = sourceLabel
    askStatus.value = 'success'
    // Wizard: move to the Listen step, then read the answer aloud.
    // goStep skips its own announcement here so it cannot collide with
    // the answer speech. nextTick lets the answer watcher settle first
    // so it cannot cancel this speech.
    goStep(4)
    await nextTick()
    if (!disposed && voicePrefs.value.autoRead) {
      readAnswerAloud()
    }
  } catch (error) {
    if (
      selectedFile.value !== sentFile ||
      question.value.trim() !== sentQuestion ||
      askTarget.value !== sentKind ||
      (sentKind === 'region' && regionIndex.value !== sentRegion)
    ) {
      askStatus.value = 'idle'
      askDetail.value = ''
      answer.value = ''
      answerSource.value = ''
      return
    }
    askStatus.value = 'error'
    askDetail.value = error instanceof Error ? error.message : t('unknownErr')
    speakStatus(askDetail.value)
  }
}

async function refreshBackendStatus() {
  if (disposed) {
    return
  }
  try {
    const response = await fetch(`${backendUrl}/health`)
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }
    const data = await response.json()
    if (!disposed) {
      status.value = data?.status === 'ok' ? 'success' : 'error'
    }
  } catch {
    if (!disposed) {
      status.value = 'error'
    }
  }
}

onMounted(() => {
  refreshBackendStatus()
  statusTimer = setInterval(refreshBackendStatus, 30000)
  refreshVoices()
  if (speechSupported) {
    try {
      window.speechSynthesis.onvoiceschanged = refreshVoices
    } catch {
      // Voice list stays as initially loaded.
    }
  }
})
</script>

<template>
  <header class="site-header">
    <div class="header-inner">
      <div class="brand">
        <span class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 32 32" width="30" height="30">
            <path
              d="M2 16s5.5-9.5 14-9.5S30 16 30 16s-5.5 9.5-14 9.5S2 16 2 16Z"
              fill="none"
              stroke="currentColor"
              stroke-width="2.4"
              stroke-linejoin="round"
            />
            <circle cx="16" cy="16" r="5" fill="currentColor" />
            <circle cx="16" cy="16" r="2" fill="var(--surface)" />
          </svg>
        </span>
        <span class="brand-text">
          <strong>VisionSpark</strong>
          <span>{{ t('brandSub') }}</span>
        </span>
      </div>
      <div class="header-status">
        <button class="btn btn-secondary btn-settings" @click="openSettings">
          <svg
            viewBox="0 0 24 24"
            width="20"
            height="20"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <circle cx="12" cy="12" r="3" />
            <path
              d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"
            />
          </svg>
          {{ t('settingsTitle') }}
        </button>
        <span
          class="pill"
          :class="{
            'pill-ok': status === 'success',
            'pill-err': status === 'error',
          }"
          role="status"
        >
          <span
            class="dot"
            :class="{
              'dot-ok': status === 'success',
              'dot-err': status === 'error',
            }"
            aria-hidden="true"
          ></span>
          <span v-if="status === 'idle'">{{ t('statusConnecting') }}</span>
          <span v-else-if="status === 'success'">{{ t('statusOnline') }}</span>
          <span v-else>{{ t('statusOffline') }}</span>
        </span>
      </div>
    </div>
  </header>

  <main class="container">
    <div class="intro">
      <h1>{{ t('title') }}</h1>
      <p class="tagline">
        {{ t('tagline') }}
      </p>
    </div>

    <nav class="wizard-progress" :aria-label="t('wizLabel')">
      <ol>
        <li
          v-for="n in 4"
          :key="n"
          :aria-current="step === n ? 'step' : undefined"
          :class="{ 'wiz-current': step === n, 'wiz-done': n < step }"
        >
          <span class="wiz-num" aria-hidden="true">{{ n < step ? '✓' : n }}</span>
          <span class="wiz-name">{{ stepName(n) }}</span>
        </li>
      </ol>
      <p class="wizard-count" role="status">{{ t('wizStepOf', { n: step }) }}</p>
    </nav>

    <div class="wizard">

    <section v-show="step === 1" class="card" aria-labelledby="step-1-heading">
      <p class="card-kicker">{{ t('wizKicker', { n: 1, name: stepName(1) }) }}</p>
      <h2 id="step-1-heading" tabindex="-1">{{ t('s1heading') }}</h2>
      <div class="camera camera-first">
        <h3 id="camera-heading" class="camera-title">{{ t('camTitle') }}</h3>
        <div class="camera-buttons">
          <button
            class="btn btn-secondary"
            :disabled="
              !cameraSupported ||
              camStatus === 'starting' ||
              camStatus === 'live'
            "
            @click="startCamera"
          >
            {{ camStatus === 'starting' ? t('camStartingBtn') : t('btnCamera') }}
          </button>
          <button
            class="btn btn-primary"
            :disabled="camStatus !== 'live'"
            @click="capturePhoto"
          >
            {{ t('btnCapture') }}
          </button>
          <button
            class="btn btn-secondary"
            :disabled="camStatus !== 'live' && camStatus !== 'starting'"
            @click="stopCamera"
          >
            {{ t('btnStop') }}
          </button>
        </div>
        <p v-if="!cameraSupported" class="muted">
          {{ t('camUnsupported') }}
        </p>
        <video
          v-if="camStatus === 'starting' || camStatus === 'live'"
          ref="videoEl"
          class="camera-video"
          autoplay
          muted
          playsinline
          :aria-label="t('vidLabel')"
        ></video>
        <div class="status-line" role="status">
          <p v-if="camStatus === 'idle' && !camFlash" class="muted">
            {{ t('camOff') }}
          </p>
          <p v-if="camStatus === 'idle' && camFlash" class="ok">
            ✓ {{ camFlash }}
          </p>
          <p v-if="camStatus === 'starting'" class="muted">
            {{ t('camStarting') }}
          </p>
          <p v-if="camStatus === 'live'" class="muted">
            {{ t('camLive') }}
          </p>
        </div>
        <p v-if="camStatus === 'error'" class="err" role="alert">
          ✗ {{ camDetail }}
        </p>
      </div>
      <div class="upload-alt">
        <label class="prompt-label" for="image-input">{{ t('uploadLabel') }}</label>
        <p class="muted hint" id="image-hint">
          {{ t('uploadHint') }}
        </p>
        <input
          id="image-input"
          ref="fileInputEl"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          aria-describedby="image-hint"
          @change="onFileChange"
        />
      </div>
      <div class="status-line" role="status">
        <p v-if="selectedFile" class="ok">✓ {{ selectedFile.name }}</p>
        <p v-else class="muted">{{ t('wizNeedPhoto') }}</p>
      </div>
    </section>

    <section v-show="step === 2" class="card" aria-labelledby="step-2-heading">
      <p class="card-kicker">{{ t('wizKicker', { n: 2, name: stepName(2) }) }}</p>
      <h2 id="step-2-heading" tabindex="-1">{{ t('wizCheckHeading') }}</h2>
      <figure v-if="previewUrl" class="preview">
        <div class="preview-frame">
          <img
            ref="previewImgEl"
            :src="previewUrl"
            :alt="selectedFile?.name ? t('altPreviewNamed', { name: selectedFile.name }) : t('altPreview')"
            @load="onImgLoad"
            @error="onImgError"
          />
          <svg
            v-if="boxes.length > 0 && naturalSize.w > 0 && naturalSize.h > 0"
            class="overlay"
            :viewBox="`0 0 ${naturalSize.w} ${naturalSize.h}`"
            role="img"
            :aria-label="t('overlayLabel')"
          >
            <g v-for="(box, index) in boxes" :key="index">
              <title>
                {{ t('boxTitle', { n: index + 1, x1: box.x1, x2: box.x2, y1: box.y1, y2: box.y2 }) }}
              </title>
              <rect
                class="box-halo"
                :x="box.x1"
                :y="box.y1"
                :width="box.x2 - box.x1"
                :height="box.y2 - box.y1"
              />
              <rect
                class="box-line"
                :x="box.x1"
                :y="box.y1"
                :width="box.x2 - box.x1"
                :height="box.y2 - box.y1"
              />
              <text
                class="box-label"
                :x="box.x1 + 6"
                :y="labelY(box)"
                :font-size="labelSize()"
              >
                {{ index + 1 }}
              </text>
            </g>
          </svg>
        </div>
        <figcaption v-if="imgError" class="err" role="alert">{{ imgError }}</figcaption>
      </figure>
      <p v-else class="muted">{{ t('wizNeedPhoto') }}</p>
      <label class="prompt-label" for="prompt-input">
        {{ t('promptLabel') }}
      </label>
      <p class="muted hint" id="prompt-hint">
        {{ t('promptHint') }}
      </p>
      <input
        id="prompt-input"
        v-model="prompt"
        type="text"
        :placeholder="t('promptPlaceholder')"
        maxlength="200"
        aria-describedby="prompt-hint"
      />
      <button
        class="btn btn-primary btn-block"
        :disabled="segStatus === 'loading' || !selectedFile || !prompt.trim()"
        @click="runSegmentation"
      >
        {{ segStatus === 'loading' ? t('runningBtn') : t('runBtn') }}
      </button>
      <div class="status-line" role="status">
        <p v-if="segStatus === 'idle'" class="muted">{{ t('segIdle') }}</p>
        <p v-if="segStatus === 'loading'" class="muted">{{ t('segLoading') }}</p>
        <p v-if="segStatus === 'success'" class="ok">✓ {{ segDetail }}</p>
      </div>
      <p v-if="segStatus === 'error'" class="err" role="alert">
        ✗ {{ segDetail }}
      </p>
    </section>

    <section v-show="step === 3" class="card" aria-labelledby="step-3-heading">
      <p class="card-kicker">{{ t('wizKicker', { n: 3, name: stepName(3) }) }}</p>
      <h2 id="step-3-heading" tabindex="-1">{{ t('s2heading') }}</h2>
      <p class="muted">
        {{ voicePrefs.autoRead ? t('autoNote') : t('voiceAutoOffNote') }}
      </p>
      <fieldset class="preset-group">
        <legend>{{ t('presetTitle') }}</legend>
        <button
          class="btn btn-secondary preset-btn"
          :disabled="askStatus === 'loading' || !selectedFile"
          @click="askPreset('presetRead')"
        >
          {{ t('presetRead') }}
        </button>
        <button
          class="btn btn-secondary preset-btn"
          :disabled="askStatus === 'loading' || !selectedFile"
          @click="askPreset('presetAllergen')"
        >
          {{ t('presetAllergen') }}
        </button>
        <button
          class="btn btn-secondary preset-btn"
          :disabled="askStatus === 'loading' || !selectedFile"
          @click="askPreset('presetExpiry')"
        >
          {{ t('presetExpiry') }}
        </button>
        <button
          class="btn btn-secondary preset-btn"
          :disabled="askStatus === 'loading' || !selectedFile"
          @click="askPreset('presetWhat')"
        >
          {{ t('presetWhat') }}
        </button>
      </fieldset>
      <label class="prompt-label" for="question-input">
        {{ t('qLabel') }}
      </label>
      <p class="muted hint" id="question-hint">
        {{ t('qHint') }}
      </p>
      <input
        id="question-input"
        v-model="question"
        type="text"
        :placeholder="t('qPlaceholder')"
        maxlength="500"
        aria-describedby="question-hint"
      />
      <fieldset class="target-group">
        <legend>{{ t('legend') }}</legend>
        <label>
          <input v-model="askTarget" type="radio" value="full" />
          {{ t('fullImg') }}
        </label>
        <label>
          <input
            v-model="askTarget"
            type="radio"
            value="region"
            :disabled="boxes.length === 0"
          />
          {{ t('regionOpt') }}
        </label>
      </fieldset>
      <p v-if="boxes.length === 0" class="muted hint">
        {{ t('regionHint') }}
      </p>
      <div v-if="askTarget === 'region' && boxes.length > 0">
        <label class="prompt-label" for="region-select">
          {{ t('regionLabel') }}
        </label>
        <select id="region-select" v-model.number="regionIndex">
          <option
            v-for="(box, index) in boxes"
            :key="index"
            :value="index"
          >
            {{ t('regionOption', { n: index + 1, x1: box.x1, x2: box.x2, y1: box.y1, y2: box.y2 }) }}
          </option>
        </select>
      </div>
      <button
        class="btn btn-primary btn-block"
        :disabled="askStatus === 'loading' || !selectedFile || !question.trim()"
        @click="runAsk"
      >
        {{ askStatus === 'loading' ? t('askingBtn') : t('askBtn') }}
      </button>
      <div class="status-line" role="status">
        <p v-if="askStatus === 'idle'" class="muted">{{ t('askIdle') }}</p>
        <p v-if="askStatus === 'loading'" class="muted">{{ t('askLoading') }}</p>
        <p v-if="askStatus === 'success'" class="ok">
          ✓ {{ t('askSuccess', { source: answerSource }) }}
        </p>
      </div>
      <p v-if="askStatus === 'error'" class="err" role="alert">
        ✗ {{ askDetail }}
      </p>
    </section>

    <section v-show="step === 4" class="card" aria-labelledby="step-4-heading">
      <p class="card-kicker">{{ t('wizKicker', { n: 4, name: stepName(4) }) }}</p>
      <h2 id="step-4-heading" tabindex="-1">{{ t('wizListenHeading') }}</h2>
      <div class="status-line" role="status">
        <p v-if="askStatus === 'success'" class="ok">
          ✓ {{ t('askSuccess', { source: answerSource }) }}
        </p>
        <p v-else class="muted">{{ t('wizAnswerEmpty') }}</p>
      </div>
      <div v-if="askStatus === 'success'">
        <h3 id="answer-heading">{{ t('answerHeading') }}</h3>
        <p class="answer" :lang="locale">{{ answer || t('emptyAnswer') }}</p>
        <p class="muted hint">
          {{ t('aiNote') }}
        </p>
      </div>
      <div v-if="askStatus === 'success'" class="speech-controls">
        <button
          class="btn btn-primary"
          :disabled="!speechSupported || !answer || isSpeaking"
          @click="readAnswerAloud"
        >
          {{ isSpeaking ? t('readingBtn') : t('readBtn') }}
        </button>
        <button
          class="btn btn-secondary"
          :disabled="!isSpeaking"
          :aria-label="t('stopLabel')"
          @click="stopSpeaking"
        >
          {{ t('stopBtn') }}
        </button>
        <p v-if="!speechSupported" class="muted">
          {{ t('speechUnsupported') }}
        </p>
        <p v-if="isSpeaking" class="muted">{{ t('speaking') }}</p>
      </div>
    </section>

    <div class="wizard-bar">
      <button
        v-if="step > 1"
        class="btn btn-secondary btn-bar"
        @click="goStep(step - 1)"
      >
        {{ t('wizBack') }}
      </button>
      <button
        class="btn btn-primary btn-bar btn-bar-primary"
        :disabled="primaryDisabled"
        @click="primaryAction"
      >
        {{ primaryLabel }}
      </button>
      <button
        v-if="isSpeaking"
        class="btn btn-secondary btn-bar"
        :aria-label="t('stopLabel')"
        @click="stopSpeaking"
      >
        {{ t('stopBtn') }}
      </button>
      <button
        v-else-if="askStatus === 'success' && answer"
        class="btn btn-secondary btn-bar"
        :disabled="!speechSupported"
        @click="readAnswerAloud"
      >
        {{ t('readBtn') }}
      </button>
      <p class="sr-only" role="status">{{ speechNote }}</p>
    </div>
    </div>

    <footer class="footer">
      <p>
        {{ t('footer') }}
      </p>
    </footer>

    <dialog
      ref="settingsDialog"
      class="settings-dialog"
      aria-labelledby="settings-heading"
      @click="onSettingsBackdrop"
      @close="cancelSpeech"
    >
      <div class="settings-head">
        <h2 id="settings-heading">{{ t('settingsTitle') }}</h2>
        <button class="btn btn-secondary" @click="closeSettings">
          {{ t('settingsClose') }}
        </button>
      </div>
      <div class="settings-section">
        <label class="prompt-label" for="locale-select">{{ t('langLabel') }}</label>
        <select id="locale-select" v-model="locale">
          <option v-for="item in LOCALES" :key="item.code" :value="item.code">
            {{ item.label }}
          </option>
        </select>
      </div>
      <div class="settings-section">
        <fieldset class="target-group settings-theme">
          <legend>{{ t('themeLabel') }}</legend>
          <label>
            <input v-model="theme" type="radio" value="system" />
            {{ t('themeSystem') }}
          </label>
          <label>
            <input v-model="theme" type="radio" value="light" />
            {{ t('themeLight') }}
          </label>
          <label>
            <input v-model="theme" type="radio" value="dark" />
            {{ t('themeDark') }}
          </label>
        </fieldset>
      </div>
      <div v-if="speechSupported" class="settings-section">
        <h3 class="settings-sub">{{ t('voicePrefsTitle') }}</h3>
        <div class="settings-grid">
          <div class="voice-row">
            <label class="prompt-label" for="voice-choice">{{ t('voiceChoiceLabel') }}</label>
            <select id="voice-choice" v-model="currentVoice">
              <option value="">{{ t('voiceDefault') }}</option>
              <option value="feminine">{{ t('voiceWoman') }}</option>
              <option value="masculine">{{ t('voiceMan') }}</option>
              <option
                v-for="voice in voiceOptions"
                :key="voice.voiceURI"
                :value="voice.voiceURI"
              >
                {{ voice.name }} ({{ voice.lang }})
              </option>
            </select>
            <p class="muted hint">{{ t('voiceStyleHint') }}</p>
          </div>
          <div class="voice-row">
            <label class="prompt-label" for="voice-tone">{{ t('voiceToneLabel') }}</label>
            <p class="muted hint" id="voice-tone-hint">{{ t('voiceToneHint') }}</p>
            <div class="rate-control">
              <input
                id="voice-tone"
                v-model.number="voicePrefs.pitch"
                type="range"
                min="0.5"
                max="1.5"
                step="0.1"
                aria-describedby="voice-tone-hint"
              />
              <output for="voice-tone">{{ voicePrefs.pitch.toFixed(1) }}</output>
            </div>
          </div>
          <div class="voice-row">
            <label class="prompt-label" for="voice-rate">{{ t('voiceRateLabel') }}</label>
            <p class="muted hint" id="voice-rate-hint">{{ t('voiceRateHint') }}</p>
            <div class="rate-control">
              <input
                id="voice-rate"
                v-model.number="voicePrefs.rate"
                type="range"
                min="0.5"
                max="2"
                step="0.1"
                aria-describedby="voice-rate-hint"
              />
              <output for="voice-rate">{{ t('voiceRateValue', { rate: voicePrefs.rate.toFixed(1) }) }}</output>
            </div>
          </div>
        </div>
        <div class="settings-row voice-checks">
          <label>
            <input v-model="voicePrefs.autoRead" type="checkbox" />
            {{ t('voiceAutoRead') }}
          </label>
          <label>
            <input v-model="voicePrefs.announce" type="checkbox" />
            {{ t('voiceAnnounce') }}
          </label>
          <button
            class="btn btn-secondary"
            :aria-label="isSpeaking ? t('stopLabel') : undefined"
            @click="isSpeaking ? stopSpeaking() : previewVoice()"
          >
            {{ isSpeaking ? t('stopBtn') : t('voicePreviewBtn') }}
          </button>
        </div>
      </div>
      <p v-else class="muted settings-section">{{ t('speechUnsupported') }}</p>
    </dialog>
  </main>
</template>

<style scoped>
.site-header {
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}

.header-inner {
  max-width: 1120px;
  margin: 0 auto;
  padding: 0.75rem 1.5rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
}

.brand {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: var(--accent-soft);
  color: var(--accent-strong);
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}

.brand-text strong {
  font-size: 1.25rem;
  letter-spacing: -0.02em;
  color: var(--text-h);
}

.brand-text span {
  font-size: 0.875rem;
  color: var(--muted);
}

.header-status {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.btn-settings {
  margin: 0;
  min-height: 44px;
  padding: 0.45rem 0.9rem;
  font-size: 1rem;
}

.btn-settings svg {
  width: 1.25rem;
  height: 1.25rem;
  flex: none;
}

.pill {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0.9rem;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border);
  background: var(--surface-2);
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--text-h);
}

.pill-ok {
  background: var(--ok-bg);
  border-color: transparent;
}

.pill-err {
  background: var(--err-bg);
  border-color: transparent;
}

.dot {
  width: 0.6rem;
  height: 0.6rem;
  border-radius: 50%;
  background: var(--muted);
}

.dot-ok {
  background: var(--ok);
}

.dot-err {
  background: var(--err);
}

.container {
  max-width: 1120px;
  margin: 0 auto;
  padding: 2.5rem 1.5rem 3rem;
}

.intro {
  max-width: 44rem;
  margin-bottom: 1.5rem;
}

.intro h1 {
  font-size: 2.25rem;
  margin: 0 0 0.5rem;
  letter-spacing: -0.025em;
}

.tagline {
  margin: 0;
  font-size: 1.1875rem;
  color: var(--muted);
}

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow);
  padding: 1.5rem;
}

.card + .card {
  margin-top: 1.25rem;
}

.card h2 {
  margin: 0 0 0.25rem;
  font-size: 1.375rem;
}

.card-kicker {
  margin: 0 0 0.35rem;
  font-size: 0.875rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--accent-strong);
}

.upload-alt {
  margin-top: 1.25rem;
  padding-top: 1.25rem;
  border-top: 1px solid var(--border);
}

.upload-alt .prompt-label {
  margin-top: 0;
}

.wizard {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  margin-top: 1.25rem;
  max-width: 46rem;
}

.wizard .card + .card {
  margin-top: 0;
}

.wizard-progress {
  margin-top: 1.25rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow);
  padding: 1rem 1.25rem 0.75rem;
  max-width: 46rem;
}

.wizard-progress ol {
  list-style: none;
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin: 0;
  padding: 0;
}

.wizard-progress li {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0.8rem 0.4rem 0.4rem;
  border-radius: var(--radius-pill);
  border: 1.5px solid transparent;
  color: var(--muted);
  font-weight: 600;
}

.wiz-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border-radius: 50%;
  background: var(--surface-2);
  border: 1.5px solid var(--border);
  font-size: 1rem;
  flex: none;
}

.wizard-progress .wiz-done {
  color: var(--ok);
}

.wizard-progress .wiz-done .wiz-num {
  background: var(--ok-bg);
  border-color: transparent;
}

.wizard-progress .wiz-current {
  color: var(--text-h);
  border-color: var(--accent);
  background: var(--accent-soft);
}

.wizard-progress .wiz-current .wiz-num {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

.wizard-count {
  margin: 0.5rem 0 0.25rem;
  color: var(--muted);
  font-size: 0.9375rem;
}

.preset-group {
  margin: 1rem 0 0;
  padding: 0.75rem 1rem 1rem;
  border: 1.5px solid var(--border);
  border-radius: var(--radius-control);
  background: var(--surface-2);
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.5rem;
}

.preset-group legend {
  font-weight: 700;
  color: var(--text-h);
  padding: 0 0.5rem;
}

.preset-group .preset-btn {
  margin: 0;
  width: 100%;
  min-height: 56px;
}

.wizard-bar {
  position: sticky;
  bottom: 0;
  z-index: 5;
  display: flex;
  gap: 0.5rem;
  align-items: stretch;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow);
  padding: 0.75rem;
}

.btn-bar {
  margin: 0;
  min-height: 56px;
  font-size: 1.125rem;
  flex: 0 1 auto;
}

.btn-bar-primary {
  flex: 1 1 auto;
}

.card input[type='file'] {
  display: block;
  width: 100%;
  margin: 0.5rem 0 0;
  padding: 0.65rem 0.75rem;
  font-size: 1rem;
  min-height: 44px;
  box-sizing: border-box;
  border: 1px dashed var(--input-border);
  border-radius: var(--radius-control);
  background: var(--surface-2);
  color: inherit;
}

.hint {
  margin: 0.25rem 0 0;
  font-size: 1rem;
}

.prompt-label {
  display: block;
  margin-top: 1rem;
  font-weight: 600;
  color: var(--text-h);
}

.card input[type='text'],
.card select,
.settings-dialog select {
  display: block;
  width: 100%;
  margin: 0.5rem 0 0;
  padding: 0.75rem 1rem;
  font-size: 1.0625rem;
  line-height: 1.5;
  min-height: 48px;
  border-radius: var(--radius-control);
  border: 1.5px solid var(--input-border);
  background: var(--surface);
  color: var(--text-h);
  box-sizing: border-box;
}

.card input[type='text']:focus,
.card select:focus,
.settings-dialog select:focus {
  border-color: var(--accent);
}

.target-group {
  margin: 1rem 0 0;
  padding: 0.75rem 1rem;
  border: 1.5px solid var(--border);
  border-radius: var(--radius-control);
  text-align: left;
  background: var(--surface-2);
}

.target-group legend {
  font-weight: 700;
  color: var(--text-h);
  padding: 0 0.5rem;
}

.target-group label {
  display: inline-block;
  margin: 0.25rem 1rem 0.25rem 0;
  font-size: 1.0625rem;
}

.target-group input[type='radio'] {
  width: 1.25rem;
  height: 1.25rem;
  margin-right: 0.5rem;
  vertical-align: middle;
  accent-color: var(--accent);
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  margin: 1rem 0.25rem 0;
  padding: 0.7rem 1.4rem;
  font-size: 1.0625rem;
  font-weight: 650;
  line-height: 1.4;
  min-height: 48px;
  border-radius: var(--radius-pill);
  border: 1.5px solid transparent;
  cursor: pointer;
  transition: background-color 0.15s ease, border-color 0.15s ease;
}

.btn-primary {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

.btn-primary:hover:not(:disabled) {
  background: var(--accent-strong);
  border-color: var(--accent-strong);
}

.btn-secondary {
  background: var(--surface);
  border-color: var(--input-border);
  color: var(--text-h);
}

.btn-secondary:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent-strong);
}

.btn-block {
  width: 100%;
}

.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.status-line p {
  margin: 1rem 0 0;
}

.preview {
  margin: 1.25rem 0 0;
  padding: 0;
}

.camera-first {
  margin-top: 0.75rem;
}

.camera h3 {
  margin: 0 0 0.5rem;
}

.camera-buttons {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.camera-buttons .btn {
  margin: 0.5rem 0 0;
}

.camera-video {
  display: block;
  width: 100%;
  aspect-ratio: 4 / 3;
  margin-top: 1rem;
  border-radius: var(--radius-control);
  background: #000;
  border: 1px solid var(--border);
}

.preview-frame {
  position: relative;
  display: block;
  max-width: 100%;
  line-height: 0;
  border-radius: var(--radius-control);
  overflow: hidden;
  border: 1px solid var(--border);
  background: #0b1211;
}

.preview-frame img {
  display: block;
  width: 100%;
  height: auto;
}

.overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.overlay .box-halo,
.overlay .box-line {
  fill: rgba(251, 191, 36, 0.1);
  vector-effect: non-scaling-stroke;
}

.overlay .box-halo {
  stroke: rgba(0, 0, 0, 0.8);
  stroke-width: 5;
}

.overlay .box-line {
  stroke: #fbbf24;
  stroke-width: 2.5;
}

.overlay .box-label {
  fill: #ffffff;
  font-weight: 700;
  paint-order: stroke;
  stroke: rgba(0, 0, 0, 0.85);
  stroke-width: 4px;
}

.preview figcaption {
  margin-top: 0.5rem;
  line-height: 1.5;
}

.answer {
  margin: 0.75rem 0 0;
  padding: 1rem 1.1rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  background: var(--surface-2);
  text-align: left;
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: break-word;
  color: var(--text-h);
}

.speech-controls {
  margin-top: 1rem;
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  align-items: center;
}

.speech-controls .btn {
  margin: 0;
}

.settings-dialog {
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow);
  background: var(--surface);
  color: var(--text);
  padding: 1.5rem;
  width: min(40rem, calc(100vw - 2rem));
  max-height: calc(100vh - 4rem);
  overflow-y: auto;
}

.settings-dialog::backdrop {
  background: rgba(11, 18, 17, 0.5);
}

.settings-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.settings-head h2 {
  margin: 0;
  font-size: 1.25rem;
  color: var(--text-h);
}

.settings-head .btn {
  margin: 0;
}

.settings-section {
  margin-top: 1.25rem;
  padding-top: 1.25rem;
  border-top: 1px solid var(--border);
}

.settings-section > .prompt-label:first-child {
  margin-top: 0;
}

.settings-sub {
  margin: 0;
  font-size: 1.0625rem;
  color: var(--text-h);
}

.settings-theme {
  margin-top: 0;
}

.settings-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 1.25rem;
}

.settings-grid .voice-row:first-child {
  grid-column: 1 / -1;
}

.settings-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 1.5rem;
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border);
}

.settings-row .btn {
  margin: 0;
}

.voice-row {
  margin-top: 1rem;
}

.voice-row .prompt-label {
  margin-top: 0;
}

.rate-control {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-top: 0.5rem;
}

.rate-control input[type='range'] {
  flex: 1 1 auto;
  min-height: 48px;
  accent-color: var(--accent);
}

.rate-control output {
  flex: none;
  min-width: 3.5rem;
  text-align: right;
  font-weight: 700;
  color: var(--text-h);
  font-variant-numeric: tabular-nums;
}

.voice-checks label {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  min-height: 48px;
  font-size: 1.0625rem;
  color: var(--text-h);
}

.voice-checks input[type='checkbox'] {
  width: 1.5rem;
  height: 1.5rem;
  flex: none;
  accent-color: var(--accent);
  margin: 0;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

code {
  font-family: ui-monospace, Consolas, monospace;
  background: var(--code-bg);
  padding: 2px 6px;
  border-radius: 6px;
  overflow-wrap: anywhere;
  font-size: 0.9375rem;
}

.muted {
  color: var(--muted);
}

.hint {
  margin: 0.25rem 0 0;
  font-size: 0.9375rem;
  color: var(--muted);
}

.prompt-label {
  display: block;
  margin-top: 1.1rem;
  font-weight: 700;
  color: var(--text-h);
}

.ok {
  color: var(--ok);
  font-weight: 650;
}

.err {
  color: var(--err);
  font-weight: 650;
}

.footer {
  margin-top: 1.5rem;
  padding: 1rem 0 0;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: 0.9375rem;
}

.footer p {
  margin: 0;
}

@media (max-width: 960px) {
  .intro h1 {
    font-size: 1.875rem;
  }
}

@media (max-width: 560px) {
  .container {
    padding: 1.75rem 1rem 2.5rem;
  }

  .card {
    padding: 1.15rem;
  }

  .header-inner {
    padding: 0.75rem 1rem;
  }

  .btn-block {
    width: 100%;
  }

  .preset-group {
    grid-template-columns: 1fr;
  }

  .settings-grid {
    grid-template-columns: 1fr;
  }

  .wizard-bar {
    flex-wrap: wrap;
  }

  .btn-bar-primary {
    flex: 1 1 100%;
    order: -1;
  }

  .wizard-bar .btn-bar:not(.btn-bar-primary) {
    flex: 1 1 auto;
  }
}
</style>
