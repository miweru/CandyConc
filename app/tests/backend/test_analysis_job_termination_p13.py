"""P13: ein Analysejob, dessen Task endet, bleibt nicht 'running'.

Gemessen am 2026-09-01: ``test_gate11_denominator_and_sample`` stand ueber
30 Minuten bei ``progress=70 'Ngram Ergebnisse werden sortiert'``. Ein
Stapelauszug zeigte die Threads des schweren Pools untaetig in
``Queue.get``, es wurde also gar nicht mehr gerechnet.

Die Ursache liegt nicht im Sortierschritt, sondern in der Lebensdauer des
Tasks. ``asyncio.CancelledError`` ist seit Python 3.8 keine
``Exception``, das ``except Exception`` am Fuss jedes ``_run_*_job``
faengt sie also nicht, und beim Abbau einer Ereignisschleife cancelt
``asyncio.run`` jeden noch laufenden Task. Danach setzte niemand mehr
einen Endzustand.

Nachgestellt mit gesaettigtem ``_HEAVY_SCAN_EXECUTOR`` (drei Sekunden
blockiert, gemessene Rechenzeit des Jobs 0,1 s): der Task war
``cancelled=True``, seine Schleife ``is_closed()``, der Job dennoch
'running'.

WO der Job stehen bleibt, haengt am Aufbau, und beide Zahlen sind hier
getrennt ausgezaehlt (gemessen 2026-09-02, je ohne die Reparatur):

* gesaettigter Pool -> ``progress=20 'Ngram Zaehler werden aufgebaut'``.
  Der Task haengt im ``await`` der Abschnittsschleife (server.py:6899),
  nicht im Sortierschritt.
* Abbruch im Sortierschritt -> ``progress=70 'Ngram Ergebnisse werden
  sortiert'``. server.py:6912 setzt die 70, und der naechste ``await``
  steht erst 49 Zeilen spaeter in server.py:6961,
  ``await asyncio.to_thread(idx.docset_token_count, doc_ids)``. Genau
  dort landet die ``CancelledError``, und genau das war das gemeldete
  Bild. ``TestDerAbbruchImSortierschritt`` zaehlt diesen Fall aus.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time

import pytest

from candyconc.services.backend import analysis_jobs

_BENCH = os.environ.get("CANDYCONC_INDEX_PATH")

# Diagnosedeckel, KEIN Zeitplan. Der Job rechnet gemessen 0,1 s, und der
# gesaettigte Pool wird nach 3 s freigegeben. Greift der Deckel, hat der
# Job keinen Endzustand erreicht, und das ist der Befund.
_DECKEL_S = 60.0


@pytest.fixture(autouse=True)
def _eigene_jobs():
    analysis_jobs._JOBS.clear()
    yield
    analysis_jobs._JOBS.clear()


class TestEinEndenderTaskHinterlaesstEinenEndzustand:
    def _abgebrochener_task(self, job_id: str) -> None:
        """Ein Task, der abgebrochen wird, waehrend seine Schleife stirbt."""

        async def _lauf() -> None:
            analysis_jobs.update(
                job_id, progress=70, message="Ngram Ergebnisse werden sortiert",
                status="running")
            await asyncio.sleep(3600)

        async def _haupt() -> None:
            task = asyncio.ensure_future(_lauf())
            analysis_jobs.attach_task(job_id, task)
            # Bis zur ersten Meldung laufen lassen, dann die Schleife
            # abbauen -- wie ``asyncio.run`` es beim Portalabbau tut.
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        asyncio.run(_haupt())

    def test_der_job_endet_terminal_statt_in_running_zu_stehen(self) -> None:
        job = analysis_jobs.create("ngrams", "demo", {})
        self._abgebrochener_task(job.job_id)

        gespeichert = analysis_jobs.get(job.job_id)
        assert gespeichert.task.cancelled(), "Vorbedingung: der Task bricht ab"
        assert gespeichert.status == "error", (
            "Der Job blieb in %r stehen, obwohl sein Task beendet ist"
            % gespeichert.status)

    def test_die_meldung_bewahrt_was_erreicht_wurde(self) -> None:
        job = analysis_jobs.create("ngrams", "demo", {})
        self._abgebrochener_task(job.job_id)

        gespeichert = analysis_jobs.get(job.job_id)
        # Ein Abbruch, der progress auf 100 setzt und die letzte Meldung
        # ueberschreibt, zerstoert auch die Aufzeichnung, dass gearbeitet
        # wurde. Genau die fehlte am 2026-09-01.
        assert gespeichert.progress == 70, gespeichert.progress
        assert "abgebrochen" in (gespeichert.error or ""), gespeichert.error
        assert "progress=70" in (gespeichert.error or ""), gespeichert.error
        assert "Ngram Ergebnisse werden sortiert" in (gespeichert.error or "")
        assert analysis_jobs.snapshot(job.job_id)["progress"] == 70

    def test_der_lauschende_strom_bekommt_sein_endereignis(self) -> None:
        """``routes/copilot_ws`` und der SSE-Strom warten auf ein Endereignis."""

        job = analysis_jobs.create("ngrams", "demo", {})
        gesehen: list[str] = []

        async def _haupt() -> None:
            async def _lauf() -> None:
                analysis_jobs.update(
                    job.job_id, progress=70,
                    message="Ngram Ergebnisse werden sortiert", status="running")
                await asyncio.sleep(3600)

            async def _lauschen() -> None:
                async for ereignis in analysis_jobs.stream(job.job_id):
                    gesehen.append(str(ereignis.get("status")))

            lauscher = asyncio.ensure_future(_lauschen())
            await asyncio.sleep(0)
            task = asyncio.ensure_future(_lauf())
            analysis_jobs.attach_task(job.job_id, task)
            await asyncio.sleep(0)
            task.cancel()
            try:
                await asyncio.wait_for(lauscher, timeout=_DECKEL_S)
            except asyncio.TimeoutError:  # pragma: no cover - der Befund
                lauscher.cancel()

        asyncio.run(_haupt())

        assert gesehen and gesehen[-1] in {"error", "done", "cancelled"}, (
            "Der Strom endete nie, zuletzt gesehen: %r" % (gesehen or None))


@pytest.mark.skipif(not _BENCH, reason="Testindex nicht gesetzt")
class TestDerNgrammJobUeberDieRoute:
    """Derselbe Befund am echten n-Gramm-Job, ueber die HTTP-Naht.

    ``TestClient`` ohne Kontextmanager oeffnet je Anfrage ein eigenes
    Portal und baut dessen Ereignisschleife danach wieder ab. Ist der
    schwere Pool belegt, ist der Job zu diesem Zeitpunkt noch nicht
    fertig und wird gecancelt -- genau die Lage der sechs parallelen
    Agenten.

    Dieser Aufbau haelt den Job in der Abschnittsschleife an, also bei
    ``progress=20 'Ngram Zaehler werden aufgebaut'`` (gemessen ohne die
    Reparatur am 2026-09-02). Die 70 des gemeldeten Befundes gehoert
    nicht hierher, sondern in ``TestDerAbbruchImSortierschritt``. Die
    Zusicherung unten prueft den Endzustand, nicht die Zahl.
    """

    def test_der_gecancelte_ngramm_job_bleibt_nicht_running(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastapi.testclient import TestClient

        from candyconc.services.backend import auth, executors
        from candyconc.services.backend import server as S

        S.get_corpus(None)
        # ueber monkeypatch, damit die Zugangspruefung nach diesem Test
        # wieder scharf ist. Eine Zuweisung an das Modul hielt sie im
        # vollen Suitenlauf dauerhaft offen und riss sieben fremde Tests
        # in tests/backend mit.
        monkeypatch.setattr(S, "_require_user_access", lambda *a, **k: None)

        frei = threading.Event()
        for _ in range(executors._HEAVY_SCAN_WORKERS):
            executors._HEAVY_SCAN_EXECUTOR.submit(frei.wait)
        loesen = threading.Timer(3.0, frei.set)
        loesen.start()
        try:
            kopf = {"Authorization": "Bearer " + auth._issue_token("t")}
            client = TestClient(S.app, raise_server_exceptions=False)
            job_id = client.post(
                "/api/v1/analysis/ngrams/job", headers=kopf,
                json={"corpus": "default", "min_n": 2, "max_n": 2, "limit": 5},
            ).json()["job_id"]

            frist = time.time() + _DECKEL_S
            stand: dict = {}
            while time.time() < frist:
                stand = client.get(
                    "/api/v1/analysis/jobs/" + job_id, headers=kopf).json()
                if stand.get("status") != "running":
                    break
                time.sleep(0.1)
        finally:
            loesen.cancel()
            frei.set()

        assert stand.get("status") != "running", (
            "Der n-Gramm-Job blieb in 'running' stehen. Zuletzt: "
            "progress=%s message=%r" % (stand.get("progress"), stand.get("message")))
        assert stand.get("error"), stand


@pytest.mark.skipif(not _BENCH, reason="Testindex nicht gesetzt")
class TestDerAbbruchImSortierschritt:
    """Die 70 des Befundes, ausgezaehlt statt behauptet.

    Der gesaettigte Pool erzeugt sie NICHT: dort haengt der Job im
    ``await`` der Abschnittsschleife bei ``progress=20``. Die 70 setzt
    ``server.py:6912``, und der naechste ``await`` steht erst 49 Zeilen
    weiter in ``server.py:6961``,
    ``asyncio.to_thread(idx.docset_token_count, doc_ids)``. Faellt der Schleifenabbau in dieses Fenster, landet die
    ``CancelledError`` dort, und der Job stand vor der Reparatur fuer
    immer bei 70 'Ngram Ergebnisse werden sortiert'.

    Deterministisch statt gewuerfelt: der Task wird genau dann
    abgebrochen, wenn der Job die 70 meldet, also im offenen Fenster
    zwischen der Meldung und dem naechsten ``await``. Denselben Abbruch
    loest im Betrieb der Schleifenabbau aus. Ihn hier nachzuspielen
    bliebe ein Rennen: laesst man die Schleife nach der Meldung
    abbauen, gewinnt oft der Job und endet 'done' (so gemessen am
    2026-09-02), und mit blossem ``TestClient`` traf das Rennen den
    Zustand in drei Laeufen einmal. Die Quelle des Abbruchs ist
    dieselbe ``Task.cancel``, die ``asyncio.run`` beim Abbau aufruft.
    """

    def _lauf_bis_zum_sortierschritt(self, job_id: str, ohne_rueckruf: bool) -> None:
        from candyconc.services.backend import server as S

        idx = S.get_corpus(None)
        # Die Herleitung der ROUTE, keine Nachbildung von Hand.
        doc_ids = S._resolve_doc_ids_for_job(idx, None, None)
        echt_update = analysis_jobs.update

        async def _haupt() -> None:
            halter: dict[str, asyncio.Task] = {}

            def _update(jid: str, **kw: object) -> None:
                echt_update(jid, **kw)
                if jid == job_id and kw.get("progress") == 70 and "task" in halter:
                    # Der Abbruch wird erst am naechsten ``await``
                    # zugestellt, und der steht 49 Zeilen spaeter in
                    # ``asyncio.to_thread`` (server.py:6961). Bis dahin
                    # rechnet der Sortierschritt zu Ende, genau wie beim
                    # Schleifenabbau im Betrieb.
                    halter["task"].cancel()

            analysis_jobs.update = _update  # type: ignore[assignment]
            try:
                task = asyncio.ensure_future(
                    S._run_ngrams_job(
                        job_id, corpus=None, doc_ids=doc_ids,
                        min_n=2, max_n=2, limit=5))
                halter["task"] = task
                if ohne_rueckruf:
                    analysis_jobs.get(job_id).task = task
                else:
                    analysis_jobs.attach_task(job_id, task)
                # ``wait`` traegt die ``CancelledError`` des Tasks NICHT
                # weiter, der Diagnosedeckel bleibt damit wirksam.
                await asyncio.wait({task}, timeout=_DECKEL_S)
            finally:
                analysis_jobs.update = echt_update  # type: ignore[assignment]

        asyncio.run(_haupt())

    def test_die_gemeldete_70_entsteht_hier_und_endet_terminal(self) -> None:
        """Beide Arme in EINER Probe.

        Arm 1 haengt den Rueckruf NICHT an und zaehlt aus, woher die
        gemeldete Zahl kommt: 'running' bei ``progress=70 'Ngram
        Ergebnisse werden sortiert'``, genau das Bild vom 2026-09-01.
        Arm 2 nimmt dieselbe Naht, wie sie im Betrieb steht. Ohne die
        Reparatur faellt Arm 2, die Probe ist also rot ohne sie, und
        Arm 1 haelt fest, dass der Aufbau die 70 wirklich erzeugt.
        """

        ohne = analysis_jobs.create("ngrams", "default", {})
        self._lauf_bis_zum_sortierschritt(ohne.job_id, ohne_rueckruf=True)
        roh = analysis_jobs.get(ohne.job_id)
        assert roh.task is not None and roh.task.cancelled(), (
            "Vorbedingung: der Task bricht im Sortierschritt ab")
        assert roh.status == "running", roh.status
        assert roh.progress == 70, roh.progress
        assert roh.message == "Ngram Ergebnisse werden sortiert", roh.message

        mit = analysis_jobs.create("ngrams", "default", {})
        self._lauf_bis_zum_sortierschritt(mit.job_id, ohne_rueckruf=False)
        gespeichert = analysis_jobs.get(mit.job_id)
        assert gespeichert.task is not None and gespeichert.task.cancelled()
        assert gespeichert.status == "error", (
            "Der Job blieb in %r stehen. Zuletzt: progress=%s message=%r"
            % (gespeichert.status, gespeichert.progress, gespeichert.message))
        # Progress und letzte Meldung bleiben stehen: sie sind die
        # Aufzeichnung, wie weit gerechnet wurde.
        assert gespeichert.progress == 70, gespeichert.progress
        assert "progress=70" in (gespeichert.error or ""), gespeichert.error
        assert "Ngram Ergebnisse werden sortiert" in (gespeichert.error or ""), (
            gespeichert.error)
