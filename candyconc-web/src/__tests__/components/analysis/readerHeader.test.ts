/**
 * The reader labels documents with the metadata fields of the corpus.
 *
 * Before, the text header read fixed project fields (speaker_name,
 * speaker_party, protocol_date, register, model) and the list rows read
 * source, register, split and model. On the State of the Union sample the
 * header subline showed only the date, although president, party, year and
 * decade tell the speeches apart, and every row showed the bare document
 * label.
 */
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/client'
import ReaderTab from '@/components/analysis/ReaderTab.vue'
import { DocumentListSchema } from '@/api/schemas'
import { useDocsetStore, useQueryStore } from '@/stores'

enableAutoUnmount(afterEach)

// Document and list responses as the server sends them for sotu_en.
const TRUMAN_META = {
  doc_id: 'sotu-1945-Truman',
  path: 'sotu-1945-Truman',
  source: 'state_union',
  variant: 'document',
  model: 'none',
  text_type: 'standalone',
  president: 'Harry S. Truman',
  party: 'Democratic',
  year: '1945',
  decade: '1940s',
  date: '1945-04-16',
  title: "PRESIDENT HARRY S. TRUMAN'S ADDRESS BEFORE A JOINT SESSION OF THE CONGRESS",
}

const VALUE_COUNTS = {
  date: 55, decade: 7, doc_id: 65, model: 1, party: 2, path: 65,
  president: 11, source: 1, text_type: 1, title: 26, variant: 1, year: 61,
}

function listItem(meta: Record<string, string>): api.DocumentListItem {
  return { doc_id: 0, doc: 'sotu-1945-Truman', meta, token_count: 1956, preview: 'Mr. Speaker, Mr. President' }
}

beforeEach(() => {
  vi.restoreAllMocks()
  setActivePinia(createPinia())
  useQueryStore().filters.corpus = 'sotu_en'
  vi.spyOn(api, 'getDocument').mockResolvedValue({ doc_id: 0, doc: 'sotu-1945-Truman', meta: TRUMAN_META, text: 'Mr. Speaker' })
  vi.spyOn(api, 'getMetaValuesPage').mockResolvedValue({ values: {}, truncatedFields: [], limit: null })
  useDocsetStore().metaFieldValueCounts = { ...VALUE_COUNTS }
})

describe('reader header and list rows from the corpus fields', () => {
  it('heads the text with its title and lists the fields that tell documents apart', async () => {
    vi.spyOn(api, 'listDocuments').mockResolvedValue({
      total: 1, offset: 0, limit: 50,
      // The list endpoint currently sends a fixed set of keys.
      items: [listItem({ source: 'state_union', date: '1945-04-16', text_type: 'standalone', variant: 'document', model: 'none' })],
    })
    const wrapper = mount(ReaderTab)
    await flushPromises()

    expect(wrapper.get('.text-kopf h2').text()).toBe(TRUMAN_META.title)
    expect(wrapper.get('.text-unterzeile').text()).toBe('Harry S. Truman · Democratic · 1945 · 1940s · 1945-04-16')
    expect(wrapper.get('.eintrag-kennung').text()).toBe('sotu-1945-Truman · 1945-04-16')
  })

  it('shows the fields a list row carries, whichever the server sends', async () => {
    vi.spyOn(api, 'listDocuments').mockResolvedValue({
      total: 1, offset: 0, limit: 50,
      // Schema-based list fields, as the server may send them.
      items: [listItem({ president: 'Harry S. Truman', party: 'Democratic', year: '1945', source: 'state_union' })],
    })
    const wrapper = mount(ReaderTab)
    await flushPromises()

    expect(wrapper.get('.eintrag-kennung').text()).toBe('sotu-1945-Truman · Harry S. Truman · Democratic · 1945')
  })

  it('heads a document without a title with its label, not with a project field', async () => {
    vi.mocked(api.getDocument).mockResolvedValue({
      doc_id: 3, doc: 'protocol-17-042', meta: { speaker_name: 'A. Speaker', session: '42' }, text: 'Text',
    })
    vi.spyOn(api, 'listDocuments').mockResolvedValue({
      total: 1, offset: 0, limit: 50,
      items: [{ doc_id: 3, doc: 'protocol-17-042', meta: {}, token_count: 4, preview: 'Text' }],
    })
    useDocsetStore().metaFieldValueCounts = { speaker_name: 30, session: 12 }
    const wrapper = mount(ReaderTab)
    await flushPromises()

    expect(wrapper.get('.text-kopf h2').text()).toBe('protocol-17-042')
    expect(wrapper.get('.text-unterzeile').text()).toBe('A. Speaker · 42')
  })
})

describe('reader fields named by the server', () => {
  // /docs/list names the fields for the reader (reader_fields): title_field
  // heads the text, label_fields tell documents apart, the most general first.
  const readerFields = {
    title_field: 'title',
    label_fields: ['party', 'decade', 'president', 'date', 'year'],
    basis: 'meta_index',
  }

  it('keeps reader_fields when the list response is validated', () => {
    const parsed = DocumentListSchema.parse({ total: 0, offset: 0, limit: 50, items: [], reader_fields: readerFields })
    expect(parsed.reader_fields).toEqual(readerFields)
    expect(DocumentListSchema.parse({ total: 0, offset: 0, limit: 50, items: [] }).reader_fields).toBeUndefined()
  })

  it('heads, sublines and labels documents in the order of label_fields', async () => {
    vi.spyOn(api, 'listDocuments').mockResolvedValue({
      total: 1, offset: 0, limit: 50,
      reader_fields: readerFields,
      items: [listItem({
        title: TRUMAN_META.title,
        party: 'Democratic', decade: '1940s', president: 'Harry S. Truman', date: '1945-04-16', year: '1945',
      })],
    })
    const wrapper = mount(ReaderTab)
    await flushPromises()

    expect(wrapper.get('.text-kopf h2').text()).toBe(TRUMAN_META.title)
    expect(wrapper.get('.text-unterzeile').text()).toBe('Democratic · 1940s · Harry S. Truman · 1945-04-16 · 1945')
    expect(wrapper.get('.eintrag-kennung').text()).toBe('sotu-1945-Truman · Democratic · 1940s · Harry S. Truman')
  })

  it('heads a document with its label when the server names no title field', async () => {
    vi.spyOn(api, 'listDocuments').mockResolvedValue({
      total: 1, offset: 0, limit: 50,
      reader_fields: { title_field: null, label_fields: ['party'], basis: 'meta_index' },
      items: [listItem({ party: 'Democratic' })],
    })
    const wrapper = mount(ReaderTab)
    await flushPromises()

    expect(wrapper.get('.text-kopf h2').text()).toBe('sotu-1945-Truman')
    expect(wrapper.get('.text-unterzeile').text()).toBe('Democratic')
  })
})
