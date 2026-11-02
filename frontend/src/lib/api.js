// Backend base URL shared by all API calls.
// Development keeps using localhost:8000; production builds call their own
// origin; VITE_BACKEND_URL=/ forces the same origin.
// The frontend only calls our backend, never api.meta.ai.
const raw = import.meta.env.VITE_BACKEND_URL
export const backendUrl = (raw ?? (import.meta.env.DEV ? 'http://localhost:8000' : '')).replace(/\/+$/, '')
