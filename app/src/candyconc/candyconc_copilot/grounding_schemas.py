"""Grounding vocabulary: constants, prompt docs, dataclasses and JSON schemas.

K3 Slice 1: byte-verbatim extraction from ``analysis_grounding.py`` (the
facade). Layer 0 of the grounding decomposition: this module imports NO
sibling grounding module, so ``grounding_evidence`` and ``grounding_contracts``
can build on it without cycles.

Moved here: the mode/track/family/evidence vocabulary constants (incl.
``GROUNDING_TRIGGER_TOOLS`` and the ``TOOL_BUNDLES`` family), the LLM prompt
doc constants (``ANALYSIS_CONTRACT_DOC`` .. ``KWIC_RELATION_ADJUDICATOR_DOC``),
the generic text/coercion helpers (``_compact_text`` .. ``_extract_json``),
the dataclasses ``ResponseRequirement``, ``EvidenceItem``, ``EvidenceBundle``,
``ObservedFact``, ``ClaimDraft``, ``AnswerEnvelope``, ``GroundingVerdict``,
``ContractReview`` plus their claim-pattern helpers, the JSON-schema builders
(except ``answer_envelope_schema``, which needs the contracts layer), and the
family/track vocabulary (``default_track_for_family``,
``default_deliverable_kind_for_family``, ``compatible_deliverable_kind``,
``resolve_allowed_tools``) together with the micro text predicates the
dataclasses call at runtime (``_normalised_question_text``, ``_has_any_phrase``,
``_dedupe_ordered_strs``, ``_is_followup_prompt``, ...).

Documented deviation from the slice sketch: ``AnalysisContract`` lives in
``grounding_contracts`` (NOT here) because ``AnalysisContract.from_raw`` calls
``normalise_response_requirements`` and the prompt heuristics at runtime.
Keeping it here would force a schemas -> contracts dependency and a cycle.

``analysis_grounding`` re-exports every name below, so all existing imports
and ``analysis_grounding.<name>`` monkeypatch seams keep working. This module
must never import ``analysis_grounding`` or a sibling grounding module.
"""

from __future__ import annotations

from candyconc.answer_language import choose as _t

import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from candyconc.question_kind import (
    enthaelt_deutungscue,
    frage_ist_blosses_nachschlagen,
    normalisierte_frage,
)
from candyconc.question_language import routing_text
from candyconc.utils.text_normalize import strip_llm_protocol_tail

MODE_VALUES = ("direct_answer", "tool_analysis", "clarify")
TRACK_VALUES = (
    "lookup",
    "bounded_analysis",
    "comparative_analysis",
    "exploratory_research",
    "method_help",
)
DELIVERABLE_KINDS = (
    "lookup_answer",
    "analysis_report",
    "contrast_report",
    "capability_report",
    "overview",
    "followup_questions",
    "method_advice",
)
ANALYSIS_FAMILIES = (
    "term_frequency",
    "kwic_context",
    "term_profile",
    "ngram_profile",
    "lexical_diversity",
    "trend_analysis",
    "word_sketch_profile",
    "collocation",
    "contrast_keyness",
    "metadata_capability",
    "document_lookup",
    "semantic_retrieval",
    "open_research",
)
EVIDENCE_KINDS = (
    "kwic_rows",
    "expanded_context",
    "frequency_rows",
    "lexical_frequency_rows",
    "content_rows",
    "contextual_rows",
    "metric_rows",
    "dispersion_profile",
    "document_rows",
    "documentation_rows",
    "metadata_rows",
    "semantic_rows",
    "cluster_rows",
    "total_hits",
)
FACT_KINDS = (
    "count",
    "pmw",
    "kwic_example",
    "ranked_row",
    "distribution",
    "metadata",
    "negative_result",
    "limitation",
    # Runde 2, P1: der kompakte Verlauf einer langen Reihe (ein Fakt mit
    # label:rate je Periode) — transportiert die ganze Zeitachse durch
    # jede Synthese-Kappe.
    "series",
)
EXACTNESS_VALUES = ("exact", "sample_only", "top_n_only", "partial", "derived")
CLAIM_SUPPORT_VALUES = (
    "counts",
    "examples",
    "ranks",
    "percentages",
    "comparisons",
    "interpretation_anchor",
)
CLAIM_KINDS = ("observation", "interpretation", "limitation", "followup")
_CLAIM_KIND_ALIASES = {
    "method_advice": "interpretation",
    "method_step": "interpretation",
}
ASSERTION_LEVELS = ("exact", "qualified", "tentative")
GROUNDING_VERDICTS = ("pass", "retry", "conservative_only")
CLAIM_ID_LIMIT = 40
MAX_ANSWER_CLAIMS = 128
MAX_VERDICT_CLAIM_IDS = 512
MAX_VERDICT_REASON_CHARS = 600
MAX_FACT_IDS_PER_CLAIM = 16
MAX_CLAIM_TEXT_CHARS = 1_200
MAX_RESPONSE_REQUIREMENTS = 16
MAX_RESPONSE_REQUIREMENT_CHARS = 320
# Q2 (Runde 5): 20 -> 50 wurde getestet und ZURÜCKGEROLLT — die
# Erhöhung bricht 6 Pin-Tests auf die "bounded model view" (bewusste
# Design-Entscheidung) und erhöht den Kontextdruck auf einem Gerät,
# das große Kontexte in der Generierung schon jetzt nicht trägt.
# Die richtige Lösung: die Fact-Surface (unbeschränkt) statt der
# gebundenen Modellansicht an die Synthese-NAHT führen — der series-
# Fakt (Runde 3) ist das Muster. Siehe runde5_widerlegung_plan_qualitaet.
DEFAULT_GROUNDING_ROW_LIMIT = 20
DEFAULT_SYNTHESIS_FACT_LIMIT = 64
CONTRACT_REVIEW_VERDICTS = ("accept", "clarify", "conservative_only")
CLARIFICATION_QUESTION_LIMIT = 800

DEFAULT_FORBIDDEN_CLAIMS = (
    "unsupported counts",
    "unsupported rank ranges",
    "unsupported examples",
    "unsupported percentages",
    "unsupported category claims",
    "unsupported cross-tool inference",
)

# KWIC rows are already bounded by their requested token window. Preserve that
# visible window for interpretation instead of applying the generic 220-char
# logging limit, which can silently remove the evaluative right context.
KWIC_GROUNDING_QUOTE_LIMIT = 2_000

TOOL_BUNDLES: Dict[str, Sequence[str]] = {
    "term_frequency": (
        "metadata_values",
        "create_docset",
        "query_count",
        "run_cqlf_query",
        "frequency_list",
        "dispersion_offsets",
    ),
    "kwic_context": (
        "metadata_values",
        "create_docset",
        "run_cqlf_query",
        "kwic_context",
        "document_search",
    ),
    "term_profile": (
        "metadata_values",
        "create_docset",
        "query_count",
        "run_cqlf_query",
        "collocate_stats",
        "frequency_list",
        "dispersion_offsets",
    ),
    "ngram_profile": ("create_docset", "ngram_frequency"),
    "lexical_diversity": ("create_docset", "lexical_diversity"),
    "trend_analysis": (
        "metadata_values",
        "create_docset",
        "trend_analysis",
    ),
    "word_sketch_profile": ("word_sketch", "run_cqlf_query"),
    "collocation": (
        "metadata_values",
        "create_docset",
        "collocate_stats",
        "word_sketch",
        "run_cqlf_query",
    ),
    "contrast_keyness": (
        "metadata_values",
        "create_docset",
        "query_count",
        "contrast_collocates",
        "compare_collocates",
        "collocate_stats",
        "run_cqlf_query",
        "keyness",
        "frequency_list",
    ),
    "metadata_capability": ("metadata_values", "document_search"),
    "document_lookup": ("document_search", "documentation_search"),
    "semantic_retrieval": (
        "semantic_search",
        "semantic_cluster",
        "semantic_cluster_words",
    ),
}
OPEN_RESEARCH_CANDIDATES = (
    "document_search",
    "documentation_search",
    "semantic_search",
    "semantic_cluster",
    "semantic_cluster_words",
)
TRACK_TOOL_CANDIDATES: Dict[str, Sequence[str]] = {
    "lookup": (
        "run_cqlf_query",
        "kwic_context",
        "frequency_list",
        "document_search",
        "metadata_values",
        "documentation_search",
    ),
    "bounded_analysis": (),
    "comparative_analysis": (
        "metadata_values",
        "create_docset",
        "query_count",
        "compare_collocates",
        "contrast_collocates",
        "keyness",
        "collocate_stats",
        "word_sketch",
        "run_cqlf_query",
        "frequency_list",
        "metadata_values",
        "document_search",
    ),
    "exploratory_research": (
        "frequency_list",
        "metadata_values",
        "semantic_search",
        "semantic_cluster_words",
        "semantic_cluster",
        "compare_collocates",
        "contrast_collocates",
        "keyness",
        "run_cqlf_query",
        "collocate_stats",
        "word_sketch",
        "dispersion_offsets",
        "document_search",
        "documentation_search",
    ),
    "method_help": (
        "frequency_list",
        "metadata_values",
        "semantic_search",
        "document_search",
        "documentation_search",
    ),
}
TRACK_TOOL_LIMITS: Dict[str, int] = {
    "lookup": 2,
    "bounded_analysis": 8,
    "comparative_analysis": 9,
    "exploratory_research": 4,
    "method_help": 3,
}
GROUNDING_TRIGGER_TOOLS = (
    "create_docset",
    "query_count",
    "run_cqlf_query",
    "frequency_list",
    "dispersion_offsets",
    "ngram_frequency",
    "lexical_diversity",
    "trend_analysis",
    "kwic_context",
    "collocate_stats",
    "compare_collocates",
    "contrast_collocates",
    "word_sketch",
    "keyness",
    "metadata_values",
    "document_search",
    "documentation_search",
    "semantic_search",
    "semantic_cluster",
    "semantic_cluster_words",
)
BOUNDED_CORPUS_EVIDENCE_KINDS = frozenset(
    {
        "kwic_rows",
        "expanded_context",
        "frequency_rows",
        "lexical_frequency_rows",
        "content_rows",
        "metric_rows",
        "dispersion_profile",
        "total_hits",
    }
)
OPEN_RESEARCH_INCOMPATIBLE_EVIDENCE_KINDS = frozenset(
    {
        "kwic_rows",
        "expanded_context",
        "metric_rows",
        "dispersion_profile",
    }
)

ANALYSIS_CONTRACT_DOC = (
    "Du klassifizierst die aktuelle Nutzerfrage für eine evidenzgebundene "
    "Korpusanalyse. Antworte ausschließlich als JSON nach Schema. "
    "Wähle zuerst einen Track: lookup, bounded_analysis, comparative_analysis, "
    "exploratory_research oder method_help. "
    "Wähle mode=tool_analysis nur, wenn eine tool-gestützte Analyse "
    "tatsächlich nötig ist. Wähle mode=clarify bei einer methodisch "
    "entscheidenden Pflicht-Unklarheit: insbesondere wenn Vergleichsgruppen "
    "oder Referenz, Zeit-/Korpusscope, Zielbegriff oder die beobachtbare "
    "Operationalisierung eines interpretativen Konstrukts fehlen. Ein hoher "
    "Autonomiegrad erlaubt nicht, solche Forschungsentscheidungen zu erraten. "
    "Bündele alle wesentlichen fehlenden Angaben in genau einer kompakten "
    "clarification_question. required_evidence muss ausschließlich aus den "
    "kanonischen Evidenzarten bestehen: kwic_rows, expanded_context, frequency_rows, "
    "lexical_frequency_rows, content_rows, contextual_rows, "
    "metric_rows, dispersion_profile, document_rows, documentation_rows, "
    "semantic_rows, cluster_rows, total_hits. "
    "content_rows meint inhaltstragende Evidenz: eine Wort-/Lemmaliste mit "
    "NOUN-, PROPN-, VERB- oder ADJ-Filter oder echte semantische, Cluster- "
    "oder Dokumenttreffer; eine unbereinigte Funktionswortliste zählt nicht. "
    "Für offene Fragen wie Corpus-Overview oder allgemeine Unterschiede "
    "zwischen Korpusteilen sollst du exploratory_research oder "
    "comparative_analysis verwenden, nicht lookup. "
    "Sobald die Antwort eine Aussage über das aktive Korpus, seine Inhalte, "
    "Häufigkeiten, Metadaten, Verteilungen oder daraus motivierte "
    "Forschungsfragen machen soll, ist direct_answer unzulässig: nutze "
    "verfügbare read-only Tools und mode=tool_analysis. "
    "Wähle zusätzlich deliverable_kind passend zur Nutzerabsicht: "
    "overview, followup_questions, contrast_report, analysis_report, "
    "capability_report, method_advice oder lookup_answer. "
    "Jede required_evidence muss mit mindestens einem allowed_tool im "
    "übergebenen Toolraum erzeugbar sein. Erfinde keine Tools außerhalb der "
    "erlaubten Track-/Familienlogik. mode=direct_answer erfordert zwingend "
    "allowed_tools=[] und required_evidence=[]; sobald du ein Tool auswählst, "
    "muss mode=tool_analysis sein. Bei mehreren verlangten methodischen "
    "Schritten muss die Evidenz deren unterschiedliche Analyseebenen tragen. "
    "Metadaten plus eine einzelne Top-N-Liste sind nur eine Bestandsaufnahme: "
    "Wenn passende Kontext-, Dokument- oder semantische Tools verfügbar sind, "
    "fordere mindestens eine komplementäre Evidenzart an, bevor Funktionen, "
    "Bedeutungen oder dokumentübergreifende Muster zum Analyseziel werden. "
    "response_requirements zerlegt ausschließlich ausdrücklich verlangte "
    "inhaltliche Antwortbestandteile in atomare Slots. source_quote ist dabei "
    "immer ein wörtlich aus der Nutzerfrage kopierter Textausschnitt. "
    "Wiederhole dort keine "
    "allgemeinen Anforderungen des deliverable_kind und schreibe keine "
    "mögliche Antwort vor. Wenn der Nutzer etwa mehrere konkurrierende "
    "Hypothesen mit je einem Widerlegungskriterium verlangt, erhält jede "
    "vollständige Hypothese genau einen eigenen, inhaltsneutral beschriebenen "
    "Slot. Formatwünsche wie Überschriften sind keine Slots."
)
RESPONSE_REQUIREMENTS_DOC = (
    "Extrahiere ausschließlich die ausdrücklich verlangten substanziellen "
    "Antwortbestandteile aus der Nutzerfrage. Antworte als JSON nach Schema. "
    "Ein Slot entspricht genau einem atomaren Beitrag, den eine fertige "
    "Antwort tatsächlich enthalten muss. Zerlege eine verlangte Anzahl in "
    "entsprechend viele Slots und integriere eng gekoppelte Bedingungen – "
    "etwa Operationalisierung und mögliches Widerlegungsergebnis einer "
    "Hypothese – in denselben Slot. source_quote muss für jeden Slot einen "
    "unveränderten, zusammenhängenden Textausschnitt aus der Nutzerfrage "
    "enthalten, der genau diese Pflicht belegt; bei einer verlangten Anzahl "
    "darf derselbe Ausschnitt für mehrere Slots wiederholt werden. Erfinde keine "
    "Antwortstrategie, Methode oder empirische Aussage. Allgemeine Pflichten "
    "wie Belege, wissenschaftliche Sorgfalt, Einleitung, Fazit, Tabellen oder "
    "Überschriften sind keine Slots. Wenn die Frage keine zusätzlichen "
    "substanziellen Bestandteile verlangt, gib eine leere Liste zurück."
)
NON_AUTHORITATIVE_GROUNDING_TOOLS = (
    "refine_cluster_label",
    "semantic_recluster",
    "cluster_save",
    "cluster_export_md",
)

