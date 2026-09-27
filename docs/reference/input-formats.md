# Input formats

This page describes the files that CandyConc imports: which columns or fields
each format needs, how metadata and document IDs are taken over, how paired
texts are grouped, and which rows are rejected. The steps of an import are in
[Import a corpus](../guides/bring-in-texts/import-a-corpus.md), the command
line options in [Command line reference](cli.md#candy-import-in-brief).

## Overview

| Format | `--input-format` | Recognized extensions | One document is | Text from |
| --- | --- | --- | --- | --- |
| CSV or TSV | `csv` | `.csv`, `.tsv` | one row | a text column |
| JSON Lines | `jsonl` | `.jsonl`, `.ndjson` | one line (a JSON object) | a text field |
| Plain text | `plaintext` | `.txt`, or a folder | one file, or one paragraph | the file |
| Parquet | `parquet` | `.parquet` | one row | a text column |
| VRT (verticalized text) | `vrt` | `.vrt`, `.xml` | one segment element | the token lines |
| Hugging Face dataset | `hf` | none, `--input` is the dataset ID | one row | a text column |
| Paired CSV, JSON Lines, or Parquet | `prealigned-csv`, `prealigned-jsonl`, `prealigned-parquet` | none, always set the format | one row, grouped by a pair key | a text column |

All text is read as UTF-8. Invalid byte sequences are replaced, not rejected.

## Text normalization

Before annotation, CandyConc normalizes every text the same way:
Unicode normalization form NFKC and line breaks as `\n`. Other white space
becomes a space, and remaining control and format characters (Unicode
categories Cc and Cf) are removed. Runs of spaces become one space. Spaces
around line breaks and at the ends of the text are removed, and more than
two consecutive line breaks become two. The file `index_build_meta.json`
records this as `text_normalization: basic_nfkc_whitespace`. The import stores for each
token whether a space followed it in the normalized text, see
[Original spacing](../concepts/corpus-index.md#original-spacing).

Texts longer than `--max-doc-chars` characters (default 1,000,000) are split
into several documents at paragraph breaks or, if necessary, at white space.
The parts get the document ID with `#0`, `#1`, and so on. `--no-split-long-texts`
keeps them whole.

## CSV and TSV

- The first row holds the column names. A UTF-8 byte order mark before it is
  removed.
- The field separator is detected from the first 8 KB of the file among
  comma, semicolon, tab, and vertical bar, unless you set `--delimiter`.
- `--text-column` names the text column (default `text`).
- `--id-column` names the column with the document ID (default `id`). When the
  column is missing or empty in a row, the document gets the ID `doc-N`, where
  `N` is the row number counted from 0.
- `--meta-columns` names the columns that become document metadata, separated
  by spaces. Without it, no column becomes metadata.
- A column named `source` sets the `source` field of each row. Otherwise
  `--source` sets it for all rows.

Example with a document ID and two metadata columns:

```text
id,text,genre,year
d1,"The river rose after heavy rain.",news,2021
d2,"Rain fell on the river all night.",fiction,2022
```

```bash
candy import --input corpus.csv --output ~/.candyconc/corpora/my_corpus \
  --meta-columns genre year --spacy-model en_core_web_sm
```

## JSON Lines

Each non-empty line is one JSON object. The options are the same as for CSV.
Nested fields can be named with a dot, for example `--meta-columns meta.author`.

```text
{"id": "d1", "text": "The river rose after heavy rain.", "genre": "news", "year": 2021}
{"id": "d2", "text": "Rain fell on the river all night.", "genre": "fiction", "year": 2022}
```

A line that is not valid JSON, that is not an object, or that is longer than
64 MB is rejected with the reason `malformed_json`, `non_object_line`, or
`line_too_large`.

## Plain text

`--input` is a single file or a folder. In a folder, every file that matches
`--pattern` (default `*.txt`) in the folder and its subfolders is imported,
except files whose real location is outside the folder. Each file becomes one
document. `--split-paragraphs` makes one document of each paragraph instead
(paragraphs are separated by an empty line).

- The document ID is the path of the file relative to the folder, with `#N`
  added for paragraphs.
- For files in a subfolder, the metadata field `register` holds the name
  of that subfolder. Files directly in the import folder use `--source`,
  which defaults to `plaintext`.

## Parquet

A Parquet file is read like a CSV file: one document per row, with the same
options (`--text-column`, `--id-column`, `--meta-columns`, `--source`,
`--reject-policy`). `candy import` uses the text column `text` unless you name
another one. The import form of the web interface proposes `input_text`,
which you can change.

If the file has no column of that name, `candy import` stops and lists the
columns of the file. A file without the text column but with a column
`target_text` is read in the paired layout of an earlier research data model.
The options `--include-prompts` and `--allow-missing-input-text` also choose
that layout.

## VRT

VRT is the verticalized text format of the IMS Open Corpus Workbench: one
token per line, the columns of a token separated by tabs, and structural
elements such as `<text>` and `<s>` on lines of their own.

```text
<text id="t1" genre="news" date="2021-03-04">
<s>
The	the	DET
river	river	NOUN
rose	rise	VERB
.	.	PUNCT
</s>
</text>
```

- `--segment-tag` (default `text`) is the element that becomes one document.
  `--sentence-tag` (default `s`) names the sentence element that `--inspect`
  reports. The sentence boundaries of the index come from the spaCy pipeline.
- The attributes of the segment element and of the element named by
  `--text-tag` fill the metadata fields `doc_id`, `source`, `register`,
  `date`, and `genre`. `--id-attrs`, `--source-attrs`, `--register-attrs`,
  `--date-attrs`, and `--genre-attrs` name the attributes for each field.
  Without these options, CandyConc looks for common attribute names such as
  `id`, `xml:id`, `source`, `date`, and `genre`. `candy import` keeps no other
  attributes.
- A document is named by its ID from the file, for example `t1` for
  `<text id="t1">`, or by the file name and its number (`corpus_2`) when it
  has none. As in a CSV import, `variant` is `document` and `model` is `none`
  unless `--variant` and `--model` give other values. VRT indexes built with
  an earlier version name their documents `t1::source::` followed by a
  checksum and keep working.
- `--token-columns` names the columns of the token lines, for example
  `word,lemma,pos`. `--word-column` (default `word`) is the word form.
- The document text is rebuilt from the word forms. With `--join-mode smart`
  (default), no space is put before punctuation. The modes `sidecar` and
  `none` store the spacing of this rebuilt text (manifest field
  `whitespace: vrt_join`).
- `--annotation-mode sidecar` (default) annotates the rebuilt text with the
  spaCy pipeline of `--spacy-model` and keeps the columns of the file in a
  side file (`vrt_token_annotations.jsonl`) of the index, where they are not
  searchable. `none` drops them.
- The annotation mode `adopt` takes the `lemma`, `pos`, and `morph` columns of
  the file as searchable attributes, with the tokenization of the file and
  without spaCy. The tags stay in the tag set of the file, and the manifest
  records `annotation_source: gold_vrt`. Named entities and dependency
  relations are not available in this mode. The file holds no spacing, so
  lines show a space between all tokens (manifest field
  `whitespace: pretokenized`). `adopt` is offered by the import
  in the web interface (Corpus manager) and the import API, not by
  `candy import`.
- `--inspect` prints what CandyConc finds in the file without building an
  index.

A corpus that is already encoded in the Corpus Workbench can be decoded with
`cwb-decode -C` and converted to this layout with
`python -m candyconc.ingest.cwb_decode_to_vrt --segment ELEMENT`, which copies
the attributes of enclosing elements onto every segment. `ELEMENT` is the
structural element that becomes one document.

## Hugging Face datasets

`--input-format hf` reads a dataset from the Hugging Face Hub. `--input` is
the dataset ID, `--hf-config` and `--hf-split` (default `train`) select the
configuration and split, and `--limit` imports only the first rows. The other
options are the same as for CSV. The format needs the `hf` extra
(`pip install "candyconc[hf]"`) and a network connection. Code that a dataset
ships is never run.

## Paired texts

A paired corpus groups several variants of the same source text, for example
an original and its simplified versions. Each row is one variant.

| Column (option) | Default | Content |
| --- | --- | --- |
| text (`--text-column`) | `text` | the text of the variant |
| ID (`--id-column`) | `id` | the document ID of the variant |
| pair key (`--pair-key-column`) | `pair_id` | the same value for all variants of one source text |
| pair role (`--pair-role-column`) | `pair_role` | the role of the variant, for example `source` or `simplified` |
| variant (`--variant-column`) | none | optional name of the variant, stored in the field `variant` |
| model (`--model-column`) | none | optional name of the program or person that produced the variant, stored in the field `model` |

- Each group needs exactly one row whose role is the anchor role
  (`--anchor-role`, default `source`). The other variants are aligned to it.
- A group with no anchor or more than one anchor is rejected with the reason
  `invalid_anchor_count`. A group with only the anchor is rejected with
  `singleton_pair_group`. Rows without a pair key or a role are rejected with
  `missing_pair_key` or `missing_pair_role`.
- In the index, the anchor has the field `text_type` with the value `anchor`
  and the other variants the value `version`. The role from the file stays in
  the field `pair_role`. Without a model column, the field `model` also holds
  the role, so the parallel concordance lists the variants under their roles.
  Indexes with builder revision 1 or lower (see
  [Index format](index-format.md)) use the values `human` and `ai` for the
  two sides and `human` as the model of the anchor. They keep working.
- `--pair-order grouped` reads large inputs one group at a time and needs the
  rows of each group to be adjacent. The default `unsorted` keeps all rows in
  memory.

```text
id,pair_id,pair_role,text
s1,p1,source,"The committee postponed the decision."
s1-easy,p1,simplified,"The group will decide later."
```

```bash
candy import --input pairs.csv --input-format prealigned-csv \
  --output ~/.candyconc/corpora/my_pairs --spacy-model en_core_web_sm
```

## Metadata

- Metadata values are stored as text. Select explicit values or a list of
  values when filtering a field such as `year`, see [Scope](../concepts/scope.md).
- The fields `doc_id`, `path`, `source`, `variant`, `model`, and `text_type`
  are set by CandyConc for every document. A metadata column with one of these
  names is ignored.
- `text_type` is `standalone` for the documents of an unpaired import (CSV,
  JSON Lines, plain text, Hugging Face, Parquet with a text column, VRT) and
  `anchor` or `version` for paired texts. VRT indexes built with an earlier
  version record `human` and keep working.
- All metadata fields go into the filter index unless `--meta-index-fields`
  names a subset.

## Rejected rows

Rows that cannot become a document are not imported. With
`--reject-policy collect` (default), the import continues and the index
contains `reject_report.json` with the number of rows seen, the number of
rows rejected, the count for each reason, and up to 50 rejected rows.
`--reject-report FILE` writes every rejected row to `FILE` as JSON Lines. With
`--reject-policy fail_fast`, the import stops at the first rejected row.

| Reason | Meaning |
| --- | --- |
| `empty_text_column` | The text column is missing or empty in this row. |
| `malformed_json`, `non_object_line`, `line_too_large` | A JSON Lines line cannot be read (see [JSON Lines](#json-lines)). |
| `missing_pair_key`, `missing_pair_role`, `invalid_anchor_count`, `singleton_pair_group` | A paired row or group is incomplete (see [Paired texts](#paired-texts)). |
