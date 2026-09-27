# Choose language and annotation layers

CandyConc annotates a corpus once, when it is imported. The annotation
pipeline you choose decides which layers the index has, and the layers
decide which queries and analyses the corpus supports. This guide helps you
choose the pipeline and the optional layers before an import.

## Before you begin

- Know the language of your texts.
- Network access, if you need to download a pipeline.

## Choose the pipeline

CandyConc uses [spaCy](https://spacy.io/) pipelines. The simplest way to
choose one is the language of your texts: `--language en` on the command
line, or **Corpus language** in the corpus manager, selects the standard
pipeline of that language, for English `en_core_web_md` and for German
`de_core_news_md`. To use another pipeline, name it with `--spacy-model` or
in the option **Annotation pipeline (spaCy)**.

| Pipeline | Layers | Download |
| --- | --- | --- |
| a trained pipeline, such as `en_core_web_sm` or `de_core_news_md` | word forms, lemmas, parts of speech (Universal Dependencies tags), morphological features, sentences, dependency relations, and on request named entities | once, with `candy pipeline NAME` |
| `blank:LANG`, such as `blank:en` or `blank:fr` | word forms and sentences only. The lemma is the word form in lowercase, and every token has the part of speech `X` | none |

The pipelines tested with CandyConc and their tag sets are listed in
[Languages and annotation pipelines](../../reference/languages.md). The
difference between tokenization and linguistic annotation is explained in
[Languages and annotation](../../concepts/languages-and-annotation.md).

Without `--language` and `--spacy-model`, `candy import` uses
`de_core_news_md`. For texts in other languages, always give the language or
the pipeline.

## Download a trained pipeline

1. Download the pipeline, for example the standard English one:

   ```bash
   candy pipeline en_core_web_md
   ```

   With the application bundle, run `./candyconc pipeline en_core_web_md` in
   the bundle folder. The output ends with `Installed en_core_web_md into`
   and the target folder.

2. Import with `--language en`, or with `--spacy-model` and the name of the
   pipeline you downloaded.

If the pipeline is missing, the import stops before it starts and names the
command that downloads it. The check of the corpus manager lists the
pipeline as one of its checks.

The download sizes of common pipelines are listed in
[What CandyConc downloads](../../get-started/install.md#what-candyconc-downloads).

## Add optional layers

Two layers depend on options at import time:

| Layer | Default | Option on the command line | Option in the corpus manager | Needed for |
| --- | --- | --- | --- | --- |
| dependency relations (attributes `rel` and `head`) | on, when the pipeline has a parser | `--no-deps` turns them off | **Generate dependency relations** (`enable_deps`) | word sketches, dependency search such as `defend >dobj freedom`, the attribute `rel` in queries |
| named entities (attribute `ent`) | off | `--enable-ner` turns them on | **Generate named entities** (`enable_ner`) | queries on `ent`, for example `cql:[ent="PERSON"]` |

The trained pipelines named in this guide have a parser. The import says so
in its second line of output, for example
`Dependency parsing is on: en_core_web_md has a parser (--no-deps turns it off).`
A `blank:LANG` pipeline has no parser, so its corpora have no dependency
relations.

A layer cannot be added to an existing index. To add one, import the corpus
again into a new folder.

## What a missing layer looks like

The interface offers only what the active corpus supports and says why
something is unavailable. On a corpus imported without dependency relations,
**Word sketch** in the menu **More** is disabled with the text
**Word sketch needs corpus data that the active corpus does not provide:
token attribute rel.** A query with an attribute that the corpus lacks is
rejected with a message that names the attribute, and a part-of-speech value
that the corpus does not use is rejected with the list of valid values.

## Result

You know which pipeline and which optional layers your corpus needs, and the
import command or the corpus manager options that produce them. Continue
with [Import a corpus](import-a-corpus.md).
