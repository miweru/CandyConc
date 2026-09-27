import { describe, expect, it } from 'vitest'

import { CLIENT_SIDE_COPILOT_ALIASES, copilotToolMetadata } from '@/lib/copilotTools'

describe('copilot tool contract helpers', () => {
  it('keeps semantic_search distinct from similar_words', () => {
    expect(CLIENT_SIDE_COPILOT_ALIASES.semantic_search).toBeUndefined()
    expect(copilotToolMetadata('semantic_search').label).toBe('Semantische Suche')
    expect(copilotToolMetadata('similar_words').label).toBe('Ähnliche Wörter')
  })
})
