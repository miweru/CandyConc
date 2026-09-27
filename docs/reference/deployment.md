# Deployment

CandyConc runs in one of two security modes. The default, single-user mode,
serves one person on one computer. Multi-user mode serves several people from
a server, with sign-in and roles. This page describes both modes, the roles,
the user file, and the templates for Docker and systemd, each with the state
of its testing for this release. The steps for setting up a server are in
[Run CandyConc for several users](../guides/run-for-a-group/multi-user-server.md)
and [Serve CandyConc behind a reverse proxy](../guides/run-for-a-group/reverse-proxy.md).

## Security modes

| | Single-user mode | Multi-user mode |
| --- | --- | --- |
| Settings | `CANDYCONC_SECURITY_MODE=local_dev_unsafe` (default) | `CANDYCONC_SECURITY_MODE=release` and `CANDYCONC_ENABLE_RBAC=1` |
| Address | `127.0.0.1` only. `--host 0.0.0.0` stops with an error unless `CANDYCONC_ALLOW_UNSAFE_NETWORK_DEV=1` is set. | any address, usually `127.0.0.1` behind a reverse proxy |
| Sign-in | none | `POST /api/v1/login` with a user of the user file |
| Token | from `GET /api/v1/auth/dev-token`, which the web interface fetches itself | from the sign-in, only in the `Authorization` header |
| Roles | not checked | checked for every route, see [Roles](#roles) |
| `Host` header | not checked | only the names in `CANDYCONC_TRUSTED_HOSTS` |
| OpenAPI pages (`/docs`, `/openapi.json`) | available | 404 |
| Routes without a classification | available | 403 |
| Record of model calls (`traces.jsonl`) | on, without message text | off |
| Start | always | refused without at least one user in the user file |

The internal name of single-user mode, `local_dev_unsafe`, states what the
mode does not do: it has no sign-in, so any program that reaches the address
has full access. On a computer that only you use, bound to `127.0.0.1`, that
is the intended setup. Do not make single-user mode reachable from a network.

Tested for this release on macOS with a local server: the refusal of
`--host 0.0.0.0` in single-user mode, and in multi-user mode the sign-in, the
refusal of requests without a token (401) and of tokens in the query string,
the refusal of an unknown `Host` header (400), the 404 of the OpenAPI pages
and of `/api/v1/auth/dev-token`, and the refusal to start without users.

## Roles

In multi-user mode every user has one role. A role includes the rights of the
roles before it:

| Role | Can |
| --- | --- |
| `user` | search, read documents, run analyses and analysis jobs, export, use the copilot, save subcorpora and analyses, annotate lines |
| `annotator` | the same as `user` in this version |
| `manager` | also change the coding scheme and switch independent annotation by several coders on or off, import line annotations on behalf of other coders |
| `admin` | also import and remove corpora, read build reports, change the model connection and other runtime settings, see system information, metrics, and the local semantic index |

The column **Role** of the [HTTP API reference](http-api.md#routes-by-task)
names the least role of every route.

## The user file

The user file is a JSON list with one object per user:

```json
[
  {"username": "admin", "password": "scrypt$...", "role": "admin"}
]
```

`password` is a scrypt hash, never the password itself. Create the file with
the first user:

```bash
python -m candyconc.tools.user_bootstrap --username admin --role admin --output /etc/candyconc/users.json
```

The tool asks for the password twice, or reads it from the environment
variable `CANDYCONC_BOOTSTRAP_PASSWORD` (another name with `--password-env`).
It writes the file readable only by its owner and refuses to overwrite an
existing file unless you add `--force`. `--print-env` prints the three
settings for multi-user mode. Without `--output`, the file goes to
`users.json` in the data directory, which is also where CandyConc looks for
it when `CANDYCONC_USER_FILE` is not set.

The tool writes one user. To add a user, run it again with `--output` pointing
to a temporary file and copy the new object into the list of the user file.
The server reads the user file when it starts.

## Docker

The template `app/deploy/Dockerfile` in the repository builds an image in two
stages: a wheel with the web interface from the source tree, then a slim image
with that wheel, a system user `candyconc`, the data directory `/data` as a
volume, and multi-user mode with role-based access control. The image starts
`candy --host 0.0.0.0 --port 8010` and has a health check on
`/api/v1/health`. The comments at the top of the file show how to create the
first user in the volume and how to start the container.

Test status: the image has not been built or run for this release.

## systemd

The template `app/deploy/candyconc.service` runs CandyConc from a virtual
environment in `/opt/candyconc/.venv` as the system user `candyconc`, with the
data directory `/var/lib/candyconc`, the user file
`/etc/candyconc/users.json`, multi-user mode, and the address
`127.0.0.1:8010` for a reverse proxy in front. The comments at the top of the
file list the steps before the first start.

Test status: the unit has not been run for this release.

## One process, one address

The server delivers the web interface and the API from the same process and
the same address: the interface at `/`, the API at `/api/v1`, the tool API at
`/mcp`. A reverse proxy therefore needs one upstream, and the interface needs
no separate web server. When the server runs behind a proxy with its own host
name, add that name to `CANDYCONC_TRUSTED_HOSTS`.

## Data on a server

All users of a server share its corpora, its project file, and its saved
analyses. Preferences are kept per user. Line annotations are kept per coder
when independent annotation by several coders is switched on. Where each part
is stored is described in [Where your data lives](../concepts/where-data-lives.md).
