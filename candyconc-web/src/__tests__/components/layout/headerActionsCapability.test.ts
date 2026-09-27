import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import HeaderActions from '@/components/layout/HeaderActions.vue'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'
import type { ProductCapabilityContract } from '@/api/client'

const apiMocks = vi.hoisted(() => ({
  getProductCapabilities: vi.fn(),
  getAuthSession: vi.fn(),
  listCorpusImportJobs: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: (...args: unknown[]) => apiMocks.getProductCapabilities(...args),
    getAuthSession: (...args: unknown[]) => apiMocks.getAuthSession(...args),
    listCorpusImportJobs: (...args: unknown[]) => apiMocks.listCorpusImportJobs(...args),
  }
})

vi.mock('@/components/settings/SettingsPanel.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/export/ExportDialog.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/bookmarks/BookmarksPanel.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/workspace/WorkspaceManager.vue', () => ({ default: { template: '<div />' } }))

function capability(id: string, visibility: 'first_class_ui' | 'hidden_experimental' = 'first_class_ui') {
  return {
    id,
    title: id,
    area: id.split('.')[0],
    maturity: visibility === 'first_class_ui' ? 'guarded' : 'experimental',
    visibility,
    backend_routes: [],
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    limits: [],
  }
}

function adminRoute(path: string, methods: string[] = ['GET']) {
  return {
    path,
    methods,
    mutates: methods.some((method) => method !== 'GET'),
    requires_corpus_features: [],
    access: 'admin' as const,
    required_role: 'admin',
    transport: 'http' as const,
    route_class: 'admin_surface' as const,
  }
}

function userRoute(path: string, methods: string[] = ['GET']) {
  return {
    path,
    methods,
    mutates: methods.some((method) => method !== 'GET'),
    requires_corpus_features: [],
    access: 'user' as const,
    required_role: 'user',
    transport: 'http' as const,
    route_class: 'product_surface' as const,
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
      capability('research.subcorpora_docsets'),
      capability('research.analysis_presets', 'hidden_experimental'),
      capability('research.replay_export', 'hidden_experimental'),
      capability('settings.embedding_management', 'hidden_experimental'),
      capability('corpus.catalogue', 'hidden_experimental'),
      capability('corpus.import', 'hidden_experimental'),
    ],
  }
}

function adminSession() {
  const session = useSessionStore()
  session.status = 'ready'
  session.session = {
    schema_version: 'auth-session-v1',
    authenticated: true,
    token_present: true,
    username: 'admin',
    role: 'admin',
    effective_role: 'admin',
    rbac_enabled: true,
    security_mode: 'release',
    release_mode: true,
    unsafe_token_transport: false,
    dev_token_available: false,
    can_access_all_roles: false,
  }
}

