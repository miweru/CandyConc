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

describe('Reader navigation', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    setActivePinia(createPinia())
    useQueryStore().filters.corpus = 'corpus-A'
    vi.spyOn(api, 'listDocuments').mockResolvedValue(verzeichnis)
    vi.spyOn(api, 'getDocument').mockImplementation(async id => dokument(Number(id)))
    vi.spyOn(api, 'getMetaValuesPage').mockResolvedValue({
      values: { source: ['A', 'B'] }, truncatedFields: [], limit: null,
    })
    vi.spyOn(api, 'docsetFromMeta').mockResolvedValue({ docset_id: 'source-A', doc_count: 1 })
    // The reader takes its browsable fields from the metadata schema.
    useDocsetStore().metaFieldValueCounts = { source: 2 }
  })

  it.each(['response', 'error'])('keeps the selected document when an older %s arrives', async outcome => {
    const first = pending<api.Document>()
    vi.mocked(api.getDocument).mockImplementationOnce(() => first.promise)
    const wrapper = mount(ReaderTab)
    await flushPromises()
    await wrapper.findAll('.listeneintrag')[1]!.trigger('click')
    await flushPromises()

    if (outcome === 'response') first.resolve(dokument(1))
    else first.reject(new Error('Altes Dokument nicht erreichbar'))
    await flushPromises()

    expect(wrapper.get('.listeneintrag.gewaehlt').text()).toContain('Dokument 2')
    expect(wrapper.get('.volltext').text()).toBe('Text 2')
    expect(wrapper.find('.reader-fehler').exists()).toBe(false)
  })

  it('removes the active filter when Ganzes Korpus is selected', async () => {
    const wrapper = mount(ReaderTab)
    await flushPromises()
    await wrapper.get('[aria-label="Metadatenfeld"]').setValue('source')
    await wrapper.get('[aria-label="Wert"]').setValue('A')
    await flushPromises()
    expect(api.listDocuments).toHaveBeenLastCalledWith(expect.objectContaining({ docsetId: 'source-A' }))

    await wrapper.get('[aria-label="Metadatenfeld"]').setValue('')
    await flushPromises()
    expect(api.listDocuments).toHaveBeenLastCalledWith(expect.objectContaining({ docsetId: undefined, offset: 0 }))
    expect(wrapper.find('.filter-weg').exists()).toBe(false)
    expect(wrapper.find('[aria-label="Wert"]').exists()).toBe(false)
  })

  it('ignores an unfinished filter after selecting Ganzes Korpus', async () => {
    const filter = pending<api.DocsetFromMetaResult>()
    vi.mocked(api.docsetFromMeta).mockImplementationOnce(() => filter.promise)
    const wrapper = mount(ReaderTab)
    await flushPromises()
    await wrapper.get('[aria-label="Metadatenfeld"]').setValue('source')
    await wrapper.get('[aria-label="Wert"]').setValue('A')
    await wrapper.get('[aria-label="Metadatenfeld"]').setValue('')
    await flushPromises()
    filter.resolve({ docset_id: 'obsolete-source-A', doc_count: 1 })
    await flushPromises()

    expect(api.listDocuments).toHaveBeenLastCalledWith(expect.objectContaining({ docsetId: undefined }))
    expect(wrapper.find('.filter-weg').exists()).toBe(false)
    expect(wrapper.get('.volltext').text()).toBe('Text 1')
  })

  it('ignores old corpus lists and metadata after switching corpus', async () => {
    const list = pending<api.DocumentList>()
    const axes = pending<api.MetaValuesPage>()
    vi.mocked(api.listDocuments).mockImplementationOnce(() => list.promise)
    vi.mocked(api.getMetaValuesPage).mockImplementationOnce(() => axes.promise)
    const wrapper = mount(ReaderTab)
    useQueryStore().filters.corpus = 'corpus-B'
    await flushPromises()
    // The schema of corpus-B arrives (the docset store cleared the old one).
    useDocsetStore().metaFieldValueCounts = { source: 2 }
    await flushPromises()
    list.resolve({ ...verzeichnis, items: [{ ...verzeichnis.items[0]!, doc_id: 99, preview: 'Alter Korpus' }] })
    axes.resolve({ values: { outdated: ['X', 'Y'] }, truncatedFields: [], limit: null })
    await flushPromises()

    expect(wrapper.findAll('.listeneintrag')).toHaveLength(2)
    expect(wrapper.text()).not.toContain('Alter Korpus')
    expect(wrapper.get('[aria-label="Metadatenfeld"]').text()).toContain('source')
    expect(api.getDocument).toHaveBeenCalledExactlyOnceWith('1', 'corpus-B')
  })

  it('does not open a document when a list arrives after closing the reader', async () => {
    const list = pending<api.DocumentList>()
    vi.mocked(api.listDocuments).mockImplementationOnce(() => list.promise)
    const wrapper = mount(ReaderTab)
    wrapper.unmount()
    list.resolve(verzeichnis)
    await flushPromises()
    expect(api.getDocument).not.toHaveBeenCalled()
  })
})
