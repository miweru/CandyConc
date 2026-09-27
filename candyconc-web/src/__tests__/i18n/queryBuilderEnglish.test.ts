/**
 * The query builder with an English interface: quick search, studio, node
 * and metadata editors, assistant panel and the messages of the AST
 * validator render in English, with no German text left over.
 *
 * Example terms come from the active corpus (queryBuilderCorpusExamples.test.ts).
 * This fixture corpus offers no frequency list, so the quick search shows no
 * example chips and a plain placeholder. Example queries in the studio use the
 * catalog words of the interface language. The scan skips <code> elements and
 * the two placeholders that embed an example, and checks their English frame.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import QueryBuilder from '@/components/search/QueryBuilder.vue'
import QueryBuilderStudio from '@/components/search/query-builder/QueryBuilderStudio.vue'
import CqlSuggestionsPanel from '@/components/search/query-builder/CqlSuggestionsPanel.vue'
import { applyLocale } from '@/i18n/locale'
import {
  hydrateBuilderState,
  metaExprExplanation,
  createMetaGroup,
  quantifierExplanation,
  collectBuilderOutline,
  createBuilderNode,
} from '@/lib/queryBuilder/ast'
import { buildSimpleSearchSummary, createDefaultSimpleSearchState } from '@/lib/queryBuilder/simple'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import type { CorpusSummary, ProductCapabilityContract } from '@/api/client'

const getProductCapabilities = vi.fn()
const getMcpTools = vi.fn()

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: (...args: unknown[]) => getProductCapabilities(...args),
    getMcpTools: (...args: unknown[]) => getMcpTools(...args),
  }
})

if (!('scrollIntoView' in HTMLElement.prototype)) {
  // @ts-expect-error augmenting prototype for jsdom
  HTMLElement.prototype.scrollIntoView = function scrollIntoView() {}
}

/** Umlauts, sharp s and German words that occur in this namespace. */
const GERMAN =
  /[äöüÄÖÜß]|\b(und|oder|der|die|das|den|nicht|mit|wird|werden|nach|oben|unten|Suche|Suchen|Wortform|Wortformen|Bedingung|Knoten|Teil|Teile|Optionen|einfügen|verschieben|entfernen|ziehen|Wert|Vorlage|Schnell|Arbeitsverlauf|Wiederholen|leer|Quelle|Quellen|Beispiele|Tokenfeld|Sequenz|Wiederholung|Metadaten|Ausdruck|Gruppe|UND|ODER|dann|offen|Zahl|Alle|anzeigen|aktiv|leeren|Schritt|Schritten|Vorschau|Startvorlagen|Abfrage|Begriffe|Assistent|Feld|Attribut|Karte|Hier|Auswahl|hierhin|Spanne|Mal|Kontext|verfügbar|geladen)\b|z\. B\./

const EXAMPLE_PLACEHOLDERS = new Set(['quick-search-term', 'cql-direct-input'])

/**
 * Visible text nodes and labelling attributes, without corpus example data.
 * Spans in backticks inside explanations are query syntax and examples.
 */
