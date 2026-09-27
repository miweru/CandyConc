/**
 * How many concordance lines a search loads at once, and scrolling to the end
 * of the table loads next: three times the preference resultsPerPage, at
 * least 200 and at most 2000 lines.
 */
export const KWIC_LOAD_WINDOW_MIN = 200
export const KWIC_LOAD_WINDOW_MAX = 2000
export const KWIC_LOAD_WINDOW_PAGES = 3

export function kwicLoadWindow(pageSize: number): number {
  return Math.min(KWIC_LOAD_WINDOW_MAX, Math.max(KWIC_LOAD_WINDOW_MIN, pageSize * KWIC_LOAD_WINDOW_PAGES))
}
