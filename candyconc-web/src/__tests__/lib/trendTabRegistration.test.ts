import { describe, expect, it } from 'vitest'

import { analysisTabSurfaces, analysisSurfaceForTab } from '@/lib/productCapabilities'
import { iconNameForAnalysisTab } from '@/lib/productSurfaceRegistry'
import {
  analysisTabComponents,
  componentBackedAnalysisTabs,
  analysisComponentForTab,
} from '@/components/analysis/surfaceComponents'

describe('trend tab registration', () => {
  it('registers the trend surface additively in the analysis tab registry', () => {
    const surface = analysisSurfaceForTab('trend')
    expect(surface).toBeDefined()
    expect(surface!.capabilityId).toBe('analysis.trend')
    expect(surface!.kind).toBe('analysis_tab')
    expect(surface!.label).toBe('Trend')
    // Neutral register, no recommendation vocabulary in the visible label.
    expect(surface!.label.toLowerCase()).not.toContain('empfohlen')
  })

  it('keeps every previously registered analysis tab surface intact', () => {
    const tabs = analysisTabSurfaces.map((surface) => surface.tab)
    for (const tab of [
      'kwic', 'frequency', 'collocations', 'collocation_network', 'dispersion',
      'semantic', 'ngrams', 'contrast', 'keyness', 'wordsketch', 'trend',
    ]) {
      expect(tabs).toContain(tab)
    }
  })

  it('maps the trend tab to a component and an icon', () => {
    expect(componentBackedAnalysisTabs).toContain('trend')
    expect(analysisTabComponents.trend).toBeTruthy()
    expect(analysisComponentForTab('trend')).toBe(analysisTabComponents.trend)
    expect(iconNameForAnalysisTab('trend')).toBe('trending-up')
  })
})
