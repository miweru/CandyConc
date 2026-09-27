"""Rezept-Daten der Analyse-Bibliothek (redigierbare DATEN, keine Logik).

Jeder Eintrag beschreibt EIN korpuslinguistisches Standardverfahren als
Daten-Dict. Die Dataclass-Definition, Validierung und das Rendering liegen in
``recipes.py``. Die Auswahl-Heuristik (``select_recipe``) liegt in
``grounding_contracts.py``.

Redaktionsregeln fuer diese Datei:

* ``trigger`` mischt drei Eintragsarten: ``family:<analysis_family>`` bindet
  das Rezept an eine Familie der bestehenden Kontrakt-Heuristik
  (``heuristic_analysis_contract``), ``wort:<lexem>`` matcht das Lexem nur
  an Wortgrenzen (H8: ``wort:stil`` trifft "Stil", nie "still"), alle
  anderen Eintraege sind Substring-Muster gegen die normalisierte
  (kleingeschriebene) Frage.
* Die Reihenfolge der Eintraege in ``RECIPES_DATA`` ist zugleich die
  Prioritaet des direkten Trigger-Scans (spezifisch vor breit).
  ``recipe_index()`` sortiert davon unabhaengig stabil nach ``id``.
* ``briefing`` ist der kompakte Verfahrenstext fuer die Turn-Injection
  (maximal 25 Zeilen). Platzhalter ``{slot_name}`` muessen in ``slots``
  deklariert sein.
* ``kern_tools``: das Rezept ist nur waehlbar, wenn mindestens eines dieser
  Werkzeuge verfuegbar ist (Capability-Gate, any-of). Der ERSTE Eintrag
  traegt zusaetzlich das schaerfere Kontrakt-Gate in
  ``grounding_contracts``. Beide Lesarten leben von derselben Liste, also
  gehoert hier nur hinein, was das Rezept fachlich traegt.
* ``wegbereiter_tools``: Werkzeuge, die der Turn braucht, um die
  Vorbedingung seines Riegels selbst herzustellen (etwa ``create_docset``
  fuer einen Kontrast, der zwei Docsets verlangt). Sie erweitern den
  Werkzeugraum, entscheiden aber NICHT ueber die Waehlbarkeit.
* ``vorplan`` (H10/G1): deterministische Schritt-1-Vorplanung als DATEN.
  Jeder Eintrag ist ``{"tool": name, "args": template}``. String-Werte, die
  exakt ``{TERM}``/``{TERM2}`` (Terme aus Anfuehrungszeichen der Frage) oder
  ``{DATE_FIELD}`` (erstes Datumsfeld der Korpus-Karte) sind, fuellt
  ``recipe_runtime.plan_recipe_first_round`` zur Laufzeit. Fehlt ein
  benoetigter Slot, gibt es KEINE Vorplanung (nie raten). Leer/fehlend =
  Runde 1 plant das Modell (heutiges Verhalten). Parameternamen exakt an
  ``tool_wrappers.py`` ausgerichtet.
* ``max_tool_runden``: weiche Runden-Leitplanke des Verfahrens. Beim
  Erreichen injiziert der Orchestrator die Wrap-up-Zeile und exponiert keine
  weiteren Tools fuer den Turn, die Antwort-Synthese laeuft normal weiter.
* ``leitplanken``: nur die 2 bis 4 Methoden-Fallstricke DIESES Verfahrens.
* Alle Werkzeug- und Feldnamen sind exakt an der realen Tool-API
  (``tool_wrappers.py``) ausgerichtet und bleiben es bei jeder Redaktion.
"""

from __future__ import annotations

from candyconc.i18n import lt

from typing import Any, Dict, Tuple

