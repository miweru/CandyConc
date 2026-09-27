<script setup lang="ts">
/**
 * AlignmentComparison - one truthful side-by-side rendering of an alignment
 * result. Fetching stays with the calling journey; this component only renders
 * the backend result so KWIC, workspace and document views cannot drift.
 */
import { computed, ref, watch } from 'vue'
import type {
  AlignmentPair,
  AlignmentRefDocResult,
  AlignmentSentence,
  AlignmentVariant,
} from '@/api/client'
import { formatNumber as formatLocaleNumber } from '@/i18n/format'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = withDefaults(defineProps<{
  result: AlignmentRefDocResult
  /** Limit the visible slice around the backend focus sentence, not the result. */
  maxRows?: number
  /** Show a token-level display diff in addition to the backend alignment scores. */
  showDiff?: boolean
}>(), {
  maxRows: Number.POSITIVE_INFINITY,
  showDiff: true,
})

const DIFF_MAX_TOKENS = 120

type DiffKind = 'equal' | 'insert' | 'delete' | 'replace'

interface DiffSegment {
  text: string
  kind: DiffKind
}

interface DiffStats {
  insert: number
  delete: number
  replace: number
  change: number
  truncated: boolean
}

interface DiffResult {
  segments: DiffSegment[]
  stats: DiffStats
}

interface ComparisonCell {
  variant: AlignmentVariant
  pair?: AlignmentPair
  diff?: DiffResult
}

interface ComparisonRow {
  key: string
  kind: 'reference' | 'variant_only'
  reference?: AlignmentSentence
  cells: ComparisonCell[]
}

interface GapSlot {
  key: string
  previousReference: number | null
  nextReference: number | null
  ordinal: number
}

