#!/usr/bin/env node
// Capture the screenshots of the documentation from the running application.
//
// The script prepares a data folder with the sample corpora, starts CandyConc
// from this checkout (the server delivers the built web interface, as after an
// installation), drives the interface in Chromium with Playwright, and writes
// one PNG per scenario to docs/_static/screenshots/ plus a manifest.
//
// Rules the script follows, so that every image shows a state a user can reach:
//   * It only operates the interface: clicks, typing, keyboard shortcuts, and
//     the deep links the application supports (?corpus=...&tab=...&q=...&run=1).
//   * No DOM changes, no injected scripts, no intercepted or invented responses.
//   * Images are only cropped (to focus) and losslessly or palette-compressed.
//   * The interface language is set to English in Settings > General.
//
// Usage (from the repository root, see docs/contribute/documentation.md):
//
//   node docs/_tools/capture_screenshots.mjs --manifest PATH [options]
//
// Options:
//   --python PY            Python with the CandyConc dependencies (default: python3)
//   --home DIR             neutral home folder for the run (default: /tmp/demo).
//                          It is deleted and created again, so it must not exist
//                          or must carry the marker file of an earlier run.
//   --port N               port of the server (default: 8076)
//   --frontend-dist DIR    built web interface (default: app/src/candyconc/web_dist
//                          from packaging/build_web.py, otherwise a Vite build into
//                          the temporary folder of the system)
//   --pipelines DIR        folder with installed spaCy pipelines (en_core_web_md,
//                          de_core_news_md), linked as CAPTURE_ROOT/.candyconc/pipelines
//   --corpora-from DIR     copy the indexes sotu_en and dta_de from DIR instead of
//                          importing examples/*.jsonl with the documented commands
//   --out DIR              image folder (default: docs/_static/screenshots)
//   --manifest PATH        manifest file (default: docs/_build/screenshots_manifest.json)
//   --only a,b             capture only these scenarios (ids below)
//   --no-optimize          keep the PNG files as Chromium wrote them
//   --attach               use a server already running on --port with the
//                          corpora in place (for writing new scenarios)
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import crypto from 'node:crypto'
import { spawn, execFileSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

// ---------------------------------------------------------------------------
// Arguments and layout

const argv = process.argv.slice(2)
const args = {}
for (let i = 0; i < argv.length; i++) {
  if (!argv[i].startsWith('--')) continue
  const key = argv[i].slice(2)
  const next = argv[i + 1]
  if (next === undefined || next.startsWith('--')) args[key] = true
  else {
    args[key] = next
    i++
  }
}

const DOCS = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const ROOT = findUp(DOCS, (dir) => fs.existsSync(path.join(dir, 'candyconc-web', 'package.json')))
const APP = [path.join(ROOT, 'app'), path.join(ROOT, 'app')].find((d) =>
  fs.existsSync(path.join(d, 'pyproject.toml')),
)
const WEB = path.join(ROOT, 'candyconc-web')
const EXAMPLES = path.join(DOCS, '..', 'examples')

const PORT = Number(args.port ?? 8076)
const BASE = `http://127.0.0.1:${PORT}`
const CAPTURE_ROOT = path.resolve(args.home ?? '/tmp/demo')
const DATA = path.join(CAPTURE_ROOT, '.candyconc')
const WORK = path.join(CAPTURE_ROOT, 'data')
const MARKER = path.join(CAPTURE_ROOT, '.candyconc-screenshot-home')
const PYTHON = args.python ?? 'python3'
const OUT = path.resolve(args.out ?? path.join(DOCS, '_static', 'screenshots'))
const MANIFEST = path.resolve(args.manifest ?? path.join(DOCS, '_build', 'screenshots_manifest.json'))
const ONLY = args.only ? new Set(String(args.only).split(',')) : null
const VIEWPORT = { width: 1440, height: 900 }
const SCALE = 2

function findUp(start, test) {
  let dir = start
  for (;;) {
    if (test(dir)) return dir
    const parent = path.dirname(dir)
    if (parent === dir) throw new Error(`no candyconc-web/package.json above ${start}`)
    dir = parent
  }
}

const require = createRequire(path.join(WEB, 'node_modules', 'playwright', 'package.json'))
const { chromium } = require('playwright')
const PLAYWRIGHT_VERSION = require('playwright/package.json').version

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const sha256File = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
const readJson = (file) => JSON.parse(fs.readFileSync(file, 'utf8'))
const log = (...a) => console.log('[capture]', ...a)

function git(...a) {
  try {
    return execFileSync('git', ['-C', ROOT, ...a], { encoding: 'utf8' }).trim()
  } catch {
    return null
  }
}

// ---------------------------------------------------------------------------
// Synthetic example files, verbatim from the pages that use them

const INTERVIEWS_CSV = `id,text,speaker,year
int01,"We moved to the city in the spring. The rent was high, but the work was steady.",A,1998
int02,"My mother kept a garden behind the house. She grew beans, tomatoes and roses.",B,1998
int03,"The factory closed in the winter. Many families left the town that year.",A,2004
int04,"I still remember the river in flood. The water reached the church steps.",C,2004
int05,"We found work again after a long search. The new job paid less, but it was close to home.",B,2011
int06,"The school opened a library for the town. Children read there every afternoon.",C,2011
`

const PAIRED_CSV = `id,pair_id,pair_role,text,level
s1,p1,source,"The committee postponed the decision because the budget figures were incomplete.",original
s1e,p1,easy,"The committee did not decide yet. The numbers for the money were not complete.",easy
s2,p2,source,"Residents are advised to remain indoors until the storm has passed.",original
s2e,p2,easy,"People should stay inside. They can go out when the storm is over.",easy
s3,p3,source,"The museum will close early on Friday because of the concert.",original
s3e,p3,easy,"The museum will close early on Friday. There is a concert.",easy
`

// ---------------------------------------------------------------------------
// Data folder and server

function prepareHome() {
  if (fs.existsSync(CAPTURE_ROOT)) {
    if (!fs.existsSync(MARKER)) {
      throw new Error(`${CAPTURE_ROOT} exists and was not created by this script. Choose another --home.`)
    }
    fs.rmSync(CAPTURE_ROOT, { recursive: true, force: true })
  }
  fs.mkdirSync(DATA, { recursive: true })
  fs.mkdirSync(WORK, { recursive: true })
  fs.writeFileSync(MARKER, 'Created by docs/_tools/capture_screenshots.mjs. Deleted on the next run.\n')
  if (args.pipelines) fs.symlinkSync(path.resolve(args.pipelines), path.join(DATA, 'pipelines'))
  fs.writeFileSync(path.join(WORK, 'interviews.csv'), INTERVIEWS_CSV)
  fs.writeFileSync(path.join(WORK, 'paired.csv'), PAIRED_CSV)
}

function serverEnv() {
  const pythonPath = [path.join(APP, 'src'), path.join(DATA, 'pipelines')]
  return {
    PATH: process.env.PATH,
    LANG: 'en_US.UTF-8',
    HOME: process.env.HOME,
    // The server refuses an index below the temporary folder. A home below
    // /tmp therefore needs a temporary folder next to it.
    TMPDIR: path.join(path.dirname(CAPTURE_ROOT), `${path.basename(CAPTURE_ROOT)}-tmp`),
    CANDYCONC_HOME: DATA,
    CANDYCONC_CONFIG_FILE: path.join(CAPTURE_ROOT, 'config.toml'),
    // No language model. The endpoints point to a closed port, so nothing can
    // reach a model server during the capture.
    COPILOT_ENDPOINT: 'http://127.0.0.1:9/v1/responses',
    CANDYCONC_GEMMA_EMB_ENDPOINT: 'http://127.0.0.1:9/v1/embeddings',
    CANDYCONC_FRONTEND_DIST: FRONTEND_DIST,
    PYTHONPATH: pythonPath.join(path.delimiter),
    PYTHONNOUSERSITE: '1',
    // The disk check of the import keeps 5 GB free by default. On a machine
    // with less free space, CANDYCONC_BUILD_DISK_RESERVE_GB of the capture
    // run lowers it (the sample corpora need well under 100 MB).
    ...(process.env.CANDYCONC_BUILD_DISK_RESERVE_GB
      ? { CANDYCONC_BUILD_DISK_RESERVE_GB: process.env.CANDYCONC_BUILD_DISK_RESERVE_GB }
      : {}),
  }
}

function runPython(argsList, label) {
  log(label)
  execFileSync(PYTHON, argsList, { cwd: ROOT, env: serverEnv(), stdio: ['ignore', 'inherit', 'inherit'] })
}

async function startServer() {
  fs.mkdirSync(serverEnv().TMPDIR, { recursive: true })
  const logPath = path.join(CAPTURE_ROOT, 'server.log')
  // Connections of an earlier run can hold the port for up to a minute after
  // that server stopped (TIME_WAIT), and the server refuses a port it cannot
  // bind. The start is then repeated.
  for (let attempt = 0; attempt < 20; attempt++) {
    const logFile = fs.openSync(logPath, 'a')
    // Like the application bundle: the server runs in the data folder.
    const child = spawn(PYTHON, ['-m', 'candyconc.entrypoints.cli', '--port', String(PORT)], {
      cwd: DATA,
      env: serverEnv(),
      stdio: ['ignore', logFile, logFile],
    })
    for (let i = 0; i < 180; i++) {
      if (child.exitCode !== null) break
      try {
        const res = await fetch(`${BASE}/api/v1/health`)
        if (res.ok) return child
      } catch {}
      await sleep(500)
    }
    if (child.exitCode === null) {
      child.kill('SIGTERM')
      throw new Error('server did not answer /api/v1/health within 90 s')
    }
    const tail = fs.readFileSync(logPath, 'utf8').slice(-400)
    if (!/already in use/.test(tail)) throw new Error(`server exited with ${child.exitCode}, see ${logPath}`)
    log(`port ${PORT} not free yet, starting again in 5 s`)
    await sleep(5000)
  }
  throw new Error(`port ${PORT} stayed in use`)
}

async function stopServer(child) {
  if (!child || child.exitCode !== null) return
  child.kill('SIGINT')
  for (let i = 0; i < 40 && child.exitCode === null; i++) await sleep(250)
  if (child.exitCode === null) child.kill('SIGKILL')
}

function buildFrontend() {
  if (args['frontend-dist']) return path.resolve(args['frontend-dist'])
  const packaged = path.join(APP, 'src', 'candyconc', 'web_dist')
  if (fs.existsSync(path.join(packaged, 'index.html'))) return packaged
  const target = path.join(os.tmpdir(), `candyconc-web-dist-${process.pid}`)
  log(`building the web interface into ${target}`)
  execFileSync('npm', ['exec', '--', 'vite', 'build', '--configLoader', 'runner', '--outDir', target, '--emptyOutDir'], {
    cwd: WEB,
    stdio: ['ignore', 'inherit', 'inherit'],
  })
  return target
}

const FRONTEND_DIST = args.attach ? '(attached server)' : buildFrontend()

function sampleCorpora() {
  const corpora = path.join(DATA, 'corpora')
  fs.mkdirSync(corpora, { recursive: true })
  if (args['corpora-from']) {
    for (const name of ['sotu_en', 'dta_de']) {
      fs.cpSync(path.join(path.resolve(args['corpora-from']), name), path.join(corpora, name), { recursive: true })
    }
    return 'copied from an existing import'
  }
  const cli = ['-m', 'candyconc.entrypoints.cli', 'import']
  runPython(
    [...cli, '--input', path.join(EXAMPLES, 'sotu_en_1945_2006.jsonl'), '--output', path.join(corpora, 'sotu_en'),
      '--language', 'en', '--meta-columns', 'president', 'party', 'year', 'decade', 'date', 'title', '--source', 'state_union'],
    'importing sotu_en (examples/README.md)',
  )
  runPython(
    [...cli, '--input', path.join(EXAMPLES, 'dta_de_1800_1899_sample.jsonl'), '--output', path.join(corpora, 'dta_de'),
      '--language', 'de', '--meta-columns', 'author', 'title', 'year', 'decade', 'genre', 'subgenre', 'url', '--source', 'dta_kernkorpus'],
    'importing dta_de (examples/README.md)',
  )
  return 'imported with the commands in examples/README.md'
}

function pairedCorpus() {
  runPython(
    ['-m', 'candyconc.entrypoints.cli', 'import', '--input', path.join(WORK, 'paired.csv'), '--input-format', 'prealigned-csv',
      '--output', path.join(DATA, 'corpora', 'paired_en'), '--language', 'en', '--meta-columns', 'level'],
    'importing paired_en (guides/bring-in-texts/import-paired-versions.md)',
  )
}

function corpusRecord(name) {
  const dir = path.join(DATA, 'corpora', name)
  if (!fs.existsSync(path.join(dir, 'index_manifest.json'))) return { name, available: false }
  const manifest = readJson(path.join(dir, 'index_manifest.json'))
  const meta = fs.existsSync(path.join(dir, 'index_build_meta.json')) ? readJson(path.join(dir, 'index_build_meta.json')) : {}
  const record = {
    name,
    token_count: meta.token_count ?? null,
    doc_count: meta.doc_count ?? null,
    language: manifest.language ?? null,
    annotation_pipeline: manifest.annotation_pipeline ?? null,
    annotation_pipeline_version: manifest.annotation_pipeline_version ?? null,
    build_fingerprint: manifest.build_fingerprint ?? null,
    builder_revision: manifest.builder_revision ?? null,
  }
  const prepare = readJson(path.join(EXAMPLES, 'prepare_manifest.json')).outputs
  const sources = {
    sotu_en: { file: 'examples/sotu_en_1945_2006.jsonl', synthetic: false, origin: 'C-SPAN State of the Union Address Corpus, NLTK Data package state_union, public domain' },
    dta_de: { file: 'examples/dta_de_1800_1899_sample.jsonl', synthetic: false, origin: 'Deutsches Textarchiv, Kernkorpus, normalized text 1800 to 1899, CC BY-SA 4.0' },
    paired_en: { file: 'paired.csv from guides/bring-in-texts/import-paired-versions.md', synthetic: true, sha256: sha256Text(PAIRED_CSV) },
    interviews: { file: 'interviews.csv from guides/bring-in-texts/import-a-corpus.md', synthetic: true, sha256: sha256Text(INTERVIEWS_CSV) },
  }
  const src = sources[name] ?? {}
  const base = path.basename(src.file ?? '')
  if (prepare[base]) src.sha256 = prepare[base].sha256
  return { ...record, source: src }
}

function sha256Text(text) {
  return crypto.createHash('sha256').update(text).digest('hex')
}

// ---------------------------------------------------------------------------
// Interface helpers (they only operate the interface)

const SEARCH_PLACEHOLDER = 'Enter a word, phrase or query...'

async function open(page, params = {}) {
  const query = new URLSearchParams(params).toString()
  await page.goto(`${BASE}/${query ? `?${query}` : ''}`, { waitUntil: 'networkidle' })
  await sleep(600)
}

async function setEnglish(page) {
  await open(page)
  await page.getByRole('button', { name: /^(Settings|Einstellungen)$/ }).click()
  const select = page.locator('#language')
  await select.waitFor()
  if ((await select.inputValue()) !== 'en') await select.selectOption('en')
  await sleep(500)
  await page.keyboard.press('Escape')
  await sleep(400)
}

async function search(page, query) {
  const box = page.getByPlaceholder(SEARCH_PLACEHOLDER)
  await box.click()
  await box.fill(query)
  await box.press('Enter')
}

async function waitKwic(page) {
  await page.locator('[data-testid^="kwic-row-"]').first().waitFor({ timeout: 60000 })
  await sleep(1000)
}

async function openTab(page, name) {
  const tab = page.getByRole('tab', { name: new RegExp(`^${name}`) })
  if (await tab.count()) {
    await tab.first().click()
  } else {
    await page.getByRole('button', { name: 'More tabs' }).click()
    await page.getByRole('menuitem', { name: new RegExp(`^${name}`) }).click()
  }
  await sleep(500)
}

async function visible(page, text) {
  return page.getByText(text, { exact: false }).first().waitFor({ timeout: 60000 })
}

async function selectListOptions(scope, anyValue, values) {
  const select = scope.locator('select').filter({ has: scope.page().locator(`option[value="${anyValue}"]`) })
  const modifier = process.platform === 'darwin' ? 'Meta' : 'Control'
  for (const [i, value] of values.entries()) {
    await select.locator(`option[value="${value}"]`).click(i === 0 ? {} : { modifiers: [modifier] })
  }
}

// Crop box in CSS pixels around a locator, with padding, inside the viewport.
async function boxOf(locator, pad = 0) {
  const b = await locator.boundingBox()
  if (!b) throw new Error('crop target not visible')
  const x = Math.max(0, Math.floor(b.x - pad))
  const y = Math.max(0, Math.floor(b.y - pad))
  const right = Math.min(VIEWPORT.width, Math.ceil(b.x + b.width + pad))
  const bottom = Math.min(VIEWPORT.height, Math.ceil(b.y + b.height + pad))
  return { x, y, width: right - x, height: bottom - y }
}

// Wait until the toasts of the last action have expired, so that they do not
// cover the view. A toast that stays (errors do) is recorded in the manifest.
async function toastsGone(page) {
  const toasts = page.locator('.toast-container .toast')
  for (let i = 0; i < 40 && (await toasts.count()) > 0; i++) await sleep(250)
  return toasts.allInnerTexts()
}

// Rest position of the pointer: on the status bar, where hovering changes nothing.
async function parkPointer(page) {
  await page.mouse.move(VIEWPORT.width - 4, VIEWPORT.height - 4)
  await sleep(200)
}

// Scroll with the mouse wheel until the element stands at the given height.
async function scrollToTop(page, locator, top = 200, pointer = { x: 720, y: 600 }) {
  let last = null
  for (let i = 0; i < 25; i++) {
    const b = await locator.boundingBox()
    if (!b) return
    const delta = Math.round(b.y - top)
    if (Math.abs(delta) < 4 || b.y === last) return
    last = b.y
    await page.mouse.move(pointer.x, pointer.y)
    await page.mouse.wheel(0, delta)
    await sleep(350)
  }
}

// Crop from the tab bar to the status bar: the view without the search bar,
// whose height changes with query notes.
async function fromTabs(page) {
  const top = Math.floor((await page.getByRole('tab').first().boundingBox()).y) - 10
  return { x: 0, y: top, width: VIEWPORT.width, height: 851 - top }
}

async function filterPanel(page) {
  await page.getByRole('button', { name: 'Open filters and subcorpus' }).click()
  const panel = page.getByRole('dialog').last()
  await panel.getByText('Metadata filters', { exact: true }).waitFor()
  await sleep(400)
  return panel
}

async function applyFilter(page, anyValue, values) {
  const panel = await filterPanel(page)
  await selectListOptions(panel, anyValue, values)
  await panel.getByRole('button', { name: 'Apply metadata' }).click()
  await sleep(400)
  return panel
}

async function runKeyness(page) {
  await openTab(page, 'Keyness')
  await page.locator('main').getByRole('button', { name: 'Keyness', exact: true }).click()
  await page.getByText(/candidates are marked as/).first().waitFor({ timeout: 120000 })
  await sleep(800)
}

// ---------------------------------------------------------------------------
// Scenarios. Each scenario names the documentation page, the corpus, the
// query and settings, and the steps. It operates the interface and calls
// shoot() for each image, with the crop and the texts that must be visible in
// the image. The checks are recorded in the manifest.

const scenarios = []
const S = (def) => scenarios.push(def)
const FREEDOM = { corpus: 'sotu_en', tab: 'kwic', q: 'freedom', run: '1' }
const ADJ_FREEDOM = 'cql:[pos="ADJ"] [lemma="freedom"%c]'
const LEMMA_FREEDOM = 'cql:[lemma="freedom"%c]'
const PANEL_RIGHT = (y = 0, h = VIEWPORT.height) => ({ x: 928, y, width: VIEWPORT.width - 928, height: h })

S({
  id: 'first-start',
  phase: 'empty',
  page: 'get-started/install.md',
  corpus: null,
  steps: ['start CandyConc with an empty data folder', 'open the interface'],
  run: async (page, shoot) => {
    await open(page)
    await visible(page, 'No corpus yet')
    await shoot('first-start-empty', { expect: ['No corpus yet', 'Import a corpus'] })
  },
})

S({
  id: 'subcorpus-and-saved-analysis',
  page: 'guides/narrow-the-scope/create-subcorpora.md, guides/keep-and-share/save-analyses.md',
  corpus: 'sotu_en',
  query: 'dollars, freedom',
  steps: [
    'search dollars, Save subcorpus, name "addresses mentioning dollars", Save',
    'top bar Subcorpora, Check sizes',
    'search freedom, tab Collocations, Save, name "freedom collocates, window 5", Save',
    'top bar Saved analyses, tab Saved analyses',
  ],
  run: async (page, shoot) => {
    await open(page, { corpus: 'sotu_en', tab: 'kwic', q: 'dollars', run: '1' })
    await waitKwic(page)
    await page.getByRole('button', { name: 'Save subcorpus' }).first().click()
    let dialog = page.getByRole('dialog').last()
    await dialog.getByText('Name subcorpus', { exact: true }).waitFor()
    await dialog.locator('input').first().fill('addresses mentioning dollars')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await toastsGone(page)
    await page.getByRole('button', { name: 'Subcorpora', exact: true }).click()
    const workspace = page.getByRole('dialog').last()
    await workspace.getByRole('button', { name: /^Check sizes/ }).click()
    await visible(page, 'CHECKED, UP TO DATE')
    await sleep(600)
    await shoot('workspace-subcorpora', {
      crop: { x: 800, y: 0, width: 640, height: 900 },
      expect: ['addresses mentioning dollars', 'CHECKED, UP TO DATE', '47 docs · 322,726 tokens', 'Source: query “dollars”'],
    })
    await page.keyboard.press('Escape')

    await open(page, { corpus: 'sotu_en', tab: 'collocations', q: 'freedom', run: '1' })
    await visible(page, '10.579')
    await page.locator('main').getByRole('button', { name: 'Save', exact: true }).click()
    dialog = page.getByRole('dialog').last()
    await dialog.getByText('Save analysis', { exact: true }).waitFor()
    await dialog.locator('input').first().fill('freedom collocates, window 5')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await toastsGone(page)
    await page.getByRole('button', { name: 'Saved analyses', exact: true }).click()
    const ws = page.getByRole('dialog').last()
    await ws.getByRole('button', { name: /^Saved analyses/ }).click()
    const entry = ws.getByText('freedom collocates, window 5', { exact: true }).first()
    await entry.waitFor()
    await entry.scrollIntoViewIfNeeded()
    await sleep(600)
    await shoot('workspace-saved-analyses', {
      crop: { x: 800, y: 0, width: 640, height: 900 },
      expect: ['freedom collocates, window 5', 'Collocations', 'Query: freedom'],
    })
    await page.keyboard.press('Escape')
  },
})

S({
  id: 'first-results',
  page: 'get-started/first-results.md',
  corpus: 'sotu_en',
  query: 'freedom',
  settings: { collocations: { window: 5, within_sentence: true, min_f: 5, measure: 'logDice' } },
  steps: [
    'select sotu_en, type freedom in the search field, press Enter',
    'click the node of the first line (document panel)',
    'press Escape, click the tab Collocations',
    'click the collocate peace',
    'search freedom again, Export > Export as CSV, scroll the dialog to Hits to export',
  ],
  run: async (page, shoot) => {
    await open(page, { corpus: 'sotu_en', tab: 'kwic' })
    await search(page, 'freedom')
    await waitKwic(page)
    await shoot('kwic-freedom', { expect: ['495 hits · 300 loaded', 'freedom'] })

    await page.locator('[data-testid^="kwic-row-"]').first().getByText('freedom', { exact: true }).first().click()
    await visible(page, 'occurrences in the full text')
    await sleep(800)
    await shoot('document-panel-truman', {
      crop: await boxOf(page.getByRole('dialog').last()),
      expect: ['Token position 202', '7 occurrences in the full text', 'PRESIDENT HARRY S. TRUMAN'],
    })
    await shoot('kwic-document-panel', { expect: ['Concordance line', 'Token position 202', 'Same in every document of the corpus'] })

    await page.keyboard.press('Escape')
    await openTab(page, 'Collocations')
    await visible(page, '10.579')
    await shoot('collocations-freedom', {
      crop: { x: 0, y: 190, width: 1440, height: 480 },
      expect: ['Window:', 'Within sentence', 'logDice', 'peace', '10.579', 'cause', '10.337', 'defend', '10.054'],
    })

    await page.getByRole('cell', { name: 'peace', exact: true }).first().click()
    await waitKwic(page)
    await visible(page, 'O11: peace 52')
    await shoot('kwic-co-anchor-peace', {
      expect: ['52 hits', 'Co-anchors', 'O11: peace 52'],
    })

    await search(page, 'freedom')
    await waitKwic(page)
    await visible(page, '495 hits')
    await page.getByRole('button', { name: 'Export', exact: true }).click()
    await page.getByText('Export as CSV', { exact: true }).click()
    const dialog = page.getByRole('dialog').last()
    await dialog.getByText('Concordance file (server)', { exact: true }).waitFor()
    await sleep(600)
    await shoot('export-dialog-format', {
      crop: await boxOf(dialog),
      expect: ['Concordance file (server)', 'CSV', 'Evidence package / report'],
    })
    await dialog.getByText('Hits to export', { exact: true }).scrollIntoViewIfNeeded()
    await sleep(500)
    await shoot('export-dialog-hits', {
      crop: await boxOf(dialog),
      expect: ['Hits to export', 'Server concordance (fully counted)', 'Include context', 'Include metadata'],
    })
    await page.keyboard.press('Escape')
  },
})

S({
  id: 'explore-a-word',
  page: 'tutorials/explore-a-word.md',
  corpus: 'sotu_en',
  query: `${ADJ_FREEDOM}, ${LEMMA_FREEDOM}, freedom`,
  steps: [
    `search ${ADJ_FREEDOM}, click 1L next to SORT LEFT`,
    `search ${LEMMA_FREEDOM}, click the tab Dispersion, scroll to the heat map`,
    'search freedom, More > Word sketch, then scroll the relation tables to HAS ADJECTIVAL MODIFIER',
  ],
  run: async (page, shoot) => {
    await open(page, { corpus: 'sotu_en', tab: 'kwic' })
    await search(page, ADJ_FREEDOM)
    await waitKwic(page)
    await page.getByRole('button', { name: '1L', exact: true }).click()
    await visible(page, 'Sorted: 1L ascending')
    await sleep(800)
    await shoot('kwic-adjective-freedom-1l', { expect: ['68 hits', 'Sorted: 1L ascending', 'American freedoms'] })

    await search(page, LEMMA_FREEDOM)
    await waitKwic(page)
    await openTab(page, 'Dispersion')
    await visible(page, 'Juilland')
    await page.getByText('Document distribution in the current scope', { exact: true }).scrollIntoViewIfNeeded()
    await sleep(800)
    await shoot('dispersion-lemma-heatmap', {
      crop: await fromTabs(page),
      expect: ['Document distribution in the current scope', 'Document basis: 65 document partitions'],
    })

    await search(page, 'freedom')
    await openTab(page, 'Word sketch')
    await visible(page, 'Word sketch for')
    await sleep(1500)
    await shoot('word-sketch-freedom', { expect: ['Word sketch for', 'Direct object of', 'defend', '(12)'] })
    // The tab scrolls with the mouse wheel until the table stands near the top.
    await scrollToTop(page, page.getByText(/^has adjectival modifier$/i).first(), 520, { x: 720, y: 700 })
    await shoot('word-sketch-freedom-amod-conj', {
      expect: ['Has adjectival modifier', 'greater', 'Has conjunct', 'democracy'],
    })
  },
})

S({
  id: 'count-and-measure',
  page: 'guides/count-and-measure/*.md',
  corpus: 'sotu_en',
  query: 'freedom',
  steps: [
    'search freedom, tab Dispersion',
    'tab Frequency (word forms, whole corpus)',
    'More > N-grams (bigrams)',
    'search freedom, More > Trend, Date field year, Granularity Year',
    'tab Semantic, Similar words, word freedom',
  ],
  run: async (page, shoot) => {
    await open(page, FREEDOM)
    await waitKwic(page)
    await openTab(page, 'Dispersion')
    await visible(page, 'Juilland')
    await sleep(800)
    await shoot('dispersion-freedom', {
      crop: { x: 0, y: 190, width: 1440, height: 650 },
      expect: ['0.3626', '0.9538', '495'],
    })

    await openTab(page, 'Frequency')
    await visible(page, 'RESULT EVIDENCE')
    await visible(page, '20,907')
    await sleep(800)
    await shoot('frequency-word-forms', { expect: ['RESULT EVIDENCE', 'Shown: 100 of 13,070 candidates', '20,907', '13,003', '12,849'] })

    await openTab(page, 'N-grams')
    await visible(page, 'candidates in total')
    await sleep(800)
    await shoot('ngrams-bigrams', { expect: ['of the', '2,593', '10,310 candidates in total'] })

    await open(page, FREEDOM)
    await waitKwic(page)
    await openTab(page, 'Trend')
    const main = page.locator('main')
    await main.getByLabel(/Date field/).selectOption('year').catch(async () => {
      await main.locator('select').filter({ has: page.locator('option[value="year"]') }).first().selectOption('year')
    })
    await visible(page, '3,670.69')
    await sleep(1200)
    await shoot('trend-freedom-year', { expect: ['3,670.69', '325.84'] })

    await openTab(page, 'Semantic')
    await page.getByRole('button', { name: /^Similar words/ }).first().click().catch(() => {})
    const wordField = main.getByRole('textbox').first()
    await wordField.fill('freedom')
    await wordField.press('Enter')
    await visible(page, 'restricted to the corpus')
    await sleep(1200)
    await shoot('similar-words-freedom', { expect: ['restricted to the corpus', 'harmony', 'world', '100.0%'] })
  },
})

S({
  id: 'compare-two-periods',
  page: 'tutorials/compare-two-periods.md',
  corpus: 'sotu_en',
  query: null,
  settings: { filter: { decade: ['1940s', '1950s'] }, keyness: { reference: 'Rest of the whole corpus', ranking: 'Signed LL', min_freq: 5 } },
  steps: ['Filter / Subcorpus, select 1940s and 1950s in decade, Apply metadata', 'Escape, More > Keyness, click Keyness'],
  run: async (page, shoot) => {
    await open(page, { corpus: 'sotu_en', tab: 'kwic' })
    await applyFilter(page, '1940s', ['1940s', '1950s'])
    await visible(page, '14 docs · 108,308 tokens')
    await sleep(600)
    await shoot('filter-decades', { crop: PANEL_RIGHT(0, 640), expect: ['14 docs · 108,308 tokens', 'decade: 1940s, 1950s'] })
    await page.keyboard.press('Escape')
    await sleep(400)
    await runKeyness(page)
    await sleep(600)
    // The tab scrolls as a whole: the wheel brings the table under the tab bar.
    await scrollToTop(page, page.getByText(/candidates are marked as/).first(), 205)
    await sleep(600)
    await shoot('keyness-decades', {
      expect: ['160 of 500 candidates'],
      require: ['dollars', 'fiscal'],
    })
  },
})

S({
  id: 'filter-and-keyness-party',
  page: 'guides/narrow-the-scope/filter-by-metadata.md, guides/count-and-measure/keyness.md',
  corpus: 'sotu_en',
  settings: { filter: { party: ['Republican'] }, keyness: { reference: 'Rest of the whole corpus', ranking: 'Signed LL', min_freq: 5 } },
  steps: ['Filter / Subcorpus, select Republican in party, Apply metadata', 'Escape, More > Keyness, click Keyness'],
  run: async (page, shoot) => {
    await open(page, { corpus: 'sotu_en', tab: 'kwic' })
    const panel = await applyFilter(page, 'Republican', ['Republican'])
    await visible(page, '36 docs · 199,379 tokens')
    await sleep(600)
    await shoot('filter-republican', { crop: PANEL_RIGHT(0, 640), expect: ['36 docs · 199,379 tokens', 'party: Republican'] })
    await page.keyboard.press('Escape')
    await sleep(400)
    await runKeyness(page)
    await sleep(600)
    await shoot('keyness-republican', { expect: ['SCOPE', 'party: Republican', 'Applause'] })
    void panel
  },
})

S({
  id: 'contrast-party',
  page: 'guides/count-and-measure/contrast.md, guides/count-and-measure/lexical-diversity.md',
  corpus: 'sotu_en',
  query: 'freedom',
  settings: { group_a: 'party = Republican', group_b: 'party = Democratic', window: 5, sort_by: 'logDice', within_sentence: true },
  steps: ['search freedom, tab Contrast', 'group A party Republican, group B party Democratic', 'Compute contrast'],
  run: async (page, shoot) => {
    await open(page, FREEDOM)
    await waitKwic(page)
    await openTab(page, 'Contrast')
    await page.getByLabel('Field for group A').selectOption('party')
    await page.getByLabel('Value for group A').selectOption('Republican')
    await page.getByLabel('Field for group B').selectOption('party')
    await page.getByLabel('Value for group B').selectOption('Democratic')
    await page.getByRole('button', { name: 'Compute contrast' }).click()
    await visible(page, 'Results cut off')
    await sleep(1500)
    // The tab scrolls as a whole: the wheel brings the diversity card under
    // the tab bar, the free contrast table follows below it.
    const card = page.getByText('Lexical diversity', { exact: true }).first()
    await scrollToTop(page, card, 215)
    await sleep(600)
    await shoot('contrast-party', {
      expect: ['Lexical diversity', 'Free contrast', 'party = Republican', 'party = Democratic', 'A logDice'],
      require: ['Guiraud R', 'Results cut off'],
    })
    const box = card.locator('xpath=ancestor::*[.//table][1]')
    await shoot('lexical-diversity-party', {
      crop: await boxOf(box, 8),
      expect: ['TTR', 'STTR'],
      require: ['Guiraud R', '174,284', '180,221'],
    })
  },
})

S({
  id: 'paired-versions',
  page: 'guides/bring-in-texts/import-paired-versions.md',
  corpus: 'paired_en',
  synthetic: true,
  query: 'museum',
  settings: { parallel: { variants: ['easy'], sentence_window: 6 } },
  steps: ['select paired_en, search museum', 'select Parallel concordance', 'select easy in Variants (prealigned)'],
  run: async (page, shoot) => {
    await open(page, { corpus: 'paired_en', tab: 'kwic', q: 'museum', run: '1' })
    await waitKwic(page)
    await page.getByText('Parallel concordance', { exact: true }).click()
    await selectListOptions(page.locator('main'), 'easy', ['easy'])
    await visible(page, 'Sim 78%')
    await sleep(1500)
    await shoot('parallel-museum', { expect: ['PARALLEL CONCORDANCE ACTIVE', 'EASY', 'Sim 78%', 'MED 4'] })
  },
})

S({
  id: 'annotate-line',
  page: 'guides/search/bookmark-and-annotate-lines.md',
  corpus: 'sotu_en',
  query: 'freedom',
  settings: { codes: ['political', 'economic'] },
  steps: [
    'search freedom, Codes & annotations, Add code political, Add code economic, Save',
    'point to the first line, Annotate line (code + note)',
    'choose political, write a note',
  ],
  run: async (page, shoot) => {
    await open(page, FREEDOM)
    await waitKwic(page)
    await page.getByRole('button', { name: 'Codes & annotations' }).click()
    let dialog = page.getByRole('dialog').last()
    await dialog.getByText('Manage codes', { exact: true }).waitFor()
    await dialog.getByRole('button', { name: 'Add code' }).click()
    await dialog.getByRole('button', { name: 'Add code' }).click()
    const names = dialog.getByPlaceholder('Code (e.g. metaphor)')
    await names.nth(0).fill('political')
    await names.nth(1).fill('economic')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await toastsGone(page)
    const row = page.locator('[data-testid^="kwic-row-"]').first()
    await row.hover()
    await row.getByRole('button', { name: /Annotate line/ }).click()
    dialog = page.getByRole('dialog').last()
    await dialog.getByText('Annotate line', { exact: true }).waitFor()
    await dialog.getByRole('button', { name: 'political', exact: true }).click()
    const note = dialog.getByPlaceholder('Free-text note on this line…')
    await note.fill('freedom as a political value, paired with justice')
    await note.scrollIntoViewIfNeeded()
    await sleep(500)
    await shoot('annotate-line-dialog', {
      crop: await boxOf(dialog),
      expect: ['Annotate line', 'political', 'economic', 'Save code and note'],
    })
    await page.keyboard.press('Escape')
  },
})

S({
  id: 'evidence-report-pdf',
  page: 'guides/keep-and-share/export-evidence-packages.md',
  corpus: 'sotu_en',
  query: ADJ_FREEDOM,
  steps: [`search ${ADJ_FREEDOM}`, 'Export > Export as CSV, PDF under Evidence package / report, Export', 'first page of the saved PDF rendered with pdftoppm at 110 dpi'],
  run: async (page, shoot) => {
    await open(page, { corpus: 'sotu_en', tab: 'kwic' })
    await search(page, ADJ_FREEDOM)
    await waitKwic(page)
    await page.getByRole('button', { name: 'Export', exact: true }).click()
    await page.getByText('Export as CSV', { exact: true }).click()
    const dialog = page.getByRole('dialog').last()
    await dialog.getByText('Evidence package report', { exact: true }).first().click()
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 180000 }),
      dialog.getByRole('button', { name: 'Export', exact: true }).click(),
    ])
    const pdf = path.join(CAPTURE_ROOT, 'evidence-report.pdf')
    await download.saveAs(pdf)
    await shoot('evidence-report-pdf', { pdf })
  },
})

