# Lexical diversity

Lexical diversity measures how many different word forms a text uses relative
to its length. CandyConc computes four measures for the corpus, a document
set, or two document sets side by side.

## What is counted

**Stream.** The word tokens of the scope in corpus order. The documents of a
document set are joined into one stream. Punctuation, line breaks, and other
tokens without a letter or digit are removed first.

**Types.** A type is an exact spelling. *The* and *the* are two types.

**Windows.** The windows of STTR and MATTR run over the joined stream and can
cross document boundaries.

## Measures

With $N$ word tokens and $V$ types:

| Column | Measure | Formula | Source |
| --- | --- | --- | --- |
| `ttr` | type-token ratio | $V / N$ | |
| `guiraud` | Guiraud's R | $V / \sqrt{N}$ | Guiraud 1954 |
| `sttr` | standardized TTR | mean TTR of consecutive windows of `sttr_window` tokens (default 1,000). The incomplete last window is dropped | Scott, WordSmith Tools |
| `mattr` | moving-average TTR | mean TTR of all windows of `mattr_window` tokens (default 500), moved one token at a time. Computed on request (`mattr=true`) | Covington and McFall 2010 |

STTR and MATTR are empty when the stream is shorter than one window.

When two document sets are compared, the response gives the values for each
side (`per_side`). If the smaller side has fewer than 80 % of the word tokens
of the larger side, the field `size_warning` states that the raw TTR values of
the two sides are not comparable.

**Kind of numbers.** Derived measures.

## Assumptions and interpretation

The TTR falls as a text grows, so TTR values of scopes of different size are
not comparable. Guiraud's R reduces this dependence, and STTR and MATTR remove
it by using windows of fixed size. Compare scopes with STTR or MATTR at the
same window size. Because types are exact spellings, capitalized words at the
beginning of sentences count as separate types.

## Example

The synthetic tea corpus with windows of 20 tokens for STTR and MATTR:

```{example-table} lexdiv-tea
```

Recomputed by hand: 136 word tokens and 75 types give
$\text{TTR} = 75 / 136 = 0.55147$ and $R = 75 / \sqrt{136} = 6.43120$. The
136 tokens form 6 complete windows of 20 for STTR, and the last 16 tokens are
dropped. With case folding there would be 66 types and a TTR of 0.48529.

## Related pages

- [Measure lexical diversity](../guides/count-and-measure/lexical-diversity.md)