CONTRACT_VERIFIER_DOC = (
    "Du prüfst einen vorgeschlagenen AnalysisContract adversarial. "
    "Deine Aufgabe ist methodisch passende, ausführbare Reichweite – nicht "
    "maximale Enge. Bewahre alle Teilfragen und Vergleichsabsichten, die mit "
    "den verfügbaren Tools und Evidenzarten ehrlich bearbeitbar sind. Wenn "
    "open_research für eine klar "
    "begrenzte Frage zu breit ist, narrowe auf die engere analysis_family. "
    "Wenn eine offene explorative Frage faelschlich auf lookup oder einen "
    "einzelnen KWIC-Pfad verengt wird, hebe sie auf exploratory_research "
    "oder comparative_analysis an. "
    "Prüfe auch den deliverable_kind: Follow-up-Fragen brauchen "
    "followup_questions statt overview; offene Vergleiche brauchen "
    "contrast_report; einfache Lookup-Faelle brauchen lookup_answer. "
    "Wenn Vergleichsgruppen/Referenz, Scope oder die Operationalisierung eines "
    "interpretativen Konstrukts methodisch entscheidend fehlen, gib clarify "
    "mit genau einer kompakten Frage zurück. Clarify ist nur richtig, wenn die "
    "Lücke eine ehrliche Analyse tatsächlich blockiert; Offenheit allein ist "
    "kein Ablehnungsgrund. Autonomie ist keine Erlaubnis zum Raten. Prüfe "
    "außerdem, dass jede required_evidence durch mindestens ein "
    "allowed_tool erzeugbar ist. Wenn required_evidence fehlt oder der Vertrag "
    "für die Frage zu vage ist, korrigiere ihn nach Möglichkeit. "
    "Für method_advice mit mehreren substanziellen Schritten prüfst du, ob die "
    "required_evidence mehr als Metadaten und eine globale Top-N-Liste umfasst. "
    "Fordere eine passende komplementäre Kontext-, Dokument- oder semantische "
    "Evidenzart an, sofern der verfügbare Toolraum sie erzeugen kann; schreibe "
    "aber kein bestimmtes Verfahren vor, wenn mehrere methodisch passen. "
    "conservative_only ist nur richtig, wenn sich aus dem verfügbaren "
    "Toolraum kein methodisch tragfähiger Vertrag bilden lässt. "
    "Antworte ausschließlich als JSON gemäß Schema."
)

OBSERVED_FACTS_DOC = (
    "Du extrahierst ausschließlich beobachtete Fakten aus dem EvidenceBundle. "
    "Keine Interpretation. Jede Aussage muss direkt an source_evidence_ids "
    "gebunden sein. Jede Aussage muss zusaetzlich grounding_quotes enthalten, "
    "die exakt in der grounding_surface der referenzierten Evidenz vorkommen. "
    "Übernimm inhaltstragende Labels, Namen und Terme wortgetreu aus diesen "
    "Quotes; führe im Statement keine neue Entität oder semantische "
    "Paraphrase ein. "
    "Wenn Evidenz nur als Top-N, Stichprobe oder partiell vorliegt, markiere "
    "exactness entsprechend."
)

ANSWER_ENVELOPE_DOC = (
    "Schreibe aus draft_answer und observed_facts eine natürliche, "
    "publikationsreife Forschungsantwort statt eines Formularberichts. Bewahre "
    "die nützliche Argumentation des Entwurfs; draft_answer ist jedoch keine "
    "Evidenz. Wenn ein Entwurf vorliegt, behandle seine Reihenfolge, fachliche "
    "Breite und Erkenntniskandidaten als redaktionellen Ausgangspunkt. Ersetze "
    "eine tragfähige, durch observed_facts belegbare Deutung nicht durch eine "
    "beliebige leichter abschreibbare Rangzeile. Verwirf oder korrigiere nur "
    "den Teil des Entwurfs, den die Facts nicht tragen. "
    "Jeder Claim ist atomar und enthält genau eine überprüfbare Proposition. "
    "Trenne eigenständige Deutung, Prüfplan und Limitation in eigene Claims, "
    "damit ein lokaler Fehler nicht eine tragfähige Interpretation verwirft. "
    "Seine empirischen Prämissen müssen durch genau die "
    "angegebenen fact_ids gedeckt sein. Technische IDs stehen nur im Feld "
    "fact_ids und niemals im sichtbaren Text. "
    "Erfinde keine Zahlen, Zitate, Beispiele, Ränge oder empirischen Beziehungen. "
    "Neue analytische Kategorien sind als ausdrücklich begrenzte Interpretation "
    "oder Hypothese zulässig, aber nicht als beobachteter Fakt. Beachte Einheiten, "
    "Scope und Exactness: Top-N-, Stichproben- "
    "und partielle Evidenz erlaubt nur entsprechend begrenzte Aussagen; getrennte "
    "Tool-Ergebnisse belegen ohne relationale Auswertung weder Korrelation noch "
    "Kausalität. Fehlende Vergleichsseiten oder Nenner werden offen benannt. "
    "Korpuspassagen belegen, was eine Quelle äußert, nicht dass ihr Inhalt eine "
    "externe Tatsache ist. "
    "Interpretation, Synthese und fachlich interessante Hypothesen sind "
    "ausdrücklich erwünscht. Sie dürfen über eine Paraphrase hinausgehen, wenn "
    "ihre Prämissen belegt sind und Modalität sowie Reichweite ehrlich bleiben. "
    "Eine prüfbare Hypothese braucht keinen erfundenen Prozentwert oder "
    "willkürlichen Schwellenwert: Eine erwartete Beziehung oder Kategorie und "
    "ein klar benanntes Gegenmuster können sie ebenso falsifizierbar machen. "
    "Formuliere in einem Hypothesen-Claim nur diese Erwartung und das mögliche "
    "Gegenmuster; direkte Beobachtungen, methodische Grenzen und Prüfpläne "
    "bleiben atomare eigene Claims. Das Gegenmuster ist ein mögliches Ergebnis "
    "einer ausführbaren Untersuchung am aktiven Korpus, nicht ein erfundener "
    "Befund aus einem hypothetischen anderen Korpus. Erfinde auch für den "
    "Prüfplan keine numerischen Grenzwerte oder Parameterwerte; beschreibe eine "
    "Sensitivitätsprüfung erforderlichenfalls relational, etwa mit niedrigerem "
    "oder höherem Schwellenwert. "
    "Partielle KWIC-Zeilen belegen einzelne Kontexte, aber ohne explizite "
    "Kodierung keine Häufigkeitsverteilung; sie dürfen dennoch interessante "
    "korpusweit zu prüfende Hypothesen motivieren. "
    "Limitationen kalibrieren die Analyse, ersetzen sie aber nicht. Nutze "
    "claim_kind=observation für direkte Befunde, interpretation für Synthesen "
    "und Hypothesen, limitation für Scope-Grenzen und followup für künftige "
    "Untersuchungen. "
    "Wenn die Nutzerfrage die Bestätigung einer einseitigen oder universellen "
    "Behauptung verlangt, behandle diese Behauptung als zu prüfende Hypothese. "
    "Bewahre belegte Gegen- und Mischbefunde, statt sie zugunsten der verlangten "
    "Schlussfolgerung auszublenden. Eine evidenzgebundene Zurückweisung der "
    "Prämisse ist eine gültige wissenschaftliche Antwort: direkte Suchbefunde "
    "bleiben observations, die Reichweitengrenze bleibt limitation und eine "
    "vorsichtige Folgerung aus beiden darf interpretation sein. "
    "Die Rangfolge einer semantischen Suche misst Retrieval-Ähnlichkeit, nicht "
    "Auftretenshäufigkeit, Prävalenz oder thematische Zentralität im Korpus. "
    "Nenne die Zeilen deshalb mit ihrem Ähnlichkeitswert und ihrem Rang, "
    "statt sie als Häufigkeitsbefund auszugeben. Prüfe bei Aussagen über "
    "gemischte oder einheitliche Wertungen alle sichtbaren Retrieval-Kandidaten; "
    "unklare und themenferne Treffer sind keine bestätigenden Belege. "
    "Bewahre Erwähnung und Gebrauch: Wenn eine Passage einen Ausdruck nennt, "
    "zitiert oder metasprachlich behandelt, übernimm ihn nicht als unmarkierte "
    "Behauptung der Analyse. "
    "Rang- und Frequenzzeilen belegen Form, Rang und Messwert, aber ohne "
    "Kontext- oder Positionsdaten weder Satzposition noch bereits eine "
    "grammatische oder formelhafte Funktion. Solche Einordnungen bleiben "
    "prüfenswerte Hypothesen. Wenn die Frage konkrete Rangzeilen verlangt, "
    "nenne sie mit ihren Messwerten; verweise nicht auf eine unsichtbare Tabelle. "
    "Ein leeres, mindestfrequenzgefiltertes Kollokationsprofil bedeutet nur, "
    "dass unter den ausgewiesenen Parametern keine Zeile zurückgegeben wurde; "
    "es beweist weder fehlende Ko-Okkurrenzen noch deren Ursache. Bezeichne "
    "Kollokatformen ohne POS- oder Kontextevidenz nicht als belegte "
    "Wortartenvorkommen und nenne eine Vollauswertung nicht Stichprobe. "
    "Berücksichtige beim Vergleich von Kollokationsprofilen, dass dieselbe "
    "absolute Mindestfrequenz für unterschiedlich häufige Knoten verschieden "
    "restriktiv ist. Trenne deshalb eine mögliche Schwellenwirkung von einer "
    "als Hypothese formulierten sprachlichen Deutung. "
    "Wenn der Nutzer eine Vergleichsbasis ausdrücklich ausschließt, benenne die "
    "dadurch entstehende Einordnungsgrenze in einem eigenen limitation-Claim; "
    "liefere trotzdem die zulässige methodische Interpretation. "
    "Vergleiche alle ausdrücklich verlangten Seiten unter vergleichbaren "
    "Parametern. Bei followup_questions formuliere unabhängige, ergebnisoffene "
    "Fragen mit sichtbarem Auslöser, ausführbarer Untersuchung und "
    "Erkenntnisziel; ohne verlangte Zahl genügen normalerweise drei. Bei "
    "method_advice liefere genau die verlangte Zahl verschiedener, ausführbarer "
    "Analyseschritte als interpretation-Claims; jeder Schritt verbindet "
    "Evidenzanker, Operation und Erkenntnisziel. Nummeriere Claims nicht selbst. "
    "Bei overview stehen mehrere inhaltliche Befunde und eine vorsichtige "
    "Synthese im Zentrum, nicht Toolstatus oder Korpusgröße. "
    "Wenn contract.response_requirements vorhanden sind, ordne einem Claim "
    "genau dann dessen response_requirement_id zu, wenn der sichtbare Claim "
    "diesen Slot vollständig und substanziell erfüllt. Eine Ankündigung, ein "
    "Slot werde später geliefert, erfüllt ihn nicht. Zusätzliche Claims tragen "
    "eine leere response_requirement_id; ein Claim darf nicht mehrere Slots "
    "nur durch Etikettierung vortäuschen. Nennt der Nutzer eine konkrete Zahl "
    "von Einheiten, ohne 'mindestens' oder einen Bereich zu formulieren, ist "
    "diese Zahl zugleich die Obergrenze: Erzeuge keine weitere unzugeordnete "
    "Einheit desselben Typs. Andere Beobachtungen, Limitationen und echte "
    "Synthesen bleiben zulässig. "
    "Bei einem Retry bleiben already_verified_do_not_repeat erhalten und werden "
    "nicht wiederholt. Repariere nur zurückgewiesene oder fehlende Teile; wenn "
    "replace_whole_deliverable=true ist, schreibe das verlangte Deliverable "
    "vollständig neu. repair_candidates sind Entwurfsmaterial, keine Evidenz. "
    "Interne IDs, Retry-Marker und Grounding-Begriffe erscheinen nie in der "
    "Nutzerantwort."
)

