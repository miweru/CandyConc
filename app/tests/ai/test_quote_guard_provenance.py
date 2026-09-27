"""Gate 11, Klasse B: die Zitatwache nach Herkunft, Form und Anfuehrungsart.

Drei Befunde des elften Gates, alle am Testindex gemessen:

1. SELBSTDECKUNG ueber ein anderes Werkzeug. ``semantic_cluster_words``
   spiegelt die uebergebenen ``tokens`` nach ``clusters[].samples``. Die
   gerenderte Zeile ``cluster[1] {'samples': ['<Fabrikat>'], ...}`` sieht
   aus wie Korpusinhalt, also deckte sie das Fabrikat: ``ZITAT_BELEGT
   True``, Fabrikat in der Prosa, NULL Annotationen. Die Klasse war damit
   ueber ein anderes Werkzeug wieder offen, nachdem sie fuer die
   Suchbegriff-Werkzeuge geschlossen war. ``traegt_korpusinhalt`` prueft
   die FORM einer Zeile, und Form allein reicht nicht.

2. ``documentation_search`` liest das HANDBUCH dieser Software. Ein Satz
   aus ``chat_api.md`` deckte ein "Korpuszitat": ein Falschbeleg, kein
   Fabrikat, und fuer einen Konkordanzer genauso wertlos.

3. Die Wache kannte GENAU ZWEI Anfuehrungsformen. Von zehn geprueften
   liefen acht ungeprueft durch, waehrend die Antwort weiter zusicherte,
   Zitate seien deterministisch gegen die Evidenz aufgeloest.

Und die Gegenrichtung, die in dieser Kampagne schon zweimal gebissen hat:
eine Wache, die echte Belege streicht, ist so schaedlich wie eine, die
Fabrikate durchlaesst.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_BENCH = os.environ.get("CANDYCONC_INDEX_PATH")
_WURZEL = Path(__file__).resolve().parents[2]


def _messen(skript: str) -> dict:
    """Ausserhalb pytest: tests/conftest.py stubbt candyconc_copilot."""
    import json

    r = subprocess.run(
        [sys.executable, "-c", skript], capture_output=True, text=True,
        cwd=str(_WURZEL), timeout=1800,
        env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""),
             "CANDYCONC_INDEX_PATH": _BENCH or ""})
    assert r.returncode == 0 and "<<<JSON>>>" in r.stdout, r.stderr[-700:]
    return json.loads(r.stdout.split("<<<JSON>>>", 1)[1])


_VORSPANN = (
    "import sys, json; sys.path.insert(0,'src')\n"
    "from candyconc.services.backend import server as S\n"
    "from candyconc.candyconc_copilot import (\n"
    "    tool_wrappers as tw, query_runtime as QR, recipe_runtime as rr)\n"
    "from candyconc.candyconc_copilot.grounding_facts import make_evidence_item\n"
    "QR._CORPUS_INDEX = S.get_corpus(None)\n"
    "F = 'der jungen Maenner sind keine Fluechtlinge sondern ruecksichtslose Invasoren'\n"
    "def kern(t):\n"
    "    return t.split(rr.METHODENSTECKBRIEF_UEBERSCHRIFT)[0]\n"
)


class TestDieHerkunftEntscheidetMit:
    """Punkt 1 und 2: Form allein reicht nicht."""

    def test_die_liste_deckt_die_ganze_registry_ab(self):
        """Sonst veraltet sie still, und ein neues Werkzeug verliert
        entweder seine Belege oder oeffnet die Wache wieder."""
        raus = _messen(
            "import sys, json; sys.path.insert(0,'src')\n"
            "from candyconc.tooling import registry as R\n"
            "import candyconc.candyconc_copilot.tool_wrappers  # fuellt REGISTRY\n"
            "from candyconc.candyconc_copilot.grounding_evidence import (\n"
            "    KORPUSLESENDE_WERKZEUGE, NICHT_KORPUSLESENDE_WERKZEUGE)\n"
            "namen = {(e.get('function') or {}).get('name') for e in R.REGISTRY}\n"
            "namen.discard(None)\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
            "  'registry': sorted(namen),\n"
            "  'unklassifiziert': sorted(\n"
            "      namen - KORPUSLESENDE_WERKZEUGE - NICHT_KORPUSLESENDE_WERKZEUGE),\n"
            "  'ueberzaehlig': sorted(\n"
            "      (KORPUSLESENDE_WERKZEUGE | NICHT_KORPUSLESENDE_WERKZEUGE) - namen),\n"
            "  'ueberschneidung': sorted(\n"
            "      KORPUSLESENDE_WERKZEUGE & NICHT_KORPUSLESENDE_WERKZEUGE)}))\n"
        )
        assert raus["registry"], raus
        assert raus["unklassifiziert"] == [], (
            "Diese Werkzeuge sind weder als korpuslesend noch als "
            "nicht-korpuslesend gefuehrt: %r" % (raus["unklassifiziert"],))
        assert raus["ueberschneidung"] == [], raus
        assert raus["ueberzaehlig"] == [], (
            "Die Liste nennt Werkzeuge, die es nicht mehr gibt: %r"
            % (raus["ueberzaehlig"],))

    @pytest.mark.skipif(not _BENCH, reason="Testindex nicht gesetzt")
    def test_die_eigene_eingabe_deckt_nichts_auch_ueber_cluster_werkzeuge(self):
        raus = _messen(
            _VORSPANN
            + "args = {'tokens': [F], 'top_n': 6}\n"
            "out = tw.semantic_cluster_words_tool(**args)\n"
            "it = make_evidence_item(item_id='e', tool='semantic_cluster_words',\n"
            "    tool_call_id='c', query=args, output=out, analysis_family='semantic')\n"
            "bel = rr.evidenz_belegzeilen([it])\n"
            "t, a = rr.politur_mit_zitatwache('Beleg: \\u201e%s\\u201c' % F, [it])\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
            "  'spiegelt_die_eingabe': F in json.dumps(out, ensure_ascii=False),\n"
            "  'belegzeilen': len(bel), 'fabrikat': F in kern(t),\n"
            "  'annotiert': bool(a)}))\n"
        )
        # Die positive Klasse: das Werkzeug spiegelt die Eingabe wirklich
        # zurueck. Ohne sie prueft dieser Test nichts.
        assert raus["spiegelt_die_eingabe"] is True, raus
        assert raus["belegzeilen"] == 0, raus
        assert raus["fabrikat"] is False, raus
        assert raus["annotiert"] is True, raus

    @pytest.mark.skipif(not _BENCH, reason="Testindex nicht gesetzt")
    def test_handbuchtext_deckt_kein_korpuszitat(self):
        raus = _messen(
            _VORSPANN
            + "out = tw.documentation_search_tool(term='Konkordanz', top_n=5, snippet=40)\n"
            "it = make_evidence_item(item_id='d', tool='documentation_search',\n"
            "    tool_call_id='c', query={'term':'Konkordanz'}, output=out,\n"
            "    analysis_family='docs')\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
            "  'hat_treffer': bool((out or {}).get('rows')),\n"
            "  'belegzeilen': len(rr.evidenz_belegzeilen([it]))}))\n"
        )
        assert raus["hat_treffer"] is True, (
            "positive Klasse fehlt: die Handbuchsuche liefert nichts")
        assert raus["belegzeilen"] == 0, raus


@pytest.mark.skipif(not _BENCH, reason="Testindex nicht gesetzt")
class TestJedeAnfuehrungsformWirdGeprueft:
    """Punkt 3: acht von zehn Formen liefen ungeprueft durch."""

    def _lauf(self):
        return _messen(
            _VORSPANN
            + "o = tw.query_count_tool(query='und')\n"
            "it = make_evidence_item(item_id='e', tool='query_count',\n"
            "    tool_call_id='c', query={'query':'und'}, output=o,\n"
            "    analysis_family='lexical')\n"
            "formen = {\n"
            "  'typografisch': '\\u201e%s\\u201c', 'gerade': '\"%s\"',\n"
            "  'englisch': '\\u201c%s\\u201d', 'guillemets': '\\u00bb%s\\u00ab',\n"
            "  'franzoesisch': '\\u00ab%s\\u00bb', 'einfach_dt': '\\u201a%s\\u2018',\n"
            "  'apostroph': \"'%s'\", 'kursiv': '*%s*', 'code': '`%s`',\n"
            "}\n"
            "raus = {}\n"
            "for name, muster in formen.items():\n"
            "    t, a = rr.politur_mit_zitatwache('Beleg: ' + muster % F, [it])\n"
            "    raus[name] = {'fabrikat': F in kern(t), 'annotiert': bool(a)}\n"
            "t, a = rr.politur_mit_zitatwache('> ' + F, [it])\n"
            "raus['blockzitat'] = {'fabrikat': F in kern(t), 'annotiert': bool(a)}\n"
            "t, a = rr.politur_mit_zitatwache(\n"
            "    'Beleg: \\u201e%s\\n%s\\u201c' % (F[:34], F[34:]), [it])\n"
            "raus['mehrzeilig'] = {'fabrikat': F[:30] in kern(t), 'annotiert': bool(a)}\n"
            "raus['_belegzeilen'] = len(rr.evidenz_belegzeilen([it]))\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps(raus))\n"
        )

    def test_null_belegzeilen_ist_die_ausgangslage(self):
        # Die positive Klasse: query_count traegt keinen Korpustext, das
        # Fabrikat ist also in KEINER Form gedeckt.
        assert self._lauf()["_belegzeilen"] == 0

    @pytest.mark.parametrize("form", [
        "typografisch", "gerade", "englisch", "guillemets", "franzoesisch",
        "einfach_dt", "apostroph", "kursiv", "code", "blockzitat", "mehrzeilig",
    ])
    def test_die_form_laesst_kein_fabrikat_durch(self, form):
        m = self._lauf()
        assert m[form]["fabrikat"] is False, (form, m[form])
        assert m[form]["annotiert"] is True, (form, m[form])


@pytest.mark.skipif(not _BENCH, reason="Testindex nicht gesetzt")
class TestDieWacheStreichtKeineEchtenBelege:
    """Die Gegenrichtung, an 600 echten Konkordanzzeilen gemessen.

    Drei getrennte Ursachen sind hier eingefangen worden:
    ein Backtick aus dem KORPUSTEXT (``kann ` s nicht fassen``) loeste die
    Kappung offener Spannen aus und loeschte den GEDECKTEN Beleg spurlos,
    ohne Annotation und ohne Platzhalter. Ein gerades Anfuehrungszeichen aus
    dem Korpustext beendete die Schutzmaske zu frueh. Und die Faltung von
    Leerraum vor Satzzeichen schrieb den Beleg um: der Index ist
    tokenisiert, in fast jeder KWIC-Zeile steht ein Leerzeichen vor dem
    Satzzeichen. Von 600 Zitaten waren 526 nicht byte-gleich zur Korpuszeile.
    """

    def _lauf(self):
        return _messen(
            _VORSPANN
            + "begriffe = [r['word'] for r in tw.frequency_list_tool(top_n=60)['rows']][:60]\n"
            "gesamt = gestrichen = untreu = 0\n"
            "backtick = gerade = 0\n"
            "for w in begriffe:\n"
            "    try: o = tw.run_cqlf_query_tool(query=w, ctx=8, limit=10)\n"
            "    except Exception: continue\n"
            "    if not o.get('rows'): continue\n"
            "    it = make_evidence_item(item_id='k', tool='run_cqlf_query',\n"
            "        tool_call_id='c', query={'query':w}, output=o, analysis_family='kwic')\n"
            "    for r in o['rows']:\n"
            "        z = ' '.join(' '.join(x for x in (r['left'].strip(),\n"
            "            r['kw'].strip(), r['right'].strip()) if x).split())\n"
            "        if len(z) < 12: continue\n"
            "        gesamt += 1\n"
            "        if '`' in z: backtick += 1\n"
            "        if '\"' in z: gerade += 1\n"
            "        t, a = rr.politur_mit_zitatwache('Der Beleg lautet: \\u201e%s\\u201c' % z, [it])\n"
            "        if a: gestrichen += 1\n"
            "        elif z not in t: untreu += 1\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
            "  'gesamt': gesamt, 'gestrichen': gestrichen, 'untreu': untreu,\n"
            "  'mit_backtick': backtick, 'mit_geradem_zitatzeichen': gerade}))\n"
        )

    def test_kein_echter_beleg_wird_gestrichen(self):
        m = self._lauf()
        assert m["gesamt"] >= 500, m
        assert m["gestrichen"] == 0, m

    def test_jeder_beleg_wird_byte_treu_ausgeliefert(self):
        m = self._lauf()
        assert m["untreu"] == 0, m

    def test_die_gefaehrlichen_zeichen_kommen_wirklich_vor(self):
        # Positive Klasse fuer die beiden Ursachen oben. Ohne sie waeren
        # die zwei Tests darueber leer.
        m = self._lauf()
        assert m["mit_backtick"] >= 1, m
        assert m["mit_geradem_zitatzeichen"] >= 1, m


