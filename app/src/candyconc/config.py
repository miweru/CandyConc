from __future__ import annotations

import builtins
import os
from pathlib import Path
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib



from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, model_validator

from typing import Any, Dict
from urllib.parse import urlparse, urlunparse


def _normalize_lm_studio_transport(value: str | None) -> str:
    raw = (value or "chat_completions").strip().lower().replace("-", "_")
    aliases = {
        "auto": "auto",
        "chat": "chat_completions",
        "chatcompletions": "chat_completions",
        "chat_completion": "chat_completions",
        "chat_completions": "chat_completions",
        "responses": "responses",
        "response": "responses",
    }
    return aliases.get(raw, raw)


def _normalize_lm_studio_base_url(value: str | None) -> str | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = f"http://{raw}"

    parsed = urlparse(raw)
    path = parsed.path.rstrip("/")
    for suffix in (
        "/v1/chat/completions",
        "/chat/completions",
        "/v1/responses",
        "/responses",
        "/v1/models",
        "/models",
    ):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    if not path.endswith("/v1"):
        path = f"{path}/v1" if path else "/v1"

    return urlunparse(parsed._replace(path=path, params="", query="", fragment="")).rstrip("/")


def _build_lm_studio_endpoint(base_url: str, transport: str) -> str:
    normalized_base = _normalize_lm_studio_base_url(base_url)
    if not normalized_base:
        raise RuntimeError("LM_STUDIO_BASE_URL is not configured")
    normalized_transport = _normalize_lm_studio_transport(transport)
    if normalized_transport == "responses":
        return f"{normalized_base.rstrip('/')}/responses"
    return f"{normalized_base.rstrip('/')}/chat/completions"


def _extract_lm_studio_base_url(endpoint: str | None) -> str | None:
    if not endpoint:
        return None
    parsed = urlparse(endpoint)
    path = parsed.path.rstrip("/")
    if path.endswith("/v1/chat/completions") or path.endswith("/chat/completions"):
        return _normalize_lm_studio_base_url(endpoint)
    if path.endswith("/v1/responses") or path.endswith("/responses"):
        return _normalize_lm_studio_base_url(endpoint)
    if path.endswith("/v1/models") or path.endswith("/models"):
        return _normalize_lm_studio_base_url(endpoint)
    return None


class ConfigFileError(RuntimeError):
    """The user configuration file exists but cannot be used."""


def _read_toml(path: Path) -> Dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _load_defaults() -> dict[str, Any]:
    """Return the source-checkout profile ``[tool.candyconc]``.

    Only a source checkout carries it: ``app/pyproject.toml`` two levels above
    this file, and only when that file describes the ``candyconc`` project.
    An installed package has no such file, so its defaults are the field
    defaults below. A broken or foreign pyproject.toml is ignored.
    """
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if not pyproject.is_file():
        return {}
    try:
        data: Dict[str, Any] = _read_toml(pyproject)
    except Exception:
        return {}
    if data.get("project", {}).get("name") != "candyconc":
        return {}
    return dict(data.get("tool", {}).get("candyconc", {}))


def _load_user_config() -> dict[str, Any]:
    """Return the settings of the user configuration file, if it exists.

    The file is TOML with the same names as the environment variables, for
    example ``COPILOT_ENDPOINT = "http://127.0.0.1:1234/v1/responses"``. Its
    location is ``CANDYCONC_CONFIG_FILE`` or ``config.toml`` in the platform
    configuration directory (see :mod:`candyconc.paths`).
    """
    from candyconc.paths import config_file

    path = config_file()
    if not path.is_file():
        return {}
    try:
        data = _read_toml(path)
    except Exception as exc:
        raise ConfigFileError(f"Configuration file {path} is not valid TOML: {exc}") from exc
    values: Dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            raise ConfigFileError(
                f"Configuration file {path}: {key} must be a single value "
                "(text, number or true/false), not a table or list."
            )
        values[key] = value
    return values


