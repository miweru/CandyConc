# Languages and annotation

"Does CandyConc support my language?" has several answers, one for each layer
that touches language: the text of the corpus, the annotation pipeline, the
query semantics, the interface, and the copilot. This page answers the
question layer by layer and explains the difference between splitting a text
into tokens and annotating the tokens.

## Tokenization and annotation

**Tokenization** splits a text into tokens and sentences. It decides, for
example, that *doesn't* becomes *does* and *n't*, and that a full stop is a
token of its own. Every corpus in CandyConc is tokenized.

**Linguistic annotation** adds information to each token: a lemma, a part of
speech, morphological features, and optionally a named entity type and a
dependency relation to another token. Annotation needs a trained model for
the language.

CandyConc does both at import time with a spaCy pipeline that you choose:

- A **trained pipeline**, for example `en_core_web_md` for English or
  `de_core_news_md` for German, tokenizes and annotates. Lemma and
  part-of-speech queries, frequency lists by lemma or part of speech, and,
  with dependency relations, word sketches become meaningful.
- A **blank pipeline**, written `blank:` followed by a language code, for
  example `blank:en`, only tokenizes, with the rules of that language. It
  needs no trained model and no download. CandyConc then sets every lemma to
  the lowercased word form and every part of speech to `X`.

A corpus imported with a blank pipeline still has `lemma` and `pos`
attributes, and the interface offers them. They carry no linguistic
information: a lemma query behaves like a case-insensitive word query, and a
part-of-speech query accepts only `X`. Choose a blank pipeline when no trained
pipeline exists for your language or when you only need word forms.

The import does not use a GPU, and it does not download a pipeline on its
own. `candy pipeline NAME` downloads a trained pipeline once. An import with a
pipeline that is not installed stops before it starts and names this
command.

## Layer 1: the language of the corpus

The index stores tokens, their attributes, and boundaries in the same way
for every language. Its manifest records the language of the corpus, the
pipeline, and the version of the pipeline (`language`,
`annotation_pipeline`, `annotation_pipeline_version`), and the corpus
selector and the corpus manager show the language. Indexes from versions
before these fields show the language as unknown.

Before tokenization, the import normalizes the text:

- Unicode normalization NFKC, so that compatibility characters are unified
  (for example the ligature `ﬁ` becomes `fi`) and combining characters are
  composed.
- Control characters and invisible format characters (Unicode categories Cc
  and Cf) are removed. Line breaks are kept.
- Runs of spaces and tabs become a single space.

Removing format characters also removes the zero-width joiner and the
zero-width non-joiner. Scripts that rely on these characters, such as Persian
or several Indic scripts, have not been tested with CandyConc.

These languages have been tested with the import, search, and analysis
workflows of this documentation:

| Language | Pipeline | Tested with |
| --- | --- | --- |
| English | `en_core_web_md` 3.8.0, with dependency relations | the State of the Union sample corpus, imported with `--language en` |
| English | `en_core_web_sm` 3.8.0, with dependency relations | the State of the Union sample corpus and the synthetic tea corpus |
| English | `blank:en` | the synthetic tea corpus of the worked examples |
| German | `de_core_news_md` 3.8.0, with dependency relations | a sample of 30 texts from the Deutsches Textarchiv, imported with `--language de` |

Other languages with a spaCy pipeline are expected to work the same way,
because nothing in the index depends on the language, but they have not been
tested. [Languages and annotation pipelines](../reference/languages.md) lists
the attributes and tag sets that each tested pipeline writes.

## Layer 2: the annotation pipeline

`--language` names the language of the corpus with its ISO 639 code and
chooses the standard pipeline of that language, the medium size of spaCy:
`--language en` chooses `en_core_web_md`, `--language de` chooses
`de_core_news_md`. For a language without a trained spaCy pipeline it
chooses `blank:` with the code, which only tokenizes. `--spacy-model` names
a pipeline directly. Without either option, `candy import` uses
`de_core_news_md`. See
[Choose language and annotation layers](../guides/bring-in-texts/choose-annotation.md).

From a spaCy pipeline, CandyConc stores:

- `word`, the token text,
- `lemma`, the lemma assigned by the pipeline,
- `pos`, the universal part-of-speech tag (`NOUN`, `VERB`, `ADJ`, `ADP`, and
  so on). The same tag set is used for every language.
- `morph`, the part of speech followed by the morphological features, for
  example `DET|Definite=Ind|PronType=Art`,
- sentence boundaries,
- with `--enable-ner`, the named entity type (`ent`),
- when the pipeline has a dependency parser, the dependency relation (`rel`)
  and the position of the head. `--no-deps` leaves them out.

