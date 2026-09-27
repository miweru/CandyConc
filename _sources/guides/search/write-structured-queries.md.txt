# Write structured queries

The query language searches on the annotation of the tokens: lemmas, parts
of speech, morphology, dependency relations, and sequences of tokens, limited
to a sentence or to documents with given metadata. This guide shows the
patterns you need for these tasks. The complete grammar is in
[Query language](../../reference/query-language.md).

## Before you begin

- The active corpus must have the layers you query. Lemmas and parts of speech
  need a trained annotation pipeline, dependency relations need an import with
  dependencies. See [Choose language and annotation layers](../bring-in-texts/choose-annotation.md).
- The examples use the English sample corpus. Its part-of-speech values are
  Universal Dependencies tags such as `NOUN`, `VERB`, and `ADJ`.

## Run a query

1. In the search field, type the query with the prefix `cql:`, for example:

   ```text
   cql:[lemma="defend"]
   ```

2. Press <kbd>Enter</kbd>.

The concordance shows **70 hits**, all forms of the verb *defend*. A query
that starts with a token condition in square brackets, such as
`[lemma="defend"]`, is recognized without the prefix.

## Search by lemma or part of speech

A token condition in square brackets names an attribute and a value.

| Query | Finds | Hits |
| --- | --- | --- |
| `cql:[lemma="freedom"]` | *freedom* and *freedoms* | 499 |
| `cql:[lemma="freedom"%c]` | the same, ignoring case | 507 |
| `cql:[lemma="freedom" & rel="nsubj"]` | *freedom* as the subject of a clause | 39 |

A condition respects case unless you add `%c` after the value. Several
conditions on one token are joined with `&`.

## Search a sequence of tokens

Several conditions one after the other match consecutive tokens. `[]` is
any token, and a number range in braces repeats the preceding element.

| Query | Finds | Hits |
| --- | --- | --- |
| `cql:[pos="ADJ"] [lemma="freedom"]` | an adjective followed by *freedom* or *freedoms* | 67 |
| `cql:[lemma="freedom"] [word="of"] [pos="NOUN"]` | *freedom of* followed by a noun | 17 |
| `cql:[lemma="free"] [pos="NOUN"]{1,2}` | *free* followed by one or two nouns | 290 |

The column **NODE** of the concordance shows the whole matched sequence.

## Limit a pattern to a sentence or a document

A pattern stays within one sentence by default. `within` names the limit
explicitly:

| Query | Finds | Hits |
| --- | --- | --- |
| `cql:within(<s>, [lemma="freedom"] []{0,30} [lemma="peace"])` | *freedom* followed by *peace* in the same sentence | 22 |
| `cql:within(<doc>, [lemma="freedom"] []{0,30} [lemma="peace"])` | the same pattern across sentence boundaries within one document | 45 |

## Restrict a query to documents with given metadata

`where` adds a condition on the document metadata:

```text
cql:where(party="Republican", [lemma="freedom"])
```

This query finds **329 hits** of *freedom* in the addresses whose field
`party` is `Republican`. To restrict every search and analysis instead of
one query, use a metadata filter, see
[Filter by document metadata](../narrow-the-scope/filter-by-metadata.md).

## Build a query with a form

1. In the search field, click **Open query builder** (the wand icon).
2. Choose the token attribute.
3. Enter the value.
4. Read the query that the builder shows at the bottom.
5. Click **Use search**.

The query builder writes the query into the search field and runs it.

## When a query is rejected

A query that the engine cannot run is rejected with a message, and nothing
is counted. Common causes:

- A part-of-speech value that the corpus does not use, such as the STTS tag
  `NN` on a spaCy import. The message lists the valid values.
- An attribute that the corpus does not have, such as `ent` on a corpus
  imported without named entities.
- An unclosed bracket or quote.

The full list of diagnostics is in
[Query language](../../reference/query-language.md#diagnostics).

## Result

The concordance shows the lines that match the annotation you asked for. How
a query becomes hits, and why the node of a sequence spans several tokens, is
explained in [Queries and hits](../../concepts/queries-and-hits.md).
