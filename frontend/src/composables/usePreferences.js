import { computed, ref, watch } from 'vue'
import { STRINGS, translate } from '../i18n.js'

/**
 * Persisted UI preferences: locale (+ <html lang>), theme (+ data-theme),
 * per-language voice preferences, and the t() translate helper.
 */
export function usePreferences() {
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

  // App mode: Quick (ask first, then point) or the step-by-step wizard.
  // Persisted like the theme; Quick is the default.
  const MODE_KEY = 'visionspark-mode'
  function loadMode() {
    try {
      const stored = localStorage.getItem(MODE_KEY)
      if (stored === 'quick' || stored === 'steps') {
        return stored
      }
    } catch {
      // Private mode or blocked storage: fall through to Quick.
    }
    return 'quick'
  }
  const mode = ref(loadMode())
  watch(mode, (value) => {
    try {
      localStorage.setItem(MODE_KEY, value)
    } catch {
      // Storage unavailable: the choice still applies for this visit.
    }
  })

  return { locale, theme, mode, voicePrefs, currentVoice, clampRate, clampPitch, t }
}
