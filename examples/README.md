# Sample corpora

Two corpora for the first steps with CandyConc and for the examples in the
documentation, one English and one German. Both files are ready to import:
one JSON object per line with the document text and its metadata.

| File | Language | Documents | Words | License |
| :-- | :-- | --: | --: | :-- |
| `sotu_en_1945_2006.jsonl` | English | 65 | 349,711 | public domain |
| `dta_de_1800_1899_sample.jsonl` | German | 30 | 498,020 | CC BY-SA 4.0, attribution "Deutsches Textarchiv" |

Words are counted at whitespace. The token counts after the import are in
the table under [Import](#import).

## Import

Install the spaCy pipeline for the language once, then import. The commands
run in the folder that contains this folder `examples/`: the root folder of
the CandyConc repository or of its source distribution, or the folder of the
application bundle. In the bundle, write `./candyconc` instead of `candy`.

English:

```bash
candy pipeline en_core_web_md
candy import --input examples/sotu_en_1945_2006.jsonl \
  --output ~/.candyconc/corpora/sotu_en --language en \
  --meta-columns president party year decade date title --source state_union
```

German:

```bash
candy pipeline de_core_news_md
candy import --input examples/dta_de_1800_1899_sample.jsonl \
  --output ~/.candyconc/corpora/dta_de --language de \
  --meta-columns author title year decade genre subgenre url --source dta_kernkorpus
```

`--language` selects the standard pipeline of the language (`en_core_web_md`,
`de_core_news_md`). Both pipelines have a dependency parser, so the import
also parses dependencies, which Word Sketch needs. `--no-deps` imports
without them. `--meta-columns` names the metadata fields that become
filters, subcorpora and trend periods. Without it the documents keep no
metadata from the file besides their `id`.

Then start CandyConc with `candy` and choose the corpus in the corpus menu.

Numbers after the import with CandyConc 0.1.0, spaCy 3.8 and the pipelines
in version 3.8.0:

| | `sotu_en` | `dta_de` |
| :-- | --: | --: |
| Documents | 65 | 30 |
| Tokens | 403,284 | 624,227 |
| Sentences | 17,758 | 36,182 |
| Rejected input rows | 0 | 0 |
| Hits for `freedom` / `Freiheit` (simple search) | 495 | 135 |

Tokens include punctuation and the line breaks that spaCy keeps as tokens
(part of speech `SPACE`): 6,577 in `sotu_en`, 34,577 in `dta_de`. The
sentence count comes from the dependency parser. With `--no-deps` CandyConc
splits sentences at punctuation instead and counts 17,707 and 34,652.

## English: State of the Union Addresses 1945 to 2006

- Content: 65 addresses of US presidents to Congress, from Harry S. Truman
  (April 1945) to George W. Bush (January 2006). Besides the annual State of
  the Union messages the collection holds a few other addresses to Congress,
  for example Truman in April 1945 after the death of Roosevelt, Kennedy's
  "Urgent National Needs" (1961), "The American Promise" (1965), the Gulf
  War address of 1991 and two addresses by George W. Bush in 2001. The field
  `title` shows which address a document is.
- Source: C-SPAN State of the Union Address Corpus, compiled by Kathleen
  Ahrens from C-SPAN sources, as distributed by NLTK Data, package
  `state_union`:
  <https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/state_union.zip>
  (retrieved 2026-09-26, SHA-256
  `366c1dc82b2abf896f42b2ec50ba802a0141a29f75d29ca48a7a243ce5bfbe8d`).
- Rights: addresses and messages of the US President are works of the US
  federal government and in the public domain in the United States
  (17 U.S.C. § 105). The NLTK Data index lists the package as "public
  domain". No attribution is required. This page names the source so that
  every text can be traced.
- Metadata: `president` and `party` (public record) from the file name,
  `year`, `decade`, `date` (ISO date where one of the first four lines has
  a date of that year, 55 of 65 documents) and `title` (first line of the
  transcript).
- Changes: character encoding normalized to UTF-8 (the five Nixon files
  1970 to 1974 are Big5 encoded and contain only typographic punctuation
  outside ASCII, `1954-Eisenhower` is cp1252). Line breaks normalized and
  whitespace at the edges removed. The text is otherwise unchanged.
- Good to know: the transcripts follow different conventions. The texts of
  George W. Bush from 2002 on contain "(Applause.)" and typographic
  apostrophes. A keyness comparison of Republican against all other
  addresses therefore ranks "Applause" and "’s" first. The concordance
  lines show why.

## German: Deutsches Textarchiv, 30 texts 1800 to 1899

- Content: 30 complete texts from the core corpus of the Deutsches
  Textarchiv, one text per decade and main genre (Belletristik,
  Gebrauchsliteratur, Wissenschaft), among them Grillparzer "Sappho"
  (1819), Helmholtz "Über die Erhaltung der Kraft" (1847), Frege "Über Sinn
  und Bedeutung" (1892) and Hauptmann "Bahnwärter Thiel" (1892).
- Source: Deutsches Textarchiv. Grundlage für ein Referenzkorpus der
  neuhochdeutschen Sprache. Herausgegeben von der Berlin-Brandenburgischen
  Akademie der Wissenschaften, Berlin. <https://www.deutschestextarchiv.de/>
  - Texts: normalized plain text release of 2020-10-23, period 1800 to 1899,
    <https://www.deutschestextarchiv.de/media/download/dtak/2020-10-23/normalized/1800-1899.zip>
    (SHA-256 `84b334bdbff73099366fe09ce298cc5659fec1fcabf22b4aa45446db00192615`).
  - Metadata: Dublin Core release of 2026-02-12,
    <https://www.deutschestextarchiv.de/media/download/dta_metadaten_oai_dc_2026-02-12.zip>
    (SHA-256 `97cee635634aa92064daa67ecb71c313cf2726044b0b1853d03de67a10893775`).
- License: the DTA full texts are licensed under Creative Commons
  Attribution-ShareAlike 4.0 International (CC BY-SA 4.0), terms of use at
  <https://deutsches-textarchiv.de/doku/nutzungsbedingungen>. The prepared
  file `dta_de_1800_1899_sample.jsonl` is a modified version (selection
  and added metadata) and is distributed under the same license. The full
  license text is in `LICENSE-CC-BY-SA-4.0.txt`, also at
  <https://creativecommons.org/licenses/by-sa/4.0/legalcode>.
- Attribution: "Deutsches Textarchiv". Every document carries its DTA URL
  in the field `url`, with the edition in the field `edition`.
- Selection: only the core corpus, `dc:date` from 1800 to 1899, main genre
  Belletristik, Gebrauchsliteratur or Wissenschaft, 5,000 to 40,000 words.
  For each decade and genre the text with the word count closest to 15,000,
  ties broken by the DTA identifier. The rule and the chosen text of every
  cell are recorded in `prepare_manifest.json`.
- Metadata: `author`, `title`, `year`, `decade`, `genre`, `subgenre`, `url`,
  `edition` from the DTA metadata.
- Changes: selection of 30 texts, metadata fields added. The text is
  unchanged.
- Why the normalized release: the original transcription keeps historical
  spellings such as "ſ", so a search for "sein" would miss "ſein", and
  `de_core_news_md` tags normalized spelling more reliably. The normalized
  texts contain no "ſ".
- Good to know: the DTA normalization is not uniform in the spelling of ß
  and ss. 8 texts write "dass", 22 write "daß", and five of the eight "dass"
  texts are Wissenschaft. A keyness comparison of Wissenschaft against the
  other genres therefore ranks "dass" first.
- Recommended citation of the DTA: Deutsches Textarchiv. Grundlage für ein
  Referenzkorpus der neuhochdeutschen Sprache. Herausgegeben von der
  Berlin-Brandenburgischen Akademie der Wissenschaften, Berlin 2026. URL:
  https://www.deutschestextarchiv.de/

## Reproducing the files

`prepare_sample_corpora.py` builds both files from the primary sources with
the Python standard library alone. It downloads three archives (about 150 MB,
almost all of it the DTA release), checks each against its SHA-256 and
applies the fixed selection rule:

```bash
python examples/prepare_sample_corpora.py --workdir /tmp/candyconc-samples
# again without network once the downloads are in the work folder:
python examples/prepare_sample_corpora.py --workdir /tmp/candyconc-samples --offline
```

The results in `<workdir>/prepared/` are byte-identical to the files here:

| File | SHA-256 |
| :-- | :-- |
| `sotu_en_1945_2006.jsonl` | `c9b089797f17d3f433da5cd8e89806b3d0fb711e6c5e15145a08f2f12e538d91` |
| `dta_de_1800_1899_sample.jsonl` | `4e8950bb782775d7f94b23dbba1e3524c0c86d4a1c7dd2fe208b8ae5be81ea0b` |

Only the time stamp in `prepare_manifest.json` changes. `ATTRIBUTION.txt`
repeats source, rights and changes in plain text.
