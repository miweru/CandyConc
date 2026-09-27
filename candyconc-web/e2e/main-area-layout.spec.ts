import { expect, test, type Page } from '@playwright/test'

// The main area loses 320 to 384 px to a docked copilot. At a 900 px window
// the analysis tabs shrank below their labels (the global button min-width
// allowed it), labels ran into each other and the icons collapsed to 0 px.
// The search input kept its intrinsic width and pushed the search button out
// of the search bar onto "Filter / Subcorpus". At 1280 px with the copilot
// docked, and at 900 px without it, the icons were squeezed to a few pixels.

type Lang = 'de' | 'en'

function capability(id: string, path: string, methods: string[] = ['GET'], requiresCorpusFeatures: string[] = []) {
  const route = {
    path,
    methods,
    mutates: methods.some((method) => method !== 'GET'),
    requires_corpus_features: requiresCorpusFeatures,
    access: 'public',
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }
  return {
    id,
    title: id,
    area: id.split('.')[0],
    maturity: 'stable',
    visibility: 'first_class_ui',
    backend_routes: [route],
    backend_route_descriptors: [route],
    operations: [{
      id: `${id}.smoke`,
      capability_id: id,
      label: id,
      description: '',
      route,
      effects: ['read'],
      surface_slot: `${id}.smoke`,
      priority: 10,
      input_schema_ref: 'operation.query_params',
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
    token_count: 403284,
    doc_count: 65,
    import_mode: 'fast_index',
    annotation_source: 'local',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: { word: true, lemma: true, pos: true, embeddings: false, word_similarity: false },
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [
        { id: 'word', cql_attribute: 'word', label: 'Word form', artifacts: ['word'] },
        { id: 'lemma', cql_attribute: 'lemma', label: 'Lemma', artifacts: ['lemma'] },
        { id: 'pos', cql_attribute: 'pos', label: 'POS', artifacts: ['pos'] },
      ],
      frequency_groups: [{ id: 'word', label: 'Word form', artifacts: ['word'] }],
      semantic: { passage_search: false, word_similarity: false, sentence_alignment: false },
      alignment: { paired: false, pair_axes: [], pairing_schema: null, parallel_groups: false, parallel_kwic: false },
    },
  }
}

async function bootShell(page: Page, lang: Lang) {
  await page.addInitScript((language) => {
    localStorage.setItem('candyconc_onboarding_completed', 'true')
    localStorage.setItem('candyconc_seen_features', JSON.stringify(['search', 'tabs', 'kwic', 'copilot', 'export', 'export-dialog']))
    localStorage.setItem('candyconc_preferences', JSON.stringify({ language }))
  }, lang)
  await page.route('**/*', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/v1/') && path !== '/mcp/tools') {
      await route.continue()
      return
    }
    let body: unknown = { status: 'ok' }
    if (path === '/api/v1/auth/dev-token') body = { token: 'e2e-dev-token' }
    else if (path === '/api/v1/capabilities') {
      body = {
        version: 'product-capabilities-v1',
        scope: 'CandyConc main area layout contract',
        fingerprint_sha256: 'a'.repeat(64),
        cqlf_capability_contract: { version: 'cqlf-capabilities-v1', current_level: '2-', fingerprint_sha256: 'b'.repeat(64), capabilities: [] },
        capabilities: [
          capability('query.kwic', '/api/v1/query'),
          capability('query.corpus_reader', '/api/v1/docs/list'),
          capability('analysis.frequency', '/api/v1/analysis/frequency_list'),
          capability('analysis.collocations', '/api/v1/analysis/collocates'),
          capability('analysis.collocation_network', '/api/v1/analysis/collocation_network'),
          capability('analysis.dispersion', '/api/v1/analysis/dispersion'),
          capability('analysis.semantic_similarity', '/api/v1/analysis/embedding_search', ['POST'], ['semantic.passage_search']),
          capability('analysis.ngrams', '/api/v1/analysis/ngrams'),
          capability('analysis.contrast', '/api/v1/analysis/contrast'),
          capability('analysis.keyness', '/api/v1/analysis/keyness'),
          capability('analysis.trend', '/api/v1/analysis/trend'),
          capability('research.copilot_grounding', '/api/v1/chat/stream', ['POST']),
          capability('corpus.catalogue', '/api/v1/corpora'),
        ],
      }
    } else if (path === '/api/v1/corpora' || path === '/api/v1/corpora/default/capabilities') {
      const corpus = corpusSummary()
      body = path.endsWith('/capabilities') ? corpus : { corpora: [corpus], count: 1 }
    } else if (path === '/mcp/tools') body = { tools: [], tool_statuses: [] }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/')
  await expect(page.locator('.tab-nav .tab-btn').first()).toBeVisible()
}

async function dockCopilot(page: Page, lang: Lang) {
  await page.getByRole('button', { name: lang === 'en' ? /^Open copilot/ : /^Copilot öffnen/ }).last().click()
  const panel = page.locator('.copilot-panel')
  await expect(panel).toBeVisible()
  await panel.getByRole('button', { name: lang === 'en' ? 'Dock' : 'Andocken', exact: true }).click()
  await expect(page.locator('.copilot-sidebar .copilot-panel')).toBeVisible()
}

interface Box { left: number, right: number, top: number, bottom: number }

async function measure(page: Page) {
  return page.evaluate(() => {
    const box = (el: Element | null): Box | null => {
      if (!el) return null
      const r = el.getBoundingClientRect()
      return { left: r.left, right: r.right, top: r.top, bottom: r.bottom }
    }
    const nav = document.querySelector('.tab-nav')!
    const tabs = [...nav.querySelectorAll('.tab-btn')].map((button) => {
      const icon = button.querySelector('svg')
      return {
        name: button.getAttribute('aria-label') ?? button.textContent?.trim() ?? '',
        box: box(button)!,
        scrollWidth: button.scrollWidth,
        clientWidth: button.clientWidth,
        iconWidth: icon ? icon.getBoundingClientRect().width : 16,
      }
    })
    return {
      nav: box(nav)!,
      navScrollWidth: nav.scrollWidth,
      tabs,
      bar: box(document.querySelector('.search-bar')),
      submit: box(document.querySelector('.submit-btn')),
      filter: box(document.querySelector('.workbar-filter-button')),
      pageScrollWidth: document.documentElement.scrollWidth,
      windowWidth: window.innerWidth,
    }
  })
}

function overlaps(a: Box, b: Box) {
  return a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5
}

async function expectTabsFit(page: Page) {
  const m = await measure(page)
  for (const tab of m.tabs) {
    expect(tab.scrollWidth, `${tab.name} content fits its tab`).toBeLessThanOrEqual(tab.clientWidth + 1)
    expect(tab.iconWidth, `${tab.name} icon keeps its size`).toBeGreaterThanOrEqual(15.5)
    expect(tab.box.right, `${tab.name} lies inside the tab bar`).toBeLessThanOrEqual(m.nav.right + 1)
  }
  for (let i = 0; i < m.tabs.length; i += 1) {
    for (let j = i + 1; j < m.tabs.length; j += 1) {
      expect(overlaps(m.tabs[i]!.box, m.tabs[j]!.box), `${m.tabs[i]!.name} and ${m.tabs[j]!.name} overlap`).toBe(false)
    }
  }
}

async function expectSearchBarFits(page: Page) {
  const m = await measure(page)
  expect(m.bar && m.submit && m.filter).toBeTruthy()
  expect(m.submit!.left, 'search button inside the search bar').toBeGreaterThanOrEqual(m.bar!.left - 1)
  expect(m.submit!.right, 'search button inside the search bar').toBeLessThanOrEqual(m.bar!.right + 1)
  expect(overlaps(m.submit!, m.filter!), 'search button overlaps the filter button').toBe(false)
  expect(m.pageScrollWidth, 'no horizontal page scroll').toBeLessThanOrEqual(m.windowWidth + 1)
}

test.describe('main area layout', () => {
  test.skip(({ isMobile }) => isMobile, 'The tab bar and the docked copilot are desktop surfaces.')

  for (const lang of ['de', 'en'] as const) {
    for (const width of [900, 1280, 1440]) {
      for (const docked of [true, false]) {
        const where = `${width} px ${docked ? 'with a docked copilot' : 'without the copilot'} (${lang})`

        test(`tabs fit at ${where}`, async ({ page }) => {
          await page.setViewportSize({ width, height: 900 })
          await bootShell(page, lang)
          if (docked) await dockCopilot(page, lang)
          await expectTabsFit(page)
        })

        test(`search bar fits at ${where}`, async ({ page }) => {
          await page.setViewportSize({ width, height: 900 })
          await bootShell(page, lang)
          await page.locator('[data-search-input]').fill('freedom')
          if (docked) await dockCopilot(page, lang)
          await expectSearchBarFits(page)
        })
      }
    }
  }

  test('a tab that loses its label keeps its name for assistive technology', async ({ page }) => {
    await page.setViewportSize({ width: 900, height: 900 })
    await bootShell(page, 'en')
    await dockCopilot(page, 'en')
    await expect(page.getByRole('tab', { name: /^Frequency \(Alt\+2\)$/ })).toBeVisible()
    await expect(page.getByRole('tab', { name: /^KWIC \(Alt\+1\)$/ })).toContainText('KWIC')
  })
})
