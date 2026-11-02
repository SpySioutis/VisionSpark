import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import { encodeWav, resampleToMono16k } from '../src/lib/wav.js'

function ascii(view, offset, length) {
  let text = ''
  for (let i = 0; i < length; i += 1) {
    text += String.fromCharCode(view.getUint8(offset + i))
  }
  return text
}

describe('encodeWav', () => {
  it('writes a 44-byte little-endian PCM header', () => {
    const wav = encodeWav(new Float32Array(100))
    assert.equal(wav.length, 44 + 200)
    const view = new DataView(wav.buffer)
    assert.equal(ascii(view, 0, 4), 'RIFF')
    assert.equal(view.getUint32(4, true), 36 + 200)
    assert.equal(ascii(view, 8, 4), 'WAVE')
    assert.equal(ascii(view, 12, 4), 'fmt ')
    assert.equal(view.getUint32(16, true), 16)
    assert.equal(view.getUint16(20, true), 1)
    assert.equal(view.getUint16(22, true), 1)
    assert.equal(view.getUint32(24, true), 16000)
    assert.equal(view.getUint32(28, true), 32000)
    assert.equal(view.getUint16(32, true), 2)
    assert.equal(view.getUint16(34, true), 16)
    assert.equal(ascii(view, 36, 4), 'data')
    assert.equal(view.getUint32(40, true), 200)
  })

  it('clamps to [-1, 1] and scales by 0x7fff', () => {
    const wav = encodeWav(new Float32Array([1.5, -2, 0.5, -0.5, 0]))
    const view = new DataView(wav.buffer)
    const samples = [0, 1, 2, 3, 4].map((i) => view.getInt16(44 + i * 2, true))
    assert.deepEqual(samples, [32767, -32767, 16384, -16383, 0])
  })
})

describe('resampleToMono16k', () => {
  it('resamples to 16 kHz output length', () => {
    assert.equal(resampleToMono16k([new Float32Array(48000)], 48000).length, 16000)
    assert.equal(resampleToMono16k([new Float32Array(44100)], 44100).length, 16000)
    assert.equal(resampleToMono16k([new Float32Array(16000)], 16000).length, 16000)
  })

  it('preserves a constant signal and downmixes channels', () => {
    const ones = resampleToMono16k([new Float32Array(48000).fill(1)], 48000)
    assert.equal(ones.length, 16000)
    for (let i = 0; i < ones.length; i += 1000) {
      assert.equal(ones[i], 1)
    }
    const mixed = resampleToMono16k(
      [new Float32Array(480).fill(1), new Float32Array(480).fill(0)],
      48000,
    )
    assert.equal(mixed.length, 160)
    for (let i = 0; i < mixed.length; i += 20) {
      assert.equal(mixed[i], 0.5)
    }
  })

  it('returns empty output for empty input', () => {
    assert.equal(resampleToMono16k([new Float32Array(0)], 48000).length, 0)
    assert.equal(resampleToMono16k([], 48000).length, 0)
  })
})
