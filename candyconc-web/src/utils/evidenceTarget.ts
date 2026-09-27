/**
 * Where an evidence chip of a copilot answer leads.
 *
 * The chip's source (`copilot.grounding.evidence`) carries the tool name and
 * the tool arguments as the backend's compact JSON (`json.dumps(sort_keys=True)`,
 * whitespace collapsed, cut to 512 characters with "..."). A click used that
 * JSON as a KWIC search term, the server answered 400 (methoden C2, inventar
 * 4.2). Now:
 *
 * - a chip of a tool the contract binds to the KWIC capability opens its
 *   query in the KWIC, in the tool's corpus and docset,
 * - the chip of any other tool reveals the cited tool result among the tool
 *   cards of the message, matched by tool name and arguments.
 */

import type { ProductCapabilityContract } from '@/api/client'
import { productCopilotToolMap } from '@/lib/copilotTools'
import type { BelegQuelle } from '@/utils/belege'

/** Capability whose tools yield a concordance (contract id). */
export const KWIC_CAPABILITY_ID = 'query.kwic'

export interface EvidenceToolCall {
  id: string
  name: string
  arguments: Record<string, unknown>
}

export interface EvidenceSearch {
  term: string
  corpus?: string
  docsetId?: string
}

/** Python-style `json.dumps(value, sort_keys=True, ensure_ascii=False)`. */
export function pythonJsonDumps(value: unknown): string {
  if (value === null || value === undefined) return 'null'
  if (Array.isArray(value)) return `[${value.map(pythonJsonDumps).join(', ')}]`
  if (typeof value === 'object') {
    const record = value as Record<string, unknown>
    const keys = Object.keys(record).sort()
    return `{${keys.map((k) => `${JSON.stringify(k)}: ${pythonJsonDumps(record[k])}`).join(', ')}}`
  }
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return JSON.stringify(value)
}

function compact(text: string): string {
  return text.split(/\s+/).filter(Boolean).join(' ')
}

/** The tool arguments of a chip source, when its JSON is complete. */
export function evidenceArguments(source: BelegQuelle): Record<string, unknown> | null {
  const raw = (source.query ?? '').trim()
  if (!raw.startsWith('{')) return null
  try {
    const parsed = JSON.parse(raw) as unknown
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : null
  } catch {
    return null
  }
}

/** True when the contract binds the tool to the KWIC capability. */
export function evidenceOpensKwic(
  toolName: string,
  contract: ProductCapabilityContract | null | undefined,
): boolean {
  return (productCopilotToolMap(contract).get(toolName) ?? []).includes(KWIC_CAPABILITY_ID)
}

const CORPUS_ALIASES = new Set(['default', 'active']) // i18n-ignore: corpus aliases of the copilot tools

/** Query, corpus and docset of a search-tool chip. */
export function evidenceSearch(source: BelegQuelle): EvidenceSearch | null {
  const args = evidenceArguments(source)
  if (!args) return null
  const term = typeof args.query === 'string' ? args.query.trim() : ''
  if (!term) return null
  const out: EvidenceSearch = { term }
  // "default" and "active" are the copilot's names for the active corpus. The
  // interface keeps its own name for it, under which the copilot's docsets are stored.
  const corpus = typeof args.corpus === 'string' ? args.corpus.trim() : ''
  if (corpus && !CORPUS_ALIASES.has(corpus.toLowerCase())) out.corpus = corpus
  if (typeof args.docset_id === 'string' && args.docset_id.trim()) out.docsetId = args.docset_id.trim()
  return out
}

/** The tool card a chip cites: same tool, same (possibly cut) argument JSON. */
export function evidenceToolCallId(
  source: BelegQuelle,
  toolCalls: readonly EvidenceToolCall[],
): string | null {
  const candidates = toolCalls.filter((call) => call.name === source.tool)
  if (!candidates.length) return null
  const cited = compact(source.query ?? '')
  const cut = cited.endsWith('...') ? cited.slice(0, -3).trimEnd() : null
  const matching = candidates.filter((call) => {
    const own = compact(pythonJsonDumps(call.arguments ?? {}))
    if (!cited) return own === '{}'
    return cut !== null ? own.startsWith(cut) : own === cited
  })
  if (matching.length) return matching[0]!.id
  return candidates.length === 1 ? candidates[0]!.id : null
}
