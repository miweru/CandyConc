<script setup lang="ts">
/**
 * CopilotPanel - Main chat interface for AI assistant
 *
 * The Copilot is a free-form LLM agent. In release mode, tool access is
 * policy-/MCP-gated; prose is shown as interpretation over computed evidence.
 *
 * M1: Structured Plan/Clarify/ActionPreview UI
 */
import { ref, computed, nextTick, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCopilot } from '@/composables'
import { useCopilotStore } from '@/stores'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useDocsetStore } from '@/stores/docset'
import { useCopilotRezepteStore } from '@/stores/copilotRezepte'
import { buildStarterPrompts, type StarterMetaField } from '@/lib/copilotStarters'
import { X, Send, Minimize2, Dock, Sparkles, History, Beaker, Square, AlertTriangle, RotateCcw, MessageSquarePlus } from 'lucide-vue-next'
import ChatMessage from './ChatMessage.vue'
import ClarificationCard from './ClarificationCard.vue'
// M1 Components
import PlanDisplay from './PlanDisplay.vue'
import ClarifyModal from './ClarifyModal.vue'
import ActionPreviewPanel from './ActionPreviewPanel.vue'
// M2/M3 Components
import RunHistoryPanel from './RunHistoryPanel.vue'
import ResearchToolsPanel from './ResearchToolsPanel.vue'
import CopilotSetupNotice from './CopilotSetupNotice.vue'
import { useCopilotStatus } from '@/composables/useCopilotStatus'

type CopilotTab = 'chat' | 'history' | 'research'

interface Props {
  mode: 'floating' | 'docked' | 'sheet'
}

const props = defineProps<Props>()
const { t } = useI18n()

const copilotStore = useCopilotStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const docsetStore = useDocsetStore()
const recipeStore = useCopilotRezepteStore()
void recipeStore.laden()
// Without a configured model the panel names that state and offers the model
// settings instead of looking ready.
const { isUnconfigured: modelMissing, refresh: refreshCopilotStatus } = useCopilotStatus()
const {
  sendMessage,
  retryMessage,
  answerClarification,
  cancel,
  close,
  isThinking,
  messages,
  pendingClarification,
  // M1: Structured events
  currentPlan,
  currentClarification,
  currentActionPreview,
  researchEvents,
  approveAction,
  rejectAction,
  answerClarificationV1,
  answerClarificationFreeText,
  expireClarification,
  clearPlan,
} = useCopilot()

/**
 * Einen neuen Chat beginnen.
 *
 * ``clearMessages`` setzt die Nachrichten UND die conversationId zurueck.
 * Ohne das zweite haenge der neue Chat am alten Gespraechsfaden des
 * Backends und der Copilot antwortete mit dem Kontext von vorher.
 */
function neuerChat() {
  copilotStore.clearMessages()
  inputValue.value = ''
}

const inputRef = ref<HTMLTextAreaElement | null>(null)
const messagesRef = ref<HTMLElement | null>(null)
const inputValue = ref('')
const activeTab = ref<CopilotTab>('chat')

const isEmpty = computed(() => messages.value.length === 0)

// The most recent failed assistant turn (id 0). When a copilot stream errors or
// times out we surface a clear, retryable notice instead of a blank bubble. The
// guard on `!isThinking` hides the affordance while a retry is in flight.
const failedMessage = computed(() => {
  if (isThinking.value) return null
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const msg = messages.value[i]
    if (msg?.error && msg.retryPrompt) return msg
  }
  return null
})

async function handleRetry() {
  const msg = failedMessage.value
  if (!msg) return
  await retryMessage(msg.id)
}

const tabs: { id: CopilotTab; labelKey: string; icon: typeof Sparkles }[] = [
  { id: 'chat', labelKey: 'copilot.panel.tabChat', icon: Sparkles },
  { id: 'history', labelKey: 'copilot.panel.tabRuns', icon: History },
  { id: 'research', labelKey: 'copilot.panel.tabResearch', icon: Beaker },
]

