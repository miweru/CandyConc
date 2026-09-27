# -*- coding: utf-8 -*-
"""Decide when collected evidence supports an answer without model synthesis.

Explicit requests for interpretation, contextualization or usage analysis
continue to model synthesis even if their contract is classified as a lookup.
Simple count and inventory questions can use a deterministic answer when the
required evidence is available. Reuse the existing interpretation detector
so metadata and general landing decisions apply the same distinction.
"""

from __future__ import annotations

from candyconc.answer_language import choose as _t, format_int

import re
from typing import Any, Mapping

from candyconc.i18n import lt

# MAX_NACHSCHLAGEZEICHEN steht seit dem 2026-09-02 in candyconc.question_kind,
# mit der gemessenen Begruendung fuer den Wert. Die Konstante musste
# dorthin, weil die Promptvertragsschicht (candyconc.tooling.tool_selection)
# dieselbe Einstufung braucht und nicht aus candyconc_copilot lesen darf.
# Der Name bleibt hier erreichbar, weil Proben und Aufrufer ihn hier lesen.
from candyconc.question_kind import (  # noqa: F401
    MAX_NACHSCHLAGEZEICHEN,
    frage_ist_blosses_nachschlagen,
)

from .analysis_grounding import (
    _metadata_request_needs_interpretation,
    compatible_deliverable_kind,
)


# Requests for ranking, shares or breakdowns need a distribution.
# A metadata inventory alone supplies distinct values without their counts.
# Check the available evidence at every landing entry point. A frequency
# result can already satisfy the request, so the question alone must not
# exclude deterministic answers.
_VERTEILUNGSFRAGE = re.compile(
    r"h[aä]ufigst|h[aä]ufigkeit|meist|dominier|st[aä]rkst|gr[oö](ss|ß)t|"
    r"verteil|anteil|rangfolge|typisch|charakteristisch|selten|"
    r"vertreten|verbreitet|aufgeschl[uü]ssel|\bpro\s|\bje\s"
)


def _ist_nachschlagefrage(
    frage: str,
    *,
    metadaten_massstab: str | None = None,
) -> bool:
    """Laenge, Deutungscue und Metadatenklausel, an EINER Stelle.

    ALLE Landungen fragen hier, auch ``erlaubt_deterministische_landung``.
    Am 2026-09-02 stand die Sequenz zweimal im Modul, wortgleich bis auf
    den Fall der leeren Frage, und ein Docstring behauptete bereits, sie
    sei zusammengezogen. Sie war es nicht. Wer heute einen Cue anfasst,
    fasst genau eine Stelle an.

    LAENGE UND DEUTUNGSCUE KOMMEN AUS ``candyconc.question_kind``. Sie standen
    hier als zwei eigene Zeilen mit einer eigenen Konstante, und die
    Kontraktschicht hatte ihre eigene Fassung. Seit dem 2026-09-02
    urteilen beide Schichten mit ``frage_ist_blosses_nachschlagen``, und
    die Konstante liegt dort, wo auch die Promptvertragsschicht sie lesen
    darf.

    ``metadaten_massstab`` GIBT ES, WEIL DIE DRITTE KLAUSEL EINE ANDERE
    FRAGE STELLT. Sie prueft, ob eine Feld- oder Wertabfrage einen
    Deutungsbedarf traegt, und ihre Cue-Liste ist viel breiter: auf die
    Vollfrage losgelassen faengt sie mit "analys" jede
    Analyseaufforderung. ``erlaubt_deterministische_landung`` uebergibt
    ihr deshalb den ``question_scope``, waehrend die beiden Textlandungen
    den Fragetext selbst pruefen, den sie ohnehin schon in der Hand
    haben. Die Begruendung mit der gemessenen Frage steht dort.

    DIE LEERE FRAGE gilt hier als Nachschlagen. Das ist bewusst und nicht
    geerbt: ohne Fragetext kann die Cue-Politik nichts aussagen, und die
    Entscheidung faellt dann an den Stellen, die etwas wissen. In
    ``erlaubt_deterministische_landung`` ist das der Kontraktfilter, in
    den beiden Textlandungen die Cue-Suche, die auf leerem Text nichts
    findet. Die Gegenrichtung haette die deterministische Landung fuer
    jeden Kontrakt ohne ``question_scope`` stillgelegt, und das waere
    eine Verhaltensaenderung ohne Befund dahinter.
    """
    text = (frage or "").strip()
    if not frage_ist_blosses_nachschlagen(text):
        return False
    massstab = text if metadaten_massstab is None else metadaten_massstab
    return not _metadata_request_needs_interpretation(massstab)


