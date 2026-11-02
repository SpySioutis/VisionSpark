// Failure descriptors for API calls: pure (no Vue), shared by both modes.
// Backend detail strings are English-only, so HTTP failures map to localized
// message descriptors instead of showing body.detail.
export function httpError(status) {
  if (status === 413) {
    return { key: 'errTooBig' }
  }
  if (status === 415) {
    return { key: 'errFileType' }
  }
  if (status === 400 || status === 422) {
    return { key: 'errRequest' }
  }
  if (status === 429) {
    return { key: 'errBusy' }
  }
  if (status === 503) {
    return { key: 'errNotConfigured' }
  }
  if (status === 502) {
    return { key: 'errProvider' }
  }
  if (status === 504) {
    return { key: 'errTimeout' }
  }
  return { key: 'errServer', params: { status } }
}

export function networkError() {
  return { key: 'errNetwork' }
}

// Normalize a caught failure into a stored message: our own throws are
// already descriptors, genuine Errors keep their text, anything else is
// an unknown error.
export function asMsg(error) {
  if (error && typeof error === 'object' && 'key' in error) {
    return error
  }
  return error instanceof Error ? { text: error.message } : { key: 'unknownErr' }
}
