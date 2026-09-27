# Contrast collocations and paired versions

A contrast compares the collocates of one word in two groups of documents,
for example the collocates of *freedom* in Republican and in Democratic
addresses. For corpora with paired versions of the same texts, the parallel
concordance compares the versions line by line. This guide covers both.

## Before you begin

- A search for the word whose collocates you want to compare, for example
  `freedom`.
- Two groups defined by metadata values or by saved subcorpora.

## Contrast the collocates of a word

1. Search for the word, for example `freedom`.
2. Click the tab **Contrast**.

   The view **Free A-vs-B contrast** names the current search as the word
   to compare.

3. Choose the kind of contrast:
   - **Word and collocation contrast** (the default) compares the collocates
     of the word in the two groups.
   - **Collocation profile contrast** compares the collocation profiles of
     the word through the collocation difference operation.
4. Under **GROUP A (TARGET)**, choose **Metadata field** or **Subcorpus**.
5. If you chose **Metadata field**, choose the field, for example **party**.
6. If you chose **Metadata field**, choose the value, for example
   **Republican**.
7. If you chose **Subcorpus**, choose a saved subcorpus.
8. Under **GROUP B (REFERENCE)**, choose the second group, for example
   **party** and **Democratic**.
9. Optional: set **Window**.
10. Optional: under **Sort by**, choose the measure.
11. Optional: adjust **Within sentence only**.
12. Click **Compute contrast**.

The result has two parts:

- **Lexical diversity** compares the vocabulary of the two groups: TTR,
  STTR, Guiraud R, the number of word tokens (N), and the number of types
  (V). See [Measure lexical diversity](lexical-diversity.md).
- **Free contrast** lists the collocates of the word with their score in
  each group (**A logDice**, **B logDice**), the difference of the scores
  (**Δ Score**), the co-occurrence frequency per million tokens of each group,
  punctuation included (**A / million**, **B / million**), its difference
  (**Δ / million**), and **Log ratio**. The line above the table states the
  ranking and whether the list was cut, for example
  **Results cut off (top 50 of 958 candidates)**.

For *freedom*, the collocate *greater* has the logDice 10.165 in Republican
and 8.791 in Democratic addresses, and 75.2 against 14.7 co-occurrences per
million tokens. A collocate that occurs in one group only, such as *work*,
shows **one side only (smoothed)** in the column **Log ratio**.

```{figure} ../../_static/screenshots/contrast-party.png
:alt: Contrast tab for freedom with group A party = Republican and group B party = Democratic, scrolled to the card Lexical diversity and the first rows of the table Free contrast, which is cut off at the top 50 of 958 candidates.
:width: 100%

The result of the contrast: the card **Lexical diversity** above, the table **Free contrast** below it. The table is ranked by the difference per million tokens, so frequent words such as *of* and *and* come first. *greater* follows further down.
```

## Go back to the lines

The numbers in the columns **A / million** and **B / million** open the
concordance of the collocate in that group. Click **75.2** in the row
*greater*: CandyConc sets the scope to group A, here **party: Republican**,
and shows the lines of *freedom* with *greater* in its window, with the
window and the sentence limit of the contrast. The line above the
concordance reads **From the contrast, group A (party = Republican): freedom
with greater, 75.2 per million, 15 co-occurrences**. A number of 0 has no
link.

The co-occurrence count counts the tokens of the collocate in the windows of
all hits of the word, and the concordance shows one line for each hit with
the collocate in its window. For *greater* in the Republican addresses, 15
co-occurrences stand in 14 lines, because the window of one hit holds two
tokens of *greater*. See
[From numbers to lines](../../concepts/from-numbers-to-lines.md). The
collocation table in the same scope shows the same co-occurrence frequency
and logDice as column A, here 15 and 10.165.

## Compare paired versions line by line

For a corpus with paired versions of the same source texts, the parallel
concordance shows, for each hit, the corresponding sentence of the other
versions with their similarity. See
[Import paired versions of source texts](../bring-in-texts/import-paired-versions.md#open-the-parallel-concordance).

## Result

You see which collocates of a word differ between two groups, how strongly,
and how large the difference is relative to the size of each group. The
definition of the contrast statistics is in [Contrast](../../methods/contrast.md).
