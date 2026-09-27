# Collocations and association measures

A collocation analysis lists the words that occur near a node and measures
how strongly each of them is associated with it. CandyConc computes all
association measures from one contingency table per collocate. This page
defines the table, every measure in the result, and the collocation network.

## Node and window

**Node.** The node is a word, a lemma, or a query:

- A word is resolved without regard to case. All spellings that are equal in
  lowercase are node hits.
- With the attribute `lemma`, node and collocates are counted on the lemma
  attribute instead of the word form.
- A query in the query language, written with the prefix `cql:`, uses every
  hit as a node, with its whole span.

**Window.** The window covers `w` tokens to the left and `w` tokens to the
right of each node hit, with `w` between 1 and 50. The node hit itself is not
part of its window. Windows end at document boundaries. In the interface and
the HTTP API they also end at sentence boundaries by default
(`within_sentence=true`).

## Event space and contingency table

CandyConc uses the contingency table for distance-based co-occurrence of
Evert (2004, figure 2.13). The windows of all node hits are merged into one
set of positions $W(u)$. A position that lies in the windows of two node hits
belongs to $W(u)$ once. Every token position of the scope is one event, and
the table crosses "inside $W(u)$" with "is the collocate $v$":

|  | token is $v$ | token is not $v$ | total |
| --- | --- | --- | --- |
| inside $W(u)$ | $O_{11}$ | $O_{12}$ | $R_1 = \lvert W(u) \rvert$ |
| outside $W(u)$ | $O_{21}$ | $O_{22}$ | $N - R_1$ |
| total | $C_1 = f(v)$ | $N - C_1$ | $N$ |

- $O_{11}$ is the number of tokens of $v$ inside $W(u)$, the **co-occurrence
  count** (column `observed`).
- $R_1$ is the size of the merged window. It includes punctuation and node
  tokens that lie in the window of a neighboring node hit.
- $C_1 = f(v)$ is the frequency of $v$ in the scope, in exactly this spelling
  (column `f2`).
- $N$ is the size of the scope in tokens, punctuation included.
- The expected co-occurrence count under independence is
  $E_{11} = R_1 C_1 / N$ (column `expected`).

The other cells follow: $O_{12} = R_1 - O_{11}$, $O_{21} = C_1 - O_{11}$,
$O_{22} = N - R_1 - C_1 + O_{11}$. The method card names this definition in
the fields `event_space`, `row_marginal_definition`, and
`column_marginal_definition`. It reports $R_1$ as `window_union_size` and
$N$ as `scope_tokens`, so that every column of a row can be recomputed from
its $O_{11}$ and $f(v)$. For *freedom* in the English sample corpus, with a
window of 5 and windows that stop at sentence boundaries, $R_1 = 4{,}250$ and
$N = 403{,}284$.

In a document set, $C_1$ and $N$ are counted in the document set.

**Candidates.** Every word form inside $W(u)$ is a candidate, except the
spellings of the node itself. Each spelling of a collocate is its own
candidate. After scoring, only word tokens are shown, so punctuation does not
appear as a collocate.

### Minimum co-occurrence

Candidates with a small $O_{11}$ are dropped before the measures are ranked. Without an explicit minimum, CandyConc derives it
from the node frequency $f(u)$:

$$
\text{minimum} = \max\bigl(2, \min(\lfloor f(u) / 10 \rfloor, 5)\bigr)
$$

From $f(u) = 50$ on, the minimum is 5. An explicit minimum can be 2 or more.
The method card reports the minimum that was applied
(`effective_min_cooccurrence`), whether it was derived or given
(`floor_mode`), and the node frequency (`node_frequency`).

## Measures

All measures in the following table are derived measures, except the raw counts $O_{11}$ and
$f(v)$ and the LRC, which is an estimate. The column names are those of the
API and the exports.

