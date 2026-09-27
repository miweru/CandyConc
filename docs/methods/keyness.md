# Keyness

Keyness finds words that are more frequent in one scope, the target, than in
another, the reference. CandyConc computes a test statistic, an effect size
with a confidence interval, a conservative effect size, and p-values and
q-values for every word, from one 2 × 2 table per word.

## What is compared

**Target and reference.** The two sides can be:

- two document sets of one corpus, which must not share documents,
- a document set and the rest of its corpus,
- two corpora,
- a corpus or document set and an external frequency list. The list must be
  declared complete, its total must match, and it must count the same parts
  of speech as the target.

In the interface, the active subcorpus is the target, so keyness needs an
active subcorpus.

**Counting unit.** Tokens per word form, without regard to case, counted over
word tokens only. The table can be restricted to one part of speech. The
field `surface_variants` of a row lists the spellings that its counts
contain.

**Denominators.** $N_t$ and $N_r$ are the numbers of word tokens of the two
sides, or, if the table is restricted to one part of speech, the numbers of
word tokens with that part of speech. The method card reports them as
`target_total` and `reference_total`, and the same counts over all tokens,
punctuation included, as `target_tokens_roh` and `reference_tokens_roh`.

**Minimum frequency.** Words with $a + c < 5$ are dropped before any test.
The number $m$ of remaining words is the number of tests for the q-values and
the LRC.

## The table and the measures

For a word with frequency $a$ in the target and $c$ in the reference:

|  | the word | other words | total |
| --- | --- | --- | --- |
| target | $a$ | $N_t - a$ | $N_t$ |
| reference | $c$ | $N_r - c$ | $N_r$ |

| Column | Measure | Formula | Kind | Source |
| --- | --- | --- | --- | --- |
| `target_freq`, `reference_freq` | frequencies | $a$, $c$ | raw count | |
| `target_per_million`, `reference_per_million` | rates | $a / N_t \cdot 10^6$, $c / N_r \cdot 10^6$ | derived | |
| `diff_per_million` | difference of the rates | target rate minus reference rate | derived | |
| `ll` | log-likelihood G² | $2 \sum_{ij} O_{ij} \ln (O_{ij} / E_{ij})$ over the four cells | derived | Dunning 1993 |
| `ll_signed` | G² with direction | G² with the sign of `diff_per_million` | derived | |
| `chi2`, `chi2_signed` | Pearson's χ² | $\sum_{ij} (O_{ij} - E_{ij})^2 / E_{ij}$ over the four cells, without continuity correction | derived | Pearson 1900 |
| `chi2_cell` | contribution of the target cell | $(a - E_{11})^2 / E_{11}$ | derived | |
| `log_ratio` | Log Ratio | $\log_2 \dfrac{(a + 0.5) / N_t}{(c + 0.5) / N_r}$ | derived | Hardie 2014 |
| `log_ratio_ci_low`, `log_ratio_ci_high` | 95 % confidence interval of Log Ratio | $\text{Log Ratio} \pm 1.96 \cdot \mathrm{SE} / \ln 2$ with $\mathrm{SE} = \sqrt{\frac{1}{a + 0.5} - \frac{1}{N_t + 0.5} + \frac{1}{c + 0.5} - \frac{1}{N_r + 0.5}}$ | estimate | Katz et al. 1978 |
| `lrc` | conservative Log Ratio | see the following section | estimate | Evert 2022 |
| `p_value` | p-value of G² | $P(\chi^2_1 \ge G^2)$ | estimate | |
| `q_value` | false discovery rate | Benjamini and Hochberg over all $m$ words | estimate | Benjamini and Hochberg 1995 |
| `bic` | BIC approximation | $G^2 - \ln (N_t + N_r)$ | derived | after Wilson 2013 |
| `expected_min`, `low_reliability` | reliability flag | smallest expected cell, flagged below 5 | diagnostic | rule of thumb after Cochran 1954 |

The expected values are $E_{11} = N_t (a + c) / (N_t + N_r)$ and so on for
the other cells.

**Log Ratio smoothing.** Hardie (2014) defines Log Ratio without smoothing.
CandyConc adds 0.5 to $a$ and to $c$, so that a word that is absent from one
side has a finite value. The value differs slightly from the unsmoothed
ratio even when neither count is zero.

