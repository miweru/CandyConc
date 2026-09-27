/**
 * Vier ehrliche Autonomiestufen — die Stufentexte müssen exakt das Verhalten
 * der realen Backend-Approval-Matrix beschreiben.
 *
 * Referenz (app/src/candyconc/candyconc_copilot/
 * orchestrator.py, `_should_require_approval` + `_plan_gate_active`):
 *
 *   Level <= 1 : Plan-Gate — vor dem ersten Tool-Batch wird ein Plan emittiert
 *                und in WAITING_APPROVAL pausiert; zusätzlich verlangt
 *                Level <= 2 Approval für JEDE Aktion.
 *   Level 3-5  : Approval nur für nicht umkehrbare Aktionen
 *                (`reversible: false`); Lese-Analysen laufen frei.
 *   Level 6-8  : Approval nur für destruktive Aktionstypen
 *                (delete/remove/clear/reset/drop).
 *   Level 9-10 : Kein Approval.
 */
import { describe, expect, it, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { AUTONOMY_STEPS, autonomyStepForLevel, useCopilotStore } from '@/stores/copilot'

interface StepFixture {
  step: 1 | 2 | 3 | 4
  /** Level, das die Stufe an das Backend sendet. */
  level: number
  /** Erwartetes Approval-Verhalten laut Backend-Matrix (Doku, siehe oben). */
  backendBehaviour: string
  /** Exakter Stufentext (EINE Textquelle: stores/copilot.ts). */
  description: string
}

const STEP_FIXTURES: StepFixture[] = [
  {
    step: 1,
    level: 1,
    backendBehaviour: 'plan gate before first tool batch + approval for every action (level <= 2)',
    description: 'Plan prüfen und bestätigen, dann ausführen',
  },
  {
    step: 2,
    level: 4,
    backendBehaviour: 'approval only for non-reversible actions (level 3-5)',
    description: 'Lese-Analysen frei, Schreib-/nicht umkehrbare Aktionen mit Bestätigung',
  },
  {
    step: 3,
    level: 7,
    backendBehaviour: 'approval only for destructive action types (level 6-8)',
    description: 'Frei außer destruktive Aktionen',
  },
  {
    step: 4,
    level: 10,
    backendBehaviour: 'no approval at all (level 9-10)',
    description: 'Vollständig autonom',
  },
]

describe('autonomy steps mirror the backend approval matrix', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('exposes exactly four steps with the honest representative levels', () => {
    expect(AUTONOMY_STEPS.map((step) => step.step)).toEqual([1, 2, 3, 4])
    expect(AUTONOMY_STEPS.map((step) => step.level)).toEqual([1, 4, 7, 10])
  })

  it('each step text states exactly the matrix behaviour of its level', () => {
    for (const fixture of STEP_FIXTURES) {
      const step = AUTONOMY_STEPS.find((entry) => entry.step === fixture.step)!
      expect(step.level, fixture.backendBehaviour).toBe(fixture.level)
      expect(step.description, fixture.backendBehaviour).toBe(fixture.description)
    }
  })

  it('store description follows the matrix bands for every numeric level', () => {
    const store = useCopilotStore()
    for (const fixture of STEP_FIXTURES) {
      store.setAutonomyLevel(fixture.level)
      expect(store.autonomyDescription, fixture.backendBehaviour).toBe(fixture.description)
      expect(store.autonomyStep.step).toBe(fixture.step)
    }
  })

  it('band boundaries match the backend matrix boundaries (<=2 / 3-5 / 6-8 / 9-10)', () => {
    // Level 0-2: always-approval band (plan gate at <= 1).
    expect(autonomyStepForLevel(0).step).toBe(1)
    expect(autonomyStepForLevel(2).step).toBe(1)
    // Level 3-5: non-reversible approval band.
    expect(autonomyStepForLevel(3).step).toBe(2)
    expect(autonomyStepForLevel(5).step).toBe(2)
    // Level 6-8: destructive-only band.
    expect(autonomyStepForLevel(6).step).toBe(3)
    expect(autonomyStepForLevel(8).step).toBe(3)
    // Level 9-10: no approval.
    expect(autonomyStepForLevel(9).step).toBe(4)
    expect(autonomyStepForLevel(10).step).toBe(4)
  })
})
