import { readFileSync } from 'node:fs'
import { expect, test, type APIRequestContext, type ConsoleMessage, type Dialog, type Download, type Page } from '@playwright/test'

test.skip(
  process.env.CANDYCONC_LIVE_BACKEND_SMOKE !== '1',
  'Backend-UI-Live-Smoke läuft nur mit CANDYCONC_LIVE_BACKEND_SMOKE=1.',
)

const KWIC_SMOKE_TERM = process.env.CANDYCONC_LIVE_SMOKE_TERM?.trim() || 'Hase'
const KWIC_SMOKE_MATCH = new RegExp(KWIC_SMOKE_TERM.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i')
const KWIC_SMOKE_EXPECTED_COUNT = Number(process.env.CANDYCONC_LIVE_SMOKE_EXPECTED_COUNT ?? '8')
const FREQUENCY_SMOKE_ITEM = process.env.CANDYCONC_LIVE_SMOKE_FREQUENCY_ITEM?.trim() || 'Hase'
const FREQUENCY_SMOKE_EXPECTED_COUNT = Number(process.env.CANDYCONC_LIVE_SMOKE_FREQUENCY_COUNT ?? '8')
const NGRAM_SMOKE_ITEM = process.env.CANDYCONC_LIVE_SMOKE_NGRAM_ITEM?.trim() || 'Der Hase'
const NGRAM_SMOKE_EXPECTED_COUNT = Number(process.env.CANDYCONC_LIVE_SMOKE_NGRAM_COUNT ?? '6')
const NGRAM_SMOKE_EXPECTED_CANDIDATES = Number(process.env.CANDYCONC_LIVE_SMOKE_NGRAM_CANDIDATES ?? '13')
const COLLOCATION_SMOKE_ITEM = process.env.CANDYCONC_LIVE_SMOKE_COLLOCATION_ITEM?.trim() || 'mag'
const COLLOCATION_SMOKE_EXPECTED_FREQ = Number(process.env.CANDYCONC_LIVE_SMOKE_COLLOCATION_FREQ ?? '5')
const COLLOCATION_SMOKE_EXPECTED_EXPECTED = Number(process.env.CANDYCONC_LIVE_SMOKE_COLLOCATION_EXPECTED ?? '4.05')
const COLLOCATION_SMOKE_EXPECTED_CHI2_CELL = Number(process.env.CANDYCONC_LIVE_SMOKE_COLLOCATION_CHI2_CELL ?? '0.22')
const COLLOCATION_SMOKE_EXPECTED_CANDIDATES = Number(process.env.CANDYCONC_LIVE_SMOKE_COLLOCATION_CANDIDATES ?? '3')
const KEYNESS_SMOKE_TERM = process.env.CANDYCONC_LIVE_SMOKE_KEYNESS_TERM?.trim() || 'Karotte'
const KEYNESS_SMOKE_ITEM = process.env.CANDYCONC_LIVE_SMOKE_KEYNESS_ITEM?.trim() || 'mag'
const KEYNESS_SMOKE_EXPECTED_COUNT = Number(process.env.CANDYCONC_LIVE_SMOKE_KEYNESS_COUNT ?? '5')
const KEYNESS_SMOKE_EXPECTED_CANDIDATES = Number(process.env.CANDYCONC_LIVE_SMOKE_KEYNESS_CANDIDATES ?? '4')
// `whole` is the disjoint remainder of the target docset, not the overlapping full corpus.
const KEYNESS_SMOKE_EXPECTED_TARGET_RAW_TOTAL = Number(process.env.CANDYCONC_LIVE_SMOKE_KEYNESS_TARGET_RAW_TOTAL ?? '25')
const KEYNESS_SMOKE_EXPECTED_REFERENCE_RAW_TOTAL = Number(process.env.CANDYCONC_LIVE_SMOKE_KEYNESS_REFERENCE_RAW_TOTAL ?? '17')
// Keyness excludes the five target and three reference sentence-ending punctuation tokens.
const KEYNESS_SMOKE_EXPECTED_TARGET_TOTAL = Number(process.env.CANDYCONC_LIVE_SMOKE_KEYNESS_TARGET_TOTAL ?? '20')
const KEYNESS_SMOKE_EXPECTED_REFERENCE_TOTAL = Number(process.env.CANDYCONC_LIVE_SMOKE_KEYNESS_REFERENCE_TOTAL ?? '14')
const KEYNESS_SMOKE_EXPECTED_REFERENCE_COUNT = Number(process.env.CANDYCONC_LIVE_SMOKE_KEYNESS_REFERENCE_COUNT ?? '0')
// Independently: O=[[5,15],[0,14]], E_ij=row_i*col_j/34; G²=2Σ O_ij ln(O_ij/E_ij), 0 ln(0)=0.
const KEYNESS_SMOKE_EXPECTED_LL_SIGNED = Number(process.env.CANDYCONC_LIVE_SMOKE_KEYNESS_LL_SIGNED ?? '5.9015726255901395')
// Δpmw=(5/20 - 0/14)*1,000,000 over the same analyzed token populations.
const KEYNESS_SMOKE_EXPECTED_DIFF_PM = Number(process.env.CANDYCONC_LIVE_SMOKE_KEYNESS_DIFF_PM ?? '250000')
const WORDSKETCH_SMOKE_RELATION = process.env.CANDYCONC_LIVE_SMOKE_WORDSKETCH_RELATION?.trim() || 'sb_rev'
const WORDSKETCH_SMOKE_LABEL = process.env.CANDYCONC_LIVE_SMOKE_WORDSKETCH_LABEL?.trim() || 'Subjekt von'
const WORDSKETCH_SMOKE_ITEM = process.env.CANDYCONC_LIVE_SMOKE_WORDSKETCH_ITEM?.trim() || 'mag'
const WORDSKETCH_SMOKE_EXPECTED_FREQ = Number(process.env.CANDYCONC_LIVE_SMOKE_WORDSKETCH_FREQ ?? '5')
const WORDSKETCH_SMOKE_EXPECTED_LOGDICE = Number(process.env.CANDYCONC_LIVE_SMOKE_WORDSKETCH_LOGDICE ?? '13.6215')
const ANNOTATION_SMOKE_NOTE = process.env.CANDYCONC_LIVE_SMOKE_ANNOTATION_NOTE?.trim() || 'Live-Smoke-Annotation: Hase geprüft'
const COPILOT_SMOKE_PROMPT = process.env.CANDYCONC_LIVE_SMOKE_COPILOT_PROMPT?.trim() || 'Wie viele Treffer hat Hase?'
const DISPERSION_SMOKE_EXPECTED_OFFSETS = (process.env.CANDYCONC_LIVE_SMOKE_DISPERSION_OFFSETS ?? '1,7,15,18,23,28,33,38')
  .split(',')
  .map((value) => Number(value.trim()))
  .filter((value) => Number.isFinite(value))

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

// The smoke reads German labels. The interface language follows the stored
// preference, without one the browser language (en-US in Playwright).
async function disableOnboarding(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('candyconc_onboarding_completed', 'true')
    localStorage.setItem(
      'candyconc_seen_features',
      JSON.stringify(['search', 'tabs', 'kwic', 'copilot', 'export', 'export-dialog']),
    )
    localStorage.setItem('candyconc_preferences', JSON.stringify({ language: 'de' }))
  })
}

