/**
 * Whether a language model is configured for the copilot.
 *
 * Without one the chat answers 424 copilot_not_configured only after a
 * question. The panel reads this status first, so that it does not look ready
 * and shows the way to the model settings. One shared state for the app: the
 * panel refreshes it when it opens, the model settings after a change.
 */
import { computed, ref } from 'vue'
import { getCopilotStatus } from '@/api/client'

export type CopilotSetupState = 'unknown' | 'configured' | 'unconfigured'

const state = ref<CopilotSetupState>('unknown')
const model = ref<string | null>(null)
let pending: Promise<void> | null = null

async function refresh(): Promise<void> {
  if (pending) return pending
  pending = (async () => {
    try {
      const status = await getCopilotStatus()
      state.value = status.configured ? 'configured' : 'unconfigured'
      model.value = status.model
    } catch {
      // Unknown (offline, signed out): the chat itself reports the reason.
      state.value = 'unknown'
    } finally {
      pending = null
    }
  })()
  return pending
}

export function useCopilotStatus() {
  return {
    state,
    model,
    isUnconfigured: computed(() => state.value === 'unconfigured'),
    refresh,
  }
}