RECIPES_DATA: Tuple[Dict[str, Any], ...] = (
    {
        "id": "verlauf",
        "router_paraphrasen": ("zeitverlauf, diachron, entwicklung/anstieg/rueckgang ueber die zeit",),
        "name": "Zeitverlauf (Diachronie)",
        "einsatz": (
            "Wie entwickelt sich X ueber die Zeit "
            "(Raten pro Periode mit Unsicherheit)?"
        ),
        "trigger": (
            "family:trend_analysis",
            "über die zeit",
            "ueber die zeit",
            "zeitverlauf",
            "zeitreihe",
            "entwickelt sich",
            "entwicklung von",
            "diachron",
            "pro jahr",
            "trend",
        ),
        "kern_tools": ("trend_analysis",),
        # P5 (Runde 2): ein Trend auf einer TEILGESAMTHEIT (FDP-Raten je
        # Jahr, nicht Korpus-Raten) braucht Docsets als Wegbereiter. Ohne
        # sie wich der Turn diachronie-2 auf den Gesamtkorpus aus und
        # beantwortete die falsche Frage.
        "wegbereiter_tools": (
            "metadata_values",
            "create_docset",
            "list_docsets",
        ),
        # H10/G1: laeuft dieses Rezept (Vorbedingung date_field erfuellt),
        # traegt die Korpus-Karte mindestens ein Datumsfeld; {DATE_FIELD}
        # kommt deterministisch von dort, {TERM} aus den Anfuehrungszeichen.
        "vorplan": (
            {
                "tool": "trend_analysis",
                "args": {
                    "query": "{TERM}",
                    "date_field": "{DATE_FIELD}",
                    "granularity": "year",
                },
            },
        ),
        "max_tool_runden": 200,
        # Haertung r2, Fix 2: ohne Datumsfeld ist kein Zeitverlauf moeglich.
        # Kein Fallback -> deterministischer Kurzschluss vor dem ersten
        # LLM-Call (0 Tool-Runden), sobald die Korpus-Karte ihr Meta-Inventar
        # ausweist und darin kein Datumsfeld liegt.
        "precondition": {"requires": "date_field"},
        "precondition_unmet_text": (
            # Ohne das Praefix "Alternative:": der Fuellwert ist seit dem
            # Rezept-Rueckfall ein ganzer Satz, der die Lage selbst
            # benennt. Zusammen ergaben beide "Alternative: Eine
            # linguistische Ersatzachse gibt es hier nicht."
            lt("Dieser Korpus hat kein Datumsfeld, daher ist kein Zeitverlauf "
            "möglich. {alternative}", 'This corpus has no date field, so a time trend cannot be calculated. {alternative}')
        ),
        "precondition_alternative": lt("Frequenz nach Register/Quelle.", 'Frequency by register or source.'),
        "briefing": (
            "Verlaufsfrage zu {ausdruck}.\n"
            "Schritt 0: Weist die Korpus-Karte kein Datumsfeld aus "
            "(datums_felder: keine), sofort ehrlich antworten: ein Satz, "
            "dass dieses Korpus keinen Zeitverlauf hergibt, plus eine "
            "machbare Alternative (etwa Frequenz oder Kontrast ohne "
            "Zeitachse). Keine Werkzeug-Runden.\n"
            "Zuerst metadata_values(fields=['*']): welches Metadatenfeld "
            "traegt Datums- oder Jahreswerte? Dieses Feld als {date_field} "
            "verwenden.\n"
            "Dann trend_analysis(query={ausdruck}, date_field={date_field}, "
            "granularity={granularitaet}): liefert pro Periode documents, "
            "hits, tokens, per_million und ein Wilson-95%-CI "
            "(ci_low/ci_high).\n"
            "Interpretation ausschliesslich an per_million und den CIs "
            "ausrichten, Rohtreffer schwanken mit der Periodengroesse.\n"
            "Perioden ohne Dokumente fehlen bewusst (werden nie als 0 "
            "gefaked), Dokumente ohne parsbares Datum liegen im Bucket "
            "'undatiert', beides in der Antwort benennen.\n"
            "periods_total und truncated pruefen, falls die Serie fuer den "
            "Kontext gekappt wurde."
        ),
        "schritte": (
            {
                "ziel": "Datumsfeld verifizieren",
                "tool_hinweis": (
                    "metadata_values(fields=['*']) -> existierendes "
                    "Datums-/Jahresfeld waehlen"
                ),
                "slots": ("date_field",),
            },
            {
                "ziel": "Verlauf berechnen",
                "tool_hinweis": (
                    "trend_analysis(query={ausdruck}, "
                    "date_field={date_field}, "
                    "granularity={granularitaet}) -> periods[period, "
                    "per_million, ci_low, ci_high]"
                ),
                "slots": ("ausdruck", "granularitaet"),
            },
            {
                "ziel": "Befund absichern",
                "tool_hinweis": (
                    "Richtungsaussagen nur dort, wo sich die CIs der "
                    "verglichenen Stuetzstellen nicht ueberlappen"
                ),
                "slots": (),
            },
        ),
        "slots": {
            "ausdruck": (
                "Suchausdruck aus der Frage (Klartext oder cql:-Prefix)"
            ),
            "date_field": (
                "Metadatenfeld mit Datumswerten, vorab mit metadata_values "
                "verifizieren"
            ),
            "granularitaet": "'year' (Default) oder 'month'",
        },
        "abbruch_kriterium": (
            "Sobald die Richtungsaussage durch feinere Granularitaet oder "
            "weitere Perioden nicht mehr kippen kann, antworten. Ohne "
            "Datumsfeld ehrlich berichten, dass das Korpus keinen Verlauf "
            "hergibt, statt eines zu konstruieren."
        ),
        "deliverable": (
            "Kompakte Verlaufsdarstellung (period, per_million, CI), "
            "Trendaussage mit Unsicherheit, Hinweis auf undatierte Anteile."
        ),
        "leitplanken": (
            "Raten (per_million) statt Rohtreffer vergleichen, die "
            "Periodengroessen (tokens) variieren.",
            "Ueberlappende Konfidenzintervalle nicht als Anstieg oder "
            "Rueckgang verkaufen.",
            "Den Bucket 'undatiert' und ausgelassene Perioden explizit "
            "benennen.",
        ),
        "beispiel_frage": (
            "Wie entwickelt sich 'Inflation' über die Zeit im Korpus?"
        ),
    },
    {
        "id": "kontrast",
        "router_paraphrasen": ("unterschiede zwischen teilkorpora/gruppen, typisch fuer x gegenueber y, wird x anders dargestellt/behandelt als y, keyness, split-/partitions-qa (train vs test), mitgelieferte markerliste pruefen",),
        "name": "Kontrast und Keyness",
        "einsatz": (
            "Was ist typisch fuer A gegenueber B "
            "(gerichtete Keyness zwischen Teilmengen)?"
        ),
        "trigger": (
            "family:contrast_keyness",
            "typisch für",
            "typisch fuer",
            "keyness",
            "schlüsselwört",
            "schluesselwoert",
            "im vergleich zu",
            "im vergleich zum",
            "unterscheiden sich",
            "kontrastiere",
            # H8 (hold_kontrast_mensch_ki): "Vergleiche die Sprache von
            # Menschen und KI" lief in den freien Modus, weil nur die
            # "im vergleich zu"-Formen abgedeckt waren. Der Substring
            # "vergleich" deckt vergleiche/vergleichen/im Vergleich ab.
            "vergleich",
        ),
        # create_docset und list_docsets gehoeren HIERHER, nicht nur in den
        # Vorplan. Der Riegel keyness_before_two_live_docsets
        # (orchestrator.py) blockiert keyness, solange nicht ZWEI erfolgreich
        # erzeugte Docsets mit konkreten IDs vorliegen, und rät dem Modell
        # "Erzeuge zuerst beide Vergleichsscopes". Der Vorplan baut sie nur
        # unter einem engen Tor (_search_contrast_preplan_active: zwei
        # Anfuehrungs-Terme UND keine kontrastierbare Metadaten-Achse).
        # Faellt das Tor zu, stand im Werkzeugraum NUR keyness.
        #
        # Gemessen am 2026-08-31 ueber zwoelf Turns: 16 Anomalie-Eintraege
        # kind=keyness_before_two_live_docsets, ausnahmslos mit
        # exposed=keyness, je viermal in methodenkritik-1, methodenkritik-2
        # und kontrast-2. Das Modell versuchte es viermal je Turn und konnte
        # die Vorbedingung nicht erfuellen, weil das dafuer noetige Werkzeug
        # nicht angeboten war. Ein Riegel, dessen Vorbedingung im
        # angebotenen Raum unerreichbar ist, ist ein Deadlock und kein
        # Schutz. Der Kommentar an grounding_contracts.py:3249 sagt dasselbe
        # ueber Kontrakte: "schlimmer als gar keiner, er bindet den Turn an
        # etwas Unerreichbares."
        #
        # keyness bleibt ALLEINIGES kern_tools, daran haengt das
        # Capability-Gate in BEIDEN Lesarten (any-of und [0]). Die
        # Docset-Werkzeuge sind Wegbereiter, keine Kernwerkzeuge: sie
        # erweitern den Werkzeugraum, damit der Turn die Vorbedingung
        # seines Riegels (zwei Docsets) selbst herstellen kann, aber ein
        # Korpus, das nur create_docset kann und kein keyness, darf dieses
        # Rezept NICHT waehlbar machen.
        "kern_tools": ("keyness",),
        # The metadata tools establish the contrast's two live docsets:
        # metadata_values lists valid values, create_docset selects them, and
        # list_docsets reuses existing selections. Required metadata evidence lets
        # the contract enforce these prerequisites before keyness.
        #
        # run_cqlf_query supplies contextual counterexamples. query_count supports
        # term lists, phrases, CQL patterns and scopes absent from a keyness row.
        # For an existing keyness row, cite its supplied rate and denominator.
        #
        # ngram_contrast uses the same docsets without satisfying the required
        # metric_rows evidence. lexical_diversity would satisfy that requirement
        # and could replace the required keyness step, so it is excluded here.
        # Prerequisite tools expand the allowed tool set while keyness remains
        # the core capability required to select this recipe.
        "wegbereiter_tools": (
            "metadata_values",
            "create_docset",
            "list_docsets",
            "run_cqlf_query",
            "query_count",
            "ngram_contrast",
            # Methoden-Invariante 3 verlangt Dispersion fuer jede korpusweite
            # Frequenzaussage. Angeboten wurde dispersion_offsets nur ueber
            # die Stichwoerter "dispersion" und "verteilung" (grounding_contracts),
            # und in 9 von 11 Laeufen von deutung-verknuepfung-dispersion
            # nannte die Abgabe die Streuung "nicht mit verfuegbaren Werkzeugen
            # rechenbar" (Pruefer Ablauf, 2026-09-26).
            "dispersion_offsets",
        ),
        # H10/G3: Vorplanung des SUCHDEFINIERTEN Kontrasts — beide Seiten
        # entstehen als Docsets per Suche (create_docset(query=Term)). Das
        # Gate liegt in recipe_runtime (_search_contrast_preplan_active):
        # der Plan laeuft NUR bei zwei Anfuehrungs-Termen in einer
        # Vergleichskonstruktion UND ohne kontrastierbare Metadaten-Achse
        # in der Karte. Achsen-Kontraste und Split-QA behalten die
        # Modellplanung (heutiger Weg). Signatur exakt tool_wrappers.py:
        # create_docset(query=..., label=...) -> docset_id.
        "vorplan": (
            {
                "tool": "create_docset",
                "args": {"query": "{TERM}", "label": "{TERM}"},
            },
            {
                "tool": "create_docset",
                "args": {"query": "{TERM2}", "label": "{TERM2}"},
            },
        ),
        # H5, Fix 3: die Kette metadata_values -> create_docset(A) ->
        # create_docset(B) -> keyness sind VIER Tool-Runden, wenn das Modell
        # die beiden Docsets nicht buendelt. Bei nur 3 Runden verbraucht ein
        # entbuendelndes Modell alle Runden fuer Metadaten plus zwei Docsets,
        # und keyness (der eigentliche Keyword-Befund) wird nie exponiert. Vier
        # Runden geben keyness seine Runde; buendelt das Modell die Docsets, ist
        # zusaetzlich die KWIC-Gegenprobe drin.
        #
        # DAS WAR EIN BODEN, KEIN DECKEL, und als Deckel hat er geschadet.
        # Gemessen am 2026-09-01: DREI von fuenf Turns liefen genau diese
        # Kette und endeten danach an der Schranke. Der Aufbau der
        # Vergleichsbasis war die ganze Arbeit, die eigentliche Analyse
        # begann nie. Im stilmerkmale-Turn folgten nach der Keyness noch
        # vier create_docset-Aufrufe, der Beginn der registerkontrollierten
        # Gegenprobe, und genau dort griff sie.
        #
        # Die acht Referenzantworten in evaluation/deutung/referenzen.json
        # fuehren 8 bis 14 Experimente auf, Median 11. Ein Failsafe liegt
        # ueber der erwarteten Arbeit, nicht darauf.
        "max_tool_runden": 200,
        # Haertung r4, Fix 2: ein Metadaten-Kontrast braucht eine Achse mit
        # >=2 Werten (Dok-ID-Felder ausgeschlossen). Weist die Korpus-Karte
        # KEINE solche Achse aus, ist der Metadaten-Kontrast unmoeglich ->
        # deterministischer Kurzschluss (0 Calls, wie verlauf). Der
        # Kurzschluss-Text benennt die vorhandenen (nicht kontrastierbaren)
        # Achsen und den Docset-ueber-Suche-Ausweichpfad, wuergt die
        # Interpretation also nicht ab. Ist EINE kontrastierbare Achse da,
        # laeuft der normale Ablauf und das Briefing lenkt auf sie.
        "precondition": {"requires": "meta_axis"},
        "precondition_unmet_text": (
            lt("Dieser Korpus hat keine mehrwertige Metadaten-Achse fuer einen "
            "Kontrast. {alternative}", 'This corpus has no metadata axis with multiple values for a contrast. {alternative}')
        ),
        "precondition_alternative": (
            lt("Ein Kontrast ueber Suchanfragen-definierte Docsets ist moeglich, "
            "wenn du zwei Wortmengen oder Themen vorgibst.", 'A contrast can use document sets defined by queries for two specified word sets or topics.')
        ),
        "briefing": (
            "Kontrastfrage A gegen B entlang {achse_feld}.\n"
            "Schritt 0: Nimm als Kontrastachse ein Metadaten-Feld, das die "
            "Korpus-Karte unter kontrastierbare_achsen fuehrt (>=2 Werte). "
            "Felder mit nur einem Wert (z.B. model auf einem reinen "
            "Human-Korpus) oder Dokument-ID-Felder sind KEINE Achse. Nicht "
            "auf ihnen kontrastieren. Technische Felder (split/fold/batch: "
            "Datenaufteilung) sind KEINE linguistische Achse. Nur "
            "kontrastieren, wenn die Frage ausdrücklich die Aufteilung "
            "selbst untersucht. Fuehrt die Karte keine kontrastierbare "
            "Achse, beantwortet der Turn das bereits deterministisch.\n"
            "Zuerst metadata_values: existieren Feld und Werte {wert_a} und "
            "{wert_b} wirklich?\n"
            "Dann beide Seiten bauen: create_docset(filters=...) je Seite, "
            "die zurueckgegebenen docset_ids verwenden (nie rohe "
            "Metadatenwerte als docset_id).\n"
            "keyness(target_docset_id=A, reference_docset_id=B, min_freq=5) "
            "liefert je Wort target_per_million, reference_per_million, "
            "log_ratio mit CI (log_ratio_ci_low/log_ratio_ci_high), "
            "ll_signed, q_value und low_reliability.\n"
            "Effektstaerke berichten (log_ratio samt CI und beide Raten), "
            "Signifikanz allein ist kein Befund. Richtung (direction) "
            "explizit machen.\n"
            "Fuer 1-2 Top-Keywords eine KWIC-Gegenprobe im Ziel-Docset "
            "ziehen (run_cqlf_query mit docset_id) und pruefen, ob der "
            "Befund ueber mehrere Dokumente streut (file-Spalte) oder an "
            "einem Einzeltext haengt.\n"
            "run_cqlf_query gibt neben rows das Feld total: das ist die "
            "exakte Gesamtzahl, nie die Zeilenzahl der gedeckelten "
            "Vorschau. Kein zweiter Aufruf noetig. Ist truncated true, "
            "deckt die file-Spalte nur die Vorschau ab: die Dokumentzahl "
            "ist dann eine untere Schranke und genau so zu berichten, nie "
            "als 'streut ueber N Dokumente'.\n"
            "Die Rate zu einer Keyness-Zeile kommt aus keyness selbst "
            "(target_per_million, Nenner diagnostics.target_tokens). "
            # A count can add a new scope even when its word already appears
            # in a keyness row for another scope.
            "query_count nicht fuer die Rate einer Keyness-Zeile im selben "
            "Docset-Paar. Fuer alles ohne Keyness-Zeile zaehlt query_count: "
            "eine andere Abfrage, etwa eine Mehrwortverbindung, oder dasselbe "
            "Wort in einem Teil-Docset, etwa einem einzelnen Modell (fuer alle "
            "Werte eines Feldes in einem Aufruf: query_count(filters=..., "
            "nach=Feld), kein Teilkorpus je Wert). Beide Werkzeuge rechnen "
            "per_million auf demselben Nenner (denominator_tokens = word_count).\n"
            "Der Nennersatz oben spricht NICHT gegen den folgenden Modus: dort "
            "gibt es gar keine Keyness-Zeile, neben die eine query_count-Rate "
            "treten koennte.\n"
            "Termlisten-Modus: Nennt die Frage eine KANDIDATENLISTE (drei "
            "oder mehr zu prüfende Wörter oder Formeln), ist das keine "
            "keyness-Eingabe. keyness liest target als Tokenstrom, sieben "
            "Kandidaten wären sieben Tokens Gesamtmasse. Stattdessen je "
            "Kandidat query_count auf beiden Seiten (Docsets aus den "
            "Achsenwerten), je Seite den Nenner (word_count des Docsets) "
            "nennen und das Verhältnis als Rate pro Million berichten. "
            "Mehrwortformeln als Sequenz abfragen, nicht als ein Token.\n"
            "Kandidaten in der Keyness-Spitze suchen ist kein Befund: "
            "fehlt ein Wort in den sichtbaren Zeilen einer großen "
            "Keyness-Tabelle, folgt daraus nichts über dieses Wort. In "
            "diesem Fall sind Schritt 3 (gerichtete Keyness) und die "
            "Antwortform der gerichteten Keyword-Liste NICHT die Pflicht "
            "dieses Turns: die Antwortform ist eine Zeile je Kandidat mit "
            "beiden Zählungen, beiden Nennern und der Rate pro Million, "
            "und die Leitplanken zu log_ratio-CI und low_reliability "
            "gelten nur für Zeilen, die aus keyness stammen."
        ),
        "schritte": (
            {
                "ziel": "Kontrastachse verifizieren",
                "tool_hinweis": (
                    "metadata_values(fields=['*']) -> Feld {achse_feld} "
                    "mit Werten {wert_a} und {wert_b} belegen"
                ),
                "slots": ("achse_feld", "wert_a", "wert_b"),
            },
            {
                "ziel": "Beide Seiten als Docsets bauen",
                "tool_hinweis": (
                    "create_docset(filters={achse_feld: Wert}) je Seite -> "
                    "docset_id A und docset_id B"
                ),
                "slots": (),
            },
            {
                "ziel": "Gerichtete Keyness rechnen",
                "tool_hinweis": (
                    "keyness(target_docset_id=A, reference_docset_id=B, "
                    "min_freq={min_freq}) -> log_ratio+CI, q_value, "
                    "low_reliability"
                ),
                "slots": ("min_freq",),
            },
            {
                "ziel": "Streuungs-Gegenprobe plus Beleg",
                "tool_hinweis": (
                    # Hier stand sample=50, seed=1 mit der Begruendung, ohne
                    # sample kaemen die Zeilen in Indexreihenfolge. Das gilt
                    # seit 2690ead8d2 nicht mehr, und ein fester Seed fuer
                    # jede Abfrage zieht in jeder Trefferliste dieselben
                    # Quantile (analysis.vorgabe_seed).
                    "run_cqlf_query(top_keyword, docset_id=A, limit=50): "
                    "Streuung ueber file pruefen (ohne sample, seed und sort_by "
                    "zieht das Werkzeug selbst eine gemeldete Zufallsstichprobe "
                    "mit eigenem Seed je Abfrage, und fuehrt das Korpus "
                    "Fassungen, nennt die Zeile 'Zeilen nach ...', aus welchen "
                    "die gezogenen Zeilen stammen), 1 Beleg woertlich zitieren, "
                    "Gesamtzahl aus dem Feld total lesen, bei truncated=true "
                    "die Dokumentzahl als untere Schranke berichten. Rate "
                    "zur Keyness-Zeile aus keyness (target_per_million, "
                    "Nenner diagnostics.target_tokens). "
                    "query_count(abfrage, docset_id) fuer alles ohne Keyness-"
                    "Zeile, eine andere Abfrage oder dasselbe Wort in einem "
                    "Teil-Docset wie einem einzelnen Modell (alle Werte eines "
                    "Feldes in einem Aufruf: query_count(filters=..., nach=Feld)), "
                    "per_million auf demselben Nenner wie keyness (denominator_tokens = word_count)"
                ),
                "slots": (),
            },
        ),
        "slots": {
            "achse_feld": (
                "Metadatenfeld der Kontrastachse, muss in der Korpus-Karte "
                "unter kontrastierbare_achsen stehen (>=2 Werte)"
            ),
            "wert_a": "Wert der Zielseite A",
            "wert_b": "Wert der Referenzseite B",
            "min_freq": (
                "Reliabilitaets-Floor der Keyness, Default 5, nicht "
                "unterschreiten"
            ),
        },
        "abbruch_kriterium": (
            "Wenn die Top-Keywords nach Effektstaerke stabil sind und die "
            "Gegenprobe (Streuung plus Beleg) sie traegt, antworten. "
            "Kollabiert ein Keyword in der Gegenprobe auf ein "
            "Einzeldokument, genau das berichten statt weiterzurechnen."
        ),
        "deliverable": (
            "Gerichtete Keyword-Liste (word, log_ratio mit CI, per_million "
            "beidseitig), Streuungs-Anmerkung, 1 KWIC-Beleg, gekennzeichnete "
            "Deutung."
        ),
        "leitplanken": (
            "Effektstaerke zuerst: log_ratio mit CI und beide "
            "per_million-Raten, nie nur p- oder q-Werte.",
            "Zeilen mit low_reliability=true nicht als Befund verkaufen.",
            "Top-Keywords auf Dokument-Streuung pruefen, ein Einzeltext "
            "kann eine Keyness-Liste dominieren. In Social-Media-Korpora "
            "sind @-Handles und Nutzernamen Adressierungsartefakte: als "
            "Keyword nur berichten, wenn die Streuungs-Gegenprobe (mehrere "
            "Dokumente, file-Spalte) sie trägt, und nie allein als "
            "Registerbefund deuten.",
            "Richtung immer benennen: typisch fuer A relativ zu B, nicht "
            "'wichtig' absolut.",
        ),
        "beispiel_frage": (
            "Welche Schlüsselwörter sind typisch für das Teilkorpus 'news' "
            "im Vergleich zum Teilkorpus 'chat'?"
        ),
    },
    {
        "id": "profil",
        "router_paraphrasen": ("grammatisches profil, word sketch, syntaktische rollen und partner, relationen eines wortes",),
        "name": "Grammatisches Profil (Word Sketch)",
        "einsatz": (
            "Welche grammatischen Relationen und Partner praegen X "
            "(Word Sketch)?"
        ),
        "trigger": (
            "family:word_sketch_profile",
            "word sketch",
            "word-sketch",
            "wortprofil",
            "grammatisches profil",
            "grammatische relationen",
            "grammatischen relationen",
        ),
        "kern_tools": ("word_sketch",),
        # run_cqlf_query provides the contextual example required by step two.
        # collocate_stats provides the linear-window fallback when word_sketch
        # reports unavailable dependency features at runtime. Both expand the
        # allowed tool set while word_sketch remains the selection prerequisite.
        "wegbereiter_tools": ("run_cqlf_query", "collocate_stats"),
        "vorplan": ({"tool": "word_sketch", "args": {"term": "{TERM}"}},),
        "max_tool_runden": 200,
        "briefing": (
            "Word-Sketch-Frage zu {term}.\n"
            "word_sketch(term={term}) rechnet auf der Dependenz-Ebene "
            "(head/relation), nicht im Token-Fenster: tables gruppiert "
            "Kollokate je grammatischer Relation, relations traegt je "
            "Relation label, total_candidates, truncated und den "
            "angewandten min_freq-Floor (Default 3).\n"
            "Zeilen unterhalb des Floors sind unterdrueckt, nichts darunter "
            "berichten.\n"
            "Relationszeilen sind Dependenz-Ereignisse ohne "
            "Abdeckungs-Nenner: keine Aussage, eine Relation sei 'dominant' "
            "oder 'ueberwiegend'.\n"
            "Das Ranking je Relation kommt aus score und score_key, f ist "
            "die gemeinsame Frequenz.\n"
            "Fuer eine markante Relation einen KWIC-Anschauungsbeleg "
            "ziehen und woertlich zitieren. run_cqlf_query matcht lineare "
            "Nachbarschaft, keine Dependenzrelation: den KWIC-Beleg als "
            "Beispiel kennzeichnen, nie als Gegenprobe/Verifikation der "
            "Relation.\n"
            "Ist word_sketch unavailable (missing_corpus_features "
            "token_attributes.rel), kein grammatisches Profil behaupten: "
            "collocate_stats als ausdrücklich LINEARE Fensterkollokation "
            "anbieten und den Unterschied benennen (lineare Kookkurrenz "
            "ist keine Dependenzrelation)."
        ),
        "schritte": (
            {
                "ziel": "Profil berechnen",
                "tool_hinweis": (
                    "word_sketch(term={term}) -> relations + tables je "
                    "Relation (word, f, score, score_key)"
                ),
                "slots": ("term",),
            },
            {
                "ziel": "Anschauungsbeleg fuer eine markante Relation",
                "tool_hinweis": (
                    "run_cqlf_query mit Term und Partnerwort -> 1 "
                    "Belegzeile woertlich als Anschauungsbeleg (Beispiel, "
                    "keine Verifikation der Relation) uebernehmen"
                ),
                "slots": (),
            },
        ),
        "slots": {
            "term": "Zielwort aus der Frage",
        },
        "abbruch_kriterium": (
            "Wenn weitere Relationen nur noch Long-Tail nahe dem Floor "
            "zeigen, antworten."
        ),
        "deliverable": (
            "Profil nach Relationen: je Relation Top-Partner (word, f, "
            "score), Methodenzeile (min_freq-Floor, score_key), 1 Beleg."
        ),
        "leitplanken": (
            "Der ausgewiesene min_freq-Floor gilt, nichts unterhalb "
            "berichten.",
            "Ohne Abdeckungs-Nenner keine Dominanz-Aussagen ueber "
            "Relationen.",
            "Relationsnamen ueber label ausgeben und score_key benennen.",
            "Relationen im {{ev:...}}-Pfad über den rohen "
            "Relationsschlüssel referenzieren (tables.nk[0].word), Labels "
            "nur als Prosa.",
        ),
        "beispiel_frage": (
            "Erstelle ein Word Sketch für 'Haus': welche grammatischen "
            "Relationen prägen das Wort?"
        ),
    },
    {
        "id": "assoziation",
        "router_paraphrasen": ("kollokationen, typische wortumgebung, lexikalische gesellschaft/nachbarschaft, tritt gemeinsam auf mit",),
        "name": "Assoziation und Kollokation",
        "einsatz": (
            "Was tritt statistisch auffaellig mit X auf "
            "(Kollokate im Fenster)?"
        ),
        "trigger": (
            "family:collocation",
            "family:term_profile",
            "kollokat",
            "kollokation",
            "kookkurrenz",
            "tritt mit",
            "zusammen mit",
            "gemeinsam mit",
            "begleitwört",
            "begleitwoert",
            "steht neben",
            "stehen neben",
            "assoziation",
        ),
        "kern_tools": ("collocate_stats",),
        "wegbereiter_tools": ("query_count", "run_cqlf_query"),
        # H10/G1: Knotenfrequenz UND Kollokate in derselben vorgeplanten
        # Runde (der Live-Befund lief stattdessen auf frequency_list ohne
        # Term). min_freq=0 ist der auto-kalibrierte Floor (H6/B6).
        "vorplan": (
            {"tool": "query_count", "args": {"query": "{TERM}"}},
            {
                "tool": "collocate_stats",
                "args": {"term": "{TERM}", "window": 5, "min_freq": 0},
            },
        ),
        "max_tool_runden": 200,
        "briefing": (
            "Kollokationsfrage zu {term}.\n"
            "collocate_stats(term={term}, window={fenster}, "
            "sort_by={mass}, min_freq=0 (auto), attribute={attribut}) liefert "
            "Kollokate mit f (Token in der Vereinigung der Fenster, je Token "
            "einmal) "
            "und Assoziationsmassen.\n"
            "logdice ist das Default-Ranking (Rychly 2008, aus den Wort-"
            "frequenzen, meist unter 10, ein Punkt mehr heisst doppelt so "
            "haeufiges gemeinsames Vorkommen, eine Schwelle fuer bemerkenswerte "
            "Kollokationen gibt es nicht). mi ueberbewertet seltene Paare.\n"
            "Der Floor wird deterministisch an der Knotenfrequenz "
            "kalibriert (5 bei häufigen Knoten, bis 2 bei node_freq<50). "
            "Bei effektivem Floor <5: Ergebnisse als explorativ (n klein) "
            "kennzeichnen, nach f berichten, keine Signifikanzaussagen aus "
            "ll/chi2/t, jedes berichtete Kollokat mit KWIC-Beleg "
            "absichern.\n"
            "Fenster (Default 5, within_sentence=true) in der Antwort "
            "nennen, das Ergebnis haengt daran.\n"
            "attribute='lemma' nur waehlen, wenn das Korpus eine "
            "Lemma-Ebene traegt, sonst Oberflaechenformen ('word').\n"
            "Bleiben die rows leer oder duennt der Floor alles aus (kein "
            "Kollokat erreicht min_freq), ist genau das der Befund und "
            "linguistisch zu formulieren: kein Kollokat erreicht die "
            "Reliabilitaetsschwelle. Dazu die Knotenfrequenz mit "
            "query_count({term}) belegen und als Zahl berichten, denn "
            "collocate_stats selbst gibt sie nicht zurueck. Den Floor-Befund "
            "EINMAL formulieren (nicht je Schreibvariante wiederholen) und die "
            "Auswege nennen: ein haeufigeres Zielwort oder ein weiteres "
            "Fenster. Keine rohen Tool-Parameter "
            "(requested_term/term_mode/attribute) als Antwort ausgeben, keine "
            "Schreibvarianten, Fensterwechsel oder themenfremden "
            "Kontrollwoerter (etwa 'und') nachschieben.\n"
            "Fuer 1-2 Top-Kollokate eine KWIC-Gegenprobe ziehen und ein "
            "woertliches Belegzitat aufnehmen."
        ),
        "schritte": (
            {
                "ziel": "Kollokate berechnen",
                "tool_hinweis": (
                    "collocate_stats(term={term}, window={fenster}, "
                    "sort_by={mass}, min_freq=0 (auto), "
                    "attribute={attribut}) -> rows[word, f, logdice, ...]"
                ),
                "slots": ("term", "fenster", "mass", "attribut"),
            },
            {
                "ziel": "Gegenprobe im Kontext",
                "tool_hinweis": (
                    "run_cqlf_query mit Term und auffaelligem Kollokat "
                    "(etwa [word=\"...\"] []{0,3} [word=\"...\"]) -> "
                    "Belegzeilen"
                ),
                "slots": (),
            },
        ),
        "slots": {
            "term": "Zielwort aus der Frage",
            "fenster": "Kontextfenster in Tokens, Default 5",
            "mass": "Assoziationsmass, Default logdice",
            "attribut": (
                "'word' (Default) oder 'lemma', lemma nur bei vorhandener "
                "Lemma-Ebene"
            ),
        },
        "abbruch_kriterium": (
            "Wenn die Top-Kollokate unter einem zweiten Mass stabil "
            "bleiben, aendert ein weiterer Call die Antwort nicht mehr, "
            "dann antworten."
        ),
        "deliverable": (
            "Top-Kollokate als kompakte Liste (word, f, logdice), "
            "Methodenzeile (Fenster, Mass, Floor), 1 KWIC-Beleg, kurze "
            "gekennzeichnete Deutung."
        ),
        "leitplanken": (
            "logdice als Default berichten, mi-Ranglisten nie ohne "
            "Frequenz-Floor interpretieren.",
            "Den automatisch kalibrierten Floor nicht manuell "
            "unterlaufen, f=1-Paare nie berichten.",
            "Fenstergroesse und within_sentence in der Antwort nennen.",
            "Assoziation ist keine Bedeutung: Deutungen als Deutung "
            "kennzeichnen und an einen Beleg binden.",
        ),
        "beispiel_frage": "Welche Kollokationen hat 'Arbeit' im Korpus?",
    },
    {
        "id": "metadaten_struktur",
        "router_paraphrasen": ("metadatenfelder und werte, herkunft/quelle, lizenz, aufbau/aufteilung des BESTANDS ohne suchbegriff, wie verteilen sich dokumente/reden ueber ein metadatenfeld, groesse der teilkorpora, grundlage fuer stichprobenbildung",),
        "name": "Korpus-Karte (Metadaten und Struktur)",
        "einsatz": (
            "Was ist im Korpus: Metadatenfelder, Werte, Teilmengen, "
            "ehrliche Grenzen?"
        ),
        "trigger": (
            "family:metadata_capability",
            "welche metadaten",
            "metadatenfeld",
            "metadatenfelder",
            "welche register",
            "welche quellen",
            "was ist im korpus",
            "was enthält das korpus",
            "was enthaelt das korpus",
            "aufbau des korpus",
            "struktur des korpus",
            "zusammensetzung des korpus",
        ),
        "kern_tools": ("metadata_values",),
        # H10/G1: das Inventar braucht keinen Frage-Slot; Runde 1 ist immer
        # metadata_values(fields=['*']) statt einer geratenen Wortsuche.
        "vorplan": ({"tool": "metadata_values", "args": {"fields": ["*"]}},),
        "max_tool_runden": 200,
        "briefing": (
            "Strukturfrage zum Korpus.\n"
            "metadata_values(fields=['*']) inventarisiert alle "
            "Dokument-Metadatenfelder (available_fields) mit ihren Werten "
            "(values), optional mit filters eingrenzen.\n"
            "Wichtige Grenze: das sind NUR Dokument-Metadaten. Token-Ebenen "
            "(word, lemma, pos, Morphologie, Dependenz) sind hier "
            "unsichtbar und gehoeren zu Query- und Frequenz-Werkzeugen.\n"
            "Groessenverhaeltnisse belegen ueber query_count "
            "(corpus_tokens, bei docset_id auch denominator_tokens) oder "
            "frequency_list, gruppiert ueber ein Attribut, das die "
            "Korpus-Karte unter attribute fuehrt.\n"
            "Teilmengen entstehen ueber create_docset oder "
            "resolve_subcorpus, rohe Metadatenwerte sind keine "
            "docset_ids.\n"
            "Fehlende Felder stehen in "
            "diagnostics.missing_requested_fields und werden als fehlend "
            "berichtet, Capability-Grenzen ehrlich benennen statt Werte zu "
            "erfinden."
        ),
        "schritte": (
            {
                "ziel": "Inventar ziehen",
                "tool_hinweis": (
                    "metadata_values(fields=['*']) -> available_fields "
                    "plus values je Feld"
                ),
                "slots": (),
            },
            {
                "ziel": "Groessen belegen",
                "tool_hinweis": (
                    "query_count(query=..., docset_id=...) oder "
                    "frequency_list(group_by=<Attribut aus der Karte>) "
                    "fuer Anteile"
                ),
                "slots": (),
            },
            {
                "ziel": "Fokusfeld vertiefen",
                "tool_hinweis": (
                    "metadata_values(fields=['{fokus_feld}'], "
                    "filters=...) fuer Detailfragen"
                ),
                "slots": ("fokus_feld",),
            },
        ),
        "slots": {
            "fokus_feld": (
                "Optionales Feld, auf das die Frage zielt (etwa register), "
                "leer bei reiner Inventarfrage"
            ),
        },
        "abbruch_kriterium": (
            "Wenn das Inventar die Frage abdeckt, keine weiteren "
            "Zoom-Calls, antworten."
        ),
        "deliverable": (
            "Korpus-Karte: Felder mit Beispielwerten, Groessenangaben mit "
            "Quelle, explizite Capability-Grenzen."
        ),
        "leitplanken": (
            "metadata_values zeigt Dokument-Metadaten, keine "
            "Token-Attribute, diese Grenze in der Antwort ziehen.",
            "Fehlende angefragte Felder aus "
            "diagnostics.missing_requested_fields berichten, nie erraten.",
            "Rohe Metadatenwerte nie als docset_id verwenden, Teilmengen "
            "ueber create_docset oder resolve_subcorpus.",
        ),
        "beispiel_frage": (
            "Welche Metadatenfelder und Register enthält das Korpus?"
        ),
    },
    {
        "id": "frequenz",
        # A4, 2026-08-23: beide Rezepte beanspruchten "Verteilung", und der
        # Klassifikator schickte "Wie verteilen sich die Reden ueber die
        # Wahlperioden?" hierher, obwohl die Frage gar keinen Suchbegriff
        # traegt. Entscheidend ist, WORUEBER verteilt wird: ein Suchbegriff
        # oder der Bestand selbst.
        "router_paraphrasen": ("wie oft/haeufig kommt EIN SUCHBEGRIFF vor, belegzahl, vorkommenszahl, haeufigkeit eines wortes normiert pro million woerter (pmw), verteilung EINES TERMS ueber teilkorpora",),
        "name": "Frequenz und Verteilung",
        "einsatz": (
            "Wie oft kommt X vor und wie ist es verteilt (absolut, pro "
            "Million, im Vergleich)?"
        ),
        "trigger": (
            "family:term_frequency",
            "family:ngram_profile",
            "wie oft",
            "wie häufig",
            "wie haeufig",
            "frequenz",
            "häufigkeit",
            "haeufigkeit",
            "trefferzahl",
            "pro million",
            "vorkommen",
            "verteilt",
            "verteilung",
            "dispersion",
        ),
        "kern_tools": ("query_count", "frequency_list", "dispersion_offsets"),
        # H10/G1: die Frequenzfrage zu einem Term beginnt IMMER mit der
        # exakten Zaehlung dieses Terms (der Live-Befund rief stattdessen
        # die allgemeine frequency_list ohne Term-Slot).
        # P2.4: Methoden-Invariante 3 verlangt, dass ein Frequenzbefund
        # ohne Dispersion nicht als korpusweit gilt. Die Norm war faktisch
        # abgeschaltet, weil dispersion_offsets nur als Prosa-Option im
        # Briefing stand und an DREI Filtern scheiterte: Werkzeugraum,
        # Kontrakt-Bundle und Vorplan-Filter. P2.3 rendert die Kennwerte
        # bereits, wenn sie da sind, hier wird ihre Beschaffung erzwungen.
        "vorplan": (
            {"tool": "query_count", "args": {"query": "{TERM}"}},
            {"tool": "dispersion_offsets", "args": {"term": "{TERM}"}},
        ),
        "max_tool_runden": 200,
        "briefing": (
            "Frequenzfrage zu {term}.\n"
            "Zuerst query_count(query={term}, ggf. docset_id): liefert "
            "total (exakte Trefferzahl), per_million (vorgerechnete Rate) "
            "und denominator_tokens (Bezugsgroesse).\n"
            "Bei Subkorpus-Bezug docset_id setzen, der Nenner wechselt "
            "dann auf das Docset (denominator_scope dokumentiert das).\n"
            "Fuer Ranglisten frequency_list nutzen (group_by word|lemma|"
            "pos, pos-Filter gegen Funktionswort-Dominanz, limit maximal "
            "100).\n"
            "Fuer Verteilungsfragen dispersion_offsets({term}) ergaenzen "
            "(dp, juilland_d, range, coverage_ratio).\n"
            "Jeder Zahlenvergleich zwischen unterschiedlich grossen Scopes "
            "laeuft ueber per_million, nie ueber Rohzahlen."
        ),
        "schritte": (
            {
                "ziel": "Exakte Trefferzahl und Rate bestimmen",
                "tool_hinweis": (
                    "query_count(query={term}, ggf. docset_id) -> total, "
                    "per_million, denominator_tokens"
                ),
                "slots": ("term",),
            },
            {
                "ziel": "Bei Vergleichsbedarf zweite Messung im "
                "Vergleichs-Scope",
                "tool_hinweis": (
                    "create_docset(filters=...) -> docset_id, dann "
                    "query_count mit docset_id, Raten vergleichen"
                ),
                "slots": ("vergleichs_scope",),
            },
            {
                "ziel": "Optional Rangkontext oder Verteilung",
                "tool_hinweis": (
                    "frequency_list(pos=..., limit<=100) oder "
                    "dispersion_offsets({term})"
                ),
                "slots": (),
            },
        ),
        "slots": {
            "term": "Wort, Wortfolge oder CQLF-Ausdruck aus der Frage",
            "vergleichs_scope": (
                "Optionales Vergleichs-Subkorpus (Metadatenfilter), leer "
                "wenn keiner erfragt ist"
            ),
        },
        "abbruch_kriterium": (
            "Sobald weitere Messungen Groessenordnung und Rangfolge der "
            "Antwort nicht mehr aendern wuerden, antworten. Bei total=0 "
            "sofort ehrlich Null berichten statt Query-Varianten zu raten."
        ),
        "deliverable": (
            "Zahlenantwort: total, per_million mit Nenner, bei Vergleich "
            "beide Raten nebeneinander, 1-2 Saetze Einordnung."
        ),
        "leitplanken": (
            # Show raw counts with normalized rates so the comparison is auditable.
            # Use per_million with its denominator as the basis for scope comparisons.
            "Vergleiche zwischen Scopes IMMER ueber per_million mit "
            "genanntem Nenner (denominator_tokens). Die Rohzahl total "
            "gehoert in dieselbe Antwort, nur nie als Vergleichsbasis.",
            "Die Laenge von rows ist nie eine Trefferzahl, nur total "
            "zaehlt (truncated beachten).",
            "frequency_list ohne pos-Filter wird von Funktionswoertern "
            "dominiert, fuer Inhaltswoerter pos setzen.",
        ),
        "beispiel_frage": (
            "Wie häufig kommt 'Klimawandel' im Korpus vor, pro Million "
            "Tokens?"
        ),
    },
    {
        "id": "gebrauch_kwic",
        "router_paraphrasen": ("verwendung/gebrauch, lesarten, kommunikative funktionen, konkordanz/kwic, textstellen als beleg, konstruktion aus mehreren token (abfolge, abstand)",),
        "name": "Gebrauch im Kontext (KWIC)",
        "einsatz": (
            "Wie wird X verwendet? Kontextmuster an KWIC-Belegen zeigen "
            "und woertlich belegen."
        ),
        # P5: die Konstruktions-Cues stehen NICHT hier, sondern in
        # ``frageform.KONSTRUKTIONS_FORM_CUES``, und ``select_recipe``
        # gibt ihnen Vorrang vor der Familienheuristik, sofern die Frage
        # zusaetzlich Belege verlangt
        # (``frageform.ist_konstruktions_suchauftrag``). Grund fuer den
        # eigenen Ort ist die Substring-Falle: die Eintraege dieser Liste
        # matchen roh, also faenge "korrelat" auch "Korrelation" und
        # "konstruktion" auch "Rekonstruktion". Die Cue-Pruefung in
        # ``frageform`` haelt Wortgrenzen und laesst nur deutsche
        # Flexionsendungen zu.
        "trigger": (
            "family:kwic_context",
            "family:document_lookup",
            "wie wird",
            "verwendet",
            "verwendung",
            "gebrauch",
            "kwic",
            "konkordanz",
            "kontext",
            "beleg",
            "stichprobe",
        ),
        # Keep a single core tool. Recipe availability accepts any core tool,
        # so adding query_count here would select a concordance recipe even when
        # run_cqlf_query is unavailable and its contract cannot be created.
        "kern_tools": ("run_cqlf_query",),
        # Prerequisite tools expand the turn and contract tool sets without
        # making this recipe selectable. query_count adds counts for scoped
        # queries. Metadata values, docset creation and docset reuse establish
        # the groups needed for those comparisons.
        "wegbereiter_tools": (
            "query_count",
            "create_docset",
            "metadata_values",
            "list_docsets",
        ),
        # H10/G1: die eine gebuendelte Runde wird vorgeplant, damit sie den
        # Term-Slot sicher traegt und keine LLM-Planungsrunde kostet.
        "vorplan": (
            {"tool": "run_cqlf_query", "args": {"query": "{TERM}", "limit": 50}},
        ),
        # Allow follow-up rounds so the model can inspect concordance results
        # and refine a construction query after its first tool calls.
        "max_tool_runden": 200,
        # NACHGEBESSERT am 2026-09-03: Schritt 2 und 3 sind BEDINGT. Das
        # Rezept bedient weiter die einfache Gebrauchsfrage, und die ist
        # seine eigene beispiel_frage: select_recipe("Wie wird
        # 'nachhaltig' verwendet? Zeig KWIC-Belege im Kontext.") liefert
        # gemessen gebrauch_kwic. Unbedingt gebrieft bekam sie eine
        # Seiten-Normierung und einen Fenster-Sweep vorgeschrieben,
        # obwohl sie weder Seite noch Fenster kennt. Das ist Arbeit, die
        # zum Ergebnis nichts beitragen kann (CLAUDE.md, Zeitlimits
        # Punkt 5).
        #
        # P6: das Briefing brieft ein VERFAHREN, keinen Einzelabruf.
        # Es zaehlt 21 der 25 erlaubten Zeilen. Gegenfinanziert ist es an
        # zwei Stellen: die Aufzaehlung der sort_by-Varianten ist raus (sie
        # kam in keiner der zehn gemessenen Antworten vor), und die
        # Belegvorgabe steht nur noch einmal, im Briefing, statt zusaetzlich
        # im Schritt-Hinweis.
        "briefing": (
            "Gebrauchs- und Konstruktionsfrage zu {ausdruck}.\n"
            "Buendle, was zusammen geht, in eine Runde. Wirft ein Ergebnis eine Frage auf, fasse nach statt zu raten.\n"
            # Represent the construction as a CQL sequence with a quantifier.
            # Use %c on its first member to include sentence-initial capitalization.
            "Formuliere die Kette als CQL: jedes Glied ein Token, der\n"
            "Abstand dazwischen ein Quantor, etwa [word=\"nicht\" %c]\n"
            "[word=\"nur\"] []{0,8} [word=\"sondern\"] [word=\"auch\"].\n"
            "{fenster} ist die Weite des Quantors.\n"
            # SATZGRENZE. Sequenzen sind satzintern als Vorgabe. Wer
            # das nicht weiss, liest aus einer Null heraus, die
            # Konstruktion komme nicht vor. Gemessen am 2026-09-01:
            # die Fachagentin der Referenzantwort zu
            # konstr-scharnier-dreigliedrig hielt es fuer unmoeglich
            # und wich auf Positionsrechnung aus, es ging um Faktor
            # drei (12 gegen 38 Belege). Die Beispielsyntax im Kern
            # zeigt within(<doc>, x), sagt aber nicht, wozu.
            "Bei einer Kette: Sequenzen bleiben im Satz. Zaehle mit query_count ZWEIMAL,\n"
            "einmal satzintern und einmal in within(<doc>, ...), und nenne beide Zahlen. Ohne\n"
            "within findest du nur, was in EINEM Satz steht.\n"
            "NUR wenn die Frage nach Seiten fragt, je Seite von {achse}: metadata_values gibt\n"
            "die Werte, create_docset(filters=...) das Teilkorpus, query_count(query,\n"
            "docset_id) Treffer UND Nenner, daraus die Rate pro Million. Rohtreffer sind bei\n"
            "ungleich grossen Teilkorpora kein Vergleich.\n"
            # FENSTER-SWEEP. Referenzantwort, vier Weiten voll gefahren:
            # 0-4 -> 30.091, 0-8 -> 45.599, 0-12 -> 47.644. Die vier Token
            # von 8 auf 12 bringen 2.045 dazu, die vier von 4 auf 8 aber
            # 15.508. Wer eine Weite hochrechnet statt sie zu fahren, liegt
            # um ein Vielfaches daneben.
            "NUR bei offener Fensterweite: fahre den Sweep mit zwei bis drei Weiten wirklich.\n"
            "Der Matcher nimmt je Startposition den linkesten laengsten Treffer, eine weitere\n"
            "Weite bringt deshalb weniger dazu als die Differenz vermuten laesst. Nie hochrechnen.\n"
            # Hier stand "ab mehr als {stichprobe_ab} Treffern mit sample={stichprobe_n}
            # und festem seed={seed}" (Vorgabe 200, 25, 42). Derselbe Seed fuer jede
            # Abfrage zieht in jeder Trefferliste dieselben Quantile
            # (analysis.vorgabe_seed), wie seed=1 im Rezept kontrast bis a8d617229f.
            "run_cqlf_query(query={ausdruck}, limit=50) liefert die KWIC-Zeilen (left, kw,\n"
            "right, file, pos), bei mehr als 50 Treffern als gemeldete Stichprobe mit\n"
            "eigenem Seed je Abfrage.\n"
            "Dann antworten: zuerst die Deutung, danach die Zahlen mit Nenner und mindestens\n"
            "3 woertliche Belege auf rows[i] samt Fundstelle (file, pos)."
        ),
        "schritte": (
            {
                "ziel": "Kette als CQL mit Quantor formulieren und "
                "satzintern wie in within(<doc>) zaehlen",
                "tool_hinweis": (
                    "query_count(query={ausdruck}) und query_count(query="
                    "within(<doc>, {ausdruck})) -> beide total behalten"
                ),
                "slots": ("ausdruck",),
            },
            {
                "ziel": "Nur bei einer Frage nach Seiten: je Seite von "
                "{achse} normalisieren",
                "tool_hinweis": (
                    "metadata_values(fields=[{achse}]) -> create_docset("
                    "filters) -> query_count(query, docset_id) -> Rate pro "
                    "Million mit denominator_tokens"
                ),
                "slots": ("achse",),
            },
            {
                "ziel": "Nur bei offener Fensterweite: Sweep ueber zwei "
                "bis drei Weiten",
                "tool_hinweis": (
                    "query_count mit dem Quantor um {fenster} herum "
                    "variiert, jede Weite wirklich gefahren"
                ),
                "slots": ("fenster",),
            },
            {
                "ziel": "KWIC-Stichprobe fuer die Belege",
                "tool_hinweis": (
                    "run_cqlf_query(query={ausdruck}, limit=50), ohne "
                    "sample und seed: ueber 50 Treffern zieht das Werkzeug "
                    "die Stichprobe selbst und meldet ihren Seed"
                ),
                "slots": ("ausdruck",),
            },
            {
                "ziel": "Deutung, dann Zahlen und Belege",
                "tool_hinweis": (
                    "kein Werkzeug: Deutung zuerst, danach beide "
                    "Trefferzahlen, die Raten mit Nenner und mindestens 3 "
                    "woertliche Belege aus rows"
                ),
                "slots": (),
            },
        ),
        "slots": {
            "ausdruck": (
                "Wort, Phrase oder CQLF-Ausdruck aus der Frage"
            ),
            "achse": (
                "Metadatenfeld fuer die Seiten-Normierung aus der "
                "Korpus-Karte, z. B. model oder register"
            ),
            "fenster": (
                "Weite des Abstands-Quantors in Token, Default 8"
            ),
        },
        "abbruch_kriterium": (
            "Saettigung: sobald zusaetzliche KWIC-Zeilen kein neues "
            "Gebrauchsmuster mehr zeigen, antworten. Kein Muster "
            "erzwingen, wenige heterogene Treffer sind ein ehrlicher "
            "Befund."
        ),
        "deliverable": (
            "Zuerst die Deutung: was der Ausdruck im Gebrauch tut und, "
            "wenn nach Seiten gefragt war, worin sie sich unterscheiden. "
            "Danach die Trefferzahlen (bei einer Kette satzintern UND in "
            "within(<doc>)), jede Rate mit ihrem Nenner, ein gefahrener "
            "Fenster-Sweep falls die Weite offen war, und mindestens 3 "
            "woertliche KWIC-Belege mit Fundstelle (file, pos) samt "
            "Stichproben-Provenienz."
        ),
        "leitplanken": (
            "rows ist gekappt (limit), nur total ist die Trefferzahl, "
            "truncated offenlegen.",
            # Interpret construction choice and construction completion separately.
            # Their counts provide distinct evidence about how a construction is used.
            "Die Deutung ist Lieferbestandteil und steht als erstes: was "
            "die Zahlen fachlich bedeuten, welcher Faktor woran haengt, "
            "was sie NICHT hergeben. Eine Antwort aus Tabellen ohne "
            "Deutung ist unvollstaendig.",
            # H8/F1 (R7b-Befund kwic_zeit): Tool-Parameter als Fliesstext
            # ('requested 25, drawn 25, seed 42') lasen sich wie ein
            # Prompt-Leak. Provenienz bleibt Pflicht, aber lesbar und am
            # richtigen Ort. Mit P6 traegt derselbe Eintrag auch die
            # Reichweite der Stichprobe (Leitplanken-Budget ist 2-4, und
            # die Deutungszeile brauchte den Platz).
            "Ohne sample und seed zieht das Werkzeug die Stichprobe "
            "selbst, mit einem gemeldeten Seed je Abfrage. Die "
            "Stichproben-Provenienz gehoert in die Grenzen-Sektion in "
            "EINEM lesbaren Satz (z. B. Zufallsstichprobe von 25 der 32 "
            "Treffer, fester Seed). Rohe Parameternamen (requested, "
            "drawn, seed) nicht in den Fliesstext. Muster aus einer "
            "Stichprobe sind Beobachtungen an der Stichprobe, nicht am "
            "Korpus.",
            "Belege woertlich aus den Zeilen zitieren (left, kw, right), "
            "nie Paraphrase als Zitat ausgeben.",
        ),
        "beispiel_frage": (
            "Wie wird 'nachhaltig' verwendet? Zeig KWIC-Belege im Kontext."
        ),
    },
    {
        "id": "exploration_meta",
        "router_paraphrasen": ("offene erkundung, auffaelligkeiten/eigenheiten, hypothesen entwickeln, korpus charakterisieren",),
        "name": "Offene Exploration",
        "einsatz": (
            "Offene Forschungsfrage: Ueberblick, Zoom, Gegenprobe, "
            "Deutung ausdruecklich erwuenscht."
        ),
        "trigger": (
            "family:open_research",
            "family:semantic_retrieval",
            "was fällt auf",
            "was faellt auf",
            "was fällt",
            "was faellt",
            "auffällig",
            "auffaellig",
            "erkunde",
            "explorier",
            "untersuche",
            "überblick",
            "ueberblick",
            "welche themen",
            "worum geht",
            "interessant",
            "hypothese",
            # H8 (hold_offen_stil): "Charakterisiere den Sprachstil dieses
            # Korpus" lief in den freien Modus. "wort:stil" matcht nur an
            # Wortgrenzen (nie in "still"), "sprachstil" und
            # "charakterisier" sind als Substrings eindeutig genug.
            "charakterisier",
            "sprachstil",
            "wort:stil",
        ),
        "kern_tools": (
            "frequency_list",
            "metadata_values",
            "run_cqlf_query",
            "semantic_search",
        ),
        # The follow-up step requires collocate_stats, run_cqlf_query and keyness.
        # create_docset and list_docsets establish the live comparison scopes.
        # These prerequisite tools expand the allowed set without making the
        # recipe selectable. open_research obtains them through _mit_rezeptraum
        # because it has no contract template of its own.
        "wegbereiter_tools": (
            "collocate_stats",
            "keyness",
            "create_docset",
            "list_docsets",
            "dispersion_offsets",
        ),
        # Collect metadata structure and a POS distribution before model planning.
        # The runtime corpus card decides whether the POS step can run. A constant
        # placeholder attribute provides no distribution and is omitted.
        "vorplan": (
            {"tool": "metadata_values", "args": {"fields": ["*"]}},
            {"tool": "frequency_list", "args": {"group_by": "pos"}},
        ),
        "max_tool_runden": 200,
        # H9/C2 (V5): frueherer Antwort-Schalter. Beide offenen Explorationen
        # des zweiten Verdikts endeten im Server-Backstop-Salvage (calls=None,
        # 135s): die Modell-Synthese kam nie. Ab 40% des Zeitbudgets schaltet
        # der Turn auf die Antwort-Landung, damit die Synthese VOR dem
        # Backstop laeuft. Andere Rezepte behalten den Default 0.55.
        "answer_switch_fraction": 0.4,
        "briefing": (
            "Offene Explorationsfrage (Fokus: {fokus}).\n"
            "Dreischritt Ueberblick -> Zoom -> Gegenprobe.\n"
            "Werkzeugwahl richtet sich nach der Korpus-Karte: semantic_search "
            "ist nur nutzbar, wenn capabilities: embeddings=true steht (sonst "
            "steht es gar nicht im Werkzeugraum). Ohne Embeddings die "
            "thematische Struktur ueber die ZAEHLENDEN Werkzeuge "
            "triangulieren: frequency_list(pos='NOUN'/'VERB') fuer das "
            "Inhaltsvokabular, metadata_values fuer die Struktur, "
            "collocate_stats fuer Assoziationen und run_cqlf_query fuer KWIC-"
            "Belege. Mit Embeddings semantic_search NUR zur Kandidatenfindung "
            "nutzen, nie als Befundquelle: ein rohes Nachbarpaar aus "
            "semantic_search (etwa 'wort / nachbar') ist KEIN Thema. Jedes im "
            "Bericht genannte Thema muss ein zaehlendes Werkzeug "
            "(frequency_list, collocate_stats oder metadata_values) "
            "quantitativ bestaetigen, und die Zahl steht als Beleg dabei. Ein "
            "semantischer Kandidat ohne solche Zahl wird nicht als Befund "
            "ausgegeben, hoechstens als 'Kandidat, nicht quantifiziert' "
            "vermerkt.\n"
            "1. Ueberblick: metadata_values(fields=['*']) fuer die "
            "Korpusstruktur plus frequency_list(pos='NOUN' oder 'VERB') "
            "fuer das inhaltliche Vokabular.\n"
            "2. Zoom: der auffaelligsten Spur folgen, je nach Form mit "
            "collocate_stats (Assoziationen), run_cqlf_query (Kontexte), "
            "keyness (Teilmengen-Kontrast) oder, falls embeddings=true, "
            "semantic_search (thematische Passagen, danach zaehlend "
            "bestaetigen).\n"
            "3. Gegenprobe: die zentrale Beobachtung mit einer "
            "unabhaengigen zweiten Evidenzart pruefen, etwa einen "
            "Frequenzbefund mit KWIC-Belegen.\n"
            "Interpretation und Hypothesen sind ausdruecklich erwuenscht: "
            "als Deutung kennzeichnen, an konkrete Zahlen und Belege "
            "binden und den Geltungsbereich (Scope, Stichprobe) nennen.\n"
            "Negativbefunde sind Befunde."
        ),
        "schritte": (
            {
                "ziel": "Ueberblick gewinnen",
                "tool_hinweis": (
                    "metadata_values(fields=['*']) plus "
                    "frequency_list(pos='NOUN') -> Struktur- und "
                    "Vokabular-Landkarte"
                ),
                "slots": (),
            },
            {
                "ziel": "Der auffaelligsten Spur nachgehen",
                "tool_hinweis": (
                    "je nach Spur collocate_stats, run_cqlf_query, keyness "
                    "oder (nur bei embeddings=true) semantic_search"
                ),
                "slots": ("fokus",),
            },
            {
                "ziel": "Gegenprobe mit zweiter Evidenzart",
                "tool_hinweis": (
                    "zentrale Beobachtung unabhaengig pruefen (etwa "
                    "Frequenzbefund -> KWIC-Belege)"
                ),
                "slots": (),
            },
            {
                "ziel": "Deutung, Hypothesen und Anschlussfragen formulieren",
                "tool_hinweis": (
                    "Beobachtung, gekennzeichnete Deutung und 2-3 "
                    "Anschlussfragen sauber trennen. Fragt die Frage nach "
                    "Hypothesen: 2-3 Sprachhypothesen als eigene Punkte, je "
                    "prüfbarer Satz + stützender Zahlen-/KWIC-Beleg + was "
                    "sie widerlegen würde"
                ),
                "slots": (),
            },
        ),
        "slots": {
            "fokus": (
                "Optionaler inhaltlicher Fokus aus der Frage, sonst frei "
                "waehlen und die Wahl begruenden"
            ),
        },
        "abbruch_kriterium": (
            "Aendert-es-die-Antwort-Test: sobald weitere Calls die "
            "Kernaussagen nicht mehr aendern wuerden, antworten. Breite "
            "vor Tiefe nur, solange sie neue Beobachtungen liefert."
        ),
        "deliverable": (
            "Explorationsbericht: 2-4 Beobachtungen mit Zahlen und "
            "Belegen, gekennzeichnete Deutungen, 2-3 Anschlussfragen. "
            "Fragt die Frage nach Hypothesen: 2-3 Sprachhypothesen als "
            "eigene Punkte, je prüfbarer Satz + stützender "
            "Zahlen-/KWIC-Beleg + was sie widerlegen würde."
        ),
        "leitplanken": (
            "Deutungen und Hypothesen sind erwuenscht, aber als Deutung "
            "gekennzeichnet und an Zahlen oder Belege gebunden. Fragt die "
            "Frage nach Hypothesen: 2-3 Sprachhypothesen als eigene "
            "Punkte, je prüfbarer Satz + stützender Zahlen-/KWIC-Beleg + "
            "was sie widerlegen würde.",
            "Geltungsbereich nennen: was wurde tatsaechlich gesichtet "
            "(Scope, Stichprobe, Caps).",
            "Jede zentrale Beobachtung braucht eine zweite, unabhaengige "
            "Evidenzart.",
            "Negativbefunde ehrlich berichten, nicht zu einem Muster "
            "auffuellen.",
        ),
        "beispiel_frage": (
            "Untersuche das Korpus offen: Was fällt thematisch auf?"
        ),
    },
)


