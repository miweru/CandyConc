"""Wann eine zitierte Spanne ueberhaupt ein KORPUSZITAT ist.

Zwei Wachen beurteilen woertliche Zitate, und sie taten es bisher nach
verschiedenen Regeln:

``recipe_runtime.strike_unsupported_quotes`` ist der deterministische
Chokepoint auf jeder Landung. ``claim_rules/_shared`` prueft dieselben
Spannen im Claim-Geruest des Verifizierers.

Der Unterschied war gemessen und einseitig. ``_shared`` kannte seit
laengerem die Auslassung (``_quoted_segment_is_supported`` splittet an
``...`` und ``…``) und den Fragenbezug (``_quote_is_user_scope_reference``:
eine Spanne, die woertlich in der Nutzerfrage steht, nennt den Gegenstand
und nicht einen Beleg). Der Chokepoint kannte beides nicht: seine
Normalisierung loeschte die Auslassungspunkte, und danach verlangte er
die Woerter als EINE zusammenhaengende Folge in EINER Belegzeile. Ein
Konstruktionsname wie ``nicht nur ... sondern auch`` konnte so nie gedeckt
sein, ein Zitat aus der Frage ebenso wenig.

Gemessen am zweiten Messarm (``evaluation/deutung/harnisch_nachher.jsonl``,
final_polish-Annotationen): aus VERIFIZIERTEN Antworten strich die Politur
7 Aussagen und 8 Zitate (erklaerroutine, Rumpf danach 548 Zeichen), 2 und 2
(korrelat), 1 und 1 (markerliste).

Die Angleichung ist in BEIDE Richtungen zu lesen. Wer den Chokepoint an
den Verifizierer heranfuehrt, darf ihn dabei nicht daran vorbeischieben:
die erste Fassung der Auslassungsregel pruefte jedes Segment einzeln und
ohne Reihenfolge und war damit an zwei Stellen LOCKERER als der
Verifizierer, den sie absichert. Beide Loecher sind gemessen und in
``recipe_runtime._segmente_der_reihe_nach_gedeckt`` und in
``jeder_befund_verneint`` benannt.

Hier steht die gemeinsame Quelle. Eine zweite Kopie waere die naechste
Divergenz, und die Begruendung ist dieselbe wie bei ``grounding_evidence``
(dort: welche Zeilen ein Zitat decken duerfen).
"""

from __future__ import annotations

import re
from typing import List

#: Auslassungspunkte in beiden Schreibweisen, drei Punkte und U+2026.
#: Ein Zitat mit Auslassung ist keine Wortfolge, sondern zwei oder mehr
#: Belegstellen mit einer Luecke dazwischen. Wer die Punkte wegwirft und
#: dann Zusammenhang verlangt, prueft eine Wortfolge, die niemand
#: behauptet hat.
AUSLASSUNG = re.compile(r"(?:\.{3,}|…)")


def auslassungssegmente(zitat: str) -> List[str]:
    """Die Teile eines Zitats zwischen seinen Auslassungen.

    Leere Liste, wenn keine Auslassung vorkommt. ``nicht nur ... sondern
    auch`` liefert zwei Segmente, ``... sondern auch`` eines: eine
    Auslassung am Rand kuerzt eine Belegzeile, sie trennt nichts.
    """
    roh = str(zitat or "")
    if AUSLASSUNG.search(roh) is None:
        return []
    return [teil.strip() for teil in AUSLASSUNG.split(roh) if teil.strip()]


def normalisiere_zitat_fuer_vergleich(text: str) -> str:
    """Auszeichnung und Leerraum weg, Interpunktion an ihr Wort gebunden."""
    ohne_auszeichnung = re.sub(r"(?:\*\*|__|~~)", "", str(text or ""))
    zusammengezogen = re.sub(r"\s+", " ", ohne_auszeichnung.casefold()).strip()
    return re.sub(r"\s+([,.;:!?])", r"\1", zusammengezogen)


def spanne_kommt_wortweise_vor(nadel: str, heuhaufen: str) -> bool:
    """Die Spanne genau so, aber nie als Bruchstueck INNERHALB eines Wortes."""
    return bool(nadel) and re.search(
        rf"(?<!\w){re.escape(nadel)}(?!\w)",
        heuhaufen,
    ) is not None


