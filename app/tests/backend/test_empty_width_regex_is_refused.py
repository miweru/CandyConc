"""Ein Muster, das nur die leere Zeichenfolge trifft, wird abgelehnt.

K8-Lauf A und K11-Lauf A, Frage 20 (r5b-konkordanz-belegqualitaet): das
Modell suchte die Pipe-Tabellen im Korpus mit [word="|"]. Im Regex ist "|"
eine leere Alternative, die Zaehlung kam still mit 0 zurueck, und beide
Antworten meldeten fuer die Pipe-Tabelle 0 Treffer. Am Testindex stehen
272.832 Pipe-Token ([word="\\|"]). Wie beim Stern nennt die Absage die
Schreibung des Zeichens selbst.
"""

import numpy as np
import pytest

from candyconc.services.backend import server as srv
from cqlhpc import predicates


class _Lex:
    """Zwei Typen, darunter die Pipe selbst."""

    id_to_str = ["", "|", "Tabelle"]

    def get_freq(self, tid):
        return 7


def _absage(muster: str) -> str:
    with pytest.raises(ValueError) as fehler:
        predicates._regex_to_type_ids(muster, _Lex())
    return str(fehler.value)


def test_die_pipe_wird_mit_ihrer_schreibung_abgelehnt():
    text = _absage("|")
    assert "leere Zeichenfolge" in text, text
    assert '[word="\\|"]' in text, text


def test_die_geschuetzte_pipe_trifft_das_zeichen():
    ids = predicates._regex_to_type_ids("\\|", _Lex())
    assert ids.tolist() == [1]


def test_ein_reiner_anker_bekommt_keinen_schreibvorschlag():
    text = _absage("^$")
    assert "leere Zeichenfolge" in text, text
    assert "schreibt sich" not in text, text


def test_eine_alternative_mit_inhalt_bleibt_ein_muster():
    ids = predicates._regex_to_type_ids("Tabelle|", _Lex())
    assert isinstance(ids, np.ndarray)
    assert ids.tolist() == [2]


def test_die_absage_ist_ein_eingabefehler():
    assert srv._is_query_user_error(_absage("|"))
