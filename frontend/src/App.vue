<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ANSWER_LANG_NAME, LOCALES } from './i18n.js'
import { usePreferences } from './composables/usePreferences.js'
import { useBackendStatus } from './composables/useBackendStatus.js'
import { useSpeech } from './composables/useSpeech.js'
import { useCamera } from './composables/useCamera.js'
import { paddedCropRect, scaleBox } from './lib/boxes.js'

const backendUrl =
  import.meta.env.VITE_BACKEND_URL ?? 'http://localhost:8000'

// Set on unmount; async callbacks check it via isDisposed() before touching state.
let disposed = false
const isDisposed = () => disposed

const prefs = usePreferences()
const { locale, theme, voicePrefs, currentVoice, t } = prefs
// Backend status is polled before voices load, as before.
const { status } = useBackendStatus({ backendUrl, isDisposed })
const {
  speechSupported,
  isSpeaking,
  speechNote,
  voiceOptions,
  speakStatus,
  readAnswerAloud,
  previewVoice,
  cancelSpeech,
  stopSpeaking,
} = useSpeech({ prefs, isDisposed })
const {
  cameraSupported,
  camStatus,
  camDetail,
  camFlash,
  videoEl,
  startCamera,
  stopCamera,
  capturePhoto,
} = useCamera({ t, speakStatus, isDisposed, onCapture: handleCameraCapture })

// Camera captures feed the same image state as file uploads.
function handleCameraCapture(file) {
  fileError.value = null
  setSelectedFile(file)
  if (fileInputEl.value) {
    fileInputEl.value.value = ''
  }
}

const MAX_BYTES = 5 * 1024 * 1024
const MAX_QUESTION_CHARS = 500
const SUPPORTED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp']
const selectedFile = ref(null)
// Step-1 upload error as a message descriptor (or null), like the other details.
const fileError = ref(null)
const fileInputEl = ref(null)
const prompt = ref('label')
const segStatus = ref('idle') // 'idle' | 'loading' | 'success' | 'error'
// Translatable message descriptors ({ key, params }) or null, rendered via
// msgText() so they follow locale changes. { text } keeps raw text as-is.
const segDetail = ref(null)
const boxes = ref([])

// Visual question answering reuses the uploaded image.
const question = ref('')
const askStatus = ref('idle') // 'idle' | 'loading' | 'success' | 'error'
const askDetail = ref(null)
const answer = ref('')
// What the next (or last) answer covers: 'full' or 'region' + regionIndex.
const askTarget = ref('full')
const regionIndex = ref(0)
// What the last answer covered (kind + region), rendered via answerSourceText.
const answerKind = ref('') // '' | 'full' | 'region'
const answerRegion = ref(0)
const answerSourceText = computed(() => {
  if (answerKind.value === 'region') {
    return t('srcRegion', { n: answerRegion.value + 1 })
  }
  if (answerKind.value === 'full') {
    return t('srcFull')
  }
  return ''
})
// Re-entry guard: askStatus becomes 'loading' only after the region crop,
// so a double tap during the crop would otherwise send two requests.
let askInFlight = false
// True while the region crop is running (before askStatus flips to loading).
const cropping = ref(false)
const askBusy = computed(() => askStatus.value === 'loading' || cropping.value)

// Audio-first wizard: one screen per action.
// 1 = Photo (capture/upload), 2 = Check (preview + find region),
// 3 = Ask (presets/question + target), 4 = Listen (answer, read aloud).
const step = ref(1)
const STEP_NAMES = ['wizPhoto', 'wizCheck', 'wizAsk', 'wizListen']
function stepName(n) {
  return t(STEP_NAMES[n - 1] ?? 'wizPhoto')
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
  fileError.value = null
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
    return askBusy.value || !selectedFile.value || !question.value.trim()
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

// Image preview + overlay state. The SVG overlay uses the image's natural
// pixel dimensions as its viewBox so scaled box coordinates map 1:1.
const previewUrl = ref(null)
const previewImgEl = ref(null)
const naturalSize = ref({ w: 0, h: 0 })
const imgError = ref(null)

function revokePreview() {
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = null
  }
}

