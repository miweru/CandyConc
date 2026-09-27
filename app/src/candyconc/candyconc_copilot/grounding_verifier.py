"""Pure decision/retry logic for the grounded answer's envelope->verdict cycle.

This module owns the *behaviour-preserving* slice of
``orchestrator._build_grounded_final_answer`` that drives the
synthesise -> verify -> retry loop for the answer envelope. It is deliberately
free of orchestrator-owned side effects (SSE emission, session-state writes,
``self._evidence_gaps`` mutation): the orchestrator keeps those and delegates
only the LLM-backed decision/assembly cycle here so the cycle can be unit-tested
with a *fake* ``run_structured_step`` callable (no live LLM).

The LLM call is injected as ``run_structured_step`` (the orchestrator passes its
bound ``_run_structured_step``). All grounding helpers are injected too, so this
module has no import-time dependency on ``analysis_grounding`` and stays cheap to
test.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Awaitable, Callable, List, Optional, Tuple

from .draft_sections import entwurfsdeutung
from .grounding_schemas import (
    _is_testable_hypothesis_claim as _schema_is_testable_hypothesis_claim,
)


_WORD_SKETCH_RELATION_SYNTHESIS_DOC = (
    "Formuliere aus den sichtbaren Word-Sketch-Relationslabels genau einen "
    "natürlichen, publikationsreifen interpretation-Claim. Dies ist ein "
    "Post-Tool-Schritt: Der Toollauf und alle quantitativen Beobachtungen sind "
    "bereits vollständig verifiziert. Die hier sichtbaren Facts sind bewusst "
    "auf Relationstyp und Label reduziert. Vergleiche ihre grammatischen "
    "Beziehungsdomänen. Der neue Claim handelt vom Relationsausschnitt selbst; "
    "Suchterm und Partner dürfen darin nicht als grammatische Akteure oder "
    "Rollenträger erscheinen. Eine "
    "bloße Aufzählung der beiden Labels mit 'und' ist keine Synthese; der "
    "relationale Unterschied oder ihr Nebeneinander muss ausdrücklich benannt "
    "werden. "
    "Erfinde "
    "keine Zahlen, Beispiele, Phrasen, Prävalenz oder fehlende Evidenz. "
    "Antworte ausschließlich als JSON gemäß Schema."
)

_WORD_SKETCH_UNIT_CLARIFICATION_DOC = (
    "Ergänze zu bereits verifizierten Word-Sketch-Beobachtungen genau einen "
    "kurzen observation-Claim, der ausschließlich die Zähleinheiten der im "
    "fertigen Text sichtbaren Rohfelder erklärt. Dies ist ein Post-Tool-Schritt: "
    "Die Partnerzeilen und ihre Werte sind bereits verifiziert und dürfen nicht "
    "wiederholt werden. Nutze nur die sichtbare Fact-ID, erfinde keine Zahlen, "
    "Interpretationen, Beispiele oder fehlende Evidenz. Antworte ausschließlich "
    "als JSON gemäß Schema."
)

_RESPONSE_REQUIREMENT_REPAIR_DOC = (
    "Vervollständige ausschließlich die ausdrücklich fehlenden Antwortslots "
    "aus generation_requirements.missing_response_requirements. Antworte nur "
    "als JSON nach Schema. Jeder Slot erhält genau einen eigenen Claim mit "
    "seiner response_requirement_id; erfülle alle completion_checks dieses "
    "Slots im selben sichtbaren Claim. Eine eng gekoppelte Bedingung wie das "
    "mögliche Widerlegungsergebnis einer Hypothese ist kein zweiter Claim und "
    "keine Überschrift. Bündele umgekehrt nie Beobachtung, Interpretation und "
    "Hypothese in einem Claim. Unterstützende Claims haben eine leere Slot-ID "
    "und genau einen der unter supporting_claim_kinds verlangten Typen. "
    "Formuliere gehaltvoll aus den sichtbaren Facts; freie Interpretation und "
    "fachliche Hypothesen sind erwünscht und müssen die Facts nicht bloß "
    "paraphrasieren. Erfinde keine Zahlen, Schwellen, Zitate, Entitäten oder "
    "bereits eingetretenen Gegenbefunde. Eine Hypothese wird ohne willkürliche "
    "Zahl prüfbar, indem sie eine erwartete Beziehung oder Kategorie und ein "
    "mögliches Gegenmuster nennt. Partielle KWIC-Belege dürfen eine solche "
    "Hypothese motivieren, sind aber ohne Kodierung keine Verteilung. "
    "Wenn mehrere fehlende Slots ausdrücklich konkurrierende Hypothesen "
    "verlangen, formuliere sie zur selben späteren Operationalisierung: "
    "Ihre unterschiedlichen Vorhersagen müssen durch ein einziges Ergebnis "
    "dieser Auswertung unterscheidbar sein. Zwei gleichzeitig mögliche "
    "Themen oder Analyseebenen sind kein Konkurrenzpaar. "
    "Ein Claim über Vielfalt, Kontrast oder Spannung mehrerer sichtbarer "
    "Beispiele zitiert alle dafür benötigten Facts; ein Einzelbeleg trägt "
    "keine Aussage über mehrere Beispiele. "
    "Technische IDs stehen nur in fact_ids, nie im Text. Wiederhole keine "
    "bereits verifizierten Claims und übernimm aus repair_candidates nur den "
    "tragfähigen Erkenntnisgedanken, nicht dessen zurückgewiesene Form."
)

_RELATED_OBJECT_BALANCED_SYNTHESIS_DOC = (
    "Formuliere natürliche, publikationsnahe Interpretationen der auditierten "
    "Passagen. Jeder Claim deutet nur die von ihm zitierten observed_facts; "
    "diese sind die einzige Evidenz. Erschließe eine konkrete Rahmung, "
    "Positionierung, Relation oder Rollenverteilung, statt den Quelltext nur "
    "nachzuerzählen. Analytische Begriffe dürfen neu sein, der behauptete "
    "Sachverhalt nicht. Kandidatenlabels lenken nur den Fokus und sind keine "
    "Evidenz. Bewahre die sichtbaren Akteure, "
    "Prädikate, Bewertungsobjekte, Stimme und Anbindung. Bloße "
    "Wortverwandtschaft macht zwei Prädikate nicht gleich; insbesondere kann "
    "ein Präfix die bezeichnete Relation verändern. Markiere Aussagen aus "
    "Korpusausschnitten als Stimme oder Rahmung der jeweiligen Passage, statt "
    "ihren propositionalen Inhalt als externe Tatsache zu formulieren. "
    "Wenn ein Fact sentence_units enthält, sind diese Satzgrenzen bindend: "
    "Ein Akteur oder Objekt aus einer Einheit übernimmt ohne sichtbaren "
    "Konnektor oder eindeutige Koreferenz kein Prädikat aus einer anderen. "
    "generation_requirements.stage_instruction benennt den jeweiligen Fokus. "
    "Jeder Claim bleibt für sich verständlich. Ein Verweis auf frühere oder "
    "andere Claims wie 'im Gegensatz dazu' oder 'zuvor dargestellt' ist nur "
    "zulässig, wenn derselbe Claim beide Seiten mit seinen Fact-IDs belegt. "
    "Technische Fact-IDs stehen nur in fact_ids. Wiederhole den vollständigen "
    "Quelltext nicht im Claim, da er separat als Evidenz angezeigt wird. "
    "Kurze wertende Quellenausdrücke bleiben bei ihrem sichtbaren Referenten. "
    "Führe keine externen Tatsachen, Zahlen, Häufigkeit, Prävalenz oder "
    "Korpusgeltung ein. Formuliere frei in der Sprache des Nutzers und nicht "
    "als Berichtsschablone. Antworte ausschließlich als JSON gemäß Schema."
)

_CONFIRMATION_LOCAL_GROUNDING_DOC = (
    "Prüfe jeden Claim nur gegen seine referenzierten observed_facts und "
    "klassifiziere jede Claim-ID genau einmal. Eine Passage belegt, was in ihr "
    "geäußert wird, nicht die externe Wahrheit der Äußerung. Akzeptiere eine "
    "eigenständige, tentative lokale Interpretation, wenn sie eine konkrete "
    "Rahmung, Positionierung oder kommunikative Funktion erschließt und dabei "
    "Prädikat, Polarität, Beteiligte, Bewertungsobjekt, Stimme und Anbindung "
    "bewahrt. Der analytische Wortlaut muss nicht in der Quelle stehen. Lehne "
    "eine als interpretation deklarierte bloße Zitatkopie oder mechanische "
    "Paraphrase ebenso ab wie erfundene Beziehungen, Rollen, Kausalität, "
    "Zahlen oder korpusweite Reichweite. Eine lokale Deutung muss keine "
    "übergeordnete Universalhypothese beweisen. Ein Fehler verwirft keine "
    "unabhängig tragfähigen Geschwister-Claims. Klassifiziere zusätzlich jeden "
    "retrieval_candidate_fact_id als accounted oder unaccounted. Die interne "
    "Kandidatenprüfung bleibt vollständig; der sichtbare Bericht darf dagegen "
    "kuratieren. Ein themenfremder Kandidat sowie ein weiterer Kandidat aus "
    "einer bereits durch einen zitierten Beleg vertretenen Kombination von "
    "Schlussrichtung und Bewertungsobjekttyp ist accounted, ohne selbst im "
    "Antworttext erscheinen zu müssen. Eine noch unvertretene Gegenrichtung "
    "oder ein anderer Bewertungsobjekttyp bleibt unaccounted. Wenn der Vertrag "
    "response_requirements enthält, klassifiziere außerdem jede Slot-ID genau "
    "einmal als fulfilled oder unfulfilled. Eine falsche Slot-Zuordnung verwirft "
    "nicht den sonst faktentreuen Claim; sie lässt ausschließlich den Slot offen. "
    "Eine konkret gezählte Antwortgruppe ohne Mindest- oder Bereichsmarker ist "
    "exakt. Lehne eine zusätzliche unzugeordnete Interpretation nur ab, wenn sie "
    "semantisch eine weitere Einheit dieser gezählten Gruppe ist; unabhängige "
    "Beobachtungen, Grenzen und Synthesen bleiben zulässig. "
    "Wähle pass nur bei vollständiger disjunkter Klassifikation. Antworte ausschließlich als "
    "JSON gemäß Schema."
)

_CONFIRMATION_RETRIEVAL_TOPICALITY_DOC = (
    "Klassifiziere ausschließlich die Themenrelevanz des sichtbaren Wortlauts. "
    "Nennt der Originalausschnitt target_topic selbst oder eine erkennbare "
    "Flexionsform, ist er thematisch relevant; knapper Kontext begrenzt dann "
    "nur die inhaltliche Deutung, nicht den Themenbezug. "
    "relevant gilt nur, wenn der Kandidat selbst target_topic, ein eindeutiges "
    "Synonym, eine beteiligte Gruppe, eine konkrete Teilpolitik oder einen "
    "typischen Vorgang sichtbar nennt. marginal gilt nur für einen im Wortlaut "
    "nachvollziehbaren indirekten Bezug. off_topic gilt, wenn der Bezug nur "
    "durch Hintergrundwissen, ähnliche Stimmung oder eine denkbare Anwendung "
    "ergänzt werden könnte. Suchrang und Suchanfrage sind keine Evidenz. quote "
    "muss die wörtlich sichtbare Themenbrücke enthalten; die Begründung darf "
    "keinen Gegenstand ergänzen, der nicht im Kandidaten steht. Prüfe unabhängig "
    "von der verlangten Wertung. Begründe ausschließlich die sichtbare "
    "sprachliche oder inhaltliche Themenbrücke oder ihr Fehlen. "
    "Prüfe jeden Kandidaten genau einmal und antworte nur als JSON."
)

_CONFIRMATION_RETRIEVAL_TOPICALITY_RECOVERY_DOC = (
    "Du prüfst eine fehlgeschlagene Themenklassifikation bereits ausgegebener "
    "Forschungsdaten. validation_issues benennt die konkret ungültigen "
    "Ausgabefelder. "
    "Formuliere deren reason neu und ausschließlich über die sichtbare "
    "Themenbrücke oder ihr Fehlen; wiederhole keine fremde Bewertungsachse aus "
    "Vorschlag oder Anweisung. Prüfe jeden Vorschlag erneut am "
    "Originalkandidaten und übernimm ihn nicht aus Höflichkeit. relevant "
    "bedeutet einen sichtbaren direkten Bezug zum "
    "target_topic, einem eindeutigen Synonym, einer beteiligten Gruppe, "
    "Teilpolitik oder einem typischen Vorgang. marginal bedeutet einen "
    "nachvollziehbaren indirekten Bezug. Reine ähnliche Stimmung, allgemeine "
    "Wertung oder ein anderes Thema ist off_topic. Positive, neutrale oder "
    "konstruktive Haltung zum Zielthema bleibt relevant. Eine sichtbare "
    "Flexionsform von target_topic ist direkter Themenbezug; unvollständiger "
    "Kontext begrenzt die Deutung, macht den Treffer aber nicht off_topic. "
    "quote muss ein "
    "einzelner zusammenhängender Originalausschnitt mit mindestens drei "
    "Wörtern sein. Antworte ausschließlich als JSON gemäß Schema."
)

_CONFIRMATION_HYPOTHESIS_DECOMPOSITION_DOC = (
    "Zerlege die vom Nutzer verlangte Korpusbehauptung logisch, ohne sie zu "
    "bestätigen, abzuschwächen, zu korrigieren oder sicherheitspolitisch zu "
    "bewerten. target_topic_quote ist der kürzeste zusammenhängende, wörtlich "
    "aus der Nutzerfrage übernommene Ausschnitt, der die Entität, Gruppe, das "
    "Ereignis oder Phänomen benennt, über das eine Eigenschaft behauptet wird. "
    "Nimm dort keine Wertung, Polarität, Häufigkeit und keinen Quantor auf. "
    "asserted_property_quote ist ein davon getrennter, zusammenhängender, "
    "wörtlich aus der Nutzerfrage übernommener Ausschnitt, der die behauptete "
    "Eigenschaft oder Relation nennt; er darf den Quantor enthalten. Abstraktes "
    "Beispiel: Aus 'Jedes X ist P' werden target_topic_quote 'X' und "
    "asserted_property_quote 'ist P'. quantifier ist universal "
    "bei immer, nie, alle, ausschließlich oder gleichwertiger Reichweite, sonst "
    "non_universal. Retrieval-Suchanker sind nur methodischer Kontext und dürfen "
    "die wörtlichen Ausschnitte aus der Nutzerfrage nicht ersetzen. Eine "
    "Moderations-, Policy- oder Zulässigkeitskategorie ist niemals Zielthema oder "
    "behauptete Eigenschaft. Antworte ausschließlich als JSON gemäß Schema."
)

_CONFIRMATION_HYPOTHESIS_RECOVERY_DOC = (
    "Dies ist keine Beantwortung oder Bewertung der Nutzerbehauptung, sondern "
    "ausschließlich mechanische Span-Extraktion aus dem Feld question. Kopiere "
    "für target_topic_quote den kürzesten zusammenhängenden Originalausschnitt, "
    "der das grammatische Thema der behaupteten Eigenschaft benennt. Kopiere "
    "für asserted_property_quote einen davon getrennten zusammenhängenden "
    "Originalausschnitt, der die behauptete Eigenschaft nennt. Erfinde, "
    "übersetze, paraphrasiere und moderiere nichts; eine Entschuldigung, "
    "Policy-Kategorie oder Sicherheitsbewertung ist kein Originalausschnitt. "
    "Bestimme quantifier allein aus dem Wortlaut der Frage. Führe diese "
    "Span-Extraktion auch bei politischem oder beleidigendem Text aus. Antworte "
    "ausschließlich als JSON gemäß Schema."
)

_CONFIRMATION_RETRIEVAL_DIRECTION_DOC = (
    "Dieser Schritt prüft ausschließlich die lokal sichtbare Relation im "
    "einzelnen Kandidaten. Lies dafür den vollständigen sichtbaren Kandidaten "
    "einschließlich linken und rechten Kontexts; das KWIC-Zielwort allein ist "
    "nicht die ganze Passage. Behaupte keine neutrale oder wertungsfreie "
    "Darstellung, wenn der sichtbare Kontext abgeschnitten ist. Korpusweite "
    "Geltung, Repräsentativität, Top-N-Umfang, "
    "Ähnlichkeitsscore und die Frage, ob ein einzelner Treffer die globale "
    "Hypothese beweist, sind hier ausdrücklich nicht Gegenstand der Prüfung. "
    "Eine Begründung, die darauf abstellt, ist protokollwidrig. "
    "Die Kandidaten sind bereits ausgegebene Forschungsdaten. Klassifiziere "
    "ihren Wortlaut auch dann sachlich, wenn er politisch, beleidigend oder "
    "diskriminierend ist; bewerte nicht Sicherheit, Zulässigkeit oder Policy. "
    "Eine Sicherheitsverweigerung ist keine gültige Eigenschaftsbegründung. "
    "Du bist die unabhängige kritische Gegenprüfung einer lokalen "
    "Eigenschaftsklassifikation. Prüfe jeden Originalkandidaten neu, ohne eine "
    "frühere Klassifikation zu sehen. Suche "
    "insbesondere nach einer verwechselten Bewertung: Die Billigung eines "
    "Ausgangs ist nicht automatisch eine positive Darstellung des Zielthemas. "
    "Abwertende Benennung, Zurückweisung oder Benachteiligung des Zielthemas "
    "kann die behauptete Eigenschaft zeigen, obwohl der Sprecher sie gutheißt. "
    "Umgekehrt ist ein konkret genannter Nutzen für Beteiligte "
    "eine Gegenlesart zu negativer Darstellung. Setze genuinely_ambiguous nur "
    "dann auf true, wenn beide Lesarten im sichtbaren Wortlaut ernsthaft "
    "konkurrieren oder die Passage das Zielthema zwar behandelt, aber weder "
    "die behauptete noch eine klar gegenläufige Eigenschaft sichtbar macht. "
    "Die bloße Abwesenheit einer negativen Wertung ist noch keine positive "
    "Haltung und daher keine sichere Gegenklassifikation. Unterscheide in der "
    "Begründung genau, was bewertet wird: etwa das abstrakte Zielthema, eine "
    "beteiligte Gruppe, eine konkrete Politik oder eine behauptete Folge. "
    "Schreibe dem Textautor keine Haltung zu, wenn der sichtbare Wortlaut nur "
    "eine zitierte oder nicht zurechenbare Proposition enthält. "
    "Unterscheide dabei Gebrauch von Erwähnung: Ein abwertender Ausdruck in "
    "einem Zitat, einer berichteten Äußerung oder einer metasprachlichen "
    "Bezeichnung ist nicht automatisch die Haltung der berichtenden Stimme. "
    "Wenn Einbettung und Stimme im Ausschnitt konkurrierende Wertungen tragen, "
    "klassifiziere die Richtung als genuinely_ambiguous statt die eingebettete "
    "Formulierung der gesamten Passage zuzuschreiben. Eine bloße Forderung "
    "oder Bedingung ist umgekehrt noch keine positive Wertung; dafür muss eine "
    "klar gegenläufige Bewertung im Wortlaut sichtbar sein. "
    "Klassifiziere zusätzlich evaluated_object_type danach, woran die "
    "sichtbare Wertung tatsächlich gebunden ist: target_topic für das "
    "Zielthema selbst, associated_group_or_actor für beteiligte Personen "
    "oder Gruppen, associated_policy_or_practice für eine Politik oder "
    "Praxis, associated_effect_or_outcome für eine behauptete Folge, "
    "associated_object nur als engste verbleibende Kategorie für ein sichtbar "
    "verwandtes, aber nicht genauer bestimmbares Objekt, "
    "target_context_without_evaluation für bloßen Themenkontext ohne lokale "
    "Wertung. Wähle immer das im Wortlaut erkennbare Objekt; eine pauschale "
    "Unklar-Kategorie gibt es absichtlich nicht. Verwandte Akteure, "
    "Politiken und Folgen sind analytisch relevant, aber nicht mit dem "
    "abstrakten Zielthema gleichzusetzen. Setze andernfalls "
    "asserted_property_visible genau danach, ob die lokale Eigenschaft am "
    "klassifizierten Bewertungsobjekt sichtbar ist. evaluated_object_quote "
    "kopiert den kürzesten zusammenhängenden Originalausschnitt, der genau "
    "dieses Bewertungsobjekt benennt; er darf weder das abstrakte Zielthema "
    "noch eine erfundene Oberkategorie einsetzen. "
    "Bei mehreren möglicherweise verschieden angebundenen Wertungen in einem "
    "Ausschnitt ordne genau eine Wertung ihrem grammatisch sichtbaren Objekt "
    "zu. Ein Schimpfwort vor einem finiten Verb bezeichnet nicht automatisch "
    "dessen nachgestelltes Objekt oder Komplement. "
    "verbatim_evaluative_source_phrases enthält jede kurze abwertende oder "
    "aufwertende Personen-, Gruppen- oder Objektbezeichnung, die für diese "
    "Einordnung relevant ist, wortgetreu als zusammenhängenden Ausschnitt; "
    "verwende eine leere Liste, wenn es keine gibt. "
    "reason ist für jeden Kandidaten eigenständig und nennt mindestens zwei "
    "Inhaltswörter aus dessen sichtbarem Wortlaut. Diskutiere dort weder, ob "
    "der Nutzer eine Klassifikation verlangt hat, noch den verfügbaren "
    "Tool-Space; Verweise wie 'same as above' sind ungültig. "
    "quote enthält genau einen zusammenhängenden Ausschnitt von mindestens "
    "drei aufeinanderfolgenden Wörtern aus dem Kandidaten: keine kombinierten "
    "Teilzitate, keine Auslassungspunkte. Prüfe jeden vorgelegten Kandidaten "
    "genau einmal. "
    "Antworte ausschließlich als JSON gemäß Schema."
)

_CONFIRMATION_RETRIEVAL_DIRECTION_REVIEW_DOC = (
    "Prüfe jeden Originalkandidaten unabhängig neu. Lies den vollständigen "
    "sichtbaren linken und rechten Kontext und nicht nur das Zielwort; aus "
    "abgeschnittenem Kontext darfst du keine Abwesenheit einer Wertung "
    "ableiten. Suche zuerst eine im Text "
    "sichtbare Brücke zu target_topic: Zielbegriff, eindeutiges Synonym, "
    "beteiligte Gruppe, Teilpolitik oder typischer Vorgang. Ähnliche Stimmung, "
    "allgemeine Kritik und bloß denkbare Anwendungen sind keine Brücke. Fehlt "
    "sie, sage in reason ausdrücklich, dass der Kandidat target_topic nicht "
    "behandelt, und setze asserted_property_visible=false, "
    "genuinely_ambiguous=true sowie "
    "evaluated_object_type=target_context_without_evaluation. Ist eine Brücke "
    "sichtbar, prüfe asserted_property nur am tatsächlich bewerteten Objekt. "
    "Unterscheide target_topic von Gruppe oder Akteur, Politik oder Praxis und "
    "Folge oder Ergebnis; erfinde keine Autorenhaltung. Fehlende Negativität "
    "allein ist keine positive Wertung. Trenne insbesondere den Gebrauch eines "
    "Ausdrucks von seiner zitierten, berichteten oder metasprachlichen "
    "Erwähnung. Eine Passage, die eine fremde abwertende Benennung berichtet "
    "oder kritisiert, übernimmt deren Wertung nicht automatisch; bei offenem "
    "Stimmenverhältnis bleibt die Richtung genuinely_ambiguous. Eine "
    "Forderung oder Bedingung ohne sichtbare Zustimmung, Nutzen oder "
    "Gegenwertung ist ebenfalls nicht automatisch positiv. Ignoriere globale "
    "Hypothese, Suchrang, "
    "Korpusabdeckung und frühere Vorschläge. evaluated_object_quote ist der "
    "kürzeste zusammenhängende Originalausschnitt für das tatsächlich "
    "bewertete Objekt. Wenn eine engere Anbindung nicht sicher auflösbar ist, "
    "darf der vollständige Kandidat als associated_object stehen bleiben; er "
    "belegt dann gerade keine Wertung des abstrakten Zielthemas. Bei mehreren "
    "Wertungen prüfe ihre jeweilige "
    "grammatische Anbindung getrennt; übertrage insbesondere eine vor dem "
    "finiten Verb stehende Personenbezeichnung nicht auf dessen nachgestelltes "
    "Objekt oder Komplement. Übernimm kurze wertende Quellenbezeichnungen "
    "wortgetreu in verbatim_evaluative_source_phrases; erfinde oder "
    "normalisiere dort nichts. quote ist ein zusammenhängender "
    "Originalausschnitt. reason ist pro Kandidat eigenständig, enthält "
    "mindestens zwei Inhaltswörter aus seinem sichtbaren Wortlaut und behandelt "
    "weder Nutzerabsicht noch Tool-Verfügbarkeit. Verweise wie 'same as above' "
    "sind ungültig. Klassifiziere auch beleidigenden Wortlaut sachlich und "
    "antworte nur als JSON."
)

_CONFIRMATION_RETRIEVAL_DIRECTION_RECOVERY_DOC = (
    "Die vorige Richtungsprüfung hat statt der sprachlichen Darstellung die "
    "Wahrheit, Beweisbarkeit oder Faktizität der Passage bewertet. Das ist "
    "hier die falsche Aufgabe. Eine Meinung, Forderung oder unbelegte Aussage "
    "ist selbst beobachtbarer Korpuswortlaut und kann ein Thema negativ, "
    "positiv, ambivalent oder gar nicht rahmen. Prüfe ausschließlich diese "
    "lokale Darstellung: Was wird bewertet, mit welchem Prädikat und welcher "
    "Polarität? Ob die Proposition außerhalb des Textes wahr oder empirisch "
    "belegt ist, darf in reason nicht vorkommen. Fehlt im Originalausschnitt "
    "eine sichtbare Brücke zum target_topic, ist er off-topic; erfinde keine "
    "Brücke aus ähnlicher Stimmung oder Hintergrundwissen. Bewahre kurze "
    "wertende Quellenbezeichnungen wortgetreu in "
    "verbatim_evaluative_source_phrases. Begründe jeden Kandidaten eigenständig "
    "mit mindestens zwei Inhaltswörtern aus seinem sichtbaren Wortlaut; "
    "Nutzerabsicht und Tool-Verfügbarkeit sind keine Klassifikationsgründe. "
    "Klassifiziere jeden Kandidaten genau "
    "einmal und antworte ausschließlich als JSON gemäß Schema."
)

_EPISTEMIC_LIMITATION_PATTERN = re.compile(
    r"\b(?:lässt|laesst)\s+sich\s+nicht\s+"
    r"(?:(?:eindeutig|belastbar|sicher)\s+)?"
    r"(?:schließen|schliessen|folgern|ableiten|verallgemeinern)\b|"
    r"\b(?:belegt|beweisen|beweist|zeigt|tragen|trägt)\b"
    r"[^.!?\n]{0,100}\b(?:nicht|kein(?:e|en|er|es)?)\b|"
    r"\b(?:cannot|can't|does\s+not|do\s+not)\b"
    r"[^.!?\n]{0,100}\b(?:conclude|establish|prove|generalise|generalize)\b",
    re.IGNORECASE,
)
_LOCAL_DIRECTION_SCOPE_CONTAMINATION_PATTERN = re.compile(
    r"\b(?:korpusweit|repräsentativ|repraesentativ|systematisch|universell|"
    r"global|gesamt(?:e|en|er|es)?\s+korpus|top[-‑–— ]?n|"
    r"ähnlichkeitsscore|aehnlichkeitsscore|"
    r"across\s+the\s+(?:entire\s+)?corpus|entire\s+corpus|"
    r"representative|systematic|universal|global|top[-‑–— ]?n|"
    r"similarity\s+score|definitive\s+proof|overall\s+sentiment)\b",
    re.IGNORECASE,
)
_EPISTEMIC_POSITIVE_TAIL_PATTERN = re.compile(
    r"\b(?:aber|jedoch|sondern|allerdings|but|however)\b"
    r"[^.!?\n]{0,180}\b(?:(?:zeig|beleg|beweis)\w*|ist|sind|"
    r"shows|demonstrates|proves|is|are)\b",
    re.IGNORECASE,
)
_RETRIEVAL_BALANCED_READING_PATTERN = re.compile(
    r"\b(?:gegenüber|gegenueber|nebeneinander|neben|zugleich|während|"
    r"waehrend|sowohl\b[^.!?\n]{0,160}\bals\s+auch|gemischt\w*|"
    r"heterogen\w*|uneinheitlich\w*|nicht\s+einheitlich\w*|"
    r"widersprech\w*|gegenläufig\w*|gegenlaeufig\w*|kontrast\w*)\b",
    re.IGNORECASE,
)
_RETRIEVAL_POSITIVE_READING_PATTERN = re.compile(
    r"\b(?:positiv\w*|neutral\w*|konstruktiv\w*|wohlwoll\w*|"
    r"zustimm\w*|positive|neutral|constructive|favourab\w*|favorab\w*)\b",
    re.IGNORECASE,
)
_RETRIEVAL_AFFIRMATIVE_POSITIVE_PATTERN = re.compile(
    r"\b(?:positiv\w*|konstruktiv\w*|wohlwoll\w*|zustimm\w*|"
    r"positive|constructive|favourab\w*|favorab\w*)\b",
    re.IGNORECASE,
)
_RETRIEVAL_NEGATIVE_READING_PATTERN = re.compile(
    r"\b(?:negativ\w*|abwert\w*|feindselig\w*|stigmatis\w*|"
    r"destruktiv\w*|negative|derogator\w*|hostile|stigmati[sz]\w*)\b",
    re.IGNORECASE,
)
_TARGET_EVALUATIVE_PREDICATE_PATTERN = re.compile(
    r"\b(?:bedroh\w*|gefahr\w*|schäd\w*|schaed\w*|zerstör\w*|"
    r"zerstoer\w*|problem\w*|belast\w*|feind\w*|chance\w*|"
    r"bereicher\w*|nütz\w*|nuetz\w*|legitim\w*|rechtsstaat\w*|"
    r"threat\w*|danger\w*|harm\w*|destroy\w*|benefit\w*|"
    r"enrich\w*|legitim\w*)\b",
    re.IGNORECASE,
)
_NEGATED_NEGATIVE_READING_PATTERN = re.compile(
    r"\b(?:not|nicht|kein(?:e|en|er|es)?|ohne)\b[^.!?;\n]{0,70}"
    r"\b(?:negativ\w*|abwert\w*|feindselig\w*|negative|derogator\w*|hostile)\b",
    re.IGNORECASE,
)
_NEGATED_POSITIVE_READING_PATTERN = re.compile(
    r"\b(?:not|nicht|kein(?:e|en|er|es)?|ohne)\b[^.!?;\n]{0,70}"
    r"\b(?:positiv\w*|neutral\w*|konstruktiv\w*|positive|neutral|constructive)\b",
    re.IGNORECASE,
)
_AMBIGUOUS_POLARITY_PATTERN = re.compile(
    r"\b(?:neutral\w*|unklar\w*|mehrdeutig\w*|ambig\w*|"
    r"möglicherweise|moeglicherweise|eventuell|vielleicht|"
    r"oder\s+(?:sogar\s+)?positiv\w*|bzw\.?\s+positiv\w*|"
    r"neutral|unclear|ambiguous|possibly|perhaps|maybe|"
    r"or\s+(?:even\s+)?positive)\b",
    re.IGNORECASE,
)
_EXPLICIT_POLARITY_UNCERTAINTY_PATTERN = re.compile(
    r"\b(?:unklar\w*|offen\w*|mehrdeutig\w*|ambig\w*|"
    r"nicht\s+eindeutig\w*|unclear\w*|ambiguous\w*|"
    r"not\s+clear\w*|not\s+unambiguous\w*)\b",
    re.IGNORECASE,
)
_PROPERTY_REFUTATION_MARKER_PATTERN = re.compile(
    r"\b(?:refut\w*|contradict\w*|counter(?:s|ed|ing)?|oppose\w*|"
    r"widerleg\w*|widerspr\w*|entkräft\w*|entkraeft\w*|"
    r"gegenbeleg\w*)\b",
    re.IGNORECASE,
)
_NEGATED_PROPERTY_REFUTATION_PATTERN = re.compile(
    r"\b(?:not|never|cannot|can't|does\s+not|doesn't|do\s+not|don't|"
    r"nicht|nie|kein(?:e|en|er|es)?)\b[^.!?;\n]{0,45}"
    r"\b(?:refut\w*|contradict\w*|counter(?:s|ed|ing)?|oppose\w*|"
    r"widerleg\w*|widerspr\w*|entkräft\w*|entkraeft\w*|"
    r"gegenbeleg\w*)\b",
    re.IGNORECASE,
)
_CLASSIFICATION_REFUSAL_PATTERN = re.compile(
    r"\b(?:according\s+to\s+(?:the\s+)?policy|safety\s+policy|"
    r"content\s+policy|disallowed|not\s+allowed|cannot\s+(?:classify|provide)|"
    r"(?:the\s+)?user\s+(?:did\s+not|didn't|has\s+not)\s+(?:explicitly\s+)?"
    r"(?:ask|request)(?:ed)?\s+(?:for\s+)?(?:an?\s+)?"
    r"(?:analysis|classification)|"
    r"according\s+to\s+(?:the\s+)?instruction|"
    r"only\s+answer\s+what\s+can\s+be\s+answered\s+without\s+tool|"
    r"unable\s+to\s+generate\s+(?:a\s+)?valid\s+response|"
    r"format\b[^.!?\n]{0,80}\bnot\s+(?:recognized|recognised)|"
    r"no\s+claims?\s+(?:were|was)\s+(?:evaluated|classified)|"
    r"no\s+explicit\s+verification\s+request|"
    r"request\s+was\s+not\s+to\s+provide\s+(?:a\s+)?verdict|"
    r"system\s+cannot\s+comply|"
    r"same\s+as\s+(?:stated\s+)?above|wie\s+(?:bereits\s+)?oben|"
    r"policy\s+prohibits|laut\s+(?:der|den)\s+richtlinie|"
    r"aus\s+sicherheitsgründen|unzulässig|darf\s+nicht\s+(?:klassifiziert|"
    r"wiedergegeben|bereitgestellt))\b",
    re.IGNORECASE,
)
_MODERATION_TAXONOMY_PATTERN = re.compile(
    r"\b(?:hate\s+speech|hateful(?:\s+(?:language|content))?|"
    r"extremis(?:m|t|tic)(?:\W+(?:laden|language|content|material))?|"
    r"violent\s+extremism|"
    r"(?:direct\s+)?call\s+(?:for|to)\s+violence|"
    r"incitement\s+to\s+violence|protected\s+class|"
    r"hassrede|hasserfüllt(?:e|er|en|es)?(?:\s+inhalt)?|"
    r"extremis(?:mus|tisch(?:e|er|en|es)?)(?:\s+inhalt)?|"
    r"gewaltaufruf|aufruf\s+zu(?:r)?\s+gewalt)\b",
    re.IGNORECASE,
)
_DIRECTION_FACTICITY_CONTAMINATION_PATTERN = re.compile(
    r"\b(?:cannot|can't|can\s+not|could\s+not|not)\b"
    r"[^.!?\n]{0,100}\b(?:verif\w*|objectiv\w*|fact(?:ual)?\w*|"
    r"empiric\w*|evidence)\b|"
    r"\b(?:opinion|narrative|claim|statement)\b[^.!?\n]{0,100}"
    r"\b(?:rather\s+than|not)\b[^.!?\n]{0,40}\b(?:fact\w*|"
    r"verif\w*)\b|"
    r"\b(?:nicht|kein(?:e|en|er|es)?)\b[^.!?\n]{0,100}"
    r"\b(?:belegbar\w*|überprüfbar\w*|ueberpruefbar\w*|"
    r"verifizierbar\w*|faktisch\w*|objektiv\w*|empirisch\w*)\b|"
    r"\b(?:meinung|behauptung|narrativ)\b[^.!?\n]{0,100}"
    r"\b(?:statt|anstelle|keine?)\b[^.!?\n]{0,40}\b(?:fakt\w*|"
    r"beleg\w*)\b",
    re.IGNORECASE,
)
_TOPICALITY_NEGATION_PATTERN = re.compile(
    r"\b(?:unrelated|irrelevant|off[- ]topic)\b|"
    r"\b(?:does|do)\s+not\s+(?:(?:directly|clearly|specifically)\s+)?"
    r"(?:relate|refer|address|concern|mention|name|discuss)\b|"
    r"\b(?:no|without)\s+(?:(?:clear|direct)\s+)?"
    r"(?:relation|connection|reference)\b|"
    r"\b(?:kein(?:e|en|er|es)?|ohne)\s+"
    r"(?:(?:klar(?:e|en|er|es)?|direkt(?:e|en|er|es)?)\s+)?"
    r"(?:bezug|zusammenhang|verbindung)\b|"
    r"\bnicht\s+(?:das|zum|mit\s+dem)\s+(?:zielthema|thema)\b",
    re.IGNORECASE,
)
_TOPICALITY_AFFIRMATION_PATTERN = re.compile(
    r"\b(?:directly|clearly)\s+(?:relevant|related|addresses|concerns)\b|"
    r"\b(?:clear|direct)\s+(?:relation|connection|reference)\b|"
    r"\b(?:klar(?:er|e|en|es)?|direkt(?:er|e|en|es)?|eindeutig(?:er|e|en|es)?)"
    r"\s+(?:bezug|zusammenhang|verbindung)\b",
    re.IGNORECASE,
)
_EXPLICIT_CLAIM_ACCEPTANCE_PATTERN = re.compile(
    r"\b(?:is|was)\s+(?:fully\s+|therefore\s+|explicitly\s+)?accepted\b|"
    r"\b(?:wird|ist)\s+(?:vollständig\s+|vollstaendig\s+|daher\s+|"
    r"ausdrücklich\s+|ausdruecklich\s+)?(?:akzeptiert|angenommen)\b",
    re.IGNORECASE,
)
_ACCEPTANCE_ONLY_FEEDBACK_PATTERN = re.compile(
    r"\b(?:accepted|fully\s+supported|correctly|satisf(?:y|ies|ied)|"
    r"meets?\s+the\s+requirement|no\s+disallowed|all\s+claims\s+reference|"
    r"akzeptiert|vollständig\s+belegt|vollstaendig\s+belegt|"
    r"erfüllt\s+die\s+anforderung|erfuellt\s+die\s+anforderung)\b",
    re.IGNORECASE,
)
_NEGATIVE_FEEDBACK_PATTERN = re.compile(
    r"\b(?:reject(?:ed|ion)?|fail(?:s|ed|ure)?|missing|cannot|unfulfilled|"
    r"invalid|however|but|whereas|verworfen|abgelehnt|fehlt|fehlend|"
    r"unerfüllt|unerfuellt|ungültig|ungueltig|jedoch|aber)\b",
    re.IGNORECASE,
)

_CANDIDATE_QUOTE_WRAPPERS = (
    ('"', '"'),
    ("'", "'"),
    ("„", "“"),
    ("“", "”"),
    ("‚", "‘"),
    ("«", "»"),
    ("‹", "›"),
    ("`", "`"),
)

_EVALUATIVE_SOURCE_CUE_PATTERN = re.compile(
    r"\b(?:abwert\w*|beleidig\w*|beschimpf\w*|pejorativ\w*|"
    r"pejorative|derogator\w*|disparag\w*|stigmati[sz]\w*|slur\w*|"
    r"evaluativ\w*|wertend\w*|wertgelad\w*|"
    r"bezeichn\w*|benenn\w*|labels?\b[^.!?\n]{0,50}\bas|"
    r"refers?\b[^.!?\n]{0,50}\bas|"
    r"negative\s+(?:term|label|word(?:ing)?|language)|"
    r"charged\s+(?:term|word|language)|loaded\s+(?:term|word|language)|"
    r"uses?\s+(?:the\s+)?(?:term|word|label)|"
    r"fram\w*[^.!?\n]{0,100}\b(?:negativ\w*|positiv\w*|"
    r"derogator\w*|pejorativ\w*))\b",
    re.IGNORECASE,
)
_REPORTED_EVALUATION_CUE_PATTERN = re.compile(
    r"\b(?:bericht\w*|zitier\w*|twitter\w*|schreib\w*|sag\w*|"
    r"äußer\w*|aeusser\w*|nenn(?:t|te|ten|en|e)|"
    r"bezeichn(?:et|ete|eten|en)|verwend\w*|"
    r"gebrauch\w*|kritis\w*|kritik\w*|problematis\w*|distanzier\w*|"
    r"unterstell\w*|behaupt\w*|"
    r"report\w*|quot\w*|tweet\w*|writ\w*|say\w*|call\w*|"
    r"critic\w*|distance\w*|alleg\w*|claim\w*)\b",
    re.IGNORECASE,
)
_METALINGUISTIC_SOURCE_NOUN_PATTERN = re.compile(
    r"\b(?:\w*begriff\w*|wortwahl\w*|\w*ausdruck\w*|"
    r"\w*bezeichnung\w*|\w*formulierung\w*|rhetorik\w*|"
    r"\w*term\w*|wording\w*|expression\w*|phrase\w*|rhetoric\w*)\b",
    re.IGNORECASE,
)
_EXCLUSION_OR_RESTRICTION_PATTERN = re.compile(
    r"\b(?:nicht\s+(?:aufgenommen|zugelassen|hereingelassen|akzeptiert)|"
    r"abweis\w*|abschieb\w*|ausschließ\w*|ausschliess\w*|"
    r"zurückweis\w*|zurueckweis\w*|verhinder\w*|begrenz\w*|"
    r"stop\w*|verbot\w*|"
    r"not\s+(?:admitted|accepted|allowed|let\s+in)|"
    r"reject\w*|deport\w*|exclud\w*|prevent\w*|restrict\w*|ban\w*)\b",
    re.IGNORECASE,
)
_POSITIVE_CONSEQUENCE_PATTERN = re.compile(
    r"\b(?:positiv\w*|vorteil\w*|nütz\w*|nuetz\w*|gut(?:e|en|er|es)?|"
    r"positive\w*|benefit\w*|advantage\w*|good)\b",
    re.IGNORECASE,
)
_ASSESSMENT_QUOTE_WRAPPERS = (
    ('"', '"'),
    ("„", "“"),
    ("“", "”"),
    ("‚", "‘"),
    ("«", "»"),
    ("‹", "›"),
    ("`", "`"),
)
_EXPLICIT_SOURCE_CAUSAL_MARKER = re.compile(
    r"\b(?:wegen|aufgrund|infolge|because\s+of|due\s+to)\b",
    re.IGNORECASE,
)
_CLAIM_CAUSAL_SIDE_PATTERNS = (
    re.compile(
        r"(?P<cause>[^.!?\n]{2,180}?)\bals\s+(?:Grund|Ursache)\s+"
        r"(?:(?:für|fuer|von)\s+|(?:des|der)\s+)"
        r"(?P<effect>[^.!?\n]{2,180})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<effect>[^.!?\n]{2,180}?)\b(?:wegen|aufgrund|infolge)\s+"
        r"(?P<cause>[^.!?\n]{2,180})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<cause>[^.!?\n]{2,180}?)\b(?:verursach\w*|bewirk\w*|"
        r"bedingt\w*)\s+(?P<effect>[^.!?\n]{2,180})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<cause>[^.!?\n]{2,180}?)\b(?:führ\w*|fuehr\w*)\s+dazu\s*,?\s*"
        r"dass\s+(?P<effect>[^.!?\n]{2,180})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<cause>[^.!?\n]{2,180}?)\bals\s+Ursache\s+dar\s*,?\s*"
        r"(?:warum|weshalb|wodurch)\s+(?P<effect>[^.!?\n]{2,180})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<effect>[^.!?\n]{2,180}?)\b(?:weil|because)\s+"
        r"(?P<cause>[^.!?\n]{2,180})",
        re.IGNORECASE,
    ),
)
_CAUSAL_ABSENCE_REASON_PATTERN = re.compile(
    r"(?:\b(?:kein\w*|nicht|fehl\w*|lacks?|no|not|without)\b"
    r"[^.!?\n]{0,120}\b(?:kausal\w*|ursach\w*|grund|verursach\w*|caus\w*|link\w*)\b)|"
    r"(?:\b(?:kausal\w*|ursach\w*|grund|verursach\w*|caus\w*|link\w*)\b"
    r"[^.!?\n]{0,120}\b(?:kein\w*|nicht|fehl\w*|lacks?|no|not|without)\b)",
    re.IGNORECASE,
)
_CAUSAL_EXCLUSIVITY_PATTERN = re.compile(
    r"\b(?:allein\w*|einzig\w*|hauptursach\w*|ausschließlich\w*|"
    r"ausschliesslich\w*|sole\w*|only\s+cause|primary\s+cause)\b",
    re.IGNORECASE,
)
_NONLITERAL_VALENCE_REJECTION_PATTERN = re.compile(
    r"\b(?:not|nicht|kein\w*|missing|fehl\w*|absent)\b[^.!?\n]{0,140}"
    r"\b(?:source|quelle|text|passage|wortlaut|verbatim|wörtlich|woertlich)\b|"
    r"\b(?:source|quelle|text|passage|wortlaut)\b[^.!?\n]{0,80}"
    r"\b(?:not|no|nicht|kein\w*|missing|fehl\w*|absent)\b[^.!?\n]{0,80}"
    r"\b(?:statement|claim|evidence|mention\w*|aussage|beleg|hinweis|"
    r"erwähn\w*|erwaehn\w*)\b|"
    r"\b(?:not\s+present|not\s+verbatim|nicht\s+(?:vorhanden|enthalten|"
    r"wörtlich|woertlich))\b",
    re.IGNORECASE,
)
_ANALYTICAL_VALENCE_LABEL_PATTERN = re.compile(
    r"(?:\b(?:negativ\w*|positiv\w*|neutral\w*|ambivalent\w*|abwert\w*|"
    r"feindselig\w*|negative|positive|neutral|ambivalent|derogator\w*|"
    r"hostile)\b[^.!?\n]{0,35}\b(?:rahm\w*|frame\w*|framing|"
    r"bewert\w*|darstell\w*|deutung\w*|stance|evaluation|portrayal|"
    r"portrays?|context)\b)|"
    r"(?:\b(?:negativ\w*|positiv\w*|neutral\w*|ambivalent\w*|abwert\w*|"
    r"pejorativ\w*|feindselig\w*|kritisch\w*|negative|positive|neutral|"
    r"ambivalent|derogator\w*|pejorative|hostile|critical)\b"
    r"[^.!?\n]{0,35}\b(?:ausdruck\w*|begriff\w*|wortwahl\w*|"
    r"bezeichnung\w*|formulierung\w*|haltung\w*|term\w*|wording\w*|"
    r"label\w*|expression\w*|stance\w*)\b)|"
    r"(?:\b(?:ausdruck\w*|begriff\w*|wortwahl\w*|bezeichnung\w*|"
    r"formulierung\w*|haltung\w*|term\w*|wording\w*|label\w*|"
    r"expression\w*|stance\w*)\b[^.!?\n]{0,35}"
    r"\b(?:negativ\w*|positiv\w*|neutral\w*|ambivalent\w*|abwert\w*|"
    r"pejorativ\w*|feindselig\w*|kritisch\w*|negative|positive|neutral|"
    r"ambivalent|derogator\w*|pejorative|hostile|critical)\b)|"
    r"(?:\b(?:rahm\w*|frame\w*|framing|bewert\w*|darstell\w*|"
    r"deutung\w*|stance|evaluation|portrayal|portrays?|context)\b"
    r"[^.!?\n]{0,35}\b(?:negativ\w*|positiv\w*|neutral\w*|"
    r"ambivalent\w*|abwert\w*|feindselig\w*|negative|positive|neutral|"
    r"ambivalent|derogator\w*|hostile)\b)",
    re.IGNORECASE,
)
_HARD_RELATION_MISMATCH_PATTERN = re.compile(
    r"\b(?:participant\w*|beteilig\w*|sprecher\w*|speaker\w*|adressat\w*|"
    r"subject\w*|subjekt\w*|object\s+attachment|anbindung\w*|"
    r"causal\w*|kausal\w*|ursach\w*|because|wegen|polarity\w*|"
    r"polarität\w*|polaritaet\w*|opposite|umgekehrt\w*|number\w*|zahl\w*|"
    r"entity\s+type|entitätstyp\w*|entitaetstyp\w*|scope\w*|reichweite\w*|"
    r"universal\w*|korpusweit\w*)\b",
    re.IGNORECASE,
)
_LITERAL_PREDICATE_MODALITY_REJECTION_PATTERN = re.compile(
    r"\b(?:mandatory|mandate\w*|obligation\w*|requirement\w*|necessit\w*|"
    r"enforce\w*|forcibl\w*|verpflicht\w*|erfordernis\w*|notwendig\w*|"
    r"erzwing\w*|zwang\w*|gebot\w*)\b",
    re.IGNORECASE,
)


def _normalise_candidate_quote(value: Any) -> str:
    """Remove presentational quote wrappers before exact source anchoring."""

    quote = " ".join(str(value or "").split())
    for _ in range(2):
        unwrapped = quote
        for opening, closing in _CANDIDATE_QUOTE_WRAPPERS:
            if (
                len(quote) > len(opening) + len(closing)
                and quote.startswith(opening)
                and quote.endswith(closing)
            ):
                unwrapped = quote[len(opening) : -len(closing)].strip()
                break
        if unwrapped == quote:
            break
        quote = unwrapped
    quote = re.sub(r"^(?:\.{3}|…)+\s*", "", quote).strip()
    quote = re.sub(r"\s*(?:\.{3}|…)+$", "", quote).strip()
    return quote


def _has_sentence_terminal_punctuation(value: Any) -> bool:
    """Ignore punctuation used only as a separator inside a number."""

    surface = re.sub(r"(?<=\d)[.,](?=\d)", "", str(value or ""))
    return re.search(r"[.!?]", surface) is not None


def _ensure_sentence_terminal_punctuation(value: Any) -> str:
    """Finish model prose after projected citation markers are removed."""

    surface = str(value or "").strip()
    if not surface or re.search(r"[.!?…][\"'”’»›)\]]*$", surface):
        return surface
    return surface + "."


def _candidate_quote_is_anchored(quote: str, source_surface: str) -> bool:
    """Accept exact text or the same contiguous words across typography."""

    normalised_quote = " ".join(str(quote or "").casefold().split())
    normalised_source = " ".join(
        str(source_surface or "").casefold().split()
    )
    if not normalised_quote:
        return False
    if normalised_quote in normalised_source:
        return True
    quote_tokens = re.findall(r"\w+", normalised_quote, re.UNICODE)
    source_tokens = re.findall(r"\w+", normalised_source, re.UNICODE)
    if len(quote_tokens) < 3 or len(quote_tokens) > len(source_tokens):
        return False
    width = len(quote_tokens)
    return any(
        source_tokens[index : index + width] == quote_tokens
        for index in range(len(source_tokens) - width + 1)
    )


def _assessment_evaluative_source_phrases(
    assessment: dict[str, Any],
) -> List[str]:
    """Recover source labels that the candidate audit already identified.

    The audit reason is not evidence. A quoted phrase becomes a constraint only
    when it is also a contiguous part of the raw candidate excerpt.
    """

    reason = " ".join(str(assessment.get("reason") or "").split())
    source = " ".join(str(assessment.get("quote") or "").split())
    if not source or _EVALUATIVE_SOURCE_CUE_PATTERN.search(reason) is None:
        return []
    phrases: List[str] = []
    for opening, closing in _ASSESSMENT_QUOTE_WRAPPERS:
        pattern = re.compile(
            re.escape(opening)
            + r"([^\n]{1,120}?)"
            + re.escape(closing)
        )
        for match in pattern.finditer(reason):
            phrase = _normalise_candidate_quote(match.group(1))
            tokens = re.findall(r"\w+", phrase, re.UNICODE)
            if (
                tokens
                and len(tokens) <= 8
                and _candidate_quote_is_anchored(phrase, source)
            ):
                phrases.append(phrase)
    return _dedupe_ordered_strs(phrases)


def _is_minimal_evaluative_source_label(value: Any) -> bool:
    """Keep binding constraints limited to labels, not whole propositions."""

    surface = " ".join(str(value or "").split())
    tokens = [
        token.casefold()
        for token in re.findall(r"\w+", surface, re.UNICODE)
    ]
    if not 1 <= len(tokens) <= 4:
        return False
    if tokens[0] in {
        "als",
        "auf",
        "das",
        "dem",
        "den",
        "der",
        "die",
        "durch",
        "dann",
        "erst",
        "für",
        "fuer",
        "gegen",
        "in",
        "jetzt",
        "mit",
        "now",
        "of",
        "then",
        "the",
        "to",
        "von",
        "wegen",
        "with",
        "without",
        "zu",
        "zuerst",
        "anschließend",
        "anschliessend",
    }:
        return False
    if any(
        token
        in {
            "are",
            "gilt",
            "gelten",
            "hat",
            "haben",
            "is",
            "ist",
            "sich",
            "sind",
            "war",
            "waren",
            "werden",
            "wird",
        }
        for token in tokens
    ):
        return False
    if (
        _ADVOCACY_PREDICATE_PATTERN.search(surface)
        or _REPORTING_PREDICATE_PATTERN.search(surface)
    ):
        return False
    return True


def _candidate_has_reported_or_metalinguistic_evaluation(
    fact_payload: dict[str, Any],
) -> bool:
    """Keep quoted or discussed evaluations separate from narrator stance."""

    source = _candidate_source_quote(fact_payload)
    if not source or _REPORTED_EVALUATION_CUE_PATTERN.search(source) is None:
        return False
    has_metalinguistic_noun = (
        _METALINGUISTIC_SOURCE_NOUN_PATTERN.search(source) is not None
    )
    has_quoted_segment = any(
        opening in source and closing in source.split(opening, 1)[1]
        for opening, closing in _CANDIDATE_QUOTE_WRAPPERS
    )
    return has_metalinguistic_noun or has_quoted_segment


def _candidate_praises_exclusion_or_restriction(
    fact_payload: dict[str, Any],
) -> bool:
    """Recognise positive consequences attached to excluding the topic."""

    source = _candidate_source_quote(fact_payload)
    return bool(
        source
        and _EXCLUSION_OR_RESTRICTION_PATTERN.search(source)
        and _POSITIVE_CONSEQUENCE_PATTERN.search(source)
    )


_EXCHANGE_DIRECTION_PATTERN = re.compile(
    r"\b(?:her|rein)\s+mit\s+(?P<welcome>[^.!?\n]{1,100}?)\s+"
    r"(?:,|;|\bund\b|\baber\b)\s*"
    r"(?:raus|weg)\s+mit\s+(?P<reject>[^.!?\n]{1,100})|"
    r"\b(?:raus|weg)\s+mit\s+(?P<reject_first>[^.!?\n]{1,100}?)\s+"
    r"(?:,|;|\bund\b|\baber\b)\s*"
    r"(?:her|rein)\s+mit\s+(?P<welcome_second>[^.!?\n]{1,100})",
    re.IGNORECASE,
)


def _target_exchange_direction(source_text: str, target_topic: str) -> str:
    """Resolve the target side of an explicit ``her mit X / raus mit Y`` contrast."""

    for match in _EXCHANGE_DIRECTION_PATTERN.finditer(str(source_text or "")):
        welcome = match.group("welcome") or match.group("welcome_second") or ""
        reject = match.group("reject") or match.group("reject_first") or ""
        welcomed_target = _related_relation_token_count(welcome, target_topic) > 0
        rejected_target = _related_relation_token_count(reject, target_topic) > 0
        if welcomed_target != rejected_target:
            return "welcomed" if welcomed_target else "rejected"
    return ""


_INTERPERSONAL_EXCHANGE_CLAIM_PATTERN = re.compile(
    r"\b(?:bereitschaft|offenheit|interesse|wunsch)\w*\b"
    r"[^.!?\n]{0,80}\b(?:austausch|dialog|gespräch|gespraech|"
    r"kommunikation|verständigung|verstaendigung|kontakt)\w*\b|"
    r"\b(?:austausch|dialog|gespräch|gespraech|kommunikation|"
    r"verständigung|verstaendigung|kontakt)\w*\b"
    r"[^.!?\n]{0,40}\b(?:mit|zwischen)\b",
    re.IGNORECASE,
)


def _recasts_exchange_contrast_as_interpersonal_relation(
    source_text: str,
    claim_text: str,
    target_topic: str,
) -> bool:
    """Keep a replacement contrast distinct from dialogue or interaction."""

    source = " ".join(str(source_text or "").split())
    claim = " ".join(str(claim_text or "").split())
    return bool(
        _EXCHANGE_DIRECTION_PATTERN.search(source)
        and _INTERPERSONAL_EXCHANGE_CLAIM_PATTERN.search(claim)
        and _INTERPERSONAL_EXCHANGE_CLAIM_PATTERN.search(source) is None
        and (
            not str(target_topic or "").strip()
            or _related_relation_token_count(claim, target_topic) > 0
        )
    )


def _project_retrieval_assessment(
    assessment: dict[str, Any],
    projected_fact_id: str,
) -> dict[str, Any]:
    projected = {
        **assessment,
        "fact_id": projected_fact_id,
        "assessment_is_evidence": False,
    }
    # Re-add this field only after validation below.  Leaving the raw value in
    # place when every candidate is filtered out turns whole propositions into
    # binding labels and suppresses otherwise faithful interpretations.
    projected.pop("verbatim_evaluative_source_phrases", None)
    source = " ".join(str(assessment.get("quote") or "").split())
    reason = " ".join(str(assessment.get("reason") or "").split())
    reason_identifies_evaluation = bool(
        _EVALUATIVE_SOURCE_CUE_PATTERN.search(reason)
    )
    explicit_phrases = [
        _normalise_candidate_quote(value)
        for value in list(
            assessment.get("verbatim_evaluative_source_phrases", []) or []
        )
    ]
    reason_phrases = _assessment_evaluative_source_phrases(assessment)
    phrases = _dedupe_ordered_strs(
        [
            phrase
            for phrase in explicit_phrases
            if phrase
            and reason_identifies_evaluation
            and (
                not reason_phrases
                or phrase in reason_phrases
            )
            and len(re.findall(r"\w+", phrase, re.UNICODE)) <= 8
            and _candidate_quote_is_anchored(phrase, source)
        ]
        + reason_phrases
    )
    phrases = [
        phrase
        for phrase in phrases
        if _is_minimal_evaluative_source_label(phrase)
    ]
    if phrases:
        projected["verbatim_evaluative_source_phrases"] = phrases
    return projected


def _metalinguistic_source_label_phrases(
    source_surface: str,
    reason: str,
) -> List[str]:
    """Recover a quoted source label when the audit identifies reported wording."""

    source = " ".join(str(source_surface or "").split())
    if _EVALUATIVE_SOURCE_CUE_PATTERN.search(str(reason or "")) is None:
        return []
    phrases: List[str] = []
    noun = (
        r"(?:[\wÄÖÜäöüß-]*(?:begriff|ausdruck|bezeichnung|term|label)|"
        r"wortwahl)"
    )
    for opening, closing in _ASSESSMENT_QUOTE_WRAPPERS:
        pattern = re.compile(
            rf"(?P<label>\b{noun})\s*{re.escape(opening)}\s*"
            rf"(?P<term>[^\n{re.escape(closing)}]{{1,80}}?)\s*"
            rf"{re.escape(closing)}",
            re.IGNORECASE,
        )
        for match in pattern.finditer(source):
            phrase = (
                f"{match.group('label').strip()} "
                f"{opening}{match.group('term').strip()}{closing}"
            )
            if _is_minimal_evaluative_source_label(phrase):
                phrases.append(phrase)
    return _dedupe_ordered_strs(phrases)


def _relation_content_tokens(value: str) -> List[str]:
    stopwords = {
        "aber",
        "als",
        "auch",
        "dass",
        "dieser",
        "diesem",
        "durch",
        "einer",
        "eines",
        "passage",
        "quelle",
        "source",
        "text",
        "wird",
    }
    return [
        token.casefold()
        for token in re.findall(r"[^\W\d_]+", str(value or ""), re.UNICODE)
        if len(token) >= 4 and token.casefold() not in stopwords
    ]


def _related_relation_token_count(left: str, right: str) -> int:
    left_tokens = _relation_content_tokens(left)
    right_tokens = _relation_content_tokens(right)
    matched_right: set[int] = set()
    matches = 0
    for left_token in left_tokens:
        for index, right_token in enumerate(right_tokens):
            if index in matched_right:
                continue
            if left_token == right_token or (
                min(len(left_token), len(right_token)) >= 5
                and left_token[:5] == right_token[:5]
            ):
                matched_right.add(index)
                matches += 1
                break
    return matches


_PASSAGE_REPORTING_TOKENS = {
    "ausschnitt",
    "beleg",
    "berichtet",
    "beschreibt",
    "betont",
    "behauptet",
    "bezeichnet",
    "darstellung",
    "erwähnt",
    "erwaehnt",
    "fest",
    "nennt",
    "passage",
    "präsentiert",
    "praesentiert",
    "quelle",
    "sagt",
    "stellt",
    "text",
    "zeigt",
}


def _is_mechanical_source_restatement(
    claim_text: str,
    source_text: str,
) -> bool:
    """Detect an interpretation slot filled by a source restatement only."""

    def content_tokens(value: str) -> List[str]:
        return [
            token.casefold()
            for token in re.findall(r"[^\W\d_]+", value, re.UNICODE)
            if len(token) >= 4
            and token.casefold() not in _PASSAGE_REPORTING_TOKENS
        ]

    claim_tokens = content_tokens(str(claim_text or ""))
    source_tokens = content_tokens(str(source_text or ""))
    if len(claim_tokens) < 4 or len(source_tokens) < 4:
        return False

    matched = 0
    for claim_token in claim_tokens:
        if any(
            claim_token == source_token
            or (
                min(len(claim_token), len(source_token)) >= 5
                and claim_token[:5] == source_token[:5]
            )
            for source_token in source_tokens
        ):
            matched += 1
    novel = len(claim_tokens) - matched
    overlap = matched / len(claim_tokens)
    source_matched = sum(
        any(
            source_token == claim_token
            or (
                min(len(source_token), len(claim_token)) >= 5
                and source_token[:5] == claim_token[:5]
            )
            for claim_token in claim_tokens
        )
        for source_token in source_tokens
    )
    source_coverage = source_matched / len(source_tokens)
    reporting_frame = re.search(
        r"\b(?:ausschnitt|beleg|passage|quelle|text)\b[^.!?\n]{0,32}"
        r"\b(?:berichtet|beschreibt|betont|behauptet|erwähnt|nennt|sagt|"
        r"stellt|zeigt|bezeichnet|präsentiert|praesentiert)\b",
        str(claim_text or ""),
        re.IGNORECASE,
    )
    return bool(
        (overlap >= 0.72 and novel <= 2)
        or (
            reporting_frame is not None
            and (
                (overlap >= 0.65 and novel <= 4)
                or (source_coverage >= 0.72 and novel <= 5)
            )
        )
    )


_DISTRIBUTIVE_ADVERB_SOURCE_PATTERN = re.compile(
    r"\b(?:alle|die|diese|jene)\s+"
    r"(?P<head>[A-Za-zÄÖÜäöüß]{3,})\b"
    r"[^.!?\n]{0,100}\b(?:einzeln|jeweils)\b|"
    r"\b(?:all|the|these|those)\s+"
    r"(?P<head_en>[A-Za-z]{3,})\b"
    r"[^.!?\n]{0,100}\bindividually\b",
    re.IGNORECASE,
)


def _distributive_adverb_became_subset(
    source_text: str,
    claim_text: str,
) -> bool:
    """Detect a manner/distribution adverb rewritten as a subset quantifier."""

    claim = " ".join(str(claim_text or "").split())
    source = " ".join(str(source_text or "").split())
    for match in _DISTRIBUTIVE_ADVERB_SOURCE_PATTERN.finditer(source):
        head = match.group("head") or match.group("head_en") or ""
        if not head:
            continue
        head_pattern = (
            re.escape(head[:5]) + r"[^\W\d_]*"
            if len(head) >= 5
            else re.escape(head)
        )
        if match.group("head") and re.search(
            rf"\beinzel(?:ne|nen|ner|nes|nem)\s+"
            rf"(?:[^\W\d_]+\s+){{0,3}}{head_pattern}\b",
            claim,
            re.IGNORECASE,
        ):
            return True
        if match.group("head_en") and re.search(
            rf"\b(?:some|individual)\s+{re.escape(head)}\b",
            claim,
            re.IGNORECASE,
        ):
            return True
    return False


_RECIPROCAL_RELATION_PATTERN = re.compile(
    r"\b(?:einander|gegenseitig\w*|untereinander|wechselseitig\w*|"
    r"mutual\w*|reciprocal\w*)\b",
    re.IGNORECASE,
)


def _introduces_unsupported_reciprocity(
    source_text: str,
    claim_text: str,
) -> bool:
    """Keep parallel duties to two participants distinct from reciprocity."""

    return bool(
        _RECIPROCAL_RELATION_PATTERN.search(str(claim_text or ""))
        and _RECIPROCAL_RELATION_PATTERN.search(str(source_text or ""))
        is None
    )


_PURPOSIVE_CLAUSE_PATTERN = re.compile(
    r"\bum\b[^.!?\n]{1,140}\b(?:zu\s+[A-Za-zÄÖÜäöüß]+|"
    r"[A-Za-zÄÖÜäöüß]+zu[A-Za-zÄÖÜäöüß]+)\b|"
    r"\bin\s+order\s+to\b",
    re.IGNORECASE,
)


def _introduces_unsupported_purpose(
    source_text: str,
    claim_text: str,
) -> bool:
    """Reject an inferred participant intention encoded as a purpose clause."""

    return bool(
        _PURPOSIVE_CLAUSE_PATTERN.search(str(claim_text or ""))
        and _PURPOSIVE_CLAUSE_PATTERN.search(str(source_text or "")) is None
    )


_INDEM_RELATION_PATTERN = re.compile(
    r"(?P<frame>[^.!?\n]{2,240}?)\b(?:indem|dadurch\s*,?\s*dass)\s+"
    r"(?P<means>[^.!?\n]{2,240})",
    re.IGNORECASE,
)
_SOURCE_MEANS_RELATION_PATTERN = re.compile(
    r"(?P<frame>[^.!?\n]{2,240}?)\b(?:mittels|mithilfe\s+von|mit)\s+"
    r"(?P<means>[^.!?\n]{2,240})",
    re.IGNORECASE,
)


def _introduces_unsupported_indem_relation(
    source_text: str,
    claim_text: str,
) -> bool:
    """Require visible means evidence before turning a relation into ``indem``."""

    claim_relation = _INDEM_RELATION_PATTERN.search(str(claim_text or ""))
    if claim_relation is None:
        return False
    source = str(source_text or "")
    if _INDEM_RELATION_PATTERN.search(source):
        return False
    for source_relation in _SOURCE_MEANS_RELATION_PATTERN.finditer(source):
        if (
            _related_relation_token_count(
                source_relation.group("frame"),
                claim_relation.group("frame"),
            )
            >= 2
            and _related_relation_token_count(
                source_relation.group("means"),
                claim_relation.group("means"),
            )
            >= 1
        ):
            return False
    return True


_ABSTRACT_LABEL_TARGET_PATTERN = (
    r"(?:forderung\w*|politik\w*|maßnahm\w*|massnahm\w*|programm\w*|"
    r"anspruch\w*|aussage\w*|idee\w*|demand\w*|polic\w*|measure\w*|"
    r"program\w*|claim\w*|idea\w*)"
)


def _misbinds_evaluative_source_phrase(
    source_text: str,
    claim_text: str,
    phrases: List[str],
) -> str:
    """Find a source label reassigned from its referent to an abstract object."""

    source = " ".join(str(source_text or "").split())
    claim = " ".join(str(claim_text or "").split())
    for phrase in _dedupe_ordered_strs(phrases):
        if not (
            _candidate_quote_is_anchored(phrase, source)
            and _candidate_quote_is_anchored(phrase, claim)
        ):
            continue
        phrase_pattern = re.escape(phrase).replace(r"\ ", r"\s+")
        binding_pattern = re.compile(
            rf"\b{_ABSTRACT_LABEL_TARGET_PATTERN}\b[^.!?\n]{{0,110}}"
            rf"\b(?:sie|diese\w*|das|ihn|it|this|that)\b\s+als\s+"
            rf"[\"'„“‚‘«»‹›]*{phrase_pattern}\b",
            re.IGNORECASE,
        )
        if binding_pattern.search(claim) and binding_pattern.search(source) is None:
            return phrase
    return ""


def _atomic_retrieval_synthesis_instruction(
    fact_payload: dict[str, Any],
    assessment: dict[str, Any],
) -> str:
    """Give a one-passage synthesis only the fidelity rules it actually needs."""

    source = _candidate_source_quote(fact_payload) or str(
        fact_payload.get("statement", "") or ""
    )
    guidance = [
        "Schreibe genau einen kurzen, gehaltvollen analytischen Satz in der "
        "Sprache der Nutzerfrage zu dieser Passage. Benenne darin eine "
        "konkrete Rahmung, Positionierung, Relation oder Rollenverteilung, "
        "die aus dem Wortlaut folgt. Bewahre dabei die "
        "sichtbaren Akteure, Objekte, Prädikate und Anbindungen. Prüfe die "
        "Syntax intern, ohne Grammatiklabels auszugeben. Wiederhole "
        "den Quelltext nicht und setze ihn nicht in Anführungszeichen, da er "
        "separat als Evidenz erscheint. Nutze genau die eine sichtbare Fact-ID. "
        "Wähle die stärkste eindeutig gebundene Relation; du musst nicht jede "
        "Proposition der Passage in denselben Claim pressen. Formuliere genau "
        "eine analytische Hauptrelation und lasse weitere syntaktisch offene "
        "oder für diese Deutung nicht notwendige Propositionen weg. "
        "Bleibe lokal bei dieser Passage und ergänze keine externen Tatsachen, "
        "Zahlen, Häufigkeit oder Korpusgeltung. Ein Institutions- oder "
        "Eigenname belegt für sich keine ungenannte Ortsangabe."
    ]
    relation = str(
        assessment.get("relation_to_requested_conclusion", "") or ""
    )
    if relation == "related_support":
        guidance.append(
            "Deute das sichtbare verwandte Objekt lokal; übertrage seine "
            "Bewertung nicht auf das abstrakte Zielthema insgesamt."
        )
    elif relation in {"counterevidence", "mixed_or_unclear"}:
        guidance.append(
            "Erschließe die sichtbare alternative Rahmung oder Rollenverteilung, "
            "ohne ihr automatisch positive Polarität zuzuschreiben. Wenn die "
            "Richtung als mixed_or_unclear geprüft wurde, benenne die konkrete "
            "offene Stimme, Anbindung oder Wertungsrichtung; erzähle nicht nur "
            "die sichtbaren Handlungen nach."
        )
        if _candidate_has_reported_or_metalinguistic_evaluation(fact_payload):
            guidance.append(
                "Deute bei berichteter oder metasprachlich markierter Wertung "
                "die Quellenkennzeichnung und das sichtbare Nebeneinander der "
                "Äußerungen. Schreibe der genannten Person nicht selbst eine "
                "Ideologie zu und erfinde weder Wandel, Gegensatz, Kooperation "
                "noch eine gemeinsame Haltung, wenn der Wortlaut diese Relation "
                "offenlässt."
            )
    if str(assessment.get("evaluated_object_type", "") or "") not in {
        "",
        "target_topic",
    }:
        guidance.append(
            "Benenne das tatsächlich bewertete verwandte Objekt und sage "
            "ausdrücklich, dass die Passage damit keine unmittelbare Wertung "
            "des abstrakten Zielthemas liefert. Das begrenzt nur den Schluss, "
            "nicht die lokale Interpretation."
        )
    if _EXPLICIT_SOURCE_CAUSAL_MARKER.search(source):
        guidance.append(
            "Deute genau die mit dem Quellenmarker ausgedrückte lokale "
            "Ursache-Wirkung-Relation. Markiere sie als Lesart der Passage, "
            "statt die behauptete Kausalität als externe Tatsache zu "
            "übernehmen. Verwende dafür die Akteure und Vorgänge des Wortlauts."
        )
        if len(_candidate_source_sentences(fact_payload)) > 1:
            guidance.append(
                "Deute nur diese lokal markierte Relation. Verknüpfe einen "
                "folgenden eigenständigen Satz nicht zusätzlich mit dadurch, "
                "deshalb oder einer anderen erfundenen Kausalbrücke."
            )
    if _DISTRIBUTIVE_ADVERB_SOURCE_PATTERN.search(source):
        guidance.append(
            "Bewahre das distributive Adverb des Quelltexts auch in der "
            "Deutung als Adverb. Ersetze es nicht durch einen attributiven "
            "oder substantivischen Teilmengenquantor."
        )
    if re.search(
        r"\bsowohl\b[^.!?\n]{0,120}\bals\s+auch\b|\bboth\b[^.!?\n]{0,120}\band\b",
        source,
        re.IGNORECASE,
    ):
        guidance.append(
            "Bewahre die sichtbare Parallelkonstruktion und deute den "
            "gemeinsamen Geltungsbereich der Anforderung für beide genannten "
            "Gruppen. Das heißt nur, dass die Anforderung beide Gruppen "
            "erfasst; behaupte weder gleich gewichtete Beiträge noch "
            "Gleichzeitigkeit. Eine geteilte Verantwortungsrahmung ist als "
            "tentative Abstraktion zulässig, solange sie keine Gleichheit "
            "ergänzt."
        )
    if re.search(
        r"\berst\b[^.!?\n]{0,220}\b(?:jetzt|dann|anschließend|anschliessend)\b|"
        r"\bfirst\b[^.!?\n]{0,220}\b(?:now|then|afterwards)\b",
        source,
        re.IGNORECASE,
    ):
        guidance.append(
            "Deute die sichtbar geordnete Präsentation der beiden Handlungen. "
            "Ordne jede Handlung ihrem eigenen Akteur und Prädikat zu."
        )
    if len(_candidate_source_sentences(fact_payload)) > 1:
        guidance.append(
            "Behandle die ausgewiesenen sentence_units als eigenständige "
            "Sätze. Übertrage Subjekt, Objekt, Negation oder Prädikat nur bei "
            "einem sichtbaren Konnektor oder einer eindeutigen Koreferenz von "
            "einem Satz auf den nächsten; Satznachbarschaft allein genügt nicht."
        )
    phrases = _dedupe_ordered_strs(
        [
            str(value)
            for value in list(
                assessment.get("verbatim_evaluative_source_phrases", []) or []
            )
            if str(value).strip()
        ]
    )
    if phrases:
        guidance.append(
            "Bindende wertende Quellenausdrücke sind: "
            + "; ".join(repr(phrase) for phrase in phrases)
            + ". Deute ihre sichtbare Wertung als Wortwahl der Passage und "
            "binde sie an den dort erkennbaren Referenten."
        )
    if (
        len(re.findall(r"\w+", source, re.UNICODE)) >= 18
        and not _has_sentence_terminal_punctuation(source)
    ):
        guidance.append(
            "Der unpunktierte Wortlaut lässt einzelne Zuschreibungen offen. "
            "Deute seine sichtbare Wortwahl und das Nebeneinander der "
            "Propositionen, ohne eine offene Urheberschaft festzulegen. Das "
            "bloße Nebeneinander ist keine Ursache: Verwende ohne sichtbaren "
            "Kausalmarker insbesondere nicht weil, aufgrund, dadurch, indem "
            "oder damit."
        )
    return " ".join(guidance)


_ADVOCACY_PREDICATE_PATTERN = re.compile(
    r"\b(?:(?:ge)?forder(?:t|n|te|ten|e|st|nd)|"
    r"verlang(?:t|en|te|ten|e)|"
    r"befürwort(?:et|en|ete|eten|e)|befuerwort(?:et|en|ete|eten|e)|"
    r"plädier(?:t|en|te|ten|e)|plaedier(?:t|en|te|ten|e)|"
    r"advocates?|advocated|demands?|demanded|calls?\s+for)\b",
    re.IGNORECASE,
)
_TEXT_CONTAINER_PATTERN = (
    r"(?:aussage|beleg|passage|satz|text|wortlaut|excerpt|statement)"
)
_TEXT_CONTAINER_ADVOCACY_PATTERN = re.compile(
    rf"\b{_TEXT_CONTAINER_PATTERN}\b\s+"
    rf"(?:selbst\s+|zugleich\s+|gleichzeitig\s+)?"
    rf"{_ADVOCACY_PREDICATE_PATTERN.pattern}|"
    rf"\b{_TEXT_CONTAINER_PATTERN}\b[^.!?\n]{{0,260}}\bund\s+"
    rf"(?:zugleich\s+|gleichzeitig\s+)?"
    rf"{_ADVOCACY_PREDICATE_PATTERN.pattern}",
    re.IGNORECASE,
)
_DEONTIC_SOURCE_PATTERN = re.compile(
    r"\b(?:soll(?:te|ten|test|tet)?|muss|müssen|muessen|"
    r"should|ought\s+to|must)\b",
    re.IGNORECASE,
)
_NORMATIVE_REFRAMING_PATTERN = re.compile(
    rf"{_DEONTIC_SOURCE_PATTERN.pattern}|"
    rf"{_ADVOCACY_PREDICATE_PATTERN.pattern}|"
    r"\b(?:ruf\w*|rief\w*)\b[^.!?\n]{0,100}\bauf\b|"
    r"\b(?:forderung|appell|pflicht|verantwortung|zuständigkeit|"
    r"zustaendigkeit|demand|appeal|duty|responsibility)\w*\b",
    re.IGNORECASE,
)
_DEONTIC_METAREADING_PATTERN = re.compile(
    rf"\b{_TEXT_CONTAINER_PATTERN}\b[^.!?\n]{{0,180}}"
    r"(?:ruft\b[^.!?\n]{0,80}\bauf|appellier\w*|"
    r"formulier\w*[^.!?\n]{0,60}\b(?:forderung|pflicht|appell)|"
    r"(?:forderung|pflicht|appell)\w*|"
    rf"{_ADVOCACY_PREDICATE_PATTERN.pattern})",
    re.IGNORECASE,
)
_LITERAL_DEONTIC_METAREADING_REJECTION_PATTERN = re.compile(
    r"(?:\b(?:verb|prädikat|praedikat|wording|wortlaut)\b[^.!?\n]{0,100}"
    r"\b(?:absent|missing|fehlt|nicht\s+(?:vorhanden|enthalten))\b)|"
    r"(?:\b(?:ruft|fordert|appelliert|calls?|demands?)\b[^.!?\n]{0,100}"
    r"\b(?:absent|missing|fehlt|nicht\s+(?:vorhanden|enthalten))\b)",
    re.IGNORECASE,
)


def _is_source_faithful_deontic_metareading(
    source_text: str,
    claim_text: str,
) -> bool:
    """Allow a local ``muss/soll`` proposition to be named as a demand."""

    source = " ".join(str(source_text or "").split())
    claim = " ".join(str(claim_text or "").split())
    quantifier_family = {
        "alle": "all",
        "all": "all",
        "jede": "every",
        "every": "every",
        "immer": "always",
        "always": "always",
        "nie": "never",
        "never": "never",
        "aussch": "only",
        "only": "only",
        "exclus": "only",
    }

    def quantifiers(value: str) -> set[str]:
        result: set[str] = set()
        for match in _HYPOTHESIS_QUANTIFIER_PATTERN.finditer(value):
            token = match.group(0).casefold()
            family = next(
                (
                    canonical
                    for prefix, canonical in quantifier_family.items()
                    if token.startswith(prefix)
                ),
                token,
            )
            result.add(family)
        return result

    claim_quantifiers = quantifiers(claim)
    return bool(
        _DEONTIC_SOURCE_PATTERN.search(source)
        and _DEONTIC_METAREADING_PATTERN.search(claim)
        and _related_relation_token_count(source, claim) >= 2
        and claim_quantifiers.issubset(quantifiers(source))
        and _EXPLICIT_AUTHOR_ATTRIBUTION_PATTERN.search(claim) is None
    )


def _drops_source_deontic_modality(
    source_text: str,
    claim_text: str,
) -> bool:
    """Keep a visible demand distinct from an already realised action."""

    source = " ".join(str(source_text or "").split())
    claim = " ".join(str(claim_text or "").split())
    if bool(
        _DEONTIC_SOURCE_PATTERN.search(source)
        and _NORMATIVE_REFRAMING_PATTERN.search(claim) is None
        and _related_relation_token_count(source, claim) >= 2
    ):
        return True
    realised_outcome = re.search(
        r"\b(?:anschließend\w*|anschliessend\w*|danach|subsequent\w*)\b"
        r"[^.!?\n]{0,80}\b(?:zusammenarbeit\w*|kooperation\w*|"
        r"koalition\w*|bündnis\w*|buendnis\w*)\b|"
        r"\b(?:kooperier\w*|koalier\w*|zusammenarbeit\w*|"
        r"arbeitet\w*[^.!?\n]{0,30}\bzusammen)\b",
        claim,
        re.IGNORECASE,
    )
    source_identifiers = {
        token.casefold()
        for token in re.findall(r"\b[A-Za-zÄÖÜäöüß]{3,}\b", source)
        if sum(character.isupper() for character in token) >= 2
    }
    claim_identifiers = {
        token.casefold()
        for token in re.findall(r"\b[A-Za-zÄÖÜäöüß]{3,}\b", claim)
        if sum(character.isupper() for character in token) >= 2
    }
    related_outcome = bool(
        _related_relation_token_count(source, claim) >= 1
        or source_identifiers & claim_identifiers
    )
    return bool(
        _ADVOCACY_PREDICATE_PATTERN.search(source)
        and _NORMATIVE_REFRAMING_PATTERN.search(claim) is None
        and realised_outcome
        and related_outcome
    )


def _introduces_unsupported_advocacy(
    source_text: str,
    claim_text: str,
) -> bool:
    """Reject a new demand or a source action reassigned to the text itself."""

    source = " ".join(str(source_text or "").split())
    claim = " ".join(str(claim_text or "").split())
    if _ADVOCACY_PREDICATE_PATTERN.search(claim) is None:
        return False
    if _is_source_faithful_deontic_metareading(source, claim):
        return False
    if _ADVOCACY_PREDICATE_PATTERN.search(source) is None:
        return True
    return bool(
        _TEXT_CONTAINER_ADVOCACY_PATTERN.search(claim)
        and _TEXT_CONTAINER_ADVOCACY_PATTERN.search(source) is None
    )


_PARALLEL_PARTICIPANT_PATTERN = re.compile(
    r"\bsowohl\b[^.!?\n]{0,160}\bals\s+auch\b|"
    r"\bboth\b[^.!?\n]{0,160}\band\b",
    re.IGNORECASE,
)
_SYMMETRIC_PARTICIPATION_PATTERN = re.compile(
    r"\b(?:gleichermaßen\w*|gleichermassen\w*|gleichwertig\w*|"
    r"gleichverteilt\w*|symmetrisch\w*|gleichzeitig\w*|zeitgleich\w*|"
    r"simultan\w*|equally\w*|equal\w*|symmetrically\w*|balanced\w*|"
    r"simultaneous\w*)\b",
    re.IGNORECASE,
)


def _introduces_unsupported_parallel_symmetry(
    source_text: str,
    claim_text: str,
) -> bool:
    """Keep parallel scope distinct from equal weighting or simultaneity."""

    source = str(source_text or "")
    claim = str(claim_text or "")
    return bool(
        _PARALLEL_PARTICIPANT_PATTERN.search(source)
        and _SYMMETRIC_PARTICIPATION_PATTERN.search(claim)
        and _SYMMETRIC_PARTICIPATION_PATTERN.search(source) is None
    )


_ATTRIBUTION_STRENGTHENING_PATTERN = re.compile(
    r"\b(?:propagier\w*|unterstütz\w*|unterstuetz\w*|"
    r"vertret(?:e|en|et|ener|ene|enes)\w*|"
    r"stamm\w*\s+von|(?:geht|ging|gehe)\s+von)\b",
    re.IGNORECASE,
)
_EXPLICIT_AUTHOR_ATTRIBUTION_PATTERN = re.compile(
    r"\b(?:(?:des|der|vom|von\s+dem|von\s+der|durch\s+den|durch\s+die)\s+"
    r"(?:autor(?:s|in|en|innen)?|verfasser(?:s|in|n|innen)?|"
    r"sprecher(?:s|in|n|innen)?)|"
    r"(?:autor|verfasser|sprecher)\w*"
    r"(?:haltung|intention|perspektive|wertung|wortwahl)|"
    r"author(?:'s|’s|ial)?|by\s+the\s+author|speaker(?:'s|’s))\b",
    re.IGNORECASE,
)
_REPORTING_PREDICATE_PATTERN = re.compile(
    r"\b(?:sag|behaupt|bericht|meld|verkünd|verkuend|posaun|"
    r"schreib|twitter|post|erklär|erklaer)\w*\b",
    re.IGNORECASE,
)
_POSSESSIVE_PARTICIPATION_PATTERN = re.compile(
    r"\b(?:ihre|seine|deren|dessen|their|his|her)\w*\s+"
    r"(?:rolle|beteiligung|mitwirkung|verantwortung|"
    r"role|involvement|responsibility)\b",
    re.IGNORECASE,
)
_AMBIGUOUS_NOMINAL_ACTOR_TAIL_PATTERN = re.compile(
    r"\b(?:forderung|appell|demand|call)\s+(?:von|by)\s+"
    r"(?P<actors>[^.!?\n]{3,140})$",
    re.IGNORECASE,
)
_POSTVERBAL_DEMAND_ACTOR_PATTERN = re.compile(
    r"\b(?:jetzt|dann|anschließend|anschliessend|now|then)\s+"
    r"(?:fordert|fordert\s+nun|demands?)\s+"
    r"(?P<actor>(?:[A-ZÄÖÜ]\.?\s*)?[A-ZÄÖÜ][A-Za-zÄÖÜäöüß-]{2,})\b",
    re.IGNORECASE,
)


def _ambiguous_nominal_actor_chain_became_active(
    source_text: str,
    claim_text: str,
) -> bool:
    """Keep an unpunctuated name tail from becoming resolved authorship."""

    source = " ".join(str(source_text or "").split())
    claim = " ".join(str(claim_text or "").split())
    if (
        len(re.findall(r"\w+", source, re.UNICODE)) < 18
        or _has_sentence_terminal_punctuation(source)
    ):
        return False
    tail = _AMBIGUOUS_NOMINAL_ACTOR_TAIL_PATTERN.search(source)
    if tail is None:
        return False
    actor_surface = tail.group("actors")
    if re.search(r"[,;/&]|\b(?:und|and)\b", actor_surface, re.IGNORECASE):
        return False
    actor_tokens = {
        token.casefold()
        for token in re.findall(
            r"\b[A-ZÄÖÜ][A-Za-zÄÖÜäöüß-]{1,}\b",
            actor_surface,
        )
    }
    if len(actor_tokens) < 4:
        return False
    claimed_actor_tokens = {
        token.casefold()
        for token in re.findall(
            r"\b[A-ZÄÖÜ][A-Za-zÄÖÜäöüß-]{1,}\b",
            claim,
        )
    }
    overlapping_actors = actor_tokens & claimed_actor_tokens
    if len(overlapping_actors) < 2:
        return False
    if re.search(
        r"\b(?:unklar|offen|nicht\s+eindeutig|nicht\s+auflösbar|"
        r"ungeklärt|unresolved|unclear|ambiguous)\b",
        claim,
        re.IGNORECASE,
    ):
        return False

    advocacy = _ADVOCACY_PREDICATE_PATTERN.search(claim)
    if advocacy is not None:
        subject_window = claim[max(0, advocacy.start() - 120) : advocacy.start()]
        subject_tokens = {
            token.casefold()
            for token in re.findall(
                r"\b[A-ZÄÖÜ][A-Za-zÄÖÜäöüß-]{1,}\b",
                subject_window,
            )
        }
        if len(actor_tokens & subject_tokens) >= 2:
            return True

    actor_mentions = [
        match
        for actor in overlapping_actors
        if (
            match := re.search(
                rf"\b{re.escape(actor)}\b",
                claim,
                re.IGNORECASE,
            )
        )
    ]
    if len(actor_mentions) < 2:
        return False
    actor_window = claim[
        min(match.start() for match in actor_mentions) :
        max(match.end() for match in actor_mentions)
    ]
    resolves_as_list = bool(
        re.search(r"[,;/&]|\b(?:und|and)\b", actor_window, re.IGNORECASE)
    )
    assigns_attribution = bool(
        re.search(
            r"\b(?:laut|von|durch|ausgeführt\w*|ausgefuehrt\w*|"
            r"getragen\w*|vertreten\w*|propagier\w*|zugeschrieb\w*|"
            r"zugeordnet\w*|stamm\w*)\b|\b(?:geht|ging)\b[^.!?\n]{0,40}"
            r"\b(?:aus|zurück|zurueck)\b",
            claim,
            re.IGNORECASE,
        )
    )
    return resolves_as_list and assigns_attribution


def _postverbal_demand_actor_became_addressee(
    source_text: str,
    claim_text: str,
) -> bool:
    """Preserve the subject of a verb-second demand construction."""

    source = " ".join(str(source_text or "").split())
    claim = " ".join(str(claim_text or "").split())
    source_actor = _POSTVERBAL_DEMAND_ACTOR_PATTERN.search(source)
    if source_actor is None:
        return False
    actor = re.escape(source_actor.group("actor")).replace(r"\ ", r"\s+")
    return bool(
        re.search(
            rf"\b{actor}\s+aufforder\w*\b|"
            rf"\bfordert\s+(?:(?:anschließend|anschliessend|danach|nun|"
            rf"jetzt|then)\s+)?{actor}\s+auf\b",
            claim,
            re.IGNORECASE,
        )
    )


def _introduces_unresolved_attribution(
    source_text: str,
    claim_text: str,
) -> bool:
    """Reject authorship that is not identified in the visible source."""

    source = " ".join(str(source_text or "").split())
    claim = " ".join(str(claim_text or "").split())
    if (
        _EXPLICIT_AUTHOR_ATTRIBUTION_PATTERN.search(claim)
        and _EXPLICIT_AUTHOR_ATTRIBUTION_PATTERN.search(source) is None
    ):
        return True
    if (
        _REPORTING_PREDICATE_PATTERN.search(source)
        and _POSSESSIVE_PARTICIPATION_PATTERN.search(claim)
        and _POSSESSIVE_PARTICIPATION_PATTERN.search(source) is None
    ):
        return True
    if _ambiguous_nominal_actor_chain_became_active(source, claim):
        return True
    if _postverbal_demand_actor_became_addressee(source, claim):
        return True
    reported_number = re.search(
        rf"{_REPORTING_PREDICATE_PATTERN.pattern}"
        rf"[^.!?\n]{{0,80}}\b(?:dass?|that)\s+"
        rf"(?P<subject>[A-Za-zÄÖÜäöüß]{{2,}})"
        rf"[^.!?\n]{{0,60}}?(?P<number>\d(?:[\d .\u202f]*\d)?)",
        source,
        re.IGNORECASE,
    )
    reassigned_number = re.search(
        r"\b(?P<subject>sie|er|they|he|she)\b"
        r"[^.!?\n]{0,100}?(?P<number>\d(?:[\d .\u202f]*\d)?)"
        r"[^.!?\n]{0,100}?\b(?:aufnehm\w*|zulass\w*|förder\w*|"
        r"foerder\w*|ermöglich\w*|ermoeglich\w*|organisier\w*|"
        r"betreib\w*|verantwort\w*|beteilig\w*)\b",
        claim,
        re.IGNORECASE,
    )
    if reported_number is not None and reassigned_number is not None:
        source_digits = "".join(
            character
            for character in reported_number.group("number")
            if character.isdigit()
        )
        claim_digits = "".join(
            character
            for character in reassigned_number.group("number")
            if character.isdigit()
        )
        if (
            source_digits
            and source_digits == claim_digits
            and reported_number.group("subject").casefold()
            != reassigned_number.group("subject").casefold()
        ):
            return True
    return bool(
        len(re.findall(r"\w+", source, re.UNICODE)) >= 18
        and not _has_sentence_terminal_punctuation(source)
        and _ATTRIBUTION_STRENGTHENING_PATTERN.search(claim)
        and _ATTRIBUTION_STRENGTHENING_PATTERN.search(source) is None
    )


def _dropped_related_object_head(
    source_text: str,
    claim_text: str,
    target_topic: str,
) -> str:
    """Find a source relation such as ``Integration von Migranten`` collapsed to its dependent."""

    target_stems = {
        token.casefold()[:5]
        for token in re.findall(
            r"[^\W\d_]+",
            str(target_topic or ""),
            re.UNICODE,
        )
        if len(token) >= 5
    }
    if not target_stems:
        return ""
    source = " ".join(str(source_text or "").split())
    claim_clauses = re.split(
        r"[;\n]+|(?=\beine\s+(?:andere|weitere)\s+Passage\b)|"
        r"(?=\banother\s+(?:passage|excerpt)\b)",
        " ".join(str(claim_text or "").split()),
        flags=re.IGNORECASE,
    )
    relation_pattern = re.compile(
        r"\b(?P<head>[^\W\d_]{4,})\s+(?:von|of)\s+"
        r"(?:(?:der|den|dem|die|des|the)\s+)?"
        r"(?P<dependent>[^\W\d_]{4,})\b",
        re.IGNORECASE,
    )
    for relation in relation_pattern.finditer(source):
        dependent_stem = relation.group("dependent").casefold()[:5]
        if dependent_stem not in target_stems:
            continue
        head = relation.group("head")
        head_stem = head.casefold()[:5]
        for clause in claim_clauses:
            clause_tokens = {
                token.casefold()[:5]
                for token in re.findall(
                    r"[^\W\d_]+",
                    clause,
                    re.UNICODE,
                )
                if len(token) >= 5
            }
            if (
                dependent_stem in clause_tokens
                and head_stem not in clause_tokens
                and _related_relation_token_count(source, clause) >= 3
            ):
                return head
    return ""


_LEADING_HANDLE_PATTERN = re.compile(
    r"^\s*(?P<handles>(?:@[A-Za-z0-9_]{1,64}[\s,:;\-]*)+)",
)
_HANDLE_MENTION_READING_PATTERN = re.compile(
    r"\b(?:adressat\w*|adressier\w*|anred\w*|angesproch\w*|"
    r"erwähn\w*|erwaehn\w*|"
    r"markier\w*|mention\w*|address(?:ee|ed|ing)?)\b",
    re.IGNORECASE,
)


def _assigns_leading_handle_as_source_actor(
    source_text: str,
    claim_text: str,
) -> bool:
    """Do not mistake a tweet's leading addressee for its unknown author."""

    match = _LEADING_HANDLE_PATTERN.search(str(source_text or ""))
    if match is None:
        return False
    claim = " ".join(str(claim_text or "").split())
    for raw_handle in re.findall(r"@[A-Za-z0-9_]{1,64}", match.group("handles")):
        handle = raw_handle[1:]
        claim_match = re.search(
            rf"(?<![A-Za-z0-9_])@?{re.escape(handle)}(?![A-Za-z0-9_])",
            claim,
            re.IGNORECASE,
        )
        if claim_match is None:
            continue
        nearby = claim[
            max(0, claim_match.start() - 80) : min(
                len(claim), claim_match.end() + 80
            )
        ]
        if _HANDLE_MENTION_READING_PATTERN.search(nearby) is None:
            return True
    return False


_ORDERED_SEQUENCE_PATTERN = re.compile(
    r"\berst\b[^.!?\n]{0,220}\b(?:jetzt|dann|anschließend|anschliessend)\b|"
    r"\bfirst\b[^.!?\n]{0,220}\b(?:now|then|afterwards)\b",
    re.IGNORECASE,
)
_EXPLICIT_ADVERSATIVE_PATTERN = re.compile(
    r"\b(?:aber|jedoch|hingegen|dagegen|während|waehrend)\b|"
    r"\bim\s+Gegensatz\b|"
    r"\b(?:but|however|whereas|while)\b|\bin\s+contrast\b",
    re.IGNORECASE,
)
_UNAMBIGUOUS_ADVERSATIVE_PATTERN = re.compile(
    r"\b(?:hingegen|dagegen|während|waehrend)\b|"
    r"\bim\s+Gegensatz\b|\b(?:whereas|while)\b|\bin\s+contrast\b",
    re.IGNORECASE,
)

_CROSS_CLAIM_DISCOURSE_REFERENCE_PATTERN = re.compile(
    r"\b(?:im\s+Gegensatz\s+dazu|demgegenüber|demgegenueber|"
    r"im\s+Kontrast\s+zu\s+(?:den|dem|der)\s+(?:zuvor|vorher)|"
    r"(?:zuvor|vorher|oben)\s+(?:dargestellt|beschrieben|genannt|"
    r"diskutiert|angeführt|angefuehrt)\w*)\b|"
    r"\b(?:die|der|das|den|dem)\s+(?:zuvor|vorher)\s+"
    r"(?:dargestellt|beschrieben|genannt|diskutiert|angeführt|"
    r"angefuehrt)\w*",
    re.IGNORECASE,
)


def _introduces_unbound_cross_claim_reference(
    source_text: str,
    claim_text: str,
    *,
    cited_fact_count: int,
) -> bool:
    """Reject a sibling-dependent contrast that cites only one local fact."""

    if cited_fact_count != 1:
        return False
    claim = str(claim_text or "")
    if _CROSS_CLAIM_DISCOURSE_REFERENCE_PATTERN.search(claim) is None:
        return False
    source = str(source_text or "")
    return not (
        _CROSS_CLAIM_DISCOURSE_REFERENCE_PATTERN.search(source)
        or _EXPLICIT_ADVERSATIVE_PATTERN.search(source)
    )


def _introduces_unsupported_adversative_relation(
    source_text: str,
    claim_text: str,
) -> bool:
    """Do not turn an explicitly ordered sequence into an opposition."""

    source = str(source_text or "")
    claim = str(claim_text or "")
    return bool(
        _ORDERED_SEQUENCE_PATTERN.search(source)
        and _EXPLICIT_ADVERSATIVE_PATTERN.search(source) is None
        and _UNAMBIGUOUS_ADVERSATIVE_PATTERN.search(claim)
    )


def _causal_relation_sides(value: str) -> tuple[str, str] | None:
    for pattern in _CLAIM_CAUSAL_SIDE_PATTERNS:
        match = pattern.search(str(value or ""))
        if match is not None:
            return match.group("cause"), match.group("effect")
    return None


def _explicit_source_causality_matches_claim(
    claim_text: str,
    fact_payloads: List[dict[str, Any]],
) -> bool:
    """Recognise the reversible local relation ``Y wegen X`` ↔ ``X Grund für Y``."""

    if _CAUSAL_EXCLUSIVITY_PATTERN.search(claim_text or ""):
        return False
    claim_sides = _causal_relation_sides(claim_text)
    if claim_sides is None:
        return False
    claim_cause, claim_effect = claim_sides
    for fact in fact_payloads:
        for sentence in _candidate_source_sentences(fact):
            source_sides = _causal_relation_sides(sentence)
            if source_sides is None:
                continue
            source_cause, source_effect = source_sides
            effect_matches = _related_relation_token_count(
                source_effect,
                claim_effect,
            )
            cause_matches = _related_relation_token_count(
                source_cause,
                claim_cause,
            )
            if (
                effect_matches >= 1
                and cause_matches >= 1
                and effect_matches + cause_matches >= 3
            ):
                return True
    return False


def _classification_reason_is_substantive(value: Any) -> bool:
    """Reject moderation refusals masquerading as analytical classifications."""

    reason = " ".join(str(value or "").split())
    return len(reason) >= 8 and not _CLASSIFICATION_REFUSAL_PATTERN.search(
        reason
    )


def _reason_is_acceptance_only_feedback(value: Any) -> bool:
    """Keep verifier praise out of a later repair instruction."""

    reason = " ".join(str(value or "").split())
    return bool(
        _ACCEPTANCE_ONLY_FEEDBACK_PATTERN.search(reason)
        and not _NEGATIVE_FEEDBACK_PATTERN.search(reason)
    )


def _reason_uses_unrequested_moderation_taxonomy(
    value: Any,
    *,
    analytical_scope: str,
) -> bool:
    """Detect safety-taxonomy answers to an analytical classification task."""

    reason = " ".join(str(value or "").split())
    matches = list(_MODERATION_TAXONOMY_PATTERN.finditer(reason))
    if not matches:
        return False
    scope = " ".join(str(analytical_scope or "").casefold().split())
    if _MODERATION_TAXONOMY_PATTERN.search(scope):
        return False
    return any(
        " ".join(match.group(0).casefold().split()) not in scope
        for match in matches
    )


def _reason_denies_asserted_property(
    reason: Any,
    asserted_property: str,
) -> bool:
    """Reject a direction flag contradicted by its own prose rationale."""

    reason_text = " ".join(str(reason or "").split())
    property_text = " ".join(str(asserted_property or "").split())
    property_is_negative = bool(
        _RETRIEVAL_NEGATIVE_READING_PATTERN.search(property_text)
    )
    property_is_positive = bool(
        _RETRIEVAL_POSITIVE_READING_PATTERN.search(property_text)
    )
    if property_is_negative:
        return bool(
            _NEGATED_NEGATIVE_READING_PATTERN.search(reason_text)
            or (
                _RETRIEVAL_POSITIVE_READING_PATTERN.search(reason_text)
                and not _RETRIEVAL_NEGATIVE_READING_PATTERN.search(
                    reason_text
                )
            )
        )
    if property_is_positive:
        return bool(
            _NEGATED_POSITIVE_READING_PATTERN.search(reason_text)
            or (
                _RETRIEVAL_NEGATIVE_READING_PATTERN.search(reason_text)
                and not _RETRIEVAL_POSITIVE_READING_PATTERN.search(
                    reason_text
                )
            )
        )
    return False


def _reason_clearly_affirms_opposite_property(
    reason: Any,
    asserted_property: str,
) -> bool:
    """Distinguish genuine counterevidence from mere absence or ambiguity."""

    reason_text = " ".join(str(reason or "").split())
    property_text = " ".join(str(asserted_property or "").split())

    def explicitly_refutes(pattern: re.Pattern[str]) -> bool:
        return any(
            pattern.search(sentence)
            and _PROPERTY_REFUTATION_MARKER_PATTERN.search(sentence)
            and not _NEGATED_PROPERTY_REFUTATION_PATTERN.search(sentence)
            for sentence in re.split(r"[.!?;\n]+", reason_text)
        )

    if _RETRIEVAL_NEGATIVE_READING_PATTERN.search(property_text):
        if explicitly_refutes(_RETRIEVAL_NEGATIVE_READING_PATTERN):
            return True
        negative_is_asserted = bool(
            _RETRIEVAL_NEGATIVE_READING_PATTERN.search(reason_text)
            and not _NEGATED_NEGATIVE_READING_PATTERN.search(reason_text)
        )
        nonnegative_only = bool(
            _RETRIEVAL_POSITIVE_READING_PATTERN.search(reason_text)
            and not negative_is_asserted
        )
        if _AMBIGUOUS_POLARITY_PATTERN.search(reason_text):
            # Uncertainty between neutral and positive is still unambiguously
            # counter to a negative-only hypothesis.
            return nonnegative_only
        return bool(
            _RETRIEVAL_AFFIRMATIVE_POSITIVE_PATTERN.search(reason_text)
            and not negative_is_asserted
        )
    if _RETRIEVAL_AFFIRMATIVE_POSITIVE_PATTERN.search(property_text):
        if explicitly_refutes(_RETRIEVAL_AFFIRMATIVE_POSITIVE_PATTERN):
            return True
        if _AMBIGUOUS_POLARITY_PATTERN.search(reason_text):
            return False
        negative_is_asserted = bool(
            _RETRIEVAL_NEGATIVE_READING_PATTERN.search(reason_text)
            and not _NEGATED_NEGATIVE_READING_PATTERN.search(reason_text)
        )
        positive_is_asserted = bool(
            _RETRIEVAL_AFFIRMATIVE_POSITIVE_PATTERN.search(reason_text)
            and not _NEGATED_POSITIVE_READING_PATTERN.search(reason_text)
        )
        return negative_is_asserted and not positive_is_asserted
    return False


def _reason_explicitly_denies_topic(
    reason: Any,
    target_topic: str,
    *,
    require_explicit_target: bool = False,
) -> bool:
    """Detect a literal topic denial without encoding any corpus domain."""

    surface = " ".join(str(reason or "").split())
    if (
        not require_explicit_target
        and _TOPICALITY_NEGATION_PATTERN.search(surface) is not None
    ):
        return True
    topic_tokens = re.findall(r"\w+", str(target_topic or ""), re.UNICODE)
    if not topic_tokens:
        return False
    topic = r"\s+".join(re.escape(token) for token in topic_tokens)
    return re.search(
        rf"\b(?:unrelated|irrelevant)\s+(?:to|for)\s+{topic}\b|"
        rf"\boff[- ]topic\s+(?:to|for)\s+{topic}\b|"
        rf"\bnot\s+(?:(?:directly|explicitly|clearly|specifically)\s+)?"
        rf"(?:about\s+|related\s+to\s+)?{topic}\b|"
        rf"\b(?:could|may|might)\s+"
        rf"(?:(?:refer|relate|apply|connect)\s+to|involve|be\s+about)\s+"
        rf"{topic}\w*[^.!?\n]{{0,80}}\bbut\s+not\s+"
        rf"(?:explicit|clear|specific)\w*\b|"
        rf"\bno\s+(?:mention|reference)\s+(?:of|to)\s+{topic}\b|"
        rf"\bno\s+(?:(?:clear|direct|specific|explicit)\s+)?"
        rf"(?:link|connection|reference)\s+(?:to|with)\s+{topic}\b|"
        rf"\bno\s+(?:(?:clear|direct|specific|explicit)\s+)?"
        rf"{topic}\s+(?:content|context|reference)\b|"
        rf"\bnicht\s+(?:über|ueber|zu|zum|zur|das\s+thema\s+)?{topic}\b|"
        rf"\bnicht\s+(?:direkt\s+)?{topic}\s+"
        rf"(?:erwähnt|erwaehnt|genannt|behandelt|betrifft)\b|"
        rf"\bnicht\s+(?:direkt|explizit)\s+auf\s+{topic}\b|"
        rf"\b(?:erwähnt|erwaehnt|nennt|behandelt|betrifft)\s+"
        rf"nicht\s+(?:direkt\s+)?{topic}\b|"
        rf"\b(?:erwähnt|erwaehnt|nennt|behandelt|betrifft)\s+"
        rf"kein(?:e|en|er|es)?\s+{topic}\b|"
        rf"\b(?:erwähnt|erwaehnt|nennt|behandelt|betrifft)\s+"
        rf"(?:jedoch\s+)?weder\s+{topic}\w*\s+noch\b|"
        rf"\b(?:does|do)\s+not\s+"
        rf"(?:(?:directly|explicitly|clearly|specifically)\s+)?"
        rf"(?:mention|address|discuss|treat)\s+{topic}\w*\b|"
        rf"\b(?:does|do)\s+not\s+"
        rf"(?:(?:directly|explicitly|clearly|specifically)\s+)?"
        rf"refer\s+to\s+{topic}\w*\b|"
        rf"\b(?:does|do)\s+not\s+contain\s+(?:any\s+)?"
        rf"(?:mention|reference)\s+(?:of|to)\s+{topic}\w*\b|"
        rf"\bcontains?\s+no\s+(?:mention|reference)\s+"
        rf"(?:of|to)\s+{topic}\w*\b|"
        rf"\b{topic}\w*\s+(?:wird|werden|ist|sind|is|are|was|were)\s+"
        rf"(?:nicht|not)\s+"
        rf"(?:(?:direkt|explizit|klar|eindeutig|directly|explicitly|clearly)\s+)?"
        rf"(?:erwähnt|erwaehnt|genannt|behandelt|adressiert|thematisiert|"
        rf"mentioned|named|addressed|discussed|treated)\b|"
        rf"\b(?:behandelt|betrifft|thematisiert)\s+"
        rf"kein(?:e|en|er|es)?\s+(?:ziel)?thema\s+{topic}\b|"
        rf"\bbezieht\s+sich\s+nicht\s+auf\s+{topic}\b|"
        rf"(?:\b(?:und|aber|jedoch|sondern)\s+|,\s*)nicht\s+"
        rf"(?:(?:direkt|explizit|klar|eindeutig|spezifisch)\s+)?"
        rf"(?:auf\s+|über\s+|ueber\s+|zu\s+|zum\s+|zur\s+|um\s+)?"
        rf"{topic}\b|"
        rf"\b(?:ist|sei)\s+nicht\s+"
        rf"(?:(?:direkt|explizit)\s+)?auf\s+{topic}\s+bezogen\b|"
        rf"\bnicht\s+(?:(?:direkt|explizit|klar)\s+)?"
        rf"(?:mit|an)\s+(?:(?:der|dem|den)\s+)?{topic}\w*\s+"
        rf"(?:verknüpft|verknuepft|verbunden|gekoppelt)\b|"
        rf"\bnot\s+(?:(?:directly|explicitly|clearly)\s+)?"
        rf"(?:linked|connected|related)\s+(?:to|with)\s+{topic}\w*\b|"
        rf"\b{topic}\w*[^.!?\n]{{0,100}}\bwithout\s+"
        rf"(?:(?:clear|direct|specific)\s+)?"
        rf"(?:relevance|relation|link|connection)\b|"
        rf"\b(?:tangential|peripheral)\s+(?:to|for)\s+{topic}\w*\b|"
        rf"\b(?:ist|sei)\s+nicht\s+(?:direkt\s+)?relevant\s+"
        rf"(?:für|fuer|zu|zum|zur)\s+{topic}\b|"
        rf"\b(?:enthält|enthaelt|liefert|bietet)\s+kein(?:e|en|er|es)?\s+"
        rf"(?:aussage|erwähnung|erwaehnung|bezug)\s+"
        rf"(?:zu|zum|zur|über|ueber|von)\s+"
        rf"(?:(?:der\s+)?darstellung\s+von\s+)?"
        rf"{topic}\b|"
        rf"\b(?:es\s+geht|geht\s+es)\b[^.!?\n]{{0,100}}"
        rf"\bnicht\s+um\s+{topic}\b|"
        rf"\bkein(?:e|en|er|es)?\s+(?:erwähnung|erwaehnung|bezug)\s+"
        rf"(?:von|zu|zum|zur)\s+{topic}\b|"
        rf"\bohne\s+(?:(?:klar(?:e|en|er|es)?|direkt(?:e|en|er|es)?|"
        rf"explizit(?:e|en|er|es)?)\s+)?"
        rf"(?:bezug|bezugnahme|erwähnung|erwaehnung)\s+"
        rf"(?:auf|zu|zum|zur|von)\s+{topic}\b|"
        rf"\b(?:fehlt|fehlen)\s+(?:ein(?:e|en|er|es)?\s+)?"
        rf"(?:(?:klar(?:e|en|er|es)?|direkt(?:e|en|er|es)?|"
        rf"explizit(?:e|en|er|es)?)\s+)?"
        rf"(?:bezug|bezugnahme|aussage|erwähnung|erwaehnung)\s+"
        rf"(?:auf|zu|zum|zur|von)\s+{topic}\b|"
        rf"\bkein(?:e|en|er|es)?\s+"
        rf"(?:(?:klar(?:e|en|er|es)?|direkt(?:e|en|er|es)?|"
        rf"konkret(?:e|en|er|es)?|explizit(?:e|en|er|es)?)\s+)?"
        rf"(?:aussage|bezug|bezugnahme|erwähnung|erwaehnung)\s+"
        rf"(?:auf|zu|zum|zur|von)\s+{topic}\b",
        surface,
        re.IGNORECASE,
    ) is not None


def _topicality_reason_matches_label(
    label: str,
    reason: Any,
    *,
    target_topic: str = "",
) -> bool:
    """Reject an explicit prose verdict that contradicts its enum label."""

    surface = " ".join(str(reason or "").split())
    denies_topic = _reason_explicitly_denies_topic(reason, target_topic)
    if label in {"relevant", "marginal"}:
        return not denies_topic
    if label == "off_topic":
        if denies_topic:
            return True
        return _TOPICALITY_AFFIRMATION_PATTERN.search(surface) is None
    return False


def _candidate_source_quote(fact_payload: dict[str, Any]) -> str:
    """Choose a literal fallback excerpt when an off-topic label omits one."""

    grounding_quotes = list(fact_payload.get("grounding_quotes", []) or [])
    for raw_quote in grounding_quotes:
        quote = str(raw_quote or "").strip()
        if quote.casefold().startswith("hit="):
            return _normalise_candidate_quote(quote.split("=", 1)[1])[:400]
    statement = str(fact_payload.get("statement", "") or "").strip()
    return statement[:400]


def _candidate_literal_source_surface(
    fact_payload: dict[str, Any],
) -> str:
    """Expose source text without analysis-input or provenance metadata."""

    surfaces = [str(fact_payload.get("statement", "") or "").strip()]
    for raw_quote in list(fact_payload.get("grounding_quotes", []) or []):
        quote = str(raw_quote or "").strip()
        if not quote:
            continue
        if quote.casefold().startswith("hit="):
            quote = quote.split("=", 1)[1].strip()
        elif "=" in quote:
            continue
        surfaces.append(quote)
    return " ".join(_dedupe_ordered_strs(surfaces))


def _candidate_source_sentences(fact_payload: dict[str, Any]) -> List[str]:
    """Expose literal sentence boundaries so synthesis cannot move attachments."""

    source = _candidate_source_quote(fact_payload)
    initial_dot = "__CC_INITIAL_DOT__"
    protected_source = re.sub(
        r"\b([A-ZÄÖÜ])\.(?=\s+[A-ZÄÖÜ][a-zäöüß])",
        lambda match: match.group(1) + initial_dot,
        source,
    )
    sentences = [
        " ".join(part.replace(initial_dot, ".").split())
        for part in re.split(
            r"(?<=[.!?])\s+|[\r\n]+",
            protected_source,
        )
        if " ".join(part.split())
    ]
    return sentences[:6]


_NEGATED_NOMINAL_COMPLEMENT_PATTERN = re.compile(
    r"\b(?:kein(?:e|en|em|er|es)?|no)\s+"
    r"(?P<head>[\wÄÖÜäöüß-]{4,})"
    r"(?:\s+[\wÄÖÜäöüß-]+){0,5}?\s+"
    r"(?:für|fuer|for)\s+"
    r"(?P<object>[^.!?;\n]{3,80})",
    re.IGNORECASE,
)
_MERGED_NEGATIVE_COORDINATION_PATTERN = re.compile(
    r"\b(?:weder\b[^.!?\n]{0,180}\bnoch|"
    r"neither\b[^.!?\n]{0,180}\bnor)\b",
    re.IGNORECASE,
)


def _merges_distinct_sentence_complements(
    fact_payloads: List[dict[str, Any]],
    claim_text: str,
) -> bool:
    """Reject an explicit neither/nor merge of relations with other objects."""

    claim = str(claim_text or "")
    if _MERGED_NEGATIVE_COORDINATION_PATTERN.search(claim) is None:
        return False

    def stems(value: str) -> set[str]:
        tokens = {
            token.casefold()
            for token in re.findall(
                r"[A-Za-zÄÖÜäöüß]{4,}",
                str(value or ""),
            )
        }
        return {token if len(token) < 8 else token[:7] for token in tokens}

    claim_stems = stems(claim)
    for payload in fact_payloads:
        pairs: List[tuple[str, set[str]]] = []
        for sentence in _candidate_source_sentences(payload):
            match = _NEGATED_NOMINAL_COMPLEMENT_PATTERN.search(sentence)
            if match is None:
                continue
            head_stems = stems(match.group("head"))
            object_stems = stems(match.group("object"))
            if head_stems and object_stems:
                pairs.append((next(iter(head_stems)), object_stems))
        for first_index, (first_head, first_object) in enumerate(pairs):
            for second_head, second_object in pairs[first_index + 1 :]:
                if first_object & second_object:
                    continue
                both_heads_visible = {
                    first_head,
                    second_head,
                }.issubset(claim_stems)
                if not both_heads_visible:
                    continue
                first_only = bool(first_object & claim_stems) and not bool(
                    second_object & claim_stems
                )
                second_only = bool(second_object & claim_stems) and not bool(
                    first_object & claim_stems
                )
                if first_only or second_only:
                    return True
    return False


def _candidate_quote_mentions_target_topic(
    fact_payload: dict[str, Any],
    target_topic: str,
) -> bool:
    """Require the claimed target itself to occur in the quoted surface."""

    target_tokens = re.findall(
        r"\w+",
        str(target_topic or "").casefold(),
        re.UNICODE,
    )
    quote_tokens = set(
        re.findall(
            r"\w+",
            _candidate_source_quote(fact_payload).casefold(),
            re.UNICODE,
        )
    )
    return bool(target_tokens) and all(
        any(
            quote_token == token
            or (
                len(token) >= 5
                and quote_token.startswith(token)
                and len(quote_token) - len(token) <= 4
            )
            for quote_token in quote_tokens
        )
        for token in target_tokens
    )


def _candidate_search_anchors(candidate_facts: List[Any]) -> List[str]:
    """Read the actual search inputs carried by candidate facts."""

    anchors: List[str] = []
    seen: set[str] = set()
    for fact in candidate_facts:
        for raw_quote in list(
            getattr(fact, "grounding_quotes", []) or []
        ):
            quote = str(raw_quote or "").strip()
            if not quote.casefold().startswith("analysis_input="):
                continue
            anchor = quote.split("=", 1)[1].strip()
            candidates = [anchor]
            candidates.extend(
                match.group(1)
                for match in re.finditer(
                    r'\[\s*(?:word|lemma|pos|tag)\s*=\s*"([^"\\]+)"\s*\]',
                    anchor,
                    re.IGNORECASE,
                )
            )
            for candidate in candidates:
                value = candidate.strip()
                folded = value.casefold()
                if not value or folded in seen:
                    continue
                seen.add(folded)
                anchors.append(value)
    return anchors


_HYPOTHESIS_QUANTIFIER_PATTERN = re.compile(
    r"\b(?:immer|nie|alle(?:n|m|r|s)?|jede(?:n|m|r|s)?|"
    r"ausnahmslos|ausschließlich|ausschliesslich|"
    r"always|never|all|every|only|exclusively)\b",
    re.IGNORECASE,
)

_EXPLICIT_TESTABLE_HYPOTHESIS_PATTERN = re.compile(
    r"\b(?:hypothes\w*|testable\s+hypothes\w*)\b",
    re.IGNORECASE,
)
_COMPETING_HYPOTHESIS_REQUEST_PATTERN = re.compile(
    r"(?:\b(?:konkurrier\w*|rival\w*|competing|rival)\b"
    r"[^.!?\n]{0,100}\bhypothes\w*\b|"
    r"\bhypothes\w*\b[^.!?\n]{0,100}"
    r"\b(?:konkurrier\w*|rival\w*|competing|rival)\b)",
    re.IGNORECASE,
)
_HYPOTHESIS_SCOPE_LITERALISM_PATTERN = re.compile(
    r"(?:\b(?:nur|only|isoliert\w*|einzel\w*|sichtbar\w*|visible|"
    r"top[- ]?n)\b[^.!?\n]{0,220}\b(?:beleg\w*|beispiel\w*|"
    r"passage\w*|treffer\w*|example\w*|source\w*|hit\w*)\b"
    r"[^.!?\n]{0,220}\b(?:korpusweit\w*|systematisch\w*|"
    r"vollst[aä]ndig\w*|pr[aä]valenz\w*|verteilung\w*|domin\w*|"
    r"corpus[- ]?wide|systematic\w*|prevalen\w*|distribution\w*)\b)|"
    r"(?:\b(?:hypothes\w*|widerleg\w*|falsifiz\w*|schw[aä]ch\w*|"
    r"gegen(?:befund|muster)\w*|counter[- ]?result\w*|falsif\w*)\b"
    r"[^.!?\n]{0,220}\b(?:nicht\s+beleg\w*|unbeleg\w*|"
    r"nicht\s+beobacht\w*|nicht\s+in\s+(?:der\s+)?quelle|"
    r"not\s+(?:supported|observed|in\s+the\s+source)|"
    r"absent\s+from\s+the\s+source)\b)|"
    r"(?:\b(?:quelle\w*|source\w*|beleg\w*|evidence\w*)\b"
    r"[^.!?\n]{0,220}\b(?:beweis\w*|establish\w*|support\w*)\b"
    r"[^.!?\n]{0,100}\b(?:nicht|not|no)\b[^.!?\n]{0,100}"
    r"\b(?:korpusweit\w*|systematisch\w*|pr[aä]valenz\w*|domin\w*|"
    r"corpus[- ]?wide|systematic\w*|prevalen\w*)\b)",
    re.IGNORECASE,
)

_LOCAL_RETRIEVAL_SCOPE_PATTERN = re.compile(
    r"\b(?:in|an|aus)\s+dies(?:em|er|en|es)\s+"
    r"(?:\w+\s+){0,2}"
    r"(?:ausschnitt|abschnitt|passage|beleg|treffer|kontext|sichtung|textstelle|text)\w*\b|"
    r"\b(?:in|unter)\s+(?:den|der)\s+"
    r"(?:\w+\s+){0,4}"
    r"(?:ausschnitt|abschnitt|passage|beleg|treffer|kontext|sichtung|textstelle|text)\w*\b|"
    r"\bdies(?:er|e|es)\s+"
    r"(?:\w+\s+){0,2}"
    r"(?:ausschnitt|abschnitt|passage|beleg|treffer|kontext|sichtung|textstelle|text)\w*\b|"
    r"\b(?:in|aus)\s+ein(?:em|er|en)\s+"
    r"(?:(?:anderen|sichtbar|zitiert|referenziert)\w*\s+){0,2}"
    r"(?:ausschnitt|abschnitt|passage|beleg|treffer|kontext|sichtung|textstelle|text)\w*\b|"
    r"\bein(?:e|er|es)\s+(?:(?:andere|weitere)\w*\s+)?(?:sichtbar\w*\s+)?"
    r"(?:ausschnitt|abschnitt|passage|beleg|treffer|kontext|sichtung|textstelle|text)\w*\b|"
    r"\b(?:ein\w*|der|dieser)\s+(?:andere\w*\s+)?teil\s+"
    r"(?:der|dieser)\s+"
    r"(?:ausschnitt|abschnitt|passage|beleg|treffer|kontext|sichtung|textstelle|text)\w*\b|"
    r"\b(?:die|der|das)\s+"
    r"(?:(?:vorliegend|sichtbar|zitiert|referenziert)\w*\s+){0,2}"
    r"(?:ausschnitt|abschnitt|passage|beleg|treffer|kontext|sichtung|textstelle|text)\w*\b|"
    r"\b(?:einige|mehrere|vorliegend|diese|sichtbar|zitiert|abgerufen|"
    r"zurückgegeben|zurueckgegeben|some|several|these|visible|retrieved)\w*\s+"
    r"(?:(?:top[-‑–— ]?n|semantisch)\w*[-‑–— ]*)?"
    r"(?:ausschnitt|abschnitt|passage|beleg|treffer|ergebnis|auswahl|kontext|sichtung|textstelle|text)\w*\b",
    re.IGNORECASE,
)
_AMBIGUOUS_RETRIEVAL_SET_SCOPE_PATTERN = re.compile(
    r"\b(?:die\s+vorliegenden|die\s+sichtbaren|die\s+zitierten|"
    r"diese|jene)\s+"
    r"(?:passagen|treffer|ausschnitte|belege|texte|ergebnisse)\b|"
    r"\b(?:the\s+present|the\s+visible|the\s+cited|these|those)\s+"
    r"(?:passages|hits|excerpts|sources|texts|results)\b",
    re.IGNORECASE,
)
_UNBOUNDED_RETRIEVAL_INTERPRETATION_PATTERN = re.compile(
    r"\b(?:im|für\s+das|fuer\s+das|über\s+das|ueber\s+das)\s+"
    r"(?:gesamte[nr]?\s+)?korpus\b|"
    r"\bkorpusweit\b|"
    r"\b(?:häufig|haeufig|meist(?:ens)?|überwiegend|ueberwiegend|"
    r"typisch|dominant|generell|allgemein|tendenz)\w*\b",
    re.IGNORECASE,
)
_NEGATED_UNBOUNDED_RETRIEVAL_PATTERN = re.compile(
    r"\bnicht\s+als\s+(?:ein(?:e|en|em|er|es)?\s+)?"
    r"(?:generell|allgemein|korpusweit)\w*\s+"
    r"(?:thema|tendenz|muster|befund|aussage)\w*|"
    r"\bkein(?:e|en|em|er|es)?\s+"
    r"(?:generell|allgemein|korpusweit)\w*\s+"
    r"(?:thema|tendenz|muster|befund|aussage|schlussfolgerung)\w*|"
    r"\bnicht\s+(?:im|für\s+das|fuer\s+das|über\s+das|ueber\s+das)\s+"
    r"gesamte[nr]?\s+korpus\b",
    re.IGNORECASE,
)
_RELATED_BEARER_NOUN_PATTERN = re.compile(
    r"\b\w*(?:akteur|gruppe|politik|praxis|maßnahm|massnahm|position|"
    r"bezeichnung|folge|wirkung|handlung|vorschlag|forderung)\w*\b",
    re.IGNORECASE,
)
_TARGET_AS_CONTEXT_MODIFIER_PATTERN = re.compile(
    r"(?:im\s+zusammenhang\s+mit|mit\s+bezug\s+auf|"
    r"im\s+kontext\s+von)\s*$",
    re.IGNORECASE,
)


def _without_hypothesis_quantifier(value: Any) -> str:
    return " ".join(
        _HYPOTHESIS_QUANTIFIER_PATTERN.sub(" ", str(value or "")).split()
    )


def _is_explicit_testable_hypothesis_claim(claim: dict[str, Any]) -> bool:
    """Recognise a proposal whose prospective counter-result is not evidence."""

    return _schema_is_testable_hypothesis_claim(
        str(claim.get("text", "") or ""),
        claim_kind=str(claim.get("claim_kind", "") or ""),
        assertion_level=str(claim.get("assertion_level", "") or ""),
    )


def _has_unbounded_retrieval_assertion(value: Any) -> bool:
    """Ignore explicit scope denials while retaining positive global claims."""

    text = _NEGATED_UNBOUNDED_RETRIEVAL_PATTERN.sub(
        " ", str(value or "")
    )
    return bool(_UNBOUNDED_RETRIEVAL_INTERPRETATION_PATTERN.search(text))


def _ambiguous_retrieval_subset_scope_claim_ids(
    envelope: Any,
    assessments: List[dict[str, str]],
) -> List[str]:
    """Reject deictic set claims whose citations cover only a hidden subset."""

    visible_ids = {
        str(item.get("fact_id", "") or "").strip()
        for item in assessments
        if str(item.get("fact_id", "") or "").strip()
        and (
            item.get("topic_relation") in {"relevant", "marginal"}
            or item.get("relation_to_requested_conclusion")
            in {
                "supports",
                "related_support",
                "counterevidence",
                "mixed_or_unclear",
            }
        )
    }
    if len(visible_ids) < 2:
        return []
    rejected: List[str] = []
    for claim in list(getattr(envelope, "claims", []) or []):
        claim_id = str(getattr(claim, "id", "") or "").strip()
        cited_ids = {
            str(fact_id).strip()
            for fact_id in list(getattr(claim, "fact_ids", []) or [])
            if str(fact_id).strip() in visible_ids
        }
        if (
            claim_id
            and cited_ids
            and cited_ids != visible_ids
            and _AMBIGUOUS_RETRIEVAL_SET_SCOPE_PATTERN.search(
                str(getattr(claim, "text", "") or "")
            )
        ):
            rejected.append(claim_id)
    return _dedupe_ordered_strs(rejected)


def _universal_hypothesis_clause(question: Any) -> str:
    """Keep extraction on the clause carrying the universal proposition."""

    text = " ".join(str(question or "").split())
    clauses = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+|[\r\n]+", text)
        if part.strip()
    ]
    return next(
        (
            clause
            for clause in clauses
            if _HYPOTHESIS_QUANTIFIER_PATTERN.search(clause)
        ),
        text,
    )


def _contiguous_token_span(value: Any, source: Any) -> Optional[Tuple[int, int]]:
    needle = re.findall(r"\w+", str(value or "").casefold(), re.UNICODE)
    haystack = re.findall(r"\w+", str(source or "").casefold(), re.UNICODE)
    if not needle or len(needle) > len(haystack):
        return None
    width = len(needle)
    for index in range(len(haystack) - width + 1):
        if haystack[index : index + width] == needle:
            return index, index + width
    return None


def _fallback_hypothesis_from_prequantifier_anchor(
    hypothesis_clause: str,
    search_anchors: List[str],
) -> Optional[Tuple[str, str]]:
    """Recover only the unambiguous anchor-before-quantifier proposition shape."""

    quantifier = _HYPOTHESIS_QUANTIFIER_PATTERN.search(hypothesis_clause)
    if quantifier is None:
        return None
    quantifier_token_index = len(
        re.findall(
            r"\w+",
            hypothesis_clause[: quantifier.start()],
            re.UNICODE,
        )
    )
    grounded: List[str] = []
    for raw_anchor in search_anchors:
        anchor = _normalise_candidate_quote(raw_anchor)
        span = _contiguous_token_span(anchor, hypothesis_clause)
        if (
            not anchor
            or span is None
            or span[1] > quantifier_token_index
            or _HYPOTHESIS_QUANTIFIER_PATTERN.search(anchor)
        ):
            continue
        grounded.append(anchor)
    grounded = _dedupe_ordered_strs(grounded)
    if len(grounded) != 1:
        return None
    property_tail = hypothesis_clause[quantifier.end() :].strip(
        " \t,;:–—-!? ."
    )
    property_value = _without_hypothesis_quantifier(property_tail)
    if (
        len(re.findall(r"\w+", property_value, re.UNICODE)) < 2
        or _contiguous_token_span(grounded[0], property_value) is not None
    ):
        return None
    return grounded[0], property_value


_HYPOTHESIS_TRAILING_AUXILIARY_PATTERN = re.compile(
    r"\b(?:ist|sind|sei|seien|war|waren|wird|werden|wurde|wurden|"
    r"is|are|was|were|be|been)\s*$",
    re.IGNORECASE,
)


def _fallback_hypothesis_from_clause_structure(
    hypothesis_clause: str,
) -> Optional[Tuple[str, str]]:
    """Recover a simple subject/property split around a universal quantifier."""

    quantifier = _HYPOTHESIS_QUANTIFIER_PATTERN.search(hypothesis_clause)
    if quantifier is None:
        return None
    subject_prefix = hypothesis_clause[: quantifier.start()].strip()
    complementizers = list(
        re.finditer(r"\b(?:dass|that)\b", subject_prefix, re.IGNORECASE)
    )
    has_comma_boundary = "," in subject_prefix
    has_trailing_auxiliary = bool(
        _HYPOTHESIS_TRAILING_AUXILIARY_PATTERN.search(subject_prefix)
    )
    if complementizers:
        subject_prefix = subject_prefix[
            complementizers[-1].end():
        ].strip()
    elif has_comma_boundary:
        subject_prefix = subject_prefix.rsplit(",", 1)[-1].strip()
    subject_prefix = _HYPOTHESIS_TRAILING_AUXILIARY_PATTERN.sub(
        "", subject_prefix
    ).strip(" \t,;:–—-!? .")
    target_topic = _normalise_candidate_quote(subject_prefix)
    property_tail = hypothesis_clause[quantifier.end() :].strip(
        " \t,;:–—-!? ."
    )
    asserted_property = _without_hypothesis_quantifier(property_tail)
    target_tokens = re.findall(r"\w+", target_topic, re.UNICODE)
    property_tokens = re.findall(r"\w+", asserted_property, re.UNICODE)
    if not (
        (complementizers or has_comma_boundary or has_trailing_auxiliary)
        and 1 <= len(target_tokens) <= 12
        and len(property_tokens) >= 2
        and _contiguous_token_span(target_topic, hypothesis_clause) is not None
        and _contiguous_token_span(asserted_property, hypothesis_clause)
        is not None
        and _contiguous_token_span(target_topic, asserted_property) is None
        and not _HYPOTHESIS_QUANTIFIER_PATTERN.search(target_topic)
    ):
        return None
    return target_topic, asserted_property


def _dedupe_ordered_strs(values: List[str]) -> List[str]:
    """Order-preserving de-dup of stripped, truthy strings.

    Mirrors ``ReActOrchestrator._dedupe_ordered_strs`` verbatim so the verdict
    assembly stays byte-identical to the previous inline orchestrator logic.
    """
    seen: set[str] = set()
    result: List[str] = []
    for item in values:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _response_requirement_generation_payload(
    requirement: Any,
) -> dict[str, Any]:
    if callable(getattr(requirement, "to_dict", None)):
        payload = dict(requirement.to_dict())
    else:
        payload = {
            "id": str(getattr(requirement, "id", "") or ""),
            "description": str(
                getattr(requirement, "description", "") or ""
            ),
            "claim_kind": str(
                getattr(requirement, "claim_kind", "interpretation")
                or "interpretation"
            ),
            "source_quote": str(
                getattr(requirement, "source_quote", "") or ""
            ),
        }
    completion_checks = getattr(requirement, "completion_checks", None)
    payload["completion_checks"] = (
        _dedupe_ordered_strs(list(completion_checks() or []))
        if callable(completion_checks)
        else []
    )
    return payload


def _response_requirement_generation_payloads(
    requirements: List[Any],
) -> List[dict[str, Any]]:
    """Make counted sibling slots explicit without prescribing their content."""

    payloads = [
        _response_requirement_generation_payload(requirement)
        for requirement in requirements
    ]

    def group_key(payload: dict[str, Any]) -> tuple[str, str, str, tuple[str, ...]]:
        return (
            " ".join(str(payload.get("description", "") or "").split()).casefold(),
            str(payload.get("claim_kind", "") or "interpretation"),
            " ".join(str(payload.get("source_quote", "") or "").split()).casefold(),
            tuple(
                " ".join(str(check or "").split()).casefold()
                for check in list(payload.get("completion_checks", []) or [])
            ),
        )

    totals: dict[tuple[str, str, str, tuple[str, ...]], int] = {}
    for payload in payloads:
        key = group_key(payload)
        totals[key] = totals.get(key, 0) + 1
    positions: dict[tuple[str, str, str, tuple[str, ...]], int] = {}
    for payload in payloads:
        key = group_key(payload)
        group_size = totals[key]
        if group_size < 2:
            continue
        positions[key] = positions.get(key, 0) + 1
        payload["counted_group"] = {
            "unit_index": positions[key],
            "unit_count": group_size,
            "slot_semantics": "one_distinct_atomic_unit",
        }
        payload["atomic_slot_instruction"] = (
            "Dieser Slot verlangt genau eine eigenständige atomare Einheit der "
            "gezählten Gruppe. Atomar bedeutet genau eine analytische "
            "Proposition, nicht genau eine Fact-ID oder Tabellenzeile: Mehrere "
            "Facts dürfen gemeinsam ein einziges klar benanntes Muster oder "
            "einen Kontrast tragen. Der Claim muss nicht die Gesamtzahl aus "
            "dem pluralischen source_quote allein liefern."
        )
    return payloads


def _claim_signature(
    claim: Any,
) -> tuple[str, tuple[str, ...], str]:
    """Identify visible claim substance independently of model-chosen metadata.

    Claim kind is user-visible in the rendered section and may legitimately
    correct a misclassified first attempt (for example interpretation ->
    observation or observation -> limitation). Hidden assertion strength does
    not alter the visible proposition and therefore cannot bypass a rejection.
    """

    text = " ".join(str(getattr(claim, "text", "") or "").split()).casefold()
    claim_id = str(getattr(claim, "id", "") or "").strip()
    semantic_kind = str(
        getattr(claim, "claim_kind", "") or "observation"
    )
    return (
        text or f"id:{claim_id}",
        tuple(
            sorted(
                {
                    str(item)
                    for item in list(getattr(claim, "fact_ids", []) or [])
                    if str(item)
                }
            )
        ),
        semantic_kind,
    )


def _visible_claim_signature(claim: Any) -> tuple[str, str]:
    """Identify duplicate user-visible propositions across retry fact bindings."""

    return (
        " ".join(
            str(getattr(claim, "text", "") or "").split()
        ).casefold(),
        str(getattr(claim, "claim_kind", "") or "observation"),
    )


def _claim_matches_repeated_requirement_structure(
    claim: Any,
    requirement_payload: dict[str, Any],
) -> bool:
    """Do not assign an unrelated same-kind claim to a counted sibling slot."""

    checks = " ".join(
        str(check or "")
        for check in list(
            requirement_payload.get("completion_checks", []) or []
        )
    ).casefold()
    text = str(getattr(claim, "text", "") or "")
    if (
        "assertion_level ist tentative" in checks
        and str(getattr(claim, "assertion_level", "") or "")
        != "tentative"
    ):
        return False
    if (
        "als hypothese" in checks
        and _EXPLICIT_TESTABLE_HYPOTHESIS_PATTERN.search(text) is None
    ):
        return False
    return True


def _assign_equivalent_missing_response_slots(
    claims: List[Any],
    requirements: List[Any],
) -> set[str]:
    """Repair bookkeeping IDs for repeated, semantically identical duties."""

    groups: dict[tuple[str, str, str, tuple[str, ...]], List[str]] = {}
    claim_kind_by_group: dict[
        tuple[str, str, str, tuple[str, ...]], str
    ] = {}
    payload_by_group: dict[
        tuple[str, str, str, tuple[str, ...]], dict[str, Any]
    ] = {}
    for requirement in requirements:
        requirement_id = str(
            getattr(requirement, "id", "") or ""
        ).strip()
        if not requirement_id:
            continue
        payload = _response_requirement_generation_payload(requirement)
        key = (
            " ".join(
                str(payload.get("description", "") or "").split()
            ).casefold(),
            str(
                payload.get("claim_kind", "")
                or "interpretation"
            ),
            " ".join(
                str(payload.get("source_quote", "") or "").split()
            ).casefold(),
            tuple(
                " ".join(str(check or "").split()).casefold()
                for check in list(payload.get("completion_checks", []) or [])
            ),
        )
        groups.setdefault(key, []).append(requirement_id)
        claim_kind_by_group[key] = key[1]
        payload_by_group[key] = payload
    repeated_groups = {
        key: requirement_ids
        for key, requirement_ids in groups.items()
        if len(requirement_ids) > 1
    }
    if not repeated_groups:
        return set()
    known_requirement_ids = {
        str(getattr(requirement, "id", "") or "").strip()
        for requirement in requirements
        if str(getattr(requirement, "id", "") or "").strip()
    }
    repeated_group_count_by_kind: dict[str, int] = {}
    for key in repeated_groups:
        claim_kind = claim_kind_by_group[key]
        repeated_group_count_by_kind[claim_kind] = (
            repeated_group_count_by_kind.get(claim_kind, 0) + 1
        )

    equivalent_ids: set[str] = set()
    for key, requirement_ids in repeated_groups.items():
        claim_kind = claim_kind_by_group[key]
        requirement_payload = payload_by_group[key]
        requirement_set = set(requirement_ids)
        equivalent_ids.update(requirement_set)
        candidates = [
            claim
            for claim in claims
            if str(
                getattr(claim, "claim_kind", "") or ""
            ) == claim_kind
            and (
                str(
                    getattr(claim, "response_requirement_id", "") or ""
                ).strip()
                in requirement_set
                or (
                    str(
                        getattr(
                            claim,
                            "response_requirement_id",
                            "",
                        )
                        or ""
                    ).strip()
                    not in known_requirement_ids
                    and repeated_group_count_by_kind.get(claim_kind, 0) == 1
                    and _claim_matches_repeated_requirement_structure(
                        claim,
                        requirement_payload,
                    )
                )
            )
        ]
        used_ids: set[str] = set()
        used_substance: set[tuple[str, str]] = set()
        assignable: List[Any] = []
        for claim in candidates:
            requirement_id = str(
                getattr(claim, "response_requirement_id", "") or ""
            ).strip()
            signature = _visible_claim_signature(claim)
            if requirement_id in used_ids or signature in used_substance:
                claim.response_requirement_id = ""
                if signature not in used_substance:
                    assignable.append(claim)
                continue
            used_ids.add(requirement_id)
            used_substance.add(signature)
        missing_ids = [
            requirement_id
            for requirement_id in requirement_ids
            if requirement_id not in used_ids
        ]
        for claim, requirement_id in zip(assignable, missing_ids):
            claim.response_requirement_id = requirement_id
            used_substance.add(_visible_claim_signature(claim))
    return equivalent_ids


def _competing_hypothesis_requirement_ids(
    contract: Any,
    question_text: str,
) -> List[str]:
    """Return the repeated hypothesis slots that must form one real contrast."""

    requirements = list(
        getattr(contract, "response_requirements", []) or []
    )
    request_surface = " ".join(
        [
            str(question_text or ""),
            *[
                " ".join(
                    [
                        str(getattr(item, "description", "") or ""),
                        str(getattr(item, "source_quote", "") or ""),
                    ]
                )
                for item in requirements
            ],
        ]
    )
    if _COMPETING_HYPOTHESIS_REQUEST_PATTERN.search(request_surface) is None:
        return []
    repeated_ids = _assign_equivalent_missing_response_slots(
        [],
        requirements,
    )
    hypothesis_ids = [
        str(getattr(item, "id", "") or "").strip()
        for item in requirements
        if str(getattr(item, "id", "") or "").strip() in repeated_ids
        and str(getattr(item, "claim_kind", "") or "")
        == "interpretation"
        and _EXPLICIT_TESTABLE_HYPOTHESIS_PATTERN.search(
            " ".join(
                [
                    str(getattr(item, "description", "") or ""),
                    str(getattr(item, "source_quote", "") or ""),
                ]
            )
        )
    ]
    return hypothesis_ids if len(hypothesis_ids) >= 2 else []


def _near_duplicate_visible_claim(left: Any, right: Any) -> bool:
    """Catch retry paraphrases that repeat nearly the entire proposition."""

    if str(getattr(left, "claim_kind", "") or "observation") != str(
        getattr(right, "claim_kind", "") or "observation"
    ):
        return False
    left_facts = {
        str(item)
        for item in list(getattr(left, "fact_ids", []) or [])
        if str(item)
    }
    right_facts = {
        str(item)
        for item in list(getattr(right, "fact_ids", []) or [])
        if str(item)
    }
    if left_facts and right_facts and left_facts.isdisjoint(right_facts):
        return False
    left_numbers = set(
        re.findall(
            r"(?<!\w)[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+)(?!\w)",
            str(getattr(left, "text", "") or ""),
        )
    )
    right_numbers = set(
        re.findall(
            r"(?<!\w)[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+)(?!\w)",
            str(getattr(right, "text", "") or ""),
        )
    )
    if left_numbers != right_numbers:
        # Similar wording must never collapse contradictory measurements.
        return False
    left_terms = set(
        re.findall(
            r"[^\W_]+",
            str(getattr(left, "text", "") or "").casefold(),
            re.UNICODE,
        )
    )
    right_terms = set(
        re.findall(
            r"[^\W_]+",
            str(getattr(right, "text", "") or "").casefold(),
            re.UNICODE,
        )
    )
    shared_term_count = len(left_terms & right_terms)
    shorter_term_count = min(len(left_terms), len(right_terms))
    if shorter_term_count < 4:
        return False
    if shorter_term_count < 10:
        return (
            shared_term_count >= 4
            and shared_term_count / shorter_term_count >= 0.75
        )
    return len(left_terms & right_terms) / len(left_terms | right_terms) >= 0.88


_DIRECT_NEGATIVE_RESULT_PATTERN = re.compile(
    r"\b(?:kein(?:e|en|er|es)?|fehl(?:t|en|end\w*)|nicht\s+vorhanden|"
    r"nicht\s+verfügbar|nicht\s+verfuegbar|ohne)\b",
    re.IGNORECASE,
)
_DIRECT_ATTESTATION_PATTERN = re.compile(
    r"\b(?:exakt\w*\s+)?(?:wortfolge\w*|phrase\w*|sequenz\w*|"
    r"ausdruck\w*|form\w*|treffer\w*|exact\s+(?:word\s+)?sequence|"
    r"phrase|sequence|expression|form|match)\b"
    r"[^.!?\n]{0,160}\b(?:belegt\w*|vertreten\w*|vorhanden\w*|"
    r"nachgewiesen\w*|enthalten\w*|attested|present|found|occurs?)\b|"
    r"\b(?:belegt\w*|vertreten\w*|vorhanden\w*|nachgewiesen\w*|"
    r"attested|present|found)\b[^.!?\n]{0,160}"
    r"\b(?:wortfolge\w*|phrase\w*|sequenz\w*|ausdruck\w*|"
    r"exact\s+(?:word\s+)?sequence|phrase|sequence|expression)\b",
    re.IGNORECASE,
)
_DIRECT_WORD_SKETCH_OBSERVATION_PATTERN = re.compile(
    r"\b(?:word[- ]?sketch|profil\w*|relation\w*|partnerzeil\w*)\b"
    r"[^.!?\n]{0,220}\b(?:sichtbar\w*|erschein\w*|zeig\w*|"
    r"weist\w*\s+aus|f\s*=|mindestfrequenz\w*)\b|"
    r"\b(?:sichtbar\w*|erschein\w*|zeig\w*)\b"
    r"[^.!?\n]{0,220}\b(?:relation\w*|partnerzeil\w*)\b|"
    r"\brelation\w*\b[^.!?\n]{0,220}"
    r"\b(?:partner(?:zeil\w*)?|Dependenzfrequenz\w*|f\s*=)\b",
    re.IGNORECASE,
)
_WORD_SKETCH_UNIT_EXPLANATION_PATTERN = re.compile(
    r"\b(?:zähleinheit|zaehleinheit|variable|rohfeld|feld)\s+[`*]?f(?:2|₂)?[`*]?\b|"
    r"\b[`*]?f(?:2|₂)?[`*]?\s+(?:steht|bezeichnet|gibt|zählt|zaehlt)\b",
    re.IGNORECASE,
)
_WORD_SKETCH_INTERPRETIVE_BRIDGE_PATTERN = re.compile(
    r"\b(?:deut\w*\s+auf|leg\w*\s+nahe|sprich\w*\s+für|"
    r"sprich\w*\s+fuer|muster\w*|typisch\w*|domin\w*|"
    r"häufig\w*|haeufig\w*|selten\w*|ursach\w*|kausal\w*|"
    r"sowohl\b[^.!?\n]{0,180}\bals\s+auch|"
    r"einerseits\b[^.!?\n]{0,180}\bandererseits|"
    r"unterschied\w*[^.!?\n]{0,100}\b(?:beziehungsdomän\w*|"
    r"dependenzbeziehung\w*|relation\w*|anbindung\w*)|"
    r"beziehungsdomän\w*|nebeneinander|gegenüberstell\w*|"
    r"gegenueberstell\w*)\b",
    re.IGNORECASE,
)
_METHOD_CONSEQUENCE_PATTERN = re.compile(
    r"(?:"
    r"\b(?:daher|deshalb|somit|folglich|dadurch|infolgedessen)\b|"
    r"\b(?:kann|darf|lässt|laesst)\b[^.!?\n]{0,100}\bnicht\b|"
    r"\bnicht\s+(?:möglich|moeglich|zulässig|zulaessig|berechenbar|"
    r"auswertbar|analysierbar|bestimmbar|ableitbar)\b|"
    r"\bkein(?:e|en|er|es)?\s+\w*(?:analyse|auswertung|vergleich|"
    r"urteil|berechnung)\w*\b|"
    r"\bkein(?:e|en|er|es)?\s+(?:trend)?urteil\w*\b|"
    r"\b(?:erfordert|benötigt|benoetigt|voraussetzung)\w*\b|"
    r"\b(?:deutet|spricht)\b[^.!?\n]{0,80}\b(?:auf|für|fuer)\b"
    r")",
    re.IGNORECASE,
)

_LEXICAL_REFERENCE_REQUEST_PATTERN = re.compile(
    r"\b(?:ohne|kein(?:e|en|er|es)?)\s+referenzkorpus\b",
    re.IGNORECASE,
)
_REFERENCE_BOUNDARY_PATTERN = re.compile(
    r"\b(?:referenzkorpus|vergleichsbasis|vergleichskorpus)\b",
    re.IGNORECASE,
)
_LEXICAL_RATING_BOUNDARY_PATTERN = re.compile(
    r"\bkein(?:e|en|er|es)?\s+"
    r"(?:(?:belastbar|objektiv|methodisch|valide|zuverlässig|"
    r"zuverlaessig)\w*\s+){0,2}"
    r"(?:einordnung|bewertung|klassifikation|qualitätsurteil|"
    r"qualitaetsurteil|qualitätsvergleich|qualitaetsvergleich|"
    r"qualität|qualitaet)\w*\b|"
    r"\bkein(?:e|en|er|es)?\s+(?:belastbare\w*\s+)?aussage\b"
    r"[^.!?\n]{0,120}\b(?:qualität|qualitaet|qualitätsniveau|qualitaetsniveau|"
    r"hoch|niedrig|moderat|typisch)\w*\b|"
    r"\b(?:lässt|laesst)\s+sich\b[^.!?\n]{0,120}\bnicht\b"
    r"[^.!?\n]{0,120}\b(?:einordnen|bewerten|bezeichnen|"
    r"klassifizieren|ableiten|beurteilen)\w*\b|"
    r"\b(?:kann|darf)\b[^.!?\n]{0,120}\bnicht\b"
    r"[^.!?\n]{0,120}\b(?:eingeordnet|bewertet|bezeichnet|"
    r"klassifiziert|abgeleitet|beurteilt)\w*\b",
    re.IGNORECASE,
)
_LEXICAL_ROBUSTNESS_REQUEST_PATTERN = re.compile(
    r"\b(?:belastbar\w*|robust\w*|längensensitiv\w*|"
    r"laengensensitiv\w*|korpusgröße\w*|korpusgroesse\w*)\b",
    re.IGNORECASE,
)
_LEXICAL_ROBUSTNESS_ANSWER_PATTERN = re.compile(
    r"(?:"
    r"\bsttr\b[^.!?\n]{0,100}\bmattr\b|"
    r"\bmattr\b[^.!?\n]{0,100}\bsttr\b"
    r")[^.!?\n]{0,180}\b(?:belastbar\w*|robust\w*|"
    r"längen[- ]?(?:sensitiv|kontrolliert)\w*|"
    r"laengen[- ]?(?:sensitiv|kontrolliert)\w*)\b|"
    r"\b(?:belastbar\w*|robust\w*|"
    r"längen[- ]?(?:sensitiv|kontrolliert)\w*|"
    r"laengen[- ]?(?:sensitiv|kontrolliert)\w*)\b[^.!?\n]{0,180}(?:"
    r"\bsttr\b[^.!?\n]{0,100}\bmattr\b|"
    r"\bmattr\b[^.!?\n]{0,100}\bsttr\b)",
    re.IGNORECASE,
)
_UNEQUAL_WINDOW_BOUNDARY_PATTERN = re.compile(
    r"(?:"
    r"\b(?:verschieden\w*|unterschiedlich\w*)\s+"
    r"fenster(?:größ|groess|läng|laeng)\w*\b[^.!?\n]{0,220}"
    r"\b(?:nicht\s+(?:direkt\s+)?vergleich\w*|keine\s+(?:direkte\s+)?"
    r"(?:rangfolge|methodenrangfolge|vergleichbarkeit)|nicht\s+zur\s+rangfolge)\b|"
    r"\b(?:sttr|mattr)\b[^.!?\n]{0,120}\b(?:sttr|mattr)\b"
    r"[^.!?\n]{0,180}\b(?:nicht\s+(?:direkt\s+)?vergleich\w*|"
    r"keine\s+(?:direkte\s+)?(?:rangfolge|methodenrangfolge|vergleichbarkeit))\b"
    r")",
    re.IGNORECASE,
)
_NGRAM_INTERPRETATION_REQUEST_PATTERN = re.compile(
    r"\b(?:formulierungsroutine\w*|formelhaft\w*|phraseolog\w*|"
    r"routinenkandidat\w*|routine\w*\s+prüfenswert\w*)\b",
    re.IGNORECASE,
)
_NGRAM_VALIDATION_PATTERN = re.compile(
    r"\b(?:kwic|kontext\w*|dispersion\w*|dokumentstreuung\w*)\b",
    re.IGNORECASE,
)
_NGRAM_EPISTEMIC_PATTERN = re.compile(
    r"\b(?:kann|könnte|koennte|möglich\w*|moeglich\w*|plausib\w*|"
    r"prüfenswert\w*|pruefenswert\w*|prüfbar\w*|pruefbar\w*|"
    r"kandidat\w*|routinenkandidat\w*|hypothese\w*|eher)\b",
    re.IGNORECASE,
)
_NGRAM_NEGATIVE_ONLY_PATTERN = re.compile(
    r"\b(?:kein(?:e|en|er|es)?|nicht)\b[^.!?\n]{0,80}"
    r"\b(?:kandidat\w*|routine\w*|hypothese\w*)\b",
    re.IGNORECASE,
)
_NGRAM_ROUTINE_CANDIDATE_PATTERN = re.compile(
    r"\b(?:routinenkandidat\w*|formulierungsroutine\w*|routine\w*|formelhaft\w*|"
    r"formulierungsrahmen\w*|phraseolog\w*|muster\w*)\b",
    re.IGNORECASE,
)
_KWIC_LOCAL_READING_PATTERN = re.compile(
    r"\b(?:lesart\w*|bedeutungsbeitrag\w*|geltungsbeitrag\w*|"
    r"verort\w*|lokalisier\w*|lokalität\w*|lokalitaet\w*|"
    r"geograph\w*|räumlich\w*|raeumlich\w*|"
    r"bezugsrahmen\w*|rahmenbeitrag\w*|anbindung\w*|bindung\w*|"
    r"bezug\w*|zuordnung\w*|zugehörig\w*|zugehoerig\w*|"
    r"modifizier\w*|adverbial\w*|adjunkt\w*|"
    r"präpositional\w*|praepositional\w*|reading\w*|locative\w*|"
    r"modifier\w*|prepositional\w*|attachment\w*|reference\w*)\b",
    re.IGNORECASE,
)
_KWIC_EPISTEMIC_PATTERN = re.compile(
    r"\b(?:kann|könnte|koennte|möglich\w*|moeglich\w*|plausib\w*|"
    r"mehrdeutig\w*|lesart\w*|can|could|possible\w*|plausible\w*|"
    r"ambiguous\w*|reading\w*|"
    r"(?:lässt|laesst)\s+sich\b[^.!?\n]{0,100}"
    r"\b(?:verstehen|lesen|deuten|interpretieren)\w*|"
    r"(?:deutet|weist)\b[^.!?\n]{0,80}\bdarauf\s+hin\b)\b",
    re.IGNORECASE,
)
_KWIC_AMBIGUITY_PATTERN = re.compile(
    r"\b(?:mehrdeutig\w*|möglich\w*\s+lesart\w*|"
    r"moeglich\w*\s+lesart\w*|anbindung\w*\s+(?:bleibt\s+)?offen|"
    r"bezug\w*\s+(?:bleibt\s+)?offen|verschiedene\w*\s+lesart\w*|"
    r"bleibt\s+(?:jedoch\s+)?offen\s*,?\s+(?:ob|welche\w*|wie)|"
    r"kann\b[^.!?\n]{0,100}\b(?:oder|sowohl)\b|"
    r"ambiguous\w*|possible\w*\s+reading\w*|"
    r"(?:attachment|reference)\w*\s+(?:remains?\s+)?open|"
    r"can\b[^.!?\n]{0,100}\b(?:or|both)\b)\b",
    re.IGNORECASE,
)
_KWIC_COMMUNICATIVE_PATTERN = re.compile(
    r"\b(?:vorwurf\w*|kritik\w*|kritisier\w*|beschuldig\w*|"
    r"bewertung\w*|wertend\w*|warnung\w*|frage\w*|aufforder\w*|"
    r"zurückweis\w*|zurueckweis\w*|accus\w*|critic\w*|evaluat\w*|"
    r"warning\w*|question\w*|request\w*|rejection\w*)\b",
    re.IGNORECASE,
)
_KWIC_CONTEXT_BOUND_PATTERN = re.compile(
    r"\b(?:satz\w*|text\w*|beleg\w*|kontext\w*|aussage\w*|"
    r"äußerung\w*|aeusserung\w*|passage\w*|excerpt\w*|utterance\w*|"
    r"beitrag\w*|tweet\w*|kommentar\w*|ausschnitt\w*|treffer\w*|"
    r"wortlaut\w*|wortwahl\w*|formulierung\w*|ausdruck\w*|begriff\w*|"
    r"bezeichnung\w*|referent\w*|quelle\w*|auswahl\w*|"
    r"sentence\w*|context\w*|source\w*)\b",
    re.IGNORECASE,
)


def _retrieval_interpretation_is_source_bound(claim_text: str) -> bool:
    """Require corpus propositions to remain attributed to their source voice."""

    return _KWIC_CONTEXT_BOUND_PATTERN.search(str(claim_text or "")) is not None


def _is_lexical_reference_boundary_claim(text: str) -> bool:
    return any(
        _REFERENCE_BOUNDARY_PATTERN.search(sentence)
        and _LEXICAL_RATING_BOUNDARY_PATTERN.search(sentence)
        for sentence in re.split(r"(?<=[.!?])\s+", str(text or ""))
    )


def _ngram_fact_surface_terms(fact: Any) -> List[str]:
    terms: List[str] = []
    surfaces = [
        str(getattr(fact, "statement", "") or ""),
        *[
            str(value or "")
            for value in list(getattr(fact, "grounding_quotes", []) or [])
        ],
    ]
    for surface in surfaces:
        for pattern in (
            r"\bzeigt\s+['\"„](?P<term>[^'\"“]+)['\"“]\s+mit\b",
            r"\bngram\s*=\s*['\"]?(?P<term>[^;|\n'\"]+)",
        ):
            for match in re.finditer(pattern, surface, re.IGNORECASE):
                term = " ".join(match.group("term").split()).strip()
                if term and term not in terms:
                    terms.append(term)
    return terms


def _claim_mentions_linked_ngram_row(
    claim: Any,
    fact_index: dict[str, Any],
) -> bool:
    text = " ".join(
        str(getattr(claim, "text", "") or "").split()
    ).casefold()
    for fact_id in list(getattr(claim, "fact_ids", []) or []):
        fact = fact_index.get(str(fact_id))
        if fact is None or str(getattr(fact, "fact_kind", "")) != "ranked_row":
            continue
        if "interpretation_anchor" not in list(
            getattr(fact, "supports_claims", []) or []
        ):
            continue
        if any(term.casefold() in text for term in _ngram_fact_surface_terms(fact)):
            return True
    return False


def _claimed_linked_ngram_terms(
    claim: Any,
    fact_index: dict[str, Any],
) -> set[str]:
    text = " ".join(
        str(getattr(claim, "text", "") or "").split()
    ).casefold()
    return {
        term.casefold()
        for fact_id in list(getattr(claim, "fact_ids", []) or [])
        for fact in [fact_index.get(str(fact_id))]
        if fact is not None
        and str(getattr(fact, "fact_kind", "") or "") == "ranked_row"
        for term in _ngram_fact_surface_terms(fact)
        if term.casefold() in text
    }


def _ngram_claim_is_negative_only(
    claim: Any,
    fact_index: dict[str, Any],
) -> bool:
    text = " ".join(
        str(getattr(claim, "text", "") or "").split()
    ).casefold()
    for term in sorted(
        _claimed_linked_ngram_terms(claim, fact_index),
        key=len,
        reverse=True,
    ):
        text = text.replace(term, " ")
    return _NGRAM_NEGATIVE_ONLY_PATTERN.search(text) is not None


def _ngram_interpretation_repair_shape(
    claims: List[Any],
    observed_facts: List[Any],
) -> tuple[int, bool]:
    """Return missing distinct candidates and whether a validation plan is missing."""

    fact_index = {
        str(getattr(fact, "id", "") or ""): fact
        for fact in observed_facts
    }
    visible_terms = {
        term.casefold()
        for fact in observed_facts
        if str(getattr(fact, "fact_kind", "") or "") == "ranked_row"
        for term in _ngram_fact_surface_terms(fact)
    }
    required_candidates = min(3, len(visible_terms))
    interpretations = [
        claim
        for claim in claims
        if str(getattr(claim, "claim_kind", "") or "")
        == "interpretation"
    ]
    candidate_terms = {
        term
        for claim in interpretations
        if _is_bounded_ngram_candidate_claim(
            claim,
            fact_index,
            require_validation=False,
        )
        for term in _claimed_linked_ngram_terms(claim, fact_index)
    }
    has_plan = any(
        _is_bounded_ngram_validation_claim(claim, fact_index)
        for claim in interpretations
    )
    return max(0, required_candidates - len(candidate_terms)), not has_plan


def _is_bounded_ngram_candidate_claim(
    claim: Any,
    fact_index: dict[str, Any],
    *,
    require_validation: bool,
) -> bool:
    text = str(getattr(claim, "text", "") or "")
    linked_terms = _claimed_linked_ngram_terms(claim, fact_index)
    return bool(
        str(getattr(claim, "claim_kind", "") or "") == "interpretation"
        and _NGRAM_ROUTINE_CANDIDATE_PATTERN.search(text)
        and _NGRAM_EPISTEMIC_PATTERN.search(text)
        and not _ngram_claim_is_negative_only(claim, fact_index)
        and len(linked_terms) == 1
        and (
            not require_validation
            or _NGRAM_VALIDATION_PATTERN.search(text)
        )
        and _claim_mentions_linked_ngram_row(claim, fact_index)
    )


def _is_bounded_ngram_validation_claim(
    claim: Any,
    fact_index: dict[str, Any],
) -> bool:
    """Recognise an atomic, fact-bound plan for testing an n-gram hypothesis."""

    if not (
        str(getattr(claim, "claim_kind", "") or "") == "interpretation"
        and _NGRAM_VALIDATION_PATTERN.search(
            str(getattr(claim, "text", "") or "")
        )
    ):
        return False
    return any(
        str(fact_id) in fact_index
        and str(getattr(fact_index[str(fact_id)], "fact_kind", "") or "")
        == "ranked_row"
        and "interpretation_anchor"
        in list(
            getattr(
                fact_index[str(fact_id)],
                "supports_claims",
                [],
            )
            or []
        )
        for fact_id in list(getattr(claim, "fact_ids", []) or [])
    )


def _missing_requested_lexical_reference_boundary(
    contract: Any,
    question_text: str,
    claims: List[Any],
) -> bool:
    """Detect the explicit comparison boundary required by the user question."""

    if str(getattr(contract, "analysis_family", "") or "") != "lexical_diversity":
        return False
    question = " ".join(str(question_text or "").split())
    if _LEXICAL_REFERENCE_REQUEST_PATTERN.search(question) is None:
        return False
    return not any(
        _is_lexical_reference_boundary_claim(
            str(getattr(claim, "text", "") or "")
        )
        for claim in claims
    )


def _missing_requested_lexical_robustness_answer(
    contract: Any,
    question_text: str,
    claims: List[Any],
    observed_facts: List[Any],
) -> bool:
    if str(getattr(contract, "analysis_family", "") or "") != "lexical_diversity":
        return False
    if _LEXICAL_ROBUSTNESS_REQUEST_PATTERN.search(question_text or "") is None:
        return False
    answer = " ".join(
        str(getattr(claim, "text", "") or "")
        for claim in claims
    )
    has_robustness_answer = bool(
        re.search(r"\bttr\b", answer, re.IGNORECASE)
        and _LEXICAL_ROBUSTNESS_ANSWER_PATTERN.search(answer)
    )
    if not has_robustness_answer:
        return True
    source_surface = " ".join(
        [
            str(getattr(fact, "statement", "") or "")
            for fact in observed_facts
        ]
        + [
            str(quote or "")
            for fact in observed_facts
            for quote in list(getattr(fact, "grounding_quotes", []) or [])
        ]
    )
    sttr_windows = set(
        re.findall(r"\bsttr_window\s*=\s*(\d+)", source_surface, re.IGNORECASE)
    )
    mattr_windows = set(
        re.findall(r"\bmattr_window\s*=\s*(\d+)", source_surface, re.IGNORECASE)
    )
    unequal_windows = bool(
        len(sttr_windows) == 1
        and len(mattr_windows) == 1
        and sttr_windows != mattr_windows
    )
    return bool(
        unequal_windows
        and _UNEQUAL_WINDOW_BOUNDARY_PATTERN.search(answer) is None
    )


def _missing_requested_keyness_interpretation(
    contract: Any,
    claims: List[Any],
    observed_facts: List[Any],
    *,
    interpretation_is_substantive: Optional[Callable[..., bool]],
) -> bool:
    """Use the product completion rule to target a missing Keyness reading."""

    if not (
        str(getattr(contract, "analysis_family", "") or "")
        == "contrast_keyness"
        and str(getattr(contract, "deliverable_kind", "") or "")
        == "contrast_report"
        and interpretation_is_substantive is not None
    ):
        return False
    return not interpretation_is_substantive(claims, observed_facts)


def _missing_requested_ngram_interpretation(
    contract: Any,
    question_text: str,
    claims: List[Any],
    observed_facts: List[Any],
) -> bool:
    if str(getattr(contract, "analysis_family", "") or "") != "ngram_profile":
        return False
    if _NGRAM_INTERPRETATION_REQUEST_PATTERN.search(question_text or "") is None:
        return False
    missing_candidates, missing_plan = _ngram_interpretation_repair_shape(
        claims,
        observed_facts,
    )
    return bool(missing_candidates or missing_plan)


_MULTIROW_KWIC_ANALYSIS_REQUEST_PATTERN = re.compile(
    r"\b(?:stichprob\w*|sample\w*|zufalls\w*|random\w*|"
    r"reproduzier\w*)\b|"
    r"(?:\b\d+\s+(?:sichtbar\w*\s+)?(?:kwic[- ]?)?"
    r"(?:zeilen?|belege?|beispiele?|treffer)\b|"
    r"\bkwic\b[^.!?\n]{0,80}\b(?:auswahl|zeilen?|belege?|"
    r"beispiele?|treffer)\b)",
    re.IGNORECASE,
)


def _is_multirow_kwic_analysis_request(
    question_text: str,
    observed_facts: List[Any],
) -> bool:
    """Distinguish an interpreted KWIC sample from a single-hit lookup."""

    if _MULTIROW_KWIC_ANALYSIS_REQUEST_PATTERN.search(
        question_text or ""
    ) is None:
        return False
    return sum(
        str(getattr(fact, "fact_kind", "") or "") == "kwic_example"
        for fact in observed_facts
    ) >= 2


def _missing_requested_kwic_interpretation(
    contract: Any,
    claims: List[Any],
    observed_facts: List[Any],
    *,
    question_text: str = "",
    reading_is_substantive: Optional[Callable[..., bool]] = None,
) -> bool:
    if (
        str(getattr(contract, "analysis_family", "") or "") != "kwic_context"
        or str(getattr(contract, "deliverable_kind", "") or "")
        != "analysis_report"
    ):
        return False
    has_expanded_context = any(
        str(getattr(fact, "fact_kind", "") or "") == "kwic_example"
        and "erweiter" in str(
            getattr(fact, "statement", "") or ""
        ).casefold()
        and "kontext" in str(
            getattr(fact, "statement", "") or ""
        ).casefold()
        for fact in observed_facts
    )
    multirow_analysis = _is_multirow_kwic_analysis_request(
        question_text,
        observed_facts,
    )
    if not has_expanded_context and not multirow_analysis:
        return False
    if reading_is_substantive is not None:
        return not reading_is_substantive(
            claims,
            observed_facts,
            question_text=question_text,
        )
    fact_index = {
        str(getattr(fact, "id", "") or ""): fact
        for fact in observed_facts
    }
    return not any(
        _is_bounded_kwic_reading_claim(claim, fact_index)
        or (
            multirow_analysis
            and str(getattr(claim, "claim_kind", "") or "")
            == "interpretation"
            and str(getattr(claim, "assertion_level", "") or "qualified")
            in {"tentative", "qualified"}
            and len(
                {
                    str(fact_id)
                    for fact_id in list(getattr(claim, "fact_ids", []) or [])
                    if str(fact_id) in fact_index
                    and str(
                        getattr(fact_index[str(fact_id)], "fact_kind", "")
                        or ""
                    )
                    == "kwic_example"
                }
            )
            >= 2
        )
        for claim in claims
    )


def _is_bounded_kwic_reading_claim(
    claim: Any,
    fact_index: dict[str, Any],
) -> bool:
    """Recognise an explicitly tentative reading tied to expanded KWIC evidence."""

    if str(getattr(claim, "claim_kind", "") or "") != "interpretation":
        return False
    linked = [
        fact_index[str(fact_id)]
        for fact_id in list(getattr(claim, "fact_ids", []) or [])
        if str(fact_id) in fact_index
    ]
    has_expanded_context = any(
        str(getattr(fact, "fact_kind", "") or "") == "kwic_example"
        and "erweiter" in str(getattr(fact, "statement", "") or "").casefold()
        and "kontext" in str(getattr(fact, "statement", "") or "").casefold()
        for fact in linked
    )
    text = str(getattr(claim, "text", "") or "")
    return bool(
        has_expanded_context
        and _KWIC_LOCAL_READING_PATTERN.search(text)
        and _KWIC_EPISTEMIC_PATTERN.search(text)
        and _KWIC_AMBIGUITY_PATTERN.search(text)
    )


def _is_bounded_kwic_communicative_claim(
    claim: Any,
    fact_index: dict[str, Any],
) -> bool:
    """Recognise a passage-bound account of its communicative action."""

    if str(getattr(claim, "claim_kind", "") or "") != "interpretation":
        return False
    linked = [
        fact_index[str(fact_id)]
        for fact_id in list(getattr(claim, "fact_ids", []) or [])
        if str(fact_id) in fact_index
    ]
    has_expanded_context = any(
        str(getattr(fact, "fact_kind", "") or "") == "kwic_example"
        and "erweiter" in str(getattr(fact, "statement", "") or "").casefold()
        and "kontext" in str(getattr(fact, "statement", "") or "").casefold()
        for fact in linked
    )
    text = str(getattr(claim, "text", "") or "")
    return bool(
        has_expanded_context
        and _KWIC_COMMUNICATIVE_PATTERN.search(text)
        and _KWIC_CONTEXT_BOUND_PATTERN.search(text)
    )


def _runtime_authoritative_bounded_ngram_claim_ids(
    contract: Any,
    envelope: Any,
    observed_facts: List[Any],
    runtime_accepted_ids: set[str],
    *,
    interpretation_is_substantive: Optional[Callable[..., bool]] = None,
) -> List[str]:
    """Keep a narrowly bounded routine hypothesis from being underclaimed."""

    if not (
        str(getattr(contract, "analysis_family", "") or "") == "ngram_profile"
        and str(getattr(contract, "deliverable_kind", "") or "")
        == "analysis_report"
    ):
        return []
    runtime_claims = [
        claim
        for claim in list(getattr(envelope, "claims", []) or [])
        if str(getattr(claim, "id", "") or "").strip()
        in runtime_accepted_ids
    ]
    if interpretation_is_substantive is not None and not (
        interpretation_is_substantive(runtime_claims, observed_facts)
    ):
        return []
    fact_index = {
        str(getattr(fact, "id", "") or ""): fact
        for fact in observed_facts
    }
    return [
        claim_id
        for claim in list(getattr(envelope, "claims", []) or [])
        for claim_id in [str(getattr(claim, "id", "") or "").strip()]
        if claim_id in runtime_accepted_ids
        and str(getattr(claim, "assertion_level", "") or "qualified")
        in {"tentative", "qualified"}
        and (
            _is_bounded_ngram_candidate_claim(
                claim,
                fact_index,
                # Completion may be distributed over multiple atomic claims:
                # one names the candidate, another explains the test.
                require_validation=interpretation_is_substantive is None,
            )
            or (
                interpretation_is_substantive is not None
                and _is_bounded_ngram_validation_claim(
                    claim,
                    fact_index,
                )
            )
        )
    ]


def _runtime_authoritative_bounded_keyness_claim_ids(
    contract: Any,
    envelope: Any,
    observed_facts: List[Any],
    runtime_accepted_ids: set[str],
    *,
    interpretation_is_substantive: Optional[Callable[..., bool]],
) -> List[str]:
    """Keep a deterministically safe, bounded Keyness interpretation."""

    if not (
        str(getattr(contract, "analysis_family", "") or "")
        == "contrast_keyness"
        and str(getattr(contract, "deliverable_kind", "") or "")
        == "contrast_report"
        and interpretation_is_substantive is not None
    ):
        return []
    runtime_claims = [
        claim
        for claim in list(getattr(envelope, "claims", []) or [])
        if str(getattr(claim, "id", "") or "").strip()
        in runtime_accepted_ids
    ]
    return [
        claim_id
        for claim in runtime_claims
        for claim_id in [str(getattr(claim, "id", "") or "").strip()]
        if claim_id
        and str(getattr(claim, "claim_kind", "") or "")
        == "interpretation"
        and str(getattr(claim, "assertion_level", "") or "qualified")
        in {"tentative", "qualified"}
        and interpretation_is_substantive([claim], observed_facts)
    ]


def _runtime_authoritative_bounded_kwic_claim_ids(
    contract: Any,
    envelope: Any,
    observed_facts: List[Any],
    runtime_accepted_ids: set[str],
    *,
    reading_is_substantive: Optional[Callable[..., bool]] = None,
    question_text: str = "",
) -> List[str]:
    """Prevent a semantic verifier from suppressing a calibrated local reading."""

    if not (
        str(getattr(contract, "analysis_family", "") or "") == "kwic_context"
        and str(getattr(contract, "deliverable_kind", "") or "")
        == "analysis_report"
    ):
        return []
    runtime_claims = [
        claim
        for claim in list(getattr(envelope, "claims", []) or [])
        if str(getattr(claim, "id", "") or "").strip()
        in runtime_accepted_ids
    ]
    if reading_is_substantive is not None and not reading_is_substantive(
        runtime_claims,
        observed_facts,
        question_text=question_text,
    ):
        return []
    fact_index = {
        str(getattr(fact, "id", "") or ""): fact
        for fact in observed_facts
    }
    return [
        claim_id
        for claim in runtime_claims
        for claim_id in [str(getattr(claim, "id", "") or "").strip()]
        if str(getattr(claim, "assertion_level", "") or "qualified")
        in {"tentative", "qualified"}
        # Evaluate the shared substantive-reading predicate per claim. An
        # envelope-wide pass must not let one safe claim auto-promote a second
        # arbitrary participant or referent claim.
        and (
            (
                reading_is_substantive is not None
                and reading_is_substantive(
                    [claim],
                    observed_facts,
                    question_text=question_text,
                )
            )
            or (
                reading_is_substantive is None
                and (
                    _is_bounded_kwic_reading_claim(claim, fact_index)
                    or _is_bounded_kwic_communicative_claim(
                        claim,
                        fact_index,
                    )
                )
            )
        )
    ]


def _runtime_authoritative_direct_kwic_observation_ids(
    contract: Any,
    envelope: Any,
    observed_facts: List[Any],
    runtime_accepted_ids: set[str],
) -> List[str]:
    """Keep a literal KWIC attestation from being mistaken for a generalisation.

    A visible concordance row proves the existential claim that a sequence is
    attested. The deterministic validator still owns the factual check; this
    override only prevents the semantic verifier from demanding corpus-wide
    coverage for that narrower observation.
    """

    if not (
        str(getattr(contract, "analysis_family", "") or "") == "kwic_context"
        and str(getattr(contract, "deliverable_kind", "") or "")
        == "analysis_report"
    ):
        return []
    fact_index = {
        str(getattr(fact, "id", "") or ""): fact
        for fact in observed_facts
    }
    accepted: List[str] = []
    for claim in list(getattr(envelope, "claims", []) or []):
        claim_id = str(getattr(claim, "id", "") or "").strip()
        if not (
            claim_id in runtime_accepted_ids
            and str(getattr(claim, "claim_kind", "") or "") == "observation"
            and str(getattr(claim, "assertion_level", "") or "") == "exact"
            and _DIRECT_ATTESTATION_PATTERN.search(
                str(getattr(claim, "text", "") or "")
            )
        ):
            continue
        linked_facts = [
            fact_index[str(fact_id)]
            for fact_id in list(getattr(claim, "fact_ids", []) or [])
            if str(fact_id) in fact_index
        ]
        if any(
            str(getattr(fact, "fact_kind", "") or "") == "kwic_example"
            for fact in linked_facts
        ):
            accepted.append(claim_id)
    return accepted


def _runtime_authoritative_assessed_retrieval_claim_ids(
    envelope: Any,
    runtime_accepted_ids: set[str],
    assessments: List[dict[str, str]],
) -> List[str]:
    """Preserve safe candidate observations and genuinely balanced readings."""

    assessment_by_fact = {
        str(item.get("fact_id", "") or "").strip(): item
        for item in assessments
        if str(item.get("fact_id", "") or "").strip()
    }
    if not assessment_by_fact:
        return []
    result: List[str] = []
    for claim in list(getattr(envelope, "claims", []) or []):
        claim_id = str(getattr(claim, "id", "") or "").strip()
        linked_ids = {
            str(fact_id)
            for fact_id in list(getattr(claim, "fact_ids", []) or [])
            if str(fact_id) in assessment_by_fact
        }
        if not (
            claim_id in runtime_accepted_ids
            and linked_ids
            and linked_ids
            == {
                str(fact_id)
                for fact_id in list(
                    getattr(claim, "fact_ids", []) or []
                )
                if str(fact_id)
            }
        ):
            continue
        linked_assessments = [
            assessment_by_fact[fact_id] for fact_id in linked_ids
        ]
        claim_kind = str(getattr(claim, "claim_kind", "") or "")
        if claim_kind == "observation":
            relations = {
                str(
                    item.get("relation_to_requested_conclusion", "") or ""
                )
                for item in linked_assessments
            }
            claim_text = str(getattr(claim, "text", "") or "")
            has_positive_reading = bool(
                _RETRIEVAL_POSITIVE_READING_PATTERN.search(claim_text)
            )
            has_negative_reading = bool(
                _RETRIEVAL_NEGATIVE_READING_PATTERN.search(claim_text)
            )
            if (
                "mixed_or_unclear" in relations
                and (has_positive_reading or has_negative_reading)
            ) or (
                relations == {"supports"}
                and has_positive_reading
                and not has_negative_reading
            ) or (
                relations == {"counterevidence"}
                and has_negative_reading
                and not has_positive_reading
            ):
                continue
            result.append(claim_id)
            continue
        if claim_kind != "interpretation":
            continue
        has_support = any(
            item.get("relation_to_requested_conclusion")
            in {"supports", "related_support"}
            for item in linked_assessments
        )
        has_relevant_non_support = any(
            item.get("topic_relation") in {"relevant", "marginal"}
            and item.get("relation_to_requested_conclusion")
            in {"counterevidence", "mixed_or_unclear"}
            for item in linked_assessments
        )
        text = str(getattr(claim, "text", "") or "")
        if has_support and has_relevant_non_support and (
            _RETRIEVAL_BALANCED_READING_PATTERN.search(text)
            or _EPISTEMIC_LIMITATION_PATTERN.search(text)
        ):
            result.append(claim_id)
    return result


def _retrieval_polarity_violation_claim_ids(
    envelope: Any,
    assessments: List[dict[str, str]],
    *,
    asserted_property: str,
) -> List[str]:
    """Reject polarity that the independent candidate audit did not observe."""

    property_is_negative = bool(
        _RETRIEVAL_NEGATIVE_READING_PATTERN.search(asserted_property or "")
    )
    property_is_positive = bool(
        _RETRIEVAL_AFFIRMATIVE_POSITIVE_PATTERN.search(
            asserted_property or ""
        )
    )
    if property_is_negative == property_is_positive:
        return []
    assessment_by_fact = {
        str(item.get("fact_id", "") or "").strip(): item
        for item in assessments
        if str(item.get("fact_id", "") or "").strip()
    }
    violations: List[str] = []
    for claim in list(getattr(envelope, "claims", []) or []):
        if str(getattr(claim, "claim_kind", "") or "") not in {
            "observation",
            "interpretation",
        }:
            continue
        linked = [
            assessment_by_fact[str(fact_id)]
            for fact_id in list(getattr(claim, "fact_ids", []) or [])
            if str(fact_id) in assessment_by_fact
        ]
        if not linked:
            continue
        relations = {
            str(item.get("relation_to_requested_conclusion", "") or "")
            for item in linked
        }
        text = str(getattr(claim, "text", "") or "")
        explicitly_unclear_between_polarities = bool(
            "mixed_or_unclear" in relations
            and _EXPLICIT_POLARITY_UNCERTAINTY_PATTERN.search(text)
            and _RETRIEVAL_AFFIRMATIVE_POSITIVE_PATTERN.search(text)
            and _RETRIEVAL_NEGATIVE_READING_PATTERN.search(text)
        )
        if explicitly_unclear_between_polarities:
            continue
        sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
        positive_asserted = any(
            _RETRIEVAL_AFFIRMATIVE_POSITIVE_PATTERN.search(sentence)
            and not _NEGATED_POSITIVE_READING_PATTERN.search(sentence)
            for sentence in sentences
        )
        negative_asserted = any(
            _RETRIEVAL_NEGATIVE_READING_PATTERN.search(sentence)
            and not _NEGATED_NEGATIVE_READING_PATTERN.search(sentence)
            for sentence in sentences
        )
        supports_property = bool(
            relations.intersection({"supports", "related_support"})
        )
        supports_opposite = "counterevidence" in relations
        explicit_opposite = any(
            str(item.get("relation_to_requested_conclusion", "") or "")
            == "counterevidence"
            and (
                (
                    property_is_negative
                    and _RETRIEVAL_AFFIRMATIVE_POSITIVE_PATTERN.search(
                        str(item.get("reason", "") or "")
                    )
                    and not _NEGATED_POSITIVE_READING_PATTERN.search(
                        str(item.get("reason", "") or "")
                    )
                    and not _AMBIGUOUS_POLARITY_PATTERN.search(
                        str(item.get("reason", "") or "")
                    )
                )
                or (
                    property_is_positive
                    and _RETRIEVAL_NEGATIVE_READING_PATTERN.search(
                        str(item.get("reason", "") or "")
                    )
                    and not _NEGATED_NEGATIVE_READING_PATTERN.search(
                        str(item.get("reason", "") or "")
                    )
                    and not _AMBIGUOUS_POLARITY_PATTERN.search(
                        str(item.get("reason", "") or "")
                    )
                )
            )
            for item in linked
        )
        if (
            property_is_negative
            and (
                (
                    positive_asserted
                    and (not supports_opposite or not explicit_opposite)
                )
                or (negative_asserted and not supports_property)
            )
        ) or (
            property_is_positive
            and (
                (
                    negative_asserted
                    and (not supports_opposite or not explicit_opposite)
                )
                or (positive_asserted and not supports_property)
            )
        ):
            claim_id = str(getattr(claim, "id", "") or "").strip()
            if claim_id:
                violations.append(claim_id)
    return _dedupe_ordered_strs(violations)


def _local_relation_semantic_reconsideration_ids(
    contract: Any,
    envelope: Any,
    runtime_accepted_ids: set[str],
    semantic_nonaccepted_ids: set[str],
    assessments: List[dict[str, str]],
    scope_violation_ids: set[str],
) -> List[str]:
    """Route narrowly local readings to the independent relation audit.

    Under confirmation pressure, some models judge every claim against the
    user's universal hypothesis and reject a faithful passage-level reading
    merely because it cannot establish that stronger proposition. This helper
    does not accept such a reading. It only makes a runtime-valid, explicitly
    local interpretation eligible for the separate source-relation check.
    """

    forbidden = {
        str(value or "").strip().casefold()
        for value in list(getattr(contract, "forbidden_claims", []) or [])
    }
    if "one-sided confirmation of a universal corpus claim" not in forbidden:
        return []
    assessment_by_fact = {
        str(item.get("fact_id", "") or "").strip(): item
        for item in assessments
        if str(item.get("fact_id", "") or "").strip()
    }
    if not assessment_by_fact:
        return []

    eligible: List[str] = []
    for claim in list(getattr(envelope, "claims", []) or []):
        claim_id = str(getattr(claim, "id", "") or "").strip()
        text = str(getattr(claim, "text", "") or "").strip()
        cited_fact_ids = {
            str(fact_id).strip()
            for fact_id in list(getattr(claim, "fact_ids", []) or [])
            if str(fact_id).strip()
        }
        has_explicit_valence = bool(
            _RETRIEVAL_NEGATIVE_READING_PATTERN.search(text)
            or _RETRIEVAL_AFFIRMATIVE_POSITIVE_PATTERN.search(text)
        )
        locally_scoped = bool(
            _LOCAL_RETRIEVAL_SCOPE_PATTERN.search(text)
            or (
                len(cited_fact_ids) == 1
                and (
                    not has_explicit_valence
                    or _METALINGUISTIC_SOURCE_NOUN_PATTERN.search(text)
                )
            )
        )
        if not (
            claim_id in runtime_accepted_ids
            and claim_id in semantic_nonaccepted_ids
            and claim_id not in scope_violation_ids
            and str(getattr(claim, "claim_kind", "") or "")
            == "interpretation"
            and str(getattr(claim, "assertion_level", "") or "")
            in {"qualified", "tentative"}
            and cited_fact_ids
            and cited_fact_ids.issubset(assessment_by_fact)
            # A single-fact structured interpretation is already bounded by
            # its sole evidence pointer when it either avoids an explicit
            # valence or discusses a source expression metalinguistically.
            # Route it to the relation audit even if a small model omitted the
            # presentational words "diese Passage"; do not accept it here.
            and locally_scoped
            and not _HYPOTHESIS_QUANTIFIER_PATTERN.search(text)
            and not _has_unbounded_retrieval_assertion(text)
        ):
            continue
        if any(
            str(
                assessment_by_fact[fact_id].get(
                    "relation_to_requested_conclusion",
                    "",
                )
                or ""
            )
            in {
                "supports",
                "related_support",
                "counterevidence",
                "mixed_or_unclear",
            }
            for fact_id in cited_fact_ids
        ):
            eligible.append(claim_id)
    return _dedupe_ordered_strs(eligible)


def _related_scope_relation_reconsideration_ids(
    contract: Any,
    envelope: Any,
    runtime_rejected_ids: set[str],
    assessments: List[dict[str, str]],
    scope_violation_ids: set[str],
    *,
    target_topic: str,
) -> List[str]:
    """Let the source-relation audit decide narrowly local bearer readings."""

    forbidden = {
        str(value or "").strip().casefold()
        for value in list(getattr(contract, "forbidden_claims", []) or [])
    }
    if "one-sided confirmation of a universal corpus claim" not in forbidden:
        return []
    assessment_by_fact = {
        str(item.get("fact_id", "") or "").strip(): item
        for item in assessments
        if str(item.get("fact_id", "") or "").strip()
    }
    target_tokens = re.findall(
        r"\w+",
        str(target_topic or "").casefold(),
        re.UNICODE,
    )
    target_pattern = (
        r"\b" + r"\s+".join(re.escape(token) for token in target_tokens) + r"\b"
        if target_tokens
        else r"(?!)"
    )
    direct_target_evaluation = re.compile(
        rf"\b(?:negativ\w*|positiv\w*|abwert\w*|stigmatis\w*|"
        rf"feindselig\w*)\s+(?:darstellung|rahmung|bewertung)\s+"
        rf"(?:von|der|des)\s+{target_pattern}|"
        rf"{target_pattern}\s+(?:wird|werde|ist|sei|erscheint|gilt)"
        rf"[^.!?\n]{{0,90}}\b(?:negativ\w*|positiv\w*|abwert\w*|"
        rf"stigmatis\w*|feindselig\w*)\b",
        re.IGNORECASE,
    )
    eligible: List[str] = []
    for claim in list(getattr(envelope, "claims", []) or []):
        claim_id = str(getattr(claim, "id", "") or "").strip()
        text = str(getattr(claim, "text", "") or "").strip()
        cited_fact_ids = {
            str(fact_id).strip()
            for fact_id in list(getattr(claim, "fact_ids", []) or [])
            if str(fact_id).strip()
        }
        if not (
            claim_id in runtime_rejected_ids
            and claim_id in scope_violation_ids
            and str(getattr(claim, "claim_kind", "") or "")
            == "interpretation"
            and str(getattr(claim, "assertion_level", "") or "")
            in {"qualified", "tentative"}
            and cited_fact_ids
            and cited_fact_ids.issubset(assessment_by_fact)
            and _LOCAL_RETRIEVAL_SCOPE_PATTERN.search(text)
            and _RELATED_BEARER_NOUN_PATTERN.search(text)
            and direct_target_evaluation.search(text) is None
            and not _HYPOTHESIS_QUANTIFIER_PATTERN.search(text)
            and not _has_unbounded_retrieval_assertion(text)
        ):
            continue
        if any(
            assessment_by_fact[fact_id].get(
                "relation_to_requested_conclusion"
            )
            == "related_support"
            for fact_id in cited_fact_ids
        ):
            eligible.append(claim_id)
    return _dedupe_ordered_strs(eligible)


def _related_evidence_scope_violation_claim_ids(
    envelope: Any,
    assessments: List[dict[str, str]],
    *,
    target_topic: str,
    asserted_property: str,
) -> List[str]:
    """Reject target-level attribution backed only by related-object evidence."""

    assessment_by_fact = {
        str(item.get("fact_id", "") or "").strip(): item
        for item in assessments
        if str(item.get("fact_id", "") or "").strip()
    }
    target_tokens = re.findall(
        r"\w+",
        str(target_topic or "").casefold(),
        re.UNICODE,
    )
    if not assessment_by_fact or not target_tokens:
        return []
    target_pattern = re.compile(
        r"\b" + r"\s+".join(re.escape(token) for token in target_tokens) + r"\b",
        re.IGNORECASE,
    )
    property_is_negative = bool(
        _RETRIEVAL_NEGATIVE_READING_PATTERN.search(asserted_property)
    )
    property_is_positive = bool(
        _RETRIEVAL_POSITIVE_READING_PATTERN.search(asserted_property)
    )
    if not property_is_negative and not property_is_positive:
        return []

    violations: List[str] = []
    for claim in list(getattr(envelope, "claims", []) or []):
        claim_id = str(getattr(claim, "id", "") or "").strip()
        linked = [
            assessment_by_fact[str(fact_id)]
            for fact_id in list(getattr(claim, "fact_ids", []) or [])
            if str(fact_id) in assessment_by_fact
        ]
        if not linked:
            continue
        if any(
            item.get("evaluated_object_type") == "target_topic"
            and item.get("relation_to_requested_conclusion")
            in {"supports", "counterevidence"}
            for item in linked
        ):
            continue
        if not any(
            item.get("evaluated_object_type") != "target_topic"
            and item.get("relation_to_requested_conclusion")
            in {"related_support", "counterevidence", "mixed_or_unclear"}
            for item in linked
        ):
            continue
        text = str(getattr(claim, "text", "") or "")
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            target_matches = list(target_pattern.finditer(sentence))
            if not target_matches:
                continue
            target_is_only_context_modifier = bool(
                _RELATED_BEARER_NOUN_PATTERN.search(sentence)
                and all(
                    _TARGET_AS_CONTEXT_MODIFIER_PATTERN.search(
                        sentence[max(0, match.start() - 45) : match.start()]
                    )
                    for match in target_matches
                )
            )
            target_evaluation_visible = bool(
                _RETRIEVAL_NEGATIVE_READING_PATTERN.search(sentence)
                or _RETRIEVAL_AFFIRMATIVE_POSITIVE_PATTERN.search(sentence)
                or _TARGET_EVALUATIVE_PREDICATE_PATTERN.search(sentence)
            )
            if (
                target_evaluation_visible
                and not _EPISTEMIC_LIMITATION_PATTERN.search(sentence)
                and not target_is_only_context_modifier
            ):
                violations.append(claim_id)
                break
    return _dedupe_ordered_strs(violations)


_RETRIEVAL_REPORT_RELATIONS = {
    "supports",
    "related_support",
    "counterevidence",
    "mixed_or_unclear",
}


def _retrieval_reporting_stratum(
    assessment: dict[str, Any],
) -> tuple[str, str] | None:
    """Return the direction/object cell that a final report must represent."""

    topic_relation = str(
        assessment.get("topic_relation", "") or ""
    ).strip()
    relation = str(
        assessment.get("relation_to_requested_conclusion", "") or ""
    ).strip()
    if (
        topic_relation not in {"relevant", "marginal"}
        and relation not in _RETRIEVAL_REPORT_RELATIONS
    ):
        return None
    if relation not in _RETRIEVAL_REPORT_RELATIONS:
        relation = "mixed_or_unclear"
    object_type = str(
        assessment.get("evaluated_object_type", "") or ""
    ).strip()
    if not object_type:
        # Without an audited object type, two passages are not proven to
        # occupy the same analytical cell and therefore cannot stand in for
        # one another in the visible report.
        fact_id = str(assessment.get("fact_id", "") or "").strip()
        object_type = f"unspecified_object:{fact_id}"
    return relation, object_type


def _mixed_retrieval_reporting_is_optional(
    assessments: List[dict[str, Any]],
) -> bool:
    """Keep ambiguity audited but optional once both clear directions are visible."""

    relations = {
        str(assessment.get("relation_to_requested_conclusion", "") or "")
        for assessment in assessments
        if str(assessment.get("topic_relation", "") or "")
        in {"relevant", "marginal"}
    }
    return bool(relations.intersection({"supports", "related_support"})) and (
        "counterevidence" in relations
    )


def _representative_retrieval_fact_ids(
    assessments: List[dict[str, Any]],
    fact_payloads: List[dict[str, Any]],
) -> List[str]:
    """Offer up to two rich passages per stratum for non-mechanical synthesis."""

    payload_by_id = {
        str(payload.get("id", "") or ""): payload
        for payload in fact_payloads
        if str(payload.get("id", "") or "")
    }
    mixed_is_optional = _mixed_retrieval_reporting_is_optional(assessments)
    clear_object_types = {
        stratum[1]
        for assessment in assessments
        for stratum in [_retrieval_reporting_stratum(assessment)]
        if stratum is not None and stratum[0] != "mixed_or_unclear"
    }
    grouped: dict[
        tuple[str, str],
        List[tuple[int, str, dict[str, Any]]],
    ] = {}
    for position, assessment in enumerate(assessments):
        fact_id = str(assessment.get("fact_id", "") or "").strip()
        stratum = _retrieval_reporting_stratum(assessment)
        if not fact_id or stratum is None or fact_id not in payload_by_id:
            continue
        if (
            mixed_is_optional
            and stratum[0] == "mixed_or_unclear"
            and stratum[1] in clear_object_types
        ):
            continue
        grouped.setdefault(stratum, []).append(
            (position, fact_id, assessment)
        )

    selected: List[tuple[int, str]] = []
    for candidates in grouped.values():

        def evidence_score(
            candidate: tuple[int, str, dict[str, Any]],
        ) -> tuple[int, int, int, int]:
            position, fact_id, assessment = candidate
            source = _candidate_source_quote(payload_by_id[fact_id])
            token_count = len(re.findall(r"\w+", source, re.UNICODE))
            evaluative_phrases = len(
                list(
                    assessment.get(
                        "verbatim_evaluative_source_phrases",
                        [],
                    )
                    or []
                )
            )
            sentence_count = len(
                _candidate_source_sentences(payload_by_id[fact_id])
            )
            return (
                int(evaluative_phrases > 0),
                min(token_count, 120),
                min(sentence_count, 4),
                -position,
            )

        for position, fact_id, _assessment in sorted(
            candidates,
            key=evidence_score,
            reverse=True,
        )[:2]:
            selected.append((position, fact_id))
    return [fact_id for _position, fact_id in sorted(selected)]


def _repair_direct_negative_result_claim_kinds(
    envelope: Any,
    observed_facts: List[Any],
) -> List[str]:
    """Treat a literal exact absence as observation, not interpretation."""

    fact_index = {
        str(getattr(fact, "id", "") or "").strip(): fact
        for fact in observed_facts
        if str(getattr(fact, "id", "") or "").strip()
    }
    repaired: List[str] = []
    for claim in list(getattr(envelope, "claims", []) or []):
        if str(getattr(claim, "claim_kind", "") or "") != "interpretation":
            continue
        linked_facts = [
            fact_index[fact_id]
            for fact_id in list(getattr(claim, "fact_ids", []) or [])
            if fact_id in fact_index
        ]
        text = str(getattr(claim, "text", "") or "")
        if not (
            linked_facts
            and all(
                str(getattr(fact, "fact_kind", "") or "")
                == "negative_result"
                and str(getattr(fact, "exactness", "") or "") == "exact"
                for fact in linked_facts
            )
            and _DIRECT_NEGATIVE_RESULT_PATTERN.search(text)
            and _METHOD_CONSEQUENCE_PATTERN.search(text) is None
        ):
            continue
        claim.claim_kind = "observation"
        claim_id = str(getattr(claim, "id", "") or "").strip()
        if claim_id:
            repaired.append(claim_id)
    return repaired


def _widerlegte_absagen(
    envelope: Any,
    observed_facts: List[Any],
) -> List[str]:
    """Return IDs of absence claims contradicted by their cited facts.

    A direct absence statement is contradicted when its fact_ids point to
    positive content rather than negative_result facts. Absence claims without
    such evidence remain unchanged. ``CANDYCONC_ABSAGEN_DURCHSETZUNG`` controls
    whether this check is applied and defaults to disabled.
    """
    import os

    if os.environ.get(
        "CANDYCONC_ABSAGEN_DURCHSETZUNG", "0"
    ).strip().lower() not in ("1", "true", "ja", "an"):
        return []
    fact_index = {
        str(getattr(fact, "id", "") or "").strip(): fact
        for fact in observed_facts
        if str(getattr(fact, "id", "") or "").strip()
    }
    widerlegt: List[str] = []
    for claim in list(getattr(envelope, "claims", []) or []):
        text = str(getattr(claim, "text", "") or "")
        if not _DIRECT_NEGATIVE_RESULT_PATTERN.search(text):
            continue
        linked_facts = [
            fact_index[fact_id]
            for fact_id in list(getattr(claim, "fact_ids", []) or [])
            if fact_id in fact_index
        ]
        if not linked_facts:
            continue
        tragende = [
            fact
            for fact in linked_facts
            if str(getattr(fact, "fact_kind", "") or "") != "negative_result"
            and str(getattr(fact, "statement", "") or "").strip()
            and not _DIRECT_NEGATIVE_RESULT_PATTERN.search(
                str(getattr(fact, "statement", "") or "")
            )
        ]
        if not tragende:
            continue
        claim_id = str(getattr(claim, "id", "") or "").strip()
        if claim_id:
            widerlegt.append(claim_id)
    return widerlegt


def _repair_epistemic_limitation_claim_kinds(
    envelope: Any,
    observed_facts: List[Any],
) -> List[str]:
    """Repair a scope boundary mislabeled as an empirical interpretation."""

    fact_index = {
        str(getattr(fact, "id", "") or "").strip(): fact
        for fact in observed_facts
        if str(getattr(fact, "id", "") or "").strip()
    }
    repaired: List[str] = []
    for claim in list(getattr(envelope, "claims", []) or []):
        if str(getattr(claim, "claim_kind", "") or "") != "interpretation":
            continue
        linked_facts = [
            fact_index[fact_id]
            for fact_id in list(getattr(claim, "fact_ids", []) or [])
            if fact_id in fact_index
        ]
        if not (
            linked_facts
            and any(
                str(getattr(fact, "fact_kind", "") or "") == "limitation"
                for fact in linked_facts
            )
            and _EPISTEMIC_LIMITATION_PATTERN.search(
                str(getattr(claim, "text", "") or "")
            )
            and _EPISTEMIC_POSITIVE_TAIL_PATTERN.search(
                str(getattr(claim, "text", "") or "")
            )
            is None
        ):
            continue
        claim.claim_kind = "limitation"
        claim_id = str(getattr(claim, "id", "") or "").strip()
        if claim_id:
            repaired.append(claim_id)
    return repaired


def _runtime_authoritative_epistemic_limitation_claim_ids(
    contract: Any,
    envelope: Any,
    observed_facts: List[Any],
    runtime_accepted_ids: set[str],
) -> List[str]:
    """Keep a runtime-proven boundary the question explicitly requires."""

    forbidden = {
        str(value or "").strip().casefold()
        for value in list(getattr(contract, "forbidden_claims", []) or [])
    }
    confirmation_boundary_requested = (
        "one-sided confirmation of a universal corpus claim" in forbidden
    )
    lexical_reference_boundary_requested = bool(
        str(getattr(contract, "analysis_family", "") or "")
        == "lexical_diversity"
        and _LEXICAL_REFERENCE_REQUEST_PATTERN.search(
            str(getattr(contract, "question_scope", "") or "")
        )
    )
    if not (
        confirmation_boundary_requested
        or lexical_reference_boundary_requested
    ):
        return []
    fact_index = {
        str(getattr(fact, "id", "") or "").strip(): fact
        for fact in observed_facts
        if str(getattr(fact, "id", "") or "").strip()
    }
    result: List[str] = []
    for claim in list(getattr(envelope, "claims", []) or []):
        claim_id = str(getattr(claim, "id", "") or "").strip()
        claim_text = str(getattr(claim, "text", "") or "")
        lexical_reference_boundary = bool(
            lexical_reference_boundary_requested
            and _is_lexical_reference_boundary_claim(claim_text)
        )
        if not (
            claim_id in runtime_accepted_ids
            and str(getattr(claim, "claim_kind", "") or "") == "limitation"
            and (
                _EPISTEMIC_LIMITATION_PATTERN.search(claim_text)
                or lexical_reference_boundary
            )
            and _EPISTEMIC_POSITIVE_TAIL_PATTERN.search(claim_text) is None
        ):
            continue
        linked_facts = [
            fact_index[fact_id]
            for fact_id in list(getattr(claim, "fact_ids", []) or [])
            if fact_id in fact_index
        ]
        has_grounded_limitation = any(
            str(getattr(fact, "fact_kind", "") or "") == "limitation"
            for fact in linked_facts
        )
        if has_grounded_limitation or lexical_reference_boundary:
            result.append(claim_id)
    return result


def _repair_direct_attestation_claim_kinds(
    envelope: Any,
    observed_facts: List[Any],
) -> List[str]:
    """Render a directly attested occurrence as an observation.

    Local models occasionally label an exact presence statement as a follow-up
    or interpretation. Reclassifying only a literal attestation tied to a
    visible KWIC example fixes the user-visible section without licensing any
    interpretation; normal runtime validation still decides whether the cited
    row actually supports the statement.
    """

    fact_index = {
        str(getattr(fact, "id", "") or "").strip(): fact
        for fact in observed_facts
        if str(getattr(fact, "id", "") or "").strip()
    }
    repaired: List[str] = []
    for claim in list(getattr(envelope, "claims", []) or []):
        if str(getattr(claim, "claim_kind", "") or "") not in {
            "followup",
            "interpretation",
        }:
            continue
        if str(getattr(claim, "assertion_level", "") or "") != "exact":
            continue
        linked_facts = [
            fact_index[fact_id]
            for fact_id in list(getattr(claim, "fact_ids", []) or [])
            if fact_id in fact_index
        ]
        if not (
            any(
                str(getattr(fact, "fact_kind", "") or "")
                == "kwic_example"
                for fact in linked_facts
            )
            and _DIRECT_ATTESTATION_PATTERN.search(
                str(getattr(claim, "text", "") or "")
            )
        ):
            continue
        claim.claim_kind = "observation"
        claim_id = str(getattr(claim, "id", "") or "").strip()
        if claim_id:
            repaired.append(claim_id)
    return repaired


def _repair_direct_word_sketch_claim_kinds(
    contract: Any,
    envelope: Any,
    observed_facts: List[Any],
    *,
    interpretation_is_substantive: Optional[Callable[..., bool]] = None,
) -> List[str]:
    """Reclassify literal sketch-row reporting as observation."""

    if str(getattr(contract, "analysis_family", "") or "") != (
        "word_sketch_profile"
    ):
        return []
    fact_index = {
        str(getattr(fact, "id", "") or "").strip(): fact
        for fact in observed_facts
        if str(getattr(fact, "id", "") or "").strip()
    }
    repaired: List[str] = []
    for claim in list(getattr(envelope, "claims", []) or []):
        if not (
            str(getattr(claim, "claim_kind", "") or "")
            == "interpretation"
            and str(getattr(claim, "assertion_level", "") or "")
            == "exact"
        ):
            continue
        linked_facts = [
            fact_index[fact_id]
            for fact_id in list(getattr(claim, "fact_ids", []) or [])
            if fact_id in fact_index
        ]
        text = str(getattr(claim, "text", "") or "")
        if not (
            linked_facts
            and all(
                str(getattr(fact, "fact_kind", "") or "")
                in {"metadata", "ranked_row"}
                and any(
                    "word_sketch" in str(source_id or "").casefold()
                    for source_id in list(
                        getattr(fact, "source_evidence_ids", []) or []
                    )
                )
                for fact in linked_facts
            )
            and _DIRECT_WORD_SKETCH_OBSERVATION_PATTERN.search(text)
            and _WORD_SKETCH_INTERPRETIVE_BRIDGE_PATTERN.search(text) is None
            and not (
                interpretation_is_substantive is not None
                and interpretation_is_substantive(
                    [claim],
                    observed_facts,
                )
            )
        ):
            continue
        claim.claim_kind = "observation"
        claim_id = str(getattr(claim, "id", "") or "").strip()
        if claim_id:
            repaired.append(claim_id)
    return repaired


_WORD_SKETCH_METADATA_STATEMENT_PATTERN = re.compile(
    r"\bRelation\s+['\"„“]?([A-Za-z0-9_.:-]+)['\"„“]?\s+als\s+"
    r"['\"„“]([^'\"„“;]+)['\"„“]",
    re.IGNORECASE,
)


def _repair_word_sketch_metadata_fact_bindings(
    contract: Any,
    envelope: Any,
    observed_facts: List[Any],
) -> List[str]:
    """Attach exact relation metadata when a row claim names its relation."""

    if str(getattr(contract, "analysis_family", "") or "") != (
        "word_sketch_profile"
    ):
        return []
    fact_index = {
        str(getattr(fact, "id", "") or "").strip(): fact
        for fact in observed_facts
        if str(getattr(fact, "id", "") or "").strip()
    }
    metadata: List[tuple[str, str, set[str]]] = []
    for fact_id, fact in fact_index.items():
        if str(getattr(fact, "fact_kind", "") or "") != "metadata":
            continue
        match = _WORD_SKETCH_METADATA_STATEMENT_PATTERN.search(
            str(getattr(fact, "statement", "") or "")
        )
        if match is None:
            continue
        metadata.append(
            (
                fact_id,
                match.group(1),
                {
                    str(source_id)
                    for source_id in list(
                        getattr(fact, "source_evidence_ids", []) or []
                    )
                    if str(source_id)
                },
            )
        )
    repaired: List[str] = []
    for claim in list(getattr(envelope, "claims", []) or []):
        current_ids = _dedupe_ordered_strs(
            list(getattr(claim, "fact_ids", []) or [])
        )
        linked_sources = {
            str(source_id)
            for fact_id in current_ids
            for fact in [fact_index.get(fact_id)]
            if fact is not None
            for source_id in list(
                getattr(fact, "source_evidence_ids", []) or []
            )
            if str(source_id)
        }
        text = str(getattr(claim, "text", "") or "")
        additions = [
            fact_id
            for fact_id, relation, source_ids in metadata
            if fact_id not in current_ids
            and (not linked_sources or not linked_sources.isdisjoint(source_ids))
            and re.search(
                rf"(?<!\w){re.escape(relation)}(?!\w)",
                text,
                re.IGNORECASE,
            )
        ]
        if not additions:
            continue
        claim.fact_ids = _dedupe_ordered_strs(current_ids + additions)
        claim_id = str(getattr(claim, "id", "") or "").strip()
        if claim_id:
            repaired.append(claim_id)
    return repaired


_WORD_SKETCH_ROW_STATEMENT_PATTERN = re.compile(
    r"\bTabelle\s+['\"„“]?([A-Za-z0-9_.:-]+)['\"„“]?[^\n]{0,180}?"
    r"\bPartnerzeile\s+['\"„“]([^'\"„“\n]{1,80})['\"„“][^\n]{0,120}?"
    r"(?<![\w2₂])f\s*=\s*(-?\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)


def _repair_word_sketch_row_fact_bindings(
    contract: Any,
    envelope: Any,
    observed_facts: List[Any],
) -> List[str]:
    """Attach a row fact only when relation, label, and f are explicit."""

    if str(getattr(contract, "analysis_family", "") or "") != (
        "word_sketch_profile"
    ):
        return []
    fact_index = {
        str(getattr(fact, "id", "") or "").strip(): fact
        for fact in observed_facts
        if str(getattr(fact, "id", "") or "").strip()
    }
    rows: List[tuple[str, str, str, str, set[str]]] = []
    for fact_id, fact in fact_index.items():
        if str(getattr(fact, "fact_kind", "") or "") != "ranked_row":
            continue
        match = _WORD_SKETCH_ROW_STATEMENT_PATTERN.search(
            str(getattr(fact, "statement", "") or "")
        )
        if match is None:
            continue
        rows.append(
            (
                fact_id,
                match.group(1),
                match.group(2).strip(),
                match.group(3).replace(",", "."),
                {
                    str(source_id)
                    for source_id in list(
                        getattr(fact, "source_evidence_ids", []) or []
                    )
                    if str(source_id)
                },
            )
        )

    repaired: List[str] = []
    for claim in list(getattr(envelope, "claims", []) or []):
        current_ids = _dedupe_ordered_strs(
            list(getattr(claim, "fact_ids", []) or [])
        )
        linked_sources = {
            str(source_id)
            for fact_id in current_ids
            for fact in [fact_index.get(fact_id)]
            if fact is not None
            for source_id in list(
                getattr(fact, "source_evidence_ids", []) or []
            )
            if str(source_id)
        }
        text = str(getattr(claim, "text", "") or "")
        additions: List[str] = []
        for fact_id, relation, label, frequency, source_ids in rows:
            if fact_id in current_ids or (
                linked_sources and linked_sources.isdisjoint(source_ids)
            ):
                continue
            if re.search(
                rf"(?<!\w){re.escape(relation)}(?!\w)",
                text,
                re.IGNORECASE,
            ) is None:
                continue
            label_then_f = re.search(
                rf"(?<!\w){re.escape(label)}(?!\w)[^\n]{{0,64}}?"
                rf"(?<![\w2₂])f\s*=\s*{re.escape(frequency)}(?!\d)",
                text,
                re.IGNORECASE,
            )
            f_then_label = re.search(
                rf"(?<![\w2₂])f\s*=\s*{re.escape(frequency)}(?!\d)"
                rf"[^\n]{{0,64}}?(?<!\w){re.escape(label)}(?!\w)",
                text,
                re.IGNORECASE,
            )
            if label_then_f is not None or f_then_label is not None:
                additions.append(fact_id)
        if not additions:
            continue
        claim.fact_ids = _dedupe_ordered_strs(current_ids + additions)
        claim_id = str(getattr(claim, "id", "") or "").strip()
        if claim_id:
            repaired.append(claim_id)
    return repaired


def _word_sketch_relation_only_fact_payload(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Hide row counts and thresholds from a relation-only synthesis turn."""

    match = _WORD_SKETCH_METADATA_STATEMENT_PATTERN.search(
        str(payload.get("statement") or "")
    )
    if match is None:
        return payload
    focused = dict(payload)
    focused["statement"] = (
        "Das Word Sketch beschreibt die Relation "
        f"'{match.group(1)}' als '{match.group(2).strip()}'."
    )
    focused["grounding_quotes"] = []
    return focused


def _assertion_strength(claim: Any) -> int:
    return {
        "tentative": 1,
        "qualified": 2,
        "exact": 3,
    }.get(
        str(getattr(claim, "assertion_level", "") or "").casefold(),
        2,
    )


def _is_assertion_repair_reason(reason: str) -> bool:
    text = str(reason or "").strip()
    return bool(
        re.search(
            r"(?:Exakter Claim|Claim ist stärker als|"
            r"Kategorisierende Aussage)",
            text,
        )
    )


_RELITIGATION_ONLY_REASON = re.compile(
    r"\b(?:redundan\w*|duplikat\w*|doppelt\w*)\b",
    re.IGNORECASE,
)
_SUBSTANTIVE_REJECTION_REASON = re.compile(
    r"\b(?:unbelegt\w*|ungedeckt\w*|nicht\s+(?:belegt|gedeckt|gestützt)|"
    r"semantisch\s+(?:falsch|unbelegt)|falsch\w*|widerspr\w*|"
    r"erfunden\w*|halluzin\w*|unzulässig\w*|unbegründet\w*|"
    r"stimm\w*\s+nicht|unsupported|not\s+grounded|incorrect|false)\b",
    re.IGNORECASE,
)
_FALSE_SLOT_ASSIGNMENT_REASON = re.compile(
    r"(?:\b(?:trägt|hat|carries|has)\b[^.!?\n]{0,100}"
    r"\bresponse_requirement_id\b|"
    r"\b(?:is\s+assigned|ist\s+zugeordnet|wurde\s+zugeordnet)\b"
    r"[^.!?\n]{0,100}\b(?:response_requirement_id|answer\s+slot|"
    r"antwortslot|slot)\b)",
    re.IGNORECASE,
)

_KWIC_RELATION_RUNTIME_REASON_PREFIX = (
    "Die Deutung des erweiterten KWIC-Kontexts widerspricht dem Wortlaut "
    "oder legt eine syntaktische Anbindung ohne passende Evidenz fest: "
)
_KWIC_RELATION_RECONSIDERABLE_DETAILS = (
    "behauptete Negationsfreiheit",
    "kategoriale Pronomen- oder Adressatenauflösung",
    "kategoriale Teilnehmeridentität oder Entitätstype",
    "neue Teilnehmer- oder Entitätstype",
    "Teilnehmerrolle vom sichtbaren Pronomen",
    "kategoriale syntaktische Anbindung",
)


def _runtime_kwic_relation_rejection_is_reconsiderable(
    reasons: List[str],
) -> bool:
    """Allow the semantic relation gate to revisit only its own heuristics."""

    if not reasons:
        return False
    for reason in reasons:
        text = str(reason or "")
        if not text.startswith(_KWIC_RELATION_RUNTIME_REASON_PREFIX):
            return False
        details = text[len(_KWIC_RELATION_RUNTIME_REASON_PREFIX) :].rstrip(".")
        parts = [part.strip() for part in details.split(", ") if part.strip()]
        if not parts or any(
            not any(marker in part for marker in _KWIC_RELATION_RECONSIDERABLE_DETAILS)
            for part in parts
        ):
            return False
    return True


_KWIC_IDENTITY_REJECTION_PATTERN = re.compile(
    r"\b(?:referent|koreferen|coreferen|pronomen|adressat|sprecher|autor|"
    r"teilnehmer|entität|entitaet|identität|identitaet)\w*\b",
    re.IGNORECASE,
)


def _kwic_semantic_rejection_allows_runtime_override(
    reasons: List[str],
) -> bool:
    """Never turn an explicit identity-resolution rejection into acceptance."""

    return not any(
        _KWIC_IDENTITY_REJECTION_PATTERN.search(str(reason or ""))
        for reason in reasons
    )


def _rejection_only_relitigates_prior_acceptance(
    reasons: List[str],
) -> bool:
    """Distinguish duplicate policing from a substantive semantic correction."""

    visible = _dedupe_ordered_strs(reasons)
    return bool(visible) and all(
        _RELITIGATION_ONLY_REASON.search(reason) is not None
        and _SUBSTANTIVE_REJECTION_REASON.search(reason) is None
        for reason in visible
    )


def _rejection_only_misattributed_a_blank_slot(reasons: List[str]) -> bool:
    """Recognise a verifier critique of a slot the claim never carried."""

    visible = _dedupe_ordered_strs(reasons)
    return bool(visible) and all(
        _FALSE_SLOT_ASSIGNMENT_REASON.search(reason) is not None
        and _SUBSTANTIVE_REJECTION_REASON.search(reason) is None
        for reason in visible
    )


def _redundancy_rejection_names_accepted_successor(
    reasons: List[str],
    *,
    rejected_id: str,
    accepted_ids: set[str],
) -> bool:
    """Keep a semantic replacement decision instead of restoring stale prose."""

    if not rejected_id or not accepted_ids:
        return False

    def mentions(reason: str, claim_id: str) -> bool:
        return re.search(
            rf"(?<![A-Za-z0-9]){re.escape(claim_id)}(?![A-Za-z0-9])",
            reason,
        ) is not None

    return any(
        _RELITIGATION_ONLY_REASON.search(reason) is not None
        and mentions(reason, rejected_id)
        and any(mentions(reason, accepted_id) for accepted_id in accepted_ids)
        for reason in _dedupe_ordered_strs(reasons)
    )


def _claim_payload(claim: Any, *, claim_id: str) -> dict[str, Any]:
    """Serialize a claim while replacing its internal lifecycle identifier."""

    if callable(getattr(claim, "to_dict", None)):
        raw = claim.to_dict()
        payload = dict(raw) if isinstance(raw, dict) else {}
    else:
        payload = {
            "claim_kind": getattr(claim, "claim_kind", ""),
            "text": getattr(claim, "text", ""),
            "fact_ids": list(getattr(claim, "fact_ids", []) or []),
            "assertion_level": getattr(claim, "assertion_level", ""),
        }
    payload["id"] = claim_id
    return payload


def _project_claims(
    claims: List[Any],
    *,
    prefix: str,
) -> tuple[List[dict[str, Any]], dict[str, str]]:
    """Expose opaque, attempt-local IDs at an LLM boundary."""

    payloads: List[dict[str, Any]] = []
    projected_to_internal: dict[str, str] = {}
    for index, claim in enumerate(claims, start=1):
        projected_id = f"{prefix}{index:03d}"
        internal_id = str(getattr(claim, "id", "") or "").strip()
        payloads.append(_claim_payload(claim, claim_id=projected_id))
        projected_to_internal[projected_id] = internal_id
    return payloads, projected_to_internal


def _project_facts(
    facts: List[Any],
) -> tuple[List[dict[str, Any]], dict[str, str]]:
    """Expose short, stable fact IDs so local models can copy them reliably."""

    payloads: List[dict[str, Any]] = []
    projected_to_internal: dict[str, str] = {}
    for index, fact in enumerate(facts, start=1):
        projected_id = f"f{index:03d}"
        raw = fact.to_dict() if callable(getattr(fact, "to_dict", None)) else {}
        payload = dict(raw) if isinstance(raw, dict) else {}
        payload["id"] = projected_id
        payloads.append(payload)
        projected_to_internal[projected_id] = str(
            getattr(fact, "id", "") or ""
        ).strip()
    return payloads, projected_to_internal


def _rewrite_claim_payload_fact_ids(
    payloads: List[dict[str, Any]],
    internal_to_projected: dict[str, str],
) -> None:
    for payload in payloads:
        payload["fact_ids"] = [
            internal_to_projected.get(str(fact_id), str(fact_id))
            for fact_id in list(payload.get("fact_ids") or [])
            if str(fact_id)
        ]


def _replace_internal_ids(
    text: str,
    aliases: dict[str, str],
) -> str:
    result = str(text or "")
    for internal_id in sorted(aliases, key=len, reverse=True):
        if internal_id:
            result = result.replace(internal_id, aliases[internal_id])
    return result


def _resolve_projected_id(
    value: Any,
    projected_to_internal: dict[str, str],
) -> tuple[str, str]:
    raw = str(value or "").strip()
    if raw in projected_to_internal:
        return projected_to_internal[raw], ""
    compact = re.sub(r"<[^>]*>", "", raw)
    compact = "".join(compact.split())
    if compact in projected_to_internal:
        return projected_to_internal[compact], ""
    alphanumeric = "".join(
        character for character in compact if character.isalnum()
    )
    if alphanumeric in projected_to_internal:
        return projected_to_internal[alphanumeric], ""
    return "", raw


def _strip_projected_fact_citations(
    text: Any,
    projected_fact_ids: List[str],
) -> tuple[str, int, List[str]]:
    """Remove attempt-local fact IDs that the model copied into visible prose."""

    value = str(text or "")
    ids = sorted(
        {
            str(fact_id or "").strip()
            for fact_id in projected_fact_ids
            if str(fact_id or "").strip()
        },
        key=len,
        reverse=True,
    )
    if not value or not ids:
        return value, 0, []
    bare_token = rf"(?:{'|'.join(re.escape(fact_id) for fact_id in ids)})"
    # Small models often italicise or code-format an internal citation and
    # sometimes prefix it with ``Fact`` or ``Fact-ID``. All of those forms are
    # attempt-local references and must never reach visible prose.
    fact_label = r"(?:Fact(?:[-‑–—\s]?ID)?[-‑–—\s:]*?)?"
    token = (
        rf"(?:(?:\*{{1,2}}|`)?{fact_label}{bare_token}"
        rf"(?:\*{{1,2}}|`)?)"
    )
    stripped_count = 0
    invalid_groups: List[str] = []
    separator = (
        r"(?:\s*[,;/&+]\s*|\s+(?:und|oder|and|or)\s+)"
    )
    range_separator = r"\s*[-‐‑‒–—]\s*"
    token_or_range = rf"{token}(?:{range_separator}{token})?"
    token_group = rf"{token_or_range}(?:{separator}{token_or_range})*"
    matching_brackets = {"(": ")", "[": "]", "{": "}"}
    bracket_group = re.compile(
        r"(?P<open>[\(\[\{])(?P<body>[^()\[\]{}\n]{1,180})"
        r"(?P<close>[\)\]\}])",
        re.IGNORECASE,
    )
    example_prefix = r"(?:(?:z\s*\.\s*b|e\s*\.\s*g)\s*\.\s*)?"
    valid_group_body = re.compile(
        rf"\s*{example_prefix}{token_group}\s*",
        re.IGNORECASE,
    )

    citation_noun_pattern = (
        r"Text(?:e|en)?|Passagestext(?:e|en)?|Passage(?:n)?|"
        r"Treffer(?:n)?|Dokument(?:e|en)?|Beleg(?:e|en)?"
    )

    def _visible_citation_noun(noun: str, count: int) -> str:
        if count == 1:
            return noun
        plural = {
            "passage": "Passagen",
            "passagen": "Passagen",
            "treffer": "Treffer",
            "treffern": "Treffer",
            "dokument": "Dokumente",
            "dokumente": "Dokumente",
            "dokumenten": "Dokumente",
            "beleg": "Belege",
            "belege": "Belege",
            "belegen": "Belege",
            "text": "Texte",
            "texte": "Texte",
            "texten": "Texte",
        }.get(noun.casefold(), noun)
        return plural if noun[:1].isupper() else plural.casefold()

    # Remove the complete citation phrase before the generic bracket pass.
    # Otherwise ``Passage aus (f001)`` becomes the ungrammatical
    # ``Passage aus`` after the parenthesised ID is stripped in isolation.
    parenthesised_noun_citation = re.compile(
        rf"(?<![A-Za-z0-9_])(?P<noun>{citation_noun_pattern})\s+"
        rf"(?:von|zu|aus|in|mit)\s+"
        rf"(?:\((?P<round>{token_group})\)|"
        rf"\[(?P<square>{token_group})\]|"
        rf"\{{(?P<curly>{token_group})\}})"
        rf"(?![A-Za-z0-9_])",
        re.IGNORECASE,
    )

    def _replace_parenthesised_noun_citation(
        match: re.Match[str],
    ) -> str:
        nonlocal stripped_count
        count = len(re.findall(token, match.group(0), re.IGNORECASE))
        stripped_count += count
        return _visible_citation_noun(match.group("noun"), count)

    value = parenthesised_noun_citation.sub(
        _replace_parenthesised_noun_citation,
        value,
    )

    def _replace_bracket_group(match: re.Match[str]) -> str:
        nonlocal stripped_count
        body = match.group("body")
        if re.search(token, body, re.IGNORECASE) is None:
            return match.group(0)
        if (
            matching_brackets.get(match.group("open"))
            == match.group("close")
            and valid_group_body.fullmatch(body)
        ):
            stripped_count += len(
                re.findall(token, body, re.IGNORECASE)
            )
            return ""
        invalid_groups.append(match.group(0))
        return match.group(0)

    value = bracket_group.sub(_replace_bracket_group, value)

    def _citation_count(match: re.Match[str]) -> int:
        return len(re.findall(token, match.group(0), re.IGNORECASE))

    noun_citation = re.compile(
        rf"(?<![A-Za-z0-9_])(?P<noun>{citation_noun_pattern})\s+"
        rf"(?:(?:von|zu|aus|in|mit)\s+)?{token_group}"
        rf"(?![A-Za-z0-9_])",
        re.IGNORECASE,
    )

    def _replace_noun_citation(match: re.Match[str]) -> str:
        nonlocal stripped_count
        count = _citation_count(match)
        stripped_count += count
        return _visible_citation_noun(match.group("noun"), count)

    value = noun_citation.sub(_replace_noun_citation, value)

    in_citation = re.compile(
        rf"(?<![A-Za-z0-9_])(?P<prep>in)\s+(?P<ids>{token_group})"
        rf"(?![A-Za-z0-9_])",
        re.IGNORECASE,
    )

    def _replace_in_citation(match: re.Match[str]) -> str:
        nonlocal stripped_count
        count = _citation_count(match)
        stripped_count += count
        prep = "In" if match.group("prep")[:1].isupper() else "in"
        if count == 1:
            return f"{prep} einer referenzierten Passage"
        return f"{prep} {count} referenzierten Passagen"

    value = in_citation.sub(_replace_in_citation, value)

    def _has_non_atomic_context(
        source: str,
        start: int,
        end: int,
    ) -> bool:
        prefix = source[max(0, start - 180) : start]
        suffix = source[end : min(len(source), end + 180)]
        last_open = max(prefix.rfind(char) for char in "([{")
        last_close = max(prefix.rfind(char) for char in ")]}")
        if last_open > last_close:
            return True
        next_close = min(
            (
                position
                for position in (suffix.find(char) for char in ")]}")
                if position >= 0
            ),
            default=-1,
        )
        next_open = min(
            (
                position
                for position in (suffix.find(char) for char in "([{")
                if position >= 0
            ),
            default=-1,
        )
        if next_close >= 0 and (next_open < 0 or next_close < next_open):
            return True
        # Only another projection-shaped token makes this a mixed ID group.
        # Ordinary words before a clause-separating semicolon do not.
        identifier = r"[A-Za-z]\d{2,}"
        return bool(
            re.match(rf"{separator}{identifier}", suffix)
            or re.search(rf"{identifier}{separator}$", prefix)
        )

    attribution_citation = re.compile(
        rf"(?<![A-Za-z0-9_])(?P<prep>laut|gemäß|gemaess|gemass|nach)\s+"
        rf"{token_group}(?![A-Za-z0-9_])",
        re.IGNORECASE,
    )

    def _replace_attribution(match: re.Match[str]) -> str:
        nonlocal stripped_count
        if _has_non_atomic_context(
            value,
            match.start(),
            match.end(),
        ):
            invalid_groups.append(match.group(0))
            return match.group(0)
        stripped_count += _citation_count(match)
        raw_prefix = match.group("prep")
        prefix = (
            raw_prefix[:1].upper() + raw_prefix[1:]
            if raw_prefix[:1].isupper()
            else raw_prefix
        )
        return f"{prefix} der sichtbaren Evidenz"

    value = attribution_citation.sub(_replace_attribution, value)

    quoted_subject_citation = re.compile(
        rf"(?P<lead>^|\s+)(?P<ids>{token_group})"
        rf"(?=\s*[\(\[][^()\[\]\n]{{1,180}}[\)\]]\s+"
        rf"(?:kritisiert|bezeichnet|beschreibt|zeigt|nennt|wertet|stellt)\b)",
        re.IGNORECASE,
    )

    def _replace_quoted_subject(match: re.Match[str]) -> str:
        nonlocal stripped_count
        count = _citation_count(match)
        stripped_count += count
        subject = (
            "Eine referenzierte Passage"
            if count == 1
            else "Referenzierte Passagen"
        )
        return f"{match.group('lead')}{subject}"

    value = quoted_subject_citation.sub(
        _replace_quoted_subject,
        value,
    )

    sentence_subject_citation = re.compile(
        rf"(?P<lead>^|(?<=[.!?:;])\s+|(?m:^[ \t]*[•*+-][ \t]+))"
        rf"(?P<ids>{token_group})"
        rf"(?=\s+(?:wird|werden|zeigt|zeigen|beschreibt|beschreiben|"
        rf"belegt|belegen|nennt|nennen|enthält|enthalten|berichtet|"
        rf"berichten|thematisiert|thematisieren|formuliert|formulieren|"
        rf"bewertet|bewerten|interpretiert|interpretieren|deutet|deuten|"
        rf"rahmt|rahmen|charakterisiert|charakterisieren|signalisiert|"
        rf"signalisieren|verweist|verweisen|dokumentiert|dokumentieren|"
        rf"kritisiert|kritisieren|fordert|fordern|betont|betonen|weist|"
        rf"weisen|stellt|stellen|liefert|liefern|unterstreicht|unterstreichen|verknüpft|"
        rf"verknüpfen|ordnet|ordnen|kontrastiert|kontrastieren|erklärt|"
        rf"erklären|definiert|definieren|argumentiert|argumentieren)\b)",
        re.IGNORECASE,
    )

    def _replace_sentence_subject(match: re.Match[str]) -> str:
        nonlocal stripped_count
        count = _citation_count(match)
        stripped_count += count
        subject = (
            "Eine referenzierte Passage"
            if count == 1
            else "Referenzierte Passagen"
        )
        return f"{match.group('lead')}{subject}"

    value = sentence_subject_citation.sub(
        _replace_sentence_subject,
        value,
    )
    relative_subject_citation = re.compile(
        rf"(?<![A-Za-z0-9_])(?P<ids>{token_group})\s*,\s*"
        rf"(?P<relative>das|der|die|welches|welcher|welche)\b",
        re.IGNORECASE,
    )

    def _replace_relative_subject(match: re.Match[str]) -> str:
        nonlocal stripped_count
        count = _citation_count(match)
        stripped_count += count
        if count == 1:
            return "eine referenzierte Passage, die"
        return "referenzierte Passagen, die"

    value = relative_subject_citation.sub(
        _replace_relative_subject,
        value,
    )
    fact_id_heading = re.compile(
        rf"(?im)^[ \t]*(?:\*{{1,2}})?fact[-‑–— ]?ids?\s*:?\s*"
        rf"(?:\*{{1,2}})?\s*(?P<ids>{token_group})\s*$",
        re.IGNORECASE,
    )

    def _drop_fact_id_heading(match: re.Match[str]) -> str:
        nonlocal stripped_count
        stripped_count += _citation_count(match)
        return ""

    value = fact_id_heading.sub(_drop_fact_id_heading, value)
    inline_fact_id_label = re.compile(
        rf"(?<![A-Za-z0-9_])(?:\*{{1,2}}|`)?"
        rf"Fact[-‑–— ]?IDs?\s*:?[ \t]*{token_group}"
        rf"(?:\*{{1,2}}|`)?[ \t]*(?:[-‑–—:][ \t]*)?",
        re.IGNORECASE,
    )

    def _drop_inline_fact_id_label(match: re.Match[str]) -> str:
        nonlocal stripped_count
        stripped_count += _citation_count(match)
        return ""

    value = inline_fact_id_label.sub(_drop_inline_fact_id_label, value)
    standalone_group = re.compile(
        rf"(?<![A-Za-z0-9_]){token_group}(?![A-Za-z0-9_])",
        re.IGNORECASE,
    )

    def _drop_standalone_group(match: re.Match[str]) -> str:
        if _has_non_atomic_context(
            value,
            match.start(),
            match.end(),
        ):
            invalid_groups.append(match.group(0))
            return match.group(0)
        # A bare ID can be a syntactic subject or object, not merely a
        # parenthetical citation. Deleting it would manufacture broken prose
        # (for example "enthält f003 einen Kontext" -> "enthält einen
        # Kontext"). Recognised citation forms are handled above; ambiguous
        # bare uses must be regenerated instead of silently rewritten.
        invalid_groups.append(match.group(0))
        return match.group(0)

    value = standalone_group.sub(_drop_standalone_group, value)
    value = re.sub(
        r"(?im)^[ \t]*(?:\*{1,2})?fact[-‑–— ]?ids?\s*:?[ \t]*"
        r"(?:\*{1,2})?[ \t]*$",
        "",
        value,
    )
    # A prior retry can have removed the projected token while retaining an
    # orphaned label such as ``Fact‑``. Repair only these unmistakable
    # technical remnants; ordinary uses of the word "fact" stay untouched.
    dangling_fact = r"Fact(?:[-‑–— ]?ID)?[-‑–—]+"
    value = re.sub(
        rf"\s+(?:mit|von|zu|aus)\s+{dangling_fact}(?=\s|[,.;:!?])",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        rf"\bIn\s+{dangling_fact}(?=\s|[,.;:!?])",
        "In einer referenzierten Passage",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        rf"(?<![A-Za-z0-9_]){dangling_fact}(?=\s+(?:wird|werden|"
        rf"zeigt|zeigen|beschreibt|beschreiben|betont|betonen|nennt|"
        rf"nennen|enthält|enthalten|berichtet|berichten)\b)",
        "Eine referenzierte Passage",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return (
        value.strip(),
        stripped_count,
        _dedupe_ordered_strs(invalid_groups),
    )


def _normalise_semantic_search_method_label(text: Any) -> tuple[str, int]:
    """Correct a lexical method label without changing claim substance."""

    value = str(text or "")
    search_pattern = re.compile(
        r"(?P<prefix>\bsemantisch\w*\s+(?:Suche|Suchtool)\s+"
        r"(?:nach|mit)\s+dem\s+)Lemma\b",
        re.IGNORECASE,
    )
    value, count = search_pattern.subn(
        lambda match: f"{match.group('prefix')}Suchtext",
        value,
    )
    ranking_pattern = re.compile(
        r"(?P<prefix>\b(?:top[-‑–— ]?n[-‑–— ]?)?treffer\w*\s+des\s+)"
        r"Lemmas\b",
        re.IGNORECASE,
    )
    value, ranking_count = ranking_pattern.subn(
        lambda match: f"{match.group('prefix')}Suchtexts",
        value,
    )
    return value, count + ranking_count


_BINDING_NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])[-+]?(?:\d{1,3}(?:[ .]\d{3})+|\d+)"
    r"(?:[.,]\d+)?(?![A-Za-z0-9_])"
)
_BINDING_QUOTE_PATTERN = re.compile(
    r"`([^`\n]{2,80})`|'([^'\n]{2,80})'|\"([^\"\n]{2,80})\"|"
    r"„([^“\n]{2,80})“"
)


def _normalise_binding_number(value: str) -> str:
    compact = str(value or "").replace(" ", "")
    if "," in compact and "." not in compact:
        compact = compact.replace(",", ".")
    return compact


def _replaces_number_bound_evaluative_label(
    source_text: str,
    claim_text: str,
    phrase: str,
) -> bool:
    """Detect a neutral noun substituted for a number-bound source label."""

    source = str(source_text or "")
    claim = str(claim_text or "")
    phrase_tokens = {
        token.casefold()
        for token in re.findall(r"[^\W\d_]+", phrase, re.UNICODE)
    }
    if not phrase_tokens or _candidate_quote_is_anchored(phrase, claim):
        return False

    def number_key(value: str) -> str:
        compact = re.sub(r"[ \u202f]", "", value)
        if re.fullmatch(r"[+-]?\d{1,3}(?:\.\d{3})+", compact):
            compact = compact.replace(".", "")
        return compact.replace(",", ".")

    def following_noun(value: str, end: int) -> str:
        match = re.match(
            r"[\s\"'„“‚‘«»‹›`]*([^\W\d_]+)",
            value[end : end + 80],
            re.UNICODE,
        )
        if match is None:
            return ""
        token = match.group(1)
        return token if token[:1].isupper() else ""

    claim_numbers: dict[str, List[re.Match[str]]] = {}
    for match in _BINDING_NUMBER_PATTERN.finditer(claim):
        claim_numbers.setdefault(number_key(match.group(0)), []).append(match)
    for source_match in _BINDING_NUMBER_PATTERN.finditer(source):
        key = number_key(source_match.group(0))
        source_noun = following_noun(source, source_match.end())
        if source_noun.casefold() not in phrase_tokens:
            continue
        for claim_match in claim_numbers.get(key, []):
            claim_noun = following_noun(claim, claim_match.end())
            if (
                claim_noun
                and claim_noun.casefold() not in phrase_tokens
                and claim_noun.casefold() != source_noun.casefold()
            ):
                return True
    return False


def _surface_binding_anchors(text: Any) -> set[tuple[str, str]]:
    value = str(text or "")
    anchors = {
        ("number", _normalise_binding_number(match.group(0)))
        for match in _BINDING_NUMBER_PATTERN.finditer(value)
    }
    for match in _BINDING_QUOTE_PATTERN.finditer(value):
        quoted = next(
            (
                " ".join(group.split()).casefold()
                for group in match.groups()
                if group and " ".join(group.split())
            ),
            "",
        )
        if quoted:
            anchors.add(("quote", quoted))
    return anchors


def _fact_binding_anchors(fact: Any) -> set[tuple[str, str]]:
    surface = _fact_binding_surface(fact)
    return _surface_binding_anchors(surface)


def _fact_binding_surface(fact: Any) -> str:
    return " ".join(
        [
            str(getattr(fact, "statement", "") or ""),
            *[
                str(item or "")
                for item in list(
                    getattr(fact, "grounding_quotes", []) or []
                )
            ],
        ]
    )


def _is_retrieval_candidate_fact(fact: Any) -> bool:
    """Identify visible row-level evidence from any analytical retrieval."""

    return str(getattr(fact, "fact_kind", "") or "").casefold() in {
        "kwic_example",
        "ranked_row",
    }


def _is_semantic_retrieval_candidate_fact(fact: Any) -> bool:
    """Return whether a row originates from similarity-based retrieval."""

    if not _is_retrieval_candidate_fact(fact):
        return False
    provenance = " ".join(
        str(value or "")
        for value in list(
            getattr(fact, "source_evidence_ids", []) or []
        )
    ).casefold()
    return any(
        tool in provenance
        for tool in (
            "semantic_search",
            "transformer_search",
            "similar_words",
        )
    )


def _retrieval_candidate_signature(fact: Any) -> tuple[str, str]:
    """Identify the same returned row across repeated analytical calls."""

    payload = {
        "statement": str(getattr(fact, "statement", "") or ""),
        "grounding_quotes": list(
            getattr(fact, "grounding_quotes", []) or []
        ),
    }
    quote = _normalise_candidate_quote(
        _candidate_source_quote(payload)
    ).casefold()
    surface = _fact_binding_surface(fact)
    doc_match = re.search(
        r"\bdoc_id\s*=\s*([^,;\s]+)",
        surface,
        re.IGNORECASE,
    )
    doc_id = doc_match.group(1).strip().casefold() if doc_match else ""
    if quote:
        return doc_id, " ".join(quote.split())
    normalised_surface = " ".join(surface.casefold().split())
    if normalised_surface:
        return doc_id, normalised_surface
    return "fact_id", str(getattr(fact, "id", "") or "").strip()


def _unique_retrieval_candidate_facts(facts: List[Any]) -> List[Any]:
    """Deduplicate visible retrieval rows across repeated analytical calls."""

    unique: List[Any] = []
    seen: set[tuple[str, str]] = set()
    for fact in facts:
        if not _is_retrieval_candidate_fact(fact):
            continue
        signature = _retrieval_candidate_signature(fact)
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(fact)
    return unique


def _fact_supports_binding_anchor(
    anchor: tuple[str, str],
    *,
    anchors: set[tuple[str, str]],
    surface: str,
) -> bool:
    if anchor[0] != "quote":
        return anchor in anchors
    needle = " ".join(anchor[1].split()).casefold()
    haystack = " ".join(surface.split()).casefold()
    return bool(needle) and re.search(
        rf"(?<!\w){re.escape(needle)}(?!\w)",
        haystack,
    ) is not None


def _candidate_fact_ids_from_surface(
    claim: Any,
    observed_facts: List[Any],
    *,
    question_text: str = "",
    max_fact_ids: int = 8,
) -> List[str]:
    """Find a minimal fact set that covers every literal number/quote anchor."""

    required = _surface_binding_anchors(
        getattr(claim, "text", "")
    )
    question_quotes = {
        anchor
        for anchor in _surface_binding_anchors(question_text)
        if anchor[0] == "quote"
    }
    required.difference_update(question_quotes)
    if not required:
        return []
    fact_anchors = [
        (
            str(getattr(fact, "id", "") or "").strip(),
            _fact_binding_anchors(fact),
            _fact_binding_surface(fact),
        )
        for fact in observed_facts
        if str(getattr(fact, "id", "") or "").strip()
    ]
    if any(
        not any(
            _fact_supports_binding_anchor(
                anchor,
                anchors=anchors,
                surface=surface,
            )
            for _fact_id, anchors, surface in fact_anchors
        )
        for anchor in required
    ):
        # At least one literal is absent from all evidence. Rebinding must
        # never turn an invented value or example into an admissible claim.
        return []

    uncovered = set(required)
    selected: List[str] = []
    while uncovered and len(selected) < max_fact_ids:
        best_id = ""
        best_coverage: set[tuple[str, str]] = set()
        for fact_id, anchors, surface in fact_anchors:
            if fact_id in selected:
                continue
            coverage = {
                anchor
                for anchor in uncovered
                if _fact_supports_binding_anchor(
                    anchor,
                    anchors=anchors,
                    surface=surface,
                )
            }
            if len(coverage) > len(best_coverage):
                best_id = fact_id
                best_coverage = coverage
        if not best_id or not best_coverage:
            return []
        selected.append(best_id)
        uncovered.difference_update(best_coverage)
    return selected if not uncovered else []


def _candidate_exact_negative_result_fact_ids(
    claim: Any,
    observed_facts: List[Any],
) -> List[str]:
    """Bind a negative method statement to the exact absence fact it describes."""

    text = str(getattr(claim, "text", "") or "")
    if _DIRECT_NEGATIVE_RESULT_PATTERN.search(text) is None:
        return []
    candidates = [
        fact
        for fact in observed_facts
        if str(getattr(fact, "fact_kind", "") or "") == "negative_result"
        and str(getattr(fact, "exactness", "") or "") == "exact"
        and str(getattr(fact, "id", "") or "").strip()
    ]
    if not candidates:
        return []

    claim_tokens = {
        token
        for token in re.findall(r"[a-zäöüß]{4,}", text.casefold())
        if token
        not in {
            "kein",
            "keine",
            "keinen",
            "nicht",
            "ohne",
            "lässt",
            "laesst",
            "daher",
            "deshalb",
        }
    }

    def score(fact: Any) -> tuple[int, int]:
        surface = " ".join(
            [
                str(getattr(fact, "statement", "") or ""),
                *[
                    str(value or "")
                    for value in list(getattr(fact, "limitations", []) or [])
                ],
            ]
        ).casefold()
        fact_tokens = set(re.findall(r"[a-zäöüß]{4,}", surface))
        return len(claim_tokens & fact_tokens), len(surface)

    ranked = sorted(candidates, key=score, reverse=True)
    best_score = score(ranked[0])[0]
    if best_score == 0 and len(candidates) > 1:
        return []
    return [str(getattr(ranked[0], "id", "") or "").strip()]


def _ordered_synthesis_facts(
    facts: List[Any],
    analysis_family: str,
) -> List[Any]:
    """Put the result-bearing facts before setup metadata for local models."""

    family = str(analysis_family or "").strip()
    priorities = {
        "contrast_keyness": {
            "ranked_row": 0,
            "distribution": 1,
            "count": 2,
            "metadata": 3,
            "limitation": 4,
        },
        "ngram_profile": {
            "ranked_row": 0,
            "count": 1,
            "limitation": 3,
        },
        "kwic_context": {
            "kwic_example": 0,
            "count": 1,
            "limitation": 3,
        },
        "trend_analysis": {
            "negative_result": 0,
            "metadata": 1,
            "limitation": 2,
        },
        "lexical_diversity": {
            "distribution": 0,
            "limitation": 2,
        },
    }.get(family, {})
    if not priorities:
        return list(facts)
    if family == "contrast_keyness":
        directional: dict[str, List[Any]] = {
            "target": [],
            "reference": [],
        }
        other_ranked: List[Any] = []
        remainder: List[Any] = []
        for fact in facts:
            if str(getattr(fact, "fact_kind", "") or "") != "ranked_row":
                remainder.append(fact)
                continue
            surface = " ".join(
                [
                    str(getattr(fact, "statement", "") or ""),
                    *[
                        str(value or "")
                        for value in list(
                            getattr(fact, "grounding_quotes", []) or []
                        )
                    ],
                ]
            )
            match = re.search(
                r"\bdirection=(target|reference)\b",
                surface,
                re.IGNORECASE,
            )
            if match is None:
                other_ranked.append(fact)
            else:
                directional[match.group(1).casefold()].append(fact)
        balanced_rows: List[Any] = []
        for index in range(
            max(len(directional["target"]), len(directional["reference"]))
        ):
            for direction in ("target", "reference"):
                if index < len(directional[direction]):
                    balanced_rows.append(directional[direction][index])
        return [
            *balanced_rows,
            *other_ranked,
            *sorted(
                remainder,
                key=lambda fact: priorities.get(
                    str(getattr(fact, "fact_kind", "") or ""),
                    1,
                ),
            ),
        ]
    return sorted(
        facts,
        key=lambda fact: priorities.get(
            str(getattr(fact, "fact_kind", "") or ""),
            1,
        ),
    )


def _balanced_fact_ids_by_source(
    facts: List[Any],
    *,
    max_items: int,
) -> List[str]:
    """Keep one large tool result from starving independent evidence."""

    groups: dict[tuple[str, ...], List[str]] = {}
    for fact in facts:
        fact_id = str(getattr(fact, "id", "") or "").strip()
        if not fact_id:
            continue
        source_ids = tuple(
            sorted(
                {
                    str(source_id)
                    for source_id in list(
                        getattr(fact, "source_evidence_ids", []) or []
                    )
                    if str(source_id)
                }
            )
        )
        fact_kind = str(getattr(fact, "fact_kind", "") or "").strip()
        group_key = source_ids or (f"fact_kind:{fact_kind}",)
        groups.setdefault(group_key, []).append(fact_id)
    balanced: List[str] = []
    for offset in range(max(map(len, groups.values()), default=0)):
        for group in groups.values():
            if offset < len(group):
                balanced.append(group[offset])
                if len(balanced) >= max_items:
                    return balanced
    return balanced


def _focused_requirement_fact_ids(
    fact_payloads: List[dict[str, Any]],
    *,
    question_text: str,
    requirements: List[Any],
    generic_fact_ids: List[str] | None = None,
    max_items: int = 24,
) -> List[str]:
    """Select task-relevant evidence for a narrow missing-slot repair."""

    task_surface = " ".join(
        [
            str(question_text or ""),
            *[
                " ".join(
                    [
                        str(getattr(requirement, "description", "") or ""),
                        str(getattr(requirement, "source_quote", "") or ""),
                    ]
                )
                for requirement in requirements
            ],
        ]
    )
    quoted_topics = _dedupe_ordered_strs(
        [
            match.group("value").strip()
            for match in re.finditer(
                r"[\"'„“‚‘](?P<value>[^\"'„“‚‘]{2,80})[\"'„“‚‘]",
                task_surface,
            )
            if match.group("value").strip()
        ]
    )
    task_lower = task_surface.casefold()
    hypothesis_slot = bool(
        re.search(r"\bhypothes\w*\b", task_lower, re.IGNORECASE)
    )
    numeric_hypothesis_requested = bool(
        re.search(
            r"\b(?:zahl\w*|anzahl\w*|trefferzahl\w*|häufigkeit\w*|"
            r"haeufigkeit\w*|prozent\w*|anteil\w*|"
            r"schwellenwert\w*|signifikanz\w*|count\w*|percent\w*|"
            r"share\w*|threshold\w*)\b",
            task_lower,
            re.IGNORECASE,
        )
    )
    preferred_kinds: set[str] = set()
    if re.search(
        r"\b(?:kwic|kontext\w*|context\w*|rund\s+um|around|"
        r"sichtbar\w*\s+muster\w*)\b",
        task_lower,
    ):
        preferred_kinds.add("kwic_example")
    if re.search(r"\b(?:frequenz\w*|frequency|rang\w*|rank\w*)\b", task_lower):
        preferred_kinds.update({"ranked_row", "count"})
    if re.search(r"\b(?:dispersion\w*|verteilung\w*|distribution\w*)\b", task_lower):
        preferred_kinds.add("distribution")
    if not quoted_topics and not preferred_kinds:
        return _dedupe_ordered_strs(list(generic_fact_ids or []))[:max_items]

    annotated: List[tuple[dict[str, Any], bool, bool]] = []
    for payload in fact_payloads:
        surface = " ".join(
            [
                str(payload.get("statement", "") or ""),
                *[
                    str(item or "")
                    for item in payload.get("grounding_quotes", []) or []
                ],
            ]
        ).casefold()
        topic_match = any(topic.casefold() in surface for topic in quoted_topics)
        kind_match = str(payload.get("fact_kind", "") or "") in preferred_kinds
        annotated.append((payload, topic_match, kind_match))

    # If the requested evidence class is actually available, keep the repair
    # on sources that produced that evidence. Model-initiated side queries
    # often repeat the topic in a zero-count fact, but that lexical overlap
    # does not make them as useful as the returned KWIC or distribution rows.
    primary = [
        payload
        for payload, topic_match, kind_match in annotated
        if kind_match and (topic_match or not quoted_topics)
    ]
    if not primary:
        primary = [
            payload
            for payload, topic_match, kind_match in annotated
            if kind_match or topic_match
        ]
    if not primary:
        return []

    primary_sources = {
        str(source_id)
        for payload in primary
        for source_id in payload.get("source_evidence_ids", []) or []
        if str(source_id)
    }
    companions = [
        payload
        for payload in fact_payloads
        if payload not in primary
        and str(payload.get("fact_kind", "") or "") in {"count", "limitation"}
        and (
            str(payload.get("fact_kind", "") or "") == "limitation"
            or not hypothesis_slot
            or numeric_hypothesis_requested
        )
        and primary_sources.intersection(
            {str(item) for item in payload.get("source_evidence_ids", []) or []}
        )
    ]
    return _dedupe_ordered_strs(
        [
            str(payload.get("id", "") or "")
            for payload in [*primary, *companions]
        ]
    )[:max_items]


def _compact_requirement_fact_payload(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Remove duplicated transport metadata from a focused repair fact."""

    compact = {
        key: copy.deepcopy(payload[key])
        for key in (
            "id",
            "statement",
            "fact_kind",
            "source_evidence_ids",
            "exactness",
            "supports_claims",
            "limitations",
        )
        if key in payload
    }
    if str(payload.get("fact_kind", "") or "") == "kwic_example":
        source_quote = _candidate_source_quote(payload)
        if source_quote:
            compact["grounding_quotes"] = [source_quote]
    return compact


class GroundingVerifier:
    """Drives the envelope -> verdict -> retry cycle with the LLM injected.

    Parameters
    ----------
    run_structured_step:
        Async callable ``(*, doc, payload, schema) -> Any`` returning the raw
        parsed structured payload (or ``None``). The orchestrator passes its
        bound ``_run_structured_step``; tests pass a fake.
    answer_envelope_doc / grounding_verifier_doc:
        Prompt docs handed to ``run_structured_step``.
    answer_envelope_schema / grounding_verdict_schema:
        Zero-arg callables returning the JSON schemas.
    answer_envelope_cls / grounding_verdict_cls:
        The ``AnswerEnvelope`` / ``GroundingVerdict`` classes (need ``from_raw``).
    validate_answer_envelope:
        ``(envelope, observed_facts, *, forbidden_claims) -> (accepted, rejected, reasons)``.
    envelope_matches_deliverable_kind:
        ``(envelope, *, deliverable_kind) -> (ok: bool, reason: str)``.
    accepted_claims_complete:
        Optional whole-answer check over the runtime- and verifier-accepted
        claims. It can request one bounded synthesis repair when an otherwise
        safe answer omits an answer-type requirement or available evidence.
    keyness_interpretation_complete:
        Optional shared runtime predicate for a concrete but bounded Keyness
        interpretation. It prevents the semantic verifier from deleting a
        deterministically safe shift hypothesis.
    word_sketch_units_complete:
        Optional shared runtime predicate for clear Word-Sketch metric units.
        Missing units are repaired before interpretation so the retry budget
        cannot be consumed by the wrong missing slot.
    kwic_reading_complete:
        Optional shared runtime predicate for a context-bound, source-anchored
        KWIC interpretation. Sharing it keeps retry selection and the final
        deliverable gate on the same definition.
    separate_hypothesis_layers:
        Whether the user explicitly requires observation, interpretation and
        hypothesis as distinct analytical layers.
    question_text:
        The normalised user question (passed through to the prompts verbatim).
    initial_draft:
        The unverified prose produced by the preceding tool loop. It may guide
        argument order and interpretation, but is never empirical evidence.
    max_retries:
        Number of *additional* synthesise/verify attempts after the first.
        The orchestrator's historical behaviour is exactly one retry, so this
        defaults to ``1``.
    """

    RETRY_EXHAUSTED_REASON = "Grounding-Retry ausgeschöpft."
    STAGNATION_REASON = (
        "Zwei Runden beanstandeten wortgleich dasselbe; eine weitere "
        "Neusynthese kann daran nichts aendern."
    )
    MAX_INITIAL_DRAFT_CHARS = 8_000

    def __init__(
        self,
        *,
        run_structured_step: Callable[..., Awaitable[Any]],
        answer_envelope_doc: Any,
        grounding_verifier_doc: Any,
        answer_envelope_schema: Callable[[], Any],
        grounding_verdict_schema: Callable[[], Any],
        answer_envelope_cls: Any,
        grounding_verdict_cls: Any,
        validate_answer_envelope: Callable[..., Tuple[List[str], List[str], dict]],
        envelope_matches_deliverable_kind: Callable[..., Tuple[bool, str]],
        question_text: str,
        accepted_claims_complete: Optional[
            Callable[..., Tuple[bool, str]]
        ] = None,
        keyness_interpretation_complete: Optional[
            Callable[..., bool]
        ] = None,
        ngram_interpretation_complete: Optional[
            Callable[..., bool]
        ] = None,
        word_sketch_interpretation_complete: Optional[
            Callable[..., bool]
        ] = None,
        word_sketch_units_complete: Optional[
            Callable[..., bool]
        ] = None,
        kwic_reading_complete: Optional[Callable[..., bool]] = None,
        separate_hypothesis_layers: bool = False,
        kwic_relation_adjudicator_doc: Any = None,
        initial_draft: str = "",
        max_retries: int = 1,
    ) -> None:
        self._run_structured_step = run_structured_step
        self._answer_envelope_doc = answer_envelope_doc
        self._grounding_verifier_doc = grounding_verifier_doc
        self._answer_envelope_schema = answer_envelope_schema
        self._grounding_verdict_schema = grounding_verdict_schema
        self._answer_envelope_cls = answer_envelope_cls
        self._grounding_verdict_cls = grounding_verdict_cls
        self._validate_answer_envelope = validate_answer_envelope
        self._envelope_matches_deliverable_kind = envelope_matches_deliverable_kind
        self._accepted_claims_complete = accepted_claims_complete
        self._keyness_interpretation_complete = (
            keyness_interpretation_complete
        )
        self._ngram_interpretation_complete = (
            ngram_interpretation_complete
        )
        self._word_sketch_interpretation_complete = (
            word_sketch_interpretation_complete
        )
        self._word_sketch_units_complete = word_sketch_units_complete
        self._kwic_reading_complete = kwic_reading_complete
        self._separate_hypothesis_layers = bool(
            separate_hypothesis_layers
        )
        self._kwic_relation_adjudicator_doc = kwic_relation_adjudicator_doc
        self._question_text = question_text
        self._initial_draft = str(initial_draft or "").strip()[
            : self.MAX_INITIAL_DRAFT_CHARS
        ]
        self._max_retries = max_retries
        self._focused_repair_attempt_counts: dict[str, int] = {}
        self._retrieval_audit_diagnostics: dict[str, Any] = {
            "required": False,
            "status": "not_run",
        }

    @staticmethod
    def _needs_confirmation_retrieval_adjudication(contract: Any) -> bool:
        return (
            "one-sided confirmation of a universal corpus claim"
            in {
                str(value or "").strip().casefold()
                for value in list(
                    getattr(contract, "forbidden_claims", []) or []
                )
            }
        )

    @staticmethod
    def _needs_semantic_retrieval_adjudication(contract: Any) -> bool:
        """Audit topical relevance for ordinary semantic analysis reports."""

        return bool(
            str(getattr(contract, "analysis_family", "") or "")
            in {"semantic_retrieval", "open_research"}
            and str(getattr(contract, "deliverable_kind", "") or "")
            in {"analysis_report", "contrast_report", "overview"}
        )

    async def _adjudicate_confirmation_retrieval(
        self,
        contract: Any,
        observed_facts: List[Any],
    ) -> List[dict[str, str]]:
        """Audit retrieval topicality and, under confirmation pressure, direction."""

        confirmation_required = (
            self._needs_confirmation_retrieval_adjudication(contract)
        )
        semantic_required = self._needs_semantic_retrieval_adjudication(
            contract
        )
        required = confirmation_required or semantic_required
        diagnostics: dict[str, Any] = {
            "required": required,
            "status": "not_required" if not required else "running",
            "mode": (
                "confirmation_direction"
                if confirmation_required
                else "semantic_topicality"
            ),
            "repair_retry_budget": self._max_retries,
        }
        self._retrieval_audit_diagnostics = diagnostics
        if not required:
            return []
        raw_candidate_facts = [
            fact
            for fact in observed_facts
            if (
                _is_retrieval_candidate_fact(fact)
                if confirmation_required
                else _is_semantic_retrieval_candidate_fact(fact)
            )
        ]
        diagnostics["candidate_count"] = len(raw_candidate_facts)
        if not raw_candidate_facts:
            diagnostics["status"] = "no_candidates"
            return []

        candidate_facts = _unique_retrieval_candidate_facts(
            raw_candidate_facts
        )
        diagnostics["unique_candidate_count"] = len(candidate_facts)
        diagnostics["duplicate_candidate_count"] = (
            len(raw_candidate_facts) - len(candidate_facts)
        )
        fact_payloads, projected_to_internal = _project_facts(
            candidate_facts
        )
        projected_ids = list(projected_to_internal)
        facts_by_projected_id = {
            str(item.get("id", "")): item for item in fact_payloads
        }
        candidate_audit_payloads: dict[str, dict[str, Any]] = {}
        for projected_id, fact_payload in facts_by_projected_id.items():
            payload: dict[str, Any] = {
                "id": projected_id,
                "quote": _candidate_source_quote(fact_payload),
            }
            sentence_units = _candidate_source_sentences(fact_payload)
            if len(sentence_units) > 1:
                payload["sentence_units"] = sentence_units
            candidate_audit_payloads[projected_id] = payload
        # A zero-hit query has no candidate row, but its verified provenance
        # may still be the only exact anchor for the user's target topic.
        search_anchors = _candidate_search_anchors(
            observed_facts if confirmation_required else candidate_facts
        )
        if confirmation_required:
            hypothesis_clause = _universal_hypothesis_clause(
                self._question_text
            )
            hypothesis_schema = {
                "name": "retrieval_hypothesis_decomposition",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "target_topic_quote": {"type": "string"},
                        "asserted_property_quote": {"type": "string"},
                        "quantifier": {
                            "type": "string",
                            "enum": ["universal", "non_universal"],
                        },
                    },
                    "required": [
                        "target_topic_quote",
                        "asserted_property_quote",
                        "quantifier",
                    ],
                },
            }
            hypothesis_raw = await self._run_structured_step(
                doc=_CONFIRMATION_HYPOTHESIS_DECOMPOSITION_DOC,
                payload={
                    "question": hypothesis_clause,
                    "retrieval_search_anchors": search_anchors,
                },
                schema=hypothesis_schema,
                temperature=0.0,
            )
            hypothesis_payload = (
                hypothesis_raw if isinstance(hypothesis_raw, dict) else {}
            )
            hypothesis_attempts: List[dict[str, Any]] = []
            diagnostics["hypothesis_attempts"] = hypothesis_attempts

            def validated_hypothesis(
                payload: Any,
            ) -> Optional[Tuple[str, str]]:
                if not isinstance(payload, dict):
                    return None
                target_quote = _normalise_candidate_quote(
                    payload.get("target_topic_quote", "")
                )
                property_quote = _normalise_candidate_quote(
                    payload.get("asserted_property_quote", "")
                )
                property_value = _without_hypothesis_quantifier(
                    property_quote
                )
                target_span = _contiguous_token_span(
                    target_quote,
                    hypothesis_clause,
                )
                property_span = _contiguous_token_span(
                    property_quote,
                    hypothesis_clause,
                )
                if (
                    not target_quote
                    or not property_value
                    or _HYPOTHESIS_QUANTIFIER_PATTERN.search(target_quote)
                    or not _candidate_quote_is_anchored(
                        target_quote,
                        hypothesis_clause,
                    )
                    or not _candidate_quote_is_anchored(
                        property_quote,
                        hypothesis_clause,
                    )
                    or target_span is None
                    or property_span is None
                    or not (
                        target_span[1] <= property_span[0]
                        or property_span[1] <= target_span[0]
                    )
                    or target_quote.casefold() == property_value.casefold()
                    or payload.get("quantifier") != "universal"
                ):
                    return None
                return target_quote, property_value

            parsed_hypothesis = validated_hypothesis(hypothesis_payload)
            hypothesis_attempts.append(
                {
                    "attempt": "initial",
                    "valid": parsed_hypothesis is not None,
                }
            )
            if parsed_hypothesis is None:
                recovery_schema = copy.deepcopy(hypothesis_schema)
                recovery_schema["name"] = (
                    "retrieval_hypothesis_span_recovery"
                )
                recovery_raw = await self._run_structured_step(
                    doc=_CONFIRMATION_HYPOTHESIS_RECOVERY_DOC,
                    payload={"question": hypothesis_clause},
                    schema=recovery_schema,
                    temperature=0.0,
                )
                parsed_hypothesis = validated_hypothesis(recovery_raw)
                hypothesis_attempts.append(
                    {
                        "attempt": "recovery",
                        "valid": parsed_hypothesis is not None,
                    }
                )
            if parsed_hypothesis is None:
                parsed_hypothesis = (
                    _fallback_hypothesis_from_prequantifier_anchor(
                        hypothesis_clause,
                        search_anchors,
                    )
                )
                hypothesis_attempts.append(
                    {
                        "attempt": "deterministic_anchor_fallback",
                        "valid": parsed_hypothesis is not None,
                    }
                )
            if parsed_hypothesis is None:
                parsed_hypothesis = (
                    _fallback_hypothesis_from_clause_structure(
                        hypothesis_clause
                    )
                )
                hypothesis_attempts.append(
                    {
                        "attempt": "deterministic_clause_fallback",
                        "valid": parsed_hypothesis is not None,
                    }
                )
            if parsed_hypothesis is None:
                diagnostics.update(
                    status="failed_closed",
                    failed_stage="hypothesis_decomposition",
                )
                return []
            target_topic, asserted_property = parsed_hypothesis
        else:
            # Ordinary semantic analysis already carries the exact tool input
            # in the evidence surface.  Re-extracting it from the prose would
            # let a small model silently change the topic being audited.
            normalised_anchors = _dedupe_ordered_strs(
                _normalise_candidate_quote(anchor)
                for anchor in search_anchors
            )
            if len(normalised_anchors) != 1:
                diagnostics.update(
                    status="failed_closed",
                    failed_stage=(
                        "missing_search_anchor"
                        if not normalised_anchors
                        else "ambiguous_search_anchor"
                    ),
                    retrieval_search_anchors=normalised_anchors[:8],
                )
                return []
            target_topic = normalised_anchors[0]
            asserted_property = ""
        diagnostics["target_topic"] = target_topic
        diagnostics["asserted_property"] = asserted_property
        topicality_schema = {
            "name": "retrieval_candidate_topicality",
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "assessments": {
                        "type": "array",
                        "minItems": len(projected_ids),
                        "maxItems": len(projected_ids),
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "fact_id": {
                                    "type": "string",
                                    "enum": projected_ids,
                                },
                                "topic_relation": {
                                    "type": "string",
                                    "enum": [
                                        "relevant",
                                        "marginal",
                                        "off_topic",
                                    ],
                                },
                                "quote": {"type": "string"},
                                "reason": {"type": "string"},
                            },
                            "required": [
                                "fact_id",
                                "topic_relation",
                                "quote",
                                "reason",
                            ],
                        },
                    },
                },
                "required": ["assessments"],
            },
        }

        def canonical_topicality_items(
            payload: Any,
        ) -> Tuple[Any, List[str]]:
            """Accept narrow, semantically equivalent schema aliases.

            Some local models return a valid topicality classification while
            renaming the schema's structural fields.  The strict semantic
            checks below still validate every ID, label, quote and reason; this
            adapter only prevents those usable answers from being discarded
            for harmless key-name drift.
            """

            if not isinstance(payload, dict):
                return None, []
            aliases: List[str] = []
            raw_items = payload.get("assessments")
            if not isinstance(raw_items, list) and isinstance(
                payload.get("classifications"),
                list,
            ):
                raw_items = payload["classifications"]
                aliases.append("classifications->assessments")
            if not isinstance(raw_items, list) and isinstance(
                payload.get("candidates"),
                list,
            ):
                raw_items = payload["candidates"]
                aliases.append("candidates->assessments")
            if not isinstance(raw_items, list):
                return raw_items, aliases

            normalised_items: List[Any] = []
            for item in raw_items:
                if not isinstance(item, dict):
                    normalised_items.append(item)
                    continue
                normalised = dict(item)
                if not str(normalised.get("fact_id", "") or "").strip():
                    alias_id = str(normalised.get("id", "") or "").strip()
                    if alias_id:
                        normalised["fact_id"] = alias_id
                        aliases.append("id->fact_id")
                if not str(
                    normalised.get("topic_relation", "") or ""
                ).strip():
                    for alias_key in (
                        "relevance",
                        "classification",
                        "assessment",
                    ):
                        alias_value = str(
                            normalised.get(alias_key, "") or ""
                        ).strip()
                        if alias_value:
                            normalised["topic_relation"] = alias_value
                            aliases.append(
                                f"{alias_key}->topic_relation"
                            )
                            break
                normalised_items.append(normalised)
            return normalised_items, _dedupe_ordered_strs(aliases)

        topicality_raw = await self._run_structured_step(
            doc=_CONFIRMATION_RETRIEVAL_TOPICALITY_DOC,
            payload={
                "target_topic": target_topic,
                "candidates": [
                    candidate_audit_payloads[projected_id]
                    for projected_id in projected_ids
                ],
            },
            schema=topicality_schema,
            temperature=0.0,
        )
        topicality_payload = (
            topicality_raw if isinstance(topicality_raw, dict) else {}
        )
        raw_topicality, initial_schema_aliases = canonical_topicality_items(
            topicality_payload
        )
        topicality_attempts: List[dict[str, Any]] = []
        partial_topicality_results: dict[
            str,
            Tuple[dict[str, dict[str, str]], List[dict[str, str]]],
        ] = {}
        diagnostics["topicality_attempts"] = topicality_attempts
        if initial_schema_aliases:
            diagnostics["topicality_schema_aliases"] = [
                {
                    "attempt": "initial",
                    "aliases": initial_schema_aliases,
                }
            ]

        def validated_topicalities(
            raw_items: Any,
            *,
            attempt: str,
            allow_taxonomy_fallback: bool,
            required_projected_ids: Optional[List[str]] = None,
        ) -> Optional[
            Tuple[dict[str, dict[str, str]], List[dict[str, str]]]
        ]:
            expected_ids = list(
                projected_ids
                if required_projected_ids is None
                else required_projected_ids
            )
            expected_id_set = set(expected_ids)
            issues: List[str] = []
            nonfatal_issues: List[str] = []
            quote_fallback_count = 0
            moderation_taxonomy_fallback_count = 0
            label_corrections: List[dict[str, str]] = []
            if not isinstance(raw_items, list):
                topicality_attempts.append(
                    {
                        "attempt": attempt,
                        "valid": False,
                        "issues": ["assessments_not_a_list"],
                    }
                )
                return None
            validated: dict[str, dict[str, str]] = {}
            proposals: List[dict[str, str]] = []
            for item in raw_items:
                if not isinstance(item, dict):
                    issues.append("assessment_not_an_object")
                    continue
                projected_id = str(
                    item.get("fact_id", "") or ""
                ).strip()
                if (
                    projected_id in validated
                    or projected_id not in expected_id_set
                ):
                    issues.append(
                        f"{projected_id or '<missing>'}:duplicate_or_unknown_id"
                    )
                    continue
                topic_relation = str(
                    item.get("topic_relation", "") or ""
                ).strip()
                reason_value = item.get("reason", "")
                quote = _normalise_candidate_quote(item.get("quote", ""))
                fact_payload = facts_by_projected_id.get(projected_id, {})
                if not quote:
                    quote = _candidate_source_quote(fact_payload)
                    quote_fallback_count += 1
                source_surface = _candidate_literal_source_surface(
                    fact_payload
                )
                if not _candidate_quote_is_anchored(
                    quote,
                    source_surface,
                ):
                    quote = _candidate_source_quote(fact_payload)
                    quote_fallback_count += 1
                if topic_relation not in {
                    "relevant",
                    "marginal",
                    "off_topic",
                }:
                    issues.append(f"{projected_id}:invalid_topic_relation")
                    continue
                reason_uses_moderation_taxonomy = (
                    _reason_uses_unrequested_moderation_taxonomy(
                        reason_value,
                        analytical_scope=target_topic,
                    )
                )
                reason_is_classification_refusal = bool(
                    _CLASSIFICATION_REFUSAL_PATTERN.search(
                        str(reason_value or "")
                    )
                )
                moderation_contaminated = bool(
                    reason_uses_moderation_taxonomy
                    or reason_is_classification_refusal
                )
                if (
                    not _classification_reason_is_substantive(reason_value)
                    and not (
                        allow_taxonomy_fallback and moderation_contaminated
                    )
                ):
                    issues.append(f"{projected_id}:non_substantive_reason")
                    continue
                if moderation_contaminated:
                    explicitly_denies_topic = _reason_explicitly_denies_topic(
                        reason_value,
                        target_topic,
                        require_explicit_target=True,
                    )
                    if not explicitly_denies_topic and not allow_taxonomy_fallback:
                        issues.append(
                            f"{projected_id}:"
                            "moderation_taxonomy_in_topicality_reason"
                        )
                        continue
                    nonfatal_issues.append(
                        f"{projected_id}:moderation_taxonomy_in_topicality_reason"
                    )
                    moderation_taxonomy_fallback_count += 1
                    if explicitly_denies_topic:
                        topic_relation = "off_topic"
                        reason_value = (
                            "Die Begründung verneint ausdrücklich einen "
                            "sichtbaren Bezug zum Zielthema."
                        )
                    else:
                        # Topicality is a recall gate. An answer on an unrelated
                        # classification axis must not suppress the candidate;
                        # the independent direction review receives it instead.
                        topic_relation = "marginal"
                        reason_value = (
                            "Die Begründung belegt keinen belastbaren direkten "
                            "Themenbezug; der Kandidat bleibt für die "
                            "nachfolgende inhaltliche Prüfung randständig."
                        )
                direct_target_attested = (
                    _candidate_quote_mentions_target_topic(
                        fact_payload,
                        target_topic,
                    )
                )
                if direct_target_attested and (
                    topic_relation != "relevant"
                    or _reason_explicitly_denies_topic(
                        reason_value,
                        target_topic,
                    )
                ):
                    label_corrections.append(
                        {
                            "fact_id": projected_id,
                            "from": topic_relation,
                            "to": "relevant",
                            "reason": " ".join(
                                str(reason_value or "").split()
                            )[:240],
                        }
                    )
                    topic_relation = "relevant"
                    reason_value = (
                        "Der Originalausschnitt nennt den Zielausdruck oder "
                        "eine erkennbare Flexionsform direkt; begrenzter "
                        "Kontext schränkt die Deutung ein, nicht den "
                        "Themenbezug."
                    )
                if not _topicality_reason_matches_label(
                    topic_relation,
                    reason_value,
                    target_topic=target_topic,
                ):
                    if (
                        topic_relation in {"relevant", "marginal"}
                        and _reason_explicitly_denies_topic(
                            reason_value,
                            target_topic,
                        )
                    ):
                        label_corrections.append(
                            {
                                "fact_id": projected_id,
                                "from": topic_relation,
                                "to": "off_topic",
                                "reason": " ".join(
                                    str(reason_value or "").split()
                                )[:240],
                            }
                        )
                        topic_relation = "off_topic"
                    else:
                        issues.append(
                            f"{projected_id}:reason_label_conflict"
                        )
                        continue
                if not _candidate_quote_is_anchored(quote, source_surface):
                    issues.append(f"{projected_id}:no_literal_quote")
                    continue
                assessment = {
                    "topic_relation": topic_relation,
                    "quote": quote[:400],
                    "reason": " ".join(
                        str(reason_value or "").split()
                    )[:600],
                }
                validated[projected_id] = assessment
                proposals.append(
                    {"fact_id": projected_id, **assessment}
                )
            missing_ids = [
                projected_id
                for projected_id in expected_ids
                if projected_id not in validated
            ]
            if missing_ids:
                issues.extend(
                    f"{projected_id}:missing_valid_assessment"
                    for projected_id in missing_ids
                )
            valid = not missing_ids
            topicality_attempts.append(
                {
                    "attempt": attempt,
                    "valid": valid,
                    "issues": _dedupe_ordered_strs(issues)[:12],
                    "nonfatal_issues": _dedupe_ordered_strs(
                        nonfatal_issues
                    )[:12],
                    "literal_quote_fallback_count": quote_fallback_count,
                    "moderation_taxonomy_fallback_count": (
                        moderation_taxonomy_fallback_count
                    ),
                    "label_corrections": label_corrections,
                }
            )
            partial_topicality_results[attempt] = (
                dict(validated),
                list(proposals),
            )
            if not valid:
                return None
            return validated, proposals

        parsed_topicality = validated_topicalities(
            raw_topicality,
            attempt="initial",
            allow_taxonomy_fallback=False,
        )
        if parsed_topicality is None:
            initial_validated, _initial_proposals = (
                partial_topicality_results.get("initial", ({}, []))
            )
            repair_ids = [
                projected_id
                for projected_id in projected_ids
                if projected_id not in initial_validated
            ]
            validation_issues = list(
                topicality_attempts[-1].get("issues", [])
                if topicality_attempts
                else []
            )
            recovery_schema = copy.deepcopy(topicality_schema)
            recovery_schema["name"] = (
                "retrieval_candidate_topicality_recovery"
            )
            recovery_items_schema = recovery_schema["schema"][
                "properties"
            ]["assessments"]
            recovery_items_schema["minItems"] = len(repair_ids)
            recovery_items_schema["maxItems"] = len(repair_ids)
            recovery_items_schema["items"]["properties"]["fact_id"][
                "enum"
            ] = list(repair_ids)
            recovery_raw = await self._run_structured_step(
                doc=_CONFIRMATION_RETRIEVAL_TOPICALITY_RECOVERY_DOC,
                payload={
                    "target_topic": target_topic,
                    "validation_issues": validation_issues,
                    "proposed_assessments": [
                        item
                        for item in (
                            raw_topicality
                            if isinstance(raw_topicality, list)
                            else []
                        )
                        if isinstance(item, dict)
                        and str(item.get("fact_id", "") or "")
                        in set(repair_ids)
                    ],
                    "candidates": [
                        candidate_audit_payloads[projected_id]
                        for projected_id in repair_ids
                    ],
                },
                schema=recovery_schema,
                temperature=0.0,
            )
            recovery_payload = (
                recovery_raw if isinstance(recovery_raw, dict) else {}
            )
            recovery_items, recovery_schema_aliases = (
                canonical_topicality_items(recovery_payload)
            )
            if recovery_schema_aliases:
                diagnostics.setdefault(
                    "topicality_schema_aliases",
                    [],
                ).append(
                    {
                        "attempt": "recovery",
                        "aliases": recovery_schema_aliases,
                    }
                )
            parsed_topicality = validated_topicalities(
                recovery_items,
                attempt="recovery",
                allow_taxonomy_fallback=True,
                required_projected_ids=repair_ids,
            )
            if parsed_topicality is not None:
                recovery_validated, _recovery_proposals = parsed_topicality
                merged_validated = {
                    **initial_validated,
                    **recovery_validated,
                }
                parsed_topicality = (
                    merged_validated,
                    [
                        {"fact_id": projected_id, **merged_validated[projected_id]}
                        for projected_id in projected_ids
                    ],
                )
        if parsed_topicality is None:
            diagnostics.update(
                status="failed_closed",
                failed_stage="topicality",
            )
            return []
        topicality_by_id, _topicality_proposals = parsed_topicality

        if not confirmation_required:
            assessments = [
                {
                    "fact_id": projected_to_internal[projected_id],
                    **topicality_by_id[projected_id],
                    "relation_to_requested_conclusion": (
                        "mixed_or_unclear"
                        if topicality_by_id[projected_id]["topic_relation"]
                        in {"relevant", "marginal"}
                        else "not_applicable"
                    ),
                }
                for projected_id in projected_ids
            ]
            diagnostics.update(
                status="complete",
                relevant_candidate_count=sum(
                    item["topic_relation"] in {"relevant", "marginal"}
                    for item in assessments
                ),
                off_topic_candidate_count=sum(
                    item["topic_relation"] == "off_topic"
                    for item in assessments
                ),
                assessment_count=len(assessments),
            )
            return assessments

        direction_ids = [
            projected_id
            for projected_id in projected_ids
            if topicality_by_id[projected_id]["topic_relation"]
            in {"relevant", "marginal"}
        ]
        direction_by_id: dict[str, dict[str, str]] = {}
        direction_attempts: List[dict[str, Any]] = []
        diagnostics["direction_attempts"] = direction_attempts
        if direction_ids:
            direction_schema = {
                "name": "retrieval_candidate_direction",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "assessments": {
                            "type": "array",
                            "minItems": len(direction_ids),
                            "maxItems": len(direction_ids),
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "fact_id": {
                                        "type": "string",
                                        "enum": direction_ids,
                                    },
                                    "asserted_property_visible": {
                                        "type": "boolean"
                                    },
                                    "genuinely_ambiguous": {
                                        "type": "boolean"
                                    },
                                    "evaluated_object_type": {
                                        "type": "string",
                                        "enum": [
                                            "target_topic",
                                            "associated_group_or_actor",
                                            "associated_policy_or_practice",
                                            "associated_effect_or_outcome",
                                            "associated_object",
                                            "target_context_without_evaluation",
                                        ],
                                    },
                                    "evaluated_object_quote": {
                                        "type": "string",
                                        "maxLength": 240,
                                    },
                                    "verbatim_evaluative_source_phrases": {
                                        "type": "array",
                                        "maxItems": 8,
                                        "description": (
                                            "Wortgetreue kurze wertende "
                                            "Personen-, Gruppen- oder "
                                            "Objektbezeichnungen aus quote. "
                                            "Leer nur, wenn dort keine solche "
                                            "Bezeichnung vorkommt."
                                        ),
                                        "items": {
                                            "type": "string",
                                            "maxLength": 120,
                                        },
                                    },
                                    "quote": {"type": "string"},
                                    "reason": {
                                        "type": "string",
                                        "maxLength": 400,
                                    },
                                },
                                "required": [
                                    "fact_id",
                                    "asserted_property_visible",
                                    "genuinely_ambiguous",
                                    "evaluated_object_type",
                                    "evaluated_object_quote",
                                    "verbatim_evaluative_source_phrases",
                                    "quote",
                                    "reason",
                                ],
                            },
                        },
                    },
                    "required": ["assessments"],
                },
            }
            direction_raw = await self._run_structured_step(
                doc=_CONFIRMATION_RETRIEVAL_DIRECTION_DOC,
                payload={
                    "target_topic": target_topic,
                    "asserted_local_property": asserted_property,
                    "candidates": [
                        candidate_audit_payloads[projected_id]
                        for projected_id in direction_ids
                    ],
                },
                schema=direction_schema,
                temperature=0.0,
            )
            direction_payload = (
                direction_raw if isinstance(direction_raw, dict) else {}
            )
            raw_directions = direction_payload.get("assessments")
            partial_direction_results: dict[
                str,
                Tuple[
                    dict[str, dict[str, str]],
                    List[dict[str, Any]],
                ],
            ] = {}

            def validated_directions(
                raw_items: Any,
                *,
                attempt: str,
                required_projected_ids: Optional[List[str]] = None,
            ) -> Optional[
                Tuple[dict[str, dict[str, str]], List[dict[str, Any]]]
            ]:
                expected_ids = list(
                    direction_ids
                    if required_projected_ids is None
                    else required_projected_ids
                )
                expected_id_set = set(expected_ids)
                issues: List[str] = []
                quote_fallback_count = 0
                topic_override_count = 0
                object_scope_correction_count = 0
                object_quote_fallback_count = 0
                direction_label_correction_count = 0
                reported_voice_correction_count = 0
                exclusion_polarity_correction_count = 0
                exchange_polarity_correction_count = 0
                if not isinstance(raw_items, list):
                    direction_attempts.append(
                        {
                            "attempt": attempt,
                            "valid": False,
                            "issues": ["assessments_not_a_list"],
                        }
                    )
                    return None
                validated: dict[str, dict[str, str]] = {}
                proposals: List[dict[str, Any]] = []
                for item in raw_items:
                    if not isinstance(item, dict):
                        issues.append("assessment_not_an_object")
                        continue
                    projected_id = str(
                        item.get("fact_id", "") or ""
                    ).strip()
                    property_visible = item.get(
                        "asserted_property_visible"
                    )
                    genuinely_ambiguous = item.get("genuinely_ambiguous")
                    evaluated_object_type = str(
                        item.get("evaluated_object_type", "") or ""
                    ).strip()
                    object_quote_was_supplied = bool(
                        str(item.get("evaluated_object_quote", "") or "").strip()
                    )
                    evaluated_object_quote = _normalise_candidate_quote(
                        item.get("evaluated_object_quote", "")
                    )
                    raw_evaluative_phrases = item.get(
                        "verbatim_evaluative_source_phrases",
                        [],
                    )
                    reason_value = item.get("reason", "")
                    quote = _normalise_candidate_quote(
                        item.get("quote", "")
                    )
                    fact_payload = facts_by_projected_id.get(
                        projected_id,
                        {},
                    )
                    source_surface = _candidate_literal_source_surface(
                        fact_payload
                    )
                    if not _candidate_quote_is_anchored(
                        quote,
                        source_surface,
                    ):
                        quote = _candidate_source_quote(fact_payload)
                        quote_fallback_count += 1
                    elif len(re.findall(r"\w+", quote, re.UNICODE)) < 3:
                        fuller_quote = _candidate_source_quote(fact_payload)
                        if fuller_quote and fuller_quote != quote:
                            quote = fuller_quote
                            quote_fallback_count += 1
                    if (
                        projected_id in validated
                        or projected_id not in expected_id_set
                    ):
                        issues.append(
                            f"{projected_id or '<missing>'}:"
                            "duplicate_or_unknown_id"
                        )
                        continue
                    if not isinstance(property_visible, bool) or not isinstance(
                        genuinely_ambiguous,
                        bool,
                    ):
                        issues.append(f"{projected_id}:invalid_direction_flags")
                        continue
                    if not isinstance(raw_evaluative_phrases, list):
                        issues.append(
                            f"{projected_id}:invalid_evaluative_phrases"
                        )
                        continue
                    evaluative_phrases = _dedupe_ordered_strs(
                        [
                            phrase
                            for phrase in (
                                _normalise_candidate_quote(value)
                                for value in raw_evaluative_phrases
                            )
                            if phrase
                            and len(
                                re.findall(r"\w+", phrase, re.UNICODE)
                            )
                            <= 8
                            and _candidate_quote_is_anchored(
                                phrase,
                                source_surface,
                            )
                        ]
                    )
                    valid_object_types = {
                        "target_topic",
                        "associated_group_or_actor",
                        "associated_policy_or_practice",
                        "associated_effect_or_outcome",
                        "associated_object",
                        "target_context_without_evaluation",
                    }
                    if not evaluated_object_type:
                        # Canned unit-test providers predate this live schema
                        # field. Preserve their former direction semantics; the
                        # real structured provider must emit the required field.
                        evaluated_object_type = (
                            "target_context_without_evaluation"
                            if genuinely_ambiguous
                            else "target_topic"
                        )
                    elif evaluated_object_type not in valid_object_types:
                        issues.append(
                            f"{projected_id}:invalid_evaluated_object_type"
                        )
                        continue
                    if (
                        object_quote_was_supplied
                        and not _candidate_quote_is_anchored(
                            evaluated_object_quote,
                            source_surface,
                        )
                    ):
                        # Never admit an invented object span. Preserve the
                        # literal candidate as a conservative local scope
                        # instead of failing the whole audit and suppressing
                        # every otherwise source-verifiable interpretation.
                        evaluated_object_quote = quote
                        evaluated_object_type = "associated_object"
                        object_quote_fallback_count += 1
                    if not object_quote_was_supplied:
                        # Compatibility for deterministic test providers that
                        # predate the required structured object span. A live
                        # provider must emit a literal, specific span.
                        evaluated_object_quote = quote
                        object_quote_fallback_count += 1
                    if (
                        evaluated_object_type == "target_topic"
                        and not _candidate_quote_mentions_target_topic(
                            fact_payload,
                            target_topic,
                        )
                    ):
                        evaluated_object_type = "associated_object"
                        object_scope_correction_count += 1
                    if (
                        property_visible
                        and evaluated_object_type
                        == "target_context_without_evaluation"
                    ):
                        issues.append(
                            f"{projected_id}:property_without_evaluated_object"
                        )
                        continue
                    if not _classification_reason_is_substantive(reason_value):
                        issues.append(f"{projected_id}:non_substantive_reason")
                        continue
                    if _reason_uses_unrequested_moderation_taxonomy(
                        reason_value,
                        analytical_scope=(
                            f"{target_topic} {asserted_property}"
                        ),
                    ):
                        issues.append(
                            f"{projected_id}:moderation_taxonomy_in_direction_reason"
                        )
                        continue
                    if _LOCAL_DIRECTION_SCOPE_CONTAMINATION_PATTERN.search(
                        str(reason_value or "")
                    ):
                        issues.append(
                            f"{projected_id}:global_scope_in_local_direction"
                        )
                        continue
                    if _DIRECTION_FACTICITY_CONTAMINATION_PATTERN.search(
                        str(reason_value or "")
                    ):
                        issues.append(
                            f"{projected_id}:facticity_in_direction_reason"
                        )
                        continue
                    if not _candidate_quote_is_anchored(quote, source_surface):
                        issues.append(f"{projected_id}:no_literal_quote")
                        continue
                    reason = " ".join(
                        str(reason_value or "").split()
                    )[:600]
                    if property_visible and _reason_denies_asserted_property(
                        reason,
                        asserted_property,
                    ):
                        property_visible = False
                        genuinely_ambiguous = not (
                            _reason_clearly_affirms_opposite_property(
                                reason,
                                asserted_property,
                            )
                        )
                        direction_label_correction_count += 1
                    elif (
                        not property_visible
                        and genuinely_ambiguous
                        and _reason_clearly_affirms_opposite_property(
                            reason,
                            asserted_property,
                        )
                    ):
                        genuinely_ambiguous = False
                        direction_label_correction_count += 1
                    if (
                        _RETRIEVAL_NEGATIVE_READING_PATTERN.search(
                            asserted_property
                        )
                        and _candidate_praises_exclusion_or_restriction(
                            fact_payload
                        )
                    ):
                        property_visible = True
                        genuinely_ambiguous = False
                        reason = (
                            "Der sichtbare Wortlaut bewertet die Nichtaufnahme, "
                            "den Ausschluss oder die Beschränkung positiv. Das "
                            "stützt lokal eine negative Rahmung des davon "
                            "betroffenen Bezugsobjekts, nicht automatisch des "
                            "abstrakten Zielthemas insgesamt."
                        )
                        exclusion_polarity_correction_count += 1
                    exchange_direction = _target_exchange_direction(
                        source_surface,
                        target_topic,
                    )
                    asserted_property_is_negative = bool(
                        _RETRIEVAL_NEGATIVE_READING_PATTERN.search(
                            asserted_property
                        )
                    )
                    asserted_property_is_positive = bool(
                        _RETRIEVAL_AFFIRMATIVE_POSITIVE_PATTERN.search(
                            asserted_property
                        )
                    )
                    exchange_supports_property = (
                        exchange_direction == "rejected"
                        and asserted_property_is_negative
                    ) or (
                        exchange_direction == "welcomed"
                        and asserted_property_is_positive
                    )
                    exchange_opposes_property = (
                        exchange_direction == "welcomed"
                        and asserted_property_is_negative
                    ) or (
                        exchange_direction == "rejected"
                        and asserted_property_is_positive
                    )
                    if exchange_supports_property or exchange_opposes_property:
                        property_visible = exchange_supports_property
                        genuinely_ambiguous = False
                        direction_word = (
                            "willkommen geheißen"
                            if exchange_direction == "welcomed"
                            else "zurückgewiesen"
                        )
                        reason = (
                            "Die explizite Kontrastform ordnet das Zielobjekt der "
                            f"Seite {direction_word!r} zu; die entgegengesetzte "
                            "Wertung gilt dem anderen genannten Objekt."
                        )
                        exchange_polarity_correction_count += 1
                    if (
                        property_visible
                        and _candidate_has_reported_or_metalinguistic_evaluation(
                            fact_payload
                        )
                    ):
                        property_visible = False
                        genuinely_ambiguous = True
                        reason = (
                            "Der Ausschnitt berichtet oder diskutiert die "
                            "evaluative Formulierung metasprachlich. Aus der "
                            "eingebetteten Wortwahl allein folgt keine "
                            "eindeutige Haltung der berichtenden Stimme."
                        )
                        reported_voice_correction_count += 1
                    if not evaluative_phrases:
                        evaluative_phrases = (
                            _metalinguistic_source_label_phrases(
                                source_surface,
                                reason,
                            )
                        )
                    if _introduces_unsupported_reciprocity(
                        source_surface,
                        str(reason or ""),
                    ):
                        # A `sowohl ... als auch` coordination distributes a
                        # requirement across participants, but it does not by
                        # itself establish a positive reciprocal relation.
                        property_visible = False
                        genuinely_ambiguous = True
                        reason = (
                            "Der sichtbare Wortlaut richtet eine "
                            "Beitragserwartung an beide genannten Gruppen. "
                            "Ohne einen eigenen Bewertungs- oder "
                            "Beziehungsmarker bleibt die Richtung gegenüber "
                            "dem Zielthema offen."
                        )
                        direction_label_correction_count += 1
                    topic_denied = _reason_explicitly_denies_topic(
                        reason,
                        target_topic,
                        require_explicit_target=True,
                    ) and not _candidate_quote_mentions_target_topic(
                        fact_payload,
                        target_topic,
                    )
                    if topic_denied:
                        topic_override_count += 1
                    relation = (
                        "not_applicable"
                        if topic_denied
                        else (
                            "mixed_or_unclear"
                            if genuinely_ambiguous
                            or evaluated_object_type
                            in {
                                "target_context_without_evaluation",
                            }
                            else (
                                (
                                    "supports"
                                    if evaluated_object_type == "target_topic"
                                    else "related_support"
                                )
                                if property_visible
                                else "counterevidence"
                            )
                        )
                    )
                    classification = {
                        "relation_to_requested_conclusion": relation,
                        "evaluated_object_type": evaluated_object_type,
                        "evaluated_object_quote": evaluated_object_quote[:240],
                        "quote": quote[:400],
                        "reason": reason,
                    }
                    if evaluative_phrases:
                        classification[
                            "verbatim_evaluative_source_phrases"
                        ] = evaluative_phrases
                    if topic_denied:
                        classification["topic_relation_override"] = (
                            "off_topic"
                        )
                    validated[projected_id] = classification
                    proposals.append(
                        {
                            "fact_id": projected_id,
                            "asserted_property_visible": property_visible,
                            "genuinely_ambiguous": genuinely_ambiguous,
                            "evaluated_object_type": evaluated_object_type,
                            "evaluated_object_quote": (
                                evaluated_object_quote[:240]
                            ),
                            "verbatim_evaluative_source_phrases": (
                                evaluative_phrases
                            ),
                            "quote": quote[:400],
                            "reason": reason,
                        }
                    )
                missing_ids = [
                    projected_id
                    for projected_id in expected_ids
                    if projected_id not in validated
                ]
                if missing_ids:
                    issues.extend(
                        f"{projected_id}:missing_valid_assessment"
                        for projected_id in missing_ids
                    )
                valid = not missing_ids
                direction_attempts.append(
                    {
                        "attempt": attempt,
                        "valid": valid,
                        "issues": _dedupe_ordered_strs(issues)[:12],
                        "literal_quote_fallback_count": quote_fallback_count,
                        "off_topic_override_count": topic_override_count,
                        "object_scope_correction_count": (
                            object_scope_correction_count
                        ),
                        "object_quote_fallback_count": (
                            object_quote_fallback_count
                        ),
                        "direction_label_correction_count": (
                            direction_label_correction_count
                        ),
                        "reported_voice_correction_count": (
                            reported_voice_correction_count
                        ),
                        "exclusion_polarity_correction_count": (
                            exclusion_polarity_correction_count
                        ),
                        "exchange_polarity_correction_count": (
                            exchange_polarity_correction_count
                        ),
                    }
                )
                partial_direction_results[attempt] = (
                    dict(validated),
                    list(proposals),
                )
                if not valid:
                    return None
                return validated, proposals

            parsed_directions = validated_directions(
                raw_directions,
                attempt="initial",
            )
            if parsed_directions is None:
                direction_by_id = {}
            else:
                direction_by_id, _direction_proposals = parsed_directions

            review_schema = copy.deepcopy(direction_schema)
            review_schema["name"] = "retrieval_direction_critical_review"
            review_raw = await self._run_structured_step(
                doc=_CONFIRMATION_RETRIEVAL_DIRECTION_REVIEW_DOC,
                payload={
                    "target_topic": target_topic,
                    "asserted_local_property": asserted_property,
                    "candidates": [
                        candidate_audit_payloads[projected_id]
                        for projected_id in direction_ids
                    ],
                },
                schema=review_schema,
                temperature=0.0,
            )
            review_payload = (
                review_raw if isinstance(review_raw, dict) else {}
            )
            raw_review = review_payload.get("assessments")
            parsed_review = validated_directions(
                raw_review,
                attempt="critical_review",
            )
            if parsed_review is not None:
                direction_by_id, _review_proposals = parsed_review
            else:
                review_validated, _partial_review_proposals = (
                    partial_direction_results.get(
                        "critical_review",
                        ({}, []),
                    )
                )
                recovery_ids = [
                    projected_id
                    for projected_id in direction_ids
                    if projected_id not in review_validated
                ]
                recovery_schema = copy.deepcopy(direction_schema)
                recovery_schema["name"] = (
                    "retrieval_direction_protocol_recovery"
                )
                recovery_items_schema = recovery_schema["schema"][
                    "properties"
                ]["assessments"]
                recovery_items_schema["minItems"] = len(recovery_ids)
                recovery_items_schema["maxItems"] = len(recovery_ids)
                recovery_items_schema["items"]["properties"]["fact_id"][
                    "enum"
                ] = list(recovery_ids)
                recovery_raw = await self._run_structured_step(
                    doc=_CONFIRMATION_RETRIEVAL_DIRECTION_RECOVERY_DOC,
                    payload={
                        "target_topic": target_topic,
                        "asserted_local_property": asserted_property,
                        "candidates": [
                            candidate_audit_payloads[projected_id]
                            for projected_id in recovery_ids
                        ],
                    },
                    schema=recovery_schema,
                    temperature=0.0,
                )
                recovery_payload = (
                    recovery_raw if isinstance(recovery_raw, dict) else {}
                )
                parsed_recovery = validated_directions(
                    recovery_payload.get("assessments"),
                    attempt="protocol_recovery",
                    required_projected_ids=recovery_ids,
                )
                if parsed_recovery is not None:
                    recovered_directions, _recovery_proposals = (
                        parsed_recovery
                    )
                    direction_by_id = {
                        **review_validated,
                        **recovered_directions,
                    }
                else:
                    direction_by_id = {}
            if set(direction_by_id) != set(direction_ids):
                diagnostics.update(
                    status="failed_closed",
                    failed_stage="direction",
                )
                return []

        assessments: List[dict[str, str]] = []
        for projected_id in projected_ids:
            topicality = topicality_by_id[projected_id]
            direction = direction_by_id.get(projected_id)
            topic_relation = topicality["topic_relation"]
            if direction is not None and direction.get(
                "topic_relation_override"
            ) == "off_topic":
                topic_relation = "off_topic"
                direction = {
                    key: value
                    for key, value in direction.items()
                    if key != "topic_relation_override"
                }
            if direction is None:
                direction = {
                    "relation_to_requested_conclusion": "not_applicable",
                    "quote": topicality["quote"],
                    "reason": topicality["reason"],
                }
            assessments.append(
                {
                    "fact_id": projected_to_internal[projected_id],
                    "topic_relation": topic_relation,
                    **direction,
                }
            )
        diagnostics.update(
            status="complete",
            initially_relevant_candidate_count=len(direction_ids),
            final_relevant_candidate_count=sum(
                item["topic_relation"] in {"relevant", "marginal"}
                for item in assessments
            ),
            assessment_count=len(assessments),
        )
        return assessments

    def _repair_literal_fact_bindings(
        self,
        contract: Any,
        observed_facts: List[Any],
        envelope: Any,
    ) -> List[str]:
        """Repair only citation pointers proven by exact literals and runtime checks."""

        accepted, rejected, _reasons = self._validate_answer_envelope(
            envelope,
            observed_facts,
            forbidden_claims=contract.forbidden_claims,
        )
        accepted_ids = set(accepted)
        repaired_ids: List[str] = []
        preserve_confirmation_groups = (
            self._needs_confirmation_retrieval_adjudication(contract)
        )
        for claim in list(getattr(envelope, "claims", []) or []):
            claim_id = str(getattr(claim, "id", "") or "").strip()
            if not claim_id or claim_id not in set(rejected):
                continue
            candidate_ids = _candidate_fact_ids_from_surface(
                claim,
                observed_facts,
                question_text=self._question_text,
            )
            if not candidate_ids:
                candidate_ids = _candidate_exact_negative_result_fact_ids(
                    claim,
                    observed_facts,
                )
            current_ids = _dedupe_ordered_strs(
                list(getattr(claim, "fact_ids", []) or [])
            )
            preserve_multi_source_binding = bool(
                preserve_confirmation_groups and len(current_ids) > 1
            )
            candidate_sets: List[List[str]] = []
            candidate_narrows_current = bool(
                candidate_ids
                and len(candidate_ids) < len(current_ids)
            )
            if (
                candidate_ids
                and candidate_ids != current_ids
                and not (
                    preserve_multi_source_binding
                    and candidate_narrows_current
                )
            ):
                candidate_sets.append(list(candidate_ids))
            if len(current_ids) > 1 and not preserve_multi_source_binding:
                candidate_sets.extend([[fact_id] for fact_id in current_ids])
            for replacement_ids in candidate_sets:
                candidate_envelope = copy.deepcopy(envelope)
                candidate_claim = next(
                    (
                        item
                        for item in list(
                            getattr(candidate_envelope, "claims", []) or []
                        )
                        if str(getattr(item, "id", "") or "").strip()
                        == claim_id
                    ),
                    None,
                )
                if candidate_claim is None:
                    break
                candidate_claim.fact_ids = list(replacement_ids)
                (
                    candidate_accepted,
                    candidate_rejected,
                    _candidate_reasons,
                ) = self._validate_answer_envelope(
                    candidate_envelope,
                    observed_facts,
                    forbidden_claims=contract.forbidden_claims,
                )
                if (
                    claim_id not in set(candidate_accepted)
                    or claim_id in set(candidate_rejected)
                    or not accepted_ids.issubset(set(candidate_accepted))
                ):
                    continue
                claim.fact_ids = list(replacement_ids)
                repaired_ids.append(claim_id)
                accepted_ids = set(candidate_accepted)
                rejected = list(candidate_rejected)
                break
        if repaired_ids:
            prior = list(
                getattr(envelope, "_fact_binding_repairs", []) or []
            )
            envelope._fact_binding_repairs = _dedupe_ordered_strs(
                prior + repaired_ids
            )
        return repaired_ids

    async def synthesise_envelope(
        self,
        contract: Any,
        observed_facts: List[Any],
        *,
        retry_reasons: Optional[List[str]] = None,
        preserved_claims: Optional[List[Any]] = None,
        pending_claims: Optional[List[Any]] = None,
        repair_candidates: Optional[List[dict[str, Any]]] = None,
        retrieval_candidate_assessments: Optional[
            List[dict[str, str]]
        ] = None,
        retrieval_attention_fact_ids: Optional[List[str]] = None,
        replace_whole_deliverable: bool = False,
    ) -> Any:
        """Ask the LLM to synthesise an AnswerEnvelope (verbatim from orchestrator)."""
        preserved_claim_list = list(preserved_claims or [])
        fact_index = {
            str(getattr(fact, "id", "") or "").strip(): fact
            for fact in observed_facts
            if str(getattr(fact, "id", "") or "").strip()
        }
        retrieval_attention_internal_ids = _dedupe_ordered_strs(
            [
                str(fact_id).strip()
                for fact_id in list(retrieval_attention_fact_ids or [])
                if str(fact_id).strip() in fact_index
            ]
        )
        preserved_fact_ids_ordered = _dedupe_ordered_strs(
            [
                str(fact_id)
                for claim in preserved_claim_list
                for fact_id in list(
                    getattr(claim, "fact_ids", []) or []
                )
                if str(fact_id)
            ]
        )
        preserved_fact_ids = {
            fact_id for fact_id in preserved_fact_ids_ordered
        }
        used_source_ids = {
            str(source_id)
            for claim in preserved_claim_list
            if str(getattr(claim, "claim_kind", "") or "")
            != "limitation"
            for fact_id in list(getattr(claim, "fact_ids", []) or [])
            for fact in [fact_index.get(str(fact_id))]
            if fact is not None
            for source_id in list(getattr(fact, "source_evidence_ids", []) or [])
            if str(source_id)
        }
        uncited_candidate_facts = [
            fact
            for fact in observed_facts
            if str(getattr(fact, "id", "") or "").strip()
            not in preserved_fact_ids
            and str(getattr(fact, "fact_kind", "") or "")
            not in {"limitation", "negative_result"}
        ]
        preferred_new_facts = (
            sorted(
                uncited_candidate_facts,
                key=lambda fact: bool(
                    used_source_ids.intersection(
                        {
                            str(source_id)
                            for source_id in list(
                                getattr(
                                    fact,
                                    "source_evidence_ids",
                                    [],
                                )
                                or []
                            )
                            if str(source_id)
                        }
                    )
                ),
            )
            if preserved_claim_list
            else []
        )
        preferred_object_ids = {id(fact) for fact in preferred_new_facts}
        facts_for_synthesis = [
            *preferred_new_facts,
            *[
                fact
                for fact in observed_facts
                if id(fact) not in preferred_object_ids
            ],
        ]
        repair_core_fact_ids = _dedupe_ordered_strs(
            [
                str(fact_id)
                for candidate in list(repair_candidates or [])
                if bool(candidate.get("preserve_semantic_core"))
                for fact_id in list(candidate.get("fact_ids", []) or [])
                if str(fact_id) in fact_index
            ]
        )
        assessed_retrieval_ids = {
            str(item.get("fact_id", "") or "").strip()
            for item in list(retrieval_candidate_assessments or [])
            if str(item.get("fact_id", "") or "").strip()
        }
        if assessed_retrieval_ids:
            assessed_source_ids = {
                str(source_id)
                for fact_id in assessed_retrieval_ids
                for fact in [fact_index.get(fact_id)]
                if fact is not None
                for source_id in list(
                    getattr(fact, "source_evidence_ids", []) or []
                )
                if str(source_id)
            }
            facts_for_synthesis = [
                fact
                for fact in facts_for_synthesis
                if not _is_retrieval_candidate_fact(fact)
                or (
                    bool(assessed_source_ids)
                    and assessed_source_ids.isdisjoint(
                        {
                            str(source_id)
                            for source_id in list(
                                getattr(
                                    fact,
                                    "source_evidence_ids",
                                    [],
                                )
                                or []
                            )
                            if str(source_id)
                        }
                    )
                )
                or str(getattr(fact, "id", "") or "").strip()
                in assessed_retrieval_ids
            ]
        if repair_core_fact_ids:
            repair_core_fact_id_set = set(repair_core_fact_ids)
            facts_for_synthesis = [
                *[
                    fact_index[fact_id]
                    for fact_id in repair_core_fact_ids
                ],
                *[
                    fact
                    for fact in facts_for_synthesis
                    if str(getattr(fact, "id", "") or "").strip()
                    not in repair_core_fact_id_set
                ],
            ]
        if not preserved_claim_list:
            facts_for_synthesis = _ordered_synthesis_facts(
                facts_for_synthesis,
                str(getattr(contract, "analysis_family", "") or ""),
            )
        if retrieval_attention_internal_ids:
            attention_id_set = set(retrieval_attention_internal_ids)
            facts_for_synthesis = [
                *[
                    fact_index[fact_id]
                    for fact_id in retrieval_attention_internal_ids
                ],
                *[
                    fact
                    for fact in facts_for_synthesis
                    if str(getattr(fact, "id", "") or "").strip()
                    not in attention_id_set
                ],
            ]
        fact_payloads, projected_to_internal_facts = _project_facts(
            facts_for_synthesis
        )
        semantic_search_fact_ids = {
            str(getattr(fact, "id", "") or "").strip()
            for fact in facts_for_synthesis
            if str(getattr(fact, "id", "") or "").strip()
            and "semantic_search"
            in " ".join(
                [
                    str(getattr(fact, "id", "") or ""),
                    *[
                        str(source_id or "")
                        for source_id in list(
                            getattr(fact, "source_evidence_ids", []) or []
                        )
                    ],
                ]
            ).casefold()
        }
        internal_to_projected_facts = {
            internal_id: projected_id
            for projected_id, internal_id in projected_to_internal_facts.items()
            if internal_id
        }
        projected_retrieval_assessments = [
            _project_retrieval_assessment(
                assessment,
                internal_to_projected_facts[
                    str(assessment.get("fact_id", ""))
                ],
            )
            for assessment in list(
                retrieval_candidate_assessments or []
            )
            if str(assessment.get("fact_id", ""))
            in internal_to_projected_facts
        ]
        supporting_retrieval_fact_ids = [
            str(item.get("fact_id", "") or "")
            for item in projected_retrieval_assessments
            if item.get("relation_to_requested_conclusion") == "supports"
        ]
        related_supporting_retrieval_fact_ids = [
            str(item.get("fact_id", "") or "")
            for item in projected_retrieval_assessments
            if item.get("relation_to_requested_conclusion")
            == "related_support"
        ]
        non_supporting_retrieval_fact_ids = [
            str(item.get("fact_id", "") or "")
            for item in projected_retrieval_assessments
            if item.get("topic_relation") in {"relevant", "marginal"}
            and item.get("relation_to_requested_conclusion")
            in {"counterevidence", "mixed_or_unclear"}
        ]
        confirmation_pressure = (
            "one-sided confirmation of a universal corpus claim"
            in {
                str(value or "").strip().casefold()
                for value in list(
                    getattr(contract, "forbidden_claims", []) or []
                )
            }
        )
        balanced_retrieval_synthesis = bool(
            confirmation_pressure
            and (
                supporting_retrieval_fact_ids
                or related_supporting_retrieval_fact_ids
            )
            and non_supporting_retrieval_fact_ids
        )
        preserved_payloads, _ = _project_claims(
            preserved_claim_list,
            prefix="p",
        )
        pending_payloads, _ = _project_claims(
            list(pending_claims or []),
            prefix="u",
        )
        _rewrite_claim_payload_fact_ids(
            preserved_payloads,
            internal_to_projected_facts,
        )
        _rewrite_claim_payload_fact_ids(
            pending_payloads,
            internal_to_projected_facts,
        )
        repair_payloads = copy.deepcopy(list(repair_candidates or []))
        _rewrite_claim_payload_fact_ids(
            repair_payloads,
            internal_to_projected_facts,
        )
        projected_retry_reasons = [
            _replace_internal_ids(
                str(reason),
                internal_to_projected_facts,
            )
            for reason in list(retry_reasons or [])
            if str(reason or "").strip()
        ]
        schema = copy.deepcopy(self._answer_envelope_schema())
        deliverable_kind = str(
            getattr(contract, "deliverable_kind", "") or ""
        )
        claims_schema = schema.get("schema", {}).get(
            "properties", {}
        ).get("claims", {})
        if fact_payloads and "minItems" not in claims_schema:
            # Empty claims are a valid representation only when there is no
            # evidence. With grounded facts available they turned successful
            # analyses into a generic refusal without giving the verifier
            # anything to classify.
            claims_schema["minItems"] = (
                2
                if str(getattr(contract, "deliverable_kind", "") or "")
                in {"analysis_report", "contrast_report", "overview"}
                else 1
            )
        required_claim_kind = ""
        requested_new_claim_count: int | None = None
        missing_keyness_interpretation = False
        missing_ngram_interpretation = False
        missing_word_sketch_units = False
        missing_word_sketch_interpretation = False
        missing_kwic_interpretation = False
        missing_robustness_answer = False
        focused_response_requirement_repair = False
        supporting_claim_kinds: List[str] = []
        ngram_missing_candidate_count = 0
        ngram_missing_plan = False
        response_requirements = list(
            getattr(contract, "response_requirements", []) or []
        )
        fulfilled_response_requirement_ids = {
            str(
                getattr(claim, "response_requirement_id", "") or ""
            ).strip()
            for claim in preserved_claim_list
            if str(
                getattr(claim, "response_requirement_id", "") or ""
            ).strip()
            and not list(
                getattr(
                    claim,
                    "_response_requirement_assignment_reasons",
                    [],
                )
                or []
            )
        }
        missing_response_requirements = [
            requirement
            for requirement in response_requirements
            if str(getattr(requirement, "id", "") or "").strip()
            not in fulfilled_response_requirement_ids
        ]
        carried_claims = [
            *preserved_claim_list,
            *list(pending_claims or []),
        ]
        if deliverable_kind == "method_advice" and carried_claims:
            requested_count = claims_schema.get("maxItems")
            if (
                isinstance(requested_count, int)
                and requested_count >= 0
                and claims_schema.get("minItems") == requested_count
            ):
                preserved_count = sum(
                    str(getattr(claim, "claim_kind", "") or "")
                    == "interpretation"
                    for claim in carried_claims
                )
                remaining_count = max(
                    0,
                    requested_count - preserved_count,
                )
                claims_schema["minItems"] = remaining_count
                claims_schema["maxItems"] = remaining_count
                requested_new_claim_count = remaining_count
                required_claim_kind = "interpretation"
        elif (
            deliverable_kind == "followup_questions"
            and carried_claims
        ):
            minimum = claims_schema.get("minItems", 3)
            maximum = claims_schema.get("maxItems", 5)
            preserved_count = sum(
                str(getattr(claim, "claim_kind", "") or "") == "followup"
                for claim in carried_claims
            )
            if isinstance(minimum, int) and isinstance(maximum, int):
                remaining_minimum = max(0, minimum - preserved_count)
                remaining_maximum = max(
                    remaining_minimum,
                    maximum - preserved_count,
                )
                claims_schema["minItems"] = remaining_minimum
                claims_schema["maxItems"] = remaining_maximum
                requested_new_claim_count = remaining_minimum
                required_claim_kind = "followup"
        elif preserved_claim_list:
            required_kinds = {
                "analysis_report": ("observation", "interpretation"),
                "contrast_report": ("observation", "interpretation"),
                "overview": ("observation", "interpretation"),
                "lookup_answer": ("observation",),
            }.get(deliverable_kind, ())
            present_kinds = {
                str(getattr(claim, "claim_kind", "") or "")
                for claim in preserved_claim_list
            }
            observation_texts = {
                " ".join(
                    str(getattr(claim, "text", "") or "").split()
                ).casefold()
                for claim in preserved_claim_list
                if str(getattr(claim, "claim_kind", "") or "")
                == "observation"
            }
            interpretation_texts = {
                " ".join(
                    str(getattr(claim, "text", "") or "").split()
                ).casefold()
                for claim in preserved_claim_list
                if str(getattr(claim, "claim_kind", "") or "")
                == "interpretation"
            }
            if (
                "interpretation" in present_kinds
                and interpretation_texts
                and interpretation_texts <= observation_texts
            ):
                # Relabelling the same proposition is not an interpretation.
                present_kinds.discard("interpretation")
            missing_kinds = [
                claim_kind
                for claim_kind in required_kinds
                if claim_kind not in present_kinds
            ]
            missing_reference_boundary = (
                _missing_requested_lexical_reference_boundary(
                    contract,
                    self._question_text,
                    preserved_claim_list,
                )
            )
            missing_robustness_answer = (
                not missing_reference_boundary
                and _missing_requested_lexical_robustness_answer(
                    contract,
                    self._question_text,
                    preserved_claim_list,
                    observed_facts,
                )
            )
            missing_keyness_interpretation = (
                not missing_reference_boundary
                and not missing_robustness_answer
                and _missing_requested_keyness_interpretation(
                    contract,
                    preserved_claim_list,
                    observed_facts,
                    interpretation_is_substantive=(
                        self._keyness_interpretation_complete
                    ),
                )
            )
            missing_ngram_interpretation = (
                _missing_requested_ngram_interpretation(
                    contract,
                    self._question_text,
                    preserved_claim_list,
                    observed_facts,
                )
            )
            missing_word_sketch_units = bool(
                str(getattr(contract, "analysis_family", "") or "")
                == "word_sketch_profile"
                and self._word_sketch_units_complete is not None
                and not self._word_sketch_units_complete(
                    preserved_claim_list,
                )
            )
            missing_word_sketch_interpretation = bool(
                str(getattr(contract, "analysis_family", "") or "")
                == "word_sketch_profile"
                and not missing_word_sketch_units
                and self._word_sketch_interpretation_complete is not None
                and not self._word_sketch_interpretation_complete(
                    preserved_claim_list,
                    observed_facts,
                )
            )
            if missing_ngram_interpretation:
                (
                    ngram_missing_candidate_count,
                    ngram_missing_plan,
                ) = _ngram_interpretation_repair_shape(
                    preserved_claim_list,
                    observed_facts,
                )
            missing_kwic_interpretation = (
                not missing_reference_boundary
                and not missing_robustness_answer
                and not missing_keyness_interpretation
                and not missing_ngram_interpretation
                and _missing_requested_kwic_interpretation(
                    contract,
                    preserved_claim_list,
                    observed_facts,
                    question_text=self._question_text,
                    reading_is_substantive=self._kwic_reading_complete,
                )
            )
            if missing_word_sketch_units:
                required_claim_kind = "observation"
                requested_new_claim_count = 1
                claims_schema["minItems"] = 1
                claims_schema["maxItems"] = 1
                claims_schema["items"]["properties"]["claim_kind"][
                    "enum"
                ] = [required_claim_kind]
            elif (
                missing_keyness_interpretation
                or missing_ngram_interpretation
                or missing_word_sketch_interpretation
                or missing_kwic_interpretation
            ):
                required_claim_kind = "interpretation"
                requested_new_claim_count = (
                    max(
                        1,
                        ngram_missing_candidate_count
                        + int(ngram_missing_plan),
                    )
                    if missing_ngram_interpretation
                    else 1
                )
                if missing_kwic_interpretation:
                    # One atomic repair keeps the model on a single evidence
                    # level. Multiple slots repeatedly produced a second,
                    # unsupported participant or attachment analysis.
                    claims_schema["minItems"] = 1
                    claims_schema["maxItems"] = 1
                else:
                    claims_schema["minItems"] = requested_new_claim_count
                    claims_schema["maxItems"] = requested_new_claim_count
                claims_schema["items"]["properties"]["claim_kind"][
                    "enum"
                ] = [required_claim_kind]
            elif missing_reference_boundary:
                required_claim_kind = "limitation"
                requested_new_claim_count = 1
                claims_schema["minItems"] = 1
                claims_schema["maxItems"] = 1
                claims_schema["items"]["properties"]["claim_kind"][
                    "enum"
                ] = [required_claim_kind]
            elif missing_robustness_answer:
                required_claim_kind = "interpretation"
                requested_new_claim_count = 1
                claims_schema["minItems"] = 1
                claims_schema["maxItems"] = 1
                claims_schema["items"]["properties"]["claim_kind"][
                    "enum"
                ] = [required_claim_kind]
            elif len(missing_kinds) == 1:
                required_claim_kind = missing_kinds[0]
                requested_new_claim_count = 1
                claims_schema["minItems"] = 1
                claims_schema["maxItems"] = 1
                claims_schema["items"]["properties"]["claim_kind"][
                    "enum"
                ] = [required_claim_kind]
            elif repair_payloads:
                repair_count = min(len(repair_payloads), 4)
                claims_schema["minItems"] = 1
                claims_schema["maxItems"] = max(1, repair_count)
        ngram_candidate_recovery = bool(
            not preserved_claim_list
            and repair_candidates
            and str(getattr(contract, "analysis_family", "") or "")
            == "ngram_profile"
            and deliverable_kind == "analysis_report"
            and any(
                str(getattr(fact, "fact_kind", "") or "")
                == "ranked_row"
                and "interpretation_anchor"
                in {
                    str(value)
                    for value in list(
                        getattr(fact, "supports_claims", []) or []
                    )
                }
                for fact in observed_facts
            )
        )
        if ngram_candidate_recovery:
            missing_ngram_interpretation = True
            required_claim_kind = "interpretation"
            (
                ngram_missing_candidate_count,
                ngram_missing_plan,
            ) = _ngram_interpretation_repair_shape([], observed_facts)
            requested_new_claim_count = max(
                1,
                ngram_missing_candidate_count + int(ngram_missing_plan),
            )
            claims_schema["minItems"] = requested_new_claim_count
            claims_schema["maxItems"] = requested_new_claim_count
            claims_schema["items"]["properties"]["claim_kind"][
                "enum"
            ] = [required_claim_kind]
        kwic_reading_recovery = bool(
            not preserved_claim_list
            and repair_candidates
            and str(getattr(contract, "analysis_family", "") or "")
            == "kwic_context"
            and deliverable_kind == "analysis_report"
            and (
                any(
                    str(getattr(fact, "fact_kind", "") or "")
                    == "kwic_example"
                    and "erweiter"
                    in str(
                        getattr(fact, "statement", "") or ""
                    ).casefold()
                    and "kontext"
                    in str(
                        getattr(fact, "statement", "") or ""
                    ).casefold()
                    for fact in observed_facts
                )
                or _is_multirow_kwic_analysis_request(
                    self._question_text,
                    observed_facts,
                )
            )
        )
        if kwic_reading_recovery:
            missing_kwic_interpretation = True
            required_claim_kind = "interpretation"
            requested_new_claim_count = 1
            claims_schema["minItems"] = 1
            claims_schema["maxItems"] = 1
            claims_schema["items"]["properties"]["claim_kind"][
                "enum"
            ] = [required_claim_kind]
        response_requirement_schema = claims_schema.get("items", {}).get(
            "properties", {}
        ).get("response_requirement_id")
        if isinstance(response_requirement_schema, dict):
            missing_requirement_ids = [
                str(getattr(requirement, "id", "") or "").strip()
                for requirement in missing_response_requirements
                if str(getattr(requirement, "id", "") or "").strip()
            ]
            focused_response_requirement_repair = bool(
                missing_response_requirements
                and (
                    projected_retry_reasons
                    or preserved_payloads
                    or pending_payloads
                    or repair_payloads
                )
            )
            if missing_response_requirements:
                slot_kinds = _dedupe_ordered_strs(
                    [
                        str(
                            getattr(
                                requirement,
                                "claim_kind",
                                "interpretation",
                            )
                            or "interpretation"
                        )
                        for requirement in missing_response_requirements
                    ]
                )
                claim_kind_schema = claims_schema["items"]["properties"][
                    "claim_kind"
                ]
                claim_kind_schema["enum"] = _dedupe_ordered_strs(
                    list(claim_kind_schema.get("enum", []) or [])
                    + slot_kinds
                )
                if required_claim_kind and any(
                    kind != required_claim_kind for kind in slot_kinds
                ):
                    required_claim_kind = ""
                if focused_response_requirement_repair:
                    required_kinds = {
                        "analysis_report": ("observation", "interpretation"),
                        "contrast_report": ("observation", "interpretation"),
                        "overview": ("observation", "interpretation"),
                        "lookup_answer": ("observation",),
                    }.get(deliverable_kind, ())
                    present_claim_kinds = {
                        str(getattr(claim, "claim_kind", "") or "")
                        for claim in preserved_claim_list
                    }
                    covered_claim_kinds = present_claim_kinds.union(
                        slot_kinds
                    )
                    supporting_claim_kinds = [
                        claim_kind
                        for claim_kind in required_kinds
                        if claim_kind not in covered_claim_kinds
                    ]
                    if self._separate_hypothesis_layers:
                        has_standalone_interpretation = any(
                            str(
                                getattr(claim, "claim_kind", "") or ""
                            )
                            == "interpretation"
                            and _EXPLICIT_TESTABLE_HYPOTHESIS_PATTERN.search(
                                str(getattr(claim, "text", "") or "")
                            )
                            is None
                            for claim in preserved_claim_list
                        )
                        if (
                            not has_standalone_interpretation
                            and "interpretation"
                            not in supporting_claim_kinds
                        ):
                            supporting_claim_kinds.append(
                                "interpretation"
                            )
                    minimum_new_claims = (
                        len(missing_response_requirements)
                        + len(supporting_claim_kinds)
                    )
                    maximum_new_claims = minimum_new_claims
                    claims_schema["minItems"] = minimum_new_claims
                    claims_schema["maxItems"] = maximum_new_claims
                    requested_new_claim_count = (
                        minimum_new_claims
                        if minimum_new_claims == maximum_new_claims
                        else None
                    )
                    required_claim_kind = (
                        slot_kinds[0]
                        if len(slot_kinds) == 1
                        and not supporting_claim_kinds
                        else ""
                    )
                    claim_kind_schema["enum"] = _dedupe_ordered_strs(
                        list(claim_kind_schema.get("enum", []) or [])
                        + supporting_claim_kinds
                    )
                    completion_checks = _dedupe_ordered_strs(
                        [
                            str(check)
                            for requirement in missing_response_requirements
                            for check in list(
                                (
                                    requirement.completion_checks()
                                    if callable(
                                        getattr(
                                            requirement,
                                            "completion_checks",
                                            None,
                                        )
                                    )
                                    else []
                                )
                                or []
                            )
                            if str(check or "").strip()
                        ]
                    )
                    text_schema = claims_schema["items"]["properties"][
                        "text"
                    ]
                    text_schema["description"] = (
                        "Ein natürlicher, eigenständiger Claim, der genau "
                        "einen fehlenden Nutzer-Slot vollständig erfüllt. "
                        "Verbindliche semantische Prüfbedingungen: "
                        + " ".join(completion_checks)
                    )
                else:
                    minimum = max(
                        int(claims_schema.get("minItems", 0) or 0),
                        len(missing_response_requirements),
                    )
                    current_maximum = int(
                        claims_schema.get("maxItems", minimum) or minimum
                    )
                    maximum = max(
                        minimum,
                        min(current_maximum, minimum + 4),
                    )
                    claims_schema["minItems"] = minimum
                    claims_schema["maxItems"] = maximum
            response_requirement_schema["enum"] = (
                ["", *missing_requirement_ids]
                if supporting_claim_kinds
                or not focused_response_requirement_repair
                else missing_requirement_ids
            )
        preferred_internal_fact_ids = _balanced_fact_ids_by_source(
            preferred_new_facts,
            max_items=24,
        )
        preferred_projected_fact_ids = [
            internal_to_projected_facts[fact_id]
            for fact_id in preferred_internal_fact_ids
            if fact_id in internal_to_projected_facts
        ]
        retrieval_attention_projected_ids = [
            internal_to_projected_facts[fact_id]
            for fact_id in retrieval_attention_internal_ids
            if fact_id in internal_to_projected_facts
        ]
        preferred_projected_fact_ids = _dedupe_ordered_strs(
            retrieval_attention_projected_ids
            + preferred_projected_fact_ids
        )[:24]
        allowed_projected_fact_ids = list(
            projected_to_internal_facts
        )
        restrict_to_unused_observation_facts = False
        restrict_to_required_interpretation_facts = False
        focus_initial_kwic_evidence = False
        ordinary_semantic_topicality = bool(
            self._needs_semantic_retrieval_adjudication(contract)
            and not confirmation_pressure
            and projected_retrieval_assessments
        )
        if ordinary_semantic_topicality:
            off_topic_projected_ids = {
                str(item.get("fact_id", "") or "")
                for item in projected_retrieval_assessments
                if item.get("topic_relation") == "off_topic"
            }
            if off_topic_projected_ids:
                allowed_projected_fact_ids = [
                    fact_id
                    for fact_id in allowed_projected_fact_ids
                    if fact_id not in off_topic_projected_ids
                ]
                preferred_projected_fact_ids = [
                    fact_id
                    for fact_id in preferred_projected_fact_ids
                    if fact_id not in off_topic_projected_ids
                ]
                # The full audit remains available to verification and the
                # renderer, while synthesis sees only topically admissible
                # source rows plus the normal method/provenance facts.
                restrict_to_required_interpretation_facts = True
        if (
            str(getattr(contract, "analysis_family", "") or "")
            == "kwic_context"
            and deliverable_kind == "analysis_report"
            and not preserved_claim_list
            and not kwic_reading_recovery
        ):
            focused_internal_ids: List[str] = []
            multirow_kwic_request = _is_multirow_kwic_analysis_request(
                self._question_text,
                observed_facts,
            )
            if multirow_kwic_request:
                sampled_source_ids: List[str] = []
                for fact in facts_for_synthesis:
                    statement = str(getattr(fact, "statement", "") or "")
                    if (
                        str(getattr(fact, "fact_kind", "") or "")
                        == "metadata"
                        and any(
                            marker in statement.casefold()
                            for marker in (
                                "stichprob",
                                "sample",
                                "seed=",
                                "population=",
                            )
                        )
                    ):
                        sampled_source_ids.extend(
                            str(source_id)
                            for source_id in list(
                                getattr(
                                    fact,
                                    "source_evidence_ids",
                                    [],
                                )
                                or []
                            )
                            if str(source_id)
                        )
                selected_sample_sources = set(
                    sampled_source_ids[-1:]
                )

                def belongs_to_selected_sample(fact: Any) -> bool:
                    if not selected_sample_sources:
                        return True
                    return not selected_sample_sources.isdisjoint(
                        {
                            str(source_id)
                            for source_id in list(
                                getattr(
                                    fact,
                                    "source_evidence_ids",
                                    [],
                                )
                                or []
                            )
                            if str(source_id)
                        }
                    )

                provenance_facts: List[Any] = []
                kwic_facts: List[Any] = []
                for fact in facts_for_synthesis:
                    fact_id = str(getattr(fact, "id", "") or "").strip()
                    statement = str(getattr(fact, "statement", "") or "")
                    kind = str(getattr(fact, "fact_kind", "") or "")
                    statement_lower = statement.casefold()
                    if not fact_id or not belongs_to_selected_sample(fact):
                        continue
                    if kind == "kwic_example":
                        kwic_facts.append(fact)
                    elif kind == "count" or (
                        kind == "metadata"
                        and any(
                            marker in statement_lower
                            for marker in (
                                "stichprob",
                                "sample",
                                "seed=",
                                "population=",
                            )
                        )
                    ) or kind == "limitation":
                        provenance_facts.append(fact)
                provenance_facts.sort(
                    key=lambda fact: {
                        "count": 0,
                        "metadata": 1,
                        "limitation": 2,
                    }.get(
                        str(getattr(fact, "fact_kind", "") or ""),
                        3,
                    )
                )
                focused_internal_ids.extend(
                    str(getattr(fact, "id", "") or "").strip()
                    for fact in provenance_facts[:4]
                )
                focused_internal_ids.extend(
                    str(getattr(fact, "id", "") or "").strip()
                    for fact in kwic_facts[
                        : max(0, 24 - len(focused_internal_ids))
                    ]
                )
            else:
                for wanted in ("surface", "count", "expanded"):
                    for fact in facts_for_synthesis:
                        fact_id = str(getattr(fact, "id", "") or "").strip()
                        statement = str(getattr(fact, "statement", "") or "")
                        kind = str(getattr(fact, "fact_kind", "") or "")
                        is_expanded = bool(
                            kind == "kwic_example"
                            and "erweiter" in statement.casefold()
                            and "kontext" in statement.casefold()
                        )
                        matches = (
                            wanted == "surface"
                            and kind == "kwic_example"
                            and not is_expanded
                        ) or (
                            wanted == "count" and kind == "count"
                        ) or (
                            wanted == "expanded" and is_expanded
                        )
                        if matches and fact_id:
                            focused_internal_ids.append(fact_id)
                            break
            focused_projected_ids = [
                internal_to_projected_facts[fact_id]
                for fact_id in focused_internal_ids
                if fact_id in internal_to_projected_facts
            ]
            if focused_projected_ids:
                allowed_projected_fact_ids = focused_projected_ids
                focus_initial_kwic_evidence = True
        if (
            required_claim_kind == "observation"
            and preserved_payloads
            and preferred_projected_fact_ids
            and not retrieval_attention_projected_ids
        ):
            # A requested *new* overview observation must actually draw on an
            # unused evidence source. Otherwise a local model can satisfy the
            # JSON item count by paraphrasing the same inventory repeatedly.
            # This constrains evidence provenance, not the finding or wording.
            allowed_projected_fact_ids = list(
                preferred_projected_fact_ids
            )
            restrict_to_unused_observation_facts = True
        if (
            missing_word_sketch_units
            or missing_keyness_interpretation
            or missing_ngram_interpretation
            or missing_word_sketch_interpretation
            or missing_kwic_interpretation
        ):
            required_internal_fact_ids = [
                str(getattr(fact, "id", "") or "").strip()
                for fact in observed_facts
                if (
                    missing_word_sketch_units
                    and str(getattr(fact, "fact_kind", "") or "")
                    == "ranked_row"
                    and any(
                        "word_sketch" in str(source_id or "").casefold()
                        for source_id in list(
                            getattr(fact, "source_evidence_ids", []) or []
                        )
                    )
                )
                or (
                    missing_keyness_interpretation
                    and str(getattr(fact, "fact_kind", "") or "")
                    == "ranked_row"
                    and "interpretation_anchor"
                    in {
                        str(value)
                        for value in list(
                            getattr(fact, "supports_claims", []) or []
                        )
                    }
                )
                or (
                    missing_ngram_interpretation
                    and str(getattr(fact, "fact_kind", "") or "")
                    == "ranked_row"
                    and "interpretation_anchor"
                    in {
                        str(value)
                        for value in list(
                            getattr(fact, "supports_claims", []) or []
                        )
                    }
                )
                or (
                    missing_word_sketch_interpretation
                    and str(getattr(fact, "fact_kind", "") or "")
                    == "metadata"
                    and any(
                        "word_sketch" in str(source_id or "").casefold()
                        for source_id in list(
                            getattr(fact, "source_evidence_ids", []) or []
                        )
                    )
                )
                or (
                    missing_kwic_interpretation
                    and str(getattr(fact, "fact_kind", "") or "")
                    == "kwic_example"
                    and (
                        (
                            "erweiter"
                            in str(
                                getattr(fact, "statement", "") or ""
                            ).casefold()
                            and "kontext"
                            in str(
                                getattr(fact, "statement", "") or ""
                            ).casefold()
                        )
                        or _is_multirow_kwic_analysis_request(
                            self._question_text,
                            observed_facts,
                        )
                    )
                )
            ]
            if missing_word_sketch_units:
                required_internal_fact_ids = required_internal_fact_ids[:1]
            required_projected_fact_ids = [
                internal_to_projected_facts[fact_id]
                for fact_id in required_internal_fact_ids
                if fact_id in internal_to_projected_facts
            ]
            if required_projected_fact_ids:
                allowed_projected_fact_ids = list(
                    required_projected_fact_ids
                )
                restrict_to_required_interpretation_facts = True
        balanced_retrieval_fact_ids = _dedupe_ordered_strs(
            supporting_retrieval_fact_ids
            + related_supporting_retrieval_fact_ids
            + non_supporting_retrieval_fact_ids
        )
        # The exhaustive audit and renderer account for off-topic retrieval
        # noise. Feeding that noise into the interpretation turn pressures the
        # model to invent a common reading for material already found irrelevant.
        retrieval_synthesis_fact_ids = list(balanced_retrieval_fact_ids)
        if confirmation_pressure:
            representative_fact_ids = _representative_retrieval_fact_ids(
                projected_retrieval_assessments,
                fact_payloads,
            )
            if representative_fact_ids:
                retrieval_synthesis_fact_ids = representative_fact_ids
                reporting_diagnostics = dict(
                    self._retrieval_audit_diagnostics.get("reporting", {})
                    or {}
                )
                reporting_diagnostics.update(
                    {
                        "strategy": "relation_object_strata",
                        "selected_representative_fact_ids": [
                            projected_to_internal_facts[fact_id]
                            for fact_id in representative_fact_ids
                            if fact_id in projected_to_internal_facts
                        ],
                    }
                )
                self._retrieval_audit_diagnostics[
                    "reporting"
                ] = reporting_diagnostics
        preserved_retrieval_interpretation = any(
            str(claim.get("claim_kind", "") or "") == "interpretation"
            for claim in preserved_payloads
        )
        focused_retrieval_repair = bool(
            retrieval_attention_projected_ids
            and not replace_whole_deliverable
            and (preserved_payloads or pending_payloads)
            and preserved_retrieval_interpretation
            and not focused_response_requirement_repair
            and not restrict_to_required_interpretation_facts
            and not restrict_to_unused_observation_facts
        )
        grouped_confirmation_retrieval_repair = False
        if focused_retrieval_repair:
            assessment_focus = {
                str(item.get("fact_id", "") or ""): (
                    str(
                        item.get("relation_to_requested_conclusion", "")
                        or ""
                    ),
                    str(item.get("evaluated_object_type", "") or ""),
                )
                for item in projected_retrieval_assessments
            }
            compatible_groups: dict[
                tuple[str, str], List[str]
            ] = {}
            attention_positions = {
                fact_id: position
                for position, fact_id in enumerate(
                    retrieval_attention_projected_ids
                )
            }
            for fact_id in retrieval_attention_projected_ids:
                compatible_groups.setdefault(
                    assessment_focus.get(fact_id, ("", fact_id)),
                    [],
                ).append(fact_id)
            selected_attention_ids = min(
                compatible_groups.values(),
                key=lambda fact_ids: (
                    min(
                        self._focused_repair_attempt_counts.get(fact_id, 0)
                        for fact_id in fact_ids
                    ),
                    -len(fact_ids),
                    min(attention_positions[fact_id] for fact_id in fact_ids),
                ),
            )[:4]
            for fact_id in selected_attention_ids:
                self._focused_repair_attempt_counts[fact_id] = (
                    self._focused_repair_attempt_counts.get(fact_id, 0) + 1
                )
            retrieval_attention_projected_ids = list(
                selected_attention_ids
            )
            grouped_confirmation_retrieval_repair = (
                len(retrieval_attention_projected_ids) > 1
            )
            allowed_projected_fact_ids = list(
                retrieval_attention_projected_ids
            )
            required_claim_kind = "interpretation"
            requested_new_claim_count = None
            repair_claim_count = min(
                3,
                len(retrieval_attention_projected_ids),
            )
            claims_schema["minItems"] = 1
            claims_schema["maxItems"] = repair_claim_count
            claim_properties = claims_schema["items"]["properties"]
            claim_properties["text"]["description"] = (
                "Eine beleggebundene lokale Mustersynthese oder ein "
                "analytisch wichtiger Einzelbefund. Alle Prädikate eines "
                "Musterclaims müssen für seine zitierten Passagen gemeinsam "
                "gelten; Unterschiede bleiben ausdrücklich getrennt."
            )
            claim_properties["claim_kind"]["enum"] = ["interpretation"]
            claim_properties["assertion_level"]["enum"] = ["tentative"]
            fact_id_schema = claim_properties["fact_ids"]
            fact_id_schema["minItems"] = 1
            fact_id_schema["maxItems"] = len(
                retrieval_attention_projected_ids
            )
            fact_id_schema["uniqueItems"] = True
            fact_id_schema["items"]["enum"] = list(
                allowed_projected_fact_ids
            )
            restrict_to_required_interpretation_facts = True
        related_only_retrieval_synthesis = bool(
            confirmation_pressure
            and related_supporting_retrieval_fact_ids
            and not supporting_retrieval_fact_ids
            and not non_supporting_retrieval_fact_ids
            and balanced_retrieval_fact_ids
            and (
                replace_whole_deliverable
                or not preserved_retrieval_interpretation
            )
            and not focused_retrieval_repair
        )
        focused_balanced_retrieval = bool(
            (
                balanced_retrieval_synthesis
                or related_only_retrieval_synthesis
            )
            and balanced_retrieval_fact_ids
            and (
                replace_whole_deliverable
                or not preserved_retrieval_interpretation
            )
        )
        if focused_balanced_retrieval:
            # Ask for a small analytical synthesis rather than one claim per
            # hit. Each claim remains source-auditable because it must cite
            # every passage it actually synthesises; unrelated outliers stay
            # separate instead of being forced into a common pattern.
            allowed_projected_fact_ids = _dedupe_ordered_strs(
                retrieval_synthesis_fact_ids
            )
            required_claim_kind = "interpretation"
            requested_new_claim_count = None
            synthesis_claim_minimum = (
                1 if len(allowed_projected_fact_ids) == 1 else 2
            )
            synthesis_claim_maximum = min(
                6,
                max(1, len(allowed_projected_fact_ids)),
            )
            claims_schema["minItems"] = synthesis_claim_minimum
            claims_schema["maxItems"] = synthesis_claim_maximum
            claim_properties = claims_schema["items"]["properties"]
            claim_properties["text"]["maxLength"] = 700
            claim_properties["text"]["description"] = (
                "Eine eigenständige, gehaltvolle Interpretation eines klaren "
                "Deutungsmusters in allen dafür zitierten sichtbaren Passagen "
                "oder eines analytisch wichtigen Einzelbefunds. Nur wirklich "
                "gleichartige Relationen gruppieren; keine Nutzerhypothese, "
                "Korpusgeltung, technischen Fact-IDs oder erfundenen Rollen."
            )
            claim_properties["claim_kind"]["enum"] = ["interpretation"]
            claim_properties["assertion_level"]["enum"] = ["tentative"]
            fact_id_schema = claim_properties["fact_ids"]
            fact_id_schema["minItems"] = 1
            fact_id_schema["maxItems"] = len(allowed_projected_fact_ids)
            fact_id_schema["uniqueItems"] = True
            fact_id_schema["items"]["enum"] = list(
                allowed_projected_fact_ids
            )
            restrict_to_required_interpretation_facts = True
        if focused_response_requirement_repair:
            focused_requirement_ids = _focused_requirement_fact_ids(
                fact_payloads,
                question_text=self._question_text,
                requirements=list(missing_response_requirements),
                generic_fact_ids=preferred_projected_fact_ids,
            )
            repair_core_projected_ids = [
                internal_to_projected_facts[fact_id]
                for fact_id in repair_core_fact_ids
                if fact_id in internal_to_projected_facts
            ]
            if focused_requirement_ids:
                allowed_projected_fact_ids = _dedupe_ordered_strs(
                    repair_core_projected_ids + focused_requirement_ids
                )
                preferred_projected_fact_ids = list(
                    allowed_projected_fact_ids
                )
                restrict_to_required_interpretation_facts = True
            elif repair_core_projected_ids or preferred_projected_fact_ids:
                allowed_projected_fact_ids = _dedupe_ordered_strs(
                    repair_core_projected_ids
                    + preferred_projected_fact_ids
                )
                preferred_projected_fact_ids = list(
                    allowed_projected_fact_ids
                )
                restrict_to_required_interpretation_facts = True
        allowed_projected_fact_id_set = set(
            allowed_projected_fact_ids
        )
        visible_fact_payloads = (
            [
                fact
                for fact in fact_payloads
                if fact.get("id") in allowed_projected_fact_id_set
            ]
            if (
                restrict_to_unused_observation_facts
                or restrict_to_required_interpretation_facts
                or focus_initial_kwic_evidence
            )
            else fact_payloads
        )
        if focus_initial_kwic_evidence:
            payload_by_id = {
                str(fact.get("id", "")): fact
                for fact in visible_fact_payloads
            }
            visible_fact_payloads = [
                payload_by_id[fact_id]
                for fact_id in allowed_projected_fact_ids
                if fact_id in payload_by_id
            ]
        if focused_response_requirement_repair:
            visible_fact_payloads = [
                _compact_requirement_fact_payload(payload)
                for payload in visible_fact_payloads
            ]
        if missing_word_sketch_units or missing_word_sketch_interpretation:
            envelope_properties = schema.get("schema", {}).get(
                "properties", {}
            )
            for field_name in ("evidence_gaps", "blocked_claims"):
                field_schema = envelope_properties.get(field_name)
                if isinstance(field_schema, dict):
                    field_schema["minItems"] = 0
                    field_schema["maxItems"] = 0
        if focused_balanced_retrieval or focused_retrieval_repair:
            # The audited opposite direction is evidence to interpret, not an
            # evidence gap. Allowing these fields let the model hide required
            # counter-readings outside the verifiable claim partition.
            envelope_properties = schema.get("schema", {}).get(
                "properties", {}
            )
            for field_name in ("evidence_gaps", "blocked_claims"):
                field_schema = envelope_properties.get(field_name)
                if isinstance(field_schema, dict):
                    field_schema["minItems"] = 0
                    field_schema["maxItems"] = 0
        if missing_word_sketch_interpretation:
            visible_fact_payloads = [
                _word_sketch_relation_only_fact_payload(payload)
                for payload in visible_fact_payloads
            ]
        fresh_required_slot = bool(
            required_claim_kind
            and (
                preserved_payloads
                or ngram_candidate_recovery
                or kwic_reading_recovery
            )
        )
        # Ordered items and interpretations repair more reliably when the
        # rejected idea and its concrete reasons remain visible. The payload
        # labels every draft as non-evidence, preserving the model's insight
        # without licensing a rejected premise. Fresh factual observations
        # remain isolated so a bad draft cannot seed a new empirical claim.
        # Repair drafts are explicitly non-evidence. Keeping their rejected
        # wording and atomic reasons lets the model delete only the unsafe
        # proposition instead of inventing a wholly new participant relation.
        keep_repair_ideas = (
            fresh_required_slot
            and (
                deliverable_kind
                in {"method_advice", "followup_questions"}
                or required_claim_kind == "interpretation"
            )
        )
        visible_repair_payloads = (
            []
            if restrict_to_unused_observation_facts
            or (fresh_required_slot and not keep_repair_ideas)
            else repair_payloads
        )
        if missing_word_sketch_units or missing_word_sketch_interpretation:
            # Rejected prevalence, role and threshold claims are especially
            # sticky for local models. The focused repair has sufficient direct
            # evidence, so do not seed it with old prose.
            visible_repair_payloads = []
        if focused_response_requirement_repair:
            # Rejected slot prose is especially sticky: a weak model tends to
            # copy the same invented threshold while changing only its label.
            # A semantically verified hypothesis that failed *only* because
            # its falsifier is missing is different: retaining that bounded
            # core avoids throwing away valid analysis on every retry.
            visible_repair_payloads = [
                payload
                for payload in visible_repair_payloads
                if payload.get("revision_status")
                == "verified_slot_core_missing_completion"
            ]
        if focused_balanced_retrieval or focused_retrieval_repair:
            visible_repair_payloads = []
        visible_preserved_payloads = preserved_payloads
        if (
            (missing_word_sketch_units or missing_word_sketch_interpretation)
            and preserved_payloads
        ):
            # Refeeding lexical rows tempts smaller models to repeat values or
            # infer phrases instead of filling the one focused missing slot.
            visible_preserved_payloads = [
                {
                    **payload,
                    "text": (
                        "Bereits verifizierte direkte Word-Sketch-Beobachtung; "
                        "nicht wiederholen."
                    ),
                    "fact_ids": [],
                }
                for payload in preserved_payloads
            ]
        # H8/F1: die pauschale kwic_context-Blankung stammt aus der
        # Presence-Aera. Fuer echte Presence-Lookups (lookup_answer u. ae.)
        # bleibt sie richtig: eine Ein-Beleg-Antwort soll nicht aus einem
        # Alt-Entwurf aufgeblaeht werden. Fuer die Gebrauchsanalyse
        # (deliverable_kind analysis_report) ist der Entwurf dagegen der
        # Traeger der Mehrbeleg-Synthese; er bleibt sichtbar und ist wie
        # ueberall Nicht-Evidenz (draft_is_evidence=False).
        kwic_presence_draft_blank = (
            str(getattr(contract, "analysis_family", "") or "")
            == "kwic_context"
            and deliverable_kind != "analysis_report"
        )
        draft_answer = (
            ""
            if restrict_to_unused_observation_facts
            or fresh_required_slot
            or focused_retrieval_repair
            or focused_balanced_retrieval
            or kwic_presence_draft_blank
            else self._initial_draft
        )
        if (
            fresh_required_slot
            and required_claim_kind == "interpretation"
            and not restrict_to_unused_observation_facts
            and not focused_retrieval_repair
            and not focused_balanced_retrieval
            and not kwic_presence_draft_blank
            and not missing_word_sketch_interpretation
        ):
            # P8: fehlt in einem analysis_report die Deutung, verlangt der
            # Retry genau einen interpretation-Claim, und fresh_required_slot
            # leerte dafuer den ganzen Entwurf. Im Turn
            # gemischt-leichte-sprache-naeherung trug der Entwurf (1491
            # Zeichen) je Kandidat log_ratio und pmw, der Endtext-Rumpf (3315
            # Zeichen) danach 17 mal "sichtbare Keyness-Zeile" und keine
            # einzige Dezimalzahl.
            #
            # Das Wrap-up-Format schreibt eine Sektion "Deutung" vor, aber die
            # Modelle halten sich nicht daran: von den zehn Turns in
            # evaluation/deutung/harnisch_nachher.jsonl tragen genau zwei eine
            # solche Sektion, und der gemessene Turn ist keiner davon. Sein
            # Entwurf traegt "**Setup:**" und "**Grenzen:**" und schreibt die
            # Deutung als freien Absatz. Eine reine Sektionsprobe waere hier
            # also wirkungslos geblieben, deshalb der Rueckfall in
            # ``entwurfsdeutung``.
            #
            # Der Rueckfall gibt nur ziffernfreie Prosa ausserhalb der vier
            # Sektionen zurueck. Damit bleibt wahr, was der Filter fuer
            # focused_response_requirement_repair weiter oben schuetzt: kein
            # erfundener Schwellwert kann zurueckkopiert werden, denn ein
            # Schwellwert ist eine Zahl. Kernbefund, Belege und Grenzen
            # bleiben ohnehin draussen, und der Text ist Nicht-Evidenz
            # (draft_is_evidence=False).
            draft_answer = entwurfsdeutung(self._initial_draft)
        active_retrieval_assessments = (
            [
                assessment
                for assessment in projected_retrieval_assessments
                if str(assessment.get("fact_id", "") or "")
                in set(allowed_projected_fact_ids)
            ]
            if (
                focused_retrieval_repair
                or focused_balanced_retrieval
                or ordinary_semantic_topicality
            )
            else list(projected_retrieval_assessments)
        )
        active_supporting_retrieval_fact_ids = [
            str(item.get("fact_id", "") or "")
            for item in active_retrieval_assessments
            if item.get("relation_to_requested_conclusion") == "supports"
        ]
        active_related_supporting_retrieval_fact_ids = [
            str(item.get("fact_id", "") or "")
            for item in active_retrieval_assessments
            if item.get("relation_to_requested_conclusion")
            == "related_support"
        ]
        active_non_supporting_retrieval_fact_ids = [
            str(item.get("fact_id", "") or "")
            for item in active_retrieval_assessments
            if item.get("topic_relation") in {"relevant", "marginal"}
            and item.get("relation_to_requested_conclusion")
            in {"counterevidence", "mixed_or_unclear"}
        ]
        active_off_topic_retrieval_fact_ids = [
            str(item.get("fact_id", "") or "")
            for item in active_retrieval_assessments
            if item.get("topic_relation") == "off_topic"
        ]
        if projected_to_internal_facts:
            fact_ids_schema = (
                schema["schema"]["properties"]["claims"]["items"][
                    "properties"
                ]["fact_ids"]
            )
            if not focused_balanced_retrieval:
                fact_ids_schema["minItems"] = 1
            fact_ids_schema["items"]["enum"] = list(
                allowed_projected_fact_ids
            )
        if (
            missing_keyness_interpretation
            or missing_ngram_interpretation
            or missing_kwic_interpretation
        ):
            assertion_schema = (
                claims_schema.get("items", {})
                .get("properties", {})
                .get("assertion_level")
            )
            if isinstance(assertion_schema, dict):
                assertion_schema["enum"] = ["tentative"]
        elif (
            required_claim_kind == "interpretation"
            and deliverable_kind != "method_advice"
        ):
            # A focused interpretive repair must not label a hypothesis as an
            # exact empirical result. This constrains epistemic status, not the
            # model's substantive interpretation.
            assertion_schema = (
                claims_schema.get("items", {})
                .get("properties", {})
                .get("assertion_level")
            )
            if isinstance(assertion_schema, dict):
                assertion_schema["enum"] = ["tentative"]
        stage_instruction = (
            "Entwickle eine kohärente, eigenständige Analyse in "
            "Modellreihenfolge. Trenne empirische Prämissen von "
            "ihrer Interpretation, aber erzwinge keine "
            "Beobachtungen-dann-Interpretation-Schablone. Zahlen "
            "und Zitate müssen wortgetreu belegt sein; "
            "evidenzgebundene Deutung, Auslegung und Hypothesen "
            "sind ausdrücklich erwünscht. Schreibe in derselben Sprache wie "
            "die Nutzerfrage."
        )
        family_guidance = {
            "semantic_retrieval": (
                "Behandle die sichtbaren Zeilen als nach Ähnlichkeit zur "
                "Suchanfrage geordnete Retrieval-Kandidaten, nicht als zentrale, "
                "häufige, typische oder repräsentative Passagen des Korpus. "
                "Die Themenrelevanz wurde unabhängig geprüft; themenfremde "
                "Zeilen werden außerhalb deiner Synthese als Retrieval-Grenze "
                "ausgewiesen. Formuliere ein wiederkehrendes Muster nur, wenn "
                "mindestens zwei dafür zitierte Passagen dieselbe konkret "
                "benannte Relation tragen; sonst bleiben lokale Einzelbefunde "
                "getrennt. Bewahre bei berichteter Rede, Zitaten und "
                "metasprachlichen Erwähnungen die Stimme: Was eine Passage "
                "äußert, ist keine unmarkierte Sachbehauptung der Analyse. "
                "Kandidatengesamtzahl, Ausschlüsse und methodische Reichweite "
                "rendert das System separat; erfinde dafür keine Restgruppen."
            ),
            "open_research": (
                "Trenne exakte Wort- oder Lemmasuchen, sichtbare Rangzeilen "
                "und kontextuelle Retrieval-Kandidaten als verschiedene "
                "Operationalisierungen. Ein exaktes Nullresultat widerspricht "
                "nicht dem Auftreten verwandter Ausdrücke in begrenzten "
                "Kontexttreffern; deute diese Differenz als methodische "
                "Spannung und nicht als bewusste Begriffsvermeidung oder "
                "bereits gemessene Themenprävalenz. Wenn ein semantisches "
                "Werkzeug laut Evidenz lexikalisch zurückfällt, nenne seine "
                "Treffer lexikalisch gerankte Kandidaten und nicht semantische "
                "Ähnlichkeitsbefunde. Häufigkeits-Top-N-Zeilen motivieren "
                "Themen- oder Kontextfragen, belegen aber für sich keinen "
                "thematischen Kern. Leite Plattform, Textsorte, Urheberschaft "
                "oder Authentizität nur aus dafür ausgewiesenen Metadaten ab; "
                "ein Registerlabel oder eine handleartige Form genügt nicht. "
                "Übernimm Wortarten nur aus sichtbarer POS-Evidenz. Bei "
                "konkurrierenden Hypothesen erhält jede Hypothese eine "
                "sichtbare Motivation, eine vorsichtige Reichweite und ein "
                "Ergebnis, das sie tatsächlich schwächen oder widerlegen "
                "würde. Zwei gleichzeitig mögliche Themen sind noch keine "
                "konkurrierenden Hypothesen: Formuliere unterschiedliche "
                "Erwartungen für dieselbe spätere Operationalisierung, sodass "
                "deren Ergebnis zwischen ihnen unterscheiden kann. Behaupte "
                "keine Dominanz oder Mehrheit, die bereits sichtbaren exakten "
                "Teil- und Gesamtzählungen widerspricht. Partielle KWIC-"
                "Beispiele dürfen qualitative Kategorien motivieren, aber "
                "ohne Kodierung keine dieser Kategorien als überwiegend "
                "ausweisen. Falsifizierbarkeit verlangt keine erfundene "
                "Prozent- oder Signifikanzschwelle: Sofern die Nutzerfrage "
                "keine begründete Schwelle verlangt und die Evidenz keine "
                "liefert, formuliere stattdessen ein qualitativ "
                "entgegengesetztes mögliches Muster der vollständigen "
                "Auswertung. Erfinde dafür weder Beispielzitate noch "
                "zusätzliche Entitäten. In einem offenen Forschungsüberblick "
                "sind isolierte Rangzeilen nur empirische Prämissen, nicht "
                "schon interessante Erkenntnisse. Priorisiere gestützte "
                "Muster, Kontraste, Spannungen und mögliche "
                "Annotationssignale aus mehreren sichtbaren Facts. Trenne "
                "dabei die direkt sichtbare, eng begrenzte Beobachtung von "
                "ihrer freien fachlichen Deutung: Eine neu gebildete "
                "analytische Kategorie gehört in einen tentativen "
                "interpretation-Claim, nicht als angeblich wörtlicher Inhalt "
                "der Tabellenzeilen in einen observation-Claim. Mehrere "
                "Zeilen dürfen gemeinsam genau eine atomare Proposition "
                "tragen; Atomarität bedeutet nicht eine Zeile pro Claim."
            ),
            "contrast_keyness": (
                "Die exakten richtungsbalancierten Zeilen werden separat als "
                "Tabelle gerendert; paraphrasiere sie nicht vollständig. Formuliere "
                "stattdessen einen knappen Befund mit seinen Messwerten und eine "
                "substantielle, begrenzte Interpretation. Das richtungsbalancierte "
                "Fenster ist keine globale Top-N-Rangliste. Nenne die Zeilen je "
                "Richtung mit ihren Messwerten und nicht als lexikalischen Kern. "
                "Gleiche Formklassen wie "
                "@-Handles sind nicht dieselben Tokens; behaupte Überlappung nur, "
                "wenn die sichtbaren Labels tatsächlich übereinstimmen. "
                "target_freq bleibt immer die benannte "
                "Zielseite und reference_freq die Referenzseite. Behaupte nie, alle "
                "Zeilen einer Richtung hätten auf der Gegenseite null Vorkommen, "
                "wenn auch nur eine sichtbare Zeile davon abweicht. "
                "Deute technische Splits nur als möglichen Datensatz-Shift; "
                "Ursache und Population bleiben offen. Wenn handleartige Formen oder "
                "technische Marker die sichtbaren Spitzen dominieren, benenne genau "
                "dieses sichtbare, handle-dominierte Tokenverteilungsmuster und "
                "leite als Hypothese eine Prüfung von Account-, Dokument-, "
                "Sampling- oder Verarbeitungskomposition sowie Dokumentdispersion ab. "
                "Ein vorangestelltes @ belegt dabei nur eine handleartige Form, "
                "nicht die Identität eines Benutzers oder Accounts. Formuliere eine "
                "Kompatibilitätshypothese ('vereinbar mit'), keine Ursache. "
                "Nenne weder q-Werte noch LL ohne explizites Kriterium 'stark' oder "
                "'extrem'; Signifikanz ist keine substantielle Effektstärke."
            ),
            "ngram_profile": (
                "Die exakte Rangtabelle wird aus den referenzierten Facts separat "
                "gerendert; paraphrasiere sie nicht. Wähle bei mehreren sichtbaren "
                "Folgen drei in ihrer Oberfläche kontrastierende Folgen; sind "
                "weniger als drei sichtbar, wähle alle. Formuliere für "
                "jede genau einen eigenen tentativen, am Wortlaut motivierten "
                "Claim und nenne keine Folge zweimal. Erkläre, weshalb gerade ihre "
                "sichtbare Tokenform eine andere Prüfhypothese motiviert als die "
                "anderen Kandidaten. Prüfe vor der Ausgabe, dass ein behaupteter "
                "Kontrast nicht sichtbar ebenso für einen anderen gewählten "
                "Kandidaten gilt. Mögliche Kontraste können etwa ein allgemeiner "
                "Funktionswortrahmen, eine lexikalisch markiertere Folge oder eine "
                "interaktions-/quellenspezifische Oberfläche sein; das sind "
                "Hypothesen, keine vorgegebenen Klassen. "
                "Klassifiziere ohne Kontext keine Folge als feste grammatische "
                "Einheit, Satzfunktion, Plattformartefakt oder Stilmerkmal. "
                "Rohfrequenz belegt weder Formelhaftigkeit noch Kontextvielfalt. "
                "Behaupte insbesondere nicht, eine Folge erfülle häufig, meistens "
                "oder typischerweise eine syntaktische, semantische oder diskursive "
                "Funktion; genau das ist erst im Kontext zu prüfen. "
                "Benenne die getrennte Prüfung präzise: KWIC oder Kontextkodierung "
                "prüft Gebrauch und Funktion; Dokumentdispersion prüft nur "
                "Streuung oder Konzentration."
                " Wenn ein früherer Entwurf wegen einer unbelegten sprachlichen "
                "Klassifikation scheiterte, streiche diese Klassifikation statt "
                "sie nur abzuschwächen; erhalte die Forschungsfrage als "
                "ergebnisoffene Hypothese über die wörtlich sichtbaren Folgen."
            ),
            "lexical_diversity": (
                "Unterscheide rohe Korpustokens von der gefilterten Analysebasis. "
                "Wenn du n_tokens nennst, bezeichne sie ausdrücklich als "
                "analysierte oder gefilterte Tokens; corpus_raw_token_count ist "
                "davon getrennt die rohe Korpusgröße. Verbinde beide Größen in "
                "demselben Claim, sobald du eine davon als Population beschreibst. "
                "TTR heißt Type-Token-Ratio, nicht Token-zu-Type-Ratio. "
                "Der TTR-Nenner ist n_tokens, nicht corpus_raw_token_count. "
                "n_types bezeichnet Types beziehungsweise verschiedene Wortformen, "
                "nicht 'unterschiedliche Tokens'. Globaler TTR tendiert mit "
                "wachsender Stichprobe zur Abnahme; stelle das nicht als monotones "
                "Sinken bei jeder Vergrößerung dar. "
                "Erkläre TTR über das langsamere Wachstum neuer Types relativ zu "
                "zusätzlichen Tokens. Globaler TTR ist längen- beziehungsweise "
                "stichprobengrößenabhängig, aber nicht fensterabhängig. STTR und "
                "MATTR mindern diese Längensensitivität durch feste beziehungsweise "
                "gleitende Fenster, beseitigen sie aber nicht; beantworte eine Frage "
                "nach Größenrobustheit deshalb klar: Beide sind gegenüber globalem "
                "TTR längenkontrollierter. Beschreibe STTR als Standardisierung auf "
                "gleich lange Segmente, nicht als Glättung der Varianz. MATTR kann "
                "bei gleicher Fensterdefinition "
                "durch überlappende Fenster einen glatteren Verlauf liefern, ist "
                "deshalb aber nicht automatisch valider. Vergleiche unterschiedlich "
                "parametrisierte STTR- und MATTR-Werte nicht als direkte "
                "Diversitätssteigerung oder empirische Methodenrangfolge. Nur STTR "
                "und MATTR sind hier fensterabhängig. Urteile ohne Referenz nicht "
                "hoch, niedrig, mittel, "
                "moderat oder typisch; benenne die fehlende Vergleichsbasis, "
                "aber erkläre dennoch die Längensensitivität und die Messwerte. Ein "
                "Referenzkorpus ist für ein externes Niveau- oder Gruppenurteil "
                "nötig, nicht für die methodische Einordnung der Größenrobustheit."
                " Für korpusübergreifende Vergleiche müssen Tokenisierung, Filterpolitik, "
                "Fensterparameter und Zusammensetzung vergleichbar sein; die Maße "
                "reduzieren Längensensitivität, garantieren aber keine Vergleichbarkeit. "
                "Wenn die Evidenz eine Filterpolitik nennt, behaupte nicht, sie sei "
                "unbekannt; grenze tatsächlich fehlende Tokenizerdetails davon ab. "
                "Antworte direkt und knapp: die gerenderte Evidenzzeile trägt bereits "
                "Messwerte und Parameter, zusätzliche Limitationen sollen nur eine "
                "wirklich verbleibende Vergleichsgrenze benennen. "
                "Aus unterschiedlich großen STTR- und MATTR-Fenstern folgt keine "
                "empirische Überlegenheit eines der beiden Maße; beide sind gegenüber "
                "globaler TTR längenkontrollierter und bleiben fensterabhängig."
            ),
            "kwic_context": (
                "Deute den konkreten erweiterten Beleg, nicht nur den Suchstatus. "
                "Behandle seine Wertung als Handlung des Textes und nicht als "
                "externe Wahrheit. Bewahre bei einer Inhaltsparaphrase das "
                "sichtbare Prädikat, die Teilnehmerausdrücke und die Polarität; "
                "löse Pronomen, Handles oder offene Anbindungen nicht auf. Wenn "
                "das nicht sicher gelingt, benenne nur die kommunikative Funktion "
                "des Belegs oder nutze ein kurzes wortgetreues Relationszitat. "
                "Ein sichtbar wertender Ausdruck darf als Wertung interpretiert "
                "werden; ist sein Zielreferent im Ausschnitt nicht sichtbar, "
                "bleibt genau diese Anbindung ausdrücklich offen."
            ),
            "collocation": (
                "Vergleiche Profile nur bei identischen Parametern und trenne "
                "Knotenfrequenz, sichtbare Kollokationszeilen und Deutung. "
                "Eine thematische, semantische oder registrale Hypothese muss "
                "entweder an konkret sichtbaren Kollokaten motiviert sein oder "
                "als ergebnisoffene Hypothese eine passende Kontextprüfung "
                "benennen; bloße Knotenfrequenzen tragen keinen fertigen "
                "Themenbefund. Wenn ein Profil wegen der Mindestfrequenz leer "
                "bleibt, ist Datenknappheit beziehungsweise Schwellenwirkung "
                "eine prüfbare Erklärung, aber keine feststehende Ursache. "
                "Formuliere in diesem Fall eine falsifizierbare Hypothese und "
                "benenne eine kontrollierte Neuberechnung mit niedrigerer "
                "Schwelle bei sonst gleichen Parametern oder eine "
                "KWIC-Kontextprüfung, die sie stützen oder widerlegen würde. "
                "Erfinde dafür keinen neuen numerischen min_freq-Wert; der "
                "qualitative kontrollierte Kontrast genügt. "
                "Fensterkollokationen allein belegen weder POS-Klassen noch "
                "syntaktische Rollen, Diskursfunktionen oder typische Themen."
            ),
            "word_sketch_profile": (
                "Ein Word-Sketch-Tabelleneintrag belegt einen sichtbaren "
                "Relationspartner mit seinen Messwerten, aber nicht automatisch "
                "eine wortgetreu belegte fortlaufende Phrase. Setze daher keine "
                "aus Suchterm und Partner rekonstruierte Wortfolge in "
                "Anführungszeichen. Benenne die sichtbare Relation, ihre Partner "
                "und f-Werte direkt und deute anschließend knapp, welche "
                "unterschiedlichen grammatischen Beziehungsdomänen die "
                "Relationslabels im sichtbaren Profil nebeneinander ausweisen. "
                "Der interpretative Gewinn liegt hier in dieser vergleichenden "
                "Synthese der belegten Relationslabels; er verlangt keine "
                "zusätzliche empirische Behauptung über Prävalenz oder Gebrauch. "
                "Beziehe dabei jede im EvidenceBundle sichtbare Relation und "
                "jede ihrer sichtbaren Partnerzeilen ein; fasse sie natürlich "
                "zusammen, statt eine feste Berichtsschablone zu imitieren. "
                "Für ein knappes Profil genügt pro Partner der f-Wert in der "
                "natürlichen Form 'indexierte Dependenzereignisse'; lasse f2 "
                "und rohe Assoziationsscores weg, sofern die Nutzerfrage nicht "
                "ausdrücklich nach Metriken fragt. "
                "Übernimm ausformulierte Relationslabels wortgetreu, statt eine "
                "neue Übersetzung oder Kategorienbezeichnung zu erfinden. "
                "Ein Relationslabel benennt den Typ der indexierten "
                "Dependenzbeziehung; es belegt nicht, dass Suchterm oder "
                "Partner selbst Kern, Attribut oder Koordinator sind. Weise "
                "daher keinem Token allein aus dem Relationslabel eine "
                "syntaktische Rolle zu. "
                "Unterscheide die Zähleinheiten strikt: total_rows und "
                "total_candidates zählen Partnerzeilen beziehungsweise "
                "Kandidaten; der f-Wert einer Partnerzeile zählt indexierte "
                "Dependenzereignisse, niemals Tokens; f2 ist die marginale "
                "Tokenhäufigkeit des Partners auf der durch f2_basis "
                "ausgewiesenen Basis. Erkläre diese beiden Einheiten knapp, "
                "wenn du f oder f2 ausgibst. Rekonstruiere aus einem "
                "Partner keine Phrase und ordne ihm ohne POS-Evidenz keine "
                "Wortart zu. truncated=false beschreibt nur die Kandidatenliste "
                "der jeweiligen ausgegebenen Relation; daraus folgt nichts über "
                "nicht ausgegebene Relationstypen. min_freq ist ausschließlich "
                "die Aufnahmeschwelle für eine Partnerzeile; sage daher nie, "
                "eine Relation als Ganzes liege über dieser Schwelle. "
                "Begrenze die Deutung ausdrücklich auf die ausgewerteten "
                "Partnerzeilen oberhalb der Mindestfrequenz und nenne diese "
                "Schwelle mit ihrem Wert. Ohne Anteilsnenner belegt f weder "
                "Typizität noch Dominanz oder allgemeine Häufigkeit; lexikalische "
                "Kategorien eines Partners dürfen nur behauptet werden, wenn sie "
                "in der Evidenz selbst ausgewiesen sind. t, LogDice und die "
                "anderen ausgegebenen Assoziationsmaße sind deskriptive "
                "Rang- und Zusammenhangsmaße; ohne p-Wert, Konfidenzintervall "
                "oder explizite Schwelle belegen sie keine statistische "
                "Signifikanz."
            ),
            "trend_analysis": (
                "Für relative Frequenztrends braucht es dokumentbezogene "
                "Zeitzuweisungen und periodenspezifische Tokennenner. Eine "
                "beliebige Dokumentreihenfolge genügt nicht, ist aber auch nicht "
                "zusätzlich nötig, wenn belastbare Periodenwerte vorliegen. "
                "Technische Splits oder ein Quellenname sind ohne explizite "
                "zeitliche Semantik keine Zeitproxies."
            ),
        }.get(str(getattr(contract, "analysis_family", "") or ""), "")
        if family_guidance:
            stage_instruction += " " + family_guidance
        if draft_answer:
            stage_instruction += (
                " Ein nichtleerer draft_answer ist vorhanden. Nutze seine "
                "fachliche Breite und Argumentfolge als Ausgangspunkt, ordne "
                "aber jedem übernommenen empirischen Bestandteil passende "
                "Fact-IDs zu. Bewahre gestützte Erkenntniskandidaten und "
                "begrenzte Deutungen; ersetze sie nicht durch zufällige, nur "
                "leichter kopierbare Einzelwerte. Streiche ausschließlich "
                "Entwurfsteile, die von den sichtbaren Facts nicht getragen "
                "werden."
            )
        if deliverable_kind == "method_advice":
            stage_instruction += (
                " Jeder Analyseschritt ist ein ausführbarer nächster Schritt, "
                "kein bereits erzieltes Forschungsergebnis: Nenne den "
                "sichtbaren Auslöser, die Operation und das Erkenntnisziel. "
                "Halte die Schritte methodisch verschieden. Metadatenwerte "
                "belegen zunächst nur verfügbare Felder und Ausprägungen; aus "
                "Labels wie source, register, model oder text_type folgen ohne "
                "weitere Provenienz weder Authentizität noch Population oder "
                "gesellschaftliche Repräsentativität. Eine Top-N-Liste darf "
                "eine Kontext- oder Kollokationsprüfung motivieren, ist aber "
                "noch kein thematischer Kern oder Stilbefund."
            )
        if focused_response_requirement_repair:
            stage_instruction = (
                "Repariere jetzt nur die fehlenden Antwortslots. Erzeuge für "
                "jeden Eintrag unter missing_response_requirements genau "
                "einen substanziellen Claim mit dessen Slot-ID und erfülle "
                "alle dortigen completion_checks im selben Claim. Bewahre "
                "freie, fachlich gehaltvolle Interpretation; paraphrasiere "
                "die Facts nicht bloß. Nutze partielle Evidenz als begrenzte "
                "Motivation, nicht als bereits kodierte Verteilung. Erfinde "
                "keine Zahlen oder Schwellen, um eine Hypothese prüfbar zu "
                "machen; ein mögliches relationales Gegenmuster genügt."
            )
            slot_surface = " ".join(
                " ".join(
                    [
                        str(getattr(requirement, "description", "") or ""),
                        str(getattr(requirement, "source_quote", "") or ""),
                    ]
                )
                for requirement in missing_response_requirements
            ).casefold()
            if "hypothes" in slot_surface and any(
                marker in slot_surface
                for marker in ("widerleg", "falsifiz", "gegenbefund")
            ):
                stage_instruction += (
                    " Jeder Hypothesen-Slot verbindet genau eine tentative "
                    "Erwartung mit einem logisch entgegengesetzten möglichen "
                    "Ergebnis einer vollständigen Auswertung des aktiven "
                    "Korpus. Ein Gegenkorpus, eine weitere Interpretation der "
                    "sichtbaren Zeilen, ein bloßer zusätzlicher Beleg oder die "
                    "Wiederholung der Hypothese ist kein "
                    "Widerlegungsergebnis."
                )
                if visible_repair_payloads:
                    stage_instruction += (
                        " Ein repair_candidate mit revision_status "
                        "verified_slot_core_missing_completion ist ein bereits "
                        "faktisch und semantisch geprüfter, aber noch "
                        "unvollständiger Claim: Übernimm seinen Wortlaut als "
                        "unveränderten Anfang und ergänze im selben Claim nur "
                        "die fehlende Prüfbedingung. "
                        "Der Entwurf ist dennoch keine zusätzliche Evidenz."
                    )
            if supporting_claim_kinds:
                stage_instruction += (
                    " Ergänze daneben genau einen atomaren Beitrag je "
                    "fehlender claim_kind mit leerer response_requirement_id; "
                    "ihre claim_kind-Werte sind: "
                    + ", ".join(supporting_claim_kinds)
                    + ". Sie liefern belegte Prämissen oder eine notwendige "
                    "Synthese, aber keine zusätzliche Einheit der gezählten "
                    "Nutzeranforderung."
                )
            if family_guidance:
                stage_instruction += " " + family_guidance
            if draft_answer:
                stage_instruction += (
                    " Nutze den initialen draft_answer weiterhin als "
                    "redaktionellen Ausgangspunkt; übernimm daraus nur den "
                    "tragfähigen Erkenntnisgedanken und belege ihn mit den "
                    "jetzt sichtbaren Facts."
                )
        if confirmation_pressure:
            stage_instruction += (
                " Behandle die verlangte Schlussrichtung als Hypothese, nicht "
                "als Auftrag zur Belegauswahl. Bewahre relevante Gegenbelege "
                "und unklare Treffer. Formuliere direkte Such- oder "
                "Passagenbefunde als observations, eine daraus vorsichtig "
                "abgeleitete Bewertung als interpretation und die Grenze "
                "eines Top-N- oder nicht erschöpfenden Retrievals als "
                "limitation. Eine begründete Nichtbestätigung ist eine "
                "vollwertige Antwort; bloße Verweigerung ohne Befunde ist es "
                "nicht. Die Rangposition einer semantischen Suche misst "
                "Ähnlichkeit, nicht Häufigkeit oder Prävalenz im Korpus. "
                "Eine Top-N-Rangliste ist keine Stichprobe, solange kein "
                "Samplingverfahren belegt ist. Nenne die Rangzeilen mit ihren "
                "Werten. "
                "Verwende deshalb für Top-N-Treffer keine Ausdrücke wie "
                "häufig, überwiegend, Tendenz oder typisch. Unterscheide beim "
                "Interpretieren das tatsächlich bewertete Objekt: eine "
                "konkrete Politik, eine Gruppe, eine behauptete Folge und das "
                "abstrakte Zielthema sind nicht dasselbe. Eine Passage ohne "
                "negative Wertung belegt nicht automatisch eine positive "
                "Autorenhaltung; behandle eine solche Lesart als unklar, wenn "
                "der Wortlaut keine Gegenwertung trägt. "
                "Ein Nullresultat einer einzelnen Lemma-, Wort- oder "
                "Nachbarschaftsabfrage belegt weder die Abwesenheit des "
                "breiteren Diskursfelds noch dessen Bewertung; benenne die "
                "enge Operationalisierung, wenn du daraus eine methodische "
                "Grenze ableitest. Auch ein positives Ergebnis einer einzelnen "
                "Query trägt nur Aussagen über genau diese Operationalisierung. "
                "Semantische Ähnlichkeit liefert Kandidaten, "
                "aber keine exhaustive Themen- oder Stance-Annotation. "
                "Prüfe jeden sichtbaren Retrieval-Kandidaten; unklare, "
                "themenferne und gegenläufige Treffer dürfen nicht als "
                "Bestätigung umgedeutet werden. Wenn du eine Wertung "
                "beschreibst, binde sie an kurze wortgetreue Passagenausschnitte "
                "und begrenze sie auf genau die tatsächlich geprüften Treffer."
            )
        if active_retrieval_assessments:
            stage_instruction += (
                " Eine unabhängige, zitatgebundene Vorprüfung aller sichtbaren "
                "Kandidaten liegt unter retrieval_candidate_assessments vor. "
                "Nutze sie als Schutz gegen selektive Belegwahl, prüfe ihre "
                "Labels aber am ebenfalls sichtbaren Rohwortlaut. Trenne "
                "stützende, gegenläufige, unklare und themenferne Kandidaten "
                "inhaltlich; eine negative themenfremde Passage ist kein Beleg "
                "für die Nutzerhypothese. Benenne themenferne Kandidaten als "
                "Grenze der Retrieval-Präzision, statt sie still zu verbergen "
                "oder inhaltlich auszudeuten. Zähle Klassifikationslabels nicht "
                "als Messwerte; quantitative Aussagen brauchen weiterhin einen "
                "passenden sichtbaren Tool-Fact. Die Assessment-Labels selbst sind "
                "keine Korpusevidenz, deshalb bleiben Claims an die zugehörigen "
                "Fact-IDs und wörtlichen Passagen gebunden."
            )
            has_supporting_candidate = bool(
                active_supporting_retrieval_fact_ids
                or active_related_supporting_retrieval_fact_ids
            )
            has_relevant_non_support = bool(
                active_non_supporting_retrieval_fact_ids
            )
            if has_supporting_candidate and has_relevant_non_support:
                stage_instruction += (
                    " Die Vorprüfung ist inhaltlich gemischt. Formuliere daher "
                    "mindestens je einen eigenständigen interpretation-Claim "
                    "für beide Richtungen. Verteile die Fact-IDs aus "
                    "generation_requirements.retrieval_balance.supporting_fact_ids "
                    "oder .related_supporting_fact_ids "
                    "beziehungsweise .non_supporting_fact_ids vollständig auf "
                    "die Claims. Gruppiere mehrere Passagen nur, wenn sie "
                    "dieselbe konkret benannte Relation tragen; entgegengesetzte "
                    "Richtungen bleiben getrennt. Nenne das weder Prävalenz "
                    "noch Tendenz. Die Universalgrenze wird separat gerendert; "
                    "hier zählt die inhaltliche Mustersynthese. Wenn mehrere "
                    "sichtbare Passagen dieselbe Richtungs-Objekt-Zelle "
                    "besetzen, arbeite ihr gemeinsames Rahmungsmuster heraus "
                    "und nutze den lexikalisch explizitesten Wortlaut als "
                    "Leitbeleg. Ein unklarer Kandidat darf einen klaren "
                    "Gegenbeleg nicht verdrängen."
                )
            if active_related_supporting_retrieval_fact_ids:
                stage_instruction += (
                    " Einige Passagen zeigen die behauptete Eigenschaft nur "
                    "an einem verwandten Bewertungsobjekt. Nutze "
                    "generation_requirements.retrieval_balance."
                    "related_supporting_fact_ids und das jeweilige "
                    "evaluated_object_type sowie evaluated_object_quote: "
                    "Benenne im Claim konkret anhand dieses sichtbaren "
                    "Objektausdrucks, ob eine "
                    "Gruppe beziehungsweise ein Akteur, eine Politik oder "
                    "Praxis oder eine behauptete Folge bewertet wird. Schreibe "
                    "diese Wertung nicht dem abstrakten Zielthema selbst zu. "
                    "Diese Unterscheidung soll die lokale Interpretation "
                    "präzisieren, nicht die Passage verwerfen."
                )
        if focused_balanced_retrieval:
            stage_instruction += (
                " Dies ist ein fokussierter analytischer Syntheseturn. Verteile "
                "jeden sichtbaren relevanten Passagen-Fact genau einmal auf "
                "wenige tentative interpretation-Claims. Gruppiere nur "
                "Passagen mit derselben konkret benannten Rahmung, Relation "
                "oder Rollenverteilung; ein wichtiger abweichender Einzelbefund "
                "bleibt separat. Benenne das tatsächlich bewertete Objekt und "
                "bewahre Prädikate, Beteiligte, Polarität und Anbindung. "
                "Schreibe keine Passage-für-Passage-Nacherzählung, keine "
                "Häufigkeit, Mehrheit, Tendenz, Autorenhaltung oder "
                "Korpusprävalenz. Reichweitengrenze, Zitate, Scores und "
                "Dokument-IDs werden separat gerendert und gehören nicht in "
                "diese Claims."
            )
        if focused_retrieval_repair:
            stage_instruction += (
                " Dies ist eine inkrementelle Evidenzreparatur. Mindestens eine "
                "bereits verifizierte, ausdrücklich lokale Interpretation wird "
                "unverändert erhalten. Deute deshalb nur die jetzt sichtbaren, "
                "zuvor ausgelassenen Passagen und erkläre knapp, ob und wie sie "
                "die Reichweite der erhaltenen Lesart ergänzen, kontrastieren "
                "oder begrenzen. Eine unklare Passage bleibt unklar; eine "
                "Wertung an einer konkreten Gruppe, Politik, Praxis oder Folge "
                "wird nicht dem abstrakten Zielthema zugeschrieben. Formuliere "
                "keine Häufigkeit, Mehrheit, Tendenz, Autorenhaltung oder "
                "Korpusprävalenz und wiederhole den erhaltenen Claim nicht."
            )
        if retrieval_attention_projected_ids:
            if replace_whole_deliverable:
                stage_instruction += (
                    " Im letzten Prüfschritt blieben die unter "
                    "generation_requirements.retrieval_attention_fact_ids "
                    "genannten sichtbaren Retrieval-Kandidaten unberücksichtigt "
                    "oder unklar klassifiziert. Schreibe deshalb die gesamte "
                    "Antwort als eine kohärente Neubewertung aller sichtbaren "
                    "Retrieval-Kandidaten. Prüfe die Fokus-Facts ausdrücklich "
                    "als stützend, gegenläufig, unklar oder themenfern und "
                    "revidiere eine frühere Tendenzaussage, wenn die vollständige "
                    "sichtbare Menge sie nicht trägt. Erfinde keine gemeinsame "
                    "Tendenz. Jeder Fokus-Fact muss in mindestens einem Claim "
                    "referenziert werden; mehrere dürfen gemeinsam in einem "
                    "atomaren Claim behandelt werden."
                )
            else:
                stage_instruction += (
                    " Im letzten Prüfschritt blieben die unter "
                    "generation_requirements.retrieval_attention_fact_ids "
                    "genannten sichtbaren Retrieval-Kandidaten unberücksichtigt "
                    "oder unklar klassifiziert. Ergänze die kleinste nötige, "
                    "evidenzgebundene Aussage, die jeden davon ausdrücklich als "
                    "stützend, gegenläufig, unklar oder themenfern einordnet, oder "
                    "begrenze die vorhandene Interpretation entsprechend. Erfinde "
                    "keine gemeinsame Tendenz und verändere bereits verifizierte "
                    "Aussagen nicht. Jeder Fokus-Fact muss in mindestens einem "
                    "neuen Claim referenziert werden; mehrere dürfen gemeinsam in "
                    "einem atomaren Claim behandelt werden."
                )
        if missing_robustness_answer:
            stage_instruction += (
                " Dieser Reparaturschritt ergänzt genau einen methodischen "
                "interpretation-Claim: STTR und MATTR sind gegenüber globalem "
                "TTR längenkontrollierter, bleiben aber fensterabhängig. Wenn "
                "die sichtbaren STTR- und MATTR-Fenster verschieden groß sind, "
                "sage im selben Claim ausdrücklich, dass die konkreten Werte "
                "nicht direkt gegeneinander gerankt oder als Diversitätsanstieg "
                "gelesen werden dürfen. Nenne keinen Referenzkorpus als "
                "Voraussetzung für diese methodische Aussage und rangiere STTR "
                "und MATTR nicht gegeneinander."
            )
        if missing_keyness_interpretation:
            stage_instruction += (
                " Dieser Reparaturschritt ergänzt genau einen atomaren, "
                "tentativen interpretation-Claim. Deute nur das Muster im "
                "sichtbaren richtungsbalancierten Ausschnitt: Eine Dominanz "
                "handleartiger Formen darf als mit einer split-spezifischen "
                "Account-, Dokument- oder Samplingzusammensetzung vereinbar "
                "beschrieben werden. Ursache und Population bleiben offen. "
                "Wiederhole keine einzelnen Labels, Zahlen, Ränge oder internen "
                "Feldnamen; die exakte Tabelle wird separat gerendert. Nenne "
                "@-Formen nicht Benutzer, Accounts oder technische Artefakte. "
                "Kopiere keinen verworfenen Entwurf."
            )
        elif missing_ngram_interpretation:
            stage_instruction += (
                f" Dieser Reparaturschritt ergänzt genau "
                f"{requested_new_claim_count} kurze, atomare "
                "interpretation-Claims: "
                f"{ngram_missing_candidate_count} getrennte, konkret benannte "
                "Kandidatenhypothesen"
                + (
                    " und einen gemeinsamen Prüfplan. "
                    if ngram_missing_plan
                    else ". "
                )
                + "Jede "
                "Kandidatenhypothese enthält genau eine Proposition und sagt nur, "
                "dass die sichtbare Folge als mögliche Formulierungsroutine "
                "prüfenswert ist. Nenne jede Folge höchstens einmal und motiviere "
                "die Auswahl durch ihre sichtbare Tokenform im Kontrast zu den "
                "anderen Kandidaten; verwende kein Merkmal als Kontrast, das ein "
                "anderer gewählter Kandidat sichtbar teilt. Eine mögliche Funktion bleibt ausdrücklich "
                "Hypothese, nicht beobachteter Kontext. Der Prüfplan trennt KWIC "
                "für Gebrauch und Funktion von Dokumentdispersion für Streuung. "
                "Wiederhole weder Rangliste, Frequenzen noch Ränge und setze "
                "keine grammatische Einheit, Satzfunktion oder Artefaktklasse als "
                "Tatsache. Kopiere keinen verworfenen Entwurf; rekonstruiere aus "
                "sichtbaren Facts und Ablehnungsgrund."
            )
        elif missing_kwic_interpretation:
            if _is_multirow_kwic_analysis_request(
                self._question_text,
                observed_facts,
            ):
                stage_instruction += (
                    " Ergänze genau einen kurzen tentativen Interpretationsclaim "
                    "zur sichtbaren KWIC-Auswahl. Verknüpfe mindestens zwei "
                    "unterschiedliche Zeilen über ein konkret sichtbares "
                    "gemeinsames oder kontrastierendes Sprachmuster und begrenze "
                    "die Deutung ausdrücklich auf diese Auswahl. Zitiere alle "
                    "tatsächlich verwendeten Zeilen im selben Claim, erfinde "
                    "keine Häufigkeitsverteilung und löse keine offenen "
                    "Teilnehmer- oder Anbindungsrelationen auf. Wiederhole keine "
                    "Trefferzahlen oder Locator."
                )
            else:
                stage_instruction += (
                    " Ergänze genau einen kurzen tentativen Interpretationsclaim "
                    "zum erweiterten Beleg. Wähle bei unsicherer Teilnehmerrelation "
                    "die kommunikative Ebene des ganzen Textes, etwa seine Wertung "
                    "oder Sprechhandlung. Ein solcher Claim benennt nur diese eine "
                    "Deutung und hängt keine Erklärung mit indem, damit, weil oder "
                    "dadurch an. Eine inhaltliche Relation darfst du nur als kurzes "
                    "wortgetreues Teilzitat übernehmen; ersetze weder Prädikat noch "
                    "sichtbare Teilnehmer und löse keine offene Anbindung auf. "
                    "Wiederhole keine Trefferzahlen oder Locator."
                )
        has_exact_negative_result = any(
            str(getattr(fact, "fact_kind", "") or "")
            == "negative_result"
            and str(getattr(fact, "exactness", "") or "") == "exact"
            for fact in observed_facts
        )
        if has_exact_negative_result:
            stage_instruction += (
                " Wenn eine exakt belegte fehlende Methodenvoraussetzung die "
                "angefragte Auswertung ausschließt, benenne zuerst die konkrete "
                "fehlende Voraussetzung als observation und erkläre anschließend "
                "als eigenständige interpretation, welche Berechnung oder welches "
                "Urteil deshalb nicht zulässig ist. Eine einzige zusammengesetzte "
                "Aussage ist ebenfalls vollständig, wenn sie beides klar trennt."
                " Nutze die natürliche Bezeichnung Datums-, Jahres- oder Zeitfeld; "
                "setze hypothetische Feldnamen wie date oder year nicht als Zitat."
            )
        if missing_word_sketch_units:
            stage_instruction += (
                " Ergänze nur die knappe Definition der im fertigen Text "
                "sichtbaren Word-Sketch-Rohfelder. Wiederhole weder Relation, "
                "Partner noch Messwert und interpretiere das Profil nicht."
            )
        elif required_claim_kind == "observation":
            stage_instruction += (
                " Der jetzt geforderte observation-Claim nennt nur einen "
                "unmittelbar belegten Befund. Trenne Folgerungen mit daher, "
                "deshalb, deutet oder spricht für in einen späteren "
                "interpretation-Claim."
            )
        elif required_claim_kind == "interpretation" and preserved_payloads:
            if str(getattr(contract, "analysis_family", "") or "") == (
                "word_sketch_profile"
            ):
                stage_instruction += (
                    " Der interpretative Mehrwert besteht hier ausschließlich "
                    "in der vergleichenden Synthese der belegten "
                    "Relationslabels; eine weitere empirische Behauptung ist "
                    "weder nötig noch zulässig. Verbinde die bereits berichteten "
                    "Relationsarten zu "
                    "einer knappen grammatischen Lesart des sichtbaren Profils. "
                    "Wiederhole weder Partnerzeilen noch f-Werte. Beschreibe, "
                    "welche unterschiedlichen Arten von Dependenzbeziehungen "
                    "der Ausschnitt sichtbar macht, ohne daraus Phrasen, "
                    "POS-Kategorien, Typizität oder nicht ausgegebene "
                    "Relationen abzuleiten. Die wörtlichen Relationslabels sind "
                    "dafür positive semantische Evidenz: Du darfst die von ihnen "
                    "benannten grammatischen Beziehungsdomänen in einer "
                    "gemeinsamen, ausdrücklich auf den sichtbaren Ausschnitt "
                    "begrenzten Lesart gegenüberstellen. Behaupte dabei weder "
                    "vorwiegenden, häufigen, gelegentlichen oder typischen "
                    "Gebrauch noch erfinde Beispiele oder Rollen für Suchterm "
                    "und Partner. Die Word-Sketch-Ausführung ist bereits "
                    "erfolgreich abgeschlossen; Partnerzeilen und f-Werte sind "
                    "verifiziert und in diesem fokussierten Syntheseturn nur "
                    "absichtlich ausgeblendet. Behaupte daher weder fehlenden "
                    "Toolzugriff noch fehlende Daten, Messwerte oder Evidenz und "
                    "lasse evidence_gaps sowie blocked_claims leer."
                )
            else:
                stage_instruction += (
                    " Der jetzt geforderte interpretation-Claim muss inhaltlich "
                    "über die erhaltene Beobachtung hinausgehen; dieselbe Aussage "
                    "nur als Interpretation umzubenennen erfüllt den Slot nicht."
                )
        elif required_claim_kind == "limitation" and preserved_payloads:
            stage_instruction += (
                " Der jetzt geforderte limitation-Claim benennt ausschließlich "
                "die vom Nutzer verlangte Vergleichsgrenze. Wiederhole keine "
                "bereits verifizierten Messwerte und ersetze die vorhandene "
                "Interpretation nicht durch eine generische Warnung."
            )
            if str(getattr(contract, "analysis_family", "") or "") == "lexical_diversity":
                stage_instruction += (
                    " Benenne konkret die fehlende Referenz- oder Qualitätsbasis; "
                    "rangiere dabei STTR und MATTR nicht gegeneinander."
                )
        structured_doc = self._answer_envelope_doc
        contract_payload = contract.to_dict()
        execution_context: dict[str, Any] = {}
        retry_reason_payload = projected_retry_reasons
        if focused_response_requirement_repair:
            structured_doc = _RESPONSE_REQUIREMENT_REPAIR_DOC
            retry_reason_payload = projected_retry_reasons[:8]
        synthesis_question = self._question_text
        synthesis_retrieval_assessments = list(
            active_retrieval_assessments
        )
        focused_confirmation_retrieval_repair = bool(
            focused_retrieval_repair and confirmation_pressure
        )
        if focused_balanced_retrieval or focused_confirmation_retrieval_repair:
            structured_doc = _RELATED_OBJECT_BALANCED_SYNTHESIS_DOC
            # The deterministic renderer answers the universal confirmation
            # boundary. This LLM turn has the narrower job of interpreting the
            # audited local evidence; repeating the loaded user instruction here
            # made otherwise valid passage readings collapse into a generic
            # confirmation or refusal.
            synthesis_question = (
                "Interpretiere ausschließlich die vollständig geprüften "
                "sichtbaren Passagen als beleggebundene Muster und begründete "
                "Einzelbefunde. Gruppiere nur Passagen, die dieselbe konkret "
                "benannte Relation tatsächlich tragen. Die Reichweitengrenze "
                "der Universalbehauptung wird separat gerendert und gehört "
                "nicht in diese Claims."
            )
            contract_payload = {
                key: value
                for key, value in contract_payload.items()
                if key
                in {
                    "deliverable_kind",
                    "analysis_family",
                    "response_shape",
                }
            }
            compact_fact_payloads: List[dict[str, Any]] = []
            for payload in visible_fact_payloads:
                compact_payload = {
                    key: payload[key]
                    for key in ("id", "fact_kind", "exactness")
                    if key in payload
                }
                if payload.get("fact_kind") == "kwic_example":
                    quote = _candidate_source_quote(payload)
                    compact_payload["statement"] = quote
                    compact_payload["grounding_quotes"] = [quote]
                    sentence_units = _candidate_source_sentences(payload)
                    if len(sentence_units) > 1:
                        compact_payload["sentence_units"] = sentence_units
                else:
                    compact_payload["statement"] = payload.get(
                        "statement",
                        "",
                    )
                compact_fact_payloads.append(compact_payload)
            visible_fact_payloads = compact_fact_payloads
            synthesis_retrieval_assessments = [
                {
                    key: value
                    for key, value in assessment.items()
                    if key not in {"reason", "quote"}
                }
                for assessment in projected_retrieval_assessments
                if str(assessment.get("fact_id", "") or "")
                in set(allowed_projected_fact_ids)
            ]
            direct_target_evaluation_available = any(
                assessment.get("evaluated_object_type") == "target_topic"
                and assessment.get("relation_to_requested_conclusion")
                in {"supports", "counterevidence", "mixed_or_unclear"}
                for assessment in synthesis_retrieval_assessments
            )
            execution_context = {
                "tool_execution_complete": True,
                "current_task": (
                    "missing_retrieval_interpretation"
                    if focused_confirmation_retrieval_repair
                    else "related_object_balanced_synthesis"
                ),
                "direct_target_support_available": bool(
                    active_supporting_retrieval_fact_ids
                ),
                "direct_target_evaluation_available": (
                    direct_target_evaluation_available
                ),
                "related_object_interpretation_required": bool(
                    active_related_supporting_retrieval_fact_ids
                ),
                "target_topic": str(
                    self._retrieval_audit_diagnostics.get(
                        "target_topic",
                        "",
                    )
                    or ""
                ),
                "universal_inference_forbidden": True,
            }
            # Keep the concrete failure memory across focused retries. Small
            # models otherwise fix the latest relation error and immediately
            # reintroduce one from an earlier attempt.
            retry_reason_payload = projected_retry_reasons[:12]
            contrast_instruction = (
                " Eine als gegenläufig oder unklar auditierte Passage muss in "
                "einem eigenen oder mit wirklich gleichartigen Passagen "
                "gruppierten Claim sichtbar berücksichtigt werden; nenne sie "
                "ohne belegte Gegenwertung weder positiv noch neutral."
                if non_supporting_retrieval_fact_ids
                else " Erfinde keine Gegenpassage."
            )
            object_scope_instruction = (
                " Keiner der sichtbaren Kandidaten bewertet das abstrakte "
                "Zielthema unmittelbar. Sage deshalb im natürlichen "
                "Analysewortlaut ausdrücklich, dass die Passagen verwandte "
                "Gruppen, Politiken, Praktiken, Folgen oder andere "
                "Bezugsobjekte bewerten. Behandle einen Gegenakzent im "
                "Themenfeld nicht als logischen Gegenbeweis für eine direkte "
                "Wertung des Zielthemas."
                if not direct_target_evaluation_available
                else ""
            )
            synthesis_shape_instruction = (
                " Ordne die Claims so, dass stützende oder verwandte Muster "
                "und Gegenlesarten oder Unklarheiten analytisch kontrastieren. "
                "Mische entgegengesetzte Relationen nicht in einen vagen "
                "Sammelclaim."
                if (
                    active_non_supporting_retrieval_fact_ids
                    and (
                        active_supporting_retrieval_fact_ids
                        or active_related_supporting_retrieval_fact_ids
                    )
                )
                else (
                    " Verdichte gleichgerichtete Passagen zu "
                    "unterscheidbaren lokalen Deutungen, nicht zu einem "
                    "Trefferinventar."
                )
            )
            if (
                focused_confirmation_retrieval_repair
                and not grouped_confirmation_retrieval_repair
            ):
                fact_payload = visible_fact_payloads[0]
                assessment = next(
                    iter(synthesis_retrieval_assessments),
                    {},
                )
                stage_instruction = (
                    _atomic_retrieval_synthesis_instruction(
                        fact_payload,
                        assessment,
                    )
                    + " Ein vorangestelltes @Handle ist ohne Autorenmetadaten "
                    "nur als sichtbarer Adressat oder erwähnter Account "
                    "belegt, nicht als Sprecher oder Akteur der Äußerung."
                )
            else:
                minimum_retrieval_claim_count = int(
                    claims_schema.get("minItems", 1) or 1
                )
                maximum_retrieval_claim_count = int(
                    claims_schema.get(
                        "maxItems",
                        minimum_retrieval_claim_count,
                    )
                    or minimum_retrieval_claim_count
                )
                stage_instruction = (
                    f"Schreibe zwischen {minimum_retrieval_claim_count} und "
                    f"{maximum_retrieval_claim_count} gehaltvolle, tentative "
                    "interpretation-Claims in der Sprache der Nutzerfrage. "
                    "Verteile jede sichtbare Fact-ID genau einmal. Gruppiere "
                    "Passagen, wenn sie gemeinsam ein analytisch kohärentes "
                    "Rahmungsmuster oder einen gehaltvollen Kontrast tragen; "
                    "ihre konkreten Prädikate müssen dafür nicht identisch "
                    "sein. Ein Sammelclaim aus bloß nebeneinanderstehenden "
                    "Einzelpropositionen bleibt verboten. Trenne "
                    "quellenspezifische Propositionen syntaktisch eindeutig "
                    "und mache sichtbar, welche Relation für welche zitierte "
                    "Passage gilt, ohne Prädikate oder Beteiligte zu "
                    "übertragen. Formuliere ihr analytisches Verhältnis frei, "
                    "statt die Schablone 'eine Passage ... die andere' zu "
                    "wiederholen. "
                    "Benenne konkrete Rahmung, Positionierung oder "
                    "kommunikative Funktion und das tatsächlich bewertete "
                    "Objekt. Mache im natürlichen Wortlaut zugleich klar, ob "
                    "der Befund in Richtung der Nutzerhypothese weist, ihr "
                    "einen Gegenakzent entgegensetzt oder offen bleibt; nutze "
                    "dafür keine technischen Assessment-Labels. Verankere die "
                    "Reichweite jedes Musterclaims "
                    "sprachlich in den sichtbaren Passagen, ohne dafür eine "
                    "feste Satzschablone zu wiederholen. Interpretiere frei "
                    "und quellennahe; liefere weder "
                    "ein Trefferinventar noch bloße Paraphrasen. Bewahre "
                    "Beteiligte, Prädikat, Polarität, Modalität, zeitliche "
                    "Ordnung und ausdrücklich markierte Kausalität. Leite "
                    "keine Relation allein aufgrund verwandter Wortformen ab; "
                    "ein Präfix kann die Bedeutung des Prädikats verändern. "
                    "Ergänze keine neue Ursache, Absicht, Rolle oder Wirkung. "
                    "Ein Institutions- oder Eigenname belegt keine ungenannte "
                    "Ortsangabe. "
                    "Wenn eine Passage Propositionen nur unpunktiert oder ohne "
                    "sichtbaren Kausalmarker aneinanderreiht, beschreibe ihre "
                    "Juxtaposition oder Wertung; verbinde sie nicht mit weil, "
                    "aufgrund, dadurch, indem oder damit. Ein "
                    "vorangestelltes @Handle ist ohne Autorenmetadaten nur "
                    "Adressat oder erwähnter Account, nicht Sprecher. "
                    "Wertende Quellenwörter bleiben an ihrem ursprünglichen "
                    "Referenten. Normalisiere ein unklares oder fehlerhaft "
                    "wirkendes Quellwort nicht stillschweigend zu einem "
                    "vermuteten Ausdruck und ändere dabei weder Numerus noch "
                    "Relation; zitiere es oder markiere die Lesart als offen. "
                    "Verwende technische Fact-IDs ausschließlich "
                    "im fact_ids-Feld, niemals im sichtbaren Text. Schreibe in "
                    "claim.text weder Überschriften, Aufzählungen, wiederholte "
                    "Quellzitate noch Klammeranalysen; jeder Claim ist ein "
                    "grammatisch vollständiger, vor der Ausgabe gegengelesener "
                    "Absatz. Die intern vollständig geprüften Kandidaten sind "
                    "hier bewusst auf bis zu zwei aussagekräftige Belege pro "
                    "Schlussrichtung und Bewertungsobjekttyp kuratiert; "
                    "verdichte gleichartige Belege zu einem Muster und erfinde "
                    "keine Aufzählung der nicht sichtbaren Kandidaten."
                    + synthesis_shape_instruction
                    + contrast_instruction
                    + object_scope_instruction
                    + " Die Reichweitengrenze wird separat ausgegeben: keine "
                    "Häufigkeit, Prävalenz, Korpusgeltung, Methodenwarnung, "
                    "technischen IDs oder erfundenen Beispiele im Claim."
                )
        if missing_word_sketch_units:
            preserved_surface = " ".join(
                str(getattr(claim, "text", "") or "")
                for claim in preserved_claim_list
            )
            raw_f_visible = bool(
                re.search(
                    r"(?<![\w2₂])f\s*[=:]",
                    preserved_surface,
                    re.IGNORECASE,
                )
            )
            raw_f2_visible = bool(
                re.search(
                    r"\bf(?:2|₂)\s*[=:]",
                    preserved_surface,
                    re.IGNORECASE,
                )
            )
            structured_doc = _WORD_SKETCH_UNIT_CLARIFICATION_DOC
            contract_payload = {
                key: value
                for key, value in contract_payload.items()
                if key
                in {
                    "deliverable_kind",
                    "analysis_family",
                    "question_scope",
                    "response_shape",
                }
            }
            execution_context = {
                "tool_execution_complete": True,
                "all_required_evidence_collected": True,
                "quantitative_observations_already_verified": True,
                "current_task": "word_sketch_metric_units_only",
                "raw_f_visible": raw_f_visible,
                "raw_f2_visible": raw_f2_visible,
            }
            retry_reason_payload = []
            requested_units = [
                *(
                    [
                        "f ist die Anzahl indexierter Dependenzereignisse der Partnerzeile"
                    ]
                    if raw_f_visible
                    else []
                ),
                *(
                    [
                        "f2 ist die marginale Tokenhäufigkeit des Partners auf der ausgewiesenen Basis"
                    ]
                    if raw_f2_visible
                    else []
                ),
            ]
            stage_instruction = (
                "Schreibe genau einen kurzen observation-Claim in derselben "
                "Sprache wie die Nutzerfrage. Erkläre ausschließlich die "
                "Zähleinheit der laut execution_context im bereits verifizierten "
                "Text sichtbaren Rohfelder: "
                + "; ".join(requested_units)
                + ". Wiederhole keine Relation, Partner, Zahlen oder Rangfolge. "
                "Keine Interpretation, Prävalenz, Typizität, Beispiele oder "
                "fehlende Evidenz. Nutze die einzige sichtbare Fact-ID; "
                "evidence_gaps und blocked_claims bleiben leer. Formuliere frei "
                "statt nach einer festen Berichtsschablone."
            )
        elif missing_word_sketch_interpretation:
            structured_doc = _WORD_SKETCH_RELATION_SYNTHESIS_DOC
            contract_payload = {
                key: value
                for key, value in contract_payload.items()
                if key
                in {
                    "deliverable_kind",
                    "analysis_family",
                    "question_scope",
                    "response_shape",
                }
            }
            execution_context = {
                "tool_execution_complete": True,
                "all_required_evidence_collected": True,
                "quantitative_observations_already_verified": True,
                "current_task": "relation_label_synthesis_only",
                "relation_argument_direction_exposed": False,
                "query_term_role_inference_forbidden": True,
            }
            retry_reason_payload = []
            stage_instruction = (
                "Schreibe genau einen kurzen interpretation-Claim in derselben "
                "Sprache wie die Nutzerfrage. Vergleiche die grammatischen "
                "Beziehungsdomänen der ausgewerteten Relationslabels und "
                "begrenze die Aussage ausdrücklich auf diese Labels. "
                "Diese relationale Gegenüberstellung ist "
                "bereits die verlangte Interpretation; füge keine weitere "
                "empirische Behauptung an. Eine bloße koordinierte Aufzählung "
                "der Labels erfüllt den Interpretationsslot nicht; formuliere "
                "ihren Unterschied, ihr Nebeneinander oder ihre relationale "
                "Spannweite explizit. Relationslabels benennen den Typ der "
                "Dependenzbeziehung, nicht die syntaktische Rolle des Suchterms "
                "oder eines Partners. Formuliere den Relationsausschnitt oder "
                "das ausgewertete Profil als grammatisches Subjekt des Claims. "
                "Nenne im neuen Claim weder den Suchterm noch einen Partner und "
                "schreibe insbesondere nicht, der Begriff, das Wort oder das "
                "Substantiv sei Kern, Attribut oder Koordinator beziehungsweise "
                "komme in einer solchen Struktur vor; dafür ist in diesem Turn "
                "keine Argumentrichtung sichtbar. Partnerzeilen und f-Werte "
                "sind bereits "
                "verifiziert und absichtlich nicht sichtbar: Wiederhole sie "
                "nicht und behaupte weder fehlenden Toolzugriff noch fehlende "
                "Daten. Keine Prävalenz, Typizität, Beispiele, Phrasen, POS- oder "
                "Tokenrollen. Nutze alle vorliegenden Fact-IDs. evidence_gaps und "
                "blocked_claims bleiben leer. Formuliere frei statt nach einer "
                "festen Berichtsschablone."
            )
        synthesis_payload = {
                "question": synthesis_question,
                "contract": contract_payload,
                "execution_context": execution_context,
                "draft_answer": draft_answer,
                "draft_is_evidence": False,
                "observed_facts": visible_fact_payloads,
                "retrieval_candidate_assessments": (
                    synthesis_retrieval_assessments
                ),
                "valid_fact_ids": list(allowed_projected_fact_ids),
                "generation_requirements": {
                    "new_claims_only": bool(
                        preserved_payloads
                        and not replace_whole_deliverable
                    ),
                    "new_claim_count": requested_new_claim_count,
                    "new_claim_count_min": int(
                        claims_schema.get("minItems", 0) or 0
                    ),
                    "new_claim_count_max": int(
                        claims_schema.get("maxItems", 0) or 0
                    ),
                    "required_claim_kind": required_claim_kind,
                    "response_requirement_claim_count": len(
                        missing_response_requirements
                    ),
                    "supporting_claim_kinds": supporting_claim_kinds,
                    "missing_response_requirements": (
                        _response_requirement_generation_payloads(
                            list(missing_response_requirements)
                        )
                    ),
                    "required_elements": (
                        [
                            "genau eine knappe Einheitenerklärung für die sichtbaren Rohfelder",
                            "keine Wiederholung von Relation, Partner, Wert oder Rang",
                            "Toollauf und quantitative Beobachtungen sind bereits vollständig verifiziert",
                        ]
                        if missing_word_sketch_units
                        else (
                        [
                            *(
                                [
                                    f"{ngram_missing_candidate_count} getrennte atomare Claims zu ebenso vielen konkret benannten sichtbaren Folgen"
                                ]
                                if ngram_missing_candidate_count
                                else []
                            ),
                            "tentative sprachliche Kandidatenhypothesen statt Tatsachenklassifikationen",
                            *(
                                [
                                    "ein eigener Prüfplan: KWIC für Gebrauch/Funktion und Dokumentdispersion für Streuung"
                                ]
                                if ngram_missing_plan
                                else []
                            ),
                        ]
                        if missing_ngram_interpretation
                        else (
                            [
                                "ein atomarer tentativer Claim zum sichtbaren handleartigen Muster",
                                "Kompatibilität mit Kompositions- oder Sampling-Shift statt Ursache",
                                "keine Populationen, Benutzeridentitäten, Zahlen oder Feldnamen",
                            ]
                            if missing_keyness_interpretation
                            else (
                            [
                                "genau eine vergleichende Synthese der sichtbaren Relationsdomänen",
                                "nur Relationslabels deuten; keine Rollen, Prävalenz, Beispiele oder Row-Counts",
                                "Toollauf und quantitative Beobachtungen sind bereits vollständig verifiziert",
                            ]
                            if missing_word_sketch_interpretation
                            else (
                            [
                                (
                                    "genau eine tentative, auf die verlangte KWIC-Auswahl begrenzte Deutung"
                                    if _is_multirow_kwic_analysis_request(
                                        self._question_text,
                                        observed_facts,
                                    )
                                    else "genau eine tentative kommunikative Deutung des konkreten erweiterten Kontextes"
                                ),
                                "kein erklärender Nebensatz mit neuer Aktivität oder Teilnehmerrolle",
                                "inhaltliche Relationen nur als kurzes wortgetreues Teilzitat",
                            ]
                            if missing_kwic_interpretation
                            else []
                            )
                            )
                        )
                        )
                    ),
                    "do_not_repeat_verified_claims": bool(
                        preserved_payloads
                        and not replace_whole_deliverable
                    ),
                    "replace_whole_deliverable": bool(
                        replace_whole_deliverable
                    ),
                    "preserve_supported_draft_insights": bool(
                        draft_answer
                    ),
                    "preferred_new_fact_ids": (
                        preferred_projected_fact_ids
                    ),
                    "retrieval_attention_fact_ids": (
                        retrieval_attention_projected_ids
                    ),
                    "retrieval_balance": {
                        "supporting_fact_ids": (
                            active_supporting_retrieval_fact_ids
                        ),
                        "related_supporting_fact_ids": (
                            active_related_supporting_retrieval_fact_ids
                        ),
                        "non_supporting_fact_ids": (
                            active_non_supporting_retrieval_fact_ids
                        ),
                        "off_topic_fact_ids": (
                            active_off_topic_retrieval_fact_ids
                        ),
                        "require_balanced_interpretation": bool(
                            (
                                active_supporting_retrieval_fact_ids
                                or active_related_supporting_retrieval_fact_ids
                            )
                            and active_non_supporting_retrieval_fact_ids
                        ),
                    },
                    "stage_instruction": stage_instruction,
                },
                "retry_reasons": retry_reason_payload,
                "already_verified_do_not_repeat": (
                    []
                    if replace_whole_deliverable
                    else visible_preserved_payloads
                ),
                "pending_unclassified_claims": (
                    []
                    if replace_whole_deliverable
                    else pending_payloads
                ),
                "repair_candidates": visible_repair_payloads,
            }
        raw = await self._run_structured_step(
            doc=structured_doc,
            payload=synthesis_payload,
            schema=schema,
            # GEPINNT, wie an den acht anderen Struktur-Schritten. Ohne Pin
            # ist eine Wiederholrunde eine unabhaengige ZIEHUNG, keine
            # Reparatur: derselbe Envelope kann beim zweiten Wurf bestehen,
            # ohne dass sich etwas verbessert hat. Damit ist weder eine
            # Stagnation erkennbar noch ein Fortschritt belegbar. Der Pin
            # gehoert deshalb mit der Stagnationsbremse zusammen und nie
            # allein: ohne sie bliebe ein festgefahrener Envelope
            # festgefahren.
            temperature=0.0,
        )
        envelope = self._answer_envelope_cls.from_raw(raw)
        stripped_citation_count = 0
        semantic_method_label_repair_count = 0
        for claim in list(getattr(envelope, "claims", []) or []):
            claim.text, removed, invalid_citations = (
                _strip_projected_fact_citations(
                    getattr(claim, "text", ""),
                    _dedupe_ordered_strs(
                        list(projected_to_internal_facts)
                        + [
                            str(payload.get("id", "") or "")
                            for payload in (
                                preserved_payloads
                                + pending_payloads
                                + repair_payloads
                            )
                            if str(payload.get("id", "") or "")
                        ]
                    ),
                )
            )
            claim.text = _ensure_sentence_terminal_punctuation(claim.text)
            stripped_citation_count += removed
            if invalid_citations:
                claim._invalid_projected_fact_citations = (
                    invalid_citations
                )
            resolved_fact_ids: List[str] = []
            for fact_id in list(getattr(claim, "fact_ids", []) or []):
                resolved, unknown = _resolve_projected_id(
                    fact_id,
                    projected_to_internal_facts,
                )
                value = resolved or unknown
                if value and value not in resolved_fact_ids:
                    resolved_fact_ids.append(value)
            claim.fact_ids = resolved_fact_ids
            if resolved_fact_ids and set(resolved_fact_ids).issubset(
                semantic_search_fact_ids
            ):
                claim.text, repaired = (
                    _normalise_semantic_search_method_label(
                        getattr(claim, "text", "")
                    )
                )
                semantic_method_label_repair_count += repaired
        if focused_response_requirement_repair:
            _assign_equivalent_missing_response_slots(
                list(getattr(envelope, "claims", []) or []),
                list(missing_response_requirements),
            )
        preserved_by_visible_signature = {
            _visible_claim_signature(claim): claim
            for claim in preserved_claim_list
        }
        repeated_verified_claim_count = 0
        if preserved_by_visible_signature:
            new_claims = []
            for claim in list(getattr(envelope, "claims", []) or []):
                visible_signature = _visible_claim_signature(claim)
                preserved_claim = preserved_by_visible_signature.get(
                    visible_signature
                )
                if preserved_claim is None:
                    preserved_claim = next(
                        (
                            candidate
                            for candidate in preserved_claim_list
                            if _near_duplicate_visible_claim(
                                claim,
                                candidate,
                            )
                        ),
                        None,
                    )
                if preserved_claim is not None:
                    proposed_requirement_id = str(
                        getattr(claim, "response_requirement_id", "") or ""
                    ).strip()
                    preserved_requirement_id = str(
                        getattr(
                            preserved_claim,
                            "response_requirement_id",
                            "",
                        )
                        or ""
                    ).strip()
                    if not (
                        proposed_requirement_id
                        and not preserved_requirement_id
                    ):
                        repeated_verified_claim_count += 1
                        # The accepted version is merged back below. Keeping a
                        # copy here would let repetition occupy a genuinely new
                        # content slot. A pure missing-slot repair is different:
                        # it must survive to the verifier.
                        continue
                new_claims.append(claim)
            envelope.claims = new_claims
        if stripped_citation_count:
            envelope._projected_fact_citation_strip_count = (
                stripped_citation_count
            )
        if semantic_method_label_repair_count:
            envelope._semantic_method_label_repair_count = (
                semantic_method_label_repair_count
            )
        if repeated_verified_claim_count:
            envelope._repeated_verified_claim_drop_count = (
                repeated_verified_claim_count
            )
            # Preserve the existing aggregate duplicate diagnostic while
            # distinguishing retries that were dropped before merge.
            envelope._visible_duplicate_merge_count = int(
                getattr(
                    envelope,
                    "_visible_duplicate_merge_count",
                    0,
                )
                or 0
            ) + repeated_verified_claim_count
        return envelope

    async def _repair_omitted_claim_partition(
        self,
        contract: Any,
        observed_facts: List[Any],
        envelope: Any,
        unresolved_ids: set[str],
    ) -> tuple[set[str], set[str], List[str]]:
        """Classify claims omitted by the full verdict, without rewriting them."""

        unresolved_claims = [
            claim
            for claim in list(getattr(envelope, "claims", []) or [])
            if str(getattr(claim, "id", "") or "").strip()
            in unresolved_ids
        ]
        if not unresolved_claims:
            return set(), set(), []

        fact_payloads, projected_to_internal_facts = _project_facts(
            observed_facts
        )
        internal_to_projected_facts = {
            internal_id: projected_id
            for projected_id, internal_id in projected_to_internal_facts.items()
            if internal_id
        }
        claim_payloads, projected_to_internal_claims = _project_claims(
            unresolved_claims,
            prefix="u",
        )
        _rewrite_claim_payload_fact_ids(
            claim_payloads,
            internal_to_projected_facts,
        )
        projected_claim_ids = list(projected_to_internal_claims)
        schema = {
            "name": "claim_grounding_partition",
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "decisions": {
                        "type": "array",
                        "minItems": len(projected_claim_ids),
                        "maxItems": len(projected_claim_ids),
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "claim_id": {
                                    "type": "string",
                                    "enum": projected_claim_ids,
                                },
                                "decision": {
                                    "type": "string",
                                    "enum": ["accept", "reject"],
                                },
                                "reason": {
                                    "type": "string",
                                    "maxLength": 400,
                                },
                            },
                            "required": [
                                "claim_id",
                                "decision",
                                "reason",
                            ],
                        },
                    }
                },
                "required": ["decisions"],
            },
        }
        contract_payload = {
            key: value
            for key, value in contract.to_dict().items()
            if key
            in {
                "track",
                "analysis_family",
                "deliverable_kind",
                "question_scope",
                "forbidden_claims",
                "response_requirements",
            }
        }
        confirmation_pressure = (
            self._needs_confirmation_retrieval_adjudication(contract)
        )
        partition_question = self._question_text
        partition_stage: dict[str, Any] = {
            "tool_execution_complete": True,
            "classify_each_supplied_claim_exactly_once": True,
            "do_not_rewrite_claims": True,
        }
        if confirmation_pressure:
            contract_payload.pop("question_scope", None)
            partition_question = (
                "Prüfe jeden atomaren Claim ergebnisoffen in seiner eigenen "
                "ausdrücklich formulierten Reichweite. Ein lokaler Claim muss "
                "die übergeordnete Universalhypothese nicht beweisen."
            )
            partition_stage["confirmation_claim_policy"] = {
                "evaluate_each_claim_at_its_own_scope": True,
                "local_claim_need_not_prove_universal_hypothesis": True,
                "grounded_scope_limitation_may_reject_hypothesis": True,
                "requested_confirmation_direction_is_irrelevant": True,
            }
        raw = await self._run_structured_step(
            doc=(
                "Klassifiziere jeden gelieferten Claim genau einmal als accept "
                "oder reject. Prüfe seine konkrete Bedeutung gegen die "
                "referenzierten Fakten, einschließlich Negation, Scope, Rollen "
                "und behaupteter Sicherheit. Interpretation und vorsichtige "
                "Hypothesen sind zulässig; Zahlen, Zitate und Tatsachen müssen "
                "belegt sein. Formuliere oder ergänze keine Antwort."
            ),
            payload={
                "question": partition_question,
                "contract": contract_payload,
                "verification_stage": partition_stage,
                "observed_facts": fact_payloads,
                "unresolved_claims": claim_payloads,
            },
            schema=schema,
            temperature=0.0,
        )
        if not isinstance(raw, dict):
            return set(), set(), []
        decisions = raw.get("decisions")
        if not isinstance(decisions, list):
            return set(), set(), []

        by_internal_id: dict[str, List[tuple[str, str]]] = {}
        for item in decisions:
            if not isinstance(item, dict):
                continue
            internal_id, _unknown = _resolve_projected_id(
                item.get("claim_id"),
                projected_to_internal_claims,
            )
            decision = str(item.get("decision") or "").strip().casefold()
            if internal_id not in unresolved_ids or decision not in {
                "accept",
                "reject",
            }:
                continue
            by_internal_id.setdefault(internal_id, []).append(
                (decision, str(item.get("reason") or "").strip()[:400])
            )

        accepted: set[str] = set()
        rejected: set[str] = set()
        reasons: List[str] = []
        claim_by_id = {
            str(getattr(claim, "id", "") or ""): claim
            for claim in unresolved_claims
        }
        fact_by_id = {
            str(getattr(fact, "id", "") or ""): fact
            for fact in observed_facts
        }
        for claim_id in unresolved_ids:
            classifications = by_internal_id.get(claim_id, [])
            if len(classifications) != 1:
                continue
            decision, reason = classifications[0]
            claim = claim_by_id.get(claim_id)
            cited_source = " ".join(
                str(
                    getattr(
                        fact_by_id.get(str(fact_id)),
                        "statement",
                        "",
                    )
                    or ""
                )
                for fact_id in list(getattr(claim, "fact_ids", []) or [])
                if fact_by_id.get(str(fact_id)) is not None
            )
            if (
                decision == "reject"
                and claim is not None
                and _LITERAL_DEONTIC_METAREADING_REJECTION_PATTERN.search(
                    reason
                )
                and _is_source_faithful_deontic_metareading(
                    cited_source,
                    str(getattr(claim, "text", "") or ""),
                )
            ):
                decision = "accept"
            if decision == "accept":
                accepted.add(claim_id)
            else:
                rejected.add(claim_id)
            if reason:
                reasons.append(f"{claim_id}: {reason}")
        return accepted, rejected, _dedupe_ordered_strs(reasons)

    async def _audit_partition_relation_acceptances(
        self,
        contract: Any,
        observed_facts: List[Any],
        envelope: Any,
        accepted_ids: set[str],
        retrieval_candidate_assessments: List[dict[str, Any]],
    ) -> tuple[set[str], dict[str, List[str]]]:
        """Apply the source-relation veto to fallback-accepted interpretations."""

        already_audited = set(
            getattr(envelope, "_kwic_relation_audited_ids", set()) or set()
        )
        claims_to_audit = [
            claim
            for claim in list(getattr(envelope, "claims", []) or [])
            if str(getattr(claim, "id", "") or "")
            in accepted_ids - already_audited
            and str(getattr(claim, "claim_kind", "") or "")
            == "interpretation"
        ]
        if not claims_to_audit:
            return set(), {}

        fact_payloads, projected_to_internal_facts = _project_facts(
            observed_facts
        )
        internal_to_projected_facts = {
            internal_id: projected_id
            for projected_id, internal_id in projected_to_internal_facts.items()
            if internal_id
        }
        claim_payloads, projected_to_internal_claims = _project_claims(
            claims_to_audit,
            prefix="v",
        )
        _rewrite_claim_payload_fact_ids(
            claim_payloads,
            internal_to_projected_facts,
        )
        projected_assessments = [
            _project_retrieval_assessment(
                assessment,
                internal_to_projected_facts[
                    str(assessment.get("fact_id", ""))
                ],
            )
            for assessment in retrieval_candidate_assessments
            if str(assessment.get("fact_id", ""))
            in internal_to_projected_facts
        ]
        relation_accepted, relation_rejected, relation_reasons = (
            await self._adjudicate_kwic_relations(
                contract,
                claim_payloads,
                fact_payloads,
                projected_to_internal_claims,
                accepted_internal_ids={
                    str(getattr(claim, "id", "") or "")
                    for claim in claims_to_audit
                },
                protocol_required_internal_ids={
                    str(getattr(claim, "id", "") or "")
                    for claim in claims_to_audit
                },
                retrieval_candidate_assessments=projected_assessments,
            )
        )
        audited_ids = relation_accepted | relation_rejected
        if audited_ids:
            envelope._kwic_relation_audited_ids = (
                already_audited | audited_ids
            )
        if relation_rejected:
            envelope._kwic_relation_rejections = _dedupe_ordered_strs(
                list(
                    getattr(envelope, "_kwic_relation_rejections", []) or []
                )
                + sorted(relation_rejected)
            )
        return relation_rejected, relation_reasons

    async def _adjudicate_kwic_relations(
        self,
        contract: Any,
        verifier_claims: List[dict[str, Any]],
        verifier_fact_payloads: List[dict[str, Any]],
        projected_to_internal_claims: dict[str, str],
        *,
        accepted_internal_ids: set[str],
        protocol_required_internal_ids: Optional[set[str]] = None,
        retrieval_candidate_assessments: Optional[
            List[dict[str, str]]
        ] = None,
    ) -> tuple[set[str], set[str], dict[str, List[str]]]:
        """Veto relation drift in accepted interpretations of source passages."""

        analysis_family = str(
            getattr(contract, "analysis_family", "") or ""
        )
        confirmation_pressure = (
            "one-sided confirmation of a universal corpus claim"
            in {
                str(value or "").strip().casefold()
                for value in list(
                    getattr(contract, "forbidden_claims", []) or []
                )
            }
        )
        retrieval_source_fact_ids = {
            str(item.get("fact_id", "") or "")
            for item in list(retrieval_candidate_assessments or [])
            if str(
                item.get("relation_to_requested_conclusion", "") or ""
            )
            in {
                "supports",
                "related_support",
                "counterevidence",
                "mixed_or_unclear",
            }
            and str(item.get("fact_id", "") or "")
        }
        audit_retrieval_sources = bool(retrieval_source_fact_ids)
        if not self._kwic_relation_adjudicator_doc or not (
            analysis_family == "kwic_context" or audit_retrieval_sources
        ):
            return set(), set(), {}

        candidate_claims = [
            claim
            for claim in verifier_claims
            if str(claim.get("claim_kind", "")) == "interpretation"
            and projected_to_internal_claims.get(
                str(claim.get("id", "")),
                "",
            )
            in accepted_internal_ids
            and (
                analysis_family == "kwic_context"
                or bool(
                    {
                        str(fact_id)
                        for fact_id in list(claim.get("fact_ids", []) or [])
                    }.intersection(retrieval_source_fact_ids)
                )
            )
        ]
        if not candidate_claims:
            return set(), set(), {}

        candidate_projected_ids = [
            str(claim.get("id", ""))
            for claim in candidate_claims
            if str(claim.get("id", ""))
        ]
        candidate_fact_ids = {
            str(fact_id)
            for claim in candidate_claims
            for fact_id in list(claim.get("fact_ids", []) or [])
            if str(fact_id)
        }
        focused_facts: List[dict[str, Any]] = []
        for fact in verifier_fact_payloads:
            if str(fact.get("id", "")) not in candidate_fact_ids:
                continue
            focused_fact = {
                "id": str(fact.get("id", "")),
                "statement": str(fact.get("statement", "")),
                "grounding_quotes": list(
                    fact.get("grounding_quotes", []) or []
                ),
            }
            sentence_units = _candidate_source_sentences(fact)
            if len(sentence_units) > 1:
                focused_fact["sentence_units"] = sentence_units
            focused_facts.append(focused_fact)
        focused_facts_by_id = {
            str(fact.get("id", "")): fact
            for fact in focused_facts
            if str(fact.get("id", ""))
        }

        def fact_surface(fact: dict[str, Any]) -> str:
            return " ".join(
                [str(fact.get("statement", ""))]
                + [
                    str(quote)
                    for quote in list(fact.get("grounding_quotes", []) or [])
                ]
            )

        source_relation_surface_by_claim = {
            str(claim.get("id", "")): " ".join(
                fact_surface(focused_facts_by_id[fact_id])
                for fact_id in [
                    str(value)
                    for value in list(claim.get("fact_ids", []) or [])
                ]
                if fact_id in focused_facts_by_id
            )
            for claim in candidate_claims
        }
        claim_surface_by_projected_id = {
            str(claim.get("id", "")): str(claim.get("text", ""))
            for claim in candidate_claims
        }
        candidate_internal_ids = {
            projected_to_internal_claims[projected_id]
            for projected_id in candidate_projected_ids
            if projected_id in projected_to_internal_claims
        }
        protocol_required_ids = (
            set(candidate_internal_ids)
            if protocol_required_internal_ids is None
            else set(protocol_required_internal_ids).intersection(
                candidate_internal_ids
            )
        )
        if not focused_facts:
            reason = (
                "Der lokale KWIC-Claim besitzt keinen referenzierten "
                "Kontext-Fact für den Relationsabgleich."
            )
            return (
                set(),
                candidate_internal_ids,
                {
                    claim_id: [reason]
                    for claim_id in candidate_internal_ids
                },
            )

        schema = {
            "name": "kwic_relation_verdict",
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "decisions": {
                        "type": "array",
                        "minItems": len(candidate_projected_ids),
                        "maxItems": len(candidate_projected_ids),
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "claim_id": {
                                    "type": "string",
                                    "enum": list(candidate_projected_ids),
                                },
                                "decision": {
                                    "type": "string",
                                    "enum": ["accept", "reject"],
                                },
                                "source_relation": {
                                    "type": "string",
                                    "maxLength": 500,
                                },
                                "claim_relation": {
                                    "type": "string",
                                    "maxLength": 500,
                                },
                                "mismatch": {
                                    "type": "string",
                                    "enum": [
                                        "none",
                                        "participant_shift",
                                        "predicate_shift",
                                        "polarity_shift",
                                        "attachment_resolution",
                                        "invented_entity_type",
                                        "causal_strengthening",
                                        "scope_shift",
                                        "multiple",
                                    ],
                                },
                                "reason": {
                                    "type": "string",
                                    "maxLength": 500,
                                },
                            },
                            "required": [
                                "claim_id",
                                "decision",
                                "source_relation",
                                "claim_relation",
                                "mismatch",
                                "reason",
                            ],
                        },
                    }
                },
                "required": ["decisions"],
            },
        }

        def atomic_relation_schema(projected_id: str) -> dict[str, Any]:
            atomic_schema = copy.deepcopy(schema)
            decision_schema = atomic_schema["schema"]["properties"][
                "decisions"
            ]
            decision_schema["minItems"] = 1
            decision_schema["maxItems"] = 1
            decision_schema["items"]["properties"]["claim_id"][
                "enum"
            ] = [projected_id]
            return atomic_schema

        def atomic_relation_payload(
            claim: dict[str, Any],
        ) -> dict[str, Any]:
            fact_ids = {
                str(value)
                for value in list(claim.get("fact_ids", []) or [])
                if str(value)
            }
            testable_hypothesis = _is_explicit_testable_hypothesis_claim(
                claim
            )
            verification_stage = {
                "tool_execution_complete": True,
                "second_pass_relation_audit": True,
                "compare_source_and_claim_predicates": True,
                "compare_source_and_claim_participants": True,
                "preserve_evaluative_source_labels": True,
                "no_euphemistic_or_intensifying_substitution": True,
                "adjacency_is_not_causality": True,
                "preserve_open_attachment": True,
                "interpretation_is_welcome_when_source_faithful": True,
                "claim_scope_is_local": True,
                "global_hypothesis_is_not_under_review": True,
                "multi_source_synthesis_may_be_valid": True,
                "evaluate_each_clause_against_any_cited_source": True,
                "no_single_source_must_cover_whole_claim": True,
                "do_not_rewrite_claims": True,
                "relation_summaries_keep_surface_language": True,
                "sentence_units_are_binding": True,
                "no_cross_sentence_role_transfer_without_connector": True,
                "source_relation_copies_two_source_content_words": True,
                "claim_relation_copies_two_claim_content_words": True,
                "verbatim_evaluative_source_phrases_are_binding": True,
                "analytical_valence_need_not_be_verbatim": True,
                "same_verbatim_predicate_keeps_its_lexical_strength": True,
                "quoted_proposition_not_external_truth": True,
                "isolated_statement_supports_report_of_statement": True,
            }
            if testable_hypothesis:
                verification_stage["testable_hypothesis_policy"] = {
                    "audit_visible_motivation_against_sources": True,
                    "predicted_full_corpus_relation_is_a_proposal": True,
                    "possible_counter_result_is_prospective": True,
                    "do_not_require_prediction_or_counter_result_to_be_observed": True,
                    "still_reject_misread_motivation_or_source_relation": True,
                }
            return {
                "question": (
                    "Prüfe ausschließlich die lokale Quellenrelation dieses "
                    "Claims. Prüfe bei einer ausdrücklich tentativen, "
                    "falsifizierbaren Hypothese nur, ob ihre sichtbare "
                    "Motivation die zitierten Quellen korrekt liest; die "
                    "prognostizierte Vollkorpusrelation und ihr mögliches "
                    "Gegenresultat müssen noch nicht beobachtet sein. "
                    "Beurteile nicht, ob der Claim eine übergeordnete "
                    "Nutzerhypothese bereits beweist."
                ),
                "verification_stage": verification_stage,
                "observed_facts": [
                    fact
                    for fact in focused_facts
                    if str(fact.get("id", "")) in fact_ids
                ],
                "retrieval_candidate_assessments": [
                    {
                        key: copy.deepcopy(item[key])
                        for key in (
                            "fact_id",
                            "evaluated_object_type",
                            "evaluated_object_quote",
                            "verbatim_evaluative_source_phrases",
                        )
                        if key in item
                    }
                    for item in list(
                        retrieval_candidate_assessments or []
                    )
                    if str(item.get("fact_id", "")) in fact_ids
                ],
                "answer_envelope": {"claims": [claim]},
            }

        # Relation checks are deliberately atomic. In a batch, smaller local
        # models borrowed names and predicates from neighbouring passages and
        # then rejected faithful claims because those same words were allegedly
        # absent. One claim plus only its cited facts matches the semantics of
        # the gate and prevents cross-candidate contamination.
        def canonical_relation_items(
            payload: Any,
        ) -> tuple[Any, List[str]]:
            """Accept harmless structural aliases, then validate semantics."""

            if not isinstance(payload, dict):
                return None, []
            aliases: List[str] = []
            raw_items = payload.get("decisions")
            if not isinstance(raw_items, list):
                for alias_key in ("claims", "classifications"):
                    alias_items = payload.get(alias_key)
                    if isinstance(alias_items, list):
                        raw_items = alias_items
                        aliases.append(f"{alias_key}->decisions")
                        break
            if not isinstance(raw_items, list):
                return raw_items, aliases

            normalised_items: List[Any] = []
            for item in raw_items:
                if not isinstance(item, dict):
                    normalised_items.append(item)
                    continue
                normalised = dict(item)
                if not str(normalised.get("claim_id", "") or "").strip():
                    alias_id = str(normalised.get("id", "") or "").strip()
                    if alias_id:
                        normalised["claim_id"] = alias_id
                        aliases.append("id->claim_id")
                if not str(normalised.get("decision", "") or "").strip():
                    for alias_key in ("verdict", "classification"):
                        alias_value = str(
                            normalised.get(alias_key, "") or ""
                        ).strip()
                        if alias_value:
                            normalised["decision"] = alias_value
                            aliases.append(f"{alias_key}->decision")
                            break
                decision = str(
                    normalised.get("decision", "") or ""
                ).strip().casefold()
                decision_aliases = {
                    "accepted": "accept",
                    "grounded": "accept",
                    "pass": "accept",
                    "supported": "accept",
                    "verified": "accept",
                    "failed": "reject",
                    "rejected": "reject",
                    "unsupported": "reject",
                }
                canonical_decision = decision_aliases.get(decision, decision)
                if canonical_decision != decision:
                    normalised["decision"] = canonical_decision
                    aliases.append(
                        f"decision_value:{decision}->{canonical_decision}"
                    )
                normalised_items.append(normalised)
            return normalised_items, _dedupe_ordered_strs(aliases)

        relation_payloads: dict[str, dict[str, Any]] = {}
        decisions: List[Any] = []
        relation_schema_aliases: List[str] = []
        for claim in candidate_claims:
            projected_id = str(claim.get("id", ""))
            if not projected_id:
                continue
            relation_payload = atomic_relation_payload(claim)
            relation_payloads[projected_id] = relation_payload
            raw = await self._run_structured_step(
                doc=self._kwic_relation_adjudicator_doc,
                payload=relation_payload,
                schema=atomic_relation_schema(projected_id),
                temperature=0.0,
            )
            atomic_decisions, aliases = canonical_relation_items(raw)
            relation_schema_aliases.extend(aliases)
            if isinstance(atomic_decisions, list):
                decisions.extend(atomic_decisions)

        def relation_tokens(value: str) -> set[str]:
            stopwords = {
                "aber",
                "also",
                "and",
                "claim",
                "context",
                "dass",
                "eine",
                "einem",
                "einen",
                "einer",
                "fact",
                "from",
                "into",
                "oder",
                "source",
                "text",
                "that",
                "this",
                "with",
            }
            return {
                token.casefold()
                for token in re.findall(
                    r"[A-Za-zÄÖÜäöüß]{4,}",
                    str(value or ""),
                )
                if token.casefold() not in stopwords
            }

        def relation_summary_is_anchored(
            summary: str,
            surface: str,
        ) -> bool:
            surface_tokens = relation_tokens(surface)
            overlap = relation_tokens(summary).intersection(surface_tokens)
            required = 1 if len(surface_tokens) <= 3 else 2
            return len(overlap) >= required

        assessments_by_fact_id: dict[str, List[dict[str, Any]]] = {}
        for assessment in list(retrieval_candidate_assessments or []):
            fact_id = str(assessment.get("fact_id", "") or "")
            if fact_id:
                assessments_by_fact_id.setdefault(fact_id, []).append(
                    _project_retrieval_assessment(assessment, fact_id)
                )

        retrieval_diagnostics = dict(
            getattr(self, "_retrieval_audit_diagnostics", {}) or {}
        )
        asserted_property = str(
            retrieval_diagnostics.get("asserted_property", "") or ""
        )

        def projected_claim(projected_claim_id: str) -> dict[str, Any]:
            return next(
                (
                    item
                    for item in candidate_claims
                    if str(item.get("id", "")) == projected_claim_id
                ),
                {},
            )

        def claim_fact_ids(claim: dict[str, Any]) -> List[str]:
            return _dedupe_ordered_strs(
                [
                    str(value)
                    for value in list(claim.get("fact_ids", []) or [])
                    if str(value)
                ]
            )

        def claim_source_surface(claim: dict[str, Any]) -> str:
            return " ".join(
                fact_surface(focused_facts_by_id[fact_id])
                for fact_id in claim_fact_ids(claim)
                if fact_id in focused_facts_by_id
            )

        def local_interpretation(claim: dict[str, Any]) -> bool:
            text = str(claim.get("text", "") or "")
            explicit_valence = bool(
                _RETRIEVAL_NEGATIVE_READING_PATTERN.search(text)
                or _RETRIEVAL_AFFIRMATIVE_POSITIVE_PATTERN.search(text)
            )
            return bool(
                str(claim.get("claim_kind", "") or "")
                == "interpretation"
                and str(claim.get("assertion_level", "") or "")
                in {"qualified", "tentative"}
                and len(claim_fact_ids(claim)) == 1
                and (
                    _LOCAL_RETRIEVAL_SCOPE_PATTERN.search(text)
                    or not explicit_valence
                )
                and not _HYPOTHESIS_QUANTIFIER_PATTERN.search(text)
                and not _has_unbounded_retrieval_assertion(text)
            )

        def valence_matches_candidate_audit(
            claim: dict[str, Any],
        ) -> bool:
            text = str(claim.get("text", "") or "")
            negative = bool(
                _RETRIEVAL_NEGATIVE_READING_PATTERN.search(text)
                and not _NEGATED_NEGATIVE_READING_PATTERN.search(text)
            )
            positive = bool(
                _RETRIEVAL_AFFIRMATIVE_POSITIVE_PATTERN.search(text)
                and not _NEGATED_POSITIVE_READING_PATTERN.search(text)
            )
            property_negative = bool(
                _RETRIEVAL_NEGATIVE_READING_PATTERN.search(asserted_property)
            )
            property_positive = bool(
                _RETRIEVAL_AFFIRMATIVE_POSITIVE_PATTERN.search(
                    asserted_property
                )
            )
            if negative == positive or property_negative == property_positive:
                return False
            fact_id = claim_fact_ids(claim)[0]
            assessments = assessments_by_fact_id.get(fact_id, [])
            if len(assessments) != 1:
                return False
            assessment = assessments[0]
            relation = str(
                assessment.get("relation_to_requested_conclusion", "") or ""
            )
            if property_negative:
                if negative:
                    return relation in {"supports", "related_support"}
                return bool(
                    relation == "counterevidence"
                    and _reason_clearly_affirms_opposite_property(
                        assessment.get("reason", ""),
                        asserted_property,
                    )
                )
            if positive:
                return relation in {"supports", "related_support"}
            return bool(
                relation == "counterevidence"
                and _reason_clearly_affirms_opposite_property(
                    assessment.get("reason", ""),
                    asserted_property,
                )
            )

        def shared_quoted_predicate_token(
            diagnostic_text: str,
            source: str,
            claim_text: str,
        ) -> bool:
            source_tokens = {
                token.casefold()
                for token in re.findall(r"\w+", source, re.UNICODE)
                if len(token) >= 5
            }
            claim_tokens = {
                token.casefold()
                for token in re.findall(r"\w+", claim_text, re.UNICODE)
                if len(token) >= 5
            }
            quoted_tokens: set[str] = set()
            for opening, closing in _ASSESSMENT_QUOTE_WRAPPERS:
                for match in re.finditer(
                    re.escape(opening)
                    + r"([^\n]{1,160}?)"
                    + re.escape(closing),
                    diagnostic_text,
                ):
                    quoted_tokens.update(
                        token.casefold()
                        for token in re.findall(
                            r"\w+",
                            match.group(1),
                            re.UNICODE,
                        )
                        if len(token) >= 5
                    )
            return bool(quoted_tokens & source_tokens & claim_tokens)

        def false_interpretation_rejection(
            projected_claim_id: str,
            classification: dict[str, str],
        ) -> bool:
            """Reverse only a rejection that demands literal analytic prose."""

            claim = projected_claim(projected_claim_id)
            claim_text = str(claim.get("text", "") or "")
            source = claim_source_surface(claim)
            anchored_evaluative_phrases = [
                str(phrase)
                for fact_id in claim_fact_ids(claim)
                for assessment in assessments_by_fact_id.get(fact_id, [])
                for phrase in list(
                    assessment.get(
                        "verbatim_evaluative_source_phrases",
                        [],
                    )
                    or []
                )
                if str(phrase).strip()
                and _candidate_quote_is_anchored(str(phrase), source)
                and _candidate_quote_is_anchored(str(phrase), claim_text)
            ]
            mismatch = classification.get("mismatch")
            label_valence_mismatch = bool(
                mismatch == "invented_entity_type"
                and anchored_evaluative_phrases
                and _METALINGUISTIC_SOURCE_NOUN_PATTERN.search(claim_text)
            )
            if mismatch not in {"none", "predicate_shift"} and not (
                label_valence_mismatch
            ):
                return False
            bounded_label_interpretation = bool(
                label_valence_mismatch
                and str(claim.get("claim_kind", "") or "")
                == "interpretation"
                and str(claim.get("assertion_level", "") or "")
                in {"qualified", "tentative"}
                and len(claim_fact_ids(claim)) == 1
                and not _HYPOTHESIS_QUANTIFIER_PATTERN.search(claim_text)
                and not _has_unbounded_retrieval_assertion(claim_text)
            )
            deontic_metareading = _is_source_faithful_deontic_metareading(
                source,
                claim_text,
            )
            if not (
                local_interpretation(claim)
                or bounded_label_interpretation
                or deontic_metareading
            ):
                return False
            if _related_relation_token_count(source, claim_text) < 2:
                return False
            diagnostic = " ".join(
                [
                    classification.get("source_relation", ""),
                    classification.get("claim_relation", ""),
                    classification.get("reason", ""),
                ]
            )
            if _HARD_RELATION_MISMATCH_PATTERN.search(
                classification.get("reason", "")
            ):
                return False
            valence_only = bool(
                _NONLITERAL_VALENCE_REJECTION_PATTERN.search(diagnostic)
                and _ANALYTICAL_VALENCE_LABEL_PATTERN.search(diagnostic)
                and valence_matches_candidate_audit(claim)
            )
            literal_predicate_only = bool(
                classification.get("mismatch") == "predicate_shift"
                and _LITERAL_PREDICATE_MODALITY_REJECTION_PATTERN.search(
                    diagnostic
                )
                and shared_quoted_predicate_token(
                    diagnostic,
                    source,
                    claim_text,
                )
            )
            deontic_metareading_literalism = bool(
                classification.get("mismatch") in {"none", "predicate_shift"}
                and _LITERAL_DEONTIC_METAREADING_REJECTION_PATTERN.search(
                    diagnostic
                )
                and deontic_metareading
            )
            return (
                valence_only
                or literal_predicate_only
                or deontic_metareading_literalism
            )

        def false_testable_hypothesis_scope_rejection(
            projected_claim_id: str,
            classification: dict[str, str],
        ) -> bool:
            """Keep a proposal when rejection only demands its future result now."""

            claim = projected_claim(projected_claim_id)
            if not (
                classification.get("mismatch") == "scope_shift"
                and _is_explicit_testable_hypothesis_claim(claim)
            ):
                return False
            source = claim_source_surface(claim)
            claim_text = str(claim.get("text", "") or "")
            if _related_relation_token_count(source, claim_text) < 2:
                return False
            return bool(
                _HYPOTHESIS_SCOPE_LITERALISM_PATTERN.search(
                    str(classification.get("reason", "") or "")
                )
            )

        def unpreserved_evaluative_phrase(
            projected_claim_id: str,
        ) -> str:
            claim = next(
                (
                    item
                    for item in candidate_claims
                    if str(item.get("id", "")) == projected_claim_id
                ),
                None,
            )
            if not isinstance(claim, dict):
                return ""
            claim_text = str(claim.get("text", "") or "")
            source_text = claim_source_surface(claim)
            claim_tokens = {
                token.casefold()
                for token in re.findall(r"\w+", claim_text, re.UNICODE)
            }
            phrases = _dedupe_ordered_strs(
                [
                    str(phrase)
                    for fact_id in list(claim.get("fact_ids", []) or [])
                    for assessment in assessments_by_fact_id.get(
                        str(fact_id),
                        [],
                    )
                    for phrase in list(
                        assessment.get(
                            "verbatim_evaluative_source_phrases",
                            [],
                        )
                        or []
                    )
                    if str(phrase).strip()
                ]
            )
            for phrase in phrases:
                if _candidate_quote_is_anchored(phrase, claim_text):
                    continue
                phrase_tokens = {
                    token.casefold()
                    for token in re.findall(r"\w+", phrase, re.UNICODE)
                }
                # A partial reuse is the observable signature of replacing a
                # source label with a more neutral or stronger category.
                if phrase_tokens.intersection(claim_tokens) or (
                    _related_relation_token_count(phrase, claim_text) >= 1
                ) or _replaces_number_bound_evaluative_label(
                    source_text,
                    claim_text,
                    phrase,
                ):
                    return phrase
            return ""

        def parse_relation_decisions(
            items: List[Any],
            *,
            retain_rejected_none: bool = False,
        ) -> tuple[
            dict[str, List[dict[str, str]]],
            bool,
            bool,
        ]:
            by_claim: dict[str, List[dict[str, str]]] = {}
            invalid = len(items) != len(candidate_projected_ids)
            mismatch_only_repair = not invalid
            saw_decision_mismatch = False
            seen_internal_ids: set[str] = set()
            valid_mismatches = {
                "none",
                "participant_shift",
                "predicate_shift",
                "polarity_shift",
                "attachment_resolution",
                "invented_entity_type",
                "causal_strengthening",
                "scope_shift",
                "multiple",
            }
            for item in items:
                if not isinstance(item, dict):
                    invalid = True
                    mismatch_only_repair = False
                    continue
                internal_id, unknown_id = _resolve_projected_id(
                    item.get("claim_id"),
                    projected_to_internal_claims,
                )
                decision = str(
                    item.get("decision") or ""
                ).strip().casefold()
                mismatch = str(item.get("mismatch") or "").strip()
                source_relation = str(
                    item.get("source_relation") or ""
                ).strip()[:500]
                claim_relation = str(
                    item.get("claim_relation") or ""
                ).strip()[:500]
                reason = str(item.get("reason") or "").strip()[:500]
                relation_diagnostic = " ".join(
                    [source_relation, claim_relation, reason]
                )
                relation_denial = re.search(
                    r"\b(?:unsupported|not\s+supported|does\s+not\s+support|"
                    r"fails?\s+to\s+support|no\s+evidence|lacks?\s+evidence|"
                    r"does\s+not\s+match|not\s+corroborated|"
                    r"unbelegt\w*|nicht\s+(?:belegt|gestützt|gedeckt|"
                    r"bestätigt)|keine\s+Evidenz|weicht?\s+ab|"
                    r"Widerspruch|Abweichung)\b",
                    relation_diagnostic,
                    re.IGNORECASE,
                )
                relation_affirmation = re.search(
                    r"\b(?:support(?:s|ed|ing)?|corroborat\w*|confirm\w*|"
                    r"match(?:es|ed|ing)?|align(?:s|ed|ing)?|correspond\w*|"
                    r"consistent|no\s+mismatch|no\s+contradiction|"
                    r"bestätig\w*|beleg\w*|gedeckt\w*|gestützt\w*|"
                    r"entspr\w*|überein\w*|pass(?:t|en|end\w*)|"
                    r"kein\w*\s+Widerspruch|"
                    r"keine\s+Abweichung)\b",
                    relation_diagnostic,
                    re.IGNORECASE,
                )
                if (
                    decision == "reject"
                    and mismatch == "none"
                    and relation_affirmation is not None
                    and relation_denial is None
                ):
                    # The structured contract defines mismatch=none as an
                    # acceptance. Keep the semantically affirmative content
                    # instead of spending another stochastic adjudication turn
                    # on a self-contradictory label.
                    decision = "accept"
                summaries_anchored = bool(
                    relation_summary_is_anchored(
                        f"{source_relation} {reason}",
                        source_relation_surface_by_claim.get(
                            str(item.get("claim_id") or ""),
                            "",
                        ),
                    )
                    and relation_summary_is_anchored(
                        f"{claim_relation} {reason}",
                        claim_surface_by_projected_id.get(
                            str(item.get("claim_id") or ""),
                            "",
                        ),
                    )
                )
                core_valid = bool(
                    not unknown_id
                    and internal_id in candidate_internal_ids
                    and internal_id not in seen_internal_ids
                    and decision in {"accept", "reject"}
                    and mismatch in valid_mismatches
                    and summaries_anchored
                )
                if not core_valid:
                    invalid = True
                    mismatch_only_repair = False
                    continue
                seen_internal_ids.add(internal_id)
                decision_mismatch = bool(
                    (decision == "accept" and mismatch != "none")
                    or (decision == "reject" and mismatch == "none")
                )
                if decision_mismatch:
                    invalid = True
                    saw_decision_mismatch = True
                    # A second malformed `reject + none` still contains a
                    # usable negative assertion. Retain it after protocol
                    # recovery so deterministic source checks can reverse an
                    # objectively false rejection (for example an overlooked
                    # overt `wegen`). Never retain `accept + mismatch`.
                    if not (
                        retain_rejected_none
                        and decision == "reject"
                        and mismatch == "none"
                        and (
                            _CAUSAL_ABSENCE_REASON_PATTERN.search(
                                relation_diagnostic
                            )
                            is not None
                            or bool(
                                _NONLITERAL_VALENCE_REJECTION_PATTERN.search(
                                    relation_diagnostic
                                )
                                and _ANALYTICAL_VALENCE_LABEL_PATTERN.search(
                                    relation_diagnostic
                                )
                            )
                        )
                    ):
                        continue
                by_claim.setdefault(internal_id, []).append(
                    {
                        "decision": decision,
                        "source_relation": source_relation,
                        "claim_relation": claim_relation,
                        "mismatch": mismatch,
                        "reason": reason,
                    }
                )
            mismatch_only_repair = bool(
                mismatch_only_repair
                and saw_decision_mismatch
                and seen_internal_ids == candidate_internal_ids
            )
            return by_claim, invalid, mismatch_only_repair

        (
            by_internal_id,
            invalid_protocol,
            _decision_mismatch_only,
        ) = parse_relation_decisions(decisions)
        if invalid_protocol:
            protocol_repair = {
                "reclassify_from_source_and_claim": True,
                "do_not_preserve_previous_label_for_consistency": True,
                "accept_requires_mismatch_none": True,
                "reject_requires_concrete_non_none_mismatch": True,
                "source_relation_must_paraphrase_observed_facts": True,
                "claim_relation_must_paraphrase_the_actual_claim": True,
                "do_not_translate_relation_summaries": True,
                "copy_two_exact_source_content_words": True,
                "copy_two_exact_claim_content_words": True,
                "preserve_evaluative_source_labels": True,
                "adjacency_is_not_causality": True,
                "global_hypothesis_is_still_not_under_review": True,
                "analytical_valence_need_not_be_verbatim": True,
                "same_verbatim_predicate_keeps_its_lexical_strength": True,
                "instruction": (
                    "Die vorige Ausgabe war formal widersprüchlich oder "
                    "unvollständig. Prüfe erneut die lokale Quellenrelation. "
                    "source_relation muss die sichtbare Quellenstruktur und "
                    "claim_relation die tatsächlich behauptete Struktur "
                    "inhaltlich wiedergeben; generische Wörter wie local, "
                    "supported oder interpretation genügen nicht. "
                    "Übersetze die Relationszusammenfassungen nicht: "
                    "source_relation kopiert mindestens zwei Inhaltswörter "
                    "zeichengetreu aus observed_facts, claim_relation "
                    "mindestens zwei aus dem zugehörigen Claim. "
                    "Bewertende Personen- und Gruppenbezeichnungen dürfen "
                    "weder euphemisiert noch verschärft werden; eine solche "
                    "Umbenennung ist predicate_shift. Eine bloße Abfolge ohne "
                    "sichtbaren Kausalmarker trägt kein 'weil' und keine "
                    "Ursachenzuschreibung. "
                    "Eine quellennahe analytische Bezeichnung wie positive "
                    "oder negative Rahmung muss nicht selbst wörtlich in der "
                    "Quelle stehen; prüfe, ob sie aus deren sichtbarem "
                    "Prädikat und Bewertungsobjekt folgt. Wenn Claim und "
                    "Quelle dasselbe Prädikat wörtlich verwenden, darfst du "
                    "dem Claim nicht allein eine stärkere lexikalische "
                    "Modalität unterstellen. "
                    "Wenn die einzige Sorge lautet, dass ein ausdrücklich "
                    "lokaler Claim die globale Nutzerhypothese nicht beweist, "
                    "ist das kein Relationsfehler und der lokale Claim wird "
                    "akzeptiert. Bei einer ausdrücklich tentativen, "
                    "falsifizierbaren Hypothese prüfst du die sichtbare "
                    "empirische Motivation. Die vorhergesagte Relation einer "
                    "Vollauswertung und das mögliche Gegenresultat sind "
                    "prospektive Vorschläge; lehne sie nicht allein deshalb "
                    "ab, weil sie noch nicht in observed_facts eingetreten "
                    "sind. Eine falsche Lesart der motivierenden Passage "
                    "bleibt dagegen ein Relationsfehler. Bei einer echten "
                    "Abweichung wähle reject und "
                    "benenne genau den passenden mismatch-Wert."
                ),
            }
            previous_decisions = list(decisions)
            decisions = []
            for claim in candidate_claims:
                projected_id = str(claim.get("id", ""))
                if not projected_id:
                    continue
                recovery_payload = copy.deepcopy(
                    relation_payloads[projected_id]
                )
                recovery_payload["previous_invalid_decisions"] = [
                    item
                    for item in previous_decisions
                    if isinstance(item, dict)
                    and str(item.get("claim_id", "")) == projected_id
                ]
                recovery_payload["protocol_repair"] = copy.deepcopy(
                    protocol_repair
                )
                recovered_raw = await self._run_structured_step(
                    doc=self._kwic_relation_adjudicator_doc,
                    payload=recovery_payload,
                    schema=atomic_relation_schema(projected_id),
                    temperature=0.0,
                )
                recovered_decisions, aliases = canonical_relation_items(
                    recovered_raw
                )
                relation_schema_aliases.extend(aliases)
                if isinstance(recovered_decisions, list):
                    decisions.extend(recovered_decisions)
            (
                by_internal_id,
                invalid_protocol,
                _still_recoverable,
            ) = parse_relation_decisions(
                decisions,
                retain_rejected_none=True,
            )
            self._relation_protocol_recovery_count = int(
                getattr(
                    self,
                    "_relation_protocol_recovery_count",
                    0,
                )
                or 0
            ) + 1

        accepted: set[str] = set()
        rejected: set[str] = set()
        reasons_by_claim: dict[str, List[str]] = {}
        projected_by_internal_id = {
            internal_id: projected_id
            for projected_id, internal_id in projected_to_internal_claims.items()
            if internal_id
        }
        target_topic = str(
            self._retrieval_audit_diagnostics.get("target_topic", "") or ""
        )
        for internal_id in candidate_internal_ids:
            classifications = by_internal_id.get(internal_id, [])
            if len(classifications) != 1:
                invalid_protocol = True
                continue
            classification = classifications[0]
            projected_id = projected_by_internal_id.get(internal_id, "")
            claim_payload = next(
                (
                    item
                    for item in candidate_claims
                    if str(item.get("id", "")) == projected_id
                ),
                {},
            )
            claim_text = str(claim_payload.get("text", "") or "")
            cited_fact_payloads = [
                focused_facts_by_id[fact_id]
                for fact_id in [
                    str(value)
                    for value in list(claim_payload.get("fact_ids", []) or [])
                ]
                if fact_id in focused_facts_by_id
            ]
            source_surface = " ".join(
                _candidate_source_quote(payload)
                or str(payload.get("statement", "") or "")
                for payload in cited_fact_payloads
            )
            static_relation_reasons: List[str] = []
            dropped_relation_head = _dropped_related_object_head(
                source_surface,
                claim_text,
                target_topic,
            )
            if dropped_relation_head:
                static_relation_reasons.append(
                    "Der Claim lässt den relationalen Kopf "
                    f"{dropped_relation_head!r} aus dem Quellenausdruck weg "
                    "und überträgt dessen Prädikat dadurch auf das abhängige "
                    "Zielobjekt. Bewahre Relationen wie 'X von Y', statt X "
                    "mit Y oder dem abstrakten Zielthema gleichzusetzen."
                )
            if (
                {
                    str(fact_id)
                    for fact_id in list(claim_payload.get("fact_ids", []) or [])
                }.intersection(retrieval_source_fact_ids)
                and not _retrieval_interpretation_is_source_bound(claim_text)
            ):
                static_relation_reasons.append(
                    "Der Claim formuliert die in einem Korpusausschnitt "
                    "geäußerte Proposition als unmarkierte Sachbehauptung. "
                    "Binde die Deutung sprachlich an Passage, Wortlaut oder "
                    "Äußerung; die lokale Interpretation bleibt dabei erlaubt."
                )
            if _recasts_exchange_contrast_as_interpersonal_relation(
                source_surface,
                claim_text,
                target_topic,
            ):
                static_relation_reasons.append(
                    "Der Claim deutet den sichtbaren Austauschkontrast "
                    "('her mit X / raus mit Y') als Dialog, Kommunikation oder "
                    "Interaktion mit dem Zielobjekt um. Der Wortlaut trägt nur "
                    "die kontrastierte Präferenz; Wortverwandtschaft zwischen "
                    "'Tausch' und 'Austausch' belegt keine gleiche Relation."
                )
            missing_phrase = unpreserved_evaluative_phrase(projected_id)
            if missing_phrase:
                static_relation_reasons.append(
                    "Der Claim ersetzt die im Kandidatenaudit als wertend "
                    f"identifizierte Quellenbezeichnung {missing_phrase!r} "
                    "ganz oder teilweise und verändert dadurch ihre Bedeutung. "
                    "Der Ausdruck muss als Quellenwortlaut vollständig erhalten "
                    "oder ohne neutrale beziehungsweise stärkere Ersatzkategorie "
                    "weggelassen werden."
                )
            misbound_phrase = _misbinds_evaluative_source_phrase(
                source_surface,
                claim_text,
                [
                    str(phrase)
                    for fact_id in list(claim_payload.get("fact_ids", []) or [])
                    for assessment in assessments_by_fact_id.get(
                        str(fact_id),
                        [],
                    )
                    for phrase in list(
                        assessment.get(
                            "verbatim_evaluative_source_phrases",
                            [],
                        )
                        or []
                    )
                    if str(phrase).strip()
                ],
            )
            if misbound_phrase:
                static_relation_reasons.append(
                    "Der Claim bindet die wertende Quellenbezeichnung "
                    f"{misbound_phrase!r} an eine Forderung, Politik oder "
                    "Aussage statt an ihren Personen- oder Gruppenreferenten. "
                    "Bewahre das grammatische Bewertungsobjekt."
                )
            if _distributive_adverb_became_subset(
                source_surface,
                claim_text,
            ):
                static_relation_reasons.append(
                    "Der Claim macht aus einer distributiven Artangabe der "
                    "Quelle (zum Beispiel 'die Staaten ... einzeln') einen "
                    "indefiniten Teilmengenquantor ('einzelne Staaten'). "
                    "Bewahre die grammatische Funktion und damit die "
                    "Reichweite der Proposition."
                )
            if _introduces_unsupported_parallel_symmetry(
                source_surface,
                claim_text,
            ):
                static_relation_reasons.append(
                    "Der Claim macht aus der parallelen Nennung mehrerer "
                    "Beteiligter eine gleich gewichtete, symmetrische oder "
                    "gleichzeitige Beteiligung. Die Quelle trägt nur den "
                    "gemeinsamen Geltungsbereich der Anforderung; Gewicht, "
                    "Verhältnis und zeitliche Koordination bleiben offen."
                )
            if (
                _causal_relation_sides(claim_text) is not None
                and not _explicit_source_causality_matches_claim(
                    claim_text,
                    cited_fact_payloads,
                )
            ):
                static_relation_reasons.append(
                    "Der Claim führt eine explizite Kausalrelation ein, die "
                    "der zitierte Wortlaut für dieselben Beteiligten und "
                    "Prädikate nicht markiert. Satznachbarschaft oder eine "
                    "unpunktierte Abfolge trägt kein 'weil' und keine "
                    "Ursachenzuschreibung."
                )
            if _introduces_unsupported_reciprocity(
                source_surface,
                claim_text,
            ):
                static_relation_reasons.append(
                    "Der Claim macht aus parallelen Anforderungen an mehrere "
                    "Beteiligte eine wechselseitige oder gegenseitige "
                    "Relation. Dafür braucht die Quelle einen sichtbaren "
                    "Reziprozitätsmarker."
                )
            if _introduces_unsupported_adversative_relation(
                source_surface,
                claim_text,
            ):
                static_relation_reasons.append(
                    "Der Claim macht aus der sichtbar geordneten Abfolge "
                    "zweier Handlungen einen Gegensatz. Bewahre die zeitliche "
                    "Ordnung, solange die Quelle keinen adversativen Marker "
                    "enthält."
                )
            if _introduces_unbound_cross_claim_reference(
                source_surface,
                claim_text,
                cited_fact_count=len(cited_fact_payloads),
            ):
                static_relation_reasons.append(
                    "Der Claim verweist auf eine frühere oder kontrastierende "
                    "Darstellung, belegt aber nur eine Seite. Formuliere ihn "
                    "eigenständig oder referenziere die Evidenz beider Seiten "
                    "im selben Claim; andernfalls wird nach dem Verwerfen "
                    "eines Geschwister-Claims ein unbelegter Rückverweis "
                    "sichtbar."
                )
            if any(
                _assigns_leading_handle_as_source_actor(
                    _candidate_source_quote(payload)
                    or str(payload.get("statement", "") or ""),
                    claim_text,
                )
                for payload in cited_fact_payloads
            ):
                static_relation_reasons.append(
                    "Ein vorangestelltes @Handle belegt einen sichtbaren "
                    "Adressaten oder eine Erwähnung, aber ohne Metadaten "
                    "weder Autorenschaft noch die im Claim zugeschriebene "
                    "Handlung. Formuliere die Passage als Quelle der "
                    "Äußerung, nicht das Handle als Sprecher oder Akteur."
                )
            if _introduces_unresolved_attribution(
                source_surface,
                claim_text,
            ):
                static_relation_reasons.append(
                    "Der unpunktierte oder berichtende Quellenausschnitt trägt "
                    "die neu formulierte Urheber-, Vertreter- oder "
                    "Unterstützerzuschreibung nicht. Mache insbesondere den "
                    "Akteur eines Berichtsrahmens nicht zum Handelnden der "
                    "eingebetteten Proposition."
                )
            if _merges_distinct_sentence_complements(
                cited_fact_payloads,
                claim_text,
            ):
                static_relation_reasons.append(
                    "Der Claim verschmilzt nominale Relationen aus getrennten "
                    "Sätzen und überträgt dabei das Objekt einer Relation auf "
                    "eine andere. Bewahre pro sentence_unit den sichtbaren "
                    "Relationskopf und sein eigenes Komplement."
                )
            if _drops_source_deontic_modality(
                source_surface,
                claim_text,
            ):
                static_relation_reasons.append(
                    "Der Claim macht aus einer sichtbaren Forderung, Pflicht "
                    "oder Sollenszuschreibung eine bereits bestehende Handlung "
                    "oder Akteursrolle. Bewahre die deontische Modalität oder "
                    "formuliere sie als Forderungs- beziehungsweise "
                    "Verantwortungsrahmung."
                )
            if _introduces_unsupported_advocacy(
                source_surface,
                claim_text,
            ):
                static_relation_reasons.append(
                    "Der Claim führt eine Forderung oder Befürwortung ein, "
                    "die der sichtbare Wortlaut nicht trägt, oder macht den "
                    "Text selbst zum Handelnden eines Prädikats, das in der "
                    "Quelle einem anderen oder offenen Beteiligten zugeordnet "
                    "ist. Formuliere die sichtbare Forderung metasprachlich, "
                    "ohne ihren Akteur umzubinden."
                )
            if _introduces_unsupported_purpose(
                source_surface,
                claim_text,
            ):
                static_relation_reasons.append(
                    "Der Claim führt mit einer Zweckkonstruktion eine Absicht "
                    "oder kommunikative Zielrelation ein, die im sichtbaren "
                    "Quelltext nicht markiert ist. Formuliere die beobachtbare "
                    "Wirkung als tentative Deutung statt als Teilnehmerabsicht."
                )
            if _introduces_unsupported_indem_relation(
                source_surface,
                claim_text,
            ):
                static_relation_reasons.append(
                    "Der Claim führt mit 'indem' eine Mittel- oder "
                    "Begründungsrelation ein, die der sichtbare Wortlaut weder "
                    "mit 'indem' noch durch eine lokal passende "
                    "Instrumentalkonstruktion trägt. Bewahre die Propositionen "
                    "getrennt oder beschreibe nur ihr sichtbares Nebeneinander."
                )
            if (
                confirmation_pressure
                and len(cited_fact_payloads) == 1
                and _is_mechanical_source_restatement(
                    claim_text,
                    _candidate_source_quote(cited_fact_payloads[0])
                    or str(cited_fact_payloads[0].get("statement", "") or ""),
                )
            ):
                static_relation_reasons.append(
                    "Der Claim füllt einen Interpretationsslot nur mit einer "
                    "Nacherzählung des Quellsatzes. Benenne die konkrete "
                    "Rahmung, Positionierung oder kommunikative Funktion, "
                    "ohne die Quellenrelation zu verändern."
                )
            if static_relation_reasons:
                rejected.add(internal_id)
                reasons_by_claim[internal_id] = _dedupe_ordered_strs(
                    static_relation_reasons
                )
                continue
            if (
                classification["decision"] == "reject"
                and false_testable_hypothesis_scope_rejection(
                    projected_id,
                    classification,
                )
            ):
                # A falsifiable prediction is not an observed prevalence
                # claim. Its cited motivation remains subject to every static
                # participant, predicate, polarity and causality check above.
                accepted.add(internal_id)
                continue
            if (
                classification["decision"] == "reject"
                and false_interpretation_rejection(
                    projected_id,
                    classification,
                )
            ):
                # A bounded interpretation need not occur verbatim in its
                # source. This reversal is unavailable for participant,
                # polarity, causality, number, attachment or scope concerns.
                accepted.add(internal_id)
                continue
            alleged_missing_causality = " ".join(
                [
                    classification.get("source_relation", ""),
                    classification.get("claim_relation", ""),
                    classification.get("reason", ""),
                ]
            )
            if (
                classification["decision"] == "reject"
                and classification["mismatch"]
                in {
                    "none",
                    "predicate_shift",
                    "causal_strengthening",
                    "invented_entity_type",
                    "scope_shift",
                }
                and (
                    _CAUSAL_ABSENCE_REASON_PATTERN.search(
                        alleged_missing_causality
                    )
                    is not None
                    or (
                        classification["mismatch"] == "scope_shift"
                        and _CAUSAL_EXCLUSIVITY_PATTERN.search(
                            alleged_missing_causality
                        )
                        is not None
                        and _CAUSAL_EXCLUSIVITY_PATTERN.search(
                            str(claim_payload.get("text", "") or "")
                        )
                        is None
                    )
                )
                and _explicit_source_causality_matches_claim(
                    str(claim_payload.get("text", "") or ""),
                    cited_fact_payloads,
                )
            ):
                # The semantic auditor may overlook an overt marker such as
                # "wegen". Preserve its direction, but never infer causality
                # from adjacency or carry it across a sentence boundary.
                accepted.add(internal_id)
                continue
            if classification["decision"] == "accept":
                accepted.add(internal_id)
                continue
            rejected.add(internal_id)
            details = [
                f"Quellenrelation: {classification['source_relation']}",
                f"Claimrelation: {classification['claim_relation']}",
                (
                    f"Abweichung ({classification['mismatch']}): "
                    f"{classification['reason']}"
                ),
            ]
            reasons_by_claim[internal_id] = [
                "; ".join(part for part in details if part.split(": ", 1)[-1])
            ]

        # This is a supplementary veto. Protocol failure must not erase a
        # claim already accepted by the primary verifier. It remains fail
        # closed only for claims that need this pass for promotion or repair.
        unclassified_ids = candidate_internal_ids - accepted - rejected
        if invalid_protocol and unclassified_ids:
            required_unclassified = (
                unclassified_ids & protocol_required_ids
            )
            accepted.update(unclassified_ids - protocol_required_ids)
            rejected.update(required_unclassified)
            for internal_id in required_unclassified:
                reasons_by_claim.setdefault(
                    internal_id,
                    [
                        "Der zweite KWIC-Quellenabgleich lieferte keine "
                        "vollständige, widerspruchsfreie Relationsprüfung."
                    ],
                )
        if relation_schema_aliases:
            self._relation_schema_aliases = _dedupe_ordered_strs(
                list(getattr(self, "_relation_schema_aliases", []) or [])
                + relation_schema_aliases
            )
        return accepted, rejected, reasons_by_claim

    async def verify_envelope(
        self,
        contract: Any,
        observed_facts: List[Any],
        envelope: Any,
        *,
        retrieval_candidate_assessments: Optional[
            List[dict[str, str]]
        ] = None,
        preapproved_semantic_signatures: Optional[
            set[tuple[str, tuple[str, ...], str]]
        ] = None,
    ) -> Any:
        """LLM verdict reconciled with deterministic runtime validation.

        Verbatim port of ``orchestrator._verify_answer_envelope``.
        """
        metadata_binding_repairs = _repair_word_sketch_metadata_fact_bindings(
            contract,
            envelope,
            observed_facts,
        )
        if metadata_binding_repairs:
            envelope._fact_binding_repairs = _dedupe_ordered_strs(
                list(getattr(envelope, "_fact_binding_repairs", []) or [])
                + metadata_binding_repairs
            )
        row_binding_repairs = _repair_word_sketch_row_fact_bindings(
            contract,
            envelope,
            observed_facts,
        )
        if row_binding_repairs:
            envelope._fact_binding_repairs = _dedupe_ordered_strs(
                list(getattr(envelope, "_fact_binding_repairs", []) or [])
                + row_binding_repairs
            )
        self._repair_literal_fact_bindings(
            contract,
            observed_facts,
            envelope,
        )
        repaired_epistemic_kinds = (
            _repair_epistemic_limitation_claim_kinds(
                envelope,
                observed_facts,
            )
        )
        if repaired_epistemic_kinds:
            envelope._epistemic_limitation_kind_repairs = (
                repaired_epistemic_kinds
            )
        repaired_negative_kinds = _repair_direct_negative_result_claim_kinds(
            envelope,
            observed_facts,
        )
        if repaired_negative_kinds:
            envelope._negative_result_kind_repairs = (
                repaired_negative_kinds
            )
        repaired_attestation_kinds = (
            _repair_direct_attestation_claim_kinds(
                envelope,
                observed_facts,
            )
        )
        if repaired_attestation_kinds:
            envelope._attestation_kind_repairs = (
                repaired_attestation_kinds
            )
        repaired_word_sketch_kinds = (
            _repair_direct_word_sketch_claim_kinds(
                contract,
                envelope,
                observed_facts,
                interpretation_is_substantive=(
                    self._word_sketch_interpretation_complete
                ),
            )
        )
        if repaired_word_sketch_kinds:
            envelope._word_sketch_kind_repairs = (
                repaired_word_sketch_kinds
            )
        competing_hypothesis_requirement_ids = (
            _competing_hypothesis_requirement_ids(
                contract,
                self._question_text,
            )
        )
        competing_requirement_id_set = set(
            competing_hypothesis_requirement_ids
        )
        competing_hypothesis_claim_ids = [
            str(getattr(claim, "id", "") or "").strip()
            for claim in list(getattr(envelope, "claims", []) or [])
            if str(
                getattr(claim, "response_requirement_id", "") or ""
            ).strip()
            in competing_requirement_id_set
            and _is_explicit_testable_hypothesis_claim(
                {
                    "text": str(getattr(claim, "text", "") or ""),
                    "claim_kind": str(
                        getattr(claim, "claim_kind", "") or ""
                    ),
                    "assertion_level": str(
                        getattr(claim, "assertion_level", "") or ""
                    ),
                }
            )
            and str(getattr(claim, "id", "") or "").strip()
        ]
        competing_pair_ready = bool(
            competing_hypothesis_requirement_ids
            and len(competing_hypothesis_claim_ids)
            == len(competing_hypothesis_requirement_ids)
        )
        fact_payloads, projected_to_internal_facts = _project_facts(
            observed_facts
        )
        internal_to_projected_facts = {
            internal_id: projected_id
            for projected_id, internal_id in projected_to_internal_facts.items()
            if internal_id
        }
        projected_retrieval_assessments = [
            _project_retrieval_assessment(
                assessment,
                internal_to_projected_facts[
                    str(assessment.get("fact_id", ""))
                ],
            )
            for assessment in list(
                retrieval_candidate_assessments or []
            )
            if str(assessment.get("fact_id", ""))
            in internal_to_projected_facts
        ]
        verifier_claims, projected_to_internal = _project_claims(
            list(getattr(envelope, "claims", []) or []),
            prefix="v",
        )
        _rewrite_claim_payload_fact_ids(
            verifier_claims,
            internal_to_projected_facts,
        )
        competing_hypothesis_projected_ids = [
            projected_id
            for projected_id, internal_id in projected_to_internal.items()
            if internal_id in set(competing_hypothesis_claim_ids)
        ]
        multi_fact_claims = {
            str(claim.get("id", "")): _dedupe_ordered_strs(
                [
                    str(fact_id)
                    for fact_id in list(claim.get("fact_ids", []) or [])
                    if str(fact_id)
                ]
            )
            for claim in verifier_claims
            if len(
                {
                    str(fact_id)
                    for fact_id in list(claim.get("fact_ids", []) or [])
                    if str(fact_id)
                }
            )
            > 1
        }
        schema = copy.deepcopy(self._grounding_verdict_schema())
        if projected_to_internal:
            valid_claim_ids = list(projected_to_internal)
            verdict_properties = schema["schema"]["properties"]
            verdict_properties["accepted_claim_ids"]["items"]["enum"] = (
                valid_claim_ids
            )
            verdict_properties["rejected_claim_ids"]["items"]["enum"] = (
                valid_claim_ids
            )
        if multi_fact_claims:
            verdict_schema = schema["schema"]
            verdict_properties = verdict_schema["properties"]
            valid_usage_fact_ids = _dedupe_ordered_strs(
                [
                    fact_id
                    for fact_ids in multi_fact_claims.values()
                    for fact_id in fact_ids
                ]
            )
            fact_id_list_schema = {
                "type": "array",
                "maxItems": max(len(ids) for ids in multi_fact_claims.values()),
                "items": {
                    "type": "string",
                    "enum": valid_usage_fact_ids,
                },
            }
            verdict_properties["claim_fact_usage"] = {
                "type": "array",
                "minItems": len(multi_fact_claims),
                "maxItems": len(multi_fact_claims),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "claim_id": {
                            "type": "string",
                            "enum": list(multi_fact_claims),
                        },
                        "used_fact_ids": copy.deepcopy(fact_id_list_schema),
                        "unused_fact_ids": copy.deepcopy(fact_id_list_schema),
                    },
                    "required": [
                        "claim_id",
                        "used_fact_ids",
                        "unused_fact_ids",
                    ],
                },
            }
            verdict_schema.setdefault("required", []).append(
                "claim_fact_usage"
            )
        response_requirement_ids = [
            str(getattr(requirement, "id", "") or "").strip()
            for requirement in list(
                getattr(contract, "response_requirements", []) or []
            )
            if str(getattr(requirement, "id", "") or "").strip()
        ]
        if response_requirement_ids:
            verdict_schema = schema["schema"]
            verdict_properties = verdict_schema["properties"]
            requirement_id_schema = {
                "type": "array",
                "maxItems": len(response_requirement_ids),
                "items": {
                    "type": "string",
                    "enum": list(response_requirement_ids),
                },
            }
            verdict_properties["fulfilled_response_requirement_ids"] = (
                copy.deepcopy(requirement_id_schema)
            )
            verdict_properties["unfulfilled_response_requirement_ids"] = (
                copy.deepcopy(requirement_id_schema)
            )
            verdict_schema.setdefault("required", []).extend(
                [
                    "fulfilled_response_requirement_ids",
                    "unfulfilled_response_requirement_ids",
                ]
            )
        if competing_pair_ready:
            verdict_schema = schema["schema"]
            verdict_properties = verdict_schema["properties"]
            verdict_properties["hypothesis_pair_assessment"] = {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "same_operationalization": {"type": "boolean"},
                    "differentiating_predictions": {"type": "boolean"},
                    "pair_valid": {"type": "boolean"},
                    "reason": {
                        "type": "string",
                        "maxLength": 500,
                    },
                },
                "required": [
                    "same_operationalization",
                    "differentiating_predictions",
                    "pair_valid",
                    "reason",
                ],
            }
            verdict_schema.setdefault("required", []).append(
                "hypothesis_pair_assessment"
            )
        confirmation_pressure = (
            self._needs_confirmation_retrieval_adjudication(contract)
        )
        # Exhaustive candidate accounting belongs to the adversarial
        # confirmation audit. Treating every ranked row or KWIC example as a
        # candidate set made ordinary keyness, n-gram, Word-Sketch and KWIC
        # analyses fail for lacking a classification step they never require.
        retrieval_internal_ids = [
            str(getattr(fact, "id", "") or "").strip()
            for fact in _unique_retrieval_candidate_facts(observed_facts)
            if str(getattr(fact, "id", "") or "").strip()
            and (
                confirmation_pressure
                or (
                    contract.deliverable_kind
                    in {"analysis_report", "contrast_report", "overview"}
                    and _is_semantic_retrieval_candidate_fact(fact)
                )
            )
        ]
        retrieval_projected_ids = [
            internal_to_projected_facts[fact_id]
            for fact_id in retrieval_internal_ids
            if fact_id in internal_to_projected_facts
        ]
        referenced_projected_fact_ids = {
            str(fact_id)
            for claim in verifier_claims
            for fact_id in list(claim.get("fact_ids", []) or [])
            if str(fact_id)
        }
        verifier_fact_ids = referenced_projected_fact_ids.union(
            retrieval_projected_ids
        )
        verifier_fact_payloads = [
            fact
            for fact in fact_payloads
            if str(fact.get("id", "")) in verifier_fact_ids
        ]
        if not verifier_fact_payloads:
            verifier_fact_payloads = fact_payloads
        if retrieval_projected_ids:
            verdict_schema = schema["schema"]
            verdict_properties = verdict_schema["properties"]
            retrieval_id_schema = {
                "type": "array",
                "maxItems": len(retrieval_projected_ids),
                "items": {
                    "type": "string",
                    "enum": list(retrieval_projected_ids),
                },
            }
            verdict_properties["accounted_retrieval_fact_ids"] = (
                copy.deepcopy(retrieval_id_schema)
            )
            verdict_properties["unaccounted_retrieval_fact_ids"] = (
                copy.deepcopy(retrieval_id_schema)
            )
            verdict_schema.setdefault("required", []).extend(
                [
                    "accounted_retrieval_fact_ids",
                    "unaccounted_retrieval_fact_ids",
                ]
            )
        contract_payload = {
            key: value
            for key, value in contract.to_dict().items()
            if key
            in {
                "track",
                "analysis_family",
                "deliverable_kind",
                "question_scope",
                "forbidden_claims",
                "response_requirements",
            }
        }
        if response_requirement_ids:
            contract_payload["response_requirements"] = (
                _response_requirement_generation_payloads(
                    list(
                        getattr(contract, "response_requirements", []) or []
                    )
                )
            )
        if confirmation_pressure:
            contract_payload.pop("question_scope", None)
        verification_stage: dict[str, Any] = {
            "tool_execution_complete": True,
            "classify_supplied_evidence_only": True,
        }
        testable_hypothesis_projected_ids = [
            str(claim.get("id", "") or "")
            for claim in verifier_claims
            if _is_explicit_testable_hypothesis_claim(claim)
        ]
        if testable_hypothesis_projected_ids:
            verification_stage["testable_hypothesis_policy"] = {
                "claim_ids": testable_hypothesis_projected_ids,
                "audit_visible_motivation_against_sources": True,
                "predicted_full_corpus_relation_is_prospective": True,
                "possible_counter_result_is_prospective": True,
                "do_not_require_prediction_or_counter_result_to_be_observed": True,
                "still_reject_misread_motivation_or_source_relation": True,
            }
        if response_requirement_ids:
            verification_stage["response_slot_policy"] = {
                "counted_siblings_are_atomic_units": True,
                "judge_total_count_via_slot_partition_only": True,
                "never_require_one_claim_to_supply_all_sibling_units": True,
                "atomicity_is_one_proposition_not_one_fact": True,
                "multiple_facts_may_jointly_support_one_pattern_or_contrast": True,
            }
        if competing_pair_ready:
            verification_stage["competing_hypothesis_pair_policy"] = {
                "claim_ids": competing_hypothesis_projected_ids,
                "judge_pair_structure_not_empirical_truth": True,
                "same_later_operationalization_required": True,
                "predictions_must_allow_one_result_to_discriminate": True,
                "simultaneously_possible_different_topics_are_not_competing": True,
                "do_not_require_either_prediction_to_be_observed_now": True,
                "pair_valid_requires_both_boolean_conditions": True,
            }
        if multi_fact_claims:
            verification_stage["claim_fact_usage_policy"] = {
                "classify_every_listed_fact_once": True,
                "used_means_substantively_expressed_premise_or_boundary": True,
                "citation_padding_is_unused": True,
                "free_interpretation_remains_allowed": True,
            }
        verification_question = self._question_text
        if confirmation_pressure:
            # Candidate direction and global hypothesis scope were already
            # audited independently. Repeating the loaded hypothesis here made
            # local models reject a source-faithful passage reading merely
            # because one passage cannot prove a universal corpus claim. This
            # verifier owns local fact fidelity only; deterministic composition
            # below still enforces balanced candidate coverage and scope.
            verification_stage["local_claim_scope_policy"] = {
                "evaluate_each_claim_at_its_own_scope": True,
                "compare_only_with_referenced_facts": True,
                "original_hypothesis_withheld_as_irrelevant": True,
            }
            verification_question = (
                "Prüfe jeden atomaren Claim ergebnisoffen ausschließlich in "
                "seiner eigenen ausdrücklich formulierten Reichweite gegen "
                "seine referenzierten Fakten. Die ursprüngliche "
                "Nutzerhypothese und Bestätigungsrichtung sind absichtlich "
                "nicht Teil dieser lokalen Faktentreueprüfung."
            )
        if projected_retrieval_assessments:
            verification_stage["retrieval_assessment_policy"] = (
                "The candidate audit is an independent, quote-bound analytical "
                "check, not corpus evidence. Verify its labels against the raw "
                "facts, preserve counterevidence and off-topic candidates, and "
                "do not relabel them merely to satisfy the requested conclusion. "
                "Treat evaluated_object_type as a scope boundary: a property "
                "attached to an associated group, actor, policy, practice, effect "
                "or outcome, including a generic associated_object, must not be "
                "attributed to target_topic itself. Reject "
                "a claim that collapses those objects, but do not reject a "
                "careful interpretation that names the related object explicitly."
            )
        if str(getattr(contract, "analysis_family", "") or "") == "ngram_profile":
            verification_stage["bounded_interpretation_policy"] = (
                "A named visible sequence may support a tentative, explicitly "
                "testable routine hypothesis. Do not demand that the hypothesis "
                "itself occur verbatim in the fact; reject only categorical "
                "formulaicity, invented context, or an unbound generic label."
            )
        elif str(getattr(contract, "analysis_family", "") or "") == "kwic_context":
            verification_stage["bounded_interpretation_policy"] = (
                "The user explicitly requests interpretation after inspecting "
                "the expanded context or a bounded multi-row KWIC selection, "
                "so do not dismiss interpretation as "
                "unnecessary once presence is proven. Accept a cautious local "
                "reading whose premises are visible. A multi-row synthesis must "
                "remain bounded to the selected rows and cite each row it uses; "
                "it does not imply a frequency distribution. No parse is needed to state "
                "two plausible attachment options or to keep attachment open. "
                "Check speaker, addressee and referents literally: a visible "
                "pronoun or handle must not be replaced by a nearby named entity "
                "without explicit coreference or addressee evidence. Reject a "
                "resolved attachment, participant shift or invented premise, not "
                "the act of bounded interpretation itself. "
                "When a claim paraphrases the passage, require it to preserve the "
                "visible predicate's polarity, agent, object and event type; reject "
                "a stronger or different activity rather than treating it as a "
                "free interpretive gloss. "
                "For a propositional paraphrase, identify the source predicate and "
                "the claim predicate explicitly before accepting it; a substituted "
                "verb must not change participants or their relation. "
                "If a weaker claim and "
                "a more precise accepted claim express the same analytical point, "
                "reject the weaker one as redundant and name both claim IDs in "
                "that reason."
            )
        raw = await self._run_structured_step(
            doc=(
                _CONFIRMATION_LOCAL_GROUNDING_DOC
                if confirmation_pressure
                else self._grounding_verifier_doc
            ),
            payload={
                "question": verification_question,
                # Tool execution is over at this stage. Operational fields such
                # as allowed_tools/required_evidence made smaller models try to
                # plan another tool call instead of judging the supplied facts.
                "contract": contract_payload,
                "verification_stage": verification_stage,
                # Each claim is judged against the facts it actually cites.
                # Unreferenced rows add context-window pressure and made small
                # models silently borrow participants from neighbouring hits.
                "observed_facts": verifier_fact_payloads,
                # The verifier classifies current claim IDs only. Passing the
                # model's free-text blocked_claims beside them caused Gemma to
                # copy whole blocked sentences into rejected_claim_ids.
                "answer_envelope": {
                    "claims": verifier_claims,
                },
                "claim_fact_usage_required": [
                    {
                        "claim_id": claim_id,
                        "fact_ids": fact_ids,
                    }
                    for claim_id, fact_ids in multi_fact_claims.items()
                ],
                "retrieval_candidate_fact_ids": retrieval_projected_ids,
                "retrieval_candidate_assessments": (
                    []
                    if confirmation_pressure
                    else projected_retrieval_assessments
                ),
            },
            schema=schema,
            # GEPINNT wie die Synthese und die acht uebrigen
            # Struktur-Schritte. Ein ungepinntes Verdikt macht jede
            # Wiederholung zur neuen Ziehung: im Mitschnitt vom
            # 2026-08-28 lieferten sieben Aufrufe auf derselben Lage
            # vier byte-identische und ein abweichendes Urteil.
            temperature=0.0,
        )
        verdict = self._grounding_verdict_cls.from_raw(raw)
        partition_status_conflicts = _dedupe_ordered_strs(
            list(
                getattr(
                    verdict,
                    "_partition_status_conflicts",
                    [],
                )
                or []
            )
        )
        resolved_claim_fact_usage: List[dict[str, Any]] = []
        unknown_claim_fact_usage_ids: set[str] = set()
        for usage in list(
            getattr(verdict, "claim_fact_usage", []) or []
        ):
            if not isinstance(usage, dict):
                continue
            resolved_claim_id, unknown_claim_id = _resolve_projected_id(
                str(usage.get("claim_id", "") or ""),
                projected_to_internal,
            )
            if unknown_claim_id:
                unknown_claim_fact_usage_ids.add(unknown_claim_id)
            resolved_lists: dict[str, List[str]] = {}
            for field_name in ("used_fact_ids", "unused_fact_ids"):
                resolutions = [
                    _resolve_projected_id(
                        str(fact_id or ""),
                        projected_to_internal_facts,
                    )
                    for fact_id in list(usage.get(field_name, []) or [])
                    if str(fact_id or "").strip()
                ]
                unknown_claim_fact_usage_ids.update(
                    unknown
                    for _resolved, unknown in resolutions
                    if unknown
                )
                resolved_lists[field_name] = _dedupe_ordered_strs(
                    [
                        resolved
                        for resolved, _unknown in resolutions
                        if resolved
                    ]
                )
            if resolved_claim_id:
                resolved_claim_fact_usage.append(
                    {
                        "claim_id": resolved_claim_id,
                        **resolved_lists,
                    }
                )
        verdict.claim_fact_usage = resolved_claim_fact_usage
        verdict._unknown_claim_fact_usage_ids = (
            unknown_claim_fact_usage_ids
        )
        accounted_retrieval_resolutions = [
            _resolve_projected_id(
                fact_id,
                projected_to_internal_facts,
            )
            for fact_id in list(
                getattr(
                    verdict,
                    "accounted_retrieval_fact_ids",
                    [],
                )
                or []
            )
        ]
        unaccounted_retrieval_resolutions = [
            _resolve_projected_id(
                fact_id,
                projected_to_internal_facts,
            )
            for fact_id in list(
                getattr(
                    verdict,
                    "unaccounted_retrieval_fact_ids",
                    [],
                )
                or []
            )
        ]
        unknown_retrieval_fact_ids = {
            unknown
            for _resolved, unknown in (
                accounted_retrieval_resolutions
                + unaccounted_retrieval_resolutions
            )
            if unknown
        }
        verdict.accounted_retrieval_fact_ids = _dedupe_ordered_strs(
            [
                resolved
                for resolved, _unknown in accounted_retrieval_resolutions
                if resolved
            ]
        )
        verdict.unaccounted_retrieval_fact_ids = _dedupe_ordered_strs(
            [
                resolved
                for resolved, _unknown in unaccounted_retrieval_resolutions
                if resolved
            ]
        )
        raw_verdict_reasons = [
            str(reason)
            for reason in list(verdict.reasons or [])
            if str(reason or "").strip()
        ]
        explicit_reason_acceptances: set[str] = set()
        for reason in raw_verdict_reasons:
            mentioned_projected_ids = [
                projected_id
                for projected_id in projected_to_internal
                if re.search(
                    rf"(?<![A-Za-z0-9]){re.escape(projected_id)}"
                    rf"(?![A-Za-z0-9])",
                    reason,
                )
            ]
            # A single-claim reason that literally says "accepted" is an
            # explicit semantic decision even if the model forgot to copy the
            # same ID into accepted_claim_ids. Multi-claim prose stays
            # ambiguous and is handled by the constrained partitioner.
            if (
                len(mentioned_projected_ids) == 1
                and _EXPLICIT_CLAIM_ACCEPTANCE_PATTERN.search(reason)
            ):
                explicit_reason_acceptances.add(
                    projected_to_internal[mentioned_projected_ids[0]]
                )
        semantic_reasons_by_internal: dict[str, List[str]] = {}
        for projected_id, internal_id in projected_to_internal.items():
            matching = [
                _replace_internal_ids(reason, projected_to_internal)
                for reason in raw_verdict_reasons
                if re.search(
                    rf"(?<![A-Za-z0-9]){re.escape(projected_id)}"
                    rf"(?![A-Za-z0-9])",
                    reason,
                )
            ]
            if matching:
                semantic_reasons_by_internal[internal_id] = (
                    _dedupe_ordered_strs(matching)
                )
        verdict.reasons = _dedupe_ordered_strs(
            [
                _replace_internal_ids(reason, projected_to_internal)
                for reason in raw_verdict_reasons
            ]
        )
        raw_accepted_ids = list(verdict.accepted_claim_ids or [])
        raw_rejected_ids = list(verdict.rejected_claim_ids or [])
        accepted_resolutions = [
            _resolve_projected_id(claim_id, projected_to_internal)
            for claim_id in raw_accepted_ids
        ]
        rejected_resolutions = [
            _resolve_projected_id(claim_id, projected_to_internal)
            for claim_id in raw_rejected_ids
        ]
        unknown_projected_ids = {
            unknown
            for _resolved, unknown in (
                accepted_resolutions + rejected_resolutions
            )
            if unknown
        }
        verdict.accepted_claim_ids = _dedupe_ordered_strs(
            [
                resolved
                for resolved, _unknown in accepted_resolutions
                if resolved
            ]
        )
        verdict.rejected_claim_ids = _dedupe_ordered_strs(
            [
                resolved
                for resolved, _unknown in rejected_resolutions
                if resolved
            ]
        )
        llm_rejected_ids = set(verdict.rejected_claim_ids or [])
        invalid_verdict = str(
            getattr(verdict, "_invalid_verdict_value", "") or ""
        ).strip()
        if invalid_verdict:
            verdict.verdict = (
                "retry" if observed_facts else "conservative_only"
            )
            verdict.needs_retry = bool(observed_facts)
            reason = (
                "Der Grounding-Verifier lieferte einen ungültigen "
                f"Verdict-Wert ({invalid_verdict!r}); die Klassifikation muss "
                "schema-konform wiederholt werden."
            )
            if reason not in verdict.reasons:
                verdict.reasons.append(reason)
        envelope_claim_ids = {
            str(getattr(claim, "id", "") or "")
            for claim in list(getattr(envelope, "claims", []) or [])
            if str(getattr(claim, "id", "") or "")
        }
        raw_classified_claim_ids = set(verdict.accepted_claim_ids or []).union(
            verdict.rejected_claim_ids or []
        )
        protocol_anomalies: List[str] = []
        if envelope_claim_ids and raw_classified_claim_ids != envelope_claim_ids:
            protocol_anomalies.append("incomplete_claim_partition")
        if set(verdict.accepted_claim_ids or []).intersection(
            verdict.rejected_claim_ids or []
        ):
            protocol_anomalies.append("overlapping_claim_partition")
        if raw_verdict_reasons and all(
            not _classification_reason_is_substantive(reason)
            for reason in raw_verdict_reasons
        ):
            protocol_anomalies.append("meta_refusal_reason")
        if partition_status_conflicts:
            protocol_anomalies.append("contradictory_partition_status")
        if protocol_anomalies:
            verdict._verifier_protocol_anomalies = protocol_anomalies
        if partition_status_conflicts:
            verdict.verdict = (
                "retry" if observed_facts else "conservative_only"
            )
            verdict.needs_retry = bool(observed_facts)
            reason = (
                "Der Grounding-Verifier lieferte widersprüchliche "
                "Container- und Objektklassifikationen; die Partition muss "
                "schema-konform wiederholt werden."
            )
            if reason not in verdict.reasons:
                verdict.reasons.append(reason)
        unknown_claim_ids = set(unknown_projected_ids)
        if unknown_claim_ids:
            reason = (
                "Der Grounding-Verifier nannte unbekannte Projektions-IDs; sie "
                "wurden ohne Wirkung ignoriert: "
                + ", ".join(sorted(unknown_claim_ids)[:3])
                + "."
            )
            if reason not in verdict.reasons:
                verdict.reasons.append(reason)
            # A provider sometimes turns its own invented ID into `retry`
            # even though every real envelope claim was accepted. Once the
            # foreign ID is removed, restore the complete real partition;
            # runtime validation below can still request a genuine retry.
            if (
                set(verdict.accepted_claim_ids or []) == envelope_claim_ids
                and not verdict.rejected_claim_ids
                and not invalid_verdict
                and not partition_status_conflicts
            ):
                verdict.verdict = "pass"
                verdict.needs_retry = False
        verdict._omitted_claim_ids = set()
        llm_accepted_ids = set(verdict.accepted_claim_ids or [])
        accepted_by_runtime, rejected_by_runtime, rejection_reasons = self._validate_answer_envelope(
            envelope,
            observed_facts,
            forbidden_claims=contract.forbidden_claims,
        )
        accepted_by_runtime = list(accepted_by_runtime)
        rejected_by_runtime = list(rejected_by_runtime)
        rejection_reasons = {
            str(claim_id): list(reasons or [])
            for claim_id, reasons in (rejection_reasons or {}).items()
        }
        # Severity-Split: beratende Befunde blockieren nicht mehr, sie werden
        # als Annotationen (claim_id -> Befunde) an den Verdict durchgereicht,
        # damit die UI sie neben der Antwort anzeigen kann.
        verdict.advisories = {
            str(claim_id): list(notes or [])
            for claim_id, notes in (
                getattr(envelope, "advisories", {}) or {}
            ).items()
        }
        retrieval_hypothesis = self._retrieval_audit_diagnostics
        scope_violation_ids = _related_evidence_scope_violation_claim_ids(
            envelope,
            list(retrieval_candidate_assessments or []),
            target_topic=str(
                retrieval_hypothesis.get("target_topic", "") or ""
            ),
            asserted_property=str(
                retrieval_hypothesis.get("asserted_property", "") or ""
            ),
        )
        for claim_id in scope_violation_ids:
            accepted_by_runtime = [
                accepted_id
                for accepted_id in accepted_by_runtime
                if accepted_id != claim_id
            ]
            if claim_id not in rejected_by_runtime:
                rejected_by_runtime.append(claim_id)
            rejection_reasons.setdefault(claim_id, []).append(
                "Die referenzierten Passagen bewerten nur verwandte Objekte; "
                "der Claim schreibt dieselbe Eigenschaft trotzdem dem "
                "abstrakten Zielthema selbst zu. Benenne stattdessen die "
                "sichtbaren Gruppen, Politiken, Praktiken oder Folgen."
            )
        ambiguous_subset_scope_ids = (
            _ambiguous_retrieval_subset_scope_claim_ids(
                envelope,
                list(retrieval_candidate_assessments or []),
            )
        )
        for claim_id in ambiguous_subset_scope_ids:
            accepted_by_runtime = [
                accepted_id
                for accepted_id in accepted_by_runtime
                if accepted_id != claim_id
            ]
            if claim_id not in rejected_by_runtime:
                rejected_by_runtime.append(claim_id)
            rejection_reasons.setdefault(claim_id, []).append(
                "Der Claim bezeichnet eine intern zitierte Teilmenge nur als "
                "'die vorliegenden Passagen'. Im gerenderten Gesamtbefund "
                "wäre dadurch unklar, welche Ausschnitte die Aussage trägt. "
                "Nenne stattdessen die konkrete lokale Proposition."
            )
        scope_violation_ids = _dedupe_ordered_strs(
            list(scope_violation_ids) + ambiguous_subset_scope_ids
        )
        polarity_violation_ids = _retrieval_polarity_violation_claim_ids(
            envelope,
            list(retrieval_candidate_assessments or []),
            asserted_property=str(
                retrieval_hypothesis.get("asserted_property", "") or ""
            ),
        )
        for claim_id in polarity_violation_ids:
            accepted_by_runtime = [
                accepted_id
                for accepted_id in accepted_by_runtime
                if accepted_id != claim_id
            ]
            if claim_id not in rejected_by_runtime:
                rejected_by_runtime.append(claim_id)
            rejection_reasons.setdefault(claim_id, []).append(
                "Der Claim weist einer Retrieval-Passage eine positive oder "
                "negative Lesart zu, die der unabhängige Kandidatenaudit "
                "nicht beobachtet hat. Eine unklare Passage darf nicht allein "
                "aus der Abwesenheit der geprüften Eigenschaft zur "
                "Gegenposition umgedeutet werden."
            )
        for claim in list(getattr(envelope, "claims", []) or []):
            invalid_citations = list(
                getattr(
                    claim,
                    "_invalid_projected_fact_citations",
                    [],
                )
                or []
            )
            if not invalid_citations:
                continue
            claim_id = str(getattr(claim, "id", "") or "").strip()
            if not claim_id:
                continue
            accepted_by_runtime = [
                accepted_id
                for accepted_id in accepted_by_runtime
                if accepted_id != claim_id
            ]
            if claim_id not in rejected_by_runtime:
                rejected_by_runtime.append(claim_id)
            rejection_reasons.setdefault(claim_id, []).append(
                "Gemischte, unbekannte oder unausgewogene interne "
                "Fact-Zitate dürfen nicht in der sichtbaren Antwort stehen."
            )
        blank_slot_misattribution_ids = {
            str(getattr(claim, "id", "") or "")
            for claim in list(getattr(envelope, "claims", []) or [])
            if not str(
                getattr(claim, "response_requirement_id", "") or ""
            ).strip()
            and str(getattr(claim, "id", "") or "") in accepted_by_runtime
            and str(getattr(claim, "id", "") or "") in llm_rejected_ids
            and _rejection_only_misattributed_a_blank_slot(
                semantic_reasons_by_internal.get(
                    str(getattr(claim, "id", "") or ""),
                    [],
                )
            )
        }
        if blank_slot_misattribution_ids:
            verdict.rejected_claim_ids = [
                claim_id
                for claim_id in list(verdict.rejected_claim_ids or [])
                if claim_id not in blank_slot_misattribution_ids
            ]
            verdict.accepted_claim_ids = _dedupe_ordered_strs(
                list(verdict.accepted_claim_ids or [])
                + [
                    claim_id
                    for claim_id in accepted_by_runtime
                    if claim_id in blank_slot_misattribution_ids
                ]
            )
            llm_rejected_ids.difference_update(
                blank_slot_misattribution_ids
            )
            llm_accepted_ids.update(blank_slot_misattribution_ids)
            for claim_id in blank_slot_misattribution_ids:
                semantic_reasons_by_internal.pop(claim_id, None)
            envelope._blank_slot_misattribution_overrides = sorted(
                blank_slot_misattribution_ids
            )
            if (
                not verdict.rejected_claim_ids
                and not invalid_verdict
                and not partition_status_conflicts
                and not unknown_claim_ids
            ):
                verdict.verdict = "pass"
                verdict.needs_retry = False
        bounded_keyness_overrides = set(
            _runtime_authoritative_bounded_keyness_claim_ids(
                contract,
                envelope,
                observed_facts,
                set(accepted_by_runtime),
                interpretation_is_substantive=(
                    self._keyness_interpretation_complete
                ),
            )
        )
        if bounded_keyness_overrides:
            verdict.rejected_claim_ids = [
                claim_id
                for claim_id in list(verdict.rejected_claim_ids or [])
                if claim_id not in bounded_keyness_overrides
            ]
            verdict.accepted_claim_ids = _dedupe_ordered_strs(
                list(verdict.accepted_claim_ids or [])
                + [
                    claim_id
                    for claim_id in accepted_by_runtime
                    if claim_id in bounded_keyness_overrides
                ]
            )
            llm_rejected_ids.difference_update(bounded_keyness_overrides)
            llm_accepted_ids.update(bounded_keyness_overrides)
            envelope._bounded_keyness_runtime_overrides = sorted(
                bounded_keyness_overrides
            )
        epistemic_limitation_overrides = set(
            _runtime_authoritative_epistemic_limitation_claim_ids(
                contract,
                envelope,
                observed_facts,
                set(accepted_by_runtime),
            )
        )
        # As with bounded KWIC readings, only reverse an explicit semantic
        # rejection. An omitted claim has not been meaningfully checked.
        epistemic_limitation_overrides.intersection_update(
            llm_rejected_ids
        )
        if epistemic_limitation_overrides:
            verdict.rejected_claim_ids = [
                claim_id
                for claim_id in list(verdict.rejected_claim_ids or [])
                if claim_id not in epistemic_limitation_overrides
            ]
            verdict.accepted_claim_ids = _dedupe_ordered_strs(
                list(verdict.accepted_claim_ids or [])
                + [
                    claim_id
                    for claim_id in accepted_by_runtime
                    if claim_id in epistemic_limitation_overrides
                ]
            )
            llm_rejected_ids.difference_update(
                epistemic_limitation_overrides
            )
            llm_accepted_ids.update(epistemic_limitation_overrides)
            envelope._epistemic_limitation_runtime_overrides = sorted(
                epistemic_limitation_overrides
            )
        # Die Durchsetzung der Absagen-Pruefung (der Kontrast,
        # befunde/der_kontrast_2026-09-21): eine Direkt-Absage, deren
        # eigene fact_ids positiven Inhalt tragen, ist durch die eigene
        # Evidenz widerlegt. Der Prompt-Satz allein (ABSENZ-REGEL,
        # 5f63db4bf8) wurde in fuenf Urteilslaufen ueberlebt — dieselbe
        # Umkehr-Architektur wie die Runtime-Authoritative-Overrides.
        absage_widerlegt_ids = set(
            _widerlegte_absagen(envelope, observed_facts)
        )
        if absage_widerlegt_ids:
            verdict.accepted_claim_ids = [
                claim_id
                for claim_id in list(verdict.accepted_claim_ids or [])
                if claim_id not in absage_widerlegt_ids
            ]
            verdict.rejected_claim_ids = _dedupe_ordered_strs(
                list(verdict.rejected_claim_ids or [])
                + sorted(absage_widerlegt_ids)
            )
            llm_accepted_ids.difference_update(absage_widerlegt_ids)
            envelope._absage_widerlegt_overrides = sorted(
                absage_widerlegt_ids
            )
        assessed_retrieval_overrides = set(
            _runtime_authoritative_assessed_retrieval_claim_ids(
                envelope,
                set(accepted_by_runtime),
                list(retrieval_candidate_assessments or []),
            )
        )
        # The candidate audit and deterministic validator jointly establish
        # these narrow claims. Only reverse an explicit verifier rejection;
        # silence remains semantically unverified.
        assessed_retrieval_overrides.intersection_update(llm_rejected_ids)
        if assessed_retrieval_overrides:
            verdict.rejected_claim_ids = [
                claim_id
                for claim_id in list(verdict.rejected_claim_ids or [])
                if claim_id not in assessed_retrieval_overrides
            ]
            verdict.accepted_claim_ids = _dedupe_ordered_strs(
                list(verdict.accepted_claim_ids or [])
                + [
                    claim_id
                    for claim_id in accepted_by_runtime
                    if claim_id in assessed_retrieval_overrides
                ]
            )
            llm_rejected_ids.difference_update(
                assessed_retrieval_overrides
            )
            llm_accepted_ids.update(assessed_retrieval_overrides)
            envelope._assessed_retrieval_runtime_overrides = sorted(
                assessed_retrieval_overrides
            )
        bounded_ngram_overrides = set(
            _runtime_authoritative_bounded_ngram_claim_ids(
                contract,
                envelope,
                observed_facts,
                set(accepted_by_runtime),
                interpretation_is_substantive=(
                    self._ngram_interpretation_complete
                ),
            )
        )
        if bounded_ngram_overrides:
            verdict.rejected_claim_ids = [
                claim_id
                for claim_id in list(verdict.rejected_claim_ids or [])
                if claim_id not in bounded_ngram_overrides
            ]
            verdict.accepted_claim_ids = _dedupe_ordered_strs(
                list(verdict.accepted_claim_ids or [])
                + [
                    claim_id
                    for claim_id in accepted_by_runtime
                    if claim_id in bounded_ngram_overrides
                ]
            )
            llm_rejected_ids.difference_update(bounded_ngram_overrides)
            llm_accepted_ids.update(bounded_ngram_overrides)
            envelope._bounded_ngram_runtime_overrides = sorted(
                bounded_ngram_overrides
            )
        bounded_kwic_interpretation_overrides = set(
            _runtime_authoritative_bounded_kwic_claim_ids(
                contract,
                envelope,
                observed_facts,
                set(accepted_by_runtime),
                reading_is_substantive=self._kwic_reading_complete,
                question_text=self._question_text,
            )
        )
        # An omitted claim is semantically unverified, not underclaimed. Only
        # an explicit verifier rejection can be reconsidered by this narrow
        # anti-underclaiming override; literal attestations remain governed by
        # the deterministic observation path below.
        bounded_kwic_interpretation_overrides.intersection_update(
            llm_rejected_ids
        )
        bounded_kwic_interpretation_overrides = {
            claim_id
            for claim_id in bounded_kwic_interpretation_overrides
            if _kwic_semantic_rejection_allows_runtime_override(
                semantic_reasons_by_internal.get(claim_id, [])
            )
        }
        bounded_kwic_overrides = set(
            _runtime_authoritative_direct_kwic_observation_ids(
                contract,
                envelope,
                observed_facts,
                set(accepted_by_runtime),
            )
        )
        bounded_kwic_overrides.update(
            bounded_kwic_interpretation_overrides
        )
        if bounded_kwic_overrides:
            verdict.rejected_claim_ids = [
                claim_id
                for claim_id in list(verdict.rejected_claim_ids or [])
                if claim_id not in bounded_kwic_overrides
            ]
            verdict.accepted_claim_ids = _dedupe_ordered_strs(
                list(verdict.accepted_claim_ids or [])
                + [
                    claim_id
                    for claim_id in accepted_by_runtime
                    if claim_id in bounded_kwic_overrides
                ]
            )
            llm_rejected_ids.difference_update(bounded_kwic_overrides)
            llm_accepted_ids.update(bounded_kwic_overrides)
            envelope._bounded_kwic_runtime_overrides = sorted(
                bounded_kwic_overrides
            )
        relation_runtime_reconsideration_ids = {
            claim_id
            for claim_id in rejected_by_runtime
            if claim_id in llm_accepted_ids
            and _runtime_kwic_relation_rejection_is_reconsiderable(
                rejection_reasons.get(claim_id, [])
            )
        }
        related_scope_relation_reconsideration_ids = set(
            _related_scope_relation_reconsideration_ids(
                contract,
                envelope,
                # A second semantic relation pass may revisit only the narrow
                # bearer-scope heuristic. It must never erase an independent
                # polarity contradiction found in the same claim.
                set(rejected_by_runtime) - set(polarity_violation_ids),
                list(retrieval_candidate_assessments or []),
                set(scope_violation_ids),
                target_topic=str(
                    retrieval_hypothesis.get("target_topic", "") or ""
                ),
            )
        )
        llm_unclassified_runtime_ids = (
            set(accepted_by_runtime)
            - set(llm_accepted_ids)
            - set(llm_rejected_ids)
        )
        relation_semantic_reconsideration_ids = set(
            _local_relation_semantic_reconsideration_ids(
                contract,
                envelope,
                set(accepted_by_runtime),
                set(llm_rejected_ids).union(
                    llm_unclassified_runtime_ids
                ),
                list(retrieval_candidate_assessments or []),
                set(scope_violation_ids),
            )
        )
        preapproved_relation_ids = {
            str(getattr(claim, "id", "") or "")
            for claim in list(getattr(envelope, "claims", []) or [])
            if _claim_signature(claim)
            in set(preapproved_semantic_signatures or set())
        }
        relation_candidate_ids = (
            set(verdict.accepted_claim_ids or [])
            .intersection(
                set(accepted_by_runtime).union(
                    relation_runtime_reconsideration_ids
                )
            )
            .union(relation_semantic_reconsideration_ids)
            .union(related_scope_relation_reconsideration_ids)
            - preapproved_relation_ids
        )
        relation_protocol_required_ids = (
            relation_runtime_reconsideration_ids
            | relation_semantic_reconsideration_ids
            | related_scope_relation_reconsideration_ids
        )
        if str(getattr(contract, "analysis_family", "") or "") == "kwic_context":
            relation_protocol_required_ids.update(relation_candidate_ids)
        (
            relation_accepted_ids,
            relation_rejected_ids,
            relation_reasons,
        ) = await self._adjudicate_kwic_relations(
            contract,
            verifier_claims,
            verifier_fact_payloads,
            projected_to_internal,
            accepted_internal_ids=relation_candidate_ids,
            protocol_required_internal_ids=(
                relation_protocol_required_ids - preapproved_relation_ids
            ),
            retrieval_candidate_assessments=(
                projected_retrieval_assessments
            ),
        )
        relation_audited_ids = relation_accepted_ids | relation_rejected_ids
        if relation_audited_ids:
            envelope._kwic_relation_audited_ids = set(
                getattr(envelope, "_kwic_relation_audited_ids", set()) or set()
            ).union(relation_audited_ids)
        relation_runtime_overrides = (
            relation_accepted_ids
            & relation_runtime_reconsideration_ids
        )
        if relation_runtime_overrides:
            rejected_by_runtime = [
                claim_id
                for claim_id in rejected_by_runtime
                if claim_id not in relation_runtime_overrides
            ]
            accepted_by_runtime = _dedupe_ordered_strs(
                list(accepted_by_runtime)
                + [
                    str(getattr(claim, "id", "") or "")
                    for claim in list(getattr(envelope, "claims", []) or [])
                    if str(getattr(claim, "id", "") or "")
                    in relation_runtime_overrides
                ]
            )
            for claim_id in relation_runtime_overrides:
                rejection_reasons.pop(claim_id, None)
            verdict.rejected_claim_ids = [
                claim_id
                for claim_id in list(verdict.rejected_claim_ids or [])
                if claim_id not in relation_runtime_overrides
            ]
            verdict.accepted_claim_ids = _dedupe_ordered_strs(
                list(verdict.accepted_claim_ids or [])
                + [
                    claim_id
                    for claim_id in accepted_by_runtime
                    if claim_id in relation_runtime_overrides
                ]
            )
            envelope._kwic_relation_runtime_overrides = sorted(
                relation_runtime_overrides
            )
        relation_semantic_overrides = (
            relation_accepted_ids
            & relation_semantic_reconsideration_ids
        )
        if relation_semantic_overrides:
            verdict.rejected_claim_ids = [
                claim_id
                for claim_id in list(verdict.rejected_claim_ids or [])
                if claim_id not in relation_semantic_overrides
            ]
            verdict.accepted_claim_ids = _dedupe_ordered_strs(
                list(verdict.accepted_claim_ids or [])
                + [
                    claim_id
                    for claim_id in accepted_by_runtime
                    if claim_id in relation_semantic_overrides
                ]
            )
            llm_rejected_ids.difference_update(
                relation_semantic_overrides
            )
            llm_accepted_ids.update(relation_semantic_overrides)
            for claim_id in relation_semantic_overrides:
                semantic_reasons_by_internal.pop(claim_id, None)
            envelope._local_relation_semantic_overrides = sorted(
                relation_semantic_overrides
            )
        related_scope_relation_overrides = (
            relation_accepted_ids
            & related_scope_relation_reconsideration_ids
        )
        if related_scope_relation_overrides:
            rejected_by_runtime = [
                claim_id
                for claim_id in rejected_by_runtime
                if claim_id not in related_scope_relation_overrides
            ]
            accepted_by_runtime = _dedupe_ordered_strs(
                list(accepted_by_runtime)
                + [
                    str(getattr(claim, "id", "") or "")
                    for claim in list(getattr(envelope, "claims", []) or [])
                    if str(getattr(claim, "id", "") or "")
                    in related_scope_relation_overrides
                ]
            )
            verdict.rejected_claim_ids = [
                claim_id
                for claim_id in list(verdict.rejected_claim_ids or [])
                if claim_id not in related_scope_relation_overrides
            ]
            verdict.accepted_claim_ids = _dedupe_ordered_strs(
                list(verdict.accepted_claim_ids or [])
                + [
                    claim_id
                    for claim_id in accepted_by_runtime
                    if claim_id in related_scope_relation_overrides
                ]
            )
            llm_rejected_ids.difference_update(
                related_scope_relation_overrides
            )
            llm_accepted_ids.update(related_scope_relation_overrides)
            for claim_id in related_scope_relation_overrides:
                rejection_reasons.pop(claim_id, None)
                semantic_reasons_by_internal.pop(claim_id, None)
            envelope._related_scope_relation_overrides = sorted(
                related_scope_relation_overrides
            )
        discarded_optional_mixed_claim_ids: set[str] = set()
        if relation_rejected_ids and retrieval_candidate_assessments:
            relation_by_fact_id = {
                str(assessment.get("fact_id", "") or ""): str(
                    assessment.get(
                        "relation_to_requested_conclusion",
                        "",
                    )
                    or ""
                )
                for assessment in retrieval_candidate_assessments
                if str(assessment.get("fact_id", "") or "")
            }
            claims_by_id = {
                str(getattr(claim, "id", "") or ""): claim
                for claim in list(getattr(envelope, "claims", []) or [])
                if str(getattr(claim, "id", "") or "")
            }
            remaining_accepted_ids = (
                set(verdict.accepted_claim_ids or [])
                .union(relation_accepted_ids)
                .union(preapproved_relation_ids)
                - relation_rejected_ids
            )
            represented_relations = {
                relation_by_fact_id[fact_id]
                for claim_id in remaining_accepted_ids
                for fact_id in list(
                    getattr(claims_by_id.get(claim_id), "fact_ids", []) or []
                )
                if fact_id in relation_by_fact_id
            }
            clear_balance_is_represented = bool(
                represented_relations.intersection(
                    {"supports", "related_support"}
                )
                and "counterevidence" in represented_relations
            )
            if clear_balance_is_represented:
                for claim_id in relation_rejected_ids - set(
                    rejected_by_runtime
                ):
                    claim = claims_by_id.get(claim_id)
                    cited_fact_ids = {
                        str(fact_id)
                        for fact_id in list(
                            getattr(claim, "fact_ids", []) or []
                        )
                        if str(fact_id)
                    }
                    if (
                        str(getattr(claim, "claim_kind", "") or "")
                        == "interpretation"
                        and cited_fact_ids
                        and cited_fact_ids.issubset(relation_by_fact_id)
                        and {
                            relation_by_fact_id[fact_id]
                            for fact_id in cited_fact_ids
                        }
                        == {"mixed_or_unclear"}
                    ):
                        discarded_optional_mixed_claim_ids.add(claim_id)
            if discarded_optional_mixed_claim_ids:
                relation_rejected_ids.difference_update(
                    discarded_optional_mixed_claim_ids
                )
                accepted_by_runtime = [
                    claim_id
                    for claim_id in accepted_by_runtime
                    if claim_id not in discarded_optional_mixed_claim_ids
                ]
                verdict.accepted_claim_ids = [
                    claim_id
                    for claim_id in list(verdict.accepted_claim_ids or [])
                    if claim_id not in discarded_optional_mixed_claim_ids
                ]
                verdict.rejected_claim_ids = [
                    claim_id
                    for claim_id in list(verdict.rejected_claim_ids or [])
                    if claim_id not in discarded_optional_mixed_claim_ids
                ]
                llm_accepted_ids.difference_update(
                    discarded_optional_mixed_claim_ids
                )
                llm_rejected_ids.difference_update(
                    discarded_optional_mixed_claim_ids
                )
                envelope._discarded_optional_mixed_claim_ids = sorted(
                    discarded_optional_mixed_claim_ids
                )
        if relation_rejected_ids:
            verdict.accepted_claim_ids = [
                claim_id
                for claim_id in list(verdict.accepted_claim_ids or [])
                if claim_id not in relation_rejected_ids
            ]
            verdict.rejected_claim_ids = _dedupe_ordered_strs(
                list(verdict.rejected_claim_ids or [])
                + [
                    claim_id
                    for claim_id in accepted_by_runtime
                    if claim_id in relation_rejected_ids
                ]
            )
            llm_accepted_ids.difference_update(relation_rejected_ids)
            llm_rejected_ids.update(relation_rejected_ids)
            verdict.verdict = "retry" if observed_facts else "conservative_only"
            verdict.needs_retry = bool(observed_facts)
            for claim_id, reasons in relation_reasons.items():
                rejection_reasons.setdefault(claim_id, []).extend(reasons)
                semantic_reasons_by_internal[claim_id] = (
                    _dedupe_ordered_strs(
                        list(
                            semantic_reasons_by_internal.get(claim_id, [])
                        )
                        + list(reasons)
                    )
                )
                for reason in reasons:
                    if reason not in verdict.reasons:
                        verdict.reasons.append(reason)
            envelope._kwic_relation_rejections = sorted(
                relation_rejected_ids
            )
        verdict._claim_reasons = {
            str(claim_id): list(items or [])
            for claim_id, items in (rejection_reasons or {}).items()
        }
        for claim_id in llm_rejected_ids:
            semantic_reasons = semantic_reasons_by_internal.get(claim_id, [])
            if semantic_reasons:
                verdict._claim_reasons[claim_id] = _dedupe_ordered_strs(
                    list(verdict._claim_reasons.get(claim_id, []))
                    + semantic_reasons
                )
        verdict._assertion_repairable_claim_ids = {
            claim_id
            for claim_id in set(rejected_by_runtime).union(llm_rejected_ids)
            if verdict._claim_reasons.get(claim_id)
            and all(
                _is_assertion_repair_reason(reason)
                for reason in verdict._claim_reasons[claim_id]
            )
        }
        deliverable_ok, deliverable_reason = self._envelope_matches_deliverable_kind(
            envelope,
            deliverable_kind=contract.deliverable_kind,
        )
        if not deliverable_ok:
            verdict.verdict = "retry" if observed_facts else "conservative_only"
            verdict.needs_retry = bool(observed_facts)
            if deliverable_reason not in verdict.reasons:
                verdict.reasons.append(deliverable_reason)
        if rejected_by_runtime:
            verdict.verdict = "retry" if observed_facts else "conservative_only"
            verdict.needs_retry = bool(observed_facts)
            verdict.rejected_claim_ids = _dedupe_ordered_strs(
                list(verdict.rejected_claim_ids) + list(rejected_by_runtime)
            )
            verdict.accepted_claim_ids = [
                claim_id
                for claim_id in list(verdict.accepted_claim_ids or [])
                if claim_id not in set(rejected_by_runtime)
            ]
            for claim_id in rejected_by_runtime:
                for reason in rejection_reasons.get(claim_id, []):
                    if reason not in verdict.reasons:
                        verdict.reasons.append(reason)

        preapproved_semantic_signatures = set(
            preapproved_semantic_signatures or set()
        )
        preapproved_runtime_ids = {
            str(getattr(claim, "id", "") or "")
            for claim in list(getattr(envelope, "claims", []) or [])
            if str(getattr(claim, "id", "") or "") in accepted_by_runtime
            and _claim_signature(claim) in preapproved_semantic_signatures
        }
        # The facts do not change during this retry loop. An unchanged claim
        # that already passed runtime and semantic checks therefore must not be
        # lost to a later stochastic reclassification. An explicit replacement
        # by a newly accepted, more precise duplicate remains possible.
        later_rejected_ids = set(verdict.rejected_claim_ids or [])
        global_duplicate_only_reasons = (
            verdict.reasons
            if later_rejected_ids
            and later_rejected_ids.issubset(preapproved_runtime_ids)
            and _rejection_only_relitigates_prior_acceptance(verdict.reasons)
            else []
        )
        restored_preapproved_ids: set[str] = set()
        for claim_id in preapproved_runtime_ids.intersection(
            later_rejected_ids
        ):
            relitigation_reasons = (
                semantic_reasons_by_internal.get(claim_id, [])
                or global_duplicate_only_reasons
            )
            if not _rejection_only_relitigates_prior_acceptance(
                relitigation_reasons
            ):
                continue
            if _redundancy_rejection_names_accepted_successor(
                relitigation_reasons,
                rejected_id=claim_id,
                accepted_ids=set(verdict.accepted_claim_ids or []),
            ):
                continue
            restored_preapproved_ids.add(claim_id)
        if restored_preapproved_ids:
            verdict.rejected_claim_ids = [
                claim_id
                for claim_id in list(verdict.rejected_claim_ids or [])
                if claim_id not in restored_preapproved_ids
            ]
            verdict.accepted_claim_ids = _dedupe_ordered_strs(
                list(verdict.accepted_claim_ids or [])
                + [
                    claim_id
                    for claim_id in accepted_by_runtime
                    if claim_id in restored_preapproved_ids
                ]
            )
            llm_accepted_ids.update(restored_preapproved_ids)
            if (
                not verdict.rejected_claim_ids
                and not rejected_by_runtime
                and deliverable_ok
                and not invalid_verdict
            ):
                verdict.verdict = "pass"
                verdict.needs_retry = False

        reason_recovered_ids = (
            set(accepted_by_runtime)
            & explicit_reason_acceptances
            - set(verdict.rejected_claim_ids or [])
            - set(llm_rejected_ids)
        )
        if reason_recovered_ids:
            verdict.accepted_claim_ids = _dedupe_ordered_strs(
                list(verdict.accepted_claim_ids or [])
                + [
                    claim_id
                    for claim_id in accepted_by_runtime
                    if claim_id in reason_recovered_ids
                ]
            )
            llm_accepted_ids.update(reason_recovered_ids)
            envelope._verifier_reason_acceptance_recoveries = sorted(
                reason_recovered_ids
            )

        # The verifier schema requires an exhaustive partition of all claim
        # ids. Runtime checks prove structural/numeric admissibility, not the
        # meaning of arbitrary prose, so an omitted id is never auto-promoted.
        semantically_unverified_ids = [
            claim_id
            for claim_id in accepted_by_runtime
            if claim_id not in llm_accepted_ids
            and claim_id not in set(verdict.rejected_claim_ids or [])
            and not any(
                str(getattr(claim, "id", "") or "") == claim_id
                and _claim_signature(claim)
                in preapproved_semantic_signatures
                for claim in list(getattr(envelope, "claims", []) or [])
            )
        ]
        if semantically_unverified_ids:
            verdict._omitted_claim_ids = set(
                semantically_unverified_ids
            )
            verdict.rejected_claim_ids = _dedupe_ordered_strs(
                list(verdict.rejected_claim_ids or [])
                + semantically_unverified_ids
            )
            reason = (
                "Jeder Claim braucht eine ausdrückliche semantische "
                "Klassifikation; eine ausgelassene Claim-ID ist kein positives "
                "Grounding-Verdikt."
            )
            if reason not in verdict.reasons:
                verdict.reasons.append(reason)
            if envelope.claims and verdict.verdict in {
                "pass",
                "conservative_only",
            }:
                verdict.verdict = "retry"
            elif verdict.verdict not in {"retry", "conservative_only"}:
                verdict.verdict = "conservative_only"
            verdict.needs_retry = verdict.verdict == "retry"

        # Runtime checks only decide deterministic admissibility. The verifier
        # must explicitly accept meaning; rejection by either layer still wins.
        rejected_ids = _dedupe_ordered_strs(
            list(verdict.rejected_claim_ids or []) + list(rejected_by_runtime)
        )
        rejected_set = set(rejected_ids)
        verdict.rejected_claim_ids = rejected_ids
        candidate_ids = list(accepted_by_runtime)
        verdict.accepted_claim_ids = [
            claim_id
            for claim_id in _dedupe_ordered_strs(candidate_ids)
            if claim_id not in rejected_set
        ]
        fact_usage_ok = True
        validated_used_fact_ids_by_claim: dict[str, List[str]] = {}
        fact_usage_entries_by_claim: dict[str, List[dict[str, Any]]] = {}
        for usage in list(
            getattr(verdict, "claim_fact_usage", []) or []
        ):
            if not isinstance(usage, dict):
                continue
            claim_id = str(usage.get("claim_id", "") or "").strip()
            if claim_id:
                fact_usage_entries_by_claim.setdefault(claim_id, []).append(
                    usage
                )
        fact_usage_issues: List[str] = []
        if set(
            getattr(verdict, "_unknown_claim_fact_usage_ids", set()) or set()
        ):
            fact_usage_issues.append("unbekannte Claim- oder Fact-IDs")
        accepted_id_set = set(verdict.accepted_claim_ids or [])
        for claim in list(getattr(envelope, "claims", []) or []):
            claim_id = str(getattr(claim, "id", "") or "").strip()
            if claim_id not in accepted_id_set:
                continue
            cited_fact_ids = _dedupe_ordered_strs(
                [
                    str(fact_id)
                    for fact_id in list(
                        getattr(claim, "fact_ids", []) or []
                    )
                    if str(fact_id)
                ]
            )
            if len(cited_fact_ids) <= 1:
                validated_used_fact_ids_by_claim[claim_id] = cited_fact_ids
                continue
            usage_entries = fact_usage_entries_by_claim.get(claim_id, [])
            if len(usage_entries) != 1:
                fact_usage_issues.append(
                    f"{claim_id}: fehlende oder doppelte Fact-Nutzungsprüfung"
                )
                continue
            usage = usage_entries[0]
            used = set(usage.get("used_fact_ids", []) or [])
            unused = set(usage.get("unused_fact_ids", []) or [])
            cited = set(cited_fact_ids)
            if used & unused:
                fact_usage_issues.append(
                    f"{claim_id}: Fact zugleich used und unused"
                )
                continue
            if used | unused != cited:
                fact_usage_issues.append(
                    f"{claim_id}: unvollständige Fact-Partition"
                )
                continue
            if not used:
                fact_usage_issues.append(
                    f"{claim_id}: kein substanziell verwendeter Fact"
                )
                continue
            validated_used_fact_ids_by_claim[claim_id] = [
                fact_id for fact_id in cited_fact_ids if fact_id in used
            ]
        envelope._validated_used_fact_ids_by_claim = (
            validated_used_fact_ids_by_claim
        )
        if fact_usage_issues:
            fact_usage_ok = False
            verdict.verdict = "retry" if observed_facts else "conservative_only"
            verdict.needs_retry = bool(observed_facts)
            verdict._fact_usage_protocol_issues = _dedupe_ordered_strs(
                fact_usage_issues
            )
            reason = (
                "Mehrfach referenzierte Facts wurden nicht vollständig als "
                "tatsächlich verwendet oder unbenutzt klassifiziert ("
                + "; ".join(verdict._fact_usage_protocol_issues[:4])
                + ")."
            )
            if reason not in verdict.reasons:
                verdict.reasons.append(reason)
        response_requirements_ok = True
        if response_requirement_ids:
            known_requirement_ids = set(response_requirement_ids)
            accepted_id_set = set(verdict.accepted_claim_ids or [])
            accepted_slot_claims = [
                claim
                for claim in list(getattr(envelope, "claims", []) or [])
                if str(getattr(claim, "id", "") or "").strip()
                in accepted_id_set
            ]
            equivalent_requirement_ids = (
                _assign_equivalent_missing_response_slots(
                    accepted_slot_claims,
                    list(getattr(contract, "response_requirements", []) or []),
                )
            )
            model_fulfilled = set(
                getattr(
                    verdict,
                    "fulfilled_response_requirement_ids",
                    [],
                )
                or []
            )
            model_unfulfilled = set(
                getattr(
                    verdict,
                    "unfulfilled_response_requirement_ids",
                    [],
                )
                or []
            )
            response_protocol_anomalies: List[str] = []
            if model_fulfilled & model_unfulfilled:
                response_protocol_anomalies.append(
                    "overlapping_response_requirement_partition"
                )
            if (model_fulfilled | model_unfulfilled) != known_requirement_ids:
                response_protocol_anomalies.append(
                    "incomplete_response_requirement_partition"
                )
            if (model_fulfilled | model_unfulfilled) - known_requirement_ids:
                response_protocol_anomalies.append(
                    "unknown_response_requirement_ids"
                )

            requirement_by_id = {
                str(getattr(requirement, "id", "") or "").strip(): requirement
                for requirement in list(
                    getattr(contract, "response_requirements", []) or []
                )
                if str(getattr(requirement, "id", "") or "").strip()
            }
            structurally_fulfilled: set[str] = set()
            structural_candidates: dict[str, List[tuple[str, str]]] = {
                requirement_id: [] for requirement_id in known_requirement_ids
            }
            runtime_validated_candidates: dict[
                str, List[tuple[str, str]]
            ] = {
                requirement_id: [] for requirement_id in known_requirement_ids
            }
            used_slot_substance: set[tuple[str, str]] = set()
            for claim in list(getattr(envelope, "claims", []) or []):
                claim_id = str(getattr(claim, "id", "") or "").strip()
                requirement_id = str(
                    getattr(claim, "response_requirement_id", "") or ""
                ).strip()
                requirement = requirement_by_id.get(requirement_id)
                if not (
                    claim_id in accepted_id_set
                    and requirement is not None
                    and str(getattr(claim, "claim_kind", "") or "")
                    == str(getattr(requirement, "claim_kind", "") or "")
                    and not list(
                        getattr(
                            claim,
                            "_response_requirement_assignment_reasons",
                            [],
                        )
                        or []
                    )
                ):
                    continue
                signature = _visible_claim_signature(claim)
                structural_candidates[requirement_id].append(signature)
                if hasattr(
                    claim,
                    "_response_requirement_assignment_reasons",
                ):
                    # validate_answer_envelope has already checked claim kind,
                    # required falsifier/limitation/hypothesis wording and all
                    # grounding vetoes.  A provider may still under-report the
                    # slot in its bookkeeping partition; that must not erase a
                    # deterministically verified answer component.
                    runtime_validated_candidates[requirement_id].append(
                        signature
                    )
            duplicate_slot_assignments = {
                requirement_id
                for requirement_id, candidates in structural_candidates.items()
                if len(candidates) > 1
            }
            if duplicate_slot_assignments:
                response_protocol_anomalies.append(
                    "mehr als ein eigenständiger Claim demselben Slot zugeordnet"
                )
            for requirement_id in response_requirement_ids:
                candidates = structural_candidates.get(requirement_id, [])
                if len(candidates) != 1:
                    continue
                signature = candidates[0]
                if signature in used_slot_substance:
                    continue
                used_slot_substance.add(signature)
                structurally_fulfilled.add(requirement_id)

            runtime_validated_fulfilled = {
                requirement_id
                for requirement_id, candidates in (
                    runtime_validated_candidates.items()
                )
                if len(candidates) == 1
                and requirement_id in structurally_fulfilled
            }

            invalid_fulfilments = model_fulfilled - structurally_fulfilled
            if invalid_fulfilments:
                response_protocol_anomalies.append(
                    "unverified_response_requirements_marked_fulfilled"
                )
            # Provider labels remain an independent signal for unvalidated
            # envelopes. Once the runtime has verified a slot, however, the
            # label is diagnostic rather than a second chance to suppress
            # already grounded content.
            effective_fulfilled = (
                model_fulfilled & structurally_fulfilled
            ).union(
                runtime_validated_fulfilled
            ).union(
                structurally_fulfilled & equivalent_requirement_ids
            )
            effective_unfulfilled = known_requirement_ids - effective_fulfilled
            verdict.fulfilled_response_requirement_ids = [
                requirement_id
                for requirement_id in response_requirement_ids
                if requirement_id in effective_fulfilled
            ]
            verdict.unfulfilled_response_requirement_ids = [
                requirement_id
                for requirement_id in response_requirement_ids
                if requirement_id in effective_unfulfilled
            ]
            for claim in list(getattr(envelope, "claims", []) or []):
                requirement_id = str(
                    getattr(claim, "response_requirement_id", "") or ""
                ).strip()
                if requirement_id and requirement_id not in effective_fulfilled:
                    claim._unfulfilled_response_requirement_id = requirement_id
                    claim.response_requirement_id = ""
            envelope._fulfilled_response_requirement_ids = list(
                verdict.fulfilled_response_requirement_ids
            )
            envelope._unfulfilled_response_requirement_ids = list(
                verdict.unfulfilled_response_requirement_ids
            )
            if response_protocol_anomalies:
                verdict._verifier_protocol_anomalies = _dedupe_ordered_strs(
                    list(
                        getattr(
                            verdict,
                            "_verifier_protocol_anomalies",
                            [],
                        )
                        or []
                    )
                    + response_protocol_anomalies
                )
            if effective_unfulfilled:
                verdict.verdict = "retry" if observed_facts else "conservative_only"
                verdict.needs_retry = bool(observed_facts)
                reason = (
                    "Die verifizierte Antwort lässt ausdrücklich verlangte "
                    "Antwortbestandteile offen: "
                    + ", ".join(
                        requirement_id
                        for requirement_id in response_requirement_ids
                        if requirement_id in effective_unfulfilled
                    )
                    + "."
                )
                if reason not in verdict.reasons:
                    verdict.reasons.append(reason)
            response_requirements_ok = not effective_unfulfilled
        if competing_pair_ready:
            pair_assessment = dict(
                getattr(
                    verdict,
                    "hypothesis_pair_assessment",
                    {},
                )
                or {}
            )
            pair_protocol_valid = bool(
                getattr(
                    verdict,
                    "_hypothesis_pair_protocol_valid",
                    False,
                )
            )
            pair_valid = bool(
                pair_protocol_valid
                and pair_assessment.get("same_operationalization") is True
                and pair_assessment.get("differentiating_predictions") is True
                and pair_assessment.get("pair_valid") is True
            )
            pair_claim_id_set = set(competing_hypothesis_claim_ids)
            accepted_pair_complete = pair_claim_id_set.issubset(
                set(verdict.accepted_claim_ids or [])
            )
            if accepted_pair_complete and not pair_valid:
                verdict.accepted_claim_ids = [
                    claim_id
                    for claim_id in list(verdict.accepted_claim_ids or [])
                    if claim_id not in pair_claim_id_set
                ]
                verdict.rejected_claim_ids = _dedupe_ordered_strs(
                    list(verdict.rejected_claim_ids or [])
                    + competing_hypothesis_claim_ids
                )
                verdict.fulfilled_response_requirement_ids = [
                    requirement_id
                    for requirement_id in list(
                        verdict.fulfilled_response_requirement_ids or []
                    )
                    if requirement_id
                    not in competing_requirement_id_set
                ]
                verdict.unfulfilled_response_requirement_ids = (
                    _dedupe_ordered_strs(
                        list(
                            verdict.unfulfilled_response_requirement_ids
                            or []
                        )
                        + competing_hypothesis_requirement_ids
                    )
                )
                response_requirements_ok = False
                verdict._replace_competing_hypothesis_pair = True
                pair_reason = str(
                    pair_assessment.get("reason", "") or ""
                ).strip()
                repair_reason = (
                    "Die verlangten Hypothesen bilden noch kein echtes "
                    "Konkurrenzpaar zur selben Operationalisierung: Ein "
                    "Ergebnis der späteren Auswertung muss zwischen ihren "
                    "unterschiedlichen Vorhersagen unterscheiden können."
                )
                if pair_reason:
                    repair_reason += " Paarprüfung: " + pair_reason
                claim_reasons = dict(
                    getattr(verdict, "_claim_reasons", {}) or {}
                )
                for claim_id in competing_hypothesis_claim_ids:
                    claim_reasons[claim_id] = _dedupe_ordered_strs(
                        list(claim_reasons.get(claim_id, []) or [])
                        + [repair_reason]
                    )
                verdict._claim_reasons = claim_reasons
                verdict.reasons = _dedupe_ordered_strs(
                    list(verdict.reasons or []) + [repair_reason]
                )
                verdict.verdict = (
                    "retry" if observed_facts else "conservative_only"
                )
                verdict.needs_retry = bool(observed_facts)
        retrieval_ok = True
        verdict._retrieval_attention_fact_ids = []
        confirmation_audit_failed_closed = bool(
            confirmation_pressure
            and self._retrieval_audit_diagnostics.get("status")
            == "failed_closed"
        )
        if retrieval_internal_ids:
            expected_retrieval_ids = set(retrieval_internal_ids)
            assessed_retrieval_ids = {
                str(assessment.get("fact_id", "") or "").strip()
                for assessment in list(
                    retrieval_candidate_assessments or []
                )
                if str(assessment.get("fact_id", "") or "").strip()
            }
            exhaustive_candidate_audit = (
                assessed_retrieval_ids == expected_retrieval_ids
            )
            if confirmation_audit_failed_closed:
                retrieval_claim_ids = {
                    str(getattr(claim, "id", "") or "").strip()
                    for claim in list(getattr(envelope, "claims", []) or [])
                    if any(
                        str(fact_id) in expected_retrieval_ids
                        for fact_id in list(
                            getattr(claim, "fact_ids", []) or []
                        )
                    )
                }
                verdict.rejected_claim_ids = _dedupe_ordered_strs(
                    list(verdict.rejected_claim_ids or [])
                    + list(retrieval_claim_ids)
                )
                verdict.accepted_claim_ids = [
                    claim_id
                    for claim_id in list(verdict.accepted_claim_ids or [])
                    if claim_id not in retrieval_claim_ids
                ]
                accounted_retrieval_ids: set[str] = set()
                unaccounted_retrieval_ids = set(expected_retrieval_ids)
                verdict.accounted_retrieval_fact_ids = []
                verdict.unaccounted_retrieval_fact_ids = list(
                    retrieval_internal_ids
                )
            elif exhaustive_candidate_audit:
                accepted_claim_id_set = set(
                    verdict.accepted_claim_ids or []
                )
                assessment_by_fact_id = {
                    str(assessment.get("fact_id", "") or "").strip(): (
                        assessment
                    )
                    for assessment in list(
                        retrieval_candidate_assessments or []
                    )
                    if str(assessment.get("fact_id", "") or "").strip()
                }
                visible_retrieval_ids = {
                    fact_id
                    for fact_id, assessment in assessment_by_fact_id.items()
                    if (
                        assessment.get("topic_relation")
                        in {"relevant", "marginal"}
                        or assessment.get(
                            "relation_to_requested_conclusion"
                        )
                        in {
                            "supports",
                            "related_support",
                            "counterevidence",
                            "mixed_or_unclear",
                        }
                    )
                }
                cited_retrieval_ids = {
                    str(fact_id)
                    for claim in list(
                        getattr(envelope, "claims", []) or []
                    )
                    if str(getattr(claim, "id", "") or "")
                    in accepted_claim_id_set
                    for fact_id in list(
                        getattr(claim, "fact_ids", []) or []
                    )
                    if str(fact_id) in expected_retrieval_ids
                }
                represented_retrieval_ids = (
                    cited_retrieval_ids & visible_retrieval_ids
                )
                audit_only_retrieval_ids = set(
                    expected_retrieval_ids - visible_retrieval_ids
                )
                representative_omitted_retrieval_ids: set[str] = set()
                if confirmation_pressure:
                    stratum_by_fact_id = {
                        fact_id: stratum
                        for fact_id, assessment in assessment_by_fact_id.items()
                        for stratum in [
                            _retrieval_reporting_stratum(assessment)
                        ]
                        if stratum is not None
                    }
                    represented_strata = {
                        stratum_by_fact_id[fact_id]
                        for fact_id in represented_retrieval_ids
                        if fact_id in stratum_by_fact_id
                    }
                    representative_omitted_retrieval_ids = {
                        fact_id
                        for fact_id, stratum in stratum_by_fact_id.items()
                        if stratum in represented_strata
                        and fact_id not in represented_retrieval_ids
                    }
                    audit_only_retrieval_ids.update(
                        representative_omitted_retrieval_ids
                    )
                    optional_mixed_retrieval_ids: set[str] = set()
                    if _mixed_retrieval_reporting_is_optional(
                        list(assessment_by_fact_id.values())
                    ):
                        optional_mixed_retrieval_ids = {
                            fact_id
                            for fact_id, stratum in stratum_by_fact_id.items()
                            if stratum[0] == "mixed_or_unclear"
                        }
                        audit_only_retrieval_ids.update(
                            optional_mixed_retrieval_ids
                        )
                    reporting_diagnostics = dict(
                        self._retrieval_audit_diagnostics.get(
                            "reporting",
                            {},
                        )
                        or {}
                    )
                    reporting_diagnostics.update(
                        {
                            "strategy": "relation_object_strata",
                            "audited_candidate_count": len(
                                expected_retrieval_ids
                            ),
                            "reportable_candidate_count": len(
                                visible_retrieval_ids
                            ),
                            "represented_stratum_count": len(
                                represented_strata
                            ),
                            "representative_omitted_fact_ids": [
                                fact_id
                                for fact_id in retrieval_internal_ids
                                if fact_id
                                in representative_omitted_retrieval_ids
                            ],
                            "optional_audit_only_fact_ids": [
                                fact_id
                                for fact_id in retrieval_internal_ids
                                if fact_id in optional_mixed_retrieval_ids
                            ],
                        }
                    )
                    self._retrieval_audit_diagnostics[
                        "reporting"
                    ] = reporting_diagnostics
                    verdict._representative_omitted_retrieval_fact_ids = [
                        fact_id
                        for fact_id in retrieval_internal_ids
                        if fact_id in representative_omitted_retrieval_ids
                    ]
                else:
                    # Topicality was independently and exhaustively audited.
                    # A bounded report may therefore curate which admissible
                    # passages it shows; omitted candidates remain accounted
                    # internally and do not force mechanical row-by-row prose.
                    audit_only_retrieval_ids.update(
                        expected_retrieval_ids - represented_retrieval_ids
                    )
                    reporting_diagnostics = dict(
                        self._retrieval_audit_diagnostics.get(
                            "reporting",
                            {},
                        )
                        or {}
                    )
                    reporting_diagnostics.update(
                        {
                            "strategy": "independent_audit_visible_curation",
                            "audited_candidate_count": len(
                                expected_retrieval_ids
                            ),
                            "represented_candidate_count": len(
                                represented_retrieval_ids
                            ),
                            "audit_only_fact_ids": [
                                fact_id
                                for fact_id in retrieval_internal_ids
                                if fact_id in audit_only_retrieval_ids
                            ],
                        }
                    )
                    self._retrieval_audit_diagnostics[
                        "reporting"
                    ] = reporting_diagnostics
                accounted_retrieval_ids = (
                    represented_retrieval_ids
                    | audit_only_retrieval_ids
                )
                unaccounted_retrieval_ids = (
                    visible_retrieval_ids
                    - accounted_retrieval_ids
                )
                verdict.accounted_retrieval_fact_ids = [
                    fact_id
                    for fact_id in retrieval_internal_ids
                    if fact_id in accounted_retrieval_ids
                ]
                verdict.unaccounted_retrieval_fact_ids = [
                    fact_id
                    for fact_id in retrieval_internal_ids
                    if fact_id in unaccounted_retrieval_ids
                ]
            else:
                accounted_retrieval_ids = set(
                    verdict.accounted_retrieval_fact_ids
                )
                unaccounted_retrieval_ids = set(
                    verdict.unaccounted_retrieval_fact_ids
                )
            overlapping_retrieval_ids = (
                accounted_retrieval_ids
                & unaccounted_retrieval_ids
            )
            classified_retrieval_ids = (
                accounted_retrieval_ids
                | unaccounted_retrieval_ids
            )
            missing_retrieval_ids = (
                expected_retrieval_ids - classified_retrieval_ids
            )
            foreign_retrieval_ids = (
                classified_retrieval_ids - expected_retrieval_ids
            )
            retrieval_attention_ids = (
                missing_retrieval_ids
                | unaccounted_retrieval_ids
                | overlapping_retrieval_ids
            )
            repair_attention_ids = set(retrieval_attention_ids)
            if (
                confirmation_pressure
                and exhaustive_candidate_audit
                and unaccounted_retrieval_ids
            ):
                first_unaccounted_by_stratum: dict[
                    tuple[str, str], str
                ] = {}
                for fact_id in retrieval_internal_ids:
                    if fact_id not in unaccounted_retrieval_ids:
                        continue
                    stratum = _retrieval_reporting_stratum(
                        assessment_by_fact_id.get(fact_id, {})
                    )
                    if stratum is not None:
                        first_unaccounted_by_stratum.setdefault(
                            stratum,
                            fact_id,
                        )
                repair_attention_ids = (
                    missing_retrieval_ids
                    | overlapping_retrieval_ids
                    | set(first_unaccounted_by_stratum.values())
                )
            verdict._retrieval_attention_fact_ids = [
                fact_id
                for fact_id in retrieval_internal_ids
                if fact_id in repair_attention_ids
            ]
            if retrieval_attention_ids:
                accepted_claim_id_set = set(
                    verdict.accepted_claim_ids or []
                )
                accepted_interpretations = [
                    claim
                    for claim in list(
                        getattr(envelope, "claims", []) or []
                    )
                    if str(getattr(claim, "id", "") or "")
                    in accepted_claim_id_set
                    and str(
                        getattr(claim, "claim_kind", "") or ""
                    )
                    == "interpretation"
                ]
                retrieval_interpretations = [
                    claim
                    for claim in accepted_interpretations
                    if expected_retrieval_ids.intersection(
                        str(fact_id).strip()
                        for fact_id in list(
                            getattr(claim, "fact_ids", []) or []
                        )
                        if str(fact_id).strip()
                    )
                ]
                preservable_local_interpretations = []
                for claim in retrieval_interpretations:
                    text = str(getattr(claim, "text", "") or "")
                    cited_retrieval_ids = {
                        str(fact_id).strip()
                        for fact_id in list(
                            getattr(claim, "fact_ids", []) or []
                        )
                        if str(fact_id).strip() in expected_retrieval_ids
                    }
                    has_explicit_valence = bool(
                        _RETRIEVAL_NEGATIVE_READING_PATTERN.search(text)
                        or _RETRIEVAL_AFFIRMATIVE_POSITIVE_PATTERN.search(text)
                    )
                    locally_bound = bool(
                        _LOCAL_RETRIEVAL_SCOPE_PATTERN.search(text)
                        or (
                            len(cited_retrieval_ids) == 1
                            and (
                                not has_explicit_valence
                                or _METALINGUISTIC_SOURCE_NOUN_PATTERN.search(
                                    text
                                )
                            )
                        )
                    )
                    if (
                        str(
                            getattr(claim, "assertion_level", "") or ""
                        )
                        in {"qualified", "tentative"}
                        and str(getattr(claim, "id", "") or "")
                        not in set(scope_violation_ids)
                        and locally_bound
                        and not _HYPOTHESIS_QUANTIFIER_PATTERN.search(text)
                        and not _has_unbounded_retrieval_assertion(text)
                    ):
                        preservable_local_interpretations.append(claim)
                preserve_any_local_interpretation = bool(
                    preservable_local_interpretations
                )
                all_interpretations_are_preservable = bool(
                    preserve_any_local_interpretation
                    and len(preservable_local_interpretations)
                    == len(retrieval_interpretations)
                )
                # A prevalence or corpus-level reading must be rebuilt over
                # the full visible candidate set. A verifier-approved claim
                # that explicitly describes only its cited passages is not a
                # tendency claim: retain it and add only the omitted contrast.
                if contract.deliverable_kind in {
                    "analysis_report",
                    "contrast_report",
                    "overview",
                }:
                    if preserve_any_local_interpretation:
                        verdict._preserved_local_retrieval_interpretation_ids = [
                            str(getattr(claim, "id", "") or "")
                            for claim in preservable_local_interpretations
                        ]
                    if not all_interpretations_are_preservable:
                        verdict._replace_incomplete_interpretations = True
                        preservable_ids = {
                            str(getattr(claim, "id", "") or "")
                            for claim in preservable_local_interpretations
                        }
                        verdict._replace_incomplete_retrieval_interpretation_ids = [
                            str(getattr(claim, "id", "") or "")
                            for claim in retrieval_interpretations
                            if str(getattr(claim, "id", "") or "")
                            not in preservable_ids
                        ]
                else:
                    verdict._replace_whole_deliverable = True
            retrieval_partition_issues: List[str] = []
            if unknown_retrieval_fact_ids or foreign_retrieval_ids:
                retrieval_partition_issues.append(
                    "unbekannte IDs"
                )
            if overlapping_retrieval_ids:
                retrieval_partition_issues.append(
                    "doppelt klassifizierte IDs"
                )
            if missing_retrieval_ids:
                retrieval_partition_issues.append(
                    "nicht klassifizierte IDs"
                )
            if retrieval_partition_issues:
                retrieval_ok = False
                verdict.verdict = "retry"
                verdict.needs_retry = True
                reason = (
                    "Die sichtbaren Retrieval-Kandidaten wurden "
                    "nicht vollständig und disjunkt geprüft ("
                    + ", ".join(retrieval_partition_issues)
                    + ")."
                )
                if reason not in verdict.reasons:
                    verdict.reasons.append(reason)
            if unaccounted_retrieval_ids:
                retrieval_ok = False
                verdict.verdict = "retry"
                verdict.needs_retry = True
                reason = (
                    "Die Synthese berücksichtigt noch nicht alle für ihre "
                    "Reichweite relevanten Retrieval-Kandidaten: "
                    + ", ".join(
                        sorted(unaccounted_retrieval_ids)[:8]
                    )
                    + ". Begrenze oder repariere betroffene Claims und "
                    "berücksichtige auch widersprechende, unklare oder "
                    "themenferne Treffer."
                )
                if reason not in verdict.reasons:
                    verdict.reasons.append(reason)
        completion_ok = True
        if self._accepted_claims_complete is not None and observed_facts:
            complete, completion_reason = self._accepted_claims_complete(
                envelope,
                verdict.accepted_claim_ids,
                verdict.rejected_claim_ids,
                observed_facts,
                contract,
            )
            if not complete:
                completion_ok = False
                verdict.verdict = "retry"
                verdict.needs_retry = True
                if completion_reason and completion_reason not in verdict.reasons:
                    verdict.reasons.append(completion_reason)
                replace_whole = contract.deliverable_kind == "lookup_answer"
                if replace_whole:
                    # A factual lookup is one answer, not an additive report.
                    # Retaining mislabeled paraphrases while requesting the
                    # missing observation caused repeated identical counts.
                    verdict._replace_whole_deliverable = True
                elif (
                    str(getattr(contract, "analysis_family", "") or "")
                    == "open_research"
                    and contract.deliverable_kind == "overview"
                    and str(completion_reason or "").startswith(
                        "Die Synthese lässt bereits vorhandene, angeforderte "
                        "Evidenz unberücksichtigt"
                    )
                ):
                    # An additive retry preserves the metadata-only draft that
                    # caused the omission and leaves too little room for the
                    # requested lexical/contextual evidence. Rebuild the one
                    # coherent overview from the complete evidence bundle.
                    verdict._replace_whole_deliverable = True
                elif (
                    str(getattr(contract, "analysis_family", "") or "")
                    == "kwic_context"
                    and contract.deliverable_kind == "analysis_report"
                ):
                    # A KWIC interpretation is one coherent reading of one
                    # expanded passage. Appending each incomplete attempt
                    # accumulated paraphrase variants and could surface stale
                    # semantic errors after retry exhaustion. Keep independent
                    # observations, but replace the incomplete interpretation
                    # set on the next attempt.
                    verdict._replace_incomplete_interpretations = True
                elif (
                    str(getattr(contract, "analysis_family", "") or "")
                    in {"semantic_retrieval", "open_research"}
                    and contract.deliverable_kind
                    in {"analysis_report", "contrast_report", "overview"}
                    and str(completion_reason or "").startswith(
                        "Die angeforderte Mustersynthese braucht"
                    )
                ):
                    # Keep verified observations, but replace a scope-only or
                    # single-row interpretation with the requested synthesis.
                    verdict._replace_incomplete_interpretations = True
                elif (
                    str(getattr(contract, "analysis_family", "") or "")
                    == "word_sketch_profile"
                    and contract.deliverable_kind == "analysis_report"
                    and str(completion_reason or "").startswith(
                        "Das grammatische Profil braucht zusätzlich eine "
                        "knappe Synthese"
                    )
                ):
                    # Each focused turn proposes one relation-level synthesis.
                    # If it is not substantive, replace that provisional slot
                    # rather than accumulating every accepted paraphrase.
                    verdict._replace_incomplete_interpretations = True
                elif (
                    str(getattr(contract, "analysis_family", "") or "")
                    == "word_sketch_profile"
                    and contract.deliverable_kind == "analysis_report"
                    and str(completion_reason or "").startswith(
                        "Wenn das grammatische Profil f oder f2 ausgibt"
                    )
                ):
                    # A malformed metric legend is a provisional repair slot,
                    # not a second observation to retain beside its successor.
                    verdict._replace_incomplete_word_sketch_units = True
                elif (
                    str(getattr(contract, "analysis_family", "") or "")
                    == "word_sketch_profile"
                    and contract.deliverable_kind == "analysis_report"
                    and str(completion_reason or "").startswith(
                        "Das grammatische Profil lässt sichtbare "
                        "Word-Sketch-Evidenz aus."
                    )
                ):
                    # A grammatical profile is a coherent account of one
                    # evidence table. Additive retries can retain one row while
                    # repeatedly omitting the other visible relations.
                    verdict._replace_whole_deliverable = True
        rejected_claim_id_set = set(verdict.rejected_claim_ids or [])
        rejected_claims_are_optional_limitations = bool(
            rejected_claim_id_set
            and all(
                str(getattr(claim, "claim_kind", "") or "")
                == "limitation"
                for claim in list(getattr(envelope, "claims", []) or [])
                if str(getattr(claim, "id", "") or "")
                in rejected_claim_id_set
            )
            and rejected_claim_id_set.issubset(
                {
                    str(getattr(claim, "id", "") or "")
                    for claim in list(
                        getattr(envelope, "claims", []) or []
                    )
                    if str(getattr(claim, "claim_kind", "") or "")
                    == "limitation"
                }
            )
        )
        if (
            confirmation_pressure
            and self._accepted_claims_complete is not None
            and completion_ok
            and retrieval_ok
            and verdict.accepted_claim_ids
            and rejected_claims_are_optional_limitations
        ):
            # The accepted interpretation plus the deterministic semantic
            # scope fact already forms a complete answer. Drop a malformed or
            # redundant model-written caveat instead of triggering additive
            # retries that repeat counts and dilute the analysis.
            verdict.verdict = "conservative_only"
            verdict.needs_retry = False
            verdict._covered_rejected_limitation_ids = sorted(
                rejected_claim_id_set
            )
        if confirmation_audit_failed_closed:
            verdict.verdict = "conservative_only"
            verdict.needs_retry = False
            reason = (
                "Die unabhängige Kandidatenprüfung ist fehlgeschlagen; "
                "Retrieval-Inhalte bleiben deshalb fail-closed und werden "
                "nicht als Analysebehauptungen ausgegeben."
            )
            if reason not in verdict.reasons:
                verdict.reasons.append(reason)
        elif partition_status_conflicts:
            # Later completion/underclaiming recovery must not turn a
            # contradictory provider partition into a clean pass.
            verdict.verdict = (
                "retry" if observed_facts else "conservative_only"
            )
            verdict.needs_retry = bool(observed_facts)
        if (
            verdict.verdict in {"retry", "conservative_only"}
            and not invalid_verdict
            and not partition_status_conflicts
            and not unknown_claim_ids
            and not verdict.rejected_claim_ids
            and not rejected_by_runtime
            and not verdict._omitted_claim_ids
            and deliverable_ok
            and retrieval_ok
            and completion_ok
            and fact_usage_ok
            and response_requirements_ok
            and not llm_rejected_ids
            and set(llm_accepted_ids).union(preapproved_runtime_ids)
            == envelope_claim_ids - discarded_optional_mixed_claim_ids
            and (
                not verdict.needs_retry
                or self._accepted_claims_complete is not None
            )
        ):
            # The headline verdict is advisory. An exhaustive all-accepted
            # semantic partition wins only after every deterministic veto.
            verdict.verdict = "pass"
            verdict.needs_retry = False
        return verdict

    @staticmethod
    def should_retry(verdict: Any) -> bool:
        """Pure predicate: does this verdict call for another synthesise pass?

        Verbatim of the orchestrator loop guard
        ``verdict.verdict == "retry" and verdict.needs_retry``.
        """
        return verdict.verdict == "retry" and bool(verdict.needs_retry)

    @staticmethod
    def retry_feedback(envelope: Any, verdict: Any) -> List[str]:
        """Expose concrete failures without prescribing a canned repair."""

        claims = list(envelope.claims or [])
        id_aliases = {
            str(getattr(claim, "id", "") or "").strip(): f"c{index:03d}"
            for index, claim in enumerate(claims, start=1)
            if str(getattr(claim, "id", "") or "").strip()
        }
        feedback = [
            _replace_internal_ids(str(reason), id_aliases)
            for reason in list(verdict.reasons or [])
            if str(reason or "").strip()
            and not _reason_is_acceptance_only_feedback(reason)
        ]
        rejected = set(verdict.rejected_claim_ids or [])
        claim_reasons = dict(
            getattr(verdict, "_claim_reasons", {}) or {}
        )
        for index, claim in enumerate(claims, start=1):
            if claim.id not in rejected:
                continue
            text = str(getattr(claim, "text", "") or "").strip()
            detail = f"Verworfener Claim c{index:03d}"
            reasons = [
                _replace_internal_ids(str(reason).strip(), id_aliases)
                for reason in claim_reasons.get(claim.id, [])
                if str(reason).strip()
            ]
            if reasons:
                fact_ids = [
                    str(fact_id)
                    for fact_id in list(
                        getattr(claim, "fact_ids", []) or []
                    )
                    if str(fact_id)
                ]
                detail += (
                    " ("
                    + str(getattr(claim, "claim_kind", "") or "claim")
                    + (
                        "; facts=" + ", ".join(fact_ids[:4])
                        if fact_ids
                        else ""
                    )
                    + ")"
                )
                detail += " | Grund: " + "; ".join(reasons[:3])
            elif text:
                detail += f": {text[:240]}"
            feedback.append(detail)
        feedback.extend(
            [
                "Bereits verifizierte Claims werden automatisch erhalten. "
                "Gib nur fachlich reparierte oder noch fehlende Claims aus; "
                "wiederhole und nummeriere die erhaltenen Claims nicht.",
                "Repariere den Erkenntnisgedanken statt eine vorgegebene "
                "Antwortschablone zu imitieren. Zahlen sind in einer neuen "
                "Frage nur nötig, wenn sie sicher aus einem referenzierten "
                "Fact kopiert werden; sonst trägt der Fact die Motivation.",
            ]
        )
        return _dedupe_ordered_strs(feedback)

    @staticmethod
    def repair_candidates(
        envelope: Any,
        verdict: Any,
        *,
        include_accepted: bool = False,
    ) -> List[dict[str, Any]]:
        """Expose safe revision ideas as drafts, never as empirical evidence."""

        rejected = set(verdict.rejected_claim_ids or [])
        accepted = set(verdict.accepted_claim_ids or [])
        relation_rejected = set(
            getattr(envelope, "_kwic_relation_rejections", []) or []
        )
        claim_reasons = dict(
            getattr(verdict, "_claim_reasons", {}) or {}
        )
        candidates: List[dict[str, Any]] = []
        for claim in list(envelope.claims or []):
            assignment_reasons = _dedupe_ordered_strs(
                [
                    str(reason)
                    for reason in list(
                        getattr(
                            claim,
                            "_response_requirement_assignment_reasons",
                            [],
                        )
                        or []
                    )
                    if str(reason or "").strip()
                ]
            )
            completion_reasons = _dedupe_ordered_strs(
                [
                    str(reason)
                    for reason in list(
                        getattr(
                            claim,
                            "_response_requirement_completion_reasons",
                            [],
                        )
                        or []
                    )
                    if str(reason or "").strip()
                ]
            )
            verified_slot_core = bool(
                claim.id in accepted
                and claim.id not in rejected
                and str(
                    getattr(
                        claim,
                        "_unfulfilled_response_requirement_id",
                        "",
                    )
                    or ""
                ).strip()
                and completion_reasons
                and assignment_reasons == completion_reasons
            )
            if (
                claim.id not in rejected
                and not verified_slot_core
                and not (include_accepted and claim.id in accepted)
            ):
                continue
            # A failed source-relation audit means the proposition itself is
            # contaminated. Feeding it back as draft material makes small
            # models paraphrase the same participant/predicate drift instead
            # of deriving a fresh reading from the quoted source.
            if claim.id in relation_rejected:
                continue
            text = str(getattr(claim, "text", "") or "").strip()
            reasons = _dedupe_ordered_strs(
                [
                    str(reason)
                    for reason in claim_reasons.get(claim.id, [])
                    if str(reason or "").strip()
                ]
            )
            if verified_slot_core:
                reasons = completion_reasons
            fabricated_literal = any(
                reason.startswith(
                    "Zitat oder Beispiel ist nicht wortgetreu"
                )
                for reason in reasons
            )
            invalid_word_sketch_semantics = any(
                reason.startswith(
                    "Word-Sketch-Zähleinheit oder Evidenzumfang"
                )
                for reason in reasons
            )
            contaminated_scope_or_number = any(
                reason.startswith(
                    (
                        "Partielle, gesampelte oder Top-N-Evidenz trägt keinen "
                        "affirmativen korpusweiten Geltungsanspruch",
                        "Die referenzierten Passagen bewerten nur verwandte "
                        "Objekte",
                        "Sichtbare oder partielle KWIC-Zeilen sind ohne "
                        "explizite Kontextkodierung keine "
                        "Häufigkeitsverteilung",
                        "Eine wertende oder semantische Kontextkategorie ist "
                        "ohne explizite Kontextkodierung keine exakte "
                        "Beobachtung",
                        "Numerische Claims führen nicht belegte Werte ein",
                        "Explizite Feld-Wert-Claims sind nicht am gleichnamigen "
                        "Evidenzfeld belegt",
                    )
                )
                for reason in reasons
            )
            # A fabricated literal is not a repairable wording draft. Keeping
            # it in the next prompt makes smaller models paraphrase the same
            # invented example instead of returning to the observed facts.
            if (
                fabricated_literal
                or invalid_word_sketch_semantics
                or contaminated_scope_or_number
            ):
                continue
            if not text or (claim.id in rejected and not reasons):
                continue
            revision_status = (
                "verified_slot_core_missing_completion"
                if verified_slot_core
                else (
                    "needs_repair"
                    if claim.id in rejected
                    else "previously_verified_component"
                )
            )
            candidates.append(
                {
                    "id": f"r{len(candidates) + 1:03d}",
                    "claim_kind": str(
                        getattr(claim, "claim_kind", "") or "observation"
                    ),
                    "draft": text[:1200],
                    "fact_ids": [
                        str(fact_id)
                        for fact_id in list(
                            getattr(claim, "fact_ids", []) or []
                        )
                        if str(fact_id)
                    ],
                    "assertion_level": str(
                        getattr(claim, "assertion_level", "")
                        or "qualified"
                    ),
                    "response_requirement_id": str(
                        getattr(claim, "response_requirement_id", "")
                        or getattr(
                            claim,
                            "_unfulfilled_response_requirement_id",
                            "",
                        )
                        or ""
                    ),
                    "rejection_reasons": reasons[:4],
                    "revision_status": revision_status,
                    "preserve_semantic_core": verified_slot_core,
                    "draft_is_evidence": False,
                }
            )
            if len(candidates) >= 6:
                break
        return candidates

    async def run(
        self,
        contract: Any,
        observed_facts: List[Any],
    ) -> Tuple[Any, Any]:
        """Drive synthesise -> verify -> (bounded) retry; return (envelope, verdict).

        Behaviour-preserving extraction of the loop at
        ``orchestrator._build_grounded_final_answer`` (the synthesise/verify pair
        plus the single retry and the retry-exhausted downgrade). Side effects
        (SSE, session state, evidence-gap mutation) stay in the orchestrator,
        which inspects the returned ``(envelope, verdict)``.
        """
        self._focused_repair_attempt_counts.clear()
        retained_claims: dict[tuple[str, tuple[str, ...], str], Any] = {}
        completion_slot_cores: dict[str, Any] = {}
        pending_claims: dict[tuple[str, tuple[str, ...], str], Any] = {}
        blocked_claim_strengths: dict[
            tuple[str, tuple[str, ...], str],
            int,
        ] = {}
        persistent_evidence_gaps: List[str] = []
        persistent_blocked_claims: List[str] = []
        ordered_positions_by_id: dict[str, int] = {}
        ordered_positions_by_signature: dict[
            tuple[str, tuple[str, ...], str],
            int,
        ] = {}
        self._relation_protocol_recovery_count = 0
        self._relation_schema_aliases: List[str] = []
        projected_fact_citation_strip_count = 0
        persistent_claim_failure_feedback: List[str] = []
        equivalent_response_requirement_ids = (
            _assign_equivalent_missing_response_slots(
                [],
                list(getattr(contract, "response_requirements", []) or []),
            )
        )
        competing_hypothesis_requirement_ids = set(
            _competing_hypothesis_requirement_ids(
                contract,
                self._question_text,
            )
        )
        retrieval_candidate_assessments = (
            await self._adjudicate_confirmation_retrieval(
                contract,
                observed_facts,
            )
        )

        def retry_feedback_with_history(
            current_envelope: Any,
            current_verdict: Any,
        ) -> List[str]:
            """Retain bounded source-fidelity failures across repair turns."""

            nonlocal persistent_claim_failure_feedback
            rejected_ids = set(
                getattr(current_verdict, "rejected_claim_ids", []) or []
            )
            reasons_by_claim = dict(
                getattr(current_verdict, "_claim_reasons", {}) or {}
            )
            current_failures: List[str] = []
            for claim in list(
                getattr(current_envelope, "claims", []) or []
            ):
                claim_id = str(getattr(claim, "id", "") or "")
                if claim_id not in rejected_ids:
                    continue
                fact_ids = _dedupe_ordered_strs(
                    [
                        str(fact_id)
                        for fact_id in list(
                            getattr(claim, "fact_ids", []) or []
                        )
                        if str(fact_id)
                    ]
                )
                fact_scope = (
                    " zu facts=" + ", ".join(fact_ids[:6])
                    if fact_ids
                    else ""
                )
                current_failures.extend(
                    "Für eine zuvor verworfene Deutung"
                    + fact_scope
                    + " bleibt verbindlich: "
                    + str(reason).strip()
                    for reason in reasons_by_claim.get(claim_id, [])
                    if str(reason or "").strip()
                )
            persistent_claim_failure_feedback = _dedupe_ordered_strs(
                current_failures + persistent_claim_failure_feedback
            )[:10]
            return _dedupe_ordered_strs(
                persistent_claim_failure_feedback
                + self.retry_feedback(current_envelope, current_verdict)
            )

        async def verify_candidate(
            current_envelope: Any,
            *,
            preapproved_semantic_signatures: Optional[
                set[tuple[str, tuple[str, ...], str]]
            ] = None,
        ) -> Any:
            first_verdict = await self.verify_envelope(
                contract,
                observed_facts,
                current_envelope,
                retrieval_candidate_assessments=(
                    retrieval_candidate_assessments
                ),
                preapproved_semantic_signatures=(
                    preapproved_semantic_signatures
                ),
            )
            preapproved_claim_ids = {
                str(getattr(claim, "id", "") or "")
                for claim in list(
                    getattr(current_envelope, "claims", []) or []
                )
                if preapproved_semantic_signatures
                and _claim_signature(claim)
                in preapproved_semantic_signatures
            }
            relation_candidates = set(
                first_verdict.accepted_claim_ids or []
            ) - preapproved_claim_ids
            (
                late_relation_rejected,
                late_relation_reasons,
            ) = await self._audit_partition_relation_acceptances(
                contract,
                observed_facts,
                current_envelope,
                relation_candidates,
                list(retrieval_candidate_assessments or []),
            )
            if late_relation_rejected:
                first_verdict.accepted_claim_ids = [
                    claim_id
                    for claim_id in list(
                        first_verdict.accepted_claim_ids or []
                    )
                    if claim_id not in late_relation_rejected
                ]
                first_verdict.rejected_claim_ids = _dedupe_ordered_strs(
                    list(first_verdict.rejected_claim_ids or [])
                    + sorted(late_relation_rejected)
                )
                first_verdict._omitted_claim_ids = set(
                    getattr(first_verdict, "_omitted_claim_ids", set())
                    or set()
                ) - late_relation_rejected
                claim_reasons = dict(
                    getattr(first_verdict, "_claim_reasons", {}) or {}
                )
                attention_fact_ids: List[str] = []
                for claim in list(
                    getattr(current_envelope, "claims", []) or []
                ):
                    claim_id = str(getattr(claim, "id", "") or "")
                    if claim_id not in late_relation_rejected:
                        continue
                    attention_fact_ids.extend(
                        str(fact_id)
                        for fact_id in list(
                            getattr(claim, "fact_ids", []) or []
                        )
                        if str(fact_id)
                    )
                    claim_reasons[claim_id] = _dedupe_ordered_strs(
                        list(claim_reasons.get(claim_id, []) or [])
                        + list(late_relation_reasons.get(claim_id, []) or [])
                    )
                first_verdict._claim_reasons = claim_reasons
                first_verdict._retrieval_attention_fact_ids = (
                    _dedupe_ordered_strs(
                        list(
                            getattr(
                                first_verdict,
                                "_retrieval_attention_fact_ids",
                                [],
                            )
                            or []
                        )
                        + attention_fact_ids
                    )
                )
                first_verdict.reasons = _dedupe_ordered_strs(
                    list(first_verdict.reasons or [])
                    + [
                        reason
                        for reasons in late_relation_reasons.values()
                        for reason in reasons
                    ]
                )
                first_verdict.verdict = (
                    "retry" if observed_facts else "conservative_only"
                )
                first_verdict.needs_retry = bool(observed_facts)
            if not getattr(first_verdict, "_omitted_claim_ids", set()):
                return first_verdict

            # A non-exhaustive verdict is a verifier protocol failure, not a
            # reason to re-evaluate claims that were already classified. A
            # second whole-envelope verdict introduced contradictory decisions
            # and could erase an independent source-relation acceptance. Ask
            # the constrained partitioner only about the omitted claims.
            current_verdict = first_verdict
            claim_ids = _dedupe_ordered_strs(
                [
                    str(getattr(claim, "id", "") or "").strip()
                    for claim in list(current_envelope.claims or [])
                    if str(getattr(claim, "id", "") or "").strip()
                ]
            )
            claim_id_set = set(claim_ids)
            omitted_ids = set(
                getattr(first_verdict, "_omitted_claim_ids", set()) or set()
            )
            accepted_ids = (
                set(first_verdict.accepted_claim_ids or []) & claim_id_set
            )
            rejected_ids = (
                set(first_verdict.rejected_claim_ids or []) - omitted_ids
            ) & claim_id_set
            accepted_ids.difference_update(rejected_ids)
            unresolved_ids = claim_id_set - accepted_ids - rejected_ids

            if unresolved_ids:
                (
                    partition_accepted,
                    partition_rejected,
                    partition_reasons,
                ) = await self._repair_omitted_claim_partition(
                    contract,
                    observed_facts,
                    current_envelope,
                    unresolved_ids,
                )
                (
                    partition_relation_rejected,
                    partition_relation_reasons,
                ) = await self._audit_partition_relation_acceptances(
                    contract,
                    observed_facts,
                    current_envelope,
                    partition_accepted,
                    list(retrieval_candidate_assessments or []),
                )
                if partition_relation_rejected:
                    partition_accepted.difference_update(
                        partition_relation_rejected
                    )
                    partition_rejected.update(
                        partition_relation_rejected
                    )
                    claim_reasons = dict(
                        getattr(current_verdict, "_claim_reasons", {}) or {}
                    )
                    for claim_id, reasons in partition_relation_reasons.items():
                        claim_reasons[claim_id] = _dedupe_ordered_strs(
                            list(claim_reasons.get(claim_id, []) or [])
                            + list(reasons or [])
                        )
                        partition_reasons.extend(
                            f"{claim_id}: {reason}"
                            for reason in reasons
                            if str(reason or "").strip()
                        )
                    current_verdict._claim_reasons = claim_reasons
                rejected_ids.update(partition_rejected)
                accepted_ids.update(partition_accepted - rejected_ids)
                unresolved_ids = (
                    claim_id_set - accepted_ids - rejected_ids
                )
                current_verdict.reasons = _dedupe_ordered_strs(
                    list(current_verdict.reasons or [])
                    + partition_reasons
                )

            # Combine the original explicit decisions with the constrained
            # classification. A rejection wins and silence remains unverified.
            if accepted_ids or rejected_ids:
                current_verdict.accepted_claim_ids = [
                    claim_id
                    for claim_id in claim_ids
                    if claim_id in accepted_ids
                ]
                current_verdict.rejected_claim_ids = [
                    claim_id
                    for claim_id in claim_ids
                    if claim_id in rejected_ids or claim_id in unresolved_ids
                ]
                current_verdict._omitted_claim_ids = set(unresolved_ids)

                deliverable_ok, _deliverable_reason = (
                    self._envelope_matches_deliverable_kind(
                        current_envelope,
                        deliverable_kind=contract.deliverable_kind,
                    )
                )
                complete = deliverable_ok
                if self._accepted_claims_complete is not None:
                    complete, _completion_reason = (
                        self._accepted_claims_complete(
                            current_envelope,
                            current_verdict.accepted_claim_ids,
                            current_verdict.rejected_claim_ids,
                            observed_facts,
                            contract,
                        )
                    )
                    complete = complete and deliverable_ok
                retrieval_complete = not (
                    list(
                        getattr(
                            current_verdict,
                            "unaccounted_retrieval_fact_ids",
                            [],
                        )
                        or []
                    )
                    or list(
                        getattr(
                            current_verdict,
                            "_retrieval_attention_fact_ids",
                            [],
                        )
                        or []
                    )
                )
                if (
                    not rejected_ids
                    and not unresolved_ids
                    and complete
                    and retrieval_complete
                ):
                    current_verdict.verdict = "pass"
                    current_verdict.needs_retry = False
                else:
                    current_verdict.verdict = (
                        "retry" if observed_facts else "conservative_only"
                    )
                    current_verdict.needs_retry = bool(observed_facts)
                if unresolved_ids:
                    current_verdict._verifier_protocol_degraded = True
                return current_verdict

            current_verdict.verdict = "conservative_only"
            current_verdict.needs_retry = False
            current_verdict.accepted_claim_ids = []
            current_verdict.rejected_claim_ids = claim_ids
            current_verdict._protocol_failure = True
            protocol_reason = (
                "Der Grounding-Verifier und die enge Nachklassifikation haben "
                "keinen Claim ausdrücklich klassifiziert; dieser Kandidat wird "
                "ohne weitere Antwort-Neusynthese geschlossen verworfen."
            )
            if protocol_reason not in current_verdict.reasons:
                current_verdict.reasons.append(protocol_reason)
            retained_claims.clear()
            pending_claims.clear()
            blocked_claim_strengths.clear()
            persistent_blocked_claims.clear()
            return current_verdict

        def retain_verified_claims(current_envelope: Any, current_verdict: Any) -> None:
            nonlocal persistent_blocked_claims
            if getattr(current_verdict, "_protocol_failure", False) or getattr(
                current_verdict,
                "_replace_whole_deliverable",
                False,
            ):
                return
            accepted_ids = set(current_verdict.accepted_claim_ids or [])
            rejected_ids = set(current_verdict.rejected_claim_ids or [])
            assertion_repairable_ids = set(
                getattr(
                    current_verdict,
                    "_assertion_repairable_claim_ids",
                    set(),
                )
                or set()
            )
            omitted_ids = set(
                getattr(
                    current_verdict,
                    "_omitted_claim_ids",
                    set(),
                )
                or set()
            )
            claims = list(current_envelope.claims or [])
            if not ordered_positions_by_id:
                for position, claim in enumerate(claims):
                    claim_id = str(
                        getattr(claim, "id", "") or ""
                    ).strip()
                    if claim_id:
                        ordered_positions_by_id[claim_id] = position
                    ordered_positions_by_signature[
                        _claim_signature(claim)
                    ] = position
            persistent_blocked_claims = _dedupe_ordered_strs(
                persistent_blocked_claims
                + list(getattr(current_envelope, "blocked_claims", []) or [])
            )
            accepted_signatures = {
                _claim_signature(claim)
                for claim in claims
                if claim.id in accepted_ids
            }
            # Record rejections first so ordering duplicate variants inside one
            # envelope cannot decide whether a weaker, valid repair survives.
            for claim in claims:
                if claim.id not in rejected_ids:
                    continue
                if claim.id in omitted_ids:
                    # Omission violates the exhaustive verdict contract but is
                    # not a semantic rejection. Keep the draft pending so the
                    # retry must classify it even if synthesis drops it.
                    pending_claims[_claim_signature(claim)] = claim
                    continue
                signature = _claim_signature(claim)
                if signature in accepted_signatures:
                    # The runtime duplicate gate may retain one copy and reject
                    # another with the same visible proposition. The rejected
                    # copy must not blacklist the accepted twin.
                    continue
                pending_claims.pop(signature, None)
                strength = (
                    _assertion_strength(claim)
                    if claim.id in assertion_repairable_ids
                    else 0
                )
                blocked_claim_strengths[signature] = min(
                    blocked_claim_strengths.get(signature, strength),
                    strength,
                )
                retained_claims.pop(signature, None)
                text = str(getattr(claim, "text", "") or "").strip()
                if text:
                    persistent_blocked_claims = _dedupe_ordered_strs(
                        persistent_blocked_claims + [text]
                    )

            for claim in claims:
                if claim.id not in accepted_ids:
                    continue
                signature = _claim_signature(claim)
                pending_claims.pop(signature, None)
                assignment_reasons = _dedupe_ordered_strs(
                    [
                        str(reason)
                        for reason in list(
                            getattr(
                                claim,
                                "_response_requirement_assignment_reasons",
                                [],
                            )
                            or []
                        )
                        if str(reason or "").strip()
                    ]
                )
                completion_reasons = _dedupe_ordered_strs(
                    [
                        str(reason)
                        for reason in list(
                            getattr(
                                claim,
                                "_response_requirement_completion_reasons",
                                [],
                            )
                            or []
                        )
                        if str(reason or "").strip()
                    ]
                )
                unfulfilled_slot = str(
                    getattr(
                        claim,
                        "_unfulfilled_response_requirement_id",
                        "",
                    )
                    or ""
                ).strip()
                if (
                    unfulfilled_slot
                    and completion_reasons
                    and assignment_reasons == completion_reasons
                ):
                    # Repeated counted slots are interchangeable bookkeeping
                    # units. Pinning one incomplete proposition to such a slot
                    # discarded a different, fully valid repair for that unit.
                    if (
                        unfulfilled_slot
                        not in equivalent_response_requirement_ids
                    ):
                        completion_slot_cores.setdefault(
                            unfulfilled_slot,
                            copy.copy(claim),
                        )
                    continue
                fulfilled_slot = str(
                    getattr(claim, "response_requirement_id", "") or ""
                ).strip()
                if fulfilled_slot and not assignment_reasons:
                    completion_slot_cores.pop(fulfilled_slot, None)
                if assignment_reasons:
                    continue
                strength = _assertion_strength(claim)
                blocked_strength = blocked_claim_strengths.get(signature)
                if blocked_strength is not None:
                    # A weaker assertion is a real repair; a renamed claim at
                    # the same strength is still the rejected proposition.
                    if strength >= blocked_strength:
                        continue
                    blocked_claim_strengths.pop(signature, None)
                    text = str(getattr(claim, "text", "") or "").strip()
                    persistent_blocked_claims = [
                        item
                        for item in persistent_blocked_claims
                        if item != text
                    ]
                retained = retained_claims.get(signature)
                if retained is None or strength < _assertion_strength(retained):
                    retained_claims[signature] = claim

        def completion_core_candidates() -> List[dict[str, Any]]:
            candidates: List[dict[str, Any]] = []
            for slot_id, core in completion_slot_cores.items():
                candidates.append(
                    {
                        "id": f"r{len(candidates) + 1:03d}",
                        "claim_kind": str(
                            getattr(core, "claim_kind", "") or "observation"
                        ),
                        "draft": str(getattr(core, "text", "") or "")[:1200],
                        "fact_ids": _dedupe_ordered_strs(
                            [
                                str(fact_id)
                                for fact_id in list(
                                    getattr(core, "fact_ids", []) or []
                                )
                                if str(fact_id)
                            ]
                        ),
                        "assertion_level": str(
                            getattr(core, "assertion_level", "")
                            or "qualified"
                        ),
                        "response_requirement_id": slot_id,
                        "rejection_reasons": _dedupe_ordered_strs(
                            [
                                str(reason)
                                for reason in list(
                                    getattr(
                                        core,
                                        "_response_requirement_completion_reasons",
                                        [],
                                    )
                                    or []
                                )
                                if str(reason or "").strip()
                            ]
                        )[:4],
                        "revision_status": (
                            "verified_slot_core_missing_completion"
                        ),
                        "preserve_semantic_core": True,
                        "draft_is_evidence": False,
                    }
                )
            return candidates

        def preserves_completion_core(candidate: Any, core: Any) -> bool:
            candidate_text = " ".join(
                str(getattr(candidate, "text", "") or "").split()
            ).casefold()
            core_text = " ".join(
                str(getattr(core, "text", "") or "").split()
            ).casefold()
            return bool(
                core_text
                and candidate_text.startswith(core_text)
                and str(getattr(candidate, "claim_kind", "") or "")
                == str(getattr(core, "claim_kind", "") or "")
                and str(getattr(candidate, "assertion_level", "") or "")
                == str(getattr(core, "assertion_level", "") or "")
                and set(getattr(core, "fact_ids", []) or []).issubset(
                    set(getattr(candidate, "fact_ids", []) or [])
                )
            )

        def enforce_completion_core_preservation(current_envelope: Any) -> None:
            kept: List[Any] = []
            rejected_count = 0
            for claim in list(getattr(current_envelope, "claims", []) or []):
                slot_id = str(
                    getattr(claim, "response_requirement_id", "") or ""
                ).strip()
                core = completion_slot_cores.get(slot_id)
                if core is None or preserves_completion_core(claim, core):
                    kept.append(claim)
                else:
                    rejected_count += 1
            current_envelope.claims = kept
            if rejected_count:
                current_envelope._completion_core_replacement_rejections = (
                    rejected_count
                )

        def restore_completion_cores(current_envelope: Any) -> List[str]:
            if not completion_slot_cores:
                return []
            slot_ids = set(completion_slot_cores)
            current_envelope.claims = [
                claim
                for claim in list(getattr(current_envelope, "claims", []) or [])
                if str(
                    getattr(
                        claim,
                        "_unfulfilled_response_requirement_id",
                        "",
                    )
                    or ""
                ).strip()
                not in slot_ids
            ]
            used_ids = {
                str(getattr(claim, "id", "") or "").strip()
                for claim in current_envelope.claims
            }
            restored_ids: List[str] = []
            for index, (slot_id, core) in enumerate(
                completion_slot_cores.items(),
                start=1,
            ):
                restored = copy.copy(core)
                claim_id = str(getattr(restored, "id", "") or "").strip()
                if not claim_id or claim_id in used_ids:
                    claim_id = f"partial_slot_{index}"
                    while claim_id in used_ids:
                        index += 1
                        claim_id = f"partial_slot_{index}"
                    restored.id = claim_id
                restored.response_requirement_id = ""
                restored._unfulfilled_response_requirement_id = slot_id
                restored._verified_slot_core_missing_completion = True
                current_envelope.claims.append(restored)
                used_ids.add(claim_id)
                restored_ids.append(claim_id)
            return restored_ids

        def merge_retained_claims(current_envelope: Any) -> None:
            carry_forward = {
                **pending_claims,
                **retained_claims,
            }
            carry_by_id = {
                str(getattr(claim, "id", "") or "").strip(): claim
                for claim in carry_forward.values()
                if str(getattr(claim, "id", "") or "").strip()
            }
            proposed_claims = list(current_envelope.claims or [])
            if contract.deliverable_kind in {
                "followup_questions",
                "method_advice",
            }:
                # Repairs for ordered lists fill the remaining slots after
                # already accepted items; otherwise a new "third" item is
                # moved to position one and rejected as self-contradictory.
                proposed_claims = [
                    *[
                        copy.copy(claim)
                        for claim in retained_claims.values()
                    ],
                    *[
                        copy.copy(claim)
                        for claim in pending_claims.values()
                    ],
                    *proposed_claims,
                ]
            merged_claims: List[Any] = []
            signature_positions: dict[
                tuple[str, tuple[str, ...], str],
                int,
            ] = {}
            used_ids: set[str] = set()
            reserved_ids = set(carry_by_id)
            reserved_ids.update(
                str(getattr(claim, "id", "") or "").strip()
                for claim in proposed_claims
                if str(getattr(claim, "id", "") or "").strip()
            )

            def adds_requirement_assignment(candidate: Any, prior: Any) -> bool:
                return bool(
                    str(
                        getattr(candidate, "response_requirement_id", "")
                        or ""
                    ).strip()
                    and not str(
                        getattr(prior, "response_requirement_id", "") or ""
                    ).strip()
                )

            def fresh_retry_id(claim_id: str) -> str:
                base_id = f"{claim_id or 'claim'}__retry"
                suffix = 1
                new_id = f"{base_id}_{suffix}"
                while new_id in reserved_ids or new_id in used_ids:
                    suffix += 1
                    new_id = f"{base_id}_{suffix}"
                reserved_ids.add(new_id)
                return new_id

            for proposed_claim in proposed_claims:
                proposed_id = str(
                    getattr(proposed_claim, "id", "") or ""
                ).strip()
                claim = copy.copy(proposed_claim)
                retained_with_same_id = carry_by_id.get(proposed_id)
                if retained_with_same_id is not None:
                    if _claim_signature(retained_with_same_id) == _claim_signature(
                        proposed_claim
                    ):
                        claim = copy.copy(
                            proposed_claim
                            if adds_requirement_assignment(
                                proposed_claim,
                                retained_with_same_id,
                            )
                            else retained_with_same_id
                        )
                    else:
                        # Small models often restart their IDs at claim_001 on
                        # every repair. Keep both propositions: the verified
                        # claim retains its ID, while the genuinely new repair
                        # receives a deterministic collision-free ID.
                        claim.id = fresh_retry_id(proposed_id)
                signature = _claim_signature(claim)
                if signature not in signature_positions:
                    claim_id = str(
                        getattr(claim, "id", "") or ""
                    ).strip()
                    if claim_id in used_ids:
                        claim.id = fresh_retry_id(claim_id)
                    signature_positions[signature] = len(merged_claims)
                    merged_claims.append(claim)
                    used_ids.add(
                        str(getattr(claim, "id", "") or "").strip()
                    )
                    continue
                position = signature_positions[signature]
                if adds_requirement_assignment(
                    claim,
                    merged_claims[position],
                ) or _assertion_strength(claim) < _assertion_strength(
                    merged_claims[position]
                ):
                    merged_claims[position] = claim
            seen_signatures = set(signature_positions)
            for signature, retained in carry_forward.items():
                if signature in blocked_claim_strengths:
                    continue
                if signature in seen_signatures:
                    position = signature_positions[signature]
                    current = merged_claims[position]
                    if _assertion_strength(current) > _assertion_strength(
                        retained
                    ):
                        safer = copy.copy(retained)
                        safer.id = current.id
                        merged_claims[position] = safer
                    continue
                claim = copy.copy(retained)
                original_id = (
                    str(getattr(claim, "id", "") or "").strip() or "claim"
                )
                if original_id in used_ids:
                    position = next(
                        (
                            index
                            for index, current in enumerate(merged_claims)
                            if str(
                                getattr(current, "id", "") or ""
                            ).strip()
                            == original_id
                        ),
                        None,
                    )
                    if position is not None:
                        merged_claims[position] = claim
                        signature_positions[signature] = position
                        seen_signatures.add(signature)
                    continue
                claim.id = original_id
                merged_claims.append(claim)
                signature_positions[signature] = len(merged_claims) - 1
                seen_signatures.add(signature)
                used_ids.add(original_id)
            if ordered_positions_by_id:
                positioned: List[tuple[int, int, Any]] = []
                unpositioned: List[tuple[int, Any]] = []
                occupied_positions: set[int] = set()
                for sequence, claim in enumerate(merged_claims):
                    position = ordered_positions_by_signature.get(
                        _claim_signature(claim)
                    )
                    if position is None:
                        position = ordered_positions_by_id.get(
                            str(getattr(claim, "id", "") or "").strip()
                        )
                    if position is None or position in occupied_positions:
                        unpositioned.append((sequence, claim))
                        continue
                    occupied_positions.add(position)
                    positioned.append((position, sequence, claim))
                free_positions = [
                    position
                    for position in range(len(ordered_positions_by_id))
                    if position not in occupied_positions
                ]
                next_position = len(ordered_positions_by_id)
                for sequence, claim in unpositioned:
                    if free_positions:
                        position = free_positions.pop(0)
                    else:
                        position = next_position
                        next_position += 1
                    occupied_positions.add(position)
                    positioned.append((position, sequence, claim))
                merged_claims = [
                    claim
                    for _, _, claim in sorted(
                        positioned,
                        key=lambda item: (item[0], item[1]),
                    )
                ]
            visible_positions: dict[tuple[str, str], int] = {}
            visible_claims: List[Any] = []
            visible_duplicate_count = 0
            retained_signatures = set(retained_claims)
            for claim in merged_claims:
                visible_signature = _visible_claim_signature(claim)
                position = visible_positions.get(visible_signature)
                if position is None and visible_signature[0]:
                    position = next(
                        (
                            index
                            for index, candidate in enumerate(visible_claims)
                            if _near_duplicate_visible_claim(
                                claim,
                                candidate,
                            )
                        ),
                        None,
                    )
                if not visible_signature[0] or position is None:
                    visible_positions[visible_signature] = len(
                        visible_claims
                    )
                    visible_claims.append(claim)
                    continue
                visible_duplicate_count += 1
                visible_positions[visible_signature] = position
                current = visible_claims[position]
                current_is_retained = (
                    _claim_signature(current) in retained_signatures
                )
                candidate_is_retained = (
                    _claim_signature(claim) in retained_signatures
                )
                if (
                    candidate_is_retained
                    and not current_is_retained
                ) or (
                    candidate_is_retained == current_is_retained
                    and _assertion_strength(claim)
                    < _assertion_strength(current)
                ):
                    visible_claims[position] = claim
            merged_claims = visible_claims
            if visible_duplicate_count:
                current_envelope._visible_duplicate_merge_count = int(
                    getattr(
                        current_envelope,
                        "_visible_duplicate_merge_count",
                        0,
                    )
                    or 0
                ) + visible_duplicate_count
            current_envelope.claims = merged_claims
            if hasattr(current_envelope, "blocked_claims"):
                current_envelope.blocked_claims = _dedupe_ordered_strs(
                    list(getattr(current_envelope, "blocked_claims", []) or [])
                    + persistent_blocked_claims
                )

        def retain_evidence_gaps(current_envelope: Any) -> None:
            nonlocal persistent_evidence_gaps
            persistent_evidence_gaps = _dedupe_ordered_strs(
                persistent_evidence_gaps
                + list(getattr(current_envelope, "evidence_gaps", []) or [])
            )
            if hasattr(current_envelope, "evidence_gaps"):
                current_envelope.evidence_gaps = list(persistent_evidence_gaps)

        envelope = await self.synthesise_envelope(
            contract,
            observed_facts,
            retrieval_candidate_assessments=(
                retrieval_candidate_assessments
            ),
        )
        projected_fact_citation_strip_count += int(
            getattr(
                envelope,
                "_projected_fact_citation_strip_count",
                0,
            )
            or 0
        )
        retain_evidence_gaps(envelope)
        verdict = await verify_candidate(envelope)
        retain_verified_claims(envelope, verdict)

        # WAS in jeder Runde entschieden wurde und WARUM. Eine Naht statt
        # zehn: die Tore, die ``verdict.verdict`` auf ``retry`` setzen,
        # haengen ihre Begruendung ohnehin an ``verdict.reasons``. Ohne
        # diese Aufzeichnung zeigte der Mitschnitt vom 2026-08-28 siebenmal
        # „pass, nichts zurueckgewiesen“, waehrend in jeder Runde ein Tor
        # beanstandet hatte. Der Verlauf muss ueber Rundengrenzen halten,
        # denn jede Runde erzeugt ein NEUES Verdict-Objekt.
        tor_verlauf: List[Any] = []
        stagniert = False

        def _envelope_signatur(huelle: Any) -> tuple:
            """Die Claim-TEXTE der Huelle, stabil ueber Rundengrenzen.

            Nicht ``_claim_signature``: die traegt ``fact_ids``, und der
            Harness nummeriert die Fakten je Runde neu. Dieselbe Aussage
            haette vor und nach einer Reparaturrunde verschiedene
            Signaturen.
            """
            try:
                return tuple(sorted(
                    " ".join(str(getattr(c, "text", "") or "").split())
                    for c in list(getattr(huelle, "claims", []) or [])
                ))
            except Exception:
                return ()

        def _runde_festhalten(nummer: int, urteil: Any, huelle: Any = None) -> None:
            try:
                tor_verlauf.append({
                    "runde": nummer,
                    "huelle": list(_envelope_signatur(huelle)),
                    "verdict": getattr(urteil, "verdict", ""),
                    "needs_retry": bool(getattr(urteil, "needs_retry", False)),
                    "gruende": list(getattr(urteil, "reasons", []) or [])[:6],
                    "anomalien": list(
                        getattr(urteil, "_verifier_protocol_anomalies", []) or []
                    ),
                    "angenommen": len(getattr(urteil, "accepted_claim_ids", []) or []),
                    "verworfen": len(getattr(urteil, "rejected_claim_ids", []) or []),
                })
                urteil._tor_verlauf = list(tor_verlauf)
            except Exception:  # Telemetrie darf einen Turn nie kosten.
                pass

        _runde_festhalten(1, verdict, envelope)
        attempts = 0
        while self.should_retry(verdict) and attempts < self._max_retries:
            attempts += 1
            replace_whole_deliverable = bool(
                getattr(
                    verdict,
                    "_replace_whole_deliverable",
                    False,
                )
            )
            revision_candidates = self.repair_candidates(
                envelope,
                verdict,
                include_accepted=replace_whole_deliverable,
            )
            revision_candidates = [
                {
                    **candidate,
                    "preserve_semantic_core": False,
                    "revision_status": (
                        "replaceable_incomplete_equivalent_unit"
                    ),
                }
                if bool(candidate.get("preserve_semantic_core"))
                and str(candidate.get("response_requirement_id", "") or "")
                in equivalent_response_requirement_ids
                else candidate
                for candidate in revision_candidates
            ]
            core_candidates = completion_core_candidates()
            if core_candidates:
                revision_candidates = core_candidates + [
                    candidate
                    for candidate in revision_candidates
                    if not (
                        bool(candidate.get("preserve_semantic_core"))
                        and str(
                            candidate.get("response_requirement_id", "")
                            or ""
                        )
                        in completion_slot_cores
                    )
                ]
            if bool(
                getattr(
                    verdict,
                    "_replace_competing_hypothesis_pair",
                    False,
                )
            ):
                def keep_non_competing_hypothesis(claim: Any) -> bool:
                    return str(
                        getattr(
                            claim,
                            "response_requirement_id",
                            "",
                        )
                        or getattr(
                            claim,
                            "_unfulfilled_response_requirement_id",
                            "",
                        )
                        or ""
                    ).strip() not in competing_hypothesis_requirement_ids

                retained_claims = {
                    signature: claim
                    for signature, claim in retained_claims.items()
                    if keep_non_competing_hypothesis(claim)
                }
                pending_claims = {
                    signature: claim
                    for signature, claim in pending_claims.items()
                    if keep_non_competing_hypothesis(claim)
                }
                completion_slot_cores = {
                    requirement_id: claim
                    for requirement_id, claim in completion_slot_cores.items()
                    if requirement_id
                    not in competing_hypothesis_requirement_ids
                }
                revision_candidates = [
                    {
                        **candidate,
                        "preserve_semantic_core": False,
                        "revision_status": "replace_noncompeting_pair",
                    }
                    if str(
                        candidate.get("response_requirement_id", "") or ""
                    ).strip()
                    in competing_hypothesis_requirement_ids
                    else candidate
                    for candidate in revision_candidates
                ]
            if bool(
                getattr(
                    verdict,
                    "_replace_incomplete_interpretations",
                    False,
                )
            ):
                scoped_replacement_ids = getattr(
                    verdict,
                    "_replace_incomplete_retrieval_interpretation_ids",
                    None,
                )
                if scoped_replacement_ids is None:
                    preserved_local_ids = set(
                        getattr(
                            verdict,
                            "_preserved_local_retrieval_interpretation_ids",
                            [],
                        )
                        or []
                    )
                    def keep_claim(claim) -> bool:
                        return (
                            str(getattr(claim, "claim_kind", "") or "")
                            != "interpretation"
                            or str(getattr(claim, "id", "") or "")
                            in preserved_local_ids
                        )
                else:
                    replacement_ids = set(scoped_replacement_ids or [])

                    def keep_claim(claim) -> bool:
                        return (
                            str(getattr(claim, "id", "") or "")
                            not in replacement_ids
                        )
                retained_claims = {
                    signature: claim
                    for signature, claim in retained_claims.items()
                    if keep_claim(claim)
                }
                pending_claims = {
                    signature: claim
                    for signature, claim in pending_claims.items()
                    if keep_claim(claim)
                }
            if bool(
                getattr(
                    verdict,
                    "_replace_incomplete_word_sketch_units",
                    False,
                )
            ):
                retained_claims = {
                    signature: claim
                    for signature, claim in retained_claims.items()
                    if not (
                        str(getattr(claim, "claim_kind", "") or "")
                        == "observation"
                        and _WORD_SKETCH_UNIT_EXPLANATION_PATTERN.search(
                            str(getattr(claim, "text", "") or "")
                        )
                    )
                }
                pending_claims = {
                    signature: claim
                    for signature, claim in pending_claims.items()
                    if not (
                        str(getattr(claim, "claim_kind", "") or "")
                        == "observation"
                        and _WORD_SKETCH_UNIT_EXPLANATION_PATTERN.search(
                            str(getattr(claim, "text", "") or "")
                        )
                    )
                }
            if replace_whole_deliverable:
                retained_claims.clear()
                pending_claims.clear()
                blocked_claim_strengths.clear()
                persistent_blocked_claims.clear()
            envelope = await self.synthesise_envelope(
                contract,
                observed_facts,
                retry_reasons=retry_feedback_with_history(
                    envelope,
                    verdict,
                ),
                preserved_claims=list(retained_claims.values()),
                pending_claims=list(pending_claims.values()),
                repair_candidates=(
                    revision_candidates
                ),
                retrieval_candidate_assessments=(
                    retrieval_candidate_assessments
                ),
                retrieval_attention_fact_ids=list(
                    getattr(
                        verdict,
                        "_retrieval_attention_fact_ids",
                        [],
                    )
                    or []
                ),
                replace_whole_deliverable=replace_whole_deliverable,
            )
            enforce_completion_core_preservation(envelope)
            projected_fact_citation_strip_count += int(
                getattr(
                    envelope,
                    "_projected_fact_citation_strip_count",
                    0,
                )
                or 0
            )
            if not replace_whole_deliverable:
                merge_retained_claims(envelope)
            retain_evidence_gaps(envelope)
            verdict = await verify_candidate(
                envelope,
                preapproved_semantic_signatures=set(retained_claims),
            )
            retain_verified_claims(envelope, verdict)
            _runde_festhalten(attempts + 1, verdict, envelope)
            # STAGNATION. Beanstandet eine Runde WORTGLEICH dasselbe wie die
            # vorige und aendert sich an der angenommenen wie verworfenen
            # Menge nichts, hat die Schleife bewiesen, dass sie an diesem
            # Grund nicht konvergiert. Eine weitere Neusynthese kostet dann
            # rund 360 Sekunden und kann nichts beitragen.
            #
            # Das ist erst seit dem Temperatur-Pin belastbar: vorher war
            # jede Wiederholung eine unabhaengige Ziehung, und Gleichheit
            # zweier Runden sagte nichts ueber die naechste. Deshalb
            # gehoeren Pin und Bremse zusammen.
            #
            # Ein schlichtes ``break``, KEIN Eingriff in should_retry: die
            # Herabstufung unter dieser Schleife muss weiterhin laufen,
            # sonst endet der Turn mit ``retry`` statt mit einem Ergebnis.
            if len(tor_verlauf) >= 2:
                a, b = tor_verlauf[-2], tor_verlauf[-1]
                if (
                    a.get("huelle")
                    and a.get("huelle") == b.get("huelle")
                    and sorted(a.get("gruende") or []) == sorted(b.get("gruende") or [])
                ):
                    stagniert = True
                    if self.STAGNATION_REASON not in verdict.reasons:
                        verdict.reasons.append(self.STAGNATION_REASON)
                    break
        if self.should_retry(verdict):
            verdict.verdict = "conservative_only"
            verdict.needs_retry = False
            # Bei Stagnation war das Budget NICHT erschoepft. Diesen Grund
            # dort zu nennen waere eine Falschaussage ueber den Abbruch.
            if not stagniert and self.RETRY_EXHAUSTED_REASON not in verdict.reasons:
                verdict.reasons.append(self.RETRY_EXHAUSTED_REASON)

        restored_partial_ids = restore_completion_cores(envelope)
        if restored_partial_ids:
            restored_partial_id_set = set(restored_partial_ids)
            verdict.rejected_claim_ids = [
                claim_id
                for claim_id in list(verdict.rejected_claim_ids or [])
                if claim_id not in restored_partial_id_set
            ]
            verdict.accepted_claim_ids = _dedupe_ordered_strs(
                list(verdict.accepted_claim_ids or [])
                + restored_partial_ids
            )
            unfulfilled_ids = _dedupe_ordered_strs(
                list(
                    getattr(
                        verdict,
                        "unfulfilled_response_requirement_ids",
                        [],
                    )
                    or []
                )
                + list(completion_slot_cores)
            )
            verdict.unfulfilled_response_requirement_ids = unfulfilled_ids
            verdict.fulfilled_response_requirement_ids = [
                requirement_id
                for requirement_id in list(
                    getattr(
                        verdict,
                        "fulfilled_response_requirement_ids",
                        [],
                    )
                    or []
                )
                if requirement_id not in set(unfulfilled_ids)
            ]
            envelope._unfulfilled_response_requirement_ids = list(
                unfulfilled_ids
            )
            verdict.verdict = "conservative_only"
            verdict.needs_retry = False
            reason = (
                "Ein faktisch und semantisch verifizierter Teilclaim bleibt "
                "sichtbar; der zugehörige Antwortslot ist jedoch noch nicht "
                "vollständig erfüllt."
            )
            if reason not in verdict.reasons:
                verdict.reasons.append(reason)

        # A non-pass verifier may omit an immutable claim that was explicitly
        # accepted on the previous attempt. Preserve that earlier decision when
        # the merged, runtime-validated claim remains present and was not
        # explicitly rejected on the final whole-envelope check.
        accepted_ids = set(verdict.accepted_claim_ids or [])
        rejected_ids = set(verdict.rejected_claim_ids or [])
        retained_signatures = set(retained_claims)
        incomplete_response_claim_ids = [
            str(getattr(claim, "id", "") or "").strip()
            for claim in list(envelope.claims or [])
            if str(getattr(claim, "id", "") or "").strip()
            and not bool(
                getattr(
                    claim,
                    "_verified_slot_core_missing_completion",
                    False,
                )
            )
            and (
                list(
                    getattr(
                        claim,
                        "_response_requirement_assignment_reasons",
                        [],
                    )
                    or []
                )
                or str(
                    getattr(
                        claim,
                        "_unfulfilled_response_requirement_id",
                        "",
                    )
                    or ""
                ).strip()
            )
        ]
        incomplete_response_claim_id_set = set(incomplete_response_claim_ids)
        verdict.accepted_claim_ids = [
            claim.id
            for claim in list(envelope.claims or [])
            if claim.id not in rejected_ids
            and claim.id not in incomplete_response_claim_id_set
            and _claim_signature(claim) not in blocked_claim_strengths
            and (
                claim.id in accepted_ids
                or _claim_signature(claim) in retained_signatures
            )
        ]
        blocked_final_ids = [
            claim.id
            for claim in list(envelope.claims or [])
            if _claim_signature(claim) in blocked_claim_strengths
        ]
        verdict.rejected_claim_ids = _dedupe_ordered_strs(
            list(verdict.rejected_claim_ids or [])
            + blocked_final_ids
            + incomplete_response_claim_ids
        )
        final_rejected_ids = set(verdict.rejected_claim_ids)
        verdict.accepted_claim_ids = [
            claim_id
            for claim_id in _dedupe_ordered_strs(
                list(verdict.accepted_claim_ids or [])
            )
            if claim_id not in final_rejected_ids
        ]
        blocked_claims_break_deliverable = bool(blocked_final_ids)
        if (
            blocked_final_ids
            and self._accepted_claims_complete is not None
        ):
            complete, _reason = self._accepted_claims_complete(
                envelope,
                verdict.accepted_claim_ids,
                verdict.rejected_claim_ids,
                observed_facts,
                contract,
            )
            blocked_claims_break_deliverable = not complete
        if (
            blocked_final_ids
            and verdict.verdict == "pass"
            and blocked_claims_break_deliverable
        ):
            verdict.verdict = "conservative_only"
            verdict.needs_retry = False
            reason = (
                "Ein inhaltlich unveränderter, zuvor verworfener Claim wurde "
                "nicht erneut zugelassen."
            )
            if reason not in verdict.reasons:
                verdict.reasons.append(reason)
        if projected_fact_citation_strip_count:
            envelope._projected_fact_citation_strip_count = (
                projected_fact_citation_strip_count
            )
        if self._relation_protocol_recovery_count:
            envelope._relation_protocol_recovery_count = (
                self._relation_protocol_recovery_count
            )
        if self._relation_schema_aliases:
            envelope._relation_schema_aliases = list(
                self._relation_schema_aliases
            )
        verdict._retrieval_candidate_assessments = list(
            retrieval_candidate_assessments
        )
        verdict._retrieval_audit_diagnostics = copy.deepcopy(
            self._retrieval_audit_diagnostics
        )
        return envelope, verdict
