<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'

const backendUrl =
  import.meta.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:8000'

const status = ref('idle') // 'idle' | 'loading' | 'success' | 'error'
const detail = ref('')

const MAX_BYTES = 5 * 1024 * 1024
const selectedFile = ref(null)
const prompt = ref('dog')
const segStatus = ref('idle') // 'idle' | 'loading' | 'success' | 'error'
const segDetail = ref('')
const boxes = ref([])

// Visual question answering reuses the uploaded image.
const question = ref('')
const askStatus = ref('idle') // 'idle' | 'loading' | 'success' | 'error'
const askDetail = ref('')
const answer = ref('')

// Text-to-speech for the Q&A answer via the Web Speech API (no backend needed).
const speechSupported =
  typeof window !== 'undefined' &&
  'speechSynthesis' in window &&
  'SpeechSynthesisUtterance' in window
const isSpeaking = ref(false)
let disposed = false

function stopSpeaking() {
  if (speechSupported) {
    window.speechSynthesis.cancel()
  }
  if (!disposed) {
    isSpeaking.value = false
  }
}

function readAnswerAloud() {
  if (!speechSupported || !answer.value) {
    return
  }
  stopSpeaking()
  const utterance = new SpeechSynthesisUtterance(answer.value)
  utterance.onend = () => {
    if (!disposed) {
      isSpeaking.value = false
    }
  }
  utterance.onerror = () => {
    if (!disposed) {
      isSpeaking.value = false
    }
  }
  isSpeaking.value = true
  window.speechSynthesis.speak(utterance)
}

// A new (or cleared) answer invalidates any ongoing speech.
watch(answer, () => {
  stopSpeaking()
})

// Image preview + overlay state. The SVG overlay uses the image's natural
// pixel dimensions as its viewBox so box coordinates map 1:1.
const previewUrl = ref(null)
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
  imgError.value = 'Could not display the selected image.'
}

// Stale results belong to the previous prompt; clear them when it changes.
watch(prompt, () => {
  if (segStatus.value === 'loading') {
    return
  }
  segStatus.value = 'idle'
  segDetail.value = ''
  boxes.value = []
})

// Same for the Q&A answer when the question changes.
watch(question, () => {
  if (askStatus.value === 'loading') {
    return
  }
  askStatus.value = 'idle'
  askDetail.value = ''
  answer.value = ''
})

onBeforeUnmount(() => {
  disposed = true
  revokePreview()
  if (speechSupported) {
    window.speechSynthesis.cancel()
  }
})

function onFileChange(event) {
  selectedFile.value = event.target.files?.[0] ?? null
  segStatus.value = 'idle'
  segDetail.value = ''
  boxes.value = []
  askStatus.value = 'idle'
  askDetail.value = ''
  answer.value = ''
  setPreview()
}

async function runSegmentation() {
  if (!selectedFile.value) {
    return
  }
  if (selectedFile.value.size > MAX_BYTES) {
    segStatus.value = 'error'
    segDetail.value = 'Image exceeds the 5 MiB size limit.'
    return
  }
  const trimmedPrompt = prompt.value.trim()
  if (!trimmedPrompt) {
    segStatus.value = 'error'
    segDetail.value = 'Enter what SAM should look for.'
    return
  }
  segStatus.value = 'loading'
  segDetail.value = ''
  boxes.value = []
  try {
    const form = new FormData()
    form.append('image', selectedFile.value)
    form.append('prompt', trimmedPrompt)
    const response = await fetch(`${backendUrl}/api/segment`, {
      method: 'POST',
      body: form,
    })
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      throw new Error(body?.detail ?? `HTTP ${response.status}`)
    }
    const data = await response.json()
    boxes.value = data?.boxes ?? []
    segStatus.value = 'success'
    segDetail.value =
      boxes.value.length === 0
        ? 'No objects found.'
        : `Found ${boxes.value.length} object${boxes.value.length === 1 ? '' : 's'}.`
  } catch (error) {
    segStatus.value = 'error'
    segDetail.value = error instanceof Error ? error.message : 'Unknown error'
  }
}

