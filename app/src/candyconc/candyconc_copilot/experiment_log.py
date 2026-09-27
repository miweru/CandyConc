# -*- coding: utf-8 -*-
"""Was gefragt wurde, was herauskam, und was daraus folgt.

ANFORDERUNG des Auftraggebers vom 2026-08-31
(docs/wuensche/deutungsevaluation.md, Abschnitt 5):

    Das KI-Gutachten kann erst ein TLDR erstellen mit der Interpretation
    der Ergebnisse, dann zeigt es uns an, welche Experimente es
    durchgefuehrt hat und was da rausging und was man aus welchem
    einzelnen Experiment folgen kann oder soll.

WAS DIESE DATEI LEISTET UND WAS NICHT. Sie rendert die EXPERIMENTE, also
den Teil, den der Harnisch selbst weiss: welches Werkzeug mit welchen
Parametern lief und welche Zahl herauskam. Das ist deterministisch und
kostet keinen Modellaufruf.

Sie rendert NICHT die Folgerung. Was aus einem Experiment folgt, ist eine
Deutung, und die ist Sache des Modells. Ein Harnisch, der sie erzeugt,
wuerde genau den Fehler wiederholen, gegen den diese Umstellung gebaut
ist: Form ohne Inhalt.

WAS SIE ERSETZT. Der bisherige Methodensteckbrief listete Parameter:
"Abfragemodus cqlf, Attribut explicit_in_query, Kontextbreite 3, maximal
angeforderte Zeilen 1". Eine Fachperson liest daraus nicht, WAS gemessen
wurde. Gemessen an zwei Live-Antworten vom 2026-08-31 machte dieser
Anhang 56,6 Prozent des ausgelieferten Textes aus, ohne ein einziges
Ergebnis zu nennen.

Der Unterschied in einer Zeile:

    vorher   KWIC: Abfragemodus cqlf, Attribut explicit_in_query,
             Kontextbreite 5, maximal angeforderte Zeilen 1, Treffer 0
    nachher  2. Suche [word="nicht"] [word="nur"] [word="sondern"]
             [word="auch"] -> 0 Treffer
"""

from __future__ import annotations

import re

from typing import AbstractSet, Any, List, Mapping, Optional, Sequence

from candyconc.answer_language import choose as _t, format_int, yes_no
from .evidence_access import belegflaeche, feld

#: Heading of the log, per answer language (candyconc/answer_language.py).
UEBERSCHRIFT_DE = "### Experimente"
UEBERSCHRIFT_EN = "### Experiments"

#: Wie ein Werkzeug in einem Bericht heisst, nicht wie es im Code heisst.
_WERKZEUGNAMEN: Mapping[str, str] = {
    "query_count": "Trefferzahl",
    "run_cqlf_query": "Suche",
    "frequency_list": "Frequenzliste",
    "collocate_stats": "Kollokationsprofil",
    "contrast_collocates": "Kollokationskontrast",
    "compare_collocates": "Kollokationskontrast Mensch gegen KI",
    "keyness": "Keyness",
    "ngram_frequency": "N-Gramm-Frequenz",
    "ngram_contrast": "N-Gramm-Kontrast",
    "dispersion_offsets": "Dispersion",
    "word_sketch": "Grammatisches Profil",
    "lexical_diversity": "Lexikalische Vielfalt",
    "metadata_values": "Metadateninventar",
    "create_docset": "Teilkorpus gebildet",
    "document_text": "Volltext gelesen",
    "document_search": "Dokumentsuche",
    "similar_words": "Distributioneller Thesaurus",
    "semantic_search": "Semantische Suche",
}
_WERKZEUGNAMEN_EN: Mapping[str, str] = {
    "query_count": "Hit count",
    "run_cqlf_query": "Search",
    "frequency_list": "Frequency list",
    "collocate_stats": "Collocation profile",
    "contrast_collocates": "Collocation contrast",
    "compare_collocates": "Collocation contrast human against AI",
    "keyness": "Keyness",
    "ngram_frequency": "N-gram frequency",
    "ngram_contrast": "N-gram contrast",
    "dispersion_offsets": "Dispersion",
    "word_sketch": "Word sketch",
    "lexical_diversity": "Lexical diversity",
    "metadata_values": "Metadata inventory",
    "create_docset": "Subcorpus built",
    "document_text": "Full text read",
    "document_search": "Document search",
    "similar_words": "Similar words",
    "semantic_search": "Semantic search",
}