The language-specific fine-grained tag of a pipeline, such as the STTS tag of
the German models or the Penn Treebank tag of the English models, is not
stored. A query with an STTS tag such as `[pos="NN"]` on such a corpus is
rejected, and the message lists the tags that occur. Named entities are off
by default. Without dependency relations, a rule-based component splits
sentences at sentence-final punctuation. With dependency relations, the
parser decides the sentence boundaries.

A VRT import can adopt the tokenization, the sentence boundaries, and the
annotation columns of the source file instead of running spaCy. The tags then
stay in the tag set of the source, for example STTS for a German corpus from
the IMS Open Corpus Workbench. This mode is available through the import
scripts and the HTTP API. The `candy import` command offers only the modes
that annotate again with spaCy. See
[Import VRT or an existing CWB corpus](../guides/bring-in-texts/import-vrt-and-cwb.md).

## Layer 3: query semantics

The query language and the plain search treat all languages alike:

- **Case.** Case-insensitive comparison uses Unicode lowercase mapping. It
  has no language-specific rules. The German *ß* and *ss* stay different, and
  the capital *ẞ* matches *ß*.
- **Diacritics.** CandyConc does not fold diacritics. The flag `%d` of CQP is
  rejected. To match variants with and without a diacritic, write a character
  class that contains both, as in `[word~".*fl[uü]cht.*"%c]`.
- **Normalization.** Queries are normalized with NFKC like the corpus text,
  so a decomposed character in the query matches the composed character in
  the index.
- **Part of speech.** Values of `pos` are checked against the tags that occur
  in the corpus.

On the German sample corpus, `cql:[word~".*fl[uü]cht.*"%c]` finds 63 hits
and `cql:[word~".*flucht.*"%c]` finds 30. The sample also shows that
historical spelling needs attention: its normalized texts write both *daß*
(2,043 hits for `cql:[word="daß"]`) and *dass* (716 hits for
`cql:[word="dass"]`), and a search for one spelling misses the other.

## Layer 4: the interface

The interface is available in English and German. The language setting
changes it at once, see
[Choose the interface language](../get-started/install.md#choose-the-interface-language).
Texts that the server writes follow the language of the interface: query
diagnostics, error messages, method explanations, the names of the sheets of
an XLSX export, and the glosses of word sketch relations. Over the HTTP API,
the header `Accept-Language` chooses the language of these texts, and
without it they are German. The command line (`candy import` with its
progress lines, `candy pipeline`, `candy migrate-project`) writes English.
Corpus text, metadata values, and your own labels are shown as they are.

## Layer 5: the copilot

The copilot analyzes the active corpus through the same operations as the
interface. It answers German and English questions in the detected language
of the question. For a single word or query whose language is unclear,
the interface locale chooses the answer language, followed by the request's
`Accept-Language` header and German as the fallback.

The routing rules recognize German and English question cues. Short lookup
questions in either language can be answered directly from the tool results.
Questions that need classification use the model. Headings, evidence labels,
added notes, and grouped numbers follow the answer language. The instructions
sent to the model remain German, while corpus text and search terms keep
their original wording.

See [How the copilot works](copilot.md) for the routing and answer procedure.

## Other language-dependent defaults

- **Word similarity.** The `sim(...)` operator of the query language and the
  word thesaurus take word vectors from the corpus itself: from its word
  similarity index, or from the static vectors of the pipeline that annotated
  it. The stop word list that filters the neighbors comes from the same
  pipeline. A corpus never borrows the vectors of another language, and a
  corpus annotated with an `_sm` pipeline or `blank:` has no word vectors.
  See [Word vectors](../reference/languages.md#word-vectors).
- **Word sketch labels.** The relations of a word sketch are the dependency
  labels of the pipeline. The interface names them by a gloss that follows the
  label scheme of the pipeline, ClearNLP for the English and TIGER for the
  German spaCy pipelines, in the language of the interface, for example
  **has adjectival modifier** for `amod`. A label outside these schemes is
  shown as its code.
- **Masking of personal data.** Before a copilot question goes to the model,
  CandyConc replaces e-mail addresses, IBANs, and telephone numbers in the
  question with placeholders. The patterns do not depend on the language. A
  separate masking of concordance text by named entity type, off by default
  (`CANDYCONC_ENABLE_PII_MASK`), recognizes the entity labels of the English
  pipelines, such as `PERSON`. German pipelines label persons `PER`, which
  this masking does not recognize.

## Related pages

- [Choose language and annotation layers](../guides/bring-in-texts/choose-annotation.md)
- [Languages and annotation pipelines](../reference/languages.md)
- [Query language](../reference/query-language.md)
