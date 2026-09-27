# Use the HTTP API

The web interface talks to the CandyConc server over an HTTP API, and scripts
can use the same API: search, count, run analyses, follow analysis jobs, and
export. This guide shows these tasks with `curl`. The complete list of
endpoints and parameters is in the [HTTP API reference](../../reference/http-api.md).

## Before you begin

- A running CandyConc server. The examples assume
  `http://127.0.0.1:8010` and the English sample corpus `sotu_en`.
- `curl`, and optionally a JSON tool such as `jq` or Python to read the
  responses.

## Get a token

Many endpoints need a token in the header `Authorization: Bearer TOKEN`.

::::{tab-set}
:::{tab-item} Single-user mode
The default local server issues a token without a password:

```bash
curl -s http://127.0.0.1:8010/api/v1/auth/dev-token
```

The response is `{"token": "..."}`.
:::
:::{tab-item} Multi-user mode
Sign in with an account of the user file. Replace `USER_NAME` and
`PASSWORD`:

```bash
curl -s -X POST http://127.0.0.1:8010/api/v1/login -H 'Content-Type: application/json' -d '{"username": "USER_NAME", "password": "PASSWORD"}'
```

The response is `{"token": "..."}`. The token is valid for 12 hours or until
the server restarts. `POST /api/v1/logout` with the token ends the session.
In multi-user mode, every protected request needs the token, and the role of
the account decides what is allowed, see
[Run CandyConc for several users](../run-for-a-group/multi-user-server.md).
:::
::::

In the following examples, `TOKEN` stands for the value of `token`.

## List the corpora

```bash
curl -s http://127.0.0.1:8010/api/v1/corpora
```

The response lists every corpus of the catalog with its name, its numbers of
tokens and documents, its import format, its language and pipeline, and its
capabilities. The field `name` is the value that the parameter `corpus` of
every other route expects. The field `id` is the build fingerprint of the
index, and two builds of the same input with the same settings have the same
`id`, so it does not tell two such corpora apart. A corpus that the server
opens with `CANDYCONC_INDEX_PATH` has the name `default`, and `display_name`
holds the name of its folder.

## Count and search

Count the hits of a query:

```bash
curl -s -G http://127.0.0.1:8010/api/v1/query/count --data-urlencode term=freedom --data-urlencode corpus=sotu_en --data-urlencode wait_ms=5000 -H "Authorization: Bearer TOKEN"
```

The response is `{"status":"ready","total":495,"partial":false,...}`.
Without `wait_ms`, a count that takes longer answers `{"status":"running"}`
first. Ask again until `status` is `ready`. `partial` is `true` if the count
stopped before the end.

Fetch concordance lines:

```bash
curl -s -G http://127.0.0.1:8010/api/v1/query --data-urlencode term=freedom --data-urlencode corpus=sotu_en --data-urlencode limit=2
```

The response is a list with one object per hit, with the fields `left`,
`kw` (the node), `right`, `pos` (the token position), `doc_id`, `doc`, and
`meta`. `term` accepts plain search and the query language, see
[Query language](../../reference/query-language.md). In parameters of
analyses, write the prefix `cql:` for the query language.

When the corpus index stores the original spacing, `left`, `kw`, and `right`
show the text as written, and three more fields locate the tokens:
`token_starts` holds, for `left`, `kw`, and `right`, the offset of every
token in the field, counted in Unicode code points, and `ws_before_kw` and
`ws_after_kw` say whether a space separates the node from its neighbors.
Positions and `match_offsets` count tokens either way, see
[Original spacing](../../concepts/corpus-index.md#original-spacing).

## Run an analysis as a job

Longer analyses run as jobs. Start the collocation analysis of *freedom*:

```bash
curl -s -X POST http://127.0.0.1:8010/api/v1/analysis/collocates/job -H "Authorization: Bearer TOKEN" -H 'Content-Type: application/json' -d '{"term": "freedom", "corpus": "sotu_en", "window": 5}'
```

The response contains the `job_id` and the addresses `status_url` and
`rows_url`. Replace `JOB_ID` with the job ID and ask for the status:

```bash
curl -s http://127.0.0.1:8010/api/v1/analysis/jobs/JOB_ID -H "Authorization: Bearer TOKEN"
```

Poll at intervals until `status` is `done`, then fetch the rows. Local
scripts share the server's [rate limits](../../reference/http-api.md#rate-limit).
On HTTP 429, pause until earlier requests leave the one-minute window before
trying again.

```bash
curl -s "http://127.0.0.1:8010/api/v1/analysis/jobs/JOB_ID/rows?offset=0&limit=200" -H "Authorization: Bearer TOKEN"
```

Each row holds the collocate and all association measures, for example
`"word": "peace"`, `"observed": 52`, and `"logdice": 10.5789`. The rows
response also contains the method card in the field `method`. The server
keeps jobs in memory, so fetch the rows before you restart it.

## Export a concordance

```bash
curl -s -X POST http://127.0.0.1:8010/api/v1/export/concordance -H "Authorization: Bearer TOKEN" -H 'Content-Type: application/json' -d '{"query": "freedom", "corpus": "sotu_en", "format": "csv"}' -o freedom.csv
```

`format` is `csv`, `tsv`, `json`, `jsonl`, or `xlsx`. The file is the one
described in [Export a concordance](../keep-and-share/export-concordances.md).
An evidence package comes from `POST /api/v1/export/evidence-package` with
the same `query` and `corpus`.

## Read the API description

In single-user mode, the server describes its API at
`http://127.0.0.1:8010/docs` (interactive) and
`http://127.0.0.1:8010/openapi.json`. In multi-user mode, both are switched
off.

## Result

Your scripts can count, search, analyze, and export over HTTP with the same
results as the interface. For the analysis operations that the copilot uses,
the capability contract, and the error format, see the
[HTTP API reference](../../reference/http-api.md).