GROUNDING_VERIFIER_DOC = (
    "Prüfe jeden Claim ausschließlich gegen seine referenzierten observed_facts. "
    "Klassifiziere jede Claim-ID genau einmal als accepted oder rejected; beide "
    "Listen sind disjunkt und vollständig. Nenne in jedem Ablehnungsgrund die "
    "betroffene Claim-ID. Die ID-Form selbst ist bedeutungslos. "
    "Wenn ein Claim eine response_requirement_id trägt, prüfe zusätzlich den "
    "zugehörigen contract.response_requirements-Slot. Akzeptiere die Zuordnung "
    "nur, wenn claim.text den beschriebenen Antwortbestandteil vollständig und "
    "inhaltlich erfüllt und claim_kind passt. Eine bloße Ankündigung, "
    "Überschrift oder metasprachliche Wiederholung der Aufgabe ist kein "
    "erfüllter Slot. Klassifiziere deshalb zusätzlich jede bekannte "
    "response_requirement-ID genau einmal als fulfilled oder unfulfilled. "
    "Diese Slot-Klassifikation ist von der Faktengründung des Claims getrennt: "
    "Eine falsche Slot-Zuordnung macht einen sonst korrekten Claim nicht falsch, "
    "sie lässt nur den Slot offen. Verschiedene Slots brauchen verschiedene "
    "substantielle Beiträge; identische oder bloß umformulierte Claims erfüllen "
    "nicht mehrere verlangte Einheiten. Mehrere Slots mit identischer "
    "description und source_quote materialisieren eine gezählte Gruppe: Jeder "
    "einzelne Slot steht genau für eine atomare Einheit dieser Gruppe. Verlange "
    "von einem einzelnen Claim niemals die Gesamtzahl aus dem pluralischen "
    "source_quote; die Gesamtzahl wird allein durch die vollständige "
    "Slot-Partition geprüft. Eine konkret gezählte Einheit ohne "
    "Mindest- oder Bereichsmarker ist exakt: Lehne zusätzliche unzugeordnete "
    "Claims nur dann ab, wenn sie semantisch eine weitere Einheit genau dieser "
    "gezählten Gruppe darstellen; unabhängige Beobachtungen, Grenzen oder "
    "Synthesen dürfen nicht als Übererfüllung verworfen werden. "
    "Wenn ein Claim mehrere fact_ids trägt, klassifiziere zusätzlich jeden "
    "dieser Facts genau einmal als used oder unused. used bedeutet, dass der "
    "Fact eine tatsächlich formulierte empirische Prämisse, Beobachtung oder "
    "Reichweitengrenze des Claims trägt. Eine nur angehängte ID ist unused und "
    "darf keine Evidenzabdeckung vortäuschen. Ein atomarer Claim darf mehrere "
    "Facts gemeinsam synthetisieren; lehne ihn niemals allein deshalb ab, weil "
    "kein einzelner Fact für sich bereits die gesamte Synthese ausdrückt. "
    "Freie Interpretation bleibt "
    "zulässig; sie muss den verwendeten Fact nicht mechanisch paraphrasieren. "
    "Lehne erfundene oder falsch gebundene Zahlen, Zitate, Beispiele, Ränge und "
    "Beziehungen sowie falsche Einheiten, Scopes oder Exactness ab. Eine neue "
    "analytische Kategorie ist als begrenzte Interpretation oder Hypothese "
    "zulässig, aber nicht als beobachteter Fakt. Getrennte Fakten belegen ohne "
    "relationale Evidenz keine "
    "Korrelation oder Ursache. Behaupte niemals, Evidenz fehle, wenn passende "
    "observed_facts sichtbar sind. Eine Korpuspassage belegt eine Äußerung der "
    "Quelle, nicht deren externe Wahrheit. "
    "Interpretation ist erwünscht: Akzeptiere plausible, vorsichtig formulierte "
    "Synthesen und Hypothesen, wenn ihre empirischen Prämissen gedeckt sind und "
    "ihre Reichweite stimmt; der interpretative Wortlaut muss nicht im Fact "
    "stehen. Forschungsfragen brauchen belegte Motivation, nicht eine bereits "
    "belegte künftige Antwort. Methodenvorschläge dürfen neue, ergebnisoffene "
    "Analysen entwerfen. "
    "Eine falsifizierbare Hypothese muss keine unbelegte Prozentgrenze nennen; "
    "eine relationale Erwartung plus mögliches Gegenmuster genügt. Partielle "
    "KWIC-Beispiele dürfen solche Hypothesen motivieren, aber ohne explizite "
    "Kontextkodierung keine beobachtete Häufigkeitsverteilung darstellen. "
    "Prüfe bei einem ausdrücklich als Hypothese markierten Claim nur die "
    "sichtbare Motivation als bereits beobachtete Prämisse. Seine Vorhersage "
    "für eine spätere Vollauswertung und das mögliche Gegenresultat sind "
    "prospektiv; lehne sie nicht ab, weil diese Auswertung noch nicht vorliegt. "
    "Ein Hypothesen-Claim soll Erwartung und Gegenmuster enthalten, aber nicht "
    "zusätzlich Beobachtung, Limitation und Prüfbericht in eine Proposition "
    "packen. Als Widerlegung zählt ein mögliches Ergebnis einer ausführbaren "
    "Untersuchung am aktiven Korpus; ein erfundener Befund aus einem nur "
    "vorgestellten anderen Korpus trägt den Claim nicht. Akzeptiere keine "
    "willkürlich ergänzten Prozentgrenzen oder numerischen Methodenparameter; "
    "eine relationale Sensitivitätsprüfung genügt. "
    "Die vom Nutzer gewünschte Schlussrichtung ist kein Akzeptanzkriterium. "
    "Wenn eine Frage einseitige Bestätigung oder einen universellen Schluss "
    "erzwingt, akzeptiere eine belegte Zurückweisung dieser Prämisse sowie "
    "begrenzte Gegen- oder Mischbefunde. Verwirf sie nicht bloß deshalb, weil "
    "sie der verlangten Bestätigung widersprechen. Beurteile dabei jeden Claim "
    "in seiner eigenen ausdrücklich formulierten Reichweite: Eine lokale, "
    "fact-gebundene Interpretation muss die Universalhypothese nicht beweisen, "
    "und eine belegte Scope-Limitation darf sie ausdrücklich nicht bestätigen. "
    "Lehne einen solchen atomaren Claim nicht allein wegen fehlender Evidenz "
    "für die viel stärkere Universalhypothese ab. "
    "Bei semantischen Trefferlisten bedeutet ein hoher Rang Ähnlichkeit zur "
    "Suchanfrage und niemals häufiges Auftreten oder thematische Zentralität im "
    "Korpus. Eine Quellenpassage, die das Wort 'zentral' selbst erwähnt, bleibt "
    "davon unberührt, sofern der Claim diese Stimme sichtbar markiert. Prüfe Behauptungen "
    "wie 'alle sichtbaren Treffer' gegen jeden sichtbaren Kandidaten; ein "
    "unklarer, themenferner oder gegenläufiger Kandidat widerlegt diese "
    "Vollständigkeitsformulierung. "
    "Rang- und Frequenzzeilen allein belegen keine Satzposition. Prüfe außerdem, "
    "ob ausdrücklich verlangte Zeilen und Messwerte tatsächlich im Claim stehen "
    "oder nur auf eine nicht vorhandene Tabelle verwiesen wird. "
    "Ein leeres, schwellenwertbegrenztes Kollokationsprofil belegt keine "
    "Abwesenheit von Ko-Okkurrenzen und keine kausale Erklärung durch die "
    "Knotenfrequenz. Oberflächenformen in einer Kollokattabelle belegen ohne "
    "POS- oder KWIC-Evidenz keine Wortartenzusammensetzung. "
    "Bei der Deutung eines KWIC-Belegs prüfe Sprecher, Adressat, Referenten, "
    "Negation und syntaktische Anbindung gegen das Zitat. Lehne Rollenwechsel, "
    "umgekehrte Polarität, neue Beteiligte und die Auflösung einer im Beleg "
    "offenen Anbindung ab; vorsichtig markierte Mehrdeutigkeit ist zulässig. "
    "Eine interpretierende Paraphrase darf abstrahieren, muss aber Polarität, "
    "Handelnden, Gegenstand und Ereignistyp der sichtbaren Prädikation bewahren; "
    "ein stärkeres oder anderes Prädikat ist nicht durch denselben Beleg gedeckt. "
    "Akzeptiere eine Inhaltsparaphrase erst, wenn jedes von ihr behauptete "
    "Ereignis mit demselben sichtbaren Prädikat, denselben Beteiligten und "
    "derselben Relation wiedergegeben ist. Ein vermeintliches Synonym darf "
    "keine neue Handlung oder Teilnehmerrelation erzeugen. "
    "Wenn zwei Claims denselben analytischen Punkt ausdrücken und einer ihn "
    "ohne neue unbelegte Prämisse präziser fasst, akzeptiere den präziseren und "
    "verwirf den schwächeren als redundant; nenne im Ablehnungsgrund beide "
    "Claim-IDs. Verschiedene begründete Lesarten bleiben getrennte Claims. "
    "Wenn retrieval_candidate_fact_ids vorliegen, klassifiziere auch jeden davon "
    "genau einmal als accounted oder unaccounted. Prüfe dabei relevante, "
    "widersprechende, unklare und themenferne Treffer gegen die beanspruchte "
    "Reichweite; ein lokal begrenzter Claim muss nicht jeden irrelevanten Treffer "
    "im Text nennen. "
    "Ein Fehler verwirft nie unabhängige tragfähige Claims. Wähle pass, wenn alle "
    "Claims akzeptiert sind; retry nur, wenn derselbe Evidenzstand eine konkrete "
    "Reparatur erlaubt; sonst conservative_only. Underclaiming und "
    "mechanische Paraphrase sind ebenso Qualitätsfehler wie Overclaiming."
)

KWIC_RELATION_ADJUDICATOR_DOC = (
    "Prüfe ausschließlich die lokale Quellenrelation jedes gelieferten Claims. "
    "Quelle sind nur statement und grounding_quotes der referenzierten Facts. "
    "Vergleiche Prädikat, Polarität, Beteiligte, Bewertungsobjekt, Stimme und "
    "syntaktische Anbindung. Akzeptiere gehaltvolle lokale Deutungen wie Kritik, "
    "Rahmung oder Positionierung; analytische Begriffe müssen nicht wörtlich in "
    "der Passage stehen. Mehrere referenzierte Passagen dürfen gemeinsam eine "
    "auf die sichtbare Auswahl begrenzte Synthese tragen. "
    "Prüfe niemals die externe Wahrheit der zitierten Proposition: Wenn die "
    "Passage P äußert, trägt sie den lokalen Claim, dass die Passage P äußert "
    "oder entsprechend rahmt, auch wenn P falsch, unbelegt oder kontextarm ist. "
    "Eine relationsgleiche Verbparaphrase ist zulässig. "
    "Bestimme auf beiden Seiten zuerst den grammatischen Kopf von Subjekt, "
    "Prädikat und Objekt oder Komplement. Ein Modifikator oder eine von-Phrase "
    "darf nicht an die Stelle ihres Kopfes treten; 'N von X' ist nicht X, und "
    "bei 'X fordert Y' bleiben X und Y in ihren Rollen. Bewahre "
    "relationsbegrenzende Wörter wie gegenseitig, untereinander, jeweils, nur, "
    "alle, kein und zeitliche Marker, sobald der Claim die betroffene "
    "Proposition wiedergibt. Ein distributives Adverb wie 'einzeln' darf im "
    "Claim nicht zum indefiniten Determinierer 'einzelne' werden; das ändert "
    "die Reichweite. Eine Interpretation darf genau eine quellennahe "
    "analytische Abstraktion ergänzen, aber keine unbelegte Kette aus "
    "Zentralität, Erfolg, Strategie, Verantwortung, Pflicht oder Intention. "
    "Parallele Erwartungen an zwei Beteiligte sind ohne sichtbaren Marker "
    "keine gegenseitige oder wechselseitige Relation. Eine angeblich konkrete "
    "Empfehlung muss die konkrete Handlung im Quelltext zeigen; ein bloßer "
    "Oberbegriff wie Beitrag, Maßnahme oder Handlung genügt nicht. Ein "
    "institutioneller Eigenname belegt keine ungenannte Ortsangabe. "
    "Repariere unbekannte oder fehlerhafte Quellwörter "
    "nicht stillschweigend; zitiere sie oder markiere die Lesart als unsicher. "
    "Eine im Quelltext genannte Zahl bleibt Zahl innerhalb der wiedergegebenen "
    "Äußerung und wird nicht ohne Kennzeichnung zur externen Tatsache. "
    "Metasprachliche Marker wie Begriff, Wort, Ausdruck oder Zitat trennen "
    "Erwähnung von eigenem Gebrauch und müssen in der Stimmenanalyse erhalten "
    "bleiben. "
    "Lehne nur eine konkrete Relationsabweichung ab: erfundene oder vertauschte "
    "Beteiligte, ein anderes oder stärkeres Prädikat, veränderte Polarität, "
    "aufgelöste Mehrdeutigkeit, erfundener Entitätstyp, unbelegte Kausalität "
    "oder korpusweite Reichweite. Eine nackte Passage weist keinen Autor oder "
    "Sprecher aus. Satzgrenze, Nachbarschaft und fehlende Interpunktion sind "
    "keine Kausalmarker; ein sichtbares 'wegen' trägt nur seine eigene Klausel. "
    "Die äquivalente Umstellung 'Y wegen X' zu 'X wird als Ursache von Y "
    "dargestellt' ist zulässig, solange X, Y und Stärke unverändert bleiben. "
    "Bewertende Bezeichnungen bleiben zeichengetreues Zitat oder werden als "
    "Wortwahl der Passage benannt; ihre Neutralisierung oder Verschärfung ist "
    "predicate_shift. Behaupte nie, ein Name oder Ausdruck fehle, wenn er im "
    "vollständigen statement oder in grounding_quotes steht. "
    "Klassifiziere jede Claim-ID genau einmal. source_relation gibt knapp "
    "Subjekt, Prädikat, Objekt oder Komplement, Skopusmarker und Stimme der "
    "Quelle wieder; claim_relation dieselben Rollen des Claims. Bei "
    "accept ist mismatch none; bei reject benennt mismatch die wichtigste "
    "konkrete Abweichung. Formuliere keine Ersatzantwort."
)


