"""Die Docset-Maske entscheidet je TREFFERPOSITION, nicht je Satz.

Befund
------
``sent_to_doc`` liefert das Dokument des ERSTEN Satztokens. Wo ein Satz eine
Dokumentgrenze ueberlaeuft, gehoert er damit ganz dem vorigen Dokument, und
jeder Treffer in seiner zweiten Haelfte bekam die falsche ``doc_id``. Die
Engine hat diese ID an drei Stellen benutzt: fuer die Maskenpruefung eines
Docsets, fuer die Dokumentzuschreibung eines Treffers und fuer den
Vorfilter der Satzkandidaten im NFA-Zweig.

Die Maskenpruefung war der teuerste der drei. Ein Treffer, dessen Satz auf
Dokument A zeigt, waehrend er selbst in B liegt, fiel aus BEIDEN Haelften
einer Partition: aus der von B, weil die Maske A prueft, und aus der von A,
weil er dort nicht liegt. Am Testindex gemessen:

    [word="und"]    797 ungefiltert, aber test 197 + train 485 = 682
    [pos="NOUN"]  9.741 ungefiltert, aber      2.416 + 5.821 = 8.237

Eine Maske ueber ALLE Dokumente verlor nichts, deshalb ist es nie
aufgefallen. Im NFA-Zweig war die Wirkung eine andere und ebenso falsch:
dort summierten die Haelften zwar auf, aber 132 von 1.820 Treffern der
``test``-Haelfte wurden ``train`` zugeschlagen (``[pos="ADJ"]* [pos="NOUN"]``,
2.163 von 5.314 Treffern mit Satz-Dokument ungleich Positions-Dokument).

Beleg, dass ``sent_to_doc`` dort schlicht falsch liegt und nicht nur anders
zaehlt, am Testindex:

    Position 46 liegt in Dokument 2 [46,69).
    Ihr Satz 4 beginnt bei 36, sent_to_doc nennt Dokument 1 [24,46).
    Dokument 1 enthaelt Position 46 nicht.

Was hier geprueft wird
----------------------
Der Test baut einen Korpus, dessen Saetze Dokumentgrenzen ueberlaufen, und
verlangt drei Dinge. Erstens die POSITIVE KLASSE: es muss ueberhaupt
Treffer geben, deren Satz auf ein anderes Dokument zeigt als ihre Position.
Ohne sie wuerde der Test auch die kaputte Fassung bestehen. Zweitens die
Partition: zwei komplementaere Masken summieren auf das ungefilterte
Ergebnis, je Treffer und je Zaehlung. Drittens die Zuschreibung: die
``doc_id`` eines Treffers ist das Dokument, das seine Position enthaelt.

Welche Achse trennscharf ist
----------------------------
Gegen die Altfassung gemessen, indem ``token_to_doc`` an die satzweise
Aufloesung gebunden wird: alle sechs Queries brechen, und zwar an der
``doc_id``-Achse (2 bis 5 falsche Zuschreibungen je Query). Die
PARTITIONS-Achse bricht im synthetischen Korpus NICHT, weil dort jedes
Satz-Dokument ein gueltiger Index bleibt und die Altfassung nur falsch
zuschreibt statt zu verlieren. Der Verlust der Altfassung ist am echten
Index belegt, und ``test_verlust_der_altfassung_am_bench_index`` haelt ihn
dort fest, wo er auftritt. Die Partitions-Achse steht hier trotzdem: sie
bewacht die Gegenrichtung, dass eine kuenftige Reparatur der Zuschreibung
nicht ihrerseits Treffer aus beiden Haelften fallen laesst.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from cqlhpc.corpus import Corpus, build_postings_from_tokens
from cqlhpc.engine import QueryEngine, SearchOptions
from cqlhpc.lexicon import Lexicon


def _lex(werte: list[str]) -> tuple[Lexicon, np.ndarray]:
    uniq = sorted(set(werte))
    s2i = {s: i for i, s in enumerate(uniq)}
    ids = np.asarray([s2i[v] for v in werte], dtype=np.int32)
    freqs = np.bincount(ids, minlength=len(uniq)).astype(np.int64)
    return Lexicon(id_to_str=uniq, str_to_id=s2i, freqs=freqs), ids


def _korpus_mit_ueberlaufenden_saetzen() -> Corpus:
    """Acht Dokumente zu je fuenf Tokens, Saetze zu je sieben.

    5 und 7 sind teilerfremd, also faellt jede Satzgrenze ausser der ersten
    neben jede Dokumentgrenze. Das ist genau die Lage am Testindex, wo
    2.163 von 5.314 Treffern betroffen waren.
    """
    muster = ["der", "gute", "Plan", "und", "die"]
    woerter = muster * 8
    tags = ["DET", "ADJ", "NOUN", "KON", "DET"] * 8
    n = len(woerter)

    lw, iw = _lex(woerter)
    lp, ip = _lex(tags)
    ll, il = _lex(woerter)

    doc_starts = np.arange(0, n, 5, dtype=np.int32)
    sent_starts = np.arange(0, n, 7, dtype=np.int32)
    return Corpus(
        attrs={"word": iw, "pos": ip, "lemma": il},
        lex={"word": lw, "pos": lp, "lemma": ll},
        postings={
            "word": build_postings_from_tokens(iw, len(lw.id_to_str)),
            "pos": build_postings_from_tokens(ip, len(lp.id_to_str)),
            "lemma": build_postings_from_tokens(il, len(ll.id_to_str)),
        },
        doc_starts=doc_starts,
        doc_ends=np.minimum(doc_starts + 5, n).astype(np.int32),
        sent_starts=sent_starts,
        sent_ends=np.minimum(sent_starts + 7, n).astype(np.int32),
        doc_meta=[{"haelfte": "a" if d % 2 == 0 else "b"} for d in range(len(doc_starts))],
    )


# Beide Auswertungspfade: Postings-Sequenz und NFA-Hybrid (Quantor, Alternative).
_QUERIES = (
    '[word="die"]',
    '[pos="NOUN"]',
    '[word="und"] [word="die"]',
    '[word="und"] | [word="die"]',
    '[pos="ADJ"]* [pos="NOUN"]',
    '[word="der"] []{0,2} [word="und"]',
)


@pytest.fixture(scope="module")
def engine_und_masken():
    corpus = _korpus_mit_ueberlaufenden_saetzen()
    n_docs = int(corpus.doc_starts.shape[0])
    a = np.zeros(n_docs, dtype=np.uint8)
    a[::2] = 1
    return QueryEngine(corpus), corpus, a, (1 - a).astype(np.uint8)


def _opt(maske=None) -> SearchOptions:
    return SearchOptions(
        max_matches=10**9, within_sentences_by_default=True, docset_mask=maske
    )


def test_die_positive_klasse_existiert_ueberhaupt(engine_und_masken):
    """Ohne Treffer an Dokumentgrenzen wuerde auch die kaputte Fassung bestehen.

    Eine Messung ohne positive Klasse ist kein Befund. Dieser Test haelt
    fest, dass der Aufbau die Lage wirklich herstellt, bevor die anderen
    Tests aus ihr Schluesse ziehen.
    """
    engine, corpus, _a, _b = engine_und_masken
    t2d, t2s, s2d = corpus.token_to_doc(), corpus.token_to_sent(), corpus.sent_to_doc()

    betroffen = 0
    for q in _QUERIES:
        starts = np.asarray(
            [m.start for m in engine.search(q, _opt())], dtype=np.int64
        )
        if starts.size:
            betroffen += int((t2d[starts] != s2d[t2s[starts]]).sum())
    assert betroffen > 0, "kein Treffer ueberlaeuft eine Dokumentgrenze"


@pytest.mark.parametrize("query", _QUERIES)
def test_zwei_komplementaere_masken_partitionieren_exakt(engine_und_masken, query):
    """Was keiner Haelfte zufaellt, ist verloren."""
    engine, _corpus, a, b = engine_und_masken

    ganz = len(engine.search(query, _opt()))
    assert ganz > 0, query
    assert len(engine.search(query, _opt(a))) + len(
        engine.search(query, _opt(b))
    ) == ganz

    # count() muss dieselbe Partition liefern wie search(): sonst zaehlt der
    # Zaehler Treffer mit, die die Suche verwirft.
    assert engine.count(query, _opt()) == ganz
    assert engine.count(query, _opt(a)) == len(engine.search(query, _opt(a)))
    assert engine.count(query, _opt(a)) + engine.count(query, _opt(b)) == ganz


@pytest.mark.parametrize("query", _QUERIES)
def test_doc_id_ist_das_dokument_das_die_position_enthaelt(engine_und_masken, query):
    """Die Zuschreibung darf nicht davon abhaengen, OB eine Maske mitkam.

    Eine Vorfassung dieser Reparatur hat nur den Maskenzweig auf
    ``token_to_doc`` umgestellt, nicht die Ausgabe. Danach widersprachen
    sich beide, und ``doc_id`` traegt Dokumentfrequenz und Dispersion.
    """
    engine, corpus, a, _b = engine_und_masken
    for maske in (None, a):
        for m in engine.search(query, _opt(maske)):
            assert m.doc_id is not None
            assert (
                corpus.doc_starts[m.doc_id] <= m.start < corpus.doc_ends[m.doc_id]
            ), f"{query}: Treffer {m.start} liegt nicht in Dokument {m.doc_id}"
            if maske is not None:
                assert a[m.doc_id], f"{query}: Treffer aus einem Dokument ausserhalb der Maske"


_BENCH = os.environ.get("CANDYCONC_INDEX_PATH")


@pytest.mark.skipif(
    not _BENCH or not Path(_BENCH).exists(),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)
@pytest.mark.parametrize(
    "query",
    [
        '[word="und"]',
        '[pos="NOUN"]',
        '[word="nicht"] [word="mehr"]',
        '[word="die"]{2}',
        '[word="und"] []{0,2} [word="die"]',
        '[pos="ADJ"]* [pos="NOUN"]',
    ],
)
def test_die_zuschreibung_am_bench_index(query):
    """Die Achse, die am ECHTEN Index trennt.

    Die Vorfassung dieses Tests hiess ``test_verlust_der_altfassung_am_
    bench_index`` und verlangte nur, dass zwei komplementaere Masken auf
    das ungefilterte Ergebnis summieren. Ein Gate hat sie widerlegt, und
    die Nachmessung gibt ihm recht: bindet man ``token_to_doc`` der
    FastCorpus-Klasse an die satzweise Aufloesung, also an die
    Altfassung, HAELT die Partition am Testindex:

        [word="und"]                797 = 247 + 550   (richtig 262 + 535)
        [pos="ADJ"]* [pos="NOUN"] 5314 = 1688 + 3626  (richtig 1820 + 3494)

    Die Haelften sind falsch, ihre Summe stimmt. Der Verlust, den die
    Commit-Nachricht von 1232f25bda beziffert (797 gegen 682), stammt aus
    dem Zustand VOR der Reparatur von ``_finalize_candidates`` und ist an
    diesem Index seither nicht mehr reproduzierbar.

    Was hier trennt, ist die ZUSCHREIBUNG: unter der Altfassung tragen
    246 der 797, 2163 der 5314 und 21 der 67 Treffer eine ``doc_id``, die
    ihre Position gar nicht enthaelt. Genau das wird geprueft, zusammen
    mit der Partition, die die Gegenrichtung bewacht.
    """
    from candyconc.core.cql_engine import _get_engine
    from candyconc.core.fast_index_backend import FastIndexBackend
    from candyconc.core.meta_filters import metadata_mask

    backend = FastIndexBackend(_BENCH)
    corpus, engine = _get_engine(backend)
    n_docs = int(corpus.doc_starts.shape[0])
    fast = getattr(backend, "fast_index", backend)

    masken = []
    for wert in ("test", "train"):
        m = metadata_mask(fast, {"split": wert}, doc_count=n_docs)
        if m is None:
            pytest.skip("Index kennt das Feld split nicht")
        masken.append(np.asarray(m, dtype=np.uint8))
    a, b = masken
    assert int(a.sum()) + int(b.sum()) == n_docs, "Masken decken den Korpus nicht"

    ganz = engine.count(query, _opt())
    if ganz == 0:
        pytest.skip(f"{query} trifft auf diesem Index nichts")

    # Achse 1, die TRENNENDE: jede doc_id enthaelt ihre Position.
    treffer = engine.search(query, _opt())
    for m in treffer:
        assert m.doc_id is not None
        assert corpus.doc_starts[m.doc_id] <= m.start < corpus.doc_ends[m.doc_id], (
            f"{query}: Treffer {m.start} liegt nicht in Dokument {m.doc_id}")

    # Achse 2, die Gegenrichtung: nichts faellt aus beiden Haelften.
    assert engine.count(query, _opt(a)) + engine.count(query, _opt(b)) == ganz
    assert len(engine.search(query, _opt(a))) + len(
        engine.search(query, _opt(b))) == ganz

    # Achse 3: die Maske haelt, was sie verspricht.
    for maske in (a, b):
        for m in engine.search(query, _opt(maske)):
            assert maske[m.doc_id], f"{query}: Treffer ausserhalb der Maske"