function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '–'
  return formatLocaleNumber(value, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

function variantLabel(variant: AlignmentVariant): string {
  return variant.meta.profile_name?.trim()
    || variant.label?.trim()
    || variant.axis_value?.trim()
    || variant.model?.trim()
    || variant.meta.model
    || t('kwic.alignment.documentId', { id: variant.doc_id })
}

function focusIndex(sentences: AlignmentSentence[], focus: number | null): number {
  if (sentences.length === 0) return 0
  if (focus !== null) {
    const found = sentences.findIndex((sentence) => sentence.index === focus)
    if (found >= 0) return found
  }
  return Math.floor(sentences.length / 2)
}

function visibleReferenceSentences(result: AlignmentRefDocResult, maxRows: number): AlignmentSentence[] {
  const sentences = result.reference.sentences
  if (!Number.isFinite(maxRows) || maxRows >= sentences.length) return sentences
  const count = Math.max(1, Math.floor(maxRows))
  const center = focusIndex(sentences, result.reference.focus_sentence_index)
  let start = Math.max(0, center - Math.floor(count / 2))
  let end = Math.min(sentences.length, start + count)
  start = Math.max(0, end - count)
  return sentences.slice(start, end)
}

function tokenize(text: string): string[] {
  return text.trim().split(/\s+/).filter(Boolean)
}

function compareTokens(referenceText: string, variantText: string): DiffResult {
  const referenceRaw = tokenize(referenceText)
  const variantRaw = tokenize(variantText)
  const reference = referenceRaw.slice(0, DIFF_MAX_TOKENS)
  const variant = variantRaw.slice(0, DIFF_MAX_TOKENS)
  const truncated = reference.length !== referenceRaw.length || variant.length !== variantRaw.length
  const n = reference.length
  const m = variant.length

  if (n === 0 && m === 0) {
    return { segments: [], stats: { insert: 0, delete: 0, replace: 0, change: 0, truncated } }
  }

  const referenceLower = reference.map((token) => token.toLowerCase())
  const variantLower = variant.map((token) => token.toLowerCase())
  const costs = Array.from({ length: n + 1 }, () => Array<number>(m + 1).fill(0))
  const moves = Array.from({ length: n + 1 }, () => Array<number>(m + 1).fill(0))

  for (let i = 1; i <= n; i += 1) {
    costs[i]![0] = i
    moves[i]![0] = 1
  }
  for (let j = 1; j <= m; j += 1) {
    costs[0]![j] = j
    moves[0]![j] = 2
  }

  for (let i = 1; i <= n; i += 1) {
    for (let j = 1; j <= m; j += 1) {
      const diagonal = costs[i - 1]![j - 1]! + (referenceLower[i - 1] === variantLower[j - 1] ? 0 : 1)
      const up = costs[i - 1]![j]! + 1
      const left = costs[i]![j - 1]! + 1
      let best = diagonal
      let move = 0
      if (up < best) {
        best = up
        move = 1
      }
      if (left < best) {
        best = left
        move = 2
      }
      costs[i]![j] = best
      moves[i]![j] = move
    }
  }

  const operations: Array<{ kind: DiffKind; reference?: string; variant?: string }> = []
  let i = n
  let j = m
  while (i > 0 || j > 0) {
    const move = moves[i]![j] ?? 0
    if (i > 0 && j > 0 && move === 0) {
      operations.push({
        kind: referenceLower[i - 1] === variantLower[j - 1] ? 'equal' : 'replace',
        reference: reference[i - 1],
        variant: variant[j - 1],
      })
      i -= 1
    } else if (i > 0 && (j === 0 || move === 1)) {
      operations.push({ kind: 'delete', reference: reference[i - 1] })
      i -= 1
    } else {
      operations.push({ kind: 'insert', variant: variant[j - 1] })
      j -= 1
    }
  }

  operations.reverse()
  const segments: DiffSegment[] = []
  let insert = 0
  let remove = 0
  let replace = 0
  for (const operation of operations) {
    if (operation.kind === 'equal') {
      if (operation.variant) segments.push({ text: operation.variant, kind: 'equal' })
    } else if (operation.kind === 'insert') {
      if (operation.variant) {
        segments.push({ text: operation.variant, kind: 'insert' })
        insert += 1
      }
    } else if (operation.kind === 'delete') {
      if (operation.reference) {
        segments.push({ text: operation.reference, kind: 'delete' })
        remove += 1
      }
    } else {
      if (operation.reference) segments.push({ text: operation.reference, kind: 'delete' })
      if (operation.variant) segments.push({ text: operation.variant, kind: 'replace' })
      if (operation.reference || operation.variant) replace += 1
    }
  }

  return {
    segments,
    stats: { insert, delete: remove, replace, change: insert + remove + replace, truncated },
  }
}

function diffClass(kind: DiffKind): string {
  return `diff-token-${kind}`
}

function changeLabel(stats: DiffStats): string {
  if (stats.change === 0) return ''
  const parts: string[] = []
  if (stats.insert > 0) parts.push(`+${stats.insert}`)
  if (stats.delete > 0) parts.push(`-${stats.delete}`)
  if (stats.replace > 0) parts.push(`~${stats.replace}`)
  return parts.join(' ')
}

function slotsForVariant(
  variant: AlignmentVariant,
  visibleReferenceIndices: Set<number>,
): { pairsBySlot: Map<string, AlignmentPair>; gaps: Map<string, GapSlot> } {
  const pairsBySlot = new Map<string, AlignmentPair>()
  const gaps = new Map<string, GapSlot>()
  const nextReferences: Array<number | null> = Array.from({ length: variant.pairs.length }, () => null)
  let nextReference: number | null = null
  for (let index = variant.pairs.length - 1; index >= 0; index -= 1) {
    const pair = variant.pairs[index]!
    if (pair.ref_index !== null) nextReference = pair.ref_index
    nextReferences[index] = nextReference
  }

  let previousReference: number | null = null
  const gapOrdinals = new Map<string, number>()
  variant.pairs.forEach((pair, index) => {
    if (pair.ref_index !== null) {
      if (visibleReferenceIndices.has(pair.ref_index)) {
        pairsBySlot.set(`reference:${pair.ref_index}`, pair)
      }
      previousReference = pair.ref_index
      return
    }

    const next = nextReferences[index] ?? null
    const adjacentToVisibleReference =
      (previousReference !== null && visibleReferenceIndices.has(previousReference))
      || (next !== null && visibleReferenceIndices.has(next))
    if (!adjacentToVisibleReference) return

    const base = `gap:${previousReference ?? 'start'}:${next ?? 'end'}`
    const ordinal = gapOrdinals.get(base) ?? 0
    gapOrdinals.set(base, ordinal + 1)
    const key = `${base}:${ordinal}`
    pairsBySlot.set(key, pair)
    gaps.set(key, {
      key,
      previousReference,
      nextReference: next,
      ordinal,
    })
  })
  return { pairsBySlot, gaps }
}

function hasAlignedPair(pair: AlignmentPair | undefined): pair is AlignmentPair {
  return Boolean(pair && pair.ref_index !== null && pair.var_index !== null)
}

function cellStatus(row: ComparisonRow, cell: ComparisonCell | undefined): 'aligned' | 'variant_only' | 'reference_only' | 'outside_window' | 'empty' {
  if (!cell) return 'empty'
  if (row.kind === 'variant_only') return cell.pair && cell.pair.var_index !== null
    ? 'variant_only'
    : 'empty'
  if (!cell.pair) return 'outside_window'
  return hasAlignedPair(cell.pair) ? 'aligned' : 'reference_only'
}

const comparison = computed(() => {
  const variants = props.result.variants ?? []
  const references = visibleReferenceSentences(props.result, props.maxRows)
  const visibleReferenceIndices = new Set(references.map((sentence) => sentence.index))
  const variantSlots = variants.map((variant) => slotsForVariant(variant, visibleReferenceIndices))
  const gaps = new Map<string, GapSlot>()
  variantSlots.forEach(({ gaps: slots }) => slots.forEach((slot, key) => gaps.set(key, slot)))

  const cellsForSlot = (key: string, kind: ComparisonRow['kind'], reference?: AlignmentSentence): ComparisonCell[] =>
    variants.map((variant, variantIndex) => {
      const pair = variantSlots[variantIndex]!.pairsBySlot.get(key)
      return {
        variant,
        pair,
        diff: props.showDiff && kind === 'reference' && reference && hasAlignedPair(pair)
          ? compareTokens(reference.text, pair.var_text)
          : undefined,
      }
    })

  const beforeReference = new Map<number, GapSlot[]>()
  const afterReference = new Map<number, GapSlot[]>()
  gaps.forEach((slot) => {
    if (slot.nextReference !== null && visibleReferenceIndices.has(slot.nextReference)) {
      const entries = beforeReference.get(slot.nextReference) ?? []
      entries.push(slot)
      beforeReference.set(slot.nextReference, entries)
      return
    }
    if (slot.previousReference !== null && visibleReferenceIndices.has(slot.previousReference)) {
      const entries = afterReference.get(slot.previousReference) ?? []
      entries.push(slot)
      afterReference.set(slot.previousReference, entries)
    }
  })

  const sortGaps = (entries: GapSlot[]) => entries.sort((a, b) =>
    a.ordinal - b.ordinal || a.key.localeCompare(b.key),
  )
  const rows: ComparisonRow[] = []
  references.forEach((reference) => {
    for (const gap of sortGaps(beforeReference.get(reference.index) ?? [])) {
      rows.push({
        key: gap.key,
        kind: 'variant_only',
        cells: cellsForSlot(gap.key, 'variant_only'),
      })
    }
    const key = `reference:${reference.index}`
    rows.push({
      key,
      kind: 'reference',
      reference,
      cells: cellsForSlot(key, 'reference', reference),
    })
    for (const gap of sortGaps(afterReference.get(reference.index) ?? [])) {
      rows.push({
        key: gap.key,
        kind: 'variant_only',
        cells: cellsForSlot(gap.key, 'variant_only'),
      })
    }
  })
  return { variants, rows }
})

const focusCaveat = computed(() =>
  props.result.focus_resolution === 'variant_sentence_resolved'
    ? t('kwic.alignment.focusCaveat')
    : null,
)

const alignmentMethodNote = computed(() => {
  const threshold = props.result.confidence_threshold
  const thresholdText = threshold === undefined
    ? t('kwic.alignment.thresholdSufficient')
    : t('kwic.alignment.thresholdPercent', { value: formatNumber(threshold * 100, 0) })
  return t('kwic.alignment.methodNote', { threshold: thresholdText })
})

// A document drawer cannot usefully show every variant as a permanent column:
// the reference disappears off-screen precisely when a researcher needs it for
// comparison. Keep one selected variant beside the reference and make the
// complete variant set explicit and switchable.
const selectedVariantIndex = ref(0)
const selectedVariant = computed(() =>
  comparison.value.variants[selectedVariantIndex.value] ?? null,
)

watch(
  () => comparison.value.variants.map((variant) => variant.doc_id).join('|'),
  () => {
    if (selectedVariantIndex.value >= comparison.value.variants.length) {
      selectedVariantIndex.value = 0
    }
  },
  { immediate: true },
)

function selectedCell(row: ComparisonRow): ComparisonCell | undefined {
  return row.cells[selectedVariantIndex.value]
}

function selectedSimilarityPercent(row: ComparisonRow): number | null {
  const similarity = selectedCell(row)?.pair?.similarity
  return similarity === null || similarity === undefined ? null : similarity * 100
}

function selectedChangeLabel(row: ComparisonRow): string {
  const stats = selectedCell(row)?.diff?.stats
  return stats ? changeLabel(stats) : ''
}
</script>

<template>
  <section class="alignment-comparison" data-testid="alignment-comparison" :aria-label="t('kwic.alignment.compareAria')">
    <p v-if="!comparison.variants.length" class="alignment-empty">
      {{ t('kwic.alignment.noVariants') }}
    </p>
    <div v-else class="alignment-scroll">
      <p v-if="focusCaveat" class="alignment-caveat">{{ focusCaveat }}</p>
      <p class="alignment-caveat">{{ alignmentMethodNote }}</p>
      <div
        v-if="comparison.variants.length > 1"
        class="variant-selector"
        role="tablist"
        :aria-label="t('kwic.alignment.variantTabsAria')"
      >
        <button
          v-for="(variant, index) in comparison.variants"
          :id="`alignment-variant-tab-${variant.doc_id}`"
          :key="`variant-tab-${variant.doc_id}`"
          class="variant-selector-button"
          :class="{ active: selectedVariantIndex === index }"
          type="button"
          role="tab"
          :aria-selected="selectedVariantIndex === index"
          :aria-controls="`alignment-variant-panel-${variant.doc_id}`"
          @click="selectedVariantIndex = index"
        >
          {{ variantLabel(variant) }}
        </button>
      </div>
      <p v-if="comparison.variants.length > 1" class="variant-selector-note">
        {{ t('kwic.alignment.variantOf', { n: selectedVariantIndex + 1, total: comparison.variants.length }) }}
      </p>
      <div
        v-if="selectedVariant"
        :id="`alignment-variant-panel-${selectedVariant.doc_id}`"
        class="alignment-grid"
        role="tabpanel"
        :aria-labelledby="`alignment-variant-tab-${selectedVariant.doc_id}`"
      >
        <div class="alignment-cell alignment-header alignment-reference-header">{{ t('kwic.alignment.reference') }}</div>
        <div class="alignment-cell alignment-header alignment-variant-header">
          <div class="variant-label">{{ variantLabel(selectedVariant) }}</div>
          <div class="variant-summary">
            MED {{ formatNumber(selectedVariant.summary.avg_med) }}
            · {{ t('kwic.alignment.similarity', { value: formatNumber(selectedVariant.summary.avg_similarity === null ? null : selectedVariant.summary.avg_similarity * 100, 0) }) }}
          </div>
        </div>

        <template v-for="row in comparison.rows" :key="row.key">
          <div
            class="alignment-cell alignment-reference-cell"
            :class="{ 'alignment-reference-cell--gap': row.kind === 'variant_only' }"
          >
            <template v-if="row.kind === 'reference' && row.reference">
              <div class="sentence-index">{{ t('kwic.alignment.sentence', { n: row.reference.index }) }}</div>
              <div class="sentence-text">{{ row.reference.text }}</div>
            </template>
            <template v-else>
              <div class="sentence-index">{{ t('kwic.alignment.noReferenceMatch') }}</div>
              <div class="sentence-gap">{{ t('kwic.alignment.onlyInVariant') }}</div>
            </template>
          </div>
          <div
            class="alignment-cell alignment-variant-cell"
            :class="{
              'alignment-variant-cell--missing': cellStatus(row, selectedCell(row)) === 'reference_only',
              'alignment-variant-cell--extra': cellStatus(row, selectedCell(row)) === 'variant_only',
            }"
          >
            <div class="sentence-index">
              <template v-if="cellStatus(row, selectedCell(row)) === 'aligned' || cellStatus(row, selectedCell(row)) === 'variant_only'">
                {{ t('kwic.alignment.sentence', { n: selectedCell(row)?.pair?.var_index ?? '' }) }}
              </template>
              <template v-else-if="cellStatus(row, selectedCell(row)) === 'reference_only'">
                {{ t('kwic.alignment.noVariantMatch') }}
              </template>
              <template v-else-if="cellStatus(row, selectedCell(row)) === 'outside_window'">
                {{ t('kwic.alignment.outsideWindow') }}
              </template>
              <template v-else>—</template>
            </div>
            <div
              class="sentence-text"
              :class="{
                'sentence-text-diff': Boolean(selectedCell(row)?.diff?.stats.change),
                'sentence-text-muted': cellStatus(row, selectedCell(row)) === 'reference_only' || cellStatus(row, selectedCell(row)) === 'outside_window' || cellStatus(row, selectedCell(row)) === 'empty',
              }"
            >
              <template v-if="cellStatus(row, selectedCell(row)) === 'aligned' && Boolean(selectedCell(row)?.diff?.stats.change)">
                <span
                  v-for="(segment, index) in selectedCell(row)?.diff?.segments ?? []"
                  :key="`${row.key}-${selectedVariant.doc_id}-${index}`"
                  class="diff-token"
                  :class="diffClass(segment.kind)"
                >{{ segment.text }}</span>
              </template>
              <template v-else-if="cellStatus(row, selectedCell(row)) === 'aligned' || cellStatus(row, selectedCell(row)) === 'variant_only'">
                {{ selectedCell(row)?.pair?.var_text || '—' }}
              </template>
              <template v-else>—</template>
            </div>
            <div class="pair-metrics">
              <template v-if="cellStatus(row, selectedCell(row)) === 'aligned'">
                MED {{ formatNumber(selectedCell(row)?.pair?.med) }}
                <span v-if="selectedSimilarityPercent(row) !== null">
                · {{ t('kwic.alignment.similarity', { value: formatNumber(selectedSimilarityPercent(row), 0) }) }}
                </span>
                <span v-if="selectedChangeLabel(row)" class="change-count">
                  Δ {{ selectedChangeLabel(row) }}
                </span>
                <span v-if="selectedCell(row)?.diff?.stats.truncated" class="truncated-mark" :title="t('kwic.alignment.truncated')">…</span>
              </template>
              <template v-else-if="cellStatus(row, selectedCell(row)) === 'variant_only'">{{ t('kwic.alignment.extraSentence') }}</template>
              <template v-else-if="cellStatus(row, selectedCell(row)) === 'reference_only'">{{ t('kwic.alignment.referenceOnly') }}</template>
              <template v-else-if="cellStatus(row, selectedCell(row)) === 'outside_window'">{{ t('kwic.alignment.noCandidate') }}</template>
              <template v-else>—</template>
            </div>
          </div>
        </template>
      </div>
      <p v-if="showDiff" class="diff-legend">
        {{ t('kwic.alignment.legend') }}
      </p>
    </div>
  </section>
