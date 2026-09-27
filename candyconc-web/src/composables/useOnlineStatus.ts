/**
 * useOnlineStatus - Online/Offline detection with backend health checks
 *
 * Provides reactive state for:
 * - Browser online/offline status
 * - Backend reachability
 * - Copilot availability
 */

import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ensureDevToken, withAuthHeadersReady } from '@/api/auth'
import { acceptLanguageHeader } from '@/i18n/locale'
import { t } from '@/i18n'

export type BackendReadiness = 'checking' | 'ready' | 'auth_required' | 'contract_unavailable' | 'offline'

interface BackendReadinessProbe {
  readiness: Exclude<BackendReadiness, 'checking'>
  reachable: boolean
  ready: boolean
}

export interface OnlineStatusOptions {
  /** Health check interval in ms (default: 30000) */
  healthCheckInterval?: number
  /** Health check timeout in ms (default: 5000) */
  healthCheckTimeout?: number
  /** Skip initial health check (default: false) */
  skipInitialCheck?: boolean
}

export function useOnlineStatus(options: OnlineStatusOptions = {}) {
  const {
    healthCheckInterval = 30000,
    healthCheckTimeout = 5000,
    skipInitialCheck = false,
  } = options

  const isOnline = ref(typeof navigator !== 'undefined' ? navigator.onLine : true)
  const backendReadiness = ref<BackendReadiness>('checking')
  const isBackendReachable = computed(() => backendReadiness.value !== 'offline')
  const isBackendReady = computed(() => backendReadiness.value === 'ready')
  const lastCheckTimestamp = ref<number | null>(null)
  const isChecking = ref(false)

  let checkIntervalId: ReturnType<typeof setInterval> | null = null

  // Browser online/offline event handlers
  function handleOnline() {
    isOnline.value = true
    // Immediately check backend when coming online
    checkBackend()
  }

  function handleOffline() {
    isOnline.value = false
    backendReadiness.value = 'offline'
  }

  // Backend health check
  async function checkBackend(): Promise<boolean> {
    if (isChecking.value) return isBackendReady.value

    isChecking.value = true
    try {
      const probe = await probeBackendReadiness(healthCheckTimeout)
      backendReadiness.value = probe.readiness
      lastCheckTimestamp.value = Date.now()
      return probe.ready
    } catch {
      backendReadiness.value = 'offline'
      lastCheckTimestamp.value = Date.now()
      return false
    } finally {
      isChecking.value = false
    }
  }

  // Force a health check
  function forceCheck() {
    return checkBackend()
  }

  // Computed: is copilot available?
  const copilotAvailable = computed(() => isOnline.value && isBackendReady.value)

  // Computed: status message for UI
  const statusMessage = computed(() => {
    if (!isOnline.value) {
      return t('layout.online.offline')
    }
    if (backendReadiness.value === 'offline') {
      return t('layout.online.unreachable')
    }
    if (backendReadiness.value === 'auth_required') {
      return t('layout.online.authMissing')
    }
    if (backendReadiness.value === 'contract_unavailable') {
      return t('layout.online.contractMissing')
    }
    if (backendReadiness.value === 'checking') {
      return t('layout.online.checking')
    }
    return t('layout.online.online')
  })

  // Setup and cleanup
  onMounted(() => {
    // Add event listeners
    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)

    // Start periodic health checks
    if (!skipInitialCheck) {
      checkBackend()
    }
    checkIntervalId = setInterval(checkBackend, healthCheckInterval)
  })

  onUnmounted(() => {
    // Remove event listeners
    window.removeEventListener('online', handleOnline)
    window.removeEventListener('offline', handleOffline)

    // Clear interval
    if (checkIntervalId) {
      clearInterval(checkIntervalId)
      checkIntervalId = null
    }
  })

  return {
    isOnline,
    isBackendReachable,
    isBackendReady,
    backendReadiness,
    copilotAvailable,
    statusMessage,
    lastCheckTimestamp,
    isChecking,
    forceCheck,
  }
}

// Singleton instance for global use
let globalInstance: ReturnType<typeof useOnlineStatus> | null = null

export function useGlobalOnlineStatus() {
  if (!globalInstance) {
    globalInstance = useOnlineStatus()
  }
  return globalInstance
}

async function fetchWithTimeout(
  path: string,
  timeoutMs: number,
  init?: RequestInit,
): Promise<Response> {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(path, {
      ...init,
      signal: controller.signal,
    })
  } finally {
    clearTimeout(timeoutId)
  }
}

export async function probeBackendReadiness(
  timeoutMs = 5000,
): Promise<BackendReadinessProbe> {
  const health = await fetchWithTimeout('/api/v1/health', timeoutMs, {
    method: 'GET',
    headers: { 'Accept-Language': acceptLanguageHeader() },
  })
  if (!health.ok) {
    return { readiness: 'offline', reachable: false, ready: false }
  }

  await ensureDevToken().catch(() => undefined)
  const headers = await withAuthHeadersReady({ Accept: 'application/json' })
  const session = await fetchWithTimeout('/api/v1/auth/session', timeoutMs, {
    method: 'GET',
    headers,
  })
  if (!session.ok) {
    return { readiness: 'contract_unavailable', reachable: true, ready: false }
  }

  const capabilities = await fetchWithTimeout('/api/v1/capabilities', timeoutMs, {
    method: 'GET',
    headers,
  })
  if (capabilities.ok) {
    return { readiness: 'ready', reachable: true, ready: true }
  }
  if (capabilities.status === 401 || capabilities.status === 403) {
    return { readiness: 'auth_required', reachable: true, ready: false }
  }
  return { readiness: 'contract_unavailable', reachable: true, ready: false }
}
