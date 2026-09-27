<script setup lang="ts">
/**
 * AnnotationSchemeEditor (F7) — edit the per-project coding scheme.
 *
 * A coding scheme is a flat list of named categories, each with a label, a
 * colour and an optional single-key keyboard shortcut. The scheme is persisted
 * via the annotations store (PUT /annotations/scheme). Rows carry at most one
 * category plus a free-text note (single-select coding, per spec).
 */
import { ref, watch, computed } from 'vue'
import { Plus, Tags, Trash2 } from 'lucide-vue-next'
import Modal from '@/components/ui/Modal.vue'
import Button from '@/components/ui/Button.vue'
import AgreementPanel from '@/components/analysis/AgreementPanel.vue'
import { useAnnotationsStore } from '@/stores'
import { useUiStore } from '@/stores/ui'
import { useProductOperationFocus } from '@/composables/useProductOperationFocus'
import type { AnnotationCategory, AnnotationSchemePreview } from '@/api/client'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

interface Props {
  modelValue: boolean
}
const props = defineProps<Props>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const annotationsStore = useAnnotationsStore()
const uiStore = useUiStore()
const { focusMatches, consumeFocusFor } = useProductOperationFocus()
const isSchemeFocused = computed(() => focusMatches('kwic.annotations.scheme'))
const isSettingsFocused = computed(() => focusMatches('kwic.annotations.settings'))
const isAgreementFocused = computed(() => focusMatches('kwic.annotations.agreement'))
consumeFocusFor([
  'kwic.annotations.scheme',
  'kwic.annotations.settings',
  'kwic.annotations.agreement',
], () => undefined)

// Active annotator name (FT-ANNOTATION-RESEARCH): attached to new/updated
// codings so multi-coder agreement can attribute rows to a coder.
const annotatorName = computed({
  get: () => annotationsStore.annotator,
  set: (value: string) => annotationsStore.setAnnotator(value),
})

const DEFAULT_COLORS = [
  '#ef4444', '#f97316', '#eab308', '#22c55e',
  '#14b8a6', '#3b82f6', '#8b5cf6', '#ec4899',
]

type DraftCategory = AnnotationCategory & { _key: string }

const draft = ref<DraftCategory[]>([])
const advancedOpen = ref(false)
const pendingRemoval = ref<AnnotationSchemePreview | null>(null)
const schemeChangedElsewhere = ref(false)

watch([isSettingsFocused, isAgreementFocused], ([settingsFocused, agreementFocused]) => {
  if (settingsFocused || agreementFocused) advancedOpen.value = true
}, { immediate: true })

function makeKey(): string {
  return `cat_${Math.random().toString(36).slice(2, 9)}`
}

function syncDraft() {
  draft.value = annotationsStore.categories.map((c, i) => ({
    ...c,
    color: c.color ?? DEFAULT_COLORS[i % DEFAULT_COLORS.length],
    shortcut: c.shortcut ?? null,
    _key: makeKey(),
  }))
  pendingRemoval.value = null
  schemeChangedElsewhere.value = false
}

async function loadLatestScheme() {
  try {
    await annotationsStore.loadScheme()
  } catch {
    uiStore.showToast(
      annotationsStore.schemeReadBlockReason ?? t('kwic.scheme.loadFailed'),
      'warning',
    )
  } finally {
    syncDraft()
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) void loadLatestScheme()
  },
  { immediate: true }
)

function addCategory() {
  if (!annotationsStore.canEditScheme) return
  const idx = draft.value.length
  draft.value.push({
    id: makeKey(),
    label: '',
    color: DEFAULT_COLORS[idx % DEFAULT_COLORS.length],
    shortcut: null,
    _key: makeKey(),
  })
}

function removeCategory(key: string) {
  if (!annotationsStore.canEditScheme) return
  draft.value = draft.value.filter((c) => c._key !== key)
}

watch(draft, () => {
  // A confirmation token is tied to the exact draft and live coding counts.
  // Any edit must force a fresh review before a destructive save is possible.
  pendingRemoval.value = null
  schemeChangedElsewhere.value = false
}, { deep: true })

function onShortcutInput(cat: DraftCategory, event: Event) {
  const value = (event.target as HTMLInputElement).value
  // Single printable character only (keyboard shortcut key).
  cat.shortcut = value ? value.slice(-1) : null
}

