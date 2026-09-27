// Fixture: reale corpus-import-method-v1-Descriptoren der vier ungepaarten
// Ingestion-Adapter (plaintext/csv/jsonl/hf), erzeugt aus
// candyconc.services.backend.corpus_import_jobs.import_method_descriptors().
// Nur availability.script_path ist auf einen stabilen Repo-Platzhalter normalisiert.
// Der Live-Abgleich gegen das Backend passiert in
// src/__tests__/api/backendCorpusImportMethodsParity.test.ts.
import type { CorpusImportMethod } from '@/api/client'

const ADAPTER_METHOD_DESCRIPTORS = [
  {
    "schema_version": "corpus-import-method-v1",
    "method": "plaintext",
    "label": "Plaintext (Ordner/Datei)",
    "description": "Ordner, Einzeldatei oder Glob mit Textdateien; ein Dokument pro Datei (optional pro Absatz), register aus dem Elternordner.",
    "input": {
      "kind": "server_file",
      "extensions": [],
      "accepts_directories": true,
      "path_hint": "/data/imports/texte/",
      "description": "Serverseitig lesbares Verzeichnis (rekursiv per Dateimuster) oder eine einzelne Textdatei."
    },
    "availability": {
      "status": "available",
      "script": "ingest_adapters.py",
      "script_path": "/repo/scripts/jobs/ingest_adapters.py",
      "subcommand": [
        "plaintext"
      ]
    },
    "ui_workflow": {
      "status": "first_class",
      "label": "First-class Import",
      "reason": "Diese Methode ist im Importmanager mit Preflight und Jobmonitoring bedienbar."
    },
    "option_specs": [
      {
        "key": "spacy_model",
        "label": "spaCy-Modell",
        "type": "string",
        "required": false,
        "description": "Pipeline für Tokenisierung und optionale linguistische Annotationen.",
        "aliases": [],
        "default": "de_core_news_md"
      },
      {
        "key": "batch_size",
        "label": "Batchgröße",
        "type": "integer",
        "required": false,
        "description": "0 nutzt die automatische Backend-Heuristik.",
        "aliases": [],
        "default": 0
      },
      {
        "key": "n_process",
        "label": "Prozesse",
        "type": "integer",
        "required": false,
        "description": "0 nutzt die automatische Backend-Heuristik.",
        "aliases": [],
        "default": 0
      },
      {
        "key": "max_doc_chars",
        "label": "Maximale Dokumentlänge",
        "type": "integer",
        "required": false,
        "description": "Lange Dokumente werden je nach split_long_texts sicher segmentiert.",
        "aliases": [],
        "default": 1000000
      },
      {
        "key": "meta_index_fields",
        "label": "Metadatenindex-Felder",
        "type": "string_list",
        "required": false,
        "description": "Felder, die zusätzlich als Metadatenindex verfügbar sein sollen.",
        "aliases": [],
        "default": [],
        "placeholder": "date, genre, source"
      },
      {
        "key": "enable_ner",
        "label": "Named Entities erzeugen",
        "type": "boolean",
        "required": false,
        "description": "Erzeugt NER-Attribute, sofern die spaCy-Pipeline sie unterstützt.",
        "aliases": [],
        "default": false
      },
      {
        "key": "enable_deps",
        "label": "Dependenzen erzeugen",
        "type": "boolean",
        "required": false,
        "description": "Erzeugt Head-/Relation-Attribute, sofern die Pipeline sie unterstützt.",
        "aliases": [],
        "default": false
      },
      {
        "key": "split_long_texts",
        "label": "Lange Texte segmentieren",
        "type": "boolean",
        "required": false,
        "description": "Schützt den Import vor sehr langen Einzeltexten.",
        "aliases": [],
        "default": true
      },
      {
        "key": "build_word_faiss",
        "label": "Wort-Thesaurus (Word-FAISS) nach dem Import bauen",
        "type": "boolean",
        "required": false,
        "description": "Nachschritt nach erfolgreichem Publish: scannt das gesamte Wortlexikon, liest spaCy-Wortvektoren und schreibt faiss_word.index + word_ids.npy. Kosten: zusätzliche Laufzeit und Arbeitsspeicher proportional zur Vokabulargröße; benötigt ein spaCy-Modell mit Vektoren (z. B. de_core_news_md — blank:-Pipelines liefern keine Vektoren, der Nachschritt schlägt dann fehl und wird als Import-Warnung gemeldet). Erst nach erfolgreichem Nachschritt wird semantic.word_similarity (Wort-Thesaurus) für dieses Korpus wahr.",
        "aliases": [],
        "default": false
      },
      {
        "key": "pattern",
        "label": "Dateimuster",
        "type": "string",
        "required": false,
        "description": "Glob-Muster für die rekursive Dateisuche unterhalb des Eingabeverzeichnisses.",
        "aliases": [],
        "default": "*.txt"
      },
      {
        "key": "split_paragraphs",
        "label": "Absätze als Dokumente",
        "type": "boolean",
        "required": false,
        "description": "Zerlegt jede Datei an Leerzeilen in ein Dokument pro Absatz.",
        "aliases": [],
        "default": false
      },
      {
        "key": "source",
        "label": "Quellenlabel",
        "type": "string",
        "required": false,
        "description": "Freies Quellenlabel. Das register-Metadatum wird aus dem unmittelbaren Elternordner jeder Datei abgeleitet; die Dokument-ID aus dem relativen Pfad.",
        "aliases": [],
        "default": ""
      },
      {
        "key": "reject_policy",
        "label": "Reject-Policy",
        "type": "choice",
        "required": false,
        "description": "Umgang mit leeren Texten oder methodisch defekten Zeilen.",
        "aliases": [],
        "default": "collect",
        "choices": [
          {
            "value": "collect",
            "label": "collect",
            "description": "Import läuft weiter und dokumentiert verworfene Zeilen im Reject-Report."
          },
          {
            "value": "fail_fast",
            "label": "fail_fast",
            "description": "Import bricht beim ersten methodischen Fehler ab."
          }
        ]
      },
      {
        "key": "reject_report",
        "label": "Reject-Report-Pfad",
        "type": "path",
        "required": false,
        "description": "Optionaler expliziter Pfad für den Reject-Report.",
        "aliases": [],
        "default": ""
      }
    ],
    "option_keys": [
      "spacy_model",
      "batch_size",
      "n_process",
      "max_doc_chars",
      "meta_index_fields",
      "enable_ner",
      "enable_deps",
      "split_long_texts",
      "build_word_faiss",
      "pattern",
      "split_paragraphs",
      "source",
      "reject_policy",
      "reject_report"
    ],
    "expected_columns": [],
    "output": {
      "paired": false,
      "paired_data_dependent": false,
      "pairing_kind": "none",
      "emitted_features": [
        "word_tokens",
        "document_metadata",
        "frequency_word",
        "kwic_ready",
        "lemma_pos_spacy",
        "optional_ner",
        "optional_deps",
        "register_from_parent_dir",
        "reject_summary"
      ],
      "guarantees": [
        "Ein Dokument pro Datei (oder pro Absatz bei split_paragraphs).",
        "Dokument-ID aus dem relativen Pfad, register aus dem unmittelbaren Elternordner."
      ],
      "limitations": [
        "Nicht-UTF-8-Dateien werden per Encoding-Erkennung bestmöglich dekodiert (ersatzweise mit Ersatzzeichen), nicht abgelehnt.",
        "Symlinks, deren Ziel das Eingabeverzeichnis verlässt, werden übersprungen."
      ]
    },
    "emitted_features": [
      "word_tokens",
      "document_metadata",
      "frequency_word",
      "kwic_ready",
      "lemma_pos_spacy",
      "optional_ner",
      "optional_deps",
      "register_from_parent_dir",
      "reject_summary"
    ],
    "reports": [
      {
        "key": "build_report",
        "label": "Build-Report",
        "description": "Status, Token-/Dokumentzahlen und Build-Phasen."
      },
      {
        "key": "reject_report",
        "label": "Reject-Report",
        "description": "Verworfene Zeilen bei collect-Policy."
      },
      {
        "key": "manifest",
        "label": "Index-Manifest",
        "description": "Capability- und Provenienzbeschreibung des erzeugten Index."
      },
      {
        "key": "build_meta",
        "label": "Build-Metadaten",
        "description": "Technische Build-Parameter und optionale Reject-Summary."
      }
    ]
  },
  {
    "schema_version": "corpus-import-method-v1",
    "method": "csv",
    "label": "CSV/TSV",
    "description": "Ungepaarte CSV/TSV-Tabellen mit konfigurierbarer Text- und ID-Spalte.",
    "input": {
      "kind": "server_file",
      "extensions": [
        ".csv",
        ".tsv"
      ],
      "accepts_directories": false,
      "path_hint": "/data/imports/korpus.csv",
      "description": "Pfad zu einer serverseitig lesbaren CSV/TSV-Datei."
    },
    "availability": {
      "status": "available",
      "script": "ingest_adapters.py",
      "script_path": "/repo/scripts/jobs/ingest_adapters.py",
      "subcommand": [
        "csv"
      ]
    },
    "ui_workflow": {
      "status": "first_class",
      "label": "First-class Import",
      "reason": "Diese Methode ist im Importmanager mit Preflight und Jobmonitoring bedienbar."
    },
    "option_specs": [
      {
        "key": "spacy_model",
        "label": "spaCy-Modell",
        "type": "string",
        "required": false,
        "description": "Pipeline für Tokenisierung und optionale linguistische Annotationen.",
        "aliases": [],
        "default": "de_core_news_md"
      },
      {
        "key": "batch_size",
        "label": "Batchgröße",
        "type": "integer",
        "required": false,
        "description": "0 nutzt die automatische Backend-Heuristik.",
        "aliases": [],
        "default": 0
      },
      {
        "key": "n_process",
        "label": "Prozesse",
        "type": "integer",
        "required": false,
        "description": "0 nutzt die automatische Backend-Heuristik.",
        "aliases": [],
        "default": 0
      },
      {
        "key": "max_doc_chars",
        "label": "Maximale Dokumentlänge",
        "type": "integer",
        "required": false,
        "description": "Lange Dokumente werden je nach split_long_texts sicher segmentiert.",
        "aliases": [],
        "default": 1000000
      },
      {
        "key": "meta_index_fields",
        "label": "Metadatenindex-Felder",
        "type": "string_list",
        "required": false,
        "description": "Felder, die zusätzlich als Metadatenindex verfügbar sein sollen.",
        "aliases": [],
        "default": [],
        "placeholder": "date, genre, source"
      },
      {
        "key": "enable_ner",
        "label": "Named Entities erzeugen",
        "type": "boolean",
        "required": false,
        "description": "Erzeugt NER-Attribute, sofern die spaCy-Pipeline sie unterstützt.",
        "aliases": [],
        "default": false
      },
      {
        "key": "enable_deps",
        "label": "Dependenzen erzeugen",
        "type": "boolean",
        "required": false,
        "description": "Erzeugt Head-/Relation-Attribute, sofern die Pipeline sie unterstützt.",
        "aliases": [],
        "default": false
      },
      {
        "key": "split_long_texts",
        "label": "Lange Texte segmentieren",
        "type": "boolean",
        "required": false,
        "description": "Schützt den Import vor sehr langen Einzeltexten.",
        "aliases": [],
        "default": true
      },
      {
        "key": "build_word_faiss",
        "label": "Wort-Thesaurus (Word-FAISS) nach dem Import bauen",
        "type": "boolean",
        "required": false,
        "description": "Nachschritt nach erfolgreichem Publish: scannt das gesamte Wortlexikon, liest spaCy-Wortvektoren und schreibt faiss_word.index + word_ids.npy. Kosten: zusätzliche Laufzeit und Arbeitsspeicher proportional zur Vokabulargröße; benötigt ein spaCy-Modell mit Vektoren (z. B. de_core_news_md — blank:-Pipelines liefern keine Vektoren, der Nachschritt schlägt dann fehl und wird als Import-Warnung gemeldet). Erst nach erfolgreichem Nachschritt wird semantic.word_similarity (Wort-Thesaurus) für dieses Korpus wahr.",
        "aliases": [],
        "default": false
      },
      {
        "key": "text_column",
        "label": "Textspalte",
        "type": "string",
        "required": true,
        "description": "Spalte bzw. Feld, das als Dokumenttext indexiert wird.",
        "aliases": [],
        "default": "text"
      },
      {
        "key": "id_column",
        "label": "ID-Spalte",
        "type": "string",
        "required": false,
        "description": "Optionale Dokument-ID; leer erzeugt der Import stabile IDs.",
        "aliases": [],
        "default": ""
      },
      {
        "key": "meta_columns",
        "label": "Metadatenspalten",
        "type": "string_list",
        "required": false,
        "description": "Zusätzliche Spalten/Felder, die als Dokumentmetadaten übernommen werden.",
        "aliases": [],
        "default": []
      },
      {
        "key": "source",
        "label": "Quellenlabel",
        "type": "string",
        "required": false,
        "description": "Freies Quellenlabel für den Import.",
        "aliases": [],
        "default": ""
      },
      {
        "key": "delimiter",
        "label": "CSV-Trenner",
        "type": "string",
        "required": false,
        "description": "Optionaler Delimiter. Leer nutzt die Autoerkennung (csv.Sniffer über Komma, Semikolon, Tab und Pipe auf einem 8-KiB-Sample; ohne Treffer fällt der Import auf Komma zurück).",
        "aliases": [],
        "default": ""
      },
      {
        "key": "reject_policy",
        "label": "Reject-Policy",
        "type": "choice",
        "required": false,
        "description": "Umgang mit leeren Texten oder methodisch defekten Zeilen.",
        "aliases": [],
        "default": "collect",
        "choices": [
          {
            "value": "collect",
            "label": "collect",
            "description": "Import läuft weiter und dokumentiert verworfene Zeilen im Reject-Report."
          },
          {
            "value": "fail_fast",
            "label": "fail_fast",
            "description": "Import bricht beim ersten methodischen Fehler ab."
          }
        ]
      },
      {
        "key": "reject_report",
        "label": "Reject-Report-Pfad",
        "type": "path",
        "required": false,
        "description": "Optionaler expliziter Pfad für den Reject-Report.",
        "aliases": [],
        "default": ""
      }
    ],
    "option_keys": [
      "spacy_model",
      "batch_size",
      "n_process",
      "max_doc_chars",
      "meta_index_fields",
      "enable_ner",
      "enable_deps",
      "split_long_texts",
      "build_word_faiss",
      "text_column",
      "id_column",
      "meta_columns",
      "source",
      "delimiter",
      "reject_policy",
      "reject_report"
    ],
    "expected_columns": [
      {
        "key": "text",
        "label": "Textspalte",
        "required": true,
        "description": "Default-Textspalte/-Feld für ungepaarte Importe.",
        "configured_by": "text_column"
      },
      {
        "key": "id",
        "label": "Dokument-ID",
        "required": false,
        "description": "Optionale Default-ID-Spalte.",
        "configured_by": "id_column"
      }
    ],
    "output": {
      "paired": false,
      "paired_data_dependent": false,
      "pairing_kind": "none",
      "emitted_features": [
        "word_tokens",
        "document_metadata",
        "frequency_word",
        "kwic_ready",
        "lemma_pos_spacy",
        "optional_ner",
        "optional_deps",
        "reject_summary"
      ],
      "guarantees": [
        "Genau die konfigurierte Textspalte wird indexiert; Delimiter wird dokumentiert erkannt."
      ],
      "limitations": [
        "CSV-Spaltensemantik wird nicht als Forschungsdesign validiert.",
        "Delimiter-Autoerkennung arbeitet auf einem bounded Sample; bei exotischen Formaten delimiter explizit setzen."
      ]
    },
    "emitted_features": [
      "word_tokens",
      "document_metadata",
      "frequency_word",
      "kwic_ready",
      "lemma_pos_spacy",
      "optional_ner",
      "optional_deps",
      "reject_summary"
    ],
    "reports": [
      {
        "key": "build_report",
        "label": "Build-Report",
        "description": "Status, Token-/Dokumentzahlen und Build-Phasen."
      },
      {
        "key": "reject_report",
        "label": "Reject-Report",
        "description": "Verworfene Zeilen bei collect-Policy."
      },
      {
        "key": "manifest",
        "label": "Index-Manifest",
        "description": "Capability- und Provenienzbeschreibung des erzeugten Index."
      },
      {
        "key": "build_meta",
        "label": "Build-Metadaten",
        "description": "Technische Build-Parameter und optionale Reject-Summary."
      }
    ]
  },
  {
    "schema_version": "corpus-import-method-v1",
    "method": "jsonl",
    "label": "JSONL",
    "description": "Ungepaarte JSONL-Zeilen mit konfigurierbarem Text- und ID-Feld (Dot-Pfade erlaubt).",
    "input": {
      "kind": "server_file",
      "extensions": [
        ".jsonl",
        ".ndjson"
      ],
      "accepts_directories": false,
      "path_hint": "/data/imports/korpus.jsonl",
      "description": "Pfad zu einer serverseitig lesbaren JSONL-Datei."
    },
    "availability": {
      "status": "available",
      "script": "ingest_adapters.py",
      "script_path": "/repo/scripts/jobs/ingest_adapters.py",
      "subcommand": [
        "jsonl"
      ]
    },
    "ui_workflow": {
      "status": "first_class",
      "label": "First-class Import",
      "reason": "Diese Methode ist im Importmanager mit Preflight und Jobmonitoring bedienbar."
    },
    "option_specs": [
      {
        "key": "spacy_model",
        "label": "spaCy-Modell",
        "type": "string",
        "required": false,
        "description": "Pipeline für Tokenisierung und optionale linguistische Annotationen.",
        "aliases": [],
        "default": "de_core_news_md"
      },
      {
        "key": "batch_size",
        "label": "Batchgröße",
        "type": "integer",
        "required": false,
        "description": "0 nutzt die automatische Backend-Heuristik.",
        "aliases": [],
        "default": 0
      },
      {
        "key": "n_process",
        "label": "Prozesse",
        "type": "integer",
        "required": false,
        "description": "0 nutzt die automatische Backend-Heuristik.",
        "aliases": [],
        "default": 0
      },
      {
        "key": "max_doc_chars",
        "label": "Maximale Dokumentlänge",
        "type": "integer",
        "required": false,
        "description": "Lange Dokumente werden je nach split_long_texts sicher segmentiert.",
        "aliases": [],
        "default": 1000000
      },
      {
        "key": "meta_index_fields",
        "label": "Metadatenindex-Felder",
        "type": "string_list",
        "required": false,
        "description": "Felder, die zusätzlich als Metadatenindex verfügbar sein sollen.",
        "aliases": [],
        "default": [],
        "placeholder": "date, genre, source"
      },
      {
        "key": "enable_ner",
        "label": "Named Entities erzeugen",
        "type": "boolean",
        "required": false,
        "description": "Erzeugt NER-Attribute, sofern die spaCy-Pipeline sie unterstützt.",
        "aliases": [],
        "default": false
      },
      {
        "key": "enable_deps",
        "label": "Dependenzen erzeugen",
        "type": "boolean",
        "required": false,
        "description": "Erzeugt Head-/Relation-Attribute, sofern die Pipeline sie unterstützt.",
        "aliases": [],
        "default": false
      },
      {
        "key": "split_long_texts",
        "label": "Lange Texte segmentieren",
        "type": "boolean",
        "required": false,
        "description": "Schützt den Import vor sehr langen Einzeltexten.",
        "aliases": [],
        "default": true
      },
      {
        "key": "build_word_faiss",
        "label": "Wort-Thesaurus (Word-FAISS) nach dem Import bauen",
        "type": "boolean",
        "required": false,
        "description": "Nachschritt nach erfolgreichem Publish: scannt das gesamte Wortlexikon, liest spaCy-Wortvektoren und schreibt faiss_word.index + word_ids.npy. Kosten: zusätzliche Laufzeit und Arbeitsspeicher proportional zur Vokabulargröße; benötigt ein spaCy-Modell mit Vektoren (z. B. de_core_news_md — blank:-Pipelines liefern keine Vektoren, der Nachschritt schlägt dann fehl und wird als Import-Warnung gemeldet). Erst nach erfolgreichem Nachschritt wird semantic.word_similarity (Wort-Thesaurus) für dieses Korpus wahr.",
        "aliases": [],
        "default": false
      },
      {
        "key": "text_column",
        "label": "Textfeld",
        "type": "string",
        "required": true,
        "description": "Feld mit dem Dokumenttext; Dot-Pfade wie payload.text sind erlaubt.",
        "aliases": [],
        "default": "text"
      },
      {
        "key": "id_column",
        "label": "ID-Feld",
        "type": "string",
        "required": false,
        "description": "Optionales ID-Feld (Dot-Pfade erlaubt); leer erzeugt der Import stabile IDs.",
        "aliases": [],
        "default": ""
      },
      {
        "key": "meta_columns",
        "label": "Metadatenfelder",
        "type": "string_list",
        "required": false,
        "description": "Zusätzliche Felder (Dot-Pfade erlaubt), die als Dokumentmetadaten übernommen werden.",
        "aliases": [],
        "default": []
      },
      {
        "key": "source",
        "label": "Quellenlabel",
        "type": "string",
        "required": false,
        "description": "Freies Quellenlabel für den Import.",
        "aliases": [],
        "default": ""
      },
      {
        "key": "reject_policy",
        "label": "Reject-Policy",
        "type": "choice",
        "required": false,
        "description": "Umgang mit leeren Texten oder methodisch defekten Zeilen.",
        "aliases": [],
        "default": "collect",
        "choices": [
          {
            "value": "collect",
            "label": "collect",
            "description": "Import läuft weiter und dokumentiert verworfene Zeilen im Reject-Report."
          },
          {
            "value": "fail_fast",
            "label": "fail_fast",
            "description": "Import bricht beim ersten methodischen Fehler ab."
          }
        ]
      },
      {
        "key": "reject_report",
        "label": "Reject-Report-Pfad",
        "type": "path",
        "required": false,
        "description": "Optionaler expliziter Pfad für den Reject-Report.",
        "aliases": [],
        "default": ""
      }
    ],
    "option_keys": [
      "spacy_model",
      "batch_size",
      "n_process",
      "max_doc_chars",
      "meta_index_fields",
      "enable_ner",
      "enable_deps",
      "split_long_texts",
      "build_word_faiss",
      "text_column",
      "id_column",
      "meta_columns",
      "source",
      "reject_policy",
      "reject_report"
    ],
    "expected_columns": [
      {
        "key": "text",
        "label": "Textspalte",
        "required": true,
        "description": "Default-Textspalte/-Feld für ungepaarte Importe.",
        "configured_by": "text_column"
      },
      {
        "key": "id",
        "label": "Dokument-ID",
        "required": false,
        "description": "Optionale Default-ID-Spalte.",
        "configured_by": "id_column"
      }
    ],
    "output": {
      "paired": false,
      "paired_data_dependent": false,
      "pairing_kind": "none",
      "emitted_features": [
        "word_tokens",
        "document_metadata",
        "frequency_word",
        "kwic_ready",
        "lemma_pos_spacy",
        "optional_ner",
        "optional_deps",
        "reject_summary"
      ],
      "guarantees": [
        "Fehlerhafte, überlange oder Nicht-Objekt-Zeilen werden dokumentiert verworfen statt den Import abzubrechen."
      ],
      "limitations": [
        "JSONL-Feldsemantik wird nicht als Forschungsdesign validiert."
      ]
    },
    "emitted_features": [
      "word_tokens",
      "document_metadata",
      "frequency_word",
      "kwic_ready",
      "lemma_pos_spacy",
      "optional_ner",
      "optional_deps",
      "reject_summary"
    ],
    "reports": [
      {
        "key": "build_report",
        "label": "Build-Report",
        "description": "Status, Token-/Dokumentzahlen und Build-Phasen."
      },
      {
        "key": "reject_report",
        "label": "Reject-Report",
        "description": "Verworfene Zeilen bei collect-Policy."
      },
      {
        "key": "manifest",
        "label": "Index-Manifest",
        "description": "Capability- und Provenienzbeschreibung des erzeugten Index."
      },
      {
        "key": "build_meta",
        "label": "Build-Metadaten",
        "description": "Technische Build-Parameter und optionale Reject-Summary."
      }
    ]
  },
  {
    "schema_version": "corpus-import-method-v1",
    "method": "hf",
    "label": "HuggingFace-Dataset",
    "description": "HuggingFace-Dataset per Dataset-ID; Download erfolgt erst beim Import (Streaming), trust_remote_code bleibt hart deaktiviert.",
    "input": {
      "kind": "hf_dataset",
      "extensions": [],
      "accepts_directories": false,
      "path_hint": "organisation/dataset-name",
      "description": "HuggingFace-Dataset-ID (kein Serverpfad). Der Download erfolgt erst beim Import; der Preflight bleibt ohne Netzzugriff."
    },
    "availability": {
      "status": "available",
      "script": "ingest_adapters.py",
      "script_path": "/repo/scripts/jobs/ingest_adapters.py",
      "subcommand": [
        "hf"
      ]
    },
    "ui_workflow": {
      "status": "first_class",
      "label": "First-class Import",
      "reason": "Diese Methode ist im Importmanager mit Preflight und Jobmonitoring bedienbar."
    },
    "option_specs": [
      {
        "key": "spacy_model",
        "label": "spaCy-Modell",
        "type": "string",
        "required": false,
        "description": "Pipeline für Tokenisierung und optionale linguistische Annotationen.",
        "aliases": [],
        "default": "de_core_news_md"
      },
      {
        "key": "batch_size",
        "label": "Batchgröße",
        "type": "integer",
        "required": false,
        "description": "0 nutzt die automatische Backend-Heuristik.",
        "aliases": [],
        "default": 0
      },
      {
        "key": "n_process",
        "label": "Prozesse",
        "type": "integer",
        "required": false,
        "description": "0 nutzt die automatische Backend-Heuristik.",
        "aliases": [],
        "default": 0
      },
      {
        "key": "max_doc_chars",
        "label": "Maximale Dokumentlänge",
        "type": "integer",
        "required": false,
        "description": "Lange Dokumente werden je nach split_long_texts sicher segmentiert.",
        "aliases": [],
        "default": 1000000
      },
      {
        "key": "meta_index_fields",
        "label": "Metadatenindex-Felder",
        "type": "string_list",
        "required": false,
        "description": "Felder, die zusätzlich als Metadatenindex verfügbar sein sollen.",
        "aliases": [],
        "default": [],
        "placeholder": "date, genre, source"
      },
      {
        "key": "enable_ner",
        "label": "Named Entities erzeugen",
        "type": "boolean",
        "required": false,
        "description": "Erzeugt NER-Attribute, sofern die spaCy-Pipeline sie unterstützt.",
        "aliases": [],
        "default": false
      },
      {
        "key": "enable_deps",
        "label": "Dependenzen erzeugen",
        "type": "boolean",
        "required": false,
        "description": "Erzeugt Head-/Relation-Attribute, sofern die Pipeline sie unterstützt.",
        "aliases": [],
        "default": false
      },
      {
        "key": "split_long_texts",
        "label": "Lange Texte segmentieren",
        "type": "boolean",
        "required": false,
        "description": "Schützt den Import vor sehr langen Einzeltexten.",
        "aliases": [],
        "default": true
      },
      {
        "key": "build_word_faiss",
        "label": "Wort-Thesaurus (Word-FAISS) nach dem Import bauen",
        "type": "boolean",
        "required": false,
        "description": "Nachschritt nach erfolgreichem Publish: scannt das gesamte Wortlexikon, liest spaCy-Wortvektoren und schreibt faiss_word.index + word_ids.npy. Kosten: zusätzliche Laufzeit und Arbeitsspeicher proportional zur Vokabulargröße; benötigt ein spaCy-Modell mit Vektoren (z. B. de_core_news_md — blank:-Pipelines liefern keine Vektoren, der Nachschritt schlägt dann fehl und wird als Import-Warnung gemeldet). Erst nach erfolgreichem Nachschritt wird semantic.word_similarity (Wort-Thesaurus) für dieses Korpus wahr.",
        "aliases": [],
        "default": false
      },
      {
        "key": "text_column",
        "label": "Textspalte",
        "type": "string",
        "required": true,
        "description": "Dataset-Spalte, die als Dokumenttext indexiert wird.",
        "aliases": [],
        "default": "text"
      },
      {
        "key": "id_column",
        "label": "ID-Spalte",
        "type": "string",
        "required": false,
        "description": "Optionale Dokument-ID-Spalte; leer erzeugt der Import stabile IDs.",
        "aliases": [],
        "default": ""
      },
      {
        "key": "meta_columns",
        "label": "Metadatenspalten",
        "type": "string_list",
        "required": false,
        "description": "Zusätzliche Dataset-Spalten, die als Dokumentmetadaten übernommen werden.",
        "aliases": [],
        "default": []
      },
      {
        "key": "config",
        "label": "Dataset-Konfiguration",
        "type": "string",
        "required": false,
        "description": "Optionaler Config-Name des Datasets.",
        "aliases": [],
        "default": ""
      },
      {
        "key": "split",
        "label": "Split",
        "type": "string",
        "required": false,
        "description": "Dataset-Split, der importiert wird.",
        "aliases": [],
        "default": "train"
      },
      {
        "key": "limit",
        "label": "Zeilenlimit",
        "type": "integer",
        "required": false,
        "description": "Maximale Zeilenzahl (0 = unbegrenzt). Begrenzt Umfang und Laufzeit des Streaming-Imports.",
        "aliases": [],
        "default": 0
      },
      {
        "key": "source",
        "label": "Quellenlabel",
        "type": "string",
        "required": false,
        "description": "Freies Quellenlabel für den Import.",
        "aliases": [],
        "default": ""
      },
      {
        "key": "reject_policy",
        "label": "Reject-Policy",
        "type": "choice",
        "required": false,
        "description": "Umgang mit leeren Texten oder methodisch defekten Zeilen.",
        "aliases": [],
        "default": "collect",
        "choices": [
          {
            "value": "collect",
            "label": "collect",
            "description": "Import läuft weiter und dokumentiert verworfene Zeilen im Reject-Report."
          },
          {
            "value": "fail_fast",
            "label": "fail_fast",
            "description": "Import bricht beim ersten methodischen Fehler ab."
          }
        ]
      },
      {
        "key": "reject_report",
        "label": "Reject-Report-Pfad",
        "type": "path",
        "required": false,
        "description": "Optionaler expliziter Pfad für den Reject-Report.",
        "aliases": [],
        "default": ""
      }
    ],
    "option_keys": [
      "spacy_model",
      "batch_size",
      "n_process",
      "max_doc_chars",
      "meta_index_fields",
      "enable_ner",
      "enable_deps",
      "split_long_texts",
      "build_word_faiss",
      "text_column",
      "id_column",
      "meta_columns",
      "config",
      "split",
      "limit",
      "source",
      "reject_policy",
      "reject_report"
    ],
    "expected_columns": [
      {
        "key": "text",
        "label": "Textspalte",
        "required": true,
        "description": "Default-Textspalte/-Feld für ungepaarte Importe.",
        "configured_by": "text_column"
      },
      {
        "key": "id",
        "label": "Dokument-ID",
        "required": false,
        "description": "Optionale Default-ID-Spalte.",
        "configured_by": "id_column"
      }
    ],
    "output": {
      "paired": false,
      "paired_data_dependent": false,
      "pairing_kind": "none",
      "emitted_features": [
        "word_tokens",
        "document_metadata",
        "frequency_word",
        "kwic_ready",
        "lemma_pos_spacy",
        "optional_ner",
        "optional_deps",
        "reject_summary"
      ],
      "guarantees": [
        "Streaming-Import mit optionalem Zeilenlimit; die Dataset-ID wird unverändert als Provenienz dokumentiert."
      ],
      "limitations": [
        "Der Import benötigt Netzzugriff und das Paket 'datasets'; der Preflight validiert nur den Descriptor ohne Netzzugriff.",
        "Sicherheitsgrenze: trust_remote_code bleibt hart False — Datasets, die eigenen Code ausführen wollen, werden nicht importiert.",
        "Spalten und Splits werden erst beim Import geprüft, nicht im Preflight."
      ]
    },
    "emitted_features": [
      "word_tokens",
      "document_metadata",
      "frequency_word",
      "kwic_ready",
      "lemma_pos_spacy",
      "optional_ner",
      "optional_deps",
      "reject_summary"
    ],
    "reports": [
      {
        "key": "build_report",
        "label": "Build-Report",
        "description": "Status, Token-/Dokumentzahlen und Build-Phasen."
      },
      {
        "key": "reject_report",
        "label": "Reject-Report",
        "description": "Verworfene Zeilen bei collect-Policy."
      },
      {
        "key": "manifest",
        "label": "Index-Manifest",
        "description": "Capability- und Provenienzbeschreibung des erzeugten Index."
      },
      {
        "key": "build_meta",
        "label": "Build-Metadaten",
        "description": "Technische Build-Parameter und optionale Reject-Summary."
      }
    ]
  }
] as const

export function corpusImportAdapterMethodDescriptors(): CorpusImportMethod[] {
  return JSON.parse(JSON.stringify(ADAPTER_METHOD_DESCRIPTORS)) as CorpusImportMethod[]
}
