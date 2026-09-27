"""Find annotation values containing the requested component.

Pipe-separated values can encode ambiguity, such as Recht|Rechte, or
combined annotations, such as ADV|Degree=Pos. Report component membership
without changing the semantics of the original query."""

from __future__ import annotations

import os

import numpy as np
import pytest

from candyconc.core.component_types import (
    Bestandteile,
    bericht,
    bestandteile_fuer,
    zerlege,
)

_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")


class _Lexikon:
    """Ein Lexikon aus einer Liste, ohne Index."""

    def __init__(self, eintraege):
        self._namen = [""] + [n for n, _f in eintraege]
        self._freqs = [0] + [int(f) for _n, f in eintraege]
        self.vocab_size = len(self._namen)

    def get_strings_for_ids(self, ids):
        return [self._namen[int(i)] for i in np.asarray(ids).tolist()]

    def get_freqs_for_ids(self, ids):
        return np.array([self._freqs[int(i)] for i in np.asarray(ids).tolist()],
                        dtype=np.int64)

    def get_id(self, wort):
        try:
            return self._namen.index(str(wort))
        except ValueError:
            return 0


class TestZerlegen:
    def test_zwei_teile(self):
        assert zerlege("Recht|Rechte") == ["Recht", "Rechte"]

    def test_drei_teile(self):
        assert zerlege("Pol|Pole|Polen") == ["Pol", "Pole", "Polen"]

    def test_sentinel_zerfaellt_in_einen_teil(self):
        """``|LBR|`` ist eine Marke, keine Verbindung zweier Werte."""
        assert zerlege("|LBR|") == ["LBR"]

    def test_ohne_trenner(self):
        assert zerlege("Migration") == ["Migration"]

    def test_blosser_trenner(self):
        assert zerlege("|") == []


class TestOhneIndex:
    LEX = _Lexikon([
        ("Recht", 110210),
        ("Recht|Rechte", 24898),
        ("Rechte", 16),
        ("Doktor", 224),
        ("Doktor|Dr.", 639263),
        ("Migration", 3077),
        ("|LBR|", 609),
        ("Pol|Pole|Polen", 985),
        ("Polen", 40),
    ])

    def test_der_fall_aus_dem_korpus(self):
        b = bestandteile_fuer(self.LEX, "Recht", attribut="lemma")
        assert b.direkt == 110210
        assert b.masse == 24898
        assert [n for n, _f in b.typen] == ["Recht|Rechte"]
        assert round(b.fehlanteil, 3) == 0.184

    def test_ein_wert_ohne_verbundtypen_meldet_nichts(self):
        """Positive Klasse: sonst waere ein 'immer etwas'-Melder gruen."""
        b = bestandteile_fuer(self.LEX, "Migration", attribut="lemma")
        assert not b
        assert b.typen == ()
        assert bericht(b) == {}

    def test_ein_wert_ohne_eigenen_typ_wird_trotzdem_gefunden(self):
        """``Dr.`` gibt es nicht als Typ, nur im Verbund."""
        b = bestandteile_fuer(self.LEX, "Dr.", attribut="lemma")
        assert b.direkt == 0
        assert b.masse == 639263
        assert b.fehlanteil == 1.0

    def test_dreiteiler_zaehlen_fuer_jeden_teil(self):
        for teil in ("Pol", "Pole", "Polen"):
            b = bestandteile_fuer(self.LEX, teil, attribut="lemma")
            assert "Pol|Pole|Polen" in [n for n, _f in b.typen], teil

    def test_der_sentinel_ist_kein_verbundtyp(self):
        """Sonst haette jeder Zeilenumbruch-Index falsche Geschwister."""
        assert not bestandteile_fuer(self.LEX, "LBR", attribut="word")

    def test_ein_wert_mit_trenner_hat_keine_geschwister_dieser_art(self):
        assert not bestandteile_fuer(self.LEX, "Recht|Rechte", attribut="lemma")

    def test_leerer_wert(self):
        assert not bestandteile_fuer(self.LEX, "", attribut="lemma")

    def test_das_muster_maskiert_den_trenner(self):
        b = bestandteile_fuer(self.LEX, "Recht", attribut="lemma")
        assert b.muster() == r"(Recht|Recht\|Rechte)"

    def test_das_muster_maskiert_auch_den_punkt(self):
        """``Dr.`` als Literal, nicht als Regex-Metazeichen."""
        b = bestandteile_fuer(self.LEX, "Doktor", attribut="lemma")
        assert r"Doktor\|Dr\." in b.muster()

    def test_das_muster_laesst_den_wert_weg_wenn_es_ihn_nicht_gibt(self):
        b = bestandteile_fuer(self.LEX, "Dr.", attribut="lemma")
        assert b.muster() == r"(Doktor\|Dr\.)"

    def test_bericht_fuehrt_die_zahlen_und_keinen_fliesstext(self):
        r = bericht(bestandteile_fuer(self.LEX, "Recht", attribut="lemma"))
        assert r["direkt"] == 110210
        assert r["in_verbundtypen"] == 24898
        assert r["verbundtypen_gesamt"] == 1
        assert r["verbundtypen"] == [{"typ": "Recht|Rechte", "frequenz": 24898}]
        assert all(not isinstance(v, str) or "|" in v or v in ("Recht", "lemma")
                   for v in r.values() if isinstance(v, str))

    def test_bericht_kappt_die_liste_und_sagt_die_gesamtzahl(self):
        lex = _Lexikon([("x", 1)] + [(f"x|y{i}", 10 - i) for i in range(9)])
        r = bericht(bestandteile_fuer(lex, "x", attribut="lemma"), hoechstens=3)
        assert len(r["verbundtypen"]) == 3
        assert r["verbundtypen_gesamt"] == 9
        assert [t["frequenz"] for t in r["verbundtypen"]] == [10, 9, 8]


