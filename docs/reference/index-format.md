# Index format

An import writes one directory, the corpus index. This page lists its files,
the fields of its manifest, and the limits of the format. What the index is
and why it is built this way is explained in
[The corpus index](../concepts/corpus-index.md).

The format has the internal name Fast Index. A corpus index is written once
by the import and is not changed afterwards, except for the optional semantic
files that can be added later.

## Files

A file exists only when the corpus has the attribute or the feature. The
attribute names are `word`, `lemma`, `pos`, `morph`, `ent`, `rel`, and `head`
(see [Languages and annotation pipelines](languages.md)).

| Files | Content |
| --- | --- |
| `index_manifest.json` | the manifest, see [The manifest](#the-manifest). Written last, so an index without it is incomplete or older than version 1 of the format. |
| `ATTR_lexicon.bin`, `ATTR_lexicon.hash.bin`, `ATTR_lexicon.bucket.bin` | the lexicon of an attribute: every distinct value with its ID |
| `ATTR_lexicon.prefix*.bin`, `ATTR_lexicon.ngram3.*` | prefix and trigram indexes of a lexicon, for wildcard and regular expression searches |
| `ATTR_ids.svb.data.bin`, `ATTR_ids.svb.ptr.bin`, `ATTR_ids.bin` | the value ID of every token position, compressed for `word` and `lemma` |
| `ATTR_postings.r32.data.bin`, `ATTR_postings.r32.ptr.bin` | for every value, the positions of its tokens |
| `ATTR_docset.bin`, `ATTR_docset.ptr.bin` | for every value, the documents that contain it |
| `ATTR_block_top.*`, `ATTR_dense_bitset.*` | acceleration structures for frequent values |
| `pos_sentence.bin`, `pos_sentence.ptr.bin` | the parts of speech of each sentence |
| `head_ids.bin` | the position of the syntactic head of every token (with dependency relations) |
| `sentence_bounds.bin`, `document_bounds.bin` | the first token position of every sentence and document |
| `doc_metadata.mmap`, `doc_metadata.idx.bin`, `doc_metadata.crc.bin` | the metadata of every document with an index and a checksum |
| `meta_index/` | the filter index of the metadata fields |
| `meta.bin` | the number of tokens |
| `index_build_meta.json` | the settings of the import: annotation pipeline, dependency relations and named entities on or off, whether the original spacing was stored (`capture_whitespace`, `whitespace`), document, sentence, and token counts, text normalization, and the summary of rejected rows |
| `build.log`, `build_report.json`, `build_report.md` | the log and report of the import |
| `reject_report.json` | counts and examples of rejected rows, see [Input formats](input-formats.md#rejected-rows) |
| `vrt_token_annotations.jsonl`, `vrt_import_report.json` | VRT imports only: the token columns of the file and the report of the conversion |
| `whitespace_after.bin` | whether a space followed each token in the normalized text: an 8-byte count, then one byte (0 or 1) per token. Written by every import except VRT with the annotation mode `adopt` and imports with `--no-capture-whitespace`, see [Original spacing](../concepts/corpus-index.md#original-spacing) |
| `passage_vecs.npy`, `faiss_passage.index` | optional: vectors and index for passage search |
| `sentence_vecs.npy` | optional: sentence vectors for the alignment of paired texts |
| `faiss_word.index`, `word_ids.npy` | optional: word vector index for similar words |

## The manifest

`index_manifest.json` describes how the index was built and what it can do.
Example from the State of the Union sample corpus, imported with
`--language en`:

```json
{"manifest_version": 1, "import_mode": "jsonl", "paired": false, "pair_axes": [], "annotation_source": "spacy", "capabilities": {"word_lex": true, "lemma_lex": true, "pos_lex": true, "morph_lex": true, "ent_lex": false, "rel_lex": true, "embeddings": false, "sentence_bounds": true, "document_bounds": true, "word_prefix_all": true, "word_ngram": true, "sentence_embeddings": false, "whitespace_after": true}, "dtypes": {"token_positions": "uint32", "term_ids": "uint32", "head_ids": "int32"}, "build_fingerprint": "cf421952230ae6df240e238bead0f75ee5f58b81bac08e44424dc2cdf1824b0b", "created_at": "2026-09-27T07:03:07.933059+00:00", "complete": true, "language": "en", "annotation_pipeline": "en_core_web_md", "annotation_pipeline_version": "3.8.0", "pipeline_vectors": 300, "builder_revision": 3, "whitespace": "text"}
```

| Field | Content |
| --- | --- |
| `manifest_version` | version of the manifest format, currently `1` |
| `import_mode` | how the index was built, for example `csv`, `jsonl`, `vrt`, `prealigned`, or `generic` |
| `paired` | `true` for a paired corpus |
| `pair_axes` | the names of the pairings (`--pair-axis`) |
| `annotation_source` | `spacy` when a spaCy pipeline annotated the tokens |
| `capabilities` | one flag for each optional part of the index, see the next table |
| `dtypes` | integer types of the stored positions and IDs |
| `build_fingerprint` | SHA-256 of the document count, the token count, the annotation pipeline, the settings for dependency relations and named entities, and the text normalization. Two imports of the same input with the same settings produce the same value. It is not a checksum of the text. |
| `created_at` | time of the import (UTC) |
| `complete` | `true` when the import finished |
| `language` | ISO 639 code of the corpus language, taken from the pipeline, for example `en`. Empty: unknown. |
| `annotation_pipeline`, `annotation_pipeline_version` | the pipeline that annotated the corpus, for example `en_core_web_md`, and its version |
| `pipeline_vectors` | width of the static word vectors of the pipeline, `0` for none, `-1` when not recorded |
| `builder_revision` | revision of the import code. Indexes with revision `0` were built before the correction of the morphological features, see [Troubleshooting](../help/troubleshooting.md#an-index-lacks-morphological-features). From revision `2`, paired imports mark the two sides of a pair as `anchor` and `version` in the field `text_type`, see [Paired texts](input-formats.md#paired-texts). From revision `3`, every import stores the original spacing unless it is switched off |
| `whitespace` | where the spacing between tokens comes from: `text` (the imported text), `vrt_join` (the text a VRT import rebuilt from its word forms), `pretokenized` (VRT with the annotation mode `adopt`, no spacing stored), `disabled` (`--no-capture-whitespace`). Empty in indexes before revision `3` |

These fields are optional. An index that lacks them was built by an earlier
version, and CandyConc reads its language as unknown.

| Capability flag | True when the index has |
| --- | --- |
| `word_lex`, `lemma_lex`, `pos_lex`, `morph_lex`, `ent_lex`, `rel_lex` | the lexicon of this attribute |
| `sentence_bounds`, `document_bounds` | sentence and document boundaries |
| `word_prefix_all`, `word_ngram` | the prefix and trigram indexes of the word lexicon |
| `embeddings` | passage vectors (`passage_vecs.npy`) |
| `sentence_embeddings` | sentence vectors (`sentence_vecs.npy`) |
| `whitespace_after` | the original spacing (`whitespace_after.bin`) |

The flags `embeddings` and `sentence_embeddings` are read from the files at
runtime, because their files can be added or removed after the import. All
other flags keep the value of the import. `GET /api/v1/corpora/{corpus}/capabilities`
returns the flags in effect together with the features the interface derives
from them.

## Versions

- An index without `index_manifest.json` still opens. CandyConc derives the
  capability flags from the files that exist and treats it as version 0.
- An index with a newer `manifest_version` than the installed CandyConc
  supports is refused with a message to update CandyConc.
- CandyConc 0.1.0 writes version 1.

## Limits

- A corpus can have at most 2,147,483,647 tokens (2^31 - 1), because the query
  engine reads token positions as signed 32-bit integers.
- A lexicon can have at most 4,294,967,295 distinct values (2^32 - 1).

An import that would exceed a limit stops with an error, and a corpus that
exceeds a limit is refused when it is opened.
