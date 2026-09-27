import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import {
  capabilityBlockReasonForAction,
  createProductCapabilityGateMiddleware,
} from '@/actions/productGate'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useQueryStore } from '@/stores/query'
import { useDocsetStore } from '@/stores/docset'
import type { Action } from '@/actions/types'
import type {
  ProductCapability,
  ProductCapabilityBackendRouteDescriptor,
  ProductCapabilityOperation,
  ProductCapabilityContract,
} from '@/api/client'

const apiMocks = vi.hoisted(() => ({
  getProductCapabilities: vi.fn(),
  getAuthSession: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: (...args: unknown[]) => apiMocks.getProductCapabilities(...args),
    getAuthSession: (...args: unknown[]) => apiMocks.getAuthSession(...args),
    loginUser: vi.fn(),
    logoutUser: vi.fn(),
  }
})


const operationSpecs: Record<string, Record<string, { path: string; method: string; label: string }>> = {
  'query.kwic': {
    'query.kwic.page': { path: '/api/v1/query', method: 'GET', label: 'KWIC-Trefferseite' },
    'query.kwic.stream': { path: '/api/v1/query/stream', method: 'GET', label: 'KWIC-Stream' },
    'query.kwic.count': { path: '/api/v1/query/count', method: 'GET', label: 'KWIC-Zählung' },
  },
  'query.document_access': {
    'query.document_access.snippet': { path: '/api/v1/doc/snippet', method: 'GET', label: 'Dokument-Snippet' },
    'query.document_access.full_text': { path: '/api/v1/document/{doc_id}', method: 'GET', label: 'Dokument öffnen' },
  },
  'analysis.frequency': {
    'analysis.frequency.list': { path: '/api/v1/analysis/frequency_list', method: 'GET', label: 'Frequenzliste' },
    'analysis.frequency.job': { path: '/api/v1/analysis/frequency_list/job', method: 'POST', label: 'Frequenzjob' },
  },
  'analysis.collocations': {
    'analysis.collocations.job': { path: '/api/v1/analysis/collocates/job', method: 'POST', label: 'Kollokationsjob' },
    'analysis.collocations.kwic': { path: '/api/v1/analysis/collocates/kwic', method: 'GET', label: 'Co-KWIC' },
  },
  'analysis.async_jobs': {
    'analysis.async_jobs.status': { path: '/api/v1/analysis/jobs/{job_id}', method: 'GET', label: 'Analysejob-Status' },
    'analysis.async_jobs.rows': { path: '/api/v1/analysis/jobs/{job_id}/rows', method: 'GET', label: 'Analysejob-Zeilen' },
  },
  'analysis.dispersion': {
    'analysis.dispersion.stats': { path: '/api/v1/analysis/dispersion', method: 'GET', label: 'Dispersion' },
    'analysis.dispersion.offsets': { path: '/api/v1/analysis/dispersion_offsets', method: 'GET', label: 'Dispersions-Offsets' },
  },
  'analysis.semantic_similarity': {
    'analysis.semantic_similarity.similar_words': { path: '/api/v1/semantic/similar_words', method: 'GET', label: 'Distributioneller Thesaurus' },
    'analysis.semantic_similarity.passage_search': { path: '/api/v1/analysis/embedding_search', method: 'POST', label: 'Semantische Passagensuche' },
  },
  'analysis.wordsketch': {
    'analysis.wordsketch.profile': { path: '/api/v1/analysis/wordsketch', method: 'POST', label: 'Word Sketch' },
  },
  'research.bookmarks': {
    'research.bookmarks.write': { path: '/api/v1/prefs/update', method: 'POST', label: 'Lesezeichen speichern/löschen' },
  },
  'research.replay_export': {
    'research.replay_export.concordance': { path: '/api/v1/export/concordance', method: 'POST', label: 'Konkordanz-Export' },
    'research.replay_export.evidence_package': { path: '/api/v1/export/evidence-package', method: 'POST', label: 'EvidencePackage-Export' },
    'research.replay_export.pdf': { path: '/api/v1/export/pdf', method: 'POST', label: 'PDF-Export' },
    'research.replay_export.docx': { path: '/api/v1/export/docx', method: 'POST', label: 'DOCX-Export' },
  },
  'research.copilot_grounding': {
    'research.copilot_grounding.chat_stream': { path: '/api/v1/chat/stream', method: 'POST', label: 'Copilot-Chat-Stream' },
    'research.copilot_grounding.clarification_answer': { path: '/api/v1/copilot/clarify/answer', method: 'POST', label: 'Copilot-Rückfrage beantworten' },
    'research.copilot_grounding.continue': { path: '/api/v1/copilot/continue', method: 'POST', label: 'Copilot-Continue' },
  },
}

