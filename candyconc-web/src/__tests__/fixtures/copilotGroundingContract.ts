import { COPILOT_GROUNDING_OPERATIONS } from '@/lib/copilotGroundingOperations'
import type {
  ProductCapability,
  ProductCapabilityBackendRouteDescriptor,
  ProductCapabilityContract,
  ProductCapabilityOperation,
} from '@/api/client'

function route(path: string, methods = ['POST']): ProductCapabilityBackendRouteDescriptor {
  return {
    path,
    methods,
    mutates: methods.some((method) => method.toUpperCase() !== 'GET'),
    requires_corpus_features: [],
    access: 'public',
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }
}

function operation(
  id: string,
  label: string,
  path: string,
): ProductCapabilityOperation {
  return {
    id,
    capability_id: 'research.copilot_grounding',
    label,
    description: '',
    route: route(path),
    effects: ['read'],
    handler_key: id.split('.').at(-1) ?? id,
    surface_slot: id,
    priority: 100,
  }
}

export function copilotGroundingCapability(
  overrides: Partial<ProductCapability> = {},
): ProductCapability {
  const routes = [
    route('/api/v1/chat/stream'),
    route('/api/v1/copilot/action/approve'),
    route('/api/v1/copilot/action/reject'),
    route('/api/v1/copilot/clarify/answer'),
    route('/api/v1/copilot/context'),
    route('/api/v1/copilot/continue'),
  ]
  return {
    id: 'research.copilot_grounding',
    title: 'Grounded research Copilot',
    area: 'copilot',
    maturity: 'guarded',
    visibility: 'first_class_ui',
    backend_routes: routes,
    backend_route_descriptors: routes,
    operations: [
      operation(COPILOT_GROUNDING_OPERATIONS.chatStream, 'Copilot-Chat streamen', '/api/v1/chat/stream'),
      operation(COPILOT_GROUNDING_OPERATIONS.actionApprove, 'Copilot-Aktion genehmigen', '/api/v1/copilot/action/approve'),
      operation(COPILOT_GROUNDING_OPERATIONS.actionReject, 'Copilot-Aktion ablehnen', '/api/v1/copilot/action/reject'),
      operation(COPILOT_GROUNDING_OPERATIONS.clarificationAnswer, 'Copilot-Rückfrage beantworten', '/api/v1/copilot/clarify/answer'),
      operation(COPILOT_GROUNDING_OPERATIONS.contextUpdate, 'Copilot-Kontext synchronisieren', '/api/v1/copilot/context'),
      operation(COPILOT_GROUNDING_OPERATIONS.continue, 'Copilot-Ausführung fortsetzen', '/api/v1/copilot/continue'),
    ],
    frontend_evidence: [],
    action_types: ['copilot/setAutonomy', 'copilot/sendMessage', 'copilot/continue'],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
    ...overrides,
  }
}

export function kwicCapability(
  overrides: Partial<ProductCapability> = {},
): ProductCapability {
  const pageRoute = route('/api/v1/query', ['GET'])
  const streamRoute = route('/api/v1/query/stream', ['GET'])
  return {
    id: 'query.kwic',
    title: 'KWIC',
    area: 'query',
    maturity: 'stable',
    visibility: 'first_class_ui',
    backend_routes: [pageRoute, streamRoute],
    backend_route_descriptors: [pageRoute, streamRoute],
    operations: [
      {
        id: 'query.kwic.page',
        capability_id: 'query.kwic',
        label: 'KWIC laden',
        description: '',
        route: pageRoute,
        effects: ['read'],
        handler_key: 'kwic_page',
        surface_slot: 'query.kwic.page',
        priority: 10,
      },
      {
        id: 'query.kwic.stream',
        capability_id: 'query.kwic',
        label: 'KWIC streamen',
        description: '',
        route: streamRoute,
        effects: ['read', 'long_running'],
        handler_key: 'kwic_stream',
        surface_slot: 'query.kwic.stream',
        priority: 20,
      },
    ],
    frontend_evidence: [],
    action_types: ['query/execute'],
    copilot_tools: ['run_cqlf_query'],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
    ...overrides,
  }
}

export function withCopilotGroundingCapability(
  contract: ProductCapabilityContract,
  overrides: Partial<ProductCapability> = {},
): ProductCapabilityContract {
  const grounding = copilotGroundingCapability(overrides)
  const capabilities = contract.capabilities.filter((capability) => capability.id !== grounding.id)
  return {
    ...contract,
    capabilities: [grounding, ...capabilities],
  }
}

export function copilotGroundingContract(
  overrides: Partial<ProductCapability> = {},
): ProductCapabilityContract {
  return withCopilotGroundingCapability({
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [],
  }, overrides)
}

export function copilotGroundingWithKwicContract(): ProductCapabilityContract {
  return withCopilotGroundingCapability({
    ...copilotGroundingContract(),
    capabilities: [kwicCapability()],
  })
}
