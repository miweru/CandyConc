# Worked examples

The examples on the methods pages use a corpus that is small enough to
recompute every number by hand. This page describes the corpus, how to
reproduce the examples in your own installation, and how the documentation
checks them.

## The synthetic tea corpus

The tea corpus is **synthetic**. Its eight short documents make the counting
rules visible and let you verify the calculations by hand. Each document
has a date and a register (`blog` or `news`):

| Document | date | register | Text |
| --- | --- | --- | --- |
| d1 | 2019-03-02 | blog | Tea is my morning ritual. I drink green tea from a big cup. A cup of tea makes the day calm. |
| d2 | 2019-11-20 | news | Coffee prices rose again this year. Traders expect coffee demand to grow. The market for coffee is volatile. |
| d3 | 2020-05-14 | blog | I prefer green tea over coffee. A cup of green tea with honey is lovely. My sister drinks black tea. |
| d4 | 2020-08-03 | news | Coffee exports fell sharply. The coffee harvest was poor, and prices for coffee climbed. |
| d5 | 2021-02-27 | blog | Some days I drink a cup of coffee, but tea wins. Hot tea, a cup of tea, and a quiet book. |
| d6 | 2021-09-09 | news | Tea imports grew, while coffee imports fell. Analysts say green tea is gaining market share. |
| d7 | 2022-04-18 | news | TEA and COFFEE futures were quiet. Tea traders waited for the harvest. |
| d8 | 2022-10-01 | blog | Green tea, green tea, always green tea. A cup of tea is a small ritual. |

The corpus has 162 tokens, of which 136 are word tokens, in 19 sentences. The
blog documents have 92 tokens (77 word tokens), the news documents 70 tokens
(59 word tokens).

Download the file: {download}`tea_demo.jsonl <data/tea_demo.jsonl>`.

## Reproduce the examples

1. Import the file with a blank English pipeline. It tokenizes without a
   trained model, so no model is needed:

   ```bash
   candy import --input tea_demo.jsonl --output ~/.candyconc/corpora/tea_demo --text-column text --id-column id --meta-columns date register --spacy-model blank:en
   ```

   The index has 162 tokens in 8 documents.

2. Open the corpus `tea_demo` in CandyConc and run the analyses with the
   settings given on each page.

The word sketch example needs dependency relations. Import the same file a
second time with `--spacy-model en_core_web_sm --enable-deps` and a different
output directory. This requires the spaCy pipeline `en_core_web_sm` in the
Python environment of CandyConc.

## Where each example is

| Example | Page | Settings |
| --- | --- | --- |
| Frequency and case | [Frequency and hits](frequency.md#example) | frequency list of word forms, searches for *tea* |
| Collocations | [Association measures](association-measures.md#example) | node *tea*, window 3, windows end at sentence boundaries |
| Lines behind a collocate | [From numbers to lines](../concepts/from-numbers-to-lines.md#from-a-collocation-row-to-the-lines) | node *tea*, window 3, collocates `green`, `a`, `A` |
| Dispersion | [Dispersion](dispersion.md#example) | *tea* and *coffee* |
| Keyness | [Keyness](keyness.md#example-the-synthetic-tea-corpus) | target: register `blog`, reference: register `news`, minimum frequency 5 |
| Bigrams | [N-grams and trends](n-grams-and-trends.md#n-gram-example) | n = 2 |
| Trend | [N-grams and trends](n-grams-and-trends.md#trend-example) | *tea* over the field `date`, by year |
| Lexical diversity | [Lexical diversity](lexical-diversity.md#example) | windows of 20 tokens |
| Word sketch | [Word sketches](word-sketches.md#example) | *tea*, minimum 1 pair, import with dependency relations |

The keyness page also shows one row from the English State of the Union
sample corpus. Its correction for multiple testing uses all 4,627 candidates.

## How the examples are checked

The tables on the methods pages are recorded responses of CandyConc, stored in
`docs/_data/worked_examples.json`. The script
`docs/_tools/check_worked_examples.py` checks them in two ways:

- The independent check recomputes the result fields and checks row
  completeness using the Python standard library and the definitions on
  these pages. It imports nothing from CandyConc. It uses `tea_demo.jsonl`,
  preserved dependency annotations for the word sketch, and the complete
  SOTU candidate counts for the keyness example and its Benjamini-Hochberg
  correction. Every difference is reported.
- With `--server`, it requests the analyses from a running CandyConc server
  and compares the responses with the independent results. Use
  `--deps-corpus` and `--sotu-corpus` to include those two examples.

Download the additional inputs:
{download}`tea dependency annotations <data/tea_dependencies.json>` and
{download}`SOTU candidate counts <data/sotu_counts.json>`.
Each file includes source and index hashes. The tea annotations were
preserved from the example import with `en_core_web_sm` 3.8.0 and builder
revision 1. The source commit is recorded in the annotation file. The SOTU
counts were independently extracted from the public example index with
`en_core_web_md` 3.8.0 and builder revision 3. These versions identify the
check inputs, not the earlier table recording.

The recorded tables and the current server responses pass these checks.
Regression tests also verify that changed values, empty tables, and duplicate
rows cause the check to fail.
[Documentation maintenance](../contribute/documentation.md) describes how to
run the script.
