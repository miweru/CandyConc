/**
 * Product Capability Store
 *
 * Runtime bridge between the backend-owned Product Capability Contract and the
 * Vue surface registry. Missing contracts only degrade permissively after the
 * session contract proves this is not a release session.
 */

import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import {
  getProductCapabilities,
  type CorpusSummary,
  type ProductCapability,
  type ProductCapabilityBackendRouteDescriptor,
  type ProductCapabilityContract,
  type ProductCapabilityOperation,
  type ProductOperationLifecycle,
} from '@/api/client'
import {
  corpusFeatureDecisionReason,
  corpusFeatureDecisionPartialReason,
  evaluateCapabilityCorpusFeatures,
  type CorpusFeatureDecision,
  type ProductBackendRouteFeaturePredicate,
} from '@/lib/productCorpusFeatures'
import {
  analysisTabSurfaces,
  analysisSurfaceForTab,
  isCapabilityFirstClass,
  isCapabilityNavigable,
  productOperationAdapterPolicyFor,
  surfaceForCapability,
  type ProductOperationAdapterPolicy,
  type ProductOperationExecutionPolicy,
  type ProductOperationGenericAction,
} from '@/lib/productCapabilities'
import {
  isFallbackAnalysisSurface,
  isFallbackAnalysisTab,
  openLabelForSurface,
  openTargetForSurface,
  type ProductSurfaceOpenTarget,
} from '@/lib/productSurfaceRegistry'
import {
  operationSlotMatches,
  productOpenTargetForOperationSlot,
} from '@/lib/productOperationPlacement'
import { actionBus } from '@/actions/bus'
import { useCopilotStore } from './copilot'
import { useSessionStore } from './session'
import { asSwitchTabId, useUiStore, type ActiveTab } from './ui'
import { i18n, t } from '@/i18n'

export type ProductCapabilityLoadStatus =
  | 'idle'
  | 'loading'
  | 'ready'
  | 'error'

export interface ResolvedProductBackendRoute {
  path: string
  methods: string[]
  mutates: boolean
  requiresCorpusFeatures: string[]
  access: string | null
  requiredRole: string | null
  transport: string
  routeClass: string | null
}

export type ProductOperationUiAdapterStatus = 'ready' | 'api_only'

interface ProductOperationAdapterStatusRecord {
  adapterStatus: ProductOperationUiAdapterStatus
  adapterMode: string | null
  adapterReason: string | null
}

export interface ProductCapabilityAccessDecision {
  allowed: boolean
  reason: string | null
}

export type ProductSurfaceAvailabilityStatus =
  | 'usable'
  | 'partial'
  | 'disabled'
  | 'expert_only'
  | 'hidden'
  | 'unmapped'
  | 'loading'

export interface ProductSurfaceAvailabilityDecision {
  status: ProductSurfaceAvailabilityStatus
  visible: boolean
  enabled: boolean
  disabledReason: string | null
  partialReason: string | null
  openLabel: string | null
  corpusFeatureDecision: CorpusFeatureDecision
}

export interface ProductRouteOperationSpec {
  path: string
  method?: string
}

export interface ProductRouteOperationAvailabilityDecision {
  visible: boolean
  enabled: boolean
  disabledReason: string | null
  operations: ProductRouteOperationSpec[]
}

export interface ProductOperationAccessOptions {
  confirmed?: boolean
  contextualConfirmation?: ProductOperationContextualConfirmation
  target?: string
  impact?: string
}

export interface ProductOperationContextualConfirmation {
  surfaceId: string
  interaction: string
  source: 'native_surface' | 'action_context'
  dispatchSource?: string | null
  requestId?: string | null
  runId?: string | null
}

export interface ProductOperationUiRecord {
  capabilityId: string
  operationId: string
  label: string
  description: string
  copilotTools: string[]
  surfaceSlot: string
  effects: string[]
  inputSchemaRef: string
  requiredContext: string[]
  responseShape: string
  runSemantics: string
  lifecycle: ProductOperationLifecycle | null
  contractExecutionPolicy: ProductOperationExecutionPolicy
  route: ResolvedProductBackendRoute
  routeLabel: string
  openTarget: ProductSurfaceOpenTarget | null
  openLabel: string | null
  priority: number
  availability: ProductRouteOperationAvailabilityDecision
  corpusFeatureDecision: CorpusFeatureDecision
  adapterStatus: ProductOperationUiAdapterStatus
  adapterMode: string | null
  adapterReason: string | null
  adapterPolicy: ProductOperationAdapterPolicy
  inspectionAllowed: boolean
  surfaceOpenAllowed: boolean
  genericAction: ProductOperationGenericAction
  executionPolicy: ProductOperationExecutionPolicy
  requiresParameters: boolean
  requiresConfirmation: boolean
  adapterPolicyReason: string | null
}

