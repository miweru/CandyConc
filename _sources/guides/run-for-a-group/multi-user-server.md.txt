# Run CandyConc for several users

By default, CandyConc runs in single-user mode: it listens only on
`127.0.0.1`, and everyone who can open the address works as administrator
without signing in. For a group, CandyConc has a multi-user mode with
accounts, roles, and sign-in. This guide creates the accounts, starts the
server in multi-user mode, and signs in.

## Before you begin

- CandyConc installed on the computer that will serve the group, see
  [Install CandyConc](../../get-started/install.md). The commands on this
  page use `candy`. With the application bundle, run `./candyconc` in the
  bundle folder for the server and `python/bin/python3 -m ...` in the bundle
  folder for the Python modules.
- The corpora imported on that computer.
- A decision about how users reach the server. For access from other
  computers, put a web server with TLS in front of CandyConc, see
  [Serve CandyConc behind a reverse proxy](reverse-proxy.md).

## Roles

Every account has one role. A higher role includes the rights of the lower
ones.

| Role | Can do |
| --- | --- |
| `user` | search, read documents, run analyses, export, annotate lines |
| `annotator` | the same rights as `user` |
| `manager` | in addition, change coding schemes and switch the annotation between single and multiple coders |
| `admin` | in addition, import, register, activate, and remove corpora, build semantic indexes, change the model connection, and see the system information |

Line annotations are recorded under the name of the signed-in account, so
the agreement between coders compares accounts.

## Create the user file

Accounts are read from a JSON file with one entry per account. The tool
`candyconc.tools.user_bootstrap` writes such a file with a hashed password.

1. Set the password of the first account in the environment variable
   `CANDYCONC_BOOTSTRAP_PASSWORD`. It must have at least 12 characters.
2. Create the file with one administrator account. Replace `ADMIN_NAME` with
   the account name:

   ```bash
   python -m candyconc.tools.user_bootstrap --username ADMIN_NAME --print-env
   ```

   The tool writes `users.json` into the CandyConc data folder, readable only
   by you, and prints the three settings for the multi-user mode:

   ```text
   export CANDYCONC_USER_FILE=/home/you/.candyconc/users.json
   export CANDYCONC_ENABLE_RBAC=1
   export CANDYCONC_SECURITY_MODE=release
   ```

Steps 3 to 6 apply to each further account.

3. Set `CANDYCONC_BOOTSTRAP_PASSWORD` to the password of that account.
4. Write the account to a separate file with its role:

   ```bash
   python -m candyconc.tools.user_bootstrap --username USER_NAME --role user --output new-user.json
   ```

   `new-user.json` contains a list with one entry.

5. Append that entry to the list in `users.json`.
6. Delete `new-user.json`.

The names `alice`, `bob`, and `charlie` are rejected, because they are
example accounts of the source tree.

## Start the server in multi-user mode

1. Set the three variables that the tool printed, for example by running the
   three `export` lines in the terminal.
2. Start CandyConc:

   ```bash
   candy --port 8010
   ```

In multi-user mode, CandyConc requires sign-in for every protected request,
accepts tokens only in the `Authorization` header, answers only to host names
in the list `CANDYCONC_TRUSTED_HOSTS` (by default `localhost`, `127.0.0.1`,
and `::1`), and hides the pages of the API documentation (`/docs`). A request
without a valid token gets the status 401, and a request with another host
name gets 400 with the message `Untrusted Host header`.

To listen on all network interfaces, add `--host 0.0.0.0`. In single-user
mode, CandyConc refuses to start with a network address. In multi-user mode
it starts, and the host names under which users reach it must be in
`CANDYCONC_TRUSTED_HOSTS`, for example:

```bash
export CANDYCONC_TRUSTED_HOSTS=corpus.example.org,localhost,127.0.0.1
```

## Sign in

1. Open the address of the server in the browser.

   The interface shows **Sign in so that CandyConc can load the capability
   catalog and the protected research features.**, and the status bar shows
   **SIGN-IN REQUIRED**.

2. In the top bar, click the session button (it reads **Not signed in**, or
   **Token expired or invalid** if the browser kept an old token).
3. In the dialog **Session and sign-in**, enter **Username**.
4. Enter **Password**.
5. Click **Sign in**.

The session button shows the account and its role, for example
**reader1 · User**, and the tab bar and the corpus catalog appear.

Functions above the role of the account are locked and name the required
role. For an account with the role `user`, the tabs **Model connection** and
**System** of the settings show **LOCKED**, and the import in the corpus
manager says **Corpus import requires at least the role Admin. Current role:
User.**

To sign out, open the session dialog and click **Sign out**.

% screenshot: interface in multi-user mode after sign-in, session button "reader1 · User"

## Sessions, limits, and logs

- A sign-in lasts 12 hours (`CANDYCONC_TOKEN_TTL_SECONDS`). The server keeps
  sessions in memory, so users sign in again after a restart.
- The server accepts at most 600 requests per minute from a signed-in account
  and 300 per minute from one address without a valid token.
- Sign-ins, failed sign-ins, and sign-outs are written to
  `logs/audit.jsonl` in the data folder.
- All users share the corpora, subcorpora, annotations, and saved analyses of
  the data folder of the server.

The settings of the multi-user mode are listed in
[Configuration reference](../../reference/configuration.md).

## Result

CandyConc serves several users with their own accounts and roles. To publish
it under a host name with TLS, continue with
[Serve CandyConc behind a reverse proxy](reverse-proxy.md).
