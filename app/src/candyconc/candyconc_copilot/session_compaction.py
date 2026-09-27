"""Sitzungsverdichtung: Vorgaben an die Runden koppeln, Zusammenfasser zaehlen.

Zwei Befunde vom 2026-09-02, beide gemessen am Harnisch-Lauf
(evaluation/deutung/harnisch_nachher.jsonl):

1. Die Vorgaben des ``SessionManager`` standen fest verdrahtet auf
   ``max_messages=20`` und ``max_tokens=2000``, waehrend die Rundenschranke
   des reichsten Rezepts (kontrast) seit P0 bei 20 Runden liegt. Die
   Verdichtungsschwelle liegt bei 0,8 mal ``max_tokens``, das waren 1600
   Woerter. Gemessene Modellsichten je Werkzeugergebnis: KWIC mit 50 Zeilen
   rund 652 Woerter, keyness 247, metadata 131. Schon das dritte
   KWIC-Ergebnis riss die Schwelle. Ab etwa Runde 8 sah das Modell nur noch
   die letzten sechs Nachrichten roh, die Keyness aus Runde 4 war ein
   220-Zeichen-Stummel, und ab Runde 9 fehlte die Nutzerfrage.

2. ``_lm_summary`` ist ein echter Modellaufruf ueber ``_lm_chat_async``. Er
   stand in keiner Bilanz: ``llm_calls_used`` zaehlt nur die Aufrufe des
   Orchestrators (orchestrator.py:4739). Ein Turn mit vier Verdichtungen
   meldete vier Modellaufrufe weniger, als er getan hatte, und ihre Dauer
   lag im Topf "Werkzeuge", weil sie in der Werkzeugschleife anfaellt.

Die Vorgaben leiten sich aus dem Kontextfenster des Modells und der
gemessenen Form der Historie ab, nicht aus ``max_steps``. Die Kopplung an
die Schrittdecke (bis 2026-09-26) band die Missbrauchsdecke an das
Gedaechtnis: wer die Decke hob, hob die Schwelle ueber das Fenster.

Die Ableitung ist zweimal daran gescheitert, dass sie einen Posten der
Historie nicht kannte. Erst fehlten Frage und Antwort, dann die beiden
Notizen, die der Orchestrator selbst schreibt (Rahmung :6851,
Vertragsnotiz :7675). Beide Male traf die Schwelle die Summe ihrer eigenen
Posten auf das Wort genau, und die erste Nachricht, die nicht in der Liste
stand, kostete Evidenz: ``microcompact`` schrieb Werkzeugergebnisse auf
220-Zeichen-Stummel um, ohne einen Modellaufruf und damit ohne eine Zeile
in irgendeiner Bilanz. Die Posten unten sind deshalb an den 21 Stellen
abgezaehlt, an denen ``orchestrator.py`` an die Sitzung anhaengt, und die
Ableitung traegt eine Reserve von einer Runde ueber ihrer eigenen Summe.
"""

from __future__ import annotations

import json
import math
import contextlib
import os
import time
from typing import Any, Dict, Tuple, List

from candyconc.config import get as get_config


#: Name der Stufe, unter der die Zeit des Zusammenfassers gebucht wird. Sie
#: steht neben "Vorlauf", "Werkzeuge" und "Verifikation" in
#: ``llm_seconds_je_stufe``. Wer die Indexzeit der Werkzeugschleife
#: ausrechnet, muss sie ABZIEHEN: die Verdichtung laeuft innerhalb der
#: Werkzeugphase (``summarise`` nach jedem Werkzeugergebnis,
#: orchestrator.py:7168), wird aber als eigene Stufe gebucht. Der Konsument
#: in scripts/dev/live_eval_suite.py tut das.
STUFE_VERDICHTUNG = "Verdichtung"

# Word-count calibration for one model-visible tool result.
# The model-view limit counts characters, so word length changes the number
# of words within that limit. Keep this calibration separate from that cap.
_WOERTER_JE_WERKZEUGERGEBNIS = 652

