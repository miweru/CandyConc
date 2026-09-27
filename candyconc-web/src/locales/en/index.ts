/**
 * Message catalog (en), composed from one file per namespace.
 * Namespace ownership: scripts/release/candyconc_export/nachweise/i18n_konventionen.md
 */
import common from './common'
import layout from './layout'
import search from './search'
import querybuilder from './querybuilder'
import subcorpus from './subcorpus'
import kwic from './kwic'
import analysis from './analysis'
import measures from './measures'
import corpus from './corpus'
import workspace from './workspace'
import exportMessages from './export'
import settings from './settings'
import copilot from './copilot'
import capabilities from './capabilities'
import errors from './errors'
import actions from './actions'

export default {
  common,
  layout,
  search,
  querybuilder,
  subcorpus,
  kwic,
  analysis,
  measures,
  corpus,
  workspace,
  export: exportMessages,
  settings,
  copilot,
  capabilities,
  errors,
  actions,
}