def _compact_text(value: Any, limit: int = 220) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, str):
        compact = " ".join(value.split())
    else:
        try:
            compact = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:
            compact = str(value)
        compact = " ".join(compact.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


_SENTENCE_END_PATTERN = re.compile(r"[.!?](?:['\"«»)\]]*)(?=\s|$)")


def _compact_sentences(value: Any, limit: int = 220) -> str:
    """Satz-schonende Kompaktion fuer Limitations-/Statement-Zeilen (H6/B2).

    Schneidet am letzten vollstaendigen Satzende vor ``limit``. Passt kein
    Satz in das Limit, bleibt der ERSTE Satz vollstaendig erhalten (auch wenn
    er laenger ist). Nur ohne erkennbare Satzgrenze faellt die Funktion auf
    eine Wortgrenzen-Kappung mit ``...`` zurueck. ``_compact_text`` selbst
    bleibt unveraendert und global im Einsatz.
    """

    compact = _compact_text(value, limit=sys.maxsize)
    if len(compact) <= limit:
        return compact
    sentence_ends = [
        match.end() for match in _SENTENCE_END_PATTERN.finditer(compact)
    ]
    fitting = [end for end in sentence_ends if end <= limit]
    if fitting:
        return compact[: fitting[-1]].rstrip()
    if sentence_ends:
        return compact[: sentence_ends[0]].rstrip()
    return _compact_quote(compact, limit)


def _compact_quote(value: Any, limit: int = 70) -> str:
    """Zitat-Kappung auf Wortgrenze: kein angebrochenes Wort vor ``...``."""

    compact = _compact_text(value, limit=sys.maxsize)
    if len(compact) <= limit:
        return compact
    cut = compact[: limit - 3]
    if " " in cut:
        head, _, tail = cut.rpartition(" ")
        # Nur das angebrochene Wort fallen lassen, nie den ganzen Text.
        if head and len(tail) < len(cut):
            cut = head
    return cut.rstrip() + "..."


def _normalise_claim_text(value: Any) -> str:
    """Keep model-owned prose intact and never cut it in the middle of a sentence."""

    if value in (None, "", [], {}):
        return ""
    compact = " ".join(strip_llm_protocol_tail(str(value)).split())
    # Some JSON-schema providers occasionally place their closing object brace
    # inside the final string value. Remove only an unmatched terminal brace;
    # balanced braces (for example in a displayed query) remain untouched.
    while compact.endswith("}") and compact.count("}") > compact.count("{"):
        compact = compact[:-1].rstrip()
    if len(compact) <= MAX_CLAIM_TEXT_CHARS:
        return compact

    bounded = compact[:MAX_CLAIM_TEXT_CHARS]
    sentence_ends = [
        match.end()
        for match in re.finditer(r"[.!?](?=\s|$)", bounded)
    ]
    if sentence_ends and sentence_ends[-1] >= MAX_CLAIM_TEXT_CHARS // 2:
        return bounded[: sentence_ends[-1]].rstrip()

    # A provider can still ignore schema length constraints. In that rare case,
    # cut only at a word boundary instead of leaking a broken token to the UI.
    word_boundary = bounded.rfind(" ")
    if word_boundary >= MAX_CLAIM_TEXT_CHARS // 2:
        bounded = bounded[:word_boundary]
    return bounded.rstrip(" ,;:-") + "..."


def _user_facing_evidence_gap(value: Any, *, limit: int = 220) -> str:
    text = _compact_text(value, limit)
    if not text:
        return ""
    if _has_any_phrase(
        _normalised_question_text(text),
        (
            "synthesefenster",
            "für die synthese",
            "fuer die synthese",
            "grounding_rows_visible",
            "belegten fakten passten nicht",
            "vorläufig fehlende vertragsevidenz",
            "vorlaeufig fehlende vertragsevidenz",
        ),
    ):
        return ""
    evidence_labels = {
        "kwic_rows": _t("KWIC-Belege", 'concordance lines'),
        "frequency_rows": _t("Frequenzzeilen", 'frequency rows'),
        "lexical_frequency_rows": _t("lexikalische Frequenzzeilen", 'lexical frequency rows'),
        "content_rows": _t("inhaltliche Belege", 'content evidence'),
        "contextual_rows": _t("kontextuelle oder semantische Belege", 'contextual or semantic evidence'),
        "metric_rows": _t("statistische Ergebniszeilen", 'statistical result rows'),
        "dispersion_profile": _t("Dispersionswerte", 'dispersion values'),
        "document_rows": _t("Dokumentbelege", 'document evidence'),
        "documentation_rows": _t("Dokumentationsbelege", 'documentation evidence'),
        "metadata_rows": _t("Metadatenwerte", 'metadata values'),
        "semantic_rows": _t("semantische Treffer", 'semantic matches'),
        "cluster_rows": _t("Clusterbelege", 'cluster evidence'),
        "total_hits": _t("Trefferzahl", 'hit count'),
    }
    for internal_name, label in evidence_labels.items():
        text = re.sub(
            rf"\b{re.escape(internal_name)}\b",
            label,
            text,
            flags=re.IGNORECASE,
        )
    text = re.sub(
        r"\bvertraglich geforderte Evidenz\b",
        _t("für die angeforderte Analyse nötige Evidenz", 'evidence needed for the requested analysis'),
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s*\(\s*truncated\s*=\s*true\s*\)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\btruncated\s*=\s*true\b",
        _t("auf sichtbare Top-N-Ergebnisse begrenzt", 'limited to the visible top-N results'),
        text,
        flags=re.IGNORECASE,
    )
    return _compact_text(text, limit)


def _format_log_ratio_metric(row: Dict[str, Any]) -> str:
    """Render a contrast row's ``log_ratio`` honestly.

    The ``+/-10`` sentinel that used to flag one-sided collocates is gone: rows
    now carry an explicit ``one_sided`` boolean and an honest smoothed
    ``log_ratio``. When ``one_sided`` is set we say the collocate is only
    attested on one side (ratio one-sided, smoothed) instead of quoting the raw
    number as if it were an exact multiple.
    """
    value = row.get("log_ratio")
    if value in (None, ""):
        return ""
    if bool(row.get("one_sided")):
        return (
            _t(f"log_ratio={value} (nur einseitig belegt; Verhaeltnis einseitig, geglaettet)", f"""log_ratio={value} (attested on one side only, ratio smoothed)""")
        )
    return f"log_ratio={value}"


def _compact_id(value: Any, limit: int = 96) -> str:
    """Compact an identifier to ``limit`` chars WITHOUT losing uniqueness.

    Unlike :func:`_compact_text` (which truncates with an ellipsis and so makes
    long ids collide), this keeps a readable prefix and appends a short hash of
    the full id, so distinct long ids stay distinct.
    """
    if value in (None, "", [], {}):
        return ""
    text = value if isinstance(value, str) else str(value)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    digest = hashlib.blake2s(text.encode("utf-8"), digest_size=6).hexdigest()  # 12 chars
    keep = max(8, limit - len(digest) - 1)
    return f"{text[:keep]}~{digest}"


def _normalise_text_list(values: Any, *, max_items: int, item_limit: int) -> List[str]:
    if values in (None, "", [], {}):
        return []
    if not isinstance(values, list):
        values = [values]
    result: List[str] = []
    seen: set[str] = set()
    for item in values:
        text = _compact_text(item, item_limit)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= max_items:
            break
    return result


def _normalise_claim_id_list(values: Any) -> List[str]:
    if values in (None, "", [], {}):
        return []
    raw_values = values if isinstance(values, list) else [values]
    result: List[str] = []
    seen: set[str] = set()
    for item in raw_values[:MAX_VERDICT_CLAIM_IDS]:
        if isinstance(item, dict):
            item = next(
                (
                    item.get(key)
                    for key in ("id", "claim_id")
                    if item.get(key) not in (None, "")
                ),
                "",
            )
        claim_id = _compact_id(item, CLAIM_ID_LIMIT)
        if not claim_id or claim_id in seen:
            continue
        seen.add(claim_id)
        result.append(claim_id)
    return result


def _normalise_enum(value: Any, allowed: Iterable[str], default: str) -> str:
    text = str(value or "").strip()
    return text if text in set(allowed) else default


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    """Parse provider booleans without treating the string ``"false"`` as true."""

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    text = str(value or "").strip().casefold()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    return default


def _extract_json(text: str) -> Any:
    text = str(text or "").strip()
    if not text:
        return None
    for candidate in (text, text.strip("`")):
        try:
            return json.loads(candidate)
        except Exception:
            continue
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except Exception:
        return None


@dataclass(frozen=True)
class ResponseRequirement:
    id: str
    description: str
    claim_kind: str = "interpretation"
    source_quote: str = ""

    @classmethod
    def from_raw(
        cls,
        raw: Any,
        *,
        fallback_id: str = "requirement",
        question_text: str = "",
    ) -> "ResponseRequirement | None":
        if isinstance(raw, cls):
            return raw
        if not isinstance(raw, dict):
            return None
        source_quote = _compact_text(
            raw.get("source_quote", ""),
            MAX_RESPONSE_REQUIREMENT_CHARS,
        )
        if question_text:
            if not source_quote or (
                not _source_quote_is_bounded_question_span(
                    source_quote,
                    question_text,
                )
            ):
                return None
            # The user's own wording is the authoritative slot description.
            # Model-written paraphrases can silently invent extra analytical
            # obligations (for example an unrequested metric or method).
            description = source_quote
        else:
            description = _compact_text(
                raw.get("description", "") or source_quote,
                MAX_RESPONSE_REQUIREMENT_CHARS,
            )
        if not description:
            return None
        return cls(
            id=(
                _compact_id(raw.get("id", ""), CLAIM_ID_LIMIT)
                or _compact_id(fallback_id, CLAIM_ID_LIMIT)
                or "requirement"
            ),
            description=description,
            claim_kind=_normalise_enum(
                _CLAIM_KIND_ALIASES.get(
                    str(raw.get("claim_kind") or "").strip().casefold(),
                    raw.get("claim_kind"),
                ),
                CLAIM_KINDS,
                "interpretation",
            ),
            source_quote=source_quote,
        )

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)

    def completion_checks(self) -> List[str]:
        """Expose structural slot duties without prescribing its content."""

        surface = " ".join(
            part
            for part in (self.description, self.source_quote)
            if str(part or "").strip()
        )
        checks = [
            "Der sichtbare Claim enthält genau eine atomare analytische Einheit."
        ]
        if _RESPONSE_REQUIREMENT_HYPOTHESIS_PATTERN.search(surface):
            checks.extend(
                [
                    "claim_kind ist interpretation und assertion_level ist tentative.",
                    "Der sichtbare Text kennzeichnet die Aussage erkennbar als Hypothese.",
                ]
            )
        if _RESPONSE_REQUIREMENT_FALSIFIER_PATTERN.search(surface):
            checks.append(
                "Derselbe Claim nennt ein mögliches Ergebnis einer "
                "vollständigen Auswertung des aktiven Korpus, das dieser "
                "Hypothese logisch widerspricht oder sie schwächt; weder ein "
                "anderes Korpus noch eine zweite Interpretation erfüllt diese "
                "Bedingung."
            )
        if _RESPONSE_REQUIREMENT_LIMITATION_PATTERN.search(surface):
            checks.append(
                "Der sichtbare Text benennt die verlangte Limitation oder "
                "Reichweitengrenze ausdrücklich."
            )
        return checks

_RESPONSE_REQUEST_VERB_PATTERN = re.compile(
    r"\b(?:formuliere|formulieren\s+sie|entwickle|entwickeln\s+sie|"
    r"diskutiere|diskutieren\s+sie|erläutere|erlaeutere|"
    r"erläutern\s+sie|erlaeutern\s+sie|erklär\w*|erklaer\w*|"
    r"explain\w*|nenne|nennen\s+sie|gib|"
    r"geben\s+sie|leite|leiten\s+sie|skizziere|skizzieren\s+sie|"
    r"schlage|schlagen\s+sie|beachte|beachten\s+sie|arbeite|"
    r"arbeiten\s+sie|trenn\w*|separat\w*|formulate|"
    r"empfiehl\w*|recommend\w*|develop|discuss|state|name|derive|"
    r"outline|suggest|acknowledge|empfehl\w*|untersuch\w*|bericht\w*|"
    r"report\w*)\b",
    re.IGNORECASE,
)


def _source_quote_is_bounded_question_span(
    source_quote: str,
    question_text: str,
) -> bool:
    """Accept a user span only at token boundaries, never inside a negation."""

    quote = _normalised_question_text(source_quote)
    question = _normalised_question_text(question_text)
    if not quote or not question:
        return False
    start = 0
    while True:
        index = question.find(quote, start)
        if index < 0:
            return False
        end = index + len(quote)
        left_ok = index == 0 or not question[index - 1].isalnum()
        right_ok = end == len(question) or not question[end].isalnum()
        if left_ok and right_ok:
            return True
        start = index + 1


def _response_text_tokens(text: str) -> Tuple[str, ...]:
    return tuple(
        re.findall(r"\w+", _normalised_question_text(text), re.UNICODE)
    )


def _tokens_are_contiguous_span(
    candidate: Sequence[str],
    container: Sequence[str],
) -> bool:
    if not candidate or len(candidate) > len(container):
        return False
    width = len(candidate)
    return any(
        tuple(container[start : start + width]) == tuple(candidate)
        for start in range(len(container) - width + 1)
    )


@dataclass
class EvidenceItem:
    id: str
    tool: str
    tool_call_id: str
    query: str
    status: str
    truncated: bool
    grounding_truncated: bool = False
    result_scope: Dict[str, Any] = field(default_factory=dict)
    payload_preview: str = ""
    raw_surface: Dict[str, Any] = field(default_factory=dict)
    fact_surface: Dict[str, Any] = field(default_factory=dict)
    grounding_surface: List[str] = field(default_factory=list)
    # Die Zeilen der grounding_surface, die die EIGENE Eingabe des Modells
    # wiederholen (Analysebegriff, Werkzeugargumente, zurueckgespiegelte
    # Abfrage). Sie stehen weiter in grounding_surface, damit der
    # Modellkontext unveraendert bleibt, sind hier aber nach HERKUNFT
    # markiert. Die Zitatwache schliesst sie darueber aus.
    #
    # Vorher wurden sie per Zeichenkettenvergleich gefiltert, und das war
    # umgehbar: ein Anfuehrungszeichen, ein doppeltes Leerzeichen, die
    # 512-Zeichen-Kuerzung oder die JSON-Maskierung einer CQL-Abfrage
    # brachen den Vergleich, und das Fabrikat deckte sich wieder selbst.
    # Herkunft laesst sich nicht umformatieren.
    eingabe_surface: List[str] = field(default_factory=list)
    raw_ref: str = ""
    analysis_family: str = ""
    partial: bool = False
    sampled: bool = False

    def to_dict(self, *, include_fact_surface: bool = True) -> Dict[str, Any]:
        result = asdict(self)
        if not include_fact_surface:
            result.pop("fact_surface", None)
        return result


