import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import MobileNav from '@/components/layout/MobileNav.vue'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import type { ProductCapabilityContract } from '@/api/client'

function route(path: string) {
  return {
    path,
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: [],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  }
}

function capability(id: string) {
  const descriptor = route(`/api/v1/test/${id}`)
  return {
    id,
    title: id,
    area: 'analysis',
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

function mobileNavContract(): ProductCapabilityContract {
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [
      capability('analysis.collocation_network'),
      capability('analysis.ngrams'),
      capability('analysis.keyness'),
      capability('analysis.wordsketch'),
      capability('analysis.frequency'),
    ],
  } as ProductCapabilityContract
}

function seedSession() {
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

describe('MobileNav capability discoverability', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    seedSession()
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = mobileNavContract()
    productCapabilities.status = 'ready'
  })

  it('renders every discoverable analysis surface instead of truncating to primary tabs', () => {
    const productCapabilities = useProductCapabilitiesStore()
    const wrapper = mount(MobileNav)
    const text = wrapper.text()

    expect(wrapper.findAll('.nav-item')).toHaveLength(productCapabilities.discoverableAnalysisTabs.length)
    expect(text).toContain('Netzwerk')
    expect(text).toContain('N-Gramme')
    expect(text).toContain('Keyness')
    expect(text).toContain('Word Sketch')
  })
})