function operationsForCapability(
  id: string,
  descriptors: ProductCapabilityBackendRouteDescriptor[],
): ProductCapabilityOperation[] {
  const routeByMethod = new Map(
    descriptors.flatMap((descriptor) =>
      (descriptor.methods?.length ? descriptor.methods : ['GET']).map((method) => [
        `${method.toUpperCase()} ${descriptor.path}`,
        descriptor,
      ] as const),
    ),
  )
  return Object.entries(operationSpecs[id] ?? {}).flatMap(([operationId, spec]) => {
    const descriptor = routeByMethod.get(`${spec.method} ${spec.path}`)
    if (!descriptor) return []
    return [{
      id: operationId,
      capability_id: id,
      label: spec.label,
      description: '',
      route: descriptor,
      effects: ['read'],
      handler_key: operationId.split('.').at(-1) ?? operationId,
      surface_slot: operationId,
      priority: 100,
      input_schema_ref: 'operation.generic_request',
      required_context: [],
      response_shape: operationId.endsWith('.pdf') || operationId.endsWith('.docx') || operationId.endsWith('.concordance')
        ? 'file'
        : 'data',
      run_semantics: operationId.endsWith('.pdf') || operationId.endsWith('.docx') || operationId.endsWith('.concordance')
        ? 'file_export'
        : 'bounded_sync',
      ui_execution_policy: 'contextual_ui',
      requires_parameters: true,
    }]
  })
}

function capability(
  id: string,
  actionTypes: string[] = [],
  overrides: Partial<ProductCapability> = {},
): ProductCapability {
  const backendRouteDescriptors = overrides.backend_route_descriptors ?? []
  return {
    id,
    title: id,
    area: id.split('.')[0],
    maturity: 'stable',
    visibility: 'first_class_ui',
    backend_routes: [],
    backend_route_descriptors: backendRouteDescriptors,
    operations: overrides.operations ?? operationsForCapability(id, backendRouteDescriptors),
    frontend_evidence: [],
    action_types: actionTypes,
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
    notes: '',
    ...overrides,
  }
}

function route(
  path: string,
  methods: string[] = ['GET'],
  overrides: Partial<ProductCapabilityBackendRouteDescriptor> = {},
): ProductCapabilityBackendRouteDescriptor {
  return {
    path,
    methods,
    mutates: methods.some((method) => method !== 'GET'),
    requires_corpus_features: [],
    access: 'public',
    required_role: null,
    transport: 'http',
    route_class: null,
    ...overrides,
  }
}

function contract(capabilities: ProductCapability[]): ProductCapabilityContract {
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities,
  }
}

function seedWordOnlyCorpus() {
  const corpusCapabilities = useCorpusCapabilitiesStore()
  corpusCapabilities.corpora = [{
    name: 'default',
    path: '/tmp/default',
    active: true,
    token_count: 100,
    doc_count: 1,
    import_mode: 'test',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: {},
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [{ id: 'word', cql_attribute: 'word', label: 'Wortform' }],
      frequency_groups: [{ id: 'word', label: 'Wortform' }],
      semantic: { passage_search: false, word_similarity: false, sentence_alignment: false },
      alignment: { paired: false, pair_axes: [], parallel_groups: false, parallel_kwic: false },
    },
  }]
}

