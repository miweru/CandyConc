/**
 * Onboarding Store - First-time user guidance
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useCorpusCapabilitiesStore } from './corpusCapabilities'
import { useProductCapabilitiesStore } from './productCapabilities'
import { t } from '@/i18n'

// ============================================
// Types
// ============================================

export interface OnboardingStep {
  id: string
  title: string
  description: string
  target: string // CSS selector
  position: 'top' | 'bottom' | 'left' | 'right'
  action?: string // Optional action hint
  capabilityId?: string
}

// ============================================
// Store
// ============================================

export const useOnboardingStore = defineStore('onboarding', () => {
  // ============================================
  // State
  // ============================================

  const hasCompletedOnboarding = ref(
    localStorage.getItem('candyconc_onboarding_completed') === 'true'
  )
  const currentStepIndex = ref(0)
  const isActive = ref(false)
  const seenFeatures = ref<Set<string>>(
    new Set(JSON.parse(localStorage.getItem('candyconc_seen_features') || '[]'))
  )

  // ============================================
  // Steps Definition
  // ============================================

  const steps: OnboardingStep[] = [
    {
      id: 'search',
      get title() { return t('layout.tour.searchTitle') },
      get description() { return t('layout.tour.searchText') },
      target: '[data-onboarding="search"]',
      position: 'bottom',
      capabilityId: 'query.kwic',
    },
    {
      id: 'tabs',
      get title() { return t('layout.tour.tabsTitle') },
      get description() { return t('layout.tour.tabsText') },
      target: '[data-onboarding="tabs"]',
      position: 'bottom',
      capabilityId: 'analysis.frequency',
    },
    {
      id: 'kwic',
      get title() { return t('layout.tour.kwicTitle') },
      get description() { return t('layout.tour.kwicText') },
      target: '[data-onboarding="kwic"]',
      position: 'top',
      capabilityId: 'query.kwic',
    },
    {
      id: 'copilot',
      get title() { return t('layout.tour.copilotTitle') },
      get description() { return t('layout.tour.copilotText') },
      target: '[data-onboarding="copilot"]',
      position: 'left',
      capabilityId: 'research.copilot_grounding',
    },
    {
      id: 'export',
      get title() { return t('layout.tour.exportTitle') },
      get description() { return t('layout.tour.exportText') },
      target: '[data-onboarding="export"]',
      position: 'bottom',
      capabilityId: 'research.replay_export',
    }
  ]

  // ============================================
  // Computed
  // ============================================

  const activeSteps = computed(() => {
    const productCapabilities = useProductCapabilitiesStore()
    const corpusCapabilities = useCorpusCapabilitiesStore()
    return steps.filter((step) => {
      if (!step.capabilityId) return true
      const decision = productCapabilities.surfaceAvailability(
        step.capabilityId,
        corpusCapabilities.activeSummary,
      )
      return decision.enabled
    })
  })
  const currentStep = computed(() => activeSteps.value[currentStepIndex.value])
  const totalSteps = computed(() => activeSteps.value.length)
  const progress = computed(() =>
    totalSteps.value > 0
      ? ((currentStepIndex.value + 1) / totalSteps.value) * 100
      : 0
  )
  const isFirstStep = computed(() => currentStepIndex.value === 0)
  const isLastStep = computed(() => currentStepIndex.value === activeSteps.value.length - 1)

  // ============================================
  // Actions
  // ============================================

  function start() {
    if (hasCompletedOnboarding.value) return
    if (activeSteps.value.length === 0) return
    isActive.value = true
    currentStepIndex.value = 0
  }

  function next() {
    if (currentStepIndex.value < activeSteps.value.length - 1) {
      currentStepIndex.value++
    } else {
      complete()
    }
  }

  function previous() {
    if (currentStepIndex.value > 0) {
      currentStepIndex.value--
    }
  }

  function goToStep(index: number) {
    if (index >= 0 && index < activeSteps.value.length) {
      currentStepIndex.value = index
    }
  }

  function skip() {
    complete()
  }

  function complete() {
    isActive.value = false
    hasCompletedOnboarding.value = true
    localStorage.setItem('candyconc_onboarding_completed', 'true')
  }

  function reset() {
    hasCompletedOnboarding.value = false
    currentStepIndex.value = 0
    localStorage.removeItem('candyconc_onboarding_completed')
  }

  // Feature tooltips
  function markFeatureSeen(featureId: string) {
    seenFeatures.value.add(featureId)
    localStorage.setItem(
      'candyconc_seen_features',
      JSON.stringify([...seenFeatures.value])
    )
  }

  function hasSeenFeature(featureId: string): boolean {
    return seenFeatures.value.has(featureId)
  }

  function resetSeenFeatures() {
    seenFeatures.value.clear()
    localStorage.removeItem('candyconc_seen_features')
  }

  return {
    // State
    hasCompletedOnboarding,
    currentStepIndex,
    isActive,
    seenFeatures,
    steps,
    activeSteps,

    // Computed
    currentStep,
    totalSteps,
    progress,
    isFirstStep,
    isLastStep,

    // Actions
    start,
    next,
    previous,
    goToStep,
    skip,
    complete,
    reset,
    markFeatureSeen,
    hasSeenFeature,
    resetSeenFeatures,
  }
})