#: Woran ein Experiment gestellt wurde. Reihenfolge ist Lesereihenfolge.
#:
#: ``label`` steht dabei, weil ein Teilkorpus ohne seinen Namen nicht
#: zuzuordnen ist. Ohne ihn las sich das Protokoll als vier gleiche
#: Zeilen ("Teilkorpus gebildet -> 5.000 Dokumente"), und der Leser
#: musste im Methodensteckbrief nachschlagen, welche davon die
#: menschliche Seite war.
_GEGENSTAND = ("requested_term", "effective_term", "label", "query", "term")

#: Was dabei herauskam, mit dem Wort, das die Zahl traegt.
_ERGEBNIS: tuple[tuple[str, str], ...] = (
    ("total", "Treffer"),
    ("result_count", "Zeilen"),
    ("node_frequency", "Knotentreffer"),
    ("doc_count", "Dokumente"),
    ("token_count", "Token"),
    ("total_hits", "Treffer"),
    ("n_documents", "Dokumente"),
    ("dp", "DP"),
    ("dpnorm", "DPnorm"),
    ("range", "Range"),
    ("ttr", "TTR"),
    ("sttr", "STTR"),
    ("periods_total", "Perioden"),
    ("rows_seen", "Zeilen"),
)
_ERGEBNISWORT_EN: Mapping[str, str] = {
    "Treffer": "hits",
    "Zeilen": "rows",
    "Knotentreffer": "node hits",
    "Dokumente": "documents",
    "Token": "tokens",
    "Perioden": "periods",
    "Typen": "types",
    "N-Gramm-Typen": "n-gram types",
    "Kandidaten": "candidates",
    "Werte": "values",
    "Token mit Satzzeichen": "tokens including punctuation",
}
_EINZAHL_EN: Mapping[str, str] = {
    "hits": "hit", "rows": "row", "node hits": "node hit", "documents": "document",
    "tokens": "token", "periods": "period", "types": "type", "n-gram types": "n-gram type",
    "candidates": "candidate", "values": "value",
    "tokens including punctuation": "token including punctuation",
}

#: Sechs statt drei (Messung 17): die Synthese spricht ueber Terme
#: tiefer in der Rangliste („sondern", „ein") — je weniger davon
#: sichtbar sind, desto mehr Behauptungen bleiben fuer den Leser
#: unpruefbar. Immer noch keine Tabelle, aber eine belegbare Auswahl.
MAX_SPITZE = 6


def _zahl(wert: Any) -> str:
    if isinstance(wert, bool):
        return yes_no(wert)
    if isinstance(wert, int):
        return format_int(wert)
    if isinstance(wert, float):
        gerundet = round(wert, 4)
        return f"{gerundet:g}" if gerundet or not wert else f"{wert:.3g}"
    return str(wert)


def _gegenstand(flaeche: Mapping[str, Any]) -> str:
    for name in _GEGENSTAND:
        wert = str(flaeche.get(name) or "").strip()
        if wert:
            return wert
    return ""


#: Wo dasselbe Feld je Werkzeug etwas anderes zaehlt.
#:
#: ``total`` heisst bei query_count "Treffer", bei frequency_list aber die
#: Zahl der TYPEN in der vollen Liste. "11.209 Treffer" waere dort schlicht
#: falsch, und eine falsch beschriftete Zahl ist genau die Fehlerklasse,
#: die dieses Projekt als hart fuehrt.
_FELDWORT_JE_WERKZEUG: Mapping[str, Mapping[str, str]] = {
    "frequency_list": {"total": "Typen"},
    "ngram_frequency": {"total": "N-Gramm-Typen"},
    "ngram_contrast": {"total": "N-Gramm-Typen"},
    "keyness": {"total": "Zeilen"},
    "contrast_collocates": {"total": "Kandidaten"},
    "metadata_values": {"total": "Werte"},
    # create_docset counts all tokens including punctuation (token_count is
    # the raw size), keyness on the same subcorpus counts word tokens without
    # punctuation (method_sheet). English probe, run b1: "199.379 Token" here
    # and "174.284 Tokens" there, and the unit did not show the difference.
    "create_docset": {"token_count": "Token mit Satzzeichen"},
}


