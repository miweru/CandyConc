# Documentation maintenance

The documentation is a Sphinx project in `docs/`, written in Markdown with the
MyST parser and rendered with the PyData Sphinx theme. This page describes how
to build it, how to check it, and which parts are generated or recorded from
a running CandyConc. Run the command blocks on this page from the repository
root.

## Build the documentation

The documentation has its own pinned toolchain in `docs/requirements.txt`.
Install it into a separate virtual environment with Python 3.12 or newer, not
into the environment of CandyConc. The build does not import CandyConc.

```bash
python3 -m venv .venv-docs
.venv-docs/bin/python -m pip install -r docs/requirements.txt
.venv-docs/bin/sphinx-build -W --keep-going -n -b html docs docs/_build/html
```

`-W` turns every warning into an error, and `-n` reports every internal link
whose target does not exist. A build is complete only when it ends with
`build succeeded` and no warning. Open `docs/_build/html/index.html` in a
browser to read the result. The pages work without a network connection.

Check the external links:

```bash
.venv-docs/bin/sphinx-build -b linkcheck docs docs/_build/linkcheck
```

The results are in `docs/_build/linkcheck/output.txt`. The exceptions are
listed with their reasons in `linkcheck_ignore` in `docs/conf.py`: links to
`127.0.0.1` and `localhost` point to a local CandyConc server, DOI links
are skipped because several publishers answer automated requests with an
error although the DOI resolves, and links to the CandyConc repository on
GitHub are skipped while the repository is private, because GitHub answers
404 to requests without access.

The footer of every page names the version, read from `version` in the
`[project]` table of `app/pyproject.toml`, and the commit, read with `git`. The variables `CANDYCONC_DOCS_VERSION` and
`CANDYCONC_DOCS_COMMIT` override them, for example when you build from an
archive without Git. Without Git and without `CANDYCONC_DOCS_COMMIT` the
footer names only the version. A release build
(`packaging/build_web.py --require-docs`, see
[Release process](release-process.md)) stops in that case.

## House style checked by the build

The local extension `docs/_ext/candyconc_docs.py` checks the text of every page
and reports em dashes, en dashes, double hyphens, and semicolons outside code
and formulas as warnings. After the build it checks the rendered title of
every page in the same way, because the templates and settings compose it.
The title is the page heading and `CandyConc VERSION`, separated by `|`
(`docs/_templates/layout.html`). Because the documented build treats warnings
as errors, such a character stops the build with the page and line. Write two
sentences instead of a semicolon, and write number ranges with "to".

The editorial rules for the documentation, including terminology and the
form of procedures, follow the Google developer documentation style guide.
Keep one term for each thing and use the terms of the
[Glossary](../reference/glossary.md).

## Diagrams and formulas

Diagrams are Mermaid source code in a `mermaid` directive, for example in
[How CandyConc works](../concepts/how-candyconc-works.md). Every diagram needs
a paragraph or list next to it that states the same relationships in words.

Formulas are LaTeX between `$...$` (inline) or `$$...$$` (display).

Both render in the browser from copies that ship with the documentation, so no
page loads a script from another host:

| File | Version | Source | Integrity of the downloaded package |
| --- | --- | --- | --- |
| `docs/_static/mermaid/mermaid.min.js` | Mermaid 11.12.1 (MIT) | `https://registry.npmjs.org/mermaid/-/mermaid-11.12.1.tgz`, file `dist/mermaid.min.js` | `sha512-UlIZrRariB11TY1RtTgUWp65tphtBv4CSq7vyS2ZZ2TgoMjs2nloq+wFqxiwcxlhHUvs7DPGgMjs2aeQxz5h9g==` |
| `docs/_static/mathjax/tex-svg.js` | MathJax 3.2.2 (Apache 2.0) | `https://registry.npmjs.org/mathjax/-/mathjax-3.2.2.tgz`, file `es5/tex-svg.js` | `sha512-Bt+SSVU8eBG27zChVewOicYs7Xsdt40qm4+UpHyX7k0/O9NliPc+x77k1/FEsPsjKPZGJvtRZM1vO+geW0OhGw==` |

