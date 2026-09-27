/**
 * Copilot Store - AI Assistant state management
 */

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { t } from '@/i18n'
import { formatNumber } from '@/i18n/format'

export type CopilotMode = 'minimized' | 'floating' | 'docked'

// ============================================
// Rezept-Transparenz
// ============================================

/**
 * Humanisierte Namen der acht Analyse-Rezepte (recipe_id aus `copilot.status`
 * und `copilot.done`). Unbekannte IDs werden unveraendert angezeigt, damit
 * neue Backend-Rezepte nie stumm verschwinden.
 */
export const COPILOT_RECIPE_LABELS: Readonly<Record<string, string>> = {
  get frequenz() { return t('copilot.recipes.frequency') },
  get gebrauch_kwic() { return t('copilot.recipes.usageKwic') },
  get assoziation() { return t('copilot.recipes.association') },
  get kontrast() { return t('copilot.recipes.contrast') },
  get verlauf() { return t('copilot.recipes.trend') },
  get profil() { return t('copilot.recipes.profile') },
  get metadaten_struktur() { return t('copilot.recipes.metadataStructure') },
  get exploration_meta() { return t('copilot.recipes.exploration') },
}

/** Humanisierter Rezeptname. `null` = freie Analyse, unbekannte ID = roh. */
export function copilotRecipeLabel(recipeId: string | null): string {
  // Anzeigename fuer einen Turn ohne Rezept (recipe_id = null).
  if (recipeId === null) return t('copilot.recipes.free')
  return COPILOT_RECIPE_LABELS[recipeId] ?? recipeId
}

/**
 * Aufwandsbilanz eines abgeschlossenen Assistant-Turns (aus `copilot.done`).
 * Rein observational, als unaufdringliche Fusszeile der Antwort gerendert.
 */
export interface ChatMessageUsage {
  llmCalls?: number
  transportRetries?: number
  elapsedS?: number
  budgetClass?: string
  /** Timeout-Salvage: Antwort ist eine gekennzeichnete Teilantwort. */
  partial?: boolean
  timeout?: string
  /**
   * Rezept des abgeschlossenen Turns (`null` = freie Analyse). Fehlt das Feld,
   * hat das Backend keine Rezept-Transparenz gemeldet (Alt-Backend).
   */
  recipeId?: string | null
  /** Modellzeit des Turns in Sekunden. */
  llmSeconds?: number
  /** Ihre Aufteilung je Stufe. */
  llmSecondsJeStufe?: Record<string, number>
}

/**
 * Eine durchlaufene Stufe mit ihrer Dauer. Anders als `ChatMessageStatus`
 * bleibt sie NACH dem Turn stehen: die Stufenfolge war bisher fluechtig,
 * `onDone` setzte sie auf `undefined`, und damit verschwand die einzige
 * Spur davon, wo die Zeit geblieben ist.
 */
export interface ChatMessageStage {
  stage: string
  /** Sekunden seit Turnbeginn, an denen die Stufe begann. */
  von: number
  /** Sekunden seit Turnbeginn, an denen sie endete. */
  bis?: number
  /** Modellzeit in dieser Stufe, aus `llm_seconds_je_stufe`. */
  modellSekunden?: number
}

/** Transiente Stufenanzeige an einer laufenden Assistant-Message. */
export interface ChatMessageStatus {
  stage: string
  detail?: string
  /** Aktives Rezept (`null` = freie Analyse, fehlend = Alt-Backend). */
  recipeId?: string | null
}

/**
 * Eine beratende Grounding-Annotation (`copilot.grounding.annotations`).
 * Beratend, nie blockierend: neutral als einklappbarer Hinweis gerendert.
 */
export interface ChatMessageAnnotation {
  rule?: string
  note?: string
}

