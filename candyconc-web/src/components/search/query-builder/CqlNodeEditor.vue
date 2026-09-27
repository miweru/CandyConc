<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { ArrowDown, ArrowUp, Braces, ChevronDown, Filter, GripVertical, Layers3, Plus, Repeat, ScanSearch, Trash2 } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import { formatNumber } from '@/i18n/format'
import { injectQuerySamples } from '@/composables/queryBuilder/useQuerySamples'
import CqlMetaExprEditor from '@/components/search/query-builder/CqlMetaExprEditor.vue'
import CodeSpanText from '@/components/ui/CodeSpanText.vue'
import {
  createBuilderNode,
  createLiteral,
  createTokenCondition,
  generateBuilderQuery,
  getNodeTypeOptions,
  getTokenAttributeSuggestions,
  getTokenOperatorOptions,
  literalExplanation,
  literalKindLabel,
  nodeExplanation,
  nodeTypeLabel,
  quantifierExplanation,
  tokenConditionExplanation,
  tokenOperatorSupportsValueFlags,
  type CqlBuilderLiteralKind,
  type CqlBuilderNode,
  type CqlBuilderNodeType,
  type CqlBuilderTokenCondition,
  type CqlBuilderTokenOperator,
} from '@/lib/queryBuilder/ast'

defineOptions({ name: 'CqlNodeEditor' })

const props = withDefaults(defineProps<{
  node: CqlBuilderNode
  metaFieldOptions: string[]
  metaValueChoices: (field: string) => string[]
  tokenAttributeSuggestions?: string[]
  removable?: boolean
  level?: number
  selectedNodeId?: string | null
  selectedMetaId?: string | null
}>(), {
  removable: false,
  level: 0,
  selectedNodeId: null,
  selectedMetaId: null,
  tokenAttributeSuggestions: () => getTokenAttributeSuggestions(),
})

const { t } = useI18n()
// Words and tags of the active corpus for the examples in the explanations.
const querySamples = injectQuerySamples()
const editorEl = ref<HTMLElement | null>(null)

const emit = defineEmits<{
  replace: [node: CqlBuilderNode]
  remove: []
  'select-node': [id: string]
  'select-meta': [id: string]
}>()

const expanded = ref(props.level <= 1)
const nodeTypeOptions = computed(() => getNodeTypeOptions())
const tokenOperatorOptions = getTokenOperatorOptions()
const resolvedTokenAttributeSuggestions = computed(() =>
  props.tokenAttributeSuggestions?.length ? props.tokenAttributeSuggestions : getTokenAttributeSuggestions()
)
const attrListId = computed(() => `token-attrs-${props.node.id}`)
const nodePreview = computed(() => truncatePreview(generateBuilderQuery(props.node)))
const typeToneClass = computed(() => `tone-${props.node.type}`)
const isSelected = computed(() => props.selectedNodeId === props.node.id)
const structuredInsertIndex = ref<number | null>(null)
const structuredDragIndex = ref<number | null>(null)
const structuredDropIndex = ref<number | null>(null)
const selectedStructuredChildIndex = computed(() => collection().findIndex((child) => child.id === props.selectedNodeId))
const nodeBadge = computed(() => {
  if (props.node.type === 'tok') {
    const count = props.node.conditions.length
    return t('querybuilder.nodeEditor.conditionsBadge', { count: formatNumber(count) }, count)
  }
  if (props.node.type === 'seq') {
    const count = props.node.parts.length
    return t('querybuilder.items.partsBadge', { count: formatNumber(count) }, count)
  }
  if (props.node.type === 'alt') {
    const count = props.node.options.length
    return t('querybuilder.items.optionsBadge', { count: formatNumber(count) }, count)
  }
  if (props.node.type === 'quant') return quantifierExplanation(props.node.min, props.node.max)
  if (props.node.type === 'within') return props.node.scope === 's' ? '<s>' : '<doc>'
  return t('querybuilder.ast.metaPlusQuery')
})

function changeNodeType(type: CqlBuilderNodeType) {
  if (type === props.node.type) return
  emit('replace', createBuilderNode(type))
  expanded.value = true
}

function replaceChild(next: CqlBuilderNode) {
  if (props.node.type === 'quant' || props.node.type === 'within' || props.node.type === 'where') {
    props.node.node = next
  }
}

function replaceIndexedChild(index: number, next: CqlBuilderNode) {
  if (props.node.type === 'seq') props.node.parts.splice(index, 1, next)
  if (props.node.type === 'alt') props.node.options.splice(index, 1, next)
}

function removeIndexedChild(index: number) {
  if (props.node.type === 'seq') {
    props.node.parts.splice(index, 1)
    if (!props.node.parts.length) props.node.parts.push(createBuilderNode('tok'))
  }
  if (props.node.type === 'alt') {
    props.node.options.splice(index, 1)
    if (!props.node.options.length) props.node.options.push(createBuilderNode('tok'))
  }
}

function moveIndexedChild(index: number, direction: -1 | 1) {
  const items = collection()
  const nextIndex = index + direction
  if (nextIndex < 0 || nextIndex >= items.length) return
  const [item] = items.splice(index, 1)
  items.splice(nextIndex, 0, item!)
  void focusWithin(`[data-child-id="${item?.id}"]`)
}

