"""Cohesive facade over the deterministic grounding flow.

WHY THIS MODULE EXISTS
----------------------
The grounding logic in :mod:`analysis_grounding` is a large collection of pure,
module-level functions. The *orchestrator* threads them together by hand inside
``_build_grounded_final_answer`` — but that method is also tangled up with
``self`` state, live LLM round-trips (``_run_structured_step``) and SSE event
emission, so it cannot be lifted out without behaviour risk.

What *can* be named and made coherent is the **deterministic core**: the part of
the flow that takes structured tool evidence and turns it into grounded facts,
notes, markdown and a prose-grounding check — with no I/O and no model calls.
``GroundingPipeline`` is exactly that seam.

It is a thin, behaviour-preserving composition: every stage delegates verbatim
to the existing public function in :mod:`analysis_grounding`. No logic is copied
or changed here. The point is coherence, testability and documentation — a
single object that spells out the contract of the deterministic pipeline.

THE CONTRACT (deterministic data flow)
--------------------------------------
::

    raw tool output (dict)
        │  extract_raw_surface(...)            # not owned here; caller-side
        ▼
    raw_surface (dict)
        │  surface()  -> build_grounding_surface
        ▼
    grounding_surface (list[str])             # the quotable evidence lines
        │
        │  (an EvidenceItem bundles raw_surface + grounding_surface; built by
        │   analysis_grounding.make_evidence_item upstream)
        ▼
    EvidenceItem[]
        │  observe_facts()  -> deterministic_observed_facts
        ▼                       (already validated against the evidence)
    ObservedFact[]
        ├─ fact_notes()       -> grounded_fact_notes   (LLM-context breadcrumbs)
        ├─ render_markdown()  -> build_grounded_markdown (family-routed prose)
        └─ validate_markdown()-> validate_markdown_grounding (prose number/quote gate)

``run()`` chains ``observe_facts → fact_notes → render_markdown`` and returns a
:class:`GroundingResult`, mirroring the deterministic fallback the orchestrator
produces when the LLM answer path is unavailable or fails its grounding gate.

WHAT IS DELIBERATELY OUT OF SCOPE
---------------------------------
The LLM-mediated answer path (observed-facts extraction via the model, answer
envelope synthesis, the verifier verdict and its retry loop) stays in the
orchestrator. Those stages need the orchestrator's session/LLM context and are
not pure, so folding them in here would create the "incoherent crutch" this
extraction is meant to avoid.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from dataclasses import dataclass, field

from . import analysis_grounding as _ag
from .analysis_grounding import (
    AnalysisContract,
    EvidenceItem,
    ObservedFact,
)

__all__ = ["GroundingPipeline", "GroundingResult"]


@dataclass
class GroundingResult:
    """Output of :meth:`GroundingPipeline.run` — the deterministic answer bundle.

    Attributes mirror exactly what the orchestrator threads into session state
    when it falls back to the deterministic path:

    - ``observed_facts``: the validated facts extracted from the evidence.
    - ``fact_notes``: short LLM-context breadcrumbs (``grounded_fact_notes``).
    - ``markdown``: the family-routed, grounded answer prose.
    """

    observed_facts: List[ObservedFact] = field(default_factory=list)
    fact_notes: List[str] = field(default_factory=list)
    markdown: str = ""


class GroundingPipeline:
    """Named composition of the deterministic grounding stages.

    Stateless: a single instance can be reused across turns. Every method is a
    1:1 delegation to the corresponding :mod:`analysis_grounding` function, so
    output is byte-identical to calling those functions directly.
    """

    # -- Stage 1: surface ------------------------------------------------- #
    def surface(self, raw_surface: Dict[str, Any]) -> List[str]:
        """Reduce a raw tool surface to deduped, quotable evidence lines.

        Delegates to :func:`analysis_grounding.build_grounding_surface`.
        """
        return _ag.build_grounding_surface(raw_surface)

    # -- Stage 2: observe facts ------------------------------------------ #
    def observe_facts(
        self,
        contract: AnalysisContract,
        evidence_items: Sequence[EvidenceItem],
    ) -> List[ObservedFact]:
        """Extract deterministic, evidence-validated :class:`ObservedFact`\\ s.

        Delegates to :func:`analysis_grounding.deterministic_observed_facts`,
        which already runs ``validate_observed_facts`` against the evidence.
        """
        return _ag.deterministic_observed_facts(contract, evidence_items)

    # -- Stage 3a: notes -------------------------------------------------- #
    def fact_notes(
        self,
        observed_facts: Sequence[ObservedFact],
        *,
        max_items: int = 5,
    ) -> List[str]:
        """Render compact fact breadcrumbs for LLM context.

        Delegates to :func:`analysis_grounding.grounded_fact_notes`.
        """
        return _ag.grounded_fact_notes(observed_facts, max_items=max_items)

    # -- Stage 3b: render markdown --------------------------------------- #
    def render_markdown(
        self,
        contract: AnalysisContract,
        observed_facts: Sequence[ObservedFact],
        evidence_items: Sequence[EvidenceItem],
        *,
        evidence_gaps: Sequence[str],
        accepted_claim_ids: Sequence[str] | None = None,
    ) -> str:
        """Build the family-routed, grounded answer markdown.

        Delegates to :func:`analysis_grounding.build_grounded_markdown`.
        """
        return _ag.build_grounded_markdown(
            contract,
            observed_facts,
            evidence_items,
            evidence_gaps=evidence_gaps,
            accepted_claim_ids=accepted_claim_ids,
        )

    # -- Stage 4: validate prose ----------------------------------------- #
    def validate_markdown(
        self,
        markdown: str,
        accepted_facts: Sequence[ObservedFact],
    ) -> List[str]:
        """Return number/range/quote tokens in ``markdown`` not backed by facts.

        Delegates to :func:`analysis_grounding.validate_markdown_grounding`.
        An empty list means the prose is fully grounded.
        """
        return _ag.validate_markdown_grounding(markdown, accepted_facts)

    # -- Composition ----------------------------------------------------- #
    def run(
        self,
        contract: AnalysisContract,
        evidence_items: Sequence[EvidenceItem],
        *,
        evidence_gaps: Sequence[str],
        accepted_claim_ids: Sequence[str] | None = None,
    ) -> GroundingResult:
        """Run the deterministic chain: observe -> notes -> render.

        This mirrors the orchestrator's deterministic fallback (the path it
        takes when there is no usable LLM answer envelope). It does NOT invoke
        the LLM-mediated envelope/verdict stages by design — see the module
        docstring.
        """
        observed_facts = self.observe_facts(contract, evidence_items)
        notes = self.fact_notes(observed_facts)
        markdown = self.render_markdown(
            contract,
            observed_facts,
            evidence_items,
            evidence_gaps=evidence_gaps,
            accepted_claim_ids=accepted_claim_ids,
        )
        return GroundingResult(
            observed_facts=observed_facts,
            fact_notes=notes,
            markdown=markdown,
        )
