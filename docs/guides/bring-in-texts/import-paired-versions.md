# Import paired versions of source texts

A paired corpus holds several versions of the same source text, for example
an original and its plain-language rewrite, or a text and its translations.
CandyConc keeps the versions of a source together and shows, for each hit in
one version, the corresponding sentence in the other versions. This guide
imports such a corpus from a table and opens the parallel concordance.

## Before you begin

- A CSV, TSV, JSONL, or Parquet file with one row per version of a text, on
  the computer where CandyConc runs.
- The annotation pipeline of the language, see
  [Choose language and annotation layers](choose-annotation.md).

## Prepare the file

Each row needs three values besides the text:

| Column | Default name | Meaning |
| --- | --- | --- |
| pair key | `pair_id` | the same value for all versions of one source text |
| pair role | `pair_role` | the kind of version, for example `source`, `easy`, or `translation` |
| document ID | `id` | a unique ID for each row |

One role is the anchor, the version that the others are compared with. By
default, the anchor role is `source`. The file `paired.csv` in this guide has
three sources, each with a rewrite in easy language:

```text
id,pair_id,pair_role,text,level
s1,p1,source,"The committee postponed the decision because the budget figures were incomplete.",original
s1e,p1,easy,"The committee did not decide yet. The numbers for the money were not complete.",easy
s2,p2,source,"Residents are advised to remain indoors until the storm has passed.",original
s2e,p2,easy,"People should stay inside. They can go out when the storm is over.",easy
s3,p3,source,"The museum will close early on Friday because of the concert.",original
s3e,p3,easy,"The museum will close early on Friday. There is a concert.",easy
```

## Import the file

On the command line:

```bash
candy import --input paired.csv --input-format prealigned-csv --output ~/.candyconc/corpora/paired_en --language en --meta-columns level
```

The format names are `prealigned-csv` for CSV and TSV, `prealigned-jsonl`,
and `prealigned-parquet`. If your columns have other names, add
`--pair-key-column`, `--pair-role-column`, `--text-column`, and
`--id-column`, and name the anchor role with `--anchor-role`.

In the corpus manager, choose the format **Pre-grouped CSV/TSV**,
**Pre-grouped JSONL**, or **Pre-grouped Parquet**, and set the same values
in the options **Pair key column** (`pair_key_column`), **Pair role column**
(`pair_role_column`), and **Anchor role** (`anchor_role`). The rest of the
procedure is the one in [Import a corpus](import-a-corpus.md).

In the corpus manager, the catalog entry of the new corpus shows
**Pair metadata: prealigned · pair groups + paired concordance**.

## Open the parallel concordance

1. Select the paired corpus in the corpus selector and search for a word,
   for example `museum`.
2. In the toolbar above the concordance, select **Parallel concordance**.

   A settings row opens. The list **Variants (prealigned)** shows the
   versions of the corpus under their role names, here **easy** and
   **source**.

3. In the list **Variants (prealigned)**, select **easy**.

The label **PARALLEL CONCORDANCE ACTIVE** appears above the table, and the
table gets a column **EASY**. For the hit *museum* in the source sentence,
the column shows the corresponding easy-language sentence *The museum will
close early on Friday*, with its similarity (**Sim 78%**) and its edit
distance in tokens (**MED 4**).

```{figure} ../../_static/screenshots/parallel-museum.png
:alt: Parallel concordance for museum in paired_en. The column EASY shows the easy-language counterpart of the hit with Sim 78% and MED 4.
:width: 100%

The parallel concordance of the synthetic example corpus `paired_en`. The column **EASY** shows the counterpart of the hit with its similarity and its edit distance.
```

Parallel rows show tokens separated by spaces, including spaces before
punctuation. To read the original spacing, open the document context of the
hit when the index includes it, see
[Original spacing](../../concepts/corpus-index.md#original-spacing).

To leave the view, click **End parallel view**.

## How CandyConc finds the corresponding sentence

The pair key decides which texts belong together. Within a pair, CandyConc
aligns the sentences of the two versions when you open the parallel
concordance. A sentence of the other version is shown as the counterpart
only if its similarity to the sentence of the hit is at least 50%. The
similarity is based on the edit distance between the two sentences, raised
by the share of words they have in common. When no sentence reaches 50%,
the column shows a dash. In the example, the storm sentences are rewritten
so freely that the search `storm` shows a dash in the column **EASY**.

The settings row also offers the **Sentence window**, the number of
sentences around the hit that the alignment considers (default ±6), and
**Presets** to save a selection of variants.

## Result

The paired corpus is in the catalog, and the parallel concordance shows the
corresponding sentences of the versions you selected next to each hit. To
compare frequencies or collocations between the versions, see
[Contrast collocations and paired versions](../count-and-measure/contrast.md).
