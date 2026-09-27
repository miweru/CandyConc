# How CandyConc works

CandyConc is one server process that you run on your own computer and a web
interface that you open in your browser. The server holds your corpora as
indexes on disk, answers searches with its own query engine, and computes
statistics on the same index. An optional copilot sends questions to a
language model and lets the model call the same analysis operations that the
interface uses. This page describes the parts, how they depend on each other,
and what runs where.

## Components and data flow

```{mermaid}
flowchart TB
  subgraph machine["Your computer"]
    files["Your text files"]
    importer["Import<br/>tokenize and annotate"]
    index[("Corpus indexes")]
    browser["Web interface<br/>in your browser"]
    subgraph server["CandyConc server"]
      api["HTTP API"]
      tools["Tool API"]
      copilot["Copilot<br/>optional"]
      ops["Analysis operations"]
      engine["Query engine"]
    end
    project[("Project file<br/>and settings")]
  end
  model["Model endpoint<br/>on this computer or remote"]

  files --> importer --> index
  browser -- "HTTP" --> api
  api --> ops
  tools --> ops
  api --> copilot
  copilot -- "tool calls" --> ops
  ops --> engine --> index
  ops --> index
  api --> project
  copilot -. "prompts with tool results" .-> model
```

The diagram shows these relationships:

- Your text files go through the import, which tokenizes and annotates them
  and writes one index directory per corpus.
- The web interface talks only to the HTTP API of the CandyConc server, over
  HTTP, server-sent event streams, and WebSocket updates for analysis jobs.
- The HTTP API passes every search and every analysis to the analysis
  operations. They read the corpus index directly or use the query engine
  to resolve search patterns.
- The HTTP API also reads and writes the project file, the settings, and the
  corpus catalog.
- The optional copilot orchestrator runs inside the same server process. It
  calls the same analysis operations as the interface and sends the question
  and selected evidence to the configured model endpoint. Semantic cluster
  labels can also use this endpoint to summarize example passages.
- The tool API offers the same operations to external programs without a
  model.

## The parts and what each one is responsible for

**Import.** The import reads CSV, JSONL, plain text, VRT, and other formats,
runs a spaCy pipeline on your CPU, and writes the index. The pipeline decides
how the text is split into tokens and sentences and which annotation each
token receives. The import runs from the command line (`candy import`) or from
the **Corpus manager** in the interface. See
[Languages and annotation](languages-and-annotation.md) for what a pipeline
adds and [The corpus index](corpus-index.md) for what the import writes.

**Corpus index.** Each corpus is a directory of binary files: one numbered
stream of tokens per attribute (word form, lemma, part of speech, and further
layers if the import added them), lexicons, postings lists, sentence and
document boundaries, document metadata, and a manifest. The manifest records
how the index was built and which capabilities it has. Every view of
CandyConc reads the same files.

**Query engine.** The query engine turns a query into positions in the
index. It resolves word forms, lemmas, and tags to numeric IDs in the
lexicons, intersects the postings lists, and checks candidate positions
against the full pattern. Its core is compiled (Cython), and the server does
not start without it. See [Queries and hits](queries-and-hits.md).

**Analysis operations.** Frequency lists, collocations, collocation networks,
dispersion, keyness, contrast, n-grams, trends, word sketches, lexical
diversity, and semantic search are operations in the server. Each operation
takes a query or a word, a scope (the whole corpus or a document set), and
parameters, and it returns rows together with a method card. The method card
names the measure and its formula, the counting unit, the window, the
denominators, and a fingerprint of the index. See
[From numbers to lines](from-numbers-to-lines.md).

**HTTP API.** The interface, the command line tools, and your own scripts use
the same HTTP API under `/api/v1`. Long analyses run as jobs with a status
and can be cancelled. In the single-user mode, the server also publishes an
OpenAPI description of the API.

**Web interface.** The interface is a single-page application. When a built
interface is present, the CandyConc server delivers it itself, so one process
serves both the interface and the API.

