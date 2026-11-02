<script setup>
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import '../quickmode.css'
import { backendUrl } from '../lib/api.js'
import { describeBox } from '../lib/boxes.js'
import { FRAMING_THRESHOLDS } from '../lib/framing.js'
import { asMsg, httpError, networkError } from '../lib/messages.js'
import { useCamera } from '../composables/useCamera.js'
import { useEarcons } from '../composables/useEarcons.js'
import { useFraming } from '../composables/useFraming.js'
import { useLiveGuidance } from '../composables/useLiveGuidance.js'
import { useVoiceQuestion } from '../composables/useVoiceQuestion.js'
import ZoomView from './ZoomView.vue'

const shared = inject('visionspark')
const {
  t,
  locale,
  voicePrefs,
  speakStatus,
  readAnswerAloud,
  cancelSpeech,
  stopSpeaking,
  isSpeaking,
  speechSupported,
  backendStatus,
} = shared
const appDisposed = shared.isDisposed

// Unmount (mode switch) invalidates async callbacks even though App lives on.
let disposed = false
const isGone = () => disposed || appDisposed()

const MAX_BYTES = 5 * 1024 * 1024
const MAX_QUESTION_CHARS = 500
const SUPPORTED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp']

// The localized preset text becomes the question; the key goes to the backend.
const PRESETS = [
  { key: 'read', textKey: 'presetRead' },
  { key: 'allergens', textKey: 'presetAllergen' },
  { key: 'expiry', textKey: 'presetExpiry' },
  { key: 'what', textKey: 'presetWhat' },
]

// Small state machine: ask -> point -> working -> answer.
const screen = ref('ask')
const question = ref('')
const preset = ref(null)
const photo = ref(null)
const result = ref(null)
const error = ref(null)
const askError = ref(null)
const pointError = ref(null)
const fileInputEl = ref(null)

const {
  cameraSupported,
  camStatus,
  camDetail,
  camFlash,
  videoEl,
  torchSupported,
  setTorch,
  startCamera,
  stopCamera,
  capturePhoto,
} = useCamera({
  t,
  speakStatus,
  isDisposed: isGone,
  onCapture: handlePointCapture,
  captureAnnouncement: null, // an earcon plays instead
})

const earcons = useEarcons({ isDisposed: isGone })

const {
  voiceSupported,
  recording,
  recordDetail,
  startRecording,
  stopRecording,
} = useVoiceQuestion({ isDisposed: isGone, earcons })

const torchOn = ref(false)
async function toggleTorch() {
  const next = !torchOn.value
  const ok = await setTorch(next)
  if (!isGone() && ok) {
    torchOn.value = next
  }
}
watch(camStatus, (value) => {
  if (value !== 'live') {
    torchOn.value = false
  }
  if (value === 'live') {
    earcons.ready()
  } else if (value === 'error') {
    earcons.error()
  }
})

// Live SAM guidance is off by default so public deployments spend nothing.
const liveGuidanceOn = import.meta.env.VITE_LIVE_GUIDANCE === 'true'

const framing = useFraming({
  videoEl,
  isLive: () => camStatus.value === 'live',
  torchSupported,
  isSpeaking,
  isDisposed: isGone,
  speak: speakStatus,
  t,
  earcons,
  onAutoCapture: () => capturePhoto(),
  // With live SAM guidance, level 1 keeps its cues but hands auto-capture
  // to level 3.
  autoCapture: !liveGuidanceOn,
})

const liveGuidance = useLiveGuidance({
  videoEl,
  isLive: () => camStatus.value === 'live',
  isSpeaking,
  isDisposed: isGone,
  speak: speakStatus,
  t,
  earcons,
  stillCheck: () => {
    const motion = framing.lastStats.value?.motion
    return motion !== undefined && motion !== null && motion <= FRAMING_THRESHOLDS.moving
  },
  onAutoCapture: () => capturePhoto(),
})

function msgText(msg) {
  if (!msg) {
    return ''
  }
  return 'text' in msg ? msg.text : t(msg.key, msg.params)
}

