/**
 * Der Modellweg-Schalter: lokal oder ueber einen Anbieter.
 *
 * Die wichtigste Eigenschaft ist eine negative: der Zugangsschluessel darf
 * nirgends in der Oberflaeche landen. Das Backend gibt ihn nicht zurueck, und
 * dieser Test haelt fest, dass die Oberflaeche ihn auch nicht selbst anzeigt.
 */
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SettingsModelRoute from '@/components/settings/SettingsModelRoute.vue'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'

const getModelRoute = vi.fn()
const setModelRoute = vi.fn()

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getModelRoute: (...args: unknown[]) => getModelRoute(...args),
    setModelRoute: (...args: unknown[]) => setModelRoute(...args),
  }
})

const PROFILE = [
  {
    id: 'lokal',
    name: 'Lokal (LM Studio)',
    endpoint: 'http://127.0.0.1:1234/v1/chat/completions',
    schluessel_noetig: false,
    hinweis: 'Läuft auf diesem Gerät. Kein Text verlässt den Rechner.',
  },
  {
    id: 'openrouter',
    name: 'OpenRouter',
    endpoint: 'https://openrouter.ai/api/v1/chat/completions',
    schluessel_noetig: true,
    hinweis: 'Fragen und Korpusausschnitte gehen an einen fremden Dienst.',
  },
]

function stand(ueberschreibung: Record<string, unknown> = {}) {
  return {
    aktiv: 'lokal',
    endpoint: 'http://127.0.0.1:1234/v1/chat/completions',
    modell: 'qwen3.8-27b',
    schluessel_gesetzt: false,
    schluessel_endet_auf: null,
    schluessel_fluechtig: true,
    profile: PROFILE,
    ...ueberschreibung,
  }
}

function erlaube(enabled: boolean) {
  const caps = useProductCapabilitiesStore()
  vi.spyOn(caps, 'productOperationAvailability').mockReturnValue({
    visible: true,
    enabled,
    disabledReason: enabled ? null : 'Nicht freigegeben',
    operations: [],
  } as never)
}

async function montiere() {
  const wrapper = mount(SettingsModelRoute)
  await flushPromises()
  return wrapper
}

describe('SettingsModelRoute', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    getModelRoute.mockReset()
    setModelRoute.mockReset()
    getModelRoute.mockResolvedValue(stand())
    erlaube(true)
  })

  it('zeigt den lokalen Weg als aktiv und ohne Warnung', async () => {
    const wrapper = await montiere()
    expect(wrapper.text()).toContain('Lokal (LM Studio)')
    expect(wrapper.find('.warnkasten').exists()).toBe(false)
    expect(wrapper.find('#modellweg-schluessel').exists()).toBe(false)
  })

  it('nennt beim fremden Dienst, dass Korpusausschnitte das Geraet verlassen', async () => {
    const wrapper = await montiere()
    await wrapper.findAll('.profil-btn')[1].trigger('click')
    const kasten = wrapper.find('.warnkasten')
    expect(kasten.exists()).toBe(true)
    expect(kasten.text()).toContain('fremden Dienst')
    expect(kasten.text().replace(/\s+/g, ' ')).toContain('nicht gespeichert')
  })

  it('uebernimmt beim Profilwechsel den Endpunkt', async () => {
    const wrapper = await montiere()
    await wrapper.findAll('.profil-btn')[1].trigger('click')
    const feld = wrapper.get('#modellweg-endpoint').element as HTMLInputElement
    expect(feld.value).toBe('https://openrouter.ai/api/v1/chat/completions')
  })

  it('zeigt den Schluessel NIRGENDS an, auch wenn einer hinterlegt ist', async () => {
    getModelRoute.mockResolvedValue(
      stand({ aktiv: 'openrouter', schluessel_gesetzt: true, schluessel_endet_auf: 'abcd' }),
    )
    const wrapper = await montiere()
    const feld = wrapper.get('#modellweg-schluessel').element as HTMLInputElement
    expect(feld.value).toBe('')
    expect(feld.getAttribute('type')).toBe('password')
    // Nur der Schwanz darf sichtbar sein, damit man ihn wiedererkennt.
    expect(wrapper.text()).toContain('endet auf abcd')
  })

  it('sendet den Schluessel nur, wenn wirklich einer eingegeben wurde', async () => {
    getModelRoute.mockResolvedValue(
      stand({ aktiv: 'openrouter', schluessel_gesetzt: true, schluessel_endet_auf: 'abcd' }),
    )
    setModelRoute.mockResolvedValue(stand({ aktiv: 'openrouter', schluessel_gesetzt: true }))
    const wrapper = await montiere()
    await wrapper.get('.speichern-btn').trigger('click')
    await flushPromises()
    expect(setModelRoute).toHaveBeenCalledWith(
      expect.objectContaining({ schluessel: undefined }),
    )
  })

  it('sperrt das Umstellen, solange fuer den fremden Weg kein Schluessel da ist', async () => {
    const wrapper = await montiere()
    await wrapper.findAll('.profil-btn')[1].trigger('click')
    const knopf = wrapper.get('.speichern-btn').element as HTMLButtonElement
    expect(knopf.disabled).toBe(true)

    await wrapper.get('#modellweg-schluessel').setValue('sk-or-v1-geheim')
    expect((wrapper.get('.speichern-btn').element as HTMLButtonElement).disabled).toBe(false)
  })

  it('sperrt alles, wenn die Faehigkeit das Umstellen nicht freigibt', async () => {
    erlaube(false)
    const wrapper = await montiere()
    expect((wrapper.get('.speichern-btn').element as HTMLButtonElement).disabled).toBe(true)
    expect((wrapper.get('#modellweg-endpoint').element as HTMLInputElement).disabled).toBe(true)
  })

  it('meldet einen abgelehnten Wechsel, statt ihn als erfolgt darzustellen', async () => {
    setModelRoute.mockRejectedValue(new Error('Der Endpunkt braucht http:// oder https:// am Anfang.'))
    const wrapper = await montiere()
    await wrapper.get('.speichern-btn').trigger('click')
    await flushPromises()
    expect(wrapper.find('.fehlerzeile').text()).toContain('http://')
  })
})
