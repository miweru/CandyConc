import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import WorkspaceManager from '@/components/workspace/WorkspaceManager.vue'
import { useAnalysisPresetsStore, useProductCapabilitiesStore, useSessionStore, useUiStore } from '@/stores'
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
  SlideOver: { template: '<div class="slide-over"><slot /></div>' },
  WorkspaceSubcorporaPanel: { template: '<div>SUBCORPORA PANEL</div>' },
  WorkspaceAnalysesPanel: { template: '<div>ANALYSES PANEL</div>' },
}

function capability(id: string, visibility: 'first_class_ui' | 'hidden_experimental' = 'first_class_ui') {
  const descriptor = {
    path: `/test/capabilities/${id.replace('.', '/')}`,
    methods: ['GET'] as Array<'GET'>,
    mutates: false,
    requires_corpus_features: [],
    access: 'user' as const,
    required_role: 'user',
    transport: 'http' as const,
    route_class: 'product_surface' as const,
  }
  const operations = id === 'analysis.async_jobs'
    ? [{
        id: 'analysis.async_jobs.status',
        capability_id: id,
        label: 'Analysejob-Status',
        description: 'Jobstatus laden.',
        route: descriptor,
        effects: ['read'] as Array<'read'>,
        handler_key: 'analysis_job_status',
        copilot_tools: [],
        surface_slot: 'analysis.jobs.status',
        priority: 10,
      }]
    : []
  return {
    id,
    title: id,
    area: id.split('.')[0],
    maturity: visibility === 'first_class_ui' ? 'guarded' : 'experimental',
    visibility,
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
      capability('research.subcorpora_docsets', 'hidden_experimental'),
      capability('research.analysis_presets', 'hidden_experimental'),
      capability('analysis.async_jobs'),
    ],
  }
}

function seedSession() {
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

describe('WorkspaceManager surface availability', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    getMcpTools.mockResolvedValue({ tools: [] })
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract()
    productCapabilities.status = 'ready'
    seedSession()
    const uiStore = useUiStore()
    uiStore.workspaceOpen = true
    uiStore.setWorkspaceTab('subcorpora')
    vi.spyOn(useAnalysisPresetsStore(), 'init').mockResolvedValue()
  })

  it('derives the analyses workspace from async jobs even when presets are hidden', async () => {
    const wrapper = mount(WorkspaceManager, { global: { stubs } })

    expect(wrapper.text()).toContain('Analysen')
    expect(wrapper.text()).not.toContain('Subkorpora')
    expect(useUiStore().workspaceTab).toBe('analyses')
    expect(wrapper.text()).toContain('ANALYSES PANEL')
    expect(wrapper.text()).not.toContain('Workspace-Operationen')
    expect(wrapper.text()).not.toContain('analysis.async_jobs.status')
  })
})