function goScreen(name, opts = {}) {
  const speak = opts.speak !== false
  // Leaving point stops the point camera (a hidden video would stream on)
  // and both guidance loops.
  if (screen.value === 'point' && name !== 'point') {
    framing.stop()
    liveGuidance.stop()
    stopCamera()
  }
  if (name === 'point') {
    framing.start()
    if (liveGuidanceOn) {
      liveGuidance.start()
    }
  }
  screen.value = name
  nextTick(() => {
    if (isGone()) {
      return
    }
    document.getElementById(`qm-${name}-heading`)?.focus()
    if (name === 'ask' && speak) {
      speakStatus(t('qmAskHeading'))
    } else if (name === 'point') {
      startCamera()
      if (speak) {
        speakStatus(`${t('qmPointHint')} ${t('qmAutoHint')}`)
      }
    }
  })
}

onMounted(() => {
  goScreen('ask')
})

onBeforeUnmount(() => {
  disposed = true
  assistRun += 1
  assistController?.abort()
  transcribeController?.abort()
  clearAutoStop()
})

// Ask: presets, typed questions, and the kept photo.
function submitQuestion() {
  if (!question.value.trim()) {
    return
  }
  askError.value = null
  if (photo.value) {
    runAssist()
  } else {
    goScreen('point')
  }
}

function askPreset(key, textKey) {
  preset.value = key
  question.value = t(textKey)
  submitQuestion()
}

function submitTyped() {
  if (!question.value.trim()) {
    askError.value = { key: 'errNoQuestion' }
    speakStatus(msgText(askError.value))
    return
  }
  preset.value = null
  submitQuestion()
}

function takeNewPhoto() {
  goScreen('point')
}

// Point: capture or file, then straight to working. Auto-capture (Phase 7)
// will hook in here.
function handlePointCapture(file) {
  pointError.value = null
  photo.value = file
  if (fileInputEl.value) {
    fileInputEl.value.value = ''
  }
  earcons.captured()
  runAssist()
}

function onQuickFile(event) {
  const file = event.target.files?.[0] ?? null
  let errorKey = null
  if (file && !SUPPORTED_IMAGE_TYPES.includes(file.type)) {
    errorKey = 'errFileType'
  } else if (file && file.size > MAX_BYTES) {
    errorKey = 'errTooBig'
  }
  if (errorKey) {
    pointError.value = { key: errorKey }
    event.target.value = ''
    speakStatus(msgText(pointError.value))
    return
  }
  if (file) {
    handlePointCapture(file)
  }
}

function cancelPoint() {
  goScreen('ask')
}

// Voice questions: hold or tap the mic button, speak, release or tap again.
// At most 15 s, then the recording stops by itself; under 0.4 s of audio
// nothing is sent.
const MAX_RECORD_MS = 15000
const MIN_RECORD_S = 0.4
const transcribing = ref(false)
let transcribeController = null
let autoStopTimer = null
let micDownAt = 0
let micHeld = false
let ignoreMicClick = false

function clearAutoStop() {
  if (autoStopTimer !== null) {
    clearTimeout(autoStopTimer)
    autoStopTimer = null
  }
}

async function micStart() {
  if (recording.value || transcribing.value) {
    return
  }
  cancelSpeech()
  const ok = await startRecording()
  if (isGone()) {
    return
  }
  if (!ok) {
    if (recordDetail.value) {
      speakStatus(msgText(recordDetail.value))
    }
    return
  }
  clearAutoStop()
  autoStopTimer = setTimeout(() => {
    autoStopTimer = null
    micStopAndTranscribe()
  }, MAX_RECORD_MS)
}

async function micStopAndTranscribe() {
  if (transcribing.value) {
    return
  }
  transcribing.value = true
  clearAutoStop()
  try {
    const done = await stopRecording()
    if (isGone() || !done) {
      return
    }
    if (!done.wav || done.durationS < MIN_RECORD_S) {
      askError.value = { key: 'qmTooShort' }
      speakStatus(msgText(askError.value))
      return
    }
    await transcribeAndGo(done.wav)
  } finally {
    if (!isGone()) {
      transcribing.value = false
    }
  }
}

