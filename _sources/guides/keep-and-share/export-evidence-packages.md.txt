# Export an evidence package

An evidence package is a file that keeps concordance lines together with the
record of how they were found: the query, the scope, the corpus and its index
fingerprint, the method, and a checksum over the lines. It is meant for
appendices, reviews, and archives. CandyConc writes it as JSON and renders it
as a PDF, Word, or LaTeX report.

## Before you begin

- A search with hits, in the scope you want to document.
- For the PDF and Word reports: the program [pandoc](https://pandoc.org/) on
  the computer where CandyConc runs, and for PDF also a LaTeX engine
  (XeLaTeX, LuaLaTeX, or pdfLaTeX). They are not part of CandyConc. The JSON
  file and the LaTeX source need neither.

## Export the package as JSON

1. Search for the lines you want to document, for example
   `cql:[pos="ADJ"] [lemma="freedom"%c]` in the English sample corpus
   (68 hits).
2. In the top bar, click **Export**.
3. Choose **Export as CSV**.
4. In the dialog **Export**, under **Evidence package / report**, click
   **Evidence JSON**.
5. Click **Export**.

The server runs the search again and builds the package. Your browser saves
a file whose name starts with `evp_` and ends in `.json`. Its main fields:

| Field | Content |
| --- | --- |
| `schema_version` | `candyconc-evidence-package-v1` |
| `package_id`, `generated_at` | the identifier and the time of the package |
| `scope` | the query, the corpus, the document set (`null` for the whole corpus), the sort order, and the case setting |
| `corpus` | the name of the corpus, its fingerprints (`index_fingerprint`, `fingerprint_sha256`), and the hash of its metadata schema |
| `result_summary` | `total_matches`, `exported_rows`, `truncated`, `export_cap`, and `row_hash_sha256`, a checksum over the rows |
| `method_blocks` | how the rows were produced, with the parameters and the limits of each step |
| `rows` | one entry per hit: position, document, left context, node, right context, document metadata, and the whole hit (`match`, `match_start`, `match_end`) |

For the example query, `result_summary` reports 68 matches, 68 exported
rows, and `truncated` `false`.

## Export a report

1. Open **Export** > **Export as CSV** as before.
2. Under **Evidence package / report**, click **PDF**, **Word**, or
   **LaTeX**.
3. Click **Export**.

The browser saves `candyconc_export_` with the date and the extension
`.pdf`, `.docx`, or `.tex`. The report is rendered from the same package. It
starts with the provenance (package ID, time, query, corpus, document set,
corpus fingerprint), then the result evidence (full hit count, lines in the
report, whether the list is complete, the row checksum), and then the lines
with left context, node, right context, the whole hit, and the document.

```{figure} ../../_static/screenshots/evidence-report-pdf.png
:alt: First page of the PDF evidence report, with the provenance (package ID, query, corpus sotu_en, fingerprint) and the result evidence (68 hits, 68 lines, row checksum).
:width: 100%

The first page of the PDF report for the example query. It is rendered from the evidence package on the server.
```

## Check a package later

To check a package against a corpus you have:

1. Compare `corpus.index_fingerprint` in the package with the line
   `IndexFingerprint` in the header of a concordance export from your
   corpus. Equal values mean the same documents and document metadata. The
   value does not cover the tokens and their annotation. See
   [The corpus index](../../concepts/corpus-index.md#fingerprints).
2. Export a new package of the same query with the same scope and the same
   settings. Equal values of `result_summary.row_hash_sha256` mean that the
   exported rows are identical. Two packages of the same query and settings
   on the same index have the same row checksum.

## Result

You have one file that holds the lines and everything needed to trace them
back to the corpus and the query. The format of the package is described in
[Export formats](../../reference/export-formats.md). How the evidence of
analyses relates to concordance lines is explained in
[From numbers to lines](../../concepts/from-numbers-to-lines.md).