@dataclass
class EvidenceBundle:
    contract: Dict[str, Any]
    items: List[Dict[str, Any]]
    tool_sequence: List[str] = field(default_factory=list)
    grounding_surface: List[str] = field(default_factory=list)
    present_evidence: List[str] = field(default_factory=list)
    missing_required_evidence: List[str] = field(default_factory=list)
    incomplete_reason: str = ""
    supports_full_answer: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ObservedFact:
    id: str
    statement: str
    fact_kind: str
    source_evidence_ids: List[str] = field(default_factory=list)
    grounding_quotes: List[str] = field(default_factory=list)
    exactness: str = "exact"
    supports_claims: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    _untrusted_model_fact: bool = field(
        default=False,
        repr=False,
        compare=False,
    )

    @classmethod
    def from_raw(cls, raw: Any) -> "ObservedFact | None":
        if not isinstance(raw, dict):
            return None
        statement = _compact_text(raw.get("statement", ""), 280)
        if not statement:
            return None
        return cls(
            id=_compact_id(raw.get("id", ""), 96)
            or f"fact_{abs(hash(statement)) % 100000}",
            statement=statement,
            fact_kind=_normalise_enum(raw.get("fact_kind"), FACT_KINDS, "metadata"),
            source_evidence_ids=_normalise_text_list(
                raw.get("source_evidence_ids"),
                max_items=6,
                item_limit=96,
            ),
            grounding_quotes=_normalise_text_list(raw.get("grounding_quotes"), max_items=16, item_limit=220),
            exactness=_normalise_enum(
                raw.get("exactness"),
                EXACTNESS_VALUES,
                "derived",
            ),
            supports_claims=[
                item
                for item in _normalise_text_list(
                    raw.get("supports_claims"),
                    max_items=6,
                    item_limit=40,
                )
                if item in CLAIM_SUPPORT_VALUES
            ],
            limitations=_normalise_text_list(raw.get("limitations"), max_items=4, item_limit=160),
            _untrusted_model_fact=True,
        )

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.pop("_untrusted_model_fact", None)
        return payload


_INTERNAL_FACT_REFERENCE_PATTERN = re.compile(
    r"\s*(?:"
    r"\((?:(?:siehe|vgl\.?|see|cf\.?|laut)\s+)?"
    r"(?:(?:IDs?|Facts?)\s+)?f\d{3}"
    r"(?:\s*(?:,|\+|[–—-]|\bund\b|\band\b)\s*f?\d{3})*\)"
    r"|\[(?:f\d{3})(?:\s*(?:,|\+|[–—-]|\bund\b|\band\b)\s*f?\d{3})*\]"
    r"|\b(?:mit|unter|with)\s+(?:(?:der|den|the)\s+)?"
    r"(?:(?:IDs?|Facts?)\s+)f\d{3}"
    r"(?:\s*(?:,|[–—-])\s*f?\d{3})*"
    r"|\b(?:IDs?|Facts?)\s+f\d{3}(?:\s*(?:,|[–—-])\s*f?\d{3})*"
    r"|\bf\d{3}(?:\s*(?:,|\+|[–—-]|\bund\b|\band\b)\s*f?\d{3})+\b"
    r"|\bf\d{3}\b"
    r")",
    re.IGNORECASE,
)
_RESPONSE_REQUIREMENT_ANNOUNCEMENT_PATTERN = re.compile(
    r"^(?:auf\s+(?:basis|grundlage)\b[^.!?]{0,180}\b)?"
    r"(?:lassen\s+sich|können|koennen|werden)\b[^.!?]{0,180}"
    r"\b(?:formulier\w*|darstell\w*|nenn\w*|aufführ\w*|"
    r"auffuehr\w*|folgen)\b\s*[:.]?$",
    re.IGNORECASE,
)
_RESPONSE_REQUIREMENT_HEADING_PATTERN = re.compile(
    r"^(?:hypothese|deutung|interpretation|beobachtung|limitation|"
    r"einschränkung|einschraenkung|forschungsfrage|research\s+question|"
    r"schritt|step)(?:\s+(?:nr\.?\s*)?\d+)?\s*[:.]?$",
    re.IGNORECASE,
)
_RESPONSE_REQUIREMENT_FALSIFIER_PATTERN = re.compile(
    r"\b(?:widerleg\w*|falsifiz\w*|gegenbefund\w*|"
    r"counter[- ]?evidence|falsif\w*|refut\w*)\b",
    re.IGNORECASE,
)
_RESPONSE_CLAIM_FALSIFIER_PATTERN = re.compile(
    r"\b(?:widerleg\w*|falsifiz\w*|entkräft\w*|entkraeft\w*|"
    r"schwäch\w*|schwaech\w*|gegen(?:befund|muster)\w*|"
    r"counter[- ]?evidence|falsif\w*|"
    r"refut\w*|weaken\w*)\b|"
    r"\bdagegen\s+(?:spräch|spraech|spricht)\w*\b",
    re.IGNORECASE,
)
_RESPONSE_CLAIM_EXTERNAL_CORPUS_FALSIFIER_PATTERN = re.compile(
    r"\b(?:gegen|vergleichs|referenz)[- ]?korpus\w*\b|"
    r"\b(?:ander\w*|zweite\w*|fremde\w*)\s+korpus\w*\b|"
    r"\b(?:another|different|comparison|reference)\s+corpus\b",
    re.IGNORECASE,
)
_RESPONSE_CLAIM_FALSIFIER_MODALITY_PATTERN = re.compile(
    r"\b(?:wäre|waere|würde|wuerde|könnte|koennte|möglich\w*|"
    r"moeglich\w*|wenn|falls|dagegen\s+(?:spräch|spraech|spricht)\w*|"
    r"would|could|if|possible\w*)\b",
    re.IGNORECASE,
)
_RESPONSE_CLAIM_INVALID_FALSIFIER_PATTERN = re.compile(
    r"\b(?:nicht|nie|niemals|kaum|bislang\s+nicht|bisher\s+nicht)\b"
    r"[^.!?\n]{0,36}\b(?:widerleg\w*|falsifiz\w*|entkräft\w*|"
    r"entkraeft\w*|refut\w*|falsif\w*)\b|"
    r"\b(?:widerleg\w*|falsifiz\w*|entkräft\w*|entkraeft\w*|"
    r"refut\w*|falsif\w*)\b[^.!?\n]{0,36}"
    r"\b(?:unmöglich\w*|unmoeglich\w*|ausgeschlossen\w*|impossible\w*)\b",
    re.IGNORECASE,
)
_RESPONSE_CLAIM_EMPIRICAL_COUNTER_RESULT_PATTERN = re.compile(
    r"\b(?:kein(?:e|en|er|es)?|ohne|ausbleib\w*|fehl\w*|"
    r"gleich\w*|ähnlich\w*|aehnlich\w*|selb\w*|homogen\w*|"
    r"neutral\w*|abweich\w*|anders|dominier\w*|"
    r"überwieg\w*|ueberwieg\w*|outweigh\w*|"
    r"gegenläufig\w*|gegenlaeufig\w*|gegenteilig\w*|"
    r"entgegengesetzt\w*|umgekehrt\w*|häufiger\w*|haeufiger\w*|"
    r"seltener\w*|mehr|weniger|steig\w*|sink\w*|zunehm\w*|"
    r"abnehm\w*|verschwind\w*|ausschließlich\w*|ausschliesslich\w*|"
    r"none|no|without|absen\w*|missing|same|similar\w*|equal\w*|"
    r"homogeneous\w*|opposite\w*|reverse\w*|higher|lower|increase\w*|"
    r"decrease\w*|disappear\w*|only)\b",
    re.IGNORECASE,
)
_RESPONSE_REQUIREMENT_LIMITATION_PATTERN = re.compile(
    r"\b(?:limitation\w*|einschränk\w*|einschraenk\w*|"
    r"reichweitengrenz\w*|caveat\w*)\b",
    re.IGNORECASE,
)
_RESPONSE_CLAIM_LIMITATION_PATTERN = re.compile(
    r"\b(?:limitation\w*|einschränk\w*|einschraenk\w*|begrenz\w*|"
    r"reichweit\w*|nur\s+(?:die|der|den|im|in|unter|sichtbar)|"
    r"top[- ]?n|stichprob\w*|sample\w*|schwellenwert\w*|"
    r"mindestfrequenz\w*|min_freq)\b|"
    r"\b(?:nicht|kein\w*)\s+(?:belegt|ableitbar|ausgewiesen|erfasst)\b|"
    r"\bnur\b[^.!?\n]{0,80}\b(?:sichtbar|belegt|ausgewiesen|erfasst)\b",
    re.IGNORECASE,
)
_RESPONSE_REQUIREMENT_HYPOTHESIS_PATTERN = re.compile(
    r"\bhypothes\w*\b",
    re.IGNORECASE,
)
_RESPONSE_CLAIM_HYPOTHESIS_PATTERN = re.compile(
    r"\bhypothes\w*\b|\b(?:prüfbar|pruefbar|zu\s+prüf\w*|"
    r"zu\s+pruef\w*)\b|\b(?:möglich\w*|moeglich\w*)\s+"
    r"(?:deutung|erklärung|erklaerung)\w*\b|\bkönnt\w*\b|\bkoennt\w*\b",
    re.IGNORECASE,
)
_HYPOTHESIS_PROPOSAL_PATTERN = re.compile(
    r"^\s*(?:"
    r"hypothese(?:\s+(?:nr\.?\s*)?\d+)?"
    r"(?:\s*\([^)]{1,40}\))?\s*(?::|lautet\b|besagt\b|ist\b)|"
    r"(?:eine|die)\s+(?:(?:erste|zweite|dritte|vierte|prüfbare|"
    r"pruefbare|mögliche|moegliche|konkurrierende|alternative)\s+){0,4}"
    r"hypothese\b[^.!?\n]{0,80}\b(?:lautet|besagt|ist)\b|"
    r"als\s+(?:eine\s+)?(?:(?:prüfbare|pruefbare|zu\s+prüf\w*|"
    r"zu\s+pruef\w*|mögliche|moegliche|"
    r"konkurrierende|alternative)\s+){0,3}hypothese\b"
    r")",
    re.IGNORECASE,
)
_HYPOTHESIS_SELF_REFERENCE_PATTERN = re.compile(
    r"\b(?:diese|die|jene|this|the)\s+hypothes\w*\b",
    re.IGNORECASE,
)

_TENTATIVE_INTERPRETATION_SURFACE_PATTERN = re.compile(
    r"\b(?:könnt\w*|koennt\w*|dürft\w*|duerft\w*|"
    r"möglicherweise|moeglicherweise|hypothese\w*|"
    r"vereinbar\s+mit|legt\w*[^.!?\n]{0,100}\bnahe|"
    r"deut\w*[^.!?\n]{0,100}\b(?:darauf|hin)|"
    r"sprich\w*[^.!?\n]{0,100}\b(?:dafür|dafuer|für|fuer))\b",
    re.IGNORECASE,
)
_ANALYTICAL_CLAIM_LABEL_PATTERN = re.compile(
    r"(?im)(?:^|(?<=[.;!?])\s+|<br\s*/?>\s*)\*{0,2}"
    r"(?:beobachtung|observation|interpretation|deutung|"
    r"hypothese|hypothesis)(?:\s+(?:nr\.?\s*)?\d+)?"
    r"\*{0,2}\s*(?::|[–—-])",
)
_ALTERNATIVE_HYPOTHESIS_PATTERN = re.compile(
    r"[;.!?]\s*(?:als\s+)?(?:eine\s+)?(?:alternative|alternativ|"
    r"konkurrierende|demgegenüber|demgegenueber|hingegen)\b"
    r"[^.!?\n]{0,180}\b(?:hypothes\w*|könnt\w*|koennt\w*|"
    r"wäre|waere|würde|wuerde|would|could)\b",
    re.IGNORECASE,
)


def _claim_contains_possible_falsifier(text: str) -> bool:
    """Recognise a possible counter-result, not merely falsification vocabulary."""

    for clause in re.split(r"\n+|(?<=[.!?;])\s+", text or ""):
        if _RESPONSE_CLAIM_FALSIFIER_PATTERN.search(clause) is None:
            continue
        if _RESPONSE_CLAIM_INVALID_FALSIFIER_PATTERN.search(clause):
            continue
        if (
            _RESPONSE_CLAIM_FALSIFIER_MODALITY_PATTERN.search(clause)
            and _RESPONSE_CLAIM_EMPIRICAL_COUNTER_RESULT_PATTERN.search(
                clause
            )
        ):
            return True
    return False


def _claim_uses_external_corpus_as_falsifier(text: str) -> bool:
    """Reject a comparison corpus standing in for a result on the active one."""

    return any(
        _RESPONSE_CLAIM_FALSIFIER_PATTERN.search(clause)
        and _RESPONSE_CLAIM_EXTERNAL_CORPUS_FALSIFIER_PATTERN.search(clause)
        for clause in re.split(r"\n+|(?<=[.!?;])\s+", text or "")
    )


def _is_testable_hypothesis_claim(
    text: str,
    *,
    claim_kind: str,
    assertion_level: str,
) -> bool:
    """Recognise a prospective, genuinely falsifiable corpus hypothesis."""

    return bool(
        claim_kind == "interpretation"
        and assertion_level == "tentative"
        and (
            _HYPOTHESIS_PROPOSAL_PATTERN.search(text or "")
            or _HYPOTHESIS_SELF_REFERENCE_PATTERN.search(text or "")
        )
        and _claim_contains_possible_falsifier(text or "")
        and not _claim_uses_external_corpus_as_falsifier(text or "")
    )


def _claim_bundles_analytical_units(text: str) -> bool:
    """Reject multiple top-level propositions while allowing one test plan."""

    if len(list(_ANALYTICAL_CLAIM_LABEL_PATTERN.finditer(text or ""))) > 1:
        return True
    numbered_parts = re.split(
        r"(?m)(?:^|\s)[1-9]\s*[.)]\s+(?=\S)",
        text or "",
    )[1:]
    hypothesis_parts = [
        part
        for part in numbered_parts
        if re.search(
            r"\b(?:hypothes\w*|könnt\w*|koennt\w*|"
            r"wäre|waere|würde|wuerde|would|could)\b",
            _RESPONSE_CLAIM_FALSIFIER_PATTERN.split(part, maxsplit=1)[0],
            re.IGNORECASE,
        )
    ]
    if len(hypothesis_parts) > 1:
        return True
    alternative = _ALTERNATIVE_HYPOTHESIS_PATTERN.search(text or "")
    if alternative is None:
        return False
    # "Dagegen spräche ..." is the falsifier of the same hypothesis, not a
    # second hypothesis. Numbered KWIC/dispersion steps are likewise harmless.
    return not _claim_contains_possible_falsifier(alternative.group(0))


def _claim_restates_user_task(
    claim_text: str,
    question_text: str,
    requirements: Sequence[ResponseRequirement],
) -> bool:
    """Detect copied instructions, not merely claims about the same topic."""

    if _RESPONSE_REQUEST_VERB_PATTERN.search(claim_text or "") is None:
        return False
    claim_tokens = _response_text_tokens(claim_text)
    if len(claim_tokens) < 4:
        return False
    candidate_texts = [question_text]
    candidate_texts.extend(
        text
        for requirement in requirements
        for text in (requirement.source_quote, requirement.description)
    )
    for candidate_text in candidate_texts:
        candidate_tokens = _response_text_tokens(candidate_text)
        if len(candidate_tokens) < 4:
            continue
        if _tokens_are_contiguous_span(claim_tokens, candidate_tokens):
            return True
        if (
            len(claim_tokens) <= len(candidate_tokens) + 2
            and _tokens_are_contiguous_span(candidate_tokens, claim_tokens)
        ):
            return True
    return False