async function transcribeAndGo(wavBytes) {
  transcribeController = new AbortController()
  try {
    const form = new FormData()
    form.append('audio', new Blob([wavBytes], { type: 'audio/wav' }), 'question.wav')
    form.append('language', locale.value)
    let response
    try {
      response = await fetch(`${backendUrl}/api/transcribe`, {
        method: 'POST',
        body: form,
        signal: transcribeController.signal,
      })
    } catch {
      throw networkError()
    }
    if (!response.ok) {
      throw httpError(response.status)
    }
    const data = await response.json()
    if (isGone()) {
      return
    }
    const transcript = (data?.transcript ?? '').trim()
    if (!transcript) {
      askError.value = { key: 'qmEmptyTranscript' }
      speakStatus(msgText(askError.value))
      return
    }
    question.value = transcript
    preset.value = null
    askError.value = null
    // The transcript is read back with the next instruction in one
    // utterance, so recognition mistakes are caught early.
    const said = `${t('voiceYouAsked', { q: transcript })} ${
      photo.value ? t('qmWorking') : `${t('qmPointHint')} ${t('qmAutoHint')}`
    }`
    if (photo.value) {
      runAssist()
    } else {
      goScreen('point', { speak: false })
    }
    nextTick(() => {
      if (!isGone()) {
        speakStatus(said)
      }
    })
  } catch (err) {
    if (isGone()) {
      return
    }
    askError.value = asMsg(err)
    speakStatus(msgText(askError.value))
  } finally {
    transcribeController = null
  }
}

function onMicDown(event) {
  if (event.pointerType === 'mouse' && event.button !== 0) {
    return
  }
  try {
    event.currentTarget?.setPointerCapture?.(event.pointerId)
  } catch {
    // Capture unsupported: hold-to-talk still works while over the button.
  }
  micDownAt = Date.now()
  if (recording.value || transcribing.value) {
    micHeld = false
    return
  }
  micHeld = true
  ignoreMicClick = true
  micStart()
}

function onMicUp() {
  if (!micHeld) {
    // Already recording at pointerdown: tap-to-stop.
    if (recording.value && !transcribing.value) {
      ignoreMicClick = true
      micStopAndTranscribe()
    }
    return
  }
  micHeld = false
  if (Date.now() - micDownAt >= 500) {
    // Hold-to-talk: released after a hold.
    ignoreMicClick = true
    if (recording.value) {
      micStopAndTranscribe()
    }
  } else {
    // Quick tap: keep recording; ignore the click that follows.
    ignoreMicClick = true
  }
}

function onMicCancel() {
  // Never stop unintentionally on an interrupted gesture.
  micHeld = false
  ignoreMicClick = true
}

function onMicClick() {
  if (ignoreMicClick) {
    ignoreMicClick = false
    return
  }
  // Keyboard, switch, and assistive-tech activation: toggle.
  if (recording.value) {
    micStopAndTranscribe()
  } else {
    micStart()
  }
}

// Working: POST /api/assist with cancellation and late-response guards.
let assistController = null
let assistInFlight = false
let assistRun = 0

async function runAssist() {
  if (assistInFlight || !photo.value || !question.value.trim()) {
    return
  }
  assistInFlight = true
  const run = ++assistRun
  const sentPhoto = photo.value
  const sentQuestion = question.value.trim()
  result.value = null
  error.value = null
  goScreen('working')
  earcons.startWorking()
  assistController = new AbortController()
  try {
    const form = new FormData()
    form.append('image', sentPhoto)
    form.append('question', sentQuestion)
    form.append('language', locale.value)
    if (preset.value) {
      form.append('preset', preset.value)
    }
    let response
    try {
      response = await fetch(`${backendUrl}/api/assist`, {
        method: 'POST',
        body: form,
        signal: assistController.signal,
      })
    } catch {
      throw networkError()
    }
    if (!response.ok) {
      throw httpError(response.status)
    }
    const data = await response.json()
    if (
      run !== assistRun ||
      isGone() ||
      photo.value !== sentPhoto ||
      question.value.trim() !== sentQuestion
    ) {
      return
    }
    result.value = data
    earcons.stopWorking()
    earcons.done()
    goScreen('answer')
    await nextTick()
    if (!isGone() && run === assistRun && voicePrefs.value.autoRead) {
      readAnswerAloud(spokenText.value)
    }
  } catch (err) {
    if (
      run !== assistRun ||
      isGone() ||
      photo.value !== sentPhoto ||
      question.value.trim() !== sentQuestion
    ) {
      return
    }
    earcons.stopWorking()
    earcons.error()
    error.value = asMsg(err)
  } finally {
    assistController = null
    assistInFlight = false
  }
}

