<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertTriangle, Filter, RotateCcw } from 'lucide-vue-next'
import FilterField from '@/components/filters/FilterField.vue'
import FilterSpecChips from '@/components/filters/FilterSpecChips.vue'
import type { FilterSpec, FilterSpecValue } from '@/api/client'
import type { MetaFieldDescriptor } from '@/stores/docset'

const props = withDefaults(defineProps<{
  modelValue?: FilterSpec | null
  enumFields: MetaFieldDescriptor[]
  rangeFields: MetaFieldDescriptor[]
  textFields?: MetaFieldDescriptor[]
  enumOptions: Record<string, string[]>
  loading?: boolean
  error?: string | null
  canLoadMetadata?: boolean
  metadataBlockReason?: string | null
  canApply?: boolean
  applyBlockReason?: string | null
  isApplying?: boolean
  title?: string
  hint?: string
  emptyLabel?: string
  applyLabel?: string
}>(), {
  textFields: () => [],
  loading: false,
  error: null,
  canLoadMetadata: true,
  metadataBlockReason: null,
  canApply: true,
  applyBlockReason: null,
  isApplying: false,
  title: undefined,
  hint: undefined,
  emptyLabel: undefined,
  applyLabel: undefined,
})

const { t } = useI18n()
const fieldIdBase = useId()
const fieldId = (kind: string, name: string) => `${fieldIdBase}-${kind}-${name.replace(/[^A-Za-z0-9_-]/g, '_')}`
const titleText = computed(() => props.title ?? t('subcorpus.generic.title'))
const hintText = computed(() => props.hint ?? t('subcorpus.generic.hint'))
const emptyText = computed(() => props.emptyLabel ?? t('subcorpus.generic.empty'))
const applyText = computed(() => props.applyLabel ?? t('subcorpus.generic.apply'))

const emit = defineEmits<{
  'update:modelValue': [value: FilterSpec]
  apply: []
  reset: []
}>()

const enumSelection = ref<Record<string, string[]>>({})
const rangeSelection = ref<Record<string, { lo: string; hi: string }>>({})
const textSelection = ref<Record<string, string>>({})

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function selectionFromSpec(spec: FilterSpec | null | undefined) {
  const enums: Record<string, string[]> = {}
  const ranges: Record<string, { lo: string; hi: string }> = {}
  const texts: Record<string, string> = {}
  const enumNames = new Set(props.enumFields.map((field) => field.name))
  const rangeNames = new Set(props.rangeFields.map((field) => field.name))
  const textNames = new Set(props.textFields.map((field) => field.name))
  for (const [field, value] of Object.entries(spec ?? {})) {
    if (enumNames.has(field)) {
      if (Array.isArray(value)) enums[field] = value.map((item) => String(item))
      else if (!isRecord(value)) enums[field] = [String(value)]
      continue
    }
    if (rangeNames.has(field) && isRecord(value)) {
      if (value.op === 'between') {
        ranges[field] = { lo: value.lo === undefined ? '' : String(value.lo), hi: value.hi === undefined ? '' : String(value.hi) }
      } else if (value.op === '>=' || value.op === '>') {
        ranges[field] = { lo: value.value === undefined ? '' : String(value.value), hi: '' }
      } else if (value.op === '<=') {
        ranges[field] = { lo: '', hi: value.value === undefined ? '' : String(value.value) }
      } else if (value.op === '=') {
        const exact = value.value === undefined ? '' : String(value.value)
        ranges[field] = { lo: exact, hi: exact }
      }
      continue
    }
    if (textNames.has(field)) {
      if (Array.isArray(value)) texts[field] = value.map((item) => String(item)).join(', ')
      else if (!isRecord(value)) texts[field] = String(value)
    }
  }
  for (const field of props.enumFields) {
    if (!enums[field.name]) enums[field.name] = []
  }
  enumSelection.value = enums
  rangeSelection.value = ranges
  textSelection.value = texts
}

function coerce(field: MetaFieldDescriptor, value: string): string | number {
  if (field.kind === 'number') {
    const num = Number(value)
    return Number.isFinite(num) ? num : value
  }
  return value
}

function rangeFor(field: string): { lo: string; hi: string } {
  if (!rangeSelection.value[field]) {
    rangeSelection.value[field] = { lo: '', hi: '' }
  }
  return rangeSelection.value[field]
}

