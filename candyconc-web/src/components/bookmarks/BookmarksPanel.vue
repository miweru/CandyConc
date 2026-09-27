<script setup lang="ts">
/**
 * BookmarksPanel - Slide-over panel for managing bookmarks
 */
import { ref, computed, onMounted } from 'vue'
import { Bookmark, Plus, Trash2, Clock, Search } from 'lucide-vue-next'
import SlideOver from '@/components/ui/SlideOver.vue'
import Button from '@/components/ui/Button.vue'
import { useBookmarksStore, type Bookmark as BookmarkType } from '@/stores/bookmarks'
import { useQueryStore } from '@/stores/query'
import { asSwitchTabId, useUiStore } from '@/stores/ui'
import { useHistoryStore } from '@/stores/history'
import { useSettingsStore } from '@/stores/settings'
import { useDispatch } from '@/composables'
import { formatDate as formatLocaleDate } from '@/i18n/format'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

interface Props {
  modelValue: boolean
}

defineProps<Props>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const bookmarksStore = useBookmarksStore()
const queryStore = useQueryStore()
const uiStore = useUiStore()
const historyStore = useHistoryStore()
const { dispatch } = useDispatch()

const searchQuery = ref('')
const newBookmarkName = ref('')
const showAddForm = ref(false)

const filteredBookmarks = computed(() => {
  if (!searchQuery.value.trim()) {
    return bookmarksStore.sortedBookmarks
  }
  const q = searchQuery.value.toLowerCase()
  return bookmarksStore.sortedBookmarks.filter(b =>
    b.name.toLowerCase().includes(q) || b.query.toLowerCase().includes(q)
  )
})

const canAddBookmark = computed(() =>
  queryStore.term && newBookmarkName.value.trim()
)