def _ergebnis(
    flaeche: Mapping[str, Any],
    werkzeug: str = "",
    etiketten: Optional[Mapping[str, str]] = None,
) -> str:
    teile: List[str] = []
    schon: set[str] = set()
    je_werkzeug = _FELDWORT_JE_WERKZEUG.get(werkzeug, {})
    for name, wort in _ERGEBNIS:
        wert = flaeche.get(name)
        if wert in (None, "", [], {}):
            continue
        wort = je_werkzeug.get(name, wort)
        # Dieselbe Bezeichnung nicht zweimal: result_count und rows_seen
        # heissen beide "Zeilen", und "9 Zeilen, 61 Knotentreffer, 9
        # Zeilen" liest sich wie ein Fehler, weil es einer ist.
        if wort in schon:
            continue
        schon.add(wort)
        englisch = _ERGEBNISWORT_EN.get(wort, wort)
        if wert == 1 and not isinstance(wert, bool):
            englisch = _EINZAHL_EN.get(englisch, englisch)
        teile.append(f"{_zahl(wert)} " + _t(wort, englisch))
        if len(teile) >= 3:
            break
    # Messung 23: die Zahl ohne Korpus-Scope liess Modell-Ableitungen am
    # falschen Nenner unpruefbar („45.334 Treffer" — in WELCHEM Docset?).
    scope = str(flaeche.get("docset_id") or flaeche.get("label") or "").strip()
    # query_count and run_cqlf_query store the subcorpus in scope.docset_id.
    # Show its create_docset label, falling back to the ID, so otherwise equal
    # counts from different subcorpora remain distinguishable.
    bereich = flaeche.get("scope")
    if not scope and isinstance(bereich, Mapping):
        kennung = str(bereich.get("docset_id") or "").strip()
        scope = str((etiketten or {}).get(kennung) or kennung)
    if scope and teile:
        teile.append(_t("Docset ", "subcorpus ") + scope)
    return ", ".join(teile)


#: Hoechstens so lang darf eine genannte Zeile sein. Was laenger ist, ist
#: kein Datenpunkt mehr, sondern ein Zitat.
MAX_SPITZE_ZEICHEN = 40

#: WAS ALS GESCHEITERT GILT, positiv aufgezaehlt.
#:
#: Der erste Anlauf fragte ``status != "success"`` und meldete damit
#: JEDEN anderen Status als Scheitern. Im Haus kommen aber mindestens
#: acht Statuswerte vor, davon allein 19 Stellen mit ``ok``. Die volle
#: Suite zeigte es woertlich: "1. dummy → gescheitert: ok". Ein
#: gelungener Aufruf stand als gescheitert in der Antwort, und das ist
#: dieselbe Fehlerklasse, gegen die dieser Anhang gebaut ist.
#:
#: Positiv aufzuzaehlen, was Scheitern IST, ist die sichere Richtung: ein
#: neuer Erfolgsstatus wird dann nicht faelschlich zum Fehler, sondern
#: hoechstens ein neuer Fehlerstatus nicht erkannt. Das ist die
#: harmlosere Haelfte des Irrtums.
GESCHEITERT = frozenset({"error", "failed", "failure", "unavailable", "timeout"})


