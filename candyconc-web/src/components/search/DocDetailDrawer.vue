<script setup lang="ts">
/**
 * DocDetailDrawer - Full document view for KWIC rows
 */
import { computed, nextTick, ref, watch } from 'vue'
import { ClipboardList, Columns2 } from 'lucide-vue-next'
import SlideOver from '@/components/ui/SlideOver.vue'
import type { AlignmentRefDocResult, DocSnippet, Document, ParallelGroupVariant } from '@/api/client'
import { useDocumentAccessOperations } from '@/composables/useDocumentAccessOperations'
import { useParallelOperations } from '@/composables/useParallelOperations'
import { useDocsetStore, useUiStore } from '@/stores'
import { copyTextToClipboard } from '@/lib/kwicCitation'
import AlignmentComparison from '@/components/search/AlignmentComparison.vue'
import { isAnchorSide } from '@/lib/pairSides'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps<{
  modelValue: boolean
  docId: string | null
  corpus?: string
  fallbackLabel?: string
  fallbackMeta?: Record<string, string>
  /** The KWIC match string to highlight in the full document. */
  highlight?: string
  /** Corpus-global token position of the KWIC hit; used as the evidential anchor. */
  highlightPosition?: number
  /** Fallback KWIC-left context while the snippet endpoint is loading or unavailable. */
  highlightLeft?: string
  /** Fallback KWIC-right context while the snippet endpoint is loading or unavailable. */
  highlightRight?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const {
  loadDocSnippet,
  loadDocument: loadDocumentById,
} = useDocumentAccessOperations()
const {
  canOpenAlignment,
  canLoadParallelGroups,
  loadAlignmentRefDoc,
  loadParallelGroups,
} = useParallelOperations()
const docsetStore = useDocsetStore()
const uiStore = useUiStore()
const loading = ref(false)
const error = ref<string | null>(null)
const doc = ref<Document | null>(null)
const anchoredSnippet = ref<DocSnippet | null>(null)
const snippetLoading = ref(false)
const snippetError = ref<string | null>(null)
const comparisonLoading = ref(false)
const comparisonError = ref<string | null>(null)
const alignmentLoading = ref(false)
const alignmentError = ref<string | null>(null)
const alignmentResult = ref<AlignmentRefDocResult | null>(null)
const comparisonReferenceDoc = ref<Document | null>(null)
interface ComparisonVariantOption {
  docId: number
  label: string
  provenance: string
}
const comparisonVariantOptions = ref<ComparisonVariantOption[]>([])
const comparisonVariantDocs = ref<Record<number, Document>>({})
const selectedComparisonVariantIds = ref<number[]>([])
const comparisonVariantLoading = ref(false)
const comparisonVariantError = ref<string | null>(null)
const firstMatchEl = ref<HTMLElement | null>(null)
const SNIPPET_CONTEXT_TOKENS = 40
let loadSerial = 0
let comparisonSerial = 0
let comparisonVariantSelectionSerial = 0

const resolvedCorpus = computed(() => props.corpus ?? docsetStore.activeCorpus)

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/**
 * Split the document text into plain/highlight segments around every occurrence
 * of the KWIC match (case-insensitive). Degrades to a single plain segment when
 * there is no highlight term or no text. The first highlight is tagged so we
 * can scroll it into view once the drawer renders.
 */
const textSegments = computed<Array<{ text: string; match: boolean }>>(() => {
  const text = doc.value?.text ?? ''
  const term = props.highlight?.trim() ?? ''
  if (!text) return []
  if (!term) return [{ text, match: false }]
  let re: RegExp
  try {
    re = new RegExp(escapeRegExp(term), 'gi')
  } catch {
    return [{ text, match: false }]
  }
  const segments: Array<{ text: string; match: boolean }> = []
  let lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    if (m.index > lastIndex) segments.push({ text: text.slice(lastIndex, m.index), match: false })
    segments.push({ text: m[0], match: true })
    lastIndex = m.index + m[0].length
    if (m[0].length === 0) re.lastIndex += 1 // guard against zero-width matches
  }
  if (lastIndex < text.length) segments.push({ text: text.slice(lastIndex), match: false })
  return segments
})

const matchCount = computed(() => textSegments.value.filter((s) => s.match).length)

const hasPositionAnchor = computed(() =>
  typeof props.highlightPosition === 'number' && Number.isFinite(props.highlightPosition)
)

const shouldScrollTextMatch = computed(() =>
  matchCount.value > 0 && (!hasPositionAnchor.value || matchCount.value === 1)
)

const anchorLeft = computed(() => anchoredSnippet.value?.left ?? props.highlightLeft ?? '')
const anchorMatch = computed(() => anchoredSnippet.value?.kw ?? props.highlight?.trim() ?? '')
const anchorRight = computed(() => anchoredSnippet.value?.right ?? props.highlightRight ?? '')

const anchorRangeLabel = computed(() => {
  const snippet = anchoredSnippet.value
  if (!snippet) return ''
  return t('kwic.drawer.anchorRange', { start: snippet.start_pos, end: snippet.end_pos, docStart: snippet.doc_start, docEnd: snippet.doc_end })
})

const anchorDocMismatch = computed(() => {
  const snippet = anchoredSnippet.value
  if (!snippet) return ''
  const openedDocId = doc.value?.doc_id ?? props.docId
  if (openedDocId === undefined || openedDocId === null) return ''
  if (String(snippet.doc_id) === String(openedDocId)) return ''
  return t('kwic.drawer.anchorMismatch', { anchorDoc: snippet.doc_id, openedDoc: openedDocId })
})