async function openTab(page: Page, label: string) {
  const name = new RegExp(`^${escapeRegExp(label)}(?:\\s|$|\\()`)
  const tab = page.getByRole('tab', { name }).first()
  if (await tab.count()) {
    await expect(tab).toBeVisible()
    await tab.click()
    return
  }
  await page.getByRole('button', { name: /^Weitere Tabs/ }).click()
  const menuItem = page.getByRole('menuitem', { name }).first()
  await expect(menuItem).toBeVisible()
  await menuItem.click()
}

async function openExportDialog(page: Page) {
  await page.locator('button[title="Exportieren"]').first().click()
  await page.getByRole('menuitem', { name: 'Als CSV exportieren' }).click()
  const dialog = page.getByRole('dialog', { name: 'Export' })
  await expect(dialog).toBeVisible()
  return dialog
}

async function downloadText(download: Download): Promise<string> {
  const path = await download.path()
  expect(path).toBeTruthy()
  return readFileSync(path!, 'utf8')
}

function dataCsvRows(text: string) {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('#'))
  return lines.slice(1)
}

function deScore(value: number) {
  return value.toLocaleString('de-DE', { minimumFractionDigits: 3, maximumFractionDigits: 3 })
}

async function exportVisibleDialog(page: Page) {
  const dialog = page.getByRole('dialog', { name: 'Export' })
  const downloadPromise = page.waitForEvent('download')
  await dialog.getByRole('button', { name: 'Exportieren', exact: true }).click()
  return downloadText(await downloadPromise)
}

function backendApiBase(): string {
  return process.env.CANDYCONC_BACKEND_URL ?? 'http://127.0.0.1:8010/api/v1'
}

async function waitForImportDone(request: APIRequestContext, jobId: string) {
  const deadline = Date.now() + 180_000
  let lastStatus = 'unknown'
  while (Date.now() < deadline) {
    const response = await request.get(`${backendApiBase()}/corpora/imports/${encodeURIComponent(jobId)}`)
    if (response.ok()) {
      const snapshot = await response.json() as {
        status?: string
        error?: string
        message?: string
        stdout_tail?: string
        stderr_tail?: string
      }
      lastStatus = String(snapshot.status ?? '')
      if (lastStatus === 'done') return
      if (['error', 'failed', 'cancelled'].includes(lastStatus)) {
        throw new Error([
          `Importjob ${jobId} endete mit Status ${lastStatus}.`,
          snapshot.error || snapshot.message || '',
          snapshot.stderr_tail || snapshot.stdout_tail || '',
        ].filter(Boolean).join('\n'))
      }
    } else {
      lastStatus = `http:${response.status()}`
    }
    await new Promise((resolve) => setTimeout(resolve, lastStatus === 'running' ? 2_000 : 1_000))
  }
  throw new Error(`Importjob ${jobId} wurde nicht rechtzeitig fertig; letzter Status: ${lastStatus}`)
}

test.describe.configure({ mode: 'serial' })