def _strip_internal_fact_references(text: Any) -> str:
    """Remove model-facing fact citations before validation and rendering."""

    cleaned = _INTERNAL_FACT_REFERENCE_PATTERN.sub("", str(text or ""))
    # Removing a citation after an explanatory dash must not leak model-facing
    # punctuation such as ``(Wert – und)`` into the researcher's answer.
    cleaned = re.sub(r"\s+[–—-]\s*(?=[)\],.;:!?]|$)", "", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    return re.sub(r"\s+([,.;:!?])", r"\1", cleaned).strip()


@dataclass
class ClaimDraft:
    id: str
    claim_kind: str
    text: str
    fact_ids: List[str] = field(default_factory=list)
    assertion_level: str = "qualified"
    response_requirement_id: str = ""
    # Beratende Annotationen der advisory-eingestuften Claim-Regeln fuer
    # DIESEN Claim. Wird von validate_answer_envelope befuellt (Spiegel von
    # AnswerEnvelope.advisories[claim.id]), nie vom Modell geliefert.
    advisories: List[str] = field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> "ClaimDraft | None":
        if not isinstance(raw, dict):
            return None
        raw_text = raw.get("text")
        text_alias = ""
        if raw_text in (None, ""):
            for alias in ("claim", "statement"):
                if raw.get(alias) in (None, ""):
                    continue
                # Preserve semantically identical provider field names without
                # relaxing any fact or scope validation performed later.
                raw_text = raw.get(alias)
                text_alias = f"{alias}->text"
                break
        text = _normalise_claim_text(
            _strip_internal_fact_references(raw_text)
        )
        if not text:
            return None
        claim_kind = _normalise_enum(
            _CLAIM_KIND_ALIASES.get(
                str(raw.get("claim_kind") or "").strip().casefold(),
                raw.get("claim_kind"),
            ),
            CLAIM_KINDS,
            "observation",
        )
        assertion_level = _normalise_enum(
            raw.get("assertion_level"),
            ASSERTION_LEVELS,
            "qualified",
        )
        if (
            claim_kind == "interpretation"
            and str(raw.get("assertion_level") or "").strip().casefold()
            not in ASSERTION_LEVELS
            and _TENTATIVE_INTERPRETATION_SURFACE_PATTERN.search(text)
        ):
            # Some local structured-output implementations omit required enum
            # fields. Preserve the epistemic force stated in the prose instead
            # of silently upgrading an explicitly cautious reading.
            assertion_level = "tentative"
        # Providers sometimes label an explicitly proposed hypothesis as an
        # exact finding. Normalising this structural mismatch preserves the
        # model's idea while keeping its epistemic status honest.
        if (
            claim_kind == "interpretation"
            and assertion_level == "exact"
            and _HYPOTHESIS_PROPOSAL_PATTERN.search(text)
        ):
            assertion_level = "tentative"
        parsed = cls(
            id=_compact_id(raw.get("id", ""), CLAIM_ID_LIMIT)
            or f"claim_{abs(hash(text)) % 100000}",
            claim_kind=claim_kind,
            text=text,
            # item_limit must match the fact.id cap in _make_fact (_compact_id 96)
            # so a claim's fact reference still resolves against fact_index.
            fact_ids=_normalise_text_list(
                raw.get("fact_ids"),
                max_items=MAX_FACT_IDS_PER_CLAIM,
                item_limit=96,
            ),
            assertion_level=assertion_level,
            response_requirement_id=_compact_id(
                raw.get("response_requirement_id", ""),
                CLAIM_ID_LIMIT,
            ),
        )
        parsed._schema_aliases = [text_alias] if text_alias else []
        return parsed

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AnswerEnvelope:
    claims: List[ClaimDraft] = field(default_factory=list)
    evidence_gaps: List[str] = field(default_factory=list)
    blocked_claims: List[str] = field(default_factory=list)
    # Beratende Annotationen (claim_id -> Befunde) der advisory-eingestuften
    # Claim-Regeln. Wird von validate_answer_envelope befuellt, nie vom
    # Modell geliefert; blockiert nicht.
    advisories: Dict[str, List[str]] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: Any) -> "AnswerEnvelope":
        payload = raw if isinstance(raw, dict) else {}
        claims: List[ClaimDraft] = []
        used_ids: set[str] = set()
        for index, item in enumerate(
            list(payload.get("claims", []) or [])[:MAX_ANSWER_CLAIMS],
            start=1,
        ):
            claim = ClaimDraft.from_raw(item)
            if claim is not None:
                if claim.id in used_ids:
                    seed = (
                        f"{index}|{claim.id}|{claim.claim_kind}|{claim.text}|"
                        + "|".join(sorted(set(claim.fact_ids)))
                    )
                    digest = hashlib.blake2s(
                        seed.encode("utf-8"),
                        digest_size=6,
                    ).hexdigest()
                    prefix = claim.id[
                        : CLAIM_ID_LIMIT - len(digest) - 1
                    ]
                    claim.id = f"{prefix}~{digest}"
                    counter = 2
                    while claim.id in used_ids:
                        suffix = f"~{digest[:8]}{counter}"
                        claim.id = (
                            claim.id[: CLAIM_ID_LIMIT - len(suffix)]
                            + suffix
                        )
                        counter += 1
                used_ids.add(claim.id)
                claims.append(claim)
        return cls(
            claims=claims,
            evidence_gaps=_normalise_text_list(payload.get("evidence_gaps"), max_items=6, item_limit=180),
            blocked_claims=_normalise_text_list(payload.get("blocked_claims"), max_items=6, item_limit=180),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claims": [claim.to_dict() for claim in self.claims],
            "evidence_gaps": list(self.evidence_gaps),
            "blocked_claims": list(self.blocked_claims),
            "advisories": {
                claim_id: list(items)
                for claim_id, items in (self.advisories or {}).items()
            },
        }