function addStructuredChild(type: CqlBuilderNodeType = 'tok') {
  if (props.node.type === 'seq') props.node.parts.push(createBuilderNode(type))
  if (props.node.type === 'alt') props.node.options.push(createBuilderNode(type))
  expanded.value = true
  void focusLastWithin('[data-role="condition-attr"], [data-role="primary-input"], .builder-select, .collapse-btn') // i18n-ignore: CSS selector
}

function slotIndices(): number[] {
  return Array.from({ length: collection().length + 1 }, (_, index) => index)
}

function toggleInsertPalette(index: number) {
  structuredInsertIndex.value = structuredInsertIndex.value === index ? null : index
}

function insertStructuredChild(index: number, type: CqlBuilderNodeType = 'tok') {
  const items = collection()
  const next = createBuilderNode(type)
  items.splice(index, 0, next)
  structuredInsertIndex.value = null
  expanded.value = true
  void focusWithin(`[data-node-id="${next.id}"]`)
}

function canMoveSelectedChildToSlot(index: number): boolean {
  const current = selectedStructuredChildIndex.value
  return current >= 0 && index !== current && index !== current + 1
}

function moveSelectedChildToSlot(index: number) {
  const current = selectedStructuredChildIndex.value
  if (current < 0) return
  const items = collection()
  const [child] = items.splice(current, 1)
  const targetIndex = index > current ? index - 1 : index
  items.splice(targetIndex, 0, child!)
  structuredInsertIndex.value = null
  void focusWithin(`[data-child-id="${child?.id}"]`)
}

function addCondition() {
  if (props.node.type !== 'tok') return
  props.node.conditions.push(createTokenCondition())
  expanded.value = true
  void focusLastWithin('[data-role="condition-attr"]')
}

function removeCondition(index: number) {
  if (props.node.type !== 'tok') return
  props.node.conditions.splice(index, 1)
}

function moveCondition(index: number, direction: -1 | 1) {
  if (props.node.type !== 'tok') return
  const nextIndex = index + direction
  if (nextIndex < 0 || nextIndex >= props.node.conditions.length) return
  const [item] = props.node.conditions.splice(index, 1)
  props.node.conditions.splice(nextIndex, 0, item!)
  void focusWithin(`[data-condition-id="${item?.id}"]`)
}

function onConditionOperatorChange(condition: CqlBuilderTokenCondition) {
  if (condition.op === 'in' && !condition.setValues.length) {
    condition.setValues.push(createLiteral())
  }
  if (!canUseCaseFlag(condition)) {
    condition.flags = ''
  }
}

function canUseCaseFlag(condition: CqlBuilderTokenCondition): boolean {
  const attr = condition.attr.trim().toLowerCase()
  return Boolean(attr && attr !== 'k' && attr !== 'sim' && tokenOperatorSupportsValueFlags(condition.op))
}

function toggleConditionCaseFlag(condition: CqlBuilderTokenCondition, checked: boolean) {
  condition.flags = checked && canUseCaseFlag(condition) ? 'c' : ''
}

function addSetValue(condition: CqlBuilderTokenCondition) {
  condition.setValues.push(createLiteral())
  void focusLastWithin('[data-role="set-value-input"]')
}

function removeSetValue(condition: CqlBuilderTokenCondition, index: number) {
  condition.setValues.splice(index, 1)
  if (!condition.setValues.length) condition.setValues.push(createLiteral())
}

function moveSetValue(condition: CqlBuilderTokenCondition, index: number, direction: -1 | 1) {
  const nextIndex = index + direction
  if (nextIndex < 0 || nextIndex >= condition.setValues.length) return
  const [item] = condition.setValues.splice(index, 1)
  condition.setValues.splice(nextIndex, 0, item!)
  void focusWithin(`[data-set-value-id="${item?.id}"]`)
}

function setQuantifierPreset(preset: string) {
  if (props.node.type !== 'quant') return
  if (preset === '?') {
    props.node.min = 0
    props.node.max = 1
    return
  }
  if (preset === '*') {
    props.node.min = 0
    props.node.max = null
    return
  }
  if (preset === '+') {
    props.node.min = 1
    props.node.max = null
    return
  }
  if (preset === 'exact') {
    props.node.min = Math.max(0, props.node.min)
    props.node.max = props.node.min
    return
  }
  if (preset === 'open') {
    props.node.min = Math.max(0, props.node.min)
    props.node.max = null
    return
  }
  props.node.min = Math.max(0, props.node.min)
  props.node.max = Math.max(props.node.min, props.node.max ?? props.node.min + 1)
}

function quantifierPreset(): string {
  if (props.node.type !== 'quant') return 'range'
  if (props.node.min === 0 && props.node.max === 1) return '?'
  if (props.node.min === 0 && props.node.max === null) return '*'
  if (props.node.min === 1 && props.node.max === null) return '+'
  if (props.node.max === null) return 'open'
  if (props.node.min === props.node.max) return 'exact'
  return 'range'
}

function literalKinds(): Array<{ value: CqlBuilderLiteralKind; label: string }> {
  return [
    { value: 'string', label: literalKindLabel('string') },
    { value: 'number', label: literalKindLabel('number') },
  ]
}

function childLabel(index: number): string {
  const n = formatNumber(index + 1)
  return props.node.type === 'alt'
    ? t('querybuilder.items.optionN', { index: n })
    : t('querybuilder.items.partN', { index: n })
}

