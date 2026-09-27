import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ChatMessage from '@/components/copilot/ChatMessage.vue'
import ToolCallResult from '@/components/copilot/ToolCallResult.vue'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useMcpToolsStore } from '@/stores/mcpTools'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import type { CorpusSummary, ProductCapabilityContract } from '@/api/client'

const getMcpTools = vi.fn()

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getMcpTools: (...args: unknown[]) => getMcpTools(...args),
  }
})

function productContract(options: {
  includeFrequencyOperation?: boolean
  frequencyRole?: 'public' | 'admin'
  extraFrequencyOperationRole?: 'public' | 'admin'
  frequencyResponseShape?: 'data' | 'job' | 'stream' | 'file' | 'image' | 'void' | 'mixed' | 'unknown'
} = {}): ProductCapabilityContract {
  const frequencyRole = options.frequencyRole ?? 'public'
  const frequencyRoute = {
    path: '/api/v1/analysis/frequency_list',
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: [],
    access: 'public',
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }
  const frequencyOperationRoute = {
    ...frequencyRoute,
    access: frequencyRole,
    required_role: frequencyRole === 'admin' ? 'admin' : null,
  }
  const extraFrequencyOperationRoute = {
    ...frequencyRoute,
    access: options.extraFrequencyOperationRole ?? 'public',
    required_role: options.extraFrequencyOperationRole === 'admin' ? 'admin' : null,
  }
  const operations = options.includeFrequencyOperation === false
    ? []
    : [{
        id: 'analysis.frequency.list',
        capability_id: 'analysis.frequency',
        label: 'Frequenzliste',
        description: 'Frequenzliste berechnen.',
        route: frequencyOperationRoute,
        effects: ['read'],
        handler_key: 'frequency_list',
        copilot_tools: ['frequency_list'],
        surface_slot: 'analysis.frequency.list',
        priority: 10,
        input_schema_ref: 'analysis.frequency_job_request',
        required_context: [],
        response_shape: options.frequencyResponseShape ?? 'data',
        ui_execution_policy: 'contextual_ui',
        requires_parameters: false,
        lifecycle: null,
      }]
  if (options.extraFrequencyOperationRole) {
    operations.push({
      id: 'analysis.frequency.support',
      capability_id: 'analysis.frequency',
      label: 'Frequenz-Support',
      description: 'Zusätzliche Frequenz-Evidenz prüfen.',
      route: extraFrequencyOperationRoute,
      effects: ['read'],
      handler_key: 'frequency_list_support',
      copilot_tools: ['frequency_list'],
      surface_slot: 'analysis.frequency.support',
      priority: 20,
      input_schema_ref: 'operation.no_input',
      required_context: [],
      response_shape: 'data',
      ui_execution_policy: 'contextual_ui',
      requires_parameters: false,
      lifecycle: null,
    })
  }
  const toolRoute = (path: string) => ({
    path,
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: [],
    access: 'public',
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  })
  const toolOperation = (
    id: string,
    capabilityId: string,
    tool: string,
    path: string,
  ) => ({
    id,
    capability_id: capabilityId,
    label: id,
    description: '',
    route: toolRoute(path),
    effects: ['read'],
    handler_key: tool,
    copilot_tools: [tool],
    surface_slot: id,
    priority: 10,
    input_schema_ref: 'operation.tool_result',
    required_context: [],
    response_shape: 'data' as const,
    ui_execution_policy: 'contextual_ui' as const,
    requires_parameters: false,
    lifecycle: null,
  })
  const toolCapability = (
    id: string,
    title: string,
    tools: Array<{ tool: string; operationId: string; path: string }>,
    actionTypes: string[] = [],
  ) => {
    const toolOperations = tools.map((tool) =>
      toolOperation(tool.operationId, id, tool.tool, tool.path)
    )
    return {
      id,
      title,
      area: id.split('.')[0],
      maturity: 'stable' as const,
      visibility: 'first_class_ui' as const,
      backend_routes: toolOperations.map((operation) => operation.route.path),
      backend_route_descriptors: toolOperations.map((operation) => operation.route),
      operations: toolOperations,
      frontend_evidence: [],
      action_types: actionTypes,
      copilot_tools: tools.map((tool) => tool.tool),
      preconditions: [],
      requires_corpus_features: [],
      limits: [],
    }
  }
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
      {
        id: 'analysis.frequency',
        title: 'Frequency',
        area: 'analysis',
        maturity: 'stable',
        visibility: 'first_class_ui',
        backend_routes: ['/api/v1/analysis/frequency_list'],
        backend_route_descriptors: [frequencyRoute],
        operations,
        frontend_evidence: [],
        action_types: ['analysis/frequency'],
        copilot_tools: ['frequency_list'],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
      },
      toolCapability('query.kwic', 'KWIC', [
        { tool: 'run_cqlf_query', operationId: 'query.kwic.page', path: '/api/v1/query' },
      ], ['query/execute']),
      toolCapability('analysis.collocations', 'Kollokationen', [
        { tool: 'collocate_stats', operationId: 'analysis.collocations.job', path: '/api/v1/analysis/collocates' },
      ], ['analysis/collocations']),
      toolCapability('research.subcorpora_docsets', 'Subkorpora', [
        { tool: 'metadata_values', operationId: 'research.subcorpora_docsets.meta_values', path: '/api/v1/meta/values' },
      ]),
      toolCapability('query.document_access', 'Dokumentzugriff', [
        { tool: 'document_text', operationId: 'query.document_access.full_text', path: '/api/v1/document/{doc_id}' },
      ]),
      toolCapability('corpus.alignment_parallel', 'Parallel-KWIC', [
        { tool: 'parallel_kwic', operationId: 'corpus.alignment_parallel.parallel_kwic', path: '/api/v1/analysis/kwic_parallel' },
      ]),
      toolCapability('analysis.contrast', 'Kontrast', [
        { tool: 'lexical_diversity', operationId: 'analysis.contrast.lexical_diversity', path: '/api/v1/analysis/lexical_diversity' },
      ], ['analysis/lexicalDiversity']),
      toolCapability('analysis.semantic_similarity', 'Semantik', [
        { tool: 'similar_words', operationId: 'analysis.semantic_similarity.similar_words', path: '/api/v1/semantic/similar_words' },
      ], ['analysis/semantic']),
    ],
  }
}