@pytest.mark.skipif(not _BENCH, reason="Testindex nicht gesetzt")
class TestDieEigeneAuszeichnungBleibtStehen:
    """Die Wache darf die vom Harness ERZEUGTE Auszeichnung nicht streichen.

    ``Gebrauch von `Zeit` im sichtbaren Suchlauf: `total=7` Treffer`` ist
    kein Modelltext, sondern der deterministische Renderer. Mit einer
    Laengenbedingung IN der Regex uebersprang der Scanner die zu kurze
    Spanne ``Zeit`` und paarte deren schliessenden Backtick mit dem
    oeffnenden von ``total=7``: die Spanne `` im sichtbaren Suchlauf ``
    galt als ungedecktes Zitat, wurde gestrichen, und
    ``drop_unresolved_sentences`` nahm den ganzen Satz mit.
    """

    def _lauf(self):
        return _messen(
            _VORSPANN
            + "o = tw.query_count_tool(query='und')\n"
            "it = make_evidence_item(item_id='e', tool='query_count',\n"
            "    tool_call_id='c', query={'query':'und'}, output=o,\n"
            "    analysis_family='lexical')\n"
            "TEXT = ('Gebrauch von `Zeit` im sichtbaren Suchlauf: '\n"
            "        '`total=7` Treffer, 1 sichtbare Trefferzeilen.')\n"
            "t, a = rr.politur_mit_zitatwache(TEXT, [it])\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
            "  'text': kern(t).strip(), 'annotiert': bool(a),\n"
            "  'belegzeilen': len(rr.evidenz_belegzeilen([it]))}))\n"
        )

    def test_die_maschinenauszeichnung_ueberlebt_unveraendert(self):
        m = self._lauf()
        assert m["belegzeilen"] == 0, (
            "positive Klasse: ohne Belegzeilen wuerde jedes echte Zitat "
            "gestrichen, die Auszeichnung aber nicht")
        assert "total=7" in m["text"], m
        assert "im sichtbaren Suchlauf" in m["text"], m
        assert m["annotiert"] is False, m


