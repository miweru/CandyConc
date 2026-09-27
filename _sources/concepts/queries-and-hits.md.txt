# Queries and hits

A query describes what to find. CandyConc turns it into a list of hits, where
each hit is a stretch of consecutive tokens in the corpus index. This page
explains how that happens, what exactly a hit is, and how a hit count relates
to token counts and document counts. The syntax is in the
[query language reference](../reference/query-language.md).

## Two ways to write a query

**Plain search** is what you type without any prefix: a word, a word with
wildcards, a phrase in double quotes, or words combined with `AND`, `OR`,
`NOT`, and `NEAR/n`. Plain search compares word forms without regard to case.

**The query language** is a CQP-style language with token conditions in
square brackets, sequences, repetition, sentence and document scope, and
metadata conditions. You mark it with the prefix `cql:`. CandyConc also
treats an input as the query language when it starts with a bracketed token
condition that contains a quoted value, as in `[lemma="free"]`, or with
`within(` or `where(`. The query language compares values exactly, including
case, unless you add the flag `%c`.

The difference in case handling shows in the counts. On the English sample
corpus, the plain search `freedom` finds 495 hits. The query
`cql:[word="freedom"]` finds 481, and `cql:[word="Freedom"]` finds the
remaining 14. The query `cql:[word="freedom"%c]` finds all 495.

## How a query runs

1. **Normalization.** CandyConc applies Unicode normalization (NFKC) and
   normalizes whitespace, so that, for example, a decomposed `ü` in your input
   matches the composed `ü` in the index.
2. **Parsing.** The query is parsed into a syntax tree. A syntax error stops
   the query with a diagnostic that points to the position of the problem.
   CandyConc never falls back to a looser search when a query is malformed.
3. **Lookup in the lexicons.** Each value is resolved to IDs in the lexicon
   of its attribute: one ID for an exact value, several IDs for a value with
   `%c`, a wildcard, or a regular expression. A part-of-speech value that
   does not occur in the corpus is an error, and the diagnostic lists the tags
   that do occur. This catches, for example, an STTS tag such as `NN` on a
   corpus annotated with Universal Dependencies tags.
4. **Candidates from postings.** For each token condition, the engine reads
   the positions of the matching IDs. For a sequence, it intersects these
   position lists, shifted by the offsets within the sequence, in an order
   that it chooses from the estimated sizes of the lists.
5. **Verification.** Candidates are checked against the full pattern by a
   finite automaton. This step handles repetition, gaps, alternatives, and
   conditions that postings alone cannot decide. It works sentence by
   sentence unless the query asks for document scope.
6. **Scope.** If a document set is active, only hits in its documents are
   kept. See [Scope, subcorpora, and document sets](scope.md).
7. **Result.** The result is the list of hits, each with the position of its
   first token and its length, in corpus order. The concordance, the counts,
   and the analyses start from this list.

## What a hit is

A hit is one occurrence of the whole pattern. A query for a single token
finds one hit per matching token. A query for a sequence of three tokens
finds one hit per occurrence of the sequence, and that hit covers three
tokens.

Hits do not overlap. The engine scans the corpus from left to right, takes
the longest match that starts at the leftmost possible position, and
continues after its end. A pattern with a longer gap can therefore produce
fewer hits than one with a shorter gap. The synthetic tea corpus used on the
[worked examples](../methods/worked-examples.md) page contains the sentence
*Green tea , green tea , always green tea .*

- `cql:[word="green"%c] []{0,1} [word="tea"]` finds three hits in this
  sentence, one for each *green tea*, and 7 hits in the corpus.
- `cql:[word="green"%c] []{0,4} [word="tea"]` finds two hits in this
  sentence. The first hit starts at the first *Green* and extends to the
  second *tea*, because that is the longest match from that position. The
  second *green* is inside that hit and cannot start another one. In the
  corpus the count is 6.

A hit count is therefore the number of non-overlapping occurrences of the
pattern. It is not the number of all pairs of tokens that satisfy the
pattern.

## Sentence scope by default

Patterns of the query language do not cross sentence boundaries unless you
ask for it. The wrapper `within(<s>, ...)` states the default explicitly, and
`within(<doc>, ...)` allows a match to span sentences within one document.
On the English sample corpus:

- `cql:[lemma="freedom"] []{0,30} [lemma="peace"]` finds 22 hits.
- `cql:within(<s>, [lemma="freedom"] []{0,30} [lemma="peace"])` finds the
  same 22 hits.
- `cql:within(<doc>, [lemma="freedom"] []{0,30} [lemma="peace"])` finds 45
  hits.

No match ever crosses a document boundary.

## Hits, tokens, and documents

Three counts appear side by side in CandyConc, and they count different
things:

- **Hits** count occurrences of the pattern, as described in the preceding
  sections. The plain search `"the people"` finds 265 hits in the English
  sample corpus. Each hit covers two tokens.
- **Tokens** count positions. A frequency list counts how many positions carry
  a word form, lemma, or tag. For a single-token query, the hit count and the
  token count agree.
- **Documents** count documents with at least one hit. The 495 hits for
  `freedom` occur in 62 of the 65 documents.

Two query forms count something else by design. `NEAR/n` in plain search
counts the positions of both words that have a partner within `n` tokens, so
`freedom NEAR/5 peace` counts occurrences of *freedom* and of *peace* (106 in
the English sample corpus). `NOT` counts every position that does not match,
including punctuation.

## Counts are exact, lines are loaded in pages

The hit count of a search is computed over all hits in the scope. It does not
depend on how many concordance lines are loaded. The count endpoint of the
API reports `partial: false` for an exact count. Concordance lines are
delivered in pages. The API returns at most 5,000 lines per request and
states in its response headers whether more lines exist and where the next
page starts.

A concordance can also be a reproducible random sample of all hits. You give
the sample size and a seed, CandyConc draws the sample without replacement
from the complete list of hits and returns it in corpus order. The response
states the requested size, the drawn size, the seed, and the size of the
population. The same query, sample size, seed, and index always give the
same lines.

## The concordance line

Each hit becomes a concordance line with left context, the hit, and right
context, together with the document and its metadata. One token of every hit
is its node. For a hit of the query language that covers several tokens, the
node is the first token of the pattern that has a fixed word or lemma value,
or the first token of the hit if no token has one. The column **NODE** shows
all tokens of the hit, and the contexts start before its first and after its
last token. For `cql:[pos="ADJ"] [lemma="freedom"]` the node is *freedom*,
and the first line on the English sample corpus shows *political freedom* in
the column **NODE**.

The node identifies the line elsewhere: the position at the start of the
line and the columns `pos` and `node` of a concordance export refer to it.
The other tokens of the hit stay in `left` and `right` of the export, and the
columns `match`, `match_start`, and `match_end` name the whole hit. For the
line above, `pos` is 1104, the position of *freedom*, `node` is `freedom`,
`left` ends with *political*, and `match` is *political freedom* from 1103
to 1104.

A phrase of plain search, such as `"the American people"`, has the first word
as its node. The column **NODE** shows the whole phrase, and an export has
the phrase in `match`.

## Related pages

- [Query language](../reference/query-language.md): complete syntax with
  tested examples.
- [The corpus index](corpus-index.md): the lexicons and postings that a query
  reads.
- [From numbers to lines](from-numbers-to-lines.md): how analysis results
  relate to hits and lines.