async function runAsk() {
  if (!selectedFile.value) {
    return
  }
  if (selectedFile.value.size > MAX_BYTES) {
    askStatus.value = 'error'
    askDetail.value = 'Image exceeds the 5 MiB size limit.'
    return
  }
  const trimmedQuestion = question.value.trim()
  if (!trimmedQuestion) {
    askStatus.value = 'error'
    askDetail.value = 'Enter a question about the image.'
    return
  }
  askStatus.value = 'loading'
  askDetail.value = ''
  answer.value = ''
  try {
    const form = new FormData()
    form.append('image', selectedFile.value)
    form.append('question', trimmedQuestion)
    const response = await fetch(`${backendUrl}/api/ask`, {
      method: 'POST',
      body: form,
    })
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      throw new Error(body?.detail ?? `HTTP ${response.status}`)
    }
    const data = await response.json()
    answer.value = data?.answer ?? ''
    askStatus.value = 'success'
  } catch (error) {
    askStatus.value = 'error'
    askDetail.value = error instanceof Error ? error.message : 'Unknown error'
  }
}

async function checkBackend() {
  status.value = 'loading'
  detail.value = ''
  try {
    const response = await fetch(`${backendUrl}/health`)
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }
    const data = await response.json()
    if (data?.status === 'ok') {
      status.value = 'success'
      detail.value = 'Backend is reachable.'
    } else {
      throw new Error('Unexpected response body')
    }
  } catch (error) {
    status.value = 'error'
    detail.value = error instanceof Error ? error.message : 'Unknown error'
  }
}
</script>

<template>
  <main class="container">
    <h1>VisionSpark</h1>
    <p class="tagline">
      Real-time multimodal accessibility assistant: converts visual input
      from everyday objects into instant, clear audio feedback.
    </p>

    <section class="status-card" aria-label="Backend status">
      <h2>Backend status</h2>
      <p>
        Backend URL: <code>{{ backendUrl }}</code>
      </p>
      <button :disabled="status === 'loading'" @click="checkBackend">
        {{ status === 'loading' ? 'Checking…' : 'Check backend health' }}
      </button>
      <p v-if="status === 'idle'" class="muted">Not checked yet.</p>
      <p v-if="status === 'loading'" class="muted">Checking backend…</p>
      <p v-if="status === 'success'" class="ok">✓ {{ detail }}</p>
      <p v-if="status === 'error'" class="err">
        ✗ Backend unreachable: {{ detail }}
      </p>
    </section>

    <section class="status-card segment" aria-label="Image segmentation">
      <h2>Image segmentation</h2>
      <p class="muted">Upload a JPEG, PNG, or WebP image (max 5 MiB).</p>
      <label class="prompt-label" for="prompt-input">
        What should SAM look for?
      </label>
      <input
        id="prompt-input"
        v-model="prompt"
        type="text"
        placeholder="dog"
        maxlength="200"
      />
      <input
        type="file"
        accept="image/jpeg,image/png,image/webp"
        @change="onFileChange"
      />
      <button
        :disabled="segStatus === 'loading' || !selectedFile || !prompt.trim()"
        @click="runSegmentation"
      >
        {{ segStatus === 'loading' ? 'Segmenting…' : 'Run segmentation' }}
      </button>
      <figure v-if="previewUrl" class="preview">
        <div class="preview-frame">
          <img
            :src="previewUrl"
            alt="Preview of the uploaded image"
            @load="onImgLoad"
            @error="onImgError"
          />
          <svg
            v-if="boxes.length > 0 && naturalSize.w > 0 && naturalSize.h > 0"
            class="overlay"
            :viewBox="`0 0 ${naturalSize.w} ${naturalSize.h}`"
            role="img"
            aria-label="Segmentation bounding boxes overlaid on the preview"
          >
            <g v-for="(box, index) in boxes" :key="index">
              <title>
                Box {{ index + 1 }}: x {{ box.x1 }} to {{ box.x2 }}, y
                {{ box.y1 }} to {{ box.y2 }}
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
        <figcaption v-if="imgError" class="err">{{ imgError }}</figcaption>
      </figure>
      <p v-if="segStatus === 'idle'" class="muted">No image segmented yet.</p>
      <p v-if="segStatus === 'loading'" class="muted">Segmenting image…</p>
      <p v-if="segStatus === 'success'" class="ok">✓ {{ segDetail }}</p>
      <p v-if="segStatus === 'error'" class="err">✗ {{ segDetail }}</p>
      <ul v-if="segStatus === 'success' && boxes.length > 0" class="box-list">
        <li v-for="(box, index) in boxes" :key="index">
          Box {{ index + 1 }}: x {{ box.x1 }}–{{ box.x2 }}, y {{ box.y1 }}–{{
            box.y2
          }}
          (image {{ box.w }}×{{ box.h }})
        </li>
      </ul>
    </section>

    <section class="status-card segment" aria-label="Ask about the image">
      <h2>Ask about the image</h2>
      <p class="muted">
        Uses the image uploaded above. Upload one first if none is selected.
      </p>
      <label class="prompt-label" for="question-input">
        What do you want to know?
      </label>
      <input
        id="question-input"
        v-model="question"
        type="text"
        placeholder="What is in this image?"
        maxlength="500"
      />
      <button
        :disabled="askStatus === 'loading' || !selectedFile || !question.trim()"
        @click="runAsk"
      >
        {{ askStatus === 'loading' ? 'Asking…' : 'Ask' }}
      </button>
      <p v-if="askStatus === 'idle'" class="muted">No question asked yet.</p>
      <p v-if="askStatus === 'loading'" class="muted">Asking Muse Spark…</p>
      <p v-if="askStatus === 'error'" class="err">✗ {{ askDetail }}</p>
      <p v-if="askStatus === 'success'" class="answer">{{ answer }}</p>
      <div v-if="askStatus === 'success'" class="speech-controls">
        <button
          :disabled="!speechSupported || !answer || isSpeaking"
          @click="readAnswerAloud"
        >
          {{ isSpeaking ? 'Reading…' : 'Read answer aloud' }}
        </button>
        <button :disabled="!isSpeaking" @click="stopSpeaking">Stop</button>
        <p v-if="!speechSupported" class="muted">
          Speech playback is not supported in this browser.
        </p>
        <p class="sr-only" role="status">
          {{ isSpeaking ? 'Reading answer aloud.' : '' }}
        </p>
      </div>
    </section>
  </main>
