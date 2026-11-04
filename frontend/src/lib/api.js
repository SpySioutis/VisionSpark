// Backend base URL shared by all API calls.
// An explicit VITE_BACKEND_URL always wins (VITE_BACKEND_URL=/ forces the
// same origin). Otherwise an HTTPS page always uses the same origin (Vite
// proxies it to the backend; calling plain HTTP from HTTPS would be mixed
// content), while a plain-HTTP page uses localhost:8000 on localhost and
// the same origin anywhere else (phone on the LAN).
// The frontend only calls our backend, never api.meta.ai.
const raw = import.meta.env.VITE_BACKEND_URL

function defaultBackendUrl() {
  if (!import.meta.env.DEV) return ''
  if (typeof window === 'undefined') return 'http://localhost:8000'
  if (window.location.protocol === 'https:') return ''
  const host = window.location.hostname
  if (host === '' || host === 'localhost' || host === '127.0.0.1' || host === '::1') {
    return 'http://localhost:8000'
  }
  return ''
}

export const backendUrl = (raw ?? defaultBackendUrl()).replace(/\/+$/, '')
