import { expect, test, type Page } from '@playwright/test'

// The run history toolbar of the copilot (search, Filter, Projects, JSON, CSV)
// did not wrap. Its minimum width stretched the docked panel beyond the
// sidebar and the window: in English the sidebar showed "Filter Projects"
// cut off at the edge, JSON and CSV lay outside the window, and in the
// mobile sheet at 320 px the row ended in "Filter P".

function capability(id: string, path: string, methods: string[] = ['GET']) {
  const route = {
    path,
    methods,
    mutates: methods.some((method) => method !== 'GET'),
    requires_corpus_features: [],
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

async function bootEnglishShell(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('candyconc_onboarding_completed', 'true')
    localStorage.setItem('candyconc_seen_features', JSON.stringify(['search', 'tabs', 'kwic', 'copilot', 'export', 'export-dialog']))
    localStorage.setItem('candyconc_preferences', JSON.stringify({ language: 'en' }))
  })
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
        scope: 'CandyConc copilot layout smoke contract',
        fingerprint_sha256: 'a'.repeat(64),
        cqlf_capability_contract: { version: 'cqlf-capabilities-v1', current_level: '2-', fingerprint_sha256: 'b'.repeat(64), capabilities: [] },
        capabilities: [
          capability('query.kwic', '/api/v1/query'),
          capability('research.copilot_grounding', '/api/v1/chat/stream', ['POST']),
        ],
      }
    } else if (path === '/api/v1/corpora') body = { corpora: [], count: 0 }
    else if (path === '/mcp/tools') body = { tools: [], tool_statuses: [] }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/')
}

async function openRunHistory(page: Page, docked: boolean) {
  await page.getByRole('button', { name: /^Open copilot/ }).last().click()
  const panel = page.locator('.copilot-panel')
  await expect(panel).toBeVisible()
  if (docked) {
    await panel.getByRole('button', { name: 'Dock', exact: true }).click()
    await expect(page.locator('.copilot-sidebar .copilot-panel')).toBeVisible()
  }
  await page.locator('.copilot-panel .tab-btn').nth(1).click()
  await expect(page.locator('.run-history-panel .toolbar')).toBeVisible()
}

/** Every control of the toolbar lies inside the panel and inside the window. */
async function expectToolbarInside(page: Page) {
  const box = await page.evaluate(() => {
    const panel = document.querySelector('.copilot-panel')!.getBoundingClientRect()
    const container = (document.querySelector('.copilot-sidebar') ?? document.querySelector('.copilot-panel'))!.getBoundingClientRect()
    const controls = [...document.querySelectorAll('.run-history-panel .toolbar .search-wrapper, .run-history-panel .toolbar button')]
      .filter((el) => (el as HTMLElement).offsetParent !== null)
      .map((el) => {
        const r = el.getBoundingClientRect()
        return { text: (el.textContent ?? '').trim(), left: r.left, right: r.right }
      })
    return { panel: { left: panel.left, right: panel.right }, container: { left: container.left, right: container.right }, width: window.innerWidth, controls }
  })
  expect(box.panel.right).toBeLessThanOrEqual(box.container.right + 1)
  expect(box.panel.right).toBeLessThanOrEqual(box.width + 1)
  for (const control of box.controls) {
    expect(control.left, control.text).toBeGreaterThanOrEqual(box.panel.left - 1)
    expect(control.right, control.text).toBeLessThanOrEqual(box.panel.right + 1)
  }
  expect(box.controls.map((control) => control.text)).toEqual(expect.arrayContaining(['Filter', 'Projects', 'JSON', 'CSV']))
}

test.describe('copilot run history toolbar', () => {
  for (const width of [900, 1440]) {
    test(`fits the docked sidebar at a ${width} px window`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      await bootEnglishShell(page)
      await openRunHistory(page, true)
      await expectToolbarInside(page)
    })
  }

  test('fits the floating panel', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await bootEnglishShell(page)
    await openRunHistory(page, false)
    await expectToolbarInside(page)
  })

  test('fits the mobile sheet at 320 px', async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 700 })
    await bootEnglishShell(page)
    await openRunHistory(page, false)
    await expectToolbarInside(page)
  })
})
