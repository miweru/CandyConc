import { formatDateTime } from '@/i18n/format'
import { t } from '@/i18n'
export type ScopeEvidenceTone = 'neutral' | 'ok' | 'warn'

export interface ScopeEvidenceInput {
  hasActiveDocset: boolean
  isDirty: boolean
  activeScopeStale?: boolean
  activeScopeWarning?: string | null
  activeScopeResolvedAt?: number | null
}

export interface ScopeEvidenceStatus {
  visible: boolean
  label: string
  tone: ScopeEvidenceTone
  title: string
  warning: string | null
  resolvedAtLabel: string | null
}


export function formatScopeResolvedAt(value?: number | null): string | null {
  if (!value) return null
  return formatDateTime(value, {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function describeScopeEvidence(input: ScopeEvidenceInput): ScopeEvidenceStatus {
  if (!input.hasActiveDocset) {
    return {
      visible: false,
      label: '',
      tone: 'neutral',
      title: t('search.scopeEvidence.wholeCorpus'),
      warning: null,
      resolvedAtLabel: null,
    }
  }

  if (input.isDirty) {
    const warning = t('search.scopeEvidence.dirtyWarning')
    return {
      visible: true,
      label: t('search.scopeEvidence.applyNeeded'),
      tone: 'warn',
      title: warning,
      warning,
      resolvedAtLabel: formatScopeResolvedAt(input.activeScopeResolvedAt),
    }
  }

  const warning = input.activeScopeWarning ?? (input.activeScopeStale ? t('search.scopeEvidence.staleWarning') : null)
  if (warning) {
    return {
      visible: true,
      label: input.activeScopeStale ? t('search.scopeEvidence.checkReproduction') : t('search.scopeEvidence.scopeWarning'),
      tone: 'warn',
      title: warning,
      warning,
      resolvedAtLabel: formatScopeResolvedAt(input.activeScopeResolvedAt),
    }
  }

  const resolvedAtLabel = formatScopeResolvedAt(input.activeScopeResolvedAt)
  return {
    visible: true,
    label: t('search.scopeEvidence.checked'),
    tone: 'ok',
    title: resolvedAtLabel
      ? t('search.scopeEvidence.checkedAt', { time: resolvedAtLabel })
      : t('search.scopeEvidence.checkedTitle'),
    warning: null,
    resolvedAtLabel,
  }
}
