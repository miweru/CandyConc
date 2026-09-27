# Contrast

Besides [keyness](keyness.md), CandyConc has three comparisons between a
target and a reference: the frequency contrast, the n-gram contrast, and the
collocation contrast. They rank rows by the difference of two rates per
million and do not compute significance tests.

## Frequency contrast

**Counting unit.** Tokens per word form, without regard to case, counted over
word tokens, as in keyness.

**Denominators.** The rates divide by the number of word tokens of each side,
as in keyness, so both views report the same rates for the same document
sets. The method card gives these numbers as `target_total` and
`reference_total`, and the numbers of all tokens, punctuation included, as
`target_tokens_roh` and `reference_tokens_roh`. See
[How CandyConc counts](index.md#denominators-of-rates-per-million).

**Ranking.** Rows are ordered by the absolute difference of the two rates,
`diff_per_million`. A row is kept if the larger of its two frequencies reaches
the minimum frequency.

**Kind of numbers.** Raw counts and derived rates.

**Example.** In the synthetic tea corpus, *tea* occurs 13 times in the blog
documents (92 tokens, 77 word tokens) and 4 times in the news documents
(70 tokens, 59 word tokens). The frequency contrast of blog against news
reports 13 / 77 · 10⁶ = 168,831.17 and 4 / 59 · 10⁶ = 67,796.61 per million,
a difference of 101,034.56. Keyness reports the same two rates.

## N-gram contrast

**Counting unit.** N-grams of one length $n$, counted as in
[N-grams](n-grams-and-trends.md): exact spelling, word tokens only, within
documents.

**Denominators.** The number of n-gram positions of length $n$ on each side,
$\sum_d \max(0, L_d - n + 1)$ over the documents $d$ with $L_d$ tokens. The method
card names this basis in `rate_basis` (`ngram_positions_per_order`) and
gives the numbers in `ngram_positions_target` and
`ngram_positions_reference`.

**Ranking.** By the absolute difference of the two rates per million. The rows
contain frequencies and rates, no test statistic, and the method card lists
exactly these two statistics, the frequency and the difference per million.

## Collocation contrast

The collocation contrast compares the collocates of one node between two
document sets, for example two subcorpora.

**Node.** The node is resolved without regard to case, as in the
[collocation analysis](association-measures.md).

**Tables.** Each side gets its own contingency table as described in
[Association measures](association-measures.md#event-space-and-contingency-table),
with the merged window $R_1$, the co-occurrence count $O_{11}$, the collocate
frequency $f(v)$, and the size $N$ of that side.

**Measures.** The chosen association measure is computed on each side and
reported as `target_score` and `reference_score`, with the difference
`diff_score`. The default measure is the Dice coefficient on the window
table, $2 O_{11} / (R_1 + f(v))$.

**Ranking.** Rows are ordered by the absolute value of the difference of the
co-occurrence rates, reported as `diff_per_million`,

$$
\Delta_{\mathrm{pm}} = \frac{O_{11}^{t}}{N_t} \cdot 10^6 - \frac{O_{11}^{r}}{N_r} \cdot 10^6 ,
$$

and not by the difference of the association measure. The method card states this
ordering in `default_sort` (`diff_abs`) and `rank_definition`, and names the
chosen measure in `score_key`. A difference in the co-occurrence rate combines two effects: a
different association and a different frequency of the node on the two sides.
A collocate can rank high only because the node itself is more frequent in the
target. Compare `diff_score` to see whether the association differs.

**Log Ratio.** Each row also carries the Log Ratio of the two co-occurrence
rates, the same rates as the columns per million, with 0.5 added to both
counts:

$$
\mathrm{LR} = \log_2 \frac{(O_{11}^{t} + 0.5) / N_t}{(O_{11}^{r} + 0.5) / N_r} .
$$

`one_sided` is true for a collocate that occurs on one side only. Its Log
Ratio rests on the added 0.5 of the other side.

**Filter.** The collocation contrast has no minimum frequency and no test of
the difference.

**Kind of numbers.** The co-occurrence counts are raw counts, scores and
rates are derived.

## Assumptions and interpretation

- All three comparisons describe differences. They do not tell you whether a
  difference could arise by chance. For single words, use
  [keyness](keyness.md), which adds G², Log Ratio with its interval, the LRC,
  and q-values.
- Rates from two views are comparable when both use the same kind of
  denominator. The frequency contrast and keyness divide by the same word
  tokens, the n-gram contrast by n-gram positions, and the collocation
  contrast by all tokens of each side.

## Related pages

- [Contrast collocations and paired versions](../guides/count-and-measure/contrast.md)
- [Lexical diversity](lexical-diversity.md) can be computed for both sides of a
  comparison.
