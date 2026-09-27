import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ContrastTab from '@/components/analysis/ContrastTab.vue'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useQueryStore } from '@/stores/query'
import { useSessionStore } from '@/stores/session'

const getMetaSchema = vi.hoisted(() => vi.fn())

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getMetaSchema: (...args: unknown[]) => getMetaSchema(...args),
  }
})

// Keep the heavy children out of the routing test.
vi.mock('@/components/analysis/KeynessTab.vue', () => ({
  default: { name: 'KeynessTab', template: '<div class="stub-keyness">LEGACY</div>' },
}))
vi.mock('@/components/analysis/FreeContrastPanel.vue', () => ({
  default: { name: 'FreeContrastPanel', template: '<div class="stub-free">FREE</div>' },
}))

function summary(name: string, pairAxes: string[]) {
  return {
    name,
    path: `/c/${name}`,
    token_count: 100,
    doc_count: 10,
    import_mode: 'rows',
    paired: pairAxes.length > 0,
    pair_axes: pairAxes,
    is_legacy: false,
    capabilities: pairAxes.length ? { parallel: true } : {},
  }
}

function installDocsetContract(): void {
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

  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.status = 'ready'
  const metaSchemaRoute = {
    path: '/api/v1/analysis/meta_schema',
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: [],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  }
  productCapabilities.contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    fingerprint_sha256: 'a'.repeat(64),
    capabilities: [{
      id: 'research.subcorpora_docsets',
      title: 'Subkorpora und Docsets',
      area: 'research_workflow',
      maturity: 'stable',
      visibility: 'first_class_ui',
      backend_routes: [metaSchemaRoute.path],
      backend_route_descriptors: [metaSchemaRoute],
      operations: [{
        id: 'research.subcorpora_docsets.meta_schema',
        capability_id: 'research.subcorpora_docsets',
        label: 'Metadatenschema',
        description: '',
        route: metaSchemaRoute,
        effects: ['read'],
        handler_key: 'meta_schema',
        surface_slot: 'research.subcorpora_docsets.meta_schema',
        priority: 10,
      }],
      frontend_evidence: [],
      action_types: [],
      copilot_tools: [],
      preconditions: [],
      requires_corpus_features: [],
      limits: [],
      notes: '',
    }],
  } as never
}

describe('ContrastTab routing (paired preset vs free contrast)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    installDocsetContract()
    getMetaSchema.mockResolvedValue({
      schemaVersion: 1,
      corpus: 'generic',
      metadataFields: [],
      warnings: [],
    })
  })

  it('shows the free contrast panel on a generic (unpaired) corpus', async () => {
    const corpus = useCorpusCapabilitiesStore()
    const query = useQueryStore()
    query.setFilters({ corpus: 'generic' })
    corpus.corpora = [summary('generic', [])]

    const wrapper = mount(ContrastTab)
    await flushPromises()

    expect(wrapper.find('.stub-free').exists()).toBe(true)
    expect(wrapper.find('.stub-keyness').exists()).toBe(false)
    // No mode switch is offered on an unpaired corpus.
    expect(wrapper.find('.contrast-mode-switch').exists()).toBe(false)
  })

  it('keeps generic paired corpora on free contrast by default', async () => {
    const corpus = useCorpusCapabilitiesStore()
    const query = useQueryStore()
    query.setFilters({ corpus: 'paired-generic' })
    corpus.corpora = [summary('paired-generic', ['model'])]

    const wrapper = mount(ContrastTab)
    await flushPromises()

    expect(getMetaSchema).toHaveBeenCalledWith({ corpus: 'paired-generic' }, {})
    expect(wrapper.find('.stub-free').exists()).toBe(true)
    expect(wrapper.find('.stub-keyness').exists()).toBe(false)
    expect(wrapper.find('.contrast-mode-switch').exists()).toBe(false)
  })

  it('offers the Human/KI preset only when metadata supports it and still defaults to free', async () => {
    getMetaSchema.mockResolvedValue({
      schemaVersion: 1,
      corpus: 'legacy-humanki',
      metadataFields: [
        { name: 'text_type', kind: 'enum' },
        { name: 'prompting_method', kind: 'enum' },
        { name: 'model', kind: 'enum' },
      ],
      warnings: [],
    })
    const corpus = useCorpusCapabilitiesStore()
    const query = useQueryStore()
    query.setFilters({ corpus: 'legacy-humanki' })
    corpus.corpora = [summary('legacy-humanki', ['model'])]

    const wrapper = mount(ContrastTab)
    await flushPromises()

    expect(wrapper.find('.stub-free').exists()).toBe(true)
    expect(wrapper.find('.stub-keyness').exists()).toBe(false)
    expect(wrapper.find('.contrast-mode-switch').exists()).toBe(true)

    // Click the special preset explicitly.
    const buttons = wrapper.findAll('.mode-btn')
    const presetBtn = buttons.find((b) => b.text().includes('Mensch/KI'))
    await presetBtn!.trigger('click')

    expect(wrapper.find('.stub-keyness').exists()).toBe(true)
    expect(wrapper.find('.stub-free').exists()).toBe(false)
  })

  it('names the preset after anchor and version for a corpus whose pairs carry those values', async () => {
    getMetaSchema.mockResolvedValue({
      schemaVersion: 1,
      corpus: 'paired-anchor',
      metadataFields: [
        { name: 'text_type', kind: 'enum' },
        { name: 'prompting_method', kind: 'enum' },
        { name: 'model', kind: 'enum' },
      ],
      warnings: [],
    })
    const corpus = useCorpusCapabilitiesStore()
    const query = useQueryStore()
    query.setFilters({ corpus: 'paired-anchor' })
    corpus.corpora = [{
      ...summary('paired-anchor', ['variant']),
      features: {
        schema_version: 'corpus-features-v1',
        alignment: {
          paired: true,
          pair_axes: ['variant'],
          pairing_schema: {
            schema_id: 'legacy_ref_doc_v1',
            group_key_field: 'ref_doc',
            anchor_role_field: 'text_type',
            default_anchor_role: 'anchor',
            variant_axis_fields: ['variant'],
            generic_axis_filters: false,
          },
        },
      },
    }] as never

    const wrapper = mount(ContrastTab)
    await flushPromises()

    const labels = wrapper.findAll('.mode-btn').map((button) => button.text())
    expect(labels).toContain('Anker/Fassung-Preset')
    expect(labels.some((label) => label.includes('Mensch/KI'))).toBe(false)
  })
})