def erlaubt_deterministische_landung(
    contract: Any,
    question_text: str = "",
) -> bool:
    """True, wenn die Antwort ohne Modellaufruf entstehen darf.

    DIE SCHRANKE IST UMGEDREHT. Vorher lautete die Frage "verlangt das
    jemand ausdruecklich als Deutung", und alles andere fiel in den
    deterministischen Verfasser. Das war die falsche Richtung: sechs von
    acht Rollenfragen bekamen dadurch eine Antwort ohne einen einzigen
    Modellaufruf, obwohl jede von ihnen um ein Urteil bittet ("Sag mir in
    Prosa, woran ich eine KI-Fassung erkenne", "ob ich von einem
    korpusweiten Befund sprechen darf", "stimmt mein Eindruck ueberhaupt").

    Jetzt schreibt das Modell, AUSSER die Frage ist nachweislich ein
    blosses Nachschlagen. Der Zweifel faellt damit zugunsten der Deutung,
    und das ist die Richtung, die der Auftrag verlangt.

    DER MASSSTAB IST DIE FRAGE, NICHT DAS ABBILD. ``question_scope`` ist auf
    dem Modellpfad nicht die gekuerzte Frage, sondern vom Modell geschriebene
    Prosa: ``AnalysisContract.from_raw`` setzt das Feld aus
    ``payload["question_scope"]`` (grounding_contracts.py:1211). Gemessen am
    2026-09-03 verlor "Gibt es das Wort Klimawandel im Korpus?" (39 Zeichen)
    mit einem 191 Zeichen langen Modell-Scope die deterministische Landung,
    obwohl der Kontrakt korrekt ``lookup_answer`` und ``lookup`` trug. Die
    Kontraktschicht urteilt seit dem 2026-09-02 auf ``question_text``, diese
    Schicht las weiter das Abbild, und damit war die Gleichheit der beiden
    Urteile genau in der Gegenrichtung offen. Ohne ``question_text`` bleibt
    ``question_scope`` der Massstab, weil die Heuristikzweige das Feld aus der
    echten Frage bauen und Proben den Kontrakt allein uebergeben.

    NUR DIESE EINE REGEL WECHSELT DEN MASSSTAB. Die Metadatenklausel darunter
    liest weiter ``question_scope``. Ihre Cue-Liste ist eine andere und viel
    breitere Frage (traegt eine Feld- oder Wertabfrage einen Deutungsbedarf),
    und auf die Vollfrage losgelassen faengt sie mit "analys" jede
    Analyseaufforderung. Gemessen am 2026-09-03 an
    "Analysiere die Treffer zu Zeit und gib nur ein direkt belegtes
    Beispiel." (69 Zeichen, Scope "KWIC fuer Zeit"): mit der Vollfrage als
    Massstab verlor diese Frage die deterministische Landung, und damit die
    strukturelle Garantie aus K1, dass bei einem lookup-Deliverable ueberhaupt
    kein Modelltext in die Antwort gelangt (tests/ai/
    test_orchestrator_grounding_runtime.py, "blocks_unsupported_kwic_example").
    Die Klausel gehoert nicht zu dieser Massnahme, deshalb behaelt sie ihren
    Massstab.
    """
    scope = getattr(contract, "question_scope", "") or ""
    frage = str(question_text or "").strip() or scope
    # Die Metadatenklausel bekommt den Scope als eigenen Massstab, alles
    # andere urteilt auf der Frage. Beides steht in
    # _ist_nachschlagefrage, damit es die eine Stelle bleibt.
    if not _ist_nachschlagefrage(frage, metadaten_massstab=scope):
        return False
    art = getattr(contract, "deliverable_kind", "")
    if art not in {"lookup_answer", "capability_report"}:
        return False
    return compatible_deliverable_kind(
        art,
        getattr(contract, "analysis_family", ""),
        question_text=frage,
        track=getattr(contract, "track", ""),
    ) == art


# Complete simple lookups as soon as the deterministic plan supplies
# their evidence. Use the same lookup predicate as the later landing path
# so interpretation requests continue through model synthesis.