function exactValues(value: string): string[] {
  return Array.from(new Set(
    value
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean),
  ))
}

function buildSpec(): FilterSpec {
  const spec: FilterSpec = {}
  for (const field of props.enumFields) {
    const selected = enumSelection.value[field.name]
    if (selected?.length) spec[field.name] = [...selected]
  }
  for (const field of props.rangeFields) {
    const range = rangeSelection.value[field.name]
    if (!range) continue
    const lo = range.lo.trim()
    const hi = range.hi.trim()
    if (lo && hi) {
      spec[field.name] = { op: 'between', lo: coerce(field, lo), hi: coerce(field, hi) } satisfies FilterSpecValue
    } else if (lo) {
      spec[field.name] = { op: '>=', value: coerce(field, lo) } satisfies FilterSpecValue
    } else if (hi) {
      spec[field.name] = { op: '<=', value: coerce(field, hi) } satisfies FilterSpecValue
    }
  }
  for (const field of props.textFields) {
    const values = exactValues(textSelection.value[field.name] ?? '')
    if (values.length) spec[field.name] = values
  }
  return spec
}

const currentSpec = computed(() => buildSpec())
const hasFields = computed(() =>
  props.enumFields.length > 0 || props.rangeFields.length > 0 || props.textFields.length > 0
)
const hasTextFields = computed(() => props.textFields.length > 0)
const hasTextSelection = computed(() =>
  props.textFields.some((field) => exactValues(textSelection.value[field.name] ?? '').length > 0)
)
const hasFilters = computed(() => Object.keys(currentSpec.value).length > 0)
const applyDisabled = computed(() => props.isApplying || !hasFilters.value || !props.canApply)
const applyTitle = computed(() => props.canApply ? applyText.value : props.applyBlockReason ?? t('subcorpus.generic.applyBlocked'))

function sameSpec(a: FilterSpec | null | undefined, b: FilterSpec | null | undefined): boolean {
  return JSON.stringify(a ?? {}) === JSON.stringify(b ?? {})
}

watch(
  () => [props.modelValue, props.enumFields, props.rangeFields, props.textFields] as const,
  () => selectionFromSpec(props.modelValue),
  { immediate: true, deep: true },
)

watch(
  [enumSelection, rangeSelection, textSelection],
  () => {
    const spec = buildSpec()
    if (!sameSpec(spec, props.modelValue)) emit('update:modelValue', spec)
  },
  { deep: true },
)

function reset() {
  enumSelection.value = {}
  rangeSelection.value = {}
  textSelection.value = {}
  emit('update:modelValue', {})
  emit('reset')
}
</script>

