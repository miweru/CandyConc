# Measure dispersion

Dispersion describes how evenly the hits of a search are spread over the
documents. A word with the same frequency can occur in almost every document
or in a few documents only, and dispersion measures tell the two apart. This
guide computes them for a search.

## Before you begin

- A search with hits, for example `freedom` in the English sample corpus.
- The measures compare the documents of the active scope. A corpus with very
  few documents gives little information about dispersion.

## Compute the dispersion

1. Search for the word or query, for example `freedom`.
2. Click the tab **Dispersion**.

CandyConc counts the hits in each document of the active scope and shows
the measures. For `freedom` in the sample corpus:

| Measure | Value | Reading |
| --- | --- | --- |
| **Gries DP (raw) · documents** | 0.3626 | 0 means spread in proportion to the document sizes, 1 means concentrated in one document |
| **DP normalized** | 0.3643 | DP rescaled for the number of documents |
| **Occurrences** | 495 | the number of hits |
| **Juilland's D** | 0.8997 | 1 means very even, 0 strongly clustered |
| **Carroll's D2** | 0.9263 | 1 means very even, 0 strongly clustered |
| **Range** | 0.9538 | the share of documents with at least one hit, here 62 of 65 |
| **VC** | 0.8027 | the coefficient of variation of the per-document frequencies |

Below the values, **Basis** names the scope, the number of tokens, and the
number of documents the measures were computed on. The heat map shows the
share of hits in each document, in the order of the corpus.

```{figure} ../../_static/screenshots/dispersion-freedom.png
:alt: Dispersion of freedom in sotu_en: Gries DP 0.3626, DP normalized 0.3643, 495 occurrences, Juilland's D 0.8997, Carroll's D2 0.9263, Range 0.9538, VC 0.8027.
:width: 100%

Each card shows one measure with a short reading. The basis of the values and the heat map follow below the cards.
```

## Compare with position windows

**Position-window DP** computes DP over equally large windows of the corpus
instead of documents, 50 by default. Change the number in
**Position windows**. It is a separate comparison value. The document-based
DP is the main result.

## Check the hit positions

Under **Offset evidence**, click **Check offsets**. CandyConc loads the
positions of the hits in the current scope and shows their number and the
first ones, for example **495 offsets** and **202, 448, 863**. These are the
token positions that the concordance shows at the start of its lines, so you
can check which hits the measures count.

## Result

You know how evenly your search is spread over the documents of the scope.
To see the documents behind the numbers, search the word with a metadata
filter on the documents in question, or open the Reader. The formulas, the
reference values for DP, and a worked example are in
[Dispersion](../../methods/dispersion.md).
