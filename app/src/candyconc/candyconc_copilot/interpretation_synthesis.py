"""Synthesize answers from collected evidence and an optional draft.

The standard path uses one tool-free synthesis call. The report path
creates an outline, expands sections and connects the completed report.
Reference resolution, number checks and quotation checks link the final
answer to the collected evidence.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Mapping, Tuple

from candyconc.answer_language import choose, is_english, resolve
from .evidence_access import belegflaeche, feld
from .prompts import DEUTUNGS_AUFTRAG_OHNE_WERKZEUGE
from .grounding_evidence import werkzeug_liefert_korpusbeleg
from .grounding_refs import MISSING_EVIDENCE_PLACEHOLDER, _eindeutige_kennung, _zahllesarten
from .claim_rules._shared import _extract_numeric_tokens, _numeric_token_is_supported
from .recipe_runtime import drop_unresolved_sentences, strike_unbound_numbers
from .session_compaction import zwischenstand

MAX_ITEMS = 30
MAX_ZEILEN_JE_ITEM = 12
FAKTEN_JE_ITEM = 8
# Emergency character boundary for an evidence package.
# Normal rendering preserves results and reports any content omitted at this boundary.
PAKET_MAX_ZEICHEN = 300_000
MAX_ABSCHNITTE = 8

# Alternative package dimensions selected by paket_voll_aktiv.
PAKET_VOLL_ZEILEN_JE_ITEM = 80
PAKET_VOLL_MAX_ZEICHEN = 60_000

#: Wie oft der Deutungsaufruf bei leerem Inhalt wiederholt wird. Kein
#: Zeitlimit, kein Token-Deckel: nur die Frage noch einmal stellen, bevor
#: eine Schablone als Antwort durchgeht.
_DEUTUNG_VERSUCHE = 3
#: Lieferarten, fuer die der Deutungspfalft Evidenz erzwingt (F-66).
DEUTUNG_LIEFERARTEN = ("analysis_report", "contrast_report", "capability_report")


def _switch(name: str, default: bool) -> bool:
    """Ein Messschalter mit seiner Vorgabe. Nur ausdrueckliche Werte zaehlen."""
    roh = os.environ.get(name, "").strip().lower()
    if roh in ("1", "true", "ja", "an", "on", "yes"):
        return True
    if roh in ("0", "false", "nein", "aus", "off", "no"):
        return False
    return default


def deutungspfad_aktiv() -> bool:
    """Enable the default path from tool phase through draft to fresh synthesis.

    ``CANDYCONC_DEUTUNGSPFAD=0`` selects verification and rebuilding instead.
    """
    return _switch("CANDYCONC_DEUTUNGSPFAD", True)


def paket_voll_aktiv() -> bool:
    """Select alternative package dimensions with CANDYCONC_PAKET_VOLL."""
    return os.environ.get("CANDYCONC_PAKET_VOLL", "").strip().lower() in (
        "1", "true", "ja", "an",
    )


def paket_masse() -> Tuple[int, int]:
    """Return the per-item row limit and package character limit for the active mode.

    The alternative mode uses its own row and character dimensions.
    The default mode uses MAX_ZEILEN_JE_ITEM and the emergency package boundary.
    """
    if paket_voll_aktiv():
        return PAKET_VOLL_ZEILEN_JE_ITEM, PAKET_VOLL_MAX_ZEICHEN
    # Die Grenze ist eine Reissleine, kein Zuschnitt (siehe PAKET_MAX_ZEICHEN).
    return MAX_ZEILEN_JE_ITEM, PAKET_MAX_ZEICHEN


def rechen_pflicht_aktiv() -> bool:
    """Enable the optional calculation instruction, disabled by default."""
    import os

    return os.environ.get("CANDYCONC_RECHEN_PFLICHT", "0").strip().lower() in (
        "1", "true", "ja", "an",
    )


def masswahl_aktiv() -> bool:
    """Enable the optional measure-selection instruction, disabled by default."""
    import os

    return os.environ.get(
        "CANDYCONC_MASSWAHL", "0"
    ).strip().lower() in ("1", "true", "ja", "an")


def paket_wahrheit_aktiv() -> bool:
    """Enable explicit reporting of evidence omitted by package limits.

    Bound individual lines so identifier lists cannot displace the results.
    Report missing elements when shortening occurs and avoid claiming that
    a shortened package is complete. Enabled by default.
    """
    return _switch("CANDYCONC_PAKET_WAHRHEIT", True)


#: Laenge, ab der eine einzelne Paketzeile gekuerzt wird. Eine Liste von
#: Dokumentkennungen hat fuer eine Deutung keinen Wert, ihre Anzahl schon.
PAKET_ZEILE_MAX = 400


def _FAKTEN_ETIKETT() -> str:
    """Label of the facts line in the package (English for English answers)."""
    return choose("Fakten: ", "Facts: ")


def _ZEILEN_ETIKETT() -> str:
    """Label of a table row in the package, ``Row 3:`` for English answers."""
    return choose("Zeile ", "Row ")


def _WEITERE_BELEGZEILEN() -> str:
    return choose(
        "(… {} weitere Belegzeilen dieses Elements liegen vor und sind hier gekuerzt)",
        "(… {} more evidence lines of this element exist and are cut here)",
    )


def _ERGEBNIS_ETIKETT() -> str:
    return choose("  Ergebnis: ", "  Result: ")


def antwortsprache_zeile() -> str:
    """Add the writing-call language instruction for English questions.

    Use the question language resolved before the call. German turns receive
    an empty addition and retain their existing message content.
    """
    if not is_english():
        return ""
    return ("\n\nANTWORTSPRACHE: Englisch, die Sprache der Frage. Die ganze "
            "Antwort ist englisch, Zahlen im englischen Format (174,284 und 1,592.3).")


def _zeile_begrenzen(zeile: str, grenze: int = PAKET_ZEILE_MAX) -> str:
    """Eine Paketzeile auf ``grenze`` Zeichen, mit ehrlicher Angabe des Rests."""
    if len(zeile) <= grenze:
        return zeile
    return zeile[:grenze] + choose(" (… {} Zeichen gekuerzt)", " (… {} characters cut)").format(
        len(zeile) - grenze)


def paket_knapp_aktiv() -> bool:
    """Enable compact evidence rendering without repeated information.

    Show each result once so duplicated profiles, denominators and fact lines
    do not displace later evidence. Enabled by default.
    """
    return _switch("CANDYCONC_PAKET_KNAPP", True)


def _knapp_zusammenfassen(substantiell: List[str], skalare: List[str],
                          fakten: Any) -> List[str]:
    """Skalare in EINE Zeile, die Fakten-Zeile nur, wenn sie Neues traegt."""
    zeilen = list(substantiell)
    if skalare:
        # Diese Felder unserer eigenen Werkzeuge sind je Aufruf entweder
        # konstant (Korpusgroesse, Nennerquelle, Abfragemodus) oder stehen
        # schon in der Kopfzeile (Abfrage, Argumente). Im Paket sind sie nur
        # Wiederholung und verdraengen die Ergebnisse.
        _wiederholung = ("status=", "query_mode=", "attribute=",
                         "corpus_tokens=", "denominator_source=", "source=",
                         "tool_args=", "scope:", "query=")
        zeilen.append("  ".join(
            z for z in skalare if not z.startswith(_wiederholung)))
    if isinstance(fakten, dict) and fakten:
        bekannt = " ".join(substantiell + skalare)
        neu = {k: v for k, v in fakten.items()
               if k not in ("status",) and str(v)[:60] not in bekannt}
        if neu:
            zeilen.append(_FAKTEN_ETIKETT() + json.dumps(
                dict(sorted(neu.items())[:FAKTEN_JE_ITEM]), ensure_ascii=False))
    return [z for z in zeilen if z.strip()]


_KENNUNG = re.compile(r"\b[0-9a-f]{32}\b")
#: Ab so vielen Werten steht eine Liste im Kopf als Anzahl (etwa doc_ids).
_LISTE_ALS_ANZAHL_AB = 20


def _aufruf_fuer_den_kopf(aufruf: str) -> str:
    """Die Argumente eines Aufrufs vollstaendig, lange Listen als Anzahl.

    Eine Abfrage wird nie gekuerzt. Nur eine Liste mit mehr als
    ``_LISTE_ALS_ANZAHL_AB`` Werten steht als "[N Werte]" da, sichtbar.
    """
    try:
        args = json.loads(aufruf)
    except (TypeError, ValueError):
        return aufruf

    def _knapp(wert: Any) -> Tuple[Any, bool]:
        if isinstance(wert, list) and len(wert) > _LISTE_ALS_ANZAHL_AB:
            return choose("[{} Werte]", "[{} values]").format(len(wert)), True
        if isinstance(wert, dict):
            paare = {k: _knapp(v) for k, v in wert.items()}
            return {k: v for k, (v, _) in paare.items()}, any(g for _, g in paare.values())
        return wert, False

    knapp, gekuerzt = _knapp(args)
    return json.dumps(knapp, ensure_ascii=False) if gekuerzt else aufruf


_TREFFERZEILE = re.compile(r"^(?:match|rows|kwic)\[(\d+)\]")
#: "rank=3" traegt nur den Zeilenindex einer Tabellenzeile (build_grounding_surface).
_RANGZEILE = re.compile(r"rank=\d+")
#: Die Zeichen, an denen str.splitlines() eine Zeile bricht.
_UMBRUCH = re.compile("[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]")


def _einzeilig(text: str, umbruch: "str | None" = None) -> str:
    """Keep one output line by replacing line breaks with JSON escapes or ``umbruch``.

    This preserves visible boundaries inside concordance contexts without
    splitting one hit into several package rows.
    """
    if umbruch is not None:
        return _UMBRUCH.sub(umbruch, text)
    return _UMBRUCH.sub(lambda m: json.dumps(m.group(0))[1:-1], text)


def _knapp_treffer(
    item: Dict[str, Any], flaeche: List[str], umbruch: "str | None" = None
) -> List[str]:
    """Render one line per KWIC hit with its source and position.

    Show the rows available to the model and report additional retrieved hits.
    This keeps repeated match, row and context representations from consuming
    the row allowance more than once per hit.
    """
    fakten = item.get("fact_surface")
    reihen = fakten.get("rows") if isinstance(fakten, dict) else None
    if not (isinstance(reihen, list) and reihen and isinstance(reihen[0], dict)):
        return []
    gesehen = {int(m.group(1)) for m in (_TREFFERZEILE.match(z) for z in flaeche) if m}
    # Die Nummern der Zeilen, die das Modell sah. Eine verteilte Auswahl ist kein
    # Anfang der Liste (view_row_selection), das Paket zeigt Zeile für Zeile dieselben.
    nummern = sorted(i for i in gesehen if i < len(reihen)) or list(range(min(len(reihen), 20)))
    zeilen: List[str] = []
    if "left" not in reihen[0]:
        # Render each table row once so duplicate row representations do not
        # displace later results from the synthesis view.
        from .grounding_field_contract import felder_der_modellsicht

        for nr in nummern:
            reihe = reihen[nr]
            # Dieselben Felder in derselben Folge wie in der Modellsicht.
            felder = felder_der_modellsicht(item.get("tool"), reihe) or [
                k for k, v in reihe.items() if not isinstance(v, (dict, list))]
            zeilen.append(_ZEILEN_ETIKETT() + "{}: {}".format(nr, "  ".join(
                f"{k}={reihe[k]}" for k in felder if k in reihe)))
        if len(reihen) > len(nummern):
            rest = len(reihen) - len(nummern)
            zeilen.append(choose(
                "(… {} weitere Zeilen dieser Tabelle sind erhoben und hier nicht aufgeführt)",
                "(… {} more row{} of this table computed and not listed here)",
            ).format(rest, "" if rest == 1 else "s"))
        return zeilen
    for nr in nummern:
        reihe = reihen[nr]
        stichwort = str(reihe.get("kw") or "")
        treffer = str(reihe.get("match") or stichwort)
        # Escape line breaks before trimming context so breaks directly beside
        # the hit remain visible in the package.
        rechts = str(reihe.get("right") or "")
        vorher, nachher = reihe.get("ws_before_kw"), reihe.get("ws_after_kw")
        if isinstance(vorher, bool) and isinstance(nachher, bool):
            # A row with the original spacing: the line reads as written, and
            # the words of the match leave right by their characters.
            links = _einzeilig(str(reihe.get("left") or ""), umbruch).strip()
            fortsetzung = treffer[len(stichwort):].lstrip(" ") if treffer.startswith(stichwort) else ""
            if fortsetzung and rechts.startswith(fortsetzung):
                rechts = rechts[len(fortsetzung):]
                nachher = rechts[:1].isspace()
            rechts = _einzeilig(rechts, umbruch).strip()
            zeilen.append("Treffer {}: {}[{}]{}  ({}, pos {})".format(
                nr, links + (" " if links and vorher else ""), _einzeilig(treffer, umbruch),
                (" " if rechts and nachher else "") + rechts,
                reihe.get("file", "?"), reihe.get("pos", "?")))
            continue
        # Wortweise, damit Leerraum um einen Zeilenumbruch den Vergleich nicht bricht:
        # match liest die Indexpositionen, right die Anzeigezeile (fix/werkzeuge).
        rest = (treffer[len(stichwort):] if treffer.startswith(stichwort) else "").split()
        worte = rechts.split()
        if rest and worte[:len(rest)] == rest:
            # Die Worte des Treffers fallen weg, der Leerraum dahinter bleibt samt Umbruch.
            rechts = re.sub(r"^\s*(?:\S+\s+){%d}\S+" % (len(rest) - 1), "", rechts)
        elif rest and rest[:len(worte)] == worte:
            # When ctx is shorter than the hit, its right side still lies inside
            # the match and must not be repeated as following context.
            rechts = ""
        zeilen.append(choose("Treffer ", "Hit ") + "{}: {} [{}] {}  ({}, pos {})".format(
            nr, _einzeilig(str(reihe.get("left") or ""), umbruch).strip(),
            _einzeilig(treffer, umbruch), _einzeilig(rechts, umbruch).strip(),
            reihe.get("file", "?"), reihe.get("pos", "?")))
    if len(reihen) > len(nummern):
        rest = len(reihen) - len(nummern)
        zeilen.append(choose(
            "(… {0} weitere Treffer dieses Aufrufs sind erhoben und hier nicht aufgeführt, total={1})",
            "(… {0} more hit{2} of this call computed and not listed here, total={1})",
        ).format(rest, fakten.get("total", "?"), "" if rest == 1 else "s"))
    return zeilen


def zahlen_streichen_aktiv() -> bool:
    """Enable replacement of unsupported numbers by the missing-evidence label.

    Disabled by default. Record what the check would replace in either mode
    so unsupported-number findings remain available without deleting the value.
    """
    return _switch("CANDYCONC_ZAHLEN_STREICHEN", False)


def teilfragen_pflicht_aktiv() -> bool:
    """Enable the optional subquestion instruction, disabled by default."""
    import os

    return os.environ.get(
        "CANDYCONC_TEILFRAGEN_PFLICHT", "0"
    ).strip().lower() in ("1", "true", "ja", "an")


def sprachdeutung_aktiv() -> bool:
    """Enable the optional linguistic-interpretation instruction, disabled by default."""
    import os

    return os.environ.get(
        "CANDYCONC_SPRACHDEUTUNG", "0"
    ).strip().lower() in ("1", "true", "ja", "an")


def f4_wachen_aktiv() -> bool:
    """Enable additional anchor-verification stages, disabled by default.

    When enabled, _verankere calls _anker_verifikation for anchor, absence,
    quotation-term and claim-verb checks. Reference resolution, unresolved
    evidence handling, number checks, chips and quotation notices remain
    independent of this switch.
    """
    return os.environ.get("CANDYCONC_F4_WACHEN", "0").strip().lower() in (
        "1", "true", "ja", "an",
    )


def gutachten_aktiv() -> bool:
    return os.environ.get("CANDYCONC_GUTACHTEN", "").strip().lower() in (
        "1",
        "true",
        "ja",
    )


def evidenz_paket_text(evidence_items: List[Any]) -> str:
    """Kompakte, deterministische Darstellung der Turn-Evidenz.

    Je Element eine Kopfzeile (id, Werkzeug, Abfrage, status) plus die
    belegbaren Fakten: ``grounding_surface``-Zeilen und ``fact_surface``.
    Genau die Flaechen, gegen die auch Referenz-Aufloesung und Zitatwache
    pruefen — was hier steht, ist zitierbar.
    """
    zeilen: List[str] = []
    voll = paket_voll_aktiv()
    wahr = paket_wahrheit_aktiv()
    zeilen_je_item, max_zeichen = paket_masse()
    item_ids: List[str] = []
    item_start: List[int] = []
    elemente = list(evidence_items or [])
    if wahr:
        # Consider all evidence items before applying the package limit.
        # Place results before inventories so context lists cannot displace
        # the counts and comparisons needed to answer the question.
        def _ist_inventar(roh: Any) -> bool:
            it = roh.to_dict() if hasattr(roh, "to_dict") else roh
            return isinstance(it, dict) and it.get("tool") in (
                "metadata_values", "list_docsets")
        elemente = ([r for r in elemente if not _ist_inventar(r)]
                    + [r for r in elemente if _ist_inventar(r)])
    else:
        elemente = elemente[:MAX_ITEMS]
    # Das Etikett jedes Teilkorpus aus seinem create_docset, wie im
    # Experimentprotokoll. Ohne es stand in jeder Zaehlung nur die Kennung.
    etiketten = {
        str(teil.get("docset_id")): str(teil.get("label"))
        for teil in (belegflaeche(e) for e in elemente
                     if str(feld(e, "tool", "")).strip() == "create_docset")
        if isinstance(teil, Mapping) and teil.get("docset_id") and teil.get("label")
    }
    for roh in elemente:
        # Die Finalisierung uebergibt EvidenceItem-OBJEKTE, aeltere Pfade
        # Dicts — beides verstehen, sonst wird das Paket still leer.
        item = roh.to_dict() if hasattr(roh, "to_dict") else roh
        if is_english():
            # Localised tool texts in the answer language.
            item = resolve(item)
        if not isinstance(item, dict) or item.get("tool") == "deutung_abgeben":
            # The model's handoff describes its own work and is not corpus evidence.
            continue
        # Keep the full call so a scoped query remains reproducible.
        aufruf = _aufruf_fuer_den_kopf(str(item.get("query", "") or ""))
        kopf = "[{}] {} ({}) status={}".format(
            item.get("id", "?"),
            item.get("tool", "?"),
            aufruf,
            item.get("status", "?"),
        )
        benannt = [etiketten[k] for k in _KENNUNG.findall(aufruf) if k in etiketten]
        if benannt and item.get("tool") != "create_docset":
            kopf += choose(", Teilkorpus ", ", subcorpus ") + ", ".join(dict.fromkeys(benannt))
        item_ids.append(str(item.get("id", "?")))
        item_start.append(len(zeilen))
        zeilen.append(kopf)
        flaeche = [
            str(z).strip()
            for z in (item.get("grounding_surface") or [])
            if str(z).strip()
        ]
        # Messung 14: substantielle Zeilen (rows/kwic/match/Richtung)
        # duerfen von den Skalaren (status/total/query) an der Kappe nicht
        # verdraengt werden — sonst sieht der Verifier die Gegen-Evidenz
        # fuer eine Absenz-Behauptung nicht. "Zeilen nach" ist die Verteilung
        # der KWIC-Zeilen ueber die Fassungen (version_distribution): eine eigene
        # Zeile direkt hinter den Treffern, im Wortlaut der Modellsicht.
        # "bereich=" nennt, in welchem Bereich eine Folge zählt (folgenbereich).
        # Als Skalar stünde die Zeile bei query_count an vierzehnter Stelle und
        # fiele ohne knappe Form an der Kappe von zwölf Zeilen je Element weg.
        _substantiell = re.compile(
            r"^(rows\[|kwic\[|match\[|rank=|Fakten:|Keyness|Richtung|model="
            r"|Zeilen nach |bereich=|docset)"
        )
        substantiell = [z for z in flaeche if _substantiell.match(z)]
        skalare = [z for z in flaeche if not _substantiell.match(z)]
        if paket_knapp_aktiv():
            treffer = _knapp_treffer(item, flaeche)
            fakten_knapp = item.get("fact_surface")
            if treffer:
                substantiell = [z for z in substantiell if not _TREFFERZEILE.match(z)]
                # Je Treffer wiederholte Kennwerte ("metric[3] kw=nicht")
                # stehen schon in den Trefferzeilen.
                skalare = [z for z in skalare if not z.startswith(("metric[", "kw=", "hit="))]
                # Remove scalar facts only when the same information already appears
                # in a rendered table row.
                tabelle = ["  " + z.split(": ", 1)[1] + "  " for z in treffer
                           if z.startswith(_ZEILEN_ETIKETT())]
                if tabelle:
                    substantiell = [z for z in substantiell if not _RANGZEILE.fullmatch(z)]
                    skalare = [z for z in skalare if not any("  " + z + "  " in t for t in tabelle)]
                if isinstance(fakten_knapp, dict):
                    fakten_knapp = {k: v for k, v in fakten_knapp.items() if k != "rows"}
            profil = fakten_knapp.get("profile") if isinstance(fakten_knapp, dict) else None
            if isinstance(profil, dict):
                # Die Belegflaeche kuerzt das Docset-Profil an der Quelle
                # ("'profile_id': '12 We..."), und mit ihm fiel die ref_doc-
                # Achse, die die Paarung belegt (nacht/deutung-stilmerkmale-
                # paarig, A1 und C2). Das Profil kommt ganz aus den Fakten.
                skalare = [z for z in skalare if not z.startswith("profile=")]
                # Place axes last so truncation preserves the source-text count.
                profil = {**{k: v for k, v in profil.items() if k != "axes"},
                          **({"axes": profil["axes"]} if "axes" in profil else {})}
                treffer = treffer + [choose("Profil: ", "Profile: ") + json.dumps(profil, ensure_ascii=False)]
                fakten_knapp = {k: v for k, v in fakten_knapp.items() if k != "profile"}
            knapp = treffer + _knapp_zusammenfassen(
                substantiell[:zeilen_je_item], skalare, fakten_knapp
            )
            # Was an der Kappe faellt, wird genannt, wie in der ausfuehrlichen
            # Form (Methodenbefund C9 der Session CandyConc Paper: weitere
            # substantielle Zeilen hoechstens zwoelf je Posten, ohne Hinweis).
            if len(substantiell) > zeilen_je_item:
                knapp.append(_WEITERE_BELEGZEILEN().format(len(substantiell) - zeilen_je_item))
            for zeile in knapp:
                # Die 400-Zeichen-Grenze gilt den Kennungslisten der Fakten.
                # Das Docset-Profil (Skalarzeile) verlor unter ihr die
                # ref_doc-Achse, die die Paarung belegt (A1 derselben Lesung).
                grenze = PAKET_ZEILE_MAX if zeile.startswith(_FAKTEN_ETIKETT()) else 4 * PAKET_ZEILE_MAX
                zeilen.append("  " + (_zeile_begrenzen(zeile, grenze) if wahr else zeile))
            if not knapp or not (substantiell or treffer):
                # Werkzeuge ohne Belegflaeche (collocate_stats) kommen nur
                # ueber die Vorschau an. Die darf die knappe Form nicht
                # verschlucken.
                vorschau = str(item.get("payload_preview") or "").strip()
                if vorschau and not skalare:
                    zeilen.append(_ERGEBNIS_ETIKETT() + vorschau[:600])
            continue
        kopf_anzahl = min(len(substantiell), zeilen_je_item - 2)
        geordnet = (substantiell[:kopf_anzahl]
                    + skalare[:zeilen_je_item - kopf_anzahl])
        for zeile in geordnet[:zeilen_je_item]:
            zeilen.append("  " + (_zeile_begrenzen(zeile) if wahr else zeile))
        # Was gekappt wurde, wird GENANNT. Ein Deutungsaufruf, der zehn von
        # 73 Perioden sieht und das nicht weiss, schreibt "es gibt keine
        # Trefferreihen" neben einen Anhang, der alle 73 fuehrt.
        gekappt = len(flaeche) - len(geordnet[:zeilen_je_item])
        if voll and gekappt > 0:
            zeilen.append("  " + _WEITERE_BELEGZEILEN().format(gekappt))
        fakten = item.get("fact_surface") or {}
        if isinstance(fakten, dict) and fakten:
            auszug = dict(sorted(fakten.items())[:FAKTEN_JE_ITEM])
            fakt_zeile = "  " + _FAKTEN_ETIKETT() + json.dumps(auszug, ensure_ascii=False)
            zeilen.append(_zeile_begrenzen(fakt_zeile) if wahr else fakt_zeile)
        # FALLBACK: Nicht jedes Werkzeug baut grounding-/fact_surface (z.B.
        # collocate_stats). Live-Befund 2026-09-04: Der Deutungs-Call sah nur
        # Kopfzeilen und meldete ehrenhaft 'keine Daten', obwohl die Tabelle
        # in der UI stand. payload_preview ist dieselbe Flaeche, gegen die
        # auch Referenz-Aufloesung und Zitatwache arbeiten.
        # Die Bedingung lautete bis zum 2026-09-17 "das Element hat GAR keine
        # Zeile beigetragen". Ein Element mit einer einzigen Skalarzeile wie
        # status=success galt damit als belegt, und seine Tabelle blieb
        # draussen. Gefragt ist, ob eine SUBSTANTIELLE Zeile steht.
        leer = (not substantiell) if voll else (not zeilen[-1].startswith("  "))
        if leer:
            vorschau = str(item.get("payload_preview") or "").strip()
            if vorschau:
                zeilen.append(_ERGEBNIS_ETIKETT() + vorschau[:600])
    text = "\n".join(zeilen)
    if len(text) > max_zeichen:
        if not wahr:
            text = text[:max_zeichen] + choose("\n… (Evidenz gekürzt)", "\n… (evidence cut)")
        else:
            # An einer Elementgrenze schneiden und die fehlenden Elemente
            # beim Namen nennen, statt mitten in einer Zeile abzubrechen.
            behalten = 0
            for nr, start in enumerate(item_start):
                if len("\n".join(zeilen[:start])) <= max_zeichen:
                    behalten = nr
            ende = item_start[behalten] if behalten < len(item_start) else len(zeilen)
            fehlend = item_ids[behalten:]
            text = "\n".join(zeilen[:ende]) + choose(
                "\n… EVIDENZ GEKÜRZT: diese {} Elemente wurden erhoben, stehen "
                "aber nicht in dieser Evidenz: {}. Eine Abwesenheit, die eines "
                "davon betreffen könnte, ist nicht belegt, sondern offen.",
                "\n… EVIDENCE CUT: these {} elements were computed but are not "
                "in this evidence: {}. An absence that could concern one of "
                "them is not established but open.",
            ).format(len(fehlend), ", ".join(fehlend))
    return text


def korpus_fuer_synthese(orchestrator: Any) -> str:
    """Pass the corpus structure used during tool calls to synthesis.

    Include source-text grouping, provenance fields, corpus description and
    attribute availability so interpretation uses the same corpus context.
    """
    try:
        from .prompt_layout import _render_corpus_card
        from .recipe_runtime import corpus_card_from_ui_context

        zeilen = _render_corpus_card(corpus_card_from_ui_context(getattr(orchestrator, "ui_context", None) or {}))
    except Exception:  # noqa: BLE001 - ohne Karte bleibt die Nachricht, wie sie war
        return ""
    return "\n".join(z for z in zeilen if z.startswith(
        ("quelltexte:", "entstehung", "attribute:", "lemma:", "einwertige attribute:")))


def synthese_mit_entwurf_aktiv() -> bool:
    """Include the model's draft in synthesis by default.

    The draft preserves interpretation developed during tool use, while the
    evidence package supplies results that may have left the earlier context.
    ``CANDYCONC_SYNTHESE_MIT_ENTWURF=0`` omits the draft.
    """
    return os.environ.get("CANDYCONC_SYNTHESE_MIT_ENTWURF", "1").strip().lower() in (
        "1", "true", "ja", "an",
    )


def deutungs_synthese_messages(
    frage: str, evidenz_text: str, korpus: str = "", entwurf: str = ""
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """System- und Nutzernachricht des frischen Deutungs-Calls."""
    vollstaendig = (
        # Name the evidence in user-facing terms rather than its package format.
        "die Evidenz steht im Nutzertext, und wo sie gekürzt ist, steht das "
        "an ihrem Ende. "
        if paket_wahrheit_aktiv()
        else "die Evidenz im Nutzertext ist vollständig. "
    )
    system = (
        "Du schreibst jetzt die FINALE ANTWORT (Deutungs-Synthese). Es gibt "
        "keine Werkzeuge mehr; " + vollstaendig +
        "Jede Zahl und jedes Korpus-Zitat trägt eine Referenz {{ev:ID}} auf "
        "das Evidenz-Element, aus dem sie stammt.\n\n"
        + DEUTUNGS_AUFTRAG_OHNE_WERKZEUGE
        + "\n\nIn diesem Aufruf gilt zusätzlich: Offene Teilfragen führst du "
        + ("nicht mehr aus. Beantworte die " if paket_wahrheit_aktiv()
           else "nicht mehr aus — die Evidenz liegt vollständig vor. Beantworte die ")
        + "Frage aus ihr; was die Evidenz nicht hergibt, benennst du in einem "
        "Satz. Kein Methodenprotokoll, keine Aufzählung der Werkzeug-Aufrufe. "
        "ABSENZ-REGEL: Bevor du schreibst, es fehlen Zahlen, Häufigkeiten, "
        "Kollokationen oder Belege, prüfe die Kopfzeilen und die Ergebnis-"
        "Zeilen jedes Evidenz-Elements — behaupte Abwesenheit nur, "
        "wenn KEIN Element etwas zur Frage enthält."
    )
    if rechen_pflicht_aktiv():
        system += (
            " RECHEN-PFLICHT: Die letzte Rechenoperation gehört in den Text. "
            "Steht im Paket eine Trefferzahl und ein Nenner, nenne die Rate "
            "pro Million; stehen zwei Raten, nenne das Verhältnis oder die "
            "Differenz; steht eine Rohzahl neben ihrer Bezugsgrösse, rechne "
            "sie zu Ende und nenne das Ergebnis als deinen Befund — eine "
            "Rohzahl allein ist keine Antwort. Die Rechnung selbst ist dir "
            "gestattet, sie braucht kein Werkzeug."
        )
    if teilfragen_pflicht_aktiv():
        system += (
            " TEILFRAGEN-PFLICHT: Lies die Nutzerfrage als Stückliste. "
            "Beantworte Jede bestellte Teilfrage einzeln, in der "
            "Reihenfolge, in der sie gestellt wurde, mit dem Ergebnis aus "
            "der Evidenz — auch ein teilweises Ergebnis gehört an seinen "
            "Platz. Eine Teilfrage, zu der die Evidenz nichts hergibt, "
            "bekommt an ihrer Stelle die benannte Lücke, nie den Verweis "
            "auf ein Methodenkapitel."
        )
    if sprachdeutung_aktiv():
        system += (
            " SPRACHDEUTUNG-PFLICHT: Der Kern der Antwort ist der "
            "sprachliche Befund — was die gefundenen Woerter und Marker "
            "ueber die Texte der Frage sagen. Jeder tragende Befund "
            "bekommt seine eigene Deutung in der Sprache der Daten: was "
            "ein Marker tut (rahmen, erklaeren, aufzaehlen, Subjekte "
            "setzen, Absichten markieren) und was das fuer die Fragende "
            "heisst. Die Beschreibung von Metadatenachsen oder "
            "Korpusfeldern ist keine Deutung und gehoert nur an den Rand, "
            "wo sie eine Zahl stuetzt."
        )
    if masswahl_aktiv():
        system += (
            " MASSWAHL-PFLICHT: Begruende die Wahl deines Masses mit "
            "einer Zahl aus deinem eigenen Lauf, nicht mit einem "
            "Lehrbuchsatz: zeig am eigenen Datensatz, warum dieses Mass "
            "hier das richtigere ist — zum Beispiel eine hohe absolute "
            "Frequenz bei niedrigem log_ratio als Grund, die Differenz "
            "nicht allein zu gewichten. Kein Ergebnis, keine Begruendung: "
            "dann fehlt sie still, ohne dass ein Lehrbuchzitat sie "
            "ersetzt."
        )
    user = (
        _FRAGE_KOPF() + str(frage or "").strip()
        + (choose("\n\nKORPUS:\n", "\n\nCORPUS:\n") + korpus.strip()
           if str(korpus or "").strip() else "")
        + _EVIDENZ_KOPF() + str(evidenz_text or "").strip()
    )
    if str(entwurf or "").strip() and synthese_mit_entwurf_aktiv():
        system += (
            " ENTWURF: Nach der Evidenz steht der Entwurf, den du am Ende der "
            "Werkzeugphase selbst geschrieben hast. Er kennt den Untersuchungsweg, "
            "aber aeltere Werkzeugergebnisse koennen ihm gefehlt haben. Behalte "
            "seine Deutungen und Einordnungen, soweit die Evidenz sie deckt. Pruefe "
            "jede Zahl, jedes Zitat und jede Zuordnung zu Modell, Register oder "
            "Teilkorpus an der Evidenz. Was sie widerlegt, korrigierst du, was sie "
            "zusaetzlich zeigt, nimmst du auf."
        )
        user += choose("\n\nENTWURF AUS DER WERKZEUGPHASE:\n", "\n\nDRAFT FROM THE TOOL PHASE:\n") + (
            entwurf_marker_vereinfachen(entwurf).strip())
    system += antwortsprache_zeile()
    return {"role": "system", "content": system}, {"role": "user", "content": user}


def _FRAGE_KOPF() -> str:
    return choose("FRAGE:\n", "QUESTION:\n")


def _EVIDENZ_KOPF() -> str:
    return choose("\n\nEVIDENZ AUS DEN WERKZEUG-LÄUFEN:\n", "\n\nEVIDENCE FROM THE TOOL RUNS:\n")


def gutachten_gliederung_messages(frage: str, evidenz_text: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Gliederungs-Call: Plan des Gutachtens aus der vorliegenden Evidenz."""
    system = (
        "Du planst ein wissenschaftliches Korpus-Gutachten, das die Frage "
        "des Nutzers beantwortet. Die Evidenz im Nutzertext ist vollständig; "
        "es gibt keine Werkzeuge mehr.\n\n"
        "Erstelle 4 bis 8 Abschnitte. Je Abschnitt GENAU EINE Zeile in "
        "diesem Format:\n"
        "## <Überschrift>\n"
        "<ein Satz: welche Evidenz (welche Zahlen, welche {{ev:ID}}) den "
        "Abschnitt trägt und welche Frage des Nutzers er beantwortet>\n\n"
        "Der erste Abschnitt beantwortet die Frage direkt (Kernbefund), der "
        "letzte benennt Grenzen und was die Evidenz NICHT hergibt. Nutze nur "
        "Evidenz, die im Paket steht. Kein Vorwort, keine Meta-Kommentare."
    )
    user = (
        _FRAGE_KOPF() + str(frage or "").strip()
        + _EVIDENZ_KOPF() + str(evidenz_text or "").strip()
    )
    system += antwortsprache_zeile()
    return {"role": "system", "content": system}, {"role": "user", "content": user}


