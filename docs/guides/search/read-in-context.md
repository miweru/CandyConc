# Read hits in context

A concordance line shows a hit with a few words around it. This guide sorts
the lines, draws a random sample, widens the context, opens a hit in its
document, and reads whole documents in the Reader.

## Before you begin

- A search with hits, for example `freedom` in the English sample corpus.

## Sort the lines

The row above the table offers sort keys:

- **1L**, **2L**, **3L** sort by the first, second, or third token to the left
  of the node.
- **node** sorts by the node itself.
- **1R**, **2R**, **3R** sort by the first, second, or third token to the
  right.

1. Click a sort key, for example **1R**.

The label **Sorted: 1R ascending** appears, and the lines are ordered
alphabetically by that token, without regard to case. Click the same key
again to sort in descending order. Click **Default** to return to the order
of the corpus, in which the lines follow the documents and the positions
within them.

The headers **LEFT CONTEXT**, **NODE**, and **RIGHT CONTEXT** of the table
also sort, by **1L**, the node, and **1R**.

## Draw a random sample

A sample shows a random selection of the hits, for example to code or read a
manageable number of lines.

1. In the toolbar, select **Random sample**.

   The fields **N** (the sample size, 200 by default) and **Seed** appear, and
   CandyConc draws the sample at once.

2. Optional: change **N** or **Seed** and click **Draw**.

The label next to the hit count names the sample, for example
**Sample 200 of 495 · Seed 713563**. The same seed draws the same sample
again, so note it if you want to repeat the selection. Clear
**Random sample** to see all hits.

## Filter the loaded lines

The field **Filter loaded hits (text or /regex/)…** above the table hides
lines that do not contain the text you type, in the node or in the context.
A label such as **9 visible** shows how many lines remain. The filter works
on the lines that are loaded in the browser, not on the whole result. To
restrict the search itself, change the query.

## Change the width of the context

By default, CandyConc fits as much context as the width of the window allows
(**Context** with **Auto** selected).

1. Click **Auto** to turn the automatic width off.
2. Move the slider **Context width in tokens** (from 40 to 600).

For one line, the button **Expand context** in the column **ACTION** shows
more text around the hit.

## Open a hit in its document

1. Click the node of a line, or the button **Open document** in the column
   **ACTION**.

A panel opens on the right with:

- the title of the document and the button **Cite**,
- the box **Concordance line** with the token position of the hit, a longer
  context, and the token range of the context,
- the metadata fields of the document in their order. Fields that have the
  same value in every document of the corpus are collected under
  **Same in every document of the corpus**,
- the full text, in which every occurrence of the searched word is
  highlighted, with the number of occurrences.

The highlight in the full text marks every occurrence of the word. The token
position in the box identifies the one hit that the line belongs to.

Press <kbd>Escape</kbd> to close the panel.

To select a line without opening its document, hold <kbd>Command</kbd>
(macOS) or <kbd>Control</kbd> (Linux) and click it. <kbd>Shift</kbd>+click
selects a range of lines. The label next to the hit count shows how many
lines are selected.

```{figure} ../../_static/screenshots/kwic-document-panel.png
:alt: Concordance for freedom with the document panel of the first hit open, showing the concordance line at token position 202, the metadata, and the highlighted full text.
:width: 100%

The document panel opens next to the concordance, and the line it belongs to stays selected in the table.
```

## Read whole documents

1. Click the tab **Reader**.

The left column lists the documents of the active scope, 50 per page, with
their size in tokens and the beginning of their text. With a filter or a
subcorpus active, a line above the list names the scope, for example
**Only documents in the scope: party: Republican**, and the list of the
English sample corpus holds the 36 Republican addresses. The first document
is open on the right with its title, its date, a collapsible list
**Metadata** with the number of fields, and the full text. Click a document
in the list to open it.

To narrow the list by one metadata field, open the list above the
documents that shows **Whole corpus**, or **Whole scope** with a filter
active, and choose a field, for example
**party (2)**, where the number counts the distinct values. Then choose a
value in the list **Choose value** next to it. **reset** returns to the whole
list.

## Result

You can order the lines, read a reproducible sample, and follow any hit into
its document. To keep lines for later, see
[Bookmark and annotate concordance lines](bookmark-and-annotate-lines.md). To
save them as a file, see [Export a concordance](../keep-and-share/export-concordances.md).
