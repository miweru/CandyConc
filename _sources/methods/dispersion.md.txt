# Dispersion

Dispersion describes how evenly the hits of a query are spread over the
documents of a scope. Two words with the same frequency can occur in almost
every document or in only one. CandyConc reports several dispersion measures
and places DP between its smallest possible, its expected, and its largest
possible value for the given document sizes.

## What is counted

**Parts.** The parts are the documents of the scope, all of them, including
documents without a hit.

**Counts.** For each document $i$ of $n$ documents:

- $o_i$ is the number of hits of the query in the document, without regard
  to case, as in plain search,
- $s_i$ is the size of the document in tokens, punctuation included,
- $F = \sum_i o_i$ is the total number of hits, and $N = \sum_i s_i$ the size
  of the scope.

The response contains both lists completely (`partitions` for $o_i$ and
`doc_sizes` for $s_i$), in the order of the documents in the index.

## Measures

| Column | Measure | Formula | Source |
| --- | --- | --- | --- |
| `dp` | deviation of proportions | $\mathrm{DP} = \frac{1}{2} \sum_i \lvert o_i / F - s_i / N \rvert$ | Gries 2008 |
| `dpnorm` | normalized DP | $\mathrm{DP} / (1 - \min_i s_i / N)$ | Lijffijt and Gries 2012 |
| `vc` | coefficient of variation | standard deviation (population) divided by the mean of $v_i = o_i / s_i$ | |
| `juilland_d` | Juilland's D | $1 - \mathrm{VC} / \sqrt{n - 1}$, limited to the range 0 to 1, and 0 if $F = 0$ | Juilland and Chang-Rodríguez 1964, formula as given by Gries 2020 |
| `carroll_d2` | D2 of raw hit counts | $-\sum_i p_i \ln p_i / \ln n$ with $p_i = o_i / F$ | normalized Shannon entropy, using raw hit shares |
| `range`, `range_prop` | range | number and share of documents with $o_i > 0$ | |

DP is 0 when the hits are spread exactly in proportion to the document
sizes, and it approaches 1 when all hits are in one small document. Juilland's
D and D2 run the other way: 1 is even, 0 is concentrated.

Juilland's D compares the relative frequencies $v_i$ in the documents.
The `carroll_d2` field compares their raw hit counts. It is 1 when every
document has the same number of hits. Equal rates in documents of different
lengths therefore give a value below 1. This is the raw-count variant of D2.
Gries (2020, pp. 102 to 103) describes D2 calculated from per-document relative
frequencies, normalized across the documents before computing the entropy.

## Reference values for DP

A DP value is hard to read without knowing what is possible for the given
document sizes and number of hits. CandyConc computes three reference values.
They are procedures of CandyConc, not measures from the literature:

- `dp_min`: the DP of the most proportional distribution of the $F$ hits
  over the documents in whole numbers,
- `dp_erwartet`: the expected DP if every hit fell into a document with a
  probability proportional to its size. The calculation sums the expected
  absolute deviations of the document-wise binomial counts. For a document
  with more than 30 expected hits, it uses the normal approximation to that
  deviation,
- `dp_max`: the DP if all hits were in the smallest document,
  $1 - \min_i s_i / N$.

The field `classification` places DP between these values:

| Label | Condition |
| --- | --- |
| `even` | DP at most 0.75 times the expected DP |
| `fairly_even` | DP up to the expected DP |
| `fairly_clustered` | DP above the expected DP, below the halfway point to `dp_max` |
| `clustered` | DP at or above the halfway point from the expected DP to `dp_max` |
| `zu_wenig_treffer` (too few hits) | `dp_max` minus `dp_min` below 0.05 |
| `not_found` | no hit |

The factors 0.75, 0.5, and 0.05 are conventions of CandyConc.

## Kind of numbers

$o_i$ and $s_i$ are raw counts. DP and the other measures are derived. The
expected DP is an estimate under the null model of proportional spread, and
the classification is a rule-based reading of these numbers.

## Assumptions and interpretation

- Documents are the parts. A corpus of a few long documents gives little
  information about dispersion, and so does a word with few hits. The
  reference values show how much room there is: when `dp_min` and `dp_max`
  are close, no measure can distinguish even from clustered.
- Compare DP with the expected value, not with 0. With few hits, even random
  spread produces a clearly positive DP.
- The null model spreads hits independently. Words that occur in bursts
  within a document are expected to exceed it.

## Example

Hits of *tea* in the eight documents of the synthetic tea corpus
(17 hits, 162 tokens):

```{example-table} dispersion-tea-parts
```

The measures for *tea* and, for comparison, *coffee* (10 hits):

```{example-table} dispersion
```

Recomputed by hand for *tea*:
$\mathrm{DP} = \frac{1}{2} \sum_i \lvert o_i / 17 - s_i / 162 \rvert = 0.23457$,
and $\mathrm{DP}_{\max} = 1 - 14 / 162 = 0.91358$. A simulation that places
the 17 hits at random in proportion to the document sizes, 20,000 times,
gives a mean DP of about 0.256, close to the analytic expected value of
0.25624. The observed DP of *tea* lies below that value, so *tea* is spread
at least as evenly as random placement would predict and is labeled
`fairly_even`. *Coffee* lies above its expected value and is labeled
`fairly_clustered`: it is concentrated in the news documents.

Carroll's D2 on the raw shares is 0.84749 for *tea*. Computed on the
size-normalized shares $v_i / \sum_j v_j$ it would be 0.84895.

## Related pages

- [Measure dispersion](../guides/count-and-measure/dispersion.md)
- [From numbers to lines](../concepts/from-numbers-to-lines.md#from-a-dispersion-result-to-the-documents)
