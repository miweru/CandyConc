# Export a concordance

A concordance export writes the lines of a search into a file that you can
open in a spreadsheet, a script, or a text editor. CandyConc can export every
hit, counted and written by the server, or only the lines that are loaded in
the browser. This guide exports both ways and describes the file.
Use the exported concordance when preparing examples or supplementary data
for a paper.

## Before you begin

- A search with hits, for example `freedom` in the English sample corpus.
- The scope of the export is the active scope. Set a filter or a subcorpus
  first if the file should contain only part of the corpus.

## Export every hit

1. In the top bar, click **Export** (the download icon).
2. Choose **Export as CSV**.

   The dialog **Export** opens.

3. Under **Concordance file (server)**, choose the format: **CSV**, **TSV**,
   **JSON**, **JSONL**, or **XLSX**.
4. Under **Hits to export**, keep **Server concordance (fully counted)**.
5. Optional: under **Options**, clear **Include context** or
   **Include metadata**, or select **Excel-compatible CSV (semicolon, BOM)**
   for spreadsheet programs that expect semicolons.
6. Click **Export**.

The server runs the search again, counts every hit, and writes the lines.
Your browser saves the file, for example `concordance.csv`. For `freedom`,
the file has one row for each of the 495 hits.

```{figure} ../../_static/screenshots/export-dialog-format.png
:alt: Upper part of the Export dialog with CSV selected under Concordance file (server), the other formats TSV, JSON, JSONL, and XLSX, and the reports under Evidence package / report.
:width: 100%

The formats of the server concordance and of the evidence package in the **Export** dialog.
```

```{figure} ../../_static/screenshots/export-dialog-hits.png
:alt: Lower part of the Export dialog, with Include context and Include metadata selected and Server concordance (fully counted) chosen under Hits to export.
:width: 100%

Further down in the same dialog, **Server concordance (fully counted)** under **Hits to export** writes every hit.
```

## What the file contains

A CSV or TSV file starts with comment lines that begin with `#`:

```text
# CandyConc Export
# Schema: candyconc-concordance-export-v1
# Query: freedom
# Corpus: sotu_en
# DocsetId:
# CaseInsensitive: true
# ContextTokens: 40
# Format: csv
# TotalMatches: 495
# ExportedRows: 495
# ExportCap: 1000000
# Truncated: false
# IndexFingerprint: sha256:...
# MetadataSchemaHash: sha256:...
# QueryJson: {...}
```

`TotalMatches` is the full hit count, `ExportedRows` the number of rows in
the file, and `Truncated` says whether the export stopped at the limit
`ExportCap` of 1,000,000 rows. `DocsetId` names the scope when a filter or
subcorpus was active. `IndexFingerprint` identifies the documents and the
document metadata of the corpus, see [Reproduce a result](reproduce-a-result.md).

The rows have the columns `pos` (the token position of the node of the
hit), `doc_id`, `doc` (the document name), `left`, `node`, `right`, `meta`
(the metadata of the document as JSON), and `match`, `match_start`, and
`match_end` (all tokens of the hit and the positions of its first and last
token). JSONL starts with a header object that holds the
same information, followed by one object per hit. XLSX is an Excel workbook.
The fields of every format are listed in
[Export formats](../../reference/export-formats.md).

## Export exactly the lines you see

The concordance loads its lines in pages, 300 at first. The dialog **Export**
shows both numbers under **Content**, for example
**300 loaded lines · Total count: 495 hits**, so you can see whether the
loaded lines are all hits.

To keep exactly the lines you see, for example a random sample, use
**Copy lines** in the toolbar above the concordance. It copies the loaded
lines to the clipboard as a table with the columns `position`, `left`,
`node`, `right`, `source`, `doc`, `match`, `match_start`, and `match_end`,
separated by tabs. The last three name the whole hit as in the server
export, taken from the loaded context. A hit token outside the loaded
context appears as `…`. A copied random
sample starts with a comment line that names the sample size, the number of
hits it was drawn from, and the seed. Paste it into a spreadsheet or a text
file.

The options **Loaded lines** under **Hits to export** and **Loaded excerpt**
do not write a file. File exports come from the server, which runs the search
again and counts every hit, and the loaded lines exist only in the browser.
When one of the two options is selected, the button **Export** stays disabled
and the dialog names this reason and the two ways that work: **Server
concordance** for a file of the search, **Copy lines** for the loaded lines.

## Include line annotations

If lines of the search carry codes, select **Include annotations** under
**Content** for a CSV export. The file then ends with a section
`# Section: Annotations` with one row per annotated line: `row_id`, `docId`,
`position`, `category`, `note`, and `annotator`. See
[Bookmark and annotate concordance lines](../search/bookmark-and-annotate-lines.md).

## Copy single lines

**Copy line (left | node | right)** and
**Copy with citation (source, document, position)** in the column **ACTION**
copy one line, the second one with its source, document, and corpus position
in square brackets.

## Result

You have a file with the lines of your search and a header that records the
query, the corpus, the scope, the hit count, and the index state. To save the
lines together with the method record in one file, see
[Export an evidence package](export-evidence-packages.md).