function formatDate(timestamp: number): string {
  return formatLocaleDate(timestamp, {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

async function handleAddBookmark() {
  if (!canAddBookmark.value) return

  const result = await dispatch({
    type: 'bookmark/add',
    payload: {
      label: newBookmarkName.value.trim(),
      positions: Array.from(queryStore.selectedRows),
    },
  }, { source: 'user' })
  if (!result.success) {
    uiStore.showToast(result.error ?? t('kwic.bookmarks.saveFailed'), result.blocked ? 'warning' : 'error')
    return
  }

  newBookmarkName.value = ''
  showAddForm.value = false
}

async function handleRestore(bookmark: BookmarkType) {
  historyStore.pushState()
  historyStore.setRestoring(true)

  try {
    await dispatch({ type: 'nav/switchTab', payload: { tab: asSwitchTabId(bookmark.tab) } }, { source: 'restore' })
    await dispatch({
      type: 'query/execute',
      payload: {
        term: bookmark.query,
        contextSize: queryStore.contextSize
      }
    }, { source: 'restore', requestId: `bookmark-restore:${bookmark.id}` })

    queryStore.setSelectedRows(bookmark.selectedRows)
    queryStore.setHighlightedRow(bookmark.selectedRows[0] ?? null)

    uiStore.showToast(t('kwic.bookmarks.restored', { name: bookmark.name }), 'info')
    emit('update:modelValue', false)
  } finally {
    historyStore.setRestoring(false)
  }
}

async function handleDelete(bookmark: BookmarkType) {
  if (!useSettingsStore().confirmDeletion(bookmark.name)) return
  const result = await dispatch({
    type: 'bookmark/remove',
    payload: { id: bookmark.id },
  }, { source: 'user' })
  if (!result.success) {
    uiStore.showToast(result.error ?? t('kwic.bookmarks.deleteFailed'), result.blocked ? 'warning' : 'error')
  }
}

async function handleClearBookmarks() {
  if (!useSettingsStore().confirmDeletion(t('kwic.bookmarks.title'))) return
  const result = await dispatch({ type: 'bookmark/clear' }, { source: 'user' })
  if (!result.success) {
    uiStore.showToast(result.error ?? t('kwic.bookmarks.clearFailed'), result.blocked ? 'warning' : 'error')
  }
}

onMounted(() => {
  bookmarksStore.init()
})
</script>

<template>
  <SlideOver
    :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)"
    :title="t('kwic.bookmarks.title')"
    size="md"
  >
    <div class="bookmarks-panel">

      <!-- Add Bookmark -->
      <div class="add-section">
        <template v-if="!showAddForm">
          <Button
            variant="primary"
            :icon="Plus"
            full-width
            :disabled="!queryStore.term"
            @click="showAddForm = true"
          >
            {{ t('kwic.bookmarks.saveCurrent') }}
          </Button>
          <p v-if="!queryStore.term" class="hint">
            {{ t('kwic.bookmarks.searchFirst') }}
          </p>
        </template>

        <div v-else class="add-form">
          <input
            v-model="newBookmarkName"
            type="text"
            class="name-input"
            :placeholder="t('kwic.bookmarks.namePlaceholder')"
            @keyup.enter="handleAddBookmark"
          />
          <div class="add-preview">
            <Search class="w-4 h-4" />
            <span>{{ queryStore.term }}</span>
          </div>
          <div class="add-actions">
            <Button variant="ghost" size="sm" @click="showAddForm = false">
              {{ t('kwic.bookmarks.cancel') }}
            </Button>
            <Button
              variant="primary"
              size="sm"
              :disabled="!canAddBookmark"
              @click="handleAddBookmark"
            >
              {{ t('kwic.bookmarks.save') }}
            </Button>
          </div>
        </div>
      </div>

      <!-- Search -->
      <div v-if="bookmarksStore.hasBookmarks" class="search-section">
        <div class="search-input-wrapper">
          <Search class="search-icon" />
          <input
            v-model="searchQuery"
            type="text"
            class="search-input"
            :placeholder="t('kwic.bookmarks.searchPlaceholder')"
          />
        </div>
      </div>

      <!-- Bookmarks List -->
      <div class="bookmarks-list">
        <template v-if="filteredBookmarks.length > 0">
          <div
            v-for="bookmark in filteredBookmarks"
            :key="bookmark.id"
            class="bookmark-item"
          >
            <button
              type="button"
              class="bookmark-main"
              @click="handleRestore(bookmark)"
            >
              <Bookmark class="bookmark-icon" />
              <div class="bookmark-info">
                <span class="bookmark-name">{{ bookmark.name }}</span>
                <span class="bookmark-query">{{ bookmark.query }}</span>
                <span class="bookmark-meta">
                  <Clock class="w-3 h-3" />
                  {{ formatDate(bookmark.timestamp) }}
                  <span v-if="bookmark.selectedRows.length > 0" class="meta-sep">
                    {{ t('kwic.bookmarks.selected', { count: bookmark.selectedRows.length }) }}
                  </span>
                </span>
              </div>
            </button>
            <button
              type="button"
              class="delete-btn"
              :title="t('kwic.bookmarks.delete')"
              @click.stop="handleDelete(bookmark)"
            >
              <Trash2 class="w-4 h-4" />
            </button>
          </div>
        </template>

        <!-- Empty State -->
        <div v-else-if="!bookmarksStore.hasBookmarks" class="empty-state">
          <Bookmark class="empty-icon" />
          <p class="empty-title">{{ t('kwic.bookmarks.emptyTitle') }}</p>
          <p class="empty-desc">
            {{ t('kwic.bookmarks.emptyText') }}
          </p>
        </div>

        <!-- No Results -->
        <div v-else class="empty-state">
          <Search class="empty-icon" />
          <p class="empty-title">{{ t('kwic.bookmarks.noMatchTitle') }}</p>
          <p class="empty-desc">
            {{ t('kwic.bookmarks.noMatchText', { query: searchQuery }) }}
          </p>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="panel-footer">
        <span class="footer-count">
          {{ t('kwic.bookmarks.count', { count: bookmarksStore.bookmarks.length }, bookmarksStore.bookmarks.length) }}
        </span>
        <Button
          v-if="bookmarksStore.hasBookmarks"
          variant="ghost"
          size="sm"
          @click="handleClearBookmarks"
        >
          {{ t('kwic.bookmarks.clearAll') }}
        </Button>
      </div>
    </template>
  </SlideOver>
</template>

<style scoped>
@reference "../../style.css";

.bookmarks-panel {
  @apply space-y-4;
}

/* Add Section */
.add-section {
  @apply pb-4 border-b border-neutral-200 dark:border-neutral-700;
}

.hint {
  @apply text-xs text-neutral-500 dark:text-neutral-400 text-center mt-2;
}

.add-form {
  @apply space-y-3;
}

.name-input {
  @apply w-full px-3 py-2 rounded-lg;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-sm;
  @apply focus:ring-2 focus:ring-primary-500 focus:outline-none;
}

.add-preview {
  @apply flex items-center gap-2;
  @apply px-3 py-2 rounded-lg;
  @apply bg-neutral-50 dark:bg-neutral-800/50;
  @apply text-sm text-neutral-600 dark:text-neutral-400;
}

.add-actions {
  @apply flex justify-end gap-2;
}

/* Search Section */
.search-section {
  @apply pb-4;
}

.search-input-wrapper {
  @apply relative;
}

.search-icon {
  @apply absolute left-3 top-1/2 -translate-y-1/2;
  @apply w-4 h-4 text-neutral-400;
}

.search-input {
  @apply w-full pl-10 pr-4 py-2 rounded-lg;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-sm;
  @apply focus:ring-2 focus:ring-primary-500 focus:outline-none;
}

/* Bookmarks List */
.bookmarks-list {
  @apply space-y-2;
}

.bookmark-item {
  @apply flex items-start gap-2;
  @apply p-3 rounded-xl;
  @apply bg-neutral-50 dark:bg-neutral-800/50;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply transition-colors;
}

.bookmark-item:hover {
  @apply bg-neutral-100 dark:bg-neutral-800;
}

.bookmark-main {
  @apply flex-1 flex items-start gap-3;
  @apply text-left;
}

.bookmark-icon {
  @apply w-5 h-5 mt-0.5;
  @apply text-primary-500;
}

.bookmark-info {
  @apply flex-1 min-w-0;
}

.bookmark-name {
  @apply block font-medium;
  @apply text-neutral-900 dark:text-neutral-100;
  @apply truncate;
}

.bookmark-query {
  @apply block text-sm;
  @apply text-neutral-600 dark:text-neutral-400;
  @apply truncate;
}

.bookmark-meta {
  @apply flex items-center gap-1 mt-1;
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.meta-sep::before {
  content: '·';
  @apply mx-1;
}

.delete-btn {
  @apply p-2 rounded-lg;
  @apply text-neutral-400;
  @apply hover:text-error-500 hover:bg-error-50 dark:hover:bg-error-900/20;
  @apply transition-colors;
}

/* Empty State */
.empty-state {
  @apply flex flex-col items-center;
  @apply py-12 text-center;
}

.empty-icon {
  @apply w-12 h-12 mb-4;
  @apply text-neutral-300 dark:text-neutral-600;
}

.empty-title {
  @apply font-medium text-neutral-900 dark:text-neutral-100;
}

.empty-desc {
  @apply text-sm text-neutral-500 dark:text-neutral-400 mt-1;
  @apply max-w-xs;
}

/* Footer */
.panel-footer {
  @apply flex items-center justify-between w-full;
}

.footer-count {
  @apply text-sm text-neutral-500 dark:text-neutral-400;
}
</style>
