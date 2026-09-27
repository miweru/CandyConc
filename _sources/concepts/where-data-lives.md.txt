# Where your data lives

CandyConc keeps the program and your data apart. The program is the
application bundle folder or the Python environment in which you installed
the wheel. Your data (corpora, project file, preferences, logs) lives in one
data directory, by default `~/.candyconc`. Updating or removing the program
does not touch the data directory, and you can copy the data directory to
back up or move your work.

To see the locations on your computer, run:

```bash
candy paths
```

With the application bundle, run `./candyconc paths` in the bundle folder.

## The data directory

The data directory is `~/.candyconc` on macOS and Linux, or the directory in
`CANDYCONC_HOME`. It contains:

| Path | Content | Written when |
| --- | --- | --- |
| `corpora/NAME/` | one corpus index per corpus, see [Index format](../reference/index-format.md) | an import finishes |
| `corpora/.imports/` | working directories of import jobs from the web interface | an import runs |
| `corpora.json` | the corpus catalog and the active corpus | you import, register, activate, or remove a corpus |
| `proj.ccproj` | the project file: saved subcorpora, line annotations, the coding scheme, see [Project files](../reference/project-files.md) | you save a subcorpus or annotate a line |
| `projects/` | saved analyses and cluster lists | you save an analysis |
| `prefs.json` | the preferences of the web interface, per user | you change a preference |
| `users.json` | the user file of multi-user mode, if you created it here | you run `python -m candyconc.tools.user_bootstrap` |
| `pipelines/` | spaCy pipelines installed with `./candyconc pipeline` or `candy pipeline --user-dir` | you install a pipeline this way |
| `logs/audit.jsonl` | sign-ins, failed sign-ins, sign-outs, and WebSocket tickets | such an event happens |
| `traces.jsonl` | a record of every call to the language model without the message text, in single-user mode | the copilot calls a model |
| `fastcount_build.log`, `fastindex_build.log` | messages about the compiled extensions | a compiled extension is missing or fails to load |
| `tmp/` | temporary files of the server | the server runs |
| `semantic-jobs/`, `runtimes/` | state and runtime of the local semantic index build (Apple silicon) | you build a local semantic index |

Older versions kept the project file and the project directory in the
working directory of the server. If a `proj.ccproj` or a `config/projects`
directory exists in the directory where you start CandyConc, it is used
instead of the one in the data directory. `candy paths` shows which one is in
effect.

## Outside the data directory

| Location | Content |
| --- | --- |
| the configuration file, see [Configuration reference](../reference/configuration.md#the-configuration-file) | settings, only if you created the file |
| the Python environment or the bundle folder | the program, and spaCy pipelines installed with `candy pipeline NAME` without `--user-dir` |
| the temporary directory of the system (`exports/`) | files of PDF and Word exports until they are downloaded |
| the download folder chosen in the browser | downloaded concordances, analysis tables, evidence packages, and document exports |
| the browser (local storage) | the search history, a copy of the preferences, the color scheme, and saved runs of the interface |
| the memory of the server | document sets, analysis and import jobs, tokens, and copilot sessions. They are gone after a restart. |

A corpus that you register from another directory with **Register existing corpus** in the
corpus manager (or `POST /api/v1/corpora/register`) stays in that directory.
Only its entry in `corpora.json` is added.

## What survives an update or an uninstall

| Data | Update | Uninstall |
| --- | --- | --- |
| corpora, project file, saved analyses, preferences, logs in the data directory | kept | kept, until you delete the data directory |
| spaCy pipelines in `~/.candyconc/pipelines` | kept | kept, until you delete the data directory |
| spaCy pipelines installed into the Python environment | kept with `pip install --upgrade` in the same environment. With a new bundle, install them again. | removed with the environment or the bundle folder |
| the configuration file | kept | kept, until you delete it |
| state in the browser | kept | kept, until you clear the site data of the browser |

In a test of the Python package on macOS, uninstalling and reinstalling
CandyConc left every file in the data directory unchanged, compared by
checksum. See [Upgrade CandyConc](../help/upgrade.md) and
[Uninstall CandyConc](../help/uninstall.md).

## Back up your work

Copy the data directory while CandyConc is not running. Also keep your
input files and downloaded exports. The corpora are the largest part, and you can also
rebuild them from your input files with the same import settings. See
[Back up your data](../guides/keep-and-share/back-up-your-data.md).
