# Use the command line

The command `candy` imports corpora, downloads pipelines, starts the server,
and maintains data without the web interface. This guide collects the tasks
you automate most often. Every option is listed in the
[Command line reference](../../reference/cli.md).

## Before you begin

- The Python package installed, see
  [Install the Python package](../../get-started/install-python-package.md).
  With the application bundle, run `./candyconc` in the bundle folder instead
  of `candy`, and `python/bin/python3 -m ...` for the Python modules on this
  page.

## Import many files in one run

A shell loop imports every CSV file of a folder into its own corpus, named
after the file:

```bash
for f in *.csv; do
  candy import --input "$f" --output ~/.candyconc/corpora/"${f%.csv}" --language en --meta-columns speaker year > "${f%.csv}.log" 2>&1 && echo "imported $f"
done
```

Each import writes its log to a file with the name of the corpus. The loop
prints `imported` and the file name for every import that ended without an
error. Rows that could not be imported are listed in `reject_report.json` in
the index folder of each corpus. See [Import a corpus](../bring-in-texts/import-a-corpus.md).

## Stop an import at the first bad row

For pipelines in which every row must be imported, add
`--reject-policy fail_fast`. The import then stops at the first row that
cannot become a document and ends with an error, which a script can check.

## Start the server for scripts

```bash
candy --port 8020 --log-file candyconc.log
```

The server starts without opening a browser, writes its log to the file,
and serves the HTTP API at `http://127.0.0.1:8020/api/v1`. A fixed port with
`--port` fails if the port is taken, so a script does not end up on another
port by accident. Without `--port`, CandyConc takes 8010 or the next free
port. To use the API, see [Use the HTTP API](use-the-http-api.md).

## Check an index

```bash
python -m candyconc.tools.check_index ~/.candyconc/corpora/sotu_en
```

The tool reads the index without changing it and reports the builder
revision, the annotation pipeline, and known build defects. For a sound
index, the last line is `No known defect found.` An index built by an older
version can report `The morph attribute of this index is incomplete. Import
the corpus again.`

## Show where CandyConc keeps its data

```bash
candy paths
```

The output lists the data folder, the configuration file, the corpus folder,
the corpus catalog, the project file, the projects folder, the logs, and the
pipelines folder. A script can read these locations instead of assuming the
defaults, for example to back up the data folder, see
[Back up your data](../keep-and-share/back-up-your-data.md).

## Migrate a project file of an older version

```bash
candy migrate-project old-project.ccproj --output proj.ccproj
```

`--dry-run` checks the file and reports what would change without writing,
and `--in-place --backup BACKUP_FILE` replaces the file after writing a
backup. The project file holds subcorpora and line annotations, see
[Where your data lives](../../concepts/where-data-lives.md).

## Result

You can import, start, check, and maintain CandyConc from scripts. For
queries and analyses from scripts, continue with
[Use the HTTP API](use-the-http-api.md).