#: Phasen, an denen der Orchestrator fragt. Der Name sagt, was schon
#: gelaufen ist, nicht was noch kommt.
PHASE_VOR_VORPLAN = "vor_vorplan"
PHASE_NACH_VORPLAN = "nach_vorplan"
PHASE_WERKZEUGRUNDE = "werkzeugrunde"

SOFORTLANDUNG_GRUND = lt(
    "Die Antwort steht deterministisch aus der erhobenen Evidenz fest. "
    "Ein weiterer Modellaufruf könnte ihr nichts hinzufügen und "
    "unterbleibt deshalb.",
    "The answer follows deterministically from the collected evidence. "
    "A further model call could not add anything, so none is made.",
)


def sofortlandung_moeglich(
    contract: Any, pending: Any, evidence: Any, frage: str = ""
) -> bool:
    """Darf der Turn HIER enden, ohne das Modell noch einmal zu rufen?

    Drei Bedingungen, alle aus dem laufenden Turn und keine davon
    geraten: der Kontrakt erlaubt die deterministische Landung, es fehlt
    keine vertraglich geforderte Evidenz mehr, und mindestens ein
    Werkzeugergebnis liegt vor. Fehlt eines, laeuft der heutige Weg.

    ``frage`` ist der Fragetext des Turns und geht weiter an
    ``erlaubt_deterministische_landung``. Ohne ihn urteilte diese Naht
    auf ``question_scope``, und das ist auf dem Modellpfad nicht die
    gekuerzte Frage, sondern vom Modell geschriebene Prosa. Gemessen am
    2026-09-03 verlor "Gibt es das Wort Klimawandel im Korpus?" mit
    einem 191 Zeichen langen Modell-Scope die deterministische Landung.
    """
    if contract is None or pending or not evidence:
        return False
    return erlaubt_deterministische_landung(contract, frage)


def _ganzzahl(wert: Any) -> int | None:
    try:
        zahl = int(wert)
    except (TypeError, ValueError):
        return None
    return zahl if zahl > 0 else None


def _zahl(wert: int) -> str:
    """Tausenderpunkt, byte-gleich zu grounding_refs._format_number."""
    return format_int(wert)


#: Was gefragt ist, wenn nach der Korpusgroesse gefragt wird.
_KORPUSGROESSE_CUES = (
    (re.compile(r"wie\s+viele\s+dokumente"), "docs"),
    (re.compile(r"wie\s+viele\s+(tokens?|w(oe|[oö])rter)"), "tokens"),
    (re.compile(r"wie\s+gro(ss|ß)\s+ist\s+(das|dieses|unser)\s+korpus"), "beides"),
    (re.compile(r"korpus(gr[oö]sse|größe|umfang)"), "beides"),
)

#: Sobald ein Suchbegriff im Spiel ist, ist es KEINE Frage nach der
#: Korpusgroesse mehr, sondern eine Zaehlfrage mit Nenner. "In wie vielen
#: Dokumenten kommt Klimawandel vor" muss ueber query_count laufen und
#: nicht aus der Karte beantwortet werden.
#:
#: OHNE "woerter". Bis zum 2026-09-02 stand die Form hier UND als
#: Alternative in der Token-Cue eine Zeile darueber, und weil dieser Test
#: zuerst laeuft, gaben "Wie viele Woerter hat das Korpus?" und "Wie viele
#: Wörter hat das Korpus?" beide leeren String zurueck: die uebliche
#: deutsche Formulierung der Tokenfrage lief weiter den vollen Modellweg
#: von 233 s, und der Cue-Zweig war toter Code, der Abdeckung
#: vortaeuschte. Den Suchbegriffsfall tragen "wort", die
#: Anfuehrungszeichen und die Verbcues.
_TERMBEZUG = re.compile(
    r"['\"„»‚]|\b(kommt|kommen|vorkommen|vorkommt|enth[aä]lt|enthalten|"
    r"treffer|beleg|belege|belegen|wort)\b"
)

# Allow these words in an unconditional lookup question.
# After removing its cue phrase, any other text can specify a filter or
# grouping. Leave such questions on the analysis path rather than answering
# with an unconditional corpus total or complete inventory.
_FUELLWOERTER = frozenset(
    """
    der die das den dem des ein eine einen einem einer eines
    im in am an auf aus bei für fuer von vom zu zum zur
    ist sind hat haben gibt es da wird werden hier
    korpus korpora korpusses dieses diesem dieser diese
    aktive aktiven aktuelle aktuellen geladene geladenen ganze ganzen
    insgesamt genau eigentlich denn überhaupt ueberhaupt gerade
    bitte mal wohl etwa ungefähr ungefaehr
    """.split()
)


