# Methods

This section describes how CandyConc counts. For every statistical operation
it states, as implemented, what is counted, what it is divided by, which
formula is applied, what the formula assumes, and how to read the result. Each page ends with a
small example that you can recompute by hand. This page collects the rules
that all operations share.

```{toctree}
:maxdepth: 1

frequency
association-measures
dispersion
keyness
contrast
n-grams-and-trends
word-sketches
semantic-similarity
lexical-diversity
inter-annotator-agreement
worked-examples
bibliography
```

## Tokens and word tokens

The corpus size is the number of positions in the index. It includes
punctuation, and with a spaCy pipeline it also includes the line breaks of the
source text, which the pipeline keeps as tokens with the part of speech
`SPACE`. See [The corpus index](../concepts/corpus-index.md).

Many operations count only **word tokens**. A word token is a token that is
not empty, is not an internal marker of the form `|…|`, and contains at least
one letter or digit. Punctuation and line breaks are not word tokens. The rule
applies differently to what an operation counts (the numerator) and to what
it divides by (the denominator):

| Operation | Counted items restricted to word tokens | Denominator restricted to word tokens |
| --- | --- | --- |
| Frequency list of word forms or lemmas | yes | yes in the copilot tool, no in the CSV export of the interface |
| Frequency list of parts of speech | no, every token has a tag | no |
| Keyness | yes | yes |
| Frequency contrast | yes | yes |
| Trend and hit count of the copilot | no, the hits of the query | yes |
| N-grams and n-gram contrast | yes, every token of the n-gram | no |
| Collocations | only the rows shown | no |
| Lexical diversity | yes | yes |
| Word sketch | yes | no |

In the synthetic tea corpus, 136 of the 162 tokens are word tokens. A keyness
comparison therefore divides by 136 in total, a collocation analysis by 162.

## Case

CandyConc compares text without regard to case by mapping both sides to
Unicode lowercase. This has no language-specific rules: *ß* and *ss* stay
different. Which side of an operation is compared this way differs:

| Operation | Node or query | Counted items |
| --- | --- | --- |
| Hit count and concordance, plain search | ignores case (can be switched off in the API) | hits |
| Hit count and concordance, query language | respects case, ignores it with `%c` | hits |
| Frequency list (`word`, `lemma`) | not applicable | ignores case. The row label is the most frequent spelling in the corpus |
| Keyness | not applicable | ignores case. The row lists the spellings it contains |
| Frequency contrast | not applicable | ignores case |
| Collocations | ignores case | each spelling of a collocate is its own row |
| Collocation contrast | ignores case | each spelling is its own row |
| Word sketch | exact spelling, or its lowercase form if the exact spelling does not occur | each spelling is its own row |
| N-grams | not applicable | exact spelling |
| Lexical diversity | not applicable | a type is an exact spelling |
| Lines behind a collocate | ignores case | node hits with the collocate in the exact spelling of its row |

In the synthetic tea corpus, *tea* occurs 13 times, *Tea* 3 times, and *TEA*
once. Collocations of *tea* work with 17 node hits, the word sketch of *tea*
with 13.

## Denominators of rates per million

A rate per million is a count divided by a number of tokens, times one
million. The number of tokens differs between views:

| View | Count | Divided by | Punctuation in the denominator |
| --- | --- | --- | --- |
| Keyness | frequency of the word, ignoring case | word tokens of the side, or its word tokens with the chosen part of speech if the table is restricted to one | no |
| Frequency contrast | frequency of the word, ignoring case | word tokens of the document set | no |
| Trend | hits in the period | word tokens of the documents in the period | no |
| N-grams | frequency of the n-gram | all tokens of the corpus or document set | yes |
| N-gram contrast | frequency of the n-gram | number of n-gram positions of that length | yes |
| Collocation contrast | co-occurrence count of the side | all tokens of the side | yes |
| Copilot tools `query_count` (also per value of a field), `trend_analysis`, and `frequency_list` of word forms or lemmas | hits or frequency | word tokens of the scope | no |
| Copilot tool `frequency_list` of parts of speech | frequency of the tag | all tokens of the scope | yes |

