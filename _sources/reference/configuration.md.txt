# Configuration reference

CandyConc works without any configuration. This page lists the settings that
you can change: first the decisions a researcher makes (which language model,
which corpus at start), then the settings for running CandyConc for others
(locations, security, logs, limits). Every setting has the same name in the
environment and in the configuration file.

The settings listed on this page are the supported configuration. Names that
the code reads but that are not listed here are internal and can change
without notice.

## Where settings come from

CandyConc reads each setting from the first of these sources that has it:

1. **A change at runtime.** **Settings > Model connection** in the web
   interface changes the endpoint, model, and key of the copilot at once. The
   change lasts until the server stops and is not written to a file.
2. **The environment** of the server process, for example
   `COPILOT_MODEL=my-model candy`.
3. **The configuration file** `config.toml`. `candy paths` prints its
   location. The default location is
   `~/Library/Application Support/candyconc/config.toml` on macOS and
   `$XDG_CONFIG_HOME/candyconc/config.toml` (usually
   `~/.config/candyconc/config.toml`) on Linux. `CANDYCONC_CONFIG_FILE`
   points to another file.
4. **`[tool.candyconc]` in `app/pyproject.toml`**, only when CandyConc runs
   from a source checkout (with `PYTHONPATH=src` or an editable install) and
   the file has this table. An installed wheel has no such file.
5. **The default** in the code, listed in the tables on this page.

Command line options of `candy` (`--enable-rbac`, `--log-level`,
`--log-file`) set the corresponding setting for one start.

All settings except the runtime change in the first source take effect when
the server starts. Restart the server after you change the environment or the
configuration file.

## The configuration file

The configuration file is TOML. Each line sets one setting with the same name
as the environment variable. Values are text, numbers, or `true` and `false`.
Tables and lists are not allowed. Example:

```toml
COPILOT_ENDPOINT = "http://127.0.0.1:1234/v1/responses"
COPILOT_MODEL = "qwen3-30b-a3b"
CANDYCONC_LOG_LEVEL = "WARNING"
```

A file that is not valid TOML, or that contains a table or a list, stops the
server at start with a message that names the file and the problem. A setting
in the environment always wins over the same setting in the file.

```{include} _generated/configuration.md
```

## Settings of the web interface

The **Settings** dialog of the web interface keeps display preferences such
as results per page and the interface language. The server saves them in the
preferences file listed under [Locations](#locations), and the browser keeps
a copy. They are not part of this configuration. The
interface is described in [Interface reference](interface.md).