// Starter questions for the empty chat: examples only, no workflow logic.
// They follow the interface language and name metadata fields of the active
// corpus, read from its metadata schema (lib/copilotStarters).
const starterFields = ref<StarterMetaField[]>([])
async function loadStarterFields() {
  starterFields.value = []
  if (!docsetStore.canLoadMetaSchema) return
  const corpus = corpusCapabilities.activeCorpus
  try {
    const schema = await docsetStore.fetchMetaSchema(corpus)
    if (schema && corpus === corpusCapabilities.activeCorpus) {
      starterFields.value = (schema.metadataFields ?? []) as StarterMetaField[]
    }
  } catch {
    starterFields.value = []
  }
}
watch(() => [corpusCapabilities.activeCorpus, docsetStore.canLoadMetaSchema] as const, () => {
  void loadStarterFields()
}, { immediate: true })
const starterPrompts = computed(() => {
  const questions = Object.values(recipeStore.rezepte)
    .filter((recipe) => recipe.beispiel_frage_quelle === 'korpus' && recipe.im_korpus_beantwortbar !== false)
    .map((recipe) => recipe.beispiel_frage.trim())
    .filter(Boolean)
  if (questions.length) return [...new Set(questions)]
  return buildStarterPrompts({
    hasPos: corpusCapabilities.canUseTokenAttribute('pos'),
    fields: starterFields.value,
  }).map((prompt) => prompt.text)
})

async function handleStarterPrompt(prompt: string) {
  if (modelMissing.value) return
  inputValue.value = prompt
  await handleSubmit()
}

function scrollToBottom() {
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}

// Auto-scroll to bottom when new messages arrive
watch(
  () => messages.value.length,
  async () => {
    await nextTick()
    scrollToBottom()
  }
)

// Auto-scroll while a streaming answer grows, so long answers do not scroll
// off-screen (DT-FE-UX-CORE). We track the last message's content length so the
// view follows the stream without the user having to scroll manually.
watch(
  () => {
    const last = messages.value[messages.value.length - 1]
    return last ? last.content.length : 0
  },
  async () => {
    if (!isThinking.value) return
    await nextTick()
    scrollToBottom()
  }
)

function stopStreaming() {
  cancel()
}

// Focus input when opened
watch(
  () => copilotStore.isOpen,
  (isOpen) => {
    if (isOpen) {
      void refreshCopilotStatus()
      nextTick(() => inputRef.value?.focus())
    }
  },
  { immediate: true }
)

async function handleSubmit() {
  const message = inputValue.value.trim()
  if (!message || isThinking.value || modelMissing.value) return

  inputValue.value = ''
  await sendMessage(message)
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    handleSubmit()
  }
}

function toggleMode() {
  if (props.mode === 'floating') {
    copilotStore.setMode('docked')
  } else {
    copilotStore.setMode('floating')
  }
}
</script>