function cancelAssist() {
  assistRun += 1
  assistController?.abort()
  earcons.stopWorking()
  goScreen('ask')
}

function tryAgain() {
  runAssist()
}

function retakePhoto() {
  photo.value = null
  result.value = null
  error.value = null
  goScreen('point')
}

function newProduct() {
  photo.value = null
  question.value = ''
  preset.value = null
  result.value = null
  error.value = null
  askError.value = null
  goScreen('ask')
}

function askAnother() {
  question.value = ''
  preset.value = null
  result.value = null
  error.value = null
  askError.value = null
  goScreen('ask')
}

// Answer first, then evidence; doubts are always spoken. Every spoken part
// is also on screen.
const isAnswered = computed(() => result.value?.answer_status === 'answered')

function fallbackTarget() {
  if (preset.value === 'allergens') {
    return t('targetIngredients')
  }
  if (preset.value === 'expiry') {
    return t('targetDate')
  }
  if (preset.value === 'read') {
    return t('targetLabel')
  }
  return t('targetGeneric')
}

function framingTip() {
  if (!result.value) {
    return ''
  }
  for (const code of result.value.framing ?? []) {
    if (code === 'not_found' && result.value.answer_status !== 'answered') {
      continue
    }
    const key =
      'tip' +
      code
        .split('_')
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join('')
    return t(key)
  }
  return ''
}

const spokenText = computed(() => {
  if (!result.value) {
    return ''
  }
  const r = result.value
  let text = r.answer || t('emptyAnswer')
  if (r.evidence) {
    text += ` ${t('qmEvidenceIntro')} ${r.evidence}`
  }
  if (r.fallback) {
    text += ` ${t('qmFallback', { target: fallbackTarget() })}`
  }
  const tip = framingTip()
  if (tip) {
    text += ` ${tip}`
  }
  return text
})

function readSpoken() {
  readAnswerAloud(spokenText.value)
}

const showZoom = computed(
  () =>
    result.value?.source === 'region' &&
    (result.value?.boxes?.length ?? 0) > 0 &&
    !!photo.value,
)

const zoomBoxName = computed(() => {
  const concept = result.value?.concept ?? ''
  return concept
    ? concept.charAt(0).toUpperCase() + concept.slice(1)
    : t('targetLabel')
})

const timingsText = computed(() => {
  const m = result.value?.timings_ms
  if (!m) {
    return ''
  }
  const s = (ms) => ((ms ?? 0) / 1000).toFixed(1)
  return t('qmTimings', {
    total: s(m.total),
    plan: s(m.plan),
    locate: s(m.locate),
    crop: s(m.crop),
    read: s(m.read),
  })
})

const regionSourceText = computed(() => {
  if (!result.value) {
    return ''
  }
  if (result.value.source !== 'region' || !result.value.boxes?.length) {
    return t('srcFull')
  }
  const { position, size } = describeBox(result.value.boxes[0])
  const cap = (id) => id.charAt(0).toUpperCase() + id.slice(1)
  return t('regionOption', {
    name: zoomBoxName.value,
    n: 1,
    position: t(`boxPos${cap(position)}`),
    size: t(`boxSize${cap(size)}`),
  })
})
</script>