</template>

<style scoped>
.container {
  max-width: 640px;
  margin: 0 auto;
  padding: 3rem 1.5rem;
  text-align: center;
}

.tagline {
  margin: 0 0 2rem;
  font-size: 1.1rem;
}

.status-card {
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.5rem;
}

.status-card h2 {
  margin-top: 0;
}

.segment {
  margin-top: 1.5rem;
}

.segment input[type='file'] {
  display: block;
  margin: 1rem auto;
}

.prompt-label {
  display: block;
  margin-top: 1rem;
  font-weight: 600;
  color: var(--text-h);
}

.segment input[type='text'] {
  display: block;
  margin: 0.5rem auto 0;
  padding: 0.5rem 0.75rem;
  font-size: 1rem;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--bg);
  color: inherit;
  max-width: 100%;
  box-sizing: border-box;
}

.box-list {
  list-style: none;
  padding: 0;
  margin: 1rem 0 0;
  text-align: left;
  font-family: ui-monospace, Consolas, monospace;
  font-size: 0.9rem;
}

.box-list li {
  padding: 0.4rem 0.6rem;
  border-top: 1px solid var(--border);
}

.preview {
  margin: 1.5rem 0 0;
  padding: 0;
}

.preview-frame {
  position: relative;
  display: inline-block;
  max-width: 100%;
  line-height: 0;
}

.preview-frame img {
  display: block;
  max-width: 100%;
  height: auto;
  border-radius: 8px;
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
  fill: rgba(190, 242, 100, 0.08);
  vector-effect: non-scaling-stroke;
}

.overlay .box-halo {
  stroke: rgba(0, 0, 0, 0.75);
  stroke-width: 5;
}

.overlay .box-line {
  stroke: #bef264;
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
  margin: 1rem 0 0;
  padding: 1rem;
  border-top: 1px solid var(--border);
  text-align: left;
  white-space: pre-wrap;
  color: var(--text-h);
}

.speech-controls {
  margin-top: 1rem;
}

.speech-controls button {
  margin: 0 0.25rem;
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

button {
  margin: 1rem 0;
  padding: 0.6rem 1.2rem;
  font-size: 1rem;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--accent-bg);
  color: inherit;
  cursor: pointer;
}

button:disabled {
  opacity: 0.6;
  cursor: wait;
}

code {
  font-family: ui-monospace, Consolas, monospace;
  background: var(--code-bg);
  padding: 2px 6px;
  border-radius: 4px;
}

.muted {
  color: var(--text);
}

.ok {
  color: #16a34a;
  font-weight: 600;
}

.err {
  color: #dc2626;
  font-weight: 600;
}
</style>
