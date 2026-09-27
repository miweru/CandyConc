<script setup lang="ts">
import { computed } from 'vue'
import type { CorpusSummary } from '@/api/client'
import {
  alignmentExecutionContractLabel,
  alignmentGenericAxisFiltersSupported,
  alignmentPairAxes,
  alignmentPairingSchema,
  frequencyGroupOptions,
  hasParallelGroups,
  hasParallelKwic,
  hasPassageSearch,
  hasWordSimilarity,
  isCorpusPaired,
  queryAttributeOptions,
} from '@/lib/corpusFeatureOptions'
import { textTypeLabel } from '@/lib/pairSides'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps<{
  summary: CorpusSummary
}>()

const schemaVersion = computed(() => props.summary.features?.schema_version ?? t('corpus.featureEvidence.legacyMap'))
const tokenAttributes = computed(() => queryAttributeOptions(props.summary).map((option) => option.label))
const frequencyGroups = computed(() => frequencyGroupOptions(props.summary).map((option) => option.label))
const semanticFlags = computed(() => [
  { key: 'passages', label: t('corpus.featureEvidence.passages'), active: hasPassageSearch(props.summary) },
  { key: 'words', label: t('corpus.featureEvidence.wordSimilarity'), active: hasWordSimilarity(props.summary) },
  { key: 'sentences', label: t('corpus.featureEvidence.sentenceAlignment'), active: Boolean(props.summary.features?.semantic?.sentence_alignment) },
])
const alignmentFlags = computed(() => [
  { key: 'paired', label: t('corpus.featureEvidence.paired'), active: isCorpusPaired(props.summary) },
  { key: 'groups', label: t('corpus.featureEvidence.parallelGroups'), active: hasParallelGroups(props.summary) },
  { key: 'kwic', label: t('corpus.featureEvidence.parallelKwic'), active: hasParallelKwic(props.summary) },
])
const pairAxes = computed(() => alignmentPairAxes(props.summary))
const pairingSchema = computed(() => alignmentPairingSchema(props.summary))
// "Anker (anchor)", "Mensch (human)": the side and the stored value.
function anchorRoleLabel(value: string): string {
  const label = textTypeLabel(value)
  return label === value ? value : `${label} (${value})`
}
const pairingContractLabel = computed(() => alignmentExecutionContractLabel(props.summary))
const genericAxisFiltersSupported = computed(() => alignmentGenericAxisFiltersSupported(props.summary))
const variantAxisFields = computed(() => pairingSchema.value?.variant_axis_fields ?? [])
const legacyResponseFieldEntries = computed(() =>
  Object.entries(pairingSchema.value?.legacy_response_fields ?? {})
)
const enabledCapabilities = computed(() =>
  Object.entries(props.summary.capabilities ?? {})
    .filter(([, value]) => value === true)
    .map(([key]) => key)
    .sort()
)
</script>