</template>

<style scoped>
@reference "../../style.css";

.alignment-scroll {
  @apply rounded-xl border border-neutral-200 bg-neutral-50 p-2;
  @apply dark:border-neutral-700 dark:bg-neutral-900;
}

.alignment-grid {
  @apply grid gap-2;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
}

.variant-selector {
  @apply mb-2 flex flex-wrap gap-1.5;
}

.variant-selector-button {
  @apply rounded-md border border-neutral-300 bg-white px-2.5 py-1.5 text-xs font-medium text-neutral-700;
  @apply hover:bg-neutral-100 focus:outline-none focus:ring-2 focus:ring-primary-500;
  @apply dark:border-neutral-600 dark:bg-neutral-800 dark:text-neutral-100 dark:hover:bg-neutral-700;
}

.variant-selector-button.active {
  @apply border-primary-600 bg-primary-50 text-primary-800 dark:border-primary-400 dark:bg-primary-950/30 dark:text-primary-100;
}

.variant-selector-note {
  @apply mb-2 text-xs text-neutral-600 dark:text-neutral-300;
}

.alignment-cell {
  @apply rounded-lg border border-neutral-200 bg-neutral-50 p-2.5;
  @apply dark:border-neutral-700 dark:bg-neutral-800/60;
}

.alignment-header {
  @apply bg-neutral-100 dark:bg-neutral-800;
}

