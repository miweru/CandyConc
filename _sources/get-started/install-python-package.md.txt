# Install the Python package

The Python package of CandyConc is a wheel that contains the server, the
command `candy`, the native query engine, the corpus importers, and the built
web interface. Install it when you manage your own Python environments, want
to script imports and analyses, or need an optional package extra. For an installation without Python, use the
[application bundle](install.md).

## Before you begin

- Python 3.11, 3.12, 3.13, or 3.14 on macOS 13 or later (Apple silicon)
  for the local release candidate. Intel macOS and Linux builds are
  configured in CI. See their
  [platform status](../reference/supported-platforms.md).
- `pip` or [uv](https://docs.astral.sh/uv/).
- About 600 MB of disk space for a virtual environment with CandyConc and its
  dependencies (measured with Python 3.13 on macOS on Apple silicon).
- Network access during the installation. pip or uv download the
  dependencies from the Python Package Index.

No compiler and no Node.js are needed. The wheels are built for each
platform and Python version and contain the compiled extensions.

## Choose the wheel

The Releases page lists one wheel for each Python version and platform. The
file name tells which one fits:

```text
candyconc-VERSION-cp313-cp313-macosx_11_0_arm64.whl
                  ^^^^^^^^^^^ ^^^^^^^^^^^^^^^^^^^^
                  Python 3.13 Apple silicon, native build target 11.0
```

| Part of the file name | Meaning |
| --- | --- |
| `cp311`, `cp312`, `cp313`, `cp314` | Python 3.11, 3.12, 3.13, 3.14 |
| `macosx_11_0_arm64` | macOS on Apple silicon |
| `macosx_11_0_x86_64` | macOS on Intel |
| `manylinux_2_28_x86_64` | Linux on x86_64 |
| `manylinux_2_28_aarch64` | Linux on aarch64 |

The `11_0` tag describes CandyConc’s own compiled extensions. Its
dependencies require macOS 13 or later for a complete prebuilt installation.
To see your Python version, run `python3 --version`.

## Install with pip

1. Download the wheel for your Python version and platform from the
   [Releases page](https://github.com/miweru/CandyConc/releases) into a
   folder of your choice.
2. In that folder, create a virtual environment and activate it:

   ```bash
   python3 -m venv candyconc-env
   source candyconc-env/bin/activate
   ```

3. Install the wheel:

   ```bash
   python -m pip install candyconc-*.whl
   ```

   pip installs CandyConc and its dependencies.

4. Check the installation:

   ```bash
   candy --version
   ```

   The output is similar to the following:

   ```text
   CandyConc 0.1.1 (Python 3.13.11)
   ```

## Install with uv

1. Download the wheel as described in the previous section.
2. In the folder with the wheel, create an environment and install the wheel
   into it:

   ```bash
   uv venv candyconc-env
   uv pip install --python candyconc-env/bin/python candyconc-*.whl
   source candyconc-env/bin/activate
   candy --version
   ```

   An environment created by uv contains no pip. `candy pipeline` detects this
   and installs pipelines with uv instead.

## Optional features

The core package contains everything for import, search, and analysis. Four
optional groups add dependencies for single features:

| Extra | Adds | Needed for |
| --- | --- | --- |
| `semantic` | `faiss-cpu` | building a word thesaurus or a passage index |
| `hf` | `datasets` | importing a Hugging Face dataset |
| `metrics` | `prometheus-client` | Prometheus metrics of the server |
| `cluster` | `hdbscan` | semantic clustering |
| `all` | all of the above | |

To install an extra, name it after the wheel file in square brackets and
quote the argument:

```bash
python -m pip install "$(ls candyconc-*.whl)[semantic]"
```

## Download an annotation pipeline

Lemmas, parts of speech, and dependency relations come from a spaCy pipeline.
CandyConc never downloads a pipeline by itself. Download one explicitly, for
example the small English pipeline (12.8 MB):

```bash
candy pipeline en_core_web_sm
```

The pipeline is installed into the active environment, next to CandyConc.
`candy pipeline en_core_web_sm --print-url` only prints the download address,
if you want to fetch the file yourself. See
[Choose language and annotation layers](../guides/bring-in-texts/choose-annotation.md).

## Start CandyConc

1. Start the server:

   ```bash
   candy --open
   ```

   The interface opens in the browser.

   Without `--open`, CandyConc starts without opening a browser and prints
   the address. It listens on `http://127.0.0.1:8010/`, or on the next free
   port if 8010 is taken. `--port` chooses the port.

2. To stop the server, press <kbd>Control</kbd>+<kbd>C</kbd>.

You can start `candy` from any folder. CandyConc keeps its data in
`~/.candyconc` (or in the folder named by `CANDYCONC_HOME`) and reads its
configuration from a file in the configuration folder of your platform.
`candy paths` prints both:

```bash
candy paths
```

The output is similar to the following:

```text
data dir           /home/you/.candyconc
config file        /home/you/.config/candyconc/config.toml
corpora dir        /home/you/.candyconc/corpora
corpus catalog     /home/you/.candyconc/corpora.json
project file       /home/you/.candyconc/proj.ccproj
projects dir       /home/you/.candyconc/projects
logs dir           /home/you/.candyconc/logs
pipelines dir      /home/you/.candyconc/pipelines
```

On macOS, the configuration file is
`~/Library/Application Support/candyconc/config.toml`. If the folder where
you start `candy` contains a file `proj.ccproj` or a folder
`config/projects`, CandyConc uses them instead of the ones in the data folder,
so that projects of earlier versions keep working.

## Next steps

To use the sample corpora, download `candyconc-VERSION.tar.gz` from the same
Releases page and unpack it. Its `examples/` folder contains the English and
German input files. Open a terminal in the unpacked folder, keep your
CandyConc environment active, and use `candy` wherever a tutorial writes
`./candyconc`.

- Import the English sample corpus and run a first analysis:
  [First results](first-results.md).
- Script imports and queries: [Use the command line](../guides/automate/use-the-cli.md)
  and [Use the HTTP API](../guides/automate/use-the-http-api.md).
- All commands and options: [Command line reference](../reference/cli.md).
- Update or remove the package: [Upgrade CandyConc](../help/upgrade.md),
  [Uninstall CandyConc](../help/uninstall.md).
