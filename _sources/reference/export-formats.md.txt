# Export formats

CandyConc exports concordances and evidence packages. Every export records
the query, the scope, and fingerprints of the index, so that you can tell
later on which data and with which settings the file was made. This page
lists the fields of each format. How to export from the web interface is
described in [Export concordances](../guides/keep-and-share/export-concordances.md)
and [Export evidence packages](../guides/keep-and-share/export-evidence-packages.md).

The examples on this page come from the State of the Union sample corpus with
the plain search `freedom` (495 hits).

## Concordance exports

The server writes a concordance export with `POST /api/v1/export/concordance`
(see [HTTP API reference](http-api.md)). It contains all hits of the query in
the chosen scope, up to the export cap of 1,000,000 lines. The count of all
hits is exact, also when the lines stop at the cap.

| Format | `format` | Media type | Provenance |
| --- | --- | --- | --- |
| CSV | `csv` | `text/csv` | comment lines at the start of the file |
| TSV | `tsv` | `text/tab-separated-values` | comment lines at the start of the file |
| XLSX | `xlsx` | Excel workbook | second sheet |
| JSON | `json` | `application/json` | fields of the top-level object |
| JSON Lines | `jsonl` | `application/x-ndjson` | first line, `"type": "header"` |

The request fields are `query` (required, a plain search or a query with
`cql:`), `corpus`, `docset_id` (a document set, see
[Scope](../concepts/scope.md)), `ctx` (context width in tokens, default 5),
`sort` and `sort_dir`, `case_insensitive` (default true), and `format`
(default `csv`). `dialect: "excel-de"` writes CSV with semicolons and a UTF-8
byte order mark for spreadsheet programs with German settings.

### Lines

CSV, TSV, and XLSX have these columns:

| Column | Content |
| --- | --- |
| `pos` | token position of the node of the hit in the corpus, see [Queries and hits](../concepts/queries-and-hits.md#the-concordance-line) |
| `doc_id` | internal number of the document |
| `doc` | document ID of the import |
| `left` | left context |
| `node` | the node token. The other tokens of a hit that covers several tokens are at the end of `left` or the start of `right`. |
| `right` | right context |
| `meta` | the metadata of the document as a JSON object |
| `match` | all tokens of the hit. For a hit of one token it is the same as `node`. |
| `match_start` | token position of the first token of the hit |
| `match_end` | token position of the last token of the hit. For a hit of one token, `match_start`, `match_end`, and `pos` are the same. |

For the query `cql:[pos="ADJ"] [lemma="freedom"]`, the first line on the
English sample corpus has `pos` 1104, `node` *freedom*, `left` ending with
*political*, `match` *political freedom*, `match_start` 1103, and
`match_end` 1104. `match` is read from the index, so it is complete also
when `ctx` is smaller than the hit.

`left`, `node`, `right`, and `match` show the text with its original spacing
when the corpus index stores it (`TRUMAN'S ADDRESS`, `freedom.`), and with a
space after every token when it does not (`TRUMAN 'S ADDRESS`, `freedom .`).
See [Original spacing](../concepts/corpus-index.md#original-spacing).

JSON and JSON Lines lines have the same fields, and also `docId` and
`document` with the same values as `doc_id` and `doc`.

A cell that starts with `=`, `+`, `-`, or `@` gets a leading `'`, so that a
spreadsheet program does not run it as a formula.

### Provenance

CSV and TSV start with comment lines. The output is similar to the following:

```text
# CandyConc Export
# Schema: candyconc-concordance-export-v1
# Query: freedom
# Corpus: sotu_en
# DocsetId: 
# Sort: 
# SortDir: asc
# CaseInsensitive: true
# ContextTokens: 5
# Format: csv
# TotalMatches: 495
# ExportedRows: 495
# ExportCap: 1000000
# Truncated: false
# Timestamp: 2026-09-27T00:10:16.474675+00:00
# IndexFingerprint: sha256:9ebff910249394f4caea2bc8f4c777d0736cf449d82d7570f57511130e92545b
# MetadataSchemaHash: sha256:7cbda15f0cd73a36777862d9fc95b2dc5751e7a55d06b8ac02477e76229fb9e3
# FingerprintStrength: structural_index_artifacts
# QueryJson: {"case_insensitive":true,"corpus":"sotu_en","ctx":5,"docset_id":null,"format":"csv","query":"freedom","sort":null,"sort_dir":"asc"}
pos,doc_id,doc,left,node,right,meta,match,match_start,match_end
```

XLSX has the lines on the first sheet and the same fields on the second
sheet. The sheets are named `Concordance` and `Provenance`, and the second
sheet has the columns `Field` and `Value`, when the export is requested from
the English interface or with `Accept-Language: en`. Otherwise they are
named `Konkordanz` and `Provenienz`, with the columns `Feld` and `Wert`. The
field names and the column names of the lines are the same in both
languages. JSON and JSON Lines carry them as `term`, `total_matches`,
`exported_rows`, `export_cap`, `truncated`, `timestamp`, `query`,
`indexFingerprint`, `metadataSchemaHash`, and `fingerprintStrength`.

The response headers repeat the counts: `X-CandyConc-Export-Total-Matches`,
`X-CandyConc-Export-Exported-Rows`, `X-CandyConc-Export-Cap`,
`X-CandyConc-Export-Truncated`, and `X-CandyConc-Index-Fingerprint`.

| Field | Meaning |
| --- | --- |
| `TotalMatches` | number of all hits of the query in the scope |
| `ExportedRows` | number of lines in the file |
| `Truncated` | `true` when the lines stopped at the export cap. The file is then not the complete concordance. |
| `IndexFingerprint`, `MetadataSchemaHash` | see [Fingerprints and checksums](#fingerprints-and-checksums) |

## Evidence packages

An evidence package is a JSON document that describes one concordance so that
it can be checked and repeated: query, scope, index fingerprints, counts, a
checksum of the lines, the method blocks, and the lines themselves. The
server writes it with `POST /api/v1/export/evidence-package`. The request
fields are those of the concordance export without `format`, plus
`include_rows` (default true).

```json
{
  "schema_version": "candyconc-evidence-package-v1",
  "package_id": "evp_6dc955c476eb3728bcdc1c7c",
  "generated_at": "2026-09-27T00:32:11.724954+00:00",
  "query_trace_id": "qtr_632839d4b59c4be2bcc44adea320f892",
  "scope": {"query": "freedom", "corpus": "sotu_en", "docset_id": null, "sort": null, "sort_dir": "asc", "case_insensitive": true, "ctx": 5},
  "corpus": {
    "name": "sotu_en",
    "fingerprint_sha256": "d8098ffda4b6294a0127f0e2bc0b15a8fa01815d19cd1983e34a9c9d951ae7cf",
    "indexFingerprint": "sha256:9ebff910249394f4caea2bc8f4c777d0736cf449d82d7570f57511130e92545b",
    "metadataSchemaHash": "sha256:7cbda15f0cd73a36777862d9fc95b2dc5751e7a55d06b8ac02477e76229fb9e3",
    "fingerprintStrength": "structural_index_artifacts",
    "docset_id": null,
    "docset_fingerprint_sha256": null
  },
  "result_summary": {
    "total_matches": 495,
    "exported_rows": 495,
    "export_cap": 1000000,
    "rows_included": 0,
    "truncated": false,
    "complete_within_export_cap": true,
    "row_hash_sha256": "bd1be531f888879d8c18e52c29115fc443c43ec6f8ce0b63e0ca10f54d90acba"
  },
  "method_blocks": ["..."]
}
```

The example is shortened: `corpus` also has `index_fingerprint` (the same
value as `indexFingerprint`) and `cacheSignature`, `result_summary` also has
`observed_hit_count`, and `method_blocks` has two entries. With
`include_rows: true` the package also has `rows`, the lines in the format of
the JSON export.

| Field | Meaning |
| --- | --- |
| `schema_version` | format of the package, `candyconc-evidence-package-v1` |
| `package_id`, `query_trace_id` | identifiers of this export. They differ for every export, also of the same query. |
| `scope` | the query and all settings that determine the lines |
| `corpus` | the corpus, its fingerprints, and the document set with its fingerprint |
| `result_summary` | the counts, whether the lines are complete, and the checksum of the lines |
| `method_blocks` | how the lines were collected, with the parameters and the limits of the package |

### Reports from an evidence package

The export dialog of the web interface also renders an evidence package as a
report:

- **LaTeX**: written in the browser from the evidence package.
- **PDF** and **Word**: the server converts the report with pandoc
  (`POST /api/v1/export/pdf` and `/api/v1/export/docx`). pandoc must be
  installed on the server, and PDF also needs a LaTeX installation. They are
  not part of CandyConc.

## Fingerprints and checksums

| Value | Computed from | Tells you |
| --- | --- | --- |
| `IndexFingerprint` (`indexFingerprint`) | SHA-256 of the document count, the number of document boundaries, and the fields of the metadata index with their types and value counts | whether two exports come from the same index state. It describes the structure of the index, not its text, as `FingerprintStrength: structural_index_artifacts` says. |
| `MetadataSchemaHash` | SHA-256 of the fields of the metadata index with their types and value counts | whether the metadata fields are the same. A saved subcorpus is marked `stale` when this value changes. |
| `row_hash_sha256` | SHA-256 of all exported lines (position, document, contexts, hit, metadata) in canonical JSON | whether two exports contain exactly the same lines. The same query on the same index gives the same value. |
| `corpus.fingerprint_sha256` | SHA-256 of the index fingerprint, the document set ID, and the document set fingerprint | whether two packages have the same corpus and scope |
| `docset_fingerprint_sha256` | SHA-256 of the document set ID, its corpus, its filter, and the metadata schema hash | which filter defined the document set |

To check that an export still describes your corpus, run the same query in
the same scope again and compare `TotalMatches` and `row_hash_sha256` (in an
evidence package) or the lines. See
[Reproduce a result](../guides/keep-and-share/reproduce-a-result.md).

## Other exports

- **Loaded lines as TSV.** **Copy lines** above the concordance copies the
  loaded lines to the clipboard as a tab-separated table. **Loaded lines**
  and **Loaded excerpt** in the export dialog leave **Export** disabled.
  For a file, choose **Server concordance**. See
  [Export concordances](../guides/keep-and-share/export-concordances.md#export-exactly-the-lines-you-see).
- **Line annotations.** `GET /api/v1/annotations` returns the annotations of
  a corpus. `POST /api/v1/annotations/import` reads records with the fields
  `row_id`, `category_id`, `note`, and `annotator`.
- **Analysis results.** Tables of analyses are returned by the analysis
  routes as JSON with a method block, see
  [How CandyConc counts](../methods/index.md).


## Run records and BibTeX

**Copilot > Research > Reproduce > Run export** exports selected recent run
records in the browser. See [Reproduce a result](../guides/keep-and-share/reproduce-a-result.md#keep-a-run-record-or-citation).

A JSON package has `version: "1.0"`, `type` (`run` or `runs`), `createdAt`
(a Unix timestamp in milliseconds), and `title`. One selected run is stored
under `run`, multiple runs under `runs`. The records retain their corpus and
scope information. Action payloads are replaced by
`{"redacted": true, "reason": "run_export_default"}`, and raw trace histories
are empty arrays.

The BibTeX file contains one `@misc` entry per selected run. Its key is
`candyconc_` followed by a normalized run ID. The title comes from the run
summary. The entry records the date and, in `note`, the run ID, analysis
action, corpus ID, scope hash, scope status, and metadata-schema hash.
The JSON file holds the fuller run record referenced by that note.
