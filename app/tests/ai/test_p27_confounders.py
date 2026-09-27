# -*- coding: utf-8 -*-
"""P2.7: die Konfundierer reisen mit dem Docset.

Methoden-Invariante 4 (``prompt_layout.py``) verlangt, vor der Deutung eines
Kontrasts Register, Dokumentlaenge und Teilkorpusgroessen zu benennen. Kein
Werkzeug lieferte sie. Bei "AfD gegen GRUENE" ist die
Dokumentlaengenverteilung die erste Rueckfrage einer Fachperson: zwei Docsets
gleicher Tokenzahl koennen aus 40 langen oder aus 4000 kurzen Texten bestehen,
und derselbe Kontrast bedeutet dann etwas anderes.

Kein eigenes Werkzeug, sondern ein Feld an ``create_docset``. Zwei Gruende,
beide aus den Vorgaben dieses Harness: der statische Prompt-Kern hat ein
hartes Limit von 31.000 Zeichen, und ein zusaetzlicher Werkzeugaufruf je
Kontrast waere genau die Aufblaehung durch Absicherungsturns, die vermieden
werden soll. Wer ein Docset baut, braucht die Zahlen ohnehin.
"""

from __future__ import annotations

import os

import pytest
from jsonschema import validate as _json_validate

from tests.ai.test_tool_wrappers_parity_r5 import _TW as tw
from tests.ai.test_tool_wrappers_parity_r5 import active_index  # noqa: F401

_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")


class TestVertrag:
    def test_schema_deklariert_das_profil(self):
        props = tw.CREATE_DOCSET_RESPONSE["properties"]
        assert "profile" in props
        profil = props["profile"]["properties"]
        assert set(profil) == {"doc_len", "axes", "source_texts"}
        assert set(profil["doc_len"]["properties"]) == {
            "min",
            "median",
            "mean",
            "max",
        }

    def test_prompt_dokumentiert_das_profil(self):
        from candyconc.candyconc_copilot import prompts as P

        doc = " ".join(P.TOOLS_DOC.split())
        # doc_len counts tokens including punctuation, and its unit is documented.
        assert "profile:{doc_len:{min,median,mean,max} in Token,axes,source_texts?}" in doc
        assert "KONFUNDIERER" in doc


@pytest.mark.skipif(
    not (_INDEX_PATH and os.path.isdir(_INDEX_PATH)),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)
class TestVerhaltenAmIndex:
    def _profil(self, wert: str) -> dict:
        antwort = tw.create_docset_tool(filters={"split": wert})
        _json_validate(antwort, tw.CREATE_DOCSET_RESPONSE)
        assert "profile" in antwort, "Feld deklariert, aber nicht geliefert"
        return antwort["profile"]

    def test_profil_traegt_echte_zahlen(self, active_index):  # noqa: F811
        profil = self._profil("test")
        laengen = profil["doc_len"]
        assert laengen["min"] > 0
        assert laengen["max"] >= laengen["min"]
        assert laengen["min"] <= laengen["median"] <= laengen["max"]
        assert laengen["min"] <= laengen["mean"] <= laengen["max"]
        assert profil["axes"], "Achsen strukturell leer"

    def test_der_laengen_konfundierer_wird_wirklich_sichtbar(self, active_index):  # noqa: F811
        """Ohne positive Klasse waere das Feld Dekoration.

        Am Testindex unterscheiden sich die beiden Splits deutlich in der
        Dokumentlaenge, und genau das war vorher aus keiner Antwort ablesbar.
        """
        test = self._profil("test")["doc_len"]
        train = self._profil("train")["doc_len"]
        assert (test["max"], train["max"]) == (787, 69)
        assert test["max"] > 10 * train["max"]

    def test_dokument_id_achsen_bleiben_draussen(self, active_index):  # noqa: F811
        """Positive Klasse: der Index HAT solche Felder, sonst waere der Test leer."""
        felder = set(active_index.metadata_fields() or [])
        assert {"doc_id", "path", "origin_id"} <= felder, (
            "Index ohne Dokument-ID-Felder, die Ausschlusspruefung waere vakuum"
        )
        achsen = set(self._profil("test")["axes"])
        for laut in ("doc_id", "path", "origin_id", "origin_doc_id", "reference_hash"):
            assert laut not in achsen, laut
        # Und die echten Achsen sind da.
        assert "register" in achsen
        assert "split" in achsen

    def test_konstante_achse_wird_als_konstant_benannt(self, active_index):  # noqa: F811
        achsen = self._profil("test")["axes"]
        assert achsen["split"] == "konstant: test"
        assert achsen["register"].startswith("konstant: ")
