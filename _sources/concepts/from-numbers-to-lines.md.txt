# From numbers to lines

Every number that CandyConc computes rests on positions in the corpus index.
This page explains which positions each kind of result counts, how you open
the concordance lines or documents behind a number, and where a number does
not correspond one to one to the lines you see. The formulas are in
[How CandyConc counts](../methods/index.md).

## Four kinds of numbers

CandyConc results contain four kinds of numbers, and only the first kind has
lines behind it:

- **Raw counts** count positions, hits, or documents: a hit count, a
  frequency in a frequency list, the co-occurrence count of a collocate, the
  frequencies in the two columns of a keyness table, the hits per document in
  a dispersion result. You can open the positions behind a raw count.
- **Derived measures** are computed from raw counts by a fixed formula: a
  rate per million, log-likelihood, logDice, Log Ratio, DP. They have no
  lines of their own. You check them by recomputing them from the raw counts
  in the same row and the sizes in the method card.
- **Estimates** describe uncertainty under a statistical model: confidence
  intervals, p-values, q-values, the conservative Log Ratio (LRC), the
  expected DP under even spread. They depend on the model assumptions that
  the methods pages state.
- **Model-generated statements** are sentences written by the language model
  of the optional copilot. They are not computed by CandyConc. Numbers that
  CandyConc inserts into a copilot answer from the tool results keep the kind
  they have in the tool result. See [How the copilot works](copilot.md).

## The method card

Analysis responses contain a method card (the field `method` in the API).
It records:

- the analysis family and, for each measure, its name, formula, smoothing,
  and literature reference,
- the default sort key,
- the index fingerprint, which identifies the index state the result was
  computed on (see [The corpus index](corpus-index.md)),
- the sizes of the scope that the computation used, such as `target_total`
  and `reference_total`,
- the window and whether windows stop at sentence boundaries,
- the case policy, and family-specific settings such as the minimum
  frequency that was actually applied and the definition of the contingency
  table.

In the interface, the method panel of keyness, n-grams, word sketches,
trends, and contrasts shows the measure with its formula and smoothing, the
sort key, the sizes of target and reference, the window, the sentence limit,
the minimum frequency, and the index fingerprint. The information button next
to a measure selector shows the formula and reference of that measure.
Several views write CSV files whose first lines are comments with the
formula, the window, and the index fingerprint.

## From a hit count to the lines

A hit count counts hits of a query. The concordance of the same query shows
one line per hit. The count and the number of lines agree as long as you load
all pages and do not draw a sample. See [Queries and hits](queries-and-hits.md).

## From a frequency list to the lines

A frequency list of word forms or lemmas counts tokens and ignores case. One
row stands for all spellings that are equal in lowercase, and the row label
is the spelling that is most frequent in the whole corpus. In the English
sample corpus, the row `the` counts 20,907 tokens of *the*, *The*, and *THE*.

To see the lines, click the row in the tab **Frequency**. CandyConc opens the
concordance of exactly the tokens that the row counts, in the same scope: for
a word form `cql:[word="the"%c]`, for a lemma `cql:[lemma="the"%c]`, and for
a part of speech `cql:[pos="NOUN"]`. The hit count equals the frequency. In
the synthetic tea corpus, the row `tea` has the frequency 17, and its lines
are 13 × *tea*, 3 × *Tea*, and 1 × *TEA*. The plain search `tea` finds the
same 17 hits, because plain search also ignores case.

The frequency list leaves out tokens without a letter or digit, such as
punctuation and line breaks. Their hits can still be searched with the query
language.

## From a collocation row to the lines

This is the most important case in which a number and the lines differ.

In a collocation row, the **co-occurrence count** (O11, column `observed`)
counts tokens of the collocate that lie inside the window of at least one hit
of the node. The windows of all node hits are first merged into one set of
positions, so a collocate token that lies in the windows of two nearby node
hits counts once. The collocate is counted in its exact spelling.

When you open the lines of a collocate, CandyConc shows **one line for each
node hit that has the collocate in its window**, with the same window, the
same sentence restriction, and the same exact spelling of the collocate as
the row. The label **Co-anchors** above the lines repeats O11, for example
**O11: peace 52**.

The two numbers therefore differ in two situations:

- A collocate token lies in the windows of two node hits. It counts once in
  O11 and appears in two lines.
- A node hit has two tokens of the collocate in its window. They count twice
  in O11 and appear in one line.

The synthetic tea corpus shows both. For the node *tea* with a window of 3
tokens, the row `green` has O11 = 6, and its lines are 7. In the sentence
*Green tea , green tea , always green tea*, the second *green* lies in the
windows of the first and the second *tea*, and the third *green* in the
windows of the second and the third *tea*. Each of them counts once in O11
and appears in two lines. The window of the second *tea* contains both of
them, so that one line holds two tokens of the collocate. The capitalized
first *Green* is counted in a row of its own, not in the row `green`. The
rows `a` (O11 = 4) and `A` (O11 = 2) open 4 and 2 lines.

