# Languages and annotation pipelines

This page lists the token attributes that an import writes, the annotation
pipelines that have been tested with CandyConc, and the tag sets that each of
them produces. Why the language question has several answers, and how
tokenization differs from annotation, is explained in
[Languages and annotation](../concepts/languages-and-annotation.md).

## Token attributes

| Attribute | Content | Written when |
| --- | --- | --- |
| `word` | the token as it appears in the normalized text | always |
| `lemma` | the lemma from the pipeline. With a blank pipeline, the lowercased word form. | always |
| `pos` | the universal part-of-speech tag of Universal Dependencies. With a blank pipeline, `X` for every token. | always |
| `morph` | the part of speech followed by the morphological features, for example `DET\|Definite=Ind\|PronType=Art` | always |
| `ent` | the named entity type of the pipeline | with `--enable-ner` |
| `rel` | the dependency relation to the head | when the pipeline has a parser, unless `--no-deps` |
| `head` | the position of the syntactic head | when the pipeline has a parser, unless `--no-deps` |

Sentence boundaries come from the parser when dependency relations are on and
from a rule-based splitter at sentence-final punctuation otherwise. The
language-specific fine-grained tag of a pipeline (for example STTS for German
or Penn Treebank for English) is not stored.

## Choosing the pipeline

`candy import` takes the pipeline from one of two options:

- `--language CODE` names the language of the corpus with its ISO 639 code,
  for example `en` or `de`. CandyConc chooses the standard pipeline of that
  language, the medium size of spaCy (`en_core_web_md`, `de_core_news_md`,
  `fr_core_news_md`, and so on). For a language without a trained spaCy
  pipeline it chooses `blank:CODE`, which only tokenizes, and says so.
- `--spacy-model NAME` names the pipeline directly, for example
  `en_core_web_sm`, `blank:en`, or the directory of a pipeline of your own.