function childMoveUpLabel(index: number): string {
  const n = formatNumber(index + 1)
  return props.node.type === 'alt'
    ? t('querybuilder.items.moveOptionUp', { index: n })
    : t('querybuilder.items.movePartUp', { index: n })
}

function childMoveDownLabel(index: number): string {
  const n = formatNumber(index + 1)
  return props.node.type === 'alt'
    ? t('querybuilder.items.moveOptionDown', { index: n })
    : t('querybuilder.items.movePartDown', { index: n })
}

function collection(): CqlBuilderNode[] {
  if (props.node.type === 'seq') return props.node.parts
  if (props.node.type === 'alt') return props.node.options
  return []
}

function separatorLabel(): string {
  return props.node.type === 'alt' ? '|' : t('querybuilder.nodeEditor.separatorThen')
}

function dragHandleLabel(index: number): string {
  const n = formatNumber(index + 1)
  return props.node.type === 'alt'
    ? t('querybuilder.items.dragOption', { index: n })
    : t('querybuilder.items.dragPart', { index: n })
}

function conditionLabel(key: string, index: number): string {
  return t(key, { index: formatNumber(index + 1) })
}

function operatorLabel(operator: CqlBuilderTokenOperator): string {
  return operator
}

function collapseLabel(): string {
  return expanded.value ? t('querybuilder.nodeEditor.collapse') : t('querybuilder.nodeEditor.expand')
}