The lines answer the question "where does this collocate occur near the
node?" and the co-occurrence count answers "how many collocate tokens are in
the node's context?". Both are exact. Read the row and the lines as two views
of the same contexts, not as a count and its list. See
[Association measures](../methods/association-measures.md) for the
contingency table that O11 enters.

## From a dispersion result to the documents

A dispersion result lists, for every document in the scope, the number of
hits of the query and the size of the document in tokens (fields
`partitions` and `doc_sizes`). Documents without a hit are included. Each
per-document number equals the number of concordance lines of the same plain
search in that document. DP, Juilland's D, and the other measures are
derived from these two lists and the corpus size. See
[Dispersion](../methods/dispersion.md).

## From a keyness row to the lines

A keyness row gives the frequency of a word in the target (column
`target_freq`) and in the reference (`reference_freq`). Both count tokens
and ignore case, like the frequency list. To see the lines, search the row
label as plain search with the target document set active, and then with the
reference document set active. The hit counts equal the two frequencies. The
field `surface_variants` lists the spellings that each frequency contains.
If the keyness table is restricted to one part of speech, add the condition
to the search, for example `cql:[word="freedom"%c & pos="NOUN"]`.

The rates per million in a keyness row divide by the number of word tokens of
each side, without punctuation. They are not rates of lines. See
[Keyness](../methods/keyness.md).

## From an n-gram row to the lines

An n-gram row counts every position where the sequence of word forms starts,
in exact spelling, within one document. A sequence that contains punctuation
is not listed. To see the lines, click the row in the n-gram table. CandyConc
searches the sequence with the query language and without `%c`, for example
`cql:within(<doc>, [word="A"] [word="cup"])`. The wrapper `within(<doc>, ...)`
is needed because n-grams are counted across sentence boundaries and query
patterns stay within a sentence by default.

The counts agree unless the n-gram overlaps with itself. A row for
*very very* counts two n-grams in *very very very*, and the query finds one
hit, because hits do not overlap. See
[N-grams and trends](../methods/n-grams-and-trends.md).

## From a trend to the lines

A trend counts the hits of a query in the documents of each period (year or
month of a date field) and divides by the number of word tokens in these
documents, without punctuation. Documents without a readable date form their
own group, and periods without documents are left out. A row or a point of
the trend opens the lines of its period: the scope is narrowed by a metadata
filter on the values of the date field that form the period, and the same
query runs there.
The hit count equals the hits of the period. In the English sample corpus,
the period 1945 of `freedom` over the field `year` has 7 hits, and its
concordance has 7 lines. The group of undated documents has no filter value
and no link. See [N-grams and trends](../methods/n-grams-and-trends.md).

## From a word sketch to the lines

A word sketch row counts pairs of tokens connected by a dependency relation,
with the node and the partner in their exact spelling. A click on the row
opens the dependency search of the pair, `HEAD >relation DEPENDENT` with
`[word=...]` for exact spelling. In the English sample corpus, the word
sketch of *freedom* lists *political* in the table **has adjectival
modifier** `>amod` with 5 pairs, and `[word=freedom] >amod [word=political]`
finds 5 hits. A relation shown with `<` means that the node is the
dependent, so the row *defend* in **direct object of** `<dobj` opens
`[word=defend] >dobj [word=freedom]` (12 hits).

The search finds heads, one line per head, and the row counts pairs. A head
with two dependents of the same word in the relation is two pairs and one
line: the row *members* under **prepositional modifier of** `<prep` in the
word sketch of *of* has 53 pairs and 51 lines. The line above the concordance names both numbers when
they differ. See [Word sketches](../methods/word-sketches.md).

## From a contrast row to the lines

A contrast row gives, for each group, the co-occurrence count of a collocate
with the word, as a rate per million tokens of the group, punctuation
included. The number in the column of a group opens the lines of that group:
the scope becomes the group, and the concordance shows one line for each hit
of the word with the collocate in its window, as for a collocation row. The co-occurrence count of
the group appears above the concordance, for example 15 for *greater* with
*freedom* in the Republican addresses, next to 14 lines. See
[From a collocation row to the lines](#from-a-collocation-row-to-the-lines)
and [Contrast](../methods/contrast.md).

## When the lines are a selection

The lines you see can be a selection of the hits that a number counts:

- **Pages.** The concordance loads lines in pages. The hit count always
  covers all hits.
- **Samples.** A random sample with a seed shows a subset of the hits. Its
  header states the population size.
- **Row limits.** Analysis tables return a limited number of rows. Every
  response states the number of candidates and whether the table was cut
  (`total_candidates`, `truncated`). The statistics are computed over all
  candidates before the rows are cut.

## When two views count the same word differently

Views that look alike can count different sets of positions:

- Collocations, frequency lists, and keyness ignore the case of the node or
  word. Word sketches and n-grams use the exact spelling.
- Keyness, the frequency contrast, and the trend divide by word tokens. The
  n-gram list divides by all tokens of the scope, including punctuation, and
  the n-gram contrast by the number of n-gram positions. The same bigram can
  therefore have two different rates per million for the same document set.

[How CandyConc counts](../methods/index.md) lists the counting unit and the
denominator of every analysis.