# Account for assistant text accompanying tool_calls in each round.
# A complete handoff answer belongs in the once-per-turn answer allowance.
_WOERTER_JE_ASSISTENZZUG = 55

#: Woerter, die eine Runde NEBEN ihrem Werkzeugergebnis anhaengt: die
#: Vertragsnotiz ueber fehlende Belege (``_evidence_note``,
#: orchestrator.py:7675, Wortlaut aus ``contract_evidence_note``). Am
#: 2026-09-03 im Arbeitsbaum an der echten Funktion ueber zehn
#: Argumentformen gemessen: 94 Woerter im kleinsten Fall (nichts fehlt,
#: ``followup=True``), 120 im groessten (sechs fehlende Belege, vier
#: erzwungene Werkzeuge, Ankerhinweis). Angesetzt ist der groesste. Sie
#: stand in keiner Ableitung, obwohl sie je Runde einmal anfallen kann.
#: Seit 2026-09-25 haengt nur noch das Ende der Werkzeugphase sie an, die
#: Folgenotiz nach jedem Werkzeugschritt ist entfallen. Je Runde einmal
#: bleibt die Obergrenze: will das Modell nach dem erzwungenen Zug wieder
#: ohne die Belege antworten, folgt die naechste.
_WOERTER_JE_RUNDENNOTIZ = 120

#: Woerter der Rahmungsnotiz, die der Turn EINMAL anhaengt
#: (orchestrator.py:6851, ``[System note: {briefing_note}]``). Gemessen am
#: selben Tag an den beiden Notizen, die es gibt:
#: ``search_contrast_briefing_note`` 42 Woerter und 466 Zeichen,
#: ``split_qa_briefing_note`` 15 Woerter. Angesetzt ist die groessere.
_WOERTER_FUER_RAHMUNG = 42

#: Nicht-Werkzeug-Anteil der Historie, in Woertern: die laengste Frage und
#: die laengste Antwort des Harnisch-Laufs (114 und 833 Woerter,
#: evaluation/deutung/harnisch_nachher.jsonl, im Arbeitsbaum ausgezaehlt).
#: Ohne diesen Summanden hatte die erste Ableitung an ihrer eigenen Decke
#: null Luft: 24 Runden liefen sauber durch, dieselben 24 Runden MIT der
#: Nutzerfrage kippten die Schwelle, und ``microcompact`` schrieb 15 der 24
#: Werkzeugergebnisse auf 220-Zeichen-Stummel um.
_WOERTER_FUER_FRAGE_UND_ANTWORT = 114 + 833

#: Reserve ueber der gemessenen Turnform, in Woertern einer Runde der
#: gemessenen Form (652 + 55 + 120). Die Aufstellung oben ist eine
#: Momentaufnahme der Stellen, an denen ``orchestrator.py`` an die Sitzung
#: anhaengt (Stand 2026-09-03). Traefe die Schwelle die Summe der gemessenen
#: Maxima auf das Wort genau, kuerzte die naechste Nachricht, die diese
#: Liste nicht kennt, Evidenz zum 220-Zeichen-Stummel. Genau das war der
#: Zustand, den die zweite Nachbesserung vorfand: mit der Schwelle 16595 und
#: der gemessenen Turnform wurden 8 von 24 Werkzeugergebnissen zu Stummeln,
#: bei null LM-Verdichtungen. Die Probe
#: ``test_die_schwelle_hat_luft_ueber_der_gemessenen_form`` verlangt diese
#: Reserve.
_RESERVE_RUNDEN = 1

# Number of rounds in the reference turn used to check that ordinary
# tool results and accompanying messages remain uncompressed.
_RUNDEN_DER_GEMESSENEN_TURNFORM = 24

#: Anteil von ``max_tokens``, ab dem ``SessionManager`` verdichtet
#: (session_manager.py:112). Hier gespiegelt, damit die Ableitung unten die
#: Schwelle trifft und nicht die Vorgabe.
_SCHWELLENANTEIL = 0.8

