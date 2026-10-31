import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { VOICE_LANG } from '../i18n.js'

const SPEECH_CHUNK_LEN = 200
// Chrome silently stops long utterances (~15 s) with some voices, so long
// answers are queued as one utterance per chunk instead of a single one.
const SENTENCE_END = '.!?…。！？'

/**
 * Split text into TTS-sized chunks: first on sentence boundaries (kept with
 * their sentence) and newlines, then hard-wrap leftovers longer than maxLen
 * at the last space (or at maxLen when there is none, e.g. CJK). Drops
 * empty pieces.
 */
export function splitForSpeech(text, maxLen = SPEECH_CHUNK_LEN) {
  const limit = Math.max(1, maxLen)
  const chunks = []
  const push = (piece) => {
    const trimmed = piece.trim()
    if (trimmed) {
      chunks.push(trimmed)
    }
  }
  const wrap = (piece) => {
    let rest = piece.trim()
    while (rest.length > limit) {
      let cut = rest.lastIndexOf(' ', limit)
      if (cut <= 0) {
        cut = limit
      }
      push(rest.slice(0, cut))
      rest = rest.slice(cut).trim()
    }
    push(rest)
  }
  // All SENTENCE_END chars are literal inside a character class.
  const sentenceRe = new RegExp(
    `[^${SENTENCE_END}]+[${SENTENCE_END}]+|[^${SENTENCE_END}]+`,
    'g',
  )
  for (const line of String(text).split('\n')) {
    for (const sentence of line.match(sentenceRe) ?? []) {
      wrap(sentence)
    }
  }
  return chunks
}

/**
 * Text-to-speech via the Web Speech API (no backend needed).
 *
 * Owns the system voice list (+ onvoiceschanged setup/teardown), voice
 * resolution, utterance configuration, spoken status updates, answer
 * reading, and the speech live-region note.
 */
export function useSpeech({ prefs, isDisposed }) {
  const { locale, voicePrefs, currentVoice, clampRate, clampPitch, t } = prefs

  const speechSupported =
    typeof window !== 'undefined' &&
    'speechSynthesis' in window &&
    'SpeechSynthesisUtterance' in window
  const isSpeaking = ref(false)
  const speechNote = ref('')
  // Run counter: readAnswerAloud() bumps it per call so chunk callbacks from
  // a superseded (cancelled) queue are ignored.
  let speechRun = 0

  // System voices for the speech picker. Browsers load these
  // asynchronously, so the list refreshes via onvoiceschanged.
  const availableVoices = ref([])
  function refreshVoices() {
    if (!speechSupported || isDisposed()) {
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
  // Strict variant with NO fallback: Woman/Man resolution uses this so a
  // mismatched-language voice can never override the utterance language.
  const strictMatchingVoices = computed(() => {
    const prefix = (VOICE_LANG[locale.value] ?? 'en-US').split('-')[0].toLowerCase()
    return availableVoices.value.filter((voice) =>
      (voice.lang ?? '').toLowerCase().startsWith(prefix),
    )
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
  // hints within same-language voices only and resolves to null when nothing
  // matches, letting the browser pick a voice for the utterance language.
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
        strictMatchingVoices.value.find(
          (voice) => guessVoiceGender(voice) === choice,
        ) ?? null
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
    if (!isDisposed()) {
      speechNote.value = text
    }
  }

  function cancelSpeech() {
    if (speechSupported) {
      window.speechSynthesis.cancel()
    }
    if (!isDisposed()) {
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

  function readAnswerAloud(text) {
    if (!speechSupported || !text) {
      return
    }
    // One utterance per chunk: Chrome silently stops single utterances
    // longer than ~15 s with some voices.
    const chunks = splitForSpeech(text)
    if (chunks.length === 0) {
      return
    }
    const run = ++speechRun
    cancelSpeech()
    isSpeaking.value = true
    announceSpeech(t('srReading'))
    chunks.forEach((chunk, index) => {
      const utterance = new SpeechSynthesisUtterance(chunk)
      configureUtterance(utterance)
      const isLast = index === chunks.length - 1
      // Programmatic cancels set isSpeaking false synchronously first, so a
      // still-true flag here means a genuine end or error worth announcing.
      // Only the last chunk's end completes the run; the run guard drops
      // callbacks from a queue superseded by a newer read.
      utterance.onend = () => {
        if (!isLast || isDisposed() || run !== speechRun || !isSpeaking.value) {
          return
        }
        isSpeaking.value = false
        speechNote.value = t('srDone')
      }
      utterance.onerror = () => {
        if (isDisposed() || run !== speechRun || !isSpeaking.value) {
          return
        }
        isSpeaking.value = false
        speechNote.value = t('srInterrupted')
      }
      window.speechSynthesis.speak(utterance)
    })
  }

  // Short spoken status updates ("Photo ready", "Found 3 objects").
  // Uses the same synthesis queue as the answer so Stop cancels either one.
  // When TTS speaks, the sr-only live region is deliberately NOT updated:
  // screen-reader users would otherwise hear the message twice (SR + TTS).
  // When announcements are off or unsupported, only the live region updates.
  function speakStatus(text) {
    if (!text || isDisposed()) {
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
      if (!isDisposed() && isSpeaking.value) {
        isSpeaking.value = false
      }
    }
    utterance.onerror = () => {
      if (!isDisposed() && isSpeaking.value) {
        isSpeaking.value = false
      }
    }
    isSpeaking.value = true
    try {
      window.speechSynthesis.speak(utterance)
    } catch {
      if (!isDisposed()) {
        isSpeaking.value = false
      }
    }
  }

  // Voice-preferences preview: speaks a sample with the current rate and
  // voice even when spoken announcements are turned off.
  function previewVoice() {
    if (!speechSupported || isSpeaking.value || isDisposed()) {
      return
    }
    cancelSpeech()
    const utterance = new SpeechSynthesisUtterance(t('voicePreviewSample'))
    configureUtterance(utterance)
    utterance.onend = () => {
      if (!isDisposed() && isSpeaking.value) {
        isSpeaking.value = false
      }
    }
    utterance.onerror = () => {
      if (!isDisposed() && isSpeaking.value) {
        isSpeaking.value = false
      }
    }
    isSpeaking.value = true
    announceSpeech(t('srReading'))
    try {
      window.speechSynthesis.speak(utterance)
    } catch {
      if (!isDisposed()) {
        isSpeaking.value = false
      }
    }
  }

  onMounted(() => {
    refreshVoices()
    if (speechSupported) {
      try {
        window.speechSynthesis.onvoiceschanged = refreshVoices
      } catch {
        // Voice list stays as initially loaded.
      }
    }
  })

  onBeforeUnmount(() => {
    if (speechSupported) {
      try {
        if (window.speechSynthesis.onvoiceschanged === refreshVoices) {
          window.speechSynthesis.onvoiceschanged = null
        }
      } catch {
        // Already torn down.
      }
    }
    cancelSpeech()
  })

  return {
    speechSupported,
    isSpeaking,
    speechNote,
    voiceOptions,
    speakStatus,
    readAnswerAloud,
    previewVoice,
    cancelSpeech,
    stopSpeaking,
  }
}