def _ohne_cue(text: str, treffer: "re.Match[str]") -> str:
    """Der Fragetext ohne die getroffene Cue-Phrase.

    Ueber die SPANNE und nicht ueber ``str.replace``. Gemessen am
    2026-09-03: bei der Feldlandung wird der Feldname vor dem Rest-Test
    entfernt, die Cue-Phrase enthaelt ihn aber ("welche register gibt
    es"), und ein replace fand sie danach nicht mehr. Uebrig blieb
    "welche", das kein Fuellwort ist, und "Welche Register gibt es im
    Korpus?" landete nicht mehr, also genau der dritte Messpunkt.
    """
    return text[: treffer.start()] + " " + text[treffer.end():]


def _hat_einschraenkung(rest: str) -> bool:
    """Bleibt nach Abzug der verstandenen Teile ein inhaltstragendes Wort?

    ``rest`` ist die Frage ohne die Teile, die die Landung wirklich
    ausgewertet hat: die getroffene Cue-Phrase, bei der Feldlandung
    zusaetzlich der Feldname. Was hier uebrig bleibt und kein Fuellwort
    ist, hat die Frage eingeschraenkt, und dann darf die Landung nicht
    die unkonditionierte Zahl oder die unkonditionierte Werteliste
    liefern.
    """
    return any(
        wort not in _FUELLWOERTER for wort in re.findall(r"\w+", rest)
    )


def _subkorpus_aktiv(karte: Mapping[str, Any] | None) -> bool:
    """Check whether a docset is active.

    The corpus-wide card landing must yield when a subcorpus is selected.
    The normal path receives that scope in the corpus card and can answer
    with the selected population.
    """
    if not isinstance(karte, Mapping):
        return False
    unterkorpus = karte.get("subcorpus")
    return isinstance(unterkorpus, Mapping) and bool(unterkorpus)


def _groessenfrage(frage: str) -> bool:
    """Fragt der Text nach der Groesse des Korpus, ohne Suchbegriff?"""
    if not _ist_nachschlagefrage(frage):
        return False
    text = (frage or "").strip().casefold()
    if _TERMBEZUG.search(text):
        return False
    return any(muster.search(text) for muster, _art in _KORPUSGROESSE_CUES)