# Derive history capacity from the model context window.
# Step counts cannot determine memory needs because a round can contain
# many tool calls. Reserve space for the static prompt and model output,
# then convert the remaining capacity to the history's word-count unit.

# Default model context size in tokens.
# CANDYCONC_MODEL_CONTEXT_TOKENS configures the actual loaded context size.
_KONTEXTFENSTER_VORGABE = 173_312

# Calibrated token allowance for the system prompt, turn suffix and tool
# schemas. Exclude messages already counted in the history.
_SOCKEL_TOKEN = 16_513

#: Platz fuer die Ausgabe einer Runde in Token, Denken eingeschlossen: die
#: groesste Ausgabe einer gelungenen Runde (Werkzeugaufruf oder Text),
#: 37.303 (Qwen, Sitzung bb5db49d, runde_01), gemessen ueber 189 Runden.
#: Keine Grenze fuer das Modell, nur der Platz, den die Historie ihm laesst.
_AUSGABE_TOKEN = 37_303

#: Token je Wort der Historie dort, wo die Schwelle greift. Gemessen als
#: Zuwachs der prompt_tokens gegen den Zuwachs der Woerter seit der ersten
#: Runde, also samt Aufrufargumenten und Vorlagenaufwand: bei Verlaeufen ab
#: 12.000 Woertern 3,39 bis 5,48 (27 Runden), darunter bis 9,67, weil kurze
#: JSON-Ergebnisse viele Token je Wort tragen, solche Verlaeufe aber weit
#: unter der Schwelle bleiben (groesster gemessener: 2.543 Woerter).
_TOKEN_JE_WORT = 5.48

#: Kleinste gemessene Modellsicht eines Werkzeugergebnisses in Woertern:
#: list_docsets ohne Treffer, 13 Woerter (4.790 Ergebnisse ohne Stummel,
#: Median 62). Grundlage der Nachrichtenkappe.
_WOERTER_JE_ERGEBNIS_MIN = 13


def kontextfenster_token() -> int:
    """Das Kontextfenster des Modells in Token.

    ``CANDYCONC_MODEL_CONTEXT_TOKENS`` (Umgebung oder Konfiguration) setzt
    es passend zur Ladung, sonst gilt die gemessene Vorgabe.
    """
    roh = os.environ.get("CANDYCONC_MODEL_CONTEXT_TOKENS") or get_config(
        "CANDYCONC_MODEL_CONTEXT_TOKENS", ""
    )
    try:
        wert = int(str(roh).strip())
    except (TypeError, ValueError):
        wert = 0
    return wert if wert > 0 else _KONTEXTFENSTER_VORGABE


def schwelle_aus_dem_fenster() -> int:
    """Woerter, die die rohe Historie im Fenster tragen darf.

    Fenster minus Sockel minus Ausgabeplatz, geteilt durch die Token je Wort
    der Verlaeufe, bei denen die Schwelle greift. Bei der Vorgabe 173.312:
    ``(173312 - 16513 - 37303) / 5,48 = 21805`` Woerter. Die gemessene
    Turnform mit Assistenztext (24 mal 827 plus 989, also 20837 Woerter)
    bleibt roh, mit 968 Woertern Luft.
    """
    frei = kontextfenster_token() - _SOCKEL_TOKEN - _AUSGABE_TOKEN
    return max(1, int(frei / _TOKEN_JE_WORT))


def session_max_messages() -> int:
    """Return the raw-history message allowance.

    Derive it from the word threshold using three messages per smallest
    tool result: assistant call, tool result and contract note. Add four
    places for the question, framing, answer and reserve. This keeps the
    message allowance from trimming evidence before the word threshold.
    """
    roh = os.environ.get("CANDYCONC_SESSION_MAX_MESSAGES") or get_config(
        "CANDYCONC_SESSION_MAX_MESSAGES", ""
    )
    try:
        wert = int(str(roh).strip())
    except (TypeError, ValueError):
        wert = 0
    if wert > 0:
        return wert
    return 4 + 3 * math.ceil(schwelle_aus_dem_fenster() / _WOERTER_JE_ERGEBNIS_MIN)


