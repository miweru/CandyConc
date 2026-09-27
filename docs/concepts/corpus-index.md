# The corpus index

When you import a corpus, CandyConc builds an index: a directory of binary
files that stores every token of every document at a numbered position,
together with its annotation, the sentence and document boundaries, and the
document metadata. Every search, every count, and every statistic reads this
index. The text files you imported are not needed afterward.

## Tokens at corpus positions

The index follows the positional data model of the IMS Open Corpus Workbench
(CWB, Evert and Hardie 2011). The corpus is one long sequence of tokens. Each token has a corpus
position, starting at 0, and each annotation layer is an attribute that has
one value at every position.

The following table shows positions 190 to 205 of the English sample corpus
(State of the Union addresses 1945 to 2006, imported with `--language en`,
that is with the spaCy pipeline `en_core_web_md` and dependency relations).
The values are read from the index files.

| Position | `word` | `lemma` | `pos` | Sentence | `rel` | Head |
| --- | --- | --- | --- | --- | --- | --- |
| 190 | The | the | DET | 8 | det | 191 |
| 191 | world | world | NOUN | 8 | nsubj | 192 |
| 192 | knows | know | VERB | 8 | ROOT | 192 |
| 193 | it | it | PRON | 8 | nsubj | 195 |
| 194 | has | have | AUX | 8 | aux | 195 |
| 195 | lost | lose | VERB | 8 | ccomp | 192 |
| 196 | a | a | DET | 8 | det | 198 |
| 197 | heroic | heroic | ADJ | 8 | amod | 198 |
| 198 | champion | champion | NOUN | 8 | dobj | 195 |
| 199 | of | of | ADP | 8 | prep | 198 |
| 200 | justice | justice | NOUN | 8 | pobj | 199 |
| 201 | and | and | CCONJ | 8 | cc | 200 |
| 202 | freedom | freedom | NOUN | 8 | conj | 200 |
| 203 | . | . | PUNCT | 8 | punct | 192 |
| 204 | (line break) | (line break) | SPACE | 8 | dep | 203 |
| 205 | Tragic | tragic | ADJ | 9 | amod | 206 |

Three things in this table matter for everything you count:

- Punctuation marks are tokens. The full stop at position 203 has its own
  position and its own values.
- A spaCy pipeline keeps line breaks of the source text as tokens with the
  part of speech `SPACE` (position 204). In the English sample corpus, 6,577
  of the 403,284 tokens are such whitespace tokens and 41,361 are
  punctuation.
- The head of a dependency relation is stored as a corpus position. Position
  202 (freedom) depends on position 200 (justice).

The corpus size that CandyConc reports is the number of positions, so it
includes punctuation and whitespace tokens. Some analyses count only word
tokens and say so in their method card. See
[How CandyConc counts](../methods/index.md).

## Token attributes

Which attributes an index has depends on the import:

| Attribute | Content | Present when |
| --- | --- | --- |
| `word` | the word form as it appears in the text | always |
| `lemma` | the base form assigned by the pipeline | always. With a `blank:` pipeline, the lemma is the lowercased word form |
| `pos` | the part of speech. With a spaCy pipeline these are Universal Dependencies tags (`NOUN`, `VERB`, `ADJ`, and so on) | always. With a `blank:` pipeline, every token has `X` |
| `morph` | the part of speech followed by the morphological features, separated by vertical bars, for example `ADJ\|Degree=Pos`. A token without features has `_` after the part of speech | always. Indexes built before the correction of the import (builder revision 0 in the manifest) lack the value for many tokens, see [Troubleshooting](../help/troubleshooting.md#an-index-lacks-morphological-features) |
| `ent` | the named entity type | the import used `--enable-ner` |
| `rel`, `head` | the dependency relation and the position of the head | the pipeline has a dependency parser and the import did not use `--no-deps` |

A VRT import in the mode that adopts the annotation of the source keeps the
tags of the source instead, for example STTS tags from a German CWB corpus.
[Languages and annotation](languages-and-annotation.md) explains the
difference between tokenization and annotation, and
[Query language](../reference/query-language.md) lists which attributes a
query can use.

## Sentences and documents

Sentence boundaries and document boundaries are stored as lists of start
positions. The English sample corpus has 17,758 sentences in 65 documents.

- Without dependency relations, a rule-based component splits sentences at
  sentence-final punctuation. With dependency relations, the dependency parser
  sets the sentence boundaries.
- Every document starts a new sentence.
- No query match, collocation window, or n-gram crosses a document
  boundary. Patterns of the query language and collocation windows also stay
  within a sentence unless you ask for more. See
  [Queries and hits](queries-and-hits.md).

## Document metadata

Each document has an identifier and a set of metadata fields, for example
`president`, `party`, `year`, and `date` in the English sample corpus. The
import stores the columns you name with `--meta-columns`. A metadata index
lists, for every field and value, the documents that have it. Metadata filters,
subcorpora, and the `where(...)` clause of the query language all use this
index. The import stores every metadata value as a character string, so a
filter compares values with `=` and `!=`, not with `<` or `>`. See
[Scope, subcorpora, and document sets](scope.md).

## Lexicons, postings, and compressed streams

For each attribute, the index keeps:

- a **lexicon** that maps each distinct value to a numeric ID, with
  additional prefix and trigram indexes that speed up wildcard and regular
  expression lookups,
- a **token stream** with the ID at every position (compressed for `word`
  and `lemma`),
- **postings**, the list of positions for each ID, in compressed form,
- a **document list** for each ID, so that the documents containing a word
  are known without reading its positions.

A query for a word form therefore does not scan the text. It looks up the ID
in the lexicon and reads the postings for that ID. A sequence query
intersects the postings of its parts. See
[Queries and hits](queries-and-hits.md).

## The index manifest

The file `index_manifest.json` describes the index. The import writes it
last, so an index without a complete manifest is an unfinished build. It
records:

- the manifest version, the import mode (for example `jsonl` or `csv`), and
  whether the corpus is paired,
- the source of the annotation (`spacy` for a pipeline import),
- the **capabilities**: which attribute lexicons, boundaries, and optional
  files exist,
- the **build fingerprint**, a SHA-256 value computed during the build,
- the language of the corpus, the annotation pipeline and its version, and
  the revision of the import code,
- the creation time and a flag that the build completed.

In the corpus catalog, a corpus has a `name` and an `id`. The name is the
name of its index folder, and it is the key by which every route of the HTTP
API and the corpus selector address the corpus. The ID is the build
fingerprint. Two builds of the same input with the same settings have the
same ID: importing the synthetic tea corpus twice into two folders gave two
corpora with different names and one ID. Importing the same input once
through the command line and once through the interface also produced the
same build fingerprint. A corpus opened with `CANDYCONC_INDEX_PATH` has the
name `default`, and the catalog gives its folder name in `display_name`.

A manifest with a newer version than the installed CandyConc understands is
rejected with a request to update CandyConc. An index without a manifest,
built by an older version, is described from the files that are present.

## Capabilities

The server derives the capabilities of a corpus from the manifest and the
files on disk and reports them at `GET /api/v1/corpora/{name}/capabilities`.
They decide which views and tools are available:

| Capability | Needed for |
| --- | --- |
| lemma and part of speech lexicons | lemma and part of speech queries, frequency lists by lemma or part of speech |
| dependency relations (`rel`) | word sketches and dependency queries |
| named entities (`ent`) | entity queries |
| sentence and document boundaries | sentence scope, dispersion, document views |
| word similarity index (`faiss_word.index`, `word_ids.npy`) or static vectors from the annotation pipeline | the word thesaurus |
| passage vectors | semantic passage search |
| sentence vectors | embedding-based alignment of paired documents |
| paired documents | parallel concordances and version comparison |

Embedding files can be added to an index after the build, and the
capabilities change with them.

## Fingerprints

CandyConc reports three identifiers for an index. They answer different
questions:

- The **build fingerprint** in the manifest identifies what was built. It is
  the corpus ID in the corpus catalog, and identical builds share it.
- The **index fingerprint in a method card** is a 12-character value derived
  from the location of the index directory and the time its files were last
  written. It tells you whether two results were computed on the same index
  directory in its current state. It changes when you rebuild the index or
  move it to another location, even if the content is the same.
- The **index fingerprint in a concordance export** is a SHA-256 value over
  the document count, the metadata index, and the document metadata. The
  export labels it `structural_index_artifacts`. It identifies the document
  and metadata structure of the corpus, not the tokens.

To state which corpus a result comes from, report the corpus name, the
build fingerprint, and the annotation pipeline with its version. To check that two results on your computer used the same
index, compare the index fingerprints in their method cards.

## Original spacing

The index stores tokens, not the character stream of the source. For the
spacing, the import keeps one flag per token in the file
`whitespace_after.bin`: whether a space followed the token in the
normalized text (see [Input formats](../reference/input-formats.md#text-normalization)).
CandyConc joins the tokens with these flags in concordance lines, the
document panel, the full text in the Reader, Co-KWIC lines, concordance
exports and evidence packages, and the concordance lines the copilot
receives. Positions 197 to 205 of the table above then read
`heroic champion of justice and freedom.` followed by a line break and
`Tragic`, not `freedom . Tragic`.

The flags change only the displayed text. Positions, hit counts, the tokens
a hit covers, collocation windows, and every statistic count tokens and are
the same with and without the file. An API row with the original spacing
lists the start of each token in `token_starts`, so a program can still
address the tokens of a line (see [Use the HTTP API](../guides/automate/use-the-http-api.md)).

The file holds one byte per token, plus an 8-byte header. For the English
sample corpus with its 403,284 tokens that is 403,292 bytes, about 2 percent
of the index.

Every import writes the file, except in these cases, where lines show a space
after every token (`freedom . Tragic`):

| Case | Manifest field `whitespace` |
| --- | --- |
| the import ran with `--no-capture-whitespace` (option **Keep the original spacing** off in the corpus manager) | `disabled` |
| a VRT file imported with the annotation mode `adopt`: the file holds tokens without their spacing | `pretokenized` |
| an index built before CandyConc stored the spacing (`builder_revision` below 3) | empty |

A VRT file imported with spaCy (modes `sidecar` and `none`) gets the spacing
of the text CandyConc rebuilds from its word forms, `whitespace: vrt_join`.
Imports of all other formats record `whitespace: text`. To add the spacing to
an older index, import the corpus again.

## Limits

Corpus positions are 32-bit values. An index holds fewer than 2^31 tokens
(about 2.1 billion), and each lexicon holds fewer than 2^32 distinct values.

## Related pages

- [Queries and hits](queries-and-hits.md): how a query becomes positions.
- [Languages and annotation](languages-and-annotation.md): what a pipeline
  adds to the tokens.
- [Index format](../reference/index-format.md): the files of an index.