@dataclass
class GroundingVerdict:
    verdict: str = "conservative_only"
    accepted_claim_ids: List[str] = field(default_factory=list)
    rejected_claim_ids: List[str] = field(default_factory=list)
    accounted_retrieval_fact_ids: List[str] = field(default_factory=list)
    unaccounted_retrieval_fact_ids: List[str] = field(default_factory=list)
    fulfilled_response_requirement_ids: List[str] = field(default_factory=list)
    unfulfilled_response_requirement_ids: List[str] = field(default_factory=list)
    claim_fact_usage: List[Dict[str, Any]] = field(default_factory=list)
    hypothesis_pair_assessment: Dict[str, Any] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    needs_retry: bool = False
    # Beratende Annotationen (claim_id -> Befunde), durchgereicht aus
    # AnswerEnvelope.advisories. Rein informativ fuer die UI; hat keinen
    # Einfluss auf verdict, rejected_claim_ids oder Repair-Schleifen.
    advisories: Dict[str, List[str]] = field(default_factory=dict)
    # WARUM DER HARNESS ETWAS BEANSTANDET HAT, und zwar sichtbar.
    #
    # Diese vier waren bisher nachtraeglich gesetzte Unterstrich-Attribute.
    # ``to_dict`` ist ``asdict(self)`` und sieht nur Dataclass-Felder, also
    # fielen sie aus jeder Aufzeichnung heraus. Folge, teuer bezahlt am
    # 2026-08-28: ein Mitschnitt von sieben Verdicts zeigte siebenmal
    # „pass“ ohne eine einzige Zurueckweisung, waehrend in JEDER Runde ein
    # deterministisches Tor beanstandet hatte. Die Diagnose lief deshalb in
    # die falsche Richtung, und zwar zweimal.
    #
    # Eine Aufzeichnung, die das Ergebnis zeigt und den Grund verschweigt,
    # ist schlimmer als keine: sie sieht vollstaendig aus.
    claim_reasons: Dict[str, List[str]] = field(default_factory=dict)
    verifier_protocol_anomalies: List[str] = field(default_factory=list)
    omitted_claim_ids: List[str] = field(default_factory=list)
    replace_whole_deliverable: bool = False
    # Je Runde: welches Tor mit welcher Begruendung ausgeloest hat.
    tor_verlauf: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> "GroundingVerdict":
        payload = raw if isinstance(raw, dict) else {}
        schema_aliases: List[str] = []

        raw_verdict = str(payload.get("verdict", "") or "").strip()
        if not raw_verdict:
            for alias_key in ("final_verdict", "decision"):
                alias_value = str(payload.get(alias_key, "") or "").strip()
                if alias_value:
                    raw_verdict = alias_value
                    schema_aliases.append(f"{alias_key}->verdict")
                    break
        verdict = _normalise_enum(
            raw_verdict,
            GROUNDING_VERDICTS,
            "conservative_only",
        )

        def classified_ids(
            raw_partition: Any,
            *,
            fulfilled_values: set[str],
            unfulfilled_values: set[str],
            boolean_key: str = "",
        ) -> tuple[List[str], List[str]]:
            """Read common map/list partitions without guessing semantics."""

            entries: List[tuple[Any, Any]] = []
            if isinstance(raw_partition, dict):
                entries.extend(raw_partition.items())
            elif isinstance(raw_partition, list):
                for item in raw_partition:
                    if not isinstance(item, dict):
                        continue
                    identifier = next(
                        (
                            item.get(key)
                            for key in (
                                "id",
                                "claim_id",
                                "requirement_id",
                                "fact_id",
                            )
                            if item.get(key) not in (None, "")
                        ),
                        "",
                    )
                    status = next(
                        (
                            item.get(key)
                            for key in ("status", "classification", "verdict", "decision")
                            if item.get(key) not in (None, "")
                        ),
                        "",
                    )
                    if not status and boolean_key and isinstance(
                        item.get(boolean_key), bool
                    ):
                        status = (
                            next(iter(fulfilled_values))
                            if item[boolean_key]
                            else next(iter(unfulfilled_values))
                        )
                    entries.append((identifier, status))

            fulfilled: List[str] = []
            unfulfilled: List[str] = []
            for identifier, raw_status in entries:
                compact_id = _compact_id(identifier, CLAIM_ID_LIMIT)
                status = str(raw_status or "").strip().casefold()
                if not compact_id:
                    continue
                if status in fulfilled_values:
                    fulfilled.append(compact_id)
                elif status in unfulfilled_values:
                    unfulfilled.append(compact_id)
            return (
                _dedupe_ordered_strs(fulfilled),
                _dedupe_ordered_strs(unfulfilled),
            )

        partition_status_conflicts: List[str] = []

        def explicit_partition_ids(
            raw_partition: Any,
            *,
            partition_name: str,
            expected_values: set[str],
            opposite_values: set[str],
            boolean_key: str = "accepted",
        ) -> tuple[List[str], List[str], bool]:
            """Respect object statuses without letting a container invert them."""

            if raw_partition in (None, "", [], {}):
                return [], [], False
            entries = (
                raw_partition
                if isinstance(raw_partition, list)
                else [raw_partition]
            )
            expected: List[str] = []
            opposite: List[str] = []
            for item in entries[:MAX_VERDICT_CLAIM_IDS]:
                if not isinstance(item, dict):
                    expected.extend(_normalise_claim_id_list(item))
                    continue
                identifier = next(
                    (
                        item.get(key)
                        for key in ("id", "claim_id")
                        if item.get(key) not in (None, "")
                    ),
                    "",
                )
                claim_id = _compact_id(identifier, CLAIM_ID_LIMIT)
                if not claim_id:
                    continue
                raw_status = next(
                    (
                        item.get(key)
                        for key in (
                            "status",
                            "classification",
                            "verdict",
                            "decision",
                        )
                        if item.get(key) not in (None, "")
                    ),
                    "",
                )
                if not raw_status and boolean_key and isinstance(
                    item.get(boolean_key), bool
                ):
                    raw_status = (
                        next(iter(expected_values))
                        if item[boolean_key]
                        else next(iter(opposite_values))
                    )
                status = str(raw_status or "").strip().casefold()
                if not status:
                    expected.append(claim_id)
                elif status in expected_values:
                    expected.append(claim_id)
                elif status in opposite_values:
                    opposite.append(claim_id)
                    partition_status_conflicts.append(
                        f"{partition_name}:{claim_id}:{status}"
                    )
                else:
                    partition_status_conflicts.append(
                        f"{partition_name}:{claim_id}:invalid_status"
                    )
            return (
                _dedupe_ordered_strs(expected),
                _dedupe_ordered_strs(opposite),
                True,
            )

        def partitioned_ids(
            fulfilled_key: str,
            unfulfilled_key: str,
            mapping_aliases: tuple[str, ...],
            *,
            fulfilled_aliases: tuple[str, ...] = (),
            unfulfilled_aliases: tuple[str, ...] = (),
            fulfilled_values: set[str],
            unfulfilled_values: set[str],
        ) -> tuple[List[str], List[str]]:
            boolean_key = (
                "fulfilled"
                if "response_requirement" in fulfilled_key
                else "accounted"
            )
            (
                fulfilled,
                misplaced_unfulfilled,
                fulfilled_present,
            ) = explicit_partition_ids(
                payload.get(fulfilled_key),
                partition_name=fulfilled_key,
                expected_values=fulfilled_values,
                opposite_values=unfulfilled_values,
                boolean_key=boolean_key,
            )
            (
                unfulfilled,
                misplaced_fulfilled,
                unfulfilled_present,
            ) = explicit_partition_ids(
                payload.get(unfulfilled_key),
                partition_name=unfulfilled_key,
                expected_values=unfulfilled_values,
                opposite_values=fulfilled_values,
                boolean_key=boolean_key,
            )
            if not fulfilled_present:
                for alias_key in fulfilled_aliases:
                    (
                        fulfilled,
                        misplaced_unfulfilled,
                        alias_present,
                    ) = explicit_partition_ids(
                        payload.get(alias_key),
                        partition_name=alias_key,
                        expected_values=fulfilled_values,
                        opposite_values=unfulfilled_values,
                        boolean_key=boolean_key,
                    )
                    if alias_present:
                        schema_aliases.append(f"{alias_key}->{fulfilled_key}")
                        break
            if not unfulfilled_present:
                for alias_key in unfulfilled_aliases:
                    (
                        unfulfilled,
                        misplaced_fulfilled,
                        alias_present,
                    ) = explicit_partition_ids(
                        payload.get(alias_key),
                        partition_name=alias_key,
                        expected_values=unfulfilled_values,
                        opposite_values=fulfilled_values,
                        boolean_key=boolean_key,
                    )
                    if alias_present:
                        schema_aliases.append(
                            f"{alias_key}->{unfulfilled_key}"
                        )
                        break
            fulfilled = _dedupe_ordered_strs(
                fulfilled + misplaced_fulfilled
            )
            unfulfilled = _dedupe_ordered_strs(
                unfulfilled + misplaced_unfulfilled
            )
            if fulfilled_present or unfulfilled_present or fulfilled or unfulfilled:
                return fulfilled, unfulfilled
            for alias_key in mapping_aliases:
                partition = payload.get(alias_key)
                if not isinstance(partition, (dict, list)):
                    continue
                alias_fulfilled, alias_unfulfilled = classified_ids(
                    partition,
                    fulfilled_values=fulfilled_values,
                    unfulfilled_values=unfulfilled_values,
                    boolean_key=(
                        "fulfilled"
                        if "response_requirement" in alias_key
                        or alias_key == "response_requirements"
                        else "accounted"
                    ),
                )
                if alias_fulfilled or alias_unfulfilled:
                    schema_aliases.append(
                        f"{alias_key}->{fulfilled_key}/{unfulfilled_key}"
                    )
                    return alias_fulfilled, alias_unfulfilled
            return fulfilled, unfulfilled

        fulfilled_requirements, unfulfilled_requirements = partitioned_ids(
            "fulfilled_response_requirement_ids",
            "unfulfilled_response_requirement_ids",
            (
                "response_requirement_fulfillment",
                "response_requirement_classification",
                "response_requirements",
                "response_requirements_fulfillment",
                "response_requirements_status",
            ),
            fulfilled_aliases=("response_requirements_fulfilled",),
            unfulfilled_aliases=("response_requirements_unfulfilled",),
            fulfilled_values={"fulfilled", "satisfied", "met"},
            unfulfilled_values={
                "unfulfilled",
                "unsatisfied",
                "not_met",
                "missing",
            },
        )
        accounted_retrieval, unaccounted_retrieval = partitioned_ids(
            "accounted_retrieval_fact_ids",
            "unaccounted_retrieval_fact_ids",
            (
                "retrieval_candidate_accounting",
                "retrieval_candidate_assessments",
                "retrieval_candidate_fact_usage",
            ),
            fulfilled_values={"accounted", "used", "covered"},
            unfulfilled_values={
                "unaccounted",
                "unused",
                "not_accounted",
                "missing",
            },
        )

        raw_usage = payload.get("claim_fact_usage")
        usage_alias_key = ""
        if raw_usage is None and isinstance(
            payload.get("fact_usage"),
            (dict, list),
        ):
            raw_usage = payload["fact_usage"]
            usage_alias_key = "fact_usage"
        elif isinstance(raw_usage, dict):
            usage_alias_key = "claim_fact_usage(object)"

        converted_usage: List[Dict[str, Any]] = []
        if isinstance(raw_usage, dict):
            for claim_id, usage in raw_usage.items():
                if not isinstance(usage, dict):
                    continue
                if "used_fact_ids" in usage or "unused_fact_ids" in usage:
                    used_ids = usage.get("used_fact_ids")
                    unused_ids = usage.get("unused_fact_ids")
                else:
                    used_ids = [
                        fact_id
                        for fact_id, status in usage.items()
                        if str(status or "").strip().casefold() == "used"
                    ]
                    unused_ids = [
                        fact_id
                        for fact_id, status in usage.items()
                        if str(status or "").strip().casefold() == "unused"
                    ]
                converted_usage.append(
                    {
                        "claim_id": claim_id,
                        "used_fact_ids": used_ids,
                        "unused_fact_ids": unused_ids,
                    }
                )
        elif isinstance(raw_usage, list):
            grouped_usage: Dict[str, Dict[str, Any]] = {}
            flattened = False
            for item in raw_usage:
                if not isinstance(item, dict):
                    continue
                claim_id = _compact_id(
                    item.get("claim_id", ""), CLAIM_ID_LIMIT
                )
                if not claim_id:
                    continue
                entry = grouped_usage.setdefault(
                    claim_id,
                    {
                        "claim_id": claim_id,
                        "used_fact_ids": [],
                        "unused_fact_ids": [],
                    },
                )
                if "used_fact_ids" in item or "unused_fact_ids" in item:
                    entry["used_fact_ids"].extend(
                        _normalise_text_list(
                            item.get("used_fact_ids"),
                            max_items=MAX_FACT_IDS_PER_CLAIM,
                            item_limit=96,
                        )
                    )
                    entry["unused_fact_ids"].extend(
                        _normalise_text_list(
                            item.get("unused_fact_ids"),
                            max_items=MAX_FACT_IDS_PER_CLAIM,
                            item_limit=96,
                        )
                    )
                    continue
                fact_id = _compact_id(item.get("fact_id", ""), 96)
                status = str(
                    item.get("usage") or item.get("status") or ""
                ).strip().casefold()
                if fact_id and status in {"used", "unused"}:
                    entry[f"{status}_fact_ids"].append(fact_id)
                    flattened = True
            converted_usage = list(grouped_usage.values())
            if flattened and not usage_alias_key:
                usage_alias_key = "claim_fact_usage(flat)"
        raw_usage = converted_usage
        if converted_usage and usage_alias_key:
            schema_aliases.append(f"{usage_alias_key}->claim_fact_usage")

        raw_reasons = payload.get("reasons")
        inline_reasons = [
            str(item.get("reason") or item.get("rejection_reason") or "")
            for key in (
                "rejected_claim_ids",
                "rejected_claims",
                "claims_rejected",
            )
            for item in (
                payload.get(key)
                if isinstance(payload.get(key), list)
                else []
            )
            if isinstance(item, dict)
            and str(
                item.get("reason") or item.get("rejection_reason") or ""
            ).strip()
        ]
        if inline_reasons:
            raw_reasons = [
                *(
                    raw_reasons
                    if isinstance(raw_reasons, list)
                    else ([raw_reasons] if raw_reasons else [])
                ),
                *inline_reasons,
            ]
            schema_aliases.append("rejected_claim_ids(objects)->reasons")
        if not raw_reasons:
            for alias_key in (
                "rejected_reasons",
                "rejection_reasons",
                "claim_rejection_reasons",
            ):
                if not isinstance(payload.get(alias_key), dict):
                    continue
                raw_reasons = list(payload[alias_key].values())
                schema_aliases.append(f"{alias_key}->reasons")
                break

        acceptance_values = {
            "accept",
            "accepted",
            "grounded",
            "pass",
            "supported",
            "verified",
        }
        rejection_values = {
            "fail",
            "reject",
            "rejected",
            "unsupported",
        }
        (
            accepted_claim_ids,
            accepted_partition_rejections,
            accepted_partition_present,
        ) = explicit_partition_ids(
            payload.get("accepted_claim_ids"),
            partition_name="accepted_claim_ids",
            expected_values=acceptance_values,
            opposite_values=rejection_values,
        )
        if not accepted_partition_present:
            for alias_key in ("accepted_claims", "claims_accepted"):
                (
                    accepted_claim_ids,
                    accepted_partition_rejections,
                    alias_present,
                ) = explicit_partition_ids(
                    payload.get(alias_key),
                    partition_name=alias_key,
                    expected_values=acceptance_values,
                    opposite_values=rejection_values,
                )
                if alias_present:
                    schema_aliases.append(
                        f"{alias_key}->accepted_claim_ids"
                    )
                    break
        (
            rejected_claim_ids,
            rejected_partition_acceptances,
            rejected_partition_present,
        ) = explicit_partition_ids(
            payload.get("rejected_claim_ids"),
            partition_name="rejected_claim_ids",
            expected_values=rejection_values,
            opposite_values=acceptance_values,
        )
        if not rejected_partition_present:
            for alias_key in ("rejected_claims", "claims_rejected"):
                (
                    rejected_claim_ids,
                    rejected_partition_acceptances,
                    alias_present,
                ) = explicit_partition_ids(
                    payload.get(alias_key),
                    partition_name=alias_key,
                    expected_values=rejection_values,
                    opposite_values=acceptance_values,
                )
                if alias_present:
                    schema_aliases.append(
                        f"{alias_key}->rejected_claim_ids"
                    )
                    break
        accepted_claim_ids = _dedupe_ordered_strs(
            accepted_claim_ids + rejected_partition_acceptances
        )
        rejected_claim_ids = _dedupe_ordered_strs(
            rejected_claim_ids + accepted_partition_rejections
        )
        if not accepted_claim_ids and not rejected_claim_ids:
            accepted_claim_ids, rejected_claim_ids = classified_ids(
                payload.get("claims"),
                fulfilled_values=acceptance_values,
                unfulfilled_values=rejection_values,
                boolean_key="accepted",
            )
            if accepted_claim_ids or rejected_claim_ids:
                schema_aliases.append(
                    "claims(classification)->accepted_claim_ids/"
                    "rejected_claim_ids"
                )

        raw_pair_assessment = payload.get("hypothesis_pair_assessment")
        pair_protocol_valid = bool(
            isinstance(raw_pair_assessment, dict)
            and all(
                isinstance(raw_pair_assessment.get(key), bool)
                for key in (
                    "same_operationalization",
                    "differentiating_predictions",
                    "pair_valid",
                )
            )
            and isinstance(raw_pair_assessment.get("reason"), str)
        )
        pair_assessment = (
            {
                "same_operationalization": raw_pair_assessment[
                    "same_operationalization"
                ],
                "differentiating_predictions": raw_pair_assessment[
                    "differentiating_predictions"
                ],
                "pair_valid": raw_pair_assessment["pair_valid"],
                "reason": _compact_text(
                    raw_pair_assessment.get("reason", ""),
                    MAX_VERDICT_REASON_CHARS,
                ),
            }
            if pair_protocol_valid
            else {}
        )

        parsed = cls(
            verdict=verdict,
            accepted_claim_ids=accepted_claim_ids,
            rejected_claim_ids=rejected_claim_ids,
            accounted_retrieval_fact_ids=accounted_retrieval,
            unaccounted_retrieval_fact_ids=unaccounted_retrieval,
            fulfilled_response_requirement_ids=fulfilled_requirements,
            unfulfilled_response_requirement_ids=unfulfilled_requirements,
            claim_fact_usage=[
                {
                    "claim_id": _compact_id(item.get("claim_id", ""), CLAIM_ID_LIMIT),
                    "used_fact_ids": _normalise_text_list(
                        item.get("used_fact_ids"),
                        max_items=MAX_FACT_IDS_PER_CLAIM,
                        item_limit=96,
                    ),
                    "unused_fact_ids": _normalise_text_list(
                        item.get("unused_fact_ids"),
                        max_items=MAX_FACT_IDS_PER_CLAIM,
                        item_limit=96,
                    ),
                }
                for item in list(raw_usage or [])[
                    :MAX_ANSWER_CLAIMS
                ]
                if isinstance(item, dict)
                and _compact_id(item.get("claim_id", ""), CLAIM_ID_LIMIT)
            ],
            hypothesis_pair_assessment=pair_assessment,
            reasons=_normalise_text_list(
                raw_reasons,
                max_items=8,
                item_limit=MAX_VERDICT_REASON_CHARS,
            ),
            needs_retry=(
                _coerce_bool(payload.get("needs_retry"))
                if verdict == "retry"
                else False
            ),
        )
        parsed._invalid_verdict_value = (
            raw_verdict
            if raw_verdict and raw_verdict not in GROUNDING_VERDICTS
            else ""
        )
        parsed._schema_aliases = _dedupe_ordered_strs(schema_aliases)
        parsed._partition_status_conflicts = _dedupe_ordered_strs(
            partition_status_conflicts
        )
        parsed._hypothesis_pair_protocol_valid = pair_protocol_valid
        return parsed

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        # WARUM beanstandet wurde, nicht nur DASS. Die vier Werte sind
        # nachtraeglich gesetzte Unterstrich-Attribute, ``asdict`` sieht sie
        # nicht. Ohne diese Spiegelung zeigt jede Aufzeichnung „pass, nichts
        # zurueckgewiesen“, waehrend ein deterministisches Tor die Runde
        # erzwungen hat. Genau daran ist die Diagnose am 2026-08-28 zweimal
        # gescheitert. Mengen werden sortiert, damit zwei Laeufe vergleichbar
        # bleiben.
        for feld, roh in (
            ("claim_reasons", getattr(self, "_claim_reasons", None)),
            ("verifier_protocol_anomalies",
             getattr(self, "_verifier_protocol_anomalies", None)),
            ("omitted_claim_ids", getattr(self, "_omitted_claim_ids", None)),
            ("replace_whole_deliverable",
             getattr(self, "_replace_whole_deliverable", None)),
            ("tor_verlauf", getattr(self, "_tor_verlauf", None)),
        ):
            if roh is None:
                continue
            if isinstance(roh, Mapping):
                payload[feld] = {
                    str(k): sorted(v) if isinstance(v, (set, frozenset))
                    else list(v) if isinstance(v, (list, tuple)) else [str(v)]
                    for k, v in roh.items()
                }
            elif isinstance(roh, (set, frozenset)):
                payload[feld] = sorted(str(x) for x in roh)
            elif isinstance(roh, (list, tuple)):
                payload[feld] = list(roh)
            else:
                payload[feld] = roh
        schema_aliases = list(getattr(self, "_schema_aliases", []) or [])
        if schema_aliases:
            payload["schema_aliases"] = schema_aliases
        return payload


