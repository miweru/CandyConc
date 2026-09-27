"""Resolve local and provider-backed model routes.

Provider keys are written to the running process environment and inherited
by child processes. They are not persisted to disk and disappear when the
process exits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from candyconc import config as _config
from candyconc.i18n import lt
from candyconc.config import APP_CONFIG


@dataclass(frozen=True)
class Profil:
    """Ein vorbereiteter Modellweg, den die Oberflaeche als Knopf anbietet."""

    id: str
    name: str
    endpoint: str
    schluessel_noetig: bool
    hinweis: str


# Die Reihenfolge ist die Reihenfolge in der Oberflaeche. Lokal steht vorn.
PROFILE: tuple[Profil, ...] = (
    Profil(
        id="lokal",
        name=lt("Lokal (LM Studio)", "Local (LM Studio)"),
        endpoint="http://127.0.0.1:1234/v1/chat/completions",
        schluessel_noetig=False,
        hinweis=lt(
            "Läuft auf diesem Gerät. Kein Text verlässt den Rechner.",
            "Runs on this device. No text leaves the computer.",
        ),
    ),
    Profil(
        id="openrouter",
        name="OpenRouter",
        endpoint="https://openrouter.ai/api/v1/chat/completions",
        schluessel_noetig=True,
        hinweis=lt(
            "Fragen und Korpusausschnitte gehen an einen fremden Dienst und "
            "werden dort verarbeitet.",
            "Questions and corpus excerpts are sent to an external service "
            "and processed there.",
        ),
    ),
)

_EIGEN = "eigen"


def profil_zu(endpoint: str | None) -> str:
    """Welchem Profil entspricht dieser Endpunkt?

    Verglichen wird ueber Schema, Host und Pfad, damit ein Endpunkt mit
    abweichendem Port oder Schraegstrich am Ende nicht faelschlich als
    ``eigen`` gilt, wenn er es nicht ist.
    """
    if not endpoint:
        return _EIGEN
    ziel = urlparse(str(endpoint))
    for profil in PROFILE:
        bekannt = urlparse(profil.endpoint)
        if (
            ziel.scheme == bekannt.scheme
            and ziel.netloc == bekannt.netloc
            and ziel.path.rstrip("/") == bekannt.path.rstrip("/")
        ):
            return profil.id
    # Ein lokal gebundener Endpunkt bleibt lokal, auch auf anderem Port.
    if ziel.hostname in {"127.0.0.1", "localhost", "::1", "0.0.0.0"}:
        return "lokal"
    return _EIGEN


def _schluessel_schwanz(wert: str | None) -> str | None:
    """Die letzten vier Zeichen, damit man den Schluessel wiedererkennt.

    Kurze Werte werden gar nicht gezeigt, sonst waere der Rest des
    Geheimnisses aus dem Angezeigten zu erraten.
    """
    if not wert or len(wert) < 12:
        return None
    return wert[-4:]


def _schluessel_ist_platzhalter(wert: str | None) -> bool:
    """``lm-studio`` ist der Vorgabewert fuer den lokalen Weg, kein Geheimnis."""
    return (wert or "").strip().lower() in {"", "lm-studio", "none", "not-needed"}


def stand() -> dict[str, Any]:
    """Der aktuelle Modellweg, ohne den Schluessel selbst."""
    endpoint = _config.get("COPILOT_ENDPOINT")
    schluessel = _config.get("COPILOT_API_KEY")
    gesetzt = not _schluessel_ist_platzhalter(schluessel)
    return {
        "aktiv": profil_zu(endpoint),
        "endpoint": endpoint,
        "modell": _config.get("COPILOT_MODEL"),
        "schluessel_gesetzt": gesetzt,
        "schluessel_endet_auf": _schluessel_schwanz(schluessel) if gesetzt else None,
        "schluessel_fluechtig": True,
        "profile": [
            {
                "id": p.id,
                "name": p.name,
                "endpoint": p.endpoint,
                "schluessel_noetig": p.schluessel_noetig,
                "hinweis": p.hinweis,
            }
            for p in PROFILE
        ],
    }


class ModellwegFehler(ValueError):
    """Die gewuenschte Einstellung wurde nicht uebernommen."""


def _pruefe_endpoint(endpoint: str) -> None:
    ziel = urlparse(endpoint)
    if ziel.scheme not in {"http", "https"}:
        raise ModellwegFehler(lt(
            "Der Endpunkt braucht http:// oder https:// am Anfang.",
            "The endpoint must start with http:// or https://.",
        ))
    if not ziel.netloc:
        raise ModellwegFehler(lt(
            "Dem Endpunkt fehlt der Rechnername.",
            "The endpoint has no host name.",
        ))


def setzen(
    *,
    endpoint: str | None = None,
    modell: str | None = None,
    schluessel: str | None = None,
) -> dict[str, Any]:
    """Modellweg umstellen und den neuen Stand zurueckgeben.

    Geprueft wird mit ``AppConfig.validate``, also mit denselben Regeln, die
    auch beim Start gelten. Eine zweite, eigene Regelmenge waere eine zweite
    Naht, an der die beiden Wege auseinanderlaufen koennten. Schlaegt die
    Pruefung fehl, wird der vorherige Stand vollstaendig zurueckgerollt.
    """
    vorher = {
        "COPILOT_ENDPOINT": _config.get("COPILOT_ENDPOINT"),
        "COPILOT_MODEL": _config.get("COPILOT_MODEL"),
        "COPILOT_API_KEY": _config.get("COPILOT_API_KEY"),
    }

    if endpoint is not None:
        endpoint = endpoint.strip()
        if not endpoint:
            raise ModellwegFehler(lt(
                "Der Endpunkt darf nicht leer sein.",
                "The endpoint must not be empty.",
            ))
        _pruefe_endpoint(endpoint)
    if modell is not None:
        modell = modell.strip()
        if not modell:
            raise ModellwegFehler(lt(
                "Der Modellname darf nicht leer sein.",
                "The model name must not be empty.",
            ))

    try:
        if endpoint is not None:
            _config.set("COPILOT_ENDPOINT", endpoint)
        if modell is not None:
            _config.set("COPILOT_MODEL", modell)
        if schluessel is not None:
            geputzt = schluessel.strip()
            if not geputzt:
                raise ModellwegFehler(lt(
                    "Der Schlüssel darf nicht leer sein.",
                    "The key must not be empty.",
                ))
            _config.set("COPILOT_API_KEY", geputzt)
        APP_CONFIG.validate()
    except ModellwegFehler:
        _zurueck(vorher)
        raise
    except RuntimeError as fehler:
        _zurueck(vorher)
        raise ModellwegFehler(str(fehler)) from fehler

    return stand()


def _zurueck(vorher: dict[str, str | None]) -> None:
    for schluessel, wert in vorher.items():
        if wert is not None:
            _config.set(schluessel, wert)
