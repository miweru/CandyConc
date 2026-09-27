import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SettingsGeneral from '@/components/settings/SettingsGeneral.vue'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useOnboardingStore } from '@/stores/onboarding'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'
import type { ProductCapabilityContract } from '@/api/client'

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: vi.fn(),
    getCorpora: vi.fn(),
    updatePrefs: vi.fn(),
  }
})

function capability(id: string, routes: Array<{ path: string; method: string }>) {
  const descriptors = routes.map((route) => ({
    path: route.path,
    methods: [route.method],
    mutates: route.method !== 'GET',
    requires_corpus_features: [],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  }))
  const operations = id === 'settings.preferences'
    ? [
        { id: 'settings.preferences.read', path: '/api/v1/prefs', method: 'GET', label: 'Einstellungen laden' },
        { id: 'settings.preferences.update', path: '/api/v1/prefs/update', method: 'POST', label: 'Einstellungen speichern' },
      ].flatMap((spec) => {
        const descriptor = descriptors.find((route) =>
          route.path === spec.path &&
          route.methods.map((method) => method.toUpperCase()).includes(spec.method)
        )
        if (!descriptor) return []
        return [{
          id: spec.id,
          capability_id: id,
          label: spec.label,
          description: '',
          route: { ...descriptor, methods: [spec.method] },
          effects: spec.method === 'GET' ? ['read'] : ['write'],
          handler_key: spec.id,
          surface_slot: spec.id,
          priority: 100,
        }]
      })
    : []
  return {
    id,
    title: id,
    area: id.split('.')[0],
    maturity: 'stable',
    visibility: 'first_class_ui',
    backend_routes: routes.map((route) => route.path),
    backend_route_descriptors: descriptors,
    operations,
    frontend_evidence: [{
      path: 'candyconc-web/src/components/settings/SettingsGeneral.vue',
      contains: 'settings.preferences',
    }],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
  }
}

function contractWithoutBookmarks(): ProductCapabilityContract {
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [
      capability('query.kwic', [
        { path: '/api/v1/query', method: 'GET' },
      ]),
      capability('settings.preferences', [
        { path: '/api/v1/prefs', method: 'GET' },
        { path: '/api/v1/prefs/update', method: 'POST' },
      ]),
      {
        ...capability('admin.security_observability', [
          { path: '/api/v1/metrics', method: 'GET' },
          { path: '/api/v1/system/info', method: 'GET' },
        ]),
        visibility: 'expert_api',
        limits: [
          'Metrics are an admin observability surface and do not enable an external telemetry exporter by themselves.',
        ],
      },
    ],
  }
}

function seedUserSession() {
  const session = useSessionStore()
  session.status = 'ready'
  session.session = {
    schema_version: 'auth-session-v1',
    authenticated: true,
    token_present: true,
    username: 'analyst',
    role: 'user',
    effective_role: 'user',
    rbac_enabled: true,
    security_mode: 'release',
    release_mode: true,
    unsafe_token_transport: false,
    dev_token_available: false,
    can_access_all_roles: false,
  }
}

describe('SettingsGeneral capability gates', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contractWithoutBookmarks()
    productCapabilities.status = 'ready'
    const corpusCapabilities = useCorpusCapabilitiesStore()
    corpusCapabilities.loaded = true
    seedUserSession()
  })

  it('keeps general preferences gated by settings.preferences, not bookmarks', () => {
    const wrapper = mount(SettingsGeneral)

    expect(wrapper.find('#language').exists()).toBe(true)
    expect(wrapper.find('#language').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('#defaultCorpus').attributes('disabled')).toBeUndefined()

    // The bookmark autosave switch had no reader (every bookmark change is
    // written at once) and was removed, so no bookmark gate remains here.
    expect(wrapper.find('#autoSaveBookmarks').exists()).toBe(false)
    expect(wrapper.find('#confirmDelete').attributes('disabled')).toBeUndefined()
  })

  it('shows the local privacy posture without usage-analytics claims', () => {
    const wrapper = mount(SettingsGeneral)

    expect(wrapper.text()).toContain('Datenschutz & Betrieb')
    expect(wrapper.text()).toContain('Lokale Verarbeitung')
    expect(wrapper.text()).toContain('keine externe Telemetrie')
    expect(wrapper.text()).toContain('CANDYCONC_ENABLE_LLM_TRACE')
    expect(wrapper.text()).toContain('external telemetry exporter')
    expect(wrapper.text()).not.toContain('analytics.jsonl')
  })

  it('restarts the capability-aware product tour from settings', async () => {
    vi.useFakeTimers()
    const uiStore = useUiStore()
    const onboardingStore = useOnboardingStore()
    uiStore.openSettings()
    onboardingStore.complete()
    const wrapper = mount(SettingsGeneral)

    await wrapper.findAll('button').find((button) => button.text().includes('Tour erneut starten'))?.trigger('click')
    vi.advanceTimersByTime(100)

    expect(uiStore.settingsOpen).toBe(false)
    expect(onboardingStore.hasCompletedOnboarding).toBe(false)
    expect(onboardingStore.isActive).toBe(true)
    expect(onboardingStore.activeSteps.map((step) => step.id)).toContain('search')
    vi.useRealTimers()
  })
})
