# Frequently asked questions

Short answers with a link to the page that covers each topic in full.

<!-- Maintenance note: the questions on this page are A1 to F6 of section 8 of
doku_konzept.md, formulated before the user walkthroughs. Questions observed in
the walkthroughs are added with their origin recorded in the evidence files,
not on this page. -->

## About CandyConc

### What can I do with CandyConc?

Search your own corpora with plain searches or a CQP-style query language,
read every hit in its document, restrict the search to documents with given
metadata, and compute frequency lists, collocations, dispersion, keyness,
trends, n-grams, and word sketches. Each result states its scope and method,
and leads back to the concordance lines it counts. You can export
concordances with the fingerprint of the index they come from, annotate
concordance lines with a coding scheme, compare paired versions of texts, and
optionally ask a copilot that runs the same analyses and cites their results.
See [How CandyConc works](../concepts/how-candyconc-works.md).

### Who is CandyConc for?

For researchers who study language in their own text collections, for
example in corpus linguistics, digital humanities, or the social sciences. It
also serves annotation projects with several coders, studies that compare
versions of the same texts, and groups that share one server. See
[How CandyConc works](../concepts/how-candyconc-works.md).

### Do I need the AI copilot to use CandyConc?

No. Import, search, concordance, document context, all statistics, and export
work without a language model. Without a model, only the copilot answers that
no model is configured. See [Data and privacy](../concepts/data-and-privacy.md).

### Is CandyConc free to use, and under which license?

Yes. CandyConc is open source under the MIT license. See
[Licenses](license.md).

### How do I cite CandyConc?

See [Cite CandyConc](cite.md).

## Installation and systems

### Should I install the application or the Python wheel?

Install the application bundle if you want to use CandyConc without setting
up Python. It contains its own Python and starts with `./candyconc`. Install
the wheel if you work in your own Python environment or want to use CandyConc
from scripts. Both contain the same program. See
[Install CandyConc](../get-started/install.md) and
[Install the Python package](../get-started/install-python-package.md).

### Which operating systems and processors are supported?

The application bundle needs macOS 13 or later on Apple silicon.
Intel macOS and Linux are configured build targets and still need artifact
builds and installation checks. Windows is not supported. See
[Supported platforms and requirements](../reference/supported-platforms.md).

### Do I need Python, Node.js, or a compiler?

For the application bundle, none of them. For the wheel, Python 3.11 to 3.14,
but no Node.js and no compiler. Only a development setup from the source code
needs Node.js and a compiler, see
[Set up a development environment](../contribute/development-setup.md).

### Does CandyConc need a GPU?