**Conservative Log Ratio (LRC).** Conditional on $a + c$, the number $a$
follows a binomial distribution. CandyConc computes the exact Clopper and
Pearson (1934) interval for the proportion $a / (a + c)$ at the level
$\alpha = 0.001 / m$ (Bonferroni correction over the $m$ words, Dunn 1961), converts both
bounds to the Log Ratio scale with
$\log_2 \frac{p}{1 - p} + \log_2 \frac{N_r}{N_t}$, and reports the bound
closer to zero, or 0 if the interval contains zero. This is the procedure of
Evert (2022), who recommends $\alpha = 0.05 / m$. CandyConc uses the stricter
level 0.001. The LRC is part of the API response. The method card lists it
among its statistics, with the level in `lrc_alpha`, the correction in
`lrc_correction` (`bonferroni`), and in `lrc_tests` the name of the field
that holds $m$, `total_candidates`.

**Sorting.** The default sort is `ll_signed`, so words that are more frequent
in the target come first, ordered by G². The table can also be sorted by `ll`,
`chi2`, `chi2_signed`, `chi2_cell`, `log_ratio`, or `bic`.

## Three ways of expressing uncertainty

A keyness row contains three inferential quantities that rest on different
assumptions, and they do not have to agree:

- The **p-value and the q-value** come from the chi-square approximation of
  G² with one degree of freedom.
- The **confidence interval of Log Ratio** is a normal approximation on the
  log scale (Katz et al. 1978), at the 95 % level, without correction for
  multiple testing.
- The **LRC** is the bound of an exact interval, corrected for all $m$
  words, at a much stricter level.

An interval of Log Ratio that excludes zero together with an LRC of 0 is
therefore not a contradiction. The LRC answers whether the difference holds
after correcting for every word in the table at the strict level, and for
small counts it usually does not.

## Assumptions and interpretation

- Every token is treated as an independent event. Words cluster in
  documents, so a word that is frequent in one long document of the target
  can reach a high G². Check the dispersion of key words and read their
  concordance lines. See [Dispersion](dispersion.md).
- G², χ², and their p-values measure the evidence against equal rates. They
  grow with the corpus size. Log Ratio and the LRC measure the size of the
  difference, as a binary logarithm: a Log Ratio of 1 means twice as frequent.
- q-values control the expected share of false discoveries among the words
  you select at a given threshold, over the $m$ words that passed the
  minimum frequency.
- Rows flagged `low_reliability` have an expected cell below 5, where the
  chi-square approximation of the p-value is poor.

## Example: the synthetic tea corpus

Blog documents (target, 4 documents, 92 tokens, 77 word tokens) against news
documents (reference, 4 documents, 70 tokens, 59 word tokens), default
minimum frequency 5. Seven words remain, so $m = 7$.

```{example-table} keyness-blog-news
```

Recomputed by hand for `tea`: the table is $[[13, 64], [4, 55]]$ with
$N = 136$. The expected values are 9.625, 67.375, 7.375, and 51.625, and
$G^2 = 2 \sum O \ln (O / E) = 3.3088$. Log Ratio is
$\log_2 \bigl((13.5 / 77) / (4.5 / 59)\bigr) = 1.2008$.

The row `coffee` shows the difference between the frameworks. Its 95 %
interval of Log Ratio, from -4.1248 to -0.1745, excludes zero. Its LRC is 0,
because the exact interval at $\alpha = 0.001 / 7$ for $a = 2$ out of 10
reaches from about -10.0 to 1.6 on the Log Ratio scale and contains zero.

## Example: the English sample corpus

Addresses by Republican presidents (36 documents, 174,284 word tokens)
against addresses by Democratic presidents (29 documents, 180,221 word
tokens). 4,627 words pass the minimum frequency. The row for *freedom*:

```{example-table} keyness-sotu-freedom
```

*Freedom* is about twice as frequent in the Republican addresses (Log Ratio
1.05), and the conservative estimate of the difference is still 0.34 after
correcting for all 4,627 words. The keyness list of the same comparison
starts with *Applause* and *’s*, which come from the transcription
conventions of the later addresses. Reading the concordance lines of such
words before interpreting them is part of the method.

## Related pages

- [Compare two subcorpora with keyness](../guides/count-and-measure/keyness.md)
- [Contrast](contrast.md): frequency contrast and collocation contrast.
- [From numbers to lines](../concepts/from-numbers-to-lines.md#from-a-keyness-row-to-the-lines)