**Copilot.** The copilot is optional. Every other function works without a
model. When you ask a question, the orchestrator sends it to the model
endpoint you configured, together with a description of the corpus and a
list of tools. The model answers with tool calls. The orchestrator runs these
calls locally as ordinary analysis operations, records every result as an
evidence item with its own ID, and returns the results to the model. For an
analysis question, a separate model call writes the final answer from these
evidence items, and CandyConc resolves the references in it to the evidence
mechanically. Some short lookup questions are answered by CandyConc directly
from the tool results, without a model writing the text. See
[How the copilot works](copilot.md).

**Tool API.** `GET /mcp/tools` lists the analysis operations that the copilot
can call, with their parameters, and `POST /mcp/call` runs one of them. No
model is involved. Despite the path, this is a plain HTTP interface of
CandyConc, not a server for the Model Context Protocol.

## One set of operations for every way in

The interface, the HTTP API, the tool API, and the copilot do not have their
own statistics. They call the same analysis operations on the same index. A
collocation table that the copilot cites is computed by the code that
computes the collocation table in the interface, and it comes with the same
method card. This is what lets you check a copilot statement in the
interface: you run the operation yourself and compare.

## Capabilities decide what is offered

Not every corpus supports every analysis. A word sketch needs dependency
relations, the word thesaurus needs word vectors from the annotation
pipeline or a word similarity index, and a parallel concordance needs paired
documents. The server derives the capabilities of
each corpus from the files in its index and reports them at
`GET /api/v1/corpora/{name}/capabilities`. The interface disables views that
the active corpus cannot support and shows the reason. The copilot is not
offered the semantic tools when their files are missing, and the tools that
need dependency relations or paired documents refuse a call with the reason.
A second contract lists which constructs of
the query language are supported. It feeds the autocompletion and the
diagnostics of the search bar. See
[Query language](../reference/query-language.md).

## What runs where

By default, everything runs on your computer. The server listens on
`127.0.0.1`, port 8010, and in the single-user mode it refuses to listen on
a network address unless you allow that explicitly. Import, annotation,
search, and all statistics run locally. CandyConc downloads a spaCy
pipeline only when you run `candy pipeline NAME`, from the spaCy models on
GitHub. An import with a pipeline that is not installed stops and names this
command.

CandyConc connects to other machines only through these functions, and only
when you use them:

- **Copilot.** Questions, the corpus description, and tool results, which
  contain concordance lines and document text, go to the model endpoint. The
  endpoint is configured in **Settings > Model connection**. The LM Studio
  profile uses a local server on `127.0.0.1`. If you configure a remote
  endpoint, this text goes to that service.
- **Passage search with an embedding service.** In a corpus whose passage
  index was built with a remote embedding model, passage search sends the
  search text to the embedding endpoint in `CANDYCONC_GEMMA_EMB_ENDPOINT`.
  The preset endpoint is a local server on `127.0.0.1`.
- **Import from Hugging Face.** The import downloads the dataset you name.
- **Local semantic index on Apple silicon.** Building it downloads a runtime
  (about 1.25 GB) and the embedding model
  `mlx-community/embeddinggemma-300m-4bit` (about 250 MB).

[Data and privacy](data-and-privacy.md) lists every connection with its
purpose.

## Where state is kept

Corpus indexes, the corpus catalog, preferences, and logs are stored under
`~/.candyconc` in your home directory. Subcorpora, line annotations, and the
coding scheme are stored in a project file, by default
`~/.candyconc/proj.ccproj`. Document sets and running jobs
live in the memory of the server process and end with it. See
[Where your data lives](where-data-lives.md).

## Why CandyConc is built this way

- **One index, many views.** Searching, reading, counting, and the copilot
  work on the same positions. A number in any view can be taken back to
  positions in the same index, and the method card states which positions
  it counts.
- **Explicit provenance.** Because an analysis result names its measure, its
  denominators, its scope, and the index fingerprint, you can repeat it later
  or report it without reconstructing the settings.
- **Capabilities instead of assumptions.** The interface and the copilot
  offer an analysis only when the corpus has the files it needs, so a missing
  annotation layer shows up as an unavailable view with a reason and not as
  an empty table.
- **Local first.** Corpus storage, search, and statistics run on your
  computer. The copilot and model-generated semantic cluster labels send
  selected text to the configured model endpoint. The data flow is described
  in [Data and privacy](data-and-privacy.md).