# Words presenting a span as a finding about the corpus.
EMPIRISCHER_KONTEXT = re.compile(
    r"\b(?:korpusbeleg\w*|beleg\w*|beispiel\w*|kwic\w*|treffer\w*|"
    r"fundstelle\w*|konkordanz\w*|lautet\w*|erschein\w*|vorkomm\w*|"
    r"enthält\w*|enthaelt\w*|gezählt\w*|gezaehlt\w*|zeigt\w*|steht\w*|"
    r"kommt\b[^.!?\n]{0,60}\bvor\b)\b",
    re.IGNORECASE,
)
#: Woerter, die eine Spanne als GEGENSTAND der Untersuchung praesentieren.
#:
#: NUR substantielle Woerter. Die Vorfassung fuehrte ``für|fuer|von|zu|bei``
#: mit, und damit war praktisch jeder deutsche Satz "Scope". Gemessen mit
#: der Frage "Kommt die Phrase ruecksichtslose Invasoren marschieren im
#: Korpus vor?" und einer Belegliste ohne jede Deckung: aus
#: 'Für „ruecksichtslose Invasoren marschieren“ ergab die Suche 12 Zeilen.'
#: entfernte die Wache nichts, der Satz stand vollstaendig in der Antwort.
#: Ueber die Ausnahme entschied dort das blosse ``Für`` am Satzanfang.
SCOPE_KONTEXT = re.compile(
    r"\b(?:suchbegriff\w*|begriff\w*|term\w*|ausdruck\w*|wort\w*|"
    r"wendung\w*|phrase\w*|konstruktion\w*|formulierung\w*|"
    r"abfrage\w*|analyse\w*|analysier\w*|untersuch\w*|scope\w*|"
    r"gesucht|suchlauf\w*|hinsichtlich)\b",
    re.IGNORECASE,
)

#: Woerter, mit denen ein Satz einen Befund VERNEINT.
#:
#: Das Befund-Veto (``EMPIRISCHER_KONTEXT``) unterschied nicht, ob der
#: Befund behauptet oder verneint wird, und traf damit die archetypische
#: ehrliche Negativantwort. Gemessen an acht Saetzen zur Frage "Wie oft
#: kommt „Das Boot ist voll und die Grenze muss dicht“ im Korpus vor?":
#: gestrichen wurden 'Im Korpus findet sich „...“ nirgends.', 'Die Wendung
#: „...“ ist im Material nicht vertreten.' und '„...“ liefert keine
#: Treffer.' Aus 'Die Wendung „...“ ist im Material nicht vertreten. Der
#: Suchlauf ergab null Zeilen.' wurde 'Der Suchlauf ergab null Zeilen.',
#: also 66 Prozent Textverlust an der KORREKTEN Antwort.
#:
#: ``nicht nur`` ist KEINE Verneinung, sondern die haeufigste deutsche
#: Steigerungsfigur. Ohne den Ausschluss schaltete 'Die Wendung „...“
#: erscheint nicht nur einmal, sondern zwoelfmal.' die Wache ab, obwohl
#: der Satz ein Vorkommen BEHAUPTET.
VERNEINTER_BEFUND = re.compile(
    r"\b(?:nicht(?!\s+nur\b)|kein|keine|keinen|keinem|keiner|keines|nie|"
    r"niemals|nirgends|nirgendwo|null|ohne|fehlt|fehlen|leer)\b",
    re.IGNORECASE,
)

#: Ein POSITIVER Mengenanspruch neben einer Verneinung.
#:
#: Die Litotes ist der Weg, auf dem ein behaupteter Befund als Verneinung
#: durchging. Gemessen zur Frage "Wie oft kommt „Das Boot ist voll und die
#: Grenze muss dicht“ im Korpus vor?" gegen Belegzeilen ohne jede Deckung:
#: '„...“ kommt nicht selten vor, insgesamt 12 mal.' lieferte
#: ``entfernt=[]``, das Zitat blieb stehen. Ausloeser war das blosse
#: ``nicht`` im Satz. Wer eine Menge nennt, verneint keinen Befund, er
#: behauptet einen.
POSITIVE_MENGE = re.compile(
    r"\d|\b(?:zwölf\w*|zwoelf\w*|mehrfach|mehrmals|insgesamt|"
    r"wiederholt|dutzend\w*)\b",
    re.IGNORECASE,
)


