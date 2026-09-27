# Glossary

The terms that this documentation and the web interface use, each with its
meaning in CandyConc. Where corpus linguistics has an established term, the
documentation uses it. Other names for the same thing are listed after
"Also called".

## Corpus and data

```{glossary}
corpus
  A collection of texts that you imported, together with its index. The plural
  is corpora.

corpus catalog
  The list of corpora that CandyConc knows. The corpus selector of the web
  interface shows it, and `GET /api/v1/corpora` returns it. Each corpus has a
  name, by which the API addresses it, and an ID, the build fingerprint of
  its index.

index
  The directory that an import builds from a corpus. It stores the tokens with
  their attributes, the sentence and document boundaries, and the metadata.
  See [Index format](index-format.md). Also called: encoded corpus (CWB).

index manifest
  The file `index_manifest.json` of an index. It records how the index was
  built and which capabilities it has.

corpus capability
  Something that an index supports because it contains the needed files, for
  example lemmas, dependency relations, or a passage index.

capability contract
  The list of operations that the installation offers, with route, role, and
  corpus requirements, returned by `GET /api/v1/capabilities`.

document
  One text of a corpus with its own ID and metadata. A document is one row,
  one line, one file, or one segment of the input, see
  [Input formats](input-formats.md).

document metadata
  Fields of a document such as year, author, or genre. Also called: text
  types (Sketch Engine).

token
  The smallest unit of an index: a word, a number, or a punctuation mark.

token attribute
  A property of every token, such as `word`, `lemma`, or `pos`. Also called:
  positional attribute (CWB), annotation layer.

word form
  The token as it appears in the text, the attribute `word`.

lemma
  The base form of a token, the attribute `lemma`.

part of speech
  The word class of a token, the attribute `pos`. spaCy pipelines write
  universal part-of-speech tags. Abbreviated POS.

morphological features
  Grammatical features of a token such as number or case, the attribute
  `morph`.

named entity
  A name of a person, place, organization, or similar, the attribute `ent`.

dependency relation
  The syntactic relation of a token to its head, the attributes `rel` and
  `head`.

linguistic annotation
  Adding lemmas, parts of speech, and other token attributes at import time.
  Not the same as line annotation.

annotation pipeline
  The spaCy pipeline that tokenizes and annotates the texts of an import, for
  example `en_core_web_sm`, or `blank:en` for tokenization only.

tokenization
  Splitting a text into tokens and sentences, without further annotation.

original spacing
  The stored information whether a space followed each token
  (`whitespace_after.bin`), so that lines and texts are shown as written.
  Every import stores it unless `--no-capture-whitespace` is given.

import
  Building an index from input files.

preflight check
  The check of an input before an import: path, format, columns, and free disk
  space.

rejected rows report
  The list of input rows that an import did not take over, with the reason
  for each, in `reject_report.json`.

build report
  The log and summary of an import.

paired corpus
  A corpus in which several variants of the same source text belong together.

variant
  One version of a source text in a paired corpus, for example the original
  or a simplified version.

pair key, pair role, anchor role
  The column that groups the variants of one source text, the column that
  names the role of each variant, and the role of the variant that the others
  are aligned to.
```

## Search and context

```{glossary}
search
  Finding the positions in a corpus that match a query.

query
  A search expression, either a plain search or a query in the query
  language.

plain search
  A search without the prefix `cql:`, for words, wildcards, and phrases. It
  ignores case.

query language
  The CQP-style language for structured queries, entered with the prefix
  `cql:`. See [Query language](query-language.md).

query builder
  The panel of the web interface that assembles a query from conditions.

hit
  One position in the corpus that matches a query. Also called: match (CWB).

hit count
  The number of hits of a query in the current scope.

partial count
  A count that stopped before the end and is marked as such.

hit sample
  A random selection from all hits with a fixed seed, so that the same sample
  can be drawn again.

concordance
  All hits of a query with their context.

KWIC
  Keyword in context: the display of a concordance with the hit in the middle
  of each line.

concordance line
  One line of a concordance.

node
  The hit in the middle of a concordance line, and the word whose collocates
  are counted. In a hit of several tokens, the one token that the position of
  the line refers to.

left context, right context
  The tokens before and after the node.

context width
  How many tokens of context a concordance line shows on each side.

Reader
  The view that shows the full text of one document.

document panel
  The side panel with the details and metadata of a document.

bookmark
  A marked concordance line.
```

## Scope

```{glossary}
scope
  The part of a corpus that an operation counts on: the whole corpus or a
  subcorpus. Every result states its scope. See [Scope](../concepts/scope.md).

subcorpus
  A named, saved selection of documents, defined by metadata filters or by a
  search.

document set
  The list of documents that a subcorpus or a filter resolves to at a given
  moment. It lives in the memory of the server. In the API it is identified by
  a `docset_id`.

filter
  A condition on document metadata.
```

## Analysis

