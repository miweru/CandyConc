<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { ArrowDown, ArrowUp, ChevronDown, GitBranch, GripVertical, Plus, Trash2 } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import { formatNumber } from '@/i18n/format'
import { injectQuerySamples } from '@/composables/queryBuilder/useQuerySamples'
import CodeSpanText from '@/components/ui/CodeSpanText.vue'
import {
  createMetaCond,
  createMetaExpr,
  createMetaGroup,
  generateMetaExprPreview,
  getMetaOperatorOptions,
  literalExplanation,
  literalKindLabel,
  metaExprExplanation,
  type CqlBuilderLiteralKind,
  type CqlBuilderMetaExpr,
  type CqlBuilderMetaKind,
} from '@/lib/queryBuilder/ast'

defineOptions({ name: 'CqlMetaExprEditor' })

const props = withDefaults(defineProps<{
  expr: CqlBuilderMetaExpr
  metaFieldOptions: string[]
  metaValueChoices: (field: string) => string[]
  removable?: boolean
  level?: number
  selectedNodeId?: string | null
  selectedMetaId?: string | null
}>(), {
  removable: false,
  level: 0,
  selectedNodeId: null,
  selectedMetaId: null,
})

const { t } = useI18n()
// Words and tags of the active corpus for the examples in the explanations.
const querySamples = injectQuerySamples()
const editorEl = ref<HTMLElement | null>(null)

const emit = defineEmits<{
  replace: [expr: CqlBuilderMetaExpr]
  remove: []
  'select-node': [id: string]
  'select-meta': [id: string]
}>()

const expanded = ref(props.level <= 1)
const metaOperatorOptions = getMetaOperatorOptions()
const exprKindOptions = computed<Array<{ value: CqlBuilderMetaKind; label: string }>>(() => [
  { value: 'cond', label: t('querybuilder.meta.condition') },
  { value: 'and', label: t('querybuilder.meta.andGroup') },
  { value: 'or', label: t('querybuilder.meta.orGroup') },
])

const datalistId = computed(() => `meta-values-${props.expr.id}`)
const valueChoices = computed(() => {
  if (props.expr.kind !== 'cond') return []
  return props.metaValueChoices(props.expr.field)
})
const exprPreview = computed(() => truncatePreview(generateMetaExprPreview(props.expr) || t('querybuilder.common.empty')))
const toneClass = computed(() => `meta-tone-${props.expr.kind}`)
const isSelected = computed(() => props.selectedMetaId === props.expr.id)
const metaInsertIndex = ref<number | null>(null)
const metaDragIndex = ref<number | null>(null)
const metaDropIndex = ref<number | null>(null)
const selectedPartIndex = computed(() => props.expr.kind === 'cond' ? -1 : props.expr.parts.findIndex((part) => part.id === props.selectedMetaId))
const exprBadge = computed(() => {
  if (props.expr.kind === 'cond') {
    return props.expr.field.trim() ? props.expr.field.trim() : 'field op value'
  }
  const count = props.expr.parts.length
  return props.expr.kind === 'and'
    ? t('querybuilder.items.partsBadge', { count: formatNumber(count) }, count)
    : t('querybuilder.items.optionsBadge', { count: formatNumber(count) }, count)
})

function collapseLabel(): string {
  return expanded.value ? t('querybuilder.metaEditor.collapse') : t('querybuilder.metaEditor.expand')
}

function actionHint(label: string): string {
  return label
}

function changeExprKind(kind: CqlBuilderMetaKind) {
  if (kind === props.expr.kind) return
  if (kind === 'cond') {
    emit('replace', createMetaCond())
    expanded.value = true
    return
  }
  emit('replace', createMetaGroup(kind))
  expanded.value = true
}

function replacePart(index: number, next: CqlBuilderMetaExpr) {
  if (props.expr.kind === 'cond') return
  props.expr.parts.splice(index, 1, next)
}

