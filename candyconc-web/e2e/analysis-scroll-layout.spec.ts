import { expect, test, type Locator, type Page } from '@playwright/test'

// Every analysis view scrolls, and its result table gets the space of the tab.
//
// Measured against a running server with the sample corpora of the
// documentation: sotu_en (examples/sotu_en_1945_2006.jsonl, imported with the
// commands in examples/README.md) and paired_en (paired.csv from
// docs/guides/bring-in-texts/import-paired-versions.md).
//
//   CANDYCONC_LAYOUT_LIVE=1 CANDYCONC_FRONTEND_PORT=5173 \
//     npx playwright test e2e/analysis-scroll-layout.spec.ts --project=chromium
//
// Before the repair the tab area clipped its content (overflow hidden): the
// contrast results started below the window and could not be reached, the
// keyness table kept 167 px of a 900 px window, the collocation table shrank
// to 0 px when the method card was open, the second line of the parallel
// concordance lay below the clipped table, and the floating copilot button
// covered the first column of every table.

test.skip(process.env.CANDYCONC_LAYOUT_LIVE !== '1', 'Runs only with CANDYCONC_LAYOUT_LIVE=1 against a server with the sample corpora.')

type Lang = 'en' | 'de'

const L = {
  en: {
    openFilter: 'Open filters and subcorpus',
    applyMeta: 'Apply metadata',
    fieldA: 'Field for group A',
    valueA: 'Value for group A',
    fieldB: 'Field for group B',
    valueB: 'Value for group B',
    compute: 'Compute contrast',
    parallel: 'Parallel concordance',
    method: 'Method and reproducibility',
    moreTabs: /^More tabs/,
  },
  de: {
    openFilter: 'Filter und Subkorpus öffnen',
    applyMeta: 'Metadaten anwenden',
    fieldA: 'Feld Gruppe A',
    valueA: 'Wert Gruppe A',
    fieldB: 'Feld Gruppe B',
    valueB: 'Wert Gruppe B',
    compute: 'Kontrast berechnen',
    parallel: 'Parallel-KWIC',
    method: 'Methode / Reproduzierbarkeit',
    moreTabs: /^Weitere Tabs/,
  },
} as const

const VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 1280, height: 800 },
] as const

async function boot(page: Page, lang: Lang, params: Record<string, string>) {
  await page.addInitScript((language) => {
    localStorage.setItem('candyconc_onboarding_completed', 'true')
    localStorage.setItem('candyconc_seen_features', JSON.stringify(['search', 'tabs', 'kwic', 'copilot', 'export', 'export-dialog']))
    localStorage.setItem('candyconc_preferences', JSON.stringify({ language }))
  }, lang)
  await page.goto(`/?${new URLSearchParams(params).toString()}`)
  await expect(page.locator('.tab-content')).toBeVisible()
}

interface Rect { top: number, bottom: number, left: number, right: number, height: number }

async function tabRect(page: Page): Promise<Rect> {
  return page.locator('.tab-content').evaluate((el) => {
    const r = el.getBoundingClientRect()
    return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, height: r.height }
  })
}

// Scroll the way a reader does: with the mouse wheel over the middle of the tab.
async function wheelDown(page: Page, times = 30, delta = 400) {
  const r = await tabRect(page)
  await page.mouse.move((r.left + r.right) / 2, r.top + r.height / 2)
  for (let i = 0; i < times; i++) {
    await page.mouse.wheel(0, delta)
    await page.waitForTimeout(40)
  }
  await page.waitForTimeout(300)
}

// Wheel until the whole element stands inside the tab area, then check that it
// is the element drawn at its centre: not clipped by a container, not covered.
async function reachByWheel(page: Page, target: Locator, maxSteps = 40) {
  await target.waitFor({ state: 'attached' })
  const r = await tabRect(page)
  await page.mouse.move((r.left + r.right) / 2, r.top + Math.min(120, r.height / 3))
  const inside = (box: { y: number, height: number } | null) =>
    !!box && box.y >= r.top - 1 && box.y + Math.min(box.height, r.height) <= r.bottom + 1
  for (let i = 0; i < maxSteps; i++) {
    if (inside(await target.boundingBox())) break
    await page.mouse.wheel(0, 250)
    await page.waitForTimeout(60)
  }
  await page.waitForTimeout(200)
  expect(inside(await target.boundingBox()), 'element can be scrolled fully into the tab area').toBe(true)
  const hit = await target.evaluate((node, height) => {
    const b = node.getBoundingClientRect()
    const x = b.left + Math.min(b.width, 40) / 2
    const y = b.top + Math.min(b.height, height) / 2
    const el = document.elementFromPoint(x, y)
    return !!el && (node === el || node.contains(el) || el.contains(node))
  }, r.height)
  expect(hit, 'element is drawn on top at its centre').toBe(true)
}

