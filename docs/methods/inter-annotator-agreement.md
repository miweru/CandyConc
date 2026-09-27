# Inter-annotator agreement

When several people assign categories of a coding scheme to the same
concordance lines, CandyConc measures how often they agree. The values come
from the line annotations stored in the project file.

## What is counted

**Basis.** Line annotations of named coders, each with a category. A line
enters the computation only if at least two coders annotated it
(`n_rows_overlap`).

**Pairs.** On each such line, every pair of coders is compared.

## Measures

| Column | Measure | Computation | Source |
| --- | --- | --- | --- |
| `percent_agreement` | observed agreement | agreeing pairs divided by all pairs, pooled over all lines. Lines with more coders have more pairs and weigh more | |
| `kappa` | chance-corrected agreement | with exactly two coders in the project, Cohen's κ. With three or more, a form of Fleiss' κ that allows a different number of coders per line. Values close to 0 are set to 0 | Cohen 1960, Fleiss 1971 |
| `per_category_agreement` | agreement per category | the pairs in which both coders chose the category, divided by the pairs in which at least one of them chose it | |

Fleiss (1971) assumes the same number of coders for every line. The variant in
CandyConc allows lines with different numbers of coders. For a line $i$,
let $n_{ij}$ be the number of coders who chose category $j$ and $n_i$ the
number who annotated that line. Its agreement is

$$
P_i = \frac{\sum_j n_{ij}^2 - n_i}{n_i(n_i-1)}.
$$

Each included line has equal weight in $\bar P$, the mean of $P_i$.
Category proportions pool the annotations:
$p_j = \sum_i n_{ij} / \sum_i n_i$. The resulting measure is

$$
P_e = \sum_j p_j^2,
\qquad \kappa = \frac{\bar P-P_e}{1-P_e}.
$$

The separately reported `percent_agreement` weights lines by their number
of coder pairs, as described in the table.

The agreement per category is a Jaccard-type ratio, $a / (a + b + c)$, where
$a$ counts the pairs in which both coders chose the category and $b$ and $c$
the pairs in which only one of them did. It is lower than the specific
agreement $2a / (2a + b + c)$ that is often reported per category, unless both
are 0 or both are 1.

**Kind of numbers.** Derived measures.

## Related pages

- [Bookmark and annotate concordance lines](../guides/search/bookmark-and-annotate-lines.md)