function removePart(index: number) {
  if (props.expr.kind === 'cond') return
  props.expr.parts.splice(index, 1)
  if (!props.expr.parts.length) {
    props.expr.parts.push(createMetaCond())
  }
}

function movePart(index: number, direction: -1 | 1) {
  if (props.expr.kind === 'cond') return
  const nextIndex = index + direction
  if (nextIndex < 0 || nextIndex >= props.expr.parts.length) return
  const [part] = props.expr.parts.splice(index, 1)
  props.expr.parts.splice(nextIndex, 0, part!)
  void focusWithin(`[data-meta-part-id="${part?.id}"]`)
}

function addPart(kind: CqlBuilderMetaKind = 'cond') {
  if (props.expr.kind === 'cond') return
  const newPart = createMetaExpr(kind)
  props.expr.parts.push(newPart)
  expanded.value = true
  if (kind === 'cond') {
    void focusWithin(`[data-focus-id="${newPart.id}"]`)
    return
  }
  void focusLastWithin('.builder-select, .collapse-btn') // i18n-ignore: CSS selector
}

function partSlotIndices(): number[] {
  if (props.expr.kind === 'cond') return [0]
  return Array.from({ length: props.expr.parts.length + 1 }, (_, index) => index)
}

function toggleInsertPalette(index: number) {
  metaInsertIndex.value = metaInsertIndex.value === index ? null : index
}

function insertPart(index: number, kind: CqlBuilderMetaKind = 'cond') {
  if (props.expr.kind === 'cond') return
  const next = createMetaExpr(kind)
  props.expr.parts.splice(index, 0, next)
  metaInsertIndex.value = null
  expanded.value = true
  void focusWithin(`[data-meta-id="${next.id}"]`)
}

function canMoveSelectedPartToSlot(index: number): boolean {
  const current = selectedPartIndex.value
  return current >= 0 && index !== current && index !== current + 1
}

function moveSelectedPartToSlot(index: number) {
  if (props.expr.kind === 'cond') return
  const current = selectedPartIndex.value
  if (current < 0) return
  const [part] = props.expr.parts.splice(current, 1)
  const targetIndex = index > current ? index - 1 : index
  props.expr.parts.splice(targetIndex, 0, part!)
  metaInsertIndex.value = null
  void focusWithin(`[data-meta-part-id="${part?.id}"]`)
}

function literalKinds(): Array<{ value: CqlBuilderLiteralKind; label: string }> {
  return [
    { value: 'string', label: literalKindLabel('string') },
    { value: 'number', label: literalKindLabel('number') },
  ]
}

function groupLabel(index: number): string {
  const n = formatNumber(index + 1)
  return props.expr.kind === 'and'
    ? t('querybuilder.items.partN', { index: n })
    : t('querybuilder.items.optionN', { index: n })
}

function moveUpLabel(index: number): string {
  const n = formatNumber(index + 1)
  return props.expr.kind === 'and'
    ? t('querybuilder.items.movePartUp', { index: n })
    : t('querybuilder.items.moveOptionUp', { index: n })
}

function moveDownLabel(index: number): string {
  const n = formatNumber(index + 1)
  return props.expr.kind === 'and'
    ? t('querybuilder.items.movePartDown', { index: n })
    : t('querybuilder.items.moveOptionDown', { index: n })
}

function separatorLabel(): string {
  return props.expr.kind === 'and' ? '&' : '|'
}

function dragHandleLabel(index: number): string {
  const n = formatNumber(index + 1)
  return props.expr.kind === 'and'
    ? t('querybuilder.items.dragPart', { index: n })
    : t('querybuilder.items.dragOption', { index: n })
}

function truncatePreview(value: string, max = 72): string {
  if (!value) return t('querybuilder.common.empty')
  return value.length > max ? `${value.slice(0, max - 1)}…` : value
}

function handleReorderShortcut(
  event: KeyboardEvent,
  directionHandlers: { up: () => void; down: () => void }
) {
  if (!event.altKey) return
  if (event.key === 'ArrowUp') {
    event.preventDefault()
    directionHandlers.up()
  }
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    directionHandlers.down()
  }
}

