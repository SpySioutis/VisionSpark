import { onBeforeUnmount, onMounted, ref } from 'vue'

/**
 * Backend reachability, checked automatically on load and then polled.
 * There is no manual health check in the UI.
 */
export function useBackendStatus({ backendUrl, isDisposed }) {
  // 'idle' | 'success' | 'error'
  const status = ref('idle')
  let statusTimer = null
  let statusInFlight = false

  async function refreshBackendStatus() {
    if (isDisposed() || statusInFlight) {
      return
    }
    statusInFlight = true
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 5000)
    try {
      const response = await fetch(`${backendUrl}/health`, {
        signal: controller.signal,
      })
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }
      const data = await response.json()
      if (!isDisposed()) {
        status.value = data?.status === 'ok' ? 'success' : 'error'
      }
    } catch {
      // Includes aborts after the timeout below.
      if (!isDisposed()) {
        status.value = 'error'
      }
    } finally {
      clearTimeout(timeoutId)
      statusInFlight = false
    }
  }

  function onVisibilityChange() {
    // Hidden tabs skip polling; re-check immediately when visible again.
    if (!document.hidden) {
      refreshBackendStatus()
    }
  }

  onMounted(() => {
    refreshBackendStatus()
    statusTimer = setInterval(() => {
      if (!document.hidden) {
        refreshBackendStatus()
      }
    }, 30000)
    document.addEventListener('visibilitychange', onVisibilityChange)
  })

  onBeforeUnmount(() => {
    if (statusTimer !== null) {
      clearInterval(statusTimer)
      statusTimer = null
    }
    document.removeEventListener('visibilitychange', onVisibilityChange)
  })

  return { status }
}