function userSession() {
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

describe('HeaderActions capability gates', () => {
  let wrapper: VueWrapper | null = null

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    apiMocks.listCorpusImportJobs.mockResolvedValue([])
    apiMocks.getAuthSession.mockResolvedValue(null)
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract()
    productCapabilities.status = 'ready'
  })

  afterEach(async () => {
    await flushPromises()
    wrapper?.unmount()
    wrapper = null
  })

  it('binds workspace and settings buttons to their exact product capabilities', async () => {
    wrapper = mount(HeaderActions, {
      shallow: true,
      global: {
        stubs: {
          Dropdown: true,
          DropdownItem: true,
          FeatureTooltip: { template: '<div><slot /></div>' },
          SettingsPanel: true,
          ExportDialog: true,
          BookmarksPanel: true,
          WorkspaceManager: true,
        },
      },
    })
    await flushPromises()

    expect(wrapper.find('button[title="Subkorpora"]').exists()).toBe(true)
    expect(wrapper.find('button[title="Analysen"]').exists()).toBe(false)
    expect(wrapper.find('button[title="Läufe"]').exists()).toBe(false)
    expect(wrapper.find('button[title="Einstellungen"]').exists()).toBe(true)
    expect(wrapper.find('button[title="Exportieren"]').exists()).toBe(false)
  })

  // erprobung B18: the header button opens the saved subcorpora. The filter
  // drawer has its own button next to the search bar (App.vue workbar).
  it('opens the saved subcorpora from the header, not the filter drawer', async () => {
    const uiStore = useUiStore()
    wrapper = mount(HeaderActions, {
      shallow: true,
      global: {
        stubs: {
          Dropdown: true,
          DropdownItem: true,
          FeatureTooltip: { template: '<div><slot /></div>' },
          SettingsPanel: true,
          ExportDialog: true,
          BookmarksPanel: true,
          WorkspaceManager: true,
        },
      },
    })
    await flushPromises()

    await wrapper.find('button[title="Subkorpora"]').trigger('click')
    await flushPromises()

    expect(uiStore.workspaceOpen).toBe(true)
    expect(uiStore.workspaceTab).toBe('subcorpora')
    expect(uiStore.subcorpusOpen).toBe(false)
  })

  it('exposes corpus management as its own first-class action', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = {
      ...contract(),
      capabilities: contract().capabilities.map((item) => item.id.startsWith('corpus.')
        ? { ...item, visibility: 'first_class_ui', maturity: 'guarded' }
        : item),
    }
    const uiStore = useUiStore()
    wrapper = mount(HeaderActions, {
      shallow: true,
      global: {
        stubs: {
          Dropdown: true,
          DropdownItem: true,
          FeatureTooltip: { template: '<div><slot /></div>' },
          SettingsPanel: true,
          ExportDialog: true,
          BookmarksPanel: true,
          WorkspaceManager: true,
        },
      },
    })
    await flushPromises()

    expect(wrapper.find('button[title="Korpora verwalten"]').exists()).toBe(true)
    expect(wrapper.find('button[title="Einstellungen"]').exists()).toBe(true)

    await wrapper.find('button[title="Korpora verwalten"]').trigger('click')

    expect(uiStore.settingsOpen).toBe(true)
    expect(uiStore.corpusManagerOpen).toBe(true)
  })

  it('keeps observable import jobs visible in the global corpus action', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    adminSession()
    productCapabilities.contract = {
      ...contract(),
      capabilities: contract().capabilities.map((item) => item.id === 'corpus.import'
        ? {
            ...item,
            visibility: 'first_class_ui',
            maturity: 'guarded',
            backend_routes: ['/api/v1/corpora/imports'],
            backend_route_descriptors: [adminRoute('/api/v1/corpora/imports')],
            operations: [
              {
                id: 'corpus.import.jobs_list',
                capability_id: 'corpus.import',
                label: 'Importjobs listen',
                description: '',
                route: adminRoute('/api/v1/corpora/imports', ['GET']),
                effects: ['read'],
                handler_key: 'loadJobs',
                surface_slot: 'corpus.import.jobs',
                priority: 10,
              },
            ],
          }
        : item),
    }
    apiMocks.listCorpusImportJobs.mockResolvedValueOnce([
      {
        job_id: 'import-running-1',
        method: 'prealigned_csv',
        target_name: 'paired-demo',
        status: 'running',
        progress: 40,
      },
    ])

    wrapper = mount(HeaderActions, {
      shallow: true,
      global: {
        stubs: {
          Dropdown: true,
          DropdownItem: true,
          FeatureTooltip: { template: '<div><slot /></div>' },
          SettingsPanel: true,
          ExportDialog: true,
          BookmarksPanel: true,
          WorkspaceManager: true,
        },
      },
    })
    await flushPromises()

    expect(apiMocks.listCorpusImportJobs).toHaveBeenCalled()
    expect(wrapper.text()).toContain('1 läuft')
    expect(wrapper.find('button[title="Korpora verwalten · Importjobs: 1 läuft"]').exists()).toBe(true)
  })

  it('disables header export formats whose ProductOperation is not available', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    userSession()
    productCapabilities.contract = {
      ...contract(),
      capabilities: contract().capabilities.map((item) => item.id === 'research.replay_export'
        ? {
            ...item,
            visibility: 'first_class_ui',
            maturity: 'guarded',
            backend_routes: [
              '/api/v1/export/evidence-package',
              '/api/v1/export/pdf',
            ],
            backend_route_descriptors: [
              userRoute('/api/v1/export/evidence-package', ['POST']),
              userRoute('/api/v1/export/pdf', ['POST']),
            ],
            operations: [
              {
                id: 'research.replay_export.evidence_package',
                capability_id: 'research.replay_export',
                label: 'EvidencePackage exportieren',
                description: '',
                route: userRoute('/api/v1/export/evidence-package', ['POST']),
                effects: ['read'],
                handler_key: 'exportEvidencePackageFromServer',
                surface_slot: 'export.evidence_package',
                priority: 10,
              },
              {
                id: 'research.replay_export.pdf',
                capability_id: 'research.replay_export',
                label: 'PDF exportieren',
                description: '',
                route: userRoute('/api/v1/export/pdf', ['POST']),
                effects: ['read'],
                handler_key: 'exportPDF',
                surface_slot: 'export.pdf',
                priority: 20,
              },
            ],
          }
        : item),
    }

    wrapper = mount(HeaderActions, {
      attachTo: document.body,
      global: {
        stubs: {
          FeatureTooltip: { template: '<div><slot /></div>' },
          AuthSessionPanel: { template: '<div />' },
          SettingsPanel: true,
          ExportDialog: true,
          BookmarksPanel: true,
          WorkspaceManager: true,
          Transition: false,
        },
      },
    })
    await flushPromises()

    await wrapper.find('button[title="Exportieren"]').trigger('click')
    await flushPromises()

    // Das Menue haengt seit dem 2026-08-31 im Portal am body, damit kein
    // Overflow-Vorfahre es beschneidet. wrapper.findAll sieht es deshalb
    // nicht mehr, das Dokument schon. Die geprueften Zusicherungen sind
    // unveraendert.
    const items = Array.from(
      document.body.querySelectorAll<HTMLElement>('.dropdown-item'),
    )
    const pdf = items.find((item) => (item.textContent ?? '').includes('PDF'))
    const docx = items.find((item) => (item.textContent ?? '').includes('Word'))
    const csv = items.find((item) => (item.textContent ?? '').includes('CSV'))

    expect(pdf).toBeDefined()
    expect(pdf?.getAttribute('disabled')).toBeNull()
    expect(docx?.getAttribute('disabled')).not.toBeNull()
    expect(docx?.getAttribute('title')).toContain('nicht als Serverfunktion verfügbar')
    expect(csv?.getAttribute('disabled')).not.toBeNull()
    expect(csv?.getAttribute('title')).toContain('nicht als Serverfunktion verfügbar')
  })
})
