# N-grams and trends

## N-grams

An n-gram list counts recurring sequences of word forms.

**Counting unit.** Every position at which a sequence of $n$ consecutive word
forms starts, for $n$ from 1 to 5. The sequence lies within one document. It
can cross a sentence boundary, but a sequence that contains a token without a
letter or digit, such as punctuation, is not counted. Because sentences
usually end with punctuation, few n-grams cross a sentence boundary.

**Case.** Exact spelling. *A cup* and *a cup* are two rows.

**Counting.** Every start position counts, so n-grams can overlap. In
*very very very*, the bigram *very very* counts twice.

**Ranking.** By frequency. Rows with the same frequency are ordered by the
internal IDs of their tokens. A minimum frequency can be set, the default
is 1.

**Kind of number.** Raw count.

**Way back.** The query
`cql:within(<doc>, [word="A"] [word="cup"])`, without `%c`, finds the hits of
the row *A cup*. The counts agree unless the n-gram overlaps with itself,
because query hits do not overlap.

### N-gram example

Bigrams of the synthetic tea corpus. 93 different bigrams occur. The first
ten rows:

```{example-table} bigrams-tea
```

The rows *A cup* (3) and *a cup* (2) are counted separately. The query
`cql:[word="a"%c] [word="cup"]` finds all 5.

## Trends

A trend counts the hits of a query per period of a date field and divides by
the number of word tokens of each period.

**Periods.** Year or month, read from the start of a metadata field. The value
must begin with four digits, optionally followed by a separator (`-`, `/`, or
`.`) and a month. Documents whose value cannot be read form a group of their
own. Periods without documents are left out and are not shown as 0. A trend
has at most 500 periods.

**Counts per period.**

- `hits`: hits of the query in the documents of the period, counted as in
  plain search, without regard to case,
- `tokens`: the number of word tokens in these documents, without
  punctuation and line breaks, the same denominator as keyness,
- `tokens_raw`: the size of these documents in tokens, punctuation included,
- `per_million`: $\text{hits} / \text{tokens} \cdot 10^6$,
- `ci_low`, `ci_high`: the Wilson score interval (Wilson 1927) at 95 % for the
  proportion $p = \text{hits} / \text{tokens}$, times $10^6$:

$$
\frac{p + \frac{z^2}{2n} \pm z \sqrt{\frac{p(1-p)}{n} + \frac{z^2}{4n^2}}}{1 + \frac{z^2}{n}}, \qquad z = 1.96, \; n = \text{tokens}
$$

**Kind of numbers.** Hits and tokens are raw counts, the rate is derived, the
interval is an estimate.

**Assumptions.** The Wilson interval treats every word token as an
independent trial. When the hits of a period come from a few documents, the
variation between documents is larger than this model assumes, and the
interval is too narrow. The method card gives the formula of the interval.
Look at the number of documents per period and at the dispersion of the query
before you read a difference between periods as a change.

**Way back.** Search the query with a metadata filter on the period.

### Trend example

The trend of *tea* over the field `date` of the synthetic tea corpus, by year:

```{example-table} trend-tea
```

Recomputed by hand for 2019: 3 hits in 39 word tokens (45 tokens with
punctuation) give $3 / 39 \cdot 10^6 = 76{,}923.08$ per million, and the
Wilson formula with $z = 1.959964$ gives the interval from 26,507.40 to
203,210.71. The intervals of all four years overlap. With two documents and
three to six hits per year, the rise from 2019 to 2022 is not supported by
these counts.

## Related pages

- [Count n-grams](../guides/count-and-measure/n-grams.md)
- [Follow a frequency over time](../guides/count-and-measure/trends.md)
- [Contrast](contrast.md#n-gram-contrast): the n-gram contrast.