#: English interface texts of the recipes, keyed by recipe id.
#:
#: Only the fields that ``GET /copilot/recipes`` shows: ``name``,
#: ``einsatz``, ``beispiel_frage`` and one goal per entry of ``schritte``, in
#: the same order. The German fields above stay the model input (classifier
#: menu, turn briefing) and are not replaced by these texts. The recipe ids
#: are the same in both languages.
RECIPES_UI_EN: Dict[str, Dict[str, Any]] = {
    "verlauf": {
        "name": "Trend over time (diachrony)",
        "einsatz": (
            "How does X develop over time (rates per period with "
            "uncertainty)?"
        ),
        "beispiel_frage": "How does 'inflation' develop over time in the corpus?",
        "schritte": (
            "Verify the date field",
            "Compute the trend",
            "Check the finding",
        ),
    },
    "kontrast": {
        "name": "Contrast and keyness",
        "einsatz": (
            "What is typical of A compared with B (directed keyness between "
            "subsets)?"
        ),
        "beispiel_frage": (
            "Which keywords are typical of the subcorpus 'news' compared "
            "with the subcorpus 'chat'?"
        ),
        "schritte": (
            "Verify the contrast axis",
            "Build both sides as subcorpora",
            "Compute directed keyness",
            "Cross-check the dispersion and quote a concordance line",
        ),
    },
    "profil": {
        "name": "Grammatical profile (word sketch)",
        "einsatz": (
            "Which grammatical relations and partners characterize X (word "
            "sketch)?"
        ),
        "beispiel_frage": (
            "Create a word sketch for 'house': which grammatical relations "
            "characterize the word?"
        ),
        "schritte": (
            "Compute the profile",
            "Quote a concordance line for a salient relation",
        ),
    },
    "assoziation": {
        "name": "Association and collocation",
        "einsatz": (
            "What occurs with X more often than chance (collocates in a "
            "window)?"
        ),
        "beispiel_frage": "Which collocations does 'work' have in the corpus?",
        "schritte": (
            "Compute the collocates",
            "Check them in context",
        ),
    },
    "metadaten_struktur": {
        "name": "Corpus overview (metadata and structure)",
        "einsatz": (
            "What is in the corpus: metadata fields, values, subsets and "
            "their limits?"
        ),
        "beispiel_frage": (
            "Which metadata fields and registers does the corpus contain?"
        ),
        "schritte": (
            "Take the inventory",
            "Report the sizes",
            "Look closer at the focus field",
        ),
    },
    "frequenz": {
        "name": "Frequency and distribution",
        "einsatz": (
            "How often does X occur and how is it distributed (raw, per "
            "million, in comparison)?"
        ),
        "beispiel_frage": (
            "How frequent is 'climate change' in the corpus, per million "
            "tokens?"
        ),
        "schritte": (
            "Determine the exact hit count and rate",
            "If a comparison is needed, measure again in the comparison scope",
            "Optionally add rank context or distribution",
        ),
    },
    "gebrauch_kwic": {
        "name": "Usage in context (KWIC)",
        "einsatz": (
            "How is X used? Show context patterns in concordance lines and "
            "quote them verbatim."
        ),
        "beispiel_frage": (
            "How is 'sustainable' used? Show KWIC lines in context."
        ),
        "schritte": (
            "Write the sequence as a CQL query with a quantifier and count "
            "it within sentences as with within(<doc>)",
            "Only if the question asks about sides: normalize per side of "
            "{achse}",
            "Only if the window size is open: sweep over two or three sizes",
            "Draw a hit sample for the quoted lines",
            "Interpretation, then numbers and concordance lines",
        ),
    },
    "exploration_meta": {
        "name": "Open exploration",
        "einsatz": (
            "Open research question: overview, zoom, cross-check, "
            "interpretation explicitly welcome."
        ),
        "beispiel_frage": (
            "Explore the corpus openly: what stands out thematically?"
        ),
        "schritte": (
            "Get an overview",
            "Follow the most salient lead",
            "Cross-check with a second kind of evidence",
            "State interpretation, hypotheses and follow-up questions",
        ),
    },
}
