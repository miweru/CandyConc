"""LOC-Budget-Waechter fuer ``candyconc_copilot`` (K3 Slice 3).

Regeln:

* Kein Modul unter ``candyconc_copilot/`` (inklusive ``claim_rules/*``)
  ueberschreitet 6.000 Zeilen, ausser es steht mit Begruendung in der
  Budget-Datei ``tests/ai/copilot_loc_budget.json``.
* ``analysis_grounding.py`` ist seit Slice 3 eine reine Fassade und bleibt
  unter 3.000 Zeilen.
* ``grounding_verifier.py`` bleibt unter dem am 2026-08-11 gemessenen
  Ist-Stand + 10 Prozent. Die Konstante ist hier gepinnt, damit eine
  stille Anhebung im JSON auffaellt.

Die Budgets duerfen sinken, aber nie steigen: wer ein Modul verkleinert,
zieht die Ausnahme nach unten oder loescht sie.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest


_TESTS_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = (
    _TESTS_DIR.parents[1] / "src" / "candyconc" / "candyconc_copilot"
)
BUDGET_PATH = _TESTS_DIR / "copilot_loc_budget.json"

# Ist-Stand von grounding_verifier.py, gemessen am 2026-08-11 (K3 Slice 3):
# 16014 Zeilen. Budget = Ist + 10 Prozent. ABSENKUNGS-ABSICHT: der Verifier
# ist der naechste Dekompositionskandidat nach dem analysis_grounding-Muster
# (Slices 1-3). Diese Konstante wird mit jedem Verifier-Slice gesenkt und
# darf nie angehoben werden.
GROUNDING_VERIFIER_BASELINE_LINES = 16014
GROUNDING_VERIFIER_MAX_LINES = int(GROUNDING_VERIFIER_BASELINE_LINES * 1.10)

# Fassaden-Budget: analysis_grounding.py ist seit K3 Slice 3 eine reine
# Re-Export-Fassade (Slice-3-Ist: 1069 Zeilen). Das 3.000er-Budget laesst
# Platz fuer weitere Re-Export-Zeilen, aber nicht fuer zurueckwachsende Logik.
ANALYSIS_GROUNDING_FACADE_MAX_LINES = 3000


def _line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def _load_budget() -> dict:
    with BUDGET_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCopilotLocBudget(unittest.TestCase):
    def test_package_root_exists(self) -> None:
        self.assertTrue(
            PACKAGE_ROOT.is_dir(),
            f"candyconc_copilot package not found at {PACKAGE_ROOT}",
        )

    def test_budget_file_pins_match_constants(self) -> None:
        budget = _load_budget()
        exceptions = budget["exceptions"]
        self.assertEqual(
            exceptions["grounding_verifier.py"]["max_lines"],
            GROUNDING_VERIFIER_MAX_LINES,
            "grounding_verifier budget in copilot_loc_budget.json must equal "
            "the pinned Ist+10% constant. Do not raise it silently.",
        )
        self.assertEqual(
            exceptions["analysis_grounding.py"]["max_lines"],
            ANALYSIS_GROUNDING_FACADE_MAX_LINES,
            "analysis_grounding facade budget must stay pinned at 3000.",
        )

    def test_every_exception_has_a_justification(self) -> None:
        budget = _load_budget()
        for module, entry in budget["exceptions"].items():
            self.assertTrue(
                str(entry.get("begruendung", "")).strip(),
                f"budget exception for {module} lacks a Begruendung",
            )
            # None heisst: Budget aufgehoben (orchestrator.py, 2026-09-26).
            if entry["max_lines"] is not None:
                self.assertIsInstance(entry["max_lines"], int, module)

    def test_exceptions_point_at_existing_modules(self) -> None:
        budget = _load_budget()
        for module in budget["exceptions"]:
            self.assertTrue(
                (PACKAGE_ROOT / module).is_file(),
                f"budget exception for {module} names a missing module. "
                "Delete the stale entry.",
            )

    def test_no_module_exceeds_its_budget(self) -> None:
        budget = _load_budget()
        default_max = int(budget["default_max_lines"])
        exceptions = budget["exceptions"]
        violations: list[str] = []
        for path in sorted(PACKAGE_ROOT.rglob("*.py")):
            relative = path.relative_to(PACKAGE_ROOT).as_posix()
            entry = exceptions.get(relative)
            if entry and entry["max_lines"] is None:
                continue
            limit = int(entry["max_lines"]) if entry else default_max
            lines = _line_count(path)
            if lines > limit:
                violations.append(
                    f"{relative}: {lines} lines > budget {limit}"
                )
        self.assertEqual(
            violations,
            [],
            "LOC budget exceeded (grow the decomposition, not the budget):\n"
            + "\n".join(violations),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