.alignment-reference-header {
  @apply text-sm font-semibold text-neutral-800 dark:text-neutral-100;
}

.alignment-variant-header,
.alignment-variant-cell {
  @apply flex flex-col gap-1.5;
}

.alignment-reference-cell {
  @apply bg-white dark:bg-neutral-900;
}

.alignment-reference-cell--gap {
  @apply border-dashed bg-amber-50 dark:bg-amber-950/20;
}

.variant-label {
  @apply text-sm font-medium text-neutral-800 dark:text-neutral-100;
}

.variant-summary,
.pair-metrics {
  @apply text-xs font-mono text-neutral-600 dark:text-neutral-300;
}

.sentence-index {
  @apply text-[11px] font-mono text-neutral-500 dark:text-neutral-400;
}

.sentence-text {
  @apply text-sm text-neutral-800 dark:text-neutral-100;
  @apply whitespace-pre-wrap break-words;
}

.sentence-text-muted,
.sentence-gap {
  @apply text-neutral-500 dark:text-neutral-400 italic;
}

.alignment-variant-cell--missing {
  @apply border-dashed bg-rose-50 dark:bg-rose-950/20;
}

.alignment-variant-cell--extra {
  @apply border-dashed bg-emerald-50 dark:bg-emerald-950/20;
}