@pytest.mark.skipif(not _BENCH, reason="Testindex nicht gesetzt")
class TestDerProduktivpfadTraegtDenWerkzeugnamen:
    """Die Kehrseite der Herkunftsregel.

    Die Regel laesst nur Zeilen von Werkzeugen aus
    ``KORPUSLESENDE_WERKZEUGE`` decken. Traegt ein Evidenzposten des
    PRODUKTIVpfades keinen oder einen unbekannten Werkzeugnamen, verliert
    er still alle Belege, und die Wache streicht danach jedes Zitat -- die
    "Schere", vor der die aelteren Tests dieser Kampagne warnen.

    Der Produktivpfad hat genau EINE Quelle (orchestrator.py:6989 baut den
    Posten, :6997 legt ``to_dict()`` ab, :2745 haengt ihn an den Turn, und
    :2897 gibt die Liste an den Engpass). Dieser Test haelt fest, dass der
    Werkzeugname diesen Weg ueberlebt, statt sich auf die Lektuere zu
    verlassen.
    """

    def test_to_dict_traegt_einen_namen_aus_der_registry(self):
        raus = _messen(
            "import sys, json; sys.path.insert(0,'src')\n"
            "from candyconc.services.backend import server as S\n"
            "from candyconc.candyconc_copilot import tool_wrappers as tw, query_runtime as QR\n"
            "from candyconc.candyconc_copilot.grounding_facts import make_evidence_item\n"
            "from candyconc.candyconc_copilot.grounding_evidence import (\n"
            "    KORPUSLESENDE_WERKZEUGE, werkzeug_liefert_korpusbeleg)\n"
            "QR._CORPUS_INDEX = S.get_corpus(None)\n"
            "proben = {\n"
            "  'run_cqlf_query': lambda: tw.run_cqlf_query_tool(query='und', limit=2),\n"
            "  'query_count': lambda: tw.query_count_tool(query='und'),\n"
            "  'document_search': lambda: tw.document_search_tool('Menschen', top_n=2),\n"
            "  'frequency_list': lambda: tw.frequency_list_tool(top_n=3),\n"
            "}\n"
            "raus = {}\n"
            "for name, f in proben.items():\n"
            "    d = make_evidence_item(item_id='e', tool=name, tool_call_id='c',\n"
            "        query={}, output=f(), analysis_family='x').to_dict()\n"
            "    raus[name] = {'tool': d.get('tool'),\n"
            "                  'deckt': werkzeug_liefert_korpusbeleg(d.get('tool'))}\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps(raus))\n"
        )
        for name, wert in raus.items():
            assert wert["tool"] == name, (name, wert)
            assert wert["deckt"] is True, (
                "Der Produktivpfad wuerde fuer %r alle Belege verlieren" % name)

    def test_ein_posten_ohne_werkzeugnamen_deckt_nichts(self):
        """Die Gegenrichtung, ausdruecklich festgehalten.

        Kein Name heisst kein Beleg. Das ist die sichere Richtung gegen den
        Angriff, und genau deshalb muss der Test darueber halten.
        """
        raus = _messen(
            "import sys, json; sys.path.insert(0,'src')\n"
            "from candyconc.candyconc_copilot.grounding_evidence import (\n"
            "    werkzeug_liefert_korpusbeleg as w)\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
            "  'leer': w(''), 'none': w(None), 'unbekannt': w('gibtsnicht'),\n"
            "  'bekannt': w('run_cqlf_query')}))\n"
        )
        assert raus["leer"] is False and raus["none"] is False, raus
        assert raus["unbekannt"] is False, raus
        assert raus["bekannt"] is True, raus