export interface BelegQuelle {
  id: string
  tool: string
  query: string
  status: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  isStreaming?: boolean
  toolCalls?: ToolCall[]
  clarification?: ClarificationQuestion
  /**
   * Aktueller Turn-Fortschritt (`copilot.status`), nur während des Streamings
   * sichtbar und bei done/error/stop entfernt.
   */
  status?: ChatMessageStatus
  /**
   * Die durchlaufenen Stufen mit ihren Dauern. Bleibt nach dem Turn stehen
   * und traegt die Zeitleiste.
   */
  stages?: ChatMessageStage[]
  /** Aufwandsbilanz des Turns nach `copilot.done`. */
  usage?: ChatMessageUsage
  /**
   * Der Text steht schon, die Gegenlesung laeuft noch.
   *
   * Gesetzt von `copilot.vorlaeufige_antwort` und von `copilot.done` wieder
   * geloescht. Er ist NICHT roh: Referenzen sind aufgeloest, Zitate gegen
   * die Evidenzzeilen geprueft, unbelegte Zahlen gestrichen. Nur die
   * Modellverifikation fehlt, und die kostet ein Vielfaches der Antwort.
   */
  vorlaeufig?: boolean
  /**
   * Beratende Hinweise aus `copilot.grounding.annotations`, unter der Antwort
   * als einklappbarer Block gerendert. Kein Modal, blockiert nichts.
   */
  annotations?: ChatMessageAnnotation[]
  /**
   * Beleg-Map des Deutungspfads (`copilot.grounding.evidence`): id, Werkzeug
   * und Abfrage je Evidenz-Element. Die Beleg-Chips im Antworttext werden
   * dagegen validiert und ihr Klick oeffnet genau diese Abfrage im Tool.
   */
  evidence?: BelegQuelle[]
  /**
   * The stream backing this assistant message failed (timeout / server error /
   * rate limit). The UI surfaces the error text and a retry affordance instead
   * of leaving a blank bubble (id 0). Any tool results already received are
   * preserved on `toolCalls`.
   */
  error?: boolean
  /**
   * The original user prompt that produced this (failed) assistant turn, so the
   * UI can re-send it on retry without the user re-typing.
   */
  retryPrompt?: string
}

export interface ToolCall {
  id: string
  name: string
  arguments: Record<string, unknown>
  status: 'pending' | 'running' | 'success' | 'error'
  result?: unknown
  error?: string
  /**
   * Vom Orchestrator gemessene Dauer des Aufrufs. Sie wurde dort bereits
   * gerechnet und verfiel in ein OTEL-Attribut, das ohne
   * CANDYCONC_ENABLE_OTEL=1 in einen No-Op-Span faellt.
   */
  durationMs?: number
  /** Sekunden seit Turnbeginn, an denen der Aufruf begann. */
  von?: number
  /**
   * Der Aufruf wurde aus dem Zwischenspeicher bedient, es lief keine
   * Abfrage gegen den Index. Muss in jeder Arbeitsansicht als solcher
   * kenntlich sein: ein Zwischenspeicher-Treffer als geleistete Arbeit zu
   * zeigen erzeugt Belege fuer Arbeit, die nicht stattgefunden hat.
   */
  wiederverwendet?: boolean
  /** Der Aufruf wurde uebersprungen. */
  uebersprungen?: boolean
}

export interface ClarificationQuestion {
  id: string
  explanation: string
  options: Array<{
    id: string
    label: string
    value: unknown
  }>
  allowCustom?: boolean
  answered?: boolean
  selectedOption?: string
  /** Timeout in ms (default: DEFAULT_CLARIFICATION_TIMEOUT_MS) */
  timeout?: number
  /** Option ID to select if timeout occurs */
  fallbackOptionId?: string
  /** Timestamp when the clarification expires */
  expiresAt?: number
}

// ============================================
// Autonomy steps
// ============================================

export interface AutonomyStep {
  step: 1 | 2 | 3 | 4
  /** Numeric level sent to the backend as ui_context.autonomy_level. */
  level: number
  label: string
  description: string
}

/**
 * Die vier ehrlichen Autonomiestufen. Sie bilden exakt die reale Backend-
 * Approval-Matrix ab (candyconc_copilot/orchestrator.py,
 * `_should_require_approval` + `_plan_gate_active`):
 *
 *  - Level <= 1: Plan-Gate vor dem ersten Tool-Batch, Ausführung erst nach
 *    Bestätigung (Level <= 2 verlangt zusätzlich Approval für jede Aktion)
 *  - Level 3-5:  Lese-Aktionen laufen frei; nicht umkehrbare Aktionen
 *    (reversible=false) brauchen Approval
 *  - Level 6-8:  frei außer destruktive Aktionstypen
 *    (delete/remove/clear/reset/drop)
 *  - Level 9-10: kein Approval
 *
 * Die Stufen senden die Level 1/4/7/10 — je ein Repräsentant pro Band, damit
 * das numerische `autonomy_level`-Feld API-kompatibel bleibt.
 */
