/**
 * Concordance queries behind a frequency or n-gram row.
 *
 * The query must select exactly the tokens the row counts, so the KWIC hit
 * count equals the row frequency in the same scope:
 *
 * - a word or lemma row of the folded frequency list counts every spelling of
 *   the lower-case class, CQL `%c` folds with the same `str.lower` rule,
 * - a POS prefix filter counts tokens whose tag starts with the prefix,
 * - a POS row counts the exact tag,
 * - an n-gram row counts the exact word sequence inside one document,
 *   sentence boundaries included, so the sequence is wrapped in
 *   `within(<doc>, ...)`. The KWIC default keeps a sequence inside a
 *   sentence and missed crossings (DTA sample: "Preis 1 fl" 22 against 7).
 *
 * Values are quoted CQL literals: `=` reads regex metacharacters as a
 * pattern, so they are escaped.
 */

const CQL_META = /[.*+?^${}()|[\]\\"]/g

export function cqlLiteral(value: string): string {
  return value.replace(CQL_META, '\\$&')
}

export interface FrequencyRowQueryInput {
  item: string
  groupBy: 'word' | 'lemma' | 'pos'
  posPrefix?: string | null
  /** The list folds upper and lower case (case_policy of the response). */
  caseFolded: boolean
}

export function frequencyRowQuery(input: FrequencyRowQueryInput): string {
  const value = cqlLiteral(input.item)
  if (input.groupBy === 'pos') return `cql:[pos="${value}"]`
  const flag = input.caseFolded ? '%c' : ''
  const attr = input.groupBy === 'lemma' ? 'lemma' : 'word'
  const prefix = (input.posPrefix ?? '').trim()
  const posCond = prefix && input.groupBy === 'word' ? ` & pos="${cqlLiteral(prefix)}.*"` : ''
  return `cql:[${attr}="${value}"${flag}${posCond}]`
}

export function ngramRowQuery(ngram: string): string {
  const tokens = ngram.split(/\s+/).filter(Boolean)
  const cells = tokens.map((token) => `[word="${cqlLiteral(token)}"]`).join(' ')
  return `cql:within(<doc>, ${cells})`
}

/**
 * Concordance query behind a word sketch row: node, relation, collocate.
 *
 * The sketch counts pairs of a head and a dependent, the node in the form the
 * sketch resolved (`node` of the response) and the collocate in its exact
 * spelling. The dependency search `HEAD >rel DEPENDENT` finds the heads, a
 * relation ending in `_rev` has the node as dependent. `[word=x]` without
 * quotes is exact, so the query selects the pairs of the row.
 *
 * A word with a quotation mark cannot stand in `[word=...]`, because a query
 * that starts with a bracket and contains a quotation mark is read as the
 * query language, which has no dependency operator. Such a word is written as
 * a plain word in front, which ignores case (`exact: false`). A word that is
 * neither expressible gives null.
 */
export interface WordSketchRowQuery {
  term: string
  /** True when both sides are exact spellings, false when one ignores case. */
  exact: boolean
}

const ATTR_SAFE = /^[^\s[\]'"]+$/
const PLAIN_SAFE = /^[^\s()[\]"*?<>]+$/
const PLAIN_OPERATOR = /^(AND|OR|NOT|NEAR\/\d+)$/i

function dependencySide(word: string): { text: string; exact: boolean } | null {
  if (ATTR_SAFE.test(word)) return { text: `[word=${word}]`, exact: true }
  if (
    PLAIN_SAFE.test(word) &&
    !PLAIN_OPERATOR.test(word) &&
    !(word.startsWith('/') && word.endsWith('/')) &&
    !(word.length > 2 && word.startsWith("'") && word.endsWith("'"))
  ) {
    return { text: word, exact: false }
  }
  return null
}

export function wordSketchRowQuery(node: string, relation: string, collocate: string): WordSketchRowQuery | null {
  const reverse = relation.endsWith('_rev')
  const rel = reverse ? relation.slice(0, -4) : relation
  if (!rel || /\s/.test(rel)) return null
  const head = dependencySide(reverse ? collocate : node)
  const dep = dependencySide(reverse ? node : collocate)
  if (!head || !dep) return null
  if (!dep.exact && head.exact) return { term: `${dep.text} <${rel} ${head.text}`, exact: false }
  return { term: `${head.text} >${rel} ${dep.text}`, exact: head.exact && dep.exact }
}
