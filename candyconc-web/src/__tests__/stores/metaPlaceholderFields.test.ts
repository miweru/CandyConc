/**
 * An unpaired import writes model=none, text_type=standalone and
 * variant=document into every document. The filter panel listed the three
 * fields as metadata filters with one value each. The server marks them as
 * placeholders in /analysis/meta_schema, and the store leaves them out.
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '@/api/client'
import { useDocsetStore } from '@/stores/docset'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useQueryStore } from '@/stores/query'

describe('metadata placeholders', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
    useQueryStore().setFilters({ corpus: 'sotu_en' })
    vi.spyOn(useProductCapabilitiesStore(), 'assertProductOperationAccess').mockResolvedValue({
      visible: true,
      enabled: true,
      disabledReason: null,
      operations: [],
    })
  })

  it('offers no placeholder field as a filter', async () => {
    vi.spyOn(api, 'getMetaSchema').mockResolvedValue({
      schemaVersion: 1,
      corpus: 'sotu_en',
      metadataSchemaHash: 'hash',
      warnings: [],
      metadataFields: [
        { name: 'model', kind: 'string', hasString: true, stringValueCount: 1, placeholder: true },
        { name: 'party', kind: 'string', hasString: true, stringValueCount: 2 },
        { name: 'text_type', kind: 'string', hasString: true, stringValueCount: 1, placeholder: true },
        { name: 'variant', kind: 'string', hasString: true, stringValueCount: 1, placeholder: true },
        { name: 'source', kind: 'string', hasString: true, stringValueCount: 1 },
      ],
    })
    const docset = useDocsetStore()
    await docset.loadMetaSchema(true)
    expect(docset.enumFields.map((field) => field.name)).toEqual(['party', 'source'])
  })
})
