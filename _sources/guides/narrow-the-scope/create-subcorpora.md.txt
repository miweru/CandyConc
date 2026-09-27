# Create and reuse subcorpora

A subcorpus is a named selection of documents that CandyConc stores in the
project file, so that you can return to it in later sessions. This guide
creates subcorpora from a search and from a metadata filter, activates them
as the scope, and manages them in the workspace.

## Before you begin

- A corpus with metadata fields, for example the English sample corpus.
- Know the difference between a filter, which lasts for the session, and a
  subcorpus, which is stored. See
  [Scope, subcorpora, and document sets](../../concepts/scope.md).

## Create a subcorpus from a search

A subcorpus from a search contains every document with at least one hit of
the query.

1. Search for a word, for example `dollars`.
2. In the toolbar above the concordance, click **Save subcorpus**.
3. Optional: in the dialog **Name subcorpus**, enter your own name, for
   example `addresses mentioning dollars`, instead of the suggested name
   **Query dollars**.
4. Click **Save**.

CandyConc reports **Subcorpus saved**. The active scope stays as it was, so
the scope label next to the search field still shows **WHOLE CORPUS**. To
work in the new subcorpus, activate it as described in
[Activate a saved subcorpus](#activate-a-saved-subcorpus). The subcorpus
holds 47 documents with 322,726 tokens: 47 of the 65 addresses contain
*dollars*.

## Create a subcorpus from metadata

1. Set a metadata filter as described in
   [Filter by document metadata](filter-by-metadata.md), for example
   **party: Republican**.
2. Search for a word, for example `freedom`.
3. Click **Save subcorpus**.
4. Enter a name.
5. Click **Save**.

The subcorpus contains the documents of the filtered scope in which the
query has hits, and it stores the filter together with the query. In the
English sample corpus, 33 of the 36 Republican addresses contain *freedom*,
so the subcorpus has 33 documents with 184,651 tokens. The filter stays the
active scope.

## Activate a saved subcorpus

1. In the top bar, click **Subcorpora** (the layers icon).

   The panel **Workspace** opens on the tab **Subcorpora**. It lists your
   subcorpora with their source, for example **Source: query “dollars”**,
   and their state.

2. Optional: click **Check sizes** to compute the size of every subcorpus on
   the current index. Each entry then shows **CHECKED, UP TO DATE** and its
   size, for example **47 docs · 322,726 tokens**.
3. Next to the subcorpus, click **Activate subcorpus**.

The panel closes, and the subcorpus is the active scope for searches and
analyses. The scope label shows its source, for example
**SCOPE Query dollars**.

```{figure} ../../_static/screenshots/workspace-subcorpora.png
:alt: Workspace, tab Subcorpora, with the subcorpus addresses mentioning dollars, checked and up to date, 47 docs and 322,726 tokens, source query dollars.
:width: 640px

After **Check sizes**, the entry shows its size on the current index and the query it was made from.
```

## Rename, duplicate, archive, or delete a subcorpus

The buttons next to each subcorpus in the workspace:

| Button | Effect |
| --- | --- |
| **Rename subcorpus** | gives the subcorpus a new name |
| **Duplicate subcorpus** | stores a copy under a new name |
| **Move to archive** | moves it to the list **Archived**, out of the everyday list |
| **Delete subcorpus** | removes it from the project file |

## Combine conditions

Values of different metadata fields in one filter are combined with AND, so
a filter with **party: Republican** and **decade: 1980s** is the intersection
of both conditions. The HTTP API also intersects two document sets, see
[HTTP API reference](../../reference/http-api.md).

## Where subcorpora are stored

Subcorpora are stored in the project file `proj.ccproj` in your data folder.
A subcorpus stores its definition, the query and the filter, not a list of
documents. **Check sizes** resolves the definition again against the current
index. `candy paths` shows the location of the project file, see
[Where your data lives](../../concepts/where-data-lives.md).

## Result

Your subcorpora are stored under their names, and one click in the workspace
makes any of them the scope of your work. To compare two subcorpora, see
[Compare two subcorpora with keyness](../count-and-measure/keyness.md) and
[Contrast collocations and paired versions](../count-and-measure/contrast.md).
