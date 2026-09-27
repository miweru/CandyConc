# Data and privacy

This page explains which functions can send data to other machines, what they send, and what CandyConc downloads. The places where CandyConc stores data on your computer are listed in [Where your data lives](where-data-lives.md).

## What stays on your computer

CandyConc is a local server. The web interface in your browser talks only to this server, and the server delivers the interface, the documentation under **Help**, and all fonts, scripts, and images from its own files. Neither the interface nor the documentation loads anything from other hosts, with one exception in the documentation described below.

The core functions send nothing to other machines:

- importing and annotating texts with an installed spaCy pipeline or with `blank:<language>`
- search, concordance, the document reader, and subcorpora
- frequency lists, collocations, dispersion, keyness, trends, n-grams, contrasts, and word sketches
- annotation of concordance lines and agreement measures
- export of concordances, tables, reports, and evidence packages

CandyConc does not check for updates and sends no usage statistics. The server counts queries and response times in its own memory for the operational metrics at `/api/v1/metrics`, which only administrators of the server can read. You can use the core functions on a computer without a network connection once the annotation pipelines you need are installed.

## Functions that connect to other machines

Each of these functions connects only when you use it.

| Function | Connects to | Sends | Receives |
| --- | --- | --- | --- |
| the copilot | the endpoint you configure, see [Connect a model](../guides/copilot/connect-a-model.md) | your question, the context of the interface, and the results of the analyses the copilot runs, see the next section | the answer of the model |
| labels for semantic clusters | the endpoint of the copilot, if one is configured | up to three concordance snippets per cluster | a short label |
| semantic search in a corpus built with Gemma embeddings | `CANDYCONC_GEMMA_EMB_ENDPOINT`, by default `http://127.0.0.1:1234/v1/embeddings` on your own computer | the search term | its embedding vector |
| `candy pipeline NAME` | GitHub (`explosion/spacy-models`) | the request for the pipeline | the pipeline package |
| `candy import --input-format hf` | the Hugging Face Hub | the name of the dataset | the dataset |
| building a local semantic index on Apple silicon (administrators) | the Python Package Index and the Hugging Face Hub | the requests for the packages and the model | a runtime of about 1.25 GB and the model `mlx-community/embeddinggemma-300m-4bit` of about 250 MB |
| downloading an embedding package from the catalog (administrators) | the address listed in the catalog | the request for the package | the package, checked against the SHA-256 checksum in the catalog |
| `CANDYCONC_MCP_URL`, if set | the address in this setting | every tool call of the copilot with its arguments | the tool results |

Without a configured copilot endpoint, the copilot and the cluster labels make no connection. Cluster labels then come from the most frequent words of the cluster.

## What the copilot sends

The copilot is off until you configure an endpoint. When you ask a question, CandyConc sends these parts to that endpoint, in several requests per question:

- your question
- the instructions for the model
- a description of the corpus: the names of the metadata fields, the number of values per field, and the date fields
- the context of the interface: the corpus name, the number of tokens and documents, the current query, the active filters with their fields and values, the number of hits, the identifiers of up to five selected lines, the last five actions in the interface, and the language of the interface. Concordance lines shown in the interface are not sent, only their number.
- the result of every analysis the copilot runs. A result of up to 12,000 characters and 20 rows is sent as it is. A larger result is sent as a compact view of up to 200 rows, whose character limit grows by 12,000 for every 20 rows, so a view of a concordance can reach about 120,000 characters. These results contain corpus text: concordance lines with their context, metadata values, and, when the copilot opens a document, up to 16,000 characters of its text.
- for the final answer, the evidence from these results

Before sending, CandyConc replaces e-mail addresses, IBANs, and telephone numbers in your question and in the context of the interface with placeholders (`CANDYCONC_ENABLE_COPILOT_PII_MASK`, on by default). The results of the analyses are sent as they are, because the model needs the corpus text to interpret it. If your corpus must not leave your computer, connect a model that runs on your own computer, for example with LM Studio at `http://127.0.0.1:1234`. The prepared connection to OpenRouter in **Settings > Model connection** sends all of the above to OpenRouter.

An API key entered in **Settings > Model connection** stays in the memory of the running server and is not written to disk.

## What the copilot keeps on your computer

- The full results of the analyses stay in the memory of the server for the current conversation.
- In single-user mode, CandyConc writes one line per model call to `traces.jsonl` in the data directory: the time, the user, the model, the names of the tools, and the length of each message in bytes. The text of the messages is not recorded. `CANDYCONC_ENABLE_LLM_TRACE=false` turns this record off.
- When a conversation becomes long, summaries of earlier steps are kept in a file in the temporary directory of your system.

## An exception in the documentation

The formulas on the methods pages are drawn by a copy of MathJax that ships with CandyConc. If you right-click a formula and switch on speech output or the explorer in the MathJax menu, MathJax downloads speech rules from `cdn.jsdelivr.net`. Reading the documentation, including the formulas, does not need this download. Screen readers read the formulas from the hidden MathML that MathJax adds to every formula without it.

## Corpus data and licenses

CandyConc does not change the license of your texts. An index, an export, or an evidence package contains text from your corpus. Share them only as far as the license of the corpus allows. See [Licenses](../help/license.md).
