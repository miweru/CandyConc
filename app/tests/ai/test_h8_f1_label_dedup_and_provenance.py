"""H8 Paket F1: Doppel-Label-Politur + Provenienz-Leitplanke (R7b-Befunde).

Alle Tests laufen offline gegen reine Funktionen und Rezept-Daten (kein LLM,
kein Index, keine Live-Calls). Geprueft werden:

- ``strip_repeated_section_labels`` faltet 'Deutung\\nDeutung: ...' (R7b
  kwic_zeit: Wrap-up-Ueberschrift + Modell wiederholt das Label) konservativ:
  NUR bei exakter Label-Wiederholung der vier Wrap-up-Sektionslabels
  (Kernbefund/Belege/Deutung/Grenzen), Doppelpunkt ist Pflicht, Fett- und
  Ueberschrift-Varianten symmetrisch.
- ``verifier_skipped_answer_text`` wendet die Politur im
  Verifier-Skip-/Salvage-Pfad an (dort leben auch fold_duplicate_lines und
  collapse_unit_number_doubles).
- Das Rezept ``gebrauch_kwic`` verlangt die Stichproben-Provenienz als EINEN
  lesbaren Satz in der Grenzen-Sektion und verbietet rohe Parameternamen
  (requested/drawn/seed) im Fliesstext (R7b kwic_zeit: 'beruht auf einer
  Zufallsstichprobe requested 25, drawn 25, seed 42 ...').
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from candyconc.candyconc_copilot.recipe_runtime import (  # noqa: E402
    strip_repeated_section_labels,
    verifier_skipped_answer_text,
)
from candyconc.candyconc_copilot.recipes import (  # noqa: E402
    get_recipe,
    render_briefing,
)


class TestStripRepeatedSectionLabels:
    def test_folds_r7b_deutung_double(self):
        # Wortlaut-Klasse aus R7b kwic_zeit (antwort_text): nackte
        # Wrap-up-Ueberschrift, direkt darunter wiederholt das Modell das
        # Label als Praefix.
        text = (
            "…::source::d12b6d3e9f7cafb1, pos 37.640\n"
            "\n"
            "Deutung\n"
            "Deutung: In der Stichprobe dominieren temporale und "
            "modal-impulsive Verwendungen von „Zeit“."
        )
        result = strip_repeated_section_labels(text)
        assert "Deutung\nDeutung:" not in result
        assert (
            "Deutung\nIn der Stichprobe dominieren temporale" in result
        )

    def test_folds_all_four_wrapup_labels(self):
        for label in ("Kernbefund", "Belege", "Deutung", "Grenzen"):
            text = f"{label}\n{label}: Inhalt der Sektion."
            assert (
                strip_repeated_section_labels(text)
                == f"{label}\nInhalt der Sektion."
            )

    def test_folds_markdown_heading_and_bold_variants(self):
        assert (
            strip_repeated_section_labels("## Deutung\nDeutung: X.")
            == "## Deutung\nX."
        )
        assert (
            strip_repeated_section_labels("**Deutung**\nDeutung: X.")
            == "**Deutung**\nX."
        )
        assert (
            strip_repeated_section_labels("Deutung\n**Deutung:** X.")
            == "Deutung\nX."
        )
        assert (
            strip_repeated_section_labels("Deutung:\nDeutung: X.")
            == "Deutung:\nX."
        )

    def test_blank_line_between_heading_and_repeat_still_folds(self):
        # 'unmittelbar vorangehende NICHT-LEERE Zeile' — Leerzeilen
        # dazwischen aendern nichts an der Wiederholung.
        assert (
            strip_repeated_section_labels("Deutung\n\nDeutung: X.")
            == "Deutung\n\nX."
        )

    def test_conservative_no_colon_no_fold(self):
        # Ohne Doppelpunkt ist es keine Label-Wiederholung, sondern
        # regulaerer Satzanfang.
        text = "Deutung\nDeutung der Daten bleibt offen."
        assert strip_repeated_section_labels(text) == text

    def test_conservative_label_mismatch_no_fold(self):
        text = "Kernbefund\nDeutung: eine Lesart."
        assert strip_repeated_section_labels(text) == text

    def test_conservative_intervening_content_resets(self):
        text = "Deutung\nEin Satz dazwischen.\nDeutung: eine Lesart."
        assert strip_repeated_section_labels(text) == text

    def test_conservative_keeps_line_that_would_become_empty(self):
        text = "Deutung\nDeutung:"
        assert strip_repeated_section_labels(text) == text

    def test_non_wrapup_labels_untouched(self):
        text = "Fazit\nFazit: alles gut."
        assert strip_repeated_section_labels(text) == text


class TestVerifierSkipPathAppliesLabelDedup:
    def test_skip_path_folds_duplicate_label(self):
        draft = (
            "Kernbefund\n"
            "Es gibt genau 32 Treffer in der Stichprobe von 25 Zeilen.\n"
            "\n"
            "Deutung\n"
            "Deutung: Temporale Verwendungen dominieren die gezogene "
            "Stichprobe deutlich."
        )
        result = verifier_skipped_answer_text(
            draft,
            lambda text: {"text": text, "bare_numbers": []},
            lambda: "",
            lambda note: f"FAIL: {note}",
        )
        assert "Deutung\nDeutung:" not in result
        assert "Temporale Verwendungen dominieren" in result
        assert "LLM-Verifikation übersprungen" in result


class TestGebrauchKwicProvenanceGuardrail:
    def test_leitplanke_demands_readable_provenance_sentence(self):
        recipe = get_recipe("gebrauch_kwic")
        matching = [
            lp
            for lp in recipe.leitplanken
            if "Grenzen-Sektion" in lp and "Fliesstext" in lp
        ]
        assert len(matching) == 1
        leitplanke = matching[0]
        assert "EINEM lesbaren Satz" in leitplanke
        assert "Zufallsstichprobe von 25 der 32 Treffer" in leitplanke
        assert "requested, drawn, seed" in leitplanke
        # Leitplanken-Budget (2-4) bleibt eingehalten.
        assert 2 <= len(recipe.leitplanken) <= 4

    def test_briefing_no_longer_asks_for_raw_params_in_answer(self):
        recipe = get_recipe("gebrauch_kwic")
        rendered = render_briefing(recipe)
        # Die Presence-Aera-Formel 'requested, drawn, seed, population
        # gehoert in die Antwort' ist raus …
        assert "population gehoert in die Antwort" not in rendered
        assert "requested/drawn/seed" not in rendered
        # … die Provenienz-Pflicht bleibt, aber lesbar und am richtigen Ort.
        assert "Grenzen-Sektion" in rendered
        assert "Stichproben-Provenienz" in rendered