def gutachten_abschnitt_messages(
    frage: str,
    nr: int,
    titel: str,
    auftrag: str,
    evidenz_text: str,
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Abschnitts-Call: ein Gutachten-Abschnitt aus frischem Kontext."""
    system = (
        "Du schreibst Abschnitt " + str(nr) + " („" + str(titel) + "“) eines "
        "wissenschaftlichen Korpus-Gutachtens zur Frage des Nutzers. Es gibt "
        "keine Werkzeuge mehr; die Evidenz im Nutzertext ist vollständig. "
        "Jede Zahl und jedes Korpus-Zitat trägt eine Referenz {{ev:ID}}.\n\n"
        + DEUTUNGS_AUFTRAG_OHNE_WERKZEUGE
        + "\n\nIn diesem Aufruf gilt zusätzlich: Schreibe NUR diesen einen "
        "Abschnitt als zusammenhängende Prosa (2 bis 4 Absätze), ohne "
        "Einleitung des Gesamttexts, ohne Methodenprotokoll. Deute die "
        "Zahlen; sage präzise, was die Evidenz nicht hergibt. Nutze nur "
        "Evidenz aus dem Paket. ZAHLEN-PFLICHT: Schreibe eine Zahl nur, "
        "wenn sie Wort für Wort (oder als einfache Rundung) im Paket "
        "steht; eine Zahl, die du dort nicht findest, gehört nicht in den "
        "Text — benenne stattdessen die Lücke. ABSENZ-REGEL: Behaupte "
        "fehlende Zahlen oder Belege nur, nachdem du die Kopfzeilen und "
        "Ergebnis-Zeilen jedes Evidenz-Elements geprüft hast — das Paket "
        "enthält die Daten der gelaufenen Werkzeuge."
    )
    user = (
        _FRAGE_KOPF() + str(frage or "").strip()
        + choose("\n\nAUFGABE DIESES ABSCHNRITTS:\n", "\n\nTASK OF THIS SECTION:\n")
        + str(auftrag or "").strip()
        + _EVIDENZ_KOPF() + str(evidenz_text or "").strip()
    )
    system += antwortsprache_zeile()
    return {"role": "system", "content": system}, {"role": "user", "content": user}


def gutachten_gesamt_messages(frage: str, abschnitte: List[str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Gesamt-Call: verbindet die geankerten Abschnitte zum Gutachten."""
    system = (
        "Du verbindest die vorliegenden Abschnitte eines Korpus-Gutachtens "
        "zu einem zusammenhängenden Text, der die Frage des Nutzers "
        "beantwortet. REGELN: Ändere keine Zahl, kein Zitat, keine "
        "fachliche Aussage. Füge eine kurze Einleitung (2-3 Sätze mit dem "
        "Kernbefund) und einen kurzen Schluss hinzu, glätte Übergänge und "
        "streiche echte Wiederholungen. Keine neuen Zahlen, keine neuen "
        "Behauptungen, keine Methodenprotokolle. TEILKONTO-PFLICHT: "
        "Beantworte jede Teilkonto-Frage (den Auftrag eines Abschnitts) "
        "ausschließlich mit den Zahlen, Feldern und Zitaten, die in den "
        "Abschnitten stehen. Enthält die gelieferte Evidenz für eine "
        "Teilkonto-Frage keine Zahl oder kein Feld, antworte mit einem "
        "strukturierten Negativ-Befund („Für <Thema> enthält die "
        "gelieferte Evidenz keine Zahl“), statt Feldnamen, Kardinalitäten "
        "oder Inventare zu behaupten. Gib den vollständigen Text aus."
    )
    user = (
        _FRAGE_KOPF() + str(frage or "").strip()
        + choose("\n\nABSCHNITTE:\n\n", "\n\nSECTIONS:\n\n")
        + "\n\n".join(
            choose("## Abschnitt ", "## Section ") + str(i + 1) + "\n\n" + str(t or "").strip()
            for i, t in enumerate(abschnitte)
        )
    )
    system += antwortsprache_zeile()
    return {"role": "system", "content": system}, {"role": "user", "content": user}


def _parse_gliederung(text: str) -> List[Tuple[str, str]]:
    """Liest die Gliederung: ``## Titel`` plus Auftragszeilen, max 8."""
    abschnitte: List[Tuple[str, str]] = []
    titel: str | None = None
    auftrag_zeilen: List[str] = []
    for zeile in str(text or "").splitlines():
        if zeile.strip().startswith("## "):
            if titel is not None:
                abschnitte.append((titel, " ".join(auftrag_zeilen).strip()))
            titel = zeile.strip()[3:].strip()
            auftrag_zeilen = []
        elif titel is not None and zeile.strip():
            auftrag_zeilen.append(zeile.strip())
    if titel is not None:
        abschnitte.append((titel, " ".join(auftrag_zeilen).strip()))
    return [(t, a) for t, a in abschnitte if t][:MAX_ABSCHNITTE]


async def _ein_call(
    orchestrator: Any,
    turn_state: Any,
    copilot_event_bus: Any,
    messages: List[Dict[str, str]],
) -> str:
    """GENAU EIN frischer LLM-Aufruf; bereinigter Text, leer bei Fehlschlag."""
    try:
        raw = await orchestrator._ra_call_llm_with_recovery(
            turn_state,
            copilot_event_bus,
            invoker=lambda: orchestrator._ra_invoke_llm(
                turn_state,
                request_messages=messages,
                tools_override=[],
                use_stream=False,
            ),
        )
    except Exception:
        # Eine echte Turn-Abbrechung darf nicht als Fehlschlag geschluckt
        # werden; CopilotTurnCancelled selbst ist an das Orchestrator-Modul
        # gebunden und hier import-technisch nicht erreichbar (Stub-Loader).
        if getattr(orchestrator, "cancel_requested", False):
            raise
        return ""
    if not isinstance(raw, dict):
        return ""
    try:
        message = raw.get("choices", [{}])[0].get("message", {}) or {}
    except (AttributeError, IndexError, TypeError):
        return ""
    from .prompts import remove_control_frames

    text = remove_control_frames(
        orchestrator._extract_message_content(str(message.get("content", "") or ""))
    )
    anlauf = _letzter_anlauf(text)
    if anlauf != text:
        zwischenstand("neuansatz_verworfen", text[: len(text) - len(anlauf)],
                      sitzung=_sitzung(orchestrator))
    return anlauf


def _letzter_anlauf(text: str) -> str:
    """Keep the last attempt when generation restarts after an unfinished word.

    Detect recurrence of the first 80 characters following an interrupted
    word. Preserve repetitions that follow a complete sentence.
    """
    rein = str(text or "").strip()
    kopf = rein[:80]
    if len(kopf) < 80:
        return text
    stelle = rein.rfind(kopf)
    davor = rein[:stelle].rstrip()
    if stelle <= 0 or not davor[-1:].isalnum():
        return text
    return rein[stelle:]


def _normiere_items(evidence_items: List[Any]) -> List[Dict[str, Any]]:
    """EvidenceItem-OBJEKTE und Dicts zu Dicts normalisieren (F-66)."""
    items: List[Dict[str, Any]] = []
    for roh in evidence_items or []:
        item = roh.to_dict() if hasattr(roh, "to_dict") else roh
        if isinstance(item, dict):
            items.append(item)
    return items


def _evidenz_zahlen(items: List[Dict[str, Any]]) -> Dict[str, str]:
    """Jede Zahlzeichenfolge der Evidenz -> die Item-ID, die sie traegt.

    Grundlage fuer die numerische Deckung (b) und die deterministischen
    Chips (a): eine Zahl gilt als belegt, wenn sie in fact_surface oder
    grounding_surface ihres Elements vorkommt — Tausender-Varianten
    (1.003 / 1003) zählen mit.
    """
    zuordnung: Dict[str, str] = {}
    for item in items:
        eid = str(item.get("id") or "")
        # Use corpus-reading tools as evidence. The model's own handoff text
        # cannot establish support for its numbers.
        if not eid or not werkzeug_liefert_korpusbeleg(item.get("tool")):
            continue
        text = json.dumps(item.get("fact_surface") or {}, ensure_ascii=False)
        text += "\n" + "\n".join(str(z) for z in (item.get("grounding_surface") or []))
        for token in _extract_numeric_tokens(text, signed=True):
            kanonisch = _zahl_kanonisch(token)
            if kanonisch is not None:
                zuordnung.setdefault(kanonisch, eid)
    return zuordnung


#: Werkzeuge, die ein Inventar auflisten (Feldwerte, gespeicherte Teilkorpora).
#: Ihre Flaeche traegt Kennungen, Daten und Modellnamen und damit fast jede
#: Zahl, aber keine Zaehlung, die eine Aussage der Antwort belegen koennte.
INVENTARWERKZEUGE = frozenset({"metadata_values", "list_docsets"})


def _chip_zahlen(items: List[Dict[str, Any]]) -> Dict[str, str]:
    """Map a number to evidence only when one counting item supplies it.

    An inventory can contain the same number as a document identifier.
    Require a unique counting source so a chip identifies the result's origin.
    """
    traeger: Dict[str, set] = {}
    for item in items:
        if str(item.get("tool") or "").strip() in INVENTARWERKZEUGE:
            continue
        eid = str(item.get("id") or "")
        if not eid or not werkzeug_liefert_korpusbeleg(item.get("tool")):
            continue
        text = json.dumps(item.get("fact_surface") or {}, ensure_ascii=False)
        text += "\n" + "\n".join(str(z) for z in (item.get("grounding_surface") or []))
        for m in re.finditer(r"\d[\d.,]*", text):
            kanonisch = _zahl_kanonisch(m.group())
            if kanonisch is not None:
                traeger.setdefault(kanonisch, set()).add(eid)
    return {zahl: next(iter(ids)) for zahl, ids in traeger.items() if len(ids) == 1}


def _evidenz_zeilen_attribution(items: List[Dict[str, Any]]) -> Dict[str, set]:
    """Tabellenzeilen der Evidenz als Attributionsquelle (F4-Restursache).

    Je Zeile der fact_surface-Tabellen: das Merkmal (erster Textwert ohne
    Ziffer, z. B. das Kollokat) -> kanonische Zahlen der Zeile. Eine Zahl
    im Antworttext ist nur dann ATTRIBUTIERT, wenn ihr Satz dieses Merkmal
    nennt und der Wert in genau dieser Zeile steht — Wert-Präsenz allein
    liess Fehlzuschreibungen durch („Prompting trägt selbst 5", wobei 5
    das min_freq eines andern Elements war)."""
    attribution: Dict[str, set] = {}
    for item in items:
        if not werkzeug_liefert_korpusbeleg(item.get("tool")):
            continue
        fakten = item.get("fact_surface")
        reihen = fakten.get("rows") if isinstance(fakten, dict) else None
        for reihe in reihen or []:
            if not isinstance(reihe, dict):
                continue
            merkmal = next(
                (
                    str(v).strip().casefold()
                    for v in reihe.values()
                    if isinstance(v, str) and v.strip() and not re.search(r"\d", v)
                ),
                None,
            )
            if not merkmal:
                continue
            for v in reihe.values():
                kanon = _zahl_kanonisch(str(v))
                if kanon is not None:
                    attribution.setdefault(merkmal, set()).add(kanon)
    return attribution


def _englische_lesart(roh: str) -> "str | None":
    """Canonical form of a number from an ENGLISH answer text, else None.

    English probe of 2026-09-27, run b1: "174,284" and "180,221" were
    listed as unsupported because the German reading took the comma for a
    decimal comma. English groups with the comma, the dot separates
    decimals, and ".85" is the short form of 0.85.
    """
    kern = roh.strip().rstrip(".,").lstrip(",")
    if re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", kern):
        return repr(float(kern.replace(",", "")))
    if re.fullmatch(r"[+-]?(?:\d*\.\d+|\d+)", kern):
        return repr(float(kern))
    return None


def _zahl_kanonisch(roh: str, deutsch: bool = False) -> "str | None":
    """Normalize a numeric string, returning None for nonnumeric text.

    Interpret answer text using its language's decimal and grouping marks.
    Evidence values retain JSON decimal notation. Thus a German grouped
    integer and an English decimal with the same punctuation remain distinct.
    """
    if deutsch and is_english():
        englisch = _englische_lesart(roh)
        if englisch is not None:
            return englisch
    roh = roh.strip(".,")
    if not roh:
        return None
    if deutsch and re.fullmatch(r"[+-]?\d{1,3}(?:\.\d{3})+(?:,\d+)?", roh):
        return repr(float(roh.replace(".", "").replace(",", ".")))
    try:
        wert = float(roh)  # JSON-Form: Punkt als Dezimalzeichen, 2.7210 == 2.721
    except ValueError:
        try:
            wert = float(roh.replace(".", "").replace(",", "."))  # de-Form 1,003
        except ValueError:
            return None
    return repr(wert)


def _setze_beleg_chips(text: str, zahlen: Dict[str, str], cap: int = 8) -> str:
    """Deterministische Chips (a): eine Zeile, die eine Evidenz-Zahl trägt,
    bekommt die Chip-Marke ihres Elements ans Zeilenende — unabhaengig
    davon, ob das Modell eine {{ev:ID}} geschrieben hat. Hoechstens `cap`
    je Antwort; Zeilen mit eigener Marke bleiben unangetastet."""
    if not zahlen:
        return text
    gesetzt = 0
    aus: List[str] = []
    for zeile in text.split("\n"):
        if gesetzt < cap and "[[beleg:" not in zeile:
            for m in _ZAHL_IM_TEXT.finditer(zeile):
                roh = m.group()
                if (is_english() and m.start() and zeile[m.start() - 1] == "."
                        and not (m.start() > 1 and zeile[m.start() - 2].isdigit())):
                    # English short form ".85": a value below 1, not 85.
                    roh = "." + roh
                kanon = _zahl_kanonisch(roh, deutsch=True)
                # Require numeric evidence with an identifiable result role.
                # Metadata inventories can contain unrelated matching numbers.
                if kanon is None or abs(float(kanon)) < 10:
                    continue
                eid = zahlen.get(kanon)
                if eid:
                    zeile = zeile.rstrip() + " [[beleg:" + eid + "]]"
                    gesetzt += 1
                    break
        aus.append(zeile)
    return "\n".join(aus)


# Zahlen im Fließtext, die NICHT in einem alphanumerischen Bezeichner
# stecken (Messung 6: „GPT‑5.2" wurde zur Entstellung
# „GPT‑5.[Beleg fehlt]" — ein Bindestrich-Bezeichner ist kein Beleg-Mangel).
# Die dritte Sperre verhindert den Neustart MITTEN in einer Zahl: ist der
# Kopf „5" geschuetzt, darf „.2" nicht als eigene Zahl gelten.
_ZAHL_IM_TEXT = re.compile(
    r"(?<![A-Za-zÄÖÜäöüß])(?<![A-Za-zÄÖÜäöüß][\-–—‑.])(?<!\d[.,])\d[\d.,]*"
    # Exclude numbers embedded in names such as "Model 20B", including prefixes.
    r"(?![\d.,A-Za-zÄÖÜäöüß])"
)

_ZITAT_ENTITAET = re.compile(r"„([^\n“]{2,48})“")

# Absenz-Signale fuer den fokussierten Nachlauf (Messung 7: der
# gebuendelte Einzeldurchlauf liess Absenz-Widersprueche durch).
_ABSENZ_SIGNAL = re.compile(
    r"\b(fehl\w*|kein\w*|ohne|nicht (?:verfügbar|vorhanden|messbar))\b",
    re.I,
)

# Deterministische Absenz-Gegenprobe (Messung 7/8: der Verifier JAs seine
# eigenen Absenz-Behauptungen auch gegen Gegen-Evidenz). Je Paar: Absenz-
# Muster im Satz, Gegen-Evidenz-Muster im Belegpaket. NUR Paare mit
# gemessenen Fabrikationen, keine spekulativen.
_ABSENZ_GEGENPROBE = (
    (r"(?i)(stratifizier|disaggregier|modellweise|modelltrenn|modell-?"
     r"spezifisch|modellgetrenn|aufschlüssel|pro modell)",
     r"(?i)(Teilkorpus(?:bildung)? .*(?:model=|Keyness)|Keyness.*Zeilen"
     r"|Keyness:.*Richtung)"),
    # Messung 16: behaupteter Fehlercode 404, belegter Status 400.
    (r"(?i)\b404\b", r"(?i)HTTP 400|status[\"=: ]{1,3}400"),
    # Messung 24: „Keyness-Berechnung ausschließlich auf dem aggregierten
    # KI-Pool" gegen die Richtung-Zeile der modellgetrennten Keyness.
    (r"(?i:(?:fehl\w*|kein\w*|ohne|ausschließlich|aggregier\w*)[^.\n]{0,80}"
     r"keyness|keyness[^.\n]{0,80}(?:fehl\w*|ausschließlich|aggregier\w*))",
     r"(?i:keyness:.*richtung \w+ gegen|teilkorpus(?:bildung)? .*model=)"),
)

# Messung 18: Ergebnis-Behauptungen über ZITIERTE Terme — kommt keiner
# der zitierten Terme im Paket vor, ist die Behauptung unbelegt.
_BEHAUPTUNG_WORT = re.compile(
    r"(?i)(signifikant|überrepräsentiert|gehäuft|dominiert|häufung|zeigen|"
    r"dokumentieren|belegen|bestätigen|offenbaren)",
)
# Messung 21: „null Treffer für „X"" gegen Paketzeilen, die X mit
# Treffern ausweisen — die Absenz ist widerlegt.
_NULL_TREFFER_FUER = re.compile(
    r"(?i)null(?:e|en)?\s+(?:\w+\s+){0,2}treffer\s+(?:für|fuer)\s+"
    r"„([^“\n]+)“",
)

# F4 gelernt (gpt-oss-20b): Fabrikationen verstecken sich in ziffern-
# freien Universal-Aussagen („Alle untersuchten Modelle …", „extreme
# Chi²-Werte") und in ausgeschriebenen Zahlen („zwölf Modelle") — auch
# diese Saetze muessen in die Verifikation.
_UNIVERSAL_BEHAUPTUNG = re.compile(
    r"\b(alle[nrms]?|kein\w*|sämtlich\w*|durchgängig|durchweg|extrem\w*"
    r"|signifikant\w*|systematisch\w*|deutlich\w*|weder|ausschließ\w*"
    r"|schließt\s+aus)\b"
    r"|chi[²2]|keyness|logdice|tf-idf|z-wert|q-wert"
    r"|\b(zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn|elf|zwölf"
    r"|dreizehn|zwanzig|fünfzig|hundert|tausend)\w*\b",
    re.I,
)


async def _anker_verifikation(
    orchestrator: Any,
    turn_state: Any,
    copilot_event_bus: Any,
    text: str,
    zahlen: Dict[str, str],
    items: List[Dict[str, Any]],
) -> Tuple[str, List[str]]:
    """Schlanke Anker-Verifikation (F4-Restursache Attribution): fuer
    zahltragende oder universal-behauptende Saetze prueft EIN gebuendelter
    LLM-Aufruf gegen die Beleg-Tabellen, ob die Aussage der Evidenz
    entspricht — Attribution (Zahl zur Sache) UND Substanz (behauptete
    Messgroesse steht in der Tabelle). NEIN-Urteile: die Zahlen des
    Satzes bzw. der ziffernfreie Satz selbst werden markiert. Kein
    Voll-Verifier, keine Deutungspruefung."""
    zeilen = text.split("\n")
    pruefungen: List[Tuple[int, str]] = []  # (zeilen_index, satz)
    satz_muster = re.compile(r"[^.!\?\n]+[.!\?]")
    for zi, zeile in enumerate(zeilen):
        for satz_m in satz_muster.finditer(zeile):
            satz = satz_m.group()
            # F4 gelernt: ALLE zahltragenden Saetze werden verifiziert —
            # nicht nur solche mit Anfuehrungs-Entitaet (die Absenz- und
            # Fehlzuschreibungs-Fabrikationen hatten keine Entitaet).
            # Absenz-Signale („fehlt", „ohne") wählen zusaetzlich aus,
            # sonst laeuft der Absenz-Nachlauf leer (Messung 7). Saetze
            # mit Zitattermen brauchen die Gegenprobe ebenso (Messung 19:
            # „oft" ueberlebte hinter dem Wort „Software").
            if not (re.search(r"\d", satz)
                    or _UNIVERSAL_BEHAUPTUNG.search(satz)
                    or _ABSENZ_SIGNAL.search(satz)
                    or _ZITAT_ENTITAET.search(satz)):
                continue
            pruefungen.append((zi, satz))
    if not pruefungen:
        return text, []
    liste = "\n".join(
        f"A{i + 1}: {satz}" for i, (_zi, satz) in enumerate(pruefungen)
    )
    system = {
        "role": "system",
        "content": (
            "Du pruefst Aussagen gegen eine Beleg-Tabelle. Fuer jede "
            "nummerierte Aussage antworte GENAU eine Zeile 'A<n>: JA' oder "
            "'A<n>: NEIN'. Pruefe die ATTRIBUTION: stimmt die Zahl zur "
            "genannten Sache in der Tabelle (steht sie in der Zeile des "
            "genannten Gegenstands)? Pruefe die SUBSTANZ: behauptet die "
            "Aussage ein Ergebnis oder eine Messgroesse (z. B. 'alle "
            "untersuchten Modelle', 'extreme Werte', eine benannte "
            "Statistik), das in der Tabelle nicht steht oder nie erhoben "
            "wurde? Behauptet die Aussage ein Ergebnis ueber Gegenstaende "
            "oder Vergleiche, fuer die die Tabelle KEINE Zeile enthaelt "
            "(z. B. Modell-Vergleiche, die nie gerechnet wurden)? Auch das "
            "ist Substanz ohne Stuetze. JA nur bei beidem. NEIN bei "
            "Fehlzuschreibung (die Zahl "
            "gehoert zu einem andern Gegenstand), Absenz-Behauptung (die "
            "Aussage behauptet, Daten fehlen, die die Tabelle zeigt), "
            "Substanz ohne Tabellen-Stuetze, und wenn die Zahl fehlt oder "
            "anders ist. Eine ehrliche Absenz-Aussage, die eine Fehlerzeile "
            "der Tabelle deckt, ist JA. Kein weiterer Text."
        ),
    }
    user = {
        "role": "user",
        "content": "BELEG-TABELLE:\n" + evidenz_paket_text(items) + "\n\nAUSSAGEN:\n" + liste,
    }
    roh = await _ein_call(orchestrator, turn_state, copilot_event_bus, [system, user])
    # Sichtbarkeit (F4-Nachher 2026-09-08): 0 [Beleg fehlt] war von einem
    # stillen Verifier-Fehlschlag ununterscheidbar — der Ausgang wird
    # aufgezeichnet, auch wenn er leer ist.
    zwischenstand(
        "4c_anker_verifikation",
        json.dumps({"aussagen": liste.split("\n"), "urteil": roh},
                   ensure_ascii=False),
        sitzung=_sitzung(orchestrator),
    )
    if not roh.strip():
        return text, []
    # Messung 7 (4c-Aufzeichnung): der gebuendelte Einzeldurchlauf laesst
    # Absenz-Widersprueche durch („Stratifikation fehlt" gegen sichtbare
    # Modell-Teilkorpora = JA). Absenz-Saetze fahren einen zweiten,
    # fokussierten Durchgang: Widerlegt eine Tabellenzeile die behauptete
    # Abwesenheit? NEIN-Urteile werden als A<n>-Zeilen ins Urteil gemischt,
    # der Streich-Loop unten bleibt unveraendert.
    rest = [
        i for i, (_zi, satz) in enumerate(pruefungen)
        if _ABSENZ_SIGNAL.search(satz)
        and not re.search(rf"A{i + 1}\s*:\s*NEIN", roh, re.I)
    ]
    if rest:
        liste2 = "\n".join(
            f"B{k + 1}: {pruefungen[i][1]}" for k, i in enumerate(rest)
        )
        system2 = {
            "role": "system",
            "content": (
                "Du pruefst ABSENZ-Behauptungen gegen eine Beleg-Tabelle. "
                "Jede Aussage behauptet, etwas fehle oder existiere nicht. "
                "Fuer jede nummerierte Aussage antworte GENAU eine Zeile "
                "'B<n>: JA' oder 'B<n>: NEIN'. NEIN, wenn eine Zeile der "
                "Tabelle das behauptete Fehlende doch zeigt oder widerlegt "
                "(z. B. zeigt 'Teilkorpus gebildet model=...', dass eine "
                "modellweise Aufteilung existiert). JA nur, wenn die "
                "Tabelle die Abwesenheit stuetzt. Kein weiterer Text."
            ),
        }
        user2 = {
            "role": "user",
            "content": ("BELEG-TABELLE:\n" + evidenz_paket_text(items)
                        + "\n\nAUSSAGEN:\n" + liste2),
        }
        roh2 = await _ein_call(
            orchestrator, turn_state, copilot_event_bus, [system2, user2])
        zwischenstand(
            "4d_absenz_verifikation",
            json.dumps({"aussagen": liste2.split("\n"), "urteil": roh2},
                       ensure_ascii=False),
            sitzung=_sitzung(orchestrator),
        )
        for k, i in enumerate(rest):
            if re.search(rf"B{k + 1}\s*:\s*NEIN", roh2 or "", re.I):
                roh += f"\nA{i + 1}: NEIN"
    # Deterministische Gegenprobe (Messung 8): Absenz-Behauptungen über
    # eine Analyse-Ebene, deren Zeilen im Paket sichtbar sind, werden
    # modellunabhängig gestrichen.
    term_marken: List[Tuple[int, str]] = []
    if items:
        paket = evidenz_paket_text(items)
        paket_klein = paket.casefold()
        # Chip-Zitat-Prüfung (Messung 28b): ein [[beleg:ID]]-Verweis deckt
        # nur das ELEMENT — das konkrete Zitat muss in dessen Zeilen
        # wiederzufinden sein, sonst wird es markiert.
        items_nach_id: Dict[str, Dict[str, Any]] = {}
        for it_roh in items:
            it_d = it_roh.to_dict() if hasattr(it_roh, "to_dict") else it_roh
            if isinstance(it_d, dict) and it_d.get("id") is not None:
                items_nach_id[str(it_d["id"])] = it_d
        for i, (_zi, satz) in enumerate(pruefungen):
            if re.search(rf"A{i + 1}\s*:\s*NEIN", roh, re.I):
                continue
            strike = False
            for satz_key, gegen in _ABSENZ_GEGENPROBE:
                if re.search(satz_key, satz) and re.search(gegen, paket):
                    strike = True
                    break
            if not strike:
                # Chip-Zitat-Prüfung (Messung 28b): das zitierte Kontext-
                # Fragment muss in den Zeilen der verlinkten Elemente
                # wiederzufinden sein — der Chip deckt nur das Element.
                chips_im_satz = re.findall(
                    r"\[\[beleg:([^\]\n]+)\]\]", satz)
                chip_flachen: List[str] = []
                for cid in chips_im_satz:
                    it = items_nach_id.get(cid.strip())
                    if isinstance(it, dict):
                        chip_flachen.append(normalisiert_flaeche(it))
                zitate = [z.strip() for z in _ZITAT_ENTITAET.findall(satz)
                          if z.strip()]
                if zitate and chip_flachen:
                    for z in zitate:
                        z_n = normalisiert(z)
                        if len(z_n) >= 12 and not any(
                            z_n in f for f in chip_flachen
                        ):
                            strike = True
                            break
            if not strike:
                zitate = [z.strip() for z in _ZITAT_ENTITAET.findall(satz)
                          if z.strip()]
                if zitate and _BEHAUPTUNG_WORT.search(satz):
                    # Wortgrenzen statt Substring: „oft“ darf nicht vom
                    # Wort „Software“ gedeckt werden (Messung 19). Jeder
                    # fehlende Term wird EINZELN markiert (Messung 20:
                    # Alle-oder-keine liess den Satz stehen, weil ein
                    # zitierte Term zufaellig im Paket stand).
                    for z in zitate:
                        if not re.search(
                            r"(?<![A-Za-zÄÖÜäöüß])" + re.escape(z.casefold())
                            + r"(?![A-Za-z])",
                            paket_klein,
                        ):
                            term_marken.append((zi, z))
                # Null-Treffer-Behauptungen gegen Paketzeilen mit Treffern
                # für denselben Gegenstand (Messung 21).
                for m in _NULL_TREFFER_FUER.finditer(satz):
                    z = m.group(1).strip()
                    if re.search(
                        re.escape(z.casefold())
                        + r".{0,120}(?:treffer|zeilen)",
                        paket_klein,
                    ):
                        strike = True
                        break
            if strike:
                roh += f"\nA{i + 1}: NEIN"
    gestrichen: List[str] = []
    for i, (zi, satz) in enumerate(pruefungen):
        if re.search(rf"A{i + 1}\s*:\s*NEIN", roh, re.I):
            if "[[beleg:" in zeilen[zi] or not re.search(r"\d", satz):
                # Chip-Zeile: die Marke belegt nur EINE Zahl der Zeile,
                # die Zahlen-Substitution wuerde die Chip-ID beschaedigen
                # — der Satz selbst faellt. Gilt auch fuer ziffernfreie
                # Universal-Fabrikationen (sie behaupten Evidenz, die es
                # nicht gibt).
                zeilen[zi] = zeilen[zi].replace(
                    satz.strip(), MISSING_EVIDENCE_PLACEHOLDER)
                gestrichen.append(satz.strip()[:48].rstrip(" ,;") + "…")
            else:
                # Die Sammel-Liste aus der Zeile (dem selben Umfang wie die
                # Substitution): der Satz allein kann leer bleiben, wenn
                # nur Bezeichner-Ziffern geschuetzt sind — sonst wuerde
                # `if not gestrichen` die geaenderte Zeile verwerfen.
                for m in _ZAHL_IM_TEXT.finditer(zeilen[zi]):
                    kanon = _zahl_kanonisch(m.group())
                    if kanon:
                        gestrichen.append(kanon)
                zeilen[zi] = _ZAHL_IM_TEXT.sub(
                    MISSING_EVIDENCE_PLACEHOLDER, zeilen[zi])
    # Term-Einzelpruefung anwenden: der fehlende zitierte Term bekommt
    # seinen Platzhalter direkt hinter dem Zitat, der Satz bleibt stehen
    # (F6: markieren, nicht streichen).
    for zi, term in term_marken:
        zeilen[zi] = zeilen[zi].replace(
            "\u201e" + term + "\u201c",
            "\u201e" + term + "\u201c " + MISSING_EVIDENCE_PLACEHOLDER,
        )
        gestrichen.append("\u201e" + term + "\u201c")
    if not gestrichen:
        return text, []
    return "\n".join(zeilen), gestrichen


def normalisiert_flaeche(item: Dict[str, Any]) -> str:
    """Die prüfbare Fläche eines Elements: Belegzeilen + Fakten,
    normalisiert für Zitat-Vergleiche."""
    teile = [str(z) for z in (item.get("grounding_surface") or [])]
    fakten = item.get("fact_surface")
    if isinstance(fakten, dict) and fakten:
        teile.append(json.dumps(fakten, ensure_ascii=False))
    return normalisiert(" ".join(teile))


def normalisiert(s: str) -> str:
    """Leerraum kollabieren, Leerraum vor Satzzeichen entfernen,
    Groß-/Kleinschreibung angleichen."""
    s = re.sub(r"\s+", " ", str(s or "").strip())
    return re.sub(r"\s+([,.!?;:])", r"\1", s).casefold()


def _zitat_normalisiert(s: str) -> str:
    """Leerraum kollabieren und Leerraum vor Satzzeichen entfernen —
    Zitate und Belegzeilen unterscheiden sich häufig genau darin.

    Eckige Klammern fallen weg: das Paket markiert die Fundstelle eines
    KWIC-Treffers mit [..], die Synthese uebernimmt das, und am 2026-09-25
    erklaerte der Zitathinweis deshalb zehn wortgleiche Belege fuer
    unverifizierbar (Lesung nacht/deutung-stilmerkmale-paarig, A6)."""
    s = re.sub(r"\[([^\]]*)\]", r"\1", str(s or ""))
    # Strip unmatched boundary brackets as well as complete pairs because
    # a nested quotation mark can end the extracted quote before its bracket.
    s = s.replace("[", "").replace("]", "")
    # A comma after whitespace directly before a word can stand for an
    # opening quotation mark. Normalize it like other quotation marks.
    s = re.sub(r"(?<=\s),(?=\w)", "", s)
    # Treat escaped line breaks and slash-separated line breaks as whitespace.
    # Keep the quoted words subject to the normal matching rules.
    s = re.sub(r"\\n|\s/\s", " ", s)
    # Normalize markdown stars and heading markers whether the evidence
    # lists separate tokens or the answer renders them as formatting.
    s = re.sub(r"\s+", " ", s.replace("*", "").replace("#", "").strip())
    # Normalize typographic hyphens and ASCII hyphens in quoted words.
    s = re.sub("[\u2010\u2011\u2012\u2013\u2014\u2212]", "-", s)
    # Normalize inner quotation marks whose style changes inside a quotation.
    s = re.sub(r"\s+", " ", re.sub(
        "[\u201e\u201c\u201d\u201a\u2018\u2019\u00ab\u00bb\u2039\u203a\"']", " ", s)).strip()
    # Normalize capitalization and spacing around brackets so sentence-initial
    # forms and tokenized punctuation match their rendered quotation.
    s = re.sub(r"\(\s+", "(", s)
    return re.sub(r"\s+([,.!?;:)])", r"\1", s).casefold()


#: Eine Auslassung in einem Zitat: "…", "..." oder ein Platzhalter wie das X in
#: "die eigentliche X". Die woertlichen Teile muessen in dieser Reihenfolge stehen.
_AUSLASSUNG = re.compile(r"…|\.\.\.|(?<![\w-])[A-Z](?![\w-])")


#: A gap with a size note: „nicht nur …(≤12 Token)… sondern“. The bracket says
#: what the omission covers, no corpus line contains it.
_LUECKENANGABE = re.compile(
    r"(?:…|\.\.\.)\s*\([^()\n]{1,40}\)\s*(?:…|\.\.\.)?|\([^()\n]{1,40}\)\s*(?:…|\.\.\.)")


def _zitat_belegt(spanne: str, heu_norm: str) -> bool:
    if "/" in spanne and not re.search(r"\s", spanne.strip()):
        # Eine Begriffsliste wie „gleichzeitig/zugleich“: jeder Begriff fuer sich.
        return all(_zitat_belegt(teil, heu_norm) for teil in spanne.split("/") if teil.strip())
    # A pattern with a size note at its gap counts as an omission, the
    # literal parts stay checked.
    spanne = _LUECKENANGABE.sub("…", spanne)
    teile = [t for t in (_zitat_normalisiert(x).strip() for x in _AUSLASSUNG.split(spanne)) if t]
    if sum(len(t) for t in teile) < 12:
        # Zu kurz zum Pruefen, wie eine Spanne unter zwoelf Zeichen.
        return True
    return re.search(".{0,160}?".join(re.escape(t) for t in teile), heu_norm, re.S) is not None


def _aus_der_frage_ohne_beleganspruch(m: "re.Match[str]", text: str, frage: str) -> bool:
    """Recognize a span quoted from the question without a corpus-evidence claim.

    A following evidence marker in the same sentence still requires checking
    the span against corpus evidence.
    """
    if not frage or normalisiert(m.group(1)) not in normalisiert(frage):
        return False
    satzrest = re.split(r"(?<=[.!?])\s|\n", text[m.end():], maxsplit=1)[0]
    return not re.search(r"\[\[\s*beleg\s*:|\{\{\s*ev\s*:", satzrest)


#: Werkzeuge, deren Belege Zahlen tragen und keine Textzeilen. Ein Zitat mit
#: ihrem Marker nennt einen Suchbegriff, es gibt keine Korpuszeile wieder.
_ZAEHLWERKZEUGE = (
    "query_count", "keyness", "ngram_contrast", "collocate_stats", "contrast_collocates",
    "compare_collocates", "frequency_list", "dispersion_offsets", "metadata_values",
    "create_docset", "list_docsets",
)
_EIGENE_STIMME = re.compile(
    r"(?i)druck|formulier|\b(?:satz|these|behauptung|schema|muster|etikett|erwartung)\b"
)
_BELEGWORT = re.compile(
    # Match "schreib" only at a word boundary so corpus-description references
    # are not mistaken for a request to formulate new text.
    r"(?i)beleg|beispiel|z\.\s?b\.|etwa|\bschreib|lautet|heißt es|originaltext|zeile|treffer"
)
#: The same classes for an English answer, checked in addition to the German ones.
_EIGENE_STIMME_EN = re.compile(
    r"(?i)phras|formulat|wording|\b(?:sentence|thesis|claim|pattern|label|expectation|slogan|term)\b"
)
_BELEGWORT_EN = re.compile(
    r"(?i)\be\.g\.|\bfor (?:example|instance)\b|\bexamples?\b|\bsuch as\b|\blines?\b|\bhits?\b"
    r"|\breads?\b|\bwrites?\b|\bwrote\b|\bquoted?\b|\bverbatim\b|\boriginal text\b"
)


def _mit_beleganspruch(m: "re.Match[str]", text: str) -> bool:
    """Determine whether a quotation presents itself as a corpus passage.

    Check spans introduced by an evidence term or accompanied by a row or
    document reference. Exclude proposed wording, labels and quotations that
    contain evidence markers as part of the answer's own formulation.
    """
    if re.search(r"\[\[\s*beleg\s*:|\{\{\s*ev\s*:", m.group(1)):
        return False
    englisch = is_english()
    # Nur der eigene Satz vor der Anfuehrung: „im selben Satz „außerdem“. -
    # Menschlicher Originaltext: „Europol …““ ist eine Korpuszeile (Frage 4).
    davor = re.split(r"(?<=[.!?])\s|\n", text[max(0, m.start() - 60):m.start()])[-1]
    # An evidence marker is not an evidence word in the surrounding prose.
    davor = re.sub(r"\[\[\s*beleg\s*:[^\]]*\]\]|\{\{\s*ev\s*:[^}]*\}\}", "", davor)
    # In "Beleg für X", X names the claim being discussed.
    # Check this before interpreting a following concordance chip as a quotation claim.
    if re.search(r"(?i)beleg\w*\s+(?:für|dafür)\s*$", davor):
        return False
    if englisch and re.search(r"(?i)\b(?:evidence|proof)\s+(?:for|of|that)\s*$", davor):
        return False
    rest = re.split(r"(?<=[.!?])\s|\n|„" + ("|“" if englisch else ""),
                    text[m.end():], maxsplit=1)[0][:160]
    for werkzeug in re.findall(r"\[\[\s*beleg\s*:\s*E_([a-z_]+?)_\d+", rest):
        if werkzeug not in _ZAEHLWERKZEUGE:
            return True
    if "(Dok." in rest:
        return True
    if _EIGENE_STIMME.search(davor) or (englisch and _EIGENE_STIMME_EN.search(davor)):
        return False
    # Backticked search terms name the object of study rather than evidence.
    # Mask them at equal length to preserve the surrounding context window.
    ohne_code = re.sub(r"`[^`\n]*`", lambda z: " " * len(z.group(0)), text[:m.start()])
    ohne_code = re.split(r"(?<=[.!?])\s|\n", ohne_code[max(0, m.start() - 60):])[-1]
    ohne_code = re.sub(r"\[\[\s*beleg\s*:[^\]]*\]\]|\{\{\s*ev\s*:[^}]*\}\}", "", ohne_code)
    return bool(_BELEGWORT.search(ohne_code[-40:])
                or (englisch and _BELEGWORT_EN.search(ohne_code[-40:])))


def _zitat_heuhaufen(items: List[Dict[str, Any]]) -> str:
    """Combine evidence lines, rendered hit rows and query terms for quote matching.

    Rendered hit rows join left context, match and right context, which may
    be separate in the evidence surface. Query terms also support mentions
    of the searched expression.
    """
    teile: List[str] = []
    for item in items:
        flaeche = [str(z).strip() for z in (item.get("grounding_surface") or [])]
        teile.extend(flaeche)
        try:
            # Umbrueche als Leerraum wie bisher: ein Zitat ueber einen Absatz hinweg
            # bleibt belegt, das \n der Paketzeile wuerde es trennen.
            teile.extend(_knapp_treffer(item, flaeche, umbruch=" "))
        except Exception:  # noqa: BLE001 - ohne Trefferzeilen bleibt die Belegflaeche
            pass
        try:
            aufruf = json.loads(str(item.get("query") or "{}"))
        except ValueError:
            aufruf = {}
        abfrage = str(aufruf.get("query") or aufruf.get("term") or "") if isinstance(aufruf, dict) else ""
        begriffe = re.findall(r'word\s*=\s*"([^"]+)"', abfrage)
        teile.append(" ".join(begriffe) if begriffe else abfrage)
    return " \n".join(t for t in teile if t)


_ZITAT_DE = re.compile(r"„([^\n“\"]{12,})[“\"]")
#: In an English answer also the English forms, “…” and "…" (answer_language.py).
_ZITAT_EN = (
    _ZITAT_DE,
    re.compile(r"“([^\n”\"]{12,})[”\"]"),
    re.compile(r"\"([^\n\"]{12,})\""),
)


def _zitatspannen(such: str) -> List["re.Match[str]"]:
    """Quotation spans of the answer, group 1 is the quoted text.

    A German answer is checked for „…“ only, as before. An English answer
    quotes with “…” or "…", and the notice never saw those spans: every
    English quotation passed unchecked. Overlapping spans keep the first.
    """
    if not is_english():
        return list(_ZITAT_DE.finditer(such))
    treffer = sorted((m for muster in _ZITAT_EN for m in muster.finditer(such)),
                     key=lambda m: (m.start(), -m.end()))
    frei: List["re.Match[str]"] = []
    ende = -1
    for m in treffer:
        if m.start() >= ende:
            frei.append(m)
            ende = m.end()
    return frei


def _unverifizierte_zitate(text: str, items: List[Dict[str, Any]], frage: str = "") -> List[str]:
    """Lange Anfuehrungs-Spannen, die in KEINER Beleglage stehen (F4:
    Belegzeilen-Imitate). Werden NICHT gestrichen (B9: eigene Stimme),
    aber als unverifiziert dokumentiert."""
    heu_norm = _zitat_normalisiert(_zitat_heuhaufen(items))
    funde: List[str] = []
    # Allow straight quotation marks to close a quotation.
    # Mask standalone quotation characters in backticks at equal length so
    # they do not open a false span. Keep backticked passages containing words
    # eligible for checking.
    zeichen = r"[„“”\"]" if is_english() else r"[„“\"]"
    such = re.sub(r"`[^`\n\w]*`", lambda z: re.sub(zeichen, "\x02", z.group(0)), text)
    for m in _zitatspannen(such):
        spanne = text[m.start(1):m.end(1)].strip()
        # Alternatives with placeholders describe a pattern rather than a literal quote.
        if " / " in spanne and ("..." in spanne or "…" in spanne):
            continue
        # Leerraum- und Satzzeichen-Normalisierung (Messung 26: das Zitat
        # „... seine Aufgaben?" stand in der Belegzeile als "... Aufgaben ?"
        # — der exakte Vergleich flaggte es fälschlich als unbelegt).
        if _aus_der_frage_ohne_beleganspruch(m, text, frage):
            continue
        if not _mit_beleganspruch(m, text):
            continue
        if not _zitat_belegt(spanne, heu_norm) and spanne not in funde:
            funde.append(spanne)
    return funde


_SATZTRENNER = re.compile(r"(?<=[.!?])(\s+)")
_LISTENZEILE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def _zeilenzeiger_entfernen(text: str) -> str:
    """Remove draft-handoff row pointers from the final answer.

    Keep their evidence markers. The pointers identify rows during synthesis
    but would otherwise repeat beside each value in the delivered text.
    """
    marke = r"(\{\{\s*ev\s*:[^}]*\}\})"
    text = re.sub(marke + r"\s*\((?:Zeile|Treffer) \d+\)", r"\1", str(text or ""))
    text = re.sub(marke + r"(\s*)\((?:Zeile|Treffer) \d+,\s*", r"\1\2(", text)
    # Keep the marker from a parenthesized row pointer unless it already
    # appears immediately before the parenthesis.
    teile = []
    ende = 0
    for m in re.finditer(r"\s*\((?:Zeile|Treffer) \d+\s*" + marke + r"\s*\)", text):
        davor = text[ende:m.start()]
        teile.append(davor)
        bisher = "".join(teile).rstrip()
        teile.append("" if bisher.endswith(m.group(1)) else " " + m.group(1))
        ende = m.end()
    teile.append(text[ende:])
    # Remove an unparenthesized row pointer immediately before a marker.
    text = re.sub(r",\s*(?:Zeile|Treffer) \d+\s*(?=\{\{\s*ev\s*:)", " ", "".join(teile))
    # Remove other row-pointer forms immediately before a marker.
    # Deduplicate markers that become adjacent after removing the pointer.
    text = re.sub(r"\s*(?:\((?:Zeilen?|Treffer) [\d\s,–-]+(?:(?:und|gegen) (?:(?:Zeilen?|Treffer) )?"
                  r"[\d\s,–-]+)*\)|\b(?:in|aus) (?:Zeile|Treffer) \d+)\s*(?=\{\{\s*ev\s*:)", " ", text)
    # Remove a trailing row pointer inside a parenthesis containing a marker.
    text = re.sub(r"(\([^()]*\{\{\s*ev\s*:[^}]*\}\}[^()]*?),\s*(?:Zeile|Treffer) \d+\)", r"\1)", text)
    # Remove an unparenthesized row pointer after a marker or its unit.
    text = re.sub(r"(\{\{\s*ev\s*:[^}]*\}\}(?:\s+(?:pro Mio\.|pro Million|pmw|Treffern?))?)\s*,?\s+"
                  r"(?:Zeile|Treffer) \d+\b", r"\1", text)
    return re.sub(marke + r"\s*\1", r"\1", text)


def _unaufloesbare_marke_allein_entfernen(text: str) -> str:
    """Remove an unresolved marker when the same claim has resolved markers.

    Preserve the supported statement. Claims without a resolved marker retain
    the existing sentence-removal rule. Treat each list row as one statement.
    """
    platzhalter = re.compile(r"[ \t]*" + re.escape(MISSING_EVIDENCE_PLACEHOLDER))

    def _bereinigt(aussage: str) -> str:
        if MISSING_EVIDENCE_PLACEHOLDER in aussage and "[[beleg:" in aussage:
            return platzhalter.sub("", aussage)
        return aussage

    zeilen = []
    for zeile in str(text or "").split("\n"):
        if MISSING_EVIDENCE_PLACEHOLDER not in zeile:
            zeilen.append(zeile)
        elif _LISTENZEILE.match(zeile):
            zeilen.append(_bereinigt(zeile))
        else:
            zeilen.append("".join(_bereinigt(s) for s in _SATZTRENNER.split(zeile)))
    return "\n".join(zeilen)


async def _verankere(
    orchestrator: Any,
    turn_state: Any,
    copilot_event_bus: Any,
    content: str,
    evidence_items: List[Any],
) -> Tuple[str, List[str]]:
    """Mechanische Ankerung nach der umgekehrten Regel (2026-09-04).

    Die Ankerungspflicht gilt fuer ZAHLEN und FUNDSTELLEN — nicht fuer
    Saetze. Ein Satz, der auf verankerten Zahlen steht, bleibt; eine
    ungedeckte Zahl wird sichtbar markiert, der Satz faellt NICHT mehr.
    Zitate beruehrt die Ankerung gar nicht: sie sind eigene Stimme des
    Antworttexts (Formulierungsvorschlag, Wortnennung), solange sie keine
    Evidenz behaupten. Gefallen ist nur der Satz, der Evidenz behauptet,
    die es nicht gibt (unresolvierte {{ev:ID}}). Zurueck kommt der Text
    und die Liste der gestrichenen Zahlen fuer EINE Sammelzeile je
    Antwort.
    """
    # Messung 6: das Modell schreibt manchmal Literal-[[beleg:ID]]-Marker.
    # Sie reisen durch denselben Validierungsgang wie {{ev:ID}}: bekannte
    # IDs werden Chips, fremde fallen mit ihrem Satz.
    content = re.sub(
        r"\[\[\s*beleg\s*:\s*([A-Za-z0-9_\-]+)\s*\]\]",
        r"{{ev:\1}}",
        str(content or ""),
    )
    # Validierte Zitat-Marker (ohne Feld) ueberleben als Chip-Marke im
    # ausgelieferten Text; das Frontend macht daraus den klickbaren Beleg.
    # Unbekannte IDs bleiben Marker, fallen also mit ihrem Satz (alte Regel).
    items = _normiere_items(evidence_items)
    bekannte_ids = {
        str(item.get("id"))
        for item in items
        if item.get("id")
    }

    def _schuetze(treffer: "re.Match[str]") -> str:
        marker_id = treffer.group(1).strip()
        if marker_id in bekannte_ids:
            return "[[beleg:" + marker_id + "]]"
        # Keep alternative ID spellings as chips when they resolve to one item.
        # Otherwise bare-ID resolution could substitute the item's primary value
        # into prose that only intended an evidence link.
        kennung = "E_" + marker_id if ("E_" + marker_id) in bekannte_ids else ""
        if not kennung:
            kennung, rest = _eindeutige_kennung(marker_id, sorted(bekannte_ids))
            kennung = kennung if rest == kennung else ""
        if kennung:
            return "[[beleg:" + kennung + "]]"
        return treffer.group(0)

    content = re.sub(
        r"\{\{\s*ev\s*:\s*([A-Za-z0-9_\-]+)\s*\}\}", _schuetze,
        _zeilenzeiger_entfernen(str(content or ""))
    )
    erste = orchestrator._ra_resolve_reference_draft(
        turn_state, content, detect_bare_numbers=False
    )
    text = str(erste.get("text") or "")
    if list(erste.get("unresolved") or []):
        if zahlen_streichen_aktiv():
            text = _unaufloesbare_marke_allein_entfernen(text)
            text = drop_unresolved_sentences(text)
        else:
            # With number removal disabled, record an unresolved marker while
            # preserving the statement, following the unsupported-number policy.
            zwischenstand("marken_ohne_beleg", "\n".join(
                str(u) for u in (erste.get("unresolved") or [])),
                sitzung=_sitzung(orchestrator))
            text = re.sub(r"[ \t]*" + re.escape(MISSING_EVIDENCE_PLACEHOLDER), "", text)
    zweite = orchestrator._ra_resolve_reference_draft(
        turn_state, text, detect_bare_numbers=True
    )
    text = str(zweite.get("text") or "")
    bare_numbers = list(zweite.get("bare_numbers") or [])
    # (b) Numerische Deckung: eine Zahl, die in fact_surface oder
    # grounding_surface ihres Elements steht, ist NICHT unbelegt — auch
    # wenn die woertliche Surface-Deckung sie verfehlt (Format, Rundung).
    zahlen = _evidenz_zahlen(items)
    zeilen_attribution = _evidenz_zeilen_attribution(items)

    def _gedeckt(finding: Dict[str, Any]) -> bool:
        if finding.get("unit") == "percent":
            return False
        written = str(finding.get("number") or "")
        kanon = _zahl_kanonisch(written, deutsch=True)
        if kanon is None:
            return True
        places = next((places for value, places in _zahllesarten(written) if value == float(kanon)), 0)
        if _numeric_token_is_supported(kanon, set(zahlen), decimal_places=places):
            return True
        kontext = str(finding.get("context") or "").casefold()
        return any(
            merkmal in kontext and kanon in kanonische
            for merkmal, kanonische in zeilen_attribution.items()
        )

    bare_numbers = [b for b in bare_numbers if not _gedeckt(b)]
    # Was gestrichen wuerde, wird IMMER aufgeschrieben, damit ein Leser jede
    # dieser Zahlen am Index nachpruefen kann. Gestrichen wird nur mit
    # Schalter (siehe zahlen_streichen_aktiv).
    zwischenstand(
        "zahlen_ohne_wortbeleg",
        "\n".join(
            "{}  |  {}".format(b.get("number"), str(b.get("context") or "")[:160])
            for b in bare_numbers
        ) or "keine",
        sitzung=_sitzung(orchestrator),
    )
    if bare_numbers and zahlen_streichen_aktiv():
        text = strike_unbound_numbers(text, bare_numbers, annotate=False)
        struck = [str(b.get("number") or "") for b in bare_numbers]
    else:
        struck = []
    # (c) Anker-Verifikation (F4): zahltragende Saetze mit Entitaet
    # gegen die Beleg-Tabellen — Absenz-Behauptungen und Fehlzu-
    # schreibungen werden hier markiert (NEIN-Urteil -> ZahlPlaceholder).
    if f4_wachen_aktiv():
        text, verifiziert = await _anker_verifikation(
            orchestrator, turn_state, copilot_event_bus, text, zahlen, items
        )
        struck.extend(verifiziert)
    text = _setze_beleg_chips(text, _chip_zahlen(items))
    # (a) Quote-Politik F4: lange Anfuehrungs-Spannen ohne Beleglage-Fund
    # werden NICHT gestrichen (B9: eigene Stimme, z. B. Formulierungs-
    # vorschlaege), aber ehrlich als unverifiziert gekennzeichnet.
    unverifiziert = _unverifizierte_zitate(text, items, str(getattr(turn_state, "normalized_question", "") or ""))
    if unverifiziert:
        text += choose(
            "\n\nHinweis: {n} wörtliche Zitate stehen nicht in der Beleglage und sind "
            "damit nicht als Korpusbelege verifizierbar ({z}).",
            "\n\nNote: {n} verbatim quotation(s) are not in the evidence and "
            "cannot be verified as corpus evidence ({z}).",
        ).format(n=len(unverifiziert), z="; ".join(
            choose("„{}“", "“{}”").format(z[:60]) for z in unverifiziert[:3]))
    return text, [z for z in struck if z]


def _sammelhinweis(struck: List[str]) -> str:
    """GENAU EINEAnnotation je Antwort fuer alle markierten Zahlen."""
    eindeutig = list(dict.fromkeys(struck))
    if not eindeutig:
        return ""
    # Ab 7 Markern zaehlt die Sammelzeile statt aufzulisten — der
    # Urteilerbefund (Messung 25/26): lange Aufzaehlungen brechen den
    # Lesefluss, und die stille Kappe bei 6 verheimlicht den Rest.
    if len(eindeutig) > 6:
        return choose(
            "\n\nHinweis: Unbelegte Angaben wurden durch {p} ersetzt — {n} Stellen insgesamt.",
            "\n\nNote: Unsupported figures were replaced by {p}, {n} places in total.",
        ).format(p=MISSING_EVIDENCE_PLACEHOLDER, n=len(eindeutig))
    return choose(
        "\n\nHinweis: Unbelegte Angaben wurden durch {p} ersetzt ({l}).",
        "\n\nNote: Unsupported figures were replaced by {p} ({l}).",
    ).format(p=MISSING_EVIDENCE_PLACEHOLDER, l=", ".join(eindeutig))


def _sammelhinweis_aus_finaltext(final: str) -> str:
    """Der Zähler zählt die Marker im ENDTEXT — nicht die Abschnitts-
    Marken, die der Gesamt-Re-Write wieder entfernt hat (Messung-23-
    Diagnoselauf: „42 Stellen“ gemeldet, der Endtext zeigte 2)."""
    anzahl = final.count(MISSING_EVIDENCE_PLACEHOLDER)
    if not anzahl:
        return ""
    mehr_wort = (choose("Stelle", "place") if anzahl == 1
                 else choose("Stellen", "places"))
    return choose(
        "\n\nHinweis: Unbelegte Angaben wurden durch {p} ersetzt — {n} {w} im Endtext.",
        "\n\nNote: Unsupported figures were replaced by {p}, {n} {w} in the final text.",
    ).format(p=MISSING_EVIDENCE_PLACEHOLDER, n=anzahl, w=mehr_wort)


def _sitzung(orchestrator: Any) -> str:
    return getattr(orchestrator.session, "session_id", "")


def entwurf_als_antwort_aktiv() -> bool:
    """Enable delivery of the model's own final draft, disabled by default.

    Use the draft only after the model voluntarily ends tool use and supplies
    nonempty answer text. Other cases continue through synthesis.
    """
    return os.environ.get("CANDYCONC_ENTWURF_ALS_ANTWORT", "0").strip().lower() in (
        "1", "true", "ja", "an",
    )


def entwurf_marker_vereinfachen(text: str) -> str:
    """Replace field references with item references while preserving row pointers.

    The number is already in the draft. An item chip avoids inserting it
    twice and supports references whose fields contain tables rather than scalars.
    """
    return re.sub(r"\{\{\s*ev\s*:\s*([A-Za-z0-9_\-]+)\.([^}]*)\}\}", _marke_mit_zeile, str(text or ""))


def _marke_mit_zeile(m: "re.Match[str]") -> str:
    """Preserve the row path in the package's row-label format.

    KWIC references use "Treffer N" and table references use "Zeile N",
    where N remains the original row index for the synthesis handoff.
    """
    kennung, pfad = m.group(1), m.group(2)
    zeile = re.match(r"\s*(?:rows|kwic)\[(\d+)\]", pfad)
    if not zeile:
        return "{{ev:%s}}" % kennung
    art = "Treffer" if ("cqlf" in kennung or "kwic" in kennung) else "Zeile"
    return "{{ev:%s}} (%s %s)" % (kennung, art, zeile.group(1))


async def fuehre_deutungs_synthese_aus(
    orchestrator: Any,
    turn_state: Any,
    copilot_event_bus: Any,
    evidence_items: List[Any],
    entwurf: str = "",
) -> str:
    """Einstieg der Finalisierung: Entwurf des Modells, Gutachten oder Einzel-Call.

    Leerer Text gilt als Fehlschlag; der fail-closed-Fallback der
    Finalisierung (Salvage) greift dann wie bei jedem anderen Leerlauf.
    Setzt den Kontrakt auf "deutungs_synthese", damit die Zitatwache an
    der Landung eigene Zitate stehen laesst (Regelumkehr).
    """
    vertrag = getattr(orchestrator, "_active_analysis_contract", None)
    if isinstance(vertrag, dict):
        vertrag["grounding_output_mode"] = "deutungs_synthese"
    _items = []
    for roh in (evidence_items or []):
        _items.append(roh.to_dict() if hasattr(roh, "to_dict") else roh)
    _items = [i for i in _items if isinstance(i, dict)]
    zwischenstand(
        "deutungs_paket_info",
        "deliverable={} evidenz_items={} belegzeilen={} tools={} previews={}".format(
            (vertrag or {}).get("deliverable_kind"),
            len(_items),
            sum(len(i.get("grounding_surface") or []) for i in _items),
            [i.get("tool") for i in _items],
            [repr(i.get("payload_preview"))[:120] for i in _items],
        ),
        sitzung=_sitzung(orchestrator),
    )
    _publiziere_belegkarte(orchestrator, copilot_event_bus, evidence_items)
    selbst_beendet = bool(getattr(orchestrator, "_ra_deutung_abgegeben", False))
    zwischenstand(
        "entwurf_des_modells",
        "Werkzeugphase selbst beendet: {}\n\n{}".format(
            "ja" if selbst_beendet else "nein", str(entwurf or "").strip() or "LEER"),
        sitzung=_sitzung(orchestrator),
    )
    if entwurf_als_antwort_aktiv() and selbst_beendet and str(entwurf or "").strip():
        text, struck = await _verankere(
            orchestrator, turn_state, copilot_event_bus,
            entwurf_marker_vereinfachen(entwurf), evidence_items,
        )
        text += _sammelhinweis(struck)
        zwischenstand("entwurf_als_antwort", text, sitzung=_sitzung(orchestrator))
        if text.strip():
            return text
    if gutachten_aktiv():
        return await fuehre_gutachten_aus(
            orchestrator, turn_state, copilot_event_bus, evidence_items
        )
    return await _einfache_synthese(
        orchestrator, turn_state, copilot_event_bus, evidence_items, entwurf
    )


def _zusammengebrochen(roh: str, entwurf: str) -> bool:
    """Detect synthesis that loses most of a substantial draft.

    Check both severe text shortening and loss of reported measurements.
    This also catches prose of similar length that replaces nearly every
    measurement with a qualitative statement or evidence marker.
    """
    kern = str(entwurf or "").strip()
    if len(kern) <= 1500:
        return False
    if len(str(roh or "").strip()) < len(kern) / 4:
        return True
    # Comparable text length can still hide the loss of quantitative results.
    # Check retained measurements independently of the character-count check.
    im_entwurf = _messwerte(kern)
    return len(im_entwurf) >= 20 and len(im_entwurf & _messwerte(roh)) < len(im_entwurf) / 10


_MESSWERT = re.compile(
    r"(?<![\w.:/-])(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+,\d+|\d{3,})(?![\w:/-])")


def _messwerte(text: str) -> set:
    """Die Messwerte eines Textes ohne Marken und Dokumentkennungen, normiert."""
    rein = re.sub(r"\{\{[^}]*\}\}|\[\[[^\]]*\]\]|\([^()]*::[^()]*\)", "", str(text or ""))
    werte = set()
    for zahl in _MESSWERT.findall(rein):
        try:
            werte.add(round(float(zahl.replace(".", "").replace(",", ".")), 2))
        except ValueError:
            continue
    return werte


async def _einfache_synthese(
    orchestrator: Any,
    turn_state: Any,
    copilot_event_bus: Any,
    evidence_items: List[Any],
    entwurf: str = "",
) -> str:
    """Baustein 1: EIN frischer Call IST die Antwort."""
    paket = evidenz_paket_text(evidence_items)
    # Der Paket-Text IST die Eingabe des Deutungsaufrufs. Bis zum 2026-09-17
    # wurde er nirgends aufgezeichnet, und der dritte Arm des Piloten konnte
    # deshalb seine eigene Frage nicht beantworten: neun Stunden Rechenzeit,
    # und ob die Zahl 294 vorlag oder nicht, blieb unentscheidbar. Die
    # Aufzeichnung schreibt nur eine Datei und aendert nichts an der Eingabe.
    zwischenstand("deutungs_paket", paket, sitzung=_sitzung(orchestrator))
    system_msg, user_msg = deutungs_synthese_messages(
        turn_state.normalized_question, paket, korpus_fuer_synthese(orchestrator), entwurf
    )
    # EIN LEERER DEUTUNGSAUFRUF IST EINE STOERUNG, KEINE ANTWORT.
    #
    # Gemessen am 2026-09-17: im Arm mit vollem Evidenzpaket lieferte der
    # Aufruf in 6 von 20 Faellen leeren Inhalt, in den beiden Vergleichsarmen
    # in 0 von 20. Der Rueckgabewert "" galt als Fehlschlag, die Finalisierung
    # rendert dann deterministisch aus der vorhandenen Evidenz, und die
    # Messdatei verzeichnet das als beantwortete Frage. Sechs der zwanzig
    # verglichenen Paare stellten damit Deutung gegen Schablone, ohne dass es
    # irgendwo stand.
    #
    # Die Paketgroesse ist NICHT der Grund: die leeren Aufrufe hatten im
    # Median 139 Belegzeilen, die gelungenen 265. Ein leerer Inhalt von einem
    # lokalen Modell ist dieselbe Klasse wie eine Modellstoerung, und
    # Stoerungen werden in diesem Harnisch wiederholt und nicht ueberschrieben.
    #
    # Kein Zeitlimit wird gesenkt, kein max_tokens gesetzt, kein Budget
    # angefasst. Es wird nur noch einmal gefragt.
    roh = ""
    versuche: List[str] = []
    for versuch in range(1, _DEUTUNG_VERSUCHE + 1):
        roh = await _ein_call(
            orchestrator, turn_state, copilot_event_bus, [system_msg, user_msg]
        )
        zwischenstand(
            "deutungs_roh" if versuch == 1 else f"deutungs_roh_versuch_{versuch}",
            roh,
            sitzung=_sitzung(orchestrator),
        )
        versuche.append(roh)
        if roh.strip() and not _zusammengebrochen(roh, entwurf):
            break
        zwischenstand(
            f"deutungs_leer_versuch_{versuch}",
            ("Der Deutungsaufruf lieferte leeren Inhalt. " if not roh.strip() else
             "Der Deutungsaufruf lieferte {} Zeichen gegen {} im Entwurf. ".format(
                 len(roh.strip()), len(str(entwurf or "").strip())))
            + f"Versuch {versuch} von {_DEUTUNG_VERSUCHE}.",
            sitzung=_sitzung(orchestrator),
        )
    else:
        # Kein Versuch hielt: der laengste gilt, wie bisher ein leerer als
        # Fehlschlag gilt.
        roh = max(versuche, key=lambda t: len(t.strip()), default="")
    if not roh.strip():
        return ""
    text, struck = await _verankere(orchestrator, turn_state, copilot_event_bus, roh, evidence_items)
    text += _sammelhinweis(struck)
    zwischenstand("deutungs_synthese", text, sitzung=_sitzung(orchestrator))
    return text


async def fuehre_gutachten_aus(
    orchestrator: Any,
    turn_state: Any,
    copilot_event_bus: Any,
    evidence_items: List[Any],
) -> str:
    """Gutachten-Stufe: Gliederung → Abschnitts-Calls → Gesamtverbindung.

    Jeder Abschnitt wird VOR der Verbindung mechanisch geankert; schlägt
    die Gliederung fehl, fällt die Stufe auf den einfachen Deutungs-Call
    zurück. Schlägt die Gesamtverbindung fehl, liefern die geankerten
    Abschnitte selbst die Antwort.
    """
    frage_text = turn_state.normalized_question
    paket = evidenz_paket_text(evidence_items)
    sitzung = _sitzung(orchestrator)
    zwischenstand("deutungs_paket", paket, sitzung=sitzung)

    gliederung_roh = await _ein_call(
        orchestrator,
        turn_state,
        copilot_event_bus,
        list(gutachten_gliederung_messages(frage_text, paket)),
    )
    zwischenstand("gutachten_gliederung", gliederung_roh, sitzung=sitzung)
    abschnitte = _parse_gliederung(gliederung_roh)
    if not abschnitte:
        # Messung 25b: der Gliederungs-Call variiert je Lauf — GENAU EIN
        # Retry, bevor der Fallback zur einfachen Synthese greift.
        gliederung_roh = await _ein_call(
            orchestrator,
            turn_state,
            copilot_event_bus,
            list(gutachten_gliederung_messages(frage_text, paket)),
        )
        zwischenstand(
            "gutachten_gliederung_retry", gliederung_roh, sitzung=sitzung
        )
        abschnitte = _parse_gliederung(gliederung_roh)
    if not abschnitte:
        return await _einfache_synthese(
            orchestrator, turn_state, copilot_event_bus, evidence_items
        )

    texte: List[str] = []
    struck_gesamt: List[str] = []
    for nr, (titel, auftrag) in enumerate(abschnitte, 1):
        roh = await _ein_call(
            orchestrator,
            turn_state,
            copilot_event_bus,
            list(gutachten_abschnitt_messages(frage_text, nr, titel, auftrag, paket)),
        )
        text, struck = await _verankere(orchestrator, turn_state, copilot_event_bus, roh, evidence_items)
        text = text.strip()
        zwischenstand("gutachten_abschnitt_" + str(nr), text, sitzung=sitzung)
        struck_gesamt.extend(struck)
        if text:
            texte.append(text)
    if not texte:
        return ""

    gesamt_roh = await _ein_call(
        orchestrator,
        turn_state,
        copilot_event_bus,
        list(gutachten_gesamt_messages(frage_text, texte)),
    )
    zwischenstand("gutachten_gesamt_roh", gesamt_roh, sitzung=sitzung)
    final, struck_ende = await _verankere(
        orchestrator, turn_state, copilot_event_bus, gesamt_roh, evidence_items
    )
    final = final.strip()
    struck_gesamt.extend(struck_ende)
    if not final:
        final = "\n\n".join(texte)
    # F4 gelernt (modellrobustheit-Rest): eine kurze Huelle ohne Zahlen ist
    # kein Kernbefund — GENAU EINE Eskalation; der laengere Text gilt.
    if len(final) < 800:
        esk_system, esk_user = deutungs_synthese_messages(frage_text, paket, korpus_fuer_synthese(orchestrator))
        esk_system = dict(esk_system)
        esk_system["content"] += (
            "\n\nESKALATION: Dein bisheriger Text war eine Huelle ohne "
            "Befund. Liefere jetzt den Kernbefund mit den konkreten "
            "Zahlen aus dem Paket — oder benenne Satz für Satz, welche "
            "Zahlen das Paket bietet und was AUS DER ZAHL folgt."
        )
        eskaliert = await _ein_call(
            orchestrator, turn_state, copilot_event_bus,
            [esk_system, esk_user],
        )
        if len(eskaliert.strip()) > len(final):
                final = eskaliert.strip()
    # Messung-23-Diagnoselauf: die Zählung kommt aus dem ENDGÜLTIGEN
    # Text — die Abschnitts-Marken überleben den Gesamt-Re-Write selten.
    final += _sammelhinweis_aus_finaltext(final)
    zwischenstand("gutachten_synthese", final, sitzung=sitzung)
    return final


def _publiziere_belegkarte(
    orchestrator: Any, copilot_event_bus: Any, evidence_items: List[Any]
) -> None:
    """Reicht dem Frontend die Beleg-Map fuer die klickbaren Chips.

    Je Evidenz-Element id, Werkzeug, Abfrage und status — genau die Daten,
    die ein Chip-Klick braucht, um DIESE Abfrage im Werkzeug zu oeffnen.
    Fehler beim Publizieren beruehren die Antwort nicht.
    """
    if copilot_event_bus is None:
        return
    eintraege: List[Dict[str, str]] = []
    # Include every evidence item so chips for later results remain resolvable.
    for roh in list(evidence_items or []):
        item = roh.to_dict() if hasattr(roh, "to_dict") else roh
        if isinstance(item, dict):
            eintraege.append(
                {
                    "id": str(item.get("id") or ""),
                    "tool": str(item.get("tool") or ""),
                    "query": str(item.get("query") or ""),
                    "status": str(item.get("status") or ""),
                }
            )
    ereignis = {
        "event": "copilot.grounding",
        "grounding": {
            "verdict": "deutungs_synthese",
            "analysis_family": "",
            "rejected_claim_count": 0,
            "annotations": [],
            "evidence": eintraege,
        },
    }
    try:
        copilot_event_bus.publish(
            ereignis, session_id=getattr(orchestrator.session, "session_id", "")
        )
    except Exception:
        pass