class AppConfig(BaseSettings):
    """Application configuration"""

    COPILOT_ENDPOINT: str | None = None
    COPILOT_API_KEY: str | None = "lm-studio"
    COPILOT_MODEL: str = "qwen3-30b-a3b"
    LM_STUDIO_BASE_URL: str | None = None
    LM_STUDIO_API_KEY: str | None = None
    LM_STUDIO_MODEL: str | None = None
    LM_STUDIO_TIMEOUT: float | None = None
    LM_STUDIO_TOOL_MODEL: str | None = None
    LM_STUDIO_JSON_MODEL: str | None = None
    LM_STUDIO_LARGE_CONTEXT_MODEL: str | None = None
    LM_STUDIO_FALLBACK_MODELS: str | None = None
    LM_STUDIO_TRANSPORT: str = "chat_completions"
    CANDYCONC_LM_STUDIO_REQUIRE_LOADED_MODEL: bool = True
    CANDYCONC_LM_STUDIO_MODEL_PREFLIGHT_TTL_SEC: float = 0.0
    CANDYCONC_LM_STUDIO_MODEL_PREFLIGHT_TIMEOUT_SEC: float = 2.0
    # HTTP round-trip timeout in seconds. This protects against a stuck socket.
    # A long-running model request may still be doing useful work.
    COPILOT_TIMEOUT: float = 8_000_000.0
    # Limits one model turn, not its wall-clock runtime. This keeps local
    # reasoning models from streaming indefinitely while preserving long,
    # timeout-free requests on contended hardware.
    # 0 = KEIN Ausgabe-Budget im Payload (Nutzervorgabe, siehe
    # llm_client._get_max_output_tokens). Ausdruecklich gesetzte positive
    # Werte wirken weiterhin.
    COPILOT_MAX_OUTPUT_TOKENS: int = 0
    # Optional OpenAI-compatible reasoning budget. Leave unset for models or
    # providers that do not expose low/medium/high effort controls.
    COPILOT_REASONING_EFFORT: str | None = None
    # Qwen3 thinking switch. Empty leaves the message unchanged, 'off' appends
    # /no_think, and 'on' appends /think. Applied only when explicitly configured.
    COPILOT_THINKING_MODE: str | None = None
    # Time limit in seconds of the recipe classifier call (stage 2 of the
    # recipe choice). None uses RECIPE_CLASSIFIER_TIMEOUT_S from
    # recipe_runtime (300 s). The environment overrides the config file.
    COPILOT_RECIPE_CLASSIFIER_TIMEOUT_S: float | None = None
    CANDYCONC_RESPONSES_BUFFERED_STREAM: bool = True
    HTTP_TIMEOUT: float = 10.0
    CANDYCONC_SECURITY_MODE: str = "local_dev_unsafe"
    CANDYCONC_ENABLE_RBAC: bool = False
    # Corpus-response masking remains opt-in because it requires entity tags in
    # the active index. Copilot-bound free text is independent of that index and
    # therefore protected by default.
    CANDYCONC_ENABLE_PII_MASK: bool = False
    CANDYCONC_ENABLE_COPILOT_PII_MASK: bool = True
    DRY_RUN: bool = False
    CANDYCONC_ENABLE_QUERY_CACHE: bool = False
    CANDYCONC_QUERY_CACHE_SIZE: int = 128
    # KWIC query runtime bounds. /api/v1/query keeps its fixed 5k hard cap;
    # streaming keeps its existing 50k cap.
    CANDYCONC_QUERY_DEFAULT_LIMIT: int = 1000
    CANDYCONC_QUERY_MAX_CONTEXT: int = 600
    CANDYCONC_KWIC_LIMIT: int = 1000
    CANDYCONC_CONTROLLER_COUNT_LIMIT: int = 200000
    CANDYCONC_WORD_SKETCH_RELATION_LIMIT: int = 100
    CANDYCONC_ANALYSIS_PAGE_LIMIT_DEFAULT: int = 200
    CANDYCONC_ANALYSIS_PAGE_LIMIT_MAX: int = 5000
    CANDYCONC_ANALYSIS_SYNC_LIMIT_DEFAULT: int = 500
    CANDYCONC_ANALYSIS_SYNC_LIMIT_MAX: int = 5000
    CANDYCONC_ANALYSIS_JOB_TOP_N_DEFAULT: int = 5000
    CANDYCONC_ANALYSIS_JOB_TOP_N_MAX: int = 50000
    CANDYCONC_ANALYSIS_NGRAM_MAX_N: int = 5
    CANDYCONC_ANALYSIS_COLLOCATE_MAX_WINDOW: int = 50
    CANDYCONC_ANALYSIS_RESULT_MAX_BYTES: int = 128 * 1024 * 1024
    # Exact sentence alignment is quadratic in sentence-token pairs.  Refuse an
    # oversized request instead of truncating text or publishing a partial score.
    CANDYCONC_ALIGNMENT_MAX_EDIT_CELLS: int = 12_000_000
    CANDYCONC_EMB_BACKEND: str = "spacy"
    CANDYCONC_EMB_SPACY_MODEL: str = "de_core_news_md"
    CANDYCONC_GEMMA_EMB_ENDPOINT: str = "http://127.0.0.1:1234/v1/embeddings"
    CANDYCONC_GEMMA_EMB_MODEL: str = "google/embedding-gemma-300m"
    CANDYCONC_GEMMA_EMB_BATCH: int = 32
    CANDYCONC_GEMMA_EMB_TIMEOUT: float = 120.0
    CANDYCONC_BACKEND_URL: str = "http://127.0.0.1:8010/api/v1"
    CANDYCONC_MCP_URL: str | None = None
    CANDYCONC_ENABLE_OTEL: bool = False
    CANDYCONC_ENABLE_LLM_TRACE: bool | None = None
    CANDYCONC_LOG_LEVEL: str = "INFO"
    CANDYCONC_LOG_FILE: str | None = None
    CANDYCONC_ENABLE_TELEMETRY: bool = True
    CANDYCONC_USER_FILE: str = "config/users.json"
    # Empty means: default location, see candyconc.paths.project_file and
    # candyconc.paths.projects_dir (data directory, or an existing
    # proj.ccproj / config/projects in the working directory).
    CANDYCONC_PROJECTS_DIR: str = ""
    CANDYCONC_PROJECT_FILE: str = ""
    # Grounding contracts are JSON-native. Providers that reject
    # response_format automatically fall back to the schema prompt route.
    USE_STRUCTURED_OUTPUT: bool = True
    ENABLE_EMBEDDING_SEARCH: bool | None = None
    ENABLE_FAISS: bool = False
    CANDYCONC_FAISS_NPROBE: int = 0
    CANDYCONC_SIM_DEFAULT_K: int = 20
    CANDYCONC_SIM_MAX_K: int = 2000
    CANDYCONC_SIM_CACHE_SIZE: int = 64
    FAISS_DIR: str = "runtime"
    # Empty: the corpus comes from CANDYCONC_INDEX_PATH or the active entry of
    # the corpus catalogue. Without either, the server starts with an empty
    # catalogue and the import.
    index_dir: str = ""

    @field_validator("CANDYCONC_BACKEND_URL", mode="before")
    @classmethod
    def _ensure_v1_prefix(cls, value: str) -> str:
        """Ensure the backend URL ends with ``/api/v1``."""
        if not value:
            return "http://127.0.0.1:8010/api/v1"
        url = value.rstrip("/")
        if url.endswith("/api"):
            url = url[:-4]
        if not url.endswith("/api/v1"):
            url = url + "/api/v1"
        return url

    @model_validator(mode="after")
    def _apply_shared_lm_studio_config(self) -> "AppConfig":
        # Re-entrancy guard: with ``validate_assignment=True`` the self-assignments
        # below would each re-trigger this mode='after' validator and recurse
        # forever. A nested invocation (already inside the derivation pass) is a
        # no-op — the outer pass has already reconciled every derived field. The
        # flag lives outside the pydantic field set (object.__setattr__) so it is
        # neither validated nor serialized.
        if getattr(self, "_in_shared_lm_studio_sync", False):
            return self
        object.__setattr__(self, "_in_shared_lm_studio_sync", True)
        try:
            return self._reconcile_shared_lm_studio_config()
        finally:
            object.__setattr__(self, "_in_shared_lm_studio_sync", False)

    def _reconcile_shared_lm_studio_config(self) -> "AppConfig":
        fields_set = builtins.set(self.model_fields_set)
        self.LM_STUDIO_TRANSPORT = _normalize_lm_studio_transport(self.LM_STUDIO_TRANSPORT)

        extracted_base = _extract_lm_studio_base_url(self.COPILOT_ENDPOINT)
        if self.LM_STUDIO_BASE_URL:
            self.LM_STUDIO_BASE_URL = _normalize_lm_studio_base_url(self.LM_STUDIO_BASE_URL)
        elif extracted_base:
            self.LM_STUDIO_BASE_URL = extracted_base

        if not self.COPILOT_ENDPOINT and self.LM_STUDIO_BASE_URL:
            self.COPILOT_ENDPOINT = _build_lm_studio_endpoint(
                self.LM_STUDIO_BASE_URL,
                self.LM_STUDIO_TRANSPORT,
            )

        if "COPILOT_API_KEY" not in fields_set and self.LM_STUDIO_API_KEY:
            self.COPILOT_API_KEY = self.LM_STUDIO_API_KEY
        if "LM_STUDIO_API_KEY" not in fields_set and self.COPILOT_API_KEY:
            self.LM_STUDIO_API_KEY = self.COPILOT_API_KEY

        if "COPILOT_MODEL" not in fields_set and self.LM_STUDIO_MODEL:
            self.COPILOT_MODEL = self.LM_STUDIO_MODEL
        if "LM_STUDIO_MODEL" not in fields_set and self.COPILOT_MODEL:
            self.LM_STUDIO_MODEL = self.COPILOT_MODEL

        if "COPILOT_TIMEOUT" not in fields_set and self.LM_STUDIO_TIMEOUT is not None:
            self.COPILOT_TIMEOUT = self.LM_STUDIO_TIMEOUT
        if "LM_STUDIO_TIMEOUT" not in fields_set:
            self.LM_STUDIO_TIMEOUT = self.COPILOT_TIMEOUT

        return self

    # validate_assignment=True runs field validators on every assignment, so
    # config.set('DRY_RUN', 'false') stores False rather than a truthy string.
    # The shared endpoint validator is idempotent and derives fields from
    # model_fields_set, so repeated assignments preserve normalized values.
    model_config = SettingsConfigDict(
        env_prefix="", extra="allow", validate_assignment=True
    )

    @field_validator("CANDYCONC_SECURITY_MODE", mode="before")
    @classmethod
    def _normalize_security_mode(cls, value: str | None) -> str:
        # Mirror candyconc.services.backend.auth._SECURITY_MODE_ALIASES exactly:
        # known aliases canonicalize to release / local_dev_unsafe, but an
        # UNKNOWN value is passed through normalized (lower/underscore) rather
        # than raising. auth.security_mode() then maps that unknown to "neither
        # release nor unsafe" — the documented fail-safe (auth.py:33-37). This
        # also makes the validator safe under validate_assignment=True: a runtime
        # config.set('CANDYCONC_SECURITY_MODE', '<unknown>') normalizes instead
        # of throwing, preserving the prior config.set semantics.
        raw = (value or "local_dev_unsafe").strip().lower().replace("-", "_")
        aliases = {
            "dev": "local_dev_unsafe",
            "local": "local_dev_unsafe",
            "local_dev": "local_dev_unsafe",
            "unsafe": "local_dev_unsafe",
            "local_dev_unsafe": "local_dev_unsafe",
            "release": "release",
            "production": "release",
            "prod": "release",
        }
        return aliases.get(raw, raw or "local_dev_unsafe")

    @property
    def copilot_configured(self) -> bool:
        """True when a model endpoint for the copilot is set.

        The copilot is optional. Without an endpoint every other function runs
        and the chat answers that no language model is configured.
        """
        return bool(self.COPILOT_ENDPOINT)

    def validate(self) -> None:  # type: ignore[override]  # pragma: no cover - simple check
        missing = []
        if not self.CANDYCONC_EMB_BACKEND:
            missing.append("CANDYCONC_EMB_BACKEND")
        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(
                f"Missing required configuration value{'s' if len(missing) > 1 else ''}: {joined}. "
                "Set it in the environment or in the configuration file before starting the application."
            )

        # Guard against misconfigured endpoints. Users sometimes set
        # ``COPILOT_ENDPOINT`` to a backend route or vice versa which leads to
        # confusing errors like ``GET /v1/chat/completions``.  Ensure the two
        # settings do not overlap and point to distinct services.
        from urllib.parse import urlparse

        if self.COPILOT_ENDPOINT:
            cp = urlparse(self.COPILOT_ENDPOINT)
            pfad = cp.path.rstrip("/")
            # Die Heuristik fing jeden Pfad mit /api/v1 ab, weil CandyConcs
            # eigenes Backend so beginnt. OpenRouter und andere
            # OpenAI-kompatible Anbieter benutzen denselben Praefix
            # (https://openrouter.ai/api/v1/chat/completions), und damit war
            # ein zweiter Modellweg allein an dieser Zeile unmoeglich.
            # Ein Pfad, der auf /chat/completions endet, ist per Definition
            # ein Modellendpunkt und keine Backend-Route. Die eigentliche
            # Verwechslung, das Zeigen auf den eigenen Server, faengt die
            # Host-Pruefung weiter unten praezise ab.
            if (
                "/api/v1" in cp.path
                and not pfad.endswith("/api/v1/chat")
                and not pfad.endswith("/chat/completions")
            ):
                raise RuntimeError(
                    "COPILOT_ENDPOINT must point to your /v1/chat/completions endpoint "
                    "or /api/v1/chat, not a backend URL."
                )

        backend = urlparse(self.CANDYCONC_BACKEND_URL)
        if "/v1/chat/completions" in backend.path:
            raise RuntimeError(
                "CANDYCONC_BACKEND_URL must be the FastAPI backend base URL, not the LLM endpoint."
            )

        if self.COPILOT_ENDPOINT:
            cp = urlparse(self.COPILOT_ENDPOINT)
            if cp.netloc == backend.netloc:
                raise RuntimeError(
                    "COPILOT_ENDPOINT and CANDYCONC_BACKEND_URL point to the same host; they must differ."
                )