def korpusgroesse_antwort(
    frage: str, karte: Mapping[str, Any] | None
) -> str:
    """Dokument- oder Tokenzahl des Korpus, direkt aus der Korpuskarte.

    Leerer String, wenn die Frage keine ist oder die Karte die Zahl nicht
    traegt. Nie eine geratene Zahl: fehlt sie, laeuft der heutige Weg.
    """
    if not isinstance(karte, Mapping) or not _ist_nachschlagefrage(frage):
        return ""
    if _subkorpus_aktiv(karte):
        return ""
    text = (frage or "").strip().casefold()
    if _TERMBEZUG.search(text) or _VERTEILUNGSFRAGE.search(text):
        return ""
    gefragt = ""
    cue_treffer = None
    for muster, art in _KORPUSGROESSE_CUES:
        cue_treffer = muster.search(text)
        if cue_treffer:
            gefragt = art
            break
    if not gefragt or cue_treffer is None:
        return ""
    if gefragt in {"docs", "tokens"} and "korpus" not in text:
        return ""
    if _hat_einschraenkung(_ohne_cue(text, cue_treffer)):
        return ""
    docs = _ganzzahl(karte.get("docs"))
    tokens = _ganzzahl(karte.get("tokens"))
    if gefragt == "docs" and docs is None:
        return ""
    if gefragt == "tokens" and tokens is None:
        return ""
    if docs is None and tokens is None:
        return ""
    korpus = str(karte.get("corpus_id") or "").strip()
    # KEINE Backticks um die Quellennamen. Gemessen am 2026-09-02: die
    # Zitatwache (recipe_runtime.strike_unsupported_quotes) behandelt eine
    # Code-Spanne ab vier Woertern wie ein Zitat, und
    # `corpus_index.token_count` normalisiert zu genau vier. Sie strich es
    # als unbelegt, danach warf drop_unresolved_sentences den ganzen Satz,
    # und uebrig blieb eine Antwort ohne die Zahl, nach der gefragt war.
    # Die Wache hat recht: ohne Werkzeugevidenz ist nichts gedeckt. Also
    # steht die Herkunft als Prosa da und nicht als Auszeichnung.
    teile = []
    if docs is not None:
        teile.append(_t(f"{_zahl(docs)} Dokumente", f"""{_zahl(docs)} documents"""))
    if tokens is not None:
        teile.append(_t(f"{_zahl(tokens)} Tokens", f"""{_zahl(tokens)} tokens"""))
    if gefragt == "tokens":
        teile.reverse()
    kopf = _t(f"Das aktive Korpus {korpus}", f"""The active corpus {korpus}""") if korpus else _t("Das aktive Korpus", "The active corpus")
    zeilen = [_t(f"{kopf} umfasst {' und '.join(teile)}.", f"""{kopf} contains {' and '.join(teile)}.""")]
    # Explain repeated versions alongside document counts so readers can
    # distinguish documents from independent source texts.
    quelltexte = karte.get("quelltexte")
    if isinstance(quelltexte, Mapping) and docs is not None:
        anzahl = _ganzzahl(quelltexte.get("anzahl"))
        fassungen = quelltexte.get("fassungen_je_quelltext")
        feld = str(quelltexte.get("feld") or "").strip()
        if anzahl and feld:
            zeilen.append(
                _t(f"Diese {_zahl(docs)} Dokumente sind {_zahl(anzahl)} "
                f"Quelltexte in je {fassungen} Fassungen (Feld {feld}). "
                "Eine Dokumentzahl in diesem Korpus zählt Fassungen, "
                "keine Quelltexte.", f"""These {_zahl(docs)} documents represent {_zahl(anzahl)} source texts with {fassungen} versions each (field {feld}). The document count in this corpus counts versions rather than source texts.""")
            )
    herkunft = [_t("Quelle ist die Korpuskarte des laufenden Turns", 'Source: the corpus card for this turn')]
    if docs is not None:
        herkunft.append(_t("Dokumentzahl aus doc_metadata", 'document count from doc_metadata'))
    if tokens is not None:
        herkunft.append(_t("Tokenzahl aus corpus_index.token_count", 'token count from corpus_index.token_count'))
    zeilen.append(
        ", ".join(herkunft)
        + _t(". Für diese Zahlen lief weder ein Werkzeug noch ein "
        "Modellaufruf.", '. These numbers were read without a tool or model call.')
    )
    return "\n\n".join(zeilen)


def _metadatenwerte(evidenz: Any) -> dict[str, tuple[list[str], int]]:
    """``{feld: (sichtbare Werte, Wertezahl)}`` aus dem Vorplanergebnis.

    Quelle ist die ``fact_surface`` der ``metadata_values``-Evidenz. Sie
    ist unbeschraenkt aufgebaut (``extract_raw_surface(bounded=False)``),
    traegt also die vollstaendige Werteliste je analytischem Feld und in
    ``value_counts`` die Wertezahl VOR dem Identifier-Filter.
    """
    gefunden: dict[str, tuple[list[str], int]] = {}
    for eintrag in list(evidenz or ()):
        if isinstance(eintrag, Mapping):
            daten = eintrag
        elif hasattr(eintrag, "to_dict"):
            daten = eintrag.to_dict()
        else:
            continue
        if str(daten.get("tool") or "") != "metadata_values":
            continue
        if str(daten.get("status") or "success").lower() == "error":
            continue
        flaeche = daten.get("fact_surface")
        if not isinstance(flaeche, Mapping):
            continue
        werte = flaeche.get("values")
        zaehler = flaeche.get("value_counts")
        if not isinstance(werte, Mapping):
            continue
        for feld, eintraege in werte.items():
            if not isinstance(eintraege, (list, tuple)) or not eintraege:
                continue
            sichtbar = [str(item) for item in eintraege]
            anzahl = len(sichtbar)
            if isinstance(zaehler, Mapping):
                anzahl = _ganzzahl(zaehler.get(str(feld))) or anzahl
            gefunden[str(feld)] = (sichtbar, anzahl)
    return gefunden


