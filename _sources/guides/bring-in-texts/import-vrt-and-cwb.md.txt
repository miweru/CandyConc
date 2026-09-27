# Import VRT or an existing CWB corpus

VRT is the vertical text format of the IMS Open Corpus Workbench (CWB): one
token per line with tab-separated columns, and XML tags for documents and
sentences. This guide imports a VRT file and keeps its existing lemmas and
part-of-speech tags, and it shows how to turn a corpus that is only
available as an encoded CWB corpus into VRT first.

## Before you begin

- A VRT file on the computer where CandyConc runs, with one XML element per
  document (by default `<text>`) and, optionally, `<s>` for sentences.
- To convert an encoded CWB corpus: the CWB command `cwb-decode` and access
  to the registry of the corpus.

A VRT file for this guide, `sample.vrt`, with the columns word form,
part of speech, and lemma:

```text
<text id="t1" year="1901" genre="news">
<s>
The	DET	the
storm	NOUN	storm
passed	VERB	pass
.	PUNCT	.
</s>
</text>
<text id="t2" year="1902" genre="letter">
<s>
We	PRON	we
saw	VERB	see
the	DET	the
train	NOUN	train
.	PUNCT	.
</s>
</text>
```

## Choose how the annotation is used

A VRT import handles the token columns of the file in one of three
annotation modes:

| Mode | Queryable lemma and part of speech come from | The columns of the file |
| --- | --- | --- |
| `adopt` | the columns of the file, unchanged | become the attributes `lemma`, `pos`, and optionally `morph` |
| `sidecar` | the spaCy pipeline of the import | are kept in the file `vrt_token_annotations.jsonl` in the index folder, not queryable |
| `none` | the spaCy pipeline of the import | are dropped |

With `adopt`, the tag set of the file is kept as it is. A query for
`[pos="NOUN"]` finds tokens only if the file uses that tag. The mode `adopt`
is available in the corpus manager. `candy import` offers `sidecar` and
`none`.

A VRT file has one token per line and no record of the spaces between
tokens. With `sidecar` and `none`, CandyConc rebuilds the text from the word
forms (with **Token join mode** `smart`, no space before punctuation) and
shows lines with the spacing of that text. With `adopt`, lines show a space
between all tokens, and the manifest of the index records
`whitespace: pretokenized`, see
[Original spacing](../../concepts/corpus-index.md#original-spacing).

## Import the VRT file in the corpus manager

1. In the top bar, click **Manage corpora**.
2. Under **Format**, choose **VRT/XML**.
3. In **Target name**, enter a name, for example `vrt_sample`.
4. In **Server file**, enter the full path of the VRT file.
5. Set the options of the format:
   - **Token columns** (option `token_columns`): the names of the columns in
     their order in the file, for example `word, pos, lemma`.
   - **Annotation mode** (`annotation_mode`): `adopt`.
   - **Annotation pipeline (spaCy)** (`spacy_model`): `blank:en`. With `adopt`, tokens and
     sentences come from the file (one token per line, sentences from the
     `<s>` elements), and no pipeline annotates them.
   - **Date attributes** (`date_attrs`): add the name of the attribute that
     holds the date or year of a document, for example `year`.
6. Click **Check input**.
7. Click **Start import**.

When the job shows **done**, the corpus is in the catalog. For the example
file, `cql:[pos="NOUN"]` finds 2 hits and `cql:[lemma="see"]` finds 1.

## Which attributes become metadata

The attributes of the document element are mapped to metadata fields by
name. Each mapping is an option of the format, with these defaults:

| Option | Attribute names, first match wins | Metadata field |
| --- | --- | --- |
| **ID attributes** (`id_attrs`) | `id`, `xml:id`, `num`, `n`, `sid`, `sent_id`, `segment_id`, `chunk_id` | `origin_id` |
| **Source attributes** (`source_attrs`) | `source`, `source_id`, `corpus`, `name` | `source` |
| **Register attributes** (`register_attrs`) | `register`, `textclass`, `domain`, `subtype` | `register` |
| **Date attributes** (`date_attrs`) | `date`, `timestamp`, `time`, `created`, `published` | `date` |
| **Genre attributes** (`genre_attrs`) | `genre`, `register`, `textclass`, `domain`, `subtype` | `genre` |

An attribute that matches none of these lists is not stored. The import
report `vrt_import_report.json` in the index folder lists such attributes
under `attrs` and `dropped`, and the build log `build.log` names them.
Add such an attribute to the fitting list before you import, as step 5 does
for `year`. In the example, the documents then carry `date` 1901 and 1902
and `genre` news and letter.

## Import on the command line

`candy import` reads VRT files with the extension `.vrt` or `.xml` and
annotates them with the pipeline you name:

```bash
candy import --input sample.vrt --output ~/.candyconc/corpora/vrt_spacy --language en
```

The lemma and part-of-speech columns of the file stay in
`vrt_token_annotations.jsonl` and are not queryable. To query them, import
in the corpus manager with the mode `adopt`.

## Convert an encoded CWB corpus to VRT

`cwb-decode -C` writes a CWB corpus in a compact form, in which every value
of a structural attribute is its own tag, such as `<text_id t1>`. CandyConc
includes a converter that turns this output into VRT with one document
element and its values as XML attributes.

1. Decode the corpus and convert it in one pipe. Replace `REGISTRY` with the
   registry folder, `CORPUS` with the name of the corpus, and the `-P` and
   `-S` arguments with the attributes of your corpus:

   ```bash
   cwb-decode -r REGISTRY -C CORPUS -P word -P lemma -P pos -S text -S text_id -S text_year -S s | python -m candyconc.ingest.cwb_decode_to_vrt --segment text > corpus.vrt
   ```

   With the application bundle, run the converter with the Python of the
   bundle: replace `python` with `CANDYCONC_FOLDER/python/bin/python3`, where
   `CANDYCONC_FOLDER` is the unpacked bundle folder.

   `--segment` names the structural attribute that delimits a document. The
   converter reports the number of documents, sentences, and tokens on the
   error output.

2. Import `corpus.vrt` as described in
   [Import the VRT file in the corpus manager](#import-the-vrt-file-in-the-corpus-manager),
   with **Token columns** set to the `-P` attributes in their order, here
   `word, lemma, pos`.

For the compact output

```text
<text>
<text_id t1>
<text_year 1901>
<s>
The	the	DET
storm	storm	NOUN
</s>
</text_year>
</text_id>
</text>
```

the converter writes

```text
<text text_id="t1" text_year="1901">
<s>
The	the	DET
storm	storm	NOUN
</s>
</text>
```

Attributes named like `text_id` and `text_year` match none of the default
lists, so add them to the fitting options, for example `text_id` to
**ID attributes** and `text_year` to **Date attributes**.

## Result

The corpus is in the catalog with the token annotation of the original
corpus. The part-of-speech values are those of its tag set, so write queries
with these values. See [Write structured queries](../search/write-structured-queries.md)
and [Languages and annotation](../../concepts/languages-and-annotation.md).