// Height of the part of the element that lies inside the visible tab area.
async function visibleHeight(page: Page, target: Locator) {
  const r = await tabRect(page)
  const box = await target.boundingBox()
  if (!box) return 0
  return Math.max(0, Math.min(box.y + box.height, r.bottom) - Math.max(box.y, r.top))
}

// Switch tabs inside the running page, so that the active subcorpus stays.
async function openTab(page: Page, lang: Lang, name: string) {
  const tab = page.getByRole('tab', { name: new RegExp(`^${name}`) })
  if (await tab.count() && await tab.first().isVisible()) {
    await tab.first().click()
  } else {
    await page.getByRole('button', { name: L[lang].moreTabs }).click()
    await page.getByRole('menuitem', { name: new RegExp(`^${name}`) }).click()
  }
}

async function waitForKwic(page: Page) {
  await page.locator('[data-testid="kwic-row-0"]').waitFor({ timeout: 60_000 })
}

test.describe('analysis views scroll and give the table the tab', () => {
  test.skip(({ isMobile }) => isMobile, 'Mobile widths run in their own test below.')
  test.setTimeout(180_000)

  for (const lang of ['en', 'de'] as const) {
    for (const vp of VIEWPORTS) {
      const where = `${vp.width}x${vp.height} (${lang})`

      test(`contrast results are reachable at ${where}`, async ({ page }) => {
        await page.setViewportSize(vp)
        await boot(page, lang, { corpus: 'sotu_en', tab: 'kwic', q: 'freedom', run: '1' })
        await waitForKwic(page)
        await page.goto('/?corpus=sotu_en&tab=contrast&q=freedom&run=1')
        await page.getByLabel(L[lang].fieldA).selectOption('party')
        await page.getByLabel(L[lang].valueA).selectOption('Republican')
        await page.getByLabel(L[lang].fieldB).selectOption('party')
        await page.getByLabel(L[lang].valueB).selectOption('Democratic')
        await page.getByRole('button', { name: L[lang].compute }).click()
        const firstRow = page.locator('.fc-table tbody tr').first()
        await firstRow.waitFor({ timeout: 120_000 })
        await reachByWheel(page, page.locator('.diversity-table tbody tr').last())
        await reachByWheel(page, page.locator('.fc-table tbody tr').last())
      })

      test(`the keyness table gets the tab at ${where}`, async ({ page }) => {
        await page.setViewportSize(vp)
        await boot(page, lang, { corpus: 'sotu_en', tab: 'kwic' })
        await page.getByRole('button', { name: L[lang].openFilter }).click()
        const panel = page.getByRole('dialog').last()
        const decade = panel.locator('select').filter({ has: page.locator('option[value="1940s"]') })
        await decade.locator('option[value="1940s"]').click()
        await decade.locator('option[value="1950s"]').click({ modifiers: [process.platform === 'darwin' ? 'Meta' : 'Control'] })
        await panel.getByRole('button', { name: L[lang].applyMeta }).click()
        await page.waitForTimeout(800)
        await page.keyboard.press('Escape')
        await openTab(page, lang, 'Keyness')
        await page.locator('main').getByRole('button', { name: 'Keyness', exact: true }).click()
        const table = page.locator('.keyness-table')
        await table.locator('tbody tr').nth(5).waitFor({ timeout: 120_000 })
        await wheelDown(page)
        const tab = await tabRect(page)
        const container = page.locator('.keyness-table').locator('xpath=..')
        expect(await visibleHeight(page, container), 'keyness table fills the tab area').toBeGreaterThanOrEqual(tab.height - 4)
        const head = await table.locator('thead th').first().boundingBox()
        expect(head && head.y, 'the column header stays at the top of the tab').toBeLessThanOrEqual(tab.top + 2)
      })

      test(`the collocation table keeps the tab with the method card open at ${where}`, async ({ page }) => {
        await page.setViewportSize(vp)
        await boot(page, lang, { corpus: 'sotu_en', tab: 'collocations', q: 'freedom', run: '1' })
        const rows = page.locator('.coll-table tbody tr')
        await rows.nth(5).waitFor({ timeout: 120_000 })
        await page.locator('main').getByText(L[lang].method).first().click()
        const lastStat = page.locator('.method-table tbody tr').last()
        await lastStat.waitFor()
        await reachByWheel(page, lastStat)
        await wheelDown(page)
        const tab = await tabRect(page)
        const container = page.locator('.coll-table').locator('xpath=..')
        expect(await visibleHeight(page, container), 'collocation table fills the tab area').toBeGreaterThanOrEqual(tab.height - 4)
      })

      test(`every relation of the word sketch is reachable at ${where}`, async ({ page }) => {
        await page.setViewportSize(vp)
        await boot(page, lang, { corpus: 'sotu_en', tab: 'wordsketch', q: 'freedom', run: '1' })
        const cards = page.locator('.relations-grid .relation-card')
        await cards.nth(3).waitFor({ timeout: 120_000 })
        // The heading "Word sketch for" starts where the tables start.
        const textStart = await page.locator('.wordsketch-tab > p.search-hint').first().evaluate((el) => {
          const range = document.createRange()
          range.selectNodeContents(el)
          return range.getBoundingClientRect().left
        })
        const firstCard = await cards.first().boundingBox()
        expect(Math.abs(textStart - firstCard!.x), 'heading and tables share their left edge').toBeLessThanOrEqual(2)
        await reachByWheel(page, cards.last().locator('tr').last())
        await wheelDown(page)
        const tab = await tabRect(page)
        const grid = page.locator('.relations-grid').first()
        expect(await visibleHeight(page, grid), 'relation tables fill the tab area').toBeGreaterThanOrEqual(tab.height - 40)
      })

      test(`the second line of the parallel concordance is reachable at ${where}`, async ({ page }) => {
        await page.setViewportSize(vp)
        await boot(page, lang, { corpus: 'paired_en', tab: 'kwic', q: 'museum', run: '1' })
        await waitForKwic(page)
        await page.getByText(L[lang].parallel, { exact: true }).click()
        const variants = page.locator('main select').filter({ has: page.locator('option[value="easy"]') })
        await variants.locator('option[value="easy"]').click()
        const second = page.locator('[data-testid="kwic-row-1"]')
        await second.waitFor()
        await page.waitForTimeout(1500)
        await reachByWheel(page, second)
        // The counterpart sentence is shown whole, not cut to the column width.
        const counterpart = page.locator('[data-testid="kwic-row-0"] .variant-context')
        await expect(counterpart).toContainText('early on Friday')
        expect(await counterpart.evaluate((el) => el.scrollHeight <= el.clientHeight + 1), 'counterpart fits its cell').toBe(true)
      })

      test(`nodes of two tokens are not cut and the concordance has one save button at ${where}`, async ({ page }) => {
        await page.setViewportSize(vp)
        await boot(page, lang, { corpus: 'sotu_en', tab: 'kwic', q: 'cql:[pos="ADJ"] [lemma="freedom"%c]', run: '1' })
        await waitForKwic(page)
        await page.waitForTimeout(800)
        const cut = await page.locator('[data-testid="kwic-row-match"]').evaluateAll((cells) =>
          cells.filter((cell) => cell.scrollWidth > cell.clientWidth + 1).map((cell) => cell.textContent?.trim()))
        expect(cut, 'node cells whose text is cut').toEqual([])
        const save = lang === 'en' ? 'Save subcorpus' : 'Subkorpus speichern'
        await expect(page.locator('main').getByRole('button', { name: save, exact: true })).toHaveCount(1)
      })

      test(`the copilot button covers no content at ${where}`, async ({ page }) => {
        await page.setViewportSize(vp)
        await boot(page, lang, { corpus: 'sotu_en', tab: 'kwic', q: 'freedom', run: '1' })
        await waitForKwic(page)
        const trigger = page.locator('.copilot-trigger')
        await expect(trigger).toBeVisible()
        const t = await trigger.boundingBox()
        const tab = await tabRect(page)
        expect(t, 'copilot button is rendered').toBeTruthy()
        const overlaps = t!.x < tab.right && t!.x + t!.width > tab.left && t!.y < tab.bottom && t!.y + t!.height > tab.top
        expect(overlaps, 'copilot button lies outside the tab area').toBe(false)
      })
    }
  }

  test('every analysis tab can be scrolled to its end (1440x900, en)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    const tabs = ['frequency', 'collocations', 'collocation_network', 'dispersion', 'semantic', 'ngrams', 'contrast', 'keyness', 'wordsketch', 'trend']
    await boot(page, 'en', { corpus: 'sotu_en', tab: 'kwic', q: 'freedom', run: '1' })
    await waitForKwic(page)
    for (const tab of tabs) {
      await page.goto(`/?corpus=sotu_en&tab=${tab}&q=freedom&run=1`)
      await page.waitForTimeout(4000)
      await wheelDown(page, 40, 500)
      const m = await page.locator('.tab-content').evaluate((el) => ({ top: el.scrollTop, sh: el.scrollHeight, ch: el.clientHeight }))
      expect(m.top + m.ch, `${tab}: the end of the tab is reachable`).toBeGreaterThanOrEqual(m.sh - 2)
    }
  })
})

