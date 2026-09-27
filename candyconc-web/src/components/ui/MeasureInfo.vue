<script setup lang="ts">
/**
 * MeasureInfo — kleines Info-Affordance neben einem Maß-Picker.
 *
 * Zeigt bei Hover UND Tastaturfokus ein Popover mit Maßname, der Formel als
 * nativem MathML (keine Rendering-Library), einer wissenschaftlichen
 * Erklärung und der etablierten Referenz. Escape schließt das Popover.
 *
 * Datenquelle in Prioritätsreihenfolge:
 *  1. der `method`-Block der letzten Analyse-Antwort (Server-Wahrheit, inkl.
 *     familienspezifischer Formel-Overrides), aufgelöst über `measureKey`;
 *  2. der statische Katalog-Spiegel `lib/measureCatalog.ts` (per Kontrakt-Test
 *     byte-identisch an die Backend-Felder gepinnt), damit die Formel schon
 *     VOR der ersten Analyse verfügbar ist.
 */
import { computed, ref } from 'vue'
import { methodStatEntries, type MethodBlock } from '@/api/client'
import { measureCatalogEntry } from '@/lib/measureCatalog'
import { safeMathml } from '@/lib/safeMathml'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  /** Katalog-/Statistik-Key des Maßes (UI-Schreibweisen wie 'tscore' erlaubt). */
  measureKey: string
  /** method-Block der letzten Analyse-Antwort (Server-Wahrheit, optional). */
  method?: MethodBlock | null
  /** Label-Fallback, falls weder method-Block noch Katalog einen Namen liefern. */
  fallbackLabel?: string
}>()

const { t } = useI18n()
const open = ref(false)
const popoverId = `measure-info-${Math.random().toString(36).slice(2, 10)}`

/** UI-Schreibweise -> Statistik-Key des method-Blocks (Response-Feldnamen). */
function normalizedStatKey(key: string): string {
  const lower = key.trim().toLowerCase()
  if (lower === 'tscore') return 't'
  if (lower === 'f') return 'frequency'
  return lower
}

const serverStat = computed(() => {
  const key = normalizedStatKey(props.measureKey)
  return methodStatEntries(props.method).find((stat) => stat.key === key) ?? null
})

const catalogEntry = computed(() => measureCatalogEntry(props.measureKey))

function stringField(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

const name = computed(() =>
  stringField(serverStat.value?.name)
  ?? catalogEntry.value?.name
  ?? props.fallbackLabel
  ?? props.measureKey,
)
const explanation = computed(() =>
  stringField(serverStat.value?.explanation) ?? catalogEntry.value?.explanation ?? null,
)
const reference = computed(() =>
  stringField(serverStat.value?.reference) ?? catalogEntry.value?.reference ?? null,
)
const rawMathml = computed(() =>
  stringField(serverStat.value?.formula_mathml) ?? catalogEntry.value?.formula_mathml ?? null,
)

const safeMathmlMarkup = computed(() => safeMathml(rawMathml.value))

const hasContent = computed(() =>
  Boolean(safeMathmlMarkup.value || explanation.value || reference.value),
)

function show() {
  open.value = true
}

function hide() {
  open.value = false
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && open.value) {
    event.stopPropagation()
    hide()
  }
}
</script>

<template>
  <span
    v-if="hasContent"
    class="measure-info"
    @mouseenter="show"
    @mouseleave="hide"
  >
    <button
      type="button"
      class="measure-info-btn"
      :aria-label="t('measures.info.formulaAria', { name })"
      :aria-describedby="open ? popoverId : undefined"
      :aria-expanded="open"
      @focus="show"
      @blur="hide"
      @keydown="onKeydown"
    >
      <svg class="measure-info-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
        <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" stroke-width="1.4" />
        <circle cx="8" cy="4.8" r="0.9" fill="currentColor" />
        <rect x="7.2" y="6.8" width="1.6" height="5" rx="0.8" fill="currentColor" />
      </svg>
    </button>
    <span
      v-show="open"
      :id="popoverId"
      class="measure-info-popover"
      role="tooltip"
    >
      <span class="measure-info-name">{{ name }}</span>
      <!-- eslint-disable-next-line vue/no-v-html — geprüftes Präsentations-MathML aus dem eigenen Methodenkatalog -->
      <span v-if="safeMathmlMarkup" class="measure-info-formula" v-html="safeMathmlMarkup" />
      <span v-if="explanation" class="measure-info-explanation">{{ explanation }}</span>
      <span v-if="reference" class="measure-info-reference">{{ t('measures.info.reference', { reference }) }}</span>
    </span>
  </span>
</template>

<style scoped>
@reference "../../style.css";

.measure-info {
  @apply relative inline-flex items-center;
}

.measure-info-btn {
  @apply inline-flex items-center justify-center p-1 rounded-full;
  @apply text-neutral-500 dark:text-neutral-400;
  @apply hover:text-primary-600 dark:hover:text-primary-400;
  @apply focus:outline-none focus:ring-2 focus:ring-primary-500;
  @apply transition-colors;
}

.measure-info-icon {
  @apply w-4 h-4;
}

.measure-info-popover {
  @apply absolute z-50 top-full left-1/2 mt-2 w-80 max-w-[80vw] -translate-x-1/2;
  @apply flex flex-col gap-2 px-3 py-2.5 rounded-lg shadow-lg text-left;
  @apply bg-white dark:bg-neutral-900;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-xs text-neutral-700 dark:text-neutral-200;
}

.measure-info-name {
  @apply font-semibold text-sm;
}

.measure-info-formula {
  @apply block overflow-x-auto py-0.5 text-sm;
}

.measure-info-explanation {
  @apply block leading-relaxed;
}

.measure-info-reference {
  @apply block text-neutral-500 dark:text-neutral-400;
}
</style>
