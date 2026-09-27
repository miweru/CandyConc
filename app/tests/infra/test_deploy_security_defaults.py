"""Sicherheitsprofil-Anker mit bewusster Asymmetrie.

Deploy-Artefakte (Dockerfile, systemd-Unit) sind Operator-Material und muessen
release-gehaertet ausgeliefert werden. Das Source-Tree-Profil in
``pyproject.toml [tool.candyconc]`` ist dagegen der Einzelplatz-Erststart:
``release`` dort wuerde ``validate_release_security()`` beim allerersten Start
(``make demo``, README-Quickstart) mit den gepackten Beispielnutzern hart
crashen — der P1-Befund des Produktaudits 2026-07.
"""
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib


APP_ROOT = Path(__file__).resolve().parents[2]

# Spiegel der Alias-Kanonisierung aus candyconc.config (Feld-Validator fuer
# CANDYCONC_SECURITY_MODE) — bewusst dupliziert, damit dieser Anker auch bei
# einem Import-Fehler in candyconc.config noch aussagekraeftig ist.
_MODE_ALIASES = {
    "dev": "local_dev_unsafe",
    "local": "local_dev_unsafe",
    "local_dev": "local_dev_unsafe",
    "unsafe": "local_dev_unsafe",
    "local_dev_unsafe": "local_dev_unsafe",
    "release": "release",
    "production": "release",
    "prod": "release",
}


def _canonical_mode(raw: object) -> str:
    return _MODE_ALIASES.get(str(raw).strip().lower().replace("-", "_"), "invalid")


def test_deploy_artifacts_default_to_release_security() -> None:
    dockerfile = (APP_ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    service = (APP_ROOT / "deploy" / "candyconc.service").read_text(encoding="utf-8")

    for text in (dockerfile, service):
        assert "CANDYCONC_SECURITY_MODE=release" in text
        assert "CANDYCONC_ENABLE_RBAC=0" not in text
        assert "local_dev_unsafe" not in text

    assert "ARG CANDYCONC_ENABLE_RBAC=1" in dockerfile
    assert 'Environment="CANDYCONC_ENABLE_RBAC=1"' in service


def test_shipped_source_profile_boots_without_user_bootstrap() -> None:
    """Erststart-Anker: shipped [tool.candyconc] darf nie release+Beispielnutzer sein."""
    data = tomllib.loads((APP_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    # A checkout may carry a [tool.candyconc] profile. Without one (installed
    # package, exported repository) the field defaults are the first-start
    # profile and must meet the same rule.
    cfg = data.get("tool", {}).get("candyconc")
    if cfg is None:
        from candyconc.config import AppConfig

        fields = AppConfig.model_fields
        cfg = {
            "CANDYCONC_SECURITY_MODE": fields["CANDYCONC_SECURITY_MODE"].default,
            "CANDYCONC_ENABLE_RBAC": fields["CANDYCONC_ENABLE_RBAC"].default,
        }

    mode = _canonical_mode(cfg.get("CANDYCONC_SECURITY_MODE", "local_dev_unsafe"))
    packaged_users = APP_ROOT / "config" / "users.json"

    if mode == "release":
        # release im Source-Tree ist nur zulaessig, wenn keine gepackten
        # Beispielnutzer mitgeliefert werden — sonst crasht jeder Erststart.
        assert not packaged_users.exists(), (
            "pyproject [tool.candyconc] liefert release-Modus zusammen mit der "
            "gepackten config/users.json aus: validate_release_security() lehnt "
            "Beispielnutzer ab und JEDER Erststart (make demo, README-Quickstart) "
            "endet in 'Application startup failed'."
        )
    else:
        assert mode == "local_dev_unsafe", (
            f"Unbekannter Security-Modus im shipped Profil: {cfg.get('CANDYCONC_SECURITY_MODE')!r}"
        )
        assert cfg.get("CANDYCONC_ENABLE_RBAC") is False, (
            "Das lokale Einzelplatz-Profil erwartet CANDYCONC_ENABLE_RBAC = false; "
            "RBAC ohne Release-Modus kombiniert Benutzerverwaltung mit Beispielnutzern."
        )