@pytest.mark.skipif(not _BENCH, reason="Testindex nicht gesetzt")
class TestDieVerbreiterungRissDreiNeueLoecher:
    """Gate 12: meine eigene Erweiterung auf elf Anfuehrungsformen.

    Alle drei Befunde sind Regressionen der Reparatur, nicht des
    urspruenglichen Zustands, und alle drei sind am Testindex gemessen.
    """

    def _lauf(self):
        return _messen(
            _VORSPANN
            + "from candyconc.candyconc_copilot.grounding_facts import make_evidence_item\n"
            "out = tw.run_cqlf_query_tool(query='cql:[word=\"und\"]', ctx=8, limit=200)\n"
            "ev = make_evidence_item(item_id='F1', tool='run_cqlf_query',\n"
            "    tool_call_id='c1', query={'query':'cql:[word=\"und\"]'},\n"
            "    output=out, analysis_family='kwic')\n"
            "belege = rr.evidenz_belegzeilen([ev.to_dict()])\n"
            "r0, r5 = out['rows'][0], out['rows'][5]\n"
            "z0 = ' '.join((r0['left'] + ' ' + r0['kw'] + ' ' + r0['right']).split())\n"
            "z5 = ' '.join((r5['left'] + ' ' + r5['kw'] + ' ' + r5['right']).split())\n"
            # 1: unpaariges oeffnendes Anfuehrungszeichen
            "text = ('Befund\\n\\nDie Abfrage liefert 797 Treffer im Korpus.\\n'\n"
            "        'Ein Beleg lautet: \\u201e' + z0 + '\\n\\n'\n"
            "        'Im Test-Split sind es 262 Treffer bei 18761 Tokens.\\n'\n"
            "        'Die Verteilung erstreckt sich ueber 683 Dokumente.\\n'\n"
            "        'Ein zweiter Beleg lautet: \\u201e' + z5 + '\\u201c\\n'\n"
            "        'Damit ist der Befund abgeschlossen.')\n"
            "p1, a1 = rr.politur_mit_zitatwache(text, [ev.to_dict()])\n"
            "k1 = kern(p1)\n"
            # 2: die vom Harness selbst gebaute Belegzeile
            "zeile = '> **Beleg:** \\u201e' + z0 + '\\u201c \\u00b7 Dokument `' + r0['file'] + '`'\n"
            "s2, e2 = rr.strike_unsupported_quotes(zeile, belege)\n"
            # 3: gerades Anfuehrungszeichen in den ersten zwoelf Zeichen
            "FAB = 'Die Regierung hat den Notstand fuer alle Buerger ausgerufen'\n"
            "drei = {}\n"
            "for pre in ('ab\" ', 'Es muss \" '):\n"
            "    s3, e3 = rr.strike_unsupported_quotes(\n"
            "        'Beleg: \\u201e' + pre + FAB + '.\\u201c', [])\n"
            "    drei[pre.strip()] = {'entfernt': len(e3), 'fabrikat': FAB[:20] in s3}\n"
            # Wie oft das Praefix im Korpus wirklich vorkommt
            "probe = tw.run_cqlf_query_tool(query='cql:[word=\".*\"]', sample=2000,\n"
            "                               seed=5, limit=1000)\n"
            "vorne = sum(1 for r in probe['rows']\n"
            "            if '\"' in (r['left'] + ' ' + r['kw'] + ' ' + r['right'])[:12])\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
            "  'eins': {'262': '262' in k1, '683': '683' in k1,\n"
            "           'zweiter_beleg': z5[:25] in k1, 'ann': [x.get('claim_id') for x in a1]},\n"
            "  'zwei': {'entfernt': len(e2), 'unveraendert': s2 == zeile},\n"
            "  'drei': drei, 'praefix_im_korpus': vorne,\n"
            "  'zeilen_probe': len(probe['rows'])}))\n"
        )

    def test_ein_unpaariges_anfuehrungszeichen_frisst_nicht_die_antwort(self):
        """Ein vergessenes schliessendes Anfuehrungszeichen ist der
        haeufigste Modellfehler ueberhaupt.

        Der mehrzeilige Zweitlauf paarte es ueber beliebig viele Zeilen mit
        dem naechsten schliessenden und behandelte alles dazwischen als EIN
        Zitat. Gemessen blieben von einer Antwort mit zwei echten Belegen
        und vier gepruefen Zahlen zwei Saetze uebrig -- und die Annotation
        meldete EIN entferntes Zitat, waehrend zwei gedeckte Belege und
        zwei geprueft-numerische Saetze verschwanden.
        """
        m = self._lauf()["eins"]
        assert m["262"] is True, m
        assert m["683"] is True, m
        assert m["zweiter_beleg"] is True, m

    def test_die_eigene_belegzeile_des_harness_bleibt_stehen(self):
        """``> **Beleg:** „<Korpuszeile>“ · Dokument `<id>`` ist kein
        Modelltext, sondern der deterministische Renderer.

        Der Blockzitat-Zweig verschlang die GANZE Zeile als Zitatinhalt.
        Die Woerter "Beleg" und "Dokument" und die Dokument-ID stehen in
        keiner Belegzeile, also galt sie als ungedeckt und wurde
        vollstaendig durch den Platzhalter ersetzt. Derselbe Commit hatte
        diese Klasse fuer Code- und Kursivspannen ausdruecklich erkannt und
        abgesichert, den Blockzitat-Zweig aber ohne Vorpruefung gelassen.
        """
        m = self._lauf()["zwei"]
        assert m["entfernt"] == 0, m
        assert m["unveraendert"] is True, m

    @pytest.mark.parametrize("praefix", ['ab"', 'Es muss "'])
    def test_ein_gerades_zitatzeichen_vorne_oeffnet_kein_loch(self, praefix):
        """Das gerade Anfuehrungszeichen durfte eine „-Spanne SCHLIESSEN.

        Stand es in den ersten zwoelf Zeichen, lehnte die Wache die Spanne
        als zu kurz ab -- und der Scanner stand danach dahinter. Der
        restliche, beliebig lange Text bis zum schliessenden Zeichen wurde
        von keinem Zweig mehr erfasst und nie geprueft. Genau die Klasse
        "Fabrikat kommt durch", die derselbe Commit geschlossen hat.
        """
        m = self._lauf()
        d = m["drei"][praefix]
        assert d["entfernt"] == 1, d
        assert d["fabrikat"] is False, d

    def test_das_praefix_kommt_im_korpus_wirklich_vor(self):
        """Positive Klasse: das Loch ist nicht konstruiert."""
        m = self._lauf()
        assert m["zeilen_probe"] >= 500, m
        assert m["praefix_im_korpus"] >= 1, (
            "kein gerades Anfuehrungszeichen in den ersten zwoelf Zeichen -- "
            "dann prueft der Test darueber einen konstruierten Fall")