def session_max_tokens() -> int:
    """Return the raw-history word allowance.

    SessionManager counts words and compacts above 0.8 times this value.
    Derive the allowance from ``schwelle_aus_dem_fenster`` and round upward.
    The strict comparison leaves the threshold itself uncompressed. The
    reference-turn check includes tool results, assistant text and framing.
    """
    roh = os.environ.get("CANDYCONC_SESSION_MAX_TOKENS") or get_config(
        "CANDYCONC_SESSION_MAX_TOKENS", ""
    )
    try:
        wert = int(str(roh).strip())
    except (TypeError, ValueError):
        wert = 0
    if wert > 0:
        return wert
    return int(math.ceil(schwelle_aus_dem_fenster() / _SCHWELLENANTEIL))


# --------------------------------------------------------------------------- #
# Bilanz des Zusammenfassers
# --------------------------------------------------------------------------- #


def verdichtungs_bilanz(session: Any) -> Tuple[int, float, int]:
    """Aufrufe, Sekunden und gekuerzte Werkzeugzeilen seit dem Turn-Beginn.

    Die dritte Zahl zaehlt NICHT Modellaufrufe: ``microcompact`` schreibt
    aeltere Werkzeugzeilen still auf 220 Zeichen um, ohne ein Modell zu
    rufen. Gemessen an der Decke von 24 verschwanden so 15 von 24
    Werkzeugergebnissen bei null LM-Verdichtungen. Ein Bericht, der "null
    Verdichtungen" meldet, waehrend Evidenz verschwand, ist genau der
    Defekt, den diese Datei schliessen soll.

    Defensiv gegen Sitzungsattrappen aus den Proben, die die Zaehler nicht
    fuehren. Fehlen sie, ist die Bilanz leer und der Bericht sieht aus wie
    vorher.
    """
    try:
        aufrufe = int(getattr(session, "verdichtungs_aufrufe", 0) or 0)
        sekunden = float(getattr(session, "verdichtungs_sekunden", 0.0) or 0.0)
        gekuerzt = int(getattr(session, "gekuerzte_werkzeugausgaben", 0) or 0)
    except (TypeError, ValueError):  # pragma: no cover - Attrappe mit Unsinn
        return 0, 0.0, 0
    return max(0, aufrufe), max(0.0, sekunden), max(0, gekuerzt)


def verdichtungs_zaehler_zuruecksetzen(session: Any) -> None:
    """Die Bilanz auf null setzen, damit sie je Turn und nicht je Sitzung gilt.

    Gerufen wird das am Ende des Turns von ``turn_usage_snapshot``, das die
    Bilanz VERBRAUCHT, nicht zu Beginn von ``run_async``. Der Unterschied
    ist gemessen: beide Chat-Routen (routes/copilot.py:357 und :482) und der
    Paket-Helfer (__init__.py:191) haengen die Client-Historie an die
    Sitzung, BEVOR der Orchestrator laeuft. Eine Historie aus 50 Nachrichten
    mit zusammen 63.650 Zeichen haelt beide Routendeckel ein und loest dabei
    drei echte ``_lm_summary``-Aufrufe aus. Eine Ruecksetzung zu Turn-Beginn
    loeschte sie, und der Bericht meldete einen Aufruf statt vier.
    """
    ruecksetzer = getattr(session, "verdichtungs_zaehler_zuruecksetzen", None)
    if callable(ruecksetzer):
        ruecksetzer()