function setPreview() {
  revokePreview()
  naturalSize.value = { w: 0, h: 0 }
  imgError.value = null
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

// Overlay boxes in natural-image pixels; each entry keeps the original box
// (for the <title>) and its index (so the label number stays index + 1).
const overlayBoxes = computed(() => {
  const nw = naturalSize.value.w
  const nh = naturalSize.value.h
  const out = []
  boxes.value.forEach((box, index) => {
    const scaled = scaleBox(box, nw, nh)
    if (scaled) {
      out.push({ ...scaled, index, box })
    }
  })
  return out
})

function onImgLoad(event) {
  naturalSize.value = {
    w: event.target.naturalWidth,
    h: event.target.naturalHeight,
  }
  imgError.value = null
}

function onImgError() {
  naturalSize.value = { w: 0, h: 0 }
  imgError.value = { key: 'imgErr' }
}

// Crop a SAM box (source-pixel coords in the token's w/h frame) out of the
// original image at its intrinsic size, with 5% padding clamped to bounds.
function cropRegion(box, index) {
  return new Promise((resolve, reject) => {
    // Failures reject with message descriptors so the caller can store and
    // speak them in the current locale.
    const fail = (message) => reject(message)
    const img = previewImgEl.value
    const nw = naturalSize.value.w
    const nh = naturalSize.value.h
    if (!img || !nw || !nh) {
      fail({ key: 'cropLoading' })
      return
    }
    const scaled = scaleBox(box, nw, nh)
    if (!scaled || scaled.x2 <= scaled.x1 || scaled.y2 <= scaled.y1) {
      fail({ key: 'cropInvalid' })
      return
    }
    const rect = paddedCropRect(scaled, nw, nh)
    if (!rect) {
      fail({ key: 'cropEmpty' })
      return
    }
    const { cx1, cy1, cx2, cy2 } = rect
    const canvas = document.createElement('canvas')
    canvas.width = cx2 - cx1
    canvas.height = cy2 - cy1
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      fail({ key: 'cropFail' })
      return
    }
    ctx.drawImage(img, cx1, cy1, cx2 - cx1, cy2 - cy1, 0, 0, canvas.width, canvas.height)
    canvas.toBlob(
      (blob) => {
        if (!blob) {
          fail({ key: 'cropFail' })
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
  segDetail.value = null
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
  revokePreview()
})

function clearAnswer() {
  askStatus.value = 'idle'
  askDetail.value = null
  answer.value = ''
  answerKind.value = ''
  answerRegion.value = 0
}

function resetResults() {
  segStatus.value = 'idle'
  segDetail.value = null
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
  const file = event.target.files?.[0] ?? null
  let errorKey = null
  if (file && !SUPPORTED_IMAGE_TYPES.includes(file.type)) {
    errorKey = 'errFileType'
  } else if (file && file.size > MAX_BYTES) {
    errorKey = 'errTooBig'
  }
  if (errorKey) {
    fileError.value = { key: errorKey }
    event.target.value = ''
    setSelectedFile(null)
    // Defer so the invalidated-answer watcher flushes first (same pattern
    // as the success announcement below).
    nextTick(() => {
      if (!disposed) {
        speakStatus(msgText(fileError.value))
      }
    })
    return
  }
  fileError.value = null
  setSelectedFile(file)
  if (selectedFile.value) {
    // Defer so the invalidated-answer watcher flushes first (see above).
    nextTick(() => {
      if (!disposed) {
        speakStatus(t('speakPhotoReady'))
      }
    })
  }
}

// Render a stored message descriptor in the current locale.
function msgText(msg) {
  if (!msg) {
    return ''
  }
  return 'text' in msg ? msg.text : t(msg.key, msg.params)
}

// Normalize a caught failure into a stored message: our own throws are
// already descriptors, genuine Errors keep their text, anything else is
// an unknown error.
function asMsg(error) {
  if (error && typeof error === 'object' && 'key' in error) {
    return error
  }
  return error instanceof Error ? { text: error.message } : { key: 'unknownErr' }
}

// Backend detail strings are English-only, so map HTTP failures to localized
// messages instead of showing body.detail (which can also be a 422 array).
function httpError(status) {
  if (status === 413) {
    return { key: 'errTooBig' }
  }
  if (status === 415) {
    return { key: 'errFileType' }
  }
  if (status === 400 || status === 422) {
    return { key: 'errRequest' }
  }
  if (status === 503) {
    return { key: 'errNotConfigured' }
  }
  if (status === 502) {
    return { key: 'errProvider' }
  }
  if (status === 504) {
    return { key: 'errTimeout' }
  }
  return { key: 'errServer', params: { status } }
}

function networkError() {
  return { key: 'errNetwork' }
}

async function runSegmentation() {
  if (!selectedFile.value) {
    return
  }
  if (selectedFile.value.size > MAX_BYTES) {
    segStatus.value = 'error'
    segDetail.value = { key: 'errTooBig' }
    speakStatus(msgText(segDetail.value))
    return
  }
  const trimmedPrompt = prompt.value.trim()
  if (!trimmedPrompt) {
    segStatus.value = 'error'
    segDetail.value = { key: 'errPromptEmpty' }
    speakStatus(msgText(segDetail.value))
    return
  }
  const sentFile = selectedFile.value
  const sentPrompt = trimmedPrompt
  segStatus.value = 'loading'
  segDetail.value = null
  boxes.value = []
  try {
    const form = new FormData()
    form.append('image', sentFile)
    form.append('prompt', sentPrompt)
    let response
    try {
      response = await fetch(`${backendUrl}/api/segment`, {
        method: 'POST',
        body: form,
      })
    } catch {
      throw networkError()
    }
    if (!response.ok) {
      throw httpError(response.status)
    }
    const data = await response.json()
    // Drop late responses if the user moved on to another image or prompt.
    if (selectedFile.value !== sentFile || prompt.value.trim() !== sentPrompt) {
      segStatus.value = 'idle'
      segDetail.value = null
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
    if (askStatus.value === 'success' && answerKind.value !== 'full') {
      clearAnswer()
    }
    segStatus.value = 'success'
    segDetail.value =
      boxes.value.length === 0
        ? { key: 'noObjects' }
        : boxes.value.length === 1
          ? { key: 'foundOne' }
          : { key: 'foundN', params: { count: boxes.value.length } }
    // Let invalidated-answer watchers settle first so they cannot cancel
    // this announcement (same pattern as the answer speech in runAsk).
    await nextTick()
    if (!disposed && segStatus.value === 'success') {
      speakStatus(msgText(segDetail.value))
    }
  } catch (error) {
    if (selectedFile.value !== sentFile || prompt.value.trim() !== sentPrompt) {
      segStatus.value = 'idle'
      segDetail.value = null
      boxes.value = []
      return
    }
    segStatus.value = 'error'
    segDetail.value = asMsg(error)
    speakStatus(msgText(segDetail.value))
  }
}

// Suffix that steers the answer language; empty for English.
function answerSuffix() {
  const answerLang = ANSWER_LANG_NAME[locale.value]
  return answerLang ? `\n\nPlease answer in ${answerLang}.` : ''
}

// Room left for the typed question once the suffix is appended upstream.
const questionMax = computed(() => MAX_QUESTION_CHARS - answerSuffix().length)

async function runAsk() {
  if (askInFlight) {
    return
  }
  if (!selectedFile.value) {
    return
  }
  const trimmedQuestion = question.value.trim()
  if (!trimmedQuestion) {
    askStatus.value = 'error'
    askDetail.value = { key: 'errNoQuestion' }
    speakStatus(msgText(askDetail.value))
    return
  }
  if (trimmedQuestion.length > questionMax.value) {
    askStatus.value = 'error'
    askDetail.value = { key: 'errQuestionTooLong', params: { max: questionMax.value } }
    speakStatus(msgText(askDetail.value))
    return
  }
  askInFlight = true
  try {
    // Resolve which pixels to send. Region mode never silently falls back:
    // without a valid box the request is refused with a clear message.
    let imageToSend = selectedFile.value
    const sentKind = askTarget.value
    const sentRegion = regionIndex.value
    if (askTarget.value === 'region') {
      const box = boxes.value[regionIndex.value]
      if (!box) {
        askStatus.value = 'error'
        askDetail.value = { key: 'regionGone' }
        speakStatus(msgText(askDetail.value))
        return
      }
      const preCropFile = selectedFile.value
      cropping.value = true
      try {
        imageToSend = await cropRegion(box, sentRegion)
      } catch (error) {
        askStatus.value = 'error'
        askDetail.value = asMsg(error)
        speakStatus(msgText(askDetail.value))
        return
      } finally {
        cropping.value = false
      }
      if (
        selectedFile.value !== preCropFile ||
        askTarget.value !== 'region' ||
        regionIndex.value !== sentRegion
      ) {
        return
      }
    }
    if (imageToSend.size > MAX_BYTES) {
      askStatus.value = 'error'
      askDetail.value = { key: 'errTooBig' }
      speakStatus(msgText(askDetail.value))
      return
    }
    const sentFile = selectedFile.value
    const sentQuestion = trimmedQuestion
    // Answers come back in the selected UI language.
    const upstreamQuestion = `${trimmedQuestion}${answerSuffix()}`
    askStatus.value = 'loading'
    askDetail.value = null
    answer.value = ''
    answerKind.value = ''
    answerRegion.value = 0
    // Let the answer watcher settle first so it cannot cancel this speech.
    await nextTick()
    if (!disposed && askStatus.value === 'loading') {
      speakStatus(t('askLoading'))
    }
    try {
      const form = new FormData()
      form.append('image', imageToSend)
      form.append('question', upstreamQuestion)
      let response
      try {
        response = await fetch(`${backendUrl}/api/ask`, {
          method: 'POST',
          body: form,
        })
      } catch {
        throw networkError()
      }
      if (!response.ok) {
        throw httpError(response.status)
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
        askDetail.value = null
        answer.value = ''
        answerKind.value = ''
        answerRegion.value = 0
        return
      }
      answer.value = data?.answer ?? ''
      answerKind.value = sentKind
      answerRegion.value = sentRegion
      askStatus.value = 'success'
      // Wizard: move to the Listen step, then read the answer aloud.
      // goStep skips its own announcement here so it cannot collide with
      // the answer speech. nextTick lets the answer watcher settle first
      // so it cannot cancel this speech.
      goStep(4)
      await nextTick()
      if (!disposed && voicePrefs.value.autoRead) {
        readAnswerAloud(answer.value)
      }
    } catch (error) {
      if (
        selectedFile.value !== sentFile ||
        question.value.trim() !== sentQuestion ||
        askTarget.value !== sentKind ||
        (sentKind === 'region' && regionIndex.value !== sentRegion)
      ) {
        askStatus.value = 'idle'
        askDetail.value = null
        answer.value = ''
        answerKind.value = ''
        answerRegion.value = 0
        return
      }
      askStatus.value = 'error'
      askDetail.value = asMsg(error)
      speakStatus(msgText(askDetail.value))
    }
  } finally {
    askInFlight = false
  }
}
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

    <div class="wizard-progress" role="group" :aria-label="t('wizLabel')">
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
      <p class="wizard-count">{{ t('wizStepOf', { n: step }) }}</p>
    </div>

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
            ✓ {{ msgText(camFlash) }}
          </p>
          <p v-if="camStatus === 'starting'" class="muted">
            {{ t('camStarting') }}
          </p>
          <p v-if="camStatus === 'live'" class="muted">
            {{ t('camLive') }}
          </p>
        </div>
        <p v-if="camStatus === 'error'" class="err" role="alert">
          ✗ {{ msgText(camDetail) }}
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
        <p v-if="fileError" class="err" role="alert">✗ {{ msgText(fileError) }}</p>
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
            v-if="overlayBoxes.length > 0 && naturalSize.w > 0 && naturalSize.h > 0"
            class="overlay"
            :viewBox="`0 0 ${naturalSize.w} ${naturalSize.h}`"
            role="img"
            :aria-label="t('overlayLabel')"
          >
            <g v-for="entry in overlayBoxes" :key="entry.index">
              <title>
                {{ t('boxTitle', { n: entry.index + 1, x1: entry.box.x1, x2: entry.box.x2, y1: entry.box.y1, y2: entry.box.y2 }) }}
              </title>
              <rect
                class="box-halo"
                :x="entry.x1"
                :y="entry.y1"
                :width="entry.x2 - entry.x1"
                :height="entry.y2 - entry.y1"
              />
              <rect
                class="box-line"
                :x="entry.x1"
                :y="entry.y1"
                :width="entry.x2 - entry.x1"
                :height="entry.y2 - entry.y1"
              />
              <text
                class="box-label"
                :x="entry.x1 + 6"
                :y="labelY(entry)"
                :font-size="labelSize()"
              >
                {{ entry.index + 1 }}
              </text>
            </g>
          </svg>
        </div>
        <figcaption v-if="imgError" class="err" role="alert">{{ msgText(imgError) }}</figcaption>
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
        <p v-if="segStatus === 'success'" class="ok">✓ {{ msgText(segDetail) }}</p>
      </div>
      <p v-if="segStatus === 'error'" class="err" role="alert">
        ✗ {{ msgText(segDetail) }}
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
          :disabled="askBusy || !selectedFile"
          @click="askPreset('presetRead')"
        >
          {{ t('presetRead') }}
        </button>
        <button
          class="btn btn-secondary preset-btn"
          :disabled="askBusy || !selectedFile"
          @click="askPreset('presetAllergen')"
        >
          {{ t('presetAllergen') }}
        </button>
        <button
          class="btn btn-secondary preset-btn"
          :disabled="askBusy || !selectedFile"
          @click="askPreset('presetExpiry')"
        >
          {{ t('presetExpiry') }}
        </button>
        <button
          class="btn btn-secondary preset-btn"
          :disabled="askBusy || !selectedFile"
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
        :maxlength="questionMax"
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
        :disabled="askBusy || !selectedFile || !question.trim()"
        @click="runAsk"
      >
        {{ askStatus === 'loading' ? t('askingBtn') : t('askBtn') }}
      </button>
      <div class="status-line" role="status">
        <p v-if="askStatus === 'idle'" class="muted">{{ t('askIdle') }}</p>
        <p v-if="askStatus === 'loading'" class="muted">{{ t('askLoading') }}</p>
        <p v-if="askStatus === 'success'" class="ok">
          ✓ {{ t('askSuccess', { source: answerSourceText }) }}
        </p>
      </div>
      <p v-if="askStatus === 'error'" class="err" role="alert">
        ✗ {{ msgText(askDetail) }}
      </p>
    </section>

    <section v-show="step === 4" class="card" aria-labelledby="step-4-heading">
      <p class="card-kicker">{{ t('wizKicker', { n: 4, name: stepName(4) }) }}</p>
      <h2 id="step-4-heading" tabindex="-1">{{ t('wizListenHeading') }}</h2>
      <div class="status-line" role="status">
        <p v-if="askStatus === 'success'" class="ok">
          ✓ {{ t('askSuccess', { source: answerSourceText }) }}
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
          @click="readAnswerAloud(answer)"
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
        @click="readAnswerAloud(answer)"
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
    <div class="settings-body">
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
            <input
              id="voice-announce"
              v-model="voicePrefs.announce"
              type="checkbox"
              aria-describedby="voice-announce-hint"
            />
            {{ t('voiceAnnounce') }}
          </label>
          <p class="muted hint" id="voice-announce-hint">{{ t('voiceAnnounceHint') }}</p>
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
    </div>
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
  color: var(--on-accent);
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
  color: var(--on-accent);
}

.btn-primary:hover:not(:disabled) {
  background: var(--accent-strong);
  border-color: var(--accent-strong);
  color: var(--on-accent);
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
  padding: 0;
  width: min(40rem, calc(100vw - 2rem));
  max-height: calc(100vh - 4rem);
  overflow-y: auto;
}

.settings-body {
  padding: 1.5rem;
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
