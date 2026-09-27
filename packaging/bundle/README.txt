CandyConc application bundle
============================

This folder is a complete CandyConc installation: a private Python with
CandyConc, the web interface, all dependencies and two sample corpora. It
needs no system Python, no compiler, no Node and no network to run.

Start
  ./candyconc
  CandyConc prints the address of the web interface (http://127.0.0.1:8010/,
  or the next free port) and opens it in your browser. Stop it with Ctrl+C.
  Without a corpus the interface opens with an empty catalogue and the import.

Sample corpora (folder examples/)
  examples/sotu_en_1945_2006.jsonl       65 State of the Union addresses,
                                         1945 to 2006, English, public domain
  examples/dta_de_1800_1899_sample.jsonl 30 texts of the Deutsches Textarchiv,
                                         1800 to 1899, German, CC BY-SA 4.0
  examples/README.md describes both, ATTRIBUTION.txt and
  LICENSE-CC-BY-SA-4.0.txt hold the source and license notices. Import them
  with the annotation pipeline of their language (see below):
  ./candyconc pipeline en_core_web_md
  ./candyconc import --input examples/sotu_en_1945_2006.jsonl \
    --output ~/.candyconc/corpora/sotu_en --language en \
    --meta-columns president party year decade date title --source state_union
  ./candyconc pipeline de_core_news_md
  ./candyconc import --input examples/dta_de_1800_1899_sample.jsonl \
    --output ~/.candyconc/corpora/dta_de --language de \
    --meta-columns author title year decade genre subgenre url --source dta_kernkorpus

Quick check without a download (four synthetic English sentences)
  ./candyconc import --input sample/synthetic_en.csv --input-format csv \
    --id-column doc_id --meta-columns genre --spacy-model blank:en \
    --output ~/.candyconc/corpora/sample_en

Linguistic annotation (lemmas, parts of speech, dependencies)
  Download a spaCy pipeline once, it is stored with your data:
  ./candyconc pipeline en_core_web_sm        (English)
  ./candyconc pipeline de_core_news_md       (German)
  Then import with --spacy-model en_core_web_sm. blank:<language> tokenizes
  without annotation and needs no download.

Where your data lives
  ./candyconc paths
  Corpora, projects, settings and pipelines are in ~/.candyconc (or
  $CANDYCONC_HOME), never inside this folder.

Update
  Download the new archive, unpack it, start the new ./candyconc and delete the
  old folder. Your data stays in ~/.candyconc.

Uninstall
  ./candyconc uninstall     removes this folder. Delete ~/.candyconc yourself
  if you also want to remove your corpora and settings.

macOS
  The bundle is not signed or notarized by Apple. A browser download carries
  the quarantine flag, and macOS then refuses to run the bundled Python.
  Download the archive in the Terminal (curl -LO <url>), or remove the flag
  from the unpacked folder once:
  xattr -dr com.apple.quarantine CandyConc-<version>-<platform>

Licenses: THIRD_PARTY_LICENSES.txt lists every bundled component.
