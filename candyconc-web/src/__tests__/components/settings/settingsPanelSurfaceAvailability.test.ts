import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SettingsPanel from '@/components/settings/SettingsPanel.vue'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'
import type { ProductCapabilityContract } from '@/api/client'

const getMcpTools = vi.fn()

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: vi.fn(),
    getAuthSession: vi.fn(),
    getMcpTools: (...args: unknown[]) => getMcpTools(...args),
  }
})

const stubs = {
  SlideOver: { props: ['modelValue', 'title'], template: '<div class="slide-over"><h2 class="slide-over-title">{{ title }}</h2><slot /><slot name="footer" /></div>' },
  SettingsGeneral: { template: '<div>GENERAL</div>' },
  SettingsAppearance: { template: '<div>APPEARANCE</div>' },
  CorpusManagerContent: { template: '<div>CORPORA</div>' },
  EmbeddingsManager: { template: '<div>EMBEDDINGS</div>' },
  SystemInfo: { template: '<div>SYSTEM</div>' },
}

function capability(id: string, role: 'user' | 'admin' = 'user') {
  const descriptor = {
    path: `/api/v1/${id.replace('.', '/')}`,
    methods: ['GET'] as Array<'GET'>,
    mutates: false,
    requires_corpus_features: [],
    access: role,
    required_role: role,
    transport: 'http' as const,
    route_class: role === 'admin' ? 'admin_surface' as const : 'product_surface' as const,
  }
  const operations = id === 'settings.preferences'
    ? [{
        id: 'settings.preferences.read',
        capability_id: id,
        label: 'Einstellungen laden',
        description: 'Persistierte Einstellungen lesen.',
        route: descriptor,
        effects: ['read'] as Array<'read'>,
        handler_key: 'settings_preferences_read',
        copilot_tools: [],
        surface_slot: 'settings.preferences.read',
        priority: 10,
      }]
    : []
  return {
    id,
    title: id,
    area: id.split('.')[0],
    maturity: 'guarded',
    visibility: 'first_class_ui',
    backend_routes: [],
    backend_route_descriptors: [descriptor],
    operations,
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
  }
}

function contract(): ProductCapabilityContract {
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
      capability('settings.preferences'),
      capability('admin.system_operations', 'admin'),
      capability('corpus.catalogue'),
      capability('settings.embedding_management'),
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

describe('SettingsPanel surface availability', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    getMcpTools.mockResolvedValue({ tools: [] })
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract()
    productCapabilities.status = 'ready'
    seedUserSession()
  })

  it('keeps role-blocked settings surfaces visible but disabled with a reason', async () => {
    const uiStore = useUiStore()
    const wrapper = mount(SettingsPanel, {
      props: { modelValue: true },
      global: { stubs },
    })

    const systemTab = wrapper.findAll('button.settings-tab').find((button) => button.text().includes('System'))
    expect(systemTab).toBeTruthy()
    expect(systemTab?.attributes('aria-disabled')).toBe('true')
    expect(systemTab?.attributes('title')).toContain('Rolle Admin')

    await systemTab?.trigger('click')

    expect(wrapper.text()).not.toContain('SYSTEM')
    expect(uiStore.toasts.at(-1)).toMatchObject({
      type: 'warning',
      message: expect.stringContaining('Rolle Admin'),
    })
  })

  it('renders the active settings tab without product-operation diagnostics', () => {
    const wrapper = mount(SettingsPanel, {
      props: { modelValue: true },
      global: { stubs },
    })

    expect(wrapper.text()).not.toContain('Einstellungs-Operationen')
    expect(wrapper.text()).not.toContain('settings.preferences.read')
    expect(wrapper.text()).toContain('GENERAL')
  })

  it('keeps appearance settings visible without preference operation diagnostics', async () => {
    const uiStore = useUiStore()
    uiStore.setSettingsTab('appearance')

    const wrapper = mount(SettingsPanel, {
      props: { modelValue: true },
      global: { stubs },
    })

    expect(wrapper.text()).not.toContain('Einstellungs-Operationen')
    expect(wrapper.text()).not.toContain('settings.preferences.read')
    expect(wrapper.text()).toContain('APPEARANCE')
  })

  it('names the corpus-management surface honestly and omits the unrelated preferences reset', () => {
    const uiStore = useUiStore()
    uiStore.openCorpusManager()

    const wrapper = mount(SettingsPanel, {
      props: { modelValue: true },
      global: { stubs },
    })

    expect(wrapper.find('.slide-over-title').text()).toBe('Korpusverwaltung')
    expect(wrapper.text()).toContain('CORPORA')
    expect(wrapper.text()).not.toContain('Einstellungen zurücksetzen')
  })
})
