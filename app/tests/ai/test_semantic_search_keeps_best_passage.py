# -*- coding: utf-8 -*-
"""Die Passagensuche behaelt je Dokument die staerkste Passage, nicht die schwaechste.

Methodenbefund B9 der Session CandyConc Paper (2026-09-26): beim
Zusammenfuehren mit den lexikalischen Saatzeilen ueberschrieb die Suche je
Dokument mit der jeweils letzten Zeile. Die Vektortreffer kommen absteigend
nach Aehnlichkeit, also blieb die schwaechste Passage stehen.
"""

from __future__ import annotations

from candyconc.candyconc_copilot.analysis import best_passage_per_document


def test_the_strongest_passage_of_a_document_stays():
    rows = [{"doc_id": 1, "score": 0.91, "kw": "stark"},
            {"doc_id": 2, "score": 0.80, "kw": "mittel"},
            {"doc_id": 1, "score": 0.42, "kw": "schwach"}]
    lexical = [{"doc_id": 3, "score": 0.0, "kw": "lexikalisch"}]
    merged = {r["doc_id"]: r["kw"] for r in best_passage_per_document(lexical, rows)}
    assert merged == {1: "stark", 2: "mittel", 3: "lexikalisch"}


def test_a_vector_hit_replaces_the_lexical_seed_of_its_document():
    rows = [{"doc_id": 3, "score": 0.7, "kw": "vektor"}]
    lexical = [{"doc_id": 3, "score": 0.0, "kw": "lexikalisch"}]
    assert [r["kw"] for r in best_passage_per_document(lexical, rows)] == ["vektor"]