@dataclass
class ContractReview:
    verdict: str = "conservative_only"
    track: str = "bounded_analysis"
    analysis_family: str = "open_research"
    deliverable_kind: str = "overview"
    required_evidence: List[str] = field(default_factory=list)
    response_shape: str = ""
    clarification_question: str = ""
    reason: str = ""

    @classmethod
    def from_raw(cls, raw: Any, *, question_text: str = "") -> "ContractReview":
        """Die Pruefung des Modellkontrakts urteilt ueber dieselbe Frage.

        DIESE SCHICHT KANNTE DIE FRAGE NICHT. Ohne ``question_text`` gaben
        ``default_track_for_family`` und ``default_deliverable_kind_for_family``
        fuer ``kwic_context`` immer ``lookup`` und ``lookup_answer`` zurueck,
        weil die leere Zeichenkette als Nachschlagen gilt. Der Verifier
        durfte damit einen bereits richtig gestellten Analysebericht wieder
        auf den Nachschlagerahmen ziehen, und nur die erneute
        ``AnalysisContract.from_raw`` weiter unten im Orchestrator hat das
        gerettet. Gemessen am 2026-09-03 an konstr-korrelat-fenster (749
        Zeichen): ohne Frage lieferte diese Funktion track="lookup" und
        deliverable_kind="lookup_answer", mit Frage bounded_analysis und
        analysis_report.
        """

        payload = raw if isinstance(raw, dict) else {}
        analysis_family = _normalise_enum(payload.get("analysis_family"), ANALYSIS_FAMILIES, "open_research")
        track = _normalise_enum(
            payload.get("track"),
            TRACK_VALUES,
            default_track_for_family(
                analysis_family,
                question_text=question_text,
            ),
        )
        requested_deliverable = _normalise_enum(
            payload.get("deliverable_kind"),
            DELIVERABLE_KINDS,
            default_deliverable_kind_for_family(
                analysis_family,
                question_text=question_text,
                track=track,
            ),
        )
        return cls(
            verdict=_normalise_enum(payload.get("verdict"), CONTRACT_REVIEW_VERDICTS, "conservative_only"),
            track=track,
            analysis_family=analysis_family,
            deliverable_kind=compatible_deliverable_kind(
                requested_deliverable,
                analysis_family,
                question_text=question_text,
                track=track,
            ),
            required_evidence=[
                item
                for item in _normalise_text_list(
                    payload.get("required_evidence"),
                    max_items=6,
                    item_limit=120,
                )
                if item in EVIDENCE_KINDS
            ],
            response_shape=_compact_text(payload.get("response_shape", ""), 120),
            clarification_question=_compact_text(
                payload.get("clarification_question", ""),
                CLARIFICATION_QUESTION_LIMIT,
            ),
            reason=_compact_text(payload.get("reason", ""), 220),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def analysis_contract_schema() -> Dict[str, Any]:
    return {
        "name": "analysis_contract",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "mode": {"type": "string", "enum": list(MODE_VALUES)},
                "track": {"type": "string", "enum": list(TRACK_VALUES)},
                "analysis_family": {"type": "string", "enum": list(ANALYSIS_FAMILIES)},
                "deliverable_kind": {"type": "string", "enum": list(DELIVERABLE_KINDS)},
                "question_scope": {"type": "string"},
                "allowed_tools": {"type": "array", "items": {"type": "string"}},
                "required_evidence": {"type": "array", "items": {"type": "string", "enum": list(EVIDENCE_KINDS)}},
                "forbidden_claims": {"type": "array", "items": {"type": "string"}},
                "response_shape": {"type": "string"},
                "response_requirements": {
                    "type": "array",
                    "maxItems": MAX_RESPONSE_REQUIREMENTS,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "id": {
                                "type": "string",
                                "maxLength": CLAIM_ID_LIMIT,
                            },
                            "source_quote": {
                                "type": "string",
                                "maxLength": MAX_RESPONSE_REQUIREMENT_CHARS,
                            },
                            "claim_kind": {
                                "type": "string",
                                "enum": list(CLAIM_KINDS),
                            },
                        },
                        "required": [
                            "id",
                            "source_quote",
                            "claim_kind",
                        ],
                    },
                },
                "needs_clarification": {"type": "boolean"},
                "clarification_question": {"type": "string"},
            },
            "required": [
                "mode",
                "track",
                "analysis_family",
                "deliverable_kind",
                "question_scope",
                "allowed_tools",
                "required_evidence",
                "forbidden_claims",
                "response_shape",
                "response_requirements",
                "needs_clarification",
                "clarification_question",
            ],
        },
    }


def response_requirements_schema() -> Dict[str, Any]:
    requirement = analysis_contract_schema()["schema"]["properties"][
        "response_requirements"
    ]
    return {
        "name": "response_requirements",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "response_requirements": requirement,
            },
            "required": ["response_requirements"],
        },
    }


def contract_review_schema() -> Dict[str, Any]:
    return {
        "name": "contract_review",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "verdict": {"type": "string", "enum": list(CONTRACT_REVIEW_VERDICTS)},
                "track": {"type": "string", "enum": list(TRACK_VALUES)},
                "analysis_family": {"type": "string", "enum": list(ANALYSIS_FAMILIES)},
                "deliverable_kind": {"type": "string", "enum": list(DELIVERABLE_KINDS)},
                "required_evidence": {"type": "array", "items": {"type": "string", "enum": list(EVIDENCE_KINDS)}},
                "response_shape": {"type": "string"},
                "clarification_question": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": [
                "verdict",
                "track",
                "analysis_family",
                "deliverable_kind",
                "required_evidence",
                "response_shape",
                "clarification_question",
                "reason",
            ],
        },
    }


def observed_facts_schema() -> Dict[str, Any]:
    return {
        "name": "observed_facts",
        "schema": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "statement": {"type": "string"},
                    "fact_kind": {"type": "string", "enum": list(FACT_KINDS)},
                    "source_evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "grounding_quotes": {"type": "array", "items": {"type": "string"}},
                    "exactness": {"type": "string", "enum": list(EXACTNESS_VALUES)},
                    "supports_claims": {"type": "array", "items": {"type": "string", "enum": list(CLAIM_SUPPORT_VALUES)}},
                    "limitations": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "id",
                    "statement",
                    "fact_kind",
                    "source_evidence_ids",
                    "grounding_quotes",
                    "exactness",
                    "supports_claims",
                    "limitations",
                ],
            },
        },
    }


def grounding_verdict_schema() -> Dict[str, Any]:
    return {
        "name": "grounding_verdict",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "verdict": {"type": "string", "enum": list(GROUNDING_VERDICTS)},
                "accepted_claim_ids": {
                    "type": "array",
                    "maxItems": MAX_VERDICT_CLAIM_IDS,
                    "items": {"type": "string", "maxLength": CLAIM_ID_LIMIT},
                },
                "rejected_claim_ids": {
                    "type": "array",
                    "maxItems": MAX_VERDICT_CLAIM_IDS,
                    "items": {"type": "string", "maxLength": CLAIM_ID_LIMIT},
                },
                "reasons": {
                    "type": "array",
                    "maxItems": 8,
                    "items": {
                        "type": "string",
                        "maxLength": MAX_VERDICT_REASON_CHARS,
                    },
                },
                "needs_retry": {"type": "boolean"},
            },
            "required": [
                "verdict",
                "accepted_claim_ids",
                "rejected_claim_ids",
                "reasons",
                "needs_retry",
            ],
        },
    }


def default_track_for_family(
    analysis_family: str,
    *,
    question_text: str = "",
) -> str:
    if analysis_family == "kwic_context" and not frage_ist_blosses_nachschlagen(
        question_text
    ):
        # DER TRACK FOLGT DERSELBEN REGEL WIE DIE LIEFERART. Der Track setzt
        # ueber TRACK_TOOL_LIMITS das Werkzeugbudget (lookup=2 gegen
        # bounded_analysis=8), er ist also kein Etikett, sondern eine
        # Ressource. Gemessen am 2026-09-03: konstr-korrelat-fenster (749
        # Zeichen) bekam ueber diesen Familien-Default track="lookup" und
        # damit allowed_tools ['metadata_values', 'create_docset'], also
        # ohne run_cqlf_query, das die im Kontrakt geforderten kwic_rows
        # erst erzeugt. ``AnalysisContract.from_raw`` hebt den Track
        # zusaetzlich, weil das MODELL "lookup" ausdruecklich schreiben
        # kann und der Default dann gar nicht erst greift. Beide Anschluesse
        # lesen dieselbe Funktion, es gibt keine zweite Regel.
        return "bounded_analysis"
    if analysis_family in {"kwic_context", "term_frequency", "document_lookup"}:
        return "lookup"
    if analysis_family in {"contrast_keyness"}:
        return "comparative_analysis"
    if analysis_family in {"open_research"}:
        return "exploratory_research"
    if analysis_family in {
        "metadata_capability",
        "semantic_retrieval",
        "term_profile",
        "ngram_profile",
        "lexical_diversity",
        "trend_analysis",
        "word_sketch_profile",
        "collocation",
    }:
        return "bounded_analysis"
    return "bounded_analysis"


def default_deliverable_kind_for_family(
    analysis_family: str,
    *,
    question_text: str = "",
    track: str = "",
) -> str:
    # English questions in the German cue vocabulary, German as before.
    lowered = routing_text(question_text)
    if analysis_family == "kwic_context":
        return (
            "lookup_answer"
            if frage_ist_blosses_nachschlagen(question_text)
            else "analysis_report"
        )
    if analysis_family in {"term_frequency", "document_lookup"}:
        return "lookup_answer"
    if analysis_family in {"contrast_keyness"}:
        return "contrast_report"
    if analysis_family in {"metadata_capability"}:
        return "capability_report"
    if analysis_family in {
        "semantic_retrieval",
        "term_profile",
        "ngram_profile",
        "lexical_diversity",
        "trend_analysis",
        "word_sketch_profile",
        "collocation",
    }:
        return "analysis_report"
    if track == "method_help":
        return "method_advice"
    if _is_followup_prompt(lowered):
        return "followup_questions"
    return "overview"


_COMPATIBLE_DELIVERABLES_BY_FAMILY = {
    "term_frequency": {"lookup_answer"},
    "kwic_context": {"lookup_answer", "analysis_report"},
    "document_lookup": {"lookup_answer"},
    "contrast_keyness": {"contrast_report"},
    "metadata_capability": {"capability_report", "analysis_report"},
    "semantic_retrieval": {"analysis_report"},
    "term_profile": {"analysis_report"},
    "ngram_profile": {"analysis_report"},
    "lexical_diversity": {"analysis_report"},
    "trend_analysis": {"analysis_report"},
    "word_sketch_profile": {"analysis_report"},
    "collocation": {"analysis_report"},
    "open_research": {
        "overview",
        "analysis_report",
        "contrast_report",
        "followup_questions",
        "method_advice",
    },
}


def compatible_deliverable_kind(
    requested: str,
    analysis_family: str,
    *,
    question_text: str = "",
    track: str = "",
) -> str:
    if (
        analysis_family == "metadata_capability"
        and _metadata_request_needs_interpretation(question_text)
    ):
        return "analysis_report"
    if (
        analysis_family == "kwic_context"
        and not frage_ist_blosses_nachschlagen(question_text)
    ):
        # Steht VOR der Kompatibilitaetspruefung, weil ``lookup_answer`` fuer
        # diese Familie erlaubt ist und ein vorgeschlagenes ``lookup_answer``
        # sonst unveraendert durchginge.
        return "analysis_report"
    allowed = _COMPATIBLE_DELIVERABLES_BY_FAMILY.get(
        analysis_family,
        set(),
    )
    if requested in allowed:
        return requested
    return default_deliverable_kind_for_family(
        analysis_family,
        question_text=question_text,
        track=track,
    )


def _ordered_allowed_tools(
    candidates: Sequence[str],
    *,
    available_tools: Sequence[str],
    read_only_tools: Sequence[str],
) -> List[str]:
    available = {str(item) for item in available_tools if str(item).strip()}
    read_only = {str(item) for item in read_only_tools if str(item).strip()}
    return [name for name in candidates if name in read_only and name in available]


def resolve_allowed_tools(
    *,
    analysis_family: str,
    track: str,
    requested_tools: Sequence[str],
    available_tools: Sequence[str],
    read_only_tools: Sequence[str],
) -> List[str]:
    if analysis_family == "open_research":
        family_candidates = TRACK_TOOL_CANDIDATES.get(track, TRACK_TOOL_CANDIDATES["exploratory_research"])
    else:
        family_candidates = TOOL_BUNDLES.get(analysis_family, ())
    allowed = _ordered_allowed_tools(
        family_candidates,
        available_tools=available_tools,
        read_only_tools=read_only_tools,
    )
    if requested_tools:
        requested = [name for name in requested_tools if name in set(allowed)]
        if requested:
            limit = TRACK_TOOL_LIMITS.get(track, 4)
            return [name for name in allowed if name in set(requested)][:limit]
    if analysis_family == "open_research" and not requested_tools:
        limit = TRACK_TOOL_LIMITS.get(track, 4)
        return allowed[:limit]
    return allowed


def _normalised_question_text(question_text: str) -> str:
    # Weiterleitung. Die Normalisierung steht in candyconc.question_kind, weil
    # candyconc.tooling.tool_selection dieselbe Einstufung braucht und nicht
    # aus candyconc_copilot lesen darf.
    return normalisierte_frage(question_text)


def _has_any_phrase(text: str, phrases: Sequence[str]) -> bool:
    return any(phrase in text for phrase in phrases)


def _metadata_request_needs_interpretation(text: str) -> bool:
    lowered = _normalised_question_text(text)
    # Inventory questions only ask which fields or values exist. A single
    # analytical cue is enough to preserve the model's interpretive task;
    # requiring two independent cue groups silently reduced valid research
    # questions such as "Welche Registerunterschiede lassen sich untersuchen?"
    return _has_any_phrase(
        lowered,
        (
            "unterschied",
            "vergleich",
            "vergleiche",
            "untersuch",
            "analys",
            "interpret",
            "erklär",
            "sinnvoll",
            "geeignet",
            "eignung",
            "belastbar",
            "zusammenhang",
            "verteil",
            "variier",
            "variation",
            "hypothese",
            "forschungsfrage",
        ),
    )


def _explicit_interpretation_request(text: str) -> bool:
    """Weiterleitung auf candyconc.question_kind.enthaelt_deutungscue.

    Der Cue-Satz stand hier und in ``tool_selection.py`` als zwei Kopien.
    Beide lesen ihn jetzt aus ``candyconc.question_kind``, weil die
    Kontraktschicht seit dem 2026-09-02 zusaetzlich ueber die Laenge der
    Frage urteilt und die zweite Kopie diese Erweiterung nicht mitbekam.
    Die gebrauch_kwic-Trigger in ``recipes_data.py`` bleiben eine eigene
    Liste: sie beantworten eine andere Frage (welches Rezept passt) und
    fuehren dafuer Familienmarker und Werkzeugnamen. Der Name hier bleibt,
    weil ihn vier Fassaden re-exportieren.
    """

    return enthaelt_deutungscue(text)


def _dedupe_ordered_strs(values: Sequence[str]) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result


def _is_followup_prompt(text: str) -> bool:
    return _has_any_phrase(
        text,
        (
            "welche fragen",
            "anschlussfragen",
            "anschlussfrage",
            "forschungsfragen",
            "nächsten fragen",
            "nächsten fragen",
            "weitere fragen",
            "welche untersuchungen",
        ),
    )
