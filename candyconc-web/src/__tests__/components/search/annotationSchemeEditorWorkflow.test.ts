import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AnnotationSchemeEditor from '@/components/search/AnnotationSchemeEditor.vue'
import { useProductCapabilitiesStore, useSessionStore } from '@/stores'
import type { ProductCapabilityContract } from '@/api/client'
import { getAnnotationScheme, previewAnnotationScheme, putAnnotationScheme } from '@/api/client'

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getAnnotations: vi.fn(async () => ({ annotations: {}, scheme: { categories: [], revision: 0 } })),
    getAnnotationScheme: vi.fn(async () => ({
      categories: [{ id: 'stance', label: 'Positionierung', color: '#14b8a6', shortcut: 'p' }],
      revision: 2,
    })),
    getAnnotationSettings: vi.fn(async () => ({ multiCoder: false })),
    getAnnotationAgreement: vi.fn(async () => ({
      comparableRows: 0,
      annotators: [],
      percentAgreement: null,
      cohensKappa: null,
      fleissKappa: null,
      perCategory: [],
    })),
    previewAnnotationScheme: vi.fn(async (scheme: { categories: unknown[]; revision: number }) => ({
      status: 'ready' as const,
      categories: scheme.categories,
      revision: scheme.revision,
      removals: [],
      confirmationToken: null,
    })),
    putAnnotationScheme: vi.fn(async (scheme: { categories: unknown[]; revision: number }) => scheme),
  }
})

function route(path: string, method = 'GET') {
  return {
    path,
    methods: [method],
    mutates: method !== 'GET',
    requires_corpus_features: [],
    access: 'public' as const,
    required_role: null,
    transport: 'http' as const,
    route_class: 'product_surface' as const,
  }
}

function operation(id: string, path: string, method: string, label: string, surfaceSlot: string) {
  return {
    id,
    capability_id: 'research.annotations',
    label,
    description: label,
    route: route(path, method),
    effects: method === 'GET' ? ['read'] : ['write'],
    handler_key: id.replaceAll('.', '_'),
    surface_slot: surfaceSlot,
    priority: 10,
    run_semantics: 'instant' as const,
    ui_execution_policy: 'contextual_ui' as const,
  }
}

function annotationContract(): ProductCapabilityContract {
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
      {
        id: 'research.annotations',
        title: 'KWIC annotation workflow',
        area: 'research_workflow',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: [
          '/api/v1/annotations',
          '/api/v1/annotations/{row_id}',
          '/api/v1/annotations/scheme',
          '/api/v1/annotations/scheme/preview',
          '/api/v1/annotations/settings',
          '/api/v1/annotations/agreement',
        ],
        backend_route_descriptors: [
          route('/api/v1/annotations'),
          route('/api/v1/annotations/{row_id}', 'PUT'),
          route('/api/v1/annotations/{row_id}', 'DELETE'),
          route('/api/v1/annotations/scheme'),
          route('/api/v1/annotations/scheme', 'PUT'),
          route('/api/v1/annotations/scheme/preview', 'POST'),
          route('/api/v1/annotations/settings'),
          route('/api/v1/annotations/settings', 'PUT'),
          route('/api/v1/annotations/agreement'),
        ],
        operations: [
          operation('research.annotations.read', '/api/v1/annotations', 'GET', 'Annotationen laden', 'kwic.annotations.read'),
          operation('research.annotations.write', '/api/v1/annotations/{row_id}', 'PUT', 'Annotation speichern', 'kwic.annotations.write'),
          operation('research.annotations.delete', '/api/v1/annotations/{row_id}', 'DELETE', 'Annotation löschen', 'kwic.annotations.delete'),
          operation('research.annotations.scheme_read', '/api/v1/annotations/scheme', 'GET', 'Kodierschema laden', 'kwic.annotations.scheme.read'),
          operation('research.annotations.scheme_preview', '/api/v1/annotations/scheme/preview', 'POST', 'Schemaänderung prüfen', 'kwic.annotations.scheme.preview'),
          operation('research.annotations.scheme_write', '/api/v1/annotations/scheme', 'PUT', 'Kodierschema speichern', 'kwic.annotations.scheme.write'),
          operation('research.annotations.settings_read', '/api/v1/annotations/settings', 'GET', 'Annotationseinstellungen laden', 'kwic.annotations.settings.read'),
          operation('research.annotations.settings_write', '/api/v1/annotations/settings', 'PUT', 'Annotationseinstellungen speichern', 'kwic.annotations.settings.write'),
          operation('research.annotations.agreement', '/api/v1/annotations/agreement', 'GET', 'Übereinstimmung laden', 'kwic.annotations.agreement'),
        ],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
        notes: '',
      },
      {
        id: 'research.annotations_import',
        title: 'Annotation bulk import',
        area: 'research_workflow',
        maturity: 'guarded',
        visibility: 'expert_api',
        backend_routes: ['/api/v1/annotations/import'],
        backend_route_descriptors: [route('/api/v1/annotations/import', 'POST')],
        operations: [],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: ['Bulk annotation import is backend-supported but not yet a first-class review workflow.'],
        notes: '',
      },
      {
        id: 'research.annotations_multi_api',
        title: 'Full multi-coder annotation table API',
        area: 'research_workflow',
        maturity: 'guarded',
        visibility: 'expert_api',
        backend_routes: ['/api/v1/annotations/multi'],
        backend_route_descriptors: [route('/api/v1/annotations/multi')],
        operations: [],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: ['Full matrix needs row scope, coder identity, conflict review and export semantics.'],
        notes: '',
      },
    ],
  }
}

