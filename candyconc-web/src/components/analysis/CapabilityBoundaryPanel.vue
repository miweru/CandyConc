<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { AlertTriangle, CheckCircle2, Info } from 'lucide-vue-next'
import MethodPanel from '@/components/analysis/MethodPanel.vue'
import {
  corpusFeatureDecisionPartialReason,
  corpusFeatureDecisionReason,
  corpusFeatureLabel,
} from '@/lib/productCorpusFeatures'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import type { MethodBlock } from '@/api/client'
import { useI18n } from 'vue-i18n'

interface RuntimeLimitation {
  code?: string
  message?: string
  detail?: string
  [key: string]: unknown
}

const props = withDefaults(defineProps<{
  capabilityId: string
  title?: string
  method?: MethodBlock | null
  runtimeLimitations?: Array<string | RuntimeLimitation> | null
  runtimeNotes?: string[] | null
  compact?: boolean
}>(), {
  title: undefined,
  method: null,
  runtimeLimitations: null,
  runtimeNotes: null,
  compact: false,
})

const { t } = useI18n()
const productCapabilities = useProductCapabilitiesStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const capability = computed(() => productCapabilities.capabilityFor(props.capabilityId))
const contractLimits = computed(() => capability.value?.limits?.filter(Boolean) ?? [])
const preconditions = computed(() => capability.value?.preconditions?.filter(Boolean) ?? [])
const corpusFeatureDecision = computed(() =>
  productCapabilities.corpusFeatureDecision(props.capabilityId, corpusCapabilities.activeSummary)
)
const corpusFeatureRequirements = computed(() => corpusFeatureDecision.value.requirements)
const corpusFeatureMissing = computed(() => corpusFeatureDecision.value.missing)
const corpusFeatureStatus = computed(() => corpusFeatureDecision.value.status)
const corpusFeatureStatusLabel = computed(() => {
  if (!corpusFeatureRequirements.value.length) return null
  const title = capability.value?.title ?? props.capabilityId
  const partialReason = corpusFeatureDecisionPartialReason(title, corpusFeatureDecision.value)
  if (partialReason) return partialReason
  const reason = corpusFeatureDecisionReason(title, corpusFeatureDecision.value)
  if (reason) return reason
  return t('analysis.capabilityBoundary.corpusMeets', { features: corpusFeatureRequirements.value.map(corpusFeatureLabel).join(', ') })
})
const activeCorpusEvidenceLabel = computed(() => {
  const corpus = corpusCapabilities.activeSummary
  if (!corpus) return t('analysis.capabilityBoundary.corpusNotLoaded')
  return t('analysis.capabilityBoundary.activeCorpus', { name: corpus.name })
})
const runtimeLimitationItems = computed(() =>
  (props.runtimeLimitations ?? [])
    .map((item) => {
      if (typeof item === 'string') return item.trim()
      const message = item.message || item.detail || item.code || ''
      return String(message).trim()
    })
    .filter(Boolean)
)
const runtimeNoteItems = computed(() => (props.runtimeNotes ?? []).map((item) => item.trim()).filter(Boolean))
const hasBoundaryContent = computed(() =>
  contractLimits.value.length > 0 ||
  preconditions.value.length > 0 ||
  corpusFeatureRequirements.value.length > 0 ||
  runtimeLimitationItems.value.length > 0 ||
  runtimeNoteItems.value.length > 0 ||
  Boolean(props.method)
)

onMounted(() => {
  if (!productCapabilities.hasContract) void productCapabilities.load().catch(() => null)
})
</script>