function scrollToFirstMatch() {
  if (!shouldScrollTextMatch.value) return
  void nextTick(() => {
    const el = firstMatchEl.value
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ block: 'center' })
    }
  })
}

const meta = computed(() => doc.value?.meta ?? props.fallbackMeta ?? {})

const title = computed(() => {
  // Prefer an author- or corpus-supplied identifier over the often opaque
  // internal document key. The latter remains available in the metadata.
  for (const key of ['title', 'label', 'name']) {
    const value = meta.value[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  const source = typeof meta.value.source === 'string' ? meta.value.source.trim() : ''
  const originId = typeof meta.value.origin_id === 'string' ? meta.value.origin_id.trim() : ''
  const profileName = typeof meta.value.profile_name === 'string' ? meta.value.profile_name.trim() : ''
  const model = typeof meta.value.model === 'string' ? meta.value.model.trim() : ''
  // The anchor of a pair is the text the versions are compared with, it gets
  // no version suffix. Older indexes mark it with model human, newer ones
  // with text_type anchor and its role from the data as model.
  const isAnchor = isAnchorSide(meta.value.text_type) || model.toLowerCase() === 'human'
  const variantIdentity = profileName || (model && !isAnchor ? model : '')
  // A source-prefixed origin id is useful provenance, but repeating the source
  // in the drawer title makes the document heading needlessly opaque. Keep the
  // full origin id in metadata and present the local identifier beside source.
  if (source && originId.startsWith(`${source}:`)) {
    const localId = originId.slice(source.length + 1).trim()
    if (localId) return `${source} · ${localId}${variantIdentity ? ` — ${variantIdentity}` : ''}`
  }
  if (originId) return `${originId}${variantIdentity ? ` — ${variantIdentity}` : ''}`
  if (props.fallbackLabel) return props.fallbackLabel
  if (doc.value?.doc) return doc.value.doc
  if (props.docId) return t('kwic.drawer.documentNumber', { id: props.docId })
  return t('kwic.drawer.document')
})

/**
 * The metadata of the document as the corpus defines it, without field names
 * of a particular project. Fields whose value is the same in every document of
 * the corpus (for example importer defaults such as text_type) do not tell
 * documents apart and are listed separately. Without a known value count, for
 * a document of another corpus or before the schema loaded, every field counts
 * as distinguishing.
 */
const valueCounts = computed(() =>
  resolvedCorpus.value === docsetStore.activeCorpus ? docsetStore.metaFieldValueCounts : {}
)

function hasMetaValue(value: unknown): boolean {
  return value !== null && value !== undefined && String(value).trim() !== ''
}

const metaEntries = computed(() =>
  Object.entries(meta.value)
    .filter(([, value]) => hasMetaValue(value))
    .map(([key, value]) => ({ key, value }))
)

const distinguishingMeta = computed(() =>
  metaEntries.value.filter(({ key }) => {
    const count = valueCounts.value[key]
    return count === null || count === undefined || count > 1
  })
)

const constantMeta = computed(() =>
  metaEntries.value.filter(({ key }) => {
    const count = valueCounts.value[key]
    return typeof count === 'number' && count <= 1
  })
)

function numericDocId(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return Math.trunc(value)
  if (typeof value === 'string' && /^\d+$/.test(value.trim())) return Number.parseInt(value, 10)
  return null
}

// Variant documents carry ref_doc. The reference document itself normally does
// not, so its own doc_id is the correct anchor for the shared alignment route.
const alignmentRefDoc = computed(() =>
  numericDocId(meta.value.ref_doc ?? meta.value.refDoc)
  ?? numericDocId(doc.value?.doc_id ?? props.docId)
)

const canCompareVariants = computed(() =>
  Boolean(doc.value && alignmentRefDoc.value !== null && canOpenAlignment.value && canLoadParallelGroups.value)
)

function comparisonVariantLabel(document: Document): string {
  const metadata = document.meta ?? {}
  return metadata.profile_name?.trim()
    || metadata.variant?.trim()
    || metadata.model?.trim()
    || document.doc
    || t('kwic.drawer.documentId', { id: document.doc_id })
}

function comparisonReferenceLabel(document: Document): string {
  const metadata = document.meta ?? {}
  for (const key of ['title', 'label', 'name']) {
    const value = metadata[key]?.trim()
    if (value) return value
  }
  const source = metadata.source?.trim() ?? ''
  const originId = metadata.origin_id?.trim() ?? ''
  if (source && originId.startsWith(`${source}:`)) {
    const localId = originId.slice(source.length + 1).trim()
    if (localId) return `${source} · ${localId}`
  }
  return originId || document.doc || t('kwic.drawer.documentId', { id: document.doc_id })
}

function comparisonProvenance(document: Document): string {
  const metadata = document.meta ?? {}
  const source = metadata.source?.trim()
  const originId = metadata.origin_id?.trim()
  return [source, originId].filter(Boolean).join(' · ')
}

function comparisonVariantOption(variant: ParallelGroupVariant): ComparisonVariantOption {
  return {
    docId: variant.doc_id,
    label: variant.label?.trim() || t('kwic.drawer.documentId', { id: variant.doc_id }),
    provenance: variant.provenance?.trim() ?? '',
  }
}

function comparisonVariantOptionFromDocument(document: Document): ComparisonVariantOption {
  return {
    docId: document.doc_id,
    label: comparisonVariantLabel(document),
    provenance: comparisonProvenance(document),
  }
}

const selectedComparisonVariants = computed(() =>
  selectedComparisonVariantIds.value
    .map((docId) => {
      const option = comparisonVariantOptions.value.find((candidate) => candidate.docId === docId)
      const document = comparisonVariantDocs.value[docId]
      return option && document ? { option, document } : null
    })
    .filter((item): item is { option: ComparisonVariantOption; document: Document } => item !== null)
)

const hasFullTextComparison = computed(() =>
  Boolean(comparisonReferenceDoc.value && selectedComparisonVariants.value.length > 0)
)

const comparisonVariantCountLabel = computed(() =>
  comparisonVariantOptions.value.length === 1
    ? t('kwic.drawer.oneVariant')
    : t('kwic.drawer.variantCount', { count: comparisonVariantOptions.value.length })
)

async function selectComparisonVariants(docIds: number[]) {
  const validIds = new Set(comparisonVariantOptions.value.map((option) => option.docId))
  const nextIds = [...new Set(docIds)].filter((docId) => validIds.has(docId))
  if (nextIds.length === 0) {
    uiStore.showToast(t('kwic.drawer.keepOneVariant'), 'info')
    return
  }
  selectedComparisonVariantIds.value = nextIds
  const missingIds = nextIds.filter((docId) => !comparisonVariantDocs.value[docId])
  if (missingIds.length === 0) return

  const serial = comparisonVariantSelectionSerial + 1
  comparisonVariantSelectionSerial = serial
  comparisonVariantLoading.value = true
  comparisonVariantError.value = null
  const loaded = await Promise.allSettled(
    missingIds.map(async (docId) => [docId, await loadDocumentById(String(docId), resolvedCorpus.value)] as const),
  )
  if (serial !== comparisonVariantSelectionSerial) return

  const nextDocuments = { ...comparisonVariantDocs.value }
  let failed = 0
  for (const entry of loaded) {
    if (entry.status === 'fulfilled') {
      nextDocuments[entry.value[0]] = entry.value[1]
    } else {
      failed += 1
    }
  }
  comparisonVariantDocs.value = nextDocuments
  if (failed > 0) {
    comparisonVariantError.value = failed === 1
      ? t('kwic.drawer.oneVariantFailed')
      : t('kwic.drawer.variantsFailed', { count: failed })
  }
  comparisonVariantLoading.value = false
}

function toggleComparisonVariant(docId: number) {
  const selected = selectedComparisonVariantIds.value
  const nextIds = selected.includes(docId)
    ? selected.filter((current) => current !== docId)
    : [...selected, docId]
  void selectComparisonVariants(nextIds)
}

function selectAllComparisonVariants() {
  void selectComparisonVariants(comparisonVariantOptions.value.map((option) => option.docId))
}

async function loadFocusedAlignmentEvidence(
  serial: number,
  referenceDocId: number,
  openedDoc: number | null,
) {
  try {
    const result = await loadAlignmentRefDoc({
      refDoc: referenceDocId,
      corpus: resolvedCorpus.value,
      focusPos: props.highlightPosition,
      includeDocIds: openedDoc !== null && openedDoc !== referenceDocId ? [openedDoc] : undefined,
      windowSentences: 24,
      maxVariants: openedDoc === referenceDocId ? 8 : 1,
    })
    if (serial === comparisonSerial) alignmentResult.value = result
  } catch (err) {
    if (serial !== comparisonSerial) return
    const message = err instanceof Error
      ? err.message
      : t('kwic.drawer.sentenceEvidenceUnavailable')
    alignmentError.value = t('kwic.drawer.sentenceCheckUnavailable', { message })
  } finally {
    if (serial === comparisonSerial) alignmentLoading.value = false
  }
}

async function loadVariantComparison() {
  const refDoc = alignmentRefDoc.value
  if (refDoc === null || !canOpenAlignment.value || !canLoadParallelGroups.value) return
  if (comparisonLoading.value || alignmentLoading.value) return
  const serial = comparisonSerial + 1
  comparisonSerial = serial
  comparisonVariantSelectionSerial += 1
  comparisonLoading.value = true
  alignmentLoading.value = hasPositionAnchor.value
  comparisonError.value = null
  comparisonVariantError.value = null
  comparisonVariantLoading.value = false
  alignmentError.value = null
  alignmentResult.value = null
  comparisonReferenceDoc.value = null
  comparisonVariantOptions.value = []
  comparisonVariantDocs.value = {}
  selectedComparisonVariantIds.value = []
  const openedDoc = numericDocId(doc.value?.doc_id ?? props.docId)
  let referenceDocId = refDoc
  try {
    const catalogue = await loadParallelGroups({
      corpus: resolvedCorpus.value,
      refDoc,
      includeAllVariants: true,
      limit: 1,
    })
    if (serial !== comparisonSerial) return
    const group = catalogue.groups.find((candidate) => candidate.ref_doc === refDoc)
    if (!group) {
      throw new Error(t('kwic.drawer.noComparisonGroup'))
    }
    referenceDocId = group.human_doc_id ?? refDoc
    const openedIsReference = openedDoc === referenceDocId
    const options = (group.variants?.length
      ? group.variants.map(comparisonVariantOption)
      : group.variant_doc_ids.map((docId) => ({ docId, label: t('kwic.drawer.documentId', { id: docId }), provenance: '' })))
    if (!openedIsReference && doc.value && !options.some((option) => option.docId === doc.value?.doc_id)) {
      // Keep the document a researcher actually opened selectable even if its
      // metadata was incomplete when the group catalogue was built.
      options.unshift(comparisonVariantOptionFromDocument(doc.value))
    }
    if (options.length === 0) {
      throw new Error(t('kwic.drawer.noComparableVariants'))
    }

    const referenceDocument = openedIsReference
      ? doc.value
      : await loadDocumentById(String(referenceDocId), resolvedCorpus.value)
    if (serial !== comparisonSerial) return

    const initialVariantId = !openedIsReference && openedDoc !== null
      ? openedDoc
      : options[0]!.docId
    const initialVariantDocument = !openedIsReference && doc.value?.doc_id === initialVariantId
      ? doc.value
      : await loadDocumentById(String(initialVariantId), resolvedCorpus.value)
    if (serial !== comparisonSerial) return
    if (!referenceDocument || !initialVariantDocument) {
      throw new Error(t('kwic.drawer.comparisonTextsFailedDot'))
    }

    comparisonReferenceDoc.value = referenceDocument
    comparisonVariantOptions.value = options
    comparisonVariantDocs.value = { [initialVariantId]: initialVariantDocument }
    selectedComparisonVariantIds.value = [initialVariantId]
  } catch (err) {
    if (serial === comparisonSerial) {
      comparisonError.value = err instanceof Error
        ? err.message
        : t('kwic.drawer.comparisonTextsFailed')
      alignmentLoading.value = false
    }
    return
  } finally {
    if (serial === comparisonSerial) comparisonLoading.value = false
  }

  if (hasPositionAnchor.value) {
    // Sentence evidence is useful, but must never hold the researcher away
    // from the already loaded full texts.
    void loadFocusedAlignmentEvidence(serial, referenceDocId, openedDoc)
  }
}

async function loadAnchorSnippet(serial: number) {
  anchoredSnippet.value = null
  snippetError.value = null
  if (!hasPositionAnchor.value) {
    snippetLoading.value = false
    return
  }
  snippetLoading.value = true
  try {
    const snippet = await loadDocSnippet({
      pos: props.highlightPosition as number,
      ctx: SNIPPET_CONTEXT_TOKENS,
      corpus: resolvedCorpus.value,
    })
    if (serial === loadSerial) anchoredSnippet.value = snippet
  } catch (err) {
    if (serial === loadSerial) {
      snippetError.value = err instanceof Error ? err.message : t('kwic.drawer.anchorFailed')
    }
  } finally {
    if (serial === loadSerial) snippetLoading.value = false
  }
}

async function loadDocument(docId: string, serial: number) {
  loading.value = true
  error.value = null
  doc.value = null
  comparisonSerial += 1
  comparisonLoading.value = false
  comparisonError.value = null
  alignmentLoading.value = false
  alignmentError.value = null
  alignmentResult.value = null
  comparisonReferenceDoc.value = null
  comparisonVariantOptions.value = []
  comparisonVariantDocs.value = {}
  selectedComparisonVariantIds.value = []
  comparisonVariantLoading.value = false
  comparisonVariantError.value = null
  const snippetPromise = loadAnchorSnippet(serial)
  try {
    const loadedDoc = await loadDocumentById(docId, resolvedCorpus.value)
    if (serial !== loadSerial) return
    doc.value = loadedDoc
  } catch (err) {
    if (serial === loadSerial) {
      error.value = err instanceof Error ? err.message : t('kwic.drawer.documentFailed')
      doc.value = null
    }
  } finally {
    if (serial === loadSerial) loading.value = false
  }
  await snippetPromise
}

/**
 * The identifier the corpus gives the document: the value of the import's id
 * column (meta doc_id) or, without one, the document label of the index. The
 * server fills meta doc_id with the internal index number when the import had
 * no id column. That number changes with a rebuild and is not a citation.
 */
const corpusDocumentId = computed(() => {
  const internal = doc.value?.doc_id ?? props.docId
  const metaId = String(meta.value.doc_id ?? '').trim()
  if (metaId && metaId !== String(internal ?? '')) return metaId
  const label = doc.value?.doc?.trim() ?? ''
  if (label) return label
  const originId = typeof meta.value.origin_id === 'string' ? meta.value.origin_id.trim() : ''
  return originId || null
})

async function copyDocCitation() {
  const parts: string[] = [title.value]
  const source = meta.value.source
  if (source) parts.push(source)
  const docKey = corpusDocumentId.value
  if (docKey && docKey !== title.value) parts.push(`doc ${docKey}`)
  const citation = parts.filter(Boolean).join(', ')
  const ok = await copyTextToClipboard(citation)
  uiStore.showToast(
    ok ? t('kwic.drawer.citationCopied') : t('kwic.drawer.copyBlocked'),
    ok ? 'success' : 'error',
    ok ? 2000 : 5000
  )
}

watch(
  () => [props.modelValue, props.docId, props.highlightPosition, resolvedCorpus.value] as const,
  ([isOpen, docId]) => {
    if (!isOpen) {
      loadSerial += 1
      comparisonSerial += 1
      comparisonVariantSelectionSerial += 1
      loading.value = false
      snippetLoading.value = false
      comparisonLoading.value = false
      alignmentLoading.value = false
      comparisonError.value = null
      comparisonReferenceDoc.value = null
      comparisonVariantOptions.value = []
      comparisonVariantDocs.value = {}
      selectedComparisonVariantIds.value = []
      comparisonVariantLoading.value = false
      comparisonVariantError.value = null
      return
    }
    if (!docId) {
      loadSerial += 1
      comparisonSerial += 1
      comparisonVariantSelectionSerial += 1
      doc.value = null
      anchoredSnippet.value = null
      snippetError.value = null
      snippetLoading.value = false
      comparisonLoading.value = false
      alignmentLoading.value = false
      comparisonError.value = null
      alignmentError.value = null
      alignmentResult.value = null
      comparisonReferenceDoc.value = null
      comparisonVariantOptions.value = []
      comparisonVariantDocs.value = {}
      selectedComparisonVariantIds.value = []
      comparisonVariantLoading.value = false
      comparisonVariantError.value = null
      error.value = t('kwic.drawer.noDocument')
      return
    }
    const serial = loadSerial + 1
    loadSerial = serial
    void loadDocument(docId, serial)
  },
  { immediate: true }
)
</script>

<template>
  <SlideOver
    :model-value="modelValue"
    :size="hasFullTextComparison ? 'wide' : 'lg'"
    :title="title"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="doc-drawer">
      <div class="doc-meta">
        <div class="doc-meta-aside">
          <!-- The index position, not the identifier the corpus gives the document (meta doc_id). -->
          <span v-if="doc?.doc_id !== undefined" class="doc-id" :title="t('kwic.drawer.indexNumberTitle')">
            {{ t('kwic.drawer.indexNumber', { id: doc.doc_id }) }}
          </span>
          <button
            type="button"
            class="doc-cite-btn"
            :title="t('kwic.drawer.copyCitation')"
            @click="copyDocCitation"
          >
            <ClipboardList class="w-3.5 h-3.5" />
            {{ t('kwic.drawer.cite') }}
          </button>
        </div>
      </div>

      <section v-if="hasPositionAnchor" class="doc-anchor-card" :aria-label="t('kwic.drawer.kwicLine')">
        <div class="doc-anchor-header">
          <span class="doc-anchor-title">{{ t('kwic.drawer.kwicLine') }}</span>
          <span class="doc-anchor-position">{{ t('kwic.drawer.tokenPosition', { position: highlightPosition ?? '' }) }}</span>
        </div>
        <div v-if="snippetLoading" class="doc-anchor-muted">
          {{ t('kwic.drawer.anchorLoading') }}
        </div>
        <div v-if="snippetError" class="doc-anchor-warning">
          {{ snippetError }} {{ t('kwic.drawer.anchorFallback') }}
        </div>
        <div v-if="anchorDocMismatch" class="doc-anchor-warning">
          {{ anchorDocMismatch }}
        </div>
        <div v-if="anchorLeft || anchorMatch || anchorRight" class="doc-anchor-line">
          <span class="doc-anchor-context">{{ anchorLeft }}</span>
          <mark class="kwic-match doc-anchor-match">{{ anchorMatch }}</mark>
          <span class="doc-anchor-context">{{ anchorRight }}</span>
        </div>
        <div v-if="anchorRangeLabel" class="doc-anchor-muted">
          {{ anchorRangeLabel }}
        </div>
        <p class="doc-anchor-note">
          {{ t('kwic.drawer.anchorNote') }}
        </p>
      </section>

      <div v-if="loading" class="doc-loading">
        {{ t('kwic.drawer.documentLoading') }}
      </div>
      <div v-else-if="error" class="doc-error">
        {{ error }}
      </div>
      <div v-else class="doc-content">
        <div v-if="distinguishingMeta.length" class="doc-meta-grid" data-testid="doc-meta">
          <div v-for="entry in distinguishingMeta" :key="entry.key" class="meta-row">
            <span class="meta-key">{{ entry.key }}</span>
            <span class="meta-value">{{ entry.value }}</span>
          </div>
        </div>
        <details v-if="constantMeta.length" class="doc-technical-meta" data-testid="doc-meta-constant">
          <summary>{{ t('kwic.drawer.constantMeta', { count: constantMeta.length }) }}</summary>
          <div class="doc-meta-grid doc-technical-meta-grid">
            <div v-for="entry in constantMeta" :key="entry.key" class="meta-row">
              <span class="meta-key">{{ entry.key }}</span>
              <span class="meta-value">{{ entry.value }}</span>
            </div>
          </div>
        </details>
        <div v-if="highlight" class="doc-hit-summary">
          <span class="doc-hit-term">{{ highlight }}</span>
          <span v-if="matchCount > 0" class="doc-hit-count">
            {{ t('kwic.drawer.textOccurrences', { count: matchCount }, matchCount) }}
          </span>
          <span v-else class="doc-hit-count doc-hit-count-muted">
            {{ t('kwic.drawer.noTextOccurrence') }}
          </span>
          <button
            v-if="shouldScrollTextMatch"
            type="button"
            class="doc-hit-jump"
            @click="scrollToFirstMatch"
          >
            {{ t('kwic.drawer.jumpToHit') }}
          </button>
          <span v-else-if="matchCount > 1" class="doc-hit-caveat">
            {{ t('kwic.drawer.ambiguousMarks') }}
          </span>
        </div>
        <section v-if="canCompareVariants" class="variant-comparison" :aria-label="t('kwic.drawer.variantsTitle')">
          <div class="variant-comparison-head">
            <div>
              <h2 class="variant-comparison-title">{{ t('kwic.drawer.variantsTitle') }}</h2>
              <p class="variant-comparison-note">
                {{ t('kwic.drawer.variantsNote') }}
              </p>
            </div>
            <button
              class="variant-comparison-btn"
              type="button"
              :disabled="comparisonLoading || alignmentLoading"
              @click="loadVariantComparison"
            >
              <Columns2 class="w-3.5 h-3.5" />
              {{ comparisonReferenceDoc ? t('kwic.drawer.refresh') : t('kwic.drawer.compareFullTexts') }}
            </button>
          </div>
          <div v-if="comparisonLoading" class="variant-comparison-status" role="status" aria-live="polite">
            {{ t('kwic.drawer.fullTextsLoading') }}
          </div>
          <div v-else-if="comparisonError" class="variant-comparison-error" role="alert">
            <span>{{ comparisonError }}</span>
            <button type="button" @click="loadVariantComparison">{{ t('kwic.drawer.loadAgain') }}</button>
          </div>
          <template v-else-if="hasFullTextComparison && comparisonReferenceDoc">
            <div class="full-text-comparison" :aria-label="t('kwic.drawer.fullTextComparison')">
              <div class="full-text-comparison-head">
                <div>
                  <h3>{{ t('kwic.drawer.fullTextComparison') }}</h3>
                  <p>
                    {{ t('kwic.drawer.fullTextComparisonNote') }}
                  </p>
                </div>
                <span v-if="alignmentResult" class="full-text-comparison-scope">
                  {{ alignmentResult.alignment_scope === 'complete_document'
                    ? t('kwic.drawer.alignmentComplete')
                    : t('kwic.drawer.alignmentAvailable') }}
                </span>
              </div>
              <div v-if="comparisonVariantOptions.length > 1" class="comparison-variant-picker">
                <div class="comparison-variant-picker-head">
                  <span>{{ t('kwic.drawer.selectVariants') }}</span>
                  <button type="button" @click="selectAllComparisonVariants">
                    {{ t('kwic.drawer.showAll', { count: comparisonVariantCountLabel }) }}
                  </button>
                </div>
                <p>
                  {{ t('kwic.drawer.pickerNote') }}
                </p>
                <div class="comparison-variant-options" :aria-label="t('kwic.drawer.selectedVariants')">
                  <label
                    v-for="option in comparisonVariantOptions"
                    :key="option.docId"
                    class="comparison-variant-choice"
                    :class="{ selected: selectedComparisonVariantIds.includes(option.docId) }"
                  >
                    <input
                      type="checkbox"
                      :checked="selectedComparisonVariantIds.includes(option.docId)"
                      @change="toggleComparisonVariant(option.docId)"
                    >
                    <span>
                      <strong>{{ option.label }}</strong>
                      <small v-if="option.provenance">{{ option.provenance }}</small>
                    </span>
                  </label>
                </div>
                <div v-if="comparisonVariantLoading" class="comparison-variant-load-status" role="status" aria-live="polite">
                  {{ t('kwic.drawer.moreVariantsLoading') }}
                </div>
                <div v-else-if="comparisonVariantError" class="comparison-variant-load-error" role="status">
                  {{ comparisonVariantError }}
                </div>
              </div>
              <div
                class="full-text-comparison-grid"
                :class="{ 'full-text-comparison-grid--multi': selectedComparisonVariants.length > 1 }"
              >
                <article class="full-text-pane">
                  <header>
                    <span class="full-text-pane-kicker">{{ t('kwic.drawer.reference') }}</span>
                    <strong>{{ comparisonReferenceLabel(comparisonReferenceDoc) }}</strong>
                    <small v-if="comparisonProvenance(comparisonReferenceDoc)">
                      {{ comparisonProvenance(comparisonReferenceDoc) }}
                    </small>
                  </header>
                  <div class="full-text-scroll" tabindex="0">
                    {{ comparisonReferenceDoc.text || t('kwic.drawer.noFullText') }}
                  </div>
                </article>
                <article
                  v-for="{ option, document } in selectedComparisonVariants"
                  :key="option.docId"
                  class="full-text-pane"
                >
                  <header>
                    <span class="full-text-pane-kicker">{{ t('kwic.drawer.variant') }}</span>
                    <strong>{{ option.label }}</strong>
                    <small v-if="option.provenance">
                      {{ option.provenance }}
                    </small>
                  </header>
                  <div class="full-text-scroll" tabindex="0">
                    {{ document.text || t('kwic.drawer.noFullText') }}
                  </div>
                </article>
              </div>
            </div>
            <div v-if="alignmentLoading" class="variant-comparison-evidence-status" role="status" aria-live="polite">
              {{ t('kwic.drawer.sentenceCheckRunning') }}
            </div>
            <div v-else-if="alignmentError" class="variant-comparison-evidence-warning" role="status">
              {{ alignmentError }} {{ t('kwic.drawer.fullTextUnchanged') }}
            </div>
            <details v-else-if="alignmentResult" class="alignment-evidence">
              <summary>{{ t('kwic.drawer.openSentenceCheck') }}</summary>
              <p>
                {{ t('kwic.drawer.sentenceCheckNote') }}
              </p>
              <AlignmentComparison :result="alignmentResult" />
            </details>
          </template>
        </section>
        <div v-if="!hasFullTextComparison" class="doc-text">
          <template v-if="textSegments.length">
            <template v-for="(seg, idx) in textSegments" :key="idx">
              <mark
                v-if="seg.match"
                :ref="(el) => { if (shouldScrollTextMatch && idx === textSegments.findIndex((s) => s.match)) firstMatchEl = (el as HTMLElement | null) }"
                class="kwic-match doc-hit"
              >{{ seg.text }}</mark>
              <template v-else>{{ seg.text }}</template>
            </template>
          </template>
          <template v-else>{{ t('kwic.drawer.noText') }}</template>
        </div>
      </div>
    </div>
  </SlideOver>
</template>

<style scoped>
@reference "../../style.css";

.doc-drawer {
  @apply flex flex-col gap-4;
}

.doc-meta {
  @apply flex flex-wrap items-center justify-end gap-2;
}

.doc-meta-aside {
  @apply flex items-center gap-2;
}

.doc-id {
  @apply text-xs font-mono text-neutral-500 dark:text-neutral-400;
}

.doc-cite-btn {
  @apply inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs;
  @apply bg-neutral-100 text-neutral-700 hover:bg-neutral-200;
  @apply dark:bg-neutral-800 dark:text-neutral-300 dark:hover:bg-neutral-700;
  @apply transition-colors;
}

.doc-loading {
  @apply text-sm text-neutral-500 dark:text-neutral-400;
}

.doc-error {
  @apply text-sm text-error-600 dark:text-error-400;
}

.doc-content {
  @apply flex flex-col gap-4;
}

.doc-meta-grid {
  @apply grid gap-2 text-xs;
  /* minmax(0, 1fr): a bare 1fr keeps the longest unbreakable value (a URL)
     as its minimum and pushes the column out of the drawer. */
  grid-template-columns: minmax(120px, auto) minmax(0, 1fr);
}

.doc-technical-meta {
  @apply rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2 text-xs;
  @apply dark:border-neutral-700 dark:bg-neutral-900/50;
}

.doc-technical-meta summary {
  @apply cursor-pointer text-neutral-600 dark:text-neutral-300;
}

.doc-technical-meta-grid {
  @apply mt-2;
}

.meta-row {
  @apply contents;
}

.meta-key {
  @apply text-neutral-500 dark:text-neutral-400;
}

.meta-value {
  @apply text-neutral-700 dark:text-neutral-200;
  min-width: 0;
  overflow-wrap: anywhere;
}

.doc-text {
  @apply text-sm leading-relaxed text-neutral-800 dark:text-neutral-100;
  @apply whitespace-pre-wrap;
}

.doc-hit-summary {
  @apply flex items-center gap-2 text-xs;
  @apply text-neutral-500 dark:text-neutral-400;
}

.doc-hit-jump {
  @apply rounded-md border border-neutral-300 bg-white px-2 py-1 text-xs font-medium text-neutral-700;
  @apply hover:bg-neutral-100 focus:outline-none focus:ring-2 focus:ring-primary-500;
  @apply dark:border-neutral-600 dark:bg-neutral-800 dark:text-neutral-100 dark:hover:bg-neutral-700;
}

.doc-hit-caveat {
  @apply text-[11px] leading-relaxed text-neutral-500 dark:text-neutral-400;
}

.doc-anchor-card {
  @apply rounded-lg border p-3 text-xs;
  @apply border-amber-200 bg-amber-50 text-amber-950;
  @apply dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-100;
}

.doc-anchor-header {
  @apply flex flex-wrap items-center justify-between gap-2 mb-2;
}

.doc-anchor-title {
  @apply font-semibold;
}

.doc-anchor-position {
  @apply font-mono text-[11px] text-amber-700 dark:text-amber-200;
}

.doc-anchor-line {
  @apply flex flex-wrap items-baseline gap-1 leading-relaxed;
}

.doc-anchor-context {
  @apply text-amber-900 dark:text-amber-100;
}

.doc-anchor-match {
  @apply rounded px-1 font-semibold;
  @apply bg-amber-200 text-amber-950 dark:bg-amber-500/40 dark:text-amber-50;
}

.doc-anchor-muted {
  @apply mt-1 text-[11px] text-amber-700 dark:text-amber-200;
}

.doc-anchor-warning {
  @apply mb-2 rounded px-2 py-1 text-[11px];
  @apply bg-amber-100 text-amber-900 dark:bg-amber-900/50 dark:text-amber-100;
}

.doc-anchor-note {
  @apply mt-2 text-[11px] leading-relaxed text-amber-800 dark:text-amber-200;
}

.doc-hit-term {
  @apply font-semibold text-neutral-700 dark:text-neutral-200;
}

.doc-hit-count {
  @apply px-1.5 py-0.5 rounded-full;
  @apply bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200;
}

.doc-hit-count-muted {
  @apply bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300;
}

.variant-comparison {
  @apply space-y-3 rounded-xl border border-neutral-200 bg-neutral-50 p-3;
  @apply dark:border-neutral-700 dark:bg-neutral-900/50;
}

.variant-comparison-head {
  @apply flex flex-wrap items-center justify-between gap-3;
}

.variant-comparison-title {
  @apply text-sm font-semibold text-neutral-800 dark:text-neutral-100;
}

.variant-comparison-note {
  @apply mt-0.5 text-xs text-neutral-500 dark:text-neutral-400;
}

.variant-comparison-btn {
  @apply inline-flex items-center gap-1.5 rounded-md border border-neutral-300 px-2.5 py-1.5 text-xs font-medium;
  @apply text-neutral-700 hover:bg-neutral-200 disabled:cursor-not-allowed disabled:opacity-60;
  @apply dark:border-neutral-600 dark:text-neutral-200 dark:hover:bg-neutral-800;
}

.variant-comparison-status,
.variant-comparison-error {
  @apply rounded-lg px-3 py-2 text-sm;
  @apply bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300;
}

.variant-comparison-error {
  @apply flex flex-wrap items-center gap-2 text-error-600 dark:text-error-300;
}

.variant-comparison-error button {
  @apply rounded-md bg-white px-2 py-0.5 text-xs font-medium text-neutral-700 hover:bg-neutral-100;
  @apply dark:bg-neutral-900 dark:text-neutral-200 dark:hover:bg-neutral-700;
}

.variant-comparison-evidence-status,
.variant-comparison-evidence-warning {
  @apply rounded-lg border border-neutral-200 bg-white px-3 py-2 text-xs leading-relaxed text-neutral-600;
  @apply dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-300;
}

.variant-comparison-evidence-warning {
  @apply border-amber-200 bg-amber-50 text-amber-900;
  @apply dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-100;
}

.full-text-comparison {
  @apply overflow-hidden rounded-lg border border-neutral-200 bg-white;
  @apply dark:border-neutral-700 dark:bg-neutral-950;
}

.full-text-comparison-head {
  @apply flex flex-wrap items-start justify-between gap-3 border-b border-neutral-200 px-4 py-3;
  @apply dark:border-neutral-700;
}

.full-text-comparison-head h3 {
  @apply text-sm font-semibold text-neutral-800 dark:text-neutral-100;
}

.full-text-comparison-head p {
  @apply mt-1 max-w-3xl text-xs leading-relaxed text-neutral-500 dark:text-neutral-400;
}

.full-text-comparison-scope {
  @apply rounded-full bg-emerald-50 px-2 py-1 text-[11px] font-medium text-emerald-800;
  @apply dark:bg-emerald-950/40 dark:text-emerald-200;
}

.full-text-comparison-grid {
  @apply grid gap-px bg-neutral-200;
  @apply dark:bg-neutral-700;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.full-text-comparison-grid--multi {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.full-text-pane {
  @apply flex min-w-0 flex-col bg-white;
  @apply dark:bg-neutral-950;
}

.full-text-pane header {
  @apply flex min-h-20 flex-col border-b border-neutral-200 bg-neutral-50 px-4 py-3;
  @apply dark:border-neutral-700 dark:bg-neutral-900/70;
}

.full-text-pane-kicker {
  @apply text-[11px] font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400;
}

.full-text-pane strong {
  @apply mt-1 text-sm text-neutral-800 dark:text-neutral-100;
}

.full-text-pane small {
  @apply mt-1 truncate text-xs text-neutral-500 dark:text-neutral-400;
}

.full-text-scroll {
  @apply max-h-[62vh] min-h-80 overflow-y-auto px-4 py-4 text-sm leading-7 text-neutral-800;
  @apply whitespace-pre-wrap dark:text-neutral-100;
  overscroll-behavior: contain;
}

.full-text-comparison-grid--multi .full-text-scroll {
  @apply max-h-[42vh] min-h-60;
}

.comparison-variant-picker {
  @apply border-b border-neutral-200 bg-neutral-50 px-4 py-3;
  @apply dark:border-neutral-700 dark:bg-neutral-900/50;
}

.comparison-variant-picker-head {
  @apply flex flex-wrap items-center justify-between gap-2 text-xs font-medium text-neutral-700;
  @apply dark:text-neutral-200;
}

.comparison-variant-picker-head button {
  @apply rounded-md border border-neutral-300 bg-white px-2 py-1 text-xs font-medium text-primary-700;
  @apply hover:bg-primary-50 focus:outline-none focus:ring-2 focus:ring-primary-500;
  @apply dark:border-neutral-600 dark:bg-neutral-950 dark:text-primary-300 dark:hover:bg-neutral-800;
}

.comparison-variant-picker > p {
  @apply mt-1 text-xs leading-relaxed text-neutral-500 dark:text-neutral-400;
}

.comparison-variant-options {
  @apply mt-3 grid gap-2;
  grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
}

.comparison-variant-choice {
  @apply flex min-w-0 cursor-pointer items-start gap-2 rounded-md border border-neutral-200 bg-white px-2.5 py-2;
  @apply hover:border-primary-300 hover:bg-primary-50/50;
  @apply dark:border-neutral-700 dark:bg-neutral-950 dark:hover:border-primary-700 dark:hover:bg-primary-950/20;
}

.comparison-variant-choice.selected {
  @apply border-primary-300 bg-primary-50;
  @apply dark:border-primary-700 dark:bg-primary-950/40;
}

.comparison-variant-choice input {
  @apply mt-0.5 shrink-0 accent-primary-600;
}

.comparison-variant-choice span {
  @apply flex min-w-0 flex-col;
}

.comparison-variant-choice strong {
  @apply truncate text-xs font-medium text-neutral-800 dark:text-neutral-100;
}

.comparison-variant-choice small {
  @apply mt-0.5 truncate text-[11px] text-neutral-500 dark:text-neutral-400;
}

.comparison-variant-load-status,
.comparison-variant-load-error {
  @apply mt-3 text-xs leading-relaxed text-neutral-500 dark:text-neutral-400;
}

.comparison-variant-load-error {
  @apply text-amber-800 dark:text-amber-200;
}

.alignment-evidence {
  @apply rounded-lg border border-dashed border-neutral-300 bg-neutral-50 px-3 py-2;
  @apply dark:border-neutral-600 dark:bg-neutral-900/40;
}

.alignment-evidence summary {
  @apply cursor-pointer text-xs font-medium text-neutral-600 dark:text-neutral-300;
}

.alignment-evidence > p {
  @apply mt-2 text-xs leading-relaxed text-neutral-500 dark:text-neutral-400;
}

.alignment-evidence :deep(.alignment-comparison) {
  @apply mt-3;
}

@media (max-width: 760px) {
  .full-text-comparison-grid,
  .full-text-comparison-grid--multi {
    @apply grid-cols-1;
  }

  .full-text-scroll {
    @apply max-h-[45vh] min-h-64;
  }
}

@media (min-width: 761px) and (max-width: 1100px) {
  .full-text-comparison-grid--multi {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.doc-text .doc-hit {
  @apply rounded px-0.5;
  @apply bg-amber-200 text-amber-950;
  @apply dark:bg-amber-500/40 dark:text-amber-50;
}
</style>
