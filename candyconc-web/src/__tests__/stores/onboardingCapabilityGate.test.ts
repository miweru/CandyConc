import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useOnboardingStore } from '@/stores/onboarding'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import type { ProductCapabilityContract } from '@/api/client'

function capability(id: string, role: 'user' | 'admin' = 'user') {
  const descriptor = {
    path: `/api/v1/${id.replace('.', '/')}`,
    methods: ['GET'] as Array<'GET'>,
    mutates: false,
    requires_corpus_features: [],
    access: role,
    required_role: role,
    transport: 'http' as const,
    route_class: role === 'admin' ? 'admin_surface' as const : 'product_surface' as const,
  }
  return {
    id,
    title: id,
    area: id.split('.')[0],
    maturity: 'stable',
    visibility: 'first_class_ui',
    backend_routes: [descriptor.path],
    backend_route_descriptors: [descriptor],
    operations: [],
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
  }
}

function contract(capabilityIds: string[]): ProductCapabilityContract {
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: capabilityIds.map((id) => capability(id)),
  }
}

function seedUserSession() {
  const session = useSessionStore()
  session.status = 'ready'
  session.session = {
    schema_version: 'auth-session-v1',
    authenticated: true,
    token_present: true,
    username: 'analyst',
    role: 'user',
    effective_role: 'user',
    rbac_enabled: true,
    security_mode: 'release',
    release_mode: true,
    unsafe_token_transport: false,
    dev_token_available: false,
    can_access_all_roles: false,
  }
}

describe('onboarding capability gates', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    seedUserSession()
    const corpusCapabilities = useCorpusCapabilitiesStore()
    corpusCapabilities.loaded = true
  })

  it('builds the tour from currently usable product capabilities', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(['query.kwic', 'research.replay_export'])
    productCapabilities.status = 'ready'
    const onboarding = useOnboardingStore()

    onboarding.start()

    expect(onboarding.isActive).toBe(true)
    expect(onboarding.activeSteps.map((step) => step.id)).toEqual(['search', 'kwic', 'export'])
    expect(onboarding.currentStep?.id).toBe('search')
    expect(onboarding.totalSteps).toBe(3)
  })

  it('does not start an empty tour when no first-class tour surface is usable', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([])
    productCapabilities.status = 'ready'
    const onboarding = useOnboardingStore()

    onboarding.start()

    expect(onboarding.activeSteps).toEqual([])
    expect(onboarding.isActive).toBe(false)
  })
})
