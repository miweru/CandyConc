<script setup lang="ts">
/**
 * Presentation-only CQL preview and submit row.
 * The explicit preview prop keeps this component independent of the retired
 * query-builder workspace scope.
 */
import { Code2 } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import Button from '@/components/ui/Button.vue'

defineProps<{
  previewCql: string
}>()

const emit = defineEmits<{
  (event: 'submit'): void
}>()

const { t } = useI18n()
</script>

<template>
  <div>
    <div class="cql-preview">
      <div class="preview-header">
        <Code2 class="w-4 h-4" />
        <span>{{ t('querybuilder.preview.title') }}</span>
      </div>
      <code class="preview-code">{{ previewCql || t('querybuilder.common.empty') }}</code>
    </div>

    <div class="submit-row">
      <Button variant="primary" @click="emit('submit')" :disabled="!previewCql">
        {{ t('querybuilder.preview.submit') }}
      </Button>
    </div>
  </div>
</template>

<style scoped>
@reference "../../../../style.css";

.cql-preview {
  @apply rounded-xl border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900/80 p-4 space-y-3;
}

.preview-header {
  @apply flex items-center gap-2;
}

.preview-header span {
  @apply text-sm font-semibold text-neutral-900 dark:text-neutral-100;
}

.preview-code {
  @apply block rounded-lg bg-neutral-950 text-emerald-300 p-4 text-sm leading-6 overflow-x-auto;
}

.submit-row {
  @apply flex justify-end;
}

@media (max-width: 960px) {
  .preview-code {
    white-space: pre-wrap;
    word-break: break-word;
  }
}
</style>
