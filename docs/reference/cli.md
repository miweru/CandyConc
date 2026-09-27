# Command line reference

CandyConc installs one command, `candy`. Without a subcommand it starts the
server and the web interface. The subcommands import corpora, download
annotation pipelines, show where CandyConc keeps its data, and migrate old
project files.

| Command | Purpose |
| --- | --- |
| `candy` | Start the server and the web interface. |
| `candy import` | Import a corpus: build a corpus index from CSV, JSONL, plain text, Parquet, VRT, a Hugging Face dataset, or paired files. |
| `candy pipeline NAME` | Download and install a spaCy annotation pipeline, for example `en_core_web_sm`. |
| `candy paths` | Show where CandyConc keeps its data and where it reads its configuration file. |
| `candy migrate-project` | Migrate a project file of an older version. |
| `candy --version` | Show the versions of CandyConc and Python. |

`python -m candyconc.entrypoints.cli` is the same command, with the same
arguments. `candy serve` is the same as `candy` without a subcommand.

The application bundle has its own launcher, `./candyconc`, with slightly
different commands. It is described in
[The launcher of the application bundle](#the-launcher-of-the-application-bundle).

## Starting the server

`candy` prints the version, the address of the web interface, the corpus it
opens, the data directory, and whether a language model for the copilot is
configured. The output is similar to the following:

```text
CandyConc 0.1.1 (Python 3.12.8)
  Web interface: http://127.0.0.1:8010/
  Corpus: none yet. Import one in the web interface (Corpora) or with: candy import --help
  Data: /home/USER/.candyconc
  Copilot: no language model configured (optional, see Settings > Model connection)
Press Ctrl+C to stop.
```

- **Port.** Without `--port`, CandyConc uses port 8010, or the next free port
  up to 8029 when 8010 is taken. With `--port`, it uses exactly that port and
  stops with `Port N on HOST is already in use` when the port is taken.
- **Corpus.** The server opens the corpus in `CANDYCONC_INDEX_PATH` if it is
  set, otherwise the active corpus of the corpus catalog, otherwise the most
  recent corpus in the data directory. Without any corpus it starts with an
  empty catalog, and the web interface offers the import.
- **Address.** The server binds to `127.0.0.1`, so only programs on the same
  computer reach it. A network address needs multi-user mode, see
  [Deployment](deployment.md).
- **Web interface.** When the built interface is missing (possible in a
  development checkout), the server prints `API only at ...` and serves only
  the API.

## `candy import` in brief

`candy import` builds a corpus index in the directory given with `--output`.
If that directory already holds an index, the new one replaces it when the
import has finished, and a running server opens it with the next request.
The format follows from the file extension unless you set `--input-format`.
Which options apply to which format:

| Options | Formats |
| --- | --- |
| `--text-column`, `--id-column`, `--meta-columns` | `csv`, `jsonl`, `parquet`, `hf`, and the paired formats |
| `--reject-policy`, `--reject-report` | `csv`, `jsonl`, `parquet`, `hf`, `plaintext`, and the paired formats |
| `--source` | all formats |
| `--delimiter` | `csv`, `prealigned-csv` |
| `--pair-key-column`, `--pair-role-column`, `--anchor-role`, `--pair-axis`, `--pair-order`, `--variant-column`, `--model-column` | `prealigned-csv`, `prealigned-jsonl`, `prealigned-parquet` |
| `--pattern`, `--split-paragraphs` | `plaintext` |
| `--segment-tag`, `--text-tag`, `--sentence-tag`, `--token-columns`, and the other options marked VRT | `vrt` |
| `--hf-config`, `--hf-split`, `--limit` | `hf` (needs the `hf` extra, see [Supported platforms and requirements](supported-platforms.md)) |
| `--language`, `--spacy-model`, `--no-deps`, `--enable-deps`, `--enable-ner`, `--batch-size`, `--n-process`, `--max-doc-chars`, `--no-split-long-texts`, `--meta-index-fields` | all formats |

`--language` or `--spacy-model` chooses the annotation pipeline, and
dependency relations are added when the pipeline has a parser. See
[Choosing the pipeline](languages.md#choosing-the-pipeline). Before the import
starts, `candy import` checks that the pipeline is installed. If it is not, it stops with a message that
names the command to install it and the tokenization-only alternative, for
example `blank:en`. The columns and fields of each format are described in
[Input formats](input-formats.md). The annotation pipelines are described in
[Languages and annotation pipelines](languages.md).

## `candy pipeline`

`candy pipeline NAME` looks up the release of the spaCy pipeline `NAME` that
fits the installed spaCy, downloads it from GitHub
(`explosion/spacy-models`), and installs it into the Python environment of
CandyConc with pip (or uv, in environments that uv created without pip).
CandyConc never downloads a pipeline on its own. `blank:<language>` needs no
download. With `--user-dir`, the pipeline goes into the data directory
(`~/.candyconc/pipelines`) instead, and with `--print-url` the command only
prints the address of the download.

## `candy paths`

`candy paths` prints the locations that CandyConc uses on this computer. The
output is similar to the following:

```text
data dir           /home/USER/.candyconc
config file        /home/USER/.config/candyconc/config.toml
corpora dir        /home/USER/.candyconc/corpora
corpus catalog     /home/USER/.candyconc/corpora.json
project file       /home/USER/.candyconc/proj.ccproj
projects dir       /home/USER/.candyconc/projects
logs dir           /home/USER/.candyconc/logs
pipelines dir      /home/USER/.candyconc/pipelines
```

What each location holds is described in
[Where your data lives](../concepts/where-data-lives.md).

## `candy migrate-project`

Project files of older versions (SQLite, or JSON of an older layout) are not
converted automatically. `candy migrate-project FILE` checks such a file and
reports what it contains without changing anything. With `--output NEW_FILE`
it writes a migrated copy, and with `--in-place --backup BACKUP_FILE` it
replaces the file after copying it to `BACKUP_FILE`. See
[Upgrade CandyConc](../help/upgrade.md).

## All commands and options

The following tables are generated from the argument parsers of `candy`, so
they match the installed version. `candy COMMAND --help` prints the same
information.

```{include} _generated/cli.md
```

## The launcher of the application bundle

The application bundle contains a launcher script, `./candyconc`, in the
unpacked folder. It runs the CandyConc of the bundle with the Python of the
bundle and passes most commands on to `candy`.

| Launcher command | What it does |
| --- | --- |
| `./candyconc` | Starts the server in the data directory and opens the web interface in the browser. Set `CANDYCONC_NO_BROWSER=1` to start without opening the browser. |
| `./candyconc import ...` | Same as `candy import ...`. |
| `./candyconc pipeline NAME` | Installs the spaCy pipeline `NAME` into `~/.candyconc/pipelines`, so that it stays when you replace the bundle with a newer one. |
| `./candyconc paths` | Same as `candy paths`. |
| `./candyconc version` | Shows the versions of CandyConc, Python, and spaCy, and the location of the bundle. |
| `./candyconc uninstall` | Removes the bundle folder after a confirmation. `--yes` skips the confirmation. The data directory stays. |
| `./candyconc help` | Shows these commands. |
| `./candyconc --port 8020`, and any other option | Starts the server with these options, like `candy`. |
