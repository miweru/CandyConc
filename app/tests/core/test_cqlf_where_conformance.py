"""Die Konformitaetsmatrix fuer ``where()``, und was ihr Fehlen kostet.

``cqlf.level2.where.metadata`` stand auf ``execution="partial"`` und
``tests="partial"``. Es faellt dadurch aus der Beispielsyntax des
Systemprompts, denn die zeigt nur Faehigkeiten, die in Syntax, Ausfuehrung
UND Tests ``supported`` sind (capabilities.py: ``is_declared_supported``).
Das Modell sieht den Bezeichner nur in der Zeile "Partial/guarded", ohne
eine einzige Zeile Syntax. Dieselbe Klasse wie ``within(<doc>)``, dort
hat sie Faktor drei auf einer echten Nutzerfrage gekostet, und dieselbe
Klasse wie die Quantoren, dort 0 statt 45.599 Treffer.

WAS DIE MASCHINE WIRKLICH KANN, an einem 29-Token-Index von Hand
nachgezaehlt und in dieser Datei festgehalten:

    where(register="chat", X)                  Wurzel
    within(<doc>, where(register="chat", X))   geschachtelt
    where(register="chat", within(<doc>, X))   andere Reihenfolge

Alle drei laufen, und die Zaehlwerkzeuge rechnen den Nenner gegen die
eingeschraenkte Dokumentmenge statt gegen den Korpus.

UND WAS SIE NICHT KANN. Die Faehigkeit deklariert sechs Meta-Operatoren
und gibt dieselben sechs an die Autovervollstaendigung weiter. Vier davon
parsen, zwei erreichen den Parser nie, und die Ordnungsvergleiche finden
auf keinem heute gebauten Index Zahlendaten. ``WhereOperatoren`` misst
alle sechs und haelt die zwei Befunde als Proben fest, statt sie
wegzulassen. Eine Faehigkeit, die auf einer von sechs Dimensionen
gemessen wurde, ist nicht gemessen.

DER MINIATURINDEX. Vier Dokumente, zwei Register, vier Jahre, 29 Token:

    d0 chat     2019  "zudem a b . c d ."         7 Token, 1x zudem
    d1 chat     2020  "zudem e f . zudem g h ."   8 Token, 2x zudem
    d2 zeitung  2021  "zudem b . c x ."           6 Token, 1x zudem
    d3 zeitung  2022  "p q r . s t u ."           8 Token, 0x zudem

    Korpus 29 Token, 4x zudem
    chat   15 Token, 3x zudem
    zeitung 14 Token, 1x zudem

Keine zwei dieser Zahlen sind gleich. Das ist Absicht: aus einer
Uebereinstimmung liesse sich sonst der falsche Schluss ziehen, die
Einschraenkung habe gar nicht gewirkt.

``jahr`` traegt vier verschiedene Zahlwerte und dient nur der
Operatorenklasse (``WhereOperatoren``). Es beantwortet die Frage, die
``register`` nicht beantworten kann: was macht ein Ordnungsvergleich.

WARUM ``register`` UND NICHT ``model``. Der generische Bauweg pinnt
``model`` hart auf ``"none"`` und ueberspringt es in ``meta_columns``
(build_fast_index_from_parquet.py: ``"model": "none"`` und die Liste
``("doc_id", "path", "source", "variant", "model", "text_type")``). Ein
Miniaturindex kann ueber diesen Weg kein zweites ``model`` tragen. Am
Testindex gemessen hat ``model`` genau einen Wert und ``split`` zwei,
``register`` einen. Die Feldnamen sind also korpusabhaengig, und der
Prompt sagt eine Zeile weiter, dass nur Attribute aus ``ui_context``
benutzt werden duerfen.

DIESER TEST UEBERSPRINGT NICHT. Er baut seinen Index selbst.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from candyconc.core.corpus_index import CorpusIndex
from candyconc.core.meta_filters import EingabeFormFehler, where_dokumente
from candyconc.core.query_runtime import run_query, set_corpus
from cqlhpc.parser import ParseError

_HIER = Path(__file__).resolve().parent
if str(_HIER) not in sys.path:
    sys.path.insert(0, str(_HIER))

from test_run_query import (  # noqa: E402
    BASIC_COMPONENT,
    REPO_ROOT,
    annotate_basic,
)

#: (Dokument-Id, Register, Jahr, Text). Siehe Modulkopf fuer die Handzaehlung.
DOKUMENTE = (
    ("d0", "chat", 2019, "zudem a b . c d ."),
    ("d1", "chat", 2020, "zudem e f . zudem g h ."),
    ("d2", "zeitung", 2021, "zudem b . c x ."),
    ("d3", "zeitung", 2022, "p q r . s t u ."),
)

#: b steht satzfinal, c satzinitial, dazwischen genau ein Token (der Punkt).
#: Kommt in d0 (chat) und d2 (zeitung) je einmal vor, nirgends sonst.
SATZUEBERGREIFEND = '[word="b"] []{1} [word="c"]'


def _baue_index(out_dir: Path) -> Path:
    """Ein echter Fast Index aus vier Dokumenten, mit Meta-Index.

    ``build_tiny_fast_index`` aus test_run_query baut genau EIN Dokument
    und setzt ``meta_index_fields`` nicht. Beides braucht ``where()``:
    ohne mehrere Dokumente gibt es nichts einzuschraenken, und ohne
    ``meta_index_fields`` gibt es keinen Meta-Index, gegen den die
    Bedingung aufgeloest wird.

    ``jahr`` steht als Zahlenspalte im Parquet und landet trotzdem als
    Zeichenkette im Meta-Index. Der Bauweg schickt jeden Metawert durch
    ``_safe_meta_value`` (build_fast_index_from_parquet.py:638), und der
    liefert immer ``str``. Am gebauten Index gemessen: ``jahr`` hat
    ``has_str=True`` und ``has_num=False``. Am Testindex gilt dasselbe
    fuer alle vierzehn Meta-Felder (meta_index/meta_index.json, jedes
    ``num_values: 0``). Diese Zeile ist die Voraussetzung fuer
    ``WhereOperatoren``, nicht ein Nebenbefund.
    """
    import polars as pl
    import spacy
    from spacy.language import Language

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import scripts.jobs.build_fast_index_from_parquet as build_mod

    if BASIC_COMPONENT not in Language.factories:
        Language.component(BASIC_COMPONENT)(annotate_basic)

    def _blank_load(_name, disable=None, **_kw):
        nlp = spacy.blank("en")
        nlp.add_pipe(BASIC_COMPONENT)
        return nlp

    inp = out_dir / "docs.parquet"
    pl.DataFrame(
        {
            "id": [d[0] for d in DOKUMENTE],
            "register": [d[1] for d in DOKUMENTE],
            "jahr": [d[2] for d in DOKUMENTE],
            "text": [d[3] for d in DOKUMENTE],
        }
    ).write_parquet(inp)
    out = out_dir / "idx"
    real_load = spacy.load
    spacy.load = _blank_load
    try:
        build_mod.build_fast_index_generic(
            inp,
            out,
            spacy_model="blank_en",
            text_column="text",
            id_column="id",
            meta_columns=["register", "jahr"],
            batch_size=1,
            n_process=1,
            disable_deps=True,
            meta_index_fields=["register", "jahr"],
        )
    finally:
        spacy.load = real_load
    return out


class _AmMiniaturindex(unittest.TestCase):
    """Gemeinsamer Unterbau: Index bauen, Korpus setzen, zaehlen."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="cc_where_idx_")
        cls.index_path = _baue_index(Path(cls._tmp))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self):
        self.idx = CorpusIndex(self.index_path, read_only=True)
        set_corpus(self.idx)
        self.addCleanup(self.idx.close)
        self.addCleanup(set_corpus, None)

    def zaehle(self, cql: str) -> int:
        return len(list(run_query("cql:" + cql, ctx=0, corpus=self.idx)))