<template>
  <section v-if="hasBoundaryContent" class="capability-boundary" :class="{ compact }">
    <header class="boundary-head">
      <div class="boundary-title-row">
        <Info class="w-4 h-4" aria-hidden="true" />
        <h3 class="boundary-title">{{ title ?? t('analysis.capabilityBoundary.title') }}</h3>
      </div>
    </header>

    <div v-if="preconditions.length" class="boundary-block">
      <div class="boundary-label">
        <CheckCircle2 class="w-3.5 h-3.5" aria-hidden="true" />
        {{ t('analysis.capabilityBoundary.preconditions') }}
      </div>
      <ul class="boundary-list">
        <li v-for="item in preconditions" :key="item">{{ item }}</li>
      </ul>
    </div>

    <div v-if="corpusFeatureRequirements.length" class="boundary-block features">
      <div class="boundary-label">{{ t('analysis.capabilityBoundary.corpusRequirements') }}</div>
      <p class="feature-status" :class="corpusFeatureStatus">
        {{ corpusFeatureStatusLabel }}
      </p>
      <p class="feature-evidence">{{ activeCorpusEvidenceLabel }}</p>
      <div class="boundary-chips">
        <span
          v-for="item in corpusFeatureRequirements"
          :key="item"
          class="boundary-chip"
          :class="{ missing: corpusFeatureMissing.includes(item) }"
        >
          {{ corpusFeatureLabel(item) }}
        </span>
      </div>
    </div>

    <div v-if="contractLimits.length" class="boundary-block">
      <div class="boundary-label">
        <AlertTriangle class="w-3.5 h-3.5" aria-hidden="true" />
        {{ t('analysis.capabilityBoundary.limits') }}
      </div>
      <ul class="boundary-list">
        <li v-for="item in contractLimits" :key="item">{{ item }}</li>
      </ul>
    </div>

    <div v-if="runtimeLimitationItems.length" class="boundary-block runtime">
      <div class="boundary-label">
        <AlertTriangle class="w-3.5 h-3.5" aria-hidden="true" />
        {{ t('analysis.capabilityBoundary.runtimeWarnings') }}
      </div>
      <ul class="boundary-list">
        <li v-for="item in runtimeLimitationItems" :key="item">{{ item }}</li>
      </ul>
    </div>

    <div v-if="runtimeNoteItems.length" class="boundary-block notes">
      <div class="boundary-label">{{ t('analysis.capabilityBoundary.resultEvidence') }}</div>
      <ul class="boundary-list">
        <li v-for="item in runtimeNoteItems" :key="item">{{ item }}</li>
      </ul>
    </div>

    <MethodPanel v-if="method" :method="method" class="boundary-method" />
  </section>
</template>

<style scoped>
@reference "../../style.css";

.capability-boundary {
  @apply rounded-xl border border-neutral-200 bg-white/80 p-3 text-sm shadow-sm;
  @apply dark:border-neutral-800 dark:bg-neutral-950/60;
}

.capability-boundary.compact {
  @apply p-2.5;
}

.boundary-head {
  @apply mb-2 flex flex-wrap items-center justify-between gap-2;
}

.boundary-title-row {
  @apply flex items-center gap-2 text-neutral-800 dark:text-neutral-100;
}

.boundary-title {
  @apply text-sm font-semibold;
}
.boundary-block {
  @apply mt-2 rounded-lg border border-neutral-100 bg-neutral-50/80 p-2;
  @apply dark:border-neutral-800 dark:bg-neutral-900/50;
}

.boundary-block.features {
  @apply border-indigo-200 bg-indigo-50/60 dark:border-indigo-900 dark:bg-indigo-950/20;
}

.boundary-block.runtime {
  @apply border-amber-200 bg-amber-50/70 dark:border-amber-900 dark:bg-amber-950/30;
}

.boundary-block.notes {
  @apply border-sky-200 bg-sky-50/70 dark:border-sky-900 dark:bg-sky-950/30;
}

.boundary-label {
  @apply mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-neutral-600;
  @apply dark:text-neutral-300;
}

.boundary-list {
  @apply list-disc space-y-1 pl-5 text-xs text-neutral-700 dark:text-neutral-300;
}

.boundary-chips {
  @apply flex flex-wrap gap-1.5;
}

.boundary-chip {
  @apply rounded-full border border-neutral-200 bg-white px-2 py-0.5 text-[11px] font-medium text-neutral-700;
  @apply dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-300;
}

.boundary-chip.missing {
  @apply border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-300;
}

.feature-status {
  @apply mb-1 text-xs font-medium text-neutral-700 dark:text-neutral-300;
}

.feature-status.pass {
  @apply text-emerald-700 dark:text-emerald-300;
}

.feature-status.unknown {
  @apply text-amber-700 dark:text-amber-300;
}

.feature-status.blocked {
  @apply text-rose-700 dark:text-rose-300;
}

.feature-evidence {
  @apply mb-1.5 text-[11px] text-neutral-500 dark:text-neutral-400;
}

.boundary-operations {
  @apply mt-2 rounded-lg border border-neutral-100 bg-white/70 p-2 text-xs text-neutral-700;
  @apply dark:border-neutral-800 dark:bg-neutral-950/40 dark:text-neutral-300;
}

.boundary-operations summary {
  @apply cursor-pointer font-semibold text-neutral-600 dark:text-neutral-300;
}

.boundary-operations .boundary-list {
  @apply mt-2;
}

.boundary-operation-strip {
  @apply mt-2;
}

.boundary-method {
  @apply mt-2;
}
</style>
