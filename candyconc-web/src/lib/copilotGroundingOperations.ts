export const COPILOT_GROUNDING_OPERATIONS = {
  chatStream: 'research.copilot_grounding.chat_stream',
  actionApprove: 'research.copilot_grounding.action_approve',
  actionReject: 'research.copilot_grounding.action_reject',
  clarificationAnswer: 'research.copilot_grounding.clarification_answer',
  contextUpdate: 'research.copilot_grounding.context_update',
  continue: 'research.copilot_grounding.continue',
} as const

export type CopilotGroundingOperationId =
  typeof COPILOT_GROUNDING_OPERATIONS[keyof typeof COPILOT_GROUNDING_OPERATIONS]