class WhereKonformitaet(_AmMiniaturindex):
    def test_der_index_ist_der_beschriebene(self):
        """Ohne diese Probe steht alles Weitere auf einer Annahme."""
        self.assertEqual(int(self.idx.token_count()), 29)
        self.assertEqual(int(self.idx.fast_index.meta_index.doc_count), 4)
        satzanfaenge = [
            int(x) for x in self.idx.fast_index.boundaries.sentence._positions
        ]
        self.assertEqual(satzanfaenge, [0, 4, 7, 11, 15, 18, 21, 25])

    # ------------------------------------------------------------------ #
    # where() an der Wurzel.                                              #
    # ------------------------------------------------------------------ #

    def test_where_schraenkt_auf_die_dokumente_des_registers_ein(self):
        """4 im Korpus, 3 in chat, 1 in zeitung. 3 + 1 = 4, ohne Rest."""
        self.assertEqual(self.zaehle('[word="zudem"]'), 4)
        self.assertEqual(self.zaehle('where(register="chat", [word="zudem"])'), 3)
        self.assertEqual(self.zaehle('where(register="zeitung", [word="zudem"])'), 1)

    def test_ein_wert_ohne_dokumente_liefert_null_und_nicht_alles(self):
        """Der teuerste Ausfall waere die stille Ruecknahme der Bedingung.

        Ein Filter, der zu keiner Bedingung normalisiert, ist keine
        fehlende Einschraenkung. Am Testindex lieferte genau dieser
        Fall einmal den ganzen Korpus zurueck (2000 statt 683 Dokumente).
        """
        self.assertEqual(self.zaehle('where(register="gibtsnicht", [word="zudem"])'), 0)

    def test_ein_feld_ohne_meta_index_wirft_statt_zu_zaehlen(self):
        """Die andere Haelfte derselben Frage: ein FELD, das es nicht gibt.

        Ein unbekannter Wert ist eine leere Menge, ein unbekanntes Feld
        ist eine Fehleingabe. Gemessen wirft der Auswerter "Meta Index
        Feld fehlt: gibtsnicht", statt die Bedingung fallen zu lassen und
        alle 4 Vorkommen auszuweisen. Ohne diese Zeile deckte die Matrix
        nur die Wertseite ab, und ein Tippfehler im Feldnamen ist der
        haeufigere der beiden Faelle.
        """
        with self.assertRaises(RuntimeError) as ctx:
            self.zaehle('where(gibtsnicht="chat", [word="zudem"])')
        self.assertIn("Meta Index Feld fehlt", str(ctx.exception))

    # ------------------------------------------------------------------ #
    # where() geschachtelt um within(<doc>, ...). Die eigentliche Aussage.#
    # ------------------------------------------------------------------ #

    def test_der_satzuebergreifende_kern_braucht_den_dokument_scope(self):
        """b auf 2, Luecke auf 3, c auf 4. Satz 2 beginnt auf 4.

        Die Vorgabe ist satzintern, die freie Abfrage findet deshalb
        nichts. Mit ``within(<doc>, ...)`` sind es zwei Treffer, je einer
        in d0 (chat) und d2 (zeitung).
        """
        self.assertEqual(self.zaehle(SATZUEBERGREIFEND), 0)
        self.assertEqual(self.zaehle(f"within(<doc>, {SATZUEBERGREIFEND})"), 2)

    def test_beide_schachtelungen_liefern_dieselbe_zahl(self):
        """where and within wrapper order does not change the query-wide filter.

Check both nestings through the actual query evaluator."""
        for register, erwartet in (("chat", 1), ("zeitung", 1)):
            with self.subTest(register=register):
                self.assertEqual(
                    self.zaehle(
                        f'where(register="{register}", '
                        f"within(<doc>, {SATZUEBERGREIFEND}))"
                    ),
                    erwartet,
                )
                self.assertEqual(
                    self.zaehle(
                        f"within(<doc>, "
                        f'where(register="{register}", {SATZUEBERGREIFEND}))'
                    ),
                    erwartet,
                )

    def test_die_einschraenkung_wirkt_auch_unter_dem_dokument_scope(self):
        """2 im Korpus, je 1 pro Register. Die Summe geht auf.

        Ohne diese Zeile koennte der Dokument-Scope die Bedingung still
        verschluckt haben und trotzdem eine plausible Zahl liefern.
        """
        ganz = self.zaehle(f"within(<doc>, {SATZUEBERGREIFEND})")
        chat = self.zaehle(
            f'where(register="chat", within(<doc>, {SATZUEBERGREIFEND}))'
        )
        zeitung = self.zaehle(
            f'where(register="zeitung", within(<doc>, {SATZUEBERGREIFEND}))'
        )
        self.assertEqual((ganz, chat, zeitung), (2, 1, 1))

    def test_ohne_dokument_scope_bleibt_die_einschraenkung_wirkungslos(self):
        """Die Bedingung kann nur einschraenken, was ueberhaupt gefunden wird."""
        self.assertEqual(
            self.zaehle(f'where(register="chat", {SATZUEBERGREIFEND})'), 0
        )

    # ------------------------------------------------------------------ #
    # Die eine Grenze, die bleibt, und dass sie laut ist.                 #
    # ------------------------------------------------------------------ #

    def test_zwei_gestapelte_bedingungen_werden_und_verknuepft(self):
        """chat UND zeitung ist leer, chat UND chat bleibt chat.

        ``_docset_from_where`` sammelt jede Bedingung auf dem Weg von der
        Wurzel nach innen und verknuepft die Masken mit ``&``. Ohne die
        leere Kombination liesse sich nicht unterscheiden, ob wirklich
        beide Bedingungen gelesen wurden oder nur die aeussere.
        """
        self.assertEqual(
            self.zaehle(
                'where(register="chat", where(register="zeitung", [word="zudem"]))'
            ),
            0,
        )
        self.assertEqual(
            self.zaehle(
                'where(register="chat", where(register="chat", [word="zudem"]))'
            ),
            3,
        )

    def test_branch_lokales_where_wirft_laut(self):
        """Nicht jede Stellung ist ausfuehrbar, und die Grenze ist gemessen.

        ``where()`` muss als queryweiter Wrapper stehen. Steht es in nur
        EINEM Zweig, waere das Ergebnis global UND-verknuepft und damit
        etwas anderes, als der Text sagt. Alle drei Stellungen werfen.
        """
        for cql in (
            '(where(register="chat", [word="zudem"]) | [word="x"])',
            '[word="zudem"] where(register="chat", [word="e"])',
            'where(register="chat", [word="zudem"]) [word="e"]',
        ):
            with self.subTest(cql=cql):
                with self.assertRaises(RuntimeError) as ctx:
                    self.zaehle(cql)
                self.assertIn("Branch-lokales where()", str(ctx.exception))