Search, statistics, and corpus annotation run on the CPU. Optional local
semantic indexing and query embeddings use the Apple GPU when available.
The copilot uses the language model behind the endpoint you configure,
which runs wherever that endpoint runs. See
[Hardware requirements](../reference/supported-platforms.md#hardware).

### What does CandyConc download on first start?

Nothing. CandyConc downloads only when you run a command for it: a spaCy
pipeline with `candy pipeline NAME`, a Hugging Face dataset with
`--input-format hf`, or the runtime and model of a local semantic index. See
[Supported platforms and requirements](../reference/supported-platforms.md#downloads-at-first-use).

### Can I install CandyConc without an internet connection?

The application bundle runs without a network connection once you have
downloaded and unpacked it. An import with `blank:<language>` needs no
download. An annotation pipeline such as `en_core_web_sm` is a separate
download, which you can do once while you are online. The wheel installs its
dependencies from the Python Package Index, so pip needs a connection, or a
directory with all dependency wheels. See
[Install CandyConc](../get-started/install.md) and
[Install the Python package](../get-started/install-python-package.md).

### How do I update to a new version without losing my corpora?

Replace the program and keep the data directory. See
[Upgrade CandyConc](upgrade.md).

### How do I uninstall CandyConc completely?

Remove the program, then delete the data directory if you want your corpora
gone too. See [Uninstall CandyConc](uninstall.md).

### The page at 127.0.0.1:8010 does not open. What now?

See [Troubleshooting](troubleshooting.md#the-page-at-1270018010-does-not-open).

### Must I keep the Terminal window open?

Yes. Keep the Terminal window running CandyConc open while you use the
application. To stop the server, press **Control+C** in that window. Your
imported corpora and saved work remain in the data directory. See
[Install CandyConc](../get-started/install.md#start-candyconc).

## Corpora, formats, languages

### How do I import my own texts?

Save them as CSV, JSON Lines, plain text files, Parquet, or VRT, and import
them in the corpus manager of the web interface or with `candy import`. See
[Import a corpus](../guides/bring-in-texts/import-a-corpus.md).

### Which file formats can I import?

CSV and TSV, JSON Lines, plain text files or folders, Parquet, VRT,
Hugging Face datasets, and paired versions of texts in CSV, JSON Lines, or
Parquet. See [Input formats](../reference/input-formats.md).

### Can I upload files in the browser, or do I need a file path?

The import in the web interface reads a file or folder by its path on the
computer where the server runs. It does not upload files from the browser. In
single-user mode that is your own computer. See
[Import a corpus](../guides/bring-in-texts/import-a-corpus.md).

### Can I analyze English texts? Other languages?

Yes. CandyConc has been tested with English and German corpora. For other
languages, use the spaCy pipeline of that language, or `blank:` with the
language code for tokenization without annotation. These have not been
tested. See [Languages and annotation](../concepts/languages-and-annotation.md).

### What is the difference between tokenization only and full annotation?

Tokenization splits the text into tokens and sentences. Annotation adds
lemmas, parts of speech, morphological features, and optionally named
entities and dependency relations. Lemma and part-of-speech queries and word
sketches need annotation. See
[Languages and annotation](../concepts/languages-and-annotation.md).

### Which annotation models are used, and can I use my own?

spaCy pipelines. `--language en` chooses the standard pipeline of the
language, here `en_core_web_md`, and `--spacy-model` names any other one.
Any installed spaCy pipeline works, also one of your own, given by its
package name or its directory. See
[Languages and annotation pipelines](../reference/languages.md).

### Can I import a corpus that is already tagged, for example from CWB?

Yes, as VRT. `cwb-decode -C` and `python -m candyconc.ingest.cwb_decode_to_vrt`
turn a CWB corpus into VRT. The import in the web interface can adopt the
lemma, part-of-speech, and morphology columns of the file as they are. See
[Input formats](../reference/input-formats.md#vrt).

### Why is the Word sketch view unavailable for my corpus?

Word sketches need dependency relations. An import adds them when its
pipeline has a dependency parser, as the trained spaCy pipelines do. A corpus
imported with `blank:<language>` or with `--no-deps` has none. Import the
corpus again with a trained pipeline and without `--no-deps`. See
[Word sketches](../guides/count-and-measure/word-sketches.md).

### How large can a corpus be?

An index can hold up to 2,147,483,647 tokens. As a measured example, the State
of the Union sample corpus with 403,284 tokens gives an index of 19 MB. See
[Index format](../reference/index-format.md#limits).

### Why do some of my rows appear in a rejected rows report?

Rows without text, lines that are not valid JSON, and incomplete groups of
paired texts are not imported. The report in `reject_report.json` names the
reason for each. See [Input formats](../reference/input-formats.md#rejected-rows).

## Searching and counting

### Is the query language the same as CQP?

It uses the token conditions, sequences, repetition, and flags of CQP.
Sentence and document scope and metadata conditions have forms of their own,
`within(...)` and `where(...)`. Constructs that it does not support are
rejected with a message. See
[Query language](../reference/query-language.md).

### Why does my part-of-speech query find nothing?

Corpora annotated with spaCy store universal part-of-speech tags such as
`NOUN` and `VERB`, not STTS or Penn Treebank tags such as `NN`. A query with a
tag that does not occur is rejected, and the message lists the tags of the
corpus. See [Languages and annotation pipelines](../reference/languages.md#tag-sets).

### Is search case-sensitive?

Plain search ignores case. The query language respects case unless you add
`%c` to a condition. See [Query language](../reference/query-language.md).

### Does `where(...)` change the active subcorpus?

`where(...)` restricts the query that contains it. To change the document
selection shared by the Reader and analysis views, use the metadata filters
or activate a saved subcorpus. The scope label shows that selection. See
[Scope and subcorpora](../concepts/scope.md#metadata-filters).

### What exactly does a hit count count?

The positions in the scope where the query matches. See
[How CandyConc counts](../methods/index.md).

### Why does a frequency differ from the number of concordance lines I see?

The concordance view loads lines page by page, while counts are computed over
the whole scope, and some counts fold case or count only word tokens. See
[From numbers to lines](../concepts/from-numbers-to-lines.md).

### How do I get from a number in a table to the lines behind it?

See [From numbers to lines](../concepts/from-numbers-to-lines.md).

### Which association measure should I use?

That depends on your question. The methods reference explains what each
measure expresses. See [Association measures](../methods/association-measures.md).

### Are the keyness results statistically significant?

The keyness table reports test statistics with p-values, q-values that
control the false discovery rate over all compared words (Benjamini and
Hochberg), and effect sizes. See
[Keyness](../methods/keyness.md) for how to read them.

### Can I reproduce a result later or on another computer?

Yes, with the same corpus and settings. Every export records the query, the
scope, and the fingerprint of the index, and an evidence package adds a
checksum of the lines. See
[Reproduce a result](../guides/keep-and-share/reproduce-a-result.md).

## Copilot and privacy

### Does my corpus leave my computer?

Import, search, analysis, annotation, and export run on your computer. The
copilot sends your question and its analysis results to the model endpoint
you configure. Model-generated labels for semantic clusters send up to three
concordance snippets per cluster to that endpoint. These requests stay on
your computer when the endpoint runs there. Semantic search with Gemma
embeddings sends the search term to its configured embedding endpoint. See
[Data and privacy](../concepts/data-and-privacy.md) for the data sent by each
optional function and the downloads used to set it up.

### Which language models work with the copilot?

Models behind an OpenAI-compatible endpoint, with the Responses API
(`/v1/responses`) or Chat Completions (`/v1/chat/completions`). The copilot
calls tools, so the model must support tool calls. See
[Connect a language model](../guides/copilot/connect-a-model.md).

### Does CandyConc download or start a language model?

No. You run the model yourself, for example in a local model server, or use a
provider. For endpoints on your computer, CandyConc checks the list of loaded
models before a question and reports a model that is not loaded. It never
loads one. See
[Connect a language model](../guides/copilot/connect-a-model.md).

### Can I use a cloud model, and what is sent to it?

Yes, with the endpoint and key of the provider. Sent are your question, the
instructions of the copilot, the context of the interface, and the tool
results with concordance lines and document text. E-mail addresses, IBANs,
and telephone numbers in the question and the interface context are replaced
by placeholders, the tool results are sent unchanged. See
[Data and privacy](../concepts/data-and-privacy.md).

### How can I check whether the copilot's answer is right?

Each claim of an answer can cite an evidence item, the computed result of a
tool call. Open the evidence chips in the answer and the research trace of the
turn, and compare them with your own search. See
[Ask and check](../guides/copilot/ask-and-check.md).

### Why does the copilot take so long?

A question can need several rounds of tool calls and model calls, and the
speed of each model call depends on the model and the hardware of the
endpoint. CandyConc sets no time limit for a question by default. See
[How the copilot works](../concepts/copilot.md).

### Can I stop a copilot answer?

Yes. A stop ends the turn without starting another model call, tool call, or
retry. See [Ask and check](../guides/copilot/ask-and-check.md).

### Does the copilot answer in English?

Yes. The copilot uses the detected language of a German or English question
for its answer, headings, and evidence labels. If a short query does not
identify a language, it uses the interface language, then the request's
`Accept-Language` header, then German. Corpus text and search terms keep
their original wording. See
[Languages and annotation](../concepts/languages-and-annotation.md).

## Data and results

### Where does CandyConc store my corpora, subcorpora, and annotations?

In the data directory, by default `~/.candyconc`. See
[Where your data lives](../concepts/where-data-lives.md).

### Who owns the data I import and the results I export?

CandyConc does not change the ownership of your texts, and it keeps them on
your computer. The MIT license covers the software, not your corpora. Each
corpus keeps the license and terms of its source, which also apply to what
you export from it. See [Licenses](license.md).

### Which export formats are there, and do exports contain all hits?

CSV, TSV, XLSX, JSON, and JSON Lines, and evidence packages. A server export
contains all hits up to 1,000,000 lines and says so when it stops at that cap.
See [Export formats](../reference/export-formats.md).

### What is an evidence package?

A JSON file with the query, the scope, the fingerprints of the index, the
counts, a checksum of the lines, and the lines. See
[Export formats](../reference/export-formats.md#evidence-packages).

### Can several people work on one installation?

Yes, in multi-user mode with a user file, sign-in, and roles. See
[Deployment](../reference/deployment.md).

### How do I back up my work?

Copy the data directory while CandyConc is not running. See
[Back up your data](../guides/keep-and-share/back-up-your-data.md).