The license files lie next to each copy. `mermaid-global.mjs` hands the
Mermaid object to `sphinxcontrib-mermaid`, which expects a module. To update
Mermaid or MathJax, download the package from the npm registry, compare its
integrity value with the one the registry lists, replace the file, and update
this table.

## Recorded examples

Numbers in the examples come from runs of CandyConc on the sample corpora.
They are stored in data files and rendered by two directives of the local
extension:

| Data file | Directive | Pages | Check |
| --- | --- | --- | --- |
| `docs/_data/query_examples.json` | `query-example` | [Query language](../reference/query-language.md) | `docs/_tools/check_query_examples.py` |
| `docs/_data/worked_examples.json` | `example-table` | the pages under [How CandyConc counts](../methods/index.md) | `docs/_tools/check_worked_examples.py` |

Both scripts use only the Python standard library. They need a running
CandyConc server with the corpora of the examples:

- the English State of the Union sample corpus and the German DTA sample
  corpus, imported with the commands in `examples/README.md` (`--language en`
  and `--language de`, with the pipelines `en_core_web_md` and
  `de_core_news_md`),
- the synthetic tea corpus, imported from `docs/methods/data/tea_demo.jsonl`
  with the command on [Worked examples](../methods/worked-examples.md), and a
  second time with `--spacy-model en_core_web_sm --enable-deps` for the word
  sketch, which needs the pipeline `en_core_web_sm`.

With the server running on port 8010 and the corpora named `sotu_en`,
`dta_de`, `tea_demo`, and `tea_demo_deps`:

```bash
python docs/_tools/check_query_examples.py --server http://127.0.0.1:8010 --corpus sotu=sotu_en --corpus dta=dta_de --corpus tea=tea_demo
python docs/_tools/check_worked_examples.py --server http://127.0.0.1:8010 --corpus tea_demo --deps-corpus tea_demo_deps --sotu-corpus sotu_en
```

Each script prints every difference and exits with status 1 if there is one.
`check_worked_examples.py` without `--server` only compares the recorded
tables with its own independent computation from the corpus file, which needs
no server.

To change an example, edit the data file (the query, or the display columns
of a table) and record the new results with `--record`. The worked examples
are recorded only if the server and the independent computation agree.
Numbers that a page states in its text, such as a hand calculation, must be
updated by hand.

## Generated reference

The four files in `docs/reference/_generated/` are generated from these
sources. Edit the sources, then regenerate the affected reference.

| Generated file | Sources |
| --- | --- |
| `cli.md` | Argument parsers in `app/src/candyconc/entrypoints/cli.py` |
| `http_api.md` | Server OpenAPI description, `docs/_data/http_api.json` and the access policies in `app/src/candyconc/services/backend/route_matrix.py` |
| `configuration.md` | `docs/_data/configuration.json` and AppConfig defaults in `app/src/candyconc/config.py`. Other names are checked against the application or bundle launcher source |
| `query_contract.md` | Query-engine contract in `app/src/cqlhpc/capabilities.py` |

These scripts import CandyConc. From the repository root, use Python from
the CandyConc development environment, including its compiled extensions:

```bash
python docs/_tools/generate_cli_reference.py
python docs/_tools/generate_http_api.py
python docs/_tools/generate_configuration.py
python docs/_tools/generate_query_contract.py
```

Check all four files without writing them:

```bash
python docs/_tools/generate_cli_reference.py --check
python docs/_tools/generate_http_api.py --check
python docs/_tools/generate_configuration.py --check
python docs/_tools/generate_query_contract.py --check
```

Each check exits with status 1 if its generated file is out of date.

## Screenshots

The screenshots in `docs/_static/screenshots/` are taken from the running
application by `docs/_tools/capture_screenshots.mjs`. The script prepares a
data folder with the sample corpora, starts CandyConc from the checkout so
that the server delivers the built web interface, operates the interface in
Chromium with Playwright, and writes one PNG file per view together with a
manifest.

The script only operates the interface: clicks, typing, keyboard, and the
deep links of the application (`?corpus=...&tab=...&q=...&run=1`). It does
not change the page, and it neither intercepts nor invents server responses.
Images are only cropped to a panel or a dialog and compressed. Every run uses
a window of 1440 by 900 pixels at double pixel density, the light color
scheme, and the English interface chosen in **Settings > General**.