```{glossary}
frequency list
  A list of word forms, lemmas, or parts of speech with their frequencies.

raw frequency
  The number of occurrences.

frequency per million tokens
  A frequency divided by a number of tokens in the scope and multiplied by
  one million. Depending on the view, the number is the word tokens, all
  tokens, or the n-gram positions of the scope, see
  [How CandyConc counts](../methods/index.md#denominators-of-rates-per-million).

denominator
  The quantity that a count is divided by, together with where it comes from.

word token
  A token with at least one letter or digit. Some operations count only word
  tokens, see [How CandyConc counts](../methods/index.md).

case folding
  Treating upper and lower case as the same.

collocation
  A word that occurs near the node more often than expected, or the pair of
  node and collocate.

collocate
  A word that occurs within the window around the node.

window
  The number of tokens on each side of the node in which collocates are
  counted. Also called: span.

co-occurrence frequency
  How often a collocate occurs within the window of the node, written O11.

contingency table
  The four counts from which association measures are computed.

association measure
  A statistic that expresses how strongly a collocate is attracted by the
  node, such as log-likelihood or logDice. See
  [Association measures](../methods/association-measures.md).

collocation network
  A graph of collocates and their collocates.

dispersion
  How evenly a word is spread over the documents of a corpus.

DP
  Deviation of proportions, a dispersion measure by Gries.

DP reference band
  The smallest possible, the expected, and the largest possible DP value for
  the given document sizes.

n-gram
  A sequence of n tokens.

trend
  The frequency of a query along a metadata field such as year.

keyness
  The comparison of two scopes for frequency differences that are larger than
  chance would produce.

keyword
  A word that is key in a keyness comparison.

target, reference
  The two scopes of a keyness comparison. Also called: focus corpus (Sketch
  Engine).

contrast
  The comparison of the collocations or frequencies of two scopes or
  variants.

parallel concordance
  A concordance that shows the aligned passages of the variants of a paired
  corpus.

word sketch
  Collocation tables grouped by dependency relation.

similar words
  Words with similar distributional vectors that occur in the corpus.

semantic search
  A search for passages by the similarity of their vectors to a search text.

lexical diversity
  Measures of the variety of the vocabulary, such as the type-token ratio.

method card
  The information about measure, formula, window, case folding, denominator,
  and index state that belongs to a result. In the API it is the `method`
  block.

provenance
  The information about where a result comes from: corpus, index state,
  scope, query, and parameters.

index fingerprint
  A value that identifies the state of an index, recorded in exports. See
  [Export formats](export-formats.md#fingerprints-and-checksums).

analysis job
  An analysis that runs in the background and reports its state.

saved analysis
  Analysis settings saved under a name.
```

## Line annotation and export

```{glossary}
line annotation
  A category and a note on one concordance line. Not the same as linguistic
  annotation.

coding scheme
  The categories that line annotations can use.

inter-annotator agreement
  How often several coders chose the same category, measured with percent
  agreement and kappa.

export
  Writing a concordance or an evidence package to a file.

loaded lines
  The concordance lines that the web interface has loaded.

full concordance export
  An export of all hits, written by the server, up to the export cap.

partial export
  An export that stopped at the export cap and is marked as such.

evidence package
  A JSON document with the query, the scope, the index fingerprints, the
  counts, a checksum of the lines, and the lines. See
  [Export formats](export-formats.md#evidence-packages).

project file
  The file with subcorpora, line annotations, and the coding scheme. See
  [Project files](project-files.md).
```

## Copilot

```{glossary}
copilot
  The optional assistant that answers research questions by calling the
  analysis tools of CandyConc and interpreting their results with a language
  model.

model endpoint
  The address of an OpenAI-compatible server that runs the language model.

model connection
  The setting for endpoint, model, and key of the copilot, in
  **Settings > Model connection**.

tool
  An analysis operation that the copilot can call.

tool call, tool result
  One call of a tool and its computed result.

evidence item
  A tool result with an identifier that the answer of the copilot can cite.

evidence chip
  A numbered button in the answer text that opens the evidence item it
  cites.

computed evidence
  The label of a tool result, as opposed to the text of the model.

AI interpretation
  The label of the text that the language model wrote.

grounding check
  A check without a model call that compares the citations, numbers, and
  quotations of an answer with the tool results of the turn.

research trace
  The record of the tool calls and results of one turn.

turn
  One question with its answer.
```

## Operation

```{glossary}
single-user mode
  The default security mode: bound to the local computer, no sign-in. The
  setting value is `local_dev_unsafe`. See [Deployment](deployment.md).

multi-user mode
  The security mode with sign-in, roles, and a user file. The setting value
  is `release`.

role
  The rights of a user in multi-user mode: `user`, `annotator`, `manager`, or
  `admin`.

user file
  The JSON file with the users, their password hashes, and roles.

data directory
  The directory in which CandyConc keeps corpora, the project file,
  preferences, and logs, by default `~/.candyconc`.

application bundle
  The download that contains CandyConc with its own Python, started with
  `./candyconc`.
```