test.describe('analysis views on a phone', () => {
  test.skip(({ isMobile }) => !isMobile, 'Uses the mobile projects.')
  test.setTimeout(180_000)

  test('the copilot button of the phone bar covers neither the status bar nor a tab', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await boot(page, 'en', { corpus: 'sotu_en', tab: 'kwic', q: 'freedom', run: '1' })
    await waitForKwic(page)
    const fab = await page.locator('.mobile-nav .copilot-fab').boundingBox()
    expect(fab, 'the copilot button is rendered').toBeTruthy()
    // Tabs count with the part that the scrolling tab list shows.
    const others = await page.evaluate(() => {
      const list = document.querySelector('.mobile-nav .nav-scroll')!.getBoundingClientRect()
      return [...document.querySelectorAll('.status-bar, .mobile-nav .nav-item')].map((el) => {
        const r = el.getBoundingClientRect()
        const clip = el.classList.contains('nav-item')
        return {
          name: el.className.toString(),
          left: clip ? Math.max(r.left, list.left) : r.left,
          right: clip ? Math.min(r.right, list.right) : r.right,
          top: r.top,
          bottom: r.bottom,
        }
      }).filter((o) => o.right > o.left)
    })
    const overlapping = others.filter((o) =>
      fab!.x < o.right - 0.5 && fab!.x + fab!.width > o.left + 0.5 && fab!.y < o.bottom - 0.5 && fab!.y + fab!.height > o.top + 0.5)
    expect(overlapping.map((o) => o.name), 'elements under the copilot button').toEqual([])
  })

  test('contrast and keyness results are reachable at phone width', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await boot(page, 'en', { corpus: 'sotu_en', tab: 'kwic', q: 'freedom', run: '1' })
    await waitForKwic(page)
    for (const tab of ['frequency', 'collocations', 'contrast', 'keyness', 'wordsketch']) {
      await page.goto(`/?corpus=sotu_en&tab=${tab}&q=freedom&run=1`)
      await page.waitForTimeout(4000)
      const m = await page.locator('.tab-content').evaluate((el) => {
        el.scrollTop = el.scrollHeight
        return { top: el.scrollTop, sh: el.scrollHeight, ch: el.clientHeight, ov: getComputedStyle(el).overflowY }
      })
      expect(m.ov, `${tab}: the tab area scrolls`).not.toBe('hidden')
      expect(m.top + m.ch, `${tab}: the end of the tab is reachable`).toBeGreaterThanOrEqual(m.sh - 2)
    }
  })
})