<template>
  <div 
    class="copilot-panel"
    :class="[`mode-${mode}`]"
  >
    <!-- Header -->
    <header class="panel-header">
      <div class="flex items-center gap-2">
        <Sparkles class="w-5 h-5 text-copilot-primary" />
        <span class="font-medium">Copilot</span>
        <span 
          v-if="isThinking" 
          class="text-xs text-copilot-thinking copilot-thinking"
        >
          {{ t('copilot.panel.thinking') }}
        </span>
      </div>
      
      <div class="flex items-center gap-1">
        <!--
          Ein neuer Chat war bisher nur ueber einen Seitenneuladen zu
          bekommen. Die Funktion lag im Store und hatte keinen Knopf.
        -->
        <button
          class="header-btn"
          :disabled="isThinking || !messages.length"
          :title="t('copilot.panel.newChat')"
          @click="neuerChat"
        >
          <MessageSquarePlus class="w-4 h-4" />
        </button>
        <button
          class="header-btn"
          @click="toggleMode"
          :title="mode === 'floating' ? t('copilot.panel.dock') : t('copilot.panel.undock')"
        >
          <Dock v-if="mode === 'floating'" class="w-4 h-4" />
          <Minimize2 v-else class="w-4 h-4" />
        </button>
        <button
          class="header-btn"
          @click="close"
          :title="t('copilot.panel.closeEsc')"
        >
          <X class="w-4 h-4" />
        </button>
      </div>
    </header>

    <!-- Tabs -->
    <div class="tab-bar">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        class="tab-btn"
        :class="{ active: activeTab === tab.id }"
        @click="activeTab = tab.id"
      >
        <component :is="tab.icon" class="w-4 h-4" />
        <span class="tab-label">{{ t(tab.labelKey) }}</span>
      </button>
    </div>

    <!-- Chat Tab: Messages -->
    <div v-if="activeTab === 'chat'" ref="messagesRef" class="messages-container">
      <CopilotSetupNotice v-if="modelMissing" />
      <!-- Empty State -->
      <div v-if="isEmpty" class="empty-state">
        <Sparkles class="w-12 h-12 text-copilot-primary opacity-50" />
        <h3 class="mt-4 font-medium text-neutral-700 dark:text-neutral-300">
          {{ t('copilot.panel.emptyTitle') }}
        </h3>
        <p class="mt-2 text-sm text-neutral-500">
          {{ t('copilot.panel.emptyText') }}
        </p>
        <div v-if="!modelMissing" class="mt-4 flex flex-wrap gap-2 justify-center">
          <button
            v-for="prompt in starterPrompts"
            :key="prompt"
            class="starter-chip"
            @click="handleStarterPrompt(prompt)"
          >
            {{ prompt }}
          </button>
        </div>
      </div>

      <!-- Message List -->
      <template v-else>
        <ChatMessage
          v-for="msg in messages"
          :key="msg.id"
          :message="msg"
        />

        <!-- M1: Structured Plan Display -->
        <PlanDisplay
          v-if="currentPlan"
          :plan="currentPlan"
          @dismiss="clearPlan"
        />

        <!-- M1: Action Preview Panel (awaiting approval) -->
        <ActionPreviewPanel
          v-if="currentActionPreview"
          :preview="currentActionPreview"
          @approve="approveAction"
          @reject="rejectAction"
        />

        <!-- M1: Structured Clarification Modal -->
        <ClarifyModal
          v-if="currentClarification"
          :question="currentClarification"
          @answer="(optionId, value) => answerClarificationV1(currentClarification!.questionId, optionId, value)"
          @free-input="(text) => answerClarificationFreeText(currentClarification?.questionId ?? null, text)"
          @timeout="() => expireClarification(currentClarification?.questionId ?? null)"
        />

        <!-- V1-Degraded-Pfad: das ClarifyModal ist bereits geschlossen
             (currentClarification geleert), aber die Rückfrage auf der
             Nachricht ist noch offen — die Karte hält sie beantwortbar. -->
        <ClarificationCard
          v-else-if="pendingClarification"
          :question="pendingClarification"
          @answer="(optionId) => answerClarification(pendingClarification!.id, optionId)"
        />

        <!-- Hintergrund-Recherche: dezente, einklappbare Statusanzeige -->
        <details v-if="researchEvents.length" class="research-status">
          <summary class="research-status-summary">
            {{ t('copilot.panel.backgroundResearch', { count: researchEvents.length }) }}
          </summary>
          <ul class="research-status-list">
            <li v-for="entry in researchEvents" :key="entry.id">{{ entry.text }}</li>
          </ul>
        </details>

        <!-- Stream-error retry affordance (id 0): a clear error notice plus a
             retry button. Any already-received tool result stays visible on the
             failed assistant message above; only the prose turn is retried. -->
        <div v-if="failedMessage" class="retry-banner" role="alert">
          <AlertTriangle class="w-4 h-4 flex-shrink-0" />
          <span class="retry-text">
            {{ t('copilot.panel.answerFailed') }}
          </span>
          <button
            class="retry-btn"
            type="button"
            @click="handleRetry"
          >
            <RotateCcw class="w-3.5 h-3.5" />
            <span>{{ t('copilot.panel.retry') }}</span>
          </button>
        </div>
      </template>
    </div>

    <!-- History Tab: Run Records -->
    <div v-else-if="activeTab === 'history'" class="panel-content">
      <RunHistoryPanel />
    </div>

    <!-- Research Tab: Templates, Reproduce, lokaler Run-Export -->
    <div v-else-if="activeTab === 'research'" class="panel-content">
      <ResearchToolsPanel />
    </div>

    <!-- Input (only in chat tab) -->
    <div v-if="activeTab === 'chat'" class="input-container">
      <textarea
        ref="inputRef"
        v-model="inputValue"
        class="message-input"
        :placeholder="modelMissing ? t('copilot.setup.inputDisabled') : t('copilot.panel.inputPlaceholder')"
        rows="1"
        :disabled="isThinking || modelMissing"
        @keydown="handleKeydown"
      />
      <button
        v-if="isThinking"
        class="stop-btn"
        type="button"
        :title="t('copilot.panel.stop')"
        :aria-label="t('copilot.panel.stop')"
        @click="stopStreaming"
      >
        <Square class="w-4 h-4" />
      </button>
      <button
        v-else
        class="send-btn"
        :disabled="!inputValue.trim() || modelMissing"
        @click="handleSubmit"
      >
        <Send class="w-4 h-4" />
      </button>
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.copilot-panel {
  @apply flex flex-col bg-white dark:bg-neutral-900;
  @apply border border-neutral-200 dark:border-neutral-700;
}

