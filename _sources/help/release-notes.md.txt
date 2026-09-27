# Release notes

## CandyConc 0.1.1

Released 27 September 2026.

**[Online documentation and help](https://miweru.github.io/CandyConc/)**

### Fixes and improvements

- Copilot count breakdowns by generation procedure now include a combined
  generator row when several generators and other procedures are present.
  Its rate uses the combined hit count and token denominator. Editing
  procedures remain separate, and the extra row leaves dispersion unchanged.
- Local word clustering also works before a corpus has been selected, using
  the configured language pipeline. With an active corpus, it uses that
  corpus's word vectors.
- The README links directly to the online manual. Bug reports, improvement
  suggestions, and pull requests have short templates. The repository now
  includes a code of conduct and a private route for security reports.
- The web interface CI job installs the Python dependencies needed by its
  backend contract tests.

### Downloads

The application bundle is for macOS 13 or later on Apple silicon. Python
wheels are provided for CPython 3.11, 3.12, 3.13, and 3.14 on macOS arm64.
The release also includes a source distribution, the offline HTML manual,
these release notes, and `SHA256SUMS`.

See [Install CandyConc](../get-started/install.md) and
[Supported platforms](../reference/supported-platforms.md).
The bundle is unsigned. The [first-start instructions](troubleshooting.md#macos-refuses-to-run-the-bundle-after-a-browser-download)
explain the macOS download check.

Version 0.1.0 and its downloads remain available unchanged.

## CandyConc 0.1.0

CandyConc 0.1.0 is the first release. It is an installable application for
corpus analysis on your own computer: import your texts, search them with
plain searches or a CQP-style query language, read hits in their documents,
restrict the analysis to documents with given metadata, compute frequency
lists, collocations, dispersion, keyness, trends, n-grams, and word sketches,
and export concordances and evidence packages. A copilot that calls the same
analyses is optional and works with a language model endpoint that you
provide.

### Downloads

The local candidate targets macOS 13 or later on Apple silicon. Intel macOS and Linux
are configured in the release workflow but have no built or verified
artifacts for this candidate. See the full
[platform status](../reference/supported-platforms.md#support-matrix).

| File | For |
| --- | --- |
| `CandyConc-0.1.0-macos-arm64.tar.gz` | application bundle for macOS on Apple silicon |
| `candyconc-0.1.0-cp3XY-cp3XY-macosx_11_0_arm64.whl` | four Python wheels for CPython 3.11, 3.12, 3.13, and 3.14 on macOS arm64 |
| `candyconc-0.1.0.tar.gz` | source distribution with the built web interface |
| `candyconc-0.1.0-docs-html.zip` | the offline HTML manual with diagrams, formulas, and search. See [Read the documentation offline](../reference/supported-platforms.md#read-the-documentation-offline). The application contains the same pages under **Help > Documentation**. |
| `SHA256SUMS` | checksums of all files |

The application bundle contains its own Python and needs no other software.
See [Install CandyConc](../get-started/install.md),
[Install the Python package](../get-started/install-python-package.md), and
[Supported platforms and requirements](../reference/supported-platforms.md).

### Changes since the first snapshot of the repository

**Installation and start**

- The wheel is a complete application: it contains the web interface, the
  import tools, and the compiled extensions, and it runs outside a clone of
  the repository. The source distribution builds a wheel without Node.js.
- An application bundle with its own Python for macOS on Apple silicon,
  started with `./candyconc`.
- `candy` starts without a corpus and without a language model. With an
  empty catalog the web interface offers the import. At start, CandyConc
  opens the active corpus or the most recent one and prints the address, the
  corpus, the data directory, and the state of the copilot. Without `--port`
  it takes the next free port after 8010.
- New commands: `candy pipeline NAME` installs a spaCy pipeline on request,
  `candy paths` shows where data and configuration live, `candy --version`
  shows the version. `candy import` checks before the import that the
  pipeline is installed and names the command to install it.
- The copilot is optional. Without a model endpoint the copilot panel says
  so and opens **Settings > Model connection** with one click, and a question
  over the API returns status 424.
- All user data lives in the data directory `~/.candyconc`
  (`CANDYCONC_HOME`), including the project file, which earlier versions
  kept in the working directory. An existing `proj.ccproj` in the working
  directory keeps being used.
- New configuration file `config.toml` in the platform configuration
  directory, with the same names as the environment variables. See
  [Configuration reference](../reference/configuration.md).
- Fewer dependencies: the core no longer installs PyTorch, Transformers,
  sentence-transformers, or Annoy. Optional extras `semantic`, `hf`,
  `metrics`, and `cluster` add the functions that need more.
- The release wheels are built without OpenMP and need no system OpenMP
  library.
- The Docker and systemd templates start the packaged application in
  multi-user mode.

**Import and languages**

- `candy import --language CODE` chooses the standard spaCy pipeline of the
  language (for example `en_core_web_md` for `en`), or `blank:CODE` where
  spaCy has no trained pipeline. The index records the language, the
  pipeline, its version, and the width of its word vectors, and the corpus
  manager and the corpus selector show the language.
- Dependency relations are added by default when the pipeline has a parser.
  `--no-deps` leaves them out.
- An ordinary Parquet file imports like a CSV file.
- Similar words and `sim()` use the word vectors of the pipeline that
  annotated the corpus, never those of another language.
- Morphological features are stored for every token. Earlier imports lost the
  features of about half of all feature sets. `python -m candyconc.tools.check_index`
  finds affected indexes, see
  [Troubleshooting](troubleshooting.md#an-index-lacks-morphological-features).
- The preflight of the import form detects the field separator of a CSV file
  as the import does.
- The folder `examples` contains two sample corpora, 65 State of the Union
  addresses and 30 German texts of the Deutsches Textarchiv, ready to import.
  It is part of the application bundle and of the source distribution.

**Search, statistics, and evidence**

- A query language sequence whose first element is a part of speech places
  the hit on the matching token.
- Multi-word hits appear completely in the hit column of the concordance,
  also the phrases of plain search. Concordance exports add the columns
  `match`, `match_start`, and `match_end` with the whole hit.
- Plain search reads the words *where* and *within* as words.
- A word sketch with `min_freq` 0 or 1 lists the partners with a single pair.
- VRT imports mark their documents as unpaired (`text_type` `standalone`),
  like the other unpaired imports. A document keeps the ID from the file
  (`id` or `xml:id`) as its name, with `variant` `document` and `model`
  `none`, and without the pair fields of the research layout.
- An exact hit count is no longer shown as a lower bound.
- The concordance lines behind a collocation row use the window and the
  units of the collocation table, also for lemma collocations.
- Frequency lists and n-grams lead to the concordance of a row.
- The row label of a case-folded frequency line is the most frequent
  spelling.
- The contrast of collocations folds the case of the node, and method blocks
  name what the rows contain.
- The frequency contrast divides by the word tokens of each side, like
  keyness, and both give the same rates per million for the same document
  sets. Its method block gives the number of all tokens next to it.
- `/api/v1/document/{doc_id}` also accepts the document ID of the import.
- Errors of a query are reported in the first answer of `/api/v1/query/count`.
- Evidence chips of the copilot open the evidence they cite.
- `!=` accepts the flag `%c` and then excludes every spelling of the value.
- Saving a subcorpus from the hits of a search in a filtered scope keeps the
  metadata filter, and the Reader lists the documents of the active scope.
- The document panel and the Reader show the metadata fields of the corpus.
  Fields with one value in the whole corpus are collected separately.
- The explanation of logDice follows Rychlý (2008) and states no threshold
  for notable collocations.

**Interface**

- The web interface is available in English. The interface language can be
  switched in **Settings**, and dates and numbers follow the chosen language.
- Messages of the server, method explanations, the glosses of word sketch
  relations, and the sheet names of XLSX exports follow the interface
  language, and over the API the header `Accept-Language`.
- Every preference in **Settings** has an effect. The preferences for a
  default context width, line numbers, and automatic saving of bookmarks, and
  the font Inter, are removed.
- The command line writes English, also the progress lines of `candy import`.

**HTTP API**

- `GET /api/v1/corpora` gives the language and the pipeline of each corpus,
  and `display_name`, the folder name, also for a corpus opened with
  `CANDYCONC_INDEX_PATH`, whose `name` is `default`.
- Error codes have one status each. A document set of another corpus
  (`docset.corpus_mismatch` and related codes) returns 422.
- `POST /api/v1/settings/embeddings` accepts only `spacy` and `none`, and
  `GET /api/v1/settings/embeddings` reports the backend in effect, what its
  spaCy pipeline embeds, and the source of the word vectors of each corpus.
- `POST /api/v1/system/rebuild-index` and `POST /api/v1/semantic/cluster_words`
  embed with the word vectors of the corpus pipeline, like similar words and
  `sim()`, and no longer with `de_core_news_md` for every corpus.
- `sim(...)` and `/api/v1/semantic/similar_words` on a corpus without word
  vectors return 422 `word_vectors.unavailable` on `/api/v1/query`,
  `/api/v1/query/count`, and the thesaurus route. The `error` event of
  `/api/v1/query/stream` carries the same `code`. When the pipeline of the
  corpus is not installed on the server, the same requests return 503
  `word_vectors.service_error`.
- `/api/v1/system/info` names the corpus catalog `corpus_catalog` under
  `paths` (formerly `corpus_catalogue`).
- The OpenAPI description, its examples, and its tags are English.

**Documentation**

- New documentation with installation, tutorials, guides, concepts, a
  methods reference with worked examples, and a technical reference.

### Known limitations

- The application bundle for macOS is not signed or notarized. A browser
  download needs one command before the first start, see
  [Troubleshooting](troubleshooting.md#macos-refuses-to-run-the-bundle-after-a-browser-download).
- Intel macOS and Linux still need their configured workflow builds and
  installation checks. The workflow has not run on GitHub.
- The Docker image and the systemd unit have not been built or run for this
  release.
- The instructions that the copilot sends to the model are German.
- Windows is not supported.

### Checksums

Check a download against `SHA256SUMS` on the release page, for example with
`shasum -a 256 -c SHA256SUMS --ignore-missing` on macOS or
`sha256sum -c SHA256SUMS --ignore-missing` on Linux.
