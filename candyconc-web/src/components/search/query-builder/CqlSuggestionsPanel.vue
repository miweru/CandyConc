<script setup lang="ts">
import { Loader2 } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import type { SuggestionItem } from '@/api/client'
import {
  humanizeSuggestionHint,
  normalizeSuggestionHint,
} from '@/components/search/cqlAutocomplete'

const { t } = useI18n()

function normalizeSuggestionText(text: string): string {
  const trimmed = text.trim()
  return trimmed.toLowerCase().startsWith('cql:') ? trimmed.slice(4).trim() : trimmed
}

// Keys are the normalized hints the server sends (protocol values). The
// labels are catalog keys, with query syntax passed in unchanged.
const suggestionHintLabels: Record<string, { labelKey: string; syntax?: string }> = {
  'token lemma set': { labelKey: 'querybuilder.suggestions.insertLemmaSet' },
  'token lemma equals': { labelKey: 'querybuilder.suggestions.insertLemmaCondition' },
  'token word equals': { labelKey: 'querybuilder.suggestions.insertWordCondition' },
  'token pos equals': { labelKey: 'querybuilder.suggestions.insertPosCondition' },
  'token semantic similarity': { labelKey: 'querybuilder.suggestions.insertSemanticMacro' },
  'wrapper within sentence': { labelKey: 'querybuilder.suggestions.insertSyntax', syntax: 'within(<s>, ...)' },
  'wrapper doc filter + query': { labelKey: 'querybuilder.suggestions.insertSyntax', syntax: 'where(..., ...)' },
  'anzahl ähnlicher wörter': { labelKey: 'querybuilder.suggestions.setSimK' }, // i18n-ignore: normalized server hint, protocol value
  group: { labelKey: 'querybuilder.suggestions.insertGroup' },
}

function suggestionLabel(item: SuggestionItem): string {
  if (item.hint) {
    const normalized = normalizeSuggestionHint(item.hint)
    const known = suggestionHintLabels[normalized]
    if (known) return known.syntax ? t(known.labelKey, { syntax: known.syntax }) : t(known.labelKey)
    return humanizeSuggestionHint(item.hint) ?? item.hint
  }
  return item.kind === 'fix' ? t('querybuilder.suggestions.fix') : t('querybuilder.suggestions.completion')
}

/**
 * CQL assistant panel: parse errors, loading state and clickable
 * suggestion groups (salient / completions / fixes).
 * Extracted verbatim from QueryBuilderStudio.vue (Phase 2 split): pure
 * presentation over the useCqlSuggestions composable state. The caller
 * keeps the visibility condition and applies the picked suggestion.
 */
defineProps<{
  isSuggesting: boolean
  analysisErrors: string[]
  analysisWarnings: string[]
  diagnosticsStatus?: 'idle' | 'loading' | 'ok' | 'unavailable'
  diagnosticsError?: string | null
  focusedMode?: 'diagnostics' | 'suggestions' | null
  salientSuggestions: SuggestionItem[]
  otherCompletionSuggestions: SuggestionItem[]
  fixSuggestions: SuggestionItem[]
}>()

defineEmits<{
  apply: [item: SuggestionItem]
}>()
</script>