class WhereOperatoren(_AmMiniaturindex):
    """Die Operatorenflaeche, die die Faehigkeit deklariert, ganz gemessen.

    ``capabilities.py`` fuehrt fuer diese Faehigkeit sechs Operatoren
    (``meta_operators``), und ``language_service_meta_operators`` gibt
    dieselben sechs an die Autovervollstaendigung weiter
    (autocomplete.py: Zustand ``where_op``). Die erste Fassung dieser
    Matrix mass genau einen davon, naemlich ``=``, und stufte die
    Faehigkeit trotzdem auf ``supported`` hoch. Zum Vergleich:
    ``within()`` deckte mit ``<s>`` UND ``<doc>`` seine ganze deklarierte
    Flaeche ab, bevor es hochgestuft wurde.

    An diesem Index und am Testindex gemessen, alle sechs:

        =    traegt         3 in chat, 1 in zeitung
        !=   traegt         1 in chat-Gegenprobe
        >=   wirft          EingabeFormFehler
        <=   wirft          EingabeFormFehler
        >    parst nicht    ParseError: expected OP, got RANGLE
        <    parst nicht    ParseError: expected OP, got LANGLE

    Zwei davon sind Befunde und keine gruene Flaeche. Sie werden hier
    festgehalten statt weggelassen, denn eine Liste, die etwas verspricht,
    was nie parst, ist teurer als eine kurze Liste.
    """

    def test_gleich_und_ungleich_tragen_die_ganze_gruene_flaeche(self):
        """Beide Richtungen, auf beiden Feldern, Summe geht auf.

        register: 3 + 1 = 4. jahr: d1 traegt 2 der 4 Vorkommen, also
        liefert die Gegenprobe die anderen 2.
        """
        self.assertEqual(self.zaehle('where(register="chat", [word="zudem"])'), 3)
        self.assertEqual(self.zaehle('where(register!="chat", [word="zudem"])'), 1)
        self.assertEqual(self.zaehle('where(jahr="2020", [word="zudem"])'), 2)
        self.assertEqual(self.zaehle('where(jahr!="2020", [word="zudem"])'), 2)

    def test_eine_zahl_ohne_anfuehrungszeichen_wirft(self):
        """Der Wert ``2020`` und der Wert ``"2020"`` sind nicht dasselbe.

        Der Meta-Index fuehrt ``jahr`` als Zeichenkette (has_num=False,
        siehe ``_baue_index``). Ein Zahlliteral nimmt in ``mask_for_cond``
        (meta_index.py:151) den Zahlenzweig und laeuft in
        ``_mask_num_range``, das ohne Zahlendaten wirft. Gemessen liefert
        ``where(jahr="2020", ...)`` 2 Treffer und ``where(jahr=2020, ...)``
        eine Ausnahme.

        Das ist eine Falle mit zweiter Quelle: die Autovervollstaendigung
        bietet im Zustand ``where_val`` ausdruecklich ``123`` als Wert an
        (autocomplete.py:184). Sie wirft nicht still den Korpusnenner
        zurueck, und genau deshalb steht die Probe hier.
        """
        with self.assertRaises(EingabeFormFehler) as ctx:
            self.zaehle('where(jahr=2020, [word="zudem"])')
        self.assertIn("keine Zahlenwerte", str(ctx.exception))

    def test_ordnungsvergleiche_werfen_auf_stringdaten(self):
        """``>=`` und ``<=`` parsen, aber kein Feld traegt Zahlendaten.

        Zwei verschiedene Meldungen, je nach Literal, beide
        ``EingabeFormFehler`` und damit HTTP 400 statt 500:
        ein Zeichenkettenliteral trifft "Ein Stringvergleich geht nur mit
        = oder !=" (meta_index.py:163), ein Zahlliteral trifft "fuehrt
        keine Zahlenwerte" (meta_index.py:99). Am Testindex ist das
        nicht anders, dort hat jedes der vierzehn Meta-Felder
        ``num_values: 0``.
        """
        for cql, brocken in (
            ('where(jahr>="2020", [word="zudem"])', "nur mit = oder"),
            ('where(jahr<="2020", [word="zudem"])', "nur mit = oder"),
            ('where(register>="chat", [word="zudem"])', "nur mit = oder"),
            ('where(jahr>=2020, [word="zudem"])', "keine Zahlenwerte"),
            ('where(jahr<=2020, [word="zudem"])', "keine Zahlenwerte"),
        ):
            with self.subTest(cql=cql):
                with self.assertRaises(EingabeFormFehler) as ctx:
                    self.zaehle(cql)
                self.assertIn(brocken, str(ctx.exception))

    def test_groesser_und_kleiner_erreichen_den_parser_nie(self):
        """FESTGEHALTENER DEFEKT, nicht behoben, sondern gemessen.

        Der Lexer bildet ``<`` und ``>`` auf LANGLE und RANGLE ab
        (lexer.py:28-29), und diese Abbildung steht VOR dem Zweig fuer
        einstellige Operatoren (lexer.py:101). Das ``self.eat('OP')`` in
        ``parse_meta_cond`` (parser.py:454) kann die beiden deshalb nie
        sehen, obwohl die Annahmeliste eine Zeile darunter
        (parser.py:456) sie fuehrt und ``_mask_num_range``
        (meta_index.py:109) ``>`` ausdruecklich implementiert. Drei
        Stellen, zwei Meinungen.

        Nicht hier repariert: LANGLE und RANGLE tragen die
        Regionensyntax ``within(<s>, ...)``, eine Lexeraenderung waere
        eine Sprachaenderung mit eigener Matrix.
        """
        for cql, erwartet in (
            ('where(jahr>2019, [word="zudem"])', "RANGLE"),
            ('where(jahr<2021, [word="zudem"])', "LANGLE"),
        ):
            with self.subTest(cql=cql):
                with self.assertRaises(ParseError) as ctx:
                    self.zaehle(cql)
                self.assertIn(f"expected OP, got {erwartet}", str(ctx.exception))

    def test_die_vorschlagsliste_verspricht_zwei_tote_operatoren(self):
        """Der Widerspruch selbst, an einer Stelle festgenagelt.

        Die Autovervollstaendigung bietet im Zustand ``where_op`` alle
        sechs an. Zwei davon parsen nach der Probe eine Klasse hoeher
        nie. Wer die Luecke schliesst, sei es im Lexer oder in der Liste,
        macht diese Probe rot und liest hier, was gemessen war.
        """
        from cqlhpc.capabilities import language_service_meta_operators

        angeboten = set(language_service_meta_operators())
        self.assertEqual(angeboten, {"=", "!=", ">=", "<=", ">", "<"})
        self.assertTrue({">", "<"} <= angeboten)


