"""Gate 11, Klasse A und C: Nenner, Stichprobe, Indexstand.

Sechs Befunde, alle am Testindex gemessen (2000 Dokumente, 56.191 Tokens,
683 split=test mit 18.761 Tokens).
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

_BENCH = os.environ.get("CANDYCONC_INDEX_PATH")
_WURZEL = Path(__file__).resolve().parents[2]


def _messen(skript: str) -> dict:
    """Ausserhalb pytest: tests/conftest.py stubbt candyconc_copilot."""
    r = subprocess.run(
        [sys.executable, "-c", skript], capture_output=True, text=True,
        cwd=str(_WURZEL), timeout=1800,
        env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""),
             "CANDYCONC_INDEX_PATH": _BENCH or ""})
    assert r.returncode == 0 and "<<<JSON>>>" in r.stdout, r.stderr[-700:]
    return json.loads(r.stdout.split("<<<JSON>>>", 1)[1])


_VORSPANN = (
    "import sys, json, asyncio; sys.path.insert(0,'src')\n"
    "from candyconc.services.backend import server as S\n"
    "from candyconc.services.backend.routes import analysis as A\n"
    "from candyconc.candyconc_copilot import tool_wrappers as tw, query_runtime as QR\n"
    "idx = S.get_corpus(None); QR._CORPUS_INDEX = idx\n"
    "S._require_user_access = lambda *a, **k: None\n"
)


@pytest.mark.skipif(not _BENCH, reason="Testindex nicht gesetzt")
class TestDieStichprobeIstKeinKorpuspraefix:
    """P1: ``sample=500`` meldete 500 und lieferte 50 -- als PRAEFIX.

    Die Ziehung ist positionssortiert, ``rows[:limit]`` lieferte deshalb den
    Korpusanfang und nannte ihn eine Stichprobe. Am Testindex gemessen::

        gemeldet    drawn 500, population 55550
        geliefert   50 Zeilen, Positionen 178..6123 von 56191
        volle Ziehung (limit=500)   Positionen 178..56174

    Wer "n=500, uniform, seed 7" berichtet, hatte 50 Zeilen aus den ersten
    elf Prozent des Positionsraums annotiert. Das Werkzeug hat kein
    ``offset``, der weggeschnittene Teil war unerreichbar.

    Eine gleichverteilte Teilziehung AUS der Ziehung ist wieder
    gleichverteilt, mit demselben Seed also reproduzierbar.
    """

    def _lauf(self):
        return _messen(
            _VORSPANN
            + "Q = 'cql:[word=\".*\"]'\n"
            "def zieh(**kw):\n"
            "    r = tw.run_cqlf_query_tool(query=Q, **kw)\n"
            "    p = [x['pos'] for x in r['rows']]\n"
            "    return {'zeilen': len(r['rows']), 'sample': r['sample'],\n"
            "            'min': min(p), 'max': max(p), 'pos': p, 'total': r['total']}\n"
            "raus = {'gedeckelt': zieh(sample=500, seed=7),\n"
            "        'voll': zieh(sample=500, seed=7, limit=500),\n"
            "        'klein': zieh(sample=30, seed=7),\n"
            "        'gleicher_seed': zieh(sample=500, seed=7)['pos'],\n"
            "        'anderer_seed': zieh(sample=500, seed=8)['pos']}\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps(raus))\n"
        )

    def test_die_gelieferte_menge_ist_kein_korpusanfang(self):
        m = self._lauf()
        g, v = m["gedeckelt"], m["voll"]
        # Die positive Klasse: die volle Ziehung spannt wirklich das ganze
        # Korpus. Ohne sie wuerde dieser Test nichts pruefen.
        assert v["max"] - v["min"] > 50_000, v
        # Und die gedeckelte Auswahl spannt es ebenso, statt im
        # Korpusanfang zu enden.
        assert g["max"] > 50_000, (
            "Die Auswahl endet bei Position %s -- das ist ein Praefix" % g["max"])
        assert g["max"] - g["min"] > 50_000, g

    def test_drawn_meldet_die_wirklich_gelieferten_zeilen(self):
        m = self._lauf()
        g = m["gedeckelt"]
        assert g["zeilen"] == g["sample"]["drawn"], g["sample"]
        assert g["sample"]["requested"] == 500, g["sample"]
        assert g["sample"]["population"] == 55550, g["sample"]

    def test_die_ungedeckelte_ziehung_bleibt_vollstaendig(self):
        m = self._lauf()
        v = m["voll"]
        assert v["zeilen"] == 500 and v["sample"]["drawn"] == 500, v["sample"]
        k = m["klein"]
        assert k["zeilen"] == 30 and k["sample"]["drawn"] == 30, k["sample"]

    def test_der_seed_bleibt_bestimmend(self):
        m = self._lauf()
        assert m["gleicher_seed"] == m["gedeckelt"]["pos"], "nicht reproduzierbar"
        assert m["anderer_seed"] != m["gedeckelt"]["pos"], "Seed ohne Wirkung"
        # Check the subset in its returned sample order rather than sorting
        # it by corpus position.
        voll = sorted(m["voll"]["pos"])
        assert m["gedeckelt"]["pos"] == [voll[i] for i in random.Random(7).sample(range(500), 50)]


@pytest.mark.skipif(not _BENCH, reason="Testindex nicht gesetzt")
class TestDerIndexstandVerlaesstKeineNahtRoh:
    """Der rohe Betreiberpfad trat ueber sechs Job-Runner aus.

    ``_corpus_cache_signature`` fuehrt ihn als ``<absoluter Pfad>@<mtime_ns>``.
    Jede synchrone Route hashte ihn bereits ueber
    ``routes/analysis._index_fingerprint``, die Job-Runner nicht -- und der
    Job-Weg ist der, den die Oberflaeche fuer NgramsTab, KeynessTab,
    CollocationsTab und WordSketchTab nimmt, deren Export
    ``# indexFingerprint: ...`` in die Datei schreibt.

    Zwischenzeitlich war es sogar schlechter als vorher: dieselbe Datei
    meldete an zwei Naehten ZWEI Werte fuer denselben Index.
    """

    def test_keine_rohe_aufrufstelle_bleibt(self):
        quelle = (_WURZEL / "src" / "candyconc" / "services" / "backend"
                  / "server.py").read_text(encoding="utf-8")
        roh = quelle.count("index_fingerprint=_corpus_cache_signature(")
        gehasht = quelle.count(
            "index_fingerprint=kurzer_indexstand(_corpus_cache_signature(")
        assert gehasht == 6, gehasht
        assert roh == 0, (
            "%s Job-Runner setzen den Indexstand weiter roh" % roh)

    def test_job_und_synchron_melden_byte_gleich(self):
        m = _messen(
            _VORSPANN
            + "import os, time\n"
            "from fastapi.testclient import TestClient\n"
            "from candyconc.services.backend import auth\n"
            "H = {'Authorization': 'Bearer ' + auth._issue_token('t')}\n"
            # EINE Ereignisschleife fuer die ganze Messung (P13).
            #
            # ``TestClient`` OHNE Kontextmanager oeffnet je Anfrage ein
            # eigenes Portal und baut dessen Schleife danach ab. Der
            # n-Gramm-Job laeuft aber als ``asyncio.create_task`` auf
            # ebendieser Schleife weiter, und ``asyncio.run`` cancelt beim
            # Abbau jeden noch laufenden Task. Solange der Job schneller
            # war als die Antwort, fiel das nicht auf. Unter Last war er
            # es nicht mehr: am 2026-09-01 blieb er bei ``progress=70``
            # stehen, der Unterprozess lief in sein 1800-Sekunden-Limit
            # und wurde per SIGKILL beendet, die Suite stand 30 Minuten.
            # Nachgestellt mit gesaettigtem Pool: Task ``cancelled=True``,
            # Schleife ``is_closed()``. Der Job steht dabei bei
            # ``progress=20`` in der Abschnittsschleife, nicht bei 70:
            # die 70 entsteht, wenn der Abbruch in den Sortierschritt
            # faellt, und wird in
            # ``tests/backend/test_analysis_job_termination_p13.py``
            # ausgezaehlt.
            #
            # Der Kontextmanager haelt EIN Portal ueber alle Anfragen, wie
            # uvicorn seine Schleife ueber alle Anfragen haelt. Gemessen
            # bei drei Sekunden blockiertem schweren Pool: 'done' nach
            # 0,1 s statt Stillstand.
            "with TestClient(S.app, raise_server_exceptions=False) as c:\n"
            " jid = c.post('/api/v1/analysis/ngrams/job', headers=H,\n"
            "    json={'corpus':'default','min_n':2,'max_n':2,'limit':5}).json()['job_id']\n"
            # EIN GEDECKELTES WARTEN, damit ein haengender Job als
            # Fehlschlag mit Diagnose endet und nicht als Stillstand.
            # Der Job rechnet allein 0,1 s, der Deckel liegt drei
            # Groessenordnungen darueber. Er ist eine Reissleine, kein
            # Zeitplan, und die Zusicherungen darunter bleiben
            # unveraendert.
            " _frist = time.time() + 120\n"
            " _st = {}\n"
            " while time.time() < _frist:\n"
            "    _st = c.get('/api/v1/analysis/jobs/' + jid, headers=H).json()\n"
            "    if _st.get('status') != 'running':\n"
            "        break\n"
            "    time.sleep(0.2)\n"
            " else:\n"
            "    sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
            "      'haenger': True, 'status': _st.get('status'),\n"
            "      'progress': _st.get('progress'), 'message': str(_st.get('message'))[:120]}))\n"
            "    raise SystemExit(0)\n"
            # Ein Job, der mit Fehler endet, ist KEIN bestandener Lauf.
            # Vor P13 verschwand dieser Fall im Stillstand.
            " if _st.get('status') != 'done':\n"
            "    sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
            "      'haenger': True, 'status': _st.get('status'),\n"
            "      'progress': _st.get('progress'), 'message': str(_st.get('error') or _st.get('message'))[:200]}))\n"
            "    raise SystemExit(0)\n"
            " job = (c.get('/api/v1/analysis/jobs/' + jid + '/rows', headers=H,\n"
            "    params={'limit':1}).json().get('method') or {}).get('indexFingerprint')\n"
            " sync = (c.get('/api/v1/analysis/dispersion', headers=H,\n"
            "    params={'term':'und'}).json().get('method') or {}).get('indexFingerprint')\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
            "  'job': job, 'sync': sync, 'heim': os.path.expanduser('~')}))\n"
        )
        assert not m.get("haenger"), (
            "Der n-Gramm-Job erreichte kein 'done'. Zuletzt: "
            f"status={m.get('status')!r} progress={m.get('progress')} "
            f"message={m.get('message')!r}."
        )
        assert m["job"] == m["sync"], m
        assert m["heim"] not in str(m["job"]), m
        assert "/" not in str(m["job"]), m
        assert len(str(m["job"])) == 12, m


@pytest.mark.skipif(not _BENCH, reason="Testindex nicht gesetzt")
class TestDerCollocatesJobRechnetGegenDieGeleseneMenge:
    """Der Job rechnete gegen das GANZE Korpus, die synchrone Route nicht.

    Gleicher Zaehler, verschiedener Nenner, und die RANGFOLGE kippt::

        synchron  target_total 18761, erwartet 1,10, chi2 43,08
        Job       target_total 56191, erwartet 0,57, chi2 96,21

    Der Job deklariert in demselben method-Block
    ``event_total_definition: anchor_count_times_scope_tokens`` und lieferte
    als scope tokens den Korpuswert, obwohl er 683 von 2000 Dokumenten
    gelesen hatte. Der Job-Weg ist der, den die Oberflaeche nimmt.
    """

    def _lauf(self):
        return _messen(
            _VORSPANN
            + "import numpy as np\n"
            "from fastapi.testclient import TestClient\n"
            "from candyconc.services.backend import auth\n"
            "from candyconc.core.meta_filters import where_dokumente\n"
            "H = {'Authorization': 'Bearer ' + auth._issue_token('t')}\n"
            "c = TestClient(S.app, raise_server_exceptions=False)\n"
            "W = 'cql:where(split=\"test\", [word=\"und\"])'\n"
            "sync = c.get('/api/v1/analysis/collocates', headers=H,\n"
            "    params={'term': W, 'limit': 3}).json()\n"
            # Die ROUTE selbst, nicht eine Nachbildung ihrer Herleitung.
            # Eine Vorfassung dieses Tests baute doc_ids hier per Hand
            # nach (_resolve_doc_ids_for_job plus where_dokumente) und
            # uebergab sie dem Runner. Damit haette sie den Fix auch dann
            # bestaetigt, wenn die Route den Schnitt gar nicht mehr macht:
            # geprueft wurde eine Kopie der Reparatur, nicht die Reparatur.
            # Jetzt faengt der Test die doc_ids ab, die die ROUTE dem
            # Runner uebergibt.
            "gefangen = {}\n"
            "_echt = S._run_collocates_job\n"
            "async def _fang(job_id, **kw):\n"
            "    gefangen['doc_ids'] = kw.get('doc_ids')\n"
            "    return await _echt(job_id, **kw)\n"
            "S._run_collocates_job = _fang\n"
            "async def lauf():\n"
            "    await A.analysis_collocates_job(payload={\n"
            "        'corpus':'default','term': W,'limit':3,'min_freq':0})\n"
            "    for _ in range(600):\n"
            "        if 'doc_ids' in gefangen: break\n"
            "        await asyncio.sleep(0.05)\n"
            "    doc_ids = gefangen.get('doc_ids')\n"
            "    job = S.analysis_jobs.create('collocates','default',{'term': W})\n"
            "    await _echt(job.job_id, corpus=None, term=W, collocate=None,\n"
            "        window=5, within_sentence=True, sort_by=None,\n"
            "        doc_ids=doc_ids, limit=3, min_freq=0)\n"
            "    erwartet = where_dokumente(idx, W)\n"
            "    return (S.analysis_jobs.get(job.job_id).result or {},\n"
            "            int(np.asarray(doc_ids).size) if doc_ids is not None else -1,\n"
            "            int(np.asarray(erwartet).size) if erwartet is not None else -1)\n"
            "res, route_docs, where_docs = asyncio.run(lauf())\n"
            "f = lambda rs: [{'word': r['word'], 'observed': r['observed'],\n"
            "                 'expected': round(float(r['expected']), 4)} for r in rs[:3]]\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
            "  'sync_total': sync['method']['target_total'], 'sync_rows': f(sync['rows']),\n"
            "  'job_total': res['method']['target_total'], 'job_rows': f(res['rows']),\n"
            "  'route_docs': route_docs, 'where_docs': where_docs}))\n"
        )

    def test_beide_naehte_nennen_denselben_nenner(self):
        m = self._lauf()
        assert m["sync_total"] == 18761, m
        assert m["job_total"] == m["sync_total"], m

    def test_die_route_selbst_schneidet_die_where_dokumente(self):
        """Der Kern: die ROUTE bildet die Grundgesamtheit, nicht der Test.

        Abgefangen wird das doc_ids-Argument, das
        ``analysis_collocates_job`` dem Runner uebergibt.
        """
        m = self._lauf()
        assert m["where_docs"] == 683, m
        assert m["route_docs"] == m["where_docs"], (
            "die Route uebergibt %r Dokumente, where() liefert %r"
            % (m["route_docs"], m["where_docs"]))

    def test_die_rangfolge_stimmt_ueberein(self):
        m = self._lauf()
        assert [r["word"] for r in m["job_rows"]] == [r["word"] for r in m["sync_rows"]], m
        assert m["job_rows"] == m["sync_rows"], m


@pytest.mark.skipif(not _BENCH, reason="Testindex nicht gesetzt")
class TestDasNetzNenntSeineGrundgesamtheit:
    """``collocation_network`` schraenkte ueber where() ein und schwieg.

    Das Nachbarwerkzeug ``collocate_stats`` meldete fuer dieselbe Abfrage
    ``scope: {level: docset, doc_count: 683}``, das Netz gar nichts --
    und Schweigen liest sich als Korpus. Der REST-``method``-Block
    deklarierte zugleich ``event_total_definition:
    anchor_count_times_scope_tokens`` und lieferte diese Groesse nirgends.
    """

    def _lauf(self):
        return _messen(
            _VORSPANN
            + "raus = {}\n"
            "for name, q in (('offen', 'cql:[word=\"und\"]'),\n"
            "                ('eng', 'cql:where(split=\"test\", [word=\"und\"])')):\n"
            "    cop = tw.collocation_network_tool(term=q)\n"
            "    rest = asyncio.run(A.analysis_collocation_network_get(term=q))\n"
            "    raus[name] = {'scope': cop.get('scope'),\n"
            "                  'rest_total': (rest.get('method') or {}).get('target_total'),\n"
            "                  'knoten': len(cop.get('nodes') or [])}\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps(raus))\n"
        )

    def test_die_eingeschraenkte_abfrage_nennt_docset_und_tokenzahl(self):
        m = self._lauf()
        assert m["eng"]["scope"]["level"] == "docset", m
        assert m["eng"]["scope"]["doc_count"] == 683, m
        assert m["eng"]["rest_total"] == 18761, m

    def test_die_offene_abfrage_nennt_das_korpus(self):
        m = self._lauf()
        assert m["offen"]["scope"]["level"] == "corpus", m
        assert m["offen"]["rest_total"] == 56191, m


@pytest.mark.skipif(not _BENCH, reason="Testindex nicht gesetzt")
class TestEineDispersionsleiterFuerBeideNaehte:
    """Zwei Leitern teilten sich das Wort ``fairly_even`` bei verschiedenen
    Grenzen, mit Richtungsumkehr::

        Term   DP       REST           Copilot
        .      0.3735   fairly_even    moderately_clustered
        ,      0.3909   fairly_even    moderately_clustered

    Ueber die 100 haeufigsten Woerter bekamen 100 von 100 verschiedene
    Etiketten. Die Dispersionsklassifikation ist genau das Kriterium, mit
    dem eine Fachperson entscheidet, ob ein Frequenzbefund korpusweit gilt.
    """

    def _lauf(self):
        return _messen(
            _VORSPANN
            + "RANG = {'even':0,'fairly_even':0,'fairly_clustered':1,'clustered':2,\n"
            "        'absent':-1,'moderately_clustered':1,'strongly_clustered':2}\n"
            "gegen = 0; n = 0; proben = {}\n"
            "for w in [r['word'] for r in tw.frequency_list_tool(top_n=100)['rows']]:\n"
            "    try:\n"
            "        rest = asyncio.run(A.analysis_dispersion(term=w))\n"
            "        cop = tw.dispersion_offsets_tool(term=w)\n"
            "    except Exception: continue\n"
            "    n += 1\n"
            "    if RANG.get(rest['classification'], 9) != RANG.get(cop['profile'], 9):\n"
            "        gegen += 1\n"
            "    if w in ('.', ',', 'und'):\n"
            "        proben[w] = {'dp': round(rest['dp'], 4),\n"
            "                     'rest': rest['classification'], 'cop': cop['profile']}\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps(\n"
            "    {'n': n, 'gegenlaeufig': gegen, 'proben': proben}))\n"
        )

    def test_keine_der_haeufigsten_woerter_bekommt_gegenlaeufige_etiketten(self):
        m = self._lauf()
        assert m["n"] >= 90, m
        assert m["gegenlaeufig"] == 0, m

    def test_das_band_der_richtungsumkehr_ist_zu(self):
        m = self._lauf()
        for w in (".", ","):
            p = m["proben"].get(w)
            if p is None:
                continue
            assert 0.35 <= p["dp"] < 0.5, p
            assert p["rest"] == "fairly_even" and p["cop"] == "fairly_even", p


@pytest.mark.skipif(not _BENCH, reason="Testindex nicht gesetzt")
class TestDerSpitzenreiterIstImmerGlobalAdressierbar:
    """``peak_partition`` wechselte unter ``where()`` still den Indexraum.

    Am Testindex::

        und                                n_documents 2000  peak 1527
        where(split="test",[word="und"])   n_documents  683  peak  519

    Globales Dokument 519 ist ``split=train`` und hat NULL Treffer der
    Abfrage. ``document_text(doc_id)`` liest immer global: wer den
    Spitzenreiter nachschlug, landete auf einem unbeteiligten Dokument, und
    kein Feld benannte den Unterschied.
    """

    def _lauf(self):
        return _messen(
            _VORSPANN
            + "a = tw.dispersion_offsets_tool(term='und')\n"
            "b = tw.dispersion_offsets_tool(term='cql:where(split=\"test\",[word=\"und\"])')\n"
            "meta = idx.fast_index.doc_metadata.get(b['peak_partition']) or {}\n"
            "txt = tw.document_text_tool(doc_id=b['peak_partition'])\n"
            "voll = txt.get('text') or txt.get('full_text') or ''\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
            "  'offen_docs': a['n_documents'], 'offen_peak': a['peak_partition'],\n"
            "  'eng_docs': b['n_documents'], 'eng_peak': b['peak_partition'],\n"
            "  'eng_peak_split': meta.get('split'),\n"
            "  'eng_peak_hat_treffer': ' und ' in (' ' + voll + ' ')}))\n"
        )

    def test_die_eingeschraenkte_spitze_ist_dieselbe_globale_id(self):
        m = self._lauf()
        assert m["eng_docs"] == 683 and m["offen_docs"] == 2000, m
        assert m["eng_peak"] == m["offen_peak"], m

    def test_das_spitzendokument_gehoert_zur_eingeschraenkten_menge(self):
        m = self._lauf()
        assert m["eng_peak_split"] == "test", (
            "Der Spitzenreiter liegt in %r statt in der gelesenen Menge"
            % (m["eng_peak_split"],))
        assert m["eng_peak_hat_treffer"] is True, m


@pytest.mark.skipif(not _BENCH, reason="Testindex nicht gesetzt")
class TestDerKontrastZeigtBeideRichtungen:
    """``ngram_contrast`` lieferte eine einseitige Rangliste mit Marker-Leck.

    Am Testindex, Top 100, gegen die REST-Schwester gemessen::

        Zeilen mit diff_per_million < 0      Copilot   0   REST  32
        Nicht-Analyst-N-Gramme in den Top100 Copilot  35   REST   0
        Ueberschneidung der Top 100                        65/100
        total / total_candidates             39472        29935

    ". |LBR|" lag auf Rang 3, waehrend ``query_count('cql:[word="|LBR|"]')``
    in derselben Sitzung 0 liefert: eine Antwort desselben Harness sagte,
    das Bigramm komme nicht vor, eine andere wies es als drittwichtigstes
    unterscheidendes Merkmal aus.

    Auf die Frage "was unterscheidet A von B" fehlte damit die halbe
    Antwort, und ``truncated: true`` sah nach "mehr desselben" aus statt
    nach "die Gegenrichtung fehlt".
    """

    def _lauf(self):
        return _messen(
            _VORSPANN
            + "dt = tw.create_docset_tool(meta_filters={'split':'test'})['docset_id']\n"
            "dr = tw.create_docset_tool(meta_filters={'split':'train'})['docset_id']\n"
            "cop = tw.ngram_contrast_tool(target_docset_id=dt, reference_docset_id=dr, limit=100)\n"
            "ti = S._doc_ids_from_meta(idx, {'split':'test'})\n"
            "ri = S._doc_ids_from_meta(idx, {'split':'train'})\n"
            "async def rest():\n"
            "    job = S.analysis_jobs.create('ngrams_diff','default',{})\n"
            "    await S._run_ngrams_diff_job(job.job_id, corpus=None, min_n=2, max_n=2,\n"
            "        target_doc_ids=ti, reference_doc_ids=ri, limit=100, min_freq=1)\n"
            "    return S.analysis_jobs.get(job.job_id).result or {}\n"
            "r = asyncio.run(rest())\n"
            "a = [x['ngram'] for x in cop['rows']]\n"
            "b = [(x.get('ngram') or x.get('token')) for x in r['rows']]\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps({\n"
            "  'reihenfolge_gleich': a == b,\n"
            "  'ueberschneidung': len(set(a) & set(b)),\n"
            "  'negativ_cop': sum(1 for x in cop['rows'] if x['diff_per_million'] < 0),\n"
            "  'negativ_rest': sum(1 for x in r['rows'] if (x.get('diff_per_million') or 0) < 0),\n"
            "  'marker': [x for x in a if '|LBR|' in x],\n"
            "  'lbr_count': tw.query_count_tool(query='cql:[word=\"|LBR|\"]')['total'],\n"
            "  'other_count': tw.query_count_tool(query='cql:[word=\"OTHER\"]')['total'],\n"
            "  'total_cop': cop['total'],\n"
            "  'total_rest': r.get('total_candidates') or r.get('total')}))\n"
        )

    def test_die_gegenrichtung_steht_in_der_liste(self):
        m = self._lauf()
        # Positive Klasse: die REST-Schwester fuehrt sie wirklich.
        assert m["negativ_rest"] >= 20, m
        assert m["negativ_cop"] == m["negativ_rest"], m

    def test_kein_indexmarker_in_der_rangliste(self):
        m = self._lauf()
        # Positive Klasse: der Marker ist im Korpus nicht zaehlbar, ein
        # echtes Wort wie OTHER dagegen schon -- der Filter darf also nicht
        # einfach alles Ungewoehnliche streichen.
        assert m["lbr_count"] == 0, m
        assert m["other_count"] > 0, m
        assert m["marker"] == [], m

    def test_beide_naehte_liefern_dieselbe_reihenfolge(self):
        m = self._lauf()
        assert m["ueberschneidung"] == 100, m
        assert m["reihenfolge_gleich"] is True, m
        assert m["total_cop"] == m["total_rest"], m


@pytest.mark.skipif(not _BENCH, reason="Testindex nicht gesetzt")
class TestGleichstaendeEntscheidetNichtDieMengenreihenfolge:
    """Der Docstring versprach Byte-Gleichheit, die Gleichstandsregel fehlte.

    ``_ngram_rows`` waehlte mit ``heapq.nlargest(key=freq)``, die REST-Route
    mit ``heapq.nsmallest(key=(-freq, token_ids))``. Bei Gleichstand
    entschied damit die Iterationsreihenfolge einer Menge, und das ist kein
    Forschungsergebnis: am Testindex tauschten die Raenge 3 und 4
    ("das ist" und "fuer die", beide freq 38), im Test-Split war sogar
    Rang 10 ein anderes Bigramm.
    """

    def _lauf(self):
        return _messen(
            _VORSPANN
            + "dt = tw.create_docset_tool(meta_filters={'split':'test'})['docset_id']\n"
            "raus = {}\n"
            "for name, kwc, kwr in (('korpus', {}, {}),\n"
            "                       ('docset', {'docset_id': dt}, {'docset_id': dt})):\n"
            "    cop = tw.ngram_frequency_tool(min_n=2, max_n=2, limit=10, **kwc)\n"
            "    rest = asyncio.run(A.analysis_ngrams(payload={'corpus':'default',\n"
            "        'min_n':2,'max_n':2,'limit':10,'min_freq':1, **kwr}))\n"
            "    a = [(r['ngram'], r['freq']) for r in cop['rows']]\n"
            "    b = [(r.get('ngram') or r.get('token'), r.get('freq')) for r in rest['rows']]\n"
            "    raus[name] = {'gleich': a == b, 'cop': a[:4], 'rest': b[:4],\n"
            "                  'gleichstaende': len(a) - len({f for _, f in a})}\n"
            "sys.stdout.write('<<<JSON>>>' + json.dumps(raus))\n"
        )

    @pytest.mark.parametrize("bereich", ["korpus", "docset"])
    def test_die_liste_ist_byte_gleich_zur_rest_route(self, bereich):
        m = self._lauf()
        assert m[bereich]["gleich"] is True, m[bereich]

    def test_es_gibt_ueberhaupt_gleichstaende(self):
        # Positive Klasse: ohne Gleichstand in den Top 10 wuerde die
        # Gleichstandsregel nichts entscheiden und der Test nichts pruefen.
        m = self._lauf()
        assert m["korpus"]["gleichstaende"] >= 1, m["korpus"]
