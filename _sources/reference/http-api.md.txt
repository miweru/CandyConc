# HTTP API reference

The web interface of CandyConc talks to the server only through this HTTP
API, so every function of the interface is also available to scripts. This
page describes what applies to all routes (address, authentication, errors,
limits, jobs, streaming) and lists every route by task. The request and
response schemas of each route are in the OpenAPI description that the server
delivers itself.

For worked examples with `curl` and Python, see
[Use the HTTP API](../guides/automate/use-the-http-api.md).

## Address and schema

The server listens on `http://127.0.0.1:8010`, or on the next free port when
8010 is taken, and prints the address at start. `--host` and `--port` choose
another address (see [Command line reference](cli.md)). The examples on this
page use port 8010. All routes except the tool API start with `/api/v1`.
`GET /api` redirects to `/api/v1`.

In single-user mode the server also delivers its own description:

| Address | Content |
| --- | --- |
| `http://127.0.0.1:8010/openapi.json` | OpenAPI description of all HTTP routes of the running version |
| `http://127.0.0.1:8010/docs` | interactive page that renders the OpenAPI description and sends requests |

In multi-user mode (`CANDYCONC_SECURITY_MODE=release`) both addresses answer
404, so a public server does not advertise its routes. Use the description of
the same version on a local installation instead.

