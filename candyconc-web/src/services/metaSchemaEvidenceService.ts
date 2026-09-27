import { getMetaSchema } from '@/api/client'
import type { MetaSchemaResponse } from '@/api/schemas'
import { t } from '@/i18n'

export interface MetaSchemaEvidence {
  indexFingerprint?: string
  metadataSchemaHash?: string
  warnings: string[]
}

const CACHE = new Map<string, MetaSchemaEvidence>()
const IN_FLIGHT = new Map<string, Promise<MetaSchemaEvidence>>()

export function clearMetaSchemaEvidenceCache(): void {
  CACHE.clear()
  IN_FLIGHT.clear()
}

export async function getMetaSchemaEvidenceForCorpus(corpusId: string): Promise<MetaSchemaEvidence> {
  const key = normalizeCorpusId(corpusId)
  const cached = CACHE.get(key)
  if (cached) return cached

  const pending = IN_FLIGHT.get(key)
  if (pending) return pending

  const request = getMetaSchema({ corpus: key === 'default' ? undefined : key }, { timeout: 5000 })
    .then((schema) => {
      const evidence = toMetaSchemaEvidence(schema)
      CACHE.set(key, evidence)
      IN_FLIGHT.delete(key)
      return evidence
    })
    .catch((error: unknown) => {
      IN_FLIGHT.delete(key)
      const warning = evidenceUnavailableWarning(error)
      if (warning === null) {
        console.warn('[MetaSchemaEvidence] Failed to load metadata schema evidence:', error)
      }
      return {
        warnings: [warning ?? t('corpus.metaSchema.loadFailed')],
      }
    })

  IN_FLIGHT.set(key, request)
  return request
}

function toMetaSchemaEvidence(schema: MetaSchemaResponse): MetaSchemaEvidence {
  return {
    indexFingerprint: schema.indexFingerprint,
    metadataSchemaHash: schema.metadataSchemaHash,
    warnings: (schema.warnings ?? []).map((warning) => `Metadata schema: ${warning}`),
  }
}

function normalizeCorpusId(corpusId: string): string {
  const trimmed = String(corpusId || '').trim()
  return trimmed || 'default'
}

function evidenceUnavailableWarning(error: unknown): string | null {
  const status = error && typeof error === 'object'
    ? (error as { response?: { status?: unknown } }).response?.status
    : undefined
  if (status === 401 || status === 403) {
    return t('corpus.metaSchema.notPermitted')
  }
  return null
}