S({
  id: 'import-corpus-manager',
  page: 'guides/bring-in-texts/import-a-corpus.md',
  corpus: 'interviews',
  synthetic: true,
  settings: { format: 'CSV/TSV', target_name: 'interviews', server_file: 'CAPTURE_ROOT/data/interviews.csv', corpus_language: 'English (en)', id_column: 'id', metadata_columns: 'speaker, year', dependencies: true },
  steps: ['top bar Manage corpora, Format CSV/TSV, fill in the fields', 'Check input', 'Start import, wait for done'],
  run: async (page, shoot) => {
    await open(page, { corpus: 'sotu_en', tab: 'kwic' })
    await page.getByRole('button', { name: 'Manage corpora', exact: true }).click()
    const panel = page.getByRole('dialog').last()
    await panel.getByText('Corpus manager', { exact: true }).first().waitFor()
    await panel.locator('select').filter({ has: page.locator('option[value="csv"]') }).first().selectOption('csv')
    await panel.getByLabel(/^Target name/).fill('interviews')
    await panel.getByLabel(/^Server file/).fill(path.join(WORK, 'interviews.csv'))
    await panel.getByLabel(/^Corpus language/).selectOption('en')
    await panel.getByLabel(/^ID column/).fill('id')
    await panel.getByLabel(/^Metadata columns/).fill('speaker, year')
    await panel.getByRole('button', { name: 'Check input' }).click()
    await visible(page, 'Preflight check passed')
    const last = panel.getByText('Free disk space is sufficient', { exact: false }).first()
    await last.scrollIntoViewIfNeeded()
    await sleep(600)
    await shoot('import-preflight', {
      crop: PANEL_RIGHT(68, 540),
      expect: ['Import method is available: CSV/TSV', 'The spaCy pipeline en_core_web_md is available.', 'Start import'],
    })
    await panel.getByRole('button', { name: 'Start import' }).click()
    const done = panel.getByText('Complete according to the report', { exact: false }).first()
    await done.waitFor({ timeout: 300000 })
    await sleep(1000)
    await scrollToTop(page, panel.getByText('csv · done · Complete according to the report', { exact: true }).first(), 110, { x: 1180, y: 500 })
    await sleep(600)
    await shoot('import-job-done', {
      crop: PANEL_RIGHT(68, 832),
      expect: ['interviews', 'Complete according to the report', 'Rejected rows'],
    })
    await page.keyboard.press('Escape')
  },
})