def _default_to_env_value(value: Any) -> str | None:
    """Render a pyproject default as an environment-variable string.

    ``None`` defaults are skipped (the caller drops them) so that an absent
    pyproject value never masks a real environment override. Booleans use the
    canonical ``true``/``false`` spelling that pydantic-settings parses.
    """

    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def load_settings() -> AppConfig:
    """Construct :class:`AppConfig` with single-source precedence.

    Precedence, highest wins:

    1. :func:`set` calls during execution (mutate ``APP_CONFIG`` + ``os.environ``)
    2. constructor ``init`` kwargs (none are passed here)
    3. environment variables
    4. the user configuration file (``CANDYCONC_CONFIG_FILE`` or
       ``config.toml`` in the platform configuration directory)
    5. ``[tool.candyconc]`` in the ``pyproject.toml`` of a source checkout
    6. field defaults declared on :class:`AppConfig`

    File values are injected by seeding ``os.environ`` *only* for keys that
    are otherwise absent, then ``AppConfig()`` is built with no init kwargs.
    Passing them as kwargs would make them outrank the environment (init > env
    in pydantic-settings). Seeding also reaches the modules that read
    ``os.environ`` directly.
    """

    for layer in (_load_user_config(), _load_defaults()):
        for key, raw in layer.items():
            if key in os.environ:
                # A real environment override (or a higher layer) already
                # set the key -> never clobber it.
                continue
            rendered = _default_to_env_value(raw)
            if rendered is None:
                continue
            os.environ[key] = rendered
    return AppConfig()


APP_CONFIG = load_settings()



def get(key: str, default: str | None = None) -> str | None:
    if key in AppConfig.model_fields:
        value = getattr(APP_CONFIG, key)
        if isinstance(value, bool):
            return "1" if value else "0"
        return str(value) if value is not None else default
    return default


def set(key: str, value: str) -> None:
    setattr(APP_CONFIG, key, value)
    # Write-through so call-time ``os.environ`` consumers and freshly
    # constructed ``AppConfig`` instances observe the same value. This is the
    # ONLY place in ``src/`` that may write a model-field name into
    # ``os.environ`` (enforced by tests/unit/test_config_single_source.py).
    if key in AppConfig.model_fields:
        if value is None:
            os.environ.pop(key, None)
        elif isinstance(value, bool):
            os.environ[key] = "true" if value else "false"
        else:
            os.environ[key] = str(value)