def modellzeit_buchen(turn_state: Any, stufe: str, dauer: float) -> None:
    """Die Dauer EINES Modellaufrufs auf Turn und Stufe buchen.

    Beide Toepfe laufen ROH mit, gerundet wird erst im Bericht
    (``usage_felder``). Die erste Fassung rundete den Stufen-Akkumulator bei
    JEDER Buchung auf drei Stellen, waehrend ``llm_seconds`` ungerundet
    weiterlief. Der Rundungsfehler summierte sich damit ueber die Aufrufe
    statt sich auszugleichen, weil ein Aufruf unter 1 ms fast immer
    aufgerundet wird.

    Gemessen am 2026-09-03 an einem Turn mit 14 Verifikationsaufrufen zu je
    etwa 0,8 ms: die Stufe ``Verifikation`` wies 0,016 s aus, gewartet
    wurden 0,0114 s, also 41 Prozent zu viel. Die Summe der Stufen lag um
    bis zu 0,006 s ueber ``llm_seconds``, und die Wache
    ``test_die_summe_der_stufen_ist_die_gesamte_modellzeit`` (Toleranz
    0,005 s) fiel in 14 von 20 Laeufen. Ohne Rundung am Akkumulator bleibt
    genau eine Rundung je Zahl im Bericht uebrig.
    """
    turn_state.llm_seconds += dauer
    turn_state.llm_seconds_je_stufe[stufe] = (
        turn_state.llm_seconds_je_stufe.get(stufe, 0.0) + dauer
    )
    if not hasattr(turn_state, "llm_calls_je_stufe"):
        turn_state.llm_calls_je_stufe = {}
    turn_state.llm_calls_je_stufe[stufe] = (
        turn_state.llm_calls_je_stufe.get(stufe, 0) + 1
    )


def usage_felder(turn_state: Any, session: Any = None) -> Dict[str, Any]:
    """Die drei Usage-Felder mit eingerechneter Verdichtung.

    Zwei Stellen schreiben dieselbe Groesse: der Usage-Bericht des Turns und
    der Analysevertrag des deterministischen Faktpfads
    (orchestrator.py:6049). Der Vertrag ist kein totes Feld, er wandert ueber
    ``_build_runtime_state`` in die Sitzungs-Rehydrierung
    (session_manager.py:674) und damit in die Modellsicht, ausserdem in
    ``build_death_landing_markdown`` und ``build_salvage_markdown``. Stuenden
    dort andere Zahlen als im Bericht, meldete derselbe Turn zwei
    verschiedene Wahrheiten ueber seine Modellaufrufe, und zwar auf genau dem
    Pfad, auf dem "ein Modellaufruf" als Befund gelesen wird.

    Die Verdichtungen erhoehen ``llm_calls_used`` und ``llm_seconds`` und
    stehen als eigene Stufe in ``llm_seconds_je_stufe``. Sie zaehlen
    BEWUSST nicht gegen das K1-Schrittbudget des Orchestrators
    (orchestrator.py:4739 zaehlt dort weiter nur eigene Aufrufe): eine
    Verdichtung ist kein ReAct-Schritt, und sie gegen die Schranke zu
    buchen wuerde die Analyse still kuerzen, sobald das Gedaechtnis eng
    wird. Der Bericht bleibt beobachtend, wie der Rest dieses Fachs.
    """
    aufrufe, sekunden, _gekuerzt = verdichtungs_bilanz(session)
    # Erst roh zusammenlegen, dann EINMAL runden. Wird je Zahl genau einmal
    # gerundet, weicht die Summe der Stufen von ``llm_seconds`` um hoechstens
    # 0,0005 s je Stufe ab, statt um die aufsummierte Rundung jedes Aufrufs
    # (siehe modellzeit_buchen: 0,006 s bei 14 Aufrufen).
    stufen = dict(getattr(turn_state, "llm_seconds_je_stufe", {}) or {})
    aufrufe_je_stufe = dict(getattr(turn_state, "llm_calls_je_stufe", {}) or {})
    if aufrufe:
        stufen[STUFE_VERDICHTUNG] = stufen.get(STUFE_VERDICHTUNG, 0.0) + sekunden
    return {
        "llm_calls_used": int(turn_state.llm_calls_used) + aufrufe,
        "llm_seconds": round(float(turn_state.llm_seconds) + sekunden, 3),
        "llm_seconds_je_stufe": {
            name: round(float(wert), 3) for name, wert in stufen.items()
        },
        "llm_calls_je_stufe": dict(aufrufe_je_stufe),
    }


