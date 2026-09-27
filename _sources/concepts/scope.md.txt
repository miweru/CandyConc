# Scope, subcorpora, and document sets

Every search and every analysis in CandyConc runs on a scope: the whole
active corpus or a set of its documents. The scope decides which hits are
found, and it also decides the denominators of every rate and every test.
This page explains the three objects that define a scope and why each result
states the scope it was computed on.

## Corpus, document set, and subcorpus

**Corpus.** The active corpus is the index you selected in the corpus
catalog. Without further restriction, an operation runs on all of its
documents.

**Document set.** A document set is a resolved list of documents of one
corpus. It is what an operation actually computes on when you restrict the
scope. CandyConc creates a document set in three ways:

- from a **metadata filter**, for example all documents whose `party` is
  `Republican`,
- from a **search**, as the documents that contain at least one hit,
- as the **intersection** of two document sets.

A document set has an ID (`docset_id` in the API) and lives in the memory of
the server. It ends when the server stops. The interface keeps track of the
document set that belongs to your current filter and creates a new one when
needed.

**Subcorpus.** A subcorpus is a named definition that you save: a metadata
filter or a search query for a given corpus. It is stored in the project
file and survives restarts. When you use a subcorpus, CandyConc resolves the
definition against the corpus again and obtains a fresh document set. If the
metadata schema of the corpus has changed since the subcorpus was saved, the
resolved result is marked as stale.

In short, a subcorpus is how you keep a scope, and a document set is how an
operation receives it.

## Metadata filters

A metadata filter names one or more metadata fields and the values to keep:

- A single value keeps documents with exactly that value.
- Several values for the same field keep documents with any of them.
- Conditions on different fields must all hold.
- A condition can also exclude a value (`!=`).

The import stores metadata values as character strings. Filters therefore
compare with `=` and `!=`. A range condition such as `year >= 1990` is
rejected with a message, and a range of years is written as a list of the
years you want.

A filter on a field name that does not exist in the corpus keeps no
documents. Check the field names in the filter panel or in the metadata
schema before you rely on an empty result.

The query language has the same filters inside a query:
`cql:where(party="Republican", [lemma="freedom"])` finds the 329 hits of the
lemma *freedom* in the 36 Republican addresses of the English sample corpus.
This condition belongs to the query. The shared document scope remains set
by the filter panel or the activated subcorpus, as shown in the scope label.
The Reader follows that shared scope. See
[Query language](../reference/query-language.md).

## Scope changes the numbers

An operation on a document set counts only positions in its documents, and
its denominators come from the same documents.

- A concordance shows only hits in the document set.
- A frequency list counts only tokens in the document set.
- Collocations compute the expected frequency from the frequency of each
  collocate in the document set and from the size of the document set.
- Keyness compares two document sets, or one document set with the rest of
  the corpus. The two sides must not share documents.

In the English sample corpus, the Republican addresses are 36 documents with
199,379 tokens, and the Democratic addresses are 29 documents with 203,905
tokens. Keyness counts word tokens only, so its method card reports 174,284
and 180,221 as the sizes of the two sides, next to the raw token counts. The
word form *freedom*, in any capitalization, then has 330 and 165
occurrences, which are 1,893 and 916 per million word tokens. See [Keyness](../methods/keyness.md) for the full row.

## Why every result states its scope

The same word has different frequencies, different collocates, and different
key status in different scopes. A number without its scope cannot be
interpreted or repeated. CandyConc therefore reports the scope with every
analysis result:

- The method card states the sizes that the computation used, for example
  `target_total` and `reference_total`.
  [How CandyConc counts](../methods/index.md) lists for each analysis
  whether these sizes include punctuation.
- Exports of concordances record the corpus, the document set, and the query.
- The interface shows the active scope with the results.

When you report a result, name the corpus, the scope (for example the
metadata filter of the subcorpus), and the sizes from the method card. See
[From numbers to lines](from-numbers-to-lines.md).

## Related pages

- [Filter by document metadata](../guides/narrow-the-scope/filter-by-metadata.md)
- [Create and reuse subcorpora](../guides/narrow-the-scope/create-subcorpora.md)
- [How CandyConc counts](../methods/index.md): denominators of each analysis.
