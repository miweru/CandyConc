import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  getAuthSession,
  loginUser,
  logoutUser,
  type AuthSession,
  type ProductCapability,
  type ProductCapabilityBackendRouteDescriptor,
} from '@/api/client'
import { clearAuthToken, ensureDevToken, getAuthToken, setAuthToken } from '@/api/auth'
import { t } from '@/i18n'

export type SessionLoadStatus = 'idle' | 'loading' | 'ready' | 'error'
export type SessionMutationStatus = 'idle' | 'loading' | 'success' | 'error'

export const SESSION_OPERATIONS = {
  read: 'platform.session.read',
  login: 'platform.session.login',
  logout: 'platform.session.logout',
} as const

const ROLE_RANK: Record<string, number> = {
  user: 1,
  annotator: 1,
  manager: 2,
  admin: 3,
}

interface MinimalRouteDescriptor {
  path: string
  methods?: string[] | null
  mutates?: boolean | null
  transport?: string | null
  access?: string | null
  required_role?: string | null
}

function roleForAccess(access?: string | null): string | null {
  if (!access || access === 'public') return null
  if (access === 'manager') return 'manager'
  if (access === 'admin') return 'admin'
  return 'user'
}

function routeRequiredRole(route: MinimalRouteDescriptor): string | null {
  return route.required_role ?? roleForAccess(route.access)
}

function backendRouteDescriptors(capability: ProductCapability | undefined): MinimalRouteDescriptor[] {
  if (!capability) return []
  if (capability.backend_route_descriptors?.length) return capability.backend_route_descriptors
  return (capability.backend_routes ?? []).map((route) => {
    if (typeof route === 'string') return { path: route }
    return route as ProductCapabilityBackendRouteDescriptor
  })
}

function roleLabel(role: string | null | undefined): string {
  if (!role) return t('layout.session.noRole')
  if (role === 'admin') return 'Admin'
  if (role === 'annotator') return 'Annotator'
  if (role === 'manager') return 'Manager'
  if (role === 'user') return 'User'
  return role
}

function needsLocalDevTokenRefresh(nextSession: AuthSession): boolean {
  return (
    nextSession.token_present
    && !nextSession.authenticated
    && !nextSession.rbac_enabled
    && nextSession.dev_token_available
    && !nextSession.release_mode
  )
}

