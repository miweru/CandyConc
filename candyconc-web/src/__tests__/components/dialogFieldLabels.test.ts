/**
 * The name fields of the dialogs "Save analysis" and "Name subcorpus" and two
 * filters of the run history had a visible label that was not tied to the
 * field. A screen reader announced an unnamed text field.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import SaveAnalysisButton from '@/components/analysis/SaveAnalysisButton.vue'

describe('labels of dialog fields', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('ties the name label of "Save analysis" to its field', async () => {
    const wrapper = mount(SaveAnalysisButton, {
      props: { type: 'collocations', defaultName: 'freedom', corpus: 'sotu_en', docset: null, params: {} },
      global: { stubs: { Modal: { template: '<div><slot /><slot name="footer" /></div>' } } },
    })
    await wrapper.get('button').trigger('click')
    await flushPromises()
    const input = wrapper.get('.save-input').element as HTMLInputElement
    const label = wrapper.get('.save-label').element as HTMLLabelElement
    expect(input.id).not.toBe('')
    expect(label.htmlFor).toBe(input.id)
  })
})
