# Supported platforms and requirements

This page lists the operating systems, processors, and Python versions of
CandyConc 0.1.0, what each download contains, and what CandyConc needs at
runtime. The steps of the installation are in
[Install CandyConc](../get-started/install.md) and
[Install the Python package](../get-started/install-python-package.md).

## Support matrix

The local release candidate targets macOS on Apple silicon. Its binary
artifacts are one application bundle and four wheels:

| Operating system | Processor | Application bundle | Python wheels |
| --- | --- | --- | --- |
| macOS 13 or later | Apple silicon (arm64) | private CPython 3.12 | CPython 3.11, 3.12, 3.13, 3.14 |

The release workflow also configures the following targets. They have no
built or verified artifacts in this local candidate because the workflow
has not run on GitHub:

| Operating system | Processor | Configured application bundle | Configured Python wheels |
| --- | --- | --- | --- |
| macOS 13 or later | Intel (x86_64) | private CPython 3.12 | CPython 3.11, 3.12, 3.13, 3.14 |
| Linux with glibc 2.28 or later | x86_64 | private CPython 3.12 | CPython 3.11, 3.12, 3.13, 3.14 |
| Linux with glibc 2.28 or later | aarch64 (arm64) | none configured | CPython 3.11, 3.12, 3.13, 3.14 |

These targets need a workflow build and installation checks before their
artifacts can join the release. The candidate also includes a source
distribution for building from source.

Windows is not supported. CandyConc uses functions of POSIX systems that
Windows does not provide. Linux distributions with musl instead of glibc,
such as Alpine Linux, are not supported.

## Downloads

| File | Content | For |
| --- | --- | --- |
| `CandyConc-VERSION-macos-arm64.tar.gz` | application bundle: a private Python 3.12, CandyConc with all dependencies, the web interface, the launcher `./candyconc`, the sample corpora in `examples/`, a synthetic sample file, and the license notices | people who do not want to set up Python, see [Install CandyConc](../get-started/install.md) |
| `candyconc-VERSION-cp3XY-cp3XY-macosx_11_0_arm64.whl` | Python wheel with the compiled extensions and the web interface | installation with pip into your own Python environment, see [Install the Python package](../get-started/install-python-package.md) |
| `candyconc-VERSION.tar.gz` | source distribution with the built web interface and the sample corpora in `examples/` | building the wheel yourself, which needs a C compiler |
| `candyconc-VERSION-docs-html.zip` | the same HTML documentation as the application, including local diagrams, formulas, and search | offline reference |
| `RELEASE_NOTES.md` | changes and the artifact list for this version | release information |
| `SHA256SUMS` | SHA-256 checksums of all files | checking a download |

Each wheel carries the tag of its platform, for example
`candyconc-0.1.0-cp312-cp312-macosx_11_0_arm64.whl`. The local macOS wheels
use macOS 11 as the deployment target for CandyConc’s own extensions. The
complete installation requires macOS 13 because of its dependencies. The
bundle includes a compatible Python interpreter and dependency set. The
configured Linux workflow uses `manylinux_2_28`. No wheel is a `none-any` wheel, because each contains
compiled extensions. The application bundle and the wheels need no
compiler, no Node.js, and no clone of the repository.

## Read the documentation offline

Unzip `candyconc-0.1.0-docs-html.zip` and open `index.html` in the extracted
folder. Pages, diagrams, and formulas work locally. Search lists matching
page titles. For search results with text previews, use **Help > Documentation**
in CandyConc or serve the extracted folder with Python 3:

```bash
python3 -m http.server 8090 --bind 127.0.0.1 --directory candyconc-0.1.0-docs-html
```

Run this command from the folder containing the extracted directory, then
open `http://127.0.0.1:8090`. This serves the manual on your computer and
needs no internet connection. Press <kbd>Ctrl</kbd>+<kbd>C</kbd> to stop it.

## Python dependencies

Release installation requires Python 3.11 or later, as specified by the
existing package metadata. The older README also mentioned Python 3.10,
which was used for development from a checkout. That environment did not
establish an installable Python 3.10 release. The release wheels cover
Python 3.11 to 3.14.

The wheel installs its dependencies from the Python Package Index, among them
FastAPI, uvicorn, NumPy, SciPy, pandas, Polars, PyArrow, and spaCy. Optional
extras add functions:

| Extra | Installs | Adds |
| --- | --- | --- |
| `semantic` | faiss-cpu | building a word vector index for similar words, and the passage index for semantic search |
| `hf` | datasets | the import of Hugging Face datasets (`--input-format hf`) |
| `metrics` | prometheus-client | Prometheus counters of the analysis tools |
| `cluster` | hdbscan | density-based clustering in semantic clustering |
| `all` | all of the above | |

Install an extra with `pip install "candyconc[semantic]"`. The application
bundle contains no extra.

## Downloads at first use

CandyConc downloads nothing without an explicit command. These downloads
happen only when you start them:

| Download | When | From |
| --- | --- | --- |
| a spaCy annotation pipeline, for example `en_core_web_sm` | `candy pipeline NAME` or `./candyconc pipeline NAME` | GitHub (`explosion/spacy-models`) |
| a Hugging Face dataset | `candy import --input-format hf` | the Hugging Face Hub |
| a runtime and a model for the local semantic index | building a local semantic index on Apple silicon | the Python Package Index and the Hugging Face Hub |

The core functions (import with `blank:<language>`, search, concordance,
statistics, export) need no network after installation. See
[Data and privacy](../concepts/data-and-privacy.md).

## Hardware

- **Processor and memory.** CandyConc runs on the CPU. The import uses
  several processes for annotation and chooses their number and batch size
  from the CPU cores and the free memory.
- **GPU.** Core search, statistics, and corpus annotation run on the CPU.
  Optional local semantic indexing and query embeddings use MLX and the
  Apple GPU when available. The copilot uses the language model of the
  endpoint you configure, and that model runs where the endpoint runs.
- **Disk.** An index is larger than its input text. Before an import,
  CandyConc estimates the needed space as 2.5 times the input size and keeps
  5 GB free on the volume of the output directory. See
  [Configuration reference](configuration.md#import). As a measured example,
  the State of the Union sample corpus (65 documents, 403,284 tokens, input
  2.1 MB, imported with `--language en`, that is with `en_core_web_md`
  including dependency relations) gives an index of 19 MB.
- **Corpus size.** An index can hold at most 2,147,483,647 tokens, see
  [Index format](index-format.md#limits).

## Web browser

The web interface is tested with Chromium. Other current browsers have not
been tested. The browser needs JavaScript and must reach the address of the
server, by default `http://127.0.0.1:8010`.

## Development

Building CandyConc from the source tree needs Python 3.11 or later, a C
compiler, and Node.js 20.19 or later (or 22.12 or later) for the web
interface. See [Set up a development environment](../contribute/development-setup.md).
