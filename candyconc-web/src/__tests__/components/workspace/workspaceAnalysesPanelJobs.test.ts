import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import WorkspaceAnalysesPanel from '@/components/workspace/WorkspaceAnalysesPanel.vue'
import {
  useAnalysisJobsStore,
  useAnalysisPresetsStore,
  useProductCapabilitiesStore,
  useSessionStore,
  useUiStore,
} from '@/stores'
import type { ProductCapability, ProductCapabilityBackendRouteDescriptor, ProductCapabilityOperation } from '@/api/client'

const apiMocks = vi.hoisted(() => ({
  cancelAnalysisJob: vi.fn(),
  getAnalysisJob: vi.fn(),
  getAnalysisJobRows: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    cancelAnalysisJob: (...args: unknown[]) => apiMocks.cancelAnalysisJob(...args),
    getAnalysisJob: (...args: unknown[]) => apiMocks.getAnalysisJob(...args),
    getAnalysisJobRows: (...args: unknown[]) => apiMocks.getAnalysisJobRows(...args),
  }
})

function route(path: string, method: string): ProductCapabilityBackendRouteDescriptor {
  return {
    path,
    methods: [method],
    mutates: method !== 'GET',
    requires_corpus_features: [],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  }
}

function operation(
  id: string,
  label: string,
  routeDescriptor: ProductCapabilityBackendRouteDescriptor,
): ProductCapabilityOperation {
  return {
    id,
    capability_id: 'analysis.async_jobs',
    label,
    description: '',
    route: routeDescriptor,
    effects: routeDescriptor.mutates ? ['write'] : ['read'],
    handler_key: id.endsWith('.cancel')
      ? 'analysis_job_cancel'
      : id.endsWith('.rows')
        ? 'analysis_job_rows'
        : 'analysis_job_status',
    surface_slot: id,
    priority: 10,
  }
}

function asyncJobsCapability(options: { includeCancel?: boolean } = {}): ProductCapability {
  const statusRoute = route('/api/v1/analysis/jobs/{job_id}', 'GET')
  const cancelRoute = route('/api/v1/analysis/jobs/{job_id}/cancel', 'POST')
  const rowsRoute = route('/api/v1/analysis/jobs/{job_id}/rows', 'GET')
  const operations = [
    operation('analysis.async_jobs.status', 'Analysejob-Status', statusRoute),
    ...(options.includeCancel === false
      ? []
      : [operation('analysis.async_jobs.cancel', 'Analyse abbrechen', cancelRoute)]),
    operation('analysis.async_jobs.rows', 'Analysejob-Zeilen', rowsRoute),
  ]
  return {
    id: 'analysis.async_jobs',
    title: 'Analysis jobs',
    area: 'analysis',
    maturity: 'guarded',
    visibility: 'first_class_ui',
    backend_routes: [statusRoute.path, cancelRoute.path, rowsRoute.path],
    backend_route_descriptors: [statusRoute, cancelRoute, rowsRoute],
    operations,
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
  }
}

function seedProductContract(options: { includeCancel?: boolean } = {}) {
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.status = 'ready'
  productCapabilities.contract = {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [asyncJobsCapability(options)],
  }
}

