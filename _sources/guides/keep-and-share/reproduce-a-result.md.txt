# Reproduce a result

A result can be computed again when you know the corpus it came from, the
query and scope, and the settings of the analysis. CandyConc records all of
them. This guide shows where to find them and how to run the analysis again,
on your computer or on another one.

## Before you begin

- The record of the result: an export file, an evidence package, a saved
  analysis, or a screenshot of the method card.

## Find the record of a result

| Record | Where it is | What it holds |
| --- | --- | --- |
| Export header | the first lines of a CSV or TSV export, the header object of JSONL | query, corpus, document set, case setting, context width, hit count, `IndexFingerprint`, and the query as JSON (`QueryJson`) |
| Evidence package | an `evp_*.json` file | scope, corpus fingerprints, result summary with row checksum, method blocks, rows |
| Method card | **Method and reproducibility** in an analysis view | every statistic with formula, smoothing, and sort key, and for most analyses the sizes of the scope, the minimum frequency, and the index fingerprint |
| Saved analysis | **Saved analyses** in the workspace | the type, the corpus, the query, the scope, and all settings of the view |
| Analysis CSV | the CSV of an analysis view | the settings in its first lines, for example `Window`, `WithinSentence`, `Measure`, and `MinFreq` for collocations |

## Identify the corpus

A result depends on the corpus, including its annotation. Record:

- the name of the corpus and the input file it was imported from,
- the import command or the options of the corpus manager, in particular the
  annotation pipeline and its version. The file `index_manifest.json` in the
  index folder records `annotation_pipeline`, `annotation_pipeline_version`,
  and `language`,
- the build fingerprint in `index_manifest.json` (`build_fingerprint`).

The same input imported with the same pipeline gives the same tokens and
annotation. A different pipeline gives a different annotation: on the English
sample corpus, `cql:[lemma="freedom"]` finds 499 hits with `en_core_web_md`
and 501 with `en_core_web_sm`, while the plain search `freedom` finds 495
with both.

The fingerprints that results carry answer narrower questions. The index
fingerprint in a method card identifies the index folder on this computer in
its current state. The `IndexFingerprint` of an export identifies the
documents and their metadata, and it is the same for both imports of the
example. See [The corpus index](../../concepts/corpus-index.md#fingerprints).

## Run the analysis again

1. Select the corpus in the corpus selector. On another computer, import the
   same input file with the same options first, see
   [Import a corpus](../bring-in-texts/import-a-corpus.md).
2. Set the same scope: the same metadata filter, or the same subcorpus.
3. Enter the query from the record.
4. Open the analysis view.
5. Set the parameters from the method card, the CSV header, or the saved
   analysis.

Compare the raw counts of the result with the record, for example the hit
count with `TotalMatches` or the co-occurrence frequency of a collocate. For
an evidence package, export a new package with the same query and settings
and compare `row_hash_sha256`.

A saved analysis stores the settings for you. Open it with
**Open analysis**, after you have selected the corpus and scope, see
[Save analyses and workspaces](save-analyses.md).


## Keep a run record or citation

In the Copilot panel, open **Research > Reproduce** and scroll to
**Run export**. Select one or more of the recent runs. **Export as JSON**
saves their records together with the recorded corpus and scope information.
The export replaces action payloads with a redaction marker and clears raw
trace histories. **Export BibTeX** saves one citation entry per selected run
in `candyconc_references.bib`.

Keep the JSON alongside the citation. The BibTeX entry identifies the run,
its date, analysis action, corpus, and recorded scope information. The
[format reference](../../reference/export-formats.md#run-records-and-bibtex)
describes both files.

## Result

You can say exactly which corpus, annotation, query, scope, and settings a
result comes from, and compute it again. How each kind of number relates to
the corpus positions is explained in
[From numbers to lines](../../concepts/from-numbers-to-lines.md).
