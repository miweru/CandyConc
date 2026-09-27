import type de from '../de/errors'
import type { LocaleNamespace } from '../types'

export default {
  api: {
    generic: 'Something went wrong. Please try again.',
    tooManyRequests: 'Too many requests. Wait a moment and try again.',
    signIn: 'Sign in, or your session has expired',
    server: 'Server error. Please try again.',
  },
  handler: {
    network: 'Network error. Check the connection.',
    auth: 'Authentication error. Sign in again.',
    validation: 'Validation error: {message}',
    server: 'Server error. Try again later.',
    unexpected: 'An unexpected error occurred',
    retried: 'Action retried successfully',
  },
  client: {
    notApplicable: '{endpoint} does not apply to this corpus',
    sampleSize: 'executeSampledQuery requires sample > 0',
    sampleSeed: 'executeSampledQuery requires a seed >= 0 (reproducibility)',
    targetRequired: 'targetDocsetId or targetSubcorpus is required',
    referenceRequired: 'referenceDocsetId or referenceSubcorpus is required',
    ngramSize: 'N-gram jobs require minN/maxN or n',
    ngramContrastSize: 'N-gram contrast jobs require minN/maxN or n',
    frequencyDiff: 'Frequency differences require targetDocsetId and referenceDocsetId',
    frequencyJobWordOnly: 'The frequency job supports only groupBy=word. Lemma and POS use the synchronous frequency endpoint.',
    filteredTokenPolicy: "Empty values, values without letters or digits, and {'|'}marker{'|'} values are excluded",
    semanticFailed: 'Semantic search failed ({status})',
    embeddingsUnavailable: 'Embeddings not available',
    agreementCorpusWide: 'Agreement is computed for the whole corpus (no subcorpus scope).',
    keynessLimited: 'The keyness result is limited.',
    exportFailed: 'Export failed (HTTP {status})',
    modelRouteFailed: 'The model connection could not be changed.',
    embeddingBackendFailed: 'The embedding backend could not be changed.',
  },
} satisfies LocaleNamespace<typeof de>