def turn_usage_snapshot(
    turn_state: Any,
    *,
    start_time: float,
    recipe_id: str,
    session: Any = None,
) -> Dict[str, Any]:
    """Den Usage-Bericht eines Turns bauen und die Bilanz dabei verbrauchen.

    Ausgelagert aus ``orchestrator.py``, wo dasselbe Woerterbuch an zwei
    Stellen woertlich stand (Kurzschluss der Rezept-Vorbedingung und das
    ``finally`` des Laufs). Ein Fix an einer von zwei Stellen waere eine
    Verschiebung gewesen: der Kurzschluss haette weiter null Verdichtungen
    gemeldet, obwohl die Historie vor dem Kurzschluss schon getrimmt wird.

    VERBRAUCHEN statt vorab loeschen: pro Turn entsteht genau ein
    Schnappschuss (der Kurzschluss bei orchestrator.py:6867 kehrt zurueck,
    bevor das ``try`` mit dem ``finally`` bei :7781 betreten wird, per AST
    geprueft). Damit faellt eine Verdichtung, die beim Anhaengen der
    Client-Historie VOR dem Turn lief, dem ersten Bericht zu, statt still
    geloescht zu werden, und der zweite Turn beginnt bei null.
    """
    _aufrufe, _sekunden, gekuerzt = verdichtungs_bilanz(session)
    bericht = {
        **usage_felder(turn_state, session),
        "gekuerzte_werkzeugausgaben": gekuerzt,
        "transport_retries_used": turn_state.retries_used,
        "elapsed_s": round(time.perf_counter() - start_time, 3),
        "recipe_id": recipe_id,
    }
    verdichtungs_zaehler_zuruecksetzen(session)
    return bericht


def guard_nachricht_fuer_modell(guard_message: str) -> Dict[str, str]:
    """Der Wächter/Gegenanker geht als Nutzer-Rolle mit [System note:]-
    Wrapper raus: Mistral-Vorlagen (z. B. mistral-small-4-119b) lehnen eine
    zweite System-Rolle ab (Jinja "got system", Live-Befund 2026-09-06).
    Das etablierte Muster fuer Modell-Hinweise in dieser Codebase."""
    if not guard_message:
        return {}
    return {"role": "user", "content": "[System note: " + guard_message + "]"}


def zwischenstand(stufe: str, text: str, sitzung: str = "sitzung_unbekannt") -> None:
    """Nimmt den Antworttext einer Nachbereitungsstufe auf, wenn das
    Umgebungsverzeichnis CANDYCONC_ZWISCHENSTAENDE_DIR gesetzt ist.

    Dient der Messung, die den Befund „die Nachbereitung entfernt die
    Deutung" auf den verursachenden Schritt zuspitzt: ohne das Verzeichnis
    wird nichts geschrieben und kein Verhalten geaendert.
    """
    ziel_dir = os.environ.get("CANDYCONC_ZWISCHENSTAENDE_DIR", "")
    if not ziel_dir:
        return
    from pathlib import Path

    try:
        verzeichnis = Path(ziel_dir) / str(sitzung)
        verzeichnis.mkdir(parents=True, exist_ok=True)
        (verzeichnis / f"{stufe}.txt").write_text(text or "", encoding="utf-8")
    except OSError:
        pass


def verdikt_bilanz(verdict: Any, envelope: Any) -> str:
    """Das Verdikt als kompakte JSON-Zeile für die Zwischenstände-Aufzeichnung."""
    return json.dumps(
        {
            "verdict": getattr(verdict, "verdict", ""),
            "accepted": len(verdict.accepted_claim_ids or ()),
            "rejected": len(verdict.rejected_claim_ids or ()),
            "claims_gesamt": len(getattr(envelope, "claims", ()) or ()),
        },
        ensure_ascii=False,
    )