If both options are given and contradict each other, the import stops before
it starts. Without either, the import uses `de_core_news_md`. The pipeline
must be installed, see [Command line reference](cli.md#candy-pipeline).

Dependency relations are added by default when the pipeline has a dependency
parser, as the trained `_sm`, `_md`, and `_lg` pipelines of spaCy do.
`--no-deps` leaves them out, `--enable-deps` requires them. Named entities
are added only with `--enable-ner`.

The index records the language, the pipeline, and its version in its
manifest (see [Index format](index-format.md#the-manifest)). The corpus
manager and the corpus selector show the language of each corpus, and
corpora from older versions show it as unknown.

## Which functions need which attribute

| Function | Needs |
| --- | --- |
| plain search, concordance, frequency list of word forms, n-grams, collocations of word forms, dispersion, keyness, trends, export | `word` only, any pipeline |
| lemma queries and lemma frequency lists | `lemma` from a trained pipeline |
| part-of-speech queries and frequency lists | `pos` from a trained pipeline |
| word sketches | `rel` and `head` from a pipeline with a parser, imported without `--no-deps` |
| similar words and `sim()` in queries | word vectors of the pipeline, see [Word vectors](#word-vectors) |
| queries on named entities | `ent`, import with `--enable-ner` |

`GET /api/v1/corpora/{corpus}/capabilities` reports which attributes a corpus
has, and the web interface shows a view as unavailable, with the reason, when
the corpus lacks what it needs.

## Tested pipelines

| Pipeline | Language | Tested with | Tested attributes |
| --- | --- | --- | --- |
| `en_core_web_sm` 3.8.0 | English | the State of the Union sample corpus and the synthetic tea corpus, with dependency relations | `word`, `lemma`, `pos`, `morph`, `rel`, `head` |
| `en_core_web_md` 3.8.0 | English | the State of the Union sample corpus, imported with `--language en` | `word`, `lemma`, `pos`, `morph`, `rel`, `head`, word vectors |
| `de_core_news_md` 3.8.0 | German | the German DTA sample corpus, with dependency relations | `word`, `lemma`, `pos`, `morph`, `rel`, `head`, word vectors |
| `blank:en` | English, tokenization only | the synthetic tea corpus of the worked examples and the synthetic sample file | `word` |

The tag lists in the next section come from the sample corpora imported
with `--language en` and `--language de`, that is with `en_core_web_md` and
`de_core_news_md`. The import of the State of the Union sample corpus with
`en_core_web_sm` wrote the same sets of values. Named entities (`--enable-ner`) have
not been tested with these corpora.
Other spaCy pipelines, for other languages or other sizes, are installed with
`candy pipeline NAME` and used the same way. They have not been tested.
`blank:` followed by a language code tokenizes with the rules of that
language and needs no download.

## Tag sets

### Parts of speech (`pos`)

Both trained pipelines write universal part-of-speech tags. The values found
in the sample corpora:

| Corpus | Values of `pos` |
| --- | --- |
| State of the Union (`en_core_web_md`) | `ADJ`, `ADP`, `ADV`, `AUX`, `CCONJ`, `DET`, `INTJ`, `NOUN`, `NUM`, `PART`, `PRON`, `PROPN`, `PUNCT`, `SCONJ`, `SPACE`, `SYM`, `VERB`, `X` |
| German DTA sample (`de_core_news_md`) | `ADJ`, `ADP`, `ADV`, `AUX`, `CCONJ`, `DET`, `INTJ`, `NOUN`, `NUM`, `PART`, `PRON`, `PROPN`, `PUNCT`, `SCONJ`, `SPACE`, `VERB`, `X` |

`SPACE` marks white space tokens that the pipeline keeps, for example
several line breaks. A query with a value that does not occur in the corpus,
such as the STTS tag `NN`, is rejected, and the message lists the values that
occur.

### Dependency relations (`rel`)

The relation labels are those of the pipeline and differ between languages.

| Corpus | Values of `rel` |
| --- | --- |
| State of the Union (`en_core_web_md`, ClearNLP labels) | `acl`, `acomp`, `advcl`, `advmod`, `agent`, `amod`, `appos`, `attr`, `aux`, `auxpass`, `case`, `cc`, `ccomp`, `compound`, `conj`, `csubj`, `csubjpass`, `dative`, `dep`, `det`, `dobj`, `expl`, `intj`, `mark`, `meta`, `neg`, `nmod`, `npadvmod`, `nsubj`, `nsubjpass`, `nummod`, `oprd`, `parataxis`, `pcomp`, `pobj`, `poss`, `preconj`, `predet`, `prep`, `prt`, `punct`, `quantmod`, `relcl`, `ROOT`, `xcomp` |
| German DTA sample (`de_core_news_md`, TIGER labels) | `ac`, `ag`, `ams`, `app`, `avc`, `cc`, `cd`, `cj`, `cm`, `cp`, `cvc`, `da`, `dep`, `dm`, `ep`, `ju`, `mnr`, `mo`, `ng`, `nk`, `nmc`, `oa`, `oc`, `og`, `op`, `par`, `pd`, `pg`, `ph`, `pm`, `pnc`, `punct`, `rc`, `re`, `ROOT`, `rs`, `sb`, `sbp`, `svp`, `uc`, `vo` |

Word sketches group collocates by these labels. See
[Word sketches](../methods/word-sketches.md).

### Morphological features (`morph`)

`morph` holds the universal part of speech and the features of Universal
Dependencies that the pipeline assigns, separated by `|`, for example
`NOUN|Number=Plur` in the State of the Union sample corpus. A token without
features has `_` after the part of speech, for example `ADP|_`. Query a feature with a regular
expression, as in `cql:[morph=".*Number=Plur.*"]`. See
[Query language](query-language.md).

## Word vectors

Similar words, and `sim()` in queries, use word vectors. They come from the
word vector index of the corpus, if it has one, or else from the static word
vectors of the pipeline that annotated the corpus. They never come from a
pipeline of another language. The `_md` and `_lg` pipelines of spaCy have
static vectors. `_sm` pipelines and `blank:` have none, and for such a corpus
the capability contract reports similar words as unavailable, with the
reason. The `_md` pipelines have fewer distinct vectors than words, so many
words share a vector, and the neighbors of a word come in blocks with equal
scores. In the State of the Union sample corpus, *harmony*, *world*, *life*,
and *ideals* all have the similarity 1.0 to *freedom*. Whether the `_lg`
pipelines give more graded neighbors is not tested here. See [Semantic similarity](../methods/semantic-similarity.md).

## Corpora with their own annotation

A VRT file can carry its own annotation columns. `candy import` annotates the
text again with the spaCy pipeline and keeps the columns of the file in a
side file of the index, where they are not searchable. The import in the web
interface and the import API also offer the annotation mode `adopt`, which
makes the `lemma`, `pos`, and `morph` columns of the file the searchable
attributes, in the tag set of the file. See
[Input formats](input-formats.md#vrt).
