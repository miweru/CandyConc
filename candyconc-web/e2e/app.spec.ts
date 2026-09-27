import { expect, test, type Page } from '@playwright/test'

// The interface language follows the stored preference, without one the
// browser language. Each case sets both, so the expected labels do not depend
// on the locale of the Playwright browser (en-US by default).
const LANGUAGES = {
  de: {
    locale: 'de-DE',
    searchbox: 'Wort oder Phrase',
    tablist: 'Analyse-Tabs',
    mobileNavigation: 'Analyse-Navigation',
    tabs: ['KWIC', 'Frequenz', 'Kollokationen', 'Dispersion'],
    frequency: 'Frequenz',
    semantic: 'Semantik',
    semanticReason: /Embedding-Index/,
  },
  en: {
    locale: 'en-US',
    searchbox: 'Word or phrase',
    tablist: 'Analysis tabs',
    mobileNavigation: 'Analysis navigation',
    tabs: ['KWIC', 'Frequency', 'Collocations', 'Dispersion'],
    frequency: 'Frequency',
    semantic: 'Semantic',
    semanticReason: /embedding index/,
  },
} as const

type Lang = keyof typeof LANGUAGES
type Strings = (typeof LANGUAGES)[Lang]

async function disableOnboarding(page: Page, lang: Lang) {
  await page.addInitScript((language) => {
    localStorage.setItem('candyconc_onboarding_completed', 'true')
    localStorage.setItem(
      'candyconc_seen_features',
      JSON.stringify(['search', 'tabs', 'kwic', 'copilot', 'export', 'export-dialog']),
    )
    localStorage.setItem('candyconc_preferences', JSON.stringify({ language }))
  }, lang)
}

function routeDescriptor(
  path: string,
  methods: string[] = ['GET'],
  requiresCorpusFeatures: string[] = [],
) {
  return {
    path,
    methods,
    mutates: methods.some((method) => method.toUpperCase() !== 'GET'),
    requires_corpus_features: requiresCorpusFeatures,
    access: 'public',
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }
}

function capability(
  id: string,
  title: string,
  area: string,
  path: string,
  methods: string[] = ['GET'],
  requiresCorpusFeatures: string[] = [],
) {
  const route = routeDescriptor(path, methods, requiresCorpusFeatures)
  return {
    id,
    title,
    area,
    maturity: 'stable',
    visibility: 'first_class_ui',
    backend_routes: [route],
    backend_route_descriptors: [route],
    operations: [{
      id: `${id}.smoke`,
      capability_id: id,
      label: title,
      description: '',
      route,
      effects: ['read'],
      surface_slot: `${id}.smoke`,
      priority: 10,
      input_schema_ref: methods.includes('GET') ? 'operation.query_params' : 'operation.body',
      required_context: [],
      response_shape: 'data',
      run_semantics: 'bounded_sync',
      ui_execution_policy: 'contextual_ui',
      requires_parameters: true,
      lifecycle: null,
    }],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
  }
}

function corpusSummary() {
  return {
    name: 'default',
    path: '/tmp/candyconc-e2e-default',
    status: 'ready',
    active: true,
    token_count: 56191,
    doc_count: 2000,
    import_mode: 'fast_index',
    annotation_source: 'local',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: {
      word: true,
      lemma: true,
      pos: true,
      embeddings: false,
      word_similarity: false,
    },
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [
        { id: 'word', cql_attribute: 'word', label: 'Wort', artifacts: ['word'] },
        { id: 'lemma', cql_attribute: 'lemma', label: 'Lemma', artifacts: ['lemma'] },
        { id: 'pos', cql_attribute: 'pos', label: 'POS', artifacts: ['pos'] },
      ],
      frequency_groups: [
        { id: 'word', label: 'Wortform', artifacts: ['word'] },
        { id: 'lemma', label: 'Lemma', artifacts: ['lemma'] },
        { id: 'pos', label: 'POS-Tag', artifacts: ['pos'] },
      ],
      semantic: {
        passage_search: false,
        word_similarity: false,
        sentence_alignment: false,
      },
      alignment: {
        paired: false,
        pair_axes: [],
        pairing_schema: null,
        parallel_groups: false,
        parallel_kwic: false,
      },
    },
  }
}

function productCapabilities() {
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc browser-shell smoke contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
      capabilities: [],
    },
    capabilities: [
      capability('query.kwic', 'KWIC', 'query', '/api/v1/query'),
      capability('analysis.frequency', 'Frequenz', 'analysis', '/api/v1/analysis/frequency_list'),
      capability('analysis.collocations', 'Kollokationen', 'analysis', '/api/v1/analysis/collocates'),
      capability('analysis.dispersion', 'Dispersion', 'analysis', '/api/v1/analysis/dispersion'),
      capability(
        'analysis.semantic_similarity',
        'Semantik',
        'analysis',
        '/api/v1/analysis/embedding_search',
        ['POST'],
        ['semantic.passage_search'],
      ),
      capability('research.copilot_grounding', 'Grounded Copilot', 'copilot', '/api/v1/chat/stream', ['POST']),
      capability('corpus.catalogue', 'Korpuskatalog', 'corpus', '/api/v1/corpora'),
    ],
  }
}

