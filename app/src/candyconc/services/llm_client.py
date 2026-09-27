from __future__ import annotations

import logging
import asyncio
import weakref
import json
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Sequence

from candyconc.logging_config import init_logging

import httpx
from urllib.parse import urlparse, urlunparse
from fastapi import HTTPException

from candyconc.config import APP_CONFIG, get as get_config
from candyconc.i18n import lt
from candyconc.candyconc_copilot.policy_engine import PolicyEngine

from candyconc.tooling.registry import get_tools

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504, 529}
_MAX_RETRIES = 3
_CONTEXT_WINDOW_HINTS = (
    "prompt",
    "context",
    "token",
    "too long",
    "maximum context",
    "context_length_exceeded",
    "max context",
)
_MAX_OUTPUT_HINTS = (
    "max_output_tokens",
    "maximum output tokens",
    "output token limit",
    "completion length",
    "completion_tokens",
)
_TRANSIENT_LM_STUDIO_HINTS = (
    "lm link connection entered error state",
    "lm link connection closed",
    # A shared machine switches models, and LM Studio reports that as HTTP
    # 400 "LM Link route changed from ... to ...". Classified as bad_request,
    # it ended 41 turns in one measurement series.
    "lm link route changed",
    "connector is closed",
    "peer_keepalive_timeout",
)
#: Nach einem Neuladen kennt der Endpunkt eine previous_response_id nicht
#: mehr. Der Client darf denselben Payload nicht wiederholen; der
#: Orchestrator vergisst die Fortsetzung und baut die Anfrage flach neu.
_STALE_CONTINUATION_HINTS = (
    "previous_response_id",
    "previous response",
)
_ENGINE_UNAVAILABLE_HINTS = (
    "engine protocol predict",
    "engine protocol runtime",
    "channel error",
)
_LM_STUDIO_MODEL_CACHE: Dict[str, tuple[float, frozenset[str]]] = {}
_LM_STUDIO_LAST_CONFIRMED_MODELS: Dict[str, frozenset[str]] = {}


class LLMErrorKind:
    AUTH_FAILED = "auth_failed"
    BAD_REQUEST = "bad_request"
    CAPABILITY_MISMATCH = "capability_mismatch"
    CONTEXT_WINDOW_EXCEEDED = "context_window_exceeded"
    ENDPOINT_NOT_FOUND = "endpoint_not_found"
    ENGINE_UNAVAILABLE = "engine_unavailable"
    STALE_CONTINUATION = "stale_continuation"
    INVALID_RESPONSE = "invalid_response"
    MAX_OUTPUT_TOKENS = "max_output_tokens"
    MEDIA_UNSUPPORTED = "media_unsupported"
    MODEL_NOT_LOADED = "model_not_loaded"
    NOT_CONFIGURED = "copilot_not_configured"
    OVERLOADED = "overloaded"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class LLMRequestError(Exception):
    kind: str
    message: str
    retryable: bool = False
    status_code: int | None = None
    endpoint: str | None = None
    retry_after: float | None = None
    body: str | None = None
    model: str | None = None
    route: str | None = None
    original: Exception | None = None
    response_started: bool = False

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)


@dataclass(frozen=True, slots=True)
class _LLMRoute:
    endpoint: str
    model: str
    structured_mode: str = "off"
    strip_media: bool = False
    reason: str = ""


def _describe_route(route: _LLMRoute) -> str:
    parts = [_route_endpoint_kind(route.endpoint), route.structured_mode]
    if route.strip_media:
        parts.append("strip_media")
    return ":".join(part for part in parts if part)


def _bind_route_error(route: _LLMRoute, error: LLMRequestError) -> LLMRequestError:
    if error.endpoint is None:
        error.endpoint = route.endpoint
    if error.model is None:
        error.model = route.model
    if error.route is None:
        error.route = _describe_route(route)
    return error


def _get_llm_headers() -> Dict[str, str] | None:
    api_key = get_config("COPILOT_API_KEY")
    if not api_key:
        return None
    return {"Authorization": f"Bearer {api_key}"}


# Reuse one HTTP client per event loop to preserve pooled connections.
# Clients bind to their loop, so process-wide reuse would retain closed
# loops in tests. Weak keys avoid keeping completed loops alive.
_HTTP_CLIENTS: "weakref.WeakKeyDictionary[Any, httpx.AsyncClient]" = (
    weakref.WeakKeyDictionary()
)


def _shared_http_client() -> httpx.AsyncClient:
    """Der wiederverwendete Client des laufenden Event-Loops."""
    loop = asyncio.get_running_loop()
    client = _HTTP_CLIENTS.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_keepalive_connections=8,
                max_connections=16,
                # Keep pooled connections through the interval between long model calls.
                # The 300-second expiry covers an observed roughly 200-second interval
                # while limiting reuse of connections that the peer may already have
                # closed. Peer keepalive failures remain retryable transport errors.
                keepalive_expiry=300.0,
            )
        )
        _HTTP_CLIENTS[loop] = client
    return client


async def aclose_http_clients() -> None:
    """Alle offenen Clients schliessen (Shutdown, Testaufraeumen)."""
    for client in list(_HTTP_CLIENTS.values()):
        if not client.is_closed:
            try:
                await client.aclose()
            except Exception:  # pragma: no cover - Abbau darf nie werfen
                pass
    _HTTP_CLIENTS.clear()


def _get_llm_timeout(*, extra_seconds: float = 0.0) -> float | None:
    raw_timeout = getattr(APP_CONFIG, "COPILOT_TIMEOUT", None)
    if raw_timeout is None:
        raw_timeout = get_config("COPILOT_TIMEOUT", "30") or "30"
    raw_normalized = str(raw_timeout).strip().lower()
    if raw_normalized in {"0", "0.0", "none", "off", "false", "disable", "disabled", "inf", "infinite"}:
        return None
    try:
        base_timeout = float(raw_timeout)
    except (TypeError, ValueError):
        base_timeout = 30.0
    if base_timeout <= 0:
        return None
    return _unter_dem_turnbudget(max(1.0, base_timeout + extra_seconds))


#: What still has to happen in the turn AFTER the last model call: wrap-up
#: call, fact extraction, synthesis, polish. Without this reserve the verifier
#: was skipped for lack of time in thirteen turns, and the time window explains
#: it without further assumption (wrap-up at 66 s, the verifier gate closes at
#: 84 s). The VALUE is provisional and belongs to the latency profile. The
#: BOUND is not: a single call must not outlive the turn.
_TURNENDE_RESERVE_SEC = 20.0


def _unter_dem_turnbudget(timeout: float) -> float:
    """Ein Call-Timeout, das kleiner ist als das Budget des ganzen Turns.

    Ausgeliefert war ``COPILOT_TIMEOUT = 120`` bei einem Turn-Budget von
    ebenfalls 120 Sekunden (``copilot_helpers._COPILOT_MAX_TIME_SEC_DEFAULT``),
    bei Schema-Aufrufen plus zehn Sekunden. Ein zaeher Call konnte den Turn
    also nicht nur ausfuellen, sondern ueberdauern. Dann feuert nicht der
    Call-Timeout mit Retry und Wrap-up, sondern der harte Turn-Abbruch, und
    der Nutzer bekommt gar keine Antwort statt einer knappen.

    Das ist keine Tuning-Entscheidung, sondern das Streichen eines Zustands,
    den es nicht geben darf.
    """
    try:
        from candyconc.services.backend.copilot_helpers import _copilot_max_time_sec

        roh = _copilot_max_time_sec()
    except Exception:  # pragma: no cover - ohne Backend gilt der Rohwert
        return timeout
    # An unlimited turn has no end-of-turn reserve to subtract.
    if roh is None:
        return timeout
    budget = float(roh)
    if budget <= 0:
        return timeout
    obergrenze = max(1.0, budget - _TURNENDE_RESERVE_SEC)
    return min(timeout, obergrenze)


def _get_max_output_tokens() -> int | None:
    # Nutzervorgabe, mehrfach ausgesprochen und repo-weit bindend: KEIN
    # Ausgabe-Budget auf LLM-Calls. Reasoning-Modelle liefern unter einem
    # Deckel leeren Content, weil das Budget im Reasoning aufgeht und fuer
    # die Antwort nichts bleibt. Der Ausschalter (Wert <= 0 -> None, kein
    # Feld im Payload) war seit jeher da, nur nutzte ihn der Default nicht:
    # er stand auf 16384 und hing damit an JEDEM Aufruf. Wer bewusst
    # deckeln will, setzt COPILOT_MAX_OUTPUT_TOKENS ausdruecklich.
    raw = get_config("COPILOT_MAX_OUTPUT_TOKENS", "0")
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        return None
    return max(512, min(value, 262_144))


def _thinking_mode_suffix() -> str:
    """Apply the explicit Qwen3 thinking-mode suffix to the last user message.

Appending /no_think or /think preserves the stable prompt prefix. Leave
messages unchanged unless the user configured the switch."""
    raw = str(get_config("COPILOT_THINKING_MODE") or "").strip().casefold()
    if raw == "off":
        return " /no_think"
    if raw == "on":
        return " /think"
    return ""


def _apply_reasoning_steering(
    messages: List[Dict[str, Any]], model: str
) -> List[Dict[str, Any]]:
    """Apply explicit Qwen reasoning steering through the template text.

Append the configured steering line to the system message so the stable
prefix remains intact. This applies only to Qwen models with a configured
COPILOT_REASONING_EFFORT, since this GGUF rejects custom reasoning fields."""
    effort = _get_reasoning_effort()
    if effort is None or "qwen" not in str(model or "").casefold():
        return messages
    # Offizieller Template-Wortlaut (Qwen/Qwen3.8-27B chat_template.jinja):
    # low/xhigh injizieren exakt diese Saetze, medium injiziert NICHTS.
    # Das Template kennt low/medium/xhigh. "high" wird auf den
    # xhigh-Wortlaut abgebildet, "medium" bleibt bewusst leer.
    if effort == "medium":
        return messages
    if effort == "low":
        zeile = (
            "Reasoning effort is set to low. Keep thinking brief and "
            "focused and move directly to the conclusion."
        )
    else:
        zeile = (
            "Reasoning effort is set to xhigh. Think carefully, validate "
            "assumptions, consider alternatives, prioritize correctness."
        )
    out = [dict(m) for m in messages]
    for m in out:
        if m.get("role") == "system" and isinstance(m.get("content"), str):
            if zeile not in m["content"]:
                m["content"] = m["content"].rstrip() + "\n\n" + zeile
            return out
    return [{"role": "system", "content": zeile}] + out


