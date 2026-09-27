"""Text emitted with interpretation submission becomes the answer draft."""

from candyconc.candyconc_copilot.deutung_abgeben import merke_abgabe_text


class _Orch:
    pass


def _aufruf(name):
    return {"id": "c1", "type": "function", "function": {"name": name, "arguments": "{}"}}


def test_text_mit_abgabe_wird_gemerkt():
    o = _Orch()
    text = "Ergebnis in einem Satz: " + "recht ist der stärkste Menschen-Marker. " * 8
    merke_abgabe_text(o, [_aufruf("deutung_abgeben")], text)
    assert o._ra_abgabe_entwurf == text.strip()


def test_ohne_abgabe_oder_ohne_text_nichts():
    o = _Orch()
    merke_abgabe_text(o, [_aufruf("query_count")], "x" * 500)
    merke_abgabe_text(o, [_aufruf("deutung_abgeben")], "kurz")
    assert not hasattr(o, "_ra_abgabe_entwurf")

