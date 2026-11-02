<script setup>
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import '../quickmode.css'
import { cropToFile } from '../lib/crop.js'
import { describeBox, scaleBox } from '../lib/boxes.js'

const props = defineProps({
  photo: { type: File, required: true },
  boxes: { type: Array, required: true },
  target: { type: String, required: true },
  boxName: { type: String, required: true },
})

const shared = inject('visionspark')
const t = shared.t

let disposed = false
const photoUrl = ref(null)
const cropUrl = ref(null)
const naturalSize = ref({ w: 0, h: 0 })
const cropError = ref(null)
const zoom = ref(1)
const highContrast = ref(false)
const inverted = ref(false)

function revoke(url) {
  if (url) {
    URL.revokeObjectURL(url)
  }
}

watch(
  () => props.photo,
  (file) => {
    revoke(photoUrl.value)
    revoke(cropUrl.value)
    photoUrl.value = null
    cropUrl.value = null
    naturalSize.value = { w: 0, h: 0 }
    cropError.value = null
    if (file) {
      photoUrl.value = URL.createObjectURL(file)
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  disposed = true
  revoke(photoUrl.value)
  revoke(cropUrl.value)
})

async function onPhotoLoad(event) {
  const img = event.target
  naturalSize.value = {
    w: img.naturalWidth,
    h: img.naturalHeight,
  }
  cropError.value = null
  if (props.boxes.length === 0) {
    return
  }
  try {
    const file = await cropToFile(img, props.boxes[0], naturalSize.value, 0)
    if (disposed) {
      return
    }
    revoke(cropUrl.value)
    cropUrl.value = URL.createObjectURL(file)
  } catch (err) {
    if (!disposed) {
      cropError.value = err
    }
  }
}

function zoomIn() {
  zoom.value = Math.min(4, zoom.value + 0.5)
}

function zoomOut() {
  zoom.value = Math.max(1, zoom.value - 0.5)
}

const cropStyle = computed(() => {
  const filters = []
  if (highContrast.value) {
    filters.push('grayscale(1) contrast(1.8)')
  }
  if (inverted.value) {
    filters.push('invert(1)')
  }
  return {
    width: zoom.value === 1 ? '100%' : `${zoom.value * 100}%`,
    maxWidth: zoom.value === 1 ? '100%' : 'none',
    filter: filters.length > 0 ? filters.join(' ') : 'none',
  }
})

// Full-photo overlay for sighted viewers: same 1:1 viewBox mapping as the
// wizard overlay, with a spoken-friendly title per box.
const overlayBoxes = computed(() => {
  const nw = naturalSize.value.w
  const nh = naturalSize.value.h
  const out = []
  props.boxes.forEach((box, index) => {
    const scaled = scaleBox(box, nw, nh)
    if (scaled) {
      out.push({ ...scaled, index, box })
    }
  })
  return out
})

const labelSize = () => Math.max(14, Math.round(naturalSize.value.h * 0.035))

function labelY(box) {
  const s = labelSize()
  return box.y1 - 8 >= s ? box.y1 - 8 : box.y1 + s + 2
}

function overlayTitle(box, index) {
  const { position, size } = describeBox(box)
  const cap = (id) => id.charAt(0).toUpperCase() + id.slice(1)
  return t('boxTitle', {
    name: props.boxName,
    n: index + 1,
    position: t(`boxPos${cap(position)}`),
    size: t(`boxSize${cap(size)}`),
  })
}
</script>

<template>
  <div class="zoom-view">
    <div class="qm-zoom-controls">
      <button
        class="qm-btn qm-btn-secondary"
        :disabled="zoom <= 1"
        @click="zoomOut"
      >
        {{ t('qmZoomOut') }}
      </button>
      <span class="qm-zoom-level" role="status">
        {{ t('qmZoomLevel', { pct: Math.round(zoom * 100) }) }}
      </span>
      <button
        class="qm-btn qm-btn-secondary"
        :disabled="zoom >= 4"
        @click="zoomIn"
      >
        {{ t('qmZoomIn') }}
      </button>
      <button class="qm-btn qm-btn-secondary" @click="zoom = 1">
        {{ t('qmZoomReset') }}
      </button>
      <button
        class="qm-btn qm-btn-secondary"
        :aria-pressed="highContrast"
        @click="highContrast = !highContrast"
      >
        {{ t('qmContrast') }}
      </button>
      <button
        class="qm-btn qm-btn-secondary"
        :aria-pressed="inverted"
        @click="inverted = !inverted"
      >
        {{ t('qmInvert') }}
      </button>
    </div>
    <div class="qm-zoom-frame">
      <img
        v-if="cropUrl"
        :src="cropUrl"
        :alt="t('qmZoomAlt', { target })"
        :style="cropStyle"
      />
      <p v-else-if="cropError" class="qm-err">{{ t(cropError.key) }}</p>
      <p v-else class="qm-muted">{{ t('qmLoading') }}</p>
    </div>
    <details class="qm-details">
      <summary>{{ t('qmFullPhoto') }}</summary>
      <div v-if="photoUrl" class="qm-preview-frame">
        <img :src="photoUrl" :alt="t('altPreview')" @load="onPhotoLoad" />
        <svg
          v-if="overlayBoxes.length > 0 && naturalSize.w > 0 && naturalSize.h > 0"
          class="qm-overlay"
          :viewBox="`0 0 ${naturalSize.w} ${naturalSize.h}`"
          role="img"
          :aria-label="t('overlayLabel')"
        >
          <g v-for="entry in overlayBoxes" :key="entry.index">
            <title>{{ overlayTitle(entry.box, entry.index) }}</title>
            <rect
              class="qm-box-halo"
              :x="entry.x1"
              :y="entry.y1"
              :width="entry.x2 - entry.x1"
              :height="entry.y2 - entry.y1"
            />
            <rect
              class="qm-box-line"
              :x="entry.x1"
              :y="entry.y1"
              :width="entry.x2 - entry.x1"
              :height="entry.y2 - entry.y1"
            />
            <text
              class="qm-box-label"
              :x="entry.x1 + 6"
              :y="labelY(entry)"
              :font-size="labelSize()"
            >
              {{ entry.index + 1 }}
            </text>
          </g>
        </svg>
      </div>
    </details>
  </div>
</template>