function actionHint(label: string): string {
  return label
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

function onConditionKeydown(event: KeyboardEvent, index: number) {
  handleReorderShortcut(event, {
    up: () => moveCondition(index, -1),
    down: () => moveCondition(index, 1),
  })
}

function onSetValueKeydown(condition: CqlBuilderTokenCondition, index: number, event: KeyboardEvent) {
  handleReorderShortcut(event, {
    up: () => moveSetValue(condition, index, -1),
    down: () => moveSetValue(condition, index, 1),
  })
}

function onStructuredItemKeydown(event: KeyboardEvent, index: number) {
  handleReorderShortcut(event, {
    up: () => moveIndexedChild(index, -1),
    down: () => moveIndexedChild(index, 1),
  })
}

function handleStructuredDragStart(index: number, event: DragEvent) {
  if (!event.dataTransfer) return
  structuredDragIndex.value = index
  structuredDropIndex.value = null
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('text/plain', collection()[index]?.id ?? '')
}

function clearStructuredDrag() {
  structuredDragIndex.value = null
  structuredDropIndex.value = null
}

function handleStructuredSlotDragOver(index: number, event: DragEvent) {
  if (!event.dataTransfer) return
  if (structuredDragIndex.value !== null) {
    if (index === structuredDragIndex.value || index === structuredDragIndex.value + 1) return
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
    structuredDropIndex.value = index
    return
  }
}

function handleStructuredSlotDrop(index: number, event: DragEvent) {
  if (structuredDragIndex.value !== null) {
    event.preventDefault()
    const sourceIndex = structuredDragIndex.value
    const items = collection()
    if (index === sourceIndex || index === sourceIndex + 1) {
      clearStructuredDrag()
      return
    }
    const [child] = items.splice(sourceIndex, 1)
    const targetIndex = index > sourceIndex ? index - 1 : index
    items.splice(targetIndex, 0, child!)
    clearStructuredDrag()
    void focusWithin(`[data-child-id="${child?.id}"]`)
    return
  }
}

function nodeIcon(type: CqlBuilderNodeType) {
  if (type === 'tok') return Braces
  if (type === 'where') return Filter
  if (type === 'quant') return Repeat
  return Layers3
}

function truncatePreview(value: string, max = 82): string {
  if (!value) return t('querybuilder.common.empty')
  return value.length > max ? `${value.slice(0, max - 1)}…` : value
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

async function focusWithin(selector: string) {
  await nextTick()
  await new Promise<void>((resolve) => window.setTimeout(resolve, 30))
  const target = editorEl.value?.querySelector<HTMLElement>(selector)
  if (!target) return
  target.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  target.focus()
}

function handleSelectNode() {
  emit('select-node', props.node.id)
}

</script>

<template>
  <div
    ref="editorEl"
    class="builder-node-card"
    :class="[typeToneClass, { 'is-selected': isSelected }]"
    :style="{ '--node-level': String(level) }"
    :data-node-id="node.id"
    tabindex="0"
    @pointerdown.stop="handleSelectNode"
    @focus="handleSelectNode"
  >
    <div class="node-toolbar">
      <div class="node-toolbar-main">
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
        <div class="node-title-block">
          <div class="node-toolbar-title-row">
            <div class="node-toolbar-title">
              <component :is="nodeIcon(node.type)" class="w-4 h-4" />
              <span>{{ nodeTypeLabel(node.type) }}</span>
            </div>
            <span class="node-badge">{{ nodeBadge }}</span>
          </div>
          <code class="node-preview-chip">{{ nodePreview }}</code>
        </div>
      </div>
      <div class="node-toolbar-controls">
        <select
          class="builder-select compact"
          :value="node.type"
          @change="changeNodeType(($event.target as HTMLSelectElement).value as CqlBuilderNodeType)"
        >
          <option v-for="option in nodeTypeOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
        <button
          v-if="removable"
          type="button"
          class="icon-btn danger tooltip-trigger"
          :aria-label="t('querybuilder.nodeEditor.remove')"
          :title="t('querybuilder.nodeEditor.remove')"
          :data-help="t('querybuilder.nodeEditor.remove')"
          @click="$emit('remove')"
        >
          <Trash2 class="w-4 h-4" />
        </button>
      </div>
    </div>

    <div v-if="expanded" class="node-body">
      <p class="node-help"><CodeSpanText :text="nodeExplanation(node, querySamples)" /></p>

      <div v-if="node.type === 'tok'" class="token-conditions">
        <datalist :id="attrListId">
          <option v-for="attr in resolvedTokenAttributeSuggestions" :key="attr" :value="attr" />
        </datalist>

        <i18n-t keypath="querybuilder.nodeEditor.reorderCards" tag="p" class="reorder-tip" scope="global">
          <template #keys><kbd class="shortcut-kbd">Alt</kbd> + <kbd class="shortcut-kbd">↑</kbd>/<kbd class="shortcut-kbd">↓</kbd></template>
        </i18n-t>

        <i18n-t v-if="!node.conditions.length" keypath="querybuilder.nodeEditor.anyToken" tag="p" class="any-token-note" scope="global">
          <template #code><code>[]</code></template>
        </i18n-t>

        <div
          v-for="(condition, index) in node.conditions"
          :key="condition.id"
          class="condition-card exact-condition-card"
          :data-condition-id="condition.id"
          tabindex="0"
          role="group"
          :aria-label="conditionLabel('querybuilder.items.conditionN', index)"
          @keydown="onConditionKeydown($event, index)"
        >
          <div class="condition-card-toolbar">
            <span class="subsection-label">{{ conditionLabel('querybuilder.items.conditionN', index) }}</span>
            <div class="inline-actions">
              <button
                type="button"
                class="icon-btn tooltip-trigger"
                :aria-label="conditionLabel('querybuilder.items.moveConditionUp', index)"
                :title="conditionLabel('querybuilder.items.moveConditionUp', index)"
                :data-help="actionHint(conditionLabel('querybuilder.items.moveConditionUp', index))"
                :disabled="index === 0"
                @click="moveCondition(index, -1)"
              >
                <ArrowUp class="w-4 h-4" />
              </button>
              <button
                type="button"
                class="icon-btn tooltip-trigger"
                :aria-label="conditionLabel('querybuilder.items.moveConditionDown', index)"
                :title="conditionLabel('querybuilder.items.moveConditionDown', index)"
                :data-help="actionHint(conditionLabel('querybuilder.items.moveConditionDown', index))"
                :disabled="index === node.conditions.length - 1"
                @click="moveCondition(index, 1)"
              >
                <ArrowDown class="w-4 h-4" />
              </button>
              <button
                type="button"
                class="icon-btn danger tooltip-trigger"
                :aria-label="conditionLabel('querybuilder.items.removeCondition', index)"
                :title="conditionLabel('querybuilder.items.removeCondition', index)"
                :data-help="actionHint(conditionLabel('querybuilder.items.removeCondition', index))"
                @click="removeCondition(index)"
              >
                <Trash2 class="w-4 h-4" />
              </button>
            </div>
          </div>

          <div class="condition-grid">
            <input
              v-model="condition.attr"
              type="text"
              class="builder-input"
              data-role="condition-attr"
              :placeholder="t('querybuilder.nodeEditor.attrPlaceholder', { example: 'word' })"
              :list="attrListId"
            />

            <select v-model="condition.op" class="builder-select" @change="onConditionOperatorChange(condition)">
              <option v-for="operator in tokenOperatorOptions" :key="operator.value" :value="operator.value">
                {{ operatorLabel(operator.value) }}
              </option>
            </select>

            <template v-if="condition.op === 'in'">
              <div class="set-values-editor span-two">
                <div
                  v-for="(literal, setIndex) in condition.setValues"
                  :key="literal.id"
                  class="set-value-row"
                  :data-set-value-id="literal.id"
                  tabindex="0"
                  role="group"
                  :aria-label="conditionLabel('querybuilder.items.setValueN', setIndex)"
                  @keydown="onSetValueKeydown(condition, setIndex, $event)"
                >
                  <select v-model="literal.kind" class="builder-select compact narrow">
                    <option v-for="kind in literalKinds()" :key="kind.value" :value="kind.value">
                      {{ kind.label }}
                    </option>
                  </select>
                  <input
                    v-model="literal.value"
                    type="text"
                    class="builder-input"
                    data-role="set-value-input"
                    :placeholder="t('querybuilder.nodeEditor.setValuePlaceholder')"
                  />
                  <div class="inline-actions">
                    <button
                      type="button"
                      class="icon-btn tooltip-trigger"
                      :aria-label="conditionLabel('querybuilder.items.moveSetValueUp', setIndex)"
                      :title="conditionLabel('querybuilder.items.moveSetValueUp', setIndex)"
                      :data-help="actionHint(conditionLabel('querybuilder.items.moveSetValueUp', setIndex))"
                      :disabled="setIndex === 0"
                      @click="moveSetValue(condition, setIndex, -1)"
                    >
                      <ArrowUp class="w-4 h-4" />
                    </button>
                    <button
                      type="button"
                      class="icon-btn tooltip-trigger"
                      :aria-label="conditionLabel('querybuilder.items.moveSetValueDown', setIndex)"
                      :title="conditionLabel('querybuilder.items.moveSetValueDown', setIndex)"
                      :data-help="actionHint(conditionLabel('querybuilder.items.moveSetValueDown', setIndex))"
                      :disabled="setIndex === condition.setValues.length - 1"
                      @click="moveSetValue(condition, setIndex, 1)"
                    >
                      <ArrowDown class="w-4 h-4" />
                    </button>
                    <button
                      type="button"
                      class="icon-btn tooltip-trigger"
                      :aria-label="conditionLabel('querybuilder.items.removeSetValue', setIndex)"
                      :title="conditionLabel('querybuilder.items.removeSetValue', setIndex)"
                      :data-help="actionHint(conditionLabel('querybuilder.items.removeSetValue', setIndex))"
                      @click="removeSetValue(condition, setIndex)"
                    >
                      <Trash2 class="w-4 h-4" />
                    </button>
                  </div>
                </div>
                <button type="button" class="ghost-action" @click="addSetValue(condition)">
                  <Plus class="w-4 h-4" />
                  {{ t('querybuilder.nodeEditor.addSetValue') }}
                </button>
              </div>
            </template>
            <template v-else>
              <select v-model="condition.scalar.kind" class="builder-select compact narrow">
                <option v-for="kind in literalKinds()" :key="kind.value" :value="kind.value">
                  {{ kind.label }}
                </option>
              </select>
              <input
                v-model="condition.scalar.value"
                type="text"
                class="builder-input"
                data-role="primary-input"
                :placeholder="t('querybuilder.items.value')"
              />
            </template>
          </div>
          <label v-if="canUseCaseFlag(condition)" class="case-flag-toggle">
            <input
              type="checkbox"
              :checked="condition.flags === 'c'"
              @change="toggleConditionCaseFlag(condition, ($event.target as HTMLInputElement).checked)"
            />
            <i18n-t keypath="querybuilder.nodeEditor.caseFlag" tag="span" scope="global">
              <template #flag><code>%c</code></template>
            </i18n-t>
          </label>
          <p class="condition-help"><CodeSpanText :text="tokenConditionExplanation(condition, querySamples)" /></p>
          <p v-if="condition.op !== 'in'" class="literal-help"><CodeSpanText :text="literalExplanation(condition.scalar)" /></p>
        </div>

        <div class="node-action-row">
          <button type="button" class="ghost-action" @click="addCondition">
            <Plus class="w-4 h-4" />
            {{ t('querybuilder.nodeEditor.addCondition') }}
          </button>
        </div>
      </div>

      <div v-else-if="node.type === 'seq' || node.type === 'alt'" class="structured-node-body">
        <div class="structured-hint">
          {{ node.type === 'alt' ? t('querybuilder.nodeEditor.hintAlt') : t('querybuilder.nodeEditor.hintSeq') }}
        </div>
        <i18n-t keypath="querybuilder.nodeEditor.reorderStructured" tag="p" class="reorder-tip" scope="global">
          <template #keys><kbd class="shortcut-kbd">Alt</kbd> + <kbd class="shortcut-kbd">↑</kbd>/<kbd class="shortcut-kbd">↓</kbd></template>
        </i18n-t>
        <div class="structured-list">
          <template v-for="slotIndex in slotIndices()" :key="`slot-${node.id}-${slotIndex}`">
            <div
              class="structured-slot"
              :class="{ 'is-drop-target': structuredDropIndex === slotIndex }"
              :data-structured-slot="slotIndex"
              @pointerdown.stop
              @dragover="handleStructuredSlotDragOver(slotIndex, $event)"
              @drop="handleStructuredSlotDrop(slotIndex, $event)"
            >
              <div class="structured-slot-line" />
              <div class="structured-slot-actions">
                <button
                  v-if="canMoveSelectedChildToSlot(slotIndex)"
                  type="button"
                  class="structured-move-btn"
                  :data-move-slot="slotIndex"
                  @click="moveSelectedChildToSlot(slotIndex)"
                >
                  <ArrowDown class="w-4 h-4" />
                  <span>{{ t('querybuilder.items.moveSelectionHere') }}</span>
                </button>
                <button
                  type="button"
                  class="structured-insert-btn"
                  :data-insert-slot="slotIndex"
                  :aria-expanded="structuredInsertIndex === slotIndex"
                  @click="toggleInsertPalette(slotIndex)"
                >
                  <Plus class="w-4 h-4" />
                  <span>{{ t('querybuilder.items.insertHere') }}</span>
                </button>
              </div>
              <div v-if="structuredInsertIndex === slotIndex" class="structured-insert-actions">
                <button type="button" class="ghost-action" @click="insertStructuredChild(slotIndex, 'tok')">
                  <Plus class="w-4 h-4" />
                  {{ t('querybuilder.nodeEditor.addToken') }}
                </button>
                <button type="button" class="ghost-action" @click="insertStructuredChild(slotIndex, 'seq')">
                  <Plus class="w-4 h-4" />
                  {{ t('querybuilder.nodeEditor.addSequence') }}
                </button>
                <button type="button" class="ghost-action" @click="insertStructuredChild(slotIndex, 'alt')">
                  <Plus class="w-4 h-4" />
                  {{ t('querybuilder.nodeEditor.addAlternative') }}
                </button>
                <button type="button" class="ghost-action" @click="insertStructuredChild(slotIndex, 'quant')">
                  <Plus class="w-4 h-4" />
                  {{ t('querybuilder.nodeEditor.addRepetition') }}
                </button>
                <button type="button" class="ghost-action" @click="insertStructuredChild(slotIndex, 'within')">
                  <Plus class="w-4 h-4" />
                  within(...)
                </button>
                <button type="button" class="ghost-action" @click="insertStructuredChild(slotIndex, 'where')">
                  <Plus class="w-4 h-4" />
                  where(...)
                </button>
              </div>
            </div>

            <div
              v-if="slotIndex < collection().length"
              class="structured-item"
              :data-child-id="collection()[slotIndex]?.id"
              tabindex="0"
              role="group"
              :aria-label="childLabel(slotIndex)"
              @pointerdown.stop="$emit('select-node', collection()[slotIndex]!.id)"
              @focus="$emit('select-node', collection()[slotIndex]!.id)"
              @keydown="onStructuredItemKeydown($event, slotIndex)"
            >
              <div v-if="slotIndex > 0" class="structured-separator">{{ separatorLabel() }}</div>
              <div class="structured-item-header">
                <div class="structured-item-label">{{ childLabel(slotIndex) }}</div>
                <div class="inline-actions">
                  <button
                    type="button"
                    class="drag-handle tooltip-trigger"
                    :data-drag-slot="slotIndex"
                    :aria-label="dragHandleLabel(slotIndex)"
                    :title="dragHandleLabel(slotIndex)"
                    :data-help="actionHint(dragHandleLabel(slotIndex))"
                    draggable="true"
                    @dragstart="handleStructuredDragStart(slotIndex, $event)"
                    @dragend="clearStructuredDrag"
                  >
                    <GripVertical class="w-4 h-4" />
                  </button>
                  <button
                    type="button"
                    class="icon-btn tooltip-trigger"
                    :aria-label="childMoveUpLabel(slotIndex)"
                    :title="childMoveUpLabel(slotIndex)"
                    :data-help="actionHint(childMoveUpLabel(slotIndex))"
                    :disabled="slotIndex === 0"
                    @click="moveIndexedChild(slotIndex, -1)"
                  >
                    <ArrowUp class="w-4 h-4" />
                  </button>
                  <button
                    type="button"
                    class="icon-btn tooltip-trigger"
                    :aria-label="childMoveDownLabel(slotIndex)"
                    :title="childMoveDownLabel(slotIndex)"
                    :data-help="actionHint(childMoveDownLabel(slotIndex))"
                    :disabled="slotIndex === collection().length - 1"
                    @click="moveIndexedChild(slotIndex, 1)"
                  >
                    <ArrowDown class="w-4 h-4" />
                  </button>
                </div>
              </div>
              <CqlNodeEditor
                :node="collection()[slotIndex]!"
                :level="level + 1"
                :meta-field-options="metaFieldOptions"
                :meta-value-choices="metaValueChoices"
                :token-attribute-suggestions="resolvedTokenAttributeSuggestions"
                :selected-node-id="selectedNodeId"
                :selected-meta-id="selectedMetaId"
                removable
                @replace="replaceIndexedChild(slotIndex, $event)"
                @remove="removeIndexedChild(slotIndex)"
                @select-node="$emit('select-node', $event)"
                @select-meta="$emit('select-meta', $event)"
              />
            </div>
          </template>
        </div>
        <div class="node-action-row wrap-actions">
          <button type="button" class="ghost-action" @click="addStructuredChild('tok')">
            <Plus class="w-4 h-4" />
            {{ t('querybuilder.nodeEditor.addToken') }}
          </button>
          <button type="button" class="ghost-action" @click="addStructuredChild('seq')">
            <Plus class="w-4 h-4" />
            {{ t('querybuilder.nodeEditor.addSequence') }}
          </button>
          <button type="button" class="ghost-action" @click="addStructuredChild('alt')">
            <Plus class="w-4 h-4" />
            {{ t('querybuilder.nodeEditor.addAlternative') }}
          </button>
          <button type="button" class="ghost-action" @click="addStructuredChild('quant')">
            <Plus class="w-4 h-4" />
            {{ t('querybuilder.nodeEditor.addRepetition') }}
          </button>
          <button type="button" class="ghost-action" @click="addStructuredChild('within')">
            <Plus class="w-4 h-4" />
            within(...)
          </button>
          <button type="button" class="ghost-action" @click="addStructuredChild('where')">
            <Plus class="w-4 h-4" />
            where(...)
          </button>
        </div>
      </div>

      <div v-else-if="node.type === 'quant'" class="quant-node-body">
        <div class="quant-grid">
          <select class="builder-select" :value="quantifierPreset()" @change="setQuantifierPreset(($event.target as HTMLSelectElement).value)">
            <option value="?">?</option>
            <option value="*">*</option>
            <option value="+">+</option>
            <option value="exact">{m}</option>
            <option value="range">{m,n}</option>
            <option value="open">{m,}</option>
          </select>
          <input v-model.number="node.min" type="number" min="0" class="builder-input narrow-input" />
          <input v-model.number="node.max" type="number" min="0" class="builder-input narrow-input" :disabled="node.max === null" />
          <label class="checkbox-inline">
            <input type="checkbox" :checked="node.max === null" @change="node.max = ($event.target as HTMLInputElement).checked ? null : node.min" />
            {{ t('querybuilder.nodeEditor.quantOpen') }}
          </label>
        </div>
        <p class="condition-help">{{ quantifierExplanation(node.min, node.max) }}</p>
        <div class="embedded-child">
          <CqlNodeEditor
            :node="node.node"
            :level="level + 1"
            :meta-field-options="metaFieldOptions"
            :meta-value-choices="metaValueChoices"
            :token-attribute-suggestions="resolvedTokenAttributeSuggestions"
            :selected-node-id="selectedNodeId"
            :selected-meta-id="selectedMetaId"
            @replace="replaceChild"
            @select-node="$emit('select-node', $event)"
            @select-meta="$emit('select-meta', $event)"
          />
        </div>
      </div>

      <div v-else-if="node.type === 'within'" class="wrapper-node-body">
        <div class="wrapper-grid">
          <select v-model="node.scope" class="builder-select narrow-select">
            <option value="s">&lt;s&gt;</option>
            <option value="doc">&lt;doc&gt;</option>
          </select>
          <span class="wrapper-hint"><CodeSpanText :text="t('querybuilder.nodeEditor.withinScope')" /></span>
        </div>
        <div class="embedded-child">
          <CqlNodeEditor
            :node="node.node"
            :level="level + 1"
            :meta-field-options="metaFieldOptions"
            :meta-value-choices="metaValueChoices"
            :token-attribute-suggestions="resolvedTokenAttributeSuggestions"
            :selected-node-id="selectedNodeId"
            :selected-meta-id="selectedMetaId"
            @replace="replaceChild"
            @select-node="$emit('select-node', $event)"
            @select-meta="$emit('select-meta', $event)"
          />
        </div>
      </div>

      <div v-else class="where-node-body">
        <div class="where-section-header">
          <Filter class="w-4 h-4" />
          <span>{{ t('querybuilder.nodeEditor.whereMeta') }}</span>
        </div>
        <CqlMetaExprEditor
          :expr="node.expr"
          :level="level + 1"
          :meta-field-options="metaFieldOptions"
          :meta-value-choices="metaValueChoices"
          :selected-node-id="selectedNodeId"
          :selected-meta-id="selectedMetaId"
          @replace="node.expr = $event"
          @select-node="$emit('select-node', $event)"
          @select-meta="$emit('select-meta', $event)"
        />

        <div class="where-section-header node-margin-top">
          <ScanSearch class="w-4 h-4" />
          <span>{{ t('querybuilder.nodeEditor.whereQuery') }}</span>
        </div>
        <CqlNodeEditor
          :node="node.node"
          :level="level + 1"
          :meta-field-options="metaFieldOptions"
          :meta-value-choices="metaValueChoices"
          :token-attribute-suggestions="resolvedTokenAttributeSuggestions"
          :selected-node-id="selectedNodeId"
          :selected-meta-id="selectedMetaId"
          @replace="replaceChild"
          @select-node="$emit('select-node', $event)"
          @select-meta="$emit('select-meta', $event)"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
@reference "../../../style.css";

.builder-node-card {
  @apply rounded-2xl border bg-neutral-50 dark:bg-neutral-900/60 p-3 space-y-3;
  @apply border-neutral-200 dark:border-neutral-700;
  margin-left: calc(var(--node-level, 0) * 0.25rem);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.55);
  scroll-margin-top: 1rem;
}

.builder-node-card.is-selected {
  @apply border-primary-400 bg-primary-50/70 ring-2 ring-primary-300 ring-offset-2 ring-offset-white dark:bg-primary-500/10 dark:ring-primary-500 dark:ring-offset-neutral-900;
}

.tone-tok { @apply border-l-4 border-l-emerald-400; }
.tone-seq { @apply border-l-4 border-l-sky-400; }
.tone-alt { @apply border-l-4 border-l-amber-400; }
.tone-quant { @apply border-l-4 border-l-violet-400; }
.tone-within { @apply border-l-4 border-l-cyan-400; }
.tone-where { @apply border-l-4 border-l-rose-400; }

.node-toolbar,
.node-toolbar-main,
.node-toolbar-title,
.node-toolbar-controls,
.where-section-header,
.wrapper-grid,
.node-action-row,
.checkbox-inline,
.inline-actions,
.condition-card-toolbar,
.structured-item-header {
  @apply flex items-center gap-2;
}

.node-toolbar,
.condition-card-toolbar,
.structured-item-header {
  @apply justify-between;
}

.node-toolbar-main {
  @apply min-w-0 flex-1 items-start;
}

.node-toolbar-controls {
  @apply shrink-0 flex-wrap justify-end;
}

.node-title-block {
  @apply min-w-0 flex-1 space-y-1;
}

.node-toolbar-title-row {
  @apply flex items-center gap-2;
}

.node-toolbar-title,
.where-section-header,
.structured-item-label,
.subsection-label {
  @apply text-sm font-semibold text-neutral-900 dark:text-neutral-100;
}

.node-badge {
  @apply rounded-full bg-white/80 dark:bg-neutral-800 px-2.5 py-1 text-[11px] font-medium text-neutral-600 dark:text-neutral-200;
}

.node-preview-chip {
  @apply inline-block max-w-full truncate rounded-full bg-neutral-950 text-emerald-300 px-3 py-1 text-xs;
}

.collapse-btn,
.icon-btn,
.drag-handle,
.ghost-action {
  @apply inline-flex items-center gap-2 rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-700 dark:text-neutral-200 hover:border-primary-300 hover:text-primary-700 transition-colors;
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

.builder-input,
.builder-select {
  @apply rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm text-neutral-900 dark:text-neutral-100;
  @apply focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent;
}

.builder-select.compact { @apply py-1.5; }
.builder-select.narrow,
.narrow-select,
.narrow-input { @apply w-28; }

.node-help,
.condition-help,
.literal-help,
.structured-hint,
.reorder-tip,
.wrapper-hint {
  @apply text-sm leading-6 text-neutral-600 dark:text-neutral-300;
}

.reorder-tip {
  @apply text-xs leading-5 text-neutral-500 dark:text-neutral-400;
}

.shortcut-kbd {
  @apply inline-flex min-w-[1.5rem] items-center justify-center rounded-md border border-neutral-300 bg-white px-1.5 py-0.5 font-mono text-[11px] text-neutral-700 shadow-sm dark:border-neutral-600 dark:bg-neutral-900 dark:text-neutral-200;
}

.node-body,
.token-conditions,
.structured-node-body,
.quant-node-body,
.wrapper-node-body,
.where-node-body,
.structured-list,
.embedded-child,
.set-values-editor {
  @apply space-y-3;
}

.condition-card {
  @apply rounded-xl border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 p-3 space-y-2;
  scroll-margin-top: 1rem;
}

.condition-grid,
.quant-grid {
  @apply grid gap-2;
  grid-template-columns: minmax(0, 1.1fr) minmax(7rem, 8rem) minmax(6rem, 7rem) minmax(0, 1.2fr);
}

.span-two {
  grid-column: span 2;
}

.set-value-row {
  @apply flex items-center gap-2;
}

.structured-separator {
  @apply inline-flex items-center rounded-full bg-neutral-200 dark:bg-neutral-700 px-2 py-1 text-[11px] uppercase tracking-wide text-neutral-600 dark:text-neutral-200;
}

.structured-slot {
  @apply rounded-xl border border-dashed border-neutral-300 dark:border-neutral-700 bg-transparent px-3 py-3 space-y-3 transition-colors;
}

.structured-slot.is-drop-target {
  @apply border-primary-400 bg-primary-50/60 dark:bg-primary-500/10;
}

.structured-slot-line {
  @apply h-px w-full bg-neutral-200 dark:bg-neutral-700;
}

.structured-slot-actions {
  @apply flex flex-wrap gap-2;
}

.structured-insert-btn {
  @apply inline-flex items-center gap-2 rounded-full border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-xs font-semibold text-neutral-700 dark:text-neutral-200 transition-colors hover:border-primary-300 hover:text-primary-700;
}

.structured-move-btn {
  @apply inline-flex items-center gap-2 rounded-full border border-primary-300 bg-primary-50 px-3 py-2 text-xs font-semibold text-primary-900 transition-colors hover:border-primary-400 hover:bg-primary-100 dark:bg-primary-500/10 dark:text-primary-100;
}

.structured-insert-actions {
  @apply flex flex-wrap gap-2;
}

.wrap-actions {
  @apply flex-wrap;
}

.builder-node-card:focus-within,
.condition-card:focus-within,
.structured-slot:focus-within,
.structured-item:focus-within {
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

.node-margin-top {
  @apply mt-4;
}

.where-section-header {
  @apply mb-2;
}

.checkbox-inline {
  @apply text-sm text-neutral-600 dark:text-neutral-300;
}

.case-flag-toggle {
  @apply inline-flex items-center gap-2 text-xs font-medium text-neutral-600 dark:text-neutral-300;
}

.case-flag-toggle code {
  @apply rounded bg-neutral-100 px-1 py-0.5 text-[11px] dark:bg-neutral-800;
}

.any-token-note {
  @apply rounded-lg border border-dashed border-neutral-200 bg-neutral-50 p-3 text-xs text-neutral-600;
  @apply dark:border-neutral-700 dark:bg-neutral-900/60 dark:text-neutral-300;
}

.any-token-note code {
  @apply rounded bg-white px-1 py-0.5 font-mono text-[11px] text-neutral-800 dark:bg-neutral-950 dark:text-neutral-100;
}

@media (max-width: 960px) {
  .builder-node-card,
  .node-body,
  .structured-node-body,
  .structured-list,
  .structured-item,
  .condition-card,
  .set-values-editor {
    overflow-x: clip;
  }

  .node-toolbar {
    @apply flex-wrap items-start;
  }

  .node-toolbar-main,
  .node-toolbar-controls {
    @apply w-full;
  }

  .node-toolbar-controls {
    @apply justify-between;
  }

  .node-toolbar-controls .builder-select.compact {
    @apply min-w-0 flex-1;
  }

  .node-toolbar-title-row {
    @apply flex-wrap;
  }

  .node-preview-chip {
    @apply rounded-2xl whitespace-normal break-words;
  }

  .condition-grid,
  .quant-grid {
    grid-template-columns: 1fr;
  }

  .builder-select.narrow,
  .narrow-select,
  .narrow-input,
  .span-two {
    @apply w-full;
    grid-column: auto;
  }

  .set-value-row {
    @apply flex-wrap;
  }

  .set-value-row > .builder-select,
  .set-value-row > .builder-input,
  .set-value-row > .inline-actions {
    @apply w-full;
  }

  .structured-insert-actions,
  .structured-slot {
    @apply w-full;
  }

  .structured-insert-btn,
  .structured-move-btn,
  .drag-handle {
    @apply w-full justify-center;
  }

  .structured-item-header,
  .condition-card-toolbar {
    @apply flex-wrap items-start;
  }
}
</style>