function operationHasContextSurface(record: ProductOperationUiRecord): boolean {
  return Boolean(
    record.openTarget &&
    record.adapterStatus === 'ready' &&
    record.availability.enabled,
  )
}

export interface ProductOperationLifecycleContract {
  operationId: string
  lifecycle: ProductOperationLifecycle
  kind: ProductOperationLifecycle['kind']
  statusOperationId: string | null
  cancelOperationId: string | null
  rowsOperationId: string | null
  reportsOperationId: string | null
  statusField: string
  progressField: string | null
  messageField: string | null
  errorField: string | null
  rowsStateField: string | null
  readinessField: string | null
  warningsField: string | null
  resultAvailableField: string | null
  resultDiscardedField: string | null
  resultDiscardReasonField: string | null
  terminalStatuses: string[]
}

export function productCapabilityDenied(reason: string): Error {
  const error = new Error(reason)
  error.name = 'ProductCapabilityDeniedError'
  return error
}

/**
 * Error thrown when the user dismisses a confirmation dialog. It is a clean
 * cancel, not a failure — callers should treat it as a no-op (no error toast).
 */
export function productOperationCancelled(reason: string): Error {
  const error = productCapabilityDenied(reason)
  ;(error as Error & { cancelled?: boolean }).cancelled = true
  return error
}

function normalizeBackendRouteDescriptor(
  route: ProductCapabilityBackendRouteDescriptor,
): ResolvedProductBackendRoute {
  return {
    path: route.path,
    methods: route.methods ?? [],
    mutates: Boolean(route.mutates),
    requiresCorpusFeatures: route.requires_corpus_features ?? [],
    access: route.access ?? null,
    requiredRole: route.required_role ?? null,
    transport: route.transport ?? 'http',
    routeClass: route.route_class ?? null,
  }
}

function backendRouteLabel(route: ResolvedProductBackendRoute): string {
  const methods =
    route.transport === 'websocket'
      ? 'WS'
      : route.methods.length
        ? route.methods.join('/')
        : 'Route'
  return `${methods} ${route.path}`
}

function capabilityWithOnlyOperationRoute(
  capability: ProductCapability | undefined,
  operation: ProductCapabilityOperation,
): ProductCapability | undefined {
  if (!capability) return undefined
  return {
    ...capability,
    backend_routes: [operation.route],
    backend_route_descriptors: [operation.route],
  }
}

function operationAdapterStatus(
  capability: ProductCapability | undefined,
  operation: ProductCapabilityOperation,
): ProductOperationAdapterStatusRecord {
  const route = normalizeBackendRouteDescriptor(operation.route)
  if (!capability) {
    return {
      adapterStatus: 'api_only',
      adapterMode: null,
      adapterReason: t('capabilities.store.noCapabilityContext'),
    }
  }
  if (
    capability.visibility !== 'first_class_ui' ||
    capability.maturity === 'unsupported'
  ) {
    return {
      adapterStatus: 'api_only',
      adapterMode: 'api_only',
      adapterReason: t('capabilities.store.expertOnly'),
    }
  }
  return {
    adapterStatus: 'ready',
    adapterMode: operation.run_semantics === 'job_lifecycle'
      ? 'job_lifecycle'
      : route.mutates || (operation.effects ?? []).some((effect) => effect === 'write' || effect === 'destructive')
        ? 'workflow'
        : 'surface',
    adapterReason: null,
  }
}

type BackendRoutePredicate = (route: {
  path: string
  methods?: string[] | null
  mutates?: boolean | null
  transport?: string | null
  access?: string | null
  required_role?: string | null
}) => boolean

type BackendRouteForAccess = Parameters<BackendRoutePredicate>[0]
type ProductRouteAccess = NonNullable<ProductCapabilityBackendRouteDescriptor['access']>
const productRouteAccessValues = new Set<ProductRouteAccess>([
  'public',
  'user',
  'manager',
  'admin',
  'owner_or_admin',
])

