"""Die Zitatwache liess sich VOM MODELL aushebeln.

Der schwerste Fund der Kampagne, gefunden im siebten Gate.

``make_evidence_item`` schreibt die Werkzeugargumente des Modells in
dieselbe Flaeche wie die Korpusbelege: ``analysis_input=<Begriff>`` und
``tool_args={...}``. Die Werkzeuge spiegeln ihre Argumente ausserdem in
der Ausgabe zurueck, sodass ``query=<Phrase>`` ueber ``raw_surface``
noch einmal hereinkommt. ``evidenz_belegzeilen`` gab alles davon an
``zitat_ist_belegt`` weiter.

Damit genuegte EIN Werkzeugaufruf mit der erfundenen Phrase als
Suchbegriff, um sie zur Belegzeile des Turns zu machen. Der Aufruf durfte
NULL Treffer liefern. Gemessen auf dem Hauptpfad, gleicher Antworttext,
gleiche Wache, einziger Unterschied das Werkzeugargument:

    query="und"        -> Im Korpus steht die Passage [Beleg fehlt].
    query="<Fabrikat>" -> Im Korpus steht die Passage "der jungen Maenner
                          sind keine Fluechtlinge. Sie sind
                          ruecksichtslose Invasoren."

Und danach fielen ALLE Wachen gleichzeitig, weil sie dieselbe Quelle
nutzen: die Endpolitur-Landung, die pausierende Landung, die
Kontrollrahmen, _ra_emit_recovery, _ra_activate_fail_closed_grounding und
der Verifier-Skip-Pfad. Eine Reparatur an einer Landung mehr haette
nichts geholfen: die Wache selbst war vergiftet.

Drei Flaechen tragen die Eingabe, und die ersten beiden Fassungen dieser
Reparatur schlossen je eine davon. Die Regel ist jetzt allgemein: eine
Zeile der Gestalt ``name=<wert>``, deren Wert in der Abfrage des Modells
steht, wiederholt die Eingabe und belegt nichts. KWIC-Zeilen tragen diese
Gestalt nicht und bleiben erhalten, auch wenn die Abfrage genau den Text
enthaelt, den der Korpus wirklich fuehrt.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_BENCH = os.environ.get("CANDYCONC_INDEX_PATH")
_WURZEL = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    not _BENCH or not Path(_BENCH).exists(),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)

_FABRIKAT = "die jungen Maenner sind hier alle Invasoren"


def _lauf(skript: str) -> dict:
    """Sauberer Unterprozess: tests/conftest.py stubbt candyconc_copilot."""
    import json
    import subprocess
    import sys

    voll = f"import sys, json\nsys.path.insert(0, {str(_WURZEL / 'src')!r})\n" + skript
    r = subprocess.run(
        [sys.executable, "-c", voll], capture_output=True, text=True,
        cwd=str(_WURZEL), timeout=900,
        env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""),
             "CANDYCONC_INDEX_PATH": _BENCH or ""})
    assert r.returncode == 0 and "<<<JSON>>>" in r.stdout, (
        f"Messlauf gescheitert (rc={r.returncode}): {r.stderr[-600:]}")
    return json.loads(r.stdout.split("<<<JSON>>>", 1)[1])


_KOPF = (
    "from candyconc.services.backend import server as srv\n"
    "from candyconc.candyconc_copilot import query_runtime as qr\n"
    "from candyconc.candyconc_copilot import recipe_runtime as rr\n"
    "from candyconc.candyconc_copilot import tool_wrappers as tw\n"
    "from candyconc.candyconc_copilot.grounding_facts import make_evidence_item\n"
    "assert 'tests' not in str(getattr(tw, '__file__', '')), 'Stub'\n"
    "qr._CORPUS_INDEX = srv.get_corpus(None)\n"
    f"F = {_FABRIKAT!r}\n"
)


@pytest.mark.parametrize(
    "tool,args,output",
    [
        ("run_cqlf_query", "{'query': F}",
         "{'status':'success','query':F,'total':0,'rows':[]}"),
        ("document_search", "{'term': F}", "{'status':'success','rows':[]}"),
        ("query_count", "{'query': '\"' + F + '\"'}",
         "{'status':'success','total':0}"),
    ],
)
def test_die_eigene_suche_deckt_das_fabrikat_NICHT(tool, args, output):
    """Der Befund selbst, ueber drei Werkzeuge und drei Flaechen."""
    e = _lauf(
        _KOPF
        + f"ev = make_evidence_item(item_id='e', tool={tool!r}, tool_call_id='c',\n"
        f"    query={args}, output={output}, analysis_family='x').to_dict()\n"
        "t, _ = rr.politur_mit_zitatwache('Im Korpus steht \"' + F + '\".', [ev])\n"
        "prosa = t.split('###')[0]\n"
        "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
        "  'fabrikat_in_der_prosa': F in prosa,\n"
        "  'beleg_fehlt': '[Beleg fehlt]' in prosa}))\n"
    )
    assert e["fabrikat_in_der_prosa"] is False, e
    assert e["beleg_fehlt"] is True, e


def test_ein_ECHTER_korpusbeleg_bleibt_erhalten():
    """Eine Wache, die alles streicht, besteht jeden Fabrikationstest.

    Der Gegenbeleg laeuft ueber eine ECHTE KWIC-Ausgabe am Testindex,
    also ueber genau die Zeilen, die eine Antwort zitieren wuerde.
    """
    e = _lauf(
        _KOPF
        + "out = tw.run_cqlf_query_tool(query='Invasoren')\n"
        "ev = make_evidence_item(item_id='e', tool='run_cqlf_query',\n"
        "    tool_call_id='c', query={'query': 'Invasoren'}, output=out,\n"
        "    analysis_family='x').to_dict()\n"
        "z = (out.get('rows') or [{}])[0]\n"
        "echt = ' '.join((str(z.get('left','')) + ' ' + str(z.get('kw','')) +\n"
        "                 ' ' + str(z.get('right',''))).split())\n"
        "t, _ = rr.politur_mit_zitatwache('Im Korpus steht \"' + echt + '\".', [ev])\n"
        "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
        "  'treffer': int(out.get('total') or 0),\n"
        "  'kernwort_erhalten': 'Invasoren' in t.split('###')[0],\n"
        "  'beleg_fehlt': '[Beleg fehlt]' in t.split('###')[0]}))\n"
    )
    assert e["treffer"] > 0, "die positive Klasse fehlt: kein echter Treffer"
    assert e["kernwort_erhalten"] is True, e
    assert e["beleg_fehlt"] is False, e


def test_die_belegzeilen_fuehren_die_modelleingabe_nicht_mehr():
    """Die Quelle, nicht nur die Wirkung."""
    e = _lauf(
        _KOPF
        + "ev = make_evidence_item(item_id='e', tool='document_search',\n"
        "    tool_call_id='c', query={'term': F},\n"
        "    output={'status':'success','rows':[]}, analysis_family='x').to_dict()\n"
        "z = rr.evidenz_belegzeilen([ev])\n"
        "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
        "  'zeilen_mit_fabrikat': [x for x in z if F in x],\n"
        "  'deckt': rr.zitat_ist_belegt(F, z)}))\n"
    )
    assert e["zeilen_mit_fabrikat"] == [], e
    assert e["deckt"] is False, e


def test_verschachtelte_prosa_in_steps_und_options_wird_bewacht():
    """Die zweite blockierende Luecke desselben Gates.

    ``steps`` und ``options`` tragen laut Systemprompt OBJEKTE. Die Wache
    betrat die Liste und liess jedes dict darin unberuehrt, also genau
    dort, wo die Prosa steht.
    """
    e = _lauf(
        _KOPF
        + "r = {'question': 'Welche?',\n"
        "     'options': [{'label': '\"' + F + '\"', 'id': 'a'}],\n"
        "     'steps': [{'description': 'Zeige \"' + F + '\"', 'n': 1}],\n"
        "     'payload': {'query': '\"' + F + '\"'}, 'actionType': 'query_count'}\n"
        "s = rr.kontrollrahmen_bewacht(r, [{'grounding_surface': ['Etwas anderes.']}])\n"
        "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
        "  'option_bewacht': F not in str(s['options'][0]),\n"
        "  'step_bewacht': F not in str(s['steps'][0]),\n"
        "  'payload_unveraendert': s['payload'] == r['payload'],\n"
        "  'actiontype_unveraendert': s['actionType'] == 'query_count'}))\n"
    )
    assert e["option_bewacht"] is True, e
    assert e["step_bewacht"] is True, e
    # Und weiterhin KEINE Ausfuehrungsdaten anfassen.
    assert e["payload_unveraendert"] is True, e
    assert e["actiontype_unveraendert"] is True, e


@pytest.mark.parametrize(
    "name,tool,args,output",
    [
        ("Anfuehrungszeichen", "query_count",
         "{'query': '\"' + F + '\"'}", "{'status':'success','total':0}"),
        ("doppeltes_Leerzeichen", "document_search",
         "{'term': F.replace(' ', '  ', 1)}", "{'status':'success','rows':[]}"),
        ("CQL_JSON_Maskierung", "run_cqlf_query",
         "{'query': '[word=\"' + F + '\"]'}",
         "{'status':'success','query':'[word=\"' + F + '\"]','total':0,'rows':[]}"),
        ("laenger_als_512", "document_search",
         "{'term': F, 'notiz': 'x'*600}", "{'status':'success','rows':[]}"),
        ("Echo_in_der_Ausgabe", "run_cqlf_query",
         "{'query': F}", "{'status':'success','query':F,'total':0,'rows':[]}"),
        ("Fehlermeldung", "run_cqlf_query",
         "{'query': F}", "{'status':'error','message':'Ungueltig: ' + F}"),
    ],
)
def test_die_sieben_umgehungswege_der_zeichenketten_fassung(name, tool, args, output):
    """Warum die Wache jetzt an der HERKUNFT haengt, nicht am Text.

    Die erste Reparatur verglich Belegzeilen mit der Abfrage des Modells.
    Ein achtes Gate hat sechs Wege gemeldet, auf denen dieser Vergleich
    bricht, jeder davon reproduziert: ein Anfuehrungszeichen, ein
    doppeltes Leerzeichen, die JSON-Maskierung einer CQL-Abfrage, die
    512-Zeichen-Kuerzung von ``query_text``, das Echo der Argumente in der
    Werkzeugausgabe und die Fehlermeldung, die das Argument umformatiert
    zurueckgibt.

    ``make_evidence_item`` markiert die Eingabe jetzt beim Anlegen in
    ``eingabe_surface``, und ein gescheitertes Werkzeug traegt ueberhaupt
    keinen Beleg bei. Herkunft laesst sich nicht umformatieren.
    """
    e = _lauf(
        _KOPF
        + f"ev = make_evidence_item(item_id='e', tool={tool!r}, tool_call_id='c',\n"
        f"    query={args}, output={output}, analysis_family='x').to_dict()\n"
        "t, _ = rr.politur_mit_zitatwache('Im Korpus steht \"' + F + '\".', [ev])\n"
        "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
        "  'fabrikat_in_der_prosa': F in t.split('###')[0],\n"
        "  'eingabe_markiert': bool(ev.get('eingabe_surface'))}))\n"
    )
    assert e["fabrikat_in_der_prosa"] is False, (name, e)


def test_die_eingabe_wird_beim_anlegen_markiert():
    """Die Quelle der Reparatur, nicht nur ihre Wirkung."""
    e = _lauf(
        _KOPF
        + "ev = make_evidence_item(item_id='e', tool='document_search',\n"
        "    tool_call_id='c', query={'term': F},\n"
        "    output={'status':'success','rows':[]}, analysis_family='x').to_dict()\n"
        "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
        "  'eingabe': ev.get('eingabe_surface'),\n"
        "  'auch_in_grounding': [z for z in ev.get('grounding_surface') or []\n"
        "                        if z in (ev.get('eingabe_surface') or [])]}))\n"
    )
    assert any(_FABRIKAT in str(z) for z in e["eingabe"]), e
    # Sie bleibt im Modellkontext sichtbar, nur nicht als Beleg.
    assert e["auch_in_grounding"], e


@pytest.mark.parametrize(
    "tool,args",
    [
        ("collocate_stats", "{'term': F}"),
        ("collocate_stats", "{'term': F.replace(' ', '  ', 1)}"),
        ("run_cqlf_query", "{'query': 'cql:[word=\"' + F + '\"]'}"),
        ("document_search", "{'term': F}"),
        ("query_count", "{'query': '\"' + F + '\"'}"),
    ],
)
def test_ECHTE_werkzeuge_decken_das_fabrikat_nicht(tool, args):
    """Ueber die echten Werkzeuge am echten Index, nicht ueber Attrappen.

    Das achte Gate hat die Zeichenketten-Fassung mit sechs Wegen
    widerlegt, darunter zwei, die eine Herkunftsmarkierung allein nicht
    schliesst: ``effective_term`` bei ``collocate_stats`` (das Werkzeug
    spiegelt den Begriff in einem Feld zurueck, das keine Liste kannte)
    und die JSON-Maskierung einer CQL-Abfrage.

    Deshalb ist die Regel jetzt umgekehrt: fuer ein woertliches Zitat
    zaehlt NUR, was Korpusinhalt traegt. ``name=wert``-Skalare tun das
    nicht, ausser den wenigen, die selbst Korpustext fuehren (snippet,
    text, example, context, left, kw, right, match). Ein Werkzeug kann
    beliebig viele neue Echofelder bekommen, ohne die Wache zu oeffnen.
    """
    e = _lauf(
        _KOPF
        + f"out = getattr(tw, {tool!r} + '_tool')(**{args})\n"
        f"ev = make_evidence_item(item_id='e', tool={tool!r}, tool_call_id='c',\n"
        f"    query={args}, output=out, analysis_family='x').to_dict()\n"
        "t, _ = rr.politur_mit_zitatwache('Ein Beleg lautet: \"' + F + '\".', [ev])\n"
        "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
        "  'fabrikat': F in t.split('###')[0]}))\n"
    )
    assert e["fabrikat"] is False, (tool, e)


def test_skalare_kopfzeilen_decken_nie_ein_zitat():
    """Die Regel selbst, mit Gegenprobe fuer die inhaltstragenden Namen."""
    from candyconc.candyconc_copilot import recipe_runtime as rr

    for zeile in ("effective_term=ein erfundener Satz", "query=ein erfundener Satz",
                  "message=Ungueltig: ein erfundener Satz", "status=success"):
        assert rr._traegt_korpusinhalt(zeile) is False, zeile
    for zeile in ("snippet=ein echter Satz", "kw=Invasoren",
                  "rows[0] {'kw': 'Invasoren'}",
                  "Fluechtlinge . Sie sind ruecksichtslose Invasoren ."):
        assert rr._traegt_korpusinhalt(zeile) is True, zeile


@pytest.mark.parametrize(
    "tool,args,zitat_aus",
    [
        ("document_text", "{'doc_id': 0}",
         "' '.join(str(out.get('text','')).split()[:8])"),
        ("kwic_context", "{'pos': 1457}",
         "' '.join((str(out.get('left','')) + ' ' + str(out.get('kw','')) +"
         " ' ' + str(out.get('right',''))).split())"),
        ("run_cqlf_query", "{'query': 'Invasoren'}",
         "' '.join(' '.join(str((out.get('rows') or [{}])[0].get(k,''))"
         " for k in ('left','kw','right')).split())"),
        ("document_search", "{'term': 'Invasoren', 'top_n': 2}",
         "' '.join(str((out.get('rows') or [{}])[0].get('snippet','')).split()[:8])"),
    ],
)
def test_ECHTE_belege_werden_NICHT_gestrichen(tool, args, zitat_aus):
    """Die gefaehrlichere Richtung, und die, die niemandem auffaellt.

    Die Erlaubnisliste der inhaltstragenden Schluessel kannte in ihrer
    ersten Fassung weder ``text`` noch die KWIC-Felder auf oberster
    Ebene. Gemessen: ``document_text`` lieferte NULL Belegzeilen, jedes
    woertliche Volltext-Zitat waere gestrichen worden, und
    ``kwic_context`` verlor die zusammengesetzte Zeile, weil es
    left/kw/right nicht in ein Objekt legt.

    Dabei kam ein aelterer Defekt mit heraus: ``text`` stand auch in
    ``extract_raw_surface`` nicht auf der Namensliste. Ein Zitat aus dem
    Volltext eines Dokuments war damit IMMER unbelegt, seit es das
    Werkzeug gibt. Ein Konkordanzer, dem man den Dokumenttext zeigt, muss
    daraus zitieren duerfen.

    Eine Wache, die echte Belege entfernt, ist so schaedlich wie eine,
    die Fabrikate durchlaesst.
    """
    e = _lauf(
        _KOPF
        + f"out = getattr(tw, {tool!r} + '_tool')(**{args})\n"
        f"ev = make_evidence_item(item_id='e', tool={tool!r}, tool_call_id='c',\n"
        f"    query={args}, output=out, analysis_family='x').to_dict()\n"
        f"zitat = {zitat_aus}\n"
        "t, _ = rr.politur_mit_zitatwache('Es steht \"' + zitat + '\".', [ev])\n"
        "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
        "  'zitat': zitat,\n"
        "  'belegzeilen': len(rr.evidenz_belegzeilen([ev])),\n"
        "  'gestrichen': '[Beleg fehlt]' in t.split('###')[0]}))\n"
    )
    assert e["zitat"].strip(), f"{tool}: kein Zitat gewinnbar, der Test misst nichts"
    assert e["belegzeilen"] > 0, (tool, e)
    assert e["gestrichen"] is False, (tool, e)


def test_gepunktete_und_geklammerte_koepfe_decken_nichts():
    """Neunter Gate-Befund: der Kopf-Erkenner sah nur NACKTE name=-Koepfe.

    ``diagnostics.requested_fields=[...]`` rutschte durch, und
    ``metadata_values`` spiegelt einen FREI WAEHLBAREN Feldnamen woertlich
    zurueck. Damit deckte das Modell seine eigene Erfindung erneut selbst,
    ueber ein Werkzeug, das gar keinen Korpustext liefert.
    """
    from candyconc.candyconc_copilot.grounding_evidence import traegt_korpusinhalt

    kein_inhalt = [
        "message=x y z a b", "query=abc", "effective_term=x", "label=a b c d",
        "diagnostics.requested_fields=['x y z a']", "values.source=[1]",
        "value_count[source]=1", "relation[obj]={}", "rerank.method=bm25",
        "filtering.minScore=0.2", "method: ci_method=x", "status=success",
    ]
    inhalt = [
        "snippet=ein echter Satz", "kw=Invasoren", "sample.text=ein Satz",
        "text=ein Satz", "rows[0] {'kw': 'Invasoren'}", 'match[0]="Invasoren"',
        "Fluechtlinge . Sie sind ruecksichtslose Invasoren .",
    ]
    for zeile in kein_inhalt:
        assert traegt_korpusinhalt(zeile) is False, zeile
    for zeile in inhalt:
        assert traegt_korpusinhalt(zeile) is True, zeile


def test_metadata_values_deckt_keinen_erfundenen_feldnamen():
    """Derselbe Befund am Produktivpfad, mit einem frei gewaehlten Feld."""
    e = _lauf(
        "from candyconc.candyconc_copilot import recipe_runtime as rr\n"
        "from candyconc.candyconc_copilot.grounding_facts import make_evidence_item\n"
        "F = 'die frechen Wollmaeuse tanzen im Serverraum'\n"
        "out = {'status':'success','values':{},'diagnostics':{\n"
        "    'requested_fields':[F],'missing_requested_fields':[F]}}\n"
        "ev = make_evidence_item(item_id='e', tool='metadata_values',\n"
        "    tool_call_id='c', query={'fields':[F]}, output=out,\n"
        "    analysis_family='x').to_dict()\n"
        "t, _ = rr.politur_mit_zitatwache('Der Beleg lautet: \"' + F + '\".', [ev])\n"
        "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
        "  'fabrikat': F in t.split('###')[0]}))\n"
    )
    assert e["fabrikat"] is False, e