@pytest.mark.skipif(
    not (_INDEX_PATH and os.path.isdir(_INDEX_PATH)),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)
class TestAmEchtenIndex:
    def test_die_masse_stimmt_gegen_die_lexikonfrequenzen(self):
        from candyconc.core.fast_index_backend import FastIndexBackend

        b = FastIndexBackend(_INDEX_PATH)
        gefunden = 0
        for attribut in ("word", "lemma", "pos", "morph"):
            lex = getattr(b.lexicons, attribut, None)
            if lex is None or int(getattr(lex, "vocab_size", 0)) <= 1:
                continue
            ids = np.arange(1, int(lex.vocab_size), dtype=np.int64)
            namen = [str(x) for x in lex.get_strings_for_ids(ids)]
            freqs = np.asarray(lex.get_freqs_for_ids(ids), dtype=np.int64)
            teile = {}
            for name, freq in zip(namen, freqs.tolist()):
                if "|" not in name:
                    continue
                zerlegt = zerlege(name)
                if len(zerlegt) < 2:
                    continue
                for t in zerlegt:
                    teile[t] = teile.get(t, 0) + int(freq)
            for wert, masse in list(teile.items())[:25]:
                befund = bestandteile_fuer(lex, wert, attribut=attribut)
                assert befund.masse == masse, (attribut, wert)
                gefunden += 1
        if gefunden == 0:
            pytest.skip("dieser Index fuehrt keine Verbundtypen")

    def test_keine_masse_uebersteigt_die_korpusgroesse(self):
        from candyconc.core.fast_index_backend import FastIndexBackend

        b = FastIndexBackend(_INDEX_PATH)
        lex = b.lexicons.lemma
        gesamt = int(lex.total_tokens)
        for wert in ("Recht", "Doktor", "Fall", "Stelle", "ADV"):
            befund = bestandteile_fuer(lex, wert, attribut="lemma")
            assert befund.direkt + befund.masse <= gesamt
