<script setup lang="ts">
/**
 * LexicalDiversityCard (F4) — TTR / STTR / Guiraud / MATTR, optionally per
 * comparison side (Human vs AI). Prominent in the Human-vs-AI contrast view.
 *
 * Methodological guard: raw TTR is length-confounded, so when the two sides
 * differ markedly in token count the card warns and steers the reader to
 * STTR / MATTR (window-normalised, corpus-size comparable).
 *
 * Defensive throughout: every backend field is optional. If the endpoint is
 * absent (older backend) the card surfaces a soft notice instead of crashing.
 */
import { ref, computed, watch } from 'vue'
import { RefreshCw, AlertTriangle, Activity } from 'lucide-vue-next'
import Button from '@/components/ui/Button.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import {
  type LexicalDiversityResult,
  type LexicalDiversitySide,
} from '@/api/client'
import { useContrastOperations } from '@/composables/useContrastOperations'
import { formatNumber } from '@/i18n/format'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  corpus?: string
  /** Target side docset (e.g. AI). */
  targetDocsetId?: string | null
  /** Reference side docset (e.g. Human). */
  referenceDocsetId?: string | null
  targetLabel?: string
  referenceLabel?: string
  /** Auto-load when both sides are available. */
  autoLoad?: boolean
}>()

const { t } = useI18n()
const result = ref<LexicalDiversityResult | null>(null)
const isLoading = ref(false)
const error = ref<string | null>(null)
const unavailable = ref(false)
const { loadLexicalDiversity } = useContrastOperations()

const canLoad = computed(() => !!props.targetDocsetId || !!props.referenceDocsetId || !!props.corpus)

interface SideView extends LexicalDiversitySide {
  resolvedLabel: string
}

const sides = computed<SideView[]>(() => {
  const r = result.value
  if (!r) return []
  if (Array.isArray(r.per_side) && r.per_side.length) {
    return r.per_side.map((side, idx) => ({
      ...side,
      // Prefer the caller's human labels for the two known sides; the backend's
      // `label` (which may just be the generic dict key 'target'/'reference')
      // is the next fallback, then a localized default.
      resolvedLabel:
        (idx === 0 ? props.targetLabel : idx === 1 ? props.referenceLabel : undefined)
        ?? side.label
        ?? (idx === 0 ? t('analysis.lexicalDiversity.target') : idx === 1 ? t('analysis.lexicalDiversity.reference') : t('analysis.lexicalDiversity.side', { n: idx + 1 })),
    }))
  }
  // Single-scope result (no comparison): present the aggregate as one column.
  return [
    {
      resolvedLabel: props.targetLabel ?? t('analysis.lexicalDiversity.corpus'),
      ttr: r.ttr,
      sttr: r.sttr,
      sttr_window: r.sttr_window,
      guiraud: r.guiraud,
      mattr: r.mattr,
      n_tokens: r.n_tokens,
      n_types: r.n_types,
    },
  ]
})

const sttrWindow = computed(() => {
  const direct = result.value?.sttr_window
  if (typeof direct === 'number') return direct
  const fromSide = sides.value.find((s) => typeof s.sttr_window === 'number')?.sttr_window
  return typeof fromSide === 'number' ? fromSide : null
})

/**
 * Warn when the two sides differ substantially in size (raw TTR is then not
 * comparable). Threshold: > 20% relative difference in token count. This is the
 * client-side FALLBACK; the backend's `size_warning` is authoritative.
 */
const lengthConfounded = computed(() => {
  if (sides.value.length < 2) return false
  const a = sides.value[0]?.n_tokens
  const b = sides.value[1]?.n_tokens
  if (typeof a !== 'number' || typeof b !== 'number' || a <= 0 || b <= 0) return false
  const ratio = Math.abs(a - b) / Math.max(a, b)
  return ratio > 0.2
})

/** The backend size caveat, if any (takes precedence over the heuristic). */
const backendSizeWarning = computed(() => {
  const w = result.value?.size_warning
  return typeof w === 'string' && w.trim() ? w.trim() : null
})

/** Whether to show the size caveat at all (backend message OR local heuristic). */
const showSizeWarning = computed(() => !!backendSizeWarning.value || lengthConfounded.value)

/** Text to render in the warning banner — prefer the backend message. */
const sizeWarningText = computed(
  () =>
    backendSizeWarning.value
    ?? t('analysis.lexicalDiversity.sizeWarning')
)

function fmt(value: number | null | undefined, digits = 3): string {
  // Active-locale decimals, matching the other analysis surfaces (CollocationsTab /
  // FreeContrastPanel) so one screen never mixes number formats.
  return typeof value === 'number' && Number.isFinite(value)
    ? formatNumber(value, { minimumFractionDigits: digits, maximumFractionDigits: digits })
    : '–'
}

function fmtInt(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? formatNumber(value)
    : '–'
}

async function load() {
  if (!canLoad.value) return
  isLoading.value = true
  error.value = null
  unavailable.value = false
  try {
    result.value = await loadLexicalDiversity({
      corpus: props.corpus,
      targetDocsetId: props.targetDocsetId ?? undefined,
      referenceDocsetId: props.referenceDocsetId ?? undefined,
    })
  } catch (err) {
    // A 404 / network failure for an unbuilt endpoint should degrade softly.
    const status = (err as { response?: { status?: number } })?.response?.status
    if (status === 404 || status === 501) {
      unavailable.value = true
    } else {
      error.value = err instanceof Error ? err.message : t('analysis.lexicalDiversity.loadFailed')
    }
  } finally {
    isLoading.value = false
  }
}

// Auto-load (and reload) when the comparison sides change.
watch(
  () => [props.targetDocsetId, props.referenceDocsetId, props.corpus],
  () => {
    if (props.autoLoad && canLoad.value) {
      void load()
    }
  },
  { immediate: true }
)