function seedSession() {
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

describe('WorkspaceAnalysesPanel active job monitor', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
    seedProductContract()
    seedSession()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.spyOn(useAnalysisPresetsStore(), 'init').mockResolvedValue()
  })

  it('keeps the analysis job monitor visible when no jobs are known', async () => {
    const wrapper = mount(WorkspaceAnalysesPanel)
    await nextTick()

    expect(wrapper.text()).toContain('Analysejobs')
    expect(wrapper.text()).toContain('Keine Analysejobs bekannt.')
    expect(wrapper.text()).toContain('0 bekannt')
    expect(wrapper.find('input[aria-label="Analysejob per Job-ID prüfen"]').attributes('disabled')).toBeUndefined()
  })

  it('keeps the analysis job monitor visible with a disabled reason when status is not available', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = {
      version: 'product-capabilities-v1',
      scope: 'CandyConc product capability contract',
      fingerprint_sha256: 'a'.repeat(64),
      cqlf_capability_contract: {
        version: 'cqlf-capabilities-v1',
        current_level: '2-',
        fingerprint_sha256: 'b'.repeat(64),
      },
      capabilities: [{
        ...asyncJobsCapability(),
        backend_routes: [],
        backend_route_descriptors: [],
        operations: [],
      }],
    }

    const wrapper = mount(WorkspaceAnalysesPanel)
    await nextTick()

    expect(wrapper.text()).toContain('Analysejobs')
    expect(wrapper.text()).toContain('Analysejob-Monitor nicht verfügbar.')
    expect(wrapper.text()).not.toContain('analysis.async_jobs.status')
    expect(wrapper.find('input[aria-label="Analysejob per Job-ID prüfen"]').attributes('disabled')).toBeDefined()
  })

  it('does not render retained job snapshots when status is not available', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = {
      version: 'product-capabilities-v1',
      scope: 'CandyConc product capability contract',
      fingerprint_sha256: 'a'.repeat(64),
      cqlf_capability_contract: {
        version: 'cqlf-capabilities-v1',
        current_level: '2-',
        fingerprint_sha256: 'b'.repeat(64),
      },
      capabilities: [{
        ...asyncJobsCapability(),
        backend_routes: [],
        backend_route_descriptors: [],
        operations: [],
      }],
    }
    const analysisJobs = useAnalysisJobsStore()
    analysisJobs.setSnapshot({
      job_id: 'job-hidden-without-status',
      kind: 'keyness',
      corpus: 'sensitive-demo',
      status: 'running',
      progress: 20,
      message: 'soll nicht sichtbar sein',
    }, 'keyness')

    const wrapper = mount(WorkspaceAnalysesPanel)
    await nextTick()

    expect(wrapper.text()).toContain('Analysejob-Monitor nicht verfügbar.')
    expect(wrapper.text()).not.toContain('job-hidden-without-status')
    expect(wrapper.text()).not.toContain('sensitive-demo')
    expect(wrapper.text()).not.toContain('soll nicht sichtbar sein')
  })

  it('shows active analysis jobs and cancels them through the ProductOperation-gated store', async () => {
    const analysisJobs = useAnalysisJobsStore()
    analysisJobs.setSnapshot({
      job_id: 'job-frequency-1',
      kind: 'frequency_list',
      corpus: 'demo',
      status: 'running',
      progress: 35,
      message: 'Zähle Tokens',
      total_rows: 1200,
    })
    analysisJobs.activeJobIdsByScope = { frequency: 'job-frequency-1' }
    apiMocks.cancelAnalysisJob.mockResolvedValue({
      job_id: 'job-frequency-1',
      kind: 'frequency_list',
      corpus: 'demo',
      status: 'cancelled',
      progress: 35,
      message: 'Abgebrochen',
    })

    const wrapper = mount(WorkspaceAnalysesPanel)
    await nextTick()

    expect(wrapper.text()).toContain('Analysejobs')
    expect(wrapper.text()).toContain('Frequenz')
    expect(wrapper.text()).toContain('job-frequency-1')
    expect(wrapper.text()).toContain('Zähle Tokens')

    await wrapper.get('button[aria-label="Analyse abbrechen"]').trigger('click')
    await flushPromises()
    await nextTick()

    expect(window.confirm).not.toHaveBeenCalled()
    expect(apiMocks.cancelAnalysisJob).toHaveBeenCalledWith('job-frequency-1')
    expect(analysisJobs.activeJobId('frequency')).toBeNull()
    expect(analysisJobs.snapshotFor('job-frequency-1')).toMatchObject({ status: 'cancelled' })
  })

  it('names a collocation contrast job by what it computes', async () => {
    const analysisJobs = useAnalysisJobsStore()
    analysisJobs.setSnapshot({
      job_id: 'job-diff-1',
      kind: 'collocates_diff',
      corpus: 'sotu_en',
      status: 'completed',
      progress: 100,
      total_rows: 50,
    })
    const wrapper = mount(WorkspaceAnalysesPanel)
    await nextTick()
    const title = wrapper.get('[data-testid="job-monitor-card-job-diff-1"] .job-monitor-title').text()
    expect(title).toBe('Kollokationskontrast')
  })

  it('counts known running jobs as active even when they are not bound to a local active scope', async () => {
    const analysisJobs = useAnalysisJobsStore()
    analysisJobs.setSnapshot({
      job_id: 'job-known-running-1',
      kind: 'keyness',
      corpus: 'demo',
      status: 'running',
      progress: 17,
      message: 'Wiederaufgenommener Backend-Job',
    }, 'keyness')

    const wrapper = mount(WorkspaceAnalysesPanel)
    await nextTick()

    expect(wrapper.text()).toContain('job-known-running-1')
    expect(wrapper.text()).toContain('Wiederaufgenommener Backend-Job')
    expect(wrapper.text()).toContain('1 aktiv')
    expect(wrapper.text()).toContain('1 bekannt')
  })

  it('consumes analysis job status ProductOperation focus on visible job cards', async () => {
    const analysisJobs = useAnalysisJobsStore()
    const uiStore = useUiStore()
    analysisJobs.setSnapshot({
      job_id: 'job-status-focus-1',
      kind: 'frequency_list',
      corpus: 'demo',
      status: 'running',
      progress: 45,
      message: 'Läuft',
    }, 'frequency')
    uiStore.focusProductOperation('analysis.async_jobs.status', {
      capabilityId: 'analysis.async_jobs',
      surfaceSlot: 'analysis.async_jobs.status',
      preferredMode: 'status',
    })

    const wrapper = mount(WorkspaceAnalysesPanel)
    await nextTick()

    expect(wrapper.text()).toContain('Fokus: Analysejob-Status')
    expect(wrapper.text()).toContain('Statusprüfung')
    expect(wrapper.text()).not.toContain('analysis.async_jobs.status')
    expect(wrapper.get('[data-testid="job-monitor-card-job-status-focus-1"]').classes()).toContain('job-monitor-card-focused')
    expect(uiStore.focusedProductOperation).toBeNull()
  })

  it('consumes analysis job rows ProductOperation focus only on completed jobs with rows', async () => {
    const analysisJobs = useAnalysisJobsStore()
    const uiStore = useUiStore()
    analysisJobs.setSnapshot({
      job_id: 'job-rows-focus-1',
      kind: 'frequency_list',
      corpus: 'demo',
      status: 'done',
      progress: 100,
      message: 'Fertig',
      result_available: true,
      total_rows: 2,
    }, 'frequency')
    analysisJobs.setSnapshot({
      job_id: 'job-rows-running-1',
      kind: 'keyness',
      corpus: 'demo',
      status: 'running',
      progress: 12,
      message: 'Läuft',
    }, 'keyness')
    uiStore.focusProductOperation('analysis.async_jobs.rows', {
      capabilityId: 'analysis.async_jobs',
      surfaceSlot: 'analysis.async_jobs.rows',
      preferredMode: 'rows',
    })

    const wrapper = mount(WorkspaceAnalysesPanel)
    await nextTick()

    expect(wrapper.text()).toContain('Fokus: Analysejob-Zeilen')
    expect(wrapper.text()).toContain('Ergebniszeilen')
    expect(wrapper.get('[data-testid="job-monitor-card-job-rows-focus-1"]').classes()).toContain('job-monitor-card-focused')
    expect(wrapper.get('[data-testid="job-monitor-card-job-rows-running-1"]').classes()).not.toContain('job-monitor-card-focused')
    expect(uiStore.focusedProductOperation).toBeNull()
  })

  it('consumes analysis job cancel ProductOperation focus on cancellable jobs', async () => {
    const analysisJobs = useAnalysisJobsStore()
    const uiStore = useUiStore()
    analysisJobs.setSnapshot({
      job_id: 'job-cancel-focus-1',
      kind: 'ngrams',
      corpus: 'demo',
      status: 'queued',
      progress: 3,
      message: 'Wartet',
    }, 'ngrams')
    uiStore.focusProductOperation('analysis.async_jobs.cancel', {
      capabilityId: 'analysis.async_jobs',
      surfaceSlot: 'analysis.async_jobs.cancel',
      preferredMode: 'cancel',
    })

    const wrapper = mount(WorkspaceAnalysesPanel)
    await nextTick()

    expect(wrapper.text()).toContain('Fokus: Analyseabbruch')
    expect(wrapper.text()).toContain('Abbruchprüfung')
    expect(wrapper.get('[data-testid="job-monitor-card-job-cancel-focus-1"]').classes()).toContain('job-monitor-card-focused')
    expect(uiStore.focusedProductOperation).toBeNull()
  })

  it('cancels active jobs directly from the explicit monitor control', async () => {
    vi.mocked(window.confirm).mockReturnValue(false)
    const analysisJobs = useAnalysisJobsStore()
    analysisJobs.setSnapshot({
      job_id: 'job-frequency-confirm-1',
      kind: 'frequency_list',
      corpus: 'demo',
      status: 'running',
      progress: 35,
      message: 'Zähle Tokens',
    })
    analysisJobs.activeJobIdsByScope = { frequency: 'job-frequency-confirm-1' }
    apiMocks.cancelAnalysisJob.mockResolvedValueOnce({
      job_id: 'job-frequency-confirm-1',
      kind: 'frequency_list',
      corpus: 'demo',
      status: 'cancelled',
      progress: 35,
      message: 'Abgebrochen',
    })

    const wrapper = mount(WorkspaceAnalysesPanel)
    await nextTick()

    await wrapper.get('button[aria-label="Analyse abbrechen"]').trigger('click')
    await flushPromises()

    expect(window.confirm).not.toHaveBeenCalled()
    expect(apiMocks.cancelAnalysisJob).toHaveBeenCalledWith('job-frequency-confirm-1')
    expect(analysisJobs.activeJobId('frequency')).toBeNull()
  })

  it('hides active-job cancel when the cancel ProductOperation is absent', async () => {
    seedProductContract({ includeCancel: false })
    const analysisJobs = useAnalysisJobsStore()
    analysisJobs.setSnapshot({
      job_id: 'job-ngram-1',
      kind: 'ngrams',
      corpus: 'demo',
      status: 'running',
      progress: 12,
      message: 'Berechne N-Gramme',
    })
    analysisJobs.activeJobIdsByScope = { ngrams: 'job-ngram-1' }

    const wrapper = mount(WorkspaceAnalysesPanel)
    await nextTick()

    expect(wrapper.text()).toContain('Analysejobs')
    expect(wrapper.text()).toContain('job-ngram-1')
    expect(wrapper.text()).toContain('Abbruch nicht verfügbar')
    expect(wrapper.find('button[aria-label="Analyse abbrechen"]').exists()).toBe(false)
    expect(apiMocks.cancelAnalysisJob).not.toHaveBeenCalled()
  })

  it('keeps completed jobs visible and loads a generic row preview through the rows ProductOperation', async () => {
    const analysisJobs = useAnalysisJobsStore()
    analysisJobs.setSnapshot({
      job_id: 'job-frequency-done-1',
      kind: 'frequency_list',
      corpus: 'demo',
      status: 'done',
      progress: 100,
      message: 'Fertig',
      total_rows: 2,
      result_available: true,
      result_readiness: 'available',
      rows_state: 'available',
    }, 'frequency')
    apiMocks.getAnalysisJobRows.mockResolvedValue({
      job_id: 'job-frequency-done-1',
      status: 'done',
      progress: 100,
      total_rows: 2,
      total_candidates: 42,
      row_limit: 5,
      truncated: true,
      offset: 0,
      limit: 5,
      method: {
        statistics: [{
          key: 'log_likelihood',
          name: 'Log-Likelihood',
          latex_formula: 'G^2',
          smoothing: 'none',
          sort_key: 'll',
        }],
        target_total: 100,
        reference_total: 200,
        indexFingerprint: 'abc123',
      },
      rows: [{ word: 'Hase', f: 7 }],
    })

    const wrapper = mount(WorkspaceAnalysesPanel)
    await nextTick()

    expect(wrapper.text()).toContain('job-frequency-done-1')
    expect(wrapper.text()).toContain('1 bekannt')
    expect(wrapper.text()).toContain('Fertig')

    const rowsButton = wrapper.findAll('button').find((button) => button.text().includes('Zeilen'))
    expect(rowsButton).toBeTruthy()
    await rowsButton!.trigger('click')
    await flushPromises()
    await nextTick()

    expect(apiMocks.getAnalysisJobRows).toHaveBeenCalledWith('job-frequency-done-1', 0, 5)
    expect(wrapper.text()).toContain('Ergebnisvorschau')
    expect(wrapper.text()).toContain('Kandidaten: 42')
    expect(wrapper.text()).toContain('Row-Limit: 5')
    expect(wrapper.text()).toContain('gekürztes Ergebnis')
    expect(wrapper.text()).toContain('Methode / Reproduzierbarkeit')
    expect(wrapper.text()).toContain('Log-Likelihood')
    expect(wrapper.text()).toContain('G^2')
    expect(wrapper.text()).toContain('Index-Fingerprint')
    expect(wrapper.text()).toContain('word: Hase')
    expect(wrapper.text()).toContain('f: 7')
  })

  it('does not load row previews for completed jobs without stored result rows', async () => {
    const analysisJobs = useAnalysisJobsStore()
    const uiStore = useUiStore()
    const toast = vi.spyOn(uiStore, 'showToast')
    analysisJobs.setSnapshot({
      job_id: 'job-discarded-rows-1',
      kind: 'ngrams',
      corpus: 'demo',
      status: 'done',
      progress: 100,
      message: 'Fertig ohne gespeichertes Ergebnis',
      total_rows: 1,
      result_available: false,
      result_discarded: true,
      result_readiness: 'discarded',
      rows_state: 'discarded',
    }, 'ngrams')

    const wrapper = mount(WorkspaceAnalysesPanel)
    await nextTick()

    expect(wrapper.text()).toContain('job-discarded-rows-1')
    const rowsButton = wrapper.findAll('button').find((button) => button.text().includes('Zeilen'))
    expect(rowsButton).toBeTruthy()
    expect(rowsButton!.attributes('disabled')).toBeDefined()
    expect(rowsButton!.attributes('title')).toBe('Analyse abgeschlossen, aber das Ergebnis wurde nicht im Job gespeichert.')
    expect(wrapper.text()).toContain('Ergebnis verworfen')
    expect(wrapper.text()).toContain('Analyse abgeschlossen, aber das Ergebnis wurde nicht im Job gespeichert.')
    expect(apiMocks.getAnalysisJobRows).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalled()
  })

  it('can look up a backend job by id and retain it in the workspace monitor', async () => {
    apiMocks.getAnalysisJob.mockResolvedValue({
      job_id: 'job-lookup-1',
      kind: 'keyness',
      corpus: 'demo',
      status: 'done',
      progress: 100,
      message: 'Fertig',
    })

    const wrapper = mount(WorkspaceAnalysesPanel)
    await nextTick()

    await wrapper.get('input[aria-label="Analysejob per Job-ID prüfen"]').setValue('job-lookup-1')
    await wrapper.get('form.job-lookup').trigger('submit')
    await flushPromises()
    await nextTick()

    expect(apiMocks.getAnalysisJob).toHaveBeenCalledWith('job-lookup-1')
    expect(wrapper.text()).toContain('job-lookup-1')
    expect(wrapper.text()).toContain('Keyness')
  })

})