function normalizeProductRouteAccess(
  value: string | null | undefined,
): ProductCapabilityBackendRouteDescriptor['access'] {
  if (value == null) return value
  if (!value) return undefined
  return productRouteAccessValues.has(value as ProductRouteAccess)
    ? (value as ProductRouteAccess)
    : undefined
}

function optionalLifecycleString(value: string | null | undefined): string | null {
  const normalized = typeof value === 'string' ? value.trim() : ''
  return normalized || null
}

function toProductRouteDescriptor(
  route: BackendRouteForAccess,
): ProductCapabilityBackendRouteDescriptor {
  return {
    path: route.path,
    methods: route.methods ?? [],
    mutates: Boolean(route.mutates),
    requires_corpus_features: [],
    access: normalizeProductRouteAccess(route.access),
    required_role: route.required_role ?? null,
    transport: route.transport === 'websocket' ? 'websocket' : 'http',
    route_class: null,
  }
}

function toAccessPredicate(
  predicate?: ProductBackendRouteFeaturePredicate,
): BackendRoutePredicate | undefined {
  if (!predicate) return undefined
  return (route) => predicate(toProductRouteDescriptor(route))
}

function operationRouteSpecs(
  operation: ProductCapabilityOperation,
): ProductRouteOperationSpec[] {
  const methods = operation.route.methods ?? []
  if (!methods.length) return [{ path: operation.route.path }]
  return methods.map((method) => ({
    path: operation.route.path,
    method,
  }))
}

function routeMatchesOperation(
  route: BackendRouteForAccess,
  operation: ProductRouteOperationSpec,
): boolean {
  if (route.path !== operation.path) return false
  const normalizedMethod = operation.method?.toUpperCase()
  if (!normalizedMethod) return true
  const methods = route.methods ?? []
  if (!methods.length) return true
  return methods
    .map((candidate) => candidate.toUpperCase())
    .includes(normalizedMethod)
}

function operationReasonLabel(
  _operationId: string,
  fallbackLabel?: string,
): { label: string; suffix: string } {
  if (!fallbackLabel) {
    return { label: t('capabilities.store.requiredServerFunction'), suffix: '' }
  }
  return {
    label: fallbackLabel,
    suffix: '',
  }
}

function defaultConfirmImpact(record: ProductOperationUiRecord): string {
  const effects = new Set(record.effects)
  if (effects.has('destructive')) {
    return t('capabilities.store.impactDestructive')
  }
  if (effects.has('long_running') && effects.has('write')) {
    return t('capabilities.store.impactLongWrite')
  }
  if (effects.has('long_running')) {
    return t('capabilities.store.impactLong')
  }
  if (effects.has('write')) {
    return t('capabilities.store.impactWrite')
  }
  return t('capabilities.store.impactDefault')
}

function confirmProductOperation(label: string, impact: string, target?: string): boolean {
  if (typeof window === 'undefined') return true
  return window.confirm([
    t('capabilities.store.confirmRun', { label }),
    target ? t('capabilities.store.confirmTarget', { target }) : null,
    t('capabilities.store.confirmImpact', { impact }),
  ].filter(Boolean).join('\n'))
}

function preferredModeForOperationSlot(surfaceSlot: string): string | null {
  if (operationSlotMatches(surfaceSlot, 'analysis.contrast.collocations')) return 'collocations'
  if (operationSlotMatches(surfaceSlot, 'analysis.contrast.free')) return 'free'
  if (operationSlotMatches(surfaceSlot, 'analysis.contrast.lexical_diversity')) return 'lexical_diversity'
  if (operationSlotMatches(surfaceSlot, 'analysis.dispersion.offsets')) return 'offset_evidence'

  const parts = surfaceSlot.split('.').map((part) => part.trim()).filter(Boolean)
  return parts.length ? parts[parts.length - 1] ?? null : null
}