<template>
  <div class="quickmode">
    <section v-if="screen === 'ask'" class="qm-card" aria-labelledby="qm-ask-heading">
      <h2 id="qm-ask-heading" tabindex="-1">{{ t('qmAskHeading') }}</h2>
      <p v-if="backendStatus === 'error'" class="qm-err">{{ t('statusOffline') }}</p>
      <div v-if="photo" class="qm-status-line" role="status">
        <p class="qm-ok">✓ {{ t('qmSamePhoto') }}</p>
      </div>
      <button v-if="photo" class="qm-btn qm-btn-secondary" @click="takeNewPhoto">
        {{ t('qmNewPhoto') }}
      </button>
      <fieldset class="qm-preset-group">
        <legend>{{ t('presetTitle') }}</legend>
        <button
          v-for="item in PRESETS"
          :key="item.key"
          class="qm-btn qm-btn-secondary"
          @click="askPreset(item.key, item.textKey)"
        >
          {{ t(item.textKey) }}
        </button>
      </fieldset>
      <!-- Mic button (hidden in Greek and without a secure-context mic). -->
      <div v-if="voiceSupported && locale !== 'el'">
        <button
          class="qm-btn qm-btn-secondary qm-btn-block"
          :aria-pressed="recording"
          :disabled="transcribing"
          @pointerdown="onMicDown"
          @pointerup="onMicUp"
          @pointercancel="onMicCancel"
          @click="onMicClick"
          @contextmenu.prevent
        >
          {{ recording ? t('voiceStop') : t('voiceAsk') }}
        </button>
        <p class="qm-hint">{{ t('voiceHint') }}</p>
        <div v-if="recording || transcribing" class="qm-status-line" role="status">
          <p class="qm-muted">{{ recording ? t('voiceRecording') : t('qmLoading') }}</p>
        </div>
        <p v-if="recordDetail" class="qm-err" role="alert">✗ {{ msgText(recordDetail) }}</p>
      </div>
      <p v-else-if="locale === 'el'" class="qm-muted">{{ t('voiceUnavailable') }}</p>
      <label class="qm-prompt-label" for="qm-question">{{ t('qLabel') }}</label>
      <p class="qm-hint" id="qm-question-hint">{{ t('qHint') }}</p>
      <input
        id="qm-question"
        v-model="question"
        type="text"
        :placeholder="t('qPlaceholder')"
        :maxlength="MAX_QUESTION_CHARS"
        aria-describedby="qm-question-hint"
        @keyup.enter="submitTyped"
      />
      <button
        class="qm-btn qm-btn-primary qm-btn-block"
        :disabled="!question.trim()"
        @click="submitTyped"
      >
        {{ t('wizNext') }}
      </button>
      <p v-if="askError" class="qm-err" role="alert">✗ {{ msgText(askError) }}</p>
    </section>

    <section v-if="screen === 'point'" class="qm-card" aria-labelledby="qm-point-heading">
      <h2 id="qm-point-heading" tabindex="-1">{{ t('qmPointHeading') }}</h2>
      <p class="qm-muted">{{ t('qmPointHint') }} {{ t('qmAutoHint') }}</p>
      <p v-if="!cameraSupported" class="qm-muted">{{ t('camUnsupported') }}</p>
      <video
        v-if="camStatus === 'starting' || camStatus === 'live'"
        ref="videoEl"
        class="qm-camera-video"
        autoplay
        muted
        playsinline
        :aria-label="t('vidLabel')"
      ></video>
      <div class="qm-status-line" role="status">
        <p v-if="camStatus === 'starting'" class="qm-muted">{{ t('camStarting') }}</p>
        <p v-if="camStatus === 'live'" class="qm-muted">{{ t('camLive') }}</p>
      </div>
      <p v-if="camStatus === 'error'" class="qm-err" role="alert">
        ✗ {{ msgText(camDetail) }}
      </p>
      <button
        class="qm-btn qm-btn-primary qm-btn-big"
        :disabled="camStatus !== 'live'"
        @click="capturePhoto"
      >
        {{ t('qmTakePhoto') }}
      </button>
      <div class="qm-camera-buttons">
        <button
          v-if="torchSupported"
          class="qm-btn qm-btn-secondary"
          :disabled="camStatus !== 'live'"
          :aria-pressed="torchOn"
          @click="toggleTorch"
        >
          {{ torchOn ? t('torchOff') : t('torchOn') }}
        </button>
        <button class="qm-btn qm-btn-secondary" @click="cancelPoint">
          {{ t('qmCancel') }}
        </button>
      </div>
      <label class="qm-prompt-label" for="qm-file">{{ t('uploadLabel') }}</label>
      <p class="qm-hint" id="qm-file-hint">{{ t('uploadHint') }}</p>
      <input
        id="qm-file"
        ref="fileInputEl"
        type="file"
        accept="image/jpeg,image/png,image/webp"
        aria-describedby="qm-file-hint"
        @change="onQuickFile"
      />
      <p v-if="pointError" class="qm-err" role="alert">✗ {{ msgText(pointError) }}</p>
    </section>

    <section
      v-if="screen === 'working'"
      class="qm-card"
      aria-labelledby="qm-working-heading"
    >
      <h2 id="qm-working-heading" tabindex="-1">{{ t('qmWorkingHeading') }}</h2>
      <div v-if="!error">
        <div class="qm-status-line" role="status">
          <p class="qm-muted">{{ t('qmWorking') }}</p>
        </div>
        <button class="qm-btn qm-btn-secondary" @click="cancelAssist">
          {{ t('qmCancel') }}
        </button>
      </div>
      <div v-else>
        <p class="qm-err" role="alert">✗ {{ msgText(error) }}</p>
        <div class="qm-answer-actions">
          <button class="qm-btn qm-btn-primary" @click="tryAgain">
            {{ t('qmTryAgain') }}
          </button>
          <button class="qm-btn qm-btn-secondary" @click="retakePhoto">
            {{ t('qmRetake') }}
          </button>
          <button class="qm-btn qm-btn-secondary" @click="newProduct">
            {{ t('qmNewProduct') }}
          </button>
        </div>
      </div>
    </section>

    <section v-if="screen === 'answer'" class="qm-card" aria-labelledby="qm-answer-heading">
      <h2 id="qm-answer-heading" tabindex="-1">{{ t('answerHeading') }}</h2>
      <div class="qm-status-line" role="status">
        <p v-if="result" class="qm-ok">
          ✓ {{ t('askSuccess', { source: regionSourceText }) }}
        </p>
      </div>
      <p v-if="result" class="qm-answer" :lang="locale">
        {{ result.answer || t('emptyAnswer') }}
      </p>
      <div v-if="result?.evidence" class="qm-evidence">
        <h3>{{ t('qmEvidenceIntro') }}</h3>
        <p class="qm-evidence-text">{{ result.evidence }}</p>
      </div>
      <p v-if="result?.fallback" class="qm-muted">
        {{ t('qmFallback', { target: fallbackTarget() }) }}
      </p>
      <p v-if="framingTip()" class="qm-tip">{{ framingTip() }}</p>
      <p class="qm-hint">{{ t('aiNote') }}</p>
      <ZoomView
        v-if="showZoom"
        :photo="photo"
        :boxes="result.boxes"
        :target="fallbackTarget()"
        :box-name="zoomBoxName"
      />
      <details v-if="result" class="qm-details">
        <summary>{{ t('qmDetailsTitle') }}</summary>
        <p>{{ timingsText }}</p>
        <p>{{ t('askSuccess', { source: regionSourceText }) }}</p>
      </details>
      <div class="qm-answer-actions">
        <button
          :class="['qm-btn', isAnswered ? 'qm-btn-primary' : 'qm-btn-secondary']"
          @click="askAnother"
        >
          {{ t('wizAskAnother') }}
        </button>
        <button
          :class="['qm-btn', isAnswered ? 'qm-btn-secondary' : 'qm-btn-primary']"
          @click="retakePhoto"
        >
          {{ t('qmRetake') }}
        </button>
        <button class="qm-btn qm-btn-secondary" @click="newProduct">
          {{ t('qmNewProduct') }}
        </button>
        <button
          class="qm-btn qm-btn-secondary"
          :disabled="!speechSupported || isSpeaking"
          @click="readSpoken"
        >
          {{ isSpeaking ? t('readingBtn') : t('readBtn') }}
        </button>
        <button
          v-if="isSpeaking"
          class="qm-btn qm-btn-secondary"
          :aria-label="t('stopLabel')"
          @click="stopSpeaking"
        >
          {{ t('stopBtn') }}
        </button>
      </div>
      <p v-if="!speechSupported" class="qm-muted">{{ t('speechUnsupported') }}</p>
    </section>
  </div>
</template>
