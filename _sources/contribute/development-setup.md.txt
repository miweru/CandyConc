# Set up a development environment

This page describes how to run CandyConc from a clone of the repository, with
the compiled extensions built locally and the web interface either built into
the package or served by its development server. To use CandyConc without
changing it, install a release instead, see
[Install CandyConc](../get-started/install.md).

## Before you begin

You need:

- Git,
- Python 3.11 or later,
- a C compiler (Xcode Command Line Tools on macOS, `gcc` on Linux),
- Node.js 20.19 or later in the 20 series, or 22.12 or later, with npm, for
  the web interface.

## The layout of the repository

| Directory | Content |
| --- | --- |
| `app/` | the Python package `candyconc` (`app/src/candyconc`) and the query engine `cqlhpc` (`app/src/cqlhpc`), their tests (`app/tests`), and the package metadata (`app/pyproject.toml`, `app/setup.py`, `app/setup_native.py`) |
| `candyconc-web/` | the web interface: Vue 3, TypeScript, Vite |
| `docs/` | this documentation (Sphinx) |
| `packaging/` | the build of the web interface into the package, the application bundle, and the synthetic sample file |
| `scripts/` | earlier entry points of the import tools, kept as thin wrappers around `candyconc.ingest` |
| `.github/workflows/` | the test and release workflows |

## Set up the Python package

1. Clone the repository and change into it:

   ```bash
   git clone https://github.com/miweru/CandyConc.git
   cd CandyConc
   ```

2. Create a virtual environment and activate it:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install the dependencies, the development tools, and Cython:

   ```bash
   python -m pip install -r app/requirements.txt -r app/requirements-dev.txt Cython
   ```

4. Build the compiled extensions in place:

   ```bash
   make -C app native
   ```

   This compiles the six Cython modules of `candyconc.core` and `cqlhpc`
   next to their sources. Run it again after you change a `.pyx` file.

5. Check the setup:

   ```bash
   PYTHONPATH=app/src python -m candyconc.entrypoints.cli --version
   ```

   The output is similar to the following:

   ```text
   CandyConc 0.1.1 (Python 3.12.8)
   ```

In this setup you run CandyConc as `python -m candyconc.entrypoints.cli` with
`PYTHONPATH=app/src`. Run from the source tree, CandyConc also reads the
settings under `[tool.candyconc]` in `app/pyproject.toml`. They set, among
others, `CANDYCONC_PROJECT_FILE = "proj.ccproj"`, so the project file with
your subcorpora is written to the directory from which you start the server,
not to the data directory as with an installed package. `candy paths` shows
the locations in effect. `python -m pip install -e app` installs it as an
editable package with the command `candy` instead, and builds the extensions
as part of the installation.

## Build the web interface into the package

The server serves the web interface that it finds in
`app/src/candyconc/web_dist`. Build it there:

```bash
python packaging/build_web.py
```

The script runs `npm ci` when `node_modules` is missing, then `npm run build`
in `candyconc-web` (type check with `vue-tsc`, then `vite build`), and copies
the result to `app/src/candyconc/web_dist`. `--skip-typecheck` leaves out the
type check. Then start the server:

```bash
PYTHONPATH=app/src python -m candyconc.entrypoints.cli
```

The web interface is at the address that the start message prints, by default
`http://127.0.0.1:8010/`. Without a build, the server prints
`API only at ...` and serves only the API.

## Work on the web interface

For changes to the interface, use the development server of Vite, which
reloads on every change:

1. Start the CandyConc server in one terminal, as in the previous section.
2. In a second terminal, install the dependencies and start the development
   server:

   ```bash
   cd candyconc-web
   npm ci
   npm run dev
   ```

3. Open the address that Vite prints, by default `http://localhost:5173/`.

The development server forwards `/api` and `/mcp` to the CandyConc server on
port 8010. If the server runs on another port, set it before `npm run dev`,
for example `CANDYCONC_BACKEND_PORT=8020 npm run dev`.

## Work on the copilot

The copilot needs an OpenAI-compatible model endpoint. Set
`COPILOT_ENDPOINT` and `COPILOT_MODEL` in the environment before you start
the server, see [Configuration reference](../reference/configuration.md). The
tests do not need a model, see [Run the tests](tests.md).

## Build the packages

```bash
python packaging/build_web.py
python -m build app
```

`python -m build app` writes the source distribution and the wheel to
`app/dist/`. With `CANDYCONC_REQUIRE_WEB_DIST=1` the build stops when the web
interface is missing. `CANDYCONC_ENABLE_OPENMP` controls OpenMP in the
compiled extensions: `auto` (default) uses it on macOS when Homebrew's
`libomp` is found, `off` builds without it, as the release wheels do. How the
release artifacts are built is described in [Release process](release-process.md).