function onPartKeydown(event: KeyboardEvent, index: number) {
  handleReorderShortcut(event, {
    up: () => movePart(index, -1),
    down: () => movePart(index, 1),
  })
}

function handlePartDragStart(index: number, event: DragEvent) {
  if (props.expr.kind === 'cond' || !event.dataTransfer) return
  metaDragIndex.value = index
  metaDropIndex.value = null
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('text/plain', props.expr.parts[index]?.id ?? '')
}

function clearPartDrag() {
  metaDragIndex.value = null
  metaDropIndex.value = null
}

function handlePartSlotDragOver(index: number, event: DragEvent) {
  if (!event.dataTransfer) return
  if (metaDragIndex.value !== null) {
    if (props.expr.kind === 'cond') return
    if (index === metaDragIndex.value || index === metaDragIndex.value + 1) return
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
    metaDropIndex.value = index
    return
  }
}

function handlePartSlotDrop(index: number, event: DragEvent) {
  if (metaDragIndex.value !== null) {
    if (props.expr.kind === 'cond') return
    event.preventDefault()
    const sourceIndex = metaDragIndex.value
    if (index === sourceIndex || index === sourceIndex + 1) {
      clearPartDrag()
      return
    }
    const [part] = props.expr.parts.splice(sourceIndex, 1)
    const targetIndex = index > sourceIndex ? index - 1 : index
    props.expr.parts.splice(targetIndex, 0, part!)
    clearPartDrag()
    void focusWithin(`[data-meta-part-id="${part?.id}"]`)
    return
  }
}

async function focusWithin(selector: string) {
  await nextTick()
  await new Promise<void>((resolve) => window.setTimeout(resolve, 30))
  const target = editorEl.value?.querySelector<HTMLElement>(selector)
  if (!target) return
  target.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  target.focus()
}

async function focusLastWithin(selector: string) {
  await nextTick()
  await new Promise<void>((resolve) => window.setTimeout(resolve, 30))
  const matches = editorEl.value?.querySelectorAll<HTMLElement>(selector)
  const target = matches?.[matches.length - 1]
  if (!target) return
  target.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  target.focus()
}

function handleSelectMeta() {
  emit('select-meta', props.expr.id)
}

</script>