def _spitze(flaeche: Mapping[str, Any]) -> str:
    """Die stärksten Zeilen, damit das Ergebnis nicht nur eine Zahl ist.

    NUR lexikalische Einheiten: ``word`` aus einer Frequenz- oder
    Kollokationsrangliste, ``ngram`` aus einer n-Gramm-Liste. NICHT ``kw``
    und nicht ``text``.

    Der erste Anlauf nahm auch ``kw``, und damit zog das Protokoll
    Satzfragmente aus einer semantischen Suche in die Antwort, deren
    Evidenz der Kontrakt gerade VERWORFEN hatte
    (test_semantic_report_summarises_visible_semantic_hits hat es
    gefangen). Ein einzelnes Wort aus einer Rangliste ist ein Datenpunkt,
    ein ganzer Satz ist ein Zitat, und Zitate gehoeren der Zitatwache.
    """
    zeilen = flaeche.get("rows")
    if not isinstance(zeilen, list):
        return ""
    namen: List[str] = []
    for zeile in zeilen[:MAX_SPITZE]:
        if not isinstance(zeile, Mapping):
            continue
        wort = str(zeile.get("word") or zeile.get("ngram") or "").strip()
        if wort and len(wort) <= MAX_SPITZE_ZEICHEN:
            # F4 (Sichtbarkeits-Konsistenz): die Frequenz gehoert zum
            # Namen, sonst ist die Zahl im Antworttext nicht auf die
            # eigene Tabelle rueckfuehrbar (F4-Urteil 2026-09-06:
            # "Exp. 1 nennt nur staerkste ohne Zahlen"). Messung 15:
            # Keyness-Zeilen tragen aus demselben Grund ihre Metriken —
            # sonst fuellt das Modell die Luecke mit erfundenen Werten.
            teile: List[str] = []
            frequenz = zeile.get("f") or zeile.get("freq") or zeile.get("frequency")
            if frequenz is not None:
                teile.append(f"f={frequenz}")
            for key in ("per_million", "log_ratio", "q_value", "ll", "score"):
                wert = zeile.get(key)
                if wert is not None:
                    teile.append(f"{key}={wert}")
            eintrag = f"{wort} ({', '.join(teile)})" if teile else wort
            namen.append(eintrag)
    return ", ".join(namen)


#: So lang darf ein Scheiterngrund werden.
MAX_GRUND_ZEICHEN = 140


def _lesbarer_grund(roh: Any) -> str:
    """Der Satz aus einer Fehlermeldung, nicht ihr Umschlag.

    LIVE am 2026-09-01. In einer ausgelieferten Antwort stand:

        4. Keyness → gescheitert: MCP Fehler: {"type":"about:blank",
           "title":"Bad Request","status":400,"detail":"Ziel- und
           Referenz-Docset duerfen keine ge

    Ein rohes Fehler-JSON, mitten im Wort abgeschnitten, weil die erste
    Fassung stumpf bei 120 Zeichen kappte. Der lesbare Teil stand im
    Umschlag ganz hinten und fiel deshalb heraus.

    Hier wird der Umschlag geoeffnet: ``detail``, ``message`` oder
    ``reason`` tragen den Satz, den ein Mensch braucht. Nur wenn nichts
    davon zu finden ist, bleibt der Rohtext, und dann gekuerzt.
    """
    text = str(roh or "").strip()
    if not text:
        return _t("ohne Angabe", "no reason given")
    # Der Umschlag kann irgendwo im Text stehen ("MCP Fehler: {...}").
    start = text.find("{")
    if start >= 0:
        import json as _json

        for ende in range(len(text), start, -1):
            if text[ende - 1] != "}":
                continue
            try:
                daten = _json.loads(text[start:ende])
            except Exception:
                continue
            if not isinstance(daten, Mapping):
                break
            for name in ("detail", "message", "reason", "title"):
                wert = daten.get(name)
                # ``detail`` traegt manchmal selbst wieder einen Umschlag.
                if isinstance(wert, Mapping):
                    wert = wert.get("reason") or wert.get("detail")
                wert = str(wert or "").strip()
                if wert and not wert.startswith("{"):
                    return wert[:MAX_GRUND_ZEICHEN]
            break
    return text[:MAX_GRUND_ZEICHEN]


#: Was an einem Experiment steht, aus dem keine Aussage geworden ist.
OHNE_AUSWERTUNG = " (ohne Auswertung geblieben)"
OHNE_AUSWERTUNG_EN = " (not evaluated)"

#: End of a line without a nameable result, per answer language.
OHNE_ERGEBNIS_DE = "→ ohne Ergebnis"
OHNE_ERGEBNIS_EN = "→ no result"