async function mockShellBootApi(page: Page) {
  await page.route('**/*', async (requestRoute) => {
    const path = new URL(requestRoute.request().url()).pathname
    if (!path.startsWith('/api/v1/') && path !== '/mcp/tools') {
      await requestRoute.continue()
      return
    }

    let body: unknown = { status: 'ok' }
    if (path === '/api/v1/auth/dev-token') {
      body = { token: 'e2e-dev-token' }
    } else if (path === '/api/v1/auth/session') {
      body = {
        schema_version: 'auth-session-v1',
        authenticated: true,
        token_present: true,
        username: 'e2e',
        role: 'admin',
        effective_role: 'admin',
        rbac_enabled: false,
        security_mode: 'local-dev',
        release_mode: false,
        unsafe_token_transport: true,
        dev_token_available: true,
        can_access_all_roles: true,
      }
    } else if (path === '/api/v1/capabilities') {
      body = productCapabilities()
    } else if (path === '/api/v1/corpora' || path === '/api/v1/corpora/default/capabilities') {
      const corpus = corpusSummary()
      body = path.endsWith('/capabilities') ? corpus : { corpora: [corpus], count: 1 }
    } else if (path === '/api/v1/analysis/meta_schema') {
      body = {
        schemaVersion: 1,
        corpus: 'default',
        documentCount: 2000,
        indexFingerprint: 'e2e-index',
        metadataSchemaHash: 'e2e-meta',
        metadataFields: [],
        warnings: [],
      }
    } else if (path === '/api/v1/annotations/settings') {
      body = { status: 'ok', multi_coder: false }
    } else if (path === '/api/v1/annotations') {
      body = { annotations: [] }
    } else if (path === '/mcp/tools') {
      body = { tools: [], tool_statuses: [] }
    }

    await requestRoute.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })
  })
}

function analysisTab(page: Page, label: string) {
  return page.getByRole('tab', { name: new RegExp(`^${label}(?:\\s|\\()`) })
}

async function isMobileNavigation(page: Page, strings: Strings) {
  return page.getByRole('navigation', { name: strings.mobileNavigation }).isVisible()
}

async function navigationItem(page: Page, strings: Strings, label: string) {
  if (await isMobileNavigation(page, strings)) {
    return page.getByRole('navigation', { name: strings.mobileNavigation })
      .getByRole('listitem', { name: new RegExp(`^${label}(?:\\s|$)`) })
  }
  return analysisTab(page, label)
}

async function expectSelectedNavigationItem(page: Page, strings: Strings, item: ReturnType<typeof analysisTab>, selected: boolean) {
  if (await isMobileNavigation(page, strings)) {
    if (selected) await expect(item).toHaveClass(/(^|\s)active(\s|$)/)
    else await expect(item).not.toHaveClass(/(^|\s)active(\s|$)/)
    return
  }
  await expect(item).toHaveAttribute('aria-selected', String(selected))
}

// This CI smoke owns browser-shell wiring only. The live backend smoke covers
// actual KWIC, analysis, import, annotation, export, and Copilot behaviour.
for (const lang of ['de', 'en'] as const) {
  const strings = LANGUAGES[lang]

  test.describe(`CandyConc App (${lang})`, () => {
    test.use({ locale: strings.locale })

    test.beforeEach(async ({ page }) => {
      await disableOnboarding(page, lang)
      await mockShellBootApi(page)
      await page.goto('/')
    })

    test('boots from the capability contract and exposes the primary research navigation', async ({ page }) => {
      await expect(page.getByRole('heading', { name: 'CandyConc' })).toBeVisible()
      await expect(page.getByRole('searchbox', { name: strings.searchbox })).toBeVisible()
      if (await isMobileNavigation(page, strings)) {
        await expect(page.getByRole('navigation', { name: strings.mobileNavigation })).toBeVisible()
      } else {
        await expect(page.getByRole('tablist', { name: strings.tablist })).toBeVisible()
      }

      for (const label of strings.tabs) {
        await expect(await navigationItem(page, strings, label)).toBeVisible()
      }

      const semantic = await navigationItem(page, strings, strings.semantic)
      await expect(semantic).toHaveAttribute('aria-disabled', 'true')
      await expect(semantic).toHaveAttribute('title', strings.semanticReason)
    })

    test('switches a capability-enabled analysis tab without bypassing the UI contract', async ({ page }) => {
      const kwic = await navigationItem(page, strings, 'KWIC')
      const frequency = await navigationItem(page, strings, strings.frequency)

      await frequency.click()

      await expectSelectedNavigationItem(page, strings, frequency, true)
      await expectSelectedNavigationItem(page, strings, kwic, false)
    })
  })
}