export const useProductCapabilitiesStore = defineStore(
  'productCapabilities',
  () => {
    const sessionStore = useSessionStore()
    const contract = ref<ProductCapabilityContract | null>(null)
    const status = ref<ProductCapabilityLoadStatus>('idle')
    const error = ref<string | null>(null)
    let loadPromise: Promise<ProductCapabilityContract | null> | null = null

    // Titles, operation labels and limits come from the server in the
    // interface language. A language switch reloads a contract already held.
    watch(
      () => i18n.global.locale.value,
      () => {
        if (contract.value) void load(true)
      },
    )

    // The contract depends on the sign-in (release mode answers 401 without
    // one). Signing in or out, or a token that runs out, loads it again, as a
    // page reload would, and the contract of the previous state is dropped.
    // Another account needs a sign-out first, so the flip covers it.
    watch(
      () => {
        const session = sessionStore.session
        return session ? (session.authenticated ? 'signed-in' : 'signed-out') : ''
      },
      (state, previous) => {
        if (!previous || state === previous) return
        contract.value = null
        void load(true)
      },
    )

    const capabilities = computed(() => contract.value?.capabilities ?? [])
    const capabilitiesById = computed(
      () =>
        new Map(
          capabilities.value.map((capability) => [capability.id, capability]),
        ),
    )
    const operationsById = computed(
      () =>
        new Map(
          capabilities.value.flatMap((capability) =>
            (capability.operations ?? []).map((operation) =>
              [operation.id, { ...operation, capability_id: operation.capability_id || capability.id }] as const,
            ),
          ),
        ),
    )
    const hasContract = computed(() => Boolean(contract.value))
    const allowsMissingContractFallback = computed(
      () =>
        !contract.value &&
        sessionStore.isAuthoritative &&
        !sessionStore.session?.release_mode,
    )

    const discoverableAnalysisTabs = computed(() =>
      analysisTabSurfaces.filter((surface) => {
        if (!contract.value) {
          return allowsMissingContractFallback.value && isFallbackAnalysisSurface(surface)
        }
        return isSurfaceDiscoverable(surface.capabilityId)
      }),
    )

    const operationUiRecords = computed<ProductOperationUiRecord[]>(() =>
      capabilities.value
        .flatMap((capability) =>
          (capability.operations ?? []).map((operation) =>
            toOperationUiRecord(capability, operation),
          ),
        )
        .sort((a, b) =>
          `${a.capabilityId}:${a.routeLabel}:${a.operationId}`.localeCompare(
            `${b.capabilityId}:${b.routeLabel}:${b.operationId}`,
          ),
        ),
    )
    const firstClassOperationUiRecords = computed(() =>
      operationUiRecords.value.filter((record) => {
        const capability = capabilityFor(record.capabilityId)
        return isCapabilityFirstClass(capability)
      }),
    )

    function loadedContractRequiresSession(): boolean {
      return capabilities.value.some((capability) =>
        (capability.backend_route_descriptors ?? []).some((route) =>
          Boolean(route.required_role || (route.access && route.access !== 'public')),
        ),
      )
    }

    async function ensureAccessContext(
      force = false,
    ): Promise<ProductCapabilityContract | null> {
      const nextContract = await load(force)
      if (nextContract) {
        if (loadedContractRequiresSession() && !sessionStore.isAuthoritative) {
          await sessionStore.load().catch(() => null)
        }
        return nextContract
      }
      if (!sessionStore.isAuthoritative) {
        await sessionStore.load().catch(() => null)
      }
      return contract.value
    }

    async function load(
      force = false,
    ): Promise<ProductCapabilityContract | null> {
      if (!force && contract.value) return contract.value
      if (!force && loadPromise) return loadPromise

      loadPromise = (async () => {
        status.value = 'loading'
        error.value = null
        try {
          contract.value = await getProductCapabilities()
          status.value = 'ready'
          return contract.value
        } catch (err) {
          error.value =
            err instanceof Error
              ? err.message
              : t('capabilities.store.loadFailed')
          status.value = 'error'
          return contract.value
        } finally {
          loadPromise = null
        }
      })()

      return loadPromise
    }

    function capabilityFor(id: string): ProductCapability | undefined {
      return capabilitiesById.value.get(id)
    }

    function operationFor(id: string): ProductCapabilityOperation | undefined {
      return operationsById.value.get(id)
    }

    function operationForRoute(
      capabilityId: string,
      path: string,
      method?: string,
    ): ProductCapabilityOperation | undefined {
      const capability = capabilityFor(capabilityId)
      if (!capability) return undefined
      const route: BackendRouteForAccess = {
        path,
        methods: method ? [method] : [],
      }
      return (capability.operations ?? [])
        .find((operation) =>
          operationRouteSpecs(operation)
            .some((spec) => routeMatchesOperation(route, spec))
        )
    }

    function operationLifecycleFor(id: string): ProductOperationLifecycle | null {
      return operationFor(id)?.lifecycle ?? null
    }

    function operationLifecycleContractFor(id: string): ProductOperationLifecycleContract | null {
      const lifecycle = operationLifecycleFor(id)
      if (!lifecycle) return null
      return {
        operationId: id,
        lifecycle,
        kind: lifecycle.kind,
        statusOperationId: optionalLifecycleString(lifecycle.status_operation_id),
        cancelOperationId: optionalLifecycleString(lifecycle.cancel_operation_id),
        rowsOperationId: optionalLifecycleString(lifecycle.rows_operation_id),
        reportsOperationId: optionalLifecycleString(lifecycle.reports_operation_id),
        statusField: optionalLifecycleString(lifecycle.status_field) ?? 'status',
        progressField: optionalLifecycleString(lifecycle.progress_field),
        messageField: optionalLifecycleString(lifecycle.message_field),
        errorField: optionalLifecycleString(lifecycle.error_field),
        rowsStateField: optionalLifecycleString(lifecycle.rows_state_field),
        readinessField: optionalLifecycleString(lifecycle.readiness_field),
        warningsField: optionalLifecycleString(lifecycle.warnings_field),
        resultAvailableField: optionalLifecycleString(lifecycle.result_available_field),
        resultDiscardedField: optionalLifecycleString(lifecycle.result_discarded_field),
        resultDiscardReasonField: optionalLifecycleString(lifecycle.result_discard_reason_field),
        terminalStatuses: (lifecycle.terminal_statuses ?? [])
          .map((status) => status.trim().toLowerCase())
          .filter(Boolean),
      }
    }

    function toOperationUiRecord(
      capability: ProductCapability,
      operation: ProductCapabilityOperation,
      summary?: CorpusSummary | null,
    ): ProductOperationUiRecord {
      const normalizedOperation: ProductCapabilityOperation = {
        ...operation,
        capability_id: operation.capability_id || capability.id,
      }
      const surface = surfaceForCapability(normalizedOperation.capability_id)
      const adapter = operationAdapterStatus(capability, normalizedOperation)
      const route = normalizeBackendRouteDescriptor(normalizedOperation.route)
      const surfaceOpenTarget = openTargetForSurface(surface)
      const openTarget = productOpenTargetForOperationSlot(
        normalizedOperation.surface_slot,
        surfaceOpenTarget,
      )
      const operationCapability = capabilityWithOnlyOperationRoute(capability, normalizedOperation)
      const adapterPolicy = productOperationAdapterPolicyFor(
        normalizedOperation,
        adapter.adapterStatus,
        adapter.adapterReason,
      )
      const inputSchemaRef = normalizedOperation.input_schema_ref
      const requiredContext = (normalizedOperation.required_context ?? []).filter((item) => Boolean(item))
      return {
        capabilityId: normalizedOperation.capability_id,
        operationId: normalizedOperation.id,
        label: normalizedOperation.label,
        description: normalizedOperation.description,
        copilotTools: normalizedOperation.copilot_tools ?? [],
        surfaceSlot: normalizedOperation.surface_slot,
        effects: normalizedOperation.effects ?? [],
        inputSchemaRef,
        requiredContext,
        responseShape: normalizedOperation.response_shape,
        runSemantics: normalizedOperation.run_semantics,
        lifecycle: normalizedOperation.lifecycle ?? null,
        contractExecutionPolicy: adapterPolicy.executionPolicy,
        route,
        routeLabel: backendRouteLabel(route),
        openTarget,
        openLabel: openLabelForSurface(surface),
        priority: normalizedOperation.priority ?? 100,
        availability: productOperationAvailability(normalizedOperation.id, undefined, summary),
        corpusFeatureDecision: summary === undefined
          ? evaluateCapabilityCorpusFeatures(undefined, null)
          : evaluateCapabilityCorpusFeatures(operationCapability, summary),
        adapterStatus: adapter.adapterStatus,
        adapterMode: adapter.adapterMode,
        adapterReason: adapter.adapterReason,
        adapterPolicy,
        inspectionAllowed: adapterPolicy.inspectionAllowed,
        surfaceOpenAllowed: adapterPolicy.surfaceOpenAllowed,
        genericAction: adapterPolicy.genericAction,
        executionPolicy: adapterPolicy.executionPolicy,
        requiresParameters: adapterPolicy.requiresParameters,
        requiresConfirmation: adapterPolicy.requiresConfirmation,
        adapterPolicyReason: adapterPolicy.reason,
      }
    }

    function operationUiRecordFor(
      operationId: string,
      summary?: CorpusSummary | null,
    ): ProductOperationUiRecord | undefined {
      if (summary === undefined) {
        return operationUiRecords.value.find((record) => record.operationId === operationId)
      }
      const operation = operationFor(operationId)
      if (!operation) return undefined
      const capability = capabilityFor(operation.capability_id)
      return capability ? toOperationUiRecord(capability, operation, summary) : undefined
    }

    function isVisible(id: string): boolean {
      if (!contract.value) return allowsMissingContractFallback.value
      const capability = capabilityFor(id)
      return (
        isCapabilityNavigable(capability) &&
        sessionStore.canAccessAnyRoute(capability)
      )
    }

    function isFallbackSurface(id: string): boolean {
      const surface = surfaceForCapability(id)
      return Boolean(
        surface &&
        surface.kind === 'analysis_tab' &&
        surface.tab &&
        isFallbackAnalysisTab(surface.tab),
      )
    }

    function isSurfaceDiscoverable(id: string): boolean {
      if (!surfaceForCapability(id)) return false
      if (!contract.value) {
        return allowsMissingContractFallback.value && isFallbackSurface(id)
      }
      return isCapabilityNavigable(capabilityFor(id))
    }

    function isSurfaceAccessible(id: string, predicate?: BackendRoutePredicate): boolean {
      if (!contract.value) {
        return allowsMissingContractFallback.value && isFallbackSurface(id)
      }
      return predicate ? isRouteVisible(id, predicate) : isVisible(id)
    }

    function isRouteVisible(
      id: string,
      predicate: BackendRoutePredicate,
    ): boolean {
      if (!contract.value) return allowsMissingContractFallback.value
      const capability = capabilityFor(id)
      return (
        isCapabilityNavigable(capability) &&
        sessionStore.canAccessAnyRoute(capability, predicate)
      )
    }

    function routeOperationPredicate(
      path: string,
      method?: string,
    ): BackendRoutePredicate {
      return (route) =>
        routeMatchesOperation(route, { path, method })
    }

    function accessBlockReason(
      id: string,
      label?: string,
      predicate?: BackendRoutePredicate,
    ): string | null {
      if (!contract.value) return null
      const capability = capabilityFor(id)
      if (!isCapabilityNavigable(capability)) {
        return t('capabilities.store.notSurface', { label: label ?? capability?.title ?? id })
      }
      return sessionStore.accessBlockReason(
        capability,
        label ?? capability?.title ?? id,
        predicate,
      )
    }

    function fallbackBlockReason(id: string, label?: string): string {
      return t('capabilities.store.notEnabledContext', { label: label ?? capabilityFor(id)?.title ?? id })
    }

    async function ensureCapabilityAccess(
      id: string,
      label?: string,
      predicate?: BackendRoutePredicate,
    ): Promise<ProductCapabilityAccessDecision> {
      await ensureAccessContext()
      const allowed = predicate ? isRouteVisible(id, predicate) : isVisible(id)
      if (allowed) return { allowed: true, reason: null }
      return {
        allowed: false,
        reason: accessBlockReason(id, label, predicate) ?? fallbackBlockReason(id, label),
      }
    }

    function productOperationAvailability(
      operationId: string,
      fallbackLabel?: string,
      summary?: CorpusSummary | null,
    ): ProductRouteOperationAvailabilityDecision {
      if (!contract.value) {
        const { label, suffix } = operationReasonLabel(operationId, fallbackLabel)
        return {
          visible: false,
          enabled: false,
          disabledReason: t('capabilities.store.waitingForCatalogue', { label, suffix }),
          operations: [],
        }
      }
      const operation = operationFor(operationId)
      if (!operation) {
        const { label, suffix } = operationReasonLabel(operationId, fallbackLabel)
        return {
          visible: false,
          enabled: false,
          disabledReason: t('capabilities.store.notServerFunction', { label, suffix }),
          operations: [],
        }
      }
      const capability = capabilityFor(operation.capability_id)
      const label = fallbackLabel ?? operation.label
      const visible = isCapabilityNavigable(capability)
      const operationCapability = capabilityWithOnlyOperationRoute(capability, operation)
      const accessReason = visible
        ? sessionStore.accessBlockReason(operationCapability, label)
        : null
      const corpusReason = visible && !accessReason && summary !== undefined
        ? corpusFeatureDecisionReason(
            label,
            evaluateCapabilityCorpusFeatures(operationCapability, summary),
          )
        : null
      return {
        visible,
        enabled: visible && !accessReason && !corpusReason,
        disabledReason: !visible
          ? t('capabilities.store.notSurface', { label })
          : accessReason ?? corpusReason,
        operations: operationRouteSpecs(operation),
      }
    }

    async function assertProductOperationAccess(
      operationId: string,
      fallbackLabel?: string,
      options: ProductOperationAccessOptions = {},
    ): Promise<ProductRouteOperationAvailabilityDecision> {
      await ensureAccessContext()
      const record = operationUiRecordFor(operationId)
      const availability = record?.availability
        ?? productOperationAvailability(operationId, fallbackLabel)
      if (!availability.enabled) {
        throw productCapabilityDenied(
          availability.disabledReason
            ?? t('capabilities.store.notEnabledCatalogue', { label: fallbackLabel ?? operationId }),
        )
      }
      const contextualConfirmation = options.contextualConfirmation
      const hasContextualConfirmation = Boolean(
        contextualConfirmation?.surfaceId?.trim() &&
        contextualConfirmation?.interaction?.trim(),
      )
      if (record?.requiresConfirmation && !options.confirmed && !hasContextualConfirmation) {
        const confirmed = confirmProductOperation(
          fallbackLabel ?? record.label,
          options.impact ?? defaultConfirmImpact(record),
          options.target,
        )
        if (!confirmed) {
          throw productOperationCancelled(
            t('capabilities.store.notConfirmed', { label: fallbackLabel ?? record.label }),
          )
        }
      }
      return availability
    }

    function isAnalysisTabVisible(tab: string): boolean {
      const surface = analysisSurfaceForTab(tab)
      if (!surface) return false
      if (!contract.value) {
        return allowsMissingContractFallback.value && isFallbackAnalysisTab(tab)
      }
      return isVisible(surface.capabilityId)
    }

    function corpusFeatureDecision(
      id: string,
      summary: CorpusSummary | null,
      predicate?: ProductBackendRouteFeaturePredicate,
    ): CorpusFeatureDecision {
      return evaluateCapabilityCorpusFeatures(capabilityFor(id), summary, predicate)
    }

    function analysisTabAvailability(
      tab: string,
      summary: CorpusSummary | null = null,
    ): ProductSurfaceAvailabilityDecision {
      const surface = analysisSurfaceForTab(tab)
      if (!surface) {
        return {
          status: 'unmapped',
          visible: false,
          enabled: false,
          disabledReason: t('capabilities.store.tabUnmapped', { tab }),
          partialReason: null,
          openLabel: null,
          corpusFeatureDecision: evaluateCapabilityCorpusFeatures(undefined, summary),
        }
      }
      return surfaceAvailability(surface.capabilityId, summary)
    }

    function surfaceAvailability(
      id: string,
      summary: CorpusSummary | null = null,
      predicate?: ProductBackendRouteFeaturePredicate,
    ): ProductSurfaceAvailabilityDecision {
      const surface = surfaceForCapability(id)
      const capability = capabilityFor(id)
      const label = surface?.label ?? capability?.title ?? id
      const openLabel = openLabelForSurface(surface)
      const accessPredicate = toAccessPredicate(predicate)
      const corpusDecision = evaluateCapabilityCorpusFeatures(
        capability,
        summary,
        predicate,
      )
      if (!surface || !openTargetForSurface(surface)) {
        const isHidden = capability?.visibility === 'hidden_experimental' ||
          ['planned', 'unsupported'].includes(capability?.maturity ?? '')
        const status: ProductSurfaceAvailabilityStatus = !surface
          ? capability?.visibility === 'first_class_ui'
            ? 'unmapped'
            : isHidden
              ? 'hidden'
              : 'expert_only'
          : isHidden
            ? 'hidden'
            : 'expert_only'
        return {
          status,
          visible: false,
          enabled: false,
          disabledReason: t('capabilities.store.noSurface', { label }),
          partialReason: null,
          openLabel,
          corpusFeatureDecision: corpusDecision,
        }
      }

      const visible = isSurfaceDiscoverable(id)
      const productReason = visible
        ? null
        : !contract.value
          ? t('capabilities.store.waitingForCatalogue', { label, suffix: '' })
          : fallbackBlockReason(id, label)
      const accessReason = visible && !isSurfaceAccessible(id, accessPredicate)
        ? accessBlockReason(id, label, accessPredicate) ?? fallbackBlockReason(id, label)
        : null
      const corpusReason = visible && !accessReason
        ? corpusFeatureDecisionReason(label, corpusDecision)
        : null
      const disabledReason = productReason ?? accessReason ?? corpusReason
      const partialReason = !disabledReason
        ? corpusFeatureDecisionPartialReason(label, corpusDecision)
        : null
      const availabilityStatus: ProductSurfaceAvailabilityStatus = !visible
        ? !contract.value
          ? 'loading'
          : capability?.visibility === 'hidden_experimental' ||
              ['planned', 'unsupported'].includes(capability?.maturity ?? '')
            ? 'hidden'
            : capability?.visibility !== 'first_class_ui'
              ? 'expert_only'
              : 'disabled'
        : disabledReason
          ? 'disabled'
          : partialReason
            ? 'partial'
            : 'usable'
      return {
        status: availabilityStatus,
        visible,
        enabled: visible && !disabledReason,
        disabledReason,
        partialReason,
        openLabel,
        corpusFeatureDecision: corpusDecision,
      }
    }

    async function dispatchTabSwitch(tab: ActiveTab): Promise<boolean> {
      const result = await actionBus.dispatch(
        { type: 'nav/switchTab', payload: { tab: asSwitchTabId(tab) } },
        { source: 'user' },
      )
      return Boolean(result?.success)
    }

    async function applyOpenTarget(target: ProductSurfaceOpenTarget): Promise<boolean> {
      const uiStore = useUiStore()
      if (target.kind === 'analysis_tab') {
        return dispatchTabSwitch(target.tab)
      }
      if (target.kind === 'query_builder') {
        uiStore.openQueryBuilder()
        return true
      }
      if (target.kind === 'kwic_tab') {
        return dispatchTabSwitch('kwic')
      }
      if (target.kind === 'subcorpus_drawer') {
        uiStore.openSubcorpus()
        return true
      }
      if (target.kind === 'corpus_manager') {
        uiStore.openCorpusManager()
        return true
      }
      if (target.kind === 'workspace') {
        uiStore.openWorkspace(target.tab)
        return true
      }
      if (target.kind === 'bookmarks') {
        uiStore.openBookmarks()
        return true
      }
      if (target.kind === 'annotation_settings') {
        const opened = await dispatchTabSwitch('kwic')
        if (!opened) return false
        uiStore.openAnnotationReview()
        return true
      }
      if (target.kind === 'copilot') {
        useCopilotStore().open()
        return true
      }
      if (target.kind === 'export_dialog') {
        uiStore.openExport()
        return true
      }
      if (target.kind === 'settings') {
        uiStore.openSettings(target.tab)
        return true
      }
      if (target.kind === 'auth') {
        uiStore.openAuth()
        return true
      }
      return false
    }

    async function openSurface(
      id: string,
      summary: CorpusSummary | null = null,
    ): Promise<boolean> {
      await ensureAccessContext()
      if (!surfaceAvailability(id, summary).enabled) return false
      const target = openTargetForSurface(surfaceForCapability(id))
      return target ? applyOpenTarget(target) : false
    }

    async function openOperation(
      operationId: string,
      summary?: CorpusSummary | null,
    ): Promise<boolean> {
      await ensureAccessContext()
      const record = operationUiRecordFor(operationId, summary)
      if (!record) return false

      const uiStore = useUiStore()
      uiStore.focusProductOperation(record.operationId, {
        capabilityId: record.capabilityId,
        surfaceSlot: record.surfaceSlot,
        openTarget: record.openTarget,
        preferredMode: preferredModeForOperationSlot(record.surfaceSlot),
        responseShape: record.responseShape,
        inputSchemaRef: record.inputSchemaRef,
      })

      if (operationHasContextSurface(record)) {
        return applyOpenTarget(record.openTarget!)
      }

      return false
    }

    return {
      contract,
      status,
      error,
      capabilities,
      capabilitiesById,
      operationUiRecords,
      firstClassOperationUiRecords,
      hasContract,
      allowsMissingContractFallback,
      discoverableAnalysisTabs,
      load,
      ensureAccessContext,
      capabilityFor,
      operationFor,
      operationForRoute,
      operationLifecycleFor,
      operationLifecycleContractFor,
      operationUiRecordFor,
      isVisible,
      isRouteVisible,
      routeOperationPredicate,
      productOperationAvailability,
      assertProductOperationAccess,
      accessBlockReason,
      ensureCapabilityAccess,
      isAnalysisTabVisible,
      corpusFeatureDecision,
      surfaceAvailability,
      analysisTabAvailability,
      openSurface,
      openOperation,
    }
  },
)
