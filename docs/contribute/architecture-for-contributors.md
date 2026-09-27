# Architecture for contributors

This page maps the components of CandyConc to the source tree and describes
the four places where CandyConc is usually extended: a new analysis
operation, a new import format, a new copilot tool, and a new interface
language. What the components do and how data flows between them is
explained in [How CandyConc works](../concepts/how-candyconc-works.md). Read
that page first.

## Code map

Paths are relative to the root of the repository. `app/src/candyconc` is
abbreviated as `candyconc/`.

| Component | Where | Notes |
| --- | --- | --- |
| Command line | `candyconc/entrypoints/cli.py` | one `argparse` parser per command. The [Command line reference](../reference/cli.md) is generated from them. |
| Configuration and data locations | `candyconc/config.py`, `candyconc/paths.py`, `candyconc/version.py` | `AppConfig` holds every setting with its default. See [Configuration reference](../reference/configuration.md). |
| Import | `candyconc/ingest/` | `ingest_adapters.py` reads CSV, JSON Lines, plain text, Hugging Face datasets, and paired files. `build_fast_index_from_parquet.py` tokenizes and annotates with spaCy and writes the index. `build_fast_index_from_vrt.py` reads VRT. `pipelines.py` handles spaCy pipelines. |
| Import jobs of the interface | `candyconc/services/backend/corpus_import_jobs.py` | preflight, options per format, jobs, reports |
| Index and counting | `candyconc/core/` | index format and manifest (`index_format.py`), lexicons, token store, metadata, compiled counting kernels (`_fast_count.pyx`, `_fast_index.pyx`), collocation engine, significance tests |
| Query engine | `app/src/cqlhpc/` | lexer, parser, planner, compiled postings intersection and pattern matching (`cython/`), and the contract of supported constructs (`capabilities.py`). It imports from `candyconc` only the compiled kernels and the index backend of `candyconc/core`. |
| HTTP server | `candyconc/services/backend/server.py`, `routes/` | FastAPI application, one module per route group, security (`auth.py`, `route_matrix.py`, `rate_limit.py`), jobs (`analysis_jobs.py`), streaming (`http_sse.py`) |
| Analysis operations | `candyconc/services/backend/routes/analysis.py`, `analysis_runners.py`, `candyconc/services/tools/` | routes and runners of the statistics. `candyconc/analysis_defaults.py` holds `METHOD_META` and `build_method_block`. |
| Product contract | `candyconc/capabilities/product.py` | every operation with its route, role, corpus requirements, maturity, interface surfaces, and copilot tools, served as `GET /api/v1/capabilities` |
| Copilot | `candyconc/candyconc_copilot/`, `candyconc/services/llm_client.py`, `candyconc/tooling/` | orchestrator, tool wrappers, evidence and grounding, model client, tool registry |
| Tool API | `candyconc/services/mcp_server.py` | `GET /mcp/tools` and `POST /mcp/call`, the copilot tools without a model |
| Web interface | `candyconc-web/src/` | Vue 3 components by area (`components/search`, `components/analysis`, `components/copilot`, ...), Pinia stores, the API client (`api/`), message catalogs (`locales/`) |
| Serving the interface | `candyconc/services/backend/frontend_static.py` | serves the built interface from `candyconc/web_dist` |

## Contracts that keep the parts consistent

Several lists exist once in the code and are read by every part that needs
them. When you add something, add it to the contract, not to a second list:

- **The product contract** (`capabilities/product.py`) decides which
  operations the interface shows, which the copilot may call, and which role
  and corpus features each one needs. The interface and the copilot read it
  from `GET /api/v1/capabilities`.
- **The corpus capabilities** come from the index manifest and the files of an
  index (`core/index_format.py`). A view that needs dependency relations reads
  them from there.
- **The method catalog** `METHOD_META` (`analysis_defaults.py`) describes
  every statistic once: name, formula, smoothing, and default sort. Responses
  carry it in their `method` block, and `app/scripts/gen_measure_catalog.py`
  writes the copy that the interface uses (`candyconc-web/src/lib/measureCatalog.ts`).
- **The query language contract** (`cqlhpc/capabilities.py`) lists every
  construct with its status. It feeds the diagnostics, the autocompletion,
  and the [Query language](../reference/query-language.md) reference.
- **The route matrix** (`services/backend/route_matrix.py`) gives every route
  family its least role. In multi-user mode a route without a classification
  answers 403.

## Add an analysis operation

1. **Computation.** Implement the analysis on the index, in
   `candyconc/services/tools/` or `candyconc/core/`, with tests in
   `app/tests/`. State the event space, the counting unit, and the
   denominator.