export const useSessionStore = defineStore('session', () => {
  const session = ref<AuthSession | null>(null)
  const status = ref<SessionLoadStatus>('idle')
  const loginStatus = ref<SessionMutationStatus>('idle')
  const logoutStatus = ref<SessionMutationStatus>('idle')
  const error = ref<string | null>(null)
  const loginError = ref<string | null>(null)
  let loadPromise: Promise<AuthSession | null> | null = null

  const effectiveRole = computed(() => session.value?.effective_role ?? session.value?.role ?? null)
  const isAuthoritative = computed(() => status.value === 'ready' && Boolean(session.value))
  const isAuthenticated = computed(() => Boolean(session.value?.authenticated))
  const isLocalDevAllRoles = computed(() => Boolean(session.value?.can_access_all_roles))
  const hasToken = computed(() => Boolean(session.value?.token_present) || Boolean(getAuthToken()))
  const hasInvalidToken = computed(() =>
    Boolean(session.value?.token_present && !session.value.authenticated && session.value.rbac_enabled)
  )
  const needsLogin = computed(() =>
    Boolean(isAuthoritative.value && session.value?.rbac_enabled && !session.value.authenticated)
  )
  const canLogout = computed(() => Boolean(isAuthenticated.value || hasToken.value))
  const username = computed(() => session.value?.username ?? null)
  const roleDisplay = computed(() => {
    if (isLocalDevAllRoles.value) return t('layout.session.localAdmin')
    return roleLabel(effectiveRole.value)
  })
  const statusLabel = computed(() => {
    if (status.value === 'loading' || status.value === 'idle') return t('layout.session.checking')
    if (status.value === 'error') return t('layout.session.uncheckable')
    if (isLocalDevAllRoles.value) return t('layout.session.localDev')
    if (isAuthenticated.value) return `${username.value ?? t('layout.session.signedIn')} · ${roleDisplay.value}`
    if (hasInvalidToken.value) return t('layout.session.tokenInvalid')
    return t('layout.session.signedOut')
  })

  async function load(force = false): Promise<AuthSession | null> {
    if (!force && session.value) return session.value
    if (!force && loadPromise) return loadPromise

    loadPromise = (async () => {
      status.value = 'loading'
      error.value = null
      try {
        const nextSession = await getAuthSession()
        if (needsLocalDevTokenRefresh(nextSession)) {
          // Dev tokens are process-local, so a backend restart invalidates a
          // token that may still exist in this browser tab.
          clearAuthToken()
          await ensureDevToken()
          session.value = await getAuthSession()
        } else {
          session.value = nextSession
        }
        status.value = 'ready'
        return session.value
      } catch (err) {
        error.value = err instanceof Error ? err.message : t('layout.session.loadFailed')
        status.value = 'error'
        return session.value
      } finally {
        loadPromise = null
      }
    })()

    return loadPromise
  }

  function canUseRequiredRole(requiredRole?: string | null): boolean {
    if (!requiredRole) return true
    if (!isAuthoritative.value) return false
    if (session.value?.can_access_all_roles) return true
    const currentRank = ROLE_RANK[effectiveRole.value ?? ''] ?? 0
    const requiredRank = ROLE_RANK[requiredRole] ?? 1
    return currentRank >= requiredRank
  }

  function canAccessRoute(route: MinimalRouteDescriptor): boolean {
    return canUseRequiredRole(routeRequiredRole(route))
  }

  function canAccessAnyRoute(
    capability: ProductCapability | undefined,
    predicate?: (route: MinimalRouteDescriptor) => boolean
  ): boolean {
    const routes = backendRouteDescriptors(capability)
    const selectedRoutes = predicate ? routes.filter(predicate) : routes
    if (predicate && selectedRoutes.length === 0) return false
    if (selectedRoutes.length === 0) return true
    return selectedRoutes.some(canAccessRoute)
  }

  function accessBlockReason(
    capability: ProductCapability | undefined,
    labelArg?: string,
    predicate?: (route: MinimalRouteDescriptor) => boolean
  ): string | null {
    if (canAccessAnyRoute(capability, predicate)) return null
    const label = labelArg ?? t('layout.session.thisFeature')
    if (status.value === 'loading' || status.value === 'idle') {
      return t('layout.session.waitingForSession', { label })
    }
    if (status.value === 'error') {
      return t('layout.session.sessionUncheckable', { label })
    }
    const routes = backendRouteDescriptors(capability)
    const selectedRoutes = predicate ? routes.filter(predicate) : routes
    const requiredRoles = Array.from(new Set(selectedRoutes.map(routeRequiredRole).filter(Boolean))) as string[]
    const required = requiredRoles.sort((a, b) => (ROLE_RANK[a] ?? 0) - (ROLE_RANK[b] ?? 0))[0] ?? 'user'
    return t('layout.session.roleRequired', { label, required: roleLabel(required), current: roleLabel(effectiveRole.value) })
  }

  async function login(username: string, password: string): Promise<AuthSession | null> {
    loginStatus.value = 'loading'
    loginError.value = null
    try {
      const result = await loginUser({ username, password })
      setAuthToken(result.token)
      const nextSession = await load(true)
      loginStatus.value = 'success'
      return nextSession
    } catch (err) {
      clearAuthToken()
      loginError.value = err instanceof Error ? err.message : t('layout.session.loginFailed')
      loginStatus.value = 'error'
      await load(true).catch(() => null)
      return session.value
    }
  }

  async function logout(): Promise<AuthSession | null> {
    logoutStatus.value = 'loading'
    try {
      if (getAuthToken()) {
        await logoutUser().catch(() => null)
      }
      clearAuthToken()
      const nextSession = await load(true)
      logoutStatus.value = 'success'
      return nextSession
    } catch (err) {
      error.value = err instanceof Error ? err.message : t('layout.session.logoutUnverified')
      logoutStatus.value = 'error'
      return session.value
    }
  }

  async function clearLocalSession(): Promise<AuthSession | null> {
    clearAuthToken()
    loginError.value = null
    return load(true)
  }

  return {
    session,
    status,
    loginStatus,
    logoutStatus,
    error,
    loginError,
    effectiveRole,
    isAuthoritative,
    isAuthenticated,
    isLocalDevAllRoles,
    hasToken,
    hasInvalidToken,
    needsLogin,
    canLogout,
    username,
    roleDisplay,
    statusLabel,
    load,
    login,
    logout,
    clearLocalSession,
    canUseRequiredRole,
    canAccessRoute,
    canAccessAnyRoute,
    accessBlockReason,
  }
})