function allFeatureCorpus(): CorpusSummary {
  return {
    name: 'default',
    path: '/corpora/default',
    active: true,
    token_count: 1000,
    doc_count: 10,
    import_mode: 'fixture',
    paired: true,
    pair_axes: ['source'],
    is_legacy: false,
    capabilities: {},
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [
        { id: 'word', cql_attribute: 'word', label: 'Wortform' },
        { id: 'lemma', cql_attribute: 'lemma', label: 'Lemma' },
        { id: 'pos', cql_attribute: 'pos', label: 'POS' },
        { id: 'rel', cql_attribute: 'rel', label: 'Dependenzrelation' },
      ],
      frequency_groups: [
        { id: 'word', label: 'Wortform' },
        { id: 'lemma', label: 'Lemma' },
        { id: 'pos', label: 'POS' },
      ],
      semantic: {
        passage_search: true,
        word_similarity: true,
        sentence_alignment: true,
      },
      alignment: {
        paired: true,
        pair_axes: ['source'],
        parallel_groups: true,
        parallel_kwic: true,
      },
    },
  }
}

function seedUserSession(): void {
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

function seedProductPinia(contract: ProductCapabilityContract = productContract()) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.contract = contract
  productCapabilities.status = 'ready'
  productCapabilities.error = null
  useCorpusCapabilitiesStore().corpora = [allFeatureCorpus()]
  seedUserSession()
  return pinia
}

