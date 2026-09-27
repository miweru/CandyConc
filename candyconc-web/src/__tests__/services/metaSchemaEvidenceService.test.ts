import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getMetaSchema } from '@/api/client'
import {
  clearMetaSchemaEvidenceCache,
  getMetaSchemaEvidenceForCorpus,
} from '@/services/metaSchemaEvidenceService'

vi.mock('@/api/client', () => ({
  getMetaSchema: vi.fn(),
}))

const getMetaSchemaMock = vi.mocked(getMetaSchema)

describe('metaSchemaEvidenceService', () => {
  beforeEach(() => {
    clearMetaSchemaEvidenceCache()
    getMetaSchemaMock.mockReset()
  })

  it('maps backend meta schema fingerprints into run evidence fields and caches by corpus', async () => {
    getMetaSchemaMock.mockResolvedValue({
      schemaVersion: 1,
      corpus: 'demo',
      indexFingerprint: 'sha256:index',
      metadataSchemaHash: 'sha256:meta',
      metadataFields: [],
      warnings: ['meta_index manifest missing'],
    })

    const first = await getMetaSchemaEvidenceForCorpus('demo')
    const second = await getMetaSchemaEvidenceForCorpus('demo')

    expect(first).toEqual({
      indexFingerprint: 'sha256:index',
      metadataSchemaHash: 'sha256:meta',
      warnings: ['Metadata schema: meta_index manifest missing'],
    })
    expect(second).toEqual(first)
    expect(getMetaSchemaMock).toHaveBeenCalledTimes(1)
    expect(getMetaSchemaMock).toHaveBeenCalledWith({ corpus: 'demo' }, { timeout: 5000 })
  })

  it('uses the default backend corpus without sending an explicit corpus query', async () => {
    getMetaSchemaMock.mockResolvedValue({
      schemaVersion: 1,
      corpus: 'default',
      indexFingerprint: 'sha256:index',
      metadataSchemaHash: 'sha256:meta',
      metadataFields: [],
      warnings: [],
    })

    await getMetaSchemaEvidenceForCorpus('default')

    expect(getMetaSchemaMock).toHaveBeenCalledWith({ corpus: undefined }, { timeout: 5000 })
  })

  it('fails soft and retries later when the backend evidence endpoint is unavailable', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    getMetaSchemaMock.mockRejectedValueOnce(new Error('offline'))
    getMetaSchemaMock.mockResolvedValueOnce({
      schemaVersion: 1,
      corpus: 'demo',
      indexFingerprint: 'sha256:index',
      metadataSchemaHash: 'sha256:meta',
      metadataFields: [],
      warnings: [],
    })

    const failed = await getMetaSchemaEvidenceForCorpus('demo')
    const retried = await getMetaSchemaEvidenceForCorpus('demo')

    expect(failed).toEqual({
      warnings: ['Metadatenschema-Evidenz konnte nicht vom Backend geladen werden.'],
    })
    expect(retried.indexFingerprint).toBe('sha256:index')
    expect(getMetaSchemaMock).toHaveBeenCalledTimes(2)
    warnSpy.mockRestore()
  })

  it('records an honest, non-noisy provenance warning when the session cannot read metadata evidence', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    warnSpy.mockClear()
    getMetaSchemaMock.mockRejectedValueOnce({ response: { status: 401 } })

    await expect(getMetaSchemaEvidenceForCorpus('demo')).resolves.toEqual({
      warnings: ['Metadatenschema-Evidenz fehlt im Laufprotokoll: Die aktuelle Sitzung darf sie nicht lesen.'],
    })
    expect(warnSpy).not.toHaveBeenCalled()
    warnSpy.mockRestore()
  })
})
