"""Place interpretation before the supporting numeric inventory."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from candyconc.candyconc_copilot.grounding_markdown import (  # noqa: E402
    build_verified_claim_markdown,
)
from candyconc.candyconc_copilot.grounding_schemas import (  # noqa: E402
    AnswerEnvelope,
    ClaimDraft,
    EvidenceItem,
    ObservedFact,
)


def _evidence_item(item_id: str, tool: str, raw_surface: dict) -> EvidenceItem:
    return EvidenceItem(
        id=item_id,
        tool=tool,
        tool_call_id=f"call_{item_id}",
        query="{}",
        status="success",
        truncated=False,
        raw_surface=raw_surface,
    )


def _fact() -> ObservedFact:
    return ObservedFact(
        id="f001",
        statement="total=40",
        fact_kind="count",
        source_evidence_ids=["ev1"],
    )


#: Woertlich im Ton der beiden gemessenen Turns gehalten.
BEOBACHTUNG = "Die sichtbare Keyness-Analyse weist total=40 Treffer aus."
DEUTUNG = (
    "Der Unterschied traegt, weil er auch nach Registerkontrolle "
    "in dieselbe Richtung zeigt."
)


def _rendern(claims: list[ClaimDraft], **kwargs) -> str:
    envelope = AnswerEnvelope(claims=claims)
    grundwerte = dict(
        deliverable_kind="analysis_report",
        question_text="Was folgt aus dem Befund?",
        evidence_items=[_evidence_item("ev1", "run_cqlf_query", {"total": 40})],
        evidence_gaps=[],
    )
    grundwerte.update(kwargs)
    return build_verified_claim_markdown(
        envelope, [c.id for c in claims], [_fact()], **grundwerte
    )


class TestDieDeutungStehtVorDerBeobachtung:
    """Die eigentliche Aussage dieses Moduls."""

    def _claims(self) -> list[ClaimDraft]:
        return [
            ClaimDraft(
                id="c_beob", claim_kind="observation",
                text=BEOBACHTUNG, fact_ids=["f001"],
            ),
            ClaimDraft(
                id="c_deut", claim_kind="interpretation",
                text=DEUTUNG, fact_ids=["f001"],
            ),
        ]

    def test_die_deutung_kommt_zuerst(self):
        markdown = _rendern(self._claims())
        assert DEUTUNG in markdown, markdown
        assert BEOBACHTUNG in markdown, markdown
        assert markdown.index(DEUTUNG) < markdown.index(BEOBACHTUNG), (
            "Die Beobachtung steht vor der Deutung. Genau so las sich der "
            "Livelauf vom 2026-09-01:\n\n" + markdown
        )

    def test_die_reihenfolge_haengt_nicht_an_der_claim_folge(self):
        """Sonst waere die Probe von der Eingabe erfuellt, nicht vom Bauer."""
        gedreht = list(reversed(self._claims()))
        markdown = _rendern(gedreht)
        assert markdown.index(DEUTUNG) < markdown.index(BEOBACHTUNG), markdown


class TestEineAntwortOhneDeutungBleibtEineAntwort:
    """Die Gegenrichtung. Ohne sie waere die Regel eine Pflicht zur Deutung.

    Ein blosses Nachschlagen hat keine Deutung, und der Bauer darf daran
    nicht scheitern und keine erfinden.
    """

    def test_nur_beobachtungen_rendern_weiterhin(self):
        claims = [
            ClaimDraft(
                id="c_beob", claim_kind="observation",
                text=BEOBACHTUNG, fact_ids=["f001"],
            ),
        ]
        markdown = _rendern(claims, deliverable_kind="lookup_answer")
        assert BEOBACHTUNG in markdown, markdown


class TestDieRegelBleibtEng:
    """Was NICHT bewegt wird. Ohne diese Proben waere die Regel eine Schablone.

    Der Renderer trug an der Aufrufstelle den Kommentar "Claim order is
    model-owned: presentation must not turn every argument into the same
    observations-then-interpretation template", und eine bestehende Probe
    (test_analysis_report_renderer_preserves_model_argument_order) hat
    meinen ersten, pauschalen Anlauf erschlagen. Zu Recht.
    """

    def test_ein_rueckverweis_bleibt_wo_er_ist(self):
        """"Daraus" zeigt nach oben. Oben angekommen zeigt es auf nichts."""
        kette = [
            ClaimDraft(
                id="c1", claim_kind="observation",
                text="Erster empirischer Ausgangspunkt.", fact_ids=["f001"],
            ),
            ClaimDraft(
                id="c2", claim_kind="observation",
                text="Ein zweiter Befund kommt hinzu.", fact_ids=["f001"],
            ),
            ClaimDraft(
                id="c3", claim_kind="interpretation",
                text="Daraus folgt eine vorsichtige Zwischendeutung.",
                fact_ids=["f001"],
            ),
        ]
        markdown = _rendern(kette)
        assert markdown.index("Erster empirischer") < markdown.index(
            "Daraus folgt"
        ), markdown

    def test_es_wandert_hoechstens_ein_claim(self):
        """Die Reihenfolge des Modells bleibt sonst unberuehrt."""
        claims = [
            ClaimDraft(
                id="c1", claim_kind="observation",
                text="Zuerst gemessen.", fact_ids=["f001"],
            ),
            ClaimDraft(
                id="c2", claim_kind="interpretation",
                text="Eine erste Einordnung mittendrin.", fact_ids=["f001"],
            ),
            ClaimDraft(
                id="c3", claim_kind="observation",
                text="Danach gemessen.", fact_ids=["f001"],
            ),
            ClaimDraft(
                id="c4", claim_kind="interpretation",
                text="Zusammengefasst zeigt sich ein Muster.",
                fact_ids=["f001"],
            ),
        ]
        markdown = _rendern(claims)
        assert markdown.index("Zusammengefasst") < markdown.index("Zuerst gemessen")
        assert markdown.index("Zuerst gemessen") < markdown.index(
            "Eine erste Einordnung"
        ), "der mittlere Claim wurde mitbewegt:\n" + markdown
        assert markdown.index("Eine erste Einordnung") < markdown.index(
            "Danach gemessen"
        ), markdown

    def test_endet_die_antwort_auf_einer_beobachtung_passiert_nichts(self):
        claims = [
            ClaimDraft(
                id="c1", claim_kind="interpretation",
                text="Eine Deutung steht schon oben.", fact_ids=["f001"],
            ),
            ClaimDraft(
                id="c2", claim_kind="observation",
                text="Und darunter die Messung.", fact_ids=["f001"],
            ),
        ]
        markdown = _rendern(claims)
        assert markdown.index("Eine Deutung steht schon oben") < markdown.index(
            "Und darunter die Messung"
        ), markdown


class TestWerSchonMitBedeutungAnfaengtWirdNichtAngefasst:
    """Die dritte Verengung, und sie kam aus einer echten Antwort.

    ``deutung-druckreif-sicherheit`` vom 2026-09-01 beginnt mit

        "Ein unbedingter Satz ueber einen allgemeinen Unterschied zwischen
         menschlichen und maschinellen Texten ist aus dieser Analyse nicht
         vertretbar."

    Das IST das Urteil, um das gebeten wurde. Der letzte Absatz derselben
    Antwort ist eine schwaechere Randbeobachtung ueber drei Wortformen.
    Meine Regel haette die schwaechere nach oben gezogen und damit eine
    gute Antwort verschlechtert.
    """

    def test_eine_fuehrende_deutung_bleibt_fuehrend(self):
        stark = "Ein unbedingter Satz ist aus dieser Analyse nicht vertretbar."
        schwach = "Am Rande passt die Verteilung zu einer Quellenlage."
        claims = [
            ClaimDraft(
                id="c1", claim_kind="interpretation",
                text=stark, fact_ids=["f001"],
            ),
            ClaimDraft(
                id="c2", claim_kind="observation",
                text=BEOBACHTUNG, fact_ids=["f001"],
            ),
            ClaimDraft(
                id="c3", claim_kind="interpretation",
                text=schwach, fact_ids=["f001"],
            ),
        ]
        markdown = _rendern(claims)
        assert markdown.index(stark) < markdown.index(schwach), (
            "die schwaechere Deutung hat die fuehrende verdraengt:\n" + markdown
        )
        assert markdown.index(stark) < markdown.index(BEOBACHTUNG), markdown