The OpenAPI description leaves out three routes: `GET /api/v1/auth/dev-token`
(see [Single-user mode](#single-user-mode)) and the two WebSocket routes (see
[Jobs and streaming](#jobs-and-streaming)).

## Authentication

What a request needs depends on the security mode of the server. The modes
are described in [Deployment](deployment.md).

### Single-user mode

In the default single-user mode there is no sign-in. Most routes answer
without a token. The routes marked in the column **Token in single-user mode**
of the tables below refuse a request without a token with
`401 User token required.`. They include the concordance export, the evidence
package, the analysis jobs, and the settings.

Get a token from the local server and send it as a bearer token:

```bash
TOKEN=$(curl -s http://127.0.0.1:8010/api/v1/auth/dev-token | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
curl -s -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query": "freedom", "format": "csv"}' \
  http://127.0.0.1:8010/api/v1/export/concordance
```

The web interface does the same when it starts. `GET /api/v1/auth/dev-token`
answers only in single-user mode with access control off. In every other
configuration it answers 404. A token is valid for 12 hours
(`CANDYCONC_TOKEN_TTL_SECONDS`) and ends when the server stops.

### Multi-user mode

In multi-user mode every route except `/api/v1/health`, `/api/v1/login`,
`/api/v1/logout`, and `/api/v1/auth/session` needs a token. Sign in with a
user of the user file:

```bash
curl -s -H 'Content-Type: application/json' \
  -d '{"username": "USERNAME", "password": "PASSWORD"}' \
  https://HOST/api/v1/login
```

Replace `USERNAME`, `PASSWORD`, and `HOST` with a user of the user file and the
address of the server. The answer contains the token. Send it in the
`Authorization: Bearer` header. Multi-user mode accepts the token only in this
header. Single-user mode also accepts it as a `token` query parameter or as a
`token` field of a JSON body.

The column **Role** in the tables below names the least role that the route
family needs in multi-user mode: `user`, `manager`, or `admin` (`none` means
no sign-in). Some routes check a higher role themselves, and their purpose
says so. The roles are described in [Deployment](deployment.md#roles).

## Errors

Errors are JSON objects in the problem details format of RFC 9457 with the
media type `application/problem+json`:

```json
{"type": "about:blank", "title": "Unauthorized", "status": 401, "detail": "User token required.", "instance": "/api/v1/export/concordance"}
```

`detail` is a text or, for some errors, an object with a `code` and a
`message`. Many errors also carry a stable `code` and its `params` at the top
level, for example `"code": "docset.corpus_mismatch"`. `code` and `params`
are the same in every language. Texts that the server has in English and
German follow the header `Accept-Language` (`en` or `de`), and without the
header they are German. The status codes that CandyConc uses on purpose:

| Status | Meaning |
| --- | --- |
| 400 | The request is invalid, for example a query with a syntax error or an unknown part-of-speech value. `detail` explains the problem and, for queries, lists the valid values or the position of the error. |
| 401 | A token is missing or unknown. |
| 403 | The role of the token is too low, or the route is not classified for multi-user mode. |
| 404 | The route, corpus, document, document set, or job does not exist. Document sets and jobs live in the memory of the server process and are gone after a restart. |
| 409 | The request conflicts with the state, for example an import into an existing directory or removing the active corpus. |
| 413 | The request body is larger than 8 MiB (`CANDYCONC_MAX_REQUEST_BYTES`), or a copilot question is too long. |
| 415 | A request body is not JSON. |
| 422 | A request field is missing or out of range, or a well-formed request does not fit the corpus, for example a document set of another corpus (`docset.corpus_mismatch`, `docset.other_corpus`, `subcorpus.corpus_mismatch`) or `sim(...)` and similar words on a corpus without word vectors (`word_vectors.unavailable`). |
| 424 | The copilot has no language model (`detail.code` is `copilot_not_configured`), or the configured model is not loaded. |
| 429 | The rate limit is reached. |
| 503 | A needed resource is not available, for example no corpus is loaded, the model endpoint cannot be reached, or the pipeline whose word vectors a corpus uses is not installed on the server (`word_vectors.service_error`). |
| 504 | The model endpoint did not answer in time. |

A missing semantic index, a corpus without dependency relations, or a query
construct that the engine does not support produce an error. They never
produce an empty result that looks like a finding.

## Rate limit

The server counts requests per minute:

- 300 requests per minute per client address for requests without a token,
- 600 requests per minute per user for requests with a token.

The web interface sends its token with every request, so the second limit
applies to it. Local scripts are counted too. Requests without a token from
the same client address share one limit, and requests authenticated as the
same user share one limit across scripts and browser tabs. Request 301
without a token (or 601 with a token) within one minute receives
`429 Rate limit exceeded` as problem details, without a `Retry-After` header. Wait until the oldest requests of the last minute leave
the window. An administrator can change both limits with
`CANDYCONC_RATE_LIMIT_ANON` and `CANDYCONC_RATE_LIMIT_DEFAULT` (see
[Configuration reference](configuration.md)).

## The capability contract

`GET /api/v1/capabilities` returns which operations this installation offers,
with the route, the least role, the corpus requirements, the maturity, and
where the operation appears (interface, API, copilot). The interface and the
copilot read the same contract. A script that reads it can decide before a
call whether an operation is available, instead of keeping its own list.
`GET /api/v1/corpora/{corpus}/capabilities` adds what one corpus supports, for
example lemmas, parts of speech, dependency relations, or a passage index. See
[The corpus index](../concepts/corpus-index.md).

## Jobs and streaming

### Analysis jobs

Routes that end in `/job` start an analysis in the background and return a
`job_id` at once. Follow the job until it reaches a final state:

1. Poll `GET /api/v1/analysis/jobs/{job_id}`. The job is `queued`, then
   `running`, and ends as `done`, `error`, or `cancelled`.
2. Read the rows of a finished job with
   `GET /api/v1/analysis/jobs/{job_id}/rows` and the parameters `offset` and
   `limit`.
3. Optional: cancel the job with `POST /api/v1/analysis/jobs/{job_id}/cancel`.

Instead of polling, open the WebSocket
`ws://127.0.0.1:8010/api/v1/ws/analysis/{job_id}`, which sends the job state
as it changes. It needs a token like the job routes. In multi-user mode, a
browser gets a one-time ticket from `POST /api/v1/ws-ticket` and adds it to
the address as `?ticket=`.

Import jobs work the same way under `/api/v1/corpora/imports`. The rebuild of
the passage index reports on the WebSocket `/api/v1/ws/faiss/{job_id}`
(admin role).

### Server-sent events

Three routes stream their result as server-sent events:

| Route | Events |
| --- | --- |
| `GET /api/v1/query/stream` | `count`, `batch` (concordance lines), `progress`, `done`. Lines arrive in corpus order. This route does not sort. A query that fails after the stream has started ends with `error` and the fields `message` and, where `GET /api/v1/query` answers with a `code`, the same `code`. |
| `POST /api/v1/chat/stream` | copilot events, see the following list |
| `POST /api/v1/copilot/continue` | copilot events of a turn that continues after an approval or an answer |

The copilot events of one turn:

- `copilot.session`: start and end of the turn with `sessionId` and `status`.
- `copilot.status`: the current stage of the turn.
- `copilot.plan`, `copilot.clarify`, `copilot.action_request`,
  `copilot.action_blocked`: a plan, a clarification question, or an action
  that waits for approval.
- `copilot.tool_result`: one tool call with its computed result.
- `copilot.recovery`: CandyConc continues the turn after an irregular step
  of the model, for example a submission that the model explained itself.
- `copilot.grounding`: the result of the grounding check and the evidence
  items of the answer.
- `copilot.done`: the final answer with `status` and `text`.
- `copilot.error`: the turn ended with an error.
- `copilot.cancelled`: the turn was stopped.

What the copilot does in each stage is explained in
[How the copilot works](../concepts/copilot.md).

## Routes by task

```{include} _generated/http_api.md
```

The tables are generated from the OpenAPI description of the server. How to
regenerate them after a change is described in
[Documentation maintenance](../contribute/documentation.md).