def runde_lesbar(
    *,
    nr: int,
    stufe: str,
    messages: Any,
    tools: Any,
    antwort: Any,
    dauer: float,
) -> str:
    """Eine Runde als LESBARER Text: was hineinging, was herauskam.

    Kein JSON-Klumpen. Die Projektregel vom 2026-09-17 verlangt, dass der
    Harnisch an der gelesenen Mikrointeraktion verbessert wird, und dafuer
    muss ein Mensch die Datei aufmachen und verstehen koennen, ohne sie zu
    parsen. Gekuerzt wird NICHTS: wer eine Runde liest, will die Runde.
    """
    teile: List[str] = [
        f"# Runde {nr}   Stufe: {stufe}   Dauer: {dauer:.1f}s",
        "",
    ]
    werkzeuge = [
        str((w or {}).get("function", {}).get("name") or (w or {}).get("name") or "?")
        for w in (tools or [])
        if isinstance(w, dict)
    ]
    teile.append(
        "## Angebotene Werkzeuge ({})".format(len(werkzeuge))
        + ("\n" + ", ".join(werkzeuge) if werkzeuge else "\nkeine")
    )
    teile.append("")
    teile.append("## Eingabe an das Modell")
    for i, m in enumerate(messages or []):
        if not isinstance(m, dict):
            teile.append(f"\n### [{i}] {type(m).__name__}\n{m}")
            continue
        rolle = str(m.get("role", "?"))
        kopf = f"\n### [{i}] {rolle}"
        if m.get("tool_call_id"):
            kopf += f"   tool_call_id={m['tool_call_id']}"
        teile.append(kopf)
        inhalt = m.get("content")
        if inhalt:
            teile.append(str(inhalt))
        for tc in m.get("tool_calls") or []:
            fn = (tc or {}).get("function", {}) if isinstance(tc, dict) else {}
            teile.append(
                f"AUFRUF {fn.get('name')}({fn.get('arguments')})"
            )
    teile.append("")
    teile.append("## Ausgabe des Modells")
    if antwort is None:
        teile.append("KEINE (Ausnahme oder Abbruch vor der Antwort)")
        return "\n".join(teile)
    if not isinstance(antwort, dict):
        teile.append(str(antwort))
        return "\n".join(teile)
    nachricht = {}
    with contextlib.suppress(Exception):
        nachricht = (antwort.get("choices") or [{}])[0].get("message") or {}
    inhalt = nachricht.get("content")
    teile.append("### content")
    teile.append(str(inhalt) if inhalt else "LEER")
    rufe = nachricht.get("tool_calls") or []
    teile.append(f"\n### tool_calls ({len(rufe)})")
    for tc in rufe:
        fn = (tc or {}).get("function", {}) if isinstance(tc, dict) else {}
        teile.append(f"{fn.get('name')}({fn.get('arguments')})")
    with contextlib.suppress(Exception):
        grund = (antwort.get("choices") or [{}])[0].get("finish_reason")
        if grund:
            teile.append(f"\n### finish_reason\n{grund}")
    # Welches Modell geantwortet hat (ein stiller Wechsel auf ein anderes
    # geladenes Modell sieht sonst aus wie eine schwache Runde), was die
    # Runde gekostet hat, und woran es gedacht hat. Eine Runde, die mit
    # "length" und LEER endet, erklaert sich NUR aus ihrem Denken.
    teile.append("\n### Modell\n{} (Route: {})".format(
        antwort.get("model") or "?", antwort.get("_cc_model") or antwort.get("_cc_route") or "?"))
    if antwort.get("usage"):
        teile.append("\n### usage\n" + json.dumps(antwort.get("usage"), ensure_ascii=False, default=str))
    denken = nachricht.get("reasoning_content") or nachricht.get("reasoning")
    teile.append("\n### Denken\n" + (str(denken) if denken else "nicht geliefert"))
    return "\n".join(teile)