def _feldmuster(feld: str) -> str:
    """Match field names with equivalent separators in the question.

    Normalize both sides so text_type, text type and texttype identify the
    same field.
    """
    name = str(feld or "").strip().casefold().replace("_", " ")
    verbunden = "[ _-]?".join(re.escape(teil) for teil in name.split())
    return r"\b" + verbunden + r"\w{0,3}\b"


def _feld_genannt(feld: str, text: str) -> bool:
    """Nennt die Frage genau dieses Metadatenfeld?

    Wortanfang mit bis zu drei Zeichen Flexion, damit "Welche Register"
    das Feld ``register`` trifft und "Registern" ebenso. Felder unter
    vier Zeichen bleiben aussen vor: ``id`` oder ``pos`` treffen sonst in
    fast jeder Frage zufaellig.
    """
    name = str(feld or "").strip().casefold().replace("_", " ")
    if len(name.replace(" ", "")) < 4:
        return False
    return bool(re.search(_feldmuster(feld), text))


# Require an explicit request for the values of one field.
# A generic question word can also introduce a ranking or distribution request.
_FELDWERTE_CUES = (
    re.compile(
        r"\bwelche\s+werte\b[^?]{0,20}?\b(hat|besitzt|f[uü]hrt|gibt\s+es)\b"
    ),
    re.compile(
        r"\bwelche\b[^?]{0,40}?\b(gibt\s+es|vorhanden|enthalten|enth[aä]lt)\b"
    ),
)


def metadatenfeld_antwort(
    frage: str, karte: Mapping[str, Any] | None, evidenz: Any
) -> str:
    """Die Werte EINES Metadatenfelds aus dem Vorplanergebnis.

    Der gemessene Fall: "Welche Register gibt es im Korpus?" bekam die
    Feldliste mit "19272 distinkte Werte", obwohl die zehn Registerwerte
    im ``metadata_values``-Ergebnis derselben Runde standen.

    Leerer String, wenn die Frage kein oder mehr als ein Feld nennt. Bei
    zwei Treffern ist nicht entscheidbar, welches gemeint ist, und eine
    geratene Auswahl waere schlechter als der heutige Weg.
    """
    if not _ist_nachschlagefrage(frage) or _subkorpus_aktiv(karte):
        return ""
    text = (frage or "").strip().casefold()
    if _VERTEILUNGSFRAGE.search(text):
        return ""
    cue_treffer = None
    for muster in _FELDWERTE_CUES:
        cue_treffer = muster.search(text)
        if cue_treffer:
            break
    if cue_treffer is None:
        return ""
    werte = _metadatenwerte(evidenz)
    treffer = [feld for feld in werte if _feld_genannt(feld, text)]
    if len(treffer) != 1:
        return ""
    feld = treffer[0]
    rest = re.sub(_feldmuster(feld), " ", _ohne_cue(text, cue_treffer))
    if _hat_einschraenkung(rest):
        return ""
    sichtbar, anzahl = werte[feld]
    liste = ", ".join(f"`{wert}`" for wert in sichtbar)
    zeilen = [
        _t(f"Das Metadatenfeld `{feld}` führt {_zahl(anzahl)} Werte: "
        f"{liste}.", f"""The metadata field `{feld}` has {_zahl(anzahl)} values: {liste}.""")
    ]
    # NUR EINE Sichtbarkeitsangabe, und nur wenn sie etwas sagt. Gemessen
    # am 2026-09-03 trug eine Antwort drei verschiedene zum selben Feld:
    # "10 von 10 Werten sichtbar" im Kopf, acht Werte im deterministischen
    # Inventar darunter und "3 von 10 Werten" im Methodensteckbrief. Der
    # Leser konnte nicht entscheiden, welche gilt. Zeigt der Kopf alle
    # Werte, ist die Angabe redundant und faellt weg.
    #
    # Der Rest des Widerspruchs wird BENANNT statt versteckt. Der Kopf
    # liest die unbeschraenkte fact_surface, das Inventar darunter die
    # gebundene raw_surface, und die kappt (im gemessenen Fall acht der
    # zehn Registerwerte) ohne es zu sagen. Welche Liste gilt, steht
    # damit hier und nicht im Ermessen des Lesers.
    quelle = _t(f"Quelle: `metadata_values`, Feld `{feld}`.", f"""Source: `metadata_values`, field `{feld}`.""")
    if len(sichtbar) < anzahl:
        quelle += _t(f" Sichtbar sind davon {_zahl(len(sichtbar))} Werte.", f""" Of these, {_zahl(len(sichtbar))} values are visible.""")
    quelle += (
        _t(" Diese Aufzählung ist die vollständige, die Feldübersicht "
        "weiter unten zeigt je Feld nur einen Ausschnitt.", ' This is the complete enumeration. The field overview below shows an excerpt for each field.')
    )
    # Das Werkzeug liefert DISTINKTE Werte, keine Dokumentzahl je Wert
    # (core/meta_filters.metadata_values gibt eine Menge zurueck). Diese
    # Luecke wird benannt und nicht gefuellt: eine Dokumentzahl je Wert
    # kostet je Wert eine eigene Zaehlung, und die hat niemand erhoben.
    zeilen.append(
        quelle
        + _t(" Wie viele Dokumente auf jeden Wert entfallen, gibt dieses "
        "Werkzeug nicht aus.", ' This tool does not report the number of documents for each value.')
    )
    return "\n\n".join(zeilen)


