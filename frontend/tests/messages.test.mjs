import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import { asMsg, httpError, networkError } from '../src/lib/messages.js'

describe('httpError', () => {
  it('maps statuses to message descriptors', () => {
    assert.deepEqual(httpError(413), { key: 'errTooBig' })
    assert.deepEqual(httpError(415), { key: 'errFileType' })
    assert.deepEqual(httpError(400), { key: 'errRequest' })
    assert.deepEqual(httpError(422), { key: 'errRequest' })
    assert.deepEqual(httpError(429), { key: 'errBusy' })
    assert.deepEqual(httpError(503), { key: 'errNotConfigured' })
    assert.deepEqual(httpError(502), { key: 'errProvider' })
    assert.deepEqual(httpError(504), { key: 'errTimeout' })
    assert.deepEqual(httpError(500), { key: 'errServer', params: { status: 500 } })
  })
})

describe('networkError and asMsg', () => {
  it('normalize failures into stored messages', () => {
    assert.deepEqual(networkError(), { key: 'errNetwork' })
    assert.deepEqual(asMsg({ key: 'errBusy' }), { key: 'errBusy' })
    assert.deepEqual(asMsg(new Error('boom')), { text: 'boom' })
    assert.deepEqual(asMsg(42), { key: 'unknownErr' })
  })
})