export const AUTONOMY_STEPS: readonly AutonomyStep[] = [
  {
    step: 1,
    level: 1,
    get label() { return t('copilot.autonomy.step1Label') },
    get description() { return t('copilot.autonomy.step1Description') },
  },
  {
    step: 2,
    level: 4,
    get label() { return t('copilot.autonomy.step2Label') },
    get description() { return t('copilot.autonomy.step2Description') },
  },
  {
    step: 3,
    level: 7,
    get label() { return t('copilot.autonomy.step3Label') },
    get description() { return t('copilot.autonomy.step3Description') },
  },
  {
    step: 4,
    level: 10,
    get label() { return t('copilot.autonomy.step4Label') },
    get description() { return t('copilot.autonomy.step4Description') },
  },
] as const

/**
 * Map a numeric autonomy level onto its honest step. The band boundaries are
 * the backend matrix boundaries (<=2 / 3-5 / 6-8 / 9-10), so the description
 * always states what the backend actually does at that level.
 */
export function autonomyStepForLevel(level: number): AutonomyStep {
  if (level <= 2) return AUTONOMY_STEPS[0]!
  if (level <= 5) return AUTONOMY_STEPS[1]!
  if (level <= 8) return AUTONOMY_STEPS[2]!
  return AUTONOMY_STEPS[3]!
}

/** The autonomy level is a setting and stays in this browser across reloads. */
export const AUTONOMY_STORAGE_KEY = 'candyconc_copilot_autonomy'

/** Waiting time of a clarification that brings no timeout of its own. */
export const DEFAULT_CLARIFICATION_TIMEOUT_MS = 60_000

function clampAutonomy(level: number): number {
  return Math.max(0, Math.min(10, level))
}

function readStoredAutonomy(fallback: number): number {
  try {
    const raw = localStorage.getItem(AUTONOMY_STORAGE_KEY)
    if (raw === null) return fallback
    const level = Number(raw)
    return Number.isFinite(level) ? clampAutonomy(level) : fallback
  } catch {
    return fallback
  }
}