def _verteilung_ohne_zaehlung(frage: str, evidenz: Any) -> bool:
    """Check whether a distribution question lacks counting evidence.

    metadata_values supplies distinct values rather than document counts.
    A counting tool can supply the required distribution and permit the
    deterministic landing.
    """
    if not _VERTEILUNGSFRAGE.search((frage or "").strip().casefold()):
        return False
    werkzeuge = set()
    for eintrag in list(evidenz or ()):
        if isinstance(eintrag, Mapping):
            werkzeuge.add(str(eintrag.get("tool") or ""))
        else:
            werkzeuge.add(str(getattr(eintrag, "tool", "") or ""))
    return not (werkzeuge - {"metadata_values", ""})


def sofortlandungsentscheid(
    phase: str,
    frage: str,
    karte: Mapping[str, Any] | None,
    contract: Any,
    pending: Any,
    evidenz: Any,
) -> tuple[str, str]:
    """``(recovery-Kind, Antwortkopf)`` oder ``("", "")``.

    Die EINE Naht, an der die Politik entscheidet. Der Orchestrator
    haengt daran mit einer Closure und traegt selbst keine Regel.
    """
    if phase == PHASE_VOR_VORPLAN:
        text = korpusgroesse_antwort(frage, karte)
        return ("sofortlandung_aus_korpuskarte", text) if text else ("", "")
    # BEI AKTIVEM SUBKORPUS gehoert eine Groessenfrage dem Modell, und
    # zwar auch dann, wenn die allgemeine Bedingung erfuellt waere.
    # Gemessen am 2026-09-03: tritt die Kartenlandung wegen des Docsets
    # zurueck, faengt die allgemeine Landung die Frage eine Runde spaeter
    # auf und beantwortet "Wie viele Dokumente hat das Korpus?" wieder
    # mit dem Feldinventar aus metadata_values, also mit dem Defekt des
    # zweiten Messpunkts. Welcher der beiden Zahlensaetze gemeint ist,
    # entscheidet nur, wer die Frage liest.
    if _groessenfrage(frage) and _subkorpus_aktiv(karte):
        return ("", "")
    if _verteilung_ohne_zaehlung(frage, evidenz):
        return ("", "")
    # DIE FELDLANDUNG HAENGT AN DENSELBEN BEDINGUNGEN wie die allgemeine.
    # Gemessen am 2026-09-03: vorher stand sie davor und kehrte bei
    # Treffer sofort zurueck, ohne pending oder Kontrakt anzusehen. Ein
    # Kontrakt mit noch offener Pflichtevidenz wurde damit durch eine
    # Feldliste stillgelegt, und der Orchestrator kam nie an die Naht,
    # die forced_next_tools setzt und die fehlende Evidenz nachfordert.
    if phase == PHASE_NACH_VORPLAN and not pending:
        text = metadatenfeld_antwort(frage, karte, evidenz)
        if text and (
            contract is None
            or erlaubt_deterministische_landung(contract, frage)
        ):
            return ("sofortlandung_metadatenfeld", text)
    if not sofortlandung_moeglich(contract, pending, evidenz, frage):
        return ("", "")
    if phase == PHASE_NACH_VORPLAN:
        return ("sofortlandung_nach_vorplan", "")
    return ("sofortlandung_nach_werkzeugrunde", "")
