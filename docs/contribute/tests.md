# Run the tests

CandyConc has three test suites: the backend tests in Python, the tests of
the web interface, and the checks of the documentation. All of them run
without a corpus of your own and without a language model. This page
describes how to run each one. The same commands run in the test workflow of
the repository (`.github/workflows/test.yml`).

## Before you begin

Set up the development environment as described in
[Set up a development environment](development-setup.md), including the
compiled extensions (`make -C app native`).

Run every command block on this page from the repository root. Commands in
parentheses change directories only within their own shell.

## Backend tests

Run the backend tests:

```bash
(cd app && PYTHONPATH=src \
  COPILOT_ENDPOINT=http://127.0.0.1:9/v1/responses \
  CANDYCONC_GEMMA_EMB_ENDPOINT=http://127.0.0.1:9/v1/embeddings \
  python -m pytest -m "not integration" tests)
```

- `-m "not integration"` leaves out the integration tests, which need a
  running language model. `app/pyproject.toml` sets the same selection as the
  default, so a plain `python -m pytest tests` does the same.
- Both endpoint variables point to a closed local port for language-model
  and embedding requests.
- `tests/conftest.py` replaces the tools of the copilot with small stand-ins
  and switches the check for loaded models off. Tests of the real tools load
  them separately.
- Some tests require an optional local reference index. When it is
  unavailable, pytest reports the missing prerequisite as the skip reason.

Run one file or one test:

```bash
(cd app && PYTHONPATH=src python -m pytest tests/unit/test_user_paths.py)
(cd app && PYTHONPATH=src python -m pytest "tests/unit/test_user_paths.py::NAME_OF_TEST" -v)
```

Replace `NAME_OF_TEST` with the name of a test function in that file.

### Lint

```bash
make -C app lint
```

`make lint` runs ruff on the backend, packaging, and import modules that the
release depends on.

### Check an installed package

`python -m candyconc.tools.install_smoke` checks an installation end to end
in a temporary data directory: the compiled extensions, the web interface and
its license notices, an import with `blank:en`, a server start without a
model endpoint, a search, and a CSV export. Run it in an environment where
you installed a wheel:

```bash
python -m candyconc.tools.install_smoke --require-web
```

It exits with status 0 when every step passed. The release workflow runs it
for every wheel.

## Tests of the web interface

Run the tests in `candyconc-web`:

```bash
(cd candyconc-web && npm ci && npx vitest run)
```

Check the types and build the interface:

```bash
(cd candyconc-web && npm run build)
```

`npm run build` runs `vue-tsc` before `vite build` and fails on a type error.
The unit tests include checks that the English and German message catalogs
have the same keys (`src/__tests__/i18n/catalogs.test.ts`).

The browser tests use Playwright. Run the Chromium project:

```bash
(cd candyconc-web && npx playwright install chromium && npm run test:e2e -- --project=chromium)
```

Playwright starts the frontend on port 5173. To use another free port, set
`CANDYCONC_FRONTEND_PORT` for the test command. The Firefox and WebKit
projects need their respective Playwright browser installations.

`e2e/app.spec.ts` runs against a simulated backend. For the live backend
check, use the Python runner from the repository root:

```bash
PYTHONPATH=app/src python -m candyconc.tools.backend_ui_live_smoke --json
```

It builds a small synthetic corpus, starts an isolated backend and frontend,
runs `e2e/backend-ui-live-smoke.spec.ts`, and stops both servers. It also
checks import preflights and compares collocation counts across the engine,
HTTP API, analysis jobs, and copilot tool without calling a language model.
The runner chooses free ports. Use `--backend-port` and `--frontend-port`
to select specific ports. Its logs and temporary data remain under
`.tmp/candyconc_backend_ui_live_smoke/`.

## Checks of the documentation

The backend suite contains `tests/docs/test_documentation_data.py`. It checks
that the generated reference pages (command line, HTTP API, configuration,
query language contract) match the code and that the worked examples of the
methods reference match an independent computation. After a change to an
option, a route, a setting, or the query engine, regenerate the pages as
described in [Documentation maintenance](documentation.md#generated-reference)
and run:

```bash
(cd app && PYTHONPATH=src python -m pytest tests/docs)
```

The build of the documentation and its link check are described in
[Documentation maintenance](documentation.md).