// Detect duplicate, case-insensitive shortcuts so two categories never collide.
const duplicateShortcuts = computed(() => {
  const seen = new Map<string, number>()
  for (const cat of draft.value) {
    if (!cat.shortcut) continue
    const key = cat.shortcut.toLowerCase()
    seen.set(key, (seen.get(key) ?? 0) + 1)
  }
  return new Set([...seen.entries()].filter(([, n]) => n > 1).map(([k]) => k))
})

const hasErrors = computed(() => {
  if (!draft.value.length) return true
  if (duplicateShortcuts.value.size > 0) return true
  return draft.value.some((c) => !c.label.trim())
})

const validationMessage = computed(() => {
  if (!draft.value.length) return t('kwic.scheme.needOne')
  if (duplicateShortcuts.value.size > 0) return t('kwic.scheme.uniqueShortcuts')
  if (draft.value.some((category) => !category.label.trim())) return t('kwic.scheme.needName')
  return null
})

function isDuplicateShortcut(cat: DraftCategory): boolean {
  return Boolean(cat.shortcut && duplicateShortcuts.value.has(cat.shortcut.toLowerCase()))
}

async function save(confirmationToken: string | null = null) {
  if (hasErrors.value) return
  const categories: AnnotationCategory[] = draft.value.map((c) => ({
    id: c.id,
    label: c.label.trim(),
    color: c.color,
    shortcut: c.shortcut ?? null,
  }))
  try {
    const result = await annotationsStore.saveScheme(categories, confirmationToken)
    if (result.status === 'confirmation_required') {
      pendingRemoval.value = result.preview
      schemeChangedElsewhere.value = false
      return
    }
    if (result.status === 'stale') {
      pendingRemoval.value = null
      schemeChangedElsewhere.value = true
      return
    }
    uiStore.showToast(t('kwic.scheme.saved'), 'success')
    emit('update:modelValue', false)
  } catch {
    uiStore.showToast(t('kwic.scheme.saveFailed'), 'error')
  }
}

function confirmRemoval() {
  if (!pendingRemoval.value?.confirmationToken) return
  void save(pendingRemoval.value.confirmationToken)
}

function close() {
  emit('update:modelValue', false)
}

function onAdvancedToggle(event: Event) {
  advancedOpen.value = (event.currentTarget as HTMLDetailsElement).open
}
</script>