<template>
  <section class="generic-filter-panel">
    <div class="generic-filter-head">
      <div>
        <div class="generic-filter-title">{{ titleText }}</div>
        <p class="generic-filter-hint">{{ hintText }}</p>
      </div>
      <FilterSpecChips :spec="currentSpec" :empty-label="t('subcorpus.generic.noneSelected')" dense />
    </div>

    <div v-if="error" class="generic-filter-error">{{ error }}</div>
    <div v-if="!canLoadMetadata" class="generic-filter-warning">
      <AlertTriangle class="w-4 h-4" />
      <span>{{ metadataBlockReason ?? t('subcorpus.generic.valuesBlocked') }}</span>
    </div>
    <div v-if="loading" class="generic-filter-note">{{ t('subcorpus.generic.loadingOptions') }}</div>
    <div v-if="!hasFields && !loading" class="generic-filter-note">{{ emptyText }}</div>

    <div v-if="hasFields" class="generic-filter-grid">
      <FilterField
        v-for="field in enumFields"
        :key="field.name"
        :label="field.name"
        :label-for="fieldId('enum', field.name)"
      >
        <select
          :id="fieldId('enum', field.name)"
          v-model="enumSelection[field.name]"
          class="generic-select"
          multiple
          size="6"
          :disabled="loading || !canLoadMetadata"
        >
          <option v-for="opt in enumOptions[field.name] ?? []" :key="opt" :value="opt" :title="opt">
            {{ opt }}
          </option>
        </select>
      </FilterField>

      <FilterField
        v-for="field in rangeFields"
        :key="field.name"
        :label="t('subcorpus.generic.rangeLabel', { field: field.name })"
      >
        <div class="range-row">
          <input
            v-model="rangeFor(field.name).lo"
            class="range-input"
            :type="field.kind === 'number' ? 'number' : 'text'"
            :placeholder="field.kind === 'date' ? t('subcorpus.generic.dateFrom') : t('subcorpus.generic.min')"
          />
          <span class="range-sep">–</span>
          <input
            v-model="rangeFor(field.name).hi"
            class="range-input"
            :type="field.kind === 'number' ? 'number' : 'text'"
            :placeholder="field.kind === 'date' ? t('subcorpus.generic.dateTo') : t('subcorpus.generic.max')"
          />
        </div>
      </FilterField>
    </div>

    <details v-if="hasTextFields" class="exact-filter-details" :open="hasTextSelection">
      <summary>{{ t('subcorpus.generic.exactSummary') }}</summary>
      <p>{{ t('subcorpus.generic.exactHelp') }}</p>
      <div class="generic-filter-grid exact-filter-grid">
        <FilterField
          v-for="field in textFields"
          :key="field.name"
          :label="field.name"
          :label-for="fieldId('text', field.name)"
        >
          <input
            :id="fieldId('text', field.name)"
            v-model="textSelection[field.name]"
            class="exact-input"
            type="text"
            :placeholder="t('subcorpus.generic.exactPlaceholder')"
            :disabled="!canApply"
          />
        </FilterField>
      </div>
    </details>

    <div class="generic-actions">
      <button
        class="generic-btn"
        type="button"
        :disabled="applyDisabled"
        :title="applyTitle"
        @click="emit('apply')"
      >
        <Filter class="w-4 h-4" />
        <span>{{ applyText }}</span>
      </button>
      <button class="generic-btn generic-btn-ghost" type="button" @click="reset">
        <RotateCcw class="w-4 h-4" />
        <span>{{ t('subcorpus.generic.reset') }}</span>
      </button>
    </div>
  </section>
</template>

<style scoped>
@reference "../../style.css";

.generic-filter-panel {
  @apply flex flex-col gap-3 rounded-xl border border-neutral-200 bg-neutral-50/70 p-3;
  @apply dark:border-neutral-800 dark:bg-neutral-950/40;
}

.generic-filter-head {
  @apply flex flex-col gap-2 md:flex-row md:items-start md:justify-between;
}

.generic-filter-title {
  @apply text-sm font-semibold text-neutral-800 dark:text-neutral-100;
}

.generic-filter-hint,
.generic-filter-note {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.generic-filter-error {
  @apply text-sm text-error-600 dark:text-error-400;
}

.generic-filter-warning {
  @apply flex items-center gap-2 text-sm text-amber-700 dark:text-amber-300;
}

.generic-filter-grid {
  /* Columns follow the width of the panel, not of the window: in the 512 px
     filter panel three columns cut names such as "Dwight D. Eisenhower". */
  @apply grid gap-3;
  grid-template-columns: repeat(auto-fill, minmax(13rem, 1fr));
}

.generic-select,
.range-input,
.exact-input {
  @apply rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm text-neutral-800;
  @apply dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100;
}

.generic-select {
  @apply min-h-32;
}

.range-row {
  @apply flex items-center gap-2;
}

.range-input {
  @apply min-w-0 flex-1;
}

.range-sep {
  @apply text-neutral-400;
}

.exact-filter-details {
  @apply rounded-lg border border-neutral-200 bg-white/60 px-3 py-2 text-sm;
  @apply dark:border-neutral-800 dark:bg-neutral-900/30;
}

.exact-filter-details summary {
  @apply cursor-pointer font-medium text-neutral-700 dark:text-neutral-200;
}

.exact-filter-details p {
  @apply mt-2 text-xs text-neutral-500 dark:text-neutral-400;
}

.exact-filter-grid {
  @apply mt-3;
}

.exact-input {
  @apply w-full;
}

.generic-actions {
  @apply flex flex-wrap gap-2;
}

.generic-btn {
  @apply inline-flex items-center gap-2 rounded-lg bg-primary-600 px-3 py-2 text-sm font-medium text-white;
  @apply hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50;
}

.generic-btn-ghost {
  @apply bg-transparent text-neutral-600 hover:bg-neutral-100 dark:text-neutral-300 dark:hover:bg-neutral-800;
}
</style>