def jeder_befund_verneint(nahe: str) -> bool:
    """Traegt JEDER Befundausdruck im Nahkontext seine eigene Verneinung?

    Die Vorfassung fragte nur, ob IRGENDWO im Satz ein Verneinungswort
    steht, und setzte damit das Befund-Veto ganz aus. Gemessen an vier
    Saetzen zur Frage "Wie oft kommt „Das Boot ist voll und die Grenze
    muss dicht“ im Korpus vor?", Belegzeilen ohne jede Deckung, alle vier
    mit ``entfernt=[]``: 'Ein Korpusbeleg lautet: „...“, nicht anders.',
    'Der Treffer „...“ steht in Zeile 4, ohne Zweifel.', '„...“ kommt
    nicht selten vor, insgesamt 12 mal.' und 'Die Wendung „...“ erscheint
    nicht nur einmal, sondern zwoelfmal.' Dieselben Saetze ohne ``frage``
    verloren ihr Zitat korrekt, die Ausnahme allein erzeugte das Loch.

    Das Fenster reicht 40 Zeichen VOR den Befundausdruck und bis an sein
    Ende. Bis an sein Ende, weil die archetypische Negativantwort ihre
    Verneinung mitten im Ausdruck traegt: "kommt nicht vor" ist EIN
    Treffer von ``EMPIRISCHER_KONTEXT``, und ein Fenster, das nur davor
    schaut, haette genau sie gestrichen. Nicht darueber hinaus, weil
    "steht in Zeile 4, ohne Zweifel" die Verneinung erst danach traegt und
    trotzdem einen Beleg behauptet.
    """
    for treffer in EMPIRISCHER_KONTEXT.finditer(nahe):
        fenster = nahe[max(0, treffer.start() - 40):treffer.end()]
        if VERNEINTER_BEFUND.search(fenster) is None:
            return False
    return True


def spanne_ist_fragenbezug(spanne: str, umgebung: str, frage: str) -> bool:
    """Nennt die Spanne den Gegenstand der FRAGE statt einen Korpusbeleg?

    Die erste Bedingung ist hart und traegt die ganze Ausnahme: die
    Spanne muss WOERTLICH in der Nutzerfrage stehen. Danach genuegt eines
    von zwei Zeichen. Entweder der Nahkontext verneint JEDEN Befund darin
    ("kommt nicht vor", "keine Treffer") und nennt keine positive Menge,
    dann ist die Spanne kein Beleganspruch, sondern dessen Gegenteil. Oder
    er fuehrt sie als Gegenstand (Suchbegriff, Ausdruck, untersucht) und
    NICHT als Befund (Beleg, Treffer, kommt vor).

    Ohne die dritte Bedingung waere die Ausnahme ein Loch: wer fragt, ob
    ``ruecksichtslose Invasoren marschieren`` im Korpus vorkommt, bekaeme
    genau diese Phrase als "Beleg" zurueck, gedeckt durch die eigene
    Frage. Die Wache soll das Modell binden, nicht den Fragesteller zum
    Kronzeugen machen.
    """
    nadel = normalisiere_zitat_fuer_vergleich(spanne)
    gefragt = normalisiere_zitat_fuer_vergleich(frage)
    if not nadel or not gefragt:
        return False
    if re.search(
        rf"(?<!\w){re.escape(nadel)}(?!\w)", gefragt, re.IGNORECASE
    ) is None:
        return False
    # Der Kontext ist die UMGEBUNG der Spanne, nicht die Spanne selbst.
    # Sonst entscheidet der Inhalt des Zitats mit darueber, ob es als
    # Zitat durchgeht: eine Spanne mit ``keine`` darin traefe den
    # Verneinungszweig ("Ein Beleg lautet „keine Fluechtlinge sondern
    # Invasoren“"), eine Spanne mit ``Wort`` darin den Scope-Zweig.
    nahe = re.sub(
        rf"(?<!\w){re.escape(nadel)}(?!\w)",
        " ",
        normalisiere_zitat_fuer_vergleich(umgebung),
        flags=re.IGNORECASE,
    )
    # A negated occurrence claim does not assert a corpus quotation.
    # Require every finding expression to be negated and reject any positive
    # quantity claim alongside it. This prevents an unrelated negation from
    # exempting a span that the same sentence presents as corpus evidence.
    # Frequency claims remain subject to the number check.
    if (
        VERNEINTER_BEFUND.search(nahe) is not None
        and jeder_befund_verneint(nahe)
        and POSITIVE_MENGE.search(nahe) is None
    ):
        return True
    return (
        SCOPE_KONTEXT.search(nahe) is not None
        and EMPIRISCHER_KONTEXT.search(nahe) is None
    )