test.describe('panels', () => {
  test.skip(({ isMobile }) => isMobile, 'Desktop panels.')
  test.setTimeout(180_000)

  test('the tab bar of the workspace hides the content scrolled beneath it', async ({ page }) => {
    // A low window, so that the job list is longer than the panel.
    await page.setViewportSize({ width: 1440, height: 640 })
    await boot(page, 'en', { corpus: 'sotu_en', tab: 'kwic', q: 'freedom', run: '1' })
    await waitForKwic(page)
    // Three analysis jobs make the job list of the workspace longer than the panel.
    for (const tab of ['frequency', 'ngrams', 'collocations']) {
      await page.goto(`/?corpus=sotu_en&tab=${tab}&q=freedom&run=1`)
      await page.waitForTimeout(3000)
    }
    await page.getByRole('button', { name: 'Saved analyses', exact: true }).click()
    const panel = page.getByRole('dialog').last()
    const content = panel.locator('.slide-over-content')
    await content.hover()
    for (let i = 0; i < 6; i++) await page.mouse.wheel(0, 150)
    await page.waitForTimeout(400)
    const probe = await content.evaluate((el) => {
      const r = el.getBoundingClientRect()
      const tabs = el.querySelector('.workspace-tabs')!
      const points = [r.top + 2, r.top + 10, tabs.getBoundingClientRect().top + 2]
      return {
        scrolled: el.scrollTop,
        hits: points.map((y) => {
          const hit = document.elementFromPoint(r.left + r.width / 2, y)
          return !!hit && (tabs === hit || tabs.contains(hit))
        }),
        background: getComputedStyle(tabs).backgroundColor,
      }
    })
    expect(probe.scrolled, 'the panel was scrolled').toBeGreaterThan(100)
    expect(probe.hits, 'the tab bar covers the top edge of the panel').toEqual([true, true, true])
    expect(probe.background, 'the tab bar is opaque').not.toMatch(/\/ 0\.|, 0\.\d+\)$/)
  })

  test('the six tabs of the settings panel stay inside the panel', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await boot(page, 'en', { corpus: 'sotu_en', tab: 'kwic' })
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    const nav = page.getByRole('dialog').last().locator('.settings-tabs')
    await nav.waitFor()
    const m = await nav.evaluate((el) => {
      const box = el.getBoundingClientRect()
      return {
        scroll: el.scrollWidth - el.clientWidth,
        outside: [...el.querySelectorAll('button')]
          .filter((b) => { const r = b.getBoundingClientRect(); return r.left < box.left - 1 || r.right > box.right + 1 })
          .map((b) => b.textContent?.trim()),
      }
    })
    expect(m.outside, 'tabs outside the visible panel').toEqual([])
    expect(m.scroll, 'the tab row does not scroll sideways').toBeLessThanOrEqual(1)
  })

  test('the filter panel shows metadata values in full width', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await boot(page, 'en', { corpus: 'sotu_en', tab: 'kwic' })
    await page.getByRole('button', { name: L.en.openFilter }).click()
    const panel = page.getByRole('dialog').last()
    const name = 'Dwight D. Eisenhower'
    const select = panel.locator('select').filter({ has: page.locator('option', { hasText: new RegExp(`^\\s*${name}\\s*$`) }) })
    await select.first().waitFor()
    // Text width of the name in the font of each list that offers it as a
    // value, against the inner width of the list.
    const fits = await select.evaluateAll((els, text) => els.map((el) => {
      const style = getComputedStyle(el)
      const context = document.createElement('canvas').getContext('2d')!
      context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`
      const inner = el.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)
      return { widest: Math.round(context.measureText(text).width), inner: Math.round(inner) }
    }), name)
    expect(fits.length).toBeGreaterThan(0)
    for (const fit of fits) {
      expect(fit.widest, 'the longest name fits into the list').toBeLessThanOrEqual(fit.inner)
    }
  })

  // Needs an import job on the server: one started in this session, or the
  // CSV at CANDYCONC_LAYOUT_IMPORT_CSV (a path the server can read), which the
  // test imports as layout_probe.
  test('import provenance keeps long paths in their cells and report toggles are light', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await boot(page, 'en', { corpus: 'sotu_en', tab: 'kwic' })
    await page.getByRole('button', { name: 'Manage corpora', exact: true }).click()
    const panel = page.getByRole('dialog').last()
    await panel.getByText('Corpus manager', { exact: true }).first().waitFor()
    await page.waitForTimeout(1500)
    if (!(await panel.locator('.job-provenance').count())) {
      const csv = process.env.CANDYCONC_LAYOUT_IMPORT_CSV
      test.skip(!csv, 'No import job on the server and no CANDYCONC_LAYOUT_IMPORT_CSV.')
      await panel.locator('select').filter({ has: page.locator('option[value="csv"]') }).first().selectOption('csv')
      await panel.getByLabel(/^Target name/).fill('layout_probe')
      await panel.getByLabel(/^Server file/).fill(csv!)
      await panel.getByLabel(/^Corpus language/).selectOption('en')
      await panel.getByLabel(/^ID column/).fill('id')
      await panel.getByRole('button', { name: 'Check input' }).click()
      await panel.getByRole('button', { name: 'Start import' }).click()
    }
    await panel.getByText('Complete according to the report', { exact: false }).first().waitFor({ timeout: 300_000 })
    await page.waitForTimeout(1000)
    const result = await panel.evaluate((root) => {
      const cells = [...root.querySelectorAll('.job-provenance .trace-grid span')]
      const toggles = [...root.querySelectorAll('details.report-snippet, details.report-full')].filter((d) => !(d as HTMLDetailsElement).open)
      const luminance = (color: string) => {
        const [r, g, b] = (color.match(/\d+(\.\d+)?/g) ?? ['255', '255', '255']).map(Number)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
      }
      return {
        cells: cells.length,
        overflowing: cells.filter((c) => c.scrollWidth > c.clientWidth + 1).map((c) => c.textContent?.slice(0, 40)),
        toggles: toggles.length,
        dark: toggles.filter((d) => luminance(getComputedStyle(d).backgroundColor) < 128).length,
      }
    })
    expect(result.cells, 'provenance cells are rendered').toBeGreaterThan(0)
    expect(result.overflowing, 'provenance cells whose text runs out').toEqual([])
    expect(result.toggles, 'closed report toggles are rendered').toBeGreaterThan(0)
    expect(result.dark, 'closed report toggles drawn as dark bars').toBe(0)
  })
})


for (const viewport of VIEWPORTS) {
  test(`co-anchor highlighting preserves spacing and the context next to the node at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await boot(page, 'en', {
      corpus: 'sotu_en', tab: 'kwic', run: '1',
      q: 'co(term="freedom", collocate="peace", window=5, within_sentence=true)',
    })
    const left = page.getByTestId('kwic-row-0').getByTestId('kwic-row-left')
    await expect(left).toContainText('lasting peace, with greater')
    await expect(left.locator('.kwic-collocate')).toHaveText('peace')
    const spacing = await left.evaluate((el) => {
      const before = el.querySelector('.kwic-collocate')!.previousElementSibling!
      const text = before.firstChild!
      const range = document.createRange()
      range.setStart(text, text.textContent!.length - 1)
      range.setEnd(text, text.textContent!.length)
      return { character: range.toString(), width: range.getBoundingClientRect().width }
    })
    expect(spacing.character).toBe(' ')
    expect(spacing.width, 'the original space occupies visible width before the co-anchor').toBeGreaterThan(1)
    for (const [index, ending] of [[0, 'greater'], [3, 'and']] as const) {
      const context = page.getByTestId(`kwic-row-${index}`).getByTestId('kwic-row-left')
      await expect(context).toContainText(ending)
      const edge = await context.evaluate((el) => {
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
        let last: Text | null = null
        while (walker.nextNode()) {
          if (walker.currentNode.textContent?.trim()) last = walker.currentNode as Text
        }
        const end = last!.textContent!.trimEnd().length
        const range = document.createRange()
        range.setStart(last!, end - 1)
        range.setEnd(last!, end)
        const glyph = range.getBoundingClientRect()
        const cell = el.getBoundingClientRect()
        return { character: range.toString(), left: glyph.left, right: glyph.right, cellLeft: cell.left, cellRight: cell.right }
      })
      expect(edge.character).toBe(ending.at(-1))
      expect(edge.left, 'the last character starts inside the context cell').toBeGreaterThanOrEqual(edge.cellLeft)
      expect(edge.right, 'the node-adjacent context is never clipped on the right').toBeLessThanOrEqual(edge.cellRight + 0.5)
    }
  })
}
