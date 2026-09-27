# Switch, register, and remove corpora

The corpus catalog lists every corpus that CandyConc can open. One of them is
the active corpus, on which searches and analyses run. This guide switches
the active corpus, adds an index that lies outside the CandyConc data folder,
and removes corpora from the catalog.

## Before you begin

- CandyConc is running with at least one imported corpus.
- Corpora that you import into the folder `corpora` of the CandyConc data
  folder (by default `~/.candyconc/corpora`) are in the catalog without
  further steps. `candy paths` shows the folder.

## Switch the active corpus

1. In the top bar, click the corpus selector. It shows the name of the
   active corpus and its number of tokens, for example
   **sotu_en · 403,284 tokens**.
2. Click the corpus you want to work with.

The selector shows the new corpus, and the address in the browser changes to
`?corpus=` followed by its name. The choice is also stored as the active
corpus of the catalog, so CandyConc opens this corpus at the next start.
While a search is running, the selector does not switch.

To choose the corpus for the next start without switching now, open
**Settings**, **General**, and choose it under **Default corpus**.

## Register an index from another folder

An index that was built elsewhere, for example on a shared drive, can be
added to the catalog without copying it.

1. In the top bar, click **Manage corpora**.
2. In the section **Register an existing index**, enter the full path of the
   index folder in **Index directory on the server**.
3. Optional: select **Use as the active working corpus after registration**.
4. Click **Register**.

The corpus appears under **CORPUS CATALOG** and in the corpus selector with
the name of its folder. The files of the index stay where they are.

## Check a corpus

Each entry under **CORPUS CATALOG** shows the state of the corpus, its
numbers of tokens and documents, the import format, and the source of its
annotation. Two buttons show more:

- **Check capabilities** reads again from the index files what the corpus
  supports, for example dependency relations or sentence boundaries.
- **Build report** loads the report that the import wrote.

## Remove a corpus from the catalog

1. In the top bar, click **Manage corpora**.
2. Under **CORPUS CATALOG**, find the corpus and click
   **Remove from registry**.

The corpus disappears from the catalog and the selector at once. The index
files are not deleted. The server refuses to remove the active corpus and the
last registered corpus, so switch to another corpus first.

**Remove from registry** is available for corpora that were registered from
another folder. For corpora in the CandyConc data folder, the button is
disabled with the note **Only registry entries can be removed. Source:
managed.**, because CandyConc lists every index in that folder.

## Delete a corpus from the data folder

To undo an import into the CandyConc data folder, delete the resulting
corpus folder:

1. Stop CandyConc with <kbd>Control</kbd>+<kbd>C</kbd> in its terminal.
2. Delete the folder of the corpus, for example
   `~/.candyconc/corpora/interviews`.
3. Start CandyConc again.

The corpus is no longer in the catalog. Deleting the folder removes the
index for good. Subcorpora and annotations that refer to the corpus stay in
the project file until you delete them. See
[Where your data lives](../../concepts/where-data-lives.md).

## Result

The catalog contains the corpora you work with, and the corpus selector
switches between them. Every result names the corpus it was computed on, see
[Scope, subcorpora, and document sets](../../concepts/scope.md).
