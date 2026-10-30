// Locale parity check: every locale must define exactly the same keys as
// English, with identical {placeholders}, and every locale needs a voice
// tag (plus a model answer-language name for non-English locales).
// Run: npm run check-locales
import { ANSWER_LANG_NAME, LOCALES, STRINGS, VOICE_LANG } from './src/i18n.js'

let failures = 0
const fail = (message) => {
  failures += 1
  console.error(`FAIL: ${message}`)
}

const baseKeys = Object.keys(STRINGS.en).sort()
const placeholder = (text) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(',')

// LOCALES codes must match STRINGS keys exactly.
const localeCodes = LOCALES.map((l) => l.code).sort()
if (JSON.stringify(localeCodes) !== JSON.stringify(Object.keys(STRINGS).sort())) {
  fail(`LOCALES codes [${localeCodes}] do not match STRINGS keys [${Object.keys(STRINGS).sort()}]`)
}

for (const { code } of LOCALES) {
  const keys = Object.keys(STRINGS[code]).sort()
  for (const missing of baseKeys.filter((k) => !keys.includes(k))) {
    fail(`${code}: missing key "${missing}"`)
  }
  for (const extra of keys.filter((k) => !baseKeys.includes(k))) {
    fail(`${code}: extra key "${extra}"`)
  }
  for (const key of baseKeys) {
    if (typeof STRINGS[code][key] !== 'string' || STRINGS[code][key].length === 0) {
      fail(`${code}.${key}: empty or not a string`)
    } else if (placeholder(STRINGS[code][key]) !== placeholder(STRINGS.en[key])) {
      fail(`${code}.${key}: placeholders differ from English`)
    }
  }
  if (!VOICE_LANG[code]) {
    fail(`${code}: missing VOICE_LANG entry`)
  }
  if (code !== 'en' && !ANSWER_LANG_NAME[code]) {
    fail(`${code}: missing ANSWER_LANG_NAME entry`)
  }
}

if (failures > 0) {
  console.error(`${failures} locale check(s) failed`)
  process.exit(1)
}
console.log(`OK: ${localeCodes.length} locales, ${baseKeys.length} keys each`)