<template>
  <details class="feature-evidence">
    <summary>
      <span>{{ t('corpus.featureEvidence.title') }}</span>
      <small>{{ schemaVersion }}</small>
    </summary>

    <div class="feature-grid">
      <div class="feature-section">
        <strong>{{ t('corpus.featureEvidence.tokenAttributes') }}</strong>
        <div class="chip-row">
          <span v-for="item in tokenAttributes" :key="item" class="feature-chip">{{ item }}</span>
          <span v-if="!tokenAttributes.length" class="feature-chip muted">{{ t('corpus.featureEvidence.noEvidence') }}</span>
        </div>
      </div>

      <div class="feature-section">
        <strong>{{ t('corpus.featureEvidence.frequencyGroups') }}</strong>
        <div class="chip-row">
          <span v-for="item in frequencyGroups" :key="item" class="feature-chip">{{ item }}</span>
          <span v-if="!frequencyGroups.length" class="feature-chip muted">{{ t('corpus.featureEvidence.noEvidence') }}</span>
        </div>
      </div>

      <div class="feature-section">
        <strong>{{ t('corpus.featureEvidence.semantic') }}</strong>
        <div class="chip-row">
          <span
            v-for="item in semanticFlags"
            :key="item.key"
            class="feature-chip"
            :class="{ active: item.active, muted: !item.active }"
          >
            {{ item.label }}: {{ item.active ? t('corpus.shared.yes') : t('corpus.shared.no') }}
          </span>
        </div>
      </div>

      <div class="feature-section">
        <strong>{{ t('corpus.featureEvidence.alignment') }}</strong>
        <div class="chip-row">
          <span
            v-for="item in alignmentFlags"
            :key="item.key"
            class="feature-chip"
            :class="{ active: item.active, muted: !item.active }"
          >
            {{ item.label }}: {{ item.active ? t('corpus.shared.yes') : t('corpus.shared.no') }}
          </span>
          <span v-for="axis in pairAxes" :key="axis" class="feature-chip active">{{ t('corpus.featureEvidence.axis', { axis }) }}</span>
        </div>
        <div v-if="pairingSchema" class="pairing-contract" :aria-label="t('corpus.featureEvidence.pairingDetails')">
          <div class="pairing-contract-head">
            <strong>{{ t('corpus.featureEvidence.pairingDetails') }}</strong>
            <span
              class="feature-chip"
              :class="{ active: genericAxisFiltersSupported, muted: !genericAxisFiltersSupported }"
            >
              {{ genericAxisFiltersSupported ? t('corpus.featureEvidence.axisFiltersGeneric') : t('corpus.featureEvidence.axisFiltersLegacy') }}
            </span>
          </div>
          <p>{{ pairingContractLabel }}</p>
          <div class="pairing-facts">
            <span><strong>{{ t('corpus.featureEvidence.pairingType') }}</strong>{{ pairingSchema.schema_id }}</span>
            <span><strong>{{ t('corpus.featureEvidence.groupField') }}</strong>{{ pairingSchema.group_key_field || t('corpus.featureOptions.notDeclared') }}</span>
            <span v-if="pairingSchema.anchor_role_field"><strong>{{ t('corpus.featureEvidence.anchorRoleField') }}</strong>{{ pairingSchema.anchor_role_field }}</span>
            <span v-if="pairingSchema.default_anchor_role"><strong>{{ t('corpus.featureEvidence.defaultAnchorRole') }}</strong>{{ anchorRoleLabel(pairingSchema.default_anchor_role) }}</span>
            <span v-if="variantAxisFields.length"><strong>{{ t('corpus.featureEvidence.variantAxes') }}</strong>{{ variantAxisFields.join(', ') }}</span>
            <span v-if="pairingSchema.legacy_variant_filter_field"><strong>{{ t('corpus.featureEvidence.variantFilter') }}</strong>{{ pairingSchema.legacy_variant_filter_field }}</span>
          </div>
          <div v-if="legacyResponseFieldEntries.length" class="legacy-response-fields">
            <strong>{{ t('corpus.featureEvidence.responseFields') }}</strong>
            <span
              v-for="entry in legacyResponseFieldEntries"
              :key="`${entry[0]}-${entry[1]}`"
              class="feature-chip code muted"
            >
              {{ entry[0] }} → {{ entry[1] }}
            </span>
          </div>
          <p v-if="!genericAxisFiltersSupported" class="pairing-warning">
            {{ t('corpus.featureEvidence.pairingWarning') }}
          </p>
        </div>
      </div>
    </div>

    <div v-if="enabledCapabilities.length" class="feature-section legacy">
      <strong>{{ t('corpus.featureEvidence.legacyFlags') }}</strong>
      <div class="chip-row">
        <span v-for="item in enabledCapabilities" :key="item" class="feature-chip code">{{ item }}</span>
      </div>
    </div>

  </details>
</template>

<style scoped>
@reference "../../style.css";

.feature-evidence {
  @apply mt-3 rounded-lg border border-neutral-200 bg-white/70 p-3 text-xs;
  @apply dark:border-neutral-700 dark:bg-neutral-900/60;
}

.feature-evidence summary {
  @apply flex cursor-pointer list-none items-center justify-between gap-2 font-semibold text-neutral-800;
  @apply dark:text-neutral-100;
}

.feature-evidence summary::-webkit-details-marker {
  @apply hidden;
}

.feature-evidence small {
  @apply rounded-full bg-neutral-100 px-2 py-0.5 text-[0.65rem] font-medium text-neutral-500;
  @apply dark:bg-neutral-800 dark:text-neutral-400;
}

.feature-grid {
  @apply mt-3 grid grid-cols-1 gap-3 md:grid-cols-2;
}

.feature-section {
  @apply space-y-1.5;
}

.feature-section strong {
  @apply text-[0.68rem] uppercase tracking-wide text-neutral-500 dark:text-neutral-400;
}

.feature-section.legacy {
  @apply mt-3 border-t border-neutral-100 pt-3 dark:border-neutral-800;
}

.pairing-contract {
  @apply mt-2 rounded-lg border border-sky-100 bg-sky-50/60 p-2;
  @apply dark:border-sky-900/40 dark:bg-sky-950/20;
}

.pairing-contract-head {
  @apply flex flex-wrap items-center justify-between gap-2;
}

.pairing-contract p {
  @apply mt-1 text-[0.68rem] leading-relaxed text-neutral-600 dark:text-neutral-300;
}

.pairing-facts {
  @apply mt-2 grid grid-cols-1 gap-1.5 sm:grid-cols-2;
}

.pairing-facts span {
  @apply rounded-md border border-white/70 bg-white/70 px-2 py-1 text-[0.68rem] text-neutral-700;
  @apply dark:border-neutral-800 dark:bg-neutral-950/50 dark:text-neutral-300;
}

.pairing-facts span strong {
  @apply mr-1.5 text-[0.62rem] text-neutral-500 dark:text-neutral-400;
}

.legacy-response-fields {
  @apply mt-2 flex flex-wrap items-center gap-1.5;
}

.pairing-warning {
  @apply text-amber-700 dark:text-amber-300;
}

.chip-row {
  @apply flex flex-wrap gap-1.5;
}

.feature-chip {
  @apply rounded-full border border-neutral-200 bg-neutral-50 px-2 py-0.5 text-[0.68rem] font-medium text-neutral-700;
  @apply dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-300;
}

.feature-chip.active {
  @apply border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-300;
}

.feature-chip.muted {
  @apply text-neutral-400 dark:text-neutral-500;
}

.feature-chip.code {
  @apply font-mono;
}
</style>
