# CandyConc

CandyConc is a corpus analysis application that runs on your own computer.
You import your texts once, and CandyConc builds an index of word forms,
lemmas, parts of speech, sentences, documents, and document metadata. On that
index you search with plain words or with a structured query language, read
every hit in its document, restrict your work to subcorpora, and compute
frequencies, collocations, dispersion, keyness, n-grams, trends, and word
sketches. Analysis results come with a method card that names the measure,
the counting unit, the scope, and the fingerprint of the index they were
computed on. An optional copilot connects to a language model that you choose
and calls the same analysis operations as the interface.

::::{grid} 1 1 2 3
:gutter: 3

:::{grid-item-card} Install CandyConc
:link: get-started/install
:link-type: doc

Download the application for your system and open it in the browser.
:::

:::{grid-item-card} First results
:link: get-started/first-results
:link-type: doc

Search the English sample corpus, read a hit in context, and export the lines.
:::

:::{grid-item-card} Import your texts
:link: guides/bring-in-texts/import-a-corpus
:link-type: doc

Build an index from CSV, JSONL, plain text, VRT, and other formats.
:::

:::{grid-item-card} How CandyConc works
:link: concepts/how-candyconc-works
:link-type: doc

Components, data flow, and what runs locally.
:::

:::{grid-item-card} How CandyConc counts
:link: methods/index
:link-type: doc

Counting units, denominators, formulas, and worked examples you can recompute.
:::

:::{grid-item-card} Query language
:link: reference/query-language
:link-type: doc

Plain search and the CQP-style query language, with tested examples.
:::

::::

```{toctree}
:hidden:
:maxdepth: 2

get-started/index
guides/index
concepts/index
methods/index
reference/index
help/index
contribute/index
```