def _apply_thinking_mode(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    suffix = _thinking_mode_suffix()
    if not suffix or not messages:
        return messages
    out = [dict(m) for m in messages]
    for m in reversed(out):
        if m.get("role") != "user" or not isinstance(m.get("content"), str):
            continue
        # Eine umgeschriebene System-Nachricht ist keine Nutzerfrage — der
        # Soft-Switch gehoert an die echte letzte Frage.
        if m["content"].startswith(_SYSTEM_NOTE_MARKER):
            continue
        if not m["content"].rstrip().endswith(suffix.strip()):
            m["content"] = m["content"] + suffix
        break
    return out


def _get_reasoning_effort() -> str | None:
    raw = get_config("COPILOT_REASONING_EFFORT")
    normalized = str(raw or "").strip().casefold()
    return (
        normalized if normalized in {"low", "medium", "high", "xhigh"} else None
    )


def _split_csv(value: str | None) -> List[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _dedupe_preserve_order(values: Sequence[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


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


def _extract_lm_studio_base_url(endpoint: str | None) -> str | None:
    if not endpoint:
        return None
    try:
        path = urlparse(endpoint).path.rstrip("/")
    except Exception:
        return None
    if not (
        path.endswith("/v1/chat/completions")
        or path.endswith("/chat/completions")
        or path.endswith("/v1/responses")
        or path.endswith("/responses")
        or path.endswith("/v1/models")
        or path.endswith("/models")
    ):
        return None
    return _normalize_lm_studio_base_url(endpoint)


def _build_lm_studio_endpoint(base_url: str, transport: str) -> str:
    normalized_base = _normalize_lm_studio_base_url(base_url)
    if not normalized_base:
        raise RuntimeError("LM_STUDIO_BASE_URL is not configured")
    if transport == "responses":
        return f"{normalized_base.rstrip('/')}/responses"
    return f"{normalized_base.rstrip('/')}/chat/completions"


def _config_bool(key: str, default: bool = False) -> bool:
    raw = get_config(key)
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _is_local_lm_studio_endpoint(endpoint: str) -> bool:
    base = _extract_lm_studio_base_url(endpoint)
    if not base:
        return False
    try:
        host = (urlparse(base).hostname or "").lower()
    except Exception:
        return False
    return host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _models_endpoint_for_route(endpoint: str) -> str | None:
    base = _extract_lm_studio_base_url(endpoint)
    if not base:
        return None
    return f"{base.rstrip('/')}/models"


def _loaded_models_from_payload(payload: Any) -> frozenset[str]:
    if isinstance(payload, dict):
        items = payload.get("data")
    else:
        items = payload
    models: set[str] = set()
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                model_id = item.get("id") or item.get("model") or item.get("name")
            else:
                model_id = item
            if model_id:
                models.add(str(model_id))
    return frozenset(models)


def _get_model_preflight_timeout(generation_timeout: float | None) -> float | None:
    try:
        configured = float(
            get_config("CANDYCONC_LM_STUDIO_MODEL_PREFLIGHT_TIMEOUT_SEC", "2") or "2"
        )
    except (TypeError, ValueError):
        configured = 2.0
    if configured <= 0:
        return None
    if generation_timeout is None:
        return configured
    return max(0.25, min(float(generation_timeout), configured))


def _preflight_probe_delay(attempt: int) -> float:
    """Abstand zwischen zwei Preflight-Sondierungen, gestaffelt.

    0,5 / 1 / 2 / 4 ... bis 60 Sekunden. Die ersten Sondierungen kommen
    schnell, weil das Modell in allen drei gemessenen Vorfaellen binnen
    Sekunden bis rund 150 Sekunden zurueck war. Danach waechst der Abstand,
    damit eine lange Wartezeit nicht als Dauerlebenszeichen im Log steht.
    """

    return min(60.0, 0.5 * (2 ** max(0, int(attempt) - 1)))


def _get_model_reappearance_grace(
    generation_timeout: float | None,
) -> float | None:
    raw = get_config("CANDYCONC_LM_STUDIO_MODEL_REAPPEAR_GRACE_SEC")
    if raw in (None, ""):
        return generation_timeout
    normalized = str(raw).strip().lower()
    if normalized in {
        "0",
        "0.0",
        "none",
        "off",
        "false",
        "disable",
        "disabled",
        "inf",
        "infinite",
    }:
        return None
    try:
        configured = float(raw)
    except (TypeError, ValueError):
        return generation_timeout
    return None if configured <= 0 else configured


async def _lm_studio_loaded_models(
    endpoint: str,
    *,
    timeout: float | None,
    headers: Dict[str, str] | None,
) -> frozenset[str]:
    models_endpoint = _models_endpoint_for_route(endpoint)
    if not models_endpoint:
        return frozenset()

    # The preflight cache is disabled by default so a model change on a
    # shared endpoint remains visible. An exclusive endpoint can configure
    # a positive TTL. _pruefe_antwortmodell also validates each response.
    try:
        ttl = float(get_config("CANDYCONC_LM_STUDIO_MODEL_PREFLIGHT_TTL_SEC", "0") or "0")
    except (TypeError, ValueError):
        ttl = 10.0
    now = time.monotonic()
    cached = _LM_STUDIO_MODEL_CACHE.get(models_endpoint)
    if cached is not None and ttl > 0 and now - cached[0] <= ttl:
        return cached[1]

    try:
        client = _shared_http_client()
        resp = await client.get(models_endpoint, timeout=timeout, headers=headers)
        resp.raise_for_status()
        payload = resp.json()
        loaded = _loaded_models_from_payload(payload)
        try:
            for entry in payload.get("data", []) or []:
                if isinstance(entry, dict) and entry.get("state") == "loaded":
                    ctx = int(entry.get("loaded_context_length") or 0)
                    if ctx > 0:
                        _LOADED_CONTEXT_BY_MODEL[str(entry.get("id") or "")] = ctx
        except (TypeError, ValueError, AttributeError):
            pass
    except httpx.HTTPStatusError as exc:
        raise _classify_http_error(models_endpoint, exc)
    except ValueError as exc:
        raise _invalid_response_error(
            models_endpoint,
            exc,
            detail=lt(
                "Der LM-Studio /models-Endpunkt hat ungültiges JSON geliefert.",
                "The LM Studio /models endpoint returned invalid JSON.",
            ),
        )
    except Exception as exc:
        raise _classify_transport_error(models_endpoint, exc)

    _LM_STUDIO_MODEL_CACHE[models_endpoint] = (now, loaded)
    if loaded:
        _LM_STUDIO_LAST_CONFIRMED_MODELS[models_endpoint] = loaded
    return loaded


async def _ensure_lm_studio_model_loaded(
    route: _LLMRoute,
    *,
    timeout: float | None,
    headers: Dict[str, str] | None,
) -> None:
    if not _config_bool("CANDYCONC_LM_STUDIO_REQUIRE_LOADED_MODEL", True):
        return
    if not _is_local_lm_studio_endpoint(route.endpoint):
        return

    preflight_timeout = _get_model_preflight_timeout(timeout)
    models_endpoint = _models_endpoint_for_route(route.endpoint)
    previously_confirmed = bool(
        models_endpoint
        and route.model
        in _LM_STUDIO_LAST_CONFIRMED_MODELS.get(
            models_endpoint,
            frozenset(),
        )
    )
    reappearance_grace = _get_model_reappearance_grace(timeout)
    started_waiting = time.monotonic()
    attempt = 0
    loaded = frozenset()
    while True:
        attempt += 1
        loaded = await _lm_studio_loaded_models(
            route.endpoint,
            timeout=preflight_timeout,
            headers=headers,
        )
        if route.model in loaded:
            return
        # Do not stop on the FIRST probe just because LM Studio reports some
        # other model. LM Studio can hold several models and unload ours for
        # a while, so the list is not empty while our model is missing. The
        # neighbouring branch (empty list) waits anyway. In three observed
        # cases the model was back within seconds to about 150 seconds, and
        # the next turn's preflight found it. A grace period would have saved
        # all three turns, which lost 40 minutes of collected evidence and
        # delivered 3,605 instead of 15,156 characters.
        #
        # The loop waits ONLY when three conditions hold at once: the model
        # has already answered in this run, there is a FINITE grace period,
        # and it has not expired yet. Everything else stops immediately.
        #
        # The grace period must be finite. With ``timeout=None``
        # ``reappearance_grace`` is None, and then neither
        # ``not previously_confirmed`` nor ``grace_exhausted`` is ever true,
        # so an unconditional wait would loop FOREVER.
        # test_confirmed_model_never_switches_to_another_loaded_model pins
        # this case. A typo or a renamed model must still fail with a message
        # instead of hanging silently.
        nachfrist_greift = bool(
            previously_confirmed
            and reappearance_grace is not None
            and (time.monotonic() - started_waiting) < reappearance_grace
        )
        if loaded and not nachfrist_greift:
            break
        initial_probe_budget_exhausted = attempt >= 3
        grace_exhausted = bool(
            previously_confirmed
            and reappearance_grace is not None
            and time.monotonic() - started_waiting
            >= reappearance_grace
        )
        if (
            (not previously_confirmed and initial_probe_budget_exhausted)
            or grace_exhausted
        ):
            break
        lage = (
            "returned an empty loaded-model list"
            if not loaded
            else "lists other models but not ours"
        )
        if attempt <= 3 or attempt % 30 == 0:
            if previously_confirmed:
                logger.warning(
                    "LM Studio /v1/models %s. Waiting for previously "
                    "confirmed model '%s' without loading or switching "
                    "models (probe %s)",
                    lage,
                    route.model,
                    attempt,
                )
            else:
                logger.warning(
                    "LM Studio /v1/models %s. Retrying initial preflight "
                    "without loading a model (probe %s/3)",
                    lage,
                    attempt,
                )
        if models_endpoint:
            _LM_STUDIO_MODEL_CACHE.pop(models_endpoint, None)
        # Gestaffelter Abstand statt fester 0,5 bis 1,0 Sekunden. Zwei
        # Gruende, und der zweite wiegt schwerer als Hoeflichkeit gegenueber
        # LM Studio: jede Sondierung erzeugt eine httpx-INFO-Zeile, und wer
        # im Sekundentakt sondiert, erzeugt ein Dauerlebenszeichen, an dem
        # eine tote Bruecke nicht mehr von einer wartenden zu unterscheiden
        # ist. Frueh schnell (das Modell war dreimal binnen Sekunden zurueck),
        # spaeter selten.
        await asyncio.sleep(_preflight_probe_delay(attempt))
    if not loaded:
        raise LLMRequestError(
            kind=LLMErrorKind.MODEL_NOT_LOADED,
            message=(
                "LM Studio model preflight failed: /v1/models returned no loaded "
                "models. No model load was attempted."
            ),
            endpoint=route.endpoint,
            model=route.model,
        )
    raise LLMRequestError(
        kind=LLMErrorKind.MODEL_NOT_LOADED,
        message=(
            f"LM Studio model preflight failed: model '{route.model}' is not "
            "currently loaded. No model load was attempted."
        ),
        endpoint=route.endpoint,
        model=route.model,
    )


async def _wait_for_same_model_after_lm_link_disconnect(
    endpoint: str,
    payload: Dict[str, Any],
    *,
    timeout: float | None,
    headers: Dict[str, str] | None,
) -> None:
    """Wait for the requested local model before retrying a closed LM Link."""

    model = str(payload.get("model") or "").strip()
    if not model or not _is_local_lm_studio_endpoint(endpoint):
        return
    await _ensure_lm_studio_model_loaded(
        _LLMRoute(endpoint=endpoint, model=model),
        timeout=timeout,
        headers=headers,
    )


async def warte_auf_modell(
    endpoint: str,
    model: str,
    *,
    timeout: float | None,
    headers: Dict[str, str] | None = None,
) -> bool:
    """Wait until ``model`` is loaded again at the LM Studio endpoint.

    For the orchestrator after a model disruption in the middle of a turn.
    Loads and switches nothing. ``timeout`` is the grace period. ``None``
    means no upper bound, for long measurement runs where an aborted run
    costs more than a waiting one. Returns False if the model did not come
    back within the grace period or was never confirmed.
    """
    if not endpoint or not model:
        return False
    frist = None if timeout is None else time.monotonic() + max(0.0, float(timeout))
    while True:
        rest = None if frist is None else max(0.0, frist - time.monotonic())
        try:
            await _ensure_lm_studio_model_loaded(
                _LLMRoute(endpoint=endpoint, model=model),
                timeout=rest,
                headers=headers,
            )
            return True
        except LLMRequestError as exc:
            # Endpunkt antwortet, Modell fehlt: die Nachfrist im Preflight ist
            # verbraucht, weiter warten hilft nicht.
            if exc.kind == LLMErrorKind.MODEL_NOT_LOADED:
                return False
            # Endpunkt selbst nicht erreichbar (LM Studio startet neu, Link
            # tot): in Abstaenden neu sondieren, bis die Nachfrist um ist.
            if frist is not None and time.monotonic() >= frist:
                return False
            await asyncio.sleep(_WARTE_AUF_ENDPUNKT_SEKUNDEN)


#: Abstand der Sondierungen, solange der Endpunkt selbst nicht antwortet.
_WARTE_AUF_ENDPUNKT_SEKUNDEN = 30.0


#: Trennzeichen, mit denen LM Studio und verwandte Server denselben
#: Modellnamen qualifizieren ("name@q4", "org/name", "name:tag").
_MODELL_QUALIFIER = ("@", "/", ":")


def _modelle_sind_dasselbe(angefordert: str, geantwortet: str) -> bool:
    a = str(angefordert or "").strip().casefold()
    g = str(geantwortet or "").strip().casefold()
    if not a or not g:
        return True  # ohne Angabe laesst sich nichts widerlegen
    if a == g:
        return True
    for kurz, lang in ((a, g), (g, a)):
        if lang.startswith(kurz) and lang[len(kurz):][:1] in _MODELL_QUALIFIER:
            return True
    return False


def _pruefe_antwortmodell(
    endpoint: str, payload: Dict[str, Any], daten: Any
) -> None:
    """Reject responses generated by a model other than the requested model.

A server can silently substitute a loaded model while returning no error.
Validate the response model at each answer boundary so such substitution
cannot be recorded as a response from the requested model."""
    if not isinstance(daten, dict):
        return
    angefordert = str(payload.get("model") or "").strip()
    geantwortet = str(daten.get("model") or "").strip()
    if _modelle_sind_dasselbe(angefordert, geantwortet):
        return
    raise LLMRequestError(
        kind=LLMErrorKind.INVALID_RESPONSE,
        message=lt(
            "Der Endpunkt hat {answered!r} geantwortet, angefordert war "
            "{requested!r}. Eine stille Modellsubstitution macht jede "
            "Messung wertlos. Lade das angeforderte Modell oder setze "
            "COPILOT_MODEL auf das geladene.",
            "The endpoint answered with {answered!r}, but {requested!r} was "
            "requested. A silent model substitution makes every measurement "
            "worthless. Load the requested model or set COPILOT_MODEL to the "
            "loaded one.",
        ).format(answered=geantwortet, requested=angefordert),
        endpoint=endpoint,
    )


def _route_endpoint_kind(endpoint: str) -> str:
    if _is_responses_api(endpoint):
        return "responses"
    if _is_custom_chat_endpoint(endpoint):
        return "custom"
    return "chat_completions"


def _content_contains_media(content: Any) -> bool:
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                item_type = str(item.get("type", "")).lower()
                if item_type and item_type not in {"text", "input_text", "output_text"}:
                    return True
            elif not isinstance(item, str):
                return True
    if isinstance(content, dict):
        item_type = str(content.get("type", "")).lower()
        return bool(item_type and item_type not in {"text", "input_text", "output_text"})
    return False


def _coerce_content_to_text(content: Any, *, strip_media: bool) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                item_type = str(item.get("type", "")).lower()
                if item_type in {"text", "input_text", "output_text"}:
                    text = item.get("text")
                    if text:
                        parts.append(str(text))
                elif not strip_media:
                    parts.append(f"[{item_type or 'content'} omitted]")
                continue
            if not strip_media:
                parts.append(str(item))
        return "\n".join(part for part in parts if part).strip()
    if isinstance(content, dict):
        text = content.get("text")
        if text:
            return str(text)
        if strip_media:
            return ""
        return json.dumps(content, ensure_ascii=False)
    return str(content)


# ChatML roles accepted by OpenAI-compatible endpoints (chat/completions and
# the Responses API). Anything else is rejected on the wire with HTTP 400.
_ALLOWED_MESSAGE_ROLES = frozenset({"system", "user", "assistant", "tool"})


def _sanitize_messages(
    messages: Sequence[Dict[str, Any]],
    *,
    strip_media: bool,
) -> List[Dict[str, Any]]:
    sanitized: List[Dict[str, Any]] = []
    for message in messages:
        item = dict(message)
        # Belt-and-suspenders: OpenAI-compatible endpoints reject any role that
        # is not one of {system, user, assistant, tool} with HTTP 400. Callers
        # occasionally leak a requester identity (e.g. a username like "guest")
        # into the message role; normalize it to "user" rather than letting the
        # whole request fail on the wire. This is the single point every route
        # branch passes through before payload building.
        role = item.get("role")
        if role not in _ALLOWED_MESSAGE_ROLES:
            logger.warning(
                "Non-standard LLM message role %r normalized to 'user'", role
            )
            item["role"] = "user"
        item["content"] = _coerce_content_to_text(item.get("content", ""), strip_media=strip_media)
        sanitized.append(item)
    return sanitized


def _messages_include_media(messages: Sequence[Dict[str, Any]]) -> bool:
    return any(_content_contains_media(message.get("content")) for message in messages)


def _build_schema_hint(json_schema: Dict[str, Any]) -> str:
    return (
        "Gib ausschließlich valides JSON zurück, das diesem JSON-Schema entspricht:\n"
        f"{json.dumps(json_schema, ensure_ascii=False)}"
    )


def _model_candidates(
    base_model: str,
    *,
    tools: Sequence[Dict[str, Any]],
    json_schema: Dict[str, Any] | None,
) -> List[str]:
    configured = [
        get_config("LM_STUDIO_JSON_MODEL") if json_schema is not None else None,
        get_config("LM_STUDIO_TOOL_MODEL") if tools else None,
        base_model,
        get_config("LM_STUDIO_LARGE_CONTEXT_MODEL"),
        *_split_csv(get_config("LM_STUDIO_FALLBACK_MODELS")),
    ]
    return _dedupe_preserve_order([value for value in configured if value])


def _build_route_candidates(
    endpoint: str,
    model: str,
    messages: Sequence[Dict[str, Any]],
    *,
    tools: Sequence[Dict[str, Any]],
    json_schema: Dict[str, Any] | None,
) -> List[_LLMRoute]:
    routes: List[_LLMRoute] = []
    lm_base = _extract_lm_studio_base_url(endpoint)
    transports: List[str] = [endpoint]
    if lm_base:
        endpoint_kind = _route_endpoint_kind(endpoint)
        preferred_transport = get_config("LM_STUDIO_TRANSPORT", "chat_completions") or "chat_completions"
        if preferred_transport == "auto":
            if tools:
                transports.extend(
                    [
                        _build_lm_studio_endpoint(lm_base, "responses"),
                        _build_lm_studio_endpoint(lm_base, "chat_completions"),
                    ]
                )
            else:
                transports.extend(
                    [
                        _build_lm_studio_endpoint(lm_base, "chat_completions"),
                        _build_lm_studio_endpoint(lm_base, "responses"),
                    ]
                )
        elif preferred_transport == "responses" or endpoint_kind == "responses":
            transports.append(_build_lm_studio_endpoint(lm_base, "chat_completions"))
        else:
            transports.append(_build_lm_studio_endpoint(lm_base, "responses"))

    strip_media_needed = _messages_include_media(messages)
    structured_output_enabled = (
        json_schema is not None and get_config("USE_STRUCTURED_OUTPUT") == "1"
    )

    seen: set[tuple[str, str, str, bool]] = set()
    # Keep the explicitly requested model while trying compatible transports
    # before considering any configured model fallback.
    candidate_models = (
        [model]
        if _is_local_lm_studio_endpoint(endpoint)
        else _model_candidates(model, tools=tools, json_schema=json_schema)
    )
    for candidate_model in candidate_models:
        candidate_endpoints = _dedupe_preserve_order(transports)
        endpoint_modes: List[tuple[str, str]] = []
        if json_schema is None:
            endpoint_modes = [
                (candidate_endpoint, "off")
                for candidate_endpoint in candidate_endpoints
            ]
        else:
            # LM Studio documents grammar-constrained JSON schema output on
            # chat completions. Prefer that native contract for structured
            # synthesis even when tool turns use the Responses API; a prompt
            # hint remains the compatibility fallback on every transport.
            if structured_output_enabled:
                endpoint_modes.extend(
                    (candidate_endpoint, "json_schema")
                    for candidate_endpoint in candidate_endpoints
                    if not _is_responses_api(candidate_endpoint)
                )
            endpoint_modes.extend(
                (candidate_endpoint, "prompt_hint")
                for candidate_endpoint in candidate_endpoints
            )
        for candidate_endpoint, structured_mode in endpoint_modes:
            strip_variants = [False, True] if strip_media_needed else [False]
            for strip_media in strip_variants:
                key = (candidate_endpoint, candidate_model, structured_mode, strip_media)
                if key in seen:
                    continue
                seen.add(key)
                is_first_route = not routes
                routes.append(
                    _LLMRoute(
                        endpoint=candidate_endpoint,
                        model=candidate_model,
                        structured_mode=structured_mode,
                        strip_media=strip_media,
                        reason="" if is_first_route else "alternate",
                    )
                )
    return routes


def _log_route_candidate_summary(
    *,
    requested_model: str,
    routes: Sequence[_LLMRoute],
    tools: Sequence[Dict[str, Any]],
    json_schema: Dict[str, Any] | None,
) -> None:
    route_models = _dedupe_preserve_order([route.model for route in routes if getattr(route, "model", "")])
    route_endpoints = _dedupe_preserve_order([route.endpoint for route in routes if getattr(route, "endpoint", "")])
    if not route_models:
        return
    if len(route_models) == 1 and route_models[0] == requested_model:
        return
    logger.warning(
        "LLM route candidates diverge from requested model. requested=%s candidates=%s endpoints=%s tools=%s structured=%s",
        requested_model,
        route_models,
        route_endpoints,
        [str(tool.get("function", {}).get("name", "") or "") for tool in tools if isinstance(tool, dict)],
        bool(json_schema is not None),
    )


def _gleiche_maschine(a: "_LLMRoute", b: "_LLMRoute") -> bool:
    """Zeigen zwei Routen auf denselben Motor mit demselben Modell?"""
    from urllib.parse import urlsplit

    if str(a.model or "").casefold() != str(b.model or "").casefold():
        return False
    return urlsplit(a.endpoint).netloc.casefold() == urlsplit(b.endpoint).netloc.casefold()


def _should_try_alternate_route(
    error: LLMRequestError,
    *,
    aktuelle: "_LLMRoute | None" = None,
    naechste: "_LLMRoute | None" = None,
) -> bool:
    """Lohnt ein Routenwechsel, oder ist er nur noch Zeitverbrennen?

    Ein TIMEOUT auf DEMSELBEN Motor mit DEMSELBEN Modell sagt nichts ueber
    die Form der naechsten Route, sondern nur, dass die Zeit weg ist. Der
    Wechsel kann dort nichts retten: es ist derselbe Prozess, der gerade zu
    langsam generiert hat. Er verbrennt aber das, was vom Turn-Budget uebrig
    ist, und verzoegert damit ausgerechnet die Bergung der Teilantwort.

    Example: after a timeout on ``/v1/chat/completions``, switching to
    ``/v1/responses`` and further while the backstop (max_time 120 + 15)
    was already running left four of ten turns with a 73-character stub
    ("Zeitlimit erreicht, bevor verwertbare Evidenz gesammelt werden
    konnte"), because no tool got its turn at all.

    Bei einem ANDEREN Host oder einem anderen Modell bleibt der Wechsel
    sinnvoll: dort kann die Ursache wirklich an der Route liegen.
    """
    if (
        error.kind == LLMErrorKind.TIMEOUT
        and aktuelle is not None
        and naechste is not None
        and _gleiche_maschine(aktuelle, naechste)
    ):
        return False
    return error.kind in {
        LLMErrorKind.CAPABILITY_MISMATCH,
        LLMErrorKind.CONTEXT_WINDOW_EXCEEDED,
        LLMErrorKind.ENDPOINT_NOT_FOUND,
        LLMErrorKind.INVALID_RESPONSE,
        LLMErrorKind.MAX_OUTPUT_TOKENS,
        LLMErrorKind.MEDIA_UNSUPPORTED,
        LLMErrorKind.OVERLOADED,
        LLMErrorKind.RATE_LIMITED,
        LLMErrorKind.TIMEOUT,
        LLMErrorKind.TRANSPORT,
    }


def _retry_delay(attempt: int, retry_after_header: str | None = None) -> float:
    if retry_after_header:
        try:
            return max(0.25, min(30.0, float(retry_after_header)))
        except ValueError:
            pass
    return min(12.0, 0.75 * (2 ** max(0, attempt - 1)))


def _parse_retry_after_seconds(retry_after_header: str | None) -> float | None:
    if not retry_after_header:
        return None
    try:
        return max(0.0, min(300.0, float(retry_after_header)))
    except (TypeError, ValueError):
        return None


def _fehlertext(exc: Exception) -> str:
    """Type AND text, because httpx transport errors often have no text.

    Without the class name the log shows lines like ``Transient LLM
    transport error from ...: .`` with empty text (eleven such lines in one
    batch of questions). A log that does not show whether the connection
    broke, the protocol failed or a transport time limit hit is useless for
    debugging. The class name costs nothing and decides exactly that.
    """
    name = type(exc).__name__
    text = str(exc).strip()
    return f"{name}: {text}" if text else f"{name} (ohne Meldung)"


def _is_retryable_exception(exc: Exception) -> bool:
    return isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.TimeoutException,
            httpx.ReadError,
            httpx.WriteError,
            httpx.RemoteProtocolError,
            httpx.PoolTimeout,
        ),
    )


def _is_media_error(body_lower: str) -> bool:
    media_tokens = (
        "image",
        "vision",
        "media",
        "multipart",
        "unsupported content",
        "input_image",
        "image_url",
    )
    return any(token in body_lower for token in media_tokens)


def _is_capability_error(body_lower: str) -> bool:
    capability_tokens = (
        "response_format",
        "json_schema",
        "json_object",
        "tool_choice",
        "tools are not supported",
        "tool calling",
        "function calling",
        "tool_calls",
        "unsupported parameter",
    )
    return any(token in body_lower for token in capability_tokens)


# Loaded context lengths from the model preflight. Include these in
# engine-failure diagnostics when the configured window is too small.
_LOADED_CONTEXT_BY_MODEL: Dict[str, int] = {}


def _is_engine_unavailable_error(body_lower: str) -> bool:
    return any(token in body_lower for token in _ENGINE_UNAVAILABLE_HINTS)


def _small_context_hint() -> str:
    """Kontextfenster-Hinweis, wenn ein geladenes Modell < 16k Kontext hat."""
    small = {
        model: ctx
        for model, ctx in _LOADED_CONTEXT_BY_MODEL.items()
        if 0 < ctx < 16384
    }
    if not small:
        return ""
    parts = ", ".join(f"{m}={c}" for m, c in sorted(small.items()))
    return lt(
        " Wahrscheinliche Ursache: zu kleines geladenes Kontextfenster "
        "({parts} Token) — der Turn-Prompt überschreitet es. Modell mit "
        "größerem Kontext laden (Nutzeraktion), CandyConc lädt nichts.",
        " Probable cause: the loaded context window is too small "
        "({parts} tokens), and the turn prompt exceeds it. Load a model with "
        "a larger context (user action). CandyConc loads nothing.",
    ).format(parts=parts)


def _engine_unavailable_error(
    endpoint: str,
    detail: Any,
    *,
    status_code: int | None = None,
    original: Exception | None = None,
) -> LLMRequestError:
    rendered = (
        json.dumps(detail, ensure_ascii=False)
        if isinstance(detail, (dict, list))
        else str(detail or "")
    ).strip()
    # Log the engine response body so failures can be diagnosed.
    logger.warning(
        "Engine-Ausfall an %s (HTTP %s). Antwortkoerper: %s",
        endpoint,
        status_code,
        rendered[:600] or "<leer>",
    )
    return LLMRequestError(
        kind=LLMErrorKind.ENGINE_UNAVAILABLE,
        message=lt(
            "Die Modell-Engine ist während der Generierung ausgefallen oder "
            "nicht mehr erreichbar. CandyConc hat kein Modell geladen oder "
            "gewechselt.",
            "The model engine failed during generation or can no longer be "
            "reached. CandyConc did not load or switch any model.",
        ) + _small_context_hint(),
        retryable=True,
        status_code=status_code,
        endpoint=endpoint,
        body=rendered[:400] or None,
        original=original,
    )


_MAX_OUTPUT_MESSAGE = lt(
    "Der aktuelle LLM-Pfad hat das Ausgabelimit der Anfrage nicht akzeptiert.",
    "The current LLM route did not accept the output limit of the request.",
)
_CONTEXT_WINDOW_MESSAGE = lt(
    "Die Anfrage überschreitet das Kontextfenster des aktuellen Modells.",
    "The request exceeds the context window of the current model.",
)
_CAPABILITY_MESSAGE = lt(
    "Der aktuelle LLM-Pfad oder das Modell unterstützen diese Anfrageform nicht.",
    "The current LLM route or the model does not support this form of request.",
)
_MEDIA_MESSAGE = lt(
    "Der aktuelle LLM-Pfad unterstützt die angefragten Medieninhalte nicht.",
    "The current LLM route does not support the requested media content.",
)


def _stream_fehler_aus_ereignis(
    endpoint: str, event_type: str, detail: Any
) -> LLMRequestError:
    """Ein ``response.failed``/``error``-Ereignis in eine Fehlerart uebersetzen.

    ``LM Link connection entered error state peer_keepalive_timeout`` must
    be recognised as transient here too. Checking only the engine hints
    would raise ``invalid_response`` without retry, while the same message
    as an HTTP error is ``transport`` and retryable. An error kind must not
    depend on whether it arrives as a status or as an event.
    """
    rendered = (
        json.dumps(detail, ensure_ascii=False)
        if isinstance(detail, (dict, list))
        else str(detail or event_type)
    )
    klein = rendered.casefold()
    if _is_engine_unavailable_error(klein):
        return _engine_unavailable_error(endpoint, detail or event_type)

    # Was die ANFRAGE verschuldet, bleibt ohne Wiederholung: derselbe zu
    # lange Kontext, dasselbe nicht unterstuetzte Werkzeugformat erzeugen
    # denselben Fehler. Diese Faelle sind benannt und endlich.
    # Reihenfolge wie in _classify_http_error: das Ausgabelimit zuerst.
    # _CONTEXT_WINDOW_HINTS enthaelt "token" und wuerde sonst jedes
    # "max_output_tokens" als Kontextfenster lesen.
    for treffer, art, text in (
        (_MAX_OUTPUT_HINTS, LLMErrorKind.MAX_OUTPUT_TOKENS, _MAX_OUTPUT_MESSAGE),
        (_CONTEXT_WINDOW_HINTS, LLMErrorKind.CONTEXT_WINDOW_EXCEEDED, _CONTEXT_WINDOW_MESSAGE),
    ):
        if any(token in klein for token in treffer):
            return LLMRequestError(kind=art, message=text, endpoint=endpoint,
                                   body=rendered[:400] or None)
    if _is_capability_error(klein):
        return LLMRequestError(
            kind=LLMErrorKind.CAPABILITY_MISMATCH,
            message=_CAPABILITY_MESSAGE,
            endpoint=endpoint, body=rendered[:400] or None)
    if _is_media_error(klein):
        return LLMRequestError(
            kind=LLMErrorKind.MEDIA_UNSUPPORTED,
            message=_MEDIA_MESSAGE,
            endpoint=endpoint, body=rendered[:400] or None)

    # Retry unknown local LM Studio errors after rejecting known input
    # errors above. The local bridge can fail with varying free-text
    # messages, so a fixed allowlist would miss recoverable failures.
    if _is_local_lm_studio_endpoint(endpoint):
        return LLMRequestError(
            kind=LLMErrorKind.TRANSPORT,
            message=lt(
                "Die Verbindung zwischen LM Studio und dem geladenen Modell "
                "wurde unterbrochen. Derselbe Aufruf wird wiederholt.",
                "The connection between LM Studio and the loaded model was "
                "interrupted. The same call is repeated.",
            ),
            retryable=True,
            endpoint=endpoint,
            body=rendered[:400] or None,
        )
    return _invalid_response_error(
        endpoint,
        ValueError(str(detail or event_type)),
        detail=lt(
            "Der Responses-Stream ist fehlgeschlagen: {detail}",
            "The Responses stream failed: {detail}",
        ).format(detail=detail or event_type),
    )


def _classify_http_error(endpoint: str, exc: httpx.HTTPStatusError) -> LLMRequestError:
    status = exc.response.status_code
    body = (exc.response.text or "").strip()
    body_lower = body.lower()
    retry_after = _parse_retry_after_seconds(exc.response.headers.get("Retry-After"))

    if _is_engine_unavailable_error(body_lower):
        return _engine_unavailable_error(
            endpoint,
            body,
            status_code=status,
            original=exc,
        )

    if status in (400, 404) and any(
        token in body_lower for token in _STALE_CONTINUATION_HINTS
    ):
        return LLMRequestError(
            kind=LLMErrorKind.STALE_CONTINUATION,
            message=lt(
                "Die Fortsetzungskennung ist am Endpunkt nicht mehr bekannt, "
                "das Modell wurde neu geladen. Der Aufruf wird ohne Fortsetzung "
                "aus der Historie wiederholt.",
                "The endpoint no longer knows the continuation ID because the "
                "model was reloaded. The call is repeated from the history "
                "without continuation.",
            ),
            retryable=True,
            status_code=status,
            endpoint=endpoint,
            body=body[:400] if body else None,
            original=exc,
        )

    if any(token in body_lower for token in _TRANSIENT_LM_STUDIO_HINTS):
        return LLMRequestError(
            kind=LLMErrorKind.TRANSPORT,
            message=lt(
                "Die Verbindung zwischen LM Studio und dem geladenen Modell wurde vorübergehend unterbrochen.",
                "The connection between LM Studio and the loaded model was temporarily interrupted.",
            ),
            retryable=True,
            status_code=status,
            endpoint=endpoint,
            retry_after=retry_after,
            body=body[:400] if body else None,
            original=exc,
        )

    if status in (400, 413, 422) and any(
        token in body_lower for token in _MAX_OUTPUT_HINTS
    ):
        return LLMRequestError(
            kind=LLMErrorKind.MAX_OUTPUT_TOKENS,
            message=_MAX_OUTPUT_MESSAGE,
            status_code=status,
            endpoint=endpoint,
            body=body[:400] if body else None,
            original=exc,
        )

    if status in (400, 413, 422, 500, 502, 503, 504) and any(
        token in body_lower for token in _CONTEXT_WINDOW_HINTS
    ):
        return LLMRequestError(
            kind=LLMErrorKind.CONTEXT_WINDOW_EXCEEDED,
            message=_CONTEXT_WINDOW_MESSAGE,
            status_code=status,
            endpoint=endpoint,
            body=body[:400] if body else None,
            original=exc,
        )

    if status in (400, 415, 422) and _is_media_error(body_lower):
        return LLMRequestError(
            kind=LLMErrorKind.MEDIA_UNSUPPORTED,
            message=_MEDIA_MESSAGE,
            status_code=status,
            endpoint=endpoint,
            body=body[:400] if body else None,
            original=exc,
        )

    if status in (400, 404, 415, 422) and _is_capability_error(body_lower):
        return LLMRequestError(
            kind=LLMErrorKind.CAPABILITY_MISMATCH,
            message=_CAPABILITY_MESSAGE,
            status_code=status,
            endpoint=endpoint,
            body=body[:400] if body else None,
            original=exc,
        )

    if status in (401, 403):
        return LLMRequestError(
            kind=LLMErrorKind.AUTH_FAILED,
            message=lt(
                "Der LLM-Endpunkt hat die Anfrage nicht akzeptiert. Prüfe Schlüssel und Berechtigungen.",
                "The LLM endpoint did not accept the request. Check the key and permissions.",
            ),
            status_code=status,
            endpoint=endpoint,
            body=body[:400] if body else None,
            original=exc,
        )

    if status == 404:
        return LLMRequestError(
            kind=LLMErrorKind.ENDPOINT_NOT_FOUND,
            message=lt(
                "Der konfigurierte LLM-Endpunkt wurde nicht gefunden.",
                "The configured LLM endpoint was not found.",
            ),
            status_code=status,
            endpoint=endpoint,
            body=body[:400] if body else None,
            original=exc,
        )

    if status == 429:
        return LLMRequestError(
            kind=LLMErrorKind.RATE_LIMITED,
            message=lt(
                "Der LLM-Endpunkt begrenzt die Anfrage aktuell.",
                "The LLM endpoint is currently rate limiting the request.",
            ),
            retryable=True,
            status_code=status,
            endpoint=endpoint,
            retry_after=retry_after,
            body=body[:400] if body else None,
            original=exc,
        )

    if status == 529 or 500 <= status < 600:
        return LLMRequestError(
            kind=LLMErrorKind.OVERLOADED,
            message=lt(
                "Der LLM-Endpunkt ist aktuell überlastet ({status}).",
                "The LLM endpoint is currently overloaded ({status}).",
            ).format(status=status),
            retryable=True,
            status_code=status,
            endpoint=endpoint,
            retry_after=retry_after,
            body=body[:400] if body else None,
            original=exc,
        )

    # Retry unknown local LM Studio bridge or model failures. Known input
    # errors above remain non-retryable. Remote endpoints keep their
    # stricter classification.
    if _is_local_lm_studio_endpoint(endpoint):
        return LLMRequestError(
            kind=LLMErrorKind.TRANSPORT,
            message=lt(
                "Die Verbindung zwischen LM Studio und dem geladenen Modell "
                "wurde unterbrochen (HTTP {status}). Derselbe Aufruf wird "
                "wiederholt.",
                "The connection between LM Studio and the loaded model was "
                "interrupted (HTTP {status}). The same call is repeated.",
            ).format(status=status),
            retryable=True,
            status_code=status,
            endpoint=endpoint,
            body=body[:400] if body else None,
            original=exc,
        )
    return LLMRequestError(
        kind=LLMErrorKind.BAD_REQUEST,
        message=lt("LLM HTTP {status}: {body}", "LLM HTTP {status}: {body}").format(
            status=status,
            body=body[:200] if body else lt("unerwartete Anfrage-Antwort", "unexpected response to the request"),
        ),
        status_code=status,
        endpoint=endpoint,
        body=body[:400] if body else None,
        original=exc,
    )


def _retryable_http_response(resp: httpx.Response) -> bool:
    if resp.status_code < 400:
        return False
    body_lower = (resp.text or "").lower()
    if _is_engine_unavailable_error(body_lower):
        # The orchestrator owns the longer same-model engine recovery budget.
        # Retrying here as well multiplies each recovery turn by the HTTP
        # retry count and hides the typed engine failure from that layer.
        return False
    if any(token in body_lower for token in _STALE_CONTINUATION_HINTS):
        # Derselbe Payload traegt die tote previous_response_id; nur der
        # Orchestrator kann die Anfrage ohne Fortsetzung neu bauen.
        return False
    if any(token in body_lower for token in _TRANSIENT_LM_STUDIO_HINTS):
        return True
    if resp.status_code not in _RETRYABLE_STATUS_CODES:
        return False
    if 500 <= resp.status_code < 600:
        if any(token in body_lower for token in _CONTEXT_WINDOW_HINTS):
            return False
        if any(token in body_lower for token in _MAX_OUTPUT_HINTS):
            return False
    return True


def _classify_transport_error(endpoint: str, exc: Exception) -> LLMRequestError:
    if isinstance(exc, httpx.TimeoutException):
        return LLMRequestError(
            kind=LLMErrorKind.TIMEOUT,
            message=lt(
                "Der LLM-Endpunkt hat nicht rechtzeitig geantwortet.",
                "The LLM endpoint did not answer in time.",
            ),
            retryable=True,
            endpoint=endpoint,
            original=exc,
        )

    if _is_retryable_exception(exc):
        return LLMRequestError(
            kind=LLMErrorKind.TRANSPORT,
            message=lt(
                "Transportfehler beim LLM-Endpunkt: {error}",
                "Transport error at the LLM endpoint: {error}",
            ).format(error=exc),
            retryable=True,
            endpoint=endpoint,
            original=exc,
        )

    return LLMRequestError(
        kind=LLMErrorKind.UNKNOWN,
        message=str(exc),
        endpoint=endpoint,
        original=exc,
    )


def _invalid_response_error(
    endpoint: str,
    exc: Exception,
    *,
    detail: str = lt(
        "Der LLM-Endpunkt hat ungültiges JSON geliefert.",
        "The LLM endpoint returned invalid JSON.",
    ),
) -> LLMRequestError:
    return LLMRequestError(
        kind=LLMErrorKind.INVALID_RESPONSE,
        message=detail,
        endpoint=endpoint,
        original=exc,
    )


def _build_route_payload(
    route: _LLMRoute,
    messages: Sequence[Dict[str, Any]],
    tools: Sequence[Dict[str, Any]],
    *,
    stream: bool,
    json_schema: Dict[str, Any] | None = None,
    seed: int | None = None,
    temperature: float | None = None,
    tool_choice: str | Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    request_messages = _sanitize_messages(messages, strip_media=route.strip_media)
    if json_schema is not None and route.structured_mode == "prompt_hint":
        request_messages = [
            {"role": "system", "content": _build_schema_hint(json_schema)},
            *request_messages,
        ]

    payload = _build_payload(
        route.endpoint,
        route.model,
        request_messages,
        list(tools),
        stream=stream,
        seed=seed,
        temperature=temperature,
        tool_choice=tool_choice,
    )

    if json_schema is not None and route.structured_mode == "json_schema":
        payload["response_format"] = {"type": "json_schema", "json_schema": json_schema}

    return payload


# Some templates require a system message at position zero. Rewrite the
# role of appended turn variables to preserve the stable prompt prefix.
# Seed known template requirements to avoid an initial failed request,
# and learn additional requirements from runtime responses.
_SYSTEM_FIRST_ONLY_PREFIXES: tuple[str, ...] = ("qwen3",)

_SYSTEM_FIRST_ONLY_MODELS: set[str] = set()

_SYSTEM_POSITION_HINTS = (
    "system message must be at the beginning",
    "system messages must be at the beginning",
    # Mistral template role requirements.
    "got system",
    "must alternate user and assistant roles",
)

_SYSTEM_NOTE_MARKER = "[Systemhinweis]"


def _is_system_position_error(exc: LLMRequestError) -> bool:
    return any(
        hint in (exc.body or "").casefold() for hint in _SYSTEM_POSITION_HINTS
    )


def _normalize_system_position(
    messages: Sequence[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], bool]:
    """System-Nachrichten hinter dem Kopf in User-Nachrichten umschreiben.

    Position und Reihenfolge bleiben unveraendert — nur die Rolle wechselt.
    Damit bleiben sowohl der byte-stabile KV-Praefix als auch die
    Recency-Wirkung der Turn-Variablen erhalten.
    """
    out: List[Dict[str, Any]] = []
    im_kopf = True
    veraendert = False
    for message in messages:
        if message.get("role") != "system":
            im_kopf = False
            out.append(dict(message))
            continue
        if im_kopf:
            out.append(dict(message))
            continue
        umgeschrieben = dict(message)
        umgeschrieben["role"] = "user"
        inhalt = str(message.get("content") or "")
        if not inhalt.startswith(_SYSTEM_NOTE_MARKER):
            inhalt = f"{_SYSTEM_NOTE_MARKER}\n{inhalt}"
        umgeschrieben["content"] = inhalt
        out.append(umgeschrieben)
        veraendert = True
    # Merge consecutive equal roles for templates requiring strict role
    # alternation.
    zusammengefuehrt: List[Dict[str, Any]] = []
    for message in out:
        if (
            zusammengefuehrt
            and message.get("role") == zusammengefuehrt[-1].get("role")
            and message.get("role") in {"user", "assistant"}
        ):
            vorher = zusammengefuehrt[-1]
            vorher["content"] = (
                str(vorher.get("content") or "")
                + "\n\n"
                + str(message.get("content") or "")
            )
            veraendert = True
            continue
        zusammengefuehrt.append(dict(message))
    return zusammengefuehrt, veraendert


def _system_first_only(model: str | None) -> bool:
    name = str(model or "").casefold()
    if name in _SYSTEM_FIRST_ONLY_MODELS:
        return True
    return any(name.startswith(p) for p in _SYSTEM_FIRST_ONLY_PREFIXES)


async def _post_with_route_fallback(
    routes: Sequence[_LLMRoute],
    messages: Sequence[Dict[str, Any]],
    tools: Sequence[Dict[str, Any]],
    *,
    timeout: float | None,
    headers: Dict[str, str] | None,
    json_schema: Dict[str, Any] | None = None,
    seed: int | None = None,
    temperature: float | None = None,
    tool_choice: str | Dict[str, Any] | None = None,
) -> tuple[_LLMRoute, Dict[str, Any]]:
    last_error: LLMRequestError | None = None
    for idx, route in enumerate(routes):

        async def _attempt(
            versuchs_messages: Sequence[Dict[str, Any]],
            _route: _LLMRoute = route,
        ) -> Dict[str, Any]:
            buffered_responses_stream = (
                _is_responses_api(_route.endpoint)
                and _config_bool(
                    "CANDYCONC_RESPONSES_BUFFERED_STREAM",
                    _is_local_lm_studio_endpoint(_route.endpoint),
                )
            )
            payload = _build_route_payload(
                _route,
                versuchs_messages,
                tools,
                stream=buffered_responses_stream,
                json_schema=json_schema,
                seed=seed,
                temperature=temperature,
                tool_choice=tool_choice,
            )
            if buffered_responses_stream:
                return await _post_responses_stream_buffered(
                    _route.endpoint,
                    payload,
                    timeout=timeout,
                    headers=headers,
                )
            return await _post_json_with_retry(
                _route.endpoint,
                payload,
                timeout=timeout,
                headers=headers,
            )

        try:
            await _ensure_lm_studio_model_loaded(route, timeout=timeout, headers=headers)
            route_messages: Sequence[Dict[str, Any]] = messages
            bereits_normalisiert = _system_first_only(route.model)
            if bereits_normalisiert:
                route_messages, _ = _normalize_system_position(messages)
            try:
                return route, await _attempt(route_messages)
            except LLMRequestError as exc:
                # Das Template duldet System-Nachrichten nur am Anfang. Rollen
                # umschreiben und EINMAL erneut versuchen, danach das Modell
                # fuer den Rest des Prozesses vormerken.
                if bereits_normalisiert or not _is_system_position_error(exc):
                    raise
                korrigiert, veraendert = _normalize_system_position(messages)
                if not veraendert:
                    raise
                _SYSTEM_FIRST_ONLY_MODELS.add(str(route.model or "").casefold())
                logger.warning(
                    "Chat-Template von %s duldet System-Nachrichten nur am "
                    "Anfang. Spaetere System-Nachrichten werden ab jetzt als "
                    "'%s'-User-Nachrichten gesendet (Position unveraendert).",
                    route.model,
                    _SYSTEM_NOTE_MARKER,
                )
                return route, await _attempt(korrigiert)
        except LLMRequestError as exc:
            last_error = _bind_route_error(route, exc)
            if idx < len(routes) - 1 and _should_try_alternate_route(
                exc, aktuelle=route, naechste=routes[idx + 1]
            ):
                logger.warning(
                    "LLM-Route %s mit Modell %s fehlgeschlagen (%s). Wechsle auf Fallback %s/%s.",
                    route.endpoint,
                    route.model,
                    last_error.kind,
                    idx + 2,
                    len(routes),
                )
                continue
            raise last_error

    if last_error is not None:
        raise last_error

    raise LLMRequestError(
        kind=LLMErrorKind.UNKNOWN,
        message=lt(
            "Der LLM-Aufruf ist ohne verwertbaren Fallback fehlgeschlagen.",
            "The LLM call failed without a usable fallback.",
        ),
    )


async def _stream_with_route_fallback(
    routes: Sequence[_LLMRoute],
    messages: Sequence[Dict[str, Any]],
    tools: Sequence[Dict[str, Any]],
    *,
    timeout: float | None,
    headers: Dict[str, str] | None,
    json_schema: Dict[str, Any] | None = None,
    seed: int | None = None,
    temperature: float | None = None,
    tool_choice: str | Dict[str, Any] | None = None,
) -> AsyncIterator[Dict[str, Any]]:
    last_error: LLMRequestError | None = None
    for idx, route in enumerate(routes):
        yielded_any = False
        try:
            await _ensure_lm_studio_model_loaded(route, timeout=timeout, headers=headers)
            route_messages: Sequence[Dict[str, Any]] = messages
            if _system_first_only(route.model):
                route_messages, _ = _normalize_system_position(messages)
            payload = _build_route_payload(
                route,
                route_messages,
                tools,
                stream=True,
                json_schema=json_schema,
                seed=seed,
                temperature=temperature,
                tool_choice=tool_choice,
            )
            if _is_custom_chat_endpoint(route.endpoint):
                data = await _post_json_with_retry(
                    route.endpoint,
                    payload,
                    timeout=timeout,
                    headers=headers,
                )
                wrapped = _wrap_response(route.endpoint, data)
                text = _extract_text(wrapped)
                if text:
                    yielded_any = True
                    yield _attach_stream_chunk_meta(
                        {
                            "choices": [
                                {
                                    "delta": {"role": "assistant", "content": text},
                                    "finish_reason": "stop",
                                }
                            ]
                        },
                        route,
                    )
                return

            async for chunk in _stream_json_with_retry(
                route.endpoint,
                payload,
                timeout=timeout,
                headers=headers,
            ):
                yielded_any = True
                yield _attach_stream_chunk_meta(chunk, route)
            return
        except LLMRequestError as exc:
            last_error = _bind_route_error(route, exc)
            if yielded_any:
                raise last_error
            if _is_system_position_error(exc):
                # Noch kein Chunk geflossen: die Rollen-Normalisierung
                # vormerken und dieselbe Route ein einziges Mal wiederholen.
                korrigiert, veraendert = _normalize_system_position(messages)
                if veraendert and not _system_first_only(route.model):
                    _SYSTEM_FIRST_ONLY_MODELS.add(str(route.model or "").casefold())
                    logger.warning(
                        "Chat-Template von %s duldet System-Nachrichten nur "
                        "am Anfang. Stream wird mit umgeschriebenen Rollen "
                        "wiederholt.",
                        route.model,
                    )
                    async for chunk in _stream_json_with_retry(
                        route.endpoint,
                        _build_route_payload(
                            route,
                            korrigiert,
                            tools,
                            stream=True,
                            json_schema=json_schema,
                            seed=seed,
                            temperature=temperature,
                            tool_choice=tool_choice,
                        ),
                        timeout=timeout,
                        headers=headers,
                    ):
                        yield _attach_stream_chunk_meta(chunk, route)
                    return
            if idx < len(routes) - 1 and _should_try_alternate_route(
                exc, aktuelle=route, naechste=routes[idx + 1]
            ):
                logger.warning(
                    "LLM-Streaming-Route %s mit Modell %s fehlgeschlagen (%s). Nutze Fallback %s/%s.",
                    route.endpoint,
                    route.model,
                    last_error.kind,
                    idx + 2,
                    len(routes),
                )
                continue
            raise last_error

    if last_error is not None:
        raise last_error

    raise LLMRequestError(
        kind=LLMErrorKind.UNKNOWN,
        message=lt(
            "Der LLM-Stream ist ohne verwertbaren Fallback fehlgeschlagen.",
            "The LLM stream failed without a usable fallback.",
        ),
    )


async def _post_responses_stream_buffered(
    endpoint: str,
    payload: Dict[str, Any],
    *,
    timeout: float | None,
    headers: Dict[str, str] | None,
) -> Dict[str, Any]:
    """Consume Responses SSE while returning the usual complete response."""

    started = time.monotonic()
    next_progress_log = 60.0
    event_count = 0
    response_state: Dict[str, Any] = {}
    output_items: Dict[int, Dict[str, Any]] = {}
    model_checked = False
    async for event in _stream_json_with_retry(
        endpoint,
        payload,
        timeout=timeout,
        headers=headers,
    ):
        if not isinstance(event, dict):
            continue
        event_count += 1
        event_type = str(event.get("type") or "")
        response = event.get("response")
        if isinstance(response, dict):
            response_state.update(response)
            # The Responses stream names the answering model inside
            # ``response`` (response.created, response.completed), not at
            # the top of the event, where the check of the shared stream
            # reader looks. Same check as on the JSON and the chat stream
            # path, at the first event that names a model.
            if not model_checked and str(response.get("model") or "").strip():
                _pruefe_antwortmodell(endpoint, payload, response)
                model_checked = True
        output_index = event.get("output_index")
        if (
            event_type == "response.output_item.added"
            and isinstance(output_index, int)
            and isinstance(event.get("item"), dict)
        ):
            output_items[output_index] = dict(event["item"])
        elif (
            event_type == "response.output_text.done"
            and isinstance(output_index, int)
        ):
            item = output_items.setdefault(
                output_index,
                {
                    "id": event.get("item_id", ""),
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                },
            )
            content = list(item.get("content") or [])
            content_index = event.get("content_index")
            part = {
                "type": "output_text",
                "text": str(event.get("text") or ""),
            }
            if isinstance(content_index, int):
                while len(content) <= content_index:
                    content.append({})
                content[content_index] = part
            else:
                content.append(part)
            item["content"] = content
            item["status"] = "completed"
        elif (
            event_type == "response.function_call_arguments.done"
            and isinstance(output_index, int)
        ):
            item = output_items.setdefault(
                output_index,
                {
                    "id": event.get("item_id", ""),
                    "type": "function_call",
                },
            )
            item["arguments"] = str(event.get("arguments") or "")
            item["status"] = "completed"
        elif (
            event_type == "response.output_item.done"
            and isinstance(output_index, int)
            and isinstance(event.get("item"), dict)
        ):
            output_items[output_index] = dict(event["item"])
        elapsed = time.monotonic() - started
        if elapsed >= next_progress_log:
            logger.warning(
                "Responses stream still active after %.0fs "
                "(events=%d, last_event=%s, model=%s, max_output_tokens=%s)",
                elapsed,
                event_count,
                event_type or "unknown",
                payload.get("model", ""),
                payload.get("max_output_tokens", "unset"),
            )
            next_progress_log = elapsed + 60.0
        if event_type == "response.completed" and isinstance(response, dict):
            return response
        if event_type == "response.incomplete" and isinstance(response, dict):
            logger.warning(
                "Responses stream ended incomplete after %.1fs "
                "(events=%d, reason=%s)",
                elapsed,
                event_count,
                (response.get("incomplete_details") or {}).get(
                    "reason",
                    "unknown",
                ),
            )
            return response
        if event_type in {"response.failed", "error"}:
            detail_source = response if isinstance(response, dict) else event
            detail = detail_source.get("error") if isinstance(detail_source, dict) else None
            raise _stream_fehler_aus_ereignis(endpoint, event_type, detail)

    reconstructed_output = [
        item
        for _index, item in sorted(output_items.items())
        if (
            item.get("type") == "message"
            and any(
                isinstance(part, dict)
                and part.get("type") in {"output_text", "text"}
                and str(part.get("text") or "")
                for part in list(item.get("content") or [])
            )
        )
        or (
            item.get("type") == "function_call"
            and item.get("status") == "completed"
            and str(item.get("name") or "")
            and str(item.get("arguments") or "")
        )
    ]
    if reconstructed_output:
        logger.warning(
            "Responses stream ended without response.completed after %.1fs; "
            "using %d terminally completed output item(s).",
            time.monotonic() - started,
            len(reconstructed_output),
        )
        return {
            **response_state,
            "status": "completed",
            "incomplete_details": None,
            "error": None,
            "output": reconstructed_output,
        }

    raise _invalid_response_error(
        endpoint,
        ValueError("response.completed missing"),
        detail=lt(
            "Der Responses-Stream endete ohne response.completed.",
            "The Responses stream ended without response.completed.",
        ),
    )


async def _post_json_with_retry(
    endpoint: str,
    payload: Dict[str, Any],
    *,
    timeout: float | None,
    headers: Dict[str, str] | None,
    max_retries: int = _MAX_RETRIES,
) -> Dict[str, Any]:
    attempts = max_retries + 1
    last_error: LLMRequestError | None = None
    for attempt in range(1, attempts + 1):
        try:
            client = _shared_http_client()
            resp = await client.post(
                endpoint,
                json=payload,
                timeout=timeout,
                headers=headers,
            )
            if _retryable_http_response(resp) and attempt < attempts:
                delay = _retry_delay(attempt, resp.headers.get("Retry-After"))
                logger.warning(
                    "Transient LLM HTTP %s from %s. Retry in %.1fs (%s/%s)",
                    resp.status_code,
                    endpoint,
                    delay,
                    attempt,
                    attempts,
                )
                if any(
                    token in (resp.text or "").casefold()
                    for token in _TRANSIENT_LM_STUDIO_HINTS
                ):
                    await _wait_for_same_model_after_lm_link_disconnect(
                        endpoint,
                        payload,
                        timeout=timeout,
                        headers=headers,
                    )
                await asyncio.sleep(delay)
                continue
            resp.raise_for_status()
            try:
                daten = resp.json()
            except ValueError as exc:
                raise _invalid_response_error(endpoint, exc)
            _pruefe_antwortmodell(endpoint, payload, daten)
            return daten
        except httpx.HTTPStatusError as exc:
            if _retryable_http_response(exc.response) and attempt < attempts:
                delay = _retry_delay(attempt, exc.response.headers.get("Retry-After"))
                logger.warning(
                    "Transient LLM HTTP %s from %s. Retry in %.1fs (%s/%s)",
                    exc.response.status_code,
                    endpoint,
                    delay,
                    attempt,
                    attempts,
                )
                if any(
                    token in (exc.response.text or "").casefold()
                    for token in _TRANSIENT_LM_STUDIO_HINTS
                ):
                    await _wait_for_same_model_after_lm_link_disconnect(
                        endpoint,
                        payload,
                        timeout=timeout,
                        headers=headers,
                    )
                await asyncio.sleep(delay)
                continue
            last_error = _classify_http_error(endpoint, exc)
            break
        except LLMRequestError as exc:
            last_error = exc
            break
        except Exception as exc:
            if _is_retryable_exception(exc) and attempt < attempts:
                delay = _retry_delay(attempt)
                logger.warning(
                    "Transient LLM transport error from %s: %s. Retry in %.1fs (%s/%s)",
                    endpoint,
                    _fehlertext(exc),
                    delay,
                    attempt,
                    attempts,
                )
                await asyncio.sleep(delay)
                continue
            last_error = _classify_transport_error(endpoint, exc)
            break

    if last_error is not None:
        raise last_error

    raise LLMRequestError(
        kind=LLMErrorKind.UNKNOWN,
        message=lt(
            "Der LLM-Aufruf ist ohne Ergebnis fehlgeschlagen.",
            "The LLM call failed without a result.",
        ),
        endpoint=endpoint,
    )


async def _stream_json_with_retry(
    endpoint: str,
    payload: Dict[str, Any],
    *,
    timeout: float | None,
    headers: Dict[str, str] | None,
    max_retries: int = _MAX_RETRIES,
) -> AsyncIterator[Dict[str, Any]]:
    attempts = max_retries + 1
    yielded_any = False
    last_error: LLMRequestError | None = None

    for attempt in range(1, attempts + 1):
        retry_after: float | None = None
        wait_for_same_model = False
        try:
            client = _shared_http_client()
            async with client.stream(
                "POST",
                endpoint,
                json=payload,
                timeout=timeout,
                headers=headers,
            ) as resp:
                if resp.status_code >= 400:
                    # The body can distinguish a real bad request from
                    # transient LM Studio transport failures that use 400.
                    await resp.aread()
                if (
                    _retryable_http_response(resp)
                    and attempt < attempts
                    and not yielded_any
                ):
                    retry_after = _retry_delay(attempt, resp.headers.get("Retry-After"))
                    wait_for_same_model = any(
                        token in (resp.text or "").casefold()
                        for token in _TRANSIENT_LM_STUDIO_HINTS
                    )
                else:
                    resp.raise_for_status()
                    strom_start = time.monotonic()
                    async for line in resp.aiter_lines():
                        # Enforce the configured call duration against wall time. An httpx read
                        # timeout only measures gaps between packets, so continuous reasoning
                        # deltas would otherwise keep a call alive past that duration.
                        if timeout and (time.monotonic() - strom_start) >= float(timeout):
                            raise httpx.ReadTimeout(
                                f"Strom ueberschritt das Per-Call-Limit "
                                f"({float(timeout):.0f}s)"
                            )
                        if not line or not line.startswith("data: "):
                            continue
                        data = line[6:].strip()
                        if data == "[DONE]":
                            return
                        try:
                            chunk = json.loads(data)
                        except ValueError as exc:
                            raise _invalid_response_error(
                                endpoint,
                                exc,
                                detail=lt(
                                    "Der LLM-Stream hat ungültiges JSON geliefert.",
                                    "The LLM stream returned invalid JSON.",
                                ),
                            )
                        if not yielded_any:
                            # Nur der erste Chunk traegt das Modell zuverlaessig.
                            _pruefe_antwortmodell(endpoint, payload, chunk)
                        yielded_any = True
                        yield chunk
                    return
        except httpx.HTTPStatusError as exc:
            if (
                _retryable_http_response(exc.response)
                and attempt < attempts
                and not yielded_any
            ):
                retry_after = _retry_delay(attempt, exc.response.headers.get("Retry-After"))
                wait_for_same_model = any(
                    token in (exc.response.text or "").casefold()
                    for token in _TRANSIENT_LM_STUDIO_HINTS
                )
            else:
                last_error = _classify_http_error(endpoint, exc)
                break
        except LLMRequestError as exc:
            last_error = exc
            break
        except Exception as exc:
            if _is_retryable_exception(exc) and attempt < attempts and not yielded_any:
                retry_after = _retry_delay(attempt)
                logger.warning(
                    "Transient LLM stream transport error from %s: %s. Retry in %.1fs (%s/%s)",
                    endpoint,
                    exc,
                    retry_after,
                    attempt,
                    attempts,
                )
            else:
                last_error = _classify_transport_error(endpoint, exc)
                break

        if retry_after is None:
            continue
        logger.warning(
            "Transient LLM streaming response from %s. Retry in %.1fs (%s/%s)",
            endpoint,
            retry_after,
            attempt,
            attempts,
        )
        if wait_for_same_model:
            await _wait_for_same_model_after_lm_link_disconnect(
                endpoint,
                payload,
                timeout=timeout,
                headers=headers,
            )
        await asyncio.sleep(retry_after)

    if last_error is not None:
        raise last_error

    raise LLMRequestError(
        kind=LLMErrorKind.UNKNOWN,
        message=lt(
            "Der LLM-Stream ist ohne Ergebnis fehlgeschlagen.",
            "The LLM stream failed without a result.",
        ),
        endpoint=endpoint,
    )


COPILOT_NOT_CONFIGURED_MESSAGE = (
    "No language model is configured for the copilot. Everything else in "
    "CandyConc works without one. To use the copilot, set a model endpoint in "
    "Settings > Model connection, or set COPILOT_ENDPOINT and COPILOT_MODEL in the "
    "environment or in the configuration file (candy paths shows where it is)."
)


def token_len(messages: List[Dict[str, Any]]) -> int:
    """Estimate the token length of ``messages`` from their word count.

    A tokenizer would need a vocabulary file for each model family. tiktoken,
    the former optional path, downloaded one from the network on first use and
    raised without network access. The estimate (about 1.3 tokens per word)
    only steers the large-context model route and the usage metrics.
    """
    count = 0
    for m in messages:
        text = str(m.get("content", ""))
        count += len(text.split()) * 4 // 3
    return count


async def ensure_copilot_runtime_available(
    messages: Sequence[Dict[str, Any]],
    tools: Sequence[Dict[str, Any]] | None = None,
    *,
    json_schema: Dict[str, Any] | None = None,
) -> None:
    """Read-only runtime gate for local LM Studio chat routes."""
    endpoint = get_config("COPILOT_ENDPOINT")
    if not endpoint:
        raise LLMRequestError(
            kind=LLMErrorKind.NOT_CONFIGURED,
            message=COPILOT_NOT_CONFIGURED_MESSAGE,
        )
    model = get_config("COPILOT_MODEL", "qwen3-7b")
    routes = _build_route_candidates(
        endpoint,
        model,
        messages,
        tools=list(tools or []),
        json_schema=json_schema,
    )
    timeout = _get_llm_timeout(extra_seconds=10.0 if json_schema is not None else 0.0)
    headers = _get_llm_headers()
    for idx, route in enumerate(routes):
        try:
            await _ensure_lm_studio_model_loaded(
                route,
                timeout=timeout,
                headers=headers,
            )
            return
        except LLMRequestError as exc:
            bound = _bind_route_error(route, exc)
            if idx < len(routes) - 1 and _should_try_alternate_route(
                exc, aktuelle=route, naechste=routes[idx + 1]
            ):
                continue
            raise bound


async def chat(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Send ``messages`` to the local LLM server."""
    init_logging()
    endpoint = APP_CONFIG.COPILOT_ENDPOINT
    if not endpoint:
        raise RuntimeError(COPILOT_NOT_CONFIGURED_MESSAGE)
    model = APP_CONFIG.COPILOT_MODEL

    if token_len(messages) > 8_000 and not get_config("LM_STUDIO_LARGE_CONTEXT_MODEL"):
        raise HTTPException(status_code=413, detail="Token budget exceeded")
    tools = get_tools()
    routes = _build_route_candidates(
        endpoint,
        model,
        messages,
        tools=tools,
        json_schema=None,
    )
    _log_route_candidate_summary(
        requested_model=model,
        routes=routes,
        tools=tools,
        json_schema=None,
    )

    headers = _get_llm_headers()
    route, data = await _post_with_route_fallback(
        routes,
        messages,
        tools,
        timeout=_get_llm_timeout(),
        headers=headers,
    )
    data = _attach_response_meta(_wrap_response(route.endpoint, data), route)
    redacted_resp = {
        k: v if k != "choices" else f"<{len(v)} choices>" for k, v in data.items()
    }
    logger.debug("LLM response: %s", redacted_resp)
    return data


async def call_llm_async(
    messages: List[Dict[str, str]],
    tools: List[Dict[str, Any]],
    *,
    json_schema: Dict[str, Any] | None = None,
    stream: bool = False,
    user: str = "default",
    policy: PolicyEngine | None = None,
    seed: int | None = None,
    temperature: float | None = None,
    tool_choice: str | Dict[str, Any] | None = None,
) -> Dict[str, Any] | Any:
    """Return LLM result for ``messages`` and ``tools`` asynchronously."""

    from candyconc.services.backend import metrics
    from candyconc.services.backend.server import trace

    endpoint = get_config("COPILOT_ENDPOINT")
    if not endpoint:
        raise RuntimeError(COPILOT_NOT_CONFIGURED_MESSAGE)
    model = get_config("COPILOT_MODEL", "qwen3-7b")
    trace_hash = trace.record_pre(messages, tools, user, model, stream=stream)

    if metrics is not None:
        metrics.inc_tokens(token_len(messages))

    timeout = _get_llm_timeout(extra_seconds=10.0 if json_schema is not None else 0.0)
    headers = _get_llm_headers()
    routes = _build_route_candidates(
        endpoint,
        model,
        messages,
        tools=tools,
        json_schema=json_schema,
    )
    _log_route_candidate_summary(
        requested_model=model,
        routes=routes,
        tools=tools,
        json_schema=json_schema,
    )

    async def _stream_gen_v2() -> Any:
        try:
            async for chunk in _stream_with_route_fallback(
                routes,
                messages,
                tools,
                timeout=timeout,
                headers=headers,
                json_schema=json_schema,
                seed=seed,
                temperature=temperature,
                tool_choice=tool_choice,
            ):
                yield chunk
        finally:
            trace.record_post(trace_hash, tokens=0)

    if stream:
        return _stream_gen_v2()

    route, data = await _post_with_route_fallback(
        routes,
        messages,
        tools,
        timeout=timeout,
        headers=headers,
        json_schema=json_schema,
        seed=seed,
        temperature=temperature,
        tool_choice=tool_choice,
    )
    data = _attach_response_meta(_wrap_response(route.endpoint, data), route)

    tokens = 0
    try:
        tokens = int(data.get("usage", {}).get("total_tokens", 0))
    except Exception:
        tokens = 0
    trace.record_post(trace_hash, tokens=tokens)
    return data


def call_llm(
    messages: List[Dict[str, str]],
    tools: List[Dict[str, Any]],
    *,
    json_schema: Dict[str, Any] | None = None,
    stream: bool = False,
    user: str = "default",
    policy: PolicyEngine | None = None,
    seed: int | None = None,
    temperature: float | None = None,
    tool_choice: str | Dict[str, Any] | None = None,
) -> Dict[str, Any] | Any:
    """Synchronous wrapper delegating to :func:`call_llm_async`."""

    if stream:
        agen = call_llm_async(
            messages,
            tools,
            json_schema=json_schema,
            stream=True,
            user=user,
            policy=policy,
            seed=seed,
            temperature=temperature,
            tool_choice=tool_choice,
        )

        def _gen() -> Any:
            loop = asyncio.new_event_loop()
            try:
                while True:
                    try:
                        chunk = loop.run_until_complete(agen.__anext__())
                    except StopAsyncIteration:
                        break
                    yield chunk
            finally:
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()

        return _gen()

    return asyncio.run(
        call_llm_async(
            messages,
            tools,
            json_schema=json_schema,
            user=user,
            policy=policy,
            seed=seed,
            temperature=temperature,
            tool_choice=tool_choice,
        )
    )


def _is_custom_chat_endpoint(endpoint: str) -> bool:
    try:
        path = urlparse(endpoint).path.rstrip("/")
    except Exception:
        return False
    return path.endswith("/api/v1/chat")


def _is_responses_api(endpoint: str) -> bool:
    """Check if endpoint uses the Responses API (supports thinking with tool calls)."""
    try:
        path = urlparse(endpoint).path.rstrip("/")
    except Exception:
        return False
    return path.endswith("/v1/responses") or path.endswith("/responses")


def _responses_tool_call_specs(tools: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    responses_tools: List[Dict[str, Any]] = []
    for tool in tools:
        if tool.get("type") != "function":
            continue
        function = tool.get("function", {}) or {}
        responses_tools.append(
            {
                "type": "function",
                "name": function.get("name", ""),
                "description": function.get("description", ""),
                "parameters": function.get("parameters", {}),
            }
        )
    return responses_tools


def _responses_continuation_from_history(
    messages: Sequence[Dict[str, Any]],
) -> tuple[str, List[Dict[str, Any]]] | None:
    """Return a native Responses continuation from stored assistant/tool turns.

    The orchestrator stores the wrapped Responses ``id`` on the assistant turn
    that produced tool calls. The next request can then send only
    ``function_call_output`` items with ``previous_response_id`` instead of
    flattening tool outputs into normal prose context.
    """

    last_tool_response_idx = -1
    previous_response_id = ""
    expected_call_ids: set[str] = set()
    for idx, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        response_id = str(message.get("_cc_response_id", "") or "").strip()
        tool_calls = message.get("tool_calls")
        if not response_id or not isinstance(tool_calls, list) or not tool_calls:
            continue
        if not response_id.startswith("resp_"):
            # Some LM Studio model adapters return a Chat Completions id from
            # /v1/responses. It cannot be used as previous_response_id; retain
            # the tool result through the portable flattened-context path.
            logger.warning(
                "Responses endpoint returned non-continuation id %r; "
                "using flattened tool context",
                response_id,
            )
            continue
        call_ids = {
            str(call.get("id", "") or "").strip()
            for call in tool_calls
            if isinstance(call, dict) and str(call.get("id", "") or "").strip()
        }
        if not call_ids:
            continue
        last_tool_response_idx = idx
        previous_response_id = response_id
        expected_call_ids = call_ids

    if last_tool_response_idx < 0 or not previous_response_id:
        return None

    continuation: List[Dict[str, Any]] = []
    saw_function_output = False
    for message in messages[last_tool_response_idx + 1 :]:
        role = message.get("role")
        content = str(message.get("content", "") or "")
        if role == "tool":
            call_id = str(message.get("tool_call_id", "") or "").strip()
            if call_id not in expected_call_ids:
                continue
            continuation.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": content,
                }
            )
            saw_function_output = True
        elif role in {"user", "assistant"} and content:
            if role == "assistant":
                # A later assistant message means this tool result was already
                # consumed by a completed model turn. Do not reuse that old
                # previous_response_id for a future user question.
                return None
            continuation.append({"role": role, "content": content})

    if not saw_function_output:
        return None
    return previous_response_id, continuation


def _build_payload(
    endpoint: str,
    model: str,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    *,
    stream: bool,
    seed: int | None = None,
    temperature: float | None = None,
    tool_choice: str | Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    # Responses API - supports thinking with tool calls
    if _is_responses_api(endpoint):
        # Apply reasoning text and /no_think before assembling instructions and
        # input, so Responses requests include the configured steering.
        messages = _apply_reasoning_steering(
            _apply_thinking_mode(messages), model
        )
        # Extract system prompt and build input from messages
        system_parts = []
        input_parts = []

        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")
            if role == "system":
                system_parts.append(content)
            elif role == "user":
                input_parts.append(content)
            elif role == "assistant":
                # Include assistant responses as context
                input_parts.append(f"[Assistant]: {content}")
            elif role == "tool":
                # Include tool results as context
                tool_id = m.get("tool_call_id", "unknown")
                input_parts.append(f"[Tool Result {tool_id}]: {content}")

        responses_tools = _responses_tool_call_specs(tools)
        continuation = _responses_continuation_from_history(messages)

        payload: Dict[str, Any] = {
            "model": model,
        }
        if continuation is not None:
            previous_response_id, continuation_items = continuation
            payload["previous_response_id"] = previous_response_id
            payload["input"] = continuation_items
        else:
            payload["input"] = "\n\n".join(input_parts).strip()

        # Add system instructions if present
        if system_parts:
            payload["instructions"] = "\n\n".join(system_parts)

        # Add tools if present
        if responses_tools:
            payload["tools"] = responses_tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice

        if stream:
            payload["stream"] = True
        max_output_tokens = _get_max_output_tokens()
        if max_output_tokens is not None:
            payload["max_output_tokens"] = max_output_tokens
        # This LM Studio/Qwen GGUF combination rejects custom reasoning payload
        # fields. Apply the template steering text in the system prompt through
        # _apply_reasoning_steering.

        # The Responses API does not provide a portable seed parameter. Keep
        # the requested seed in the evaluation artefact, but do not send an
        # unsupported field that would make the transport fail. Temperature is
        # supported by compatible Responses endpoints.
        if temperature is not None:
            payload["temperature"] = temperature

        return payload

    # Legacy custom chat endpoint (no tool support)
    if _is_custom_chat_endpoint(endpoint):
        system_prompt = "\n".join(
            m.get("content", "") for m in messages if m.get("role") == "system"
        ).strip()
        user_inputs = [m.get("content", "") for m in messages if m.get("role") == "user"]
        input_text = "\n".join([t for t in user_inputs if t]).strip()
        if not input_text:
            input_text = str(messages[-1].get("content", "")).strip() if messages else ""
        return {
            "model": model,
            "system_prompt": system_prompt,
            "input": input_text,
        }

    # Standard OpenAI Chat Completions API
    payload = {"model": model, "messages": _apply_reasoning_steering(_apply_thinking_mode(messages), model), "tools": tools}
    if stream:
        payload["stream"] = True
    payload["tool_choice"] = tool_choice or "auto"
    if seed is not None:
        payload["seed"] = seed
    if temperature is not None:
        payload["temperature"] = temperature
    max_output_tokens = _get_max_output_tokens()
    if max_output_tokens is not None:
        # Chat Completions names the same output budget ``max_tokens``.
        payload["max_tokens"] = max_output_tokens
    # Top-level and chat_template_kwargs reasoning fields fail on this GGUF.
    # Use the system-prompt text from _apply_reasoning_steering.
    return payload


def _wrap_response(endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize response to Chat Completions format for orchestrator compatibility."""
    # Already in Chat Completions format
    if "choices" in data:
        return data

    # Responses API format - convert to Chat Completions format
    if _is_responses_api(endpoint):
        return _wrap_responses_api(data)

    # Legacy custom chat endpoint
    if _is_custom_chat_endpoint(endpoint):
        text = _extract_text(data)
        return {"choices": [{"message": {"role": "assistant", "content": text}}]}

    return data


def _attach_response_meta(data: Dict[str, Any], route: _LLMRoute) -> Dict[str, Any]:
    wrapped = dict(data)
    wrapped["_cc_route"] = _describe_route(route)
    wrapped["_cc_model"] = route.model
    wrapped["_cc_endpoint"] = route.endpoint
    return wrapped


def _attach_stream_chunk_meta(chunk: Dict[str, Any], route: _LLMRoute) -> Dict[str, Any]:
    wrapped = dict(chunk)
    wrapped["_cc_route"] = _describe_route(route)
    wrapped["_cc_model"] = route.model
    wrapped["_cc_endpoint"] = route.endpoint
    return wrapped


def _wrap_responses_api(data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert Responses API format to Chat Completions format.

    Responses API returns:
    {
        "id": "...",
        "status": "completed" | "incomplete",
        "output": [
            {
                "type": "reasoning",
                "content": [{"type": "reasoning_text", "text": "..."}]
            },
            {
                "type": "function_call",
                "name": "run_cqlf_query",
                "arguments": "{...}",
                "call_id": "call_123"
            },
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "..."}]
            }
        ],
        ...
    }

    Convert to Chat Completions format for orchestrator compatibility.
    """
    output = data.get("output", [])
    status = str(data.get("status", "completed") or "completed").casefold()
    if isinstance(output, str):
        # Simple text response
        return {
            "choices": [
                {
                    "message": {"role": "assistant", "content": output},
                    "finish_reason": (
                        "length" if status == "incomplete" else "stop"
                    ),
                }
            ]
        }

    if not isinstance(output, list):
        output = [output] if output else []

    message: Dict[str, Any] = {"role": "assistant", "content": ""}
    reasoning_parts = []
    content_parts = []
    tool_calls = []
    discarded_function_calls = 0

    for item in output:
        if not isinstance(item, dict):
            content_parts.append(str(item))
            continue

        item_type = item.get("type", "")

        if item_type == "reasoning":
            # Reasoning has nested content array with reasoning_text items
            content_list = item.get("content", [])
            if isinstance(content_list, list):
                for c in content_list:
                    if isinstance(c, dict) and c.get("type") == "reasoning_text":
                        reasoning_parts.append(c.get("text", ""))
                    elif isinstance(c, str):
                        reasoning_parts.append(c)
            elif isinstance(content_list, str):
                reasoning_parts.append(content_list)

        elif item_type == "message":
            # Message has nested content array with output_text items
            content_list = item.get("content", [])
            if isinstance(content_list, list):
                for c in content_list:
                    if isinstance(c, dict) and c.get("type") in ("output_text", "text"):
                        content_parts.append(c.get("text", ""))
                    elif isinstance(c, str):
                        content_parts.append(c)
            elif isinstance(content_list, str):
                content_parts.append(content_list)

        elif item_type == "function_call":
            item_status = str(item.get("status", "") or "").casefold()
            # An incomplete Responses turn may end inside the JSON argument
            # object. Never turn that fragment into an executable `{}` call.
            if item_status in {"incomplete", "failed", "cancelled"} or (
                status == "incomplete" and item_status != "completed"
            ):
                discarded_function_calls += 1
                continue
            arguments = item.get("arguments", "{}")
            try:
                parsed_arguments = (
                    json.loads(arguments)
                    if isinstance(arguments, str)
                    else arguments
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                discarded_function_calls += 1
                continue
            if not isinstance(parsed_arguments, dict):
                discarded_function_calls += 1
                continue
            # Convert to OpenAI tool_calls format
            tool_calls.append({
                "id": item.get("call_id", item.get("id", f"call_{len(tool_calls)}")),
                "type": "function",
                "function": {
                    "name": item.get("name", ""),
                    "arguments": arguments,
                }
            })

    # Build message
    if content_parts:
        message["content"] = "\n".join(content_parts)
    if reasoning_parts:
        message["reasoning"] = "\n".join(reasoning_parts)
    if tool_calls:
        message["tool_calls"] = tool_calls

    # Determine finish reason
    finish_reason = "tool_calls" if tool_calls else "stop"
    if status == "incomplete":
        finish_reason = "length"

    wrapped = {
        "id": data.get("id", ""),
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": data.get("usage", {}),
    }
    if str(data.get("model") or "").strip():
        # The model that answered, as on the chat completions path.
        wrapped["model"] = data["model"]
    if discarded_function_calls:
        wrapped["_cc_discarded_incomplete_tool_calls"] = (
            discarded_function_calls
        )
        logger.warning(
            "Discarded %s incomplete or malformed Responses tool call(s)",
            discarded_function_calls,
        )
    return wrapped


def _extract_text(data: Dict[str, Any]) -> str:
    if not isinstance(data, dict):
        return str(data)
    for key in ("output", "response", "text", "message"):
        if key in data:
            value = data.get(key)
            if isinstance(value, dict):
                return str(value.get("content", ""))
            return str(value)
    return ""