describe('Copilot evidence labels', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    getMcpTools.mockReset()
    getMcpTools.mockResolvedValue({ tools: [], tool_statuses: [] })
  })

  it('marks assistant prose as interpretation and tool calls as computed evidence', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: {
          id: 'm1',
          role: 'assistant',
          content: 'Das deutet auf ein wiederkehrendes Muster hin.',
          timestamp: 1,
          toolCalls: [
            {
              id: 't1',
              name: 'frequency_list',
              arguments: {},
              status: 'success',
              result: { rows: [{ word: 'Hase', f: 3 }] },
            },
          ],
        },
      },
      global: {
        stubs: {
          ToolCallResult: true,
        },
      },
    })

    expect(wrapper.text()).toContain('AI-Interpretation')
    expect(wrapper.text()).toContain('Einordnung der berechneten Tool-Evidenz')
    expect(wrapper.text()).toContain('Berechnete Evidenz')
    expect(wrapper.text()).toContain('Toolwerte sind die prüfbare Basis')
  })

  it('marks assistant prose without tool calls as interpretation without computed tool evidence', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: {
          id: 'm1b',
          role: 'assistant',
          content: 'Ich würde zuerst die Frequenzen prüfen.',
          timestamp: 1,
          toolCalls: [],
        },
      },
      global: {
        stubs: {
          ToolCallResult: true,
        },
      },
    })

    expect(wrapper.text()).toContain('AI-Interpretation')
    expect(wrapper.text()).toContain('ohne berechnete Tool-Evidenz')
    expect(wrapper.text()).not.toContain('Berechnete Evidenz')
    expect(wrapper.text()).not.toContain('Toolwerte sind die prüfbare Basis')
  })

  it('marks failed assistant turns as error state, not as finished interpretation', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: {
          id: 'm1-error',
          role: 'assistant',
          content: 'Die Copilot-Antwort konnte nicht abgeschlossen werden.',
          timestamp: 1,
          error: true,
          toolCalls: [],
        },
      },
      global: {
        stubs: {
          ToolCallResult: true,
        },
      },
    })

    expect(wrapper.text()).toContain('AI-Fehlerstatus')
    expect(wrapper.text()).toContain('Antwort nicht abgeschlossen')
    expect(wrapper.text()).not.toContain('AI-Interpretation')
    expect(wrapper.find('[aria-label="AI-Fehlerstatus"]').exists()).toBe(true)
  })

  it('does not label failed or blocked tool calls as computed evidence', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: {
          id: 'm1c',
          role: 'assistant',
          content: 'Das Tool konnte keine freigegebene Evidenz liefern.',
          timestamp: 1,
          toolCalls: [
            {
              id: 't-blocked',
              name: 'frequency_list',
              arguments: {},
              status: 'success',
              result: { blocked: true, error: 'MCP blockiert.' },
            },
            {
              id: 't-error',
              name: 'wild_tool',
              arguments: {},
              status: 'error',
              error: 'Nicht registriert.',
            },
          ],
        },
      },
      global: {
        stubs: {
          ToolCallResult: true,
        },
      },
    })

    expect(wrapper.text()).toContain('ohne berechnete Tool-Evidenz')
    expect(wrapper.text()).toContain('Toolaufruf ohne Evidenzfreigabe')
    expect(wrapper.text()).toContain('Kein Toolresultat dieser Nachricht ist als Evidenz freigegeben')
    expect(wrapper.text()).not.toContain('Toolwerte sind die prüfbare Basis')
  })

  it('labels a structured parser failure as a syntax diagnosis', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: {
          id: 'm-diagnostic',
          role: 'assistant',
          content: 'Die Abfrage enthält eine unausgeglichene Klammer.',
          timestamp: 1,
          toolCalls: [
            {
              id: 't-diagnostic',
              name: 'run_cqlf_query',
              arguments: { query: 'cql:[lemma="Demokratie"' },
              status: 'error',
              error: 'Expected closing bracket',
              result: {
                status: 'error',
                message: 'Expected closing bracket',
                query: 'cql:[lemma="Demokratie"',
                diagnostics: {
                  errors: ['Unbalanced brackets'],
                  suggestions: ['cql:[lemma="Demokratie"]'],
                },
              },
            },
          ],
        },
      },
      global: {
        stubs: {
          ToolCallResult: true,
        },
      },
    })

    expect(wrapper.text()).toContain('Syntaxdiagnose')
    expect(wrapper.text()).toContain('Einordnung der Parserdiagnose. Es liegt keine Korpusauswertung vor.')
    expect(wrapper.text()).toContain('Korpustreffer wurden nicht berechnet')
    expect(wrapper.text()).not.toContain('Toolaufruf ohne Evidenzfreigabe')
  })

  it('does not label user messages as AI interpretation', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: {
          id: 'm2',
          role: 'user',
          content: 'Zeig mir Kollokationen.',
          timestamp: 1,
        },
      },
      global: {
        stubs: {
          ToolCallResult: true,
        },
      },
    })

    expect(wrapper.text()).not.toContain('AI-Interpretation')
    expect(wrapper.text()).not.toContain('Berechnete Evidenz')
  })

  it('marks interpretative mutating tool results as side-effectful interpretation', () => {
    const wrapper = mount(ToolCallResult, {
      props: {
        toolCall: {
          id: 't2',
          name: 'refine_cluster_label',
          arguments: { samples: ['A', 'B'] },
          status: 'success',
          result: { status: 'success', label: 'Thema' },
        },
      },
      global: {
          plugins: [seedProductPinia()],
        stubs: {
          ClusterRenderer: true,
        },
      },
    })

    expect(wrapper.text()).toContain('nicht read-only / interpretativ')
  })

  it('renders run_cqlf_query samples as sample evidence, not total hits', () => {
    const wrapper = mount(ToolCallResult, {
      props: {
        toolCall: {
          id: 't3',
          name: 'run_cqlf_query',
          arguments: { query: 'cql:[word="Hase"]' },
          status: 'success',
          result: {
            status: 'success',
            rows: [
              { left: 'der', match: 'Hase', right: 'läuft' },
              { left: 'ein', match: 'Hase', right: 'springt' },
            ],
          },
        },
      },
      global: {
        plugins: [seedProductPinia()],
        stubs: {
          Search: true,
          Clock: true,
        },
      },
    })

    expect(wrapper.text()).toContain('2 geladene Belegzeilen')
    expect(wrapper.text()).toContain('Stichprobe, keine Gesamtzählung')
    expect(wrapper.text()).not.toContain('Operation ·')
    expect(wrapper.text()).not.toContain('2 Treffer')
  })

  it('renders collocation chi-square cell scores under the explicit chi2 label', () => {
    const wrapper = mount(ToolCallResult, {
      props: {
        toolCall: {
          id: 't3b',
          name: 'collocate_stats',
          arguments: { term: 'Hase', sort_by: 'chi2_cell' },
          status: 'success',
          result: {
            rows: [
              { word: 'und', f: 5, observed: 5, expected: 1.8, mi: 9.9, chi2_cell: 4.2 },
            ],
          },
        },
      },
      global: {
        plugins: [seedProductPinia()],
      },
    })

    expect(wrapper.text()).toContain('χ²-Zellbeitrag')
    // Numbers follow the interface language (German here, copilotRendererNumbers.test.ts).
    expect(wrapper.text()).toContain('4,200')
    expect(wrapper.text()).toContain('O11 5 · E11 1,80')
    expect(wrapper.text()).not.toContain('MI²')
    expect(wrapper.text()).not.toContain('9,900')
  })

  it('uses the requested logDice score instead of another available statistic', () => {
    const wrapper = mount(ToolCallResult, {
      props: {
        toolCall: {
          id: 't3bb',
          name: 'collocate_stats',
          arguments: { term: 'Hase', sort_by: 'logdice' },
          status: 'success',
          result: { rows: [{ word: 'mag', f: 5, mi: 0.3, chi2_cell: 0.22, logdice: 13.6215 }] },
        },
      },
      global: { plugins: [seedProductPinia()] },
    })

    expect(wrapper.text()).toContain('logDice')
    expect(wrapper.text()).toContain('13,622')
    expect(wrapper.text()).not.toContain('0,300')
  })

  it('renders the requested Delta-P direction instead of silently falling back to MI', () => {
    const wrapper = mount(ToolCallResult, {
      props: {
        toolCall: {
          id: 't3-deltap',
          name: 'collocate_stats',
          arguments: { term: 'Hase', sort_by: 'delta_p_nc' },
          status: 'success',
          result: {
            rows: [{ word: 'Bau', f: 8, mi: 9.9, delta_p_nc: 0.8 }],
          },
        },
      },
      global: { plugins: [seedProductPinia()] },
    })

    expect(wrapper.text()).toContain('ΔP (Knoten→Kollokat)')
    expect(wrapper.text()).toContain('0,800')
    expect(wrapper.text()).not.toContain('9,900')
  })

  it('marks a lemma fallback as a different analysis rather than a surface-form result', () => {
    const wrapper = mount(ToolCallResult, {
      props: {
        toolCall: {
          id: 't3-lemma-fallback',
          name: 'collocate_stats',
          arguments: { term: 'Mensch', sort_by: 'logdice' },
          status: 'success',
          result: {
            requested_term: 'Mensch',
            effective_term: 'cql:[lemma="Mensch"]',
            term_mode: 'lemma_fallback',
            rows: [{ word: 'Gesellschaft', f: 9, logdice: 10.2 }],
          },
        },
      },
      global: { plugins: [seedProductPinia()] },
    })

    expect(wrapper.text()).toContain('Keine Oberflächenform-Analyse')
    expect(wrapper.text()).toContain('Lemma-Abfrage')
  })

  it('marks a historical mi2 tool result as unusable instead of relabelling it', () => {
    const wrapper = mount(ToolCallResult, {
      props: {
        toolCall: {
          id: 't3c',
          name: 'collocate_stats',
          arguments: { term: 'Hase' },
          status: 'success',
          result: { rows: [{ word: 'und', f: 5, measure: 'mi2', score: 4.2 }] },
        },
      },
      global: { plugins: [seedProductPinia()] },
    })

    expect(wrapper.text()).toContain('Nicht interpretierbares Altmaß')
    expect(wrapper.text()).not.toContain('χ²-Zellbeitrag')
  })


  it('marks mutating tool results as not read-only side effects', () => {
    const wrapper = mount(ToolCallResult, {
      props: {
        toolCall: {
          id: 't4',
          name: 'cluster_save',
          arguments: { cluster_id: 'c1' },
          status: 'success',
          result: { status: 'success' },
        },
      },
      global: {
        plugins: [seedProductPinia()],
        stubs: {
          ClusterRenderer: true,
        },
      },
    })

    expect(wrapper.text()).toContain('nicht read-only / Nebenwirkung')
  })

  it('renders metadata_values as field/value evidence with diagnostics', () => {
    const wrapper = mount(ToolCallResult, {
      props: {
        toolCall: {
          id: 'meta-1',
          name: 'metadata_values',
          arguments: { fields: ['model'] },
          status: 'success',
          result: {
            status: 'success',
            available_fields: ['model', 'source'],
            values: {
              model: ['qwen', 'llama'],
            },
            diagnostics: {
              requested_fields: ['model'],
              missing_requested_fields: [],
            },
          },
        },
      },
      global: {
        plugins: [seedProductPinia()],
      },
    })

    expect(wrapper.text()).toContain('Metadatenwerte')
    expect(wrapper.text()).toContain('docset')
    expect(wrapper.text()).toContain('field')
    expect(wrapper.text()).toContain('model')
    expect(wrapper.text()).toContain('qwen')
    expect(wrapper.text()).toContain('requested fields')
  })

  it('renders document_text as text evidence and keeps truncation visible', () => {
    const wrapper = mount(ToolCallResult, {
      props: {
        toolCall: {
          id: 'doc-1',
          name: 'document_text',
          arguments: { doc_id: 7 },
          status: 'success',
          result: {
            status: 'success',
            doc_id: 7,
            text: 'Dies ist ein längerer Dokumentausschnitt zur Prüfung.',
            char_count: 54,
            token_count: 8,
            truncated: true,
            meta: { source: 'test' },
          },
        },
      },
      global: {
        plugins: [seedProductPinia()],
      },
    })

    expect(wrapper.text()).toContain('Dokumenttext')
    expect(wrapper.text()).toContain('Text')
    expect(wrapper.text()).toContain('gekürzt')
    expect(wrapper.text()).toContain('Dies ist ein längerer Dokumentausschnitt')
    expect(wrapper.text()).toContain('doc id')
    expect(wrapper.text()).toContain('token count')
  })

  it('renders parallel_kwic variants instead of a generic success label', () => {
    const wrapper = mount(ToolCallResult, {
      props: {
        toolCall: {
          id: 'parallel-1',
          name: 'parallel_kwic',
          arguments: { pos: 42, keyword: 'Hase' },
          status: 'success',
          result: {
            status: 'success',
            ref_doc: 3,
            base_doc_id: 9,
            variants: [
              {
                doc_id: 9,
                model: 'human',
                text_type: 'human',
                left: 'der',
                kw: 'Hase',
                right: 'läuft',
                matched: true,
                similarity: 1,
              },
              {
                doc_id: 10,
                model: 'qwen',
                text_type: 'ai',
                left: 'ein',
                kw: 'Kaninchen',
                right: 'springt',
                matched: false,
                similarity: 0.73,
              },
            ],
          },
        },
      },
      global: {
        plugins: [seedProductPinia()],
      },
    })

    expect(wrapper.text()).toContain('Parallel-KWIC')
    expect(wrapper.text()).toContain('parallel')
    expect(wrapper.text()).toContain('ref doc')
    expect(wrapper.text()).toContain('qwen')
    expect(wrapper.text()).toContain('Kaninchen')
    expect(wrapper.text()).not.toContain('Erfolgreich')
  })

  it('renders lexical_diversity metrics as backend-provided values', () => {
    const wrapper = mount(ToolCallResult, {
      props: {
        toolCall: {
          id: 'lex-1',
          name: 'lexical_diversity',
          arguments: { docset_id: 'docset-a' },
          status: 'success',
          result: {
            status: 'success',
            ttr: 0.42,
            sttr: 0.38,
            guiraud: 12.5,
            n_tokens: 1000,
            n_types: 420,
            analyst_tokens_only: true,
          },
        },
      },
      global: {
        plugins: [seedProductPinia()],
      },
    })

    expect(wrapper.text()).toContain('Lexikalische Diversität')
    expect(wrapper.text()).toContain('ttr')
    expect(wrapper.text()).toContain('n tokens')
    expect(wrapper.text()).toContain('1.000')
    expect(wrapper.text()).toContain('analyst tokens only')
  })

  it('renders similar_words as interpretative semantic evidence', () => {
    const wrapper = mount(ToolCallResult, {
      props: {
        toolCall: {
          id: 'sim-1',
          name: 'similar_words',
          arguments: { term: 'Hase' },
          status: 'success',
          result: {
            status: 'success',
            term: 'Hase',
            neighbours: [
              { word: 'Kaninchen', score: 0.81, frequency: 12 },
            ],
          },
        },
      },
      global: {
        plugins: [seedProductPinia()],
      },
    })

    expect(wrapper.text()).toContain('Ähnliche Wörter')
    expect(wrapper.text()).toContain('experimentell / interpretativ')
    expect(wrapper.text()).toContain('Kaninchen')
    expect(wrapper.text()).toContain('Semantische Nähe ist interpretativ')
  })

  it('does not render blocked success payloads as computed evidence', () => {
    const wrapper = mount(ToolCallResult, {
      props: {
        toolCall: {
          id: 'blocked-1',
          name: 'frequency_list',
          arguments: { group_by: 'lemma' },
          status: 'success',
          result: {
            blocked: true,
            error: 'Frequenzliste ist für diese Rolle nicht freigegeben.',
            rows: [{ word: 'Hase', f: 3 }],
          },
        },
      },
      global: {
        plugins: [seedProductPinia()],
      },
    })

    expect(wrapper.text()).toContain('nicht als Evidenz freigegeben')
    expect(wrapper.text()).toContain('Frequenzliste ist für diese Rolle nicht freigegeben')
    expect(wrapper.text()).not.toContain('Hase')
    expect(wrapper.text()).not.toContain('angezeigte Evidenzzeilen')
  })

  it('does not render successful tool results as evidence when MCP marks the tool non-dispatchable', () => {
    const pinia = seedProductPinia(productContract())
    const mcpTools = useMcpToolsStore()
    mcpTools.status = 'ready'
    mcpTools.toolStatuses = [{
      name: 'frequency_list',
      status: 'policy_blocked',
      dispatchable: false,
      reason: 'Release-Default-Deny blockiert nicht-read-only Tools ohne explizite Tool-ACL.',
      registered: true,
      visible_product_claimed: true,
      read_only: false,
      concurrency_safe: false,
      runtime_metadata_status: 'missing',
      product_operation_ids: ['analysis.frequency.list'],
      product_capability_ids: ['analysis.frequency'],
      product_effects: ['write'],
      requires_corpus_features: [],
    }]

    const wrapper = mount(ToolCallResult, {
      props: {
        toolCall: {
          id: 'mcp-blocked-1',
          name: 'frequency_list',
          arguments: { group_by: 'word' },
          status: 'success',
          result: {
            status: 'success',
            rows: [{ word: 'Hase', f: 3 }],
          },
        },
      },
      global: {
        plugins: [pinia],
      },
    })

    expect(wrapper.text()).toContain('nicht als Evidenz freigegeben')
    expect(wrapper.text()).toContain('Tool gesperrt')
    expect(wrapper.text()).toContain('derzeit gesperrt und wird nicht als Beleg genutzt')
    expect(wrapper.text()).not.toContain('policy_blocked')
    expect(wrapper.text()).not.toContain('MCP-Runtime')
    expect(wrapper.text()).not.toContain('Hase')
  })

  it('does not render successful tool results as evidence before the Fähigkeitskatalog is loaded', () => {
    const pinia = createPinia()
    setActivePinia(pinia)

    const wrapper = mount(ToolCallResult, {
      props: {
        toolCall: {
          id: 'no-contract-1',
          name: 'frequency_list',
          arguments: { group_by: 'word' },
          status: 'success',
          result: {
            status: 'success',
            rows: [{ word: 'Hase', f: 3 }],
          },
        },
      },
      global: {
        plugins: [pinia],
      },
    })

    expect(wrapper.text()).toContain('nicht als Evidenz freigegeben')
    expect(wrapper.text()).toContain('verfügbaren Funktionen noch geladen')
    expect(wrapper.text()).not.toContain('Hase')
  })

  it('does not render unknown successful tool results as product evidence when a contract is loaded', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = productContract()
    productCapabilities.status = 'ready'

    const wrapper = mount(ToolCallResult, {
      props: {
        toolCall: {
          id: 'unknown-1',
          name: 'wild_backend_tool',
          arguments: { term: 'Hase' },
          status: 'success',
          result: {
            status: 'success',
            rows: [{ word: 'Hase', f: 3 }],
          },
        },
      },
      global: {
        plugins: [pinia],
      },
    })

    expect(wrapper.text()).toContain('nicht als Evidenz freigegeben')
    expect(wrapper.text()).toContain('für diese Installation nicht freigegeben')
    expect(wrapper.text()).not.toContain('angezeigte Evidenzzeilen')
    expect(wrapper.text()).not.toContain('word')
  })

  it('does not render a visible tool as evidence when its ProductOperation is missing', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = productContract({ includeFrequencyOperation: false })
    productCapabilities.status = 'ready'

    const wrapper = mount(ToolCallResult, {
      props: {
        toolCall: {
          id: 'missing-operation-1',
          name: 'frequency_list',
          arguments: { group_by: 'word' },
          status: 'success',
          result: {
            status: 'success',
            rows: [{ word: 'Hase', f: 3 }],
          },
        },
      },
      global: {
        plugins: [pinia],
      },
    })

    expect(wrapper.text()).toContain('nicht als Evidenz freigegeben')
    expect(wrapper.text()).toContain('keine passende CandyConc-Funktion freigegeben')
    expect(wrapper.text()).not.toContain('Hase')
  })

  it('does not render a successful tool result when the owning ProductOperation is unavailable to the session', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = productContract({ frequencyRole: 'admin' })
    productCapabilities.status = 'ready'
    seedUserSession()

    const wrapper = mount(ToolCallResult, {
      props: {
        toolCall: {
          id: 'blocked-operation-1',
          name: 'frequency_list',
          arguments: { group_by: 'word' },
          status: 'success',
          result: {
            status: 'success',
            rows: [{ word: 'Hase', f: 3 }],
          },
        },
      },
      global: {
        plugins: [pinia],
      },
    })

    expect(wrapper.text()).toContain('nicht als Evidenz freigegeben')
    expect(wrapper.text()).toContain('CandyConc-Funktion aktuell gesperrt')
    expect(wrapper.text()).not.toContain('analysis.frequency.list')
    expect(wrapper.text()).not.toContain('Hase')
  })

  it('does not render multi-operation tool results when a linked ProductOperation is unavailable', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = productContract({ extraFrequencyOperationRole: 'admin' })
    productCapabilities.status = 'ready'
    seedUserSession()

    const wrapper = mount(ToolCallResult, {
      props: {
        toolCall: {
          id: 'partial-operation-1',
          name: 'frequency_list',
          arguments: { group_by: 'word' },
          status: 'success',
          result: {
            status: 'success',
            rows: [{ word: 'Hase', f: 3 }],
          },
        },
      },
      global: {
        plugins: [pinia],
      },
    })

    expect(wrapper.text()).toContain('nicht als Evidenz freigegeben')
    expect(wrapper.text()).toContain('CandyConc-Funktion aktuell gesperrt')
    expect(wrapper.text()).not.toContain('analysis.frequency.support')
    expect(wrapper.text()).not.toContain('Hase')
  })

  it('does not render tool results when the linked ProductOperation has no renderable response contract', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = productContract({ frequencyResponseShape: 'unknown' })
    productCapabilities.status = 'ready'
    seedUserSession()

    const wrapper = mount(ToolCallResult, {
      props: {
        toolCall: {
          id: 'unknown-shape-1',
          name: 'frequency_list',
          arguments: { group_by: 'word' },
          status: 'success',
          result: {
            status: 'success',
            rows: [{ word: 'Hase', f: 3 }],
          },
        },
      },
      global: {
        plugins: [pinia],
      },
    })

    expect(wrapper.text()).toContain('nicht als Evidenz freigegeben')
    expect(wrapper.text()).toContain('kein anzeigbares Ergebnisformat')
    expect(wrapper.text()).not.toContain('Hase')
  })

})
