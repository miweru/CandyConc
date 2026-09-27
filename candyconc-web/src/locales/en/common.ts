import type de from '../de/common'
import type { LocaleNamespace } from '../types'

export default {
  dialog: {
    opened: 'Dialog opened: {title}',
    close: 'Close',
    panelOpened: 'Side panel opened: {title}',
  },
  toast: {
    region: 'Notifications',
    close: 'Close notification',
  },
  dropdown: {
    trigger: 'Menu',
  },
  format: {
    interval: '{low} to {high}',
  },
  pairSides: {
    anchor: 'Anchor',
    version: 'Version',
    human: 'Human',
    ai: 'AI',
    mixed: 'Mixed',
  },
} satisfies LocaleNamespace<typeof de>