defineExpose({ load })
</script>

<template>
  <section class="diversity-card">
    <header class="card-head">
      <div class="card-title">
        <Activity class="w-4 h-4" />
        {{ t('analysis.lexicalDiversity.title') }}
      </div>
      <Button
        variant="ghost"
        size="sm"
        :icon="RefreshCw"
        :disabled="!canLoad || isLoading"
        @click="load"
      >
        {{ result ? t('analysis.lexicalDiversity.refresh') : t('analysis.lexicalDiversity.compute') }}
      </Button>
    </header>

    <p class="card-hint">
      {{ t('analysis.lexicalDiversity.ttrHint') }}
      <span v-if="sttrWindow">{{ t('analysis.lexicalDiversity.sttrWindow', { size: fmtInt(sttrWindow) }) }}</span>
    </p>

    <div v-if="isLoading" class="card-loading">
      <Skeleton v-for="i in 3" :key="i" height="1.75rem" class="mb-2" />
    </div>

    <div v-else-if="unavailable" class="card-note">
      {{ t('analysis.lexicalDiversity.unavailable') }}
    </div>

    <div v-else-if="error" class="card-error">
      <AlertTriangle class="w-4 h-4" />
      <span>{{ error }}</span>
    </div>

    <template v-else-if="sides.length">
      <div
        v-if="showSizeWarning"
        class="length-warning"
        role="note"
      >
        <AlertTriangle class="w-4 h-4 shrink-0" />
        <span>{{ sizeWarningText }}</span>
      </div>

      <div class="table-wrap">
        <table class="diversity-table">
          <thead>
            <tr>
              <th>{{ t('analysis.lexicalDiversity.measure') }}</th>
              <th v-for="side in sides" :key="`h-${side.resolvedLabel}`" class="num">
                {{ side.resolvedLabel }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr :class="{ deemphasize: showSizeWarning }">
              <td class="metric">
                TTR
                <span v-if="showSizeWarning" class="metric-flag" :title="t('analysis.lexicalDiversity.lengthConfounded')">!</span>
              </td>
              <td v-for="side in sides" :key="`ttr-${side.resolvedLabel}`" class="num">
                {{ fmt(side.ttr) }}
              </td>
            </tr>
            <tr>
              <td class="metric">STTR</td>
              <td v-for="side in sides" :key="`sttr-${side.resolvedLabel}`" class="num strong">
                {{ fmt(side.sttr) }}
              </td>
            </tr>
            <tr>
              <td class="metric">Guiraud R</td>
              <td v-for="side in sides" :key="`g-${side.resolvedLabel}`" class="num">
                {{ fmt(side.guiraud, 2) }}
              </td>
            </tr>
            <tr v-if="sides.some((s) => typeof s.mattr === 'number')">
              <td class="metric">MATTR</td>
              <td v-for="side in sides" :key="`m-${side.resolvedLabel}`" class="num strong">
                {{ fmt(side.mattr) }}
              </td>
            </tr>
            <tr class="meta-row">
              <td class="metric">{{ t('analysis.lexicalDiversity.tokens') }}</td>
              <td v-for="side in sides" :key="`n-${side.resolvedLabel}`" class="num">
                {{ fmtInt(side.n_tokens) }}
              </td>
            </tr>
            <tr class="meta-row">
              <td class="metric">{{ t('analysis.lexicalDiversity.types') }}</td>
              <td v-for="side in sides" :key="`v-${side.resolvedLabel}`" class="num">
                {{ fmtInt(side.n_types) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <div v-else class="card-note">
      {{ t('analysis.lexicalDiversity.empty') }}
    </div>
  </section>
</template>

<style scoped>
@reference "../../style.css";

.diversity-card {
  @apply rounded-xl border border-neutral-200 dark:border-neutral-700;
  @apply bg-white dark:bg-neutral-900;
  @apply p-4 space-y-3;
}

.card-head {
  @apply flex items-center justify-between gap-2;
}

.card-title {
  @apply flex items-center gap-2 text-sm font-semibold;
  @apply text-neutral-800 dark:text-neutral-100;
}

.card-hint {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.card-loading {
  @apply pt-1;
}

.card-note {
  @apply text-sm text-neutral-500 dark:text-neutral-400;
}

.card-error {
  @apply flex items-center gap-2 text-sm text-error-600 dark:text-error-400;
}

.length-warning {
  @apply flex items-start gap-2 rounded-lg px-3 py-2 text-xs;
  @apply bg-amber-50 text-amber-800 border border-amber-200;
  @apply dark:bg-amber-900/20 dark:text-amber-200 dark:border-amber-800;
}

.table-wrap {
  @apply overflow-x-auto;
}

.diversity-table {
  @apply w-full text-sm;
  border-collapse: collapse;
}

.diversity-table th {
  @apply py-1.5 px-3 text-left font-medium text-neutral-500 dark:text-neutral-400;
  @apply border-b border-neutral-200 dark:border-neutral-700;
}

.diversity-table th.num,
.diversity-table td.num {
  @apply text-right tabular-nums;
}

.diversity-table td {
  @apply py-1.5 px-3;
  @apply border-b border-neutral-100 dark:border-neutral-800;
}

.metric {
  @apply font-medium text-neutral-700 dark:text-neutral-300 whitespace-nowrap;
}

.metric-flag {
  @apply ml-1 inline-flex items-center justify-center;
  @apply text-[10px] font-bold text-amber-600 dark:text-amber-400;
}

.num.strong {
  @apply font-semibold text-neutral-900 dark:text-neutral-100;
}

.deemphasize {
  @apply opacity-60;
}

.meta-row td {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}
</style>
