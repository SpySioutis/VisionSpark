<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

const backendUrl =
  import.meta.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:8000'

const status = ref('idle') // 'idle' | 'loading' | 'success' | 'error'
const detail = ref('')

const MAX_BYTES = 5 * 1024 * 1024
const MAX_CAPTURE_EDGE = 1600
const selectedFile = ref(null)
const fileInputEl = ref(null)
const prompt = ref('dog')
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

// Text-to-speech for the Q&A answer via the Web Speech API (no backend needed).
const speechSupported =
  typeof window !== 'undefined' &&
  'speechSynthesis' in window &&
  'SpeechSynthesisUtterance' in window
const isSpeaking = ref(false)
const speechNote = ref('')
let disposed = false

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
    announceSpeech('Speech stopped.')
  }
}

function readAnswerAloud() {
  if (!speechSupported || !answer.value) {
    return
  }
  cancelSpeech()
  const utterance = new SpeechSynthesisUtterance(answer.value)
  // Programmatic cancels set isSpeaking false synchronously first, so a
  // still-true flag here means a genuine end or error worth announcing.
  utterance.onend = () => {
    if (!disposed && isSpeaking.value) {
      isSpeaking.value = false
      speechNote.value = 'Finished reading the answer.'
    }
  }
  utterance.onerror = () => {
    if (!disposed && isSpeaking.value) {
      isSpeaking.value = false
      speechNote.value = 'Speech was interrupted.'
    }
  }
  isSpeaking.value = true
  announceSpeech('Reading answer aloud.')
  window.speechSynthesis.speak(utterance)
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
      return 'Camera permission was denied. Allow camera access in your browser to use this feature.'
    case 'NotFoundError':
    case 'DevicesNotFoundError':
    case 'OverconstrainedError':
      return 'No camera was found on this device.'
    case 'NotReadableError':
    case 'TrackStartError':
      return 'The camera is already in use by another app.'
    case 'AbortError':
      return 'The camera request was interrupted. Try again.'
    default:
      return 'Could not start the camera. Try again.'
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
    camDetail.value = 'No live camera frame is available to capture.'
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
    camDetail.value = 'Could not capture a photo. Try again.'
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
        camDetail.value = 'Could not capture a photo. Try again.'
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
      camFlash.value = 'Photo captured — it is now the selected image.'
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
  imgError.value = 'Could not display the selected image.'
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
      fail('The image is still loading. Wait a moment and try again.')
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
      fail('The selected region has invalid coordinates.')
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
      fail('The selected region is empty after clipping to the image.')
      return
    }
    const canvas = document.createElement('canvas')
    canvas.width = cx2 - cx1
    canvas.height = cy2 - cy1
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      fail('Could not crop the selected region. Try again.')
      return
    }
    ctx.drawImage(img, cx1, cy1, cx2 - cx1, cy2 - cy1, 0, 0, canvas.width, canvas.height)
    canvas.toBlob(
      (blob) => {
        if (!blob) {
          fail('Could not crop the selected region. Try again.')
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
    if (askStatus.value === 'success' && answerSource.value !== 'the full image') {
      clearAnswer()
    }
    segStatus.value = 'success'
    segDetail.value =
      boxes.value.length === 0
        ? 'No objects found.'
        : `Found ${boxes.value.length} object${boxes.value.length === 1 ? '' : 's'}.`
  } catch (error) {
    if (selectedFile.value !== sentFile || prompt.value.trim() !== sentPrompt) {
      segStatus.value = 'idle'
      segDetail.value = ''
      boxes.value = []
      return
    }
    segStatus.value = 'error'
    segDetail.value = error instanceof Error ? error.message : 'Unknown error'
  }
}

async function runAsk() {
  if (!selectedFile.value) {
    return
  }
  const trimmedQuestion = question.value.trim()
  if (!trimmedQuestion) {
    askStatus.value = 'error'
    askDetail.value = 'Enter a question about the image.'
    return
  }
  // Resolve which pixels to send. Region mode never silently falls back:
  // without a valid box the request is refused with a clear message.
  let imageToSend = selectedFile.value
  let sourceLabel = 'the full image'
  const sentKind = askTarget.value
  const sentRegion = regionIndex.value
  if (askTarget.value === 'region') {
    const box = boxes.value[regionIndex.value]
    if (!box) {
      askStatus.value = 'error'
      askDetail.value =
        'The selected region is no longer available. Choose Full image or re-run segmentation.'
      return
    }
    const preCropFile = selectedFile.value
    try {
      imageToSend = await cropRegion(box, sentRegion)
    } catch (error) {
      askStatus.value = 'error'
      askDetail.value = error instanceof Error ? error.message : 'Unknown error'
      return
    }
    if (
      selectedFile.value !== preCropFile ||
      askTarget.value !== 'region' ||
      regionIndex.value !== sentRegion
    ) {
      return
    }
    sourceLabel = `detected region ${sentRegion + 1}`
  }
  if (imageToSend.size > MAX_BYTES) {
    askStatus.value = 'error'
    askDetail.value = 'Image exceeds the 5 MiB size limit.'
    return
  }
  const sentFile = selectedFile.value
  const sentQuestion = trimmedQuestion
  askStatus.value = 'loading'
  askDetail.value = ''
  answer.value = ''
  answerSource.value = ''
  try {
    const form = new FormData()
    form.append('image', imageToSend)
    form.append('question', sentQuestion)
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

    <section class="status-card" aria-labelledby="how-heading">
      <h2 id="how-heading">How it works</h2>
      <ol class="steps">
        <li>Select a photo — upload a file or capture one with your camera.</li>
        <li>Optionally segment it to locate an object in the image.</li>
        <li>Ask a question about the full image or a detected region.</li>
        <li>Read the answer, or listen to it with “Read answer aloud”.</li>
      </ol>
    </section>

    <section class="status-card segment" aria-labelledby="backend-heading">
      <h2 id="backend-heading">Backend status</h2>
      <p>
        Backend URL: <code>{{ backendUrl }}</code>
      </p>
      <button :disabled="status === 'loading'" @click="checkBackend">
        {{ status === 'loading' ? 'Checking…' : 'Check backend health' }}
      </button>
      <div class="status-line" role="status">
        <p v-if="status === 'idle'" class="muted">Not checked yet.</p>
        <p v-if="status === 'loading'" class="muted">Checking backend…</p>
        <p v-if="status === 'success'" class="ok">✓ {{ detail }}</p>
      </div>
      <p v-if="status === 'error'" class="err" role="alert">
        ✗ Backend unreachable: {{ detail }}
      </p>
    </section>

    <section class="status-card segment" aria-labelledby="segment-heading">
      <h2 id="segment-heading">Image segmentation</h2>
      <label class="prompt-label" for="image-input">Choose an image</label>
      <p class="muted hint" id="image-hint">
        JPEG, PNG, or WebP, max 5 MiB.
      </p>
      <input
        id="image-input"
        ref="fileInputEl"
        type="file"
        accept="image/jpeg,image/png,image/webp"
        aria-describedby="image-hint"
        @change="onFileChange"
      />
      <div class="camera">
        <h3 id="camera-heading">Or use your camera</h3>
        <div class="camera-buttons">
          <button
            :disabled="
              !cameraSupported ||
              camStatus === 'starting' ||
              camStatus === 'live'
            "
            @click="startCamera"
          >
            {{ camStatus === 'starting' ? 'Starting…' : 'Use camera' }}
          </button>
          <button :disabled="camStatus !== 'live'" @click="capturePhoto">
            Capture photo
          </button>
          <button
            :disabled="camStatus !== 'live' && camStatus !== 'starting'"
            @click="stopCamera"
          >
            Stop camera
          </button>
        </div>
        <p v-if="!cameraSupported" class="muted">
          Camera is not supported in this browser.
        </p>
        <video
          v-if="camStatus === 'starting' || camStatus === 'live'"
          ref="videoEl"
          class="camera-video"
          autoplay
          muted
          playsinline
          aria-label="Live camera preview"
        ></video>
        <div class="status-line" role="status">
          <p v-if="camStatus === 'idle' && !camFlash" class="muted">
            Camera is off.
          </p>
          <p v-if="camStatus === 'idle' && camFlash" class="ok">
            ✓ {{ camFlash }}
          </p>
          <p v-if="camStatus === 'starting'" class="muted">
            Starting camera…
          </p>
          <p v-if="camStatus === 'live'" class="muted">
            Camera is live. Frame your object, then choose Capture photo.
          </p>
        </div>
        <p v-if="camStatus === 'error'" class="err" role="alert">
          ✗ {{ camDetail }}
        </p>
      </div>
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
      <button
        :disabled="segStatus === 'loading' || !selectedFile || !prompt.trim()"
        @click="runSegmentation"
      >
        {{ segStatus === 'loading' ? 'Segmenting…' : 'Run segmentation' }}
      </button>
      <figure v-if="previewUrl" class="preview">
        <div class="preview-frame">
          <img
            ref="previewImgEl"
            :src="previewUrl"
            :alt="`Preview of the selected image${selectedFile?.name ? `: ${selectedFile.name}` : ''}`"
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
        <figcaption v-if="imgError" class="err" role="alert">{{ imgError }}</figcaption>
      </figure>
      <div class="status-line" role="status">
        <p v-if="segStatus === 'idle'" class="muted">No image segmented yet.</p>
        <p v-if="segStatus === 'loading'" class="muted">Segmenting image…</p>
        <p v-if="segStatus === 'success'" class="ok">✓ {{ segDetail }}</p>
      </div>
      <p v-if="segStatus === 'error'" class="err" role="alert">
        ✗ {{ segDetail }}
      </p>
      <div v-if="segStatus === 'success' && boxes.length > 0">
        <h3 id="boxes-heading">Detected objects</h3>
        <ul class="box-list" aria-labelledby="boxes-heading">
          <li v-for="(box, index) in boxes" :key="index">
            Box {{ index + 1 }}: x {{ box.x1 }}–{{ box.x2 }}, y {{ box.y1 }}–{{
              box.y2
            }}
            (image {{ box.w }}×{{ box.h }})
          </li>
        </ul>
      </div>
    </section>

    <section class="status-card segment" aria-labelledby="ask-heading">
      <h2 id="ask-heading">Ask about the image</h2>
      <p class="muted">
        Uses the image selected above. Choose a file or capture a photo
        first if none is selected.
      </p>
      <label class="prompt-label" for="question-input">
        What do you want to know?
      </label>
      <p class="muted hint" id="question-hint">
        Ask one specific thing, e.g. “What allergens are listed?” or “What is
        the expiration date?”
      </p>
      <input
        id="question-input"
        v-model="question"
        type="text"
        placeholder="What is in this image?"
        maxlength="500"
        aria-describedby="question-hint"
      />
      <fieldset class="target-group">
        <legend>What should the question cover?</legend>
        <label>
          <input v-model="askTarget" type="radio" value="full" />
          Full image
        </label>
        <label>
          <input
            v-model="askTarget"
            type="radio"
            value="region"
            :disabled="boxes.length === 0"
          />
          Detected region
        </label>
      </fieldset>
      <p v-if="boxes.length === 0" class="muted hint">
        Region questions need segmentation first — run it above, or ask about
        the full image.
      </p>
      <div v-if="askTarget === 'region' && boxes.length > 0">
        <label class="prompt-label" for="region-select">
          Choose a detected region
        </label>
        <select id="region-select" v-model.number="regionIndex">
          <option
            v-for="(box, index) in boxes"
            :key="index"
            :value="index"
          >
            Detected region {{ index + 1 }} (x {{ box.x1 }}–{{ box.x2 }}, y
            {{ box.y1 }}–{{ box.y2 }})
          </option>
        </select>
      </div>
      <button
        :disabled="askStatus === 'loading' || !selectedFile || !question.trim()"
        @click="runAsk"
      >
        {{ askStatus === 'loading' ? 'Asking…' : 'Ask' }}
      </button>
      <div class="status-line" role="status">
        <p v-if="askStatus === 'idle'" class="muted">No question asked yet.</p>
        <p v-if="askStatus === 'loading'" class="muted">Asking Muse Spark…</p>
        <p v-if="askStatus === 'success'" class="ok">
          ✓ Answer received — asked about {{ answerSource }}.
        </p>
      </div>
      <p v-if="askStatus === 'error'" class="err" role="alert">
        ✗ {{ askDetail }}
      </p>
      <div v-if="askStatus === 'success'">
        <h3 id="answer-heading">Answer</h3>
        <p class="answer">{{ answer || 'The model returned an empty answer.' }}</p>
        <p class="muted hint">
          AI-generated answer — if text is unclear, or for allergens, dates,
          doses, or safety, always double-check the actual label.
        </p>
      </div>
      <div v-if="askStatus === 'success'" class="speech-controls">
        <button
          :disabled="!speechSupported || !answer || isSpeaking"
          @click="readAnswerAloud"
        >
          {{ isSpeaking ? 'Reading…' : 'Read answer aloud' }}
        </button>
        <button :disabled="!isSpeaking" aria-label="Stop reading aloud" @click="stopSpeaking">
          Stop
        </button>
        <p v-if="!speechSupported" class="muted">
          Speech playback is not supported in this browser.
        </p>
        <p v-if="isSpeaking" class="muted">Speaking — press Stop to cancel.</p>
        <p class="sr-only" role="status">{{ speechNote }}</p>
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
  font-size: 1.25rem;
}

.steps {
  margin: 0;
  padding-left: 1.5rem;
  text-align: left;
  display: inline-block;
}

.steps li {
  margin: 0.25rem 0;
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
  width: 100%;
  margin: 0.5rem 0 0;
  padding: 0.5rem 0;
  font-size: 1rem;
  min-height: 44px;
  box-sizing: border-box;
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

.segment input[type='text'] {
  display: block;
  width: 100%;
  margin: 0.5rem 0 0;
  padding: 0.75rem 1rem;
  font-size: 1.125rem;
  line-height: 1.5;
  min-height: 44px;
  border-radius: 8px;
  border: 2px solid var(--input-border);
  background: var(--bg);
  color: inherit;
  box-sizing: border-box;
}

.target-group {
  margin: 1rem 0 0;
  padding: 0.75rem 1rem;
  border: 2px solid var(--border);
  border-radius: 8px;
  text-align: left;
}

.target-group legend {
  font-weight: 600;
  color: var(--text-h);
  padding: 0 0.5rem;
}

.target-group label {
  display: inline-block;
  margin: 0.25rem 1rem 0.25rem 0;
  font-size: 1.125rem;
}

.target-group input[type='radio'] {
  width: 1.25rem;
  height: 1.25rem;
  margin-right: 0.5rem;
  vertical-align: middle;
  accent-color: var(--focus);
}

.segment select {
  display: block;
  width: 100%;
  margin: 0.5rem 0 0;
  padding: 0.75rem 1rem;
  font-size: 1.125rem;
  line-height: 1.5;
  min-height: 44px;
  border-radius: 8px;
  border: 2px solid var(--input-border);
  background: var(--bg);
  color: inherit;
  box-sizing: border-box;
}

.status-line p {
  margin: 1rem 0 0;
}

.box-list {
  list-style: none;
  padding: 0;
  margin: 0.5rem 0 0;
  text-align: left;
  font-family: ui-monospace, Consolas, monospace;
  font-size: 1rem;
}

.box-list li {
  padding: 0.4rem 0.6rem;
  border-top: 1px solid var(--border);
}

.preview {
  margin: 1.5rem 0 0;
  padding: 0;
}

.camera {
  margin-top: 1.5rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border);
}

.camera h3 {
  margin: 0 0 0.5rem;
}

.camera-buttons button {
  margin: 0.5rem 0.25rem 0;
}

.camera-video {
  display: block;
  width: 100%;
  aspect-ratio: 4 / 3;
  margin-top: 1rem;
  border-radius: 8px;
  background: #000;
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
  margin: 0.5rem 0 0;
  padding: 1rem;
  border-top: 1px solid var(--border);
  text-align: left;
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: break-word;
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
  margin: 1rem 0.25rem 0;
  padding: 0.75rem 1.5rem;
  font-size: 1.125rem;
  font-weight: 600;
  line-height: 1.5;
  min-height: 48px;
  border-radius: 8px;
  border: 2px solid var(--input-border);
  background: var(--accent-bg);
  color: inherit;
  cursor: pointer;
}

button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

code {
  font-family: ui-monospace, Consolas, monospace;
  background: var(--code-bg);
  padding: 2px 6px;
  border-radius: 4px;
  overflow-wrap: anywhere;
}

.muted {
  color: var(--text);
}

.ok {
  color: var(--ok);
  font-weight: 600;
}

.err {
  color: var(--err);
  font-weight: 600;
}

@media (max-width: 480px) {
  .container {
    padding: 2rem 1rem;
  }

  .status-card {
    padding: 1.25rem 1rem;
  }
}
</style>