.mode-floating {
  @apply fixed bottom-20 right-6;
  @apply w-96 h-[32rem] rounded-xl shadow-2xl;
  z-index: var(--z-copilot);
}

.mode-docked {
  /* The sidebar sets the width. Without min-w-0 the widest content (a toolbar,
     a table) stretched the panel beyond the sidebar and the window. */
  @apply h-full w-full min-w-0;
}

.mode-sheet {
  @apply h-full border-0;
}

.panel-header {
  @apply flex items-center justify-between;
  @apply px-4 py-3;
  @apply border-b border-neutral-200 dark:border-neutral-700;
}

.header-btn {
  @apply p-1.5 rounded-md;
  @apply text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
  @apply transition-colors;
}

/* Tab Bar */
.tab-bar {
  @apply flex items-center gap-1 px-2 py-1;
  @apply border-b border-neutral-200 dark:border-neutral-700;
  @apply bg-neutral-50 dark:bg-neutral-800/50;
}

.tab-btn {
  @apply flex items-center gap-1.5 px-3 py-1.5 rounded-md;
  @apply text-xs font-medium;
  @apply text-neutral-500 dark:text-neutral-400;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-700;
  @apply transition-colors;
}

.tab-btn.active {
  @apply bg-copilot-primary/10 text-copilot-primary;
}

.tab-label {
  @apply hidden sm:inline;
}

.copilot-operations {
  @apply mx-3 my-2;
}

/* Panel Content (for non-chat tabs) */
.panel-content {
  @apply flex-1 overflow-y-auto;
}

.messages-container {
  @apply flex-1 overflow-y-auto p-4;
  @apply space-y-4;
}

.empty-state {
  @apply flex flex-col items-center justify-center h-full;
  @apply text-center px-4;
}

.starter-chip {
  @apply px-3 py-1.5 text-xs rounded-full;
  @apply bg-copilot-bg text-copilot-primary;
  @apply hover:bg-copilot-primary hover:text-white;
  @apply transition-colors cursor-pointer;
  @apply border border-copilot-primary/20;
}

.input-container {
  @apply flex items-end gap-2 p-4;
  @apply border-t border-neutral-200 dark:border-neutral-700;
}

.message-input {
  @apply flex-1 px-3 py-2 rounded-lg;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply text-neutral-900 dark:text-neutral-100;
  @apply placeholder-neutral-500;
  @apply resize-none;
  @apply focus:outline-none focus:ring-2 focus:ring-copilot-primary;
  min-height: 40px;
  max-height: 120px;
}

.send-btn {
  @apply p-2.5 rounded-lg;
  @apply bg-copilot-primary text-white;
  @apply hover:bg-copilot-secondary;
  @apply disabled:opacity-50 disabled:cursor-not-allowed;
  @apply transition-colors;
}

.stop-btn {
  @apply p-2.5 rounded-lg;
  @apply bg-error-500 text-white;
  @apply hover:bg-error-600;
  @apply transition-colors;
}

/* Hintergrund-Recherche-Status (einklappbar, dezent) */
.research-status {
  @apply px-3 py-2 rounded-lg;
  @apply bg-neutral-50 dark:bg-neutral-800/40;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.research-status-summary {
  @apply cursor-pointer select-none font-medium;
}

.research-status-list {
  @apply mt-2 space-y-1 list-disc pl-4;
}

/* Stream-error retry banner (id 0) */
.retry-banner {
  @apply flex items-center gap-2 px-3 py-2 rounded-lg;
  @apply bg-error-50 dark:bg-error-900/20;
  @apply border border-error-200 dark:border-error-800;
  @apply text-error-700 dark:text-error-300;
  @apply text-xs;
}

.retry-text {
  @apply flex-1 min-w-0;
}

.retry-btn {
  @apply inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md;
  @apply bg-error-600 text-white font-medium;
  @apply hover:bg-error-700;
  @apply transition-colors flex-shrink-0;
}
</style>
