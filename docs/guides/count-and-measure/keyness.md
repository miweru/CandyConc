# Compare two subcorpora with keyness

Keyness finds the words whose relative frequency differs most between a
target and a reference. In CandyConc the target is always the active scope,
and the reference is the rest of the corpus, a saved subcorpus, or a second
corpus. This guide sets up the comparison, reads the table, and goes back to
the lines. The tutorial [Compare two periods](../../tutorials/compare-two-periods.md)
walks through one comparison step by step.

## Before you begin

- A metadata filter or an active subcorpus that defines the target. See
  [Filter by document metadata](../narrow-the-scope/filter-by-metadata.md).
  Without one, the view has no target.
- For a saved subcorpus as reference: the subcorpus, see
  [Create and reuse subcorpora](../narrow-the-scope/create-subcorpora.md).

## Compute keyness

1. Set the target scope, for example the filter **party: Republican**.
2. Click **More** in the tab bar.
3. Choose **Keyness**.

   The view shows the target as **Scope: Subcorpus**.

4. Under **REFERENCE**, choose the reference:
   - **Rest of the whole corpus**: every document of the corpus that is not
     in the target.
   - **Saved reference subcorpus**: a subcorpus that you saved, chosen in the
     list that appears.
   - **Second corpus**: another corpus of the catalog. Enter its name in the
     field **CORPUS**, for example `dta_de`.
5. Optional: choose the ranking statistic (**Signed LL**,
   **Log ratio (effect)**, **χ² (cell)**, **Log-likelihood**). Once a result
   is shown, the list also offers **Chi² (2x2 Pearson)** and **Chi² signed**,
   which the result supplies, so the list has six statistics. They reorder
   the candidates of the result, as a click on the header of a statistic
   column does.
6. Optional: set **MIN. FREQ**.
7. Click the button **Keyness**.

The table lists up to 500 candidates. For the Republican addresses against
the rest of the sample corpus, the first words are *Applause* and *’s*,
because the transcripts of George W. Bush from 2002 on record applause and
use typographic apostrophes. Such a result is a reason to read the lines
before you interpret it.

## Read the table

| Column | Meaning |
| --- | --- |
| **WORD** | the word form, counted without regard to case |
| **SIGNED LL** | the log-likelihood statistic G², positive when the word is relatively more frequent in the target |
| **LOG RATIO [CI]** | the binary logarithm of the ratio of the two relative frequencies, with its 95% confidence interval |
| **χ² (2X2 PEARSON)**, **χ² (CELL)** | the chi-square statistic of the 2×2 table and the contribution of the target cell |
| **P**, **Q (FDR)** | the p-value and the p-value corrected for the number of words tested |
| **DIRECTION** | the side on which the word is more frequent, with the difference per million word tokens |

A note above the table counts the candidates marked as low reliability,
because an expected frequency in their contingency table is below 5.
**Load more keyness candidates** at the end of the table shows more rows.

```{figure} ../../_static/screenshots/keyness-republican.png
:alt: Keyness for the scope party Republican against the rest of the whole corpus, ranked by signed LL, with Applause in the first row of the table.
:width: 100%

The keyness view with the reference **Rest of the whole corpus**. The table below the method notes starts with *Applause*.
```

## Go back to the lines

The frequencies of a keyword on both sides are the hit counts of the word in
the two scopes. Keep the target filter, search the word in the tab **KWIC**,
and the hit count is the target frequency. Then set a filter for the
reference documents and search again. The tutorial
[Compare two periods](../../tutorials/compare-two-periods.md#step-4-go-back-to-the-lines-on-the-target-side)
does this for *dollars* (236 and 95 hits).

## Export the table

1. After computing keyness, click **CSV** next to the **Keyness** button.
2. Leave **Keyness** selected. Keep **Include metadata and parameters**
   selected to retain the corpus, comparison and method information.
3. Click **Export** to download the `keyness_…csv` file.

The number beside **Keyness** is the number of exported candidates, including
rows not yet visible in the table. The file contains their statistics,
confidence intervals, p- and q-values, and target and reference frequencies.

## Save the settings

**Save** stores the comparison as a saved analysis, see
[Save analyses and workspaces](../keep-and-share/save-analyses.md).

## Result

You have the words that distinguish the target from the reference, with the
size of each difference and its uncertainty. The statistics, their
assumptions, and the definition of word tokens are described in
[Keyness](../../methods/keyness.md).