| Column | Measure | Formula | Source |
| --- | --- | --- | --- |
| `observed` | co-occurrence count | $O_{11}$ | |
| `f2` | frequency of the collocate | $C_1 = f(v)$ | |
| `expected` | expected co-occurrence count | $E_{11} = R_1 C_1 / N$, rounded to 2 decimals | Evert 2009 |
| `mi` | pointwise mutual information | $\log_2 (O_{11} / E_{11})$ | Church and Hanks 1990 |
| `mi3` | MI³ | $\log_2 (O_{11}^3 / E_{11})$ | Evert 2009 (MI^k with k = 3) |
| `lmi` | local MI | $O_{11} \log_2 (O_{11} / E_{11})$ | Evert 2004 |
| `npmi` | normalized PMI | $\log_2 (O_{11} / E_{11}) \,/\, \bigl(-\log_2 (O_{11} / N)\bigr)$ | Bouma 2009 |
| `t` | t-score | $(O_{11} - E_{11}) / \sqrt{O_{11}}$ | Church et al. 1991, Evert 2009 |
| `z` | z-score | $(O_{11} - E_{11}) / \sqrt{E_{11}}$ | Evert 2009 |
| `chi2_cell` | contribution of cell 11 to Pearson's χ² | $(O_{11} - E_{11})^2 / E_{11}$ | Pearson 1900 |
| `ll` | log-likelihood G² | $2 \sum_{ij} O_{ij} \ln (O_{ij} / E_{ij})$ over all four cells | Dunning 1993, Evert 2009 |
| `dice` | Dice coefficient on the window table | $2 O_{11} / (R_1 + C_1)$ | Dice 1945, Evert 2009 |
| `logdice_window` | logDice on the window table | $14 + \log_2 \bigl(2 O_{11} / (R_1 + C_1)\bigr)$ | log transformation after Rychlý 2008 |
| `logdice` | logDice | $14 + \log_2 \bigl(2 O_{11} / (f(u) + f(v))\bigr)$ | Rychlý 2008 |
| `delta_p_nc` | ΔP, node to collocate | $O_{11} / R_1 - O_{21} / (N - R_1)$ | Gries 2013, Ellis 2006 |
| `delta_p_cn` | ΔP, collocate to node | $O_{11} / C_1 - O_{12} / (N - C_1)$ | Gries 2013 |
| `log_ratio` | Log Ratio | $\log_2 \dfrac{(O_{11} + 0.5) / R_1}{(O_{21} + 0.5) / (N - R_1)}$ | Hardie 2014 |
| `lrc` | conservative Log Ratio | see the following section | Evert 2022 |

For MI³, CandyConc uses Evert’s $MI^k$ formulation. Daille (1994, page 119)
uses $\log_2(O_{11}^3 / (R_1 C_1))$, written in the symbols above. CandyConc’s
scores are higher by
$\log_2 N$, so the two forms rank collocates identically for a fixed $N$.

The default sort order is `logdice`.

**Two logDice columns.** `logdice` follows Rychlý (2008): the denominator is
the sum of the frequencies of node and collocate, $f(u) + f(v)$, and it can
be compared across nodes and corpora. Rychlý gives orientation points for
the scale: 14 for a pair whose words always occur together, usually values
below 10, and one point more for a co-occurrence twice as frequent. He gives
no threshold for notable collocations. In a window table, $O_{11}$ counts
collocate tokens, and one window can hold a collocate several times, so
$O_{11}$ can exceed $f(u)$ and `logdice` can exceed 14. `logdice_window`
applies the same transformation to the Dice coefficient of the window table,
whose denominator is $R_1 + C_1$. It depends on the size of the merged window
and is meaningful only within one result list. The two columns can rank
collocates differently.

**Log Ratio smoothing.** Hardie (2014) defines Log Ratio as the binary
logarithm of the ratio of two relative frequencies, without smoothing.
CandyConc adds 0.5 to both counts so that the value is defined when a count is
zero. The value therefore differs slightly from the unsmoothed ratio even
when no count is zero. The method card states the smoothing.

**Conservative Log Ratio (LRC).** The LRC follows the procedure of Evert
(2022). It takes the exact Clopper and Pearson (1934) confidence interval for
the proportion $O_{11} / (O_{11} + O_{21})$, converts both bounds to the Log
Ratio scale, and reports the bound closer to zero, or 0 if the interval
contains zero. The confidence level is corrected for multiple testing with
the Bonferroni method (Dunn 1961): $\alpha = 0.001 / m$, where $m$ is the number of
candidate collocates after the minimum co-occurrence and the word-token
filter. Punctuation is never a row and is not tested, so it does not count
in $m$. The method card reports $m$ as `lrc_tests`, the level as
`lrc_alpha`, and the correction as `lrc_correction`. For *freedom* in the
English sample corpus with the default settings, $m = 111$. Evert (2022)
recommends $\alpha = 0.05 / m$. CandyConc uses the stricter level 0.001.