<template>
  <Modal
    :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)"
    :title="t('kwic.scheme.title')"
    :description="t('kwic.scheme.description')"
    size="lg"
  >
    <div class="scheme-editor">
      <p v-if="!annotationsStore.canEditScheme" class="scheme-warn">
        {{ annotationsStore.schemeWriteBlockReason ?? t('kwic.scheme.readOnly') }}
      </p>

      <p class="scheme-scope-note">
        {{ t('kwic.scheme.scopeNote') }}
      </p>

      <div
        v-if="!draft.length"
        class="scheme-empty"
        :class="{ 'surface-focus': isSchemeFocused }"
      >
        <Tags class="w-8 h-8 text-neutral-400" />
        <p>{{ t('kwic.scheme.empty') }}</p>
      </div>
      <p v-if="!draft.length" class="scheme-warn" role="alert">
        {{ t('kwic.scheme.needOne') }}
      </p>

      <ul v-else class="category-list" :class="{ 'surface-focus': isSchemeFocused }">
        <li v-for="cat in draft" :key="cat._key" class="category-row">
          <label class="sr-only" :for="`code-color-${cat._key}`">
            {{ t('kwic.scheme.colorFor', { name: cat.label.trim() || t('kwic.scheme.unnamedCode') }) }}
          </label>
          <input
            :id="`code-color-${cat._key}`"
            v-model="cat.color"
            type="color"
            class="color-swatch"
            :disabled="!annotationsStore.canEditScheme"
          />
          <label class="sr-only" :for="`code-label-${cat._key}`">
            {{ t('kwic.scheme.codeName') }}
          </label>
          <input
            :id="`code-label-${cat._key}`"
            v-model="cat.label"
            type="text"
            class="label-input"
            :placeholder="t('kwic.scheme.codePlaceholder')"
            :disabled="!annotationsStore.canEditScheme"
          />
          <div class="shortcut-field">
            <label class="shortcut-hint" :for="`code-shortcut-${cat._key}`">{{ t('kwic.scheme.key') }}</label>
            <input
              :id="`code-shortcut-${cat._key}`"
              :value="cat.shortcut ?? ''"
              type="text"
              maxlength="1"
              class="shortcut-input"
              :class="{ 'is-dup': isDuplicateShortcut(cat) }"
              placeholder="–"
              :title="isDuplicateShortcut(cat) ? t('kwic.scheme.duplicateShortcut') : t('kwic.scheme.optionalShortcut')"
              :aria-invalid="isDuplicateShortcut(cat) ? 'true' : undefined"
              :aria-describedby="isDuplicateShortcut(cat) ? `shortcut-error-${cat._key}` : undefined"
              :disabled="!annotationsStore.canEditScheme"
              @input="onShortcutInput(cat, $event)"
            />
            <span
              v-if="isDuplicateShortcut(cat)"
              :id="`shortcut-error-${cat._key}`"
              class="sr-only"
            >
              {{ t('kwic.scheme.duplicateShortcutLong') }}
            </span>
          </div>
          <button
            class="remove-btn"
            type="button"
            :title="cat.label.trim() ? t('kwic.scheme.removeNamed', { name: cat.label.trim() }) : t('kwic.scheme.removeUnnamed')"
            :aria-label="cat.label.trim() ? t('kwic.scheme.removeNamed', { name: cat.label.trim() }) : t('kwic.scheme.removeUnnamed')"
            :disabled="!annotationsStore.canEditScheme"
            @click="removeCategory(cat._key)"
          >
            <Trash2 class="w-4 h-4" />
          </button>
        </li>
      </ul>

      <button
        class="add-btn"
        type="button"
        :disabled="!annotationsStore.canEditScheme"
        @click="addCategory"
      >
        <Plus class="w-4 h-4" />
        {{ t('kwic.scheme.addCode') }}
      </button>

      <p v-if="duplicateShortcuts.size > 0" class="scheme-warn">
        {{ t('kwic.scheme.uniqueShortcuts') }}
      </p>

      <section v-if="pendingRemoval" class="scheme-impact" role="alert" aria-live="assertive">
        <h3>{{ t('kwic.scheme.impactTitle') }}</h3>
        <p>
          {{ t('kwic.scheme.impactText') }}
        </p>
        <ul>
          <li v-for="removal in pendingRemoval.removals" :key="removal.categoryId">
            <strong>{{ removal.label }}</strong>: {{ t('kwic.scheme.impactCounts', { annotations: removal.annotationCount, corpora: removal.corpusCount, coders: removal.annotatorCount }) }}
          </li>
        </ul>
        <p class="scheme-impact-hint">
          {{ t('kwic.scheme.renameHint') }}
        </p>
        <div class="scheme-impact-actions">
          <Button variant="danger" size="sm" :loading="annotationsStore.isSavingScheme" @click="confirmRemoval">
            {{ t('kwic.scheme.removeAndSave') }}
          </Button>
          <Button variant="ghost" size="sm" @click="pendingRemoval = null">{{ t('kwic.scheme.editDraft') }}</Button>
        </div>
      </section>

      <section v-if="schemeChangedElsewhere" class="scheme-stale" role="status">
        {{ t('kwic.scheme.changedElsewhere') }}
        <Button variant="secondary" size="sm" @click="loadLatestScheme">{{ t('kwic.scheme.loadLatest') }}</Button>
      </section>

      <details
        class="advanced-coding"
        :open="advancedOpen"
        @toggle="onAdvancedToggle"
      >
        <summary>{{ t('kwic.scheme.advanced') }}</summary>
        <div class="advanced-coding-content">
          <div class="coder-field" :class="{ 'surface-focus': isSettingsFocused }">
            <label class="coder-label" for="annotator-name">{{ t('kwic.scheme.coderName') }}</label>
            <input
              id="annotator-name"
              v-model="annotatorName"
              type="text"
              class="coder-input"
              :placeholder="t('kwic.scheme.coderPlaceholder')"
            />
          </div>

          <AgreementPanel
            v-if="advancedOpen"
            class="agreement-section"
            :class="{ 'surface-focus': isAgreementFocused }"
          />
        </div>
      </details>
    </div>

    <template #footer>
      <Button variant="ghost" @click="close">{{ t('kwic.scheme.cancel') }}</Button>
      <Button
        variant="primary"
        :loading="annotationsStore.isSavingScheme"
        :disabled="hasErrors || !annotationsStore.canEditScheme"
        :title="validationMessage ?? annotationsStore.schemeWriteBlockReason ?? t('kwic.scheme.saveCodes')"
        @click="() => void save()"
      >
        {{ t('kwic.scheme.save') }}
      </Button>
    </template>
  </Modal>
