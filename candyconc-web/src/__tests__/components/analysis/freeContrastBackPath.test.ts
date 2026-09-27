/**
 * A contrast row opens the concordance in group A or group B: the scope
 * becomes the group, and the concordance shows the hits of the node with the
 * collocate in their window. Before, the rows had no back path, and the guide
 * described setting a filter and opening the collocations by hand.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import FreeContrastPanel from '@/components/analysis/FreeContrastPanel.vue'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useQueryStore } from '@/stores/query'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'
import { useDocsetStore } from '@/stores/docset'
import { actionBus } from '@/actions/bus'

const getMetaSchema = vi.hoisted(() => vi.fn())
const getMetaValues = vi.hoisted(() => vi.fn())
const listSubcorpora = vi.hoisted(() => vi.fn())
const docsetFromMeta = vi.hoisted(() => vi.fn())
const resolveSubcorpus = vi.hoisted(() => vi.fn())
const createContrastJob = vi.hoisted(() => vi.fn())
const createCollocatesDiffJob = vi.hoisted(() => vi.fn())
const getAnalysisJob = vi.hoisted(() => vi.fn())
const getAnalysisJobRows = vi.hoisted(() => vi.fn())

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getMetaSchema: (...args: unknown[]) => getMetaSchema(...args),
    getMetaValues: (...args: unknown[]) => getMetaValues(...args),
    listSubcorpora: (...args: unknown[]) => listSubcorpora(...args),
    docsetFromMeta: (...args: unknown[]) => docsetFromMeta(...args),
    resolveSubcorpus: (...args: unknown[]) => resolveSubcorpus(...args),
    createContrastJob: (...args: unknown[]) => createContrastJob(...args),
    createCollocatesDiffJob: (...args: unknown[]) => createCollocatesDiffJob(...args),
    getAnalysisJob: (...args: unknown[]) => getAnalysisJob(...args),
    getAnalysisJobRows: (...args: unknown[]) => getAnalysisJobRows(...args),
  }
})

vi.mock('@/components/analysis/LexicalDiversityCard.vue', () => ({
  default: {
    name: 'LexicalDiversityCard',
    props: [
      'corpus',
      'targetDocsetId',
      'referenceDocsetId',
      'targetLabel',
      'referenceLabel',
      'autoLoad',
    ],
    template: `
      <div class="stub-diversity">
        {{ corpus }}|{{ targetDocsetId }}|{{ referenceDocsetId }}|{{ targetLabel }}|{{ referenceLabel }}|{{ autoLoad }}
      </div>
    `,
  },
}))

const stubs = {
  Button: { template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>', props: ['disabled'] },
  EmptyState: { template: '<div class="empty"><slot /></div>' },
  MethodPanel: { template: '<div class="method" />' },
  Scale: true,
  RefreshCw: true,
  ArrowRight: true,
}

function installProductContract() {
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
  const docsetRoutes = {
    metaSchema: {
      path: '/api/v1/analysis/meta_schema',
      methods: ['GET'],
      mutates: false,
      requires_corpus_features: [],
      access: 'user',
      required_role: 'user',
      transport: 'http',
      route_class: 'product_surface',
    },
    metaValues: {
      path: '/api/v1/analysis/meta_values',
      methods: ['POST'],
      mutates: false,
      requires_corpus_features: [],
      access: 'user',
      required_role: 'user',
      transport: 'http',
      route_class: 'product_surface',
    },
    docsetFromMeta: {
      path: '/api/v1/analysis/docset_from_meta',
      methods: ['POST'],
      mutates: false,
      requires_corpus_features: [],
      access: 'user',
      required_role: 'user',
      transport: 'http',
      route_class: 'product_surface',
    },
    subcorporaList: {
      path: '/api/v1/subcorpora',
      methods: ['GET'],
      mutates: false,
      requires_corpus_features: [],
      access: 'user',
      required_role: 'user',
      transport: 'http',
      route_class: 'product_surface',
    },
    subcorporaResolve: {
      path: '/api/v1/subcorpora/{name}/resolve',
      methods: ['POST'],
      mutates: false,
      requires_corpus_features: [],
      access: 'user',
      required_role: 'user',
      transport: 'http',
      route_class: 'product_surface',
    },
  } as const
  productCapabilities.contract = {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [
      {
        id: 'analysis.contrast',
        title: 'Pairing-free and paired contrast analyses',
        area: 'analysis',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: [
          '/api/v1/analysis/contrast',
          '/api/v1/analysis/collocates_diff/job',
          '/api/v1/analysis/lexical-diversity',
        ],
        backend_route_descriptors: [
          {
            path: '/api/v1/analysis/contrast',
            methods: ['POST'],
            mutates: false,
            requires_corpus_features: [],
            access: 'user',
            required_role: 'user',
            transport: 'http',
            route_class: 'product_surface',
          },
          {
            path: '/api/v1/analysis/collocates_diff/job',
            methods: ['POST'],
            mutates: false,
            requires_corpus_features: [],
            access: 'user',
            required_role: 'user',
            transport: 'http',
            route_class: 'product_surface',
          },
          {
            path: '/api/v1/analysis/lexical-diversity',
            methods: ['GET'],
            mutates: false,
            requires_corpus_features: [],
            access: 'user',
            required_role: 'user',
            transport: 'http',
            route_class: 'product_surface',
          },
        ],
        operations: [
          {
            id: 'analysis.contrast.free_job',
            capability_id: 'analysis.contrast',
            label: 'Freier Kontrastjob',
            description: '',
            route: {
              path: '/api/v1/analysis/contrast',
              methods: ['POST'],
              mutates: false,
              requires_corpus_features: [],
              access: 'user',
              required_role: 'user',
              transport: 'http',
              route_class: 'product_surface',
            },
            effects: ['read', 'long_running'],
            handler_key: 'contrast_job',
            surface_slot: 'analysis.contrast.free',
            priority: 10,
          },
          {
            id: 'analysis.contrast.collocations_diff_job',
            capability_id: 'analysis.contrast',
            label: 'Kollokations-Kontrastjob',
            description: '',
            route: {
              path: '/api/v1/analysis/collocates_diff/job',
              methods: ['POST'],
              mutates: false,
              requires_corpus_features: [],
              access: 'user',
              required_role: 'user',
              transport: 'http',
              route_class: 'product_surface',
            },
            effects: ['read', 'long_running'],
            handler_key: 'collocates_diff_job',
            surface_slot: 'analysis.contrast.collocations_diff',
            priority: 20,
          },
          {
            id: 'analysis.contrast.lexical_diversity',
            capability_id: 'analysis.contrast',
            label: 'Lexikalische Diversität',
            description: '',
            route: {
              path: '/api/v1/analysis/lexical-diversity',
              methods: ['GET'],
              mutates: false,
              requires_corpus_features: [],
              access: 'user',
              required_role: 'user',
              transport: 'http',
              route_class: 'product_surface',
            },
            effects: ['read'],
            handler_key: 'lexical_diversity',
            surface_slot: 'analysis.contrast.lexical_diversity',
            priority: 30,
          },
        ],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
        notes: '',
      },
      {
        id: 'analysis.async_jobs',
        title: 'Observable long-running analysis jobs',
        area: 'analysis',
        maturity: 'stable',
        visibility: 'first_class_ui',
        backend_routes: [
          '/api/v1/analysis/jobs/{job_id}',
          '/api/v1/analysis/jobs/{job_id}/rows',
        ],
        backend_route_descriptors: [
          {
            path: '/api/v1/analysis/jobs/{job_id}',
            methods: ['GET'],
            mutates: false,
            requires_corpus_features: [],
            access: 'user',
            required_role: 'user',
            transport: 'http',
            route_class: 'product_surface',
          },
          {
            path: '/api/v1/analysis/jobs/{job_id}/rows',
            methods: ['GET'],
            mutates: false,
            requires_corpus_features: [],
            access: 'user',
            required_role: 'user',
            transport: 'http',
            route_class: 'product_surface',
          },
        ],
        operations: [
          {
            id: 'analysis.async_jobs.status',
            capability_id: 'analysis.async_jobs',
            label: 'Analysejob-Status',
            description: '',
            route: {
              path: '/api/v1/analysis/jobs/{job_id}',
              methods: ['GET'],
              mutates: false,
              requires_corpus_features: [],
              access: 'user',
              required_role: 'user',
              transport: 'http',
              route_class: 'product_surface',
            },
            effects: ['read'],
            handler_key: 'analysis_job_status',
            surface_slot: 'analysis.jobs.status',
            priority: 10,
          },
          {
            id: 'analysis.async_jobs.rows',
            capability_id: 'analysis.async_jobs',
            label: 'Analysejob-Zeilen',
            description: '',
            route: {
              path: '/api/v1/analysis/jobs/{job_id}/rows',
              methods: ['GET'],
              mutates: false,
              requires_corpus_features: [],
              access: 'user',
              required_role: 'user',
              transport: 'http',
              route_class: 'product_surface',
            },
            effects: ['read'],
            handler_key: 'analysis_job_rows',
            surface_slot: 'analysis.jobs.rows',
            priority: 30,
          },
        ],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
        notes: '',
      },
      {
        id: 'research.subcorpora_docsets',
        title: 'Subkorpora und Docsets',
        area: 'research_workflow',
        maturity: 'stable',
        visibility: 'first_class_ui',
        backend_routes: Object.values(docsetRoutes).map((route) => route.path),
        backend_route_descriptors: Object.values(docsetRoutes),
        operations: [
          {
            id: 'research.subcorpora_docsets.meta_schema',
            capability_id: 'research.subcorpora_docsets',
            label: 'Metadatenschema',
            description: '',
            route: docsetRoutes.metaSchema,
            effects: ['read'],
            handler_key: 'meta_schema',
            surface_slot: 'research.subcorpora_docsets.meta_schema',
            priority: 10,
          },
          {
            id: 'research.subcorpora_docsets.meta_values',
            capability_id: 'research.subcorpora_docsets',
            label: 'Metadatenwerte',
            description: '',
            route: docsetRoutes.metaValues,
            effects: ['read'],
            handler_key: 'meta_values',
            surface_slot: 'research.subcorpora_docsets.meta_values',
            priority: 20,
          },
          {
            id: 'research.subcorpora_docsets.docset_from_meta',
            capability_id: 'research.subcorpora_docsets',
            label: 'Metadaten-Docset',
            description: '',
            route: docsetRoutes.docsetFromMeta,
            effects: ['read'],
            handler_key: 'docset_from_meta',
            surface_slot: 'research.subcorpora_docsets.docset_from_meta',
            priority: 30,
          },
          {
            id: 'research.subcorpora_docsets.subcorpora_list',
            capability_id: 'research.subcorpora_docsets',
            label: 'Subkorpora listen',
            description: '',
            route: docsetRoutes.subcorporaList,
            effects: ['read'],
            handler_key: 'subcorpora_list',
            surface_slot: 'research.subcorpora_docsets.subcorpora_list',
            priority: 40,
          },
          {
            id: 'research.subcorpora_docsets.subcorpora_resolve',
            capability_id: 'research.subcorpora_docsets',
            label: 'Subkorpus auflösen',
            description: '',
            route: docsetRoutes.subcorporaResolve,
            effects: ['read'],
            handler_key: 'subcorpora_resolve',
            surface_slot: 'research.subcorpora_docsets.subcorpora_resolve',
            priority: 50,
          },
        ],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
        notes: '',
      },
    ],
  }
}

describe('FreeContrastPanel back path to the concordance', () => {
  let dispatch: ReturnType<typeof vi.spyOn>
  let setScope: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    installProductContract()
    const query = useQueryStore()
    query.setTerm('Sprache')
    query.setFilters({ corpus: 'demo' })
    getMetaSchema.mockResolvedValue({ schemaVersion: 1, corpus: 'demo', metadataFields: [{ name: 'genre', kind: 'enum' }], warnings: [] })
    getMetaValues.mockResolvedValue({ genre: ['Blog', 'Zeitung'] })
    listSubcorpora.mockResolvedValue([])
    docsetFromMeta.mockImplementation((filter: Record<string, string>) => ({
      docset_id: filter.genre === 'Blog' ? 'ds-blog' : 'ds-zeitung',
      doc_count: 2,
    }))
    createContrastJob.mockResolvedValue({ job_id: 'job-1', status_url: '/jobs/job-1' })
    getAnalysisJob.mockResolvedValue({ job_id: 'job-1', status: 'done' })
    getAnalysisJobRows.mockResolvedValue({
      rows: [
        { word: 'Beispiel', target_freq: 4, reference_freq: 0, target_per_million: 12, reference_per_million: 0,
          diff_per_million: 12, target_score: 3.5, reference_score: null, diff_score: 3.5, score_key: 'logdice',
          log_ratio: 2.1, one_sided: true },
        { word: 'Satz', target_freq: 2, reference_freq: 5, target_per_million: 6, reference_per_million: 9,
          diff_per_million: -3, target_score: 1, reference_score: 2, diff_score: -1, score_key: 'logdice', log_ratio: -0.6 },
      ],
      total: 2,
    })
    const docsetStore = useDocsetStore()
    setScope = vi.spyOn(docsetStore, 'setMetaScope').mockImplementation(async (spec) => {
      docsetStore.activeDocsetId = (spec as Record<string, string>).genre === 'Blog' ? 'ds-blog-active' : 'ds-zeitung-active'
      return true
    })
    dispatch = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true })
  })

  afterEach(() => {
    dispatch.mockRestore()
    setScope.mockRestore()
  })

  async function runContrast() {
    const wrapper = mount(FreeContrastPanel, { global: { stubs } })
    await flushPromises()
    const selects = wrapper.findAll('select')
    await selects[0]!.setValue('genre')
    await flushPromises()
    await selects[1]!.setValue('Blog')
    await selects[2]!.setValue('genre')
    await flushPromises()
    await selects[3]!.setValue('Zeitung')
    await wrapper.find('.fc-actions button').trigger('click')
    await flushPromises()
    await flushPromises()
    return wrapper
  }

  it('opens the co-occurrence lines of a row in group A', async () => {
    const wrapper = await runContrast()
    const target = wrapper.findAll('[data-testid="contrast-open-target"]')[0]!
    expect(target.attributes('title')).toContain('Sprache mit Beispiel in genre = Blog')

    await target.trigger('click')
    await flushPromises()

    const coTerm = 'co(term="Sprache", collocate="Beispiel", window=5, within_sentence=true)'
    expect(setScope).toHaveBeenCalledWith({ genre: 'Blog' })
    expect(dispatch).toHaveBeenCalledWith({
      type: 'query/execute',
      payload: { term: coTerm, contextSize: useQueryStore().contextSize, docsetId: 'ds-blog-active' },
    })
    expect(dispatch).toHaveBeenLastCalledWith({ type: 'nav/switchTab', payload: { tab: 'kwic' } })
    expect(useQueryStore().backPathOrigin).toEqual({
      kind: 'contrast',
      term: coTerm,
      node: 'Sprache',
      collocate: 'Beispiel',
      side: 'target',
      group: 'genre = Blog',
      cooccurrences: 4,
      perMillion: 12,
    })
  })

  it('opens group B from the B column', async () => {
    const wrapper = await runContrast()
    await wrapper.findAll('[data-testid="contrast-open-reference"]')[1]!.trigger('click')
    await flushPromises()
    expect(setScope).toHaveBeenCalledWith({ genre: 'Zeitung' })
    expect(useQueryStore().backPathOrigin).toMatchObject({ side: 'reference', group: 'genre = Zeitung', cooccurrences: 5, collocate: 'Satz' })
  })

  it('has no link where the collocate does not occur in the group', async () => {
    const wrapper = await runContrast()
    const reference = wrapper.findAll('[data-testid="contrast-open-reference"]')[0]!
    expect(reference.attributes('disabled')).toBeDefined()
    expect(reference.attributes('title')).toContain('kommt das Kollokat nicht im Fenster')
    await reference.trigger('click')
    await flushPromises()
    expect(setScope).not.toHaveBeenCalled()
    expect(dispatch).not.toHaveBeenCalled()
  })
})