## Assumptions and interpretation

- The table treats every token position as an independent event. Words in
  texts are not independent events: they cluster in documents and topics.
  CandyConc does not derive p-values from the collocation table, and the LRC
  uses a strict significance level.
- Measures of association answer different questions (Evert 2009). MI, MI³,
  NPMI, logDice, and Log Ratio express how strong the association is. MI in
  particular gives high values to rare pairs. The t-score and G² express how
  much evidence there is against independence, and they grow with frequency.
  Report the measure you ranked by.
- A collocate is counted in its exact spelling, and the node in all
  spellings. *The* and *the* can therefore appear as two collocates of one
  node. Use the lemma attribute to merge spellings on the collocate side.
- The co-occurrence count is not the number of concordance lines behind a
  collocate. See
  [From numbers to lines](../concepts/from-numbers-to-lines.md#from-a-collocation-row-to-the-lines).

## Example

Collocations of *tea* in the synthetic tea corpus, window 3, windows ending at
sentence boundaries. The 17 node hits (13 × *tea*, 3 × *Tea*, 1 × *TEA*) give
a merged window of $R_1 = 74$ positions in a corpus of $N = 162$ tokens. The
derived minimum is $\max(2, \min(1, 5)) = 2$.

```{example-table} collocation-tea
```

The remaining measures for the same rows:

```{example-table} collocation-tea-more
```

Recomputed by hand for `green` ($O_{11} = 6$, $f(v) = 6$):

- $E_{11} = 74 \cdot 6 / 162 = 2.7407$
- $\text{MI} = \log_2 (6 / 2.7407) = 1.1304$
- $\text{logDice} = 14 + \log_2 \bigl(12 / (17 + 6)\bigr) = 13.0614$
- Dice on the window table $= 12 / (74 + 6) = 0.15$, so
  $\text{logDice (window)} = 14 + \log_2 0.15 = 11.2630$
- $\Delta P$ node to collocate $= 6 / 74 - 0 / 88 = 0.0811$
- $\Delta P$ collocate to node $= 6 / 6 - 68 / 156 = 0.5641$
- $\text{Log Ratio} = \log_2 \bigl((6.5 / 74) / (0.5 / 88)\bigr) = 3.9504$

The LRC is 0 for every row: with at most six co-occurrences, the exact
interval at $\alpha = 0.001 / m$ contains zero. Without the sentence limit,
the merged window grows to $R_1 = 77$.

The rows `A` and `a` show that each spelling of a collocate is its own row,
while the node covers all spellings. The script
`docs/_tools/check_worked_examples.py` recomputes every value in both tables
from the corpus file. See [Worked examples](worked-examples.md).

## Collocation network

The collocation network shows a node, its strongest collocates, and
optionally their own strongest collocates.

- The first ring holds the strongest collocates of the node by the chosen
  measure, by default `logdice`.
- With depth 2, up to $\max(5, \lfloor (\text{nodes} - 1) / 2 \rfloor)$
  collocates of the first ring become hubs, and their strongest collocates
  are added as a second ring.
- Each edge carries the measure computed with the hub as node. Because the
  merged window depends on the node, the value of an edge depends on its
  direction. An edge is added once, in the direction in which it is first
  found.
- By default, the minimum co-occurrence is 5 and windows end at sentence
  boundaries. The HTTP API accepts other settings through `min_count` and
  `within_sentence`. A network has at most 120 nodes.
- The size of a node in the graph is the co-occurrence count $O_{11}$ of
  that word with the hub through which it was first reached, not its corpus
  frequency. The response names this hub for every node in `freq_via`.
- The response reports whether the network was cut
  (`diagnostics.truncated`).

## Related pages

- [Find collocations](../guides/count-and-measure/collocations.md)
- [Contrast](contrast.md) compares collocations between two scopes.
- [Word sketches](word-sketches.md) count collocations by grammatical
  relation.
