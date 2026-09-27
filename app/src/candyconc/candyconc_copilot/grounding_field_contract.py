# -*- coding: utf-8 -*-
"""Select the result fields each tool must expose to the model.

A shared preference list followed by an alphabetical remainder can hide
effect sizes, intervals or denominators while retaining redundant measures.
Each contract therefore supplies the complete field selection. The requested
sort measure is added through ``required_keys`` when it is not already listed.
"""

from __future__ import annotations

from typing import Mapping, Sequence

#: Je Werkzeug die Felder, die in die Modellsicht gehoeren, in dieser
#: Reihenfolge. Wer hier etwas streicht, nimmt es dem Modell weg.
FELDVERTRAEGE: Mapping[str, tuple[str, ...]] = {
    # Keyness. ``direction`` bleibt, weil claim_rules/keyness.py es AUS DER
    # OBERFLAECHE liest, um Richtungsaussagen zu pruefen. ``log_ratio`` ist
    # die Effektstaerke, die _KEYNESS_METRIC_EVIDENCE_PATTERN als Beleg
    # erwartet und bisher nie zu sehen bekam. ``diff_per_million`` faellt
    # weg: es ist die Differenz der beiden Raten, die jetzt beide dastehen,
    # und es war die Stelle, an der das Modell nachweislich
    # "log_ratio minus 2345,3 pmw" schrieb, waehrend es darauf zeigte.
    "keyness": (
        "word",
        "direction",
        "target_freq",
        "reference_freq",
        "target_per_million",
        "reference_per_million",
        # diff_per_million bleibt, obwohl es die Differenz der beiden Raten
        # darueber ist und obwohl das Modell nachweislich einmal
        # "log_ratio minus 2345,3 pmw" schrieb, waehrend es darauf zeigte.
        # Es traegt die gerenderte Beleg-Tabelle der gerichteten
        # Keyness-Ergebnisse. Es zu streichen haette Produktverhalten
        # abgeschaltet, und das ist teurer als die Redundanz. Gegen die
        # Verwechslung hilft die Feld-Label-Pruefung, nicht das Verstecken.
        "diff_per_million",
        # ll_signed ist das VORGABE-Sortiermass und traegt das Vorzeichen der
        # Richtung. Es gehoert in den Vertrag, nicht nur ueber required_keys:
        # die Faktenbildung fuer gerichtete Keyness-Ergebnisse liest es aus
        # der Oberflaeche, und ohne es entfiel der ganze Abschnitt
        # "Sichtbare gerichtete Keyness-Ergebnisse" aus der Antwort. Ein
        # Vertrag, der Darstellung regelt, darf keine Auswertung abschalten.
        "ll_signed",
        "log_ratio",
        # Expose the confidence interval requested by the contrast recipe.
        "log_ratio_ci_low",
        "log_ratio_ci_high",
        "lrc",
        "q_value",
        "low_reliability",
        # Expose each spelling's contribution to a folded class so that
        # sentence-initial capitalization remains visible.
        "surface_variants",
    ),
    # Kollokationen. ``f2`` ist die Eigenfrequenz des Kollokators: ohne sie
    # laesst sich weder beurteilen, ob ein hoher logDice von einem seltenen
    # oder einem haeufigen Wort kommt, noch der Wert nachrechnen. ``expected``
    # macht die Kontingenztafel pruefbar. mi3, mi, t und ll fallen weg, vier
    # Masse derselben Familie sind keine vier Auskuenfte.
    "collocate_stats": (
        "rank",
        "word",
        "f",
        "f2",
        "expected",
        "logdice",
        "lrc",
        "log_ratio",
    ),
    # Use the same n-gram field order in the model view and evidence package:
    # feature, raw counts, rates and difference. Rate denominators belong in
    # the adjacent populations table for each n-gram order.
    "ngram_contrast": (
        "ngram",
        "n",
        "freq_target",
        "freq_reference",
        "per_million_target",
        "per_million_reference",
        "diff_per_million",
    ),
    # Keep the grouping value and total visible when query_count adds
    # intervals and hit-distribution fields to each breakdown row.
    "query_count": (
        "wert",
        "total",
        "per_million",
        "per_million_ci",
        "share",
        "share_ci",
        "docs_with_hits",
        "source_texts_with_hits",
        "docs",
        "tokens",
        # Only present for a row that exceptionally mixes multiple procedures.
        "procedures",
    ),
}


def vertrag_fuer(werkzeug: str | None) -> tuple[str, ...] | None:
    """Der Feldvertrag dieses Werkzeugs, oder ``None``.

    ``None`` heisst: die bisherige gemeinsame Vorzugsliste gilt weiter. Das
    ist fuer Werkzeuge ohne eigene Methoden-Invarianten richtig und nicht
    dasselbe wie ein stiller Rueckfall, denn ein Werkzeug MIT Vertrag
    bekommt ihn an jeder Naht (siehe test_field_contract_reaches_every_seam).
    """
    if not werkzeug:
        return None
    return FELDVERTRAEGE.get(str(werkzeug))


def felder_der_modellsicht(
    werkzeug: str | None,
    zeile: Mapping[str, object],
    *,
    pflicht: Sequence[str] = (),
) -> list[str] | None:
    """Die Feldnamen der Modellsicht, in Vertragsreihenfolge.

    ``pflicht`` ist das gewaehlte Sortiermass: es steht vorn, damit die
    Zahl, nach der gerankt wurde, nie fehlt, auch wenn der Vertrag sie
    nicht fuehrt.
    """
    vertrag = vertrag_fuer(werkzeug)
    if not vertrag:
        return None
    vorn = [
        vorhanden
        for verlangt in pflicht
        for vorhanden in zeile
        if str(vorhanden).casefold() == str(verlangt).casefold()
    ]
    return list(dict.fromkeys([*vorn, *(f for f in vertrag if f in zeile)]))
