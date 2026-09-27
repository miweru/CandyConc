"""Typed CQL errors for empty conditions and evaluation failures.

Both classes inherit ValueError for existing exception handlers. Callers
distinguish the conditions by type so translated or revised error messages
do not change whether a request returns zero hits or fails."""

from __future__ import annotations

# User-visible cqlhpc messages are German and English pairs. This module is
# the only cqlhpc edge to ``candyconc.i18n``: the other cqlhpc modules import
# ``lt`` from here. Without candyconc the German text is used alone.
try:
    from candyconc.i18n import lt
except ImportError:  # pragma: no cover - cqlhpc used without candyconc
    def lt(de: str, en: str) -> str:  # type: ignore[misc]
        return de


class EmptyMatchError(ValueError):
    """Die Bedingung ist wohlgeformt und trifft in diesem Korpus nichts.

    Ein Aufrufer darf daraus eine leere Treffermenge machen, ein Zweig einer
    Alternation darf sie verschlucken.
    """


class UnresolvableConditionError(ValueError):
    """Der Wert der Bedingung laesst sich nicht in Lexikon-Ids uebersetzen.

    Das ist ein Form- oder Programmierfehler, kein Null-Ergebnis.
    """


# Message templates of the two classes above, shared by engine and predicates.
NO_HITS = lt(
    "CQL Bedingung liefert keine Treffer: {attr}{op}{value}",
    "CQL condition has no hits: {attr}{op}{value}",
)
UNRESOLVABLE = lt(
    "CQL Bedingung nicht auflösbar: {attr}{op}{value}",
    "CQL condition cannot be resolved: {attr}{op}{value}",
)
UNKNOWN_ATTRIBUTE = lt("Unbekanntes Attribut in CQL: {attr}", "Unknown attribute in CQL: {attr}")

# Shared by the editor diagnostics and the engine, which raises it.
BRANCH_LOCAL_WHERE = lt(
    "Branch-lokales where() ist im Release-Modus eingeschraenkt: where() muss als "
    "queryweiter Wrapper um den gesamten Ausdruck stehen.",
    "Branch-local where() is restricted in this release: where() must stand as a "
    "query-wide wrapper around the entire expression.",
)


__all__ = [
    "BRANCH_LOCAL_WHERE",
    "EmptyMatchError",
    "NO_HITS",
    "UNKNOWN_ATTRIBUTE",
    "UNRESOLVABLE",
    "UnresolvableConditionError",
    "lt",
]