// Last, because it changes the model connection of the running server. The
// server sends nothing to a model before a question is asked, and it is
// stopped right after this scenario.
S({
  id: 'model-connection',
  page: 'guides/copilot/connect-a-model.md',
  corpus: 'sotu_en',
  settings: { profile: 'Custom endpoint', selected_profile: 'LM Studio (local)', endpoint: 'http://127.0.0.1:9/v1/responses', model: 'MODEL_NAME' },
  steps: ['Settings > Model connection', 'click the local LM Studio profile, set Endpoint to the closed port http://127.0.0.1:9/v1/responses, enter a model name', 'Apply (configuration only, no model request)'],
  run: async (page, shoot) => {
    await open(page, { corpus: 'sotu_en', tab: 'kwic' })
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    const panel = page.getByRole('dialog').last()
    await panel.getByRole('button', { name: 'Model connection', exact: true }).click()
    await panel.getByText('Active:', { exact: false }).first().waitFor()
    await panel.locator('.profil-btn').first().click()
    await panel.getByLabel('Endpoint', { exact: true }).fill('http://127.0.0.1:9/v1/responses')
    await panel.getByLabel('Model', { exact: true }).fill('MODEL_NAME')
    await panel.getByRole('button', { name: 'Apply', exact: true }).click()
    await toastsGone(page)
    await sleep(400)
    await shoot('settings-model-connection', {
      // The six tabs of the panel take two rows: the crop reaches to Apply.
      crop: PANEL_RIGHT(0, 720),
      expect: ['Model connection', 'Active:', 'MODEL_NAME'],
    })
  },
})