class WhereNenner(_AmMiniaturindex):
    """Der Nenner der Zaehlwerkzeuge, gegen die Handzaehlung.

    Eine ``where()``-Einschraenkung IM Abfragetext setzt kein
    ``docset_id``. Der Nenner war deshalb einmal der ganze Korpus, am
    Testindex gemessen 4662,7 statt 13965,1 pro Million. Eine Rate mit
    falschem Nenner ist schlimmer als keine Rate.
    """

    def test_where_dokumente_liefert_die_richtige_teilmenge(self):
        """Die gemeinsame Naht beider Oberflaechen (REST und Copilot)."""
        chat = where_dokumente(self.idx, 'cql:where(register="chat", [word="zudem"])')
        self.assertEqual(list(chat), [0, 1])
        self.assertEqual(int(self.idx.docset_token_count(chat)), 15)

        zeitung = where_dokumente(
            self.idx, 'cql:where(register="zeitung", [word="zudem"])'
        )
        self.assertEqual(list(zeitung), [2, 3])
        self.assertEqual(int(self.idx.docset_token_count(zeitung)), 14)

    def test_where_dokumente_sieht_die_bedingung_auch_unter_within(self):
        """Eine Klammer weiter innen ist dieselbe Einschraenkung.

        Eine Vorfassung sah nur ein Where ganz aussen, und
        ``within(<s>, where(...))`` zaehlte gegen den Korpusnenner.
        """
        ids = where_dokumente(
            self.idx,
            'cql:within(<doc>, where(register="zeitung", [word="zudem"]))',
        )
        self.assertEqual(list(ids), [2, 3])
        self.assertEqual(int(self.idx.docset_token_count(ids)), 14)

    def test_ohne_where_bleibt_der_korpusnenner(self):
        """``None`` heisst "keine Einschraenkung im Abfragetext"."""
        self.assertIsNone(where_dokumente(self.idx, 'cql:[word="zudem"]'))

    def test_query_count_normiert_auf_die_eingeschraenkte_menge(self):
        """Gemessen an diesem Index, jede Zahl von Hand nachzaehlbar:

            [word="zudem"]                       4 / 29  = 137931,0 pmw
            where(register="chat", ...)          3 / 15  = 200000,0 pmw
            where(register="zeitung", ...)       1 / 14  =  71428,6 pmw
            within(<doc>, where(chat, ...))      3 / 15  = 200000,0 pmw

        ``corpus_tokens`` behaelt in allen vier Faellen die Bedeutung
        "ganzer Korpus" und bleibt 29. Nur ``denominator_tokens`` folgt
        der Einschraenkung.
        """
        from candyconc.services.backend import server as _server
        from tests.ai.test_tool_wrappers_parity_r5 import (
            _load_real_tool_wrappers,
        )

        tw = _load_real_tool_wrappers()
        vorher = getattr(_server, "_INDEX", None)
        _server.set_default_index(self.idx)
        try:
            # Analysis-token denominators exclude punctuation: 21 of 29 tokens in
            # the corpus, 11 of 15 in chat and 10 of 14 in zeitung. Preserve the
            # raw counts alongside them in denominator_tokens_raw.
            faelle = (
                ('cql:[word="zudem"]', 4, 21, 29, "corpus", 190476.2),
                ('cql:where(register="chat", [word="zudem"])',
                 3, 11, 15, "docset", 272727.3),
                ('cql:where(register="zeitung", [word="zudem"])',
                 1, 10, 14, "docset", 100000.0),
                ('cql:within(<doc>, where(register="chat", [word="zudem"]))',
                 3, 11, 15, "docset", 272727.3),
            )
            for query, treffer, nenner, roh, bereich, pmw in faelle:
                with self.subTest(query=query):
                    r = tw.query_count_tool(query)
                    self.assertEqual(int(r["total"]), treffer)
                    self.assertEqual(int(r["denominator_tokens"]), nenner)
                    self.assertEqual(int(r["denominator_tokens_raw"]), roh)
                    self.assertEqual(r["denominator_scope"], bereich)
                    self.assertEqual(float(r["per_million"]), pmw)
                    self.assertEqual(int(r["corpus_tokens"]), 29)
        finally:
            _server.set_default_index(vorher)


