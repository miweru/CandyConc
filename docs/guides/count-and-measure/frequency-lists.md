# Make a frequency list

A frequency list counts how often each word form, lemma, or part of speech
occurs in the active scope. This guide makes a list, restricts it to one
part of speech, and opens the lines behind a row.

## Before you begin

- An active corpus. Lemma and part-of-speech lists need a corpus imported
  with a trained pipeline, see
  [Choose language and annotation layers](../bring-in-texts/choose-annotation.md).
- Optional: a metadata filter or an active subcorpus, if the list should
  count only part of the corpus. The list always counts the active scope.

## Make the list

1. Click the tab **Frequency**.

   The list of word forms in the active scope appears. The label at the top
   left names the scope, for example **Whole corpus**.

2. Optional: in the first list above the table, choose what to count: word
   forms, lemmas, or parts of speech.
3. Optional: under **Limit**, choose how many rows to show: 50, 100, 250, or
   500.

In the English sample corpus, the list of word forms starts with *the*
(20,907), *of* (13,003), and *and* (12,849). The line
**RESULT EVIDENCE** above the table states what was counted, for example
**Basis: Word form (case folded)**, the token policy, and
**Shown: 100 of 13,070 candidates**.

A frequency list of word forms or lemmas ignores case: one row counts all
spellings that are equal in lowercase. It leaves out tokens without a letter
or digit, such as punctuation.

## Restrict the list to one part of speech

1. In the field **POS**, enter the beginning of a part-of-speech tag, for
   example `NOUN`.
2. Press <kbd>Enter</kbd>.

The list shows only word forms with that part of speech, and the line
**RESULT EVIDENCE** adds **POS prefix: NOUN**. In the sample corpus, the
list then starts with *people* (1,314), *world* (1,145), and *year* (1,104).
The field is available for word form lists.

## Open the lines behind a row

1. Click a word in the table, for example **peace**.

CandyConc switches to the tab **KWIC** and runs the query
`cql:[word="peace"%c]`. The concordance shows **649 hits**, the frequency of
the row.

## Show a chart or save the list

- **Chart** shows the counts as a bar chart, **Table** returns to the table.
- **CSV** downloads the list with the counting basis in its first lines.
- **Save** stores the settings as a saved analysis, see
  [Save analyses and workspaces](../keep-and-share/save-analyses.md).

```{figure} ../../_static/screenshots/frequency-word-forms.png
:alt: Frequency list of word forms in sotu_en with the result evidence (100 of 13,070 candidates shown) and the first rows the 20,907, of 13,003, and and 12,849.
:width: 100%

The line **RESULT EVIDENCE** names the counting basis, the case policy, the excluded tokens, and how many candidates the table shows.
```

## Result

You have the frequencies of the active scope and can open the lines behind
each of them. The counting unit, the case policy, and the tokens that are
left out are described in [Frequency and hits](../../methods/frequency.md).