export const useCopilotStore = defineStore('copilot', () => {
  // State
  const mode = ref<CopilotMode>('minimized')
  const isOpen = ref(false)
  // Default: Stufe 2 — Lese-Analysen frei, Schreibendes mit Bestätigung.
  const autonomyLevel = ref(readStoredAutonomy(AUTONOMY_STEPS[1]!.level))
  watch(autonomyLevel, (level) => {
    try {
      localStorage.setItem(AUTONOMY_STORAGE_KEY, String(level))
    } catch {
      // Without storage the level still applies in this session.
    }
  })
  const messages = ref<ChatMessage[]>([])
  const isThinking = ref(false)
  const currentStreamingMessage = ref<string>('')

  // Clarification timeout tracking
  const clarificationTimeoutId = ref<ReturnType<typeof setTimeout> | null>(null)

  // Session
  const sessionId = ref<string | null>(null)
  const conversationId = ref<string | null>(null)

  // Computed
  const isMinimized = computed(() => mode.value === 'minimized')
  const isFloating = computed(() => mode.value === 'floating')
  const isDocked = computed(() => mode.value === 'docked')

  const lastMessage = computed(() =>
    messages.value.length > 0 ? messages.value[messages.value.length - 1] : null
  )

  const pendingClarification = computed(() => {
    const last = lastMessage.value
    if (last?.role === 'assistant' && last.clarification && !last.clarification.answered) {
      return last.clarification
    }
    return null
  })

  const autonomyStep = computed(() => autonomyStepForLevel(autonomyLevel.value))

  // EINE Textquelle für das Autonomie-Verhalten; die UI konsumiert nur diese.
  const autonomyDescription = computed(() => autonomyStep.value.description)

  // Actions
  function setMode(newMode: CopilotMode) {
    mode.value = newMode
    if (newMode !== 'minimized') {
      isOpen.value = true
    }
  }

  function open(openMode?: CopilotMode) {
    if (openMode) {
      mode.value = openMode
    } else if (mode.value === 'minimized') {
      mode.value = 'floating'
    }
    isOpen.value = true
  }

  function close() {
    isOpen.value = false
    mode.value = 'minimized'
  }

  function toggle() {
    if (isOpen.value) {
      close()
    } else {
      open()
    }
  }

  /**
   * Set the numeric autonomy level (clamped to 0-10). The UI drives this via
   * the four honest steps; arbitrary numeric levels stay API-compatible.
   */
  function setAutonomyLevel(level: number): void {
    autonomyLevel.value = clampAutonomy(level)
  }

  /** Set autonomy via one of the four honest steps (1-4). */
  function setAutonomyStep(step: number): void {
    const found = AUTONOMY_STEPS.find((entry) => entry.step === step)
    if (found) {
      autonomyLevel.value = found.level
    }
  }

  function addMessage(message: Pick<ChatMessage, 'role' | 'content'> & Partial<Omit<ChatMessage, 'role' | 'content' | 'id' | 'timestamp'>>) {
    // Clear any existing clarification timeout
    if (clarificationTimeoutId.value) {
      clearTimeout(clarificationTimeoutId.value)
      clarificationTimeoutId.value = null
    }

    const newMessage: ChatMessage = {
      id: crypto.randomUUID(),
      timestamp: Date.now(),
      role: message.role,
      content: message.content,
      isStreaming: message.isStreaming,
      toolCalls: message.toolCalls,
      clarification: message.clarification,
      status: message.status,
      usage: message.usage,
      annotations: message.annotations,
      error: message.error,
      retryPrompt: message.retryPrompt
    }

    // Set up clarification timeout if present
    if (newMessage.clarification && !newMessage.clarification.answered) {
      const timeout = newMessage.clarification.timeout ?? DEFAULT_CLARIFICATION_TIMEOUT_MS
      newMessage.clarification.expiresAt = Date.now() + timeout

      clarificationTimeoutId.value = setTimeout(() => {
        handleClarificationTimeout(newMessage.id, newMessage.clarification!, timeout)
      }, timeout)
    }

    messages.value.push(newMessage)
    return newMessage.id
  }

  /**
   * Handle clarification timeout
   */
  function handleClarificationTimeout(messageId: string, clarification: ClarificationQuestion, timeoutMs: number): void {
    if (clarification.answered) return

    if (clarification.fallbackOptionId) {
      // Auto-answer with fallback option
      answerClarification(clarification.id, clarification.fallbackOptionId)
    } else {
      // Mark as timed out and notify
      const msg = messages.value.find(m => m.id === messageId)
      if (msg?.clarification) {
        msg.clarification.answered = true
        msg.clarification.selectedOption = '__timeout__'
      }

      // Add system message about timeout
      // The notice names the time this question actually waited.
      addMessage({
        role: 'system',
        content: t('copilot.store.clarificationTimeout', {
          seconds: formatNumber(timeoutMs / 1000, { maximumFractionDigits: 1 }),
        })
      })
    }

    clarificationTimeoutId.value = null
  }

  function updateMessage(id: string, updates: Partial<Omit<ChatMessage, 'id' | 'timestamp'>>) {
    const idx = messages.value.findIndex(m => m.id === id)
    if (idx !== -1) {
      const existing = messages.value[idx]!
      messages.value[idx] = { ...existing, ...updates }
    }
  }

  function setStreaming(streaming: boolean, content = '') {
    isThinking.value = streaming
    currentStreamingMessage.value = content
  }

  function appendStreamingContent(content: string) {
    currentStreamingMessage.value += content
  }

  function answerClarification(questionId: string, optionId: string) {
    // Clear timeout when answered
    if (clarificationTimeoutId.value) {
      clearTimeout(clarificationTimeoutId.value)
      clarificationTimeoutId.value = null
    }

    const msg = messages.value.find(m => m.clarification?.id === questionId)
    if (msg?.clarification) {
      msg.clarification.answered = true
      msg.clarification.selectedOption = optionId
    }
  }

  /**
   * Get remaining time for current clarification (in ms)
   */
  function getClarificationRemainingTime(): number | null {
    const pending = pendingClarification.value
    if (!pending?.expiresAt) return null
    return Math.max(0, pending.expiresAt - Date.now())
  }

  function clearMessages() {
    messages.value = []
    conversationId.value = null
  }

  function setSession(session: string, conversation?: string) {
    sessionId.value = session
    conversationId.value = conversation ?? null
  }

  return {
    // State
    mode,
    isOpen,
    autonomyLevel,
    messages,
    isThinking,
    currentStreamingMessage,
    sessionId,
    conversationId,
    // Computed
    isMinimized,
    isFloating,
    isDocked,
    lastMessage,
    pendingClarification,
    autonomyStep,
    autonomyDescription,
    // Actions
    setMode,
    open,
    close,
    toggle,
    setAutonomyLevel,
    setAutonomyStep,
    addMessage,
    updateMessage,
    setStreaming,
    appendStreamingContent,
    answerClarification,
    getClarificationRemainingTime,
    clearMessages,
    setSession
  }
})