.sentence-text-diff {
  @apply flex flex-wrap items-start gap-x-1 gap-y-1;
}

.diff-token {
  @apply inline-flex items-center rounded-md border border-transparent px-1 py-0.5;
}

.diff-token-equal {
  @apply bg-transparent px-0 py-0 text-neutral-800 dark:text-neutral-100;
}

.diff-token-insert {
  @apply border-emerald-200 bg-emerald-100 text-emerald-800;
  @apply dark:border-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200;
}

.diff-token-replace {
  @apply border-amber-200 bg-amber-100 text-amber-800;
  @apply dark:border-amber-800 dark:bg-amber-900/40 dark:text-amber-200;
}

.diff-token-delete {
  @apply border-rose-200 bg-rose-50 text-rose-700 line-through;
  @apply dark:border-rose-800/60 dark:bg-rose-900/20 dark:text-rose-200;
}

.change-count {
  @apply ml-1.5 inline-flex rounded-full border border-neutral-300 bg-neutral-100 px-1.5 py-0.5 text-[10px] text-neutral-700;
  @apply dark:border-neutral-600 dark:bg-neutral-800 dark:text-neutral-200;
}

.truncated-mark {
  @apply ml-1 text-[10px] text-neutral-500 dark:text-neutral-400;
}

.diff-legend {
  @apply mt-2 px-1 text-[11px] leading-relaxed text-neutral-500 dark:text-neutral-400;
}

.alignment-empty {
  @apply rounded-lg bg-neutral-100 px-3 py-2 text-sm text-neutral-600;
  @apply dark:bg-neutral-800 dark:text-neutral-300;
}

.alignment-caveat {
  @apply mb-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-900;
  @apply dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-100;
}
</style>