def getragene_evidenz(
    claims: Sequence[Any],
    angenommene_ids: Sequence[str],
    fakten: Sequence[Any],
) -> set:
    """Auf welcher Evidenz am Ende wirklich eine Aussage ruht.

    Der Weg ist Claim -> ``fact_ids`` -> Fact -> ``source_evidence_ids``.

    NUR ANGENOMMENE CLAIMS zaehlen. Ein verworfener traegt nichts, und
    seine Evidenz hat folglich auch nichts getragen. Wuerde hier ueber
    alle Claims gelaufen, waere jedes Experiment ausgewertet, auch die
    vier Teilkorpora aus dem Lauf vom 2026-09-01, die nie eines wurden.

    Diese Funktion steht hier und nicht im Orchestrator, weil sie reine
    Rechnung ohne Turn-Zustand ist. Der Orchestrator hat ein LOC-Budget
    von 7800 Zeilen mit Absenkungsabsicht, und ein Budget waechst nicht,
    weil eine Rechnung ein Zuhause sucht.
    """
    nach_evidenz = {
        str(feld(fakt, "id", "") or ""): [
            str(x) for x in (feld(fakt, "source_evidence_ids", None) or ())
        ]
        for fakt in (fakten or ())
    }
    angenommen = {str(x) for x in (angenommene_ids or ())}
    heraus: set = set()
    for claim in claims or ():
        if str(feld(claim, "id", "") or "") not in angenommen:
            continue
        for fid in feld(claim, "fact_ids", None) or ():
            heraus.update(nach_evidenz.get(str(fid), ()))
    return heraus


def experimente(
    evidenz: Sequence[Any],
    *,
    ausgewertet: Optional[AbstractSet[str]] = None,
) -> List[str]:
    """Ein Protokolleintrag je Werkzeugaufruf, in Aufrufreihenfolge.

    Leere Liste, wenn kein Werkzeug lief. Ein Protokoll ueber nichts wäre
    eine Ueberschrift ohne Inhalt, und davon hat dieses Projekt genug.

    ``ausgewertet`` ist die Menge der Evidenz-IDs, auf denen am Ende
    wirklich eine Aussage ruht. Was nicht darin steht, bekommt
    ``OHNE_AUSWERTUNG`` angehaengt.

    WARUM DAS DAZUGEHOERT. Die Vorgabe vom 2026-08-31 verlangt, dass die
    Antwort sagt, "was man aus welchem einzelnen Experiment folgern
    kann". Bei vier von sieben Experimenten der gemessenen Antwort vom
    2026-09-01 lautet die ehrliche Auskunft: nichts. Es waren vier
    Teilkorpora (``AI news``, ``AI blog_essay``, ``Human news``, ``Human
    blog_essay``), gebaut kurz vor der Rundenschranke und nie
    ausgewertet. Das Protokoll fuehrte sie mit Dokument- und Tokenzahl
    auf, als haetten sie etwas ergeben.

    Der Claim-Text wird hier ABSICHTLICH NICHT wiederholt. Er steht im
    Rumpf, und "jede Zahl einmal, in dem Block, dessen Aufgabe sie ist"
    gilt auch fuer Saetze. Neu ist allein die Auskunft ueber das
    Ausbleiben.

    Ohne ``ausgewertet`` bleibt jede Zeile unmarkiert. Wer es nicht weiss,
    behauptet es nicht.
    """
    heraus: List[str] = []
    # Das Etikett jedes Teilkorpus, aus seinem create_docset (siehe _ergebnis).
    etiketten = {
        str(teil.get("docset_id")): str(teil.get("label"))
        for teil in (belegflaeche(e) for e in evidenz or []
                     if str(feld(e, "tool", "")).strip() == "create_docset")
        if isinstance(teil, Mapping) and teil.get("docset_id") and teil.get("label")
    }
    for eintrag in evidenz or []:
        werkzeug = str(feld(eintrag, "tool", "")).strip()
        if not werkzeug:
            continue
        status = str(feld(eintrag, "status", "")).strip().lower()
        flaeche = belegflaeche(eintrag)
        if not isinstance(flaeche, Mapping):
            continue
        name = _t(_WERKZEUGNAMEN, _WERKZEUGNAMEN_EN).get(werkzeug, werkzeug)  # type: ignore[attr-defined]
        gegenstand = _gegenstand(flaeche)
        kopf = f"{name}" + (f" `{gegenstand}`" if gegenstand else "")
        # EIN GESCHEITERTER AUFRUF IST DAS INTERESSANTESTE PROTOKOLL.
        #
        # Live am 2026-08-31 stand in einer ausgelieferten Antwort viermal
        # "Suche → ohne Ergebnis", und zwei davon waren die Abfragen, um die
        # es der Nutzerin ging. Der Aufrufer wirft solche Zeilen weg, weil
        # ein Aufruf ohne nennbare Zahl nichts beitraegt. Ein GESCHEITERTER
        # Aufruf traegt aber sehr wohl bei: er sagt, dass der Harnisch es
        # versucht hat und woran es lag. Ohne ihn liest sich das Protokoll,
        # als waere der Versuch nie unternommen worden.
        if status in GESCHEITERT:
            roh_grund = (
                feld(eintrag, "error", "")
                or flaeche.get("error")
                or flaeche.get("detail")
                or flaeche.get("message")
                or status
            )
            grund = _lesbarer_grund(roh_grund)
            # Messung 16: das Modell behauptete „404-Fehler“, wo die
            # Beleglage status=400 zeigt — der tatsaechliche Statuscode
            # gehoert in die Protokollzeile, sonst ist die Widerlegung
            # fuer den Leser unsichtbar.
            code = re.search(r'"status"\s*:\s*(\d{3})', str(roh_grund))
            if code:
                grund = _t("HTTP {} — {}", "HTTP {}, {}").format(code.group(1), grund)
            heraus.append(kopf + _t(" → gescheitert: ", " → failed: ") + grund)
            continue
        ergebnis = _ergebnis(flaeche, werkzeug, etiketten)
        spitze = _spitze(flaeche)
        # Ein gescheiterter Aufruf traegt seinen Grund schon und wird nicht
        # zusaetzlich als unausgewertet gemeldet: er ist oben raus.
        marke = ""
        if ausgewertet is not None:
            kennung = str(feld(eintrag, "id", "") or "").strip()
            if kennung and kennung not in ausgewertet:
                marke = _t(OHNE_AUSWERTUNG, OHNE_AUSWERTUNG_EN)
        if ergebnis and spitze:
            heraus.append(f"{kopf} → {ergebnis}" + _t(", stärkste: ", ", strongest: ") + f"{spitze}{marke}")
        elif ergebnis:
            heraus.append(f"{kopf} → {ergebnis}{marke}")
        elif spitze:
            heraus.append(f"{kopf} → {spitze}{marke}")
        else:
            # Ein Aufruf ohne nennbares Ergebnis wird trotzdem genannt:
            # dass er lief, ist selbst eine Auskunft, und ein verschwiegener
            # Nullbefund ist die schlimmere Variante.
            heraus.append(f"{kopf} " + _t(OHNE_ERGEBNIS_DE, OHNE_ERGEBNIS_EN))
    return heraus