<template>
  <div class="cql-suggestions">
    <div class="suggestions-header">
      <span>{{ t('querybuilder.suggestions.title') }}</span>
      <span class="suggestions-note">{{ t('querybuilder.suggestions.note') }}</span>
    </div>

    <div v-if="focusedMode" class="operation-focus-note">
      <template v-if="focusedMode === 'diagnostics'">
        {{ t('querybuilder.suggestions.focusDiagnostics') }}
      </template>
      <template v-else>
        {{ t('querybuilder.suggestions.focusSuggestions') }}
      </template>
    </div>

    <div v-if="analysisErrors.length" class="analysis-errors">
      <div v-for="error in analysisErrors" :key="error" class="analysis-error-item">
        {{ error }}
      </div>
    </div>

    <div v-if="analysisWarnings.length" class="analysis-warnings">
      <div v-for="warning in analysisWarnings" :key="warning" class="analysis-warning-item">
        {{ warning }}
      </div>
    </div>

    <div
      v-if="diagnosticsStatus === 'unavailable' && diagnosticsError"
      class="analysis-unavailable"
      role="status"
      aria-live="polite"
    >
      <strong>{{ t('querybuilder.suggestions.diagnosticsUnavailable') }}</strong>
      <span>{{ diagnosticsError }}</span>
      <span class="analysis-unavailable-note">
        {{ t('querybuilder.suggestions.diagnosticsUnavailableNote') }}
      </span>
    </div>

    <div v-if="isSuggesting" class="suggestions-loading" role="status" aria-live="polite">
      <Loader2 class="w-4 h-4 animate-spin" aria-hidden="true" />
      <span>{{ t('querybuilder.suggestions.loading') }}</span>
    </div>

    <div v-if="salientSuggestions.length" class="suggestion-group">
      <div class="suggestion-group-title">{{ t('querybuilder.suggestions.salientTitle') }}</div>
      <button
        v-for="(item, index) in salientSuggestions"
        :key="`salient-${item.text}-${index}`"
        type="button"
        class="suggestion-item"
        @click="$emit('apply', item)"
      >
        <span class="suggestion-title">{{ suggestionLabel(item) }}</span>
        <span class="suggestion-code">{{ normalizeSuggestionText(item.text) }}</span>
        <span v-if="item.hasPlaceholders" class="suggestion-note">{{ t('querybuilder.suggestions.replacePlaceholders', { placeholders: '$1, $2' }) }}</span>
      </button>
    </div>

    <div v-if="otherCompletionSuggestions.length" class="suggestion-group">
      <div class="suggestion-group-title">{{ t('querybuilder.suggestions.otherTitle') }}</div>
      <button
        v-for="(item, index) in otherCompletionSuggestions"
        :key="`complete-${item.text}-${index}`"
        type="button"
        class="suggestion-item"
        @click="$emit('apply', item)"
      >
        <span class="suggestion-title">{{ suggestionLabel(item) }}</span>
        <span class="suggestion-code">{{ normalizeSuggestionText(item.text) }}</span>
        <span v-if="item.hasPlaceholders" class="suggestion-note">{{ t('querybuilder.suggestions.replacePlaceholders', { placeholders: '$1, $2' }) }}</span>
      </button>
    </div>

    <div v-if="fixSuggestions.length" class="suggestion-group">
      <div class="suggestion-group-title">{{ t('querybuilder.suggestions.fixesTitle') }}</div>
      <button
        v-for="(item, index) in fixSuggestions"
        :key="`fix-${item.text}-${index}`"
        type="button"
        class="suggestion-item"
        @click="$emit('apply', item)"
      >
        <span class="suggestion-title">{{ suggestionLabel(item) }}</span>
        <span class="suggestion-code">{{ normalizeSuggestionText(item.text) }}</span>
        <span v-if="item.hasPlaceholders" class="suggestion-note">{{ t('querybuilder.suggestions.replacePlaceholders', { placeholders: '$1, $2' }) }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
@reference "../../../style.css";

.cql-suggestions {
  @apply rounded-xl border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900/80 p-4 space-y-3;
}

.suggestions-header {
  @apply flex items-center gap-2;
}

.suggestions-header span:first-child {
  @apply text-sm font-semibold text-neutral-900 dark:text-neutral-100;
}

.suggestions-note {
  @apply text-sm text-neutral-500 dark:text-neutral-400;
}

.operation-focus-note {
  @apply rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900;
  @apply dark:border-amber-500/50 dark:bg-amber-900/20 dark:text-amber-100;
}

.cql-suggestions.operation-focused {
  @apply ring-2 ring-amber-300 ring-offset-2 ring-offset-white;
  @apply dark:ring-amber-500/80 dark:ring-offset-neutral-950;
}

.analysis-errors {
  @apply space-y-2;
}

.analysis-error-item {
  @apply rounded-lg bg-rose-50 text-rose-800 px-3 py-2 text-sm border border-rose-200;
}

.analysis-warnings {
  @apply space-y-2;
}

.analysis-warning-item {
  @apply rounded-lg bg-amber-50 text-amber-900 px-3 py-2 text-sm border border-amber-200;
}

.analysis-unavailable {
  @apply rounded-lg bg-slate-50 text-slate-800 px-3 py-2 text-sm border border-slate-300;
  @apply flex flex-col gap-1;
}

.analysis-unavailable-note {
  @apply text-xs text-slate-600;
}

.suggestions-loading {
  @apply flex items-center gap-2 text-sm text-neutral-500 dark:text-neutral-400;
}

.suggestion-group {
  @apply space-y-2;
}

.suggestion-group-title {
  @apply text-xs font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400;
}

.suggestion-item {
  @apply w-full text-left rounded-xl border border-neutral-200 dark:border-neutral-700 px-3 py-3 bg-neutral-50 dark:bg-neutral-800/80 hover:border-primary-300 hover:bg-primary-50/50 dark:hover:bg-neutral-800 transition-colors space-y-1;
}

.suggestion-title {
  @apply block text-sm font-medium text-neutral-900 dark:text-neutral-100;
}

.suggestion-code {
  @apply block font-mono text-xs text-neutral-600 dark:text-neutral-300 break-all;
}

.suggestion-note {
  @apply block text-xs text-neutral-500 dark:text-neutral-400;
}
</style>