function interfaceTexts(root: Element): string[] {
  const clone = root.cloneNode(true) as Element
  clone.querySelectorAll('code, .simple-example-chip').forEach((node) => node.remove())
  const texts: string[] = []
  const walker = document.createTreeWalker(clone, NodeFilter.SHOW_TEXT)
  let current = walker.nextNode()
  while (current) {
    texts.push(current.textContent ?? '')
    current = walker.nextNode()
  }
  clone.querySelectorAll('*').forEach((node) => {
    for (const attr of ['aria-label', 'title', 'data-help', 'placeholder']) {
      const value = node.getAttribute(attr)
      if (!value) continue
      if (attr === 'placeholder' && EXAMPLE_PLACEHOLDERS.has(node.id)) continue
      texts.push(value)
    }
  })
  return texts
    .map((text) => text.replace(/`[^`]*`/g, ' ').replace(/\s+/g, ' ').trim())
    .filter(Boolean)
}

function germanLeftovers(root: Element): string[] {
  return interfaceTexts(root).filter((text) => GERMAN.test(text))
}

function corpus(): CorpusSummary {
  return {
    name: 'default',
    path: '/corpora/default',
    token_count: 1000,
    doc_count: 12,
    import_mode: 'generic',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    // No token attribute descriptors: the labels come from the interface's
    // own fallback options, not from the server.
    capabilities: { lemma_lex: true, pos_lex: true },
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [],
      frequency_groups: [],
      semantic: { passage_search: false, word_similarity: true, sentence_alignment: false },
      alignment: { paired: false, pair_axes: [], pairing_schema: null, parallel_groups: false, parallel_kwic: false },
    },
  }
}

function contractWithoutDiagnostics(): ProductCapabilityContract {
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [],
  }
}

const wrappers: Array<ReturnType<typeof mount>> = []

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  const contract = contractWithoutDiagnostics()
  getProductCapabilities.mockResolvedValue(contract)
  getMcpTools.mockResolvedValue({ tools: [] })
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.contract = contract
  productCapabilities.status = 'ready'
  const corpusCapabilities = useCorpusCapabilitiesStore()
  corpusCapabilities.corpora = [corpus()]
  corpusCapabilities.loaded = true
  applyLocale('en')
})

afterEach(() => {
  while (wrappers.length) wrappers.pop()?.unmount()
})

async function clickButton(wrapper: ReturnType<typeof mount>, selector: string, text: string) {
  const button = wrapper.findAll(selector).find((candidate) => candidate.text().includes(text))
  expect(button, `${selector} with "${text}"`).toBeTruthy()
  await button!.trigger('click')
  await flushPromises()
}

describe('query builder in English', () => {
  it('labels the quick search in English and leaves no German text', async () => {
    const wrapper = mount(QueryBuilder, { props: { modelValue: '' }, attachTo: document.body })
    wrappers.push(wrapper)
    await flushPromises()

    const text = wrapper.text()
    for (const label of [
      'Quick',
      'no query syntax',
      'Build a matching search quickly',
      'Token value or phrase',
      'All word forms',
      'Similar words',
      'What to search for',
      'Token attribute',
      'Suited to a specific word form or a fixed word sequence.',
      'Narrow down (optional)',
      'Show filters',
      'How the app runs this search',
      'No search term yet.',
      '(empty)',
    ]) {
      expect(text).toContain(label)
    }
    expect(wrapper.find('[role="radiogroup"]').attributes('aria-label')).toBe('Query builder mode')
    // Without corpus examples: no example chips and no invented example term.
    expect(wrapper.find('.simple-example-row').exists()).toBe(false)
    expect(wrapper.find('#quick-search-term').attributes('placeholder')).toBe('Search term')
    expect(germanLeftovers(wrapper.element)).toEqual([])

    // The filters are the metadata fields of the corpus. This fixture offers no
    // schema, the field names themselves are corpus data (queryBuilderSchemaFilters.test.ts).
    await clickButton(wrapper, '.simple-link-btn', 'Show filters')
    for (const label of ['Hide filters', 'The metadata fields of the corpus are not available.', 'Clear filters']) {
      expect(wrapper.text()).toContain(label)
    }
    expect(germanLeftovers(wrapper.element)).toEqual([])

    await wrapper.find('#quick-search-token-attribute').setValue('pos')
    await wrapper.find('#quick-search-term').setValue('NN')
    await flushPromises()
    expect(wrapper.text()).toContain('Search POS values')
    expect(wrapper.text()).toContain('Simple search on the corpus attribute POS.')
    expect(wrapper.text()).toContain('Search for the POS value "NN".')
    expect(germanLeftovers(wrapper.element)).toEqual([])

    await clickButton(wrapper, '.simple-intent-card', 'Similar words')
    await wrapper.find('#quick-search-term').setValue('Krise')
    await flushPromises()
    expect(wrapper.text()).toContain('How broad should the similarity be?')
    expect(wrapper.text()).toContain('Top 20 similar words')
    expect(wrapper.text()).toContain('Search for words similar to "Krise" (top 20).')
    expect(germanLeftovers(wrapper.element)).toEqual([])
  })

  it('relabels a mounted builder when the language changes', async () => {
    applyLocale('de')
    const wrapper = mount(QueryBuilder, { props: { modelValue: '' }, attachTo: document.body })
    wrappers.push(wrapper)
    await flushPromises()
    expect(wrapper.text()).toContain('Tokenwert oder Phrase')

    applyLocale('en')
    await flushPromises()
    expect(wrapper.text()).toContain('Token value or phrase')
    expect(wrapper.text()).toContain('No search term yet.')
    expect(germanLeftovers(wrapper.element)).toEqual([])
  })

  it('explains the quick search in English, with filters and plural forms', () => {
    expect(buildSimpleSearchSummary({
      ...createDefaultSimpleSearchState(),
      term: 'Hase',
      filters: { source: 'mlsum', register: 'news' },
    })).toBe('Search for the exact word form "Hase", restricted to source "mlsum" and register "news".')
    expect(buildSimpleSearchSummary({
      ...createDefaultSimpleSearchState(),
      intent: 'lemma',
      term: 'gehen',
      filters: { register: 'news' },
    })).toBe('Search for all word forms of "gehen", restricted to register "news".')
    expect(createDefaultSimpleSearchState().tokenAttributeLabel).toBe('Word form')
  })

  it('labels the studio, its node and metadata editors in English', async () => {
    const wrapper = mount(QueryBuilderStudio, {
      props: { modelValue: '', initialMode: 'advanced', embeddedStudio: true },
      attachTo: document.body,
    })
    wrappers.push(wrapper)
    await flushPromises()

    const text = wrapper.text()
    for (const label of [
      'Query studio',
      'Switch to quick mode',
      'Exact query mapping',
      'Token clauses',
      'Starter templates',
      'Visual query builder',
      'Token clause [...]',
      'Enter query directly',
      'History',
      'Undo',
      'Redo',
      'Initial state',
      'Query preview',
      'Search',
    ]) {
      expect(text).toContain(label)
    }
    expect(wrapper.find('.cql-textarea').attributes('placeholder')).toMatch(/^e\.g\. where\(/)
    expect(germanLeftovers(wrapper.element)).toEqual([])

    // A sequence shows the token condition cards, slots and reorder controls.
    await clickButton(wrapper, '.starter-card', 'Sequence')
    expect(wrapper.text()).toContain('Template: Sequence')
    expect(wrapper.text()).toContain('Part 1')
    expect(wrapper.text()).toContain('Condition 1')
    expect(wrapper.text()).toContain('Insert here')
    expect(wrapper.text()).toContain('Add condition')
    expect(wrapper.find('[data-role="condition-attr"]').attributes('placeholder')).toBe('Attribute, e.g. word')
    expect(germanLeftovers(wrapper.element)).toEqual([])

    // The operator "in" switches a condition to set values.
    await wrapper.find('.condition-grid select').setValue('in')
    await flushPromises()
    expect(wrapper.text()).toContain('Set condition:')
    expect(wrapper.find('[data-role="set-value-input"]').attributes('placeholder')).toBe('Set value')
    expect(germanLeftovers(wrapper.element)).toEqual([])

    // A repetition inserted into a slot.
    await wrapper.find('.structured-insert-btn').trigger('click')
    await clickButton(wrapper, '.structured-insert-actions .ghost-action', 'Repetition')
    expect(wrapper.text()).toContain('Optional: ?')
    expect(wrapper.text()).toContain('open')
    expect(germanLeftovers(wrapper.element)).toEqual([])

    // where(...) shows the metadata expression editor.
    await clickButton(wrapper, '.starter-card', 'where(..., ...)')
    expect(wrapper.text()).toContain('Metadata expression')
    expect(wrapper.text()).toContain('Parts are joined with AND (&).')
    expect(wrapper.text()).toContain('AND group')
    expect(germanLeftovers(wrapper.element)).toEqual([])
  })

  it('labels the query assistant and its suggestions in English', () => {
    const wrapper = mount(CqlSuggestionsPanel, {
      props: {
        isSuggesting: true,
        analysisErrors: [],
        analysisWarnings: [],
        diagnosticsStatus: 'unavailable',
        diagnosticsError: 'Query diagnostics are not enabled at the moment.',
        focusedMode: 'diagnostics',
        salientSuggestions: [{ text: '[lemma="$1"]', hint: 'token lemma equals', hasPlaceholders: true, kind: 'completion' }],
        otherCompletionSuggestions: [{ text: 'within(<s>, $1)', hint: 'wrapper within sentence', kind: 'completion' }],
        fixSuggestions: [{ text: '[word="x"]', kind: 'fix' }],
      },
    })
    wrappers.push(wrapper)

    const text = wrapper.text()
    for (const label of [
      'Query assistant',
      'Inserts without running',
      'Focus: check query.',
      'Server diagnostics not available.',
      'Loading suggestions…',
      'Key query building blocks',
      'Insert lemma condition',
      'Replace placeholders ($1, $2)',
      'More completions',
      'Insert within(<s>, ...)',
      'Fixes',
      'Fix',
    ]) {
      expect(text).toContain(label)
    }
    expect(germanLeftovers(wrapper.element)).toEqual([])
  })

  it('reports validator messages and structure details in English', () => {
    expect(hydrateBuilderState(null).unsupportedReason).toBe('The server returned no builder structure.')
    expect(hydrateBuilderState({ type: 'within', scope: 'p', node: { type: 'tok', conds: [] } }).unsupportedReason)
      .toBe('within supports only <s> or <doc>.')
    expect(hydrateBuilderState({ type: 'tok', conds: [{ attr: 'word', op: 'in', value: 'x' }] }).unsupportedReason)
      .toBe('Set conditions need a list of values.')
    expect(quantifierExplanation(1, 1)).toBe('Exactly 1 time: {1}')
    expect(quantifierExplanation(3, 3)).toBe('Exactly 3 times: {3}')
    expect(metaExprExplanation(createMetaGroup('or'))).toBe(
      'Boolean OR group for metadata. The structure corresponds exactly to `a | b | c`.',
    )
    const outline = collectBuilderOutline(createBuilderNode('seq'))
    expect(outline[0]).toMatchObject({ label: 'Sequence', detail: '2 parts' })
    expect(outline[1]).toMatchObject({ label: 'Token clause [...]', detail: '1 condition' })
  })
})
