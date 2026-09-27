"""tests/ai directory conftest: pin the REAL backend module tree early.

Several modules in this directory execute real-module loaders at import
(collection) time which temporarily install stub packages under production
names (``candyconc.services``, ``candyconc.services.llm_client``, ...).  If
the real ``candyconc.services.backend.server`` were first imported WHILE such
stubs are active (policy_engine -> backend.__init__ -> server), the server
would permanently bind stub objects (e.g. a fake ``LLMRequestError``) and
tests in other directories would fail in the same pytest process.

Importing the server here — before any tests/ai module is collected — caches
the whole real module tree under its real names, so loader re-imports only
ever hit the cache.  ``tests/ai/test_observability.py`` already imported the
server mid-collection, so this adds no new side effect to ai-only runs.
"""

from __future__ import annotations

try:  # pragma: no cover - environments without backend deps skip the pin
    import candyconc.services.backend.server  # noqa: F401
except Exception:  # pragma: no cover
    pass


import pytest  # noqa: E402


@pytest.fixture
def earlier_answer_path(monkeypatch):
    """Der fruehere Antwortweg mit Verifikation und Neuaufbau (CANDYCONC_DEUTUNGSPFAD=0).

    Seit dem 2026-09-26 ist der Deutungspfad die Vorgabe.
    Proben, die Verifikation, Neuaufbau oder deren Texte pruefen, setzen den
    frueheren Weg ausdruecklich. Er bleibt fuer Vergleichsmessungen zuschaltbar.
    """
    monkeypatch.setenv("CANDYCONC_DEUTUNGSPFAD", "0")
