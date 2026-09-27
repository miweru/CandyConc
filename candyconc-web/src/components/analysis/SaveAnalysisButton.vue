<script setup lang="ts">
/**
 * SaveAnalysisButton - Save current analysis config as preset
 */
import { ref, useId } from 'vue'
import Button from '@/components/ui/Button.vue'
import Modal from '@/components/ui/Modal.vue'
import { useAnalysisPresetsStore, useUiStore, type AnalysisType } from '@/stores'
import { Save } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'

interface Props {
  type: AnalysisType
  defaultName: string
  corpus: string
  docset: Record<string, unknown> | null
  queryTerm?: string
  params: Record<string, unknown>
  result?: unknown
  resultMeta?: Record<string, unknown>
  disabled?: boolean
  disabledReason?: string
}

const props = defineProps<Props>()
const { t } = useI18n()
const presetsStore = useAnalysisPresetsStore()
const uiStore = useUiStore()

const open = ref(false)
const nameInputId = useId()
const nameDraft = ref(props.defaultName)
const isSaving = ref(false)

function openModal() {
  if (props.disabled) return
  nameDraft.value = props.defaultName
  open.value = true
}

async function save() {
  if (props.disabled || isSaving.value) return
  isSaving.value = true
  try {
    let resultMeta = props.resultMeta
    if (props.result) {
      const cacheKey = await presetsStore.buildCacheKey({
        type: props.type,
        corpus: props.corpus,
        docset: props.docset as any,
        queryTerm: props.queryTerm,
        params: props.params,
      })
      resultMeta = {
        ...(props.resultMeta ?? {}),
        cacheKey,
        cacheVersion: presetsStore.cacheVersion,
      }
    }
    const preset = presetsStore.createPreset({
      name: nameDraft.value.trim() || props.defaultName,
      type: props.type,
      corpus: props.corpus,
      docset: props.docset as any,
      queryTerm: props.queryTerm,
      params: props.params,
      result: props.result,
      resultMeta,
    })
    await presetsStore.add(preset)
    open.value = false
    uiStore.showToast(t('analysis.saveAnalysis.saved'), 'success', 2000)
  } catch (err) {
    const message = err instanceof Error ? err.message : t('analysis.saveAnalysis.failed')
    uiStore.showToast(message, 'error')
  } finally {
    isSaving.value = false
  }
}
</script>

<template>
  <Button
    variant="ghost"
    size="sm"
    :icon="Save"
    :disabled="disabled"
    :title="disabledReason"
    @click="openModal"
  >
    {{ t('analysis.saveAnalysis.save') }}
  </Button>

  <Modal v-model="open" :title="t('analysis.saveAnalysis.title')">
    <div class="save-modal">
      <label class="save-label" :for="nameInputId">{{ t('analysis.saveAnalysis.name') }}</label>
      <input :id="nameInputId" v-model="nameDraft" class="save-input" type="text" />
      <div class="save-actions">
        <Button variant="ghost" size="sm" @click="open = false">{{ t('analysis.saveAnalysis.cancel') }}</Button>
        <Button variant="primary" size="sm" :loading="isSaving" @click="save">{{ t('analysis.saveAnalysis.save') }}</Button>
      </div>
    </div>
  </Modal>
</template>

<style scoped>
@reference "../../style.css";

.save-modal {
  @apply flex flex-col gap-3;
}

.save-label {
  @apply text-xs font-medium text-neutral-600 dark:text-neutral-400;
}

.save-input {
  @apply w-full px-3 py-2 rounded-lg text-sm;
  @apply bg-white dark:bg-neutral-900;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply focus:ring-2 focus:ring-primary-500 focus:outline-none;
}

.save-actions {
  @apply flex items-center justify-end gap-2;
}
</style>
