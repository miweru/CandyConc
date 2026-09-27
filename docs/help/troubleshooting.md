# Troubleshooting

Each entry describes a problem that was observed with this version: what you
see, why it happens, and what fixes it. For questions that are not about an
error, see the [FAQ](faq.md).

## Installation and start

### macOS refuses to run the bundle after a browser download

**Symptom.** The application bundle was downloaded with a web browser, and
macOS refuses to run `./candyconc` or the Python inside the bundle.

**Cause.** A browser marks downloaded files with the quarantine attribute.
The bundle is not signed or notarized by Apple, so macOS refuses to run its
programs while the attribute is set.

**Fix.** Remove the attribute from the unpacked folder once:

```bash
xattr -dr com.apple.quarantine BUNDLE_FOLDER
```

Replace `BUNDLE_FOLDER` with the name of the unpacked folder, for example
`CandyConc-0.1.0-macos-arm64`. Alternatively, download the archive in the
Terminal with `curl -LO ADDRESS`, which sets no quarantine attribute. Replace
`ADDRESS` with the address of the archive on the release page.

### The port is already in use

**Symptom.** CandyConc stops at start with
`Port 8010 on 127.0.0.1 is already in use. Choose another one with --port.`

**Cause.** You started CandyConc with `--port`, and another program, often a
CandyConc that is still running, uses that port. Without `--port`, CandyConc
takes the next free port from 8010 to 8029 and prints the address it uses.

**Fix.** Stop the other CandyConc (Control+C in its terminal), or start with
another port, for example `candy --port 8020`. Open the address that the
start message prints.

### The page at 127.0.0.1:8010 does not open

**Symptom.** The browser cannot connect to `http://127.0.0.1:8010`.

**Cause.** CandyConc is not running, or it runs on another port because 8010
was taken.

**Fix.** Look at the terminal in which you started CandyConc. The line
`Web interface: http://127.0.0.1:PORT/` names the address. If the terminal
shows an error instead, find it on this page.

### The server does not start with a pinned corpus

**Symptom.** CandyConc stops at start with
`No valid index path found:` followed by a directory.

**Cause.** `CANDYCONC_INDEX_PATH` (or `index_dir` in the configuration file)
points to a directory that is not a complete corpus index.

**Fix.** Correct the path, or remove the setting. Without it, CandyConc opens
the active corpus of the catalog, or starts with an empty catalog.

## Import

### The annotation pipeline is not installed

**Symptom.** `candy import` stops with
`The spaCy pipeline 'en_core_web_sm' is not installed. Install it with: candy pipeline en_core_web_sm ...`

**Cause.** The import annotates with the spaCy pipeline of `--spacy-model`,
and CandyConc never downloads a pipeline on its own.

**Fix.** Install the pipeline, then import again:

```bash
candy pipeline en_core_web_sm
```

With the application bundle, run `./candyconc pipeline en_core_web_sm`. To
import without linguistic annotation and without a download, use
`--spacy-model blank:en` (or the code of your language).

### The import is refused for lack of disk space

**Symptom.** The import stops before it starts. On the command line the
message begins with `The disk space check blocks the import:`, names the
free space, the estimated need, and the reserve, and ends with
`Override: CANDYCONC_BUILD_ALLOW_LOW_DISK=1`.

**Cause.** Before an import, CandyConc estimates the size of the index as 2.5
times the input size and requires that 5 GB stay free on the volume of the
output directory. On a nearly full disk, even a small import is refused.

**Fix.** Free disk space, or import into a directory on another volume. If
you know that the index fits, set `CANDYCONC_BUILD_ALLOW_LOW_DISK=1` for the
import, which turns the refusal into a warning, or lower the reserve with
`CANDYCONC_BUILD_DISK_RESERVE_GB`. See
[Configuration reference](../reference/configuration.md#import).

### Some rows are missing after the import

**Symptom.** The corpus has fewer documents than the input has rows.

**Cause.** Rows without text, invalid JSON lines, and incomplete groups of a
paired corpus are rejected. The import continues without them.

**Fix.** Open `reject_report.json` in the index directory. It lists the
number of rejected rows for each reason and up to 50 examples. The reasons are
explained in [Input formats](../reference/input-formats.md#rejected-rows).

### An index lacks morphological features

**Symptom.** In a corpus imported with an earlier version, queries on
morphological features, for example `cql:[morph=".*Number=Sing.*"]`, find
fewer tokens than the text contains, and many tokens have no value in
`morph` at all.

**Cause.** Imports before the correction (builder revision 0 in the index
manifest) stored an empty value for every token whose feature set had a
spaCy hash of 2^63 or more, about half of all feature sets.

**Fix.** Check the index:

```bash
python -m candyconc.tools.check_index INDEX_DIRECTORY
```

Replace `INDEX_DIRECTORY` with the directory of the corpus, for example
`~/.candyconc/corpora/my_corpus`. In the application bundle, run
`python/bin/python3 -m candyconc.tools.check_index INDEX_DIRECTORY` in the
bundle folder. Exit status 1 means the index is affected: import the corpus
again with the current version. Exit status 0 means no defect was found, 2
that the directory is not a readable index. The check only reads the index.

## Search

### A query is rejected

**Symptom.** A search with `cql:` shows an error instead of results.

**Cause.** The query has a syntax error, or it uses a value that does not
occur in the corpus. Two observed examples on the State of the Union sample
corpus: `cql:[lemma="free"` lacks the closing bracket, and
`cql:[pos="NN"]` uses a Penn Treebank tag, while the corpus stores universal
part-of-speech tags.

**Fix.** Read the message. For a syntax error it names what was expected and
the position, here
`CQL parse error: expected RBRACK, got EOF at 13:13`. For an unknown value it
lists the values that occur in the corpus, here
`Unknown pos tag in CQL: 'NN' is not a valid value of the attribute 'pos' in this corpus. Valid values: ADJ, ADP, ADV, ...`. `cql:[pos="NOUN"]` is the query that was meant. A phrase without
`cql:`, such as `heavy rain`, is also rejected, and the message shows the
query language form with one pair of brackets per word. See
[Query language](../reference/query-language.md).

## Copilot

### The copilot answers that no language model is configured

**Symptom.** A question to the copilot returns
`No language model is configured for the copilot.`, over the API with status
424 and the code `copilot_not_configured`.

**Cause.** No model endpoint is set. CandyConc works without one, only the
copilot needs it.

**Fix.** Set an endpoint in **Settings > Model connection**, or set
`COPILOT_ENDPOINT` and `COPILOT_MODEL` in the environment or the
configuration file and restart. See
[Connect a language model](../guides/copilot/connect-a-model.md).

## HTTP API

### An export over the API returns 401

**Symptom.** `POST /api/v1/export/concordance` returns
`401` with `User token required.`, although the server runs in single-user
mode.

**Cause.** Exports, the evidence package, and analysis jobs need a token also
in single-user mode.

**Fix.** Get a token from `GET /api/v1/auth/dev-token` and send it as
`Authorization: Bearer TOKEN`. See
[HTTP API reference](../reference/http-api.md#single-user-mode).

### Requests return 429

**Symptom.** Requests return `429` with `Rate limit exceeded`.

**Cause.** More than 300 requests in one minute from one address without a
token, or more than 600 in one minute with a token.

**Fix.** Wait a minute, send fewer requests, or send a token to get the
higher limit. An administrator can raise the limits. See
[HTTP API reference](../reference/http-api.md#rate-limit).
