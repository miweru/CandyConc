import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'

import RunHistoryPanel from '@/components/copilot/RunHistoryPanel.vue'
import { runRecords, traceHistory } from '@/actions/traceRecorder'
import { addRunToProject, clearAllData, createProject } from '@/services/runRecordService'
import type { RunRecordV1 } from '@/types/copilot-protocol'

function runRecord(): RunRecordV1 {
  return {
    schemaVersion: '2.0',
    runId: 'run-1',
    requestId: 'req-1',
    ts: Date.UTC(2026, 5, 21, 8, 0),
    kind: 'analysis',
    actionType: 'analysis/frequency',
    actionPayload: { groupBy: 'word', limit: 25 },
    corpus: { corpusId: 'default', subcorpusHash: 'scope-abc' },
    queryHash: 'query-hash',
    resultRef: { type: 'analysis/frequency', hash: 'result-hash', rows: 12 },
    summary: 'Frequenzliste berechnet',
    notes: ['prüfen'],
    evidence: {
      schemaVersion: '2.0',
      provenance: 'frontend_actionbus',
      completeness: 'full',
      corpusFingerprint: {
        corpusId: 'default',
        subcorpusHash: 'scope-abc',
        queryHash: 'query-hash',
        indexFingerprint: 'index-fp',
      },
      researchScope: {
        corpusId: 'default',
        scopeHash: 'scope-abc',
        scopeStatus: 'corpus',
        label: 'Gesamtkorpus',
      },
      toolFingerprint: {
        actionType: 'analysis/frequency',
        toolSchemaHash: 'tool-schema-hash',
      },
      resultFingerprint: {
        resultType: 'analysis/frequency',
        resultHash: 'result-hash',
        rows: 12,
        queryTraceId: 'frontend-trace-id',
        backendQueryTraceId: 'backend-trace-id',
      },
      warnings: [],
    },
  }
}

describe('RunHistoryPanel', () => {
  beforeEach(() => {
    clearAllData()
    runRecords.value = [runRecord()]
    traceHistory.value = [{
      id: 'trace-1',
      ts: Date.UTC(2026, 5, 21, 8, 0),
      actor: 'user',
      actionType: 'analysis/frequency',
      payloadHash: 'payload-hash',
      ok: true,
      linkRunId: 'run-1',
    }]
  })

  it('keeps run context visible without exposing raw scope and trace diagnostics', async () => {
    const wrapper = mount(RunHistoryPanel)

    expect(wrapper.text()).toContain('Run-Historie')
    expect(wrapper.text()).not.toContain('Traces')
    expect(wrapper.find('button[title="Trace-Log exportieren"]').exists()).toBe(false)

    await wrapper.find('.run-header').trigger('click')

    expect(wrapper.text()).toContain('Frequenzliste berechnet')
    expect(wrapper.text()).toContain('default')
    expect(wrapper.text()).toContain('Gesamtkorpus')
    expect(wrapper.text()).toContain('JSON')
    expect(wrapper.text()).toContain('CSV')
    expect(wrapper.text()).toContain('prüfen')
    expect(wrapper.text()).toContain('12 Zeilen')
    expect(wrapper.text()).not.toContain('scope-abc')
    expect(wrapper.text()).not.toContain('ScopeHash')
    expect(wrapper.text()).not.toContain('Subcorpus Hash')
    expect(wrapper.text()).not.toContain('Scope Status')
    expect(wrapper.text()).not.toContain('Scope Label')
    expect(wrapper.text()).not.toContain('analysis/frequency')
    expect(wrapper.text()).not.toContain('Payload:')
    expect(wrapper.text()).not.toContain('Evidence:')
    expect(wrapper.text()).not.toContain('Evidence Warnings')
    expect(wrapper.text()).not.toContain('Duplizieren')
    expect(wrapper.text()).not.toContain('Alte löschen')
    expect(wrapper.text()).not.toContain('Tool Schema')
    expect(wrapper.text()).not.toContain('Backend Query Trace')
    expect(wrapper.text()).not.toContain('Frontend Trace')
    expect(wrapper.text()).not.toContain('tool-schema-hash')
    expect(wrapper.text()).not.toContain('backend-trace-id')
  })

  it('filters the run list by project and offers a project JSON export', async () => {
    runRecords.value = [
      runRecord(),
      { ...runRecord(), runId: 'run-2', requestId: 'req-2', summary: 'Zweiter Run ohne Projekt' },
    ]
    const project = createProject('Studie A')
    addRunToProject(project.id, 'run-1')

    const wrapper = mount(RunHistoryPanel)

    expect(wrapper.text()).toContain('Frequenzliste berechnet')
    expect(wrapper.text()).toContain('Zweiter Run ohne Projekt')

    const filterToggle = wrapper.findAll('button').find(b => b.text().includes('Filter'))
    expect(filterToggle).toBeDefined()
    await filterToggle!.trigger('click')

    const projectSelect = wrapper.find('#run-project-filter')
    expect(projectSelect.exists()).toBe(true)
    expect(projectSelect.text()).toContain('Studie A (1)')

    await projectSelect.setValue(project.id)

    expect(wrapper.text()).toContain('Frequenzliste berechnet')
    expect(wrapper.text()).not.toContain('Zweiter Run ohne Projekt')
    expect(wrapper.text()).toContain('Projekt als JSON exportieren')

    await projectSelect.setValue(undefined)

    expect(wrapper.text()).toContain('Zweiter Run ohne Projekt')
    expect(wrapper.text()).not.toContain('Projekt als JSON exportieren')
  })
})