The copilot tools `keyness` and `ngram_contrast` divide like keyness and the
n-gram contrast. The frequency list of the interface shows counts. Its CSV
export adds the column `relative`, the frequency divided by all tokens of the
corpus or document set.

The same item can therefore have different rates in different views. In the
tea corpus, the bigram *cup of* occurs 5 times in the blog documents. The
n-gram list restricted to these documents reports 5 / 92 tokens = 54,347.83
per million, the n-gram contrast of blog against news reports 5 / 88 bigram
positions = 56,818.18 per million. For single words, keyness and the
frequency contrast divide by the same word tokens: *tea* occurs 13 times in
the blog documents, and both report 13 / 77 = 168,831.17 per million. The
copilot tool `query_count` divides by the same 77 word tokens. The method card
of each view states its denominator.

## Four kinds of numbers

Every number in a result belongs to one of four kinds, and each methods page
says which kind each output is:

- **Raw counts**: hits, frequencies, co-occurrence counts, token counts.
- **Derived measures**: values computed deterministically from raw counts,
  such as MI, log-likelihood, logDice, Log Ratio, or DP.
- **Estimates**: confidence intervals, p-values, q-values, the conservative
  Log Ratio (LRC), and the expected DP under even spread. They rest on the
  assumptions of a statistical model.
- **Model-generated statements**: text written by the language model of the
  copilot. No methods page describes them, because CandyConc does not compute
  them. See [How the copilot works](../concepts/copilot.md).

[From numbers to lines](../concepts/from-numbers-to-lines.md) explains how to
get from a raw count to the concordance lines behind it.

## Completeness, row limits, and samples

- **All candidates are scored.** Every analysis computes its statistics over
  the complete set of candidates and only then sorts and cuts the table. Each
  response reports `total_candidates`, the number of rows returned
  (`row_limit`), and whether the table was cut (`truncated`).
- **Row limits.** A direct analysis request returns 500 rows by default and at
  most 5,000. An analysis job returns 5,000 rows by default and at most
  50,000. The interface uses jobs for long analyses.
- **No silent cuts of the hits.** The hits of a query that an analysis uses
  are not capped. If a computation would exceed a hard limit, it stops with an
  error instead of computing on a part of the data. A word sketch stops above
  5,000,000 node positions (`CANDYCONC_WORD_SKETCH_MAX_POSITIONS`), a trend
  above 500 periods.
- **Concordance lines** are delivered in pages, at most 5,000 per request. The
  hit count always covers all hits. See
  [Queries and hits](../concepts/queries-and-hits.md).
- **Samples.** A concordance can be a random sample of the hits, drawn with a
  seed. See [Frequency and hits](frequency.md#random-samples-of-hits).

## Minimum frequencies

Several operations drop candidates below a minimum frequency before they
compute the statistics:

| Operation | Minimum | Applies to |
| --- | --- | --- |
| Collocations | adaptive, see [Association measures](association-measures.md#minimum-co-occurrence) | co-occurrence count O11 |
| Collocation network | 5 by default | co-occurrence count |
| Keyness | 5 | sum of both frequencies |
| Word sketch | 3 | number of pairs |
| N-grams | as requested, default 1 | n-gram frequency |

The minimum changes the number of tests. Keyness q-values and the
conservative Log Ratio correct for the number of candidates that remain after
the minimum, so a different minimum gives different q-values and LRC values
for the same row.

## The method card

Every analysis response contains a method card with the measure, its formula
and reference, the smoothing, the sizes of the scope, the window, the case
policy, the minimum frequency that was applied, and the index fingerprint.
See [From numbers to lines](../concepts/from-numbers-to-lines.md#the-method-card).
