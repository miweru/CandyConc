# Frequency and hits

This page covers the two basic counts, the hit count of a query and the
frequency list, together with rates per million and random samples of
concordance lines.

## Hit count

**Event space.** All token positions in the scope.

**Counting unit.** A hit: one non-overlapping occurrence of the query. A
sequence of several tokens counts once per occurrence. See
[Queries and hits](../concepts/queries-and-hits.md).

**Case.** Plain search ignores case by default. The query language respects
case unless a value carries `%c`.

**Scope.** The whole corpus, or a document set. Metadata conditions in the
query (`where(...)`) restrict the scope in the same way.

**Kind of number.** Raw count. The count is exact: it covers every hit in the
scope, and the API reports `partial: false`.

**Rate per million.** The count endpoint of the HTTP API returns the raw count
only. The trend view and the copilot tool `query_count` give a rate per
million on the word tokens of the scope, without punctuation, the same
denominator as keyness. See
[How CandyConc counts](index.md#denominators-of-rates-per-million).

**Way back.** The concordance of the same query shows one line per hit.

## Frequency list

**Event space.** All token positions in the scope.

**Counting unit.** Tokens per type. A type is a word form (the default), a
lemma, or a part of speech.

**Case.** For word forms and lemmas, all spellings that are equal in
lowercase form one row. The row label is the spelling of the row that is
most frequent in the whole corpus, and of two equally frequent spellings the
one that the lexicon lists first. The label does not depend on the scope, so
every view prints the same label for a row. The response names this rule as
`label_policy: most_frequent_surface_in_corpus`. For parts of speech, tags
are counted as they are.

**Filter.** Lists of word forms and lemmas count only word tokens, so
punctuation and line breaks do not appear. A list of parts of speech counts
every token, so punctuation and line breaks appear under their tags, for
example `PUNCT` and `SPACE`. A list of stop words can be excluded, and the
list can be restricted to one part of speech. A query cannot restrict a
frequency list.

**Scope.** The whole corpus or a document set.

**Kind of number.** Raw count. The CSV export of the interface adds the
relative frequency, the count divided by the size of the scope in tokens,
punctuation included. When the interface does not know the size of the scope,
it divides by the sum of the frequencies it displays, and the value is then a
share of the displayed rows. The copilot tool `frequency_list` gives a rate
per million on the word tokens of the scope, and for parts of speech on all
tokens of the scope.

**Row limit.** The response reports how many types exist
(`total_candidates`) and whether the list was cut (`truncated`).

**Way back.** A click on a row in the interface opens the concordance of the
tokens that the row counts, in the same scope: `cql:[word="LABEL"%c]` for a
word form, `cql:[lemma="LABEL"%c]` for a lemma, and `cql:[pos="TAG"]` for a
part of speech, where `LABEL` and `TAG` stand for the row label. The hit
count equals the frequency. Plain search of the row label, which ignores
case, finds the same hits for a word form row.

## Example

The synthetic tea corpus has 162 tokens, 136 of them word tokens, and 66
types of word forms after case folding. The frequency list shows `tea` with a
frequency of 17, and the searches give:

| Search | Hits | Why |
| --- | --- | --- |
| `tea` (plain) | 17 | plain search ignores case |
| `Tea` (plain) | 17 | the same |
| `Tea` with `case_insensitive=false` | 3 | exact spelling |
| `cql:[word="Tea"]` | 3 | the query language respects case |
| `cql:[word="tea"%c]` | 17 | `%c` ignores case |

Recomputed by hand: the text contains *tea* 13 times, *Tea* 3 times, and
*TEA* once, together 17. The first rows of the frequency list are:

```{example-table} frequency-tea
```

(random-samples-of-hits)=
## Random samples of hits

A concordance can be a random sample of the hits instead of the first lines.
You give the sample size and a seed.

**Procedure.** CandyConc draws the requested number of hits uniformly and
without replacement from the complete list of hits in the scope. It uses the
random number generator of NumPy (`numpy.random.default_rng(seed)`), so the
same query, sample size, seed, and index always give the same sample. The
sample is returned in corpus order. Sorting and paging then work on the
sample.

**Limits.** The sample size is at most 10,000, and a seed is required.

**Provenance.** The response header `X-CandyConc-Sample` reports the requested
size, the drawn size, the seed, the size of the population, and whether the
population count was complete.

**Kind of number.** Proportions that you observe in the sample, for example
the share of lines with a certain meaning, are estimates of the proportions
among all hits.

## Assumptions and interpretation

A hit count is a property of the corpus as it is. When you compare counts
between scopes of different size, compare rates, and state the denominator.
Counts of a query in the query language depend on its exact form: with or
without `%c`, with or without an explicit `within(<doc>, ...)`, and on the
non-overlap of hits. Report the query together with the number.
