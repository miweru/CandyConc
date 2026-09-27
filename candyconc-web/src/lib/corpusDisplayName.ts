import type { CorpusSummary } from '@/api/client'

/**
 * The name to show for a corpus: the display name from the catalogue, else
 * its identifier. Requests keep sending the identifier (`name`).
 */
export function corpusDisplayName(
  summary: Pick<CorpusSummary, 'name' | 'display_name'> | null | undefined,
  fallback = '',
): string {
  return summary?.display_name?.trim() || summary?.name || fallback
}
