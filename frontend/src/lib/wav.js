// Pure WAV encoding for voice questions (no DOM, no Web Audio): mono
// float samples at 16 kHz become 16-bit PCM WAV bytes for /api/transcribe.

export const WAV_SAMPLE_RATE = 16000

/**
 * Downmix multi-channel input to mono and resample to 16 kHz by averaging
 * the input samples that fall into each output sample's 1/16000 s window.
 * channels: one Float32Array per channel, all the same length.
 */
export function resampleToMono16k(channels, inputRate) {
  const inputLength = channels[0]?.length ?? 0
  const count = channels.length
  const outLength = Math.floor((inputLength * WAV_SAMPLE_RATE) / inputRate)
  const out = new Float32Array(outLength)
  for (let i = 0; i < outLength; i += 1) {
    const from = Math.floor((i * inputRate) / WAV_SAMPLE_RATE)
    const to = Math.max(from + 1, Math.floor(((i + 1) * inputRate) / WAV_SAMPLE_RATE))
    const end = Math.min(to, inputLength)
    let sum = 0
    for (let c = 0; c < count; c += 1) {
      const ch = channels[c]
      for (let j = from; j < end; j += 1) {
        sum += ch[j]
      }
    }
    const n = (end - from) * count
    out[i] = n > 0 ? sum / n : 0
  }
  return out
}

/**
 * Encode mono float samples (-1..1) at 16 kHz as 16-bit PCM WAV.
 * Returns a Uint8Array: a 44-byte little-endian header plus the data.
 */
export function encodeWav(mono) {
  const dataSize = mono.length * 2
  const buffer = new ArrayBuffer(44 + dataSize)
  const view = new DataView(buffer)
  const writeAscii = (offset, text) => {
    for (let i = 0; i < text.length; i += 1) {
      view.setUint8(offset + i, text.charCodeAt(i))
    }
  }
  writeAscii(0, 'RIFF')
  view.setUint32(4, 36 + dataSize, true)
  writeAscii(8, 'WAVE')
  writeAscii(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // mono
  view.setUint32(24, WAV_SAMPLE_RATE, true)
  view.setUint32(28, WAV_SAMPLE_RATE * 2, true) // byte rate
  view.setUint16(32, 2, true) // block align
  view.setUint16(34, 16, true) // bits per sample
  writeAscii(36, 'data')
  view.setUint32(40, dataSize, true)
  for (let i = 0; i < mono.length; i += 1) {
    const clamped = Math.max(-1, Math.min(1, mono[i]))
    view.setInt16(44 + i * 2, Math.round(clamped * 0x7fff), true)
  }
  return new Uint8Array(buffer)
}
