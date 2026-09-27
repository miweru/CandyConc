<script setup lang="ts">
/**
 * ContrastTab — entry point for A-vs-B contrast.
 *
 * Routing:
 *  - The generic FreeContrastPanel is the default for every corpus.
 *  - A legacy Human/KI preset is offered only when the metadata schema proves
 *    that this special case is available.
 *  - Generic corpora use FreeContrastPanel, which drives its
 *    group selectors from /analysis/meta_schema and calls /analysis/contrast.
 */
import { ref, computed, onMounted, watch } from 'vue'
import KeynessTab from './KeynessTab.vue'
import FreeContrastPanel from './FreeContrastPanel.vue'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useDocsetStore } from '@/stores/docset'
import { pairSideValues } from '@/lib/pairSides'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const corpusStore = useCorpusCapabilitiesStore()
const docsetStore = useDocsetStore()
const isPaired = computed(() => corpusStore.isPaired)

const legacyPresetAvailable = ref(false)
const useLegacyPreset = ref(false)
const legacyPresetError = ref<string | null>(null)

async function refreshLegacyPresetAvailability() {
  legacyPresetError.value = null
  legacyPresetAvailable.value = false
  useLegacyPreset.value = false
  if (!isPaired.value) return
  try {
    const schema = await docsetStore.fetchMetaSchema(corpusStore.activeCorpus)
    if (!schema) throw new Error(docsetStore.error ?? t('analysis.contrast.schemaFailed'))
    const fields = new Set((schema.metadataFields ?? []).map((field) => field.name))
    legacyPresetAvailable.value =
      fields.has('text_type') &&
      fields.has('prompting_method') &&
      fields.has('model')
  } catch (error) {
    legacyPresetError.value = error instanceof Error ? error.message : t('analysis.contrast.schemaFailed')
  }
}

watch(
  () => [corpusStore.activeCorpus, isPaired.value] as const,
  () => {
    void refreshLegacyPresetAvailability()
  }
)

watch(legacyPresetAvailable, (available) => {
  if (!available) {
    useLegacyPreset.value = false
  }
})

onMounted(() => {
  void refreshLegacyPresetAvailability()
})

const showLegacyPreset = computed(() => legacyPresetAvailable.value && useLegacyPreset.value)
// Human/AI only for corpora whose pairs carry those values.
const presetLabel = computed(() =>
  pairSideValues(corpusStore.activeSummary).anchor === 'anchor'
    ? t('analysis.contrast.anchorVersionPreset')
    : t('analysis.contrast.humanAiPreset')
)
</script>

<template>
  <div class="contrast-tab">
    <div v-if="legacyPresetAvailable" class="contrast-mode-switch" role="tablist" :aria-label="t('analysis.contrast.mode')">
      <button
        type="button"
        class="mode-btn"
        :class="{ active: useLegacyPreset }"
        role="tab"
        :aria-selected="useLegacyPreset"
        @click="useLegacyPreset = true"
      >
        {{ presetLabel }}
      </button>
      <button
        type="button"
        class="mode-btn"
        :class="{ active: !useLegacyPreset }"
        role="tab"
        :aria-selected="!useLegacyPreset"
        @click="useLegacyPreset = false"
      >
        {{ t('analysis.contrast.free') }}
      </button>
    </div>
    <p v-else-if="isPaired && legacyPresetError" class="contrast-hint" role="status">
      {{ t('analysis.contrast.pairedPresetMissing') }}
    </p>

    <KeynessTab v-if="showLegacyPreset" mode="contrast" />
    <FreeContrastPanel v-else />
  </div>
</template>

<style scoped>
@reference "../../style.css";

.contrast-mode-switch {
  @apply flex items-center gap-1 p-1 m-4 mb-0 w-fit rounded-lg;
  @apply bg-neutral-100 dark:bg-neutral-800;
}

.mode-btn {
  @apply px-3 py-1.5 rounded-md text-sm font-medium;
  @apply text-neutral-600 dark:text-neutral-300;
  @apply transition-colors;
}

.mode-btn.active {
  @apply bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100 shadow-sm;
}

.contrast-hint {
  @apply m-4 mb-0 text-sm text-neutral-600 dark:text-neutral-300;
}
</style>
