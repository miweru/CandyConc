# Filter by document metadata

A metadata filter restricts every search and analysis to the documents whose
metadata match the values you choose, for example the addresses of one party
or of some decades. This guide sets such a filter, checks its size, and
removes it again.

## Before you begin

- A corpus imported with metadata fields, see
  [Import a corpus](../bring-in-texts/import-a-corpus.md). The examples use
  the fields `party` and `decade` of the English sample corpus.

## Set a filter

1. Click **Filter / Subcorpus** next to the search field.

   The panel **Subcorpus filters** opens. Under **Metadata filters** it lists
   every metadata field of the corpus with its values.

2. In the list of a field, select one or more values. To select several
   values, hold <kbd>Command</kbd> (macOS) or <kbd>Control</kbd> (Linux)
   while you click. For example, select **Republican** in the list **party**.
3. Optional: select values in further fields. Values in one field are
   combined with OR, and different fields are combined with AND.
4. Click **Apply metadata**.

The top of the panel shows the size of the scope, for example
**Subcorpus 36 docs · 199,379 tokens** for the Republican addresses, and the
chosen values are listed above the fields. Next to the search field, the
scope label changes from **WHOLE CORPUS** to **SCOPE** with the filter, for
example **SCOPE party: Republican**.

5. Press <kbd>Escape</kbd> to close the panel.

```{figure} ../../_static/screenshots/filter-republican.png
:alt: Subcorpus filters with Republican selected in the field party. The panel reports 36 docs and 199,379 tokens.
:width: 512px

The size of the filtered scope stands at the top of the panel, and the chosen values are listed above the fields.
```

## Work in the filtered scope

Every search and every analysis now counts only in the filtered documents.
In the English sample corpus, the search `freedom` finds **330 hits** with
the filter **party: Republican**, against 495 in the whole corpus. The export
and the method card of an analysis record the scope they were computed on.
With a second value in another field, for example **1980s** in **decade**,
the scope narrows to the documents that match both, here
**9 docs · 48,396 tokens**.

## Remove the filter

1. Click **Filter / Subcorpus**.
2. Click **Reset** at the top of the panel.

The scope label shows **WHOLE CORPUS** again.

## Filter one query instead of the whole scope

To restrict a single query without changing the scope, use a metadata
condition in the query language:

```text
cql:where(party="Republican", [lemma="freedom"])
```

See [Write structured queries](../search/write-structured-queries.md).

## Result

Searches and analyses run on the documents that match your filter, and the
scope label names it. A filter lasts for the session. To keep a scope under a
name, see [Create and reuse subcorpora](create-subcorpora.md). Why the scope
is part of every number is explained in
[Scope, subcorpora, and document sets](../../concepts/scope.md).