class WhereOhneMetaIndex(unittest.TestCase):
    """Der Fehlerfall, und dass er laut ist.

    Ein vor dem Meta-Index gebauter Fast Index hat das Verzeichnis nicht.
    Der Bauweg legt es heute immer an, deshalb wird es hier entfernt: das
    ist der Zustand, den die Meldung "Bitte Fast Index neu bauen" meint.

    Still zu degradieren waere hier besonders teuer, denn die Antwort
    saehe aus wie eine eingeschraenkte Zahl und waere die des ganzen
    Korpus.
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="cc_where_ohne_meta_")
        cls.index_path = _baue_index(Path(cls._tmp))
        shutil.rmtree(Path(cls.index_path) / "meta_index")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self):
        self.idx = CorpusIndex(self.index_path, read_only=True)
        set_corpus(self.idx)
        self.addCleanup(self.idx.close)
        self.addCleanup(set_corpus, None)

    def test_der_index_hat_wirklich_keinen_meta_index(self):
        self.assertIsNone(getattr(self.idx.fast_index, "meta_index", None))

    def test_where_wirft_statt_still_den_ganzen_korpus_zu_zaehlen(self):
        with self.assertRaises(RuntimeError) as ctx:
            list(
                run_query(
                    'cql:where(register="chat", [word="zudem"])',
                    ctx=0,
                    corpus=self.idx,
                )
            )
        self.assertIn("Meta Index", str(ctx.exception))

    def test_die_freie_abfrage_laeuft_unveraendert_weiter(self):
        """Der fehlende Meta-Index legt nur ``where()`` still, nicht alles."""
        self.assertEqual(
            len(list(run_query('cql:[word="zudem"]', ctx=0, corpus=self.idx))), 4
        )

    def test_auch_die_werkzeugoberflaeche_wirft(self):
        """Die Naht, an der ein Nutzer den Ausfall trifft.

        ``run_query`` zu pruefen genuegt nicht: die Zaehlwerkzeuge bilden
        den Nenner mit ``where_dokumente`` und rufen die Abfrage getrennt
        auf. Gemessen an diesem Index wirft ``query_count_tool`` mit
        "Meta Index fehlt fuer where(). Bitte Fast Index neu bauen.",
        waehrend dieselbe freie Abfrage 4 Treffer und den Korpusnenner 29
        liefert. Der Ausfall trifft also where() und nicht das Werkzeug.
        """
        from candyconc.services.backend import server as _server
        from tests.ai.test_tool_wrappers_parity_r5 import (
            _load_real_tool_wrappers,
        )

        tw = _load_real_tool_wrappers()
        vorher = getattr(_server, "_INDEX", None)
        _server.set_default_index(self.idx)
        try:
            with self.assertRaises(RuntimeError) as ctx:
                tw.query_count_tool('cql:where(register="chat", [word="zudem"])')
            self.assertIn("Meta Index fehlt", str(ctx.exception))
            frei = tw.query_count_tool('cql:[word="zudem"]')
            self.assertEqual(
                (int(frei["total"]), int(frei["denominator_tokens"]),
                 int(frei["denominator_tokens_raw"])),
                (4, 21, 29),  # Analysis tokens, with the raw count reported separately.
            )
        finally:
            _server.set_default_index(vorher)

    def test_der_nenner_allein_wuerde_still_den_korpus_nehmen(self):
        """A missing metadata index returns None at the denominator helper boundary.

