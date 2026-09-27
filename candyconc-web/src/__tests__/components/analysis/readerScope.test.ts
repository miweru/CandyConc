import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/client'
import ReaderTab from '@/components/analysis/ReaderTab.vue'
import { useDocsetStore, useQueryStore } from '@/stores'

enableAutoUnmount(afterEach)

function pending<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

const dokument = (id: number, text = `Text ${id}`): api.Document =>
  ({ doc_id: id, doc: `Dokument ${id}`, meta: {}, text })
const verzeichnis: api.DocumentList = {
  total: 2, offset: 0, limit: 50,
  items: [1, 2].map(id => ({ ...dokument(id), token_count: 10, preview: `Vorschau ${id}` })),
}

describe('Reader and the active scope (erprobung B6)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    setActivePinia(createPinia())
    useQueryStore().filters.corpus = 'corpus-A'
    vi.spyOn(api, 'listDocuments').mockResolvedValue(verzeichnis)
    vi.spyOn(api, 'getDocument').mockImplementation(async id => dokument(Number(id)))
    vi.spyOn(api, 'getMetaValuesPage').mockResolvedValue({
      values: { party: ['Democratic', 'Republican'] }, truncatedFields: [], limit: null,
    })
    vi.spyOn(api, 'docsetFromMeta').mockResolvedValue({ docset_id: 'party-D', doc_count: 1 })
    useDocsetStore().metaFieldValueCounts = { party: 2 }
  })

  it('offers the browsable schema fields and hides corpus-wide constants in the row label', async () => {
    const docset = useDocsetStore()
    docset.metaFieldValueCounts = { party: 2, source: 1, model: 1, doc_id: 65, path: 65 }
    vi.mocked(api.listDocuments).mockResolvedValue({
      ...verzeichnis,
      items: verzeichnis.items.map((item) => ({ ...item, meta: { source: 'state_union', model: 'none' } })),
    })
    const wrapper = mount(ReaderTab)
    await flushPromises()
    expect(api.getMetaValuesPage).toHaveBeenCalledWith(expect.objectContaining({ fields: ['party'] }))
    expect(wrapper.get('[aria-label="Metadatenfeld"]').text()).toContain('party')
    expect(wrapper.text()).not.toContain('state_union')
  })

  it('lists only the documents of the active scope and names it', async () => {
    const docset = useDocsetStore()
    docset.activeDocsetId = 'scope-R'
    docset.activeFilterSpec = { party: ['Republican'] }
    docset.activeDocsetOrigin = { kind: 'meta' }
    const wrapper = mount(ReaderTab)
    await flushPromises()
    expect(api.listDocuments).toHaveBeenLastCalledWith(
      expect.objectContaining({ corpus: 'corpus-A', scopeDocsetId: 'scope-R', docsetId: undefined }),
    )
    expect(wrapper.get('[data-testid="reader-scope"]').text()).toContain('party: Republican')
  })

  it('keeps the scope when its own field filter is applied', async () => {
    useDocsetStore().activeDocsetId = 'scope-R'
    const wrapper = mount(ReaderTab)
    await flushPromises()
    await wrapper.get('[aria-label="Metadatenfeld"]').setValue('party')
    await wrapper.get('[aria-label="Wert"]').setValue('Democratic')
    await flushPromises()
    expect(api.listDocuments).toHaveBeenLastCalledWith(
      expect.objectContaining({ docsetId: 'party-D', scopeDocsetId: 'scope-R' }),
    )
  })

  it('reloads the list when the scope changes and drops it when the scope ends', async () => {
    const wrapper = mount(ReaderTab)
    await flushPromises()
    expect(api.listDocuments).toHaveBeenLastCalledWith(expect.objectContaining({ scopeDocsetId: undefined }))
    const docset = useDocsetStore()
    docset.activeDocsetId = 'scope-R'
    await flushPromises()
    expect(api.listDocuments).toHaveBeenLastCalledWith(expect.objectContaining({ scopeDocsetId: 'scope-R', offset: 0 }))
    docset.resetDocset()
    await flushPromises()
    expect(api.listDocuments).toHaveBeenLastCalledWith(expect.objectContaining({ scopeDocsetId: undefined }))
    expect(wrapper.find('[data-testid="reader-scope"]').exists()).toBe(false)
  })

  it('ignores a scope that belongs to another corpus', async () => {
    const docset = useDocsetStore()
    docset.activeDocsetId = 'scope-R'
    useQueryStore().filters.corpus = 'corpus-B'
    mount(ReaderTab)
    await flushPromises()
    // The docset store resets its scope on a corpus change, the reader never
    // sends a docset of the old corpus.
    expect(api.listDocuments).toHaveBeenLastCalledWith(expect.objectContaining({ scopeDocsetId: undefined }))
  })
})