### Before you begin

- The development installation of CandyConc, see
  [Development setup](development-setup.md), with Node.js and the packages of
  `candyconc-web` (`npm ci`). Install the browser of Playwright once:

  ```bash
  (cd candyconc-web && npx playwright install chromium)
  ```

- The pipelines `en_core_web_md` and `de_core_news_md` in one folder:

  ```bash
  candy pipeline en_core_web_md --target PIPELINES_DIR
  candy pipeline de_core_news_md --target PIPELINES_DIR
  ```

  Replace `PIPELINES_DIR` with a folder outside the repository.

- pandoc, a LaTeX engine, and `pdftoppm` (Poppler) for the image of the PDF
  report. `pngquant` is optional. It reduces the files to 30 to 40 percent of
  their size.

### Take the screenshots

Build the web interface, then run the script from the repository root:

```bash
python packaging/build_web.py --no-docs
node docs/_tools/capture_screenshots.mjs --python PYTHON --pipelines PIPELINES_DIR --manifest MANIFEST
```

Replace `PYTHON` with the Python of the CandyConc environment and `MANIFEST`
with a path outside `docs/`, for example `../screenshots_manifest.json`.
The script imports the sample corpora and reports each capture as it runs.
It deletes and creates the folder `/tmp/demo` for the server's data and
configuration, so that no personal path appears in the images. `--home` chooses another folder, and the script refuses a folder it
did not create itself. The first scenario runs with an empty data folder.
Then the script imports the sample corpora with the commands in
`examples/README.md`, and the paired example corpus of
[Import paired versions of source texts](../guides/bring-in-texts/import-paired-versions.md).
The server runs without a language model: its model endpoints point to a
closed port.

The import checks that 5 GB stay free on the disk. On a machine with less
free space, set `CANDYCONC_BUILD_DISK_RESERVE_GB`, for example to `1`, for
the run: the script passes it to the server.

`--only SCENARIO,SCENARIO` repeats single scenarios and updates only their
entries in the manifest. The scenario names are the `id` values in the
script. `--corpora-from DIR` copies existing indexes of `sotu_en` and
`dta_de` instead of importing them.

### Check the result

The manifest records for each image the commit, the scenario and its page,
the corpus with its source file, checksum, and index fingerprint, the query
and settings, the steps, the crop, and the SHA-256 of the file. Each image
lists texts that must be visible in it, for example the hit count of a
concordance, and the manifest records whether each one was found. A scenario
can also name texts without which its image is not taken. The script then
lists the image under `not_captured` with the reason, and the page keeps its
text without the image.

Look at every new image before you commit it: the text is legible, no
control is cut off, the interface is English, and no state contradicts the
caption. Then build the documentation and read the pages at full width and
in a narrow window.

### Add a screenshot to a page

A screenshot is a MyST figure with a width, an alternative text that says
what the view shows, and a caption that says what to notice:

````markdown
```{figure} ../_static/screenshots/kwic-freedom.png
:alt: Concordance for freedom in sotu_en with 495 hits, 300 of them loaded.
:width: 100%

The concordance for *freedom*.
```
````

Give panels and dialogs half their width in pixels (for example `512px`),
because the images have double pixel density. The figure then links to the
full-size file. Name synthetic example data in the caption. The procedure
must stay complete without its image, and commands stay text.
`exclude_patterns` in `docs/conf.py` keeps the folder
`_static/screenshots` out of the static files of the build, so that each
image ships once, in `_images`.

## Add a page

1. Create a Markdown file in the section that matches the reader's goal:
   `get-started`, `tutorials`, `guides`, `concepts`, `methods`, `reference`,
   `help`, or `contribute`.
2. Add it to the `toctree` of the section's `index.md`.
3. Link to other pages with relative Markdown links, for example
   `[Query language](../reference/query-language.md)`. The build reports a
   link whose target does not exist.
4. Build with `-W -n` and read the page in the browser, at full width and in a
   narrow window.
