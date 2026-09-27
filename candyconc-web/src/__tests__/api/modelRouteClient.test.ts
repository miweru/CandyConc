/**
 * Der Modellweg-Client.
 *
 * Der Live-Lauf am 2026-08-30 zeigte: das Backend erklaerte einen abgelehnten
 * Endpunkt praezise ("Der Endpunkt braucht http:// oder https:// am Anfang."),
 * und die Oberflaeche zeigte davon nur "Request failed with status code 400".
 * Der Hinweis, der die Eingabe repariert haette, ging genau dort verloren.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getModelRoute, setModelRoute } from '@/api/client'

interface Erfasst {
  url: string
  body: Record<string, unknown> | null
}

let erfasst: Erfasst[]

const STAND = {
  aktiv: 'lokal',
  endpoint: 'http://127.0.0.1:1234/v1/chat/completions',
  modell: 'qwen3.8-27b',
  schluessel_gesetzt: false,
  schluessel_endet_auf: null,
  schluessel_fluechtig: true,
  profile: [],
}

function installiereFetch(nutzlast: unknown, status = 200, contentType = 'application/json') {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request | string, init?: RequestInit) => {
      if (input instanceof Request) {
        const text = await input.clone().text()
        erfasst.push({ url: input.url, body: text ? JSON.parse(text) : null })
      } else {
        erfasst.push({
          url: String(input),
          body: init?.body ? JSON.parse(String(init.body)) : null,
        })
      }
      return new Response(typeof nutzlast === 'string' ? nutzlast : JSON.stringify(nutzlast), {
        status,
        headers: { 'Content-Type': contentType },
      })
    }),
  )
}

describe('Modellweg-Client', () => {
  beforeEach(() => {
    erfasst = []
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('laedt den Stand', async () => {
    installiereFetch(STAND)
    const stand = await getModelRoute()
    expect(stand.aktiv).toBe('lokal')
    expect(erfasst[0].url).toContain('settings/model-route')
  })

  it('sendet KEINEN Schluessel, wenn das Feld leer blieb', async () => {
    installiereFetch(STAND)
    await setModelRoute({ endpoint: 'http://127.0.0.1:1234/v1/chat/completions', modell: 'x' })
    expect(erfasst[0].body).not.toHaveProperty('schluessel')
  })

  it('sendet den Schluessel, wenn einer eingegeben wurde', async () => {
    installiereFetch(STAND)
    await setModelRoute({ modell: 'x', schluessel: 'sk-or-v1-geheim' })
    expect(erfasst[0].body).toMatchObject({ schluessel: 'sk-or-v1-geheim' })
  })

  it('reicht die Begruendung des Backends durch, nicht den rohen HTTP-Text', async () => {
    installiereFetch(
      {
        type: 'about:blank',
        title: 'Bad Request',
        status: 400,
        detail: 'Der Endpunkt braucht http:// oder https:// am Anfang.',
      },
      400,
    )
    await expect(setModelRoute({ endpoint: 'kein-schema' })).rejects.toThrow(
      'Der Endpunkt braucht http:// oder https:// am Anfang.',
    )
  })

  it('faellt auf den Titel zurueck, wenn kein detail dabei ist', async () => {
    installiereFetch({ title: 'Unauthorized', status: 401 }, 401)
    await expect(setModelRoute({ modell: 'x' })).rejects.toThrow('Unauthorized')
  })

  it('bleibt verstaendlich, wenn die Antwort gar kein JSON ist', async () => {
    installiereFetch('<html>502</html>', 502, 'text/html')
    await expect(setModelRoute({ modell: 'x' })).rejects.toThrow()
  })
})