</template>

<style scoped>
@reference "../../style.css";

.scheme-editor {
  @apply space-y-4;
}

.surface-focus {
  @apply ring-2 ring-primary-500/70 ring-offset-2 ring-offset-white dark:ring-offset-neutral-950;
}

.scheme-empty {
  @apply flex flex-col items-center gap-3 py-8 text-center;
  @apply text-sm text-neutral-500 dark:text-neutral-400;
}

.category-list {
  @apply space-y-2;
}

.category-row {
  @apply flex items-center gap-3;
}

.color-swatch {
  @apply w-9 h-9 rounded-lg border border-neutral-300 dark:border-neutral-600 cursor-pointer flex-shrink-0;
  background: transparent;
  padding: 2px;
}

.label-input {
  @apply flex-1 px-3 py-2 rounded-lg text-sm;
  @apply bg-white dark:bg-neutral-900;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply focus:ring-2 focus:ring-primary-500 focus:outline-none;
}

.shortcut-field {
  @apply flex items-center gap-1.5 flex-shrink-0;
}

.shortcut-hint {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.shortcut-input {
  @apply w-10 px-2 py-2 rounded-lg text-sm text-center uppercase;
  @apply bg-white dark:bg-neutral-900;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply focus:ring-2 focus:ring-primary-500 focus:outline-none;
}

.shortcut-input.is-dup {
  @apply border-error-500 ring-1 ring-error-500;
}

.remove-btn {
  @apply p-2 rounded-lg flex-shrink-0;
  @apply text-neutral-400 hover:text-error-500;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
  @apply transition-colors;
}

.add-btn {
  @apply inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium;
  @apply text-copilot-primary;
  @apply bg-copilot-bg hover:bg-copilot-primary hover:text-white;
  @apply transition-colors;
}

.scheme-warn {
  @apply text-xs text-error-500;
}

.scheme-scope-note {
  @apply rounded-lg border border-primary-200 bg-primary-50 px-3 py-2 text-xs leading-relaxed text-primary-800;
  @apply dark:border-primary-900/60 dark:bg-primary-950/30 dark:text-primary-200;
}

.scheme-impact {
  @apply rounded-lg border border-error-300 bg-error-50 p-3 text-sm text-error-900;
  @apply dark:border-error-900/70 dark:bg-error-900/30 dark:text-error-100;
}

.scheme-impact h3 {
  @apply font-semibold;
}

.scheme-impact p {
  @apply mt-1 leading-relaxed;
}

.scheme-impact ul {
  @apply mt-2 list-disc space-y-1 pl-5 text-xs;
}

.scheme-impact-hint {
  @apply text-xs;
}

.scheme-impact-actions {
  @apply mt-3 flex flex-wrap gap-2;
}

.scheme-stale {
  @apply flex flex-wrap items-center gap-2 rounded-lg border border-warning-300 bg-warning-50 px-3 py-2 text-xs text-warning-900;
  @apply dark:border-warning-900/70 dark:bg-warning-900/30 dark:text-warning-100;
}

.advanced-coding {
  @apply rounded-lg border border-neutral-200 bg-neutral-50;
  @apply dark:border-neutral-700 dark:bg-neutral-900/50;
}

.advanced-coding summary {
  @apply cursor-pointer px-3 py-2 text-sm font-medium text-neutral-700;
  @apply dark:text-neutral-200;
}

.advanced-coding-content {
  @apply border-t border-neutral-200 px-3 pb-3;
  @apply dark:border-neutral-700;
}

.coder-field {
  @apply flex flex-col gap-1 pt-3 mt-2;
  @apply border-t border-neutral-200 dark:border-neutral-700;
}

.coder-label {
  @apply text-xs font-medium text-neutral-500 dark:text-neutral-400;
}

.coder-input {
  @apply px-2.5 py-1.5 rounded-md text-sm;
  @apply bg-white dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-neutral-900 dark:text-neutral-100;
  @apply focus:outline-none focus:ring-2 focus:ring-primary-500;
}

.agreement-section {
  @apply mt-3;
}
</style>