2. **Route.** Add a route in `candyconc/services/backend/routes/analysis.py`
   (or a new route module included by `server.py`). Long analyses run as a
   job: follow an existing `/job` route, which returns a `job_id` and writes
   its rows to the job store (`analysis_jobs.py`).
3. **Method block.** Add every statistic that the result contains to
   `METHOD_META` and return `build_method_block(family, ...)` as the `method`
   field of the response, with the index fingerprint, the totals, and the
   scope parameters. Then regenerate the copy for the interface:

   ```bash
   python app/scripts/gen_measure_catalog.py
   ```

4. **Route matrix.** Make sure the path falls under a route family in
   `route_matrix.py`, or add one with the least role.
5. **Product contract.** Add an `operation(...)` to the capability of the
   area in `capabilities/product.py`, or a new `ui_capability(...)`, with the
   route, the effects, the input schema, the lifecycle for jobs, and the
   copilot tool if the copilot may call it. Name the corpus features it needs
   and its limits.
6. **Interface.** Add the view or panel in `candyconc-web/src/components/analysis/`,
   read the operation from the contract, and show the method block with the
   existing components.
7. **Documentation.** Describe the method on a page under
   [How CandyConc counts](../methods/index.md), add a guide, and regenerate
   the HTTP API reference (`python docs/_tools/generate_http_api.py`) after
   adding the purpose of the route to `docs/_data/http_api.json`.

## Add an import format

1. **Reader.** Add a reader to `candyconc/ingest/ingest_adapters.py` that
   yields one record per document, and a build function that passes the
   records to the shared index build, like `build_index_from_csv`. Record
   rejected rows with a reason in the reject sink.
2. **Subcommand.** Add a subcommand for the format to the parser in `main()`
   of `ingest_adapters.py`.
3. **Method table.** Register the format in `_IMPORT_BUILDERS` in
   `candyconc/utils/import_builders.py`.
4. **Command line.** Add it to the choices of `--input-format` and, if it has
   a file extension, to the extension detection in
   `candyconc/entrypoints/cli.py`, and pass its options on.
5. **Import jobs.** Add its options, columns, and preflight to
   `candyconc/services/backend/corpus_import_jobs.py`. The import form of the
   interface is built from these descriptions.
6. **Tests and documentation.** Test the reader with small files and
   describe the format in [Input formats](../reference/input-formats.md).
   Regenerate the command line reference
   (`python docs/_tools/generate_cli_reference.py`).

## Add a copilot tool

A copilot tool is a thin wrapper around an analysis operation. The model sees
its name, description, and parameter schema, and its result becomes an
evidence item with an identifier.

1. **Operation first.** The tool calls an operation that exists as an HTTP
   route or a function of the analysis layer, so that the interface, the tool
   API, and the copilot compute the same numbers.
2. **Wrapper.** Write the wrapper in
   `candyconc/candyconc_copilot/tool_wrappers.py` and register it with the
   decorator `llm_tool` of `candyconc/tooling/registry.py`, with an OpenAI
   function schema whose parameters are an object. Return a dictionary with
   `status` and the computed fields.
3. **Contract.** Name the tool in the `copilot_tools` of the operation in
   `capabilities/product.py`. Only tools named there are offered to the
   model (`visible_product_copilot_tools`).
4. **Tests.** Test the real wrapper, not only the stand-in of
   `tests/conftest.py`, and test that `GET /mcp/tools` lists it.

## Add an interface language

The interface has message catalogs per language and area in
`candyconc-web/src/locales/`. English and German exist.

1. Copy `candyconc-web/src/locales/en/` to a directory named with the
   language code and translate the values. Keep the keys. Every catalog ends
   with `satisfies LocaleNamespace<typeof de>`, so a missing or extra key is a
   type error.
2. Import the new catalogs in `candyconc-web/src/i18n/index.ts`, add the code
   to `SUPPORTED_LOCALES`, and add the language to `messages`.
3. In `candyconc-web/src/i18n/locale.ts`, add the Intl tag for number and date
   formats to `INTL_TAGS`, the detection in `normalizeLocale` and
   `detectBrowserLocale`, and the value of `acceptLanguageHeader`.
4. Add the language to the language selection in the general settings.
5. Run `npx vitest run` and `npm run build`. The catalog test compares the
   keys of all catalogs.

The server chooses the language of its own messages from the
`Accept-Language` header of each request
(`candyconc/services/backend/request_language.py`). It supports German and
English, and falls back to German. Texts of the server that the interface
shows need a translation there as well.