def protokoll_anhaengen(
    text: str,
    evidenz: Sequence[Any],
    *,
    ausgewertet: Optional[AbstractSet[str]] = None,
) -> str:
    """Das Experimentprotokoll unter den Antworttext setzen.

    Idempotent: steht die Ueberschrift schon da, bleibt der Text
    unveraendert. Jeder Fehler laesst den Grundtext unangetastet,
    Telemetrie darf eine Antwort nie kosten.
    """
    grundtext = str(text or "")
    if not grundtext.strip() or UEBERSCHRIFT_DE in grundtext or UEBERSCHRIFT_EN in grundtext:
        return grundtext
    try:
        zeilen = experimente(evidenz, ausgewertet=ausgewertet)
    except Exception:  # pragma: no cover - eine Antwort darf nie daran fallen
        return grundtext
    # Keep zero-hit results and failed calls because both convey an outcome.
    # Omit successful calls with no reportable result from an otherwise empty log.
    zeilen = [z for z in zeilen if not z.endswith((OHNE_ERGEBNIS_DE, OHNE_ERGEBNIS_EN))]
    if not zeilen:
        return grundtext
    nummeriert = "\n".join(
        f"{i}. {z}" for i, z in enumerate(zeilen, start=1)
    )
    ueberschrift = _t(UEBERSCHRIFT_DE, UEBERSCHRIFT_EN)
    return f"{grundtext.rstrip()}\n\n{ueberschrift}\n{nummeriert}"