describe('Product capability action gate', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    apiMocks.getAuthSession.mockResolvedValue({
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
    })
  })

  it('blocks mapped actions whose owning capability is not first-class visible', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('research.replay_export', ['export/data'], { visibility: 'expert_api' }),
    ])
    productCapabilities.status = 'ready'

    const reason = capabilityBlockReasonForAction({
      type: 'export/data',
      payload: { format: 'pdf' },
    })

    expect(reason).toContain('research.replay_export')
  })

  it('blocks mapped export actions when the concrete ProductOperation is not offered', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('research.replay_export', ['export/data']),
    ])
    productCapabilities.status = 'ready'

    const reason = capabilityBlockReasonForAction({
      type: 'export/data',
      payload: { format: 'pdf' },
    })

    expect(reason).toContain('EvidencePackage-Export')
    expect(reason).toContain('nicht als Serverfunktion verfügbar')
  })

  it('blocks PDF export when the EvidencePackage dependency is missing', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('research.replay_export', ['export/data'], {
        backend_routes: ['/api/v1/export/pdf'],
        backend_route_descriptors: [
          route('/api/v1/export/pdf', ['POST']),
        ],
      }),
    ])
    productCapabilities.status = 'ready'

    const reason = capabilityBlockReasonForAction({
      type: 'export/data',
      payload: { format: 'pdf' },
    })

    expect(reason).toContain('EvidencePackage-Export')
    expect(reason).toContain('nicht als Serverfunktion verfügbar')
  })

  it('lets mapped PDF export actions through when the full operation chain is offered', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('research.replay_export', ['export/data'], {
        backend_routes: ['/api/v1/export/evidence-package', '/api/v1/export/pdf'],
        backend_route_descriptors: [
          route('/api/v1/export/evidence-package', ['POST']),
          route('/api/v1/export/pdf', ['POST']),
        ],
      }),
    ])
    productCapabilities.status = 'ready'

    expect(capabilityBlockReasonForAction({
      type: 'export/data',
      payload: { format: 'pdf' },
    })).toBeNull()
  })

  it('blocks local CSV export actions before pretending a backend concordance export exists', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('research.replay_export', ['export/data'], {
        backend_routes: ['/api/v1/export/concordance'],
        backend_route_descriptors: [
          route('/api/v1/export/concordance', ['POST']),
        ],
      }),
    ])
    productCapabilities.status = 'ready'

    expect(capabilityBlockReasonForAction({
      type: 'export/data',
      payload: { format: 'csv' },
    })).toContain('Lokaler CSV-Auszug ohne freigegebenen Server-Export ist nicht direkt ausführbar')

    expect(capabilityBlockReasonForAction({
      type: 'export/data',
      payload: { format: 'csv', selection: 'all' },
    })).toBeNull()

    expect(capabilityBlockReasonForAction({
      type: 'export/data',
      payload: { format: 'csv', scope: 'all-server' },
    })).toBeNull()

    expect(capabilityBlockReasonForAction({
      type: 'export/data',
      payload: { format: 'csv', selection: 'selected', scope: 'all-server' },
    })).toContain('Lokaler CSV-Auszug ohne freigegebenen Server-Export ist nicht direkt ausführbar')
  })

  it('blocks mapped analysis actions when the concrete backend operation is not offered', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('analysis.frequency', ['analysis/frequency']),
    ])
    productCapabilities.status = 'ready'

    const reason = capabilityBlockReasonForAction({
      type: 'analysis/frequency',
      payload: { groupBy: 'word' },
    })

    expect(reason).toContain('Frequenzjob')
    expect(reason).toContain('nicht als Serverfunktion verfügbar')
  })

  it('allows mapped frequency actions through the sync fallback when only the list operation is offered', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('analysis.frequency', ['analysis/frequency'], {
        backend_routes: ['/api/v1/analysis/frequency_list'],
        backend_route_descriptors: [
          route('/api/v1/analysis/frequency_list', ['GET']),
        ],
      }),
    ])
    productCapabilities.status = 'ready'

    expect(capabilityBlockReasonForAction({
      type: 'analysis/frequency',
      payload: { groupBy: 'word' },
    })).toBeNull()
  })

  it('allows mapped frequency actions through the observable job lifecycle when offered', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('analysis.frequency', ['analysis/frequency'], {
        backend_routes: ['/api/v1/analysis/frequency_list/job'],
        backend_route_descriptors: [
          route('/api/v1/analysis/frequency_list/job', ['POST']),
        ],
      }),
      capability('analysis.async_jobs', [], {
        backend_routes: [
          '/api/v1/analysis/jobs/{job_id}',
          '/api/v1/analysis/jobs/{job_id}/rows',
        ],
        backend_route_descriptors: [
          route('/api/v1/analysis/jobs/{job_id}', ['GET']),
          route('/api/v1/analysis/jobs/{job_id}/rows', ['GET']),
        ],
      }),
    ])
    productCapabilities.status = 'ready'

    expect(capabilityBlockReasonForAction({
      type: 'analysis/frequency',
      payload: { groupBy: 'word' },
    })).toBeNull()
  })

  it('requires sync frequency list for lemma and POS requests', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('analysis.frequency', ['analysis/frequency'], {
        backend_routes: ['/api/v1/analysis/frequency_list/job'],
        backend_route_descriptors: [
          route('/api/v1/analysis/frequency_list/job', ['POST']),
        ],
      }),
      capability('analysis.async_jobs', [], {
        backend_routes: [
          '/api/v1/analysis/jobs/{job_id}',
          '/api/v1/analysis/jobs/{job_id}/rows',
        ],
        backend_route_descriptors: [
          route('/api/v1/analysis/jobs/{job_id}', ['GET']),
          route('/api/v1/analysis/jobs/{job_id}/rows', ['GET']),
        ],
      }),
    ])
    productCapabilities.status = 'ready'

    const reason = capabilityBlockReasonForAction({
      type: 'analysis/frequency',
      payload: { groupBy: 'lemma' },
    })
    expect(reason).toContain('Frequenzliste')
  })

  it('gates bulk bookmark deletion through the bookmark write ProductOperation', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('research.bookmarks', ['bookmark/add', 'bookmark/remove', 'bookmark/clear'], {
        backend_routes: ['/api/v1/prefs/update'],
        backend_route_descriptors: [
          route('/api/v1/prefs/update', ['POST']),
        ],
      }),
    ])
    productCapabilities.status = 'ready'

    expect(capabilityBlockReasonForAction({ type: 'bookmark/clear' })).toBeNull()

    productCapabilities.contract = contract([
      capability('research.bookmarks', ['bookmark/add', 'bookmark/remove', 'bookmark/clear']),
    ])

    const reason = capabilityBlockReasonForAction({ type: 'bookmark/clear' })
    expect(reason).toContain('Lesezeichen speichern')
    expect(reason).toContain('nicht als Serverfunktion verfügbar')
  })

  it('does not require query.cqlf to claim the KWIC execute route', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('query.kwic', ['query/execute'], {
        backend_routes: ['/api/v1/query/stream'],
        backend_route_descriptors: [
          route('/api/v1/query/stream', ['GET']),
        ],
      }),
      capability('query.cqlf', ['query/execute'], {
        backend_routes: ['/api/v1/query/analyse', '/api/v1/query/lexicon/suggest'],
        backend_route_descriptors: [
          route('/api/v1/query/analyse', ['POST']),
          route('/api/v1/query/lexicon/suggest', ['POST']),
        ],
      }),
    ])
    productCapabilities.status = 'ready'

    expect(capabilityBlockReasonForAction({
      type: 'query/execute',
      payload: { term: 'cql:[lemma="gehen"]' },
    })).toBeNull()
  })

  it('requires the streaming KWIC route for unsorted query execution', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('query.kwic', ['query/execute'], {
        backend_routes: ['/api/v1/query'],
        backend_route_descriptors: [
          route('/api/v1/query', ['GET']),
        ],
      }),
    ])
    productCapabilities.status = 'ready'

    const reason = capabilityBlockReasonForAction({
      type: 'query/execute',
      payload: { term: 'Hase' },
    })

    expect(reason).toContain('KWIC-Suche')
    expect(reason).toContain('nicht als Serverfunktion verfügbar')
  })

  it('requires the sorted KWIC route when the current KWIC state is sorted', () => {
    const queryStore = useQueryStore()
    queryStore.setSort('node')
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('query.kwic', ['query/execute'], {
        backend_routes: ['/api/v1/query/stream'],
        backend_route_descriptors: [
          route('/api/v1/query/stream', ['GET']),
        ],
      }),
    ])
    productCapabilities.status = 'ready'

    const reason = capabilityBlockReasonForAction({
      type: 'query/execute',
      payload: { term: 'Hase' },
    })

    expect(reason).toContain('KWIC-Suche')
    expect(reason).toContain('nicht als Serverfunktion verfügbar')
  })

  it('allows sorted KWIC execution when the sorted query route is offered', () => {
    const queryStore = useQueryStore()
    queryStore.setSort('node')
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('query.kwic', ['query/execute'], {
        backend_routes: ['/api/v1/query'],
        backend_route_descriptors: [
          route('/api/v1/query', ['GET']),
        ],
      }),
    ])
    productCapabilities.status = 'ready'

    expect(capabilityBlockReasonForAction({
      type: 'query/execute',
      payload: { term: 'Hase' },
    })).toBeNull()
  })

  it('uses the sorted query route when a new term drops the active docset', () => {
    const queryStore = useQueryStore()
    const docsetStore = useDocsetStore()
    queryStore.setTerm('alter Suchterm')
    queryStore.setSort('node')
    docsetStore.activeDocsetId = 'docset-1'
    docsetStore.isDirty = false
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('query.kwic', ['query/execute'], {
        backend_routes: ['/api/v1/query/stream'],
        backend_route_descriptors: [
          route('/api/v1/query/stream', ['GET']),
        ],
      }),
    ])
    productCapabilities.status = 'ready'

    const reason = capabilityBlockReasonForAction({
      type: 'query/execute',
      payload: { term: 'neuer Suchterm' },
    })

    expect(reason).toContain('KWIC-Suche')
    expect(reason).toContain('nicht als Serverfunktion verfügbar')
  })

  it('gates Co-KWIC pagination through the collocate KWIC route', () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('co(term="Hase", collocate="schnell", window=5)')
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('query.kwic', ['query/loadMore'], {
        backend_routes: ['/api/v1/query/stream'],
        backend_route_descriptors: [
          route('/api/v1/query/stream', ['GET']),
        ],
      }),
      capability('analysis.collocations', ['analysis/collocations'], {
        backend_routes: ['/api/v1/analysis/collocates/job'],
        backend_route_descriptors: [
          route('/api/v1/analysis/collocates/job', ['POST']),
        ],
      }),
    ])
    productCapabilities.status = 'ready'

    const reason = capabilityBlockReasonForAction({
      type: 'query/loadMore',
      payload: {},
    })

    expect(reason).toContain('Co-KWIC-Pagination')
    expect(reason).toContain('nicht als Serverfunktion verfügbar')
  })

  it('requires both async job status and row routes for collocation actions', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('analysis.collocations', ['analysis/collocations'], {
        backend_routes: ['/api/v1/analysis/collocates/job'],
        backend_route_descriptors: [
          route('/api/v1/analysis/collocates/job', ['POST']),
        ],
      }),
      capability('analysis.async_jobs', [], {
        backend_routes: ['/api/v1/analysis/jobs/{job_id}'],
        backend_route_descriptors: [
          route('/api/v1/analysis/jobs/{job_id}', ['GET']),
        ],
      }),
    ])
    productCapabilities.status = 'ready'

    const reason = capabilityBlockReasonForAction({
      type: 'analysis/collocations',
      payload: { term: 'Hase' },
    })

    expect(reason).toContain('Analysejob-Zeilen')
    expect(reason).toContain('nicht als Serverfunktion verfügbar')
  })

  it('checks semantic action submodes against the matching route operation', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('analysis.semantic_similarity', ['analysis/semantic'], {
        backend_routes: ['/api/v1/semantic/similar_words'],
        backend_route_descriptors: [
          route('/api/v1/semantic/similar_words', ['GET']),
        ],
      }),
    ])
    productCapabilities.status = 'ready'

    expect(capabilityBlockReasonForAction({
      type: 'analysis/semantic',
      payload: { query: 'Hase', mode: 'thesaurus' },
    })).toBeNull()
    expect(capabilityBlockReasonForAction({
      type: 'analysis/semantic',
      payload: { query: 'Hase', mode: 'passage' },
    })).toContain('Semantische Passagensuche')
  })

  it('gates Copilot stream actions through the concrete chat ProductOperation', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('research.copilot_grounding', ['copilot/sendMessage']),
    ])
    productCapabilities.status = 'ready'

    const reason = capabilityBlockReasonForAction({
      type: 'copilot/sendMessage',
      payload: { message: 'Analysiere das Korpus.' },
    })

    expect(reason).toContain('Copilot-Chat-Stream')
    expect(reason).toContain('nicht als Serverfunktion verfügbar')

    productCapabilities.contract = contract([
      capability('research.copilot_grounding', ['copilot/sendMessage'], {
        backend_routes: ['/api/v1/chat/stream'],
        backend_route_descriptors: [
          route('/api/v1/chat/stream', ['POST']),
        ],
      }),
    ])

    expect(capabilityBlockReasonForAction({
      type: 'copilot/sendMessage',
      payload: { message: 'Analysiere das Korpus.' },
    })).toBeNull()
  })

  it('gates clarification answers against the actual chat-stream handler path', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('research.copilot_grounding', ['copilot/answerClarification'], {
        backend_routes: ['/api/v1/copilot/clarify/answer'],
        backend_route_descriptors: [
          route('/api/v1/copilot/clarify/answer', ['POST']),
        ],
      }),
    ])
    productCapabilities.status = 'ready'

    const reason = capabilityBlockReasonForAction({
      type: 'copilot/answerClarification',
      payload: { questionId: 'q1', optionId: 'a1' },
    })
    expect(reason).toContain('Clarification als Chat-Follow-up')

    productCapabilities.contract = contract([
      capability('research.copilot_grounding', ['copilot/answerClarification'], {
        backend_routes: ['/api/v1/chat/stream'],
        backend_route_descriptors: [
          route('/api/v1/chat/stream', ['POST']),
        ],
      }),
    ])

    expect(capabilityBlockReasonForAction({
      type: 'copilot/answerClarification',
      payload: { questionId: 'q1', optionId: 'a1' },
    })).toBeNull()
  })

  it('leaves operation-level corpus requirements to the action handler', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('analysis.wordsketch', ['analysis/wordSketch'], {
        backend_routes: ['/api/v1/analysis/wordsketch'],
        backend_route_descriptors: [
          route('/api/v1/analysis/wordsketch', ['POST'], {
            requires_corpus_features: ['token_attributes.rel'],
          }),
        ],
      }),
    ])
    productCapabilities.status = 'ready'
    seedWordOnlyCorpus()

    const reason = capabilityBlockReasonForAction({
      type: 'analysis/wordSketch',
      payload: { term: 'Hase' },
    })

    expect(reason).toBeNull()
  })

  it('allows dispersion actions with the primary stats operation alone', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('analysis.dispersion', ['analysis/dispersion'], {
        backend_routes: ['/api/v1/analysis/dispersion'],
        backend_route_descriptors: [
          route('/api/v1/analysis/dispersion', ['GET']),
        ],
      }),
    ])
    productCapabilities.status = 'ready'

    expect(capabilityBlockReasonForAction({
      type: 'analysis/dispersion',
      payload: { term: 'Hase' },
    })).toBeNull()
  })

  it('blocks route-visible actions when the concrete operation requires a higher role', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('analysis.frequency', ['analysis/frequency'], {
        backend_routes: ['/api/v1/analysis/frequency_list'],
        backend_route_descriptors: [
          route('/api/v1/analysis/frequency_list', ['GET'], {
            access: 'admin',
            required_role: 'admin',
          }),
        ],
      }),
    ])
    productCapabilities.status = 'ready'
    const next = vi.fn(async () => ({ success: true }))
    const middleware = createProductCapabilityGateMiddleware()

    const result = await middleware(
      {
        type: 'analysis/frequency',
        payload: { groupBy: 'word' },
      } satisfies Action,
      next,
      { source: 'copilot', timestamp: 1 },
    )

    expect(apiMocks.getAuthSession).toHaveBeenCalledOnce()
    expect(next).not.toHaveBeenCalled()
    expect(result).toMatchObject({
      success: false,
      blocked: true,
      policyDecision: 'block',
    })
    expect(result.error).toContain('Rolle Admin')
  })

  it('blocks hidden analysis-tab navigation centrally', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('analysis.frequency', [], { maturity: 'planned' }),
    ])
    productCapabilities.status = 'ready'

    const reason = capabilityBlockReasonForAction({
      type: 'nav/switchTab',
      payload: { tab: 'frequency' },
    })

    expect(reason).toContain('frequency')
  })

  it('short-circuits middleware before the handler when a product action is blocked', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('research.replay_export', ['export/data'], { visibility: 'expert_api' }),
    ])
    productCapabilities.status = 'ready'
    const next = vi.fn(async () => ({ success: true }))
    const middleware = createProductCapabilityGateMiddleware()

    const result = await middleware(
      { type: 'export/data', payload: { format: 'docx' } } satisfies Action,
      next,
      { source: 'user', timestamp: 1 },
    )

    expect(next).not.toHaveBeenCalled()
    expect(result).toMatchObject({
      success: false,
      blocked: true,
      source: 'user',
      policyDecision: 'block',
    })
    expect(result.error).toContain('research.replay_export')
  })

  it('loads an idle product contract before deciding a protected action', async () => {
    apiMocks.getProductCapabilities.mockResolvedValueOnce(contract([
      capability('research.replay_export', ['export/data'], { visibility: 'expert_api' }),
    ]))
    const next = vi.fn(async () => ({ success: true }))
    const middleware = createProductCapabilityGateMiddleware()

    const result = await middleware(
      { type: 'export/data', payload: { format: 'pdf' } } satisfies Action,
      next,
      { source: 'user', timestamp: 1 },
    )

    expect(apiMocks.getProductCapabilities).toHaveBeenCalledOnce()
    expect(next).not.toHaveBeenCalled()
    expect(result).toMatchObject({
      success: false,
      blocked: true,
      policyDecision: 'block',
    })
    expect(result.error).toContain('research.replay_export')
  })

  it('allows missing-contract fallback only after an authoritative non-release session', async () => {
    apiMocks.getProductCapabilities.mockRejectedValueOnce(new Error('offline'))
    apiMocks.getAuthSession.mockResolvedValueOnce({
      schema_version: 'auth-session-v1',
      authenticated: true,
      token_present: false,
      username: 'dev',
      role: 'admin',
      effective_role: 'admin',
      rbac_enabled: false,
      security_mode: 'local-dev',
      release_mode: false,
      unsafe_token_transport: true,
      dev_token_available: true,
      can_access_all_roles: true,
    })
    const next = vi.fn(async () => ({ success: true }))
    const middleware = createProductCapabilityGateMiddleware()

    const result = await middleware(
      { type: 'query/clear' } satisfies Action,
      next,
      { source: 'user', timestamp: 1 },
    )

    expect(apiMocks.getProductCapabilities).toHaveBeenCalledOnce()
    expect(apiMocks.getAuthSession).toHaveBeenCalledOnce()
    expect(next).toHaveBeenCalledOnce()
    expect(result).toEqual({ success: true })
  })

  it('does not load the product contract for always-allowed UI status actions', async () => {
    const next = vi.fn(async () => ({ success: true }))
    const middleware = createProductCapabilityGateMiddleware()

    const result = await middleware(
      {
        type: 'ui/toast',
        payload: { message: 'ok', type: 'info' },
      } satisfies Action,
      next,
      { source: 'system', timestamp: 1 },
    )

    expect(apiMocks.getProductCapabilities).not.toHaveBeenCalled()
    expect(next).toHaveBeenCalledOnce()
    expect(result).toEqual({ success: true })
  })
})