function seedProductAccess() {
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.contract = annotationContract()
  productCapabilities.status = 'ready'
  const session = useSessionStore()
  session.status = 'ready'
  session.session = {
    schema_version: 'auth-session-v1',
    authenticated: true,
    token_present: true,
    username: 'manager',
    role: 'manager',
    effective_role: 'manager',
    rbac_enabled: true,
    security_mode: 'test',
    release_mode: true,
    unsafe_token_transport: false,
    dev_token_available: false,
    can_access_all_roles: true,
  }
}

describe('AnnotationSchemeEditor review surface', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    seedProductAccess()
  })

  it('puts basic coding first and keeps team coding behind an explicit disclosure', async () => {
    const wrapper = mount(AnnotationSchemeEditor, {
      props: { modelValue: true },
      global: {
        stubs: {
          Modal: { template: '<section><slot /><slot name="footer" /></section>' },
          Button: {
            props: ['disabled'],
            emits: ['click'],
            template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
          },
          AgreementPanel: { template: '<div>AgreementPanel</div>' },
        },
      },
    })

    await flushPromises()

    expect(wrapper.find<HTMLInputElement>('.label-input').element.value).toBe('Positionierung')
    // BEANSTANDET 2026-08-31: hier stand die nummerierte Klickfolge
    // "1. Codes anlegen. 2. In der KWIC-Tabelle einen Beleg markieren.
    // 3. Bei Bedarf eine Notiz ergaenzen." Eine Kurzanleitung ueber
    // beschrifteten Bedienelementen. Der Test pinnte sie.
    expect(wrapper.text()).not.toContain('1. Codes anlegen.')
    expect(wrapper.text()).toContain('Erweitert: Teamkodierung und Übereinstimmung')
    expect(wrapper.text()).not.toContain('AgreementPanel')
    expect(wrapper.text()).not.toContain('Review-Queue')
    expect(wrapper.text()).not.toContain('Expert/API')

    const details = wrapper.get('details')
    ;(details.element as HTMLDetailsElement).open = true
    await details.trigger('toggle')
    await flushPromises()

    expect(wrapper.text()).toContain('AgreementPanel')
  })

  it('reviews the exact impact before a used code can be removed', async () => {
    vi.mocked(getAnnotationScheme).mockResolvedValueOnce({
      categories: [
        { id: 'keep', label: 'Behalten', color: '#14b8a6', shortcut: 'b' },
        { id: 'drop', label: 'Entfernen', color: '#ef4444', shortcut: 'e' },
      ],
      revision: 5,
    })
    vi.mocked(previewAnnotationScheme).mockResolvedValue({
      status: 'ready',
      categories: [
        { id: 'keep', label: 'Behalten', color: '#14b8a6', shortcut: 'b' },
        { id: 'drop', label: 'Entfernen', color: '#ef4444', shortcut: 'e' },
      ],
      revision: 5,
      removals: [{
        categoryId: 'drop',
        label: 'Entfernen',
        annotationCount: 7,
        corpusCount: 2,
        annotatorCount: 3,
      }],
      confirmationToken: 'reviewed-token',
    })
    vi.mocked(putAnnotationScheme).mockResolvedValue({
      categories: [{ id: 'keep', label: 'Behalten', color: '#14b8a6', shortcut: 'b' }],
      revision: 6,
    })
    const wrapper = mount(AnnotationSchemeEditor, {
      props: { modelValue: true },
      global: {
        stubs: {
          Modal: { template: '<section><slot /><slot name="footer" /></section>' },
          Button: {
            props: ['disabled'],
            emits: ['click'],
            template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
          },
          AgreementPanel: { template: '<div />' },
        },
      },
    })
    await flushPromises()

    const remove = wrapper.findAll('button').find((button) => button.attributes('aria-label') === 'Entfernen Code entfernen')
    expect(remove).toBeDefined()
    await remove!.trigger('click')
    await wrapper.findAll('button').find((button) => button.text() === 'Speichern')!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Entfernen würde bestehende Kodierungen ändern')
    expect(wrapper.text()).toContain('7 Kodierungen')
    expect(wrapper.text()).toContain('2 Korpora')
    expect(putAnnotationScheme).not.toHaveBeenCalled()

    await wrapper.findAll('button').find((button) => button.text() === 'Kodierungen entfernen und speichern')!.trigger('click')
    await flushPromises()

    expect(putAnnotationScheme).toHaveBeenCalledWith(
      expect.objectContaining({ revision: 5 }),
      { expectedRevision: 5, confirmationToken: 'reviewed-token', corpus: 'default' },
    )
  })
})
