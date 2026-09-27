<script setup lang="ts">
/**
 * DocumentSearchRenderer - Displays ranked documents or documentation hits
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { FileText, ExternalLink } from 'lucide-vue-next'
import { actionBus } from '@/actions'
import { useUiStore } from '@/stores'
import { formatNumber, formatPercent } from '@/i18n/format'

interface DocumentRow {
  doc_id?: string | number
  docId?: string | number
  id?: string | number
  title?: string
  file?: string
  snippet?: string
  score?: number
}

interface Props {
  data: DocumentRow[] | { rows?: DocumentRow[] }
  limit?: number
}

const props = withDefaults(defineProps<Props>(), {
  limit: 8
})

const uiStore = useUiStore()
const { t } = useI18n()

const rows = computed<DocumentRow[]>(() => {
  if (Array.isArray(props.data)) return props.data
  return props.data.rows ?? []
})

const displayRows = computed(() => rows.value.slice(0, props.limit))

function labelForRow(row: DocumentRow): string {
  return row.title || row.file || (row.doc_id === undefined ? '' : String(row.doc_id)) || t('copilot.renderers.documentFallback')
}

function docIdForRow(row: DocumentRow): string {
  const raw = row.doc_id ?? row.docId ?? row.id
  return raw === undefined || raw === null ? '' : String(raw)
}

async function openDocument(row: DocumentRow): Promise<void> {
  const docId = docIdForRow(row)
  if (!docId) return
  const result = await actionBus.dispatch({
    type: 'nav/openDocument',
    payload: { docId, fallbackLabel: labelForRow(row) },
  }, { source: 'copilot' })
  if (!result.success) {
    uiStore.showToast(result.error ?? t('copilot.renderers.documentOpenFailed'), 'warning')
  }
}
</script>

<template>
  <div class="document-renderer">
    <div class="renderer-header">
      <FileText class="w-4 h-4 text-primary-500" />
      <span class="font-medium">{{ t('copilot.renderers.documentsTitle') }}</span>
      <span class="text-xs text-neutral-500">
        {{ t('copilot.renderers.hits', { count: formatNumber(rows.length) }, rows.length) }}
      </span>
    </div>

    <div class="document-list">
      <button
        v-for="(row, idx) in displayRows"
        :key="`${labelForRow(row)}-${idx}`"
        type="button"
        class="document-item"
        :disabled="!docIdForRow(row)"
        :title="docIdForRow(row) ? t('copilot.renderers.documentOpen') : t('copilot.renderers.documentNoId')"
        @click="openDocument(row)"
      >
        <div class="item-header">
          <ExternalLink
            class="w-3.5 h-3.5"
            :class="docIdForRow(row) ? 'text-primary-500' : 'text-neutral-400'"
          />
          <span class="item-title">{{ labelForRow(row) }}</span>
          <span v-if="typeof row.score === 'number'" class="item-score">
            {{ formatPercent(row.score, 0) }}
          </span>
        </div>
        <p v-if="row.snippet" class="item-snippet">
          {{ row.snippet }}
        </p>
      </button>
    </div>
  </div>
</template>

<style scoped>
@reference "../../../style.css";

.document-renderer {
  @apply rounded-lg border border-neutral-200 dark:border-neutral-700;
  @apply bg-white dark:bg-neutral-900;
  @apply overflow-hidden;
}

.renderer-header {
  @apply flex items-center gap-2 px-3 py-2;
  @apply border-b border-neutral-200 dark:border-neutral-700;
  @apply bg-neutral-50 dark:bg-neutral-800;
}

.document-list {
  @apply p-3 space-y-2 max-h-80 overflow-y-auto;
}

.document-item {
  @apply p-3 rounded-lg;
  @apply bg-neutral-50 dark:bg-neutral-800;
  @apply border border-transparent;
  @apply hover:border-primary-300 dark:hover:border-primary-700;
  @apply transition-colors;
  @apply block w-full text-left;
}

.document-item:disabled {
  @apply cursor-default opacity-75 hover:border-transparent;
}

.item-header {
  @apply flex items-center gap-2;
}

.item-title {
  @apply flex-1 text-sm font-medium text-neutral-900 dark:text-neutral-100 truncate;
}

.item-score {
  @apply text-xs font-mono text-primary-600 dark:text-primary-400;
}

.item-snippet {
  @apply mt-1 text-sm text-neutral-600 dark:text-neutral-300 leading-relaxed;
}
</style>
