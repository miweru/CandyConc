import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { getMcpTools, type McpToolRuntime, type McpToolStatus } from '@/api/client'
import { t } from '@/i18n'

export type McpToolsStatus = 'idle' | 'loading' | 'ready' | 'error'
export type McpOperationRuntimeStatus =
  | 'not_bound'
  | 'loading'
  | 'error'
  | 'available'
  | 'not_listed'
  | 'operation_mismatch'

export interface McpOperationRuntimeDecision {
  status: McpOperationRuntimeStatus
  toolNames: string[]
  listedToolNames: string[]
  missingToolNames: string[]
  misboundToolNames: string[]
  readOnly: boolean | null
  concurrencySafe: boolean | null
  runtimeMetadataStatus: 'verified' | 'missing' | 'mixed' | null
  reason: string | null
}

interface OperationToolBindingLike {
  operationId: string
  copilotTools: string[]
}

function unique(values: Iterable<string | null | undefined>): string[] {
  return [...new Set([...values].filter((value): value is string => Boolean(value)))]
}

function mixedRuntimeStatus(tools: McpToolRuntime[]): 'verified' | 'missing' | 'mixed' | null {
  const statuses = unique(tools.map((tool) => tool.runtime_metadata_status))
  if (!statuses.length) return null
  if (statuses.length === 1 && (statuses[0] === 'verified' || statuses[0] === 'missing')) return statuses[0]
  return 'mixed'
}

export const useMcpToolsStore = defineStore('mcpTools', () => {
  const tools = ref<McpToolRuntime[]>([])
  const toolStatuses = ref<McpToolStatus[]>([])
  const status = ref<McpToolsStatus>('idle')
  const error = ref<string | null>(null)
  let loadPromise: Promise<McpToolRuntime[] | null> | null = null

  const toolsByName = computed(() =>
    new Map(tools.value.map((tool) => [tool.function.name, tool])),
  )

  const toolStatusesByName = computed(() =>
    new Map(toolStatuses.value.map((toolStatus) => [toolStatus.name, toolStatus])),
  )

  const toolsByOperationId = computed(() => {
    const map = new Map<string, McpToolRuntime[]>()
    for (const tool of tools.value) {
      for (const operationId of tool.product_operation_ids ?? []) {
        const current = map.get(operationId) ?? []
        current.push(tool)
        map.set(operationId, current)
      }
    }
    return map
  })

  async function load(force = false): Promise<McpToolRuntime[] | null> {
    if (!force && status.value === 'ready') return tools.value
    if (!force && loadPromise) return loadPromise
    loadPromise = (async () => {
      status.value = 'loading'
      error.value = null
      try {
        const response = await getMcpTools()
        tools.value = response.tools
        toolStatuses.value = response.tool_statuses ?? []
        status.value = 'ready'
        return tools.value
      } catch (err) {
        error.value = err instanceof Error ? err.message : t('copilot.toolStatus.loadFailed')
        status.value = 'error'
        return null
      } finally {
        loadPromise = null
      }
    })()
    return loadPromise
  }

  function toolsForOperation(operationId: string): McpToolRuntime[] {
    return toolsByOperationId.value.get(operationId) ?? []
  }

  function runtimeDecisionForOperation(
    binding: OperationToolBindingLike,
  ): McpOperationRuntimeDecision {
    const toolNames = unique(binding.copilotTools)
    if (!toolNames.length) {
      return {
        status: 'not_bound',
        toolNames: [],
        listedToolNames: [],
        missingToolNames: [],
        misboundToolNames: [],
        readOnly: null,
        concurrencySafe: null,
        runtimeMetadataStatus: null,
        reason: t('copilot.toolStatus.notBound'),
      }
    }
    if (status.value === 'idle' || status.value === 'loading') {
      return {
        status: 'loading',
        toolNames,
        listedToolNames: [],
        missingToolNames: toolNames,
        misboundToolNames: [],
        readOnly: null,
        concurrencySafe: null,
        runtimeMetadataStatus: null,
        reason: t('copilot.toolStatus.loading'),
      }
    }
    if (status.value === 'error') {
      return {
        status: 'error',
        toolNames,
        listedToolNames: [],
        missingToolNames: toolNames,
        misboundToolNames: [],
        readOnly: null,
        concurrencySafe: null,
        runtimeMetadataStatus: null,
        reason: error.value ?? t('copilot.toolStatus.unavailable'),
      }
    }

    const listedTools = toolNames
      .map((name) => toolsByName.value.get(name))
      .filter((tool): tool is McpToolRuntime => Boolean(tool))
    const listedToolNames = listedTools.map((tool) => tool.function.name)
    const missingToolNames = toolNames.filter((name) => !toolsByName.value.has(name))
    const misboundToolNames = listedTools
      .filter((tool) => !(tool.product_operation_ids ?? []).includes(binding.operationId))
      .map((tool) => tool.function.name)
    const allListed = missingToolNames.length === 0
    const allBound = misboundToolNames.length === 0
    return {
      status: allListed && allBound
        ? 'available'
        : allListed
          ? 'operation_mismatch'
          : 'not_listed',
      toolNames,
      listedToolNames,
      missingToolNames,
      misboundToolNames,
      readOnly: listedTools.length ? listedTools.every((tool) => tool.read_only) : null,
      concurrencySafe: listedTools.length ? listedTools.every((tool) => tool.concurrency_safe) : null,
      runtimeMetadataStatus: mixedRuntimeStatus(listedTools),
      reason: allListed && allBound
        ? t('copilot.toolStatus.allAvailable')
        : !allListed
          ? t('copilot.toolStatus.notListed')
          : t('copilot.toolStatus.operationMismatch'),
    }
  }

  return {
    tools,
    toolStatuses,
    status,
    error,
    toolsByName,
    toolStatusesByName,
    toolsByOperationId,
    load,
    toolsForOperation,
    runtimeDecisionForOperation,
  }
})
