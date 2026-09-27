# Connect a language model

The copilot is optional. It answers research questions by calling the same
analysis operations as the interface and needs a language model for that.
CandyConc does not ship, download, or start a model. It connects to a model
server that you run or choose, over an OpenAI-compatible HTTP interface. This
guide connects such a server.

## Before you begin

- A running model server with an OpenAI-compatible endpoint, for example
  LM Studio on your computer, or an online provider.
- The address of its endpoint and the name under which it lists the model.
- For an online provider: an API key.
- Decide where the model runs. With a model on your computer, questions and
  corpus excerpts stay on it. With an online provider, they are sent to that
  provider. See [Data and privacy](../../concepts/data-and-privacy.md).

## Without a model

Everything except the copilot works without a model. When you start
CandyConc without one, the terminal shows
`Copilot: no language model configured (optional, see Settings > Model connection)`.
The copilot panel then shows **No language model set up** with the button
**Set up model connection**, which opens the tab **Model connection** of the
settings. The input field of the panel is locked until a model is set. Over
the HTTP API, a question returns the status 424 with the code
`copilot_not_configured`. No request leaves your computer.

## Connect a model for the current session

1. Click **Settings**.
2. Open the tab **Model connection**.
3. In **Endpoint**, enter the address of the model server, for example
   `http://127.0.0.1:1234/v1/chat/completions` for LM Studio on your
   computer.
4. In **Model**, enter the name under which the server lists the model.
5. Click **Apply**.

CandyConc reports **Model connection changed. It applies from the next
question.**, and the line **Active:** shows the model and the endpoint.

The tab also offers two prepared connections as buttons: a local LM Studio
server at `http://127.0.0.1:1234/v1/chat/completions`, and OpenRouter, an
online provider, at `https://openrouter.ai/api/v1/chat/completions`, which
needs an API key. The note under each button says whether text leaves the
computer.

A connection set in this tab lasts until CandyConc stops. An API key entered
here is kept only in the memory of the running server and is never written
to disk.

```{figure} ../../_static/screenshots/settings-model-connection.png
:alt: Settings, tab Model connection, with Local (LM Studio) selected, the custom endpoint http://127.0.0.1:9/v1/responses, and MODEL_NAME shown in the form and the Active line.
:width: 512px

After **Apply**, **Active:** shows the configured model and endpoint. This illustration uses the placeholder `MODEL_NAME` and a closed local port. Applying settings does not test the model connection.
```

## Connect a model permanently

Set the connection in the configuration file or in the environment. The
configuration file is `config.toml` at the location that `candy paths` shows
as `config file`. Create it with these lines, adapted to your server:

```toml
COPILOT_ENDPOINT = "http://127.0.0.1:1234/v1/chat/completions"
COPILOT_MODEL = "MODEL_NAME"
```

Replace `MODEL_NAME` with the name of the model on the server. For a
provider that needs a key, add `COPILOT_API_KEY = "YOUR_KEY"`, or set the key
in the environment variable `COPILOT_API_KEY` to keep it out of the file.

The same names work as environment variables, for example:

```bash
COPILOT_ENDPOINT=http://127.0.0.1:1234/v1/chat/completions COPILOT_MODEL=MODEL_NAME candy
```

An environment variable takes precedence over the configuration file. Restart
CandyConc after a change. The terminal then shows the line
`Copilot: MODEL_NAME at` followed by the endpoint.

## Which endpoints CandyConc accepts

The endpoint must start with `http://` or `https://`. CandyConc accepts the
chat completions interface (`/v1/chat/completions`) and the responses
interface (`/v1/responses`) of OpenAI-compatible servers. An address without
one of these paths is completed with `/chat/completions`. The copilot calls
analysis tools, so the model must support tool calls.

## Result

The copilot sends your next question to the model you connected. How the
copilot works, which evidence it uses, and how to check its answers is
described in [How the copilot works](../../concepts/copilot.md). All settings
of the copilot are listed in [Configuration reference](../../reference/configuration.md).