test.describe('Backend-UI live smoke', () => {
  test.use({ locale: 'de-DE' })

  test.beforeEach(async ({ page }) => {
    await disableOnboarding(page)
  })

  test('loads the real capability contract, executes KWIC, and renders frequency data', async ({ page, request }) => {
    test.setTimeout(120_000)

    const capabilitiesResponse = page.waitForResponse((response) =>
      response.url().includes('/api/v1/capabilities') && response.status() === 200,
    )
    const corporaResponse = page.waitForResponse((response) =>
      response.url().includes('/api/v1/corpora') && response.status() === 200,
    )

    await page.goto('/')
    const capabilities = await (await capabilitiesResponse).json()
    await corporaResponse

    const productCapabilities = capabilities as {
      capabilities: Array<{
        id?: string
        backend_route_descriptors?: Array<{ path?: string; requires_corpus_features?: string[] }>
      }>
    }
    expect(productCapabilities.capabilities.length).toBeGreaterThan(0)
    expect(productCapabilities.capabilities.some((capability) => capability.id === 'query.kwic')).toBe(true)
    expect(productCapabilities.capabilities.some((capability) => capability.id === 'research.copilot_grounding')).toBe(true)

    const wordSketchCapability = productCapabilities.capabilities.find((capability) =>
      capability.id === 'analysis.wordsketch'
    )
    const wordSketchRoute = wordSketchCapability?.backend_route_descriptors?.find((route) =>
      route.path === '/api/v1/analysis/wordsketch'
    )
    expect(wordSketchRoute?.requires_corpus_features).toEqual(['token_attributes.rel'])

    const corpusCapabilitiesResponse = await request.get(`${backendApiBase()}/corpora/default/capabilities`)
    expect(corpusCapabilitiesResponse.ok()).toBe(true)
    const corpusCapabilities = await corpusCapabilitiesResponse.json() as {
      capabilities?: { rel_lex?: boolean }
      features?: {
        token_attributes?: Array<{ id?: string }>
        semantic?: { passage_search?: boolean; word_similarity?: boolean }
      }
    }
    expect(corpusCapabilities.capabilities?.rel_lex).toBe(true)
    expect(
      corpusCapabilities.features?.token_attributes?.some((attribute) => attribute.id === 'rel'),
    ).toBe(true)
    expect(corpusCapabilities.features?.semantic?.passage_search).toBe(false)
    expect(corpusCapabilities.features?.semantic?.word_similarity).toBe(false)

    const copilotRuntimeGateResponse = await request.post(`${backendApiBase()}/chat/stream`, {
      data: {
        messages: [{ role: 'user', content: COPILOT_SMOKE_PROMPT }],
      },
    })
    expect(copilotRuntimeGateResponse.status()).toBe(503)
    const copilotRuntimeGate = await copilotRuntimeGateResponse.json() as {
      detail?: { code?: string; message?: string; model?: string }
    }
    expect(copilotRuntimeGate.detail?.code).toBe('transport')
    expect(copilotRuntimeGate.detail?.message).toContain('Transportfehler beim LLM-Endpunkt')
    expect(copilotRuntimeGate.detail?.model).toBe('candyconc-live-smoke-unavailable')

    const semanticTab = page.getByRole('tab', { name: /^Semantik/ })
    await expect(semanticTab).toHaveAttribute('aria-disabled', 'true')
    await expect(semanticTab).toHaveAttribute('title', /Embedding-Index/)
    await page.getByRole('button', { name: /^Weitere Tabs/ }).click()
    const wordSketchItem = page.getByRole('menuitem', { name: /Word Sketch/ }).first()
    await expect(wordSketchItem).toBeVisible()
    await expect(wordSketchItem).toHaveAttribute('aria-disabled', 'false')
    await page.keyboard.press('Escape')

    const countResponse = await request.get(`${backendApiBase()}/query/count`, {
      params: {
        term: KWIC_SMOKE_TERM,
        ctx: '200',
        corpus: 'default',
        wait_ms: '5000',
        case_insensitive: 'true',
      },
    })
    expect(countResponse.ok()).toBe(true)
    const countPayload = await countResponse.json() as { status?: string; total?: number; partial?: boolean }
    expect(countPayload.status).toBe('ready')
    expect(countPayload.partial).toBe(false)
    expect(countPayload.total).toBe(KWIC_SMOKE_EXPECTED_COUNT)

    await expect(page.locator('[data-search-input]')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Suche starten' })).toBeVisible()

    const queryResponse = page.waitForResponse((response) =>
      response.url().includes('/api/v1/query/stream') && response.status() === 200,
    )
    await page.locator('[data-search-input]').fill(KWIC_SMOKE_TERM)
    await page.getByRole('button', { name: 'Suche starten' }).click()
    await queryResponse

    const firstRow = page.getByTestId('kwic-row-0')
    await expect(firstRow).toBeVisible()
    await expect(firstRow.getByTestId('kwic-row-match')).toContainText(KWIC_SMOKE_MATCH)
    await expect(page.getByTestId('kwic-table-header')).toContainText(`${KWIC_SMOKE_EXPECTED_COUNT} Treffer`)

    await firstRow.getByRole('button', { name: 'Zeile codieren: Code und Notiz' }).click()
    const annotationDialog = page.getByRole('dialog', { name: 'Zeile codieren' })
    await expect(annotationDialog).toBeVisible()
    await annotationDialog.getByLabel('Notiz').fill(ANNOTATION_SMOKE_NOTE)
    const annotationPutResponse = page.waitForResponse((response) =>
      response.url().includes('/api/v1/annotations/') &&
      response.request().method() === 'PUT' &&
      response.status() === 200,
    )
    await annotationDialog.getByRole('button', { name: 'Code und Notiz speichern' }).click()
    const annotationResponse = await annotationPutResponse
    const annotationPayload = await annotationResponse.json() as {
      row_id?: string
      annotation?: { note?: string | null; category_id?: string | null; annotator?: string | null }
    }
    expect(annotationPayload.annotation?.note).toBe(ANNOTATION_SMOKE_NOTE)
    expect(annotationPayload.annotation?.category_id ?? null).toBeNull()
    await expect(firstRow.locator('.row-annotation-badge')).toBeVisible()
    await expect(firstRow.locator('.ann-note-icon')).toBeVisible()

    const annotationRowId = annotationPayload.row_id
    expect(annotationRowId).toBeTruthy()
    const annotationsResponse = await request.get(`${backendApiBase()}/annotations`, {
      params: { corpus: 'default' },
    })
    expect(annotationsResponse.ok()).toBe(true)
    const annotationsPayload = await annotationsResponse.json() as {
      annotations?: Record<string, { note?: string | null; category_id?: string | null }>
    }
    expect(annotationsPayload.annotations?.[annotationRowId!]?.note).toBe(ANNOTATION_SMOKE_NOTE)
    expect(annotationsPayload.annotations?.[annotationRowId!]?.category_id ?? null).toBeNull()

    const copilotButton = page.getByRole('button', { name: /Copilot öffnen/ })
    await expect(copilotButton).toBeVisible()
    await expect(copilotButton).toBeEnabled()
    await copilotButton.click()
    const copilotPanel = page.locator('.copilot-panel').first()
    await expect(copilotPanel).toBeVisible()
    const copilotInput = copilotPanel.getByPlaceholder('Nachricht an Copilot...')
    await copilotInput.fill(COPILOT_SMOKE_PROMPT)
    await copilotInput.press('Enter')
    await expect(copilotPanel.getByText(/Fehler: .*Transportfehler beim LLM-Endpunkt/)).toBeVisible({ timeout: 20_000 })
    await expect(copilotPanel.getByRole('alert')).toContainText('Die Antwort konnte nicht abgeschlossen werden')
    await expect(copilotPanel.getByText('AI-Fehlerstatus')).toBeVisible()
    await copilotPanel.getByTitle('Schließen (Esc)').click()
    await expect(copilotPanel).toBeHidden()

    let exportDialog = await openExportDialog(page)
    await exportDialog.getByLabel('Server-Konkordanz (vollständig gezählt)').check()
    const csvResponse = page.waitForResponse((response) =>
      response.url().includes('/api/v1/export/concordance') &&
      response.request().method() === 'POST' &&
      response.status() === 200,
    )
    const csvText = await exportVisibleDialog(page)
    await csvResponse
    expect(csvText).toContain('pos,doc_id,doc,left,node,right,meta')
    expect(csvText).toMatch(KWIC_SMOKE_MATCH)
    expect(dataCsvRows(csvText)).toHaveLength(KWIC_SMOKE_EXPECTED_COUNT)

    exportDialog = await openExportDialog(page)
    await exportDialog.getByRole('button', { name: /^JSON Server-Konkordanz/ }).click()
    const jsonResponse = page.waitForResponse((response) =>
      response.url().includes('/api/v1/export/concordance') &&
      response.request().method() === 'POST' &&
      response.status() === 200,
    )
    const jsonText = await exportVisibleDialog(page)
    await jsonResponse
    const jsonExport = JSON.parse(jsonText) as {
      term?: string
      rows?: Array<{ doc_id?: number | string; meta?: Record<string, unknown> | null; node?: string }>
    }
    expect(jsonExport.term).toBe(KWIC_SMOKE_TERM)
    expect(jsonExport.rows).toHaveLength(KWIC_SMOKE_EXPECTED_COUNT)
    expect(jsonExport.rows?.some((row) => KWIC_SMOKE_MATCH.test(String(row.node ?? '')))).toBe(true)
    expect(jsonExport.rows?.some((row) => row.doc_id !== undefined && row.meta !== undefined)).toBe(true)

    exportDialog = await openExportDialog(page)
    await exportDialog.getByRole('button', { name: /^Evidence JSON/ }).click()
    const evidenceResponse = page.waitForResponse((response) =>
      response.url().includes('/api/v1/export/evidence-package') &&
      response.request().method() === 'POST' &&
      response.status() === 200,
    )
    const evidenceText = await exportVisibleDialog(page)
    await evidenceResponse
    const evidencePackage = JSON.parse(evidenceText) as {
      schema_version?: string
      scope?: { query?: string }
      result_summary?: { rows_included?: number }
    }
    expect(evidencePackage.schema_version).toBe('candyconc-evidence-package-v1')
    expect(evidencePackage.scope?.query).toBe(KWIC_SMOKE_TERM)
    expect(evidencePackage.result_summary?.rows_included).toBe(KWIC_SMOKE_EXPECTED_COUNT)

    const frequencyApiResponse = await request.get(`${backendApiBase()}/analysis/frequency_list`, {
      params: {
        corpus: 'default',
        group_by: 'word',
        limit: '100',
      },
    })
    expect(frequencyApiResponse.ok()).toBe(true)
    const frequencyApi = await frequencyApiResponse.json() as { rows?: Array<{ word?: string; f?: number }> }
    const frequencyApiRow = frequencyApi.rows?.find((row) => row.word === FREQUENCY_SMOKE_ITEM)
    expect(frequencyApiRow?.f).toBe(FREQUENCY_SMOKE_EXPECTED_COUNT)

    const frequencyResponse = page.waitForResponse((response) =>
      (
        response.url().includes('/api/v1/analysis/frequency_list') ||
        response.url().includes('/api/v1/analysis/frequency_list/job')
      ) && response.status() < 400,
    )
    await openTab(page, 'Frequenz')
    await frequencyResponse

    const frequencyTab = page.getByTestId('frequency-tab')
    await expect(frequencyTab).toBeVisible()
    await expect(frequencyTab.getByText(/Basis: /)).toBeVisible()
    await expect(page.getByTestId('frequency-table')).toBeVisible()
    await expect(page.getByTestId('frequency-row-0')).toBeVisible()
    const frequencyUiRows = await page.getByTestId('frequency-table').locator('tbody tr').evaluateAll((rows) =>
      rows.map((row) => ({
        item: row.querySelector('[data-testid="frequency-row-item"]')?.textContent?.trim() ?? '',
        count: row.querySelector('[data-testid="frequency-row-count"]')?.textContent?.trim() ?? '',
      }))
    )
    expect(frequencyUiRows.find((row) => row.item === FREQUENCY_SMOKE_ITEM)?.count).toBe(
      FREQUENCY_SMOKE_EXPECTED_COUNT.toLocaleString('de-DE'),
    )

    const frequencyDownload = page.waitForEvent('download')
    await frequencyTab.getByRole('button', { name: /CSV/ }).click()
    const frequencyCsvText = await downloadText(await frequencyDownload)
    expect(frequencyCsvText).toContain('# Analysis: Frequency')
    expect(frequencyCsvText).toContain(`${FREQUENCY_SMOKE_ITEM},${FREQUENCY_SMOKE_EXPECTED_COUNT},`)

    const wordSketchApiResponse = await request.post(`${backendApiBase()}/analysis/wordsketch`, {
      data: {
        corpus: 'default',
        term: KWIC_SMOKE_TERM,
        limit: 10,
      },
    })
    expect(wordSketchApiResponse.ok()).toBe(true)
    const wordSketchApi = await wordSketchApiResponse.json() as {
      sketches?: Record<string, Array<{ word?: string; f?: number; frequency?: number; score?: number }>>
      relations?: Record<string, { label?: string; row_limit?: number; total_candidates?: number; total_rows?: number; truncated?: boolean }>
      method?: { family?: string; default_sort?: string; min_freq?: number }
    }
    const wordSketchRows = wordSketchApi.sketches?.[WORDSKETCH_SMOKE_RELATION] ?? []
    const wordSketchApiRow = wordSketchRows.find((row) => row.word === WORDSKETCH_SMOKE_ITEM)
    const wordSketchApiRelation = wordSketchApi.relations?.[WORDSKETCH_SMOKE_RELATION]
    expect(wordSketchApiRelation?.label).toBe(WORDSKETCH_SMOKE_LABEL)
    expect(wordSketchApiRelation?.row_limit).toBe(10)
    expect(wordSketchApiRelation?.total_candidates).toBe(wordSketchRows.length)
    expect(wordSketchApiRelation?.total_rows).toBe(wordSketchRows.length)
    expect(wordSketchApiRelation?.truncated).toBe(false)
    expect(wordSketchApi.method?.family).toBe('wordsketch')
    expect(wordSketchApi.method?.default_sort).toBe('logdice')
    expect(wordSketchApi.method?.min_freq).toBe(3)
    expect(wordSketchApiRow?.f ?? wordSketchApiRow?.frequency).toBe(WORDSKETCH_SMOKE_EXPECTED_FREQ)
    expect(wordSketchApiRow?.score).toBeCloseTo(WORDSKETCH_SMOKE_EXPECTED_LOGDICE, 3)

    const wordSketchResponse = page.waitForResponse((response) =>
      response.url().includes('/api/v1/analysis/wordsketch') &&
      response.request().method() === 'POST' &&
      response.status() === 200,
    )
    await openTab(page, 'Word Sketch')
    const wordSketchTab = page.locator('.wordsketch-tab')
    await expect(wordSketchTab).toBeVisible()
    await wordSketchTab.getByRole('button', { name: 'Analysieren' }).click()
    await wordSketchResponse
    const wordSketchRelation = wordSketchTab.locator('.relation-card').filter({
      hasText: WORDSKETCH_SMOKE_LABEL,
    }).first()
    await expect(wordSketchRelation).toBeVisible()
    await expect(wordSketchRelation).toContainText(WORDSKETCH_SMOKE_ITEM)
    await expect(wordSketchRelation).toContainText(`(${WORDSKETCH_SMOKE_EXPECTED_FREQ})`)
    await expect(wordSketchRelation).toContainText(
      deScore(Number(wordSketchApiRow?.score ?? WORDSKETCH_SMOKE_EXPECTED_LOGDICE)),
    )
    await expect(wordSketchRelation).toContainText(`${wordSketchRows.length} von ${wordSketchRows.length} angezeigt`)

    const ngramApiResponse = await request.post(`${backendApiBase()}/analysis/ngrams`, {
      data: {
        corpus: 'default',
        min_n: 2,
        max_n: 2,
        limit: 100,
      },
    })
    expect(ngramApiResponse.ok()).toBe(true)
    const ngramApi = await ngramApiResponse.json() as {
      rows?: Array<{ ngram?: string; freq?: number }>
      total_candidates?: number
      truncated?: boolean
    }
    expect(ngramApi.total_candidates).toBe(NGRAM_SMOKE_EXPECTED_CANDIDATES)
    expect(ngramApi.truncated).toBe(false)
    expect(ngramApi.rows?.find((row) => row.ngram === NGRAM_SMOKE_ITEM)?.freq).toBe(NGRAM_SMOKE_EXPECTED_COUNT)

    await openTab(page, 'N-Gramme')
    const ngramsTab = page.locator('.ngrams-tab')
    await expect(ngramsTab).toBeVisible()
    await ngramsTab.getByLabel(/Min\. Frequenz/).fill('1')
    const ngramRowsResponse = page.waitForResponse((response) =>
      response.url().includes('/api/v1/analysis/jobs/') &&
      response.url().includes('/rows') &&
      response.status() === 200,
    )
    await ngramsTab.getByRole('button', { name: /Aktualisieren/ }).first().click()
    const ngramRowsPayload = await (await ngramRowsResponse).json() as {
      rows?: Array<{ ngram?: string; freq?: number }>
      total_candidates?: number
      truncated?: boolean
    }
    expect(ngramRowsPayload.total_candidates).toBe(NGRAM_SMOKE_EXPECTED_CANDIDATES)
    expect(ngramRowsPayload.truncated).toBe(false)
    expect(ngramRowsPayload.rows?.find((row) => row.ngram === NGRAM_SMOKE_ITEM)?.freq).toBe(NGRAM_SMOKE_EXPECTED_COUNT)
    await expect(ngramsTab.locator('tbody tr', { hasText: NGRAM_SMOKE_ITEM })).toContainText(
      String(NGRAM_SMOKE_EXPECTED_COUNT),
    )

    const ngramDownload = page.waitForEvent('download')
    await ngramsTab.getByRole('button', { name: /CSV/ }).click()
    const ngramCsvText = await downloadText(await ngramDownload)
    expect(ngramCsvText).toContain('# Analysis: Ngrams')
    expect(ngramCsvText).toContain(`# Result.total_candidates: ${NGRAM_SMOKE_EXPECTED_CANDIDATES}`)
    expect(ngramCsvText).toContain(`${NGRAM_SMOKE_ITEM},${NGRAM_SMOKE_EXPECTED_COUNT},`)

    const dispersionApiResponse = await request.get(`${backendApiBase()}/analysis/dispersion`, {
      params: {
        term: KWIC_SMOKE_TERM,
        corpus: 'default',
        partitions: '10',
      },
    })
    expect(dispersionApiResponse.ok()).toBe(true)
    const dispersionApi = await dispersionApiResponse.json() as {
      observed_frequency?: number
      partitions?: number[]
      token_count?: number
      basis?: string
      partial?: boolean
      fallback?: boolean
    }
    expect(dispersionApi.observed_frequency).toBe(KWIC_SMOKE_EXPECTED_COUNT)
    expect(dispersionApi.partitions?.reduce((sum, value) => sum + value, 0)).toBe(KWIC_SMOKE_EXPECTED_COUNT)
    expect(dispersionApi.token_count).toBe(42)
    expect(dispersionApi.basis).toBe('global')
    expect(dispersionApi.partial).toBe(false)
    expect(dispersionApi.fallback).toBe(false)

    const dispersionOffsetsResponse = await request.get(`${backendApiBase()}/analysis/dispersion_offsets`, {
      params: {
        term: KWIC_SMOKE_TERM,
        corpus: 'default',
        limit: '20',
      },
    })
    expect(dispersionOffsetsResponse.ok()).toBe(true)
    const dispersionOffsets = await dispersionOffsetsResponse.json() as {
      offsets?: number[]
      total?: number
      token_count?: number
      truncated?: boolean
    }
    expect(dispersionOffsets.offsets).toEqual(DISPERSION_SMOKE_EXPECTED_OFFSETS)
    expect(dispersionOffsets.total).toBe(KWIC_SMOKE_EXPECTED_COUNT)
    expect(dispersionOffsets.token_count).toBe(42)
    expect(dispersionOffsets.truncated).toBe(false)

    const dispersionResponse = page.waitForResponse((response) =>
      response.url().includes('/api/v1/analysis/dispersion') &&
      !response.url().includes('dispersion_offsets') &&
      response.status() === 200,
    )
    await openTab(page, 'Dispersion')
    await dispersionResponse
    const dispersionTab = page.locator('.dispersion-tab')
    await expect(dispersionTab).toBeVisible()
    await expect(dispersionTab.locator('.stat-card', { hasText: /^Vorkommen/ })).toContainText(
      String(KWIC_SMOKE_EXPECTED_COUNT),
    )
    await expect(dispersionTab.locator('.basis-panel')).toContainText('Token-Basis: 42')
    await expect(dispersionTab.locator('.basis-panel')).toContainText('Dokumentbasis: 8 Dokumentpartitionen')

    const uiOffsetsResponse = page.waitForResponse((response) =>
      response.url().includes('/api/v1/analysis/dispersion_offsets') && response.status() === 200,
    )
    await dispersionTab.getByRole('button', { name: /Offsets prüfen/ }).click()
    await uiOffsetsResponse
    await expect(dispersionTab.getByText('1, 7, 15, 18, 23, 28, 33, 38')).toBeVisible()

    const dispersionDownload = page.waitForEvent('download')
    await dispersionTab.getByRole('button', { name: /Dispersion als CSV exportieren/ }).click()
    const dispersionCsvText = await downloadText(await dispersionDownload)
    expect(dispersionCsvText).toContain('# Analysis: Dispersion')
    expect(dispersionCsvText).toContain(`# Term: ${KWIC_SMOKE_TERM}`)
    expect(dispersionCsvText).toContain('# DispersionTokenBasis: 42')
    expect(dataCsvRows(dispersionCsvText)).toEqual(['1,1', '2,1', '3,1', '4,1', '5,1', '6,1', '7,1', '8,1'])

    const collocationsApiResponse = await request.get(`${backendApiBase()}/analysis/collocates`, {
      params: {
        term: KWIC_SMOKE_TERM,
        corpus: 'default',
        window: '5',
        min_freq: '1',
        within_sentence: 'true',
        sort_by: 'chi2_cell',
        limit: '50',
      },
    })
    expect(collocationsApiResponse.ok()).toBe(true)
    const collocationsApi = await collocationsApiResponse.json() as {
      rows?: Array<{ word?: string; f?: number; observed?: number; expected?: number; chi2_cell?: number }>
      method?: {
        cooccurrence_floor?: number
        effective_min_cooccurrence?: number
        floor_mode?: string
        target_total?: number
        event_space?: string
        event_total_definition?: string
      }
      total_candidates?: number
      truncated?: boolean
    }
    const collocationApiRow = collocationsApi.rows?.find((row) => row.word === COLLOCATION_SMOKE_ITEM)
    expect(collocationsApi.total_candidates).toBe(COLLOCATION_SMOKE_EXPECTED_CANDIDATES)
    expect(collocationsApi.truncated).toBe(false)
    expect(collocationsApi.method?.cooccurrence_floor).toBe(5)
    // Explicit min_freq=1 is raised to the shared lower limit; 5 is the default ceiling.
    expect(collocationsApi.method?.effective_min_cooccurrence).toBe(2)
    expect(collocationsApi.method?.floor_mode).toBe('requested_raised')
    expect(collocationsApi.method?.target_total).toBe(42)
    // Evert's distance table uses corpus tokens, window-union R1, and collocate-frequency C1.
    expect(collocationsApi.method?.event_space).toBe('corpus_tokens')
    expect(collocationsApi.method?.event_total_definition).toBe('scope_tokens')
    expect(collocationApiRow?.f).toBe(COLLOCATION_SMOKE_EXPECTED_FREQ)
    expect(collocationApiRow?.observed).toBe(COLLOCATION_SMOKE_EXPECTED_FREQ)
    expect(collocationApiRow?.expected).toBeCloseTo(COLLOCATION_SMOKE_EXPECTED_EXPECTED, 4)
    expect(collocationApiRow?.chi2_cell).toBeCloseTo(COLLOCATION_SMOKE_EXPECTED_CHI2_CELL, 4)

    const retiredMi2Response = await request.get(`${backendApiBase()}/analysis/collocates`, {
      params: { term: KWIC_SMOKE_TERM, corpus: 'default', sort_by: 'mi2' },
    })
    expect(retiredMi2Response.status()).toBe(422)

    const initialCollocationRowsResponse = page.waitForResponse((response) =>
      response.url().includes('/api/v1/analysis/jobs/') &&
      response.url().includes('/rows') &&
      response.status() === 200,
    )
    await openTab(page, 'Kollokationen')
    const collocationsTab = page.locator('.collocations-tab')
    await expect(collocationsTab).toBeVisible()
    await initialCollocationRowsResponse
    const collocationRowsResponse = page.waitForResponse((response) =>
      response.url().includes('/api/v1/analysis/jobs/') &&
      response.url().includes('/rows') &&
      response.status() === 200,
    )
    await collocationsTab.locator('select.select').selectOption('chi2_cell')
    const collocationRowsPayload = await (await collocationRowsResponse).json() as {
      rows?: Array<{ word?: string; f?: number; observed?: number; expected?: number; chi2_cell?: number }>
      method?: {
        cooccurrence_floor?: number
        effective_min_cooccurrence?: number
        target_total?: number
        event_space?: string
        event_total_definition?: string
      }
      total_candidates?: number
      truncated?: boolean
    }
    const collocationJobRow = collocationRowsPayload.rows?.find((row) => row.word === COLLOCATION_SMOKE_ITEM)
    expect(collocationRowsPayload.total_candidates).toBe(COLLOCATION_SMOKE_EXPECTED_CANDIDATES)
    expect(collocationRowsPayload.truncated).toBe(false)
    expect(collocationRowsPayload.method?.cooccurrence_floor).toBe(5)
    expect(collocationRowsPayload.method?.effective_min_cooccurrence).toBe(5)
    expect(collocationRowsPayload.method?.target_total).toBe(42)
    expect(collocationRowsPayload.method?.event_space).toBe('corpus_tokens')
    expect(collocationRowsPayload.method?.event_total_definition).toBe('scope_tokens')
    expect(collocationJobRow?.f).toBe(COLLOCATION_SMOKE_EXPECTED_FREQ)
    expect(collocationJobRow?.observed).toBe(COLLOCATION_SMOKE_EXPECTED_FREQ)
    expect(collocationJobRow?.expected).toBeCloseTo(COLLOCATION_SMOKE_EXPECTED_EXPECTED, 4)
    expect(collocationJobRow?.chi2_cell).toBeCloseTo(COLLOCATION_SMOKE_EXPECTED_CHI2_CELL, 4)
    const collocationUiRow = collocationsTab.locator('tbody tr', { hasText: COLLOCATION_SMOKE_ITEM })
    await expect(collocationUiRow).toContainText(String(COLLOCATION_SMOKE_EXPECTED_FREQ))
    await expect(collocationUiRow).toContainText(deScore(COLLOCATION_SMOKE_EXPECTED_CHI2_CELL))

    const collocationDownload = page.waitForEvent('download')
    await collocationsTab.getByRole('button', { name: /Kollokationen als CSV exportieren/ }).click()
    const collocationCsvText = await downloadText(await collocationDownload)
    expect(collocationCsvText).toContain('# Analysis: Collocations')
    expect(collocationCsvText).toContain(`# Term: ${KWIC_SMOKE_TERM}`)
    expect(collocationCsvText).toContain(`# Result.total_candidates: ${COLLOCATION_SMOKE_EXPECTED_CANDIDATES}`)
    expect(collocationCsvText).toContain(
      `${COLLOCATION_SMOKE_ITEM},${COLLOCATION_SMOKE_EXPECTED_FREQ},${COLLOCATION_SMOKE_EXPECTED_EXPECTED.toFixed(4)},${COLLOCATION_SMOKE_EXPECTED_CHI2_CELL.toFixed(4)},chi2_cell,${COLLOCATION_SMOKE_EXPECTED_CHI2_CELL.toFixed(4)}`,
    )

    await openTab(page, 'KWIC')
    await page.getByRole('button', { name: 'Query‑Builder öffnen' }).click()
    const queryBuilderDialog = page.getByRole('dialog', { name: 'Query‑Builder' })
    await expect(queryBuilderDialog).toBeVisible()
    await queryBuilderDialog.locator('[data-intent-option="exact"]').click()
    await queryBuilderDialog.locator('#quick-search-term').fill(KWIC_SMOKE_TERM)
    await queryBuilderDialog.locator('#quick-search-term').press('Control+Enter')
    await expect(queryBuilderDialog).toHaveCount(0)

    const generatedQuery = await page.locator('[data-search-input]').inputValue()
    expect(generatedQuery).toContain(KWIC_SMOKE_TERM)
    expect(generatedQuery).toContain('[')

    const queryBuilderResponse = page.waitForResponse((response) =>
      response.url().includes('/api/v1/query/stream') && response.status() === 200,
    )
    await page.getByRole('button', { name: 'Suche starten' }).click()
    await queryBuilderResponse
    await expect(page.getByTestId('kwic-table-header')).toContainText(`${KWIC_SMOKE_EXPECTED_COUNT} Treffer`)
    await expect(page.getByTestId('kwic-row-0').getByTestId('kwic-row-match')).toContainText(KWIC_SMOKE_MATCH)
  })

  test('opens KWIC context without the Copilot trigger intercepting it', async ({ page }) => {
    test.setTimeout(60_000)

    await page.goto('/')
    await expect(page.locator('[data-search-input]')).toBeVisible()

    const queryResponse = page.waitForResponse((response) =>
      response.url().includes('/api/v1/query/stream') && response.status() === 200,
    )
    await page.locator('[data-search-input]').fill(KWIC_SMOKE_TERM)
    await page.getByRole('button', { name: 'Suche starten' }).click()
    await queryResponse

    const firstRow = page.getByTestId('kwic-row-0')
    await expect(firstRow).toBeVisible()
    await firstRow.hover()

    const snippetResponse = page.waitForResponse((response) =>
      response.url().includes('/api/v1/doc/snippet') && response.status() === 200,
    )
    await firstRow.locator('button[title="Kontext erweitern"]').click()
    await snippetResponse
    await expect(firstRow.locator('.expanded-context')).toBeVisible()

    await page.locator('.copilot-trigger').click()
    await expect(page.locator('.copilot-panel.mode-floating')).toBeVisible()
  })

  test('builds a query subcorpus and verifies Keyness counts through API, UI, and CSV', async ({ page, request }) => {
    test.setTimeout(120_000)

    await page.goto('/')
    await expect(page.locator('[data-search-input]')).toBeVisible()

    const queryResponse = page.waitForResponse((response) =>
      response.url().includes('/api/v1/query/stream') && response.status() === 200,
    )
    await page.locator('[data-search-input]').fill(KEYNESS_SMOKE_TERM)
    await page.getByRole('button', { name: 'Suche starten' }).click()
    await queryResponse

    await expect(page.getByTestId('kwic-row-0')).toBeVisible()
    await expect(page.getByTestId('kwic-table-header')).toContainText(`${KEYNESS_SMOKE_EXPECTED_COUNT} Treffer`)

    const saveSubcorpusButton = page
      .getByTestId('kwic-table')
      .getByRole('button', { name: 'Subkorpus speichern' })
      .first()
    await expect(saveSubcorpusButton).toBeEnabled()
    await saveSubcorpusButton.click()
    const nameDialog = page.getByRole('dialog', { name: 'Subkorpus benennen' })
    await expect(nameDialog).toBeVisible()
    await nameDialog.locator('input').fill('Smoke Keyness Karotte')

    const unexpectedDialogs: string[] = []
    const captureUnexpectedDialog = async (dialog: Dialog) => {
      unexpectedDialogs.push(dialog.message())
      await dialog.accept()
    }
    page.on('dialog', captureUnexpectedDialog)
    const docsetResponse = page.waitForResponse((response) =>
      response.url().includes('/api/v1/analysis/docset_from_search') &&
      response.request().method() === 'POST' &&
      response.status() === 200,
    )
    await nameDialog.getByRole('button', { name: 'Speichern' }).click()
    const docsetPayload = await (await docsetResponse).json() as {
      docset_id?: string
      doc_count?: number
      token_count?: number
    }
    expect(unexpectedDialogs).toEqual([])
    page.off('dialog', captureUnexpectedDialog)
    expect(docsetPayload.docset_id).toBeTruthy()
    expect(docsetPayload.doc_count).toBe(5)
    expect(docsetPayload.token_count).toBe(KEYNESS_SMOKE_EXPECTED_TARGET_RAW_TOTAL)
    await expect(nameDialog).toHaveCount(0)

    const keynessApiResponse = await request.post(`${backendApiBase()}/analysis/keyness`, {
      data: {
        target_docset_id: docsetPayload.docset_id,
        reference_source: 'whole',
        corpus: 'default',
        min_freq: 5,
        limit: 50,
        sort: 'll_signed',
      },
    })
    expect(keynessApiResponse.ok()).toBe(true)
    const keynessApi = await keynessApiResponse.json() as {
      rows?: Array<{
        word?: string
        target_freq?: number
        reference_freq?: number
        ll_signed?: number
        diff_per_million?: number
        direction?: string
      }>
      method?: {
        target_total?: number; reference_total?: number; min_freq?: number; reference_source?: string
        target_tokens_roh?: number; reference_tokens_roh?: number
      }
      total_candidates?: number
      truncated?: boolean
    }
    const keynessApiRow = keynessApi.rows?.find((row) => row.word === KEYNESS_SMOKE_ITEM)
    expect(keynessApi.total_candidates).toBe(KEYNESS_SMOKE_EXPECTED_CANDIDATES)
    expect(keynessApi.truncated).toBe(false)
    expect(keynessApi.method?.target_total).toBe(KEYNESS_SMOKE_EXPECTED_TARGET_TOTAL)
    expect(keynessApi.method?.reference_total).toBe(KEYNESS_SMOKE_EXPECTED_REFERENCE_TOTAL)
    expect(keynessApi.method?.target_tokens_roh).toBe(KEYNESS_SMOKE_EXPECTED_TARGET_RAW_TOTAL)
    expect(keynessApi.method?.reference_tokens_roh).toBe(KEYNESS_SMOKE_EXPECTED_REFERENCE_RAW_TOTAL)
    expect(keynessApi.method?.reference_source).toBe('whole')
    expect(keynessApiRow?.target_freq).toBe(KEYNESS_SMOKE_EXPECTED_COUNT)
    expect(keynessApiRow?.reference_freq).toBe(KEYNESS_SMOKE_EXPECTED_REFERENCE_COUNT)
    expect(keynessApiRow?.ll_signed).toBeCloseTo(KEYNESS_SMOKE_EXPECTED_LL_SIGNED, 12)
    expect(keynessApiRow?.diff_per_million).toBeCloseTo(KEYNESS_SMOKE_EXPECTED_DIFF_PM, 8)
    expect(keynessApiRow?.direction).toBe('target')

    // Saving keeps the current scope unchanged. Activate the saved target explicitly.
    await page.getByRole('button', { name: 'Subkorpora', exact: true }).click()
    const savedTarget = page.locator('.snapshot-card').filter({ hasText: 'Smoke Keyness Karotte' })
    await savedTarget.getByRole('button', { name: 'Subkorpus aktivieren', exact: true }).click()
    await expect(page.getByRole('button', { name: /^Suchbereich ändern/ })).toContainText(`Query ${KEYNESS_SMOKE_TERM}`)

    const keynessRowsResponse = page.waitForResponse((response) =>
      response.url().includes('/api/v1/analysis/jobs/') &&
      response.url().includes('/rows') &&
      response.status() === 200,
    )
    await openTab(page, 'Keyness')
    const keynessTab = page.locator('.keyness-tab')
    await expect(keynessTab).toBeVisible()
    await keynessTab.getByRole('button', { name: 'Keyness' }).click()
    const keynessRowsPayload = await (await keynessRowsResponse).json() as {
      rows?: Array<{
        word?: string
        target_freq?: number
        reference_freq?: number
        ll_signed?: number
        diff_per_million?: number
        direction?: string
      }>
      method?: {
        target_total?: number; reference_total?: number; min_freq?: number; reference_source?: string
        target_tokens_roh?: number; reference_tokens_roh?: number
      }
      total_candidates?: number
      truncated?: boolean
    }
    const keynessJobRow = keynessRowsPayload.rows?.find((row) => row.word === KEYNESS_SMOKE_ITEM)
    expect(keynessRowsPayload.total_candidates).toBe(KEYNESS_SMOKE_EXPECTED_CANDIDATES)
    expect(keynessRowsPayload.truncated).toBe(false)
    expect(keynessRowsPayload.method?.target_total).toBe(KEYNESS_SMOKE_EXPECTED_TARGET_TOTAL)
    expect(keynessRowsPayload.method?.reference_total).toBe(KEYNESS_SMOKE_EXPECTED_REFERENCE_TOTAL)
    expect(keynessRowsPayload.method?.target_tokens_roh).toBe(KEYNESS_SMOKE_EXPECTED_TARGET_RAW_TOTAL)
    expect(keynessRowsPayload.method?.reference_tokens_roh).toBe(KEYNESS_SMOKE_EXPECTED_REFERENCE_RAW_TOTAL)
    expect(keynessRowsPayload.method?.reference_source).toBe('whole')
    expect(keynessJobRow?.target_freq).toBe(KEYNESS_SMOKE_EXPECTED_COUNT)
    expect(keynessJobRow?.reference_freq).toBe(KEYNESS_SMOKE_EXPECTED_REFERENCE_COUNT)
    expect(keynessJobRow?.ll_signed).toBeCloseTo(KEYNESS_SMOKE_EXPECTED_LL_SIGNED, 12)
    expect(keynessJobRow?.diff_per_million).toBeCloseTo(KEYNESS_SMOKE_EXPECTED_DIFF_PM, 8)
    expect(keynessJobRow?.direction).toBe('target')

    const keynessUiRow = keynessTab.locator('tbody tr', { hasText: KEYNESS_SMOKE_ITEM })
    await expect(keynessUiRow).toContainText(
      KEYNESS_SMOKE_EXPECTED_LL_SIGNED.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    )
    await expect(keynessUiRow).toContainText('Target')

    await keynessTab.getByRole('button', { name: 'CSV' }).click()
    const exportDialog = page.getByRole('dialog', { name: 'CSV Export' })
    await expect(exportDialog).toBeVisible()
    const keynessDownload = page.waitForEvent('download')
    await exportDialog.getByRole('button', { name: 'Exportieren' }).click()
    const keynessCsvText = await downloadText(await keynessDownload)
    expect(keynessCsvText).toContain('# Analysis: Contrast/Keyness')
    expect(keynessCsvText).toContain('# Target: Smoke Keyness Karotte')
    expect(keynessCsvText).toContain('# ReferenceSource: whole')
    expect(keynessCsvText).toContain('# ReferenceExcludedDocset:')
    expect(keynessCsvText).toContain(`# target_total: ${KEYNESS_SMOKE_EXPECTED_TARGET_TOTAL}`)
    expect(keynessCsvText).toContain(`# reference_total: ${KEYNESS_SMOKE_EXPECTED_REFERENCE_TOTAL}`)
    expect(keynessCsvText).toContain(`# KeynessResult.total_candidates: ${KEYNESS_SMOKE_EXPECTED_CANDIDATES}`)
    expect(keynessCsvText).toContain(`${KEYNESS_SMOKE_ITEM},${KEYNESS_SMOKE_EXPECTED_LL_SIGNED},`)
  })

  test('drives the real corpus import workflow through the UI and verifies post-import evidence', async ({ page, request }) => {
    test.setTimeout(240_000)

    const importInput = process.env.CANDYCONC_IMPORT_SMOKE_INPUT ?? ''
    const importMethod = process.env.CANDYCONC_IMPORT_SMOKE_METHOD ?? 'prealigned_csv'
    const targetName = process.env.CANDYCONC_IMPORT_SMOKE_TARGET ?? 'ui-import-smoke'
    const spacyModel = process.env.CANDYCONC_IMPORT_SMOKE_SPACY_MODEL ?? 'blank:de'
    test.skip(!importInput, 'CANDYCONC_IMPORT_SMOKE_INPUT fehlt.')

    await page.goto('/')
    const corpusManagerButton = page.locator('button[title^="Korpora verwalten"]').first()
    await expect(corpusManagerButton).toBeVisible({ timeout: 30_000 })
    await corpusManagerButton.click()

    await expect(page.getByTestId('corpus-manager')).toBeVisible()
    const importCard = page.getByTestId('corpus-import-card')
    await expect(importCard).toContainText('Serverpfad importieren')

    await importCard.getByTestId('corpus-import-method').selectOption(importMethod)
    await importCard.getByTestId('corpus-import-target-name').fill(targetName)
    await importCard.getByTestId('corpus-import-input-path').fill(importInput)
    await importCard
      .getByRole('textbox', { name: /^spaCy-Modell\b/ })
      .fill(spacyModel)

    const preflightResponse = page.waitForResponse((response) =>
      response.url().includes('/api/v1/corpora/import-preflight') &&
      response.request().method() === 'POST' &&
      response.status() === 200,
    )
    await importCard.getByTestId('corpus-import-preflight-button').click()
    const preflight = await (await preflightResponse).json() as { ok?: boolean; evidence?: { columns?: string[] } }
    expect(preflight.ok).toBe(true)
    expect(preflight.evidence?.columns).toEqual(expect.arrayContaining(['text', 'pair_id', 'pair_role']))
    await expect(importCard).toContainText(/Import-Preflight: (bestanden|Warnungen)/)
    await expect(importCard).toContainText('Spalten/Felder')

    const unexpectedImportDialogs: string[] = []
    const captureUnexpectedImportDialog = async (dialog: Dialog) => {
      unexpectedImportDialogs.push(dialog.message())
      await dialog.accept()
    }
    page.on('dialog', captureUnexpectedImportDialog)
    const startResponse = page.waitForResponse((response) =>
      response.url().includes('/api/v1/corpora/imports') &&
      response.request().method() === 'POST' &&
      response.status() === 202,
    )
    await importCard.getByTestId('corpus-import-start-button').click()
    const started = await (await startResponse).json() as { job_id?: string }
    expect(started.job_id).toBeTruthy()
    expect(unexpectedImportDialogs).toEqual([])
    page.off('dialog', captureUnexpectedImportDialog)

    const jobCard = page
      .getByTestId('corpus-import-job-card')
      .filter({ hasText: targetName })
      .first()
    await expect(jobCard).toBeVisible({ timeout: 30_000 })
    await waitForImportDone(request, started.job_id!)

    const statusResponse = page.waitForResponse((response) =>
      response.url().includes(`/api/v1/corpora/imports/${encodeURIComponent(started.job_id!)}`) &&
      response.request().method() === 'GET' &&
      response.status() === 200,
    )
    await jobCard.getByRole('button', { name: 'Status prüfen' }).click()
    await statusResponse

    await expect(jobCard).toContainText('done')

    const reportsResponse = page.waitForResponse((response) =>
      response.url().includes(`/api/v1/corpora/imports/${encodeURIComponent(started.job_id!)}/reports`) &&
      response.request().method() === 'GET' &&
      response.status() === 200,
    )
    await jobCard.getByRole('button', { name: /Reports laden/ }).click()
    const reports = await (await reportsResponse).json() as { schema_version?: string; reports?: Record<string, unknown> }
    expect(reports.schema_version).toBe('corpus-import-reports-v1')
    expect(reports.reports?.manifest).toBeTruthy()
    await expect(jobCard).toContainText('Post-Import-Evidenz', { timeout: 30_000 })
    await expect(jobCard).toContainText('Index-Manifest')
    await expect(jobCard).toContainText('Paarmetadaten')

    const buildReportResponse = page.waitForResponse((response) =>
      response.url().includes(`/api/v1/corpora/${encodeURIComponent(targetName)}/build-report`) &&
      response.status() === 200,
    )
    await jobCard.getByRole('button', { name: /Build-Report prüfen/ }).click()
    await buildReportResponse
    await expect(jobCard).toContainText('Build-Report des Zielkorpus')

    const capabilitiesResponse = page.waitForResponse((response) =>
      response.url().includes(`/api/v1/corpora/${encodeURIComponent(targetName)}/capabilities`) &&
      response.status() === 200,
    )
    await jobCard.getByRole('button', { name: /Fähigkeiten des Zielkorpus prüfen/ }).click()
    await capabilitiesResponse

    const activateButton = jobCard.getByRole('button', { name: /Zielkorpus aktivieren/ })
    if (await activateButton.isVisible()) {
      const activationResponse = page.waitForResponse((response) =>
        response.url().includes(`/api/v1/corpora/${encodeURIComponent(targetName)}/activate`) &&
        response.request().method() === 'POST' &&
        response.status() === 200,
      )
      await activateButton.click()
      const activated = await (await activationResponse).json() as { name?: string; active?: boolean }
      expect(activated.name).toBe(targetName)
      expect(activated.active).toBe(true)
    }
    await expect(jobCard).toContainText('aktiv')

    await page.getByRole('button', { name: 'Schließen' }).click()
    await expect(page.getByTestId('corpus-manager')).toHaveCount(0)

    const targetQueryResponse = page.waitForResponse((response) => {
      if (!response.url().includes('/api/v1/query/stream') || response.status() !== 200) return false
      const url = new URL(response.url())
      return url.searchParams.get('term') === 'rabbit'
    })
    await page.locator('[data-search-input]').fill('rabbit')
    await page.getByRole('button', { name: 'Suche starten' }).click()
    const importedQuery = await targetQueryResponse
    const importedQueryUrl = new URL(importedQuery.url())
    expect(importedQueryUrl.searchParams.get('corpus')).toBe(targetName)

    const importedRow = page.getByTestId('kwic-row-0')
    await expect(importedRow).toBeVisible({ timeout: 30_000 })
    await expect(importedRow.getByTestId('kwic-row-match')).toContainText(/rabbit/i)

    // Parallel projection prefetches visible rows. A native confirmation here
    // would re-open once per row and prevent the projection from ever loading.
    const unexpectedDialogs: string[] = []
    const consoleMessages: string[] = []
    const captureParallelDialog = async (dialog: Dialog) => {
      unexpectedDialogs.push(dialog.message())
      await dialog.dismiss()
    }
    const captureParallelConsole = (message: ConsoleMessage) => {
      if (message.type() === 'error' || message.type() === 'warning') {
        consoleMessages.push(message.text())
      }
    }
    page.on('dialog', captureParallelDialog)
    page.on('console', captureParallelConsole)
    const parallelResponse = page.waitForResponse((response) =>
      response.url().includes('/api/v1/analysis/kwic_parallel') &&
      response.request().method() === 'POST' &&
      response.status() === 200,
    )
    const parallelToggle = page.locator('.parallel-toggle input[type="checkbox"]')
    await expect(parallelToggle).toBeVisible({ timeout: 30_000 })
    await parallelToggle.check()
    const parallelModelSelect = page.locator('select.parallel-select--models')
    await expect(parallelModelSelect.locator('option[value="target"]')).toHaveCount(1)
    await parallelModelSelect.selectOption('target')
    await parallelResponse
    await expect(importedRow.locator('.row-variant').first()).toBeVisible()
    await parallelToggle.uncheck()
    await expect(parallelToggle).not.toBeChecked()
    await expect(importedRow.locator('.row-variant')).toHaveCount(0)
    await page.waitForTimeout(200)
    expect(unexpectedDialogs).toEqual([])
    expect(consoleMessages.join('\n')).not.toContain('Maximum recursive updates')
    page.off('dialog', captureParallelDialog)
    page.off('console', captureParallelConsole)
  })
})