// Scenarios of the documentation that this script does not capture, with the
// reason. They are written to the manifest.
const NOT_CAPTURED = [
  {
    scenario: 'multi-user-signed-in',
    page: 'guides/run-for-a-group/multi-user-server.md',
    reason:
      'Needs a second server in multi-user mode with accounts and a sign-in with a password. The capture run does not create accounts or type passwords. The guide is complete without the image.',
  },
  {
    scenario: 'copilot-answers',
    page: 'guides/copilot/ask-and-check.md, concepts/copilot.md',
    reason: 'Copilot answers are captured only from a real model run with a kept trace. This run has no model.',
  },
]

// ---------------------------------------------------------------------------
// Run

async function inViewCheck(page, text, region) {
  const loc = page.getByText(text, { exact: false })
  const n = Math.min(await loc.count(), 30)
  for (let i = 0; i < n; i++) {
    const el = loc.nth(i)
    if (!(await el.isVisible())) continue
    const b = await el.boundingBox()
    if (!b) continue
    const cx = b.x + Math.min(b.width, 40) / 2
    const cy = b.y + b.height / 2
    if (cx < region.x || cx > region.x + region.width || cy < region.y || cy > region.y + region.height) continue
    // The element must be the one drawn at that point: not scrolled out of
    // its container and not covered by another layer.
    const onTop = await el.evaluate((node, [x, y]) => {
      const hit = document.elementFromPoint(x, y)
      return !!hit && (node.contains(hit) || hit.contains(node))
    }, [cx, cy])
    if (onTop) return true
  }
  return false
}