<template>
  <div
    ref="editorEl"
    class="meta-editor"
    :class="[toneClass, { 'is-selected': isSelected }]"
    :style="{ '--meta-level': String(level) }"
    :data-meta-id="expr.id"
    tabindex="0"
    @pointerdown.stop="handleSelectMeta"
    @focus="handleSelectMeta"
  >
    <div class="meta-toolbar">
      <div class="meta-toolbar-main">
        <button
          type="button"
          class="collapse-btn tooltip-trigger"
          :aria-label="collapseLabel()"
          :title="collapseLabel()"
          :data-help="actionHint(collapseLabel())"
          @click="expanded = !expanded"
        >
          <ChevronDown class="w-4 h-4 transition-transform" :class="{ 'rotate-180': expanded }" />
        </button>
        <div class="meta-title-block">
          <div class="meta-toolbar-title-row">
            <div class="meta-toolbar-title">
              <GitBranch class="w-4 h-4" />
              <span>{{ t('querybuilder.metaEditor.title') }}</span>
            </div>
            <span class="meta-badge">{{ exprBadge }}</span>
          </div>
          <code class="meta-preview-chip">{{ exprPreview }}</code>
        </div>
      </div>
      <div class="meta-toolbar-controls">
        <select
          class="builder-select compact"
          :value="expr.kind"
          @change="changeExprKind(($event.target as HTMLSelectElement).value as CqlBuilderMetaKind)"
        >
          <option v-for="option in exprKindOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
        <button
          v-if="removable"
          type="button"
          class="icon-btn danger tooltip-trigger"
          :aria-label="t('querybuilder.metaEditor.remove')"
          :title="t('querybuilder.metaEditor.remove')"
          :data-help="t('querybuilder.metaEditor.remove')"
          @click="$emit('remove')"
        >
          <Trash2 class="w-4 h-4" />
        </button>
      </div>
    </div>

    <div v-if="expanded" class="meta-body">
      <p class="node-help"><CodeSpanText :text="metaExprExplanation(expr, querySamples)" /></p>

      <div v-if="expr.kind === 'cond'" class="meta-cond-card">
        <div class="meta-cond-grid">
          <input
            v-model="expr.field"
            type="text"
            class="builder-input"
            data-role="meta-field-input"
            :data-focus-id="expr.id"
            :placeholder="t('querybuilder.metaEditor.fieldPlaceholder', { example: 'source' })"
            list="query-builder-meta-fields"
          />

          <select v-model="expr.op" class="builder-select">
            <option v-for="operator in metaOperatorOptions" :key="operator" :value="operator">
              {{ operator }}
            </option>
          </select>

          <select v-model="expr.value.kind" class="builder-select compact narrow">
            <option v-for="kind in literalKinds()" :key="kind.value" :value="kind.value">
              {{ kind.label }}
            </option>
          </select>

          <input
            v-model="expr.value.value"
            type="text"
            class="builder-input"
            :placeholder="t('querybuilder.items.value')"
            :list="expr.value.kind === 'string' && expr.field.trim() ? datalistId : undefined"
          />
        </div>

        <datalist v-if="expr.field.trim()" :id="datalistId">
          <option v-for="choice in valueChoices" :key="`${expr.id}-${choice}`" :value="choice" />
        </datalist>

        <p class="literal-help"><CodeSpanText :text="literalExplanation(expr.value)" /></p>
      </div>

      <div v-else class="meta-group-body">
        <i18n-t keypath="querybuilder.metaEditor.joinHint" tag="div" class="meta-join-hint" scope="global">
          <template #operator>
            <strong>{{ expr.kind === 'and' ? t('querybuilder.metaEditor.joinAnd') : t('querybuilder.metaEditor.joinOr') }}</strong>
          </template>
        </i18n-t>
        <i18n-t keypath="querybuilder.metaEditor.reorderGroups" tag="p" class="reorder-tip" scope="global">
          <template #keys><kbd class="shortcut-kbd">Alt</kbd> + <kbd class="shortcut-kbd">↑</kbd>/<kbd class="shortcut-kbd">↓</kbd></template>
        </i18n-t>

        <div class="meta-group-list">
          <template v-for="slotIndex in partSlotIndices()" :key="`slot-${expr.id}-${slotIndex}`">
            <div
              class="meta-slot"
              :class="{ 'is-drop-target': metaDropIndex === slotIndex }"
              :data-meta-slot="slotIndex"
              @pointerdown.stop
              @dragover="handlePartSlotDragOver(slotIndex, $event)"
              @drop="handlePartSlotDrop(slotIndex, $event)"
            >
              <div class="meta-slot-line" />
              <div class="meta-slot-actions">
                <button
                  v-if="canMoveSelectedPartToSlot(slotIndex)"
                  type="button"
                  class="meta-move-btn"
                  :data-meta-move-slot="slotIndex"
                  @click="moveSelectedPartToSlot(slotIndex)"
                >
                  <ArrowDown class="w-4 h-4" />
                  <span>{{ t('querybuilder.items.moveSelectionHere') }}</span>
                </button>
                <button
                  type="button"
                  class="meta-insert-btn"
                  :data-meta-insert-slot="slotIndex"
                  :aria-expanded="metaInsertIndex === slotIndex"
                  @click="toggleInsertPalette(slotIndex)"
                >
                  <Plus class="w-4 h-4" />
                  <span>{{ t('querybuilder.items.insertHere') }}</span>
                </button>
              </div>
              <div v-if="metaInsertIndex === slotIndex" class="meta-insert-actions">
                <button type="button" class="ghost-action" @click="insertPart(slotIndex, 'cond')">
                  <Plus class="w-4 h-4" />
                  {{ t('querybuilder.meta.condition') }}
                </button>
                <button type="button" class="ghost-action" @click="insertPart(slotIndex, 'and')">
                  <Plus class="w-4 h-4" />
                  {{ t('querybuilder.meta.andGroup') }}
                </button>
                <button type="button" class="ghost-action" @click="insertPart(slotIndex, 'or')">
                  <Plus class="w-4 h-4" />
                  {{ t('querybuilder.meta.orGroup') }}
                </button>
              </div>
            </div>

            <div
              v-if="slotIndex < expr.parts.length"
              class="meta-group-item"
              :data-meta-part-id="expr.parts[slotIndex]?.id"
              tabindex="0"
              role="group"
              :aria-label="groupLabel(slotIndex)"
              @pointerdown.stop="$emit('select-meta', expr.parts[slotIndex]!.id)"
              @focus="$emit('select-meta', expr.parts[slotIndex]!.id)"
              @keydown="onPartKeydown($event, slotIndex)"
            >
              <div v-if="slotIndex > 0" class="meta-group-separator">{{ separatorLabel() }}</div>
              <div class="meta-group-item-header">
                <div class="meta-group-item-label">{{ groupLabel(slotIndex) }}</div>
                <div class="inline-actions">
                  <button
                    type="button"
                    class="drag-handle tooltip-trigger"
                    :data-meta-drag-slot="slotIndex"
                    :aria-label="dragHandleLabel(slotIndex)"
                    :title="dragHandleLabel(slotIndex)"
                    :data-help="actionHint(dragHandleLabel(slotIndex))"
                    draggable="true"
                    @dragstart="handlePartDragStart(slotIndex, $event)"
                    @dragend="clearPartDrag"
                  >
                    <GripVertical class="w-4 h-4" />
                  </button>
                  <button
                    type="button"
                    class="icon-btn tooltip-trigger"
                    :aria-label="moveUpLabel(slotIndex)"
                    :title="moveUpLabel(slotIndex)"
                    :data-help="actionHint(moveUpLabel(slotIndex))"
                    :disabled="slotIndex === 0"
                    @click="movePart(slotIndex, -1)"
                  >
                    <ArrowUp class="w-4 h-4" />
                  </button>
                  <button
                    type="button"
                    class="icon-btn tooltip-trigger"
                    :aria-label="moveDownLabel(slotIndex)"
                    :title="moveDownLabel(slotIndex)"
                    :data-help="actionHint(moveDownLabel(slotIndex))"
                    :disabled="slotIndex === expr.parts.length - 1"
                    @click="movePart(slotIndex, 1)"
                  >
                    <ArrowDown class="w-4 h-4" />
                  </button>
                </div>
              </div>
              <CqlMetaExprEditor
                :expr="expr.parts[slotIndex]!"
                :level="level + 1"
                :meta-field-options="metaFieldOptions"
                :meta-value-choices="metaValueChoices"
                :selected-node-id="selectedNodeId"
                :selected-meta-id="selectedMetaId"
                removable
                @replace="replacePart(slotIndex, $event)"
                @remove="removePart(slotIndex)"
                @select-node="$emit('select-node', $event)"
                @select-meta="$emit('select-meta', $event)"
              />
            </div>
          </template>
        </div>

        <div class="node-action-row wrap-actions">
          <button type="button" class="ghost-action" @click="addPart('cond')">
            <Plus class="w-4 h-4" />
            {{ t('querybuilder.meta.condition') }}
          </button>
          <button type="button" class="ghost-action" @click="addPart('and')">
            <Plus class="w-4 h-4" />
            {{ t('querybuilder.meta.andGroup') }}
          </button>
          <button type="button" class="ghost-action" @click="addPart('or')">
            <Plus class="w-4 h-4" />
            {{ t('querybuilder.meta.orGroup') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
@reference "../../../style.css";

.meta-editor {
  @apply rounded-2xl border bg-white dark:bg-neutral-900/70 p-3 space-y-3;
  @apply border-neutral-200 dark:border-neutral-700;
  margin-left: calc(var(--meta-level, 0) * 0.25rem);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.55);
  scroll-margin-top: 1rem;
}

.meta-editor.is-selected {
  @apply border-primary-400 bg-primary-50/70 ring-2 ring-primary-300 ring-offset-2 ring-offset-white dark:bg-primary-500/10 dark:ring-primary-500 dark:ring-offset-neutral-900;
}

.meta-tone-cond { @apply border-l-4 border-l-cyan-400; }
.meta-tone-and { @apply border-l-4 border-l-emerald-400; }
.meta-tone-or { @apply border-l-4 border-l-amber-400; }

.meta-toolbar,
.meta-toolbar-main,
.meta-toolbar-title,
.meta-toolbar-title-row,
.meta-toolbar-controls,
.meta-cond-grid,
.node-action-row,
.inline-actions,
.meta-group-item-header {
  @apply flex items-center gap-2;
}

.meta-toolbar,
.meta-group-item-header {
  @apply justify-between;
}

.meta-toolbar-main {
  @apply min-w-0 flex-1 items-start;
}

.meta-toolbar-controls {
  @apply shrink-0 flex-wrap justify-end;
}

.meta-title-block,
.meta-body,
.meta-group-body,
.meta-group-list,
.meta-cond-card {
  @apply min-w-0 flex-1 space-y-3;
}

.meta-toolbar-title {
  @apply text-sm font-semibold text-neutral-900 dark:text-neutral-100;
}

.meta-preview-chip {
  @apply inline-block max-w-full truncate rounded-full bg-neutral-950 text-emerald-300 px-3 py-1 text-xs;
}

.meta-badge {
  @apply rounded-full bg-neutral-200 dark:bg-neutral-700 px-2.5 py-1 text-[11px] font-medium text-neutral-700 dark:text-neutral-100;
}

.meta-group-item-label,
.meta-group-separator {
  @apply text-xs uppercase tracking-wide text-neutral-500 dark:text-neutral-400;
}

.meta-slot {
  @apply rounded-xl border border-dashed border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-3 space-y-3 transition-colors;
}

.meta-slot.is-drop-target {
  @apply border-primary-400 bg-primary-50/60 dark:bg-primary-500/10;
}

.meta-slot-line {
  @apply h-px w-full bg-neutral-200 dark:bg-neutral-700;
}

.meta-slot-actions {
  @apply flex flex-wrap gap-2;
}

.meta-insert-btn {
  @apply inline-flex items-center gap-2 rounded-full border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-xs font-semibold text-neutral-700 dark:text-neutral-200 transition-colors hover:border-primary-300 hover:text-primary-700;
}

.meta-move-btn {
  @apply inline-flex items-center gap-2 rounded-full border border-primary-300 bg-primary-50 px-3 py-2 text-xs font-semibold text-primary-900 transition-colors hover:border-primary-400 hover:bg-primary-100 dark:bg-primary-500/10 dark:text-primary-100;
}

.meta-insert-actions {
  @apply flex flex-wrap gap-2;
}

.builder-input,
.builder-select {
  @apply rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100;
  @apply focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent;
}

.builder-select.compact,
.builder-select.narrow {
  @apply w-auto;
}

.collapse-btn,
.icon-btn,
.drag-handle,
.ghost-action {
  @apply inline-flex items-center gap-2 rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm text-neutral-700 dark:text-neutral-200 hover:border-primary-300 hover:text-primary-700 transition-colors;
}

.collapse-btn,
.icon-btn,
.drag-handle {
  @apply px-2.5 py-2;
}

.icon-btn:disabled,
.collapse-btn:disabled,
.drag-handle:disabled {
  @apply opacity-40 cursor-not-allowed;
}

.collapse-btn:focus-visible,
.icon-btn:focus-visible,
.drag-handle:focus-visible,
.ghost-action:focus-visible {
  @apply outline-none ring-2 ring-primary-400 ring-offset-2 ring-offset-white dark:ring-primary-500 dark:ring-offset-neutral-900;
}

.icon-btn.danger {
  @apply hover:border-rose-300 hover:text-rose-700;
}

.node-help,
.literal-help,
.reorder-tip,
.meta-join-hint {
  @apply text-sm leading-6 text-neutral-600 dark:text-neutral-300;
}

.reorder-tip {
  @apply text-xs leading-5 text-neutral-500 dark:text-neutral-400;
}

.shortcut-kbd {
  @apply inline-flex min-w-[1.5rem] items-center justify-center rounded-md border border-neutral-300 bg-white px-1.5 py-0.5 font-mono text-[11px] text-neutral-700 shadow-sm dark:border-neutral-600 dark:bg-neutral-900 dark:text-neutral-200;
}

.meta-cond-card,
.meta-group-item {
  @apply rounded-xl border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/70 p-3;
  scroll-margin-top: 1rem;
}

.meta-cond-grid {
  @apply grid gap-2;
  grid-template-columns: minmax(0, 1.1fr) minmax(6rem, 8rem) minmax(6rem, 8rem) minmax(0, 1fr);
}

.wrap-actions {
  @apply flex-wrap;
}

.meta-editor:focus-within,
.meta-cond-card:focus-within,
.meta-slot:focus-within,
.meta-group-item:focus-within {
  @apply ring-2 ring-primary-300 ring-offset-2 ring-offset-white dark:ring-primary-500 dark:ring-offset-neutral-900;
}

.tooltip-trigger[data-help] {
  @apply relative;
}

.tooltip-trigger[data-help]::after {
  content: attr(data-help);
  @apply pointer-events-none absolute left-1/2 top-full z-20 mt-2 -translate-x-1/2 rounded-lg bg-neutral-950 px-2.5 py-1.5 text-[11px] leading-4 text-white opacity-0 shadow-lg transition-opacity duration-150;
  width: max-content;
  min-width: 0;
  max-width: min(15rem, calc(100vw - 2rem));
  white-space: normal;
}

.tooltip-trigger[data-help]::before {
  content: '';
  @apply pointer-events-none absolute left-1/2 top-full z-20 mt-0.5 h-2 w-2 -translate-x-1/2 rotate-45 bg-neutral-950 opacity-0 transition-opacity duration-150;
}

.tooltip-trigger[data-help]:hover::after,
.tooltip-trigger[data-help]:hover::before,
.tooltip-trigger[data-help]:focus-visible::after,
.tooltip-trigger[data-help]:focus-visible::before {
  @apply opacity-100;
}

@media (hover: none), (pointer: coarse) {
  .tooltip-trigger[data-help]::after,
  .tooltip-trigger[data-help]::before {
    display: none;
  }
}

@media (max-width: 960px) {
  .meta-editor,
  .meta-body,
  .meta-group-body,
  .meta-group-list,
  .meta-group-item,
  .meta-cond-card {
    overflow-x: clip;
  }

  .meta-toolbar {
    @apply flex-wrap items-start;
  }

  .meta-toolbar-main,
  .meta-toolbar-controls {
    @apply w-full;
  }

  .meta-toolbar-controls {
    @apply justify-between;
  }

  .meta-toolbar-controls .builder-select.compact {
    @apply min-w-0 flex-1;
  }

  .meta-toolbar-title-row,
  .meta-group-item-header {
    @apply flex-wrap items-start;
  }

  .meta-preview-chip {
    @apply rounded-2xl whitespace-normal break-words;
  }

  .meta-cond-grid {
    grid-template-columns: 1fr;
  }

  .meta-slot,
  .meta-insert-actions {
    @apply w-full;
  }

  .meta-insert-btn,
  .meta-move-btn,
  .drag-handle {
    @apply w-full justify-center;
  }
}
</style>