Record that behavior separately from the query path, which rejects the
missing metadata index before the denominator is used."""
        self.assertIsNone(
            where_dokumente(self.idx, 'cql:where(register="chat", [word="zudem"])')
        )
        self.assertEqual(int(self.idx.token_count()), 29)


class DerPromptZeigtDieSyntax(unittest.TestCase):
    """Die Maschine kann es. Der Prompt muss es auch sagen.

    Genau diese Probe fehlte bei den Quantoren, und die Luecke kostete
    dort 0 statt 45.599 Treffer auf einer echten Nutzerfrage.
    """

    def test_where_ist_in_allen_gepruefeten_dimensionen_supported(self):
        from cqlhpc.capabilities import supported_capabilities

        ids = {cap.id for cap in supported_capabilities()}
        self.assertIn("cqlf.level2.where.metadata", ids)

    def test_die_beispielsyntax_zeigt_where_mit_einer_bedingung(self):
        """Ein Bezeichner ist keine Syntax.

        ``where($1, $2)`` rendert zu ``where(x, y)`` und verschweigt, dass
        das erste Argument ``feld="wert"`` ist. Ohne diese Form komponiert
        das Modell die Bedingung nicht.
        """
        from candyconc.candyconc_copilot.prompt_layout import build_static_core

        kern = build_static_core()
        self.assertIn('where(model="x"', kern)

    def test_der_kern_bleibt_unter_seinem_budget(self):
        from candyconc.candyconc_copilot.prompt_layout import (
            STATIC_CORE_MAX_CHARS,
            build_static_core,
        )

        self.assertLessEqual(len(build_static_core()), STATIC_CORE_MAX_CHARS)


if __name__ == "__main__":
    unittest.main()
