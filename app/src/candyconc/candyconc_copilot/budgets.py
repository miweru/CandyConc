"""Bound transport retries without limiting analytical depth.

Tool planning is already bounded by ``max_steps`` and grounding repairs have
their own verifier budget. A second cap over all LLM calls would make those
independent protocols compete and can stop an exploratory turn before answer
synthesis. This module therefore controls only retries of the same failed
transport request.
"""

from __future__ import annotations

import time


# Semantic grounding repairs deliberately do not consume this budget.
TRANSPORT_RETRY_LIMIT = 2

# Do not begin another transport retry near an explicit turn deadline.
RETRY_MIN_TIME_FRACTION = 0.4

# Do not start the LLM grounding verifier without a real time reserve: below
# this fraction of the turn budget the deterministic reference path finalises
# the answer and the skip is annotated in the copilot.grounding event.
VERIFIER_MIN_TIME_FRACTION = 0.3


def _time_remaining_ok(
    started_at: float,
    max_time: float | None,
    fraction: float,
    now: float | None,
) -> bool:
    if max_time is None or max_time <= 0:
        return True
    ts = time.perf_counter() if now is None else float(now)
    remaining = float(max_time) - (ts - float(started_at))
    return remaining >= fraction * float(max_time)


def retry_time_remaining_ok(
    started_at: float,
    max_time: float | None,
    *,
    now: float | None = None,
) -> bool:
    """Return whether an identical failed request may be retried in time."""
    return _time_remaining_ok(
        started_at, max_time, RETRY_MIN_TIME_FRACTION, now
    )


# H11: Engine-Ausfall-Retries sind der letzte Rettungsanker eines Turns —
# die Erholung der bereits geladenen Engine dauert typischerweise 2-5s.
# Das 40%-Anteilstor (RETRY_MIN_TIME_FRACTION) verbot spaete Retries und
# liess Turns bei 65-80% Budgetverbrauch sterben (H10-Akzeptanz: 3 Turns).
# Fuer DIESE Fehlerklasse zaehlt die absolute Restzeit.
ENGINE_RETRY_MIN_SECONDS = 12.0


def engine_retry_time_ok(
    started_at: float,
    max_time: float | None,
    *,
    now: float | None = None,
) -> bool:
    """Darf ein Engine-Ausfall-Retry noch starten (absolute Restzeit)?"""
    if max_time is None or max_time <= 0:
        return True
    ts = time.perf_counter() if now is None else float(now)
    remaining = float(max_time) - (ts - float(started_at))
    return remaining >= ENGINE_RETRY_MIN_SECONDS


def verifier_time_remaining_ok(
    started_at: float,
    max_time: float | None,
    *,
    now: float | None = None,
) -> bool:
    """Return whether the LLM grounding verifier may still start.

    Mirrors the K1 transport pattern: without an explicit turn deadline the
    verifier always runs. With a deadline it only starts while at least
    ``VERIFIER_MIN_TIME_FRACTION`` of the budget remains, because a verifier
    that begins near the deadline reliably times out mid-protocol and turns a
    grounded partial answer into an empty timeout apology.
    """
    return _time_remaining_ok(
        started_at, max_time, VERIFIER_MIN_TIME_FRACTION, now
    )


# Estimated seconds for one synthesis and verification pair.
# This calibration includes the latency of the configured model service.
VERIFIER_RETRY_PAAR_SEKUNDEN = 22.0


def retry_budget_fuer_restzeit(
    started_at: float,
    max_time: float | None,
    *,
    confirmation_guarded: bool,
    retrieval_candidate_count: int,
    now: float | None = None,
) -> int:
    """Das Retry-Budget aus der RESTZEIT statt aus einer Konstante (P3.3).

    Bis hierher stand das Budget auf 6, bei Bestaetigungsdruck bis 8, und
    zwar unabhaengig davon, ob noch 90 Sekunden uebrig waren oder 9. Jeder
    Retry kostet ZWEI Roundtrips.

    Gemessen am 2026-08-17: die Finalisierung wird im Median nach 16,0
    Sekunden erreicht, das Verifier-Tor schliesst bei 84,0 (also bei
    ``max_time`` 120 und ``VERIFIER_MIN_TIME_FRACTION`` 0,3). Es bleiben
    rund 68 Sekunden, das reicht fuer zwei bis drei Paare. Ein Budget von 6
    bis 8 war damit KONSTRUKTIV UNERREICHBAR: die Zeitschranke laesst
    hoechstens die Haelfte zu, und die Restrunden enden nicht als geplante
    Landung, sondern als Abbruch mitten im Protokoll. Genau auf dieser
    Skip-Landung sind die drei erfundenen Zitate der Kampagne entstanden.

    Die Obergrenze bleibt unveraendert, das Budget kann durch diese
    Rechnung nur SINKEN, nie steigen. Und es faellt nie unter 1: wer den
    Verifier ueberhaupt startet, bekommt einen Versuch.
    """
    obergrenze = (
        min(8, max(6, int(retrieval_candidate_count) + 2))
        if confirmation_guarded
        else 6
    )
    if not max_time:
        return obergrenze
    jetzt = time.perf_counter() if now is None else now
    bis_zum_tor = (
        float(max_time) * (1.0 - VERIFIER_MIN_TIME_FRACTION)
        - (jetzt - float(started_at))
    )
    if bis_zum_tor <= 0.0:
        return 1
    passende_paare = int(bis_zum_tor // VERIFIER_RETRY_PAAR_SEKUNDEN)
    return max(1, min(obergrenze, passende_paare))