function renderPdfFirstPage(pdf, file) {
  const base = file.replace(/\.png$/, '')
  // Letter page at 110 dpi is 935 x 1210 pixels. The crop removes the empty
  // top and bottom margins only.
  execFileSync('pdftoppm', ['-png', '-r', '110', '-f', '1', '-l', '1', '-y', '150', '-H', '960', '-singlefile', pdf, base])
  return 'first PDF page rendered with pdftoppm -png -r 110 -y 150 -H 960 (empty margins cut)'
}

function optimize(file) {
  if (args['no-optimize']) return null
  try {
    execFileSync('pngquant', ['--force', '--skip-if-larger', '--quality', '80-98', '--speed', '1', '--strip', '--output', file, file])
    return 'pngquant --quality 80-98 --speed 1 --strip (256-colour palette)'
  } catch (err) {
    if (err.status === 98 || err.status === 99) return 'pngquant: no smaller result, file unchanged'
    if (err.code === 'ENOENT') return null
    throw err
  }
}

function pngSize(file) {
  const buf = fs.readFileSync(file)
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) }
}

async function runPhase(phase, manifest) {
  const selected = scenarios.filter((s) => (s.phase ?? 'main') === phase && (!ONLY || ONLY.has(s.id)))
  if (!selected.length || (args.attach && phase !== 'main')) return
  const server = args.attach ? null : await startServer()
  const browser = await chromium.launch({ headless: true })
  manifest.procedure.browser = `chromium ${browser.version()}`
  try {
    const context = await browser.newContext({
      viewport: VIEWPORT,
      deviceScaleFactor: SCALE,
      colorScheme: 'light',
      reducedMotion: 'reduce',
      locale: 'en-US',
      timezoneId: 'UTC',
      acceptDownloads: true,
    })
    const page = await context.newPage()
    const errors = []
    page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
    page.on('pageerror', (e) => errors.push(String(e)))
    await setEnglish(page)
    for (const sc of selected) {
      log(`scenario ${sc.id}`)
      let before = errors.length
      const shoot = async (name, opts = {}) => {
        const file = path.join(OUT, `${name}.png`)
        let procedure
        let checks = []
        let toasts = []
        if (opts.pdf) {
          procedure = renderPdfFirstPage(opts.pdf, file)
        } else {
          toasts = await toastsGone(page)
          await parkPointer(page)
          const region = opts.crop ?? { x: 0, y: 0, ...VIEWPORT }
          for (const text of opts.expect ?? []) checks.push({ text, in_image: await inViewCheck(page, text, region) })
          // Texts the image is about. Without them the image is not taken, and
          // the manifest says why (the state on the screen is kept for the report).
          const absent = []
          for (const text of opts.require ?? []) if (!(await inViewCheck(page, text, region))) absent.push(text)
          if (absent.length) {
            const debug = path.join(CAPTURE_ROOT, `${name}.NOT-IN-VIEW.png`)
            await page.screenshot({ path: debug })
            manifest.not_captured.push({
              scenario: sc.id,
              file: path.relative(DOCS, file),
              page: sc.page,
              reason: `The interface does not show ${absent.map((t) => `"${t}"`).join(', ')} in the window of ${VIEWPORT.width}x${VIEWPORT.height} after the steps, so the image was not taken.${opts.why ? ` ${opts.why}` : ''}`,
              screen_state: debug,
            })
            log(`  ${name}.png NOT TAKEN, not in view: ${absent.join(' | ')}`)
            return
          }
          await page.screenshot({ path: file, animations: 'disabled', caret: 'hide', ...(opts.crop ? { clip: opts.crop } : {}) })
          procedure = `playwright page.screenshot, ${opts.crop ? 'clip' : 'full viewport'}`
        }
        const compression = optimize(file)
        manifest.shots.push({
          file: path.relative(DOCS, file),
          scenario: sc.id,
          page: sc.page,
          sha256: sha256File(file),
          bytes: fs.statSync(file).size,
          pixels: pngSize(file),
          crop_css_px: opts.crop ?? (opts.pdf ? null : 'full viewport'),
          procedure,
          compression,
          corpus: sc.corpus,
          synthetic_data: Boolean(sc.synthetic),
          query: sc.query ?? null,
          settings: sc.settings ?? {},
          steps: sc.steps,
          checks,
          toasts_left: toasts,
          page_url: opts.pdf ? null : page.url(),
          console_errors: errors.slice(before),
        })
        before = errors.length
        const missing = checks.filter((c) => !c.in_image).map((c) => c.text)
        log(`  ${name}.png${missing.length ? `  WARNING not in image: ${missing.join(' | ')}` : ''}`)
      }
      try {
        await sc.run(page, shoot)
      } catch (err) {
        const debug = path.join(CAPTURE_ROOT, `${sc.id}.FAILED.png`)
        await page.screenshot({ path: debug }).catch(() => {})
        log(`  FAILED ${sc.id}: ${err.message.split('\n')[0]} (state in ${debug})`)
        manifest.failed.push({ scenario: sc.id, page: sc.page, error: err.message.split('\n')[0] })
      }
    }
  } finally {
    await browser.close()
    await stopServer(server)
  }
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true })
  fs.mkdirSync(path.dirname(MANIFEST), { recursive: true })
  if (!args.attach) prepareHome()
  const manifest = {
    schema: 'candyconc-screenshot-manifest-v1',
    captured_at: new Date().toISOString(),
    revision: {
      commit: git('rev-parse', 'HEAD'),
      branch: git('rev-parse', '--abbrev-ref', 'HEAD'),
      uncommitted_product_changes: (git('status', '--porcelain', '--', 'candyconc-web/src', path.relative(ROOT, path.join(APP, 'src'))) || '')
        .split('\n')
        .filter(Boolean),
    },
    application: {
      start: `python -m candyconc.entrypoints.cli --port ${PORT} in CAPTURE_ROOT/.candyconc, CANDYCONC_HOME=CAPTURE_ROOT/.candyconc, CANDYCONC_FRONTEND_DIST=built interface`,
      home: CAPTURE_ROOT,
      frontend_dist: FRONTEND_DIST.startsWith(ROOT) ? path.relative(ROOT, FRONTEND_DIST) : 'vite build into a folder outside the checkout',
      python: args.attach ? null : execFileSync(PYTHON, ['--version'], { encoding: 'utf8' }).trim(),
      model: 'none: COPILOT_ENDPOINT and CANDYCONC_GEMMA_EMB_ENDPOINT point to the closed port 127.0.0.1:9',
    },
    settings: {
      viewport: VIEWPORT,
      device_scale_factor: SCALE,
      color_scheme: 'light',
      reduced_motion: 'reduce',
      ui_language: 'en, chosen in Settings > General > Language',
      browser_locale: 'en-US',
      timezone: 'UTC',
    },
    procedure: {
      tool: `playwright ${PLAYWRIGHT_VERSION}`,
      script: path.relative(ROOT, fileURLToPath(import.meta.url)),
      rules: 'Real interface only: clicks, typing, keyboard, deep links of the application. No DOM changes, no request interception. Crops only focus.',
    },
    corpora: {},
    shots: [],
    failed: [],
    not_captured: [...NOT_CAPTURED],
  }
  await runPhase('empty', manifest)
  if (!args.attach) {
    const how = sampleCorpora()
    pairedCorpus()
    for (const name of ['sotu_en', 'dta_de']) manifest.corpora[name] = { ...corpusRecord(name), prepared: how }
    manifest.corpora.paired_en = { ...corpusRecord('paired_en'), prepared: 'candy import as in guides/bring-in-texts/import-paired-versions.md' }
  }
  await runPhase('main', manifest)
  if (!args.attach && fs.existsSync(path.join(DATA, 'corpora', 'interviews'))) {
    manifest.corpora.interviews = { ...corpusRecord('interviews'), prepared: 'imported in the corpus manager during the scenario import-corpus-manager' }
  }
  if (ONLY && fs.existsSync(MANIFEST)) {
    // A partial run replaces only its own entries.
    const old = readJson(MANIFEST)
    const files = new Set(manifest.shots.map((s) => s.file))
    const ids = new Set(manifest.shots.map((s) => s.scenario).concat(manifest.failed.map((f) => f.scenario)))
    manifest.shots = old.shots.filter((s) => !files.has(s.file)).concat(manifest.shots)
    manifest.failed = (old.failed ?? []).filter((f) => !ids.has(f.scenario)).concat(manifest.failed)
    const dynamic = (list) => (list ?? []).filter((n) => n.file)
    manifest.not_captured = [...NOT_CAPTURED, ...dynamic(old.not_captured).filter((n) => !ids.has(n.scenario) && !files.has(n.file)), ...dynamic(manifest.not_captured)]
    manifest.corpora = { ...old.corpora, ...manifest.corpora }
    manifest.partial_runs = [...(old.partial_runs ?? []), { captured_at: manifest.captured_at, only: [...ONLY], commit: manifest.revision.commit }]
    manifest.captured_at = old.captured_at
  }
  const order = (s) => scenarios.findIndex((x) => x.id === s.scenario)
  manifest.shots.sort((a, b) => order(a) - order(b))
  fs.writeFileSync(MANIFEST, JSON.stringify(manifest, null, 2) + '\n')
  const total = manifest.shots.reduce((n, s) => n + s.bytes, 0)
  log(`${manifest.shots.length} images (${(total / 1e6).toFixed(2)} MB), ${manifest.failed.length} failed, manifest ${MANIFEST}`)
  if (manifest.failed.length) process.exitCode = 1
}

await main()
