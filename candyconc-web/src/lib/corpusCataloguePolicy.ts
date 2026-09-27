import type { CorpusSummary } from '@/api/client'
import { t } from '@/i18n'

export function corpusStatusForActivation(corpus: CorpusSummary | null | undefined): string {
  return String(corpus?.status ?? 'ready').toLowerCase()
}

export function corpusRequiresPartialImportAcknowledgement(
  corpus: CorpusSummary | null | undefined,
): boolean {
  return Boolean(corpus?.partial_input)
}

export function canActivateCorpusSummary(corpus: CorpusSummary | null | undefined): boolean {
  return Boolean(corpus) &&
    corpusStatusForActivation(corpus) === 'ready' &&
    !corpusRequiresPartialImportAcknowledgement(corpus)
}

export function canActivateCorpusWithPartialImportAcknowledgement(
  corpus: CorpusSummary | null | undefined,
  acknowledged: boolean,
): boolean {
  return Boolean(corpus) &&
    corpusStatusForActivation(corpus) === 'ready' &&
    (!corpusRequiresPartialImportAcknowledgement(corpus) || acknowledged)
}

export function corpusActivationBlockReason(corpus: CorpusSummary | null | undefined): string | null {
  if (!corpus) return t('corpus.cataloguePolicy.notYetInCatalogue')
  const status = corpusStatusForActivation(corpus)
  if (status === 'ready' && corpusRequiresPartialImportAcknowledgement(corpus)) {
    return t('corpus.cataloguePolicy.partialImport')
  }
  if (status === 'ready') return null
  const detail = corpus.status_reason ? ` ${corpus.status_reason}` : ''
  return t('corpus.cataloguePolicy.notReady', { status, detail })
}

export function canUnregisterCorpusSummary(corpus: CorpusSummary | null | undefined): boolean {
  if (!corpus || corpus.name.toLowerCase() === 'default') return false
  return corpus.source === 'registry'
}

export function corpusUnregisterBlockReason(corpus: CorpusSummary | null | undefined): string | null {
  if (!corpus) return t('corpus.cataloguePolicy.notInCatalogue')
  if (corpus.name.toLowerCase() === 'default') return t('corpus.cataloguePolicy.defaultNotRemovable')
  if (corpus.source !== 'registry') {
    return t('corpus.cataloguePolicy.onlyRegistry', { source: corpus.source ?? t('corpus.cataloguePolicy.unknown') })
  }
  return null
}
