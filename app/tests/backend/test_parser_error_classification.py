"""Malformed queries are classified as input errors rather than server failures."""

from __future__ import annotations

import re
import pathlib

import pytest

from candyconc.services.backend.query_count import _is_query_user_error

#: Jede Meldung, die ``domain/query_parser.py`` werfen kann, mit einem
#: Beispielwert fuer die Platzhalter.
PARSERMELDUNGEN = [
    "Unexpected token: (",
    "Unexpected token: )",
    "Unexpected end of input",
    "Expected relation name",
    "Invalid attribute filter",
    'Expected "]"',
]


@pytest.mark.parametrize("meldung", PARSERMELDUNGEN)
def test_jede_parsermeldung_gilt_als_aufruferfehler(meldung):
    assert _is_query_user_error(meldung), meldung


def test_die_liste_deckt_den_parser_wirklich_ab():
    """Der Parser darf keine Form werfen, die hier fehlt.

    Ohne diese Pruefung waere die Parametrisierung oben nur eine Kopie
    meiner Annahmen. Sie liest die Formen aus der Quelle.
    """
    quelle = pathlib.Path(
        "src/candyconc/domain/query_parser.py"
    ).read_text(encoding="utf-8")
    formen = set(re.findall(r'raise ValueError\(f?"([^"]+)"', quelle))
    assert formen, "keine ValueError-Formen gefunden, Pfad falsch?"
    # ``Expected {value}`` hat genau EINEN Aufrufer, und der uebergibt ein
    # Satzzeichen. Der Platzhalter wird deshalb aus den echten Aufrufen
    # gefuellt, nicht mit einem erfundenen Wort: sonst prueft der Test
    # eine Meldung, die der Parser nie wirft, und die Klassifikation
    # muesste dafuer breiter sein als noetig.
    erwartete = re.findall(r'self\._expect\("([^"]+)"\)', quelle)
    assert erwartete, "keine _expect-Aufrufe gefunden"
    for form in formen:
        if "{value}" in form:
            beispiele = [form.replace("{value}", w) for w in erwartete]
        else:
            beispiele = [re.sub(r"\{[^}]*\}", "x", form)]
        for beispiel in beispiele:
            assert _is_query_user_error(beispiel), (form, beispiel)


def test_ein_echter_serverfehler_bleibt_einer():
    # POSITIVE KLASSE. Ohne sie waere ein Klassifikator gruen, der ALLES
    # zum Aufruferfehler erklaert und damit echte Serverfehler als 400
    # verharmlost.
    for meldung in (
        "Index nicht erreichbar",
        "OSError: disk full",
        "Segmentation fault",
    ):
        assert not _is_query_user_error(meldung), meldung
