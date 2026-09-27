import { describe, expect, it } from 'vitest'

import {
  normalizeBuilderSeedTerm,
  shouldOpenQueryBuilderInAdvancedMode,
} from '@/utils/queryTerm'

describe('queryTerm builder helpers', () => {
  it('strips the external cql prefix for builder seeds', () => {
    expect(normalizeBuilderSeedTerm('cql:[lemma="Haus"]')).toBe('[lemma="Haus"]')
    expect(normalizeBuilderSeedTerm(' cql:within(<s>, [word="Haus"]) ')).toBe('within(<s>, [word="Haus"])')
    expect(normalizeBuilderSeedTerm('cql:')).toBe('')
  })

  it('opens the builder in advanced mode for explicit or implicit cql', () => {
    expect(shouldOpenQueryBuilderInAdvancedMode('cql:')).toBe(true)
    expect(shouldOpenQueryBuilderInAdvancedMode('cql:[lemma="Haus"]')).toBe(true)
    expect(shouldOpenQueryBuilderInAdvancedMode('[lemma="Haus"]')).toBe(false)
    expect(shouldOpenQueryBuilderInAdvancedMode('[sim="Haus" & k=20]')).toBe(false)
    expect(shouldOpenQueryBuilderInAdvancedMode('where(source="mlsum", [word="Haus"])')).toBe(false)
    expect(shouldOpenQueryBuilderInAdvancedMode('within(<s>, [word="Haus"])')).toBe(true)
    expect(shouldOpenQueryBuilderInAdvancedMode('[lemma="Haus" & pos="NN"]')).toBe(true)
    expect(shouldOpenQueryBuilderInAdvancedMode('Haus')).toBe(false)
  })
})
